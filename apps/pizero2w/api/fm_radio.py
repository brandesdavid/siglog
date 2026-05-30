import json
import logging
import queue
import subprocess
import threading
import time
from pathlib import Path

DATA = Path("/app/data")
CONTROL_DIR = DATA / "control"
RADIO_STATE = CONTROL_DIR / "radio.json"
SUPERVISOR_CONF = __import__("os").getenv(
    "SUPERVISOR_CONFIG", "/etc/supervisor/conf.d/siglog-no-gps.conf"
)

log = logging.getLogger("siglog.fm_radio")

_radio_lock = threading.Lock()
_radio_proc: subprocess.Popen | None = None
_radio_freq_mhz: float | None = None
_reader_thread: threading.Thread | None = None
_listener_queues: list[queue.Queue] = []
_reader_stop = threading.Event()
FM_MIN_MHZ = 87.5
FM_MAX_MHZ = 108.0


def _supervisorctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["supervisorctl", "-c", SUPERVISOR_CONF, *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _write_state(payload: dict) -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = RADIO_STATE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    tmp.replace(RADIO_STATE)


def read_radio_state() -> dict:
    try:
        with open(RADIO_STATE, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {"active": False}


def _other_sdr_busy() -> str | None:
    from manual_capture import capture_busy

    if capture_busy():
        return "SDR busy (capture or signal check)"
    return None


def radio_busy() -> bool:
    st = read_radio_state()
    if st.get("active"):
        return True
    global _radio_proc
    return _radio_proc is not None and _radio_proc.poll() is None


def _broadcast(chunk: bytes) -> None:
    dead = []
    for q in _listener_queues:
        try:
            q.put_nowait(chunk)
        except queue.Full:
            try:
                q.get_nowait()
                q.put_nowait(chunk)
            except queue.Empty:
                dead.append(q)
        except Exception:
            dead.append(q)
    for q in dead:
        if q in _listener_queues:
            _listener_queues.remove(q)


def _reader_loop() -> None:
    global _radio_proc
    while not _reader_stop.is_set():
        proc = _radio_proc
        if not proc or proc.stdout is None:
            break
        try:
            chunk = proc.stdout.read(4096)
        except OSError:
            break
        if not chunk:
            break
        if chunk:
            _broadcast(chunk)
    if not _reader_stop.is_set():
        threading.Thread(target=stop_radio, daemon=True).start()


def _attach_reader() -> None:
    global _reader_thread
    _reader_stop.clear()
    _reader_thread = threading.Thread(target=_reader_loop, daemon=True)
    _reader_thread.start()


def start_radio(freq_mhz: float) -> dict:
    busy = _other_sdr_busy()
    if busy:
        return {"ok": False, "error": busy}
    if radio_busy():
        return {"ok": False, "error": "FM radio already running"}

    freq_mhz = round(float(freq_mhz), 2)
    if freq_mhz < FM_MIN_MHZ or freq_mhz > FM_MAX_MHZ:
        return {
            "ok": False,
            "error": f"Frequency must be {FM_MIN_MHZ}–{FM_MAX_MHZ} MHz",
        }

    global _radio_proc, _radio_freq_mhz
    with _radio_lock:
        _supervisorctl("stop", "dump1090")
        time.sleep(1)
        cmd = [
            "rtl_fm",
            "-d",
            "0",
            "-f",
            f"{freq_mhz}M",
            "-M",
            "wbfm",
            "-s",
            "170k",
            "-r",
            "48000",
            "-g",
            "40",
            "-",
        ]
        try:
            _radio_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as e:
            _supervisorctl("start", "dump1090")
            return {"ok": False, "error": str(e)}
        _radio_freq_mhz = freq_mhz
        _write_state(
            {
                "active": True,
                "freqMhz": freq_mhz,
                "startedTs": int(time.time()),
                "message": f"FM {freq_mhz} MHz",
            }
        )
        _attach_reader()
    log.info("FM radio started %.2f MHz", freq_mhz)
    return {
        "ok": True,
        "freqMhz": freq_mhz,
        "message": f"Listening FM {freq_mhz} MHz · ADS-B paused",
    }


def stop_radio() -> dict:
    global _radio_proc, _radio_freq_mhz
    _reader_stop.set()
    with _radio_lock:
        if _radio_proc and _radio_proc.poll() is None:
            _radio_proc.terminate()
            try:
                _radio_proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                _radio_proc.kill()
        _radio_proc = None
        _radio_freq_mhz = None
        _listener_queues.clear()
        _write_state({"active": False, "message": "FM stopped"})
        _supervisorctl("start", "dump1090")
    log.info("FM radio stopped")
    return {"ok": True, "message": "FM stopped · ADS-B resumed"}


def stream_chunks():
    if not radio_busy():
        return
    q: queue.Queue = queue.Queue(maxsize=32)
    _listener_queues.append(q)
    try:
        while radio_busy() and not _reader_stop.is_set():
            try:
                chunk = q.get(timeout=2.0)
                yield chunk
            except queue.Empty:
                continue
    finally:
        if q in _listener_queues:
            _listener_queues.remove(q)


def parse_rtl_power(text: str) -> dict:
    import csv
    from io import StringIO

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return {"freqsMhz": [], "db": [], "lowMhz": FM_MIN_MHZ, "highMhz": FM_MAX_MHZ}
    row = None
    for line in reversed(lines):
        if line.startswith("#"):
            continue
        try:
            row = next(csv.reader(StringIO(line)))
            break
        except csv.Error:
            continue
    if not row or len(row) < 7:
        return {"freqsMhz": [], "db": [], "lowMhz": FM_MIN_MHZ, "highMhz": FM_MAX_MHZ}
    low_hz = float(row[2])
    high_hz = float(row[3])
    step_hz = float(row[4])
    db = [float(x) for x in row[6:] if x]
    freqs = [low_hz + i * step_hz for i in range(len(db))]
    return {
        "freqsMhz": [round(f / 1e6, 3) for f in freqs],
        "db": db,
        "lowMhz": round(low_hz / 1e6, 2),
        "highMhz": round(high_hz / 1e6, 2),
        "stepKhz": round(step_hz / 1e3, 1),
    }


def rf_spectrum_sweep() -> dict:
    busy = _other_sdr_busy()
    if busy:
        return {"ok": False, "error": busy}
    was_radio = radio_busy()
    freq = read_radio_state().get("freqMhz")
    if was_radio:
        stop_radio()
        time.sleep(0.5)
    _supervisorctl("stop", "dump1090")
    time.sleep(0.5)
    out_path = CONTROL_DIR / "rtl_power.csv"
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        "rtl_power",
        "-f",
        "88M:108M:200k",
        "-i",
        "1",
        "-1",
        str(out_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        text = ""
        if out_path.is_file():
            text = out_path.read_text(encoding="utf-8", errors="replace")
        if not text and proc.stdout:
            text = proc.stdout
        spec = parse_rtl_power(text)
        if not spec["db"]:
            return {"ok": False, "error": "Spectrum sweep failed", "stderr": proc.stderr[-300:]}
        result = {"ok": True, **spec, "message": "FM band scan 88–108 MHz"}
        if was_radio and freq:
            start_radio(freq)
        else:
            _supervisorctl("start", "dump1090")
        return result
    except subprocess.TimeoutExpired:
        _supervisorctl("start", "dump1090")
        return {"ok": False, "error": "Spectrum sweep timed out"}
    except OSError as e:
        _supervisorctl("start", "dump1090")
        return {"ok": False, "error": str(e)}
