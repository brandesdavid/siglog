import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("siglog.manual_capture")

DATA = Path("/app/data")
CAPTURE_DIR = DATA / "captures"
CONTROL_DIR = DATA / "control"
HOST_CMD = CONTROL_DIR / "host.cmd"
HOST_RESULT = CONTROL_DIR / "host.result"
CAPTURE_STATE = CONTROL_DIR / "capture.json"
NOAA_APT = os.getenv("NOAA_APT_BIN", "/usr/local/bin/noaa-apt")
SUPERVISOR_CONF = os.getenv(
    "SUPERVISOR_CONFIG", "/etc/supervisor/conf.d/siglog-no-gps.conf"
)

_capture_lock = threading.Lock()
_capture_proc: subprocess.Popen | None = None


def _write_capture_state(payload: dict) -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CAPTURE_STATE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    tmp.replace(CAPTURE_STATE)


def read_capture_state() -> dict:
    try:
        with open(CAPTURE_STATE, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {"active": False}


def supervisorctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["supervisorctl", "-c", SUPERVISOR_CONF, *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def queue_host_command(cmd: str) -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    allowed = {"status", "hotspot", "wifi", "auto", "leave"}
    if cmd not in allowed:
        raise ValueError(f"unknown host command: {cmd}")
    HOST_CMD.write_text(cmd, encoding="utf-8")
    if HOST_RESULT.exists():
        HOST_RESULT.unlink()


def read_host_result() -> str | None:
    try:
        text = HOST_RESULT.read_text(encoding="utf-8").strip()
        return text or None
    except OSError:
        return None


def list_captures() -> list[dict]:
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(CAPTURE_DIR.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_file():
            continue
        st = p.stat()
        out.append(
            {
                "name": p.name,
                "size": st.st_size,
                "ts": int(st.st_mtime),
                "url": f"/api/captures/{p.name}",
            }
        )
    return out[:50]


def capture_busy() -> bool:
    st = read_capture_state()
    if st.get("active"):
        return True
    global _capture_proc
    return _capture_proc is not None and _capture_proc.poll() is None


def stop_capture() -> dict:
    global _capture_proc
    with _capture_lock:
        if _capture_proc and _capture_proc.poll() is None:
            _capture_proc.terminate()
            try:
                _capture_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _capture_proc.kill()
            _capture_proc = None
        _write_capture_state({"active": False, "message": "Stopped"})
        supervisorctl("start", "dump1090")
        return {"ok": True, "message": "Capture stopped"}


def start_capture(
    freq_mhz: float,
    duration_sec: int,
    label: str,
    decode_apt: bool = False,
    pass_name: str | None = None,
) -> dict:
    if capture_busy():
        return {"ok": False, "error": "Capture already running"}

    duration_sec = min(max(duration_sec, 30), 900)

    def worker():
        global _capture_proc
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        wav = CAPTURE_DIR / f"{label}_{stamp}.wav"
        png = CAPTURE_DIR / f"{label}_{stamp}.png"
        started = int(time.time())
        _write_capture_state(
            {
                "active": True,
                "freqMhz": freq_mhz,
                "durationSec": duration_sec,
                "label": label,
                "passName": pass_name,
                "wav": str(wav.name),
                "startedTs": started,
                "message": f"Recording {pass_name or label} @ {freq_mhz} MHz",
            }
        )
        log.info("Manual capture %s %.3f MHz %ss", label, freq_mhz, duration_sec)
        supervisorctl("stop", "dump1090")
        time.sleep(2)
        cmd = [
            "timeout",
            str(duration_sec),
            "rtl_fm",
            "-d",
            "0",
            "-f",
            f"{freq_mhz}M",
            "-M",
            "fm",
            "-s",
            "48k",
            "-g",
            "40",
            "-E",
            "wav",
            str(wav),
        ]
        try:
            with _capture_lock:
                _capture_proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
            rc = _capture_proc.wait(timeout=duration_sec + 45)
        except subprocess.TimeoutExpired:
            _capture_proc.kill()
            rc = -1
        finally:
            with _capture_lock:
                _capture_proc = None
            supervisorctl("start", "dump1090")

        ok = rc in (0, 124) and wav.exists() and wav.stat().st_size > 10000
        result = {
            "active": False,
            "ok": ok,
            "freqMhz": freq_mhz,
            "durationSec": duration_sec,
            "label": label,
            "wav": wav.name if wav.exists() else None,
            "wavUrl": f"/api/captures/{wav.name}" if wav.exists() else None,
            "size": wav.stat().st_size if wav.exists() else 0,
            "message": "Recording saved" if ok else "Recording failed",
        }
        if ok and decode_apt:
            _write_capture_state({**result, "active": True, "message": "Decoding APT…"})
            dec = subprocess.run(
                [
                    NOAA_APT,
                    str(wav),
                    "-o",
                    str(png),
                    "-q",
                    "-p",
                    "fast",
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if dec.returncode == 0 and png.exists():
                result["png"] = png.name
                result["pngUrl"] = f"/api/captures/{png.name}"
                result["message"] = "WAV + PNG saved"
            else:
                result["decodeError"] = (dec.stderr or "")[-400:]
                result["message"] = "WAV saved, APT decode failed"
        _write_capture_state(result)

    threading.Thread(target=worker, daemon=True).start()
    return {
        "ok": True,
        "message": f"Started {duration_sec}s capture @ {freq_mhz} MHz",
    }
