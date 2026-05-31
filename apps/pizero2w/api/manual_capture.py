import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

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

from signal_monitor import (
    CHECK_SEC,
    analyze_wav,
    interpret_check,
    quick_check_cmd,
    run_capture_monitor,
    snapshot_signal,
)

log = logging.getLogger("siglog.manual_capture")

_capture_lock = threading.Lock()
_capture_proc: subprocess.Popen | None = None
_check_lock = threading.Lock()


def _capture_satellite_name(label: str, pass_name: str | None) -> str:
    if pass_name:
        return pass_name
    low = label.lower()
    if "apt" in low:
        return "NOAA APT"
    if "1379" in low:
        return "METEOR-M2 3"
    if "1371" in low:
        return "METEOR-M 2"
    return label.replace("_", " ")


def _capture_decoder(label: str, decode_apt: bool, decoder: str | None) -> str:
    if decoder:
        return decoder
    if decode_apt or "apt" in label.lower():
        return "apt"
    return "lrpt"


def _write_capture_state(payload: dict) -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CAPTURE_STATE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    tmp.replace(CAPTURE_STATE)


def _patch_capture_state(patch: dict) -> None:
    cur = read_capture_state()
    cur.update(patch)
    _write_capture_state(cur)


def quick_signal_check(freq_mhz: float, duration_sec: int = CHECK_SEC) -> dict:
    if not _check_lock.acquire(blocking=False):
        return {"ok": False, "error": "Signal check busy"}
    if capture_busy():
        _check_lock.release()
        return {"ok": False, "error": "Capture running"}
    duration_sec = min(max(duration_sec, 3), 15)
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    wav = CAPTURE_DIR / f"check_{stamp}.wav"
    try:
        supervisorctl("stop", "dump1090")
        time.sleep(1)
        cmd = quick_check_cmd(freq_mhz, duration_sec, wav)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=duration_sec + 20)
        supervisorctl("start", "dump1090")
        if proc.returncode not in (0, 124) or not wav.exists():
            return {"ok": False, "error": "Signal check failed", "freqMhz": freq_mhz}
        snap = snapshot_signal(wav)
        snap["freqMhz"] = freq_mhz
        result = interpret_check(snap)
        try:
            wav.unlink()
        except OSError:
            pass
        return result
    except subprocess.TimeoutExpired:
        supervisorctl("start", "dump1090")
        return {"ok": False, "error": "Signal check timed out", "freqMhz": freq_mhz}
    except Exception as e:
        supervisorctl("start", "dump1090")
        return {"ok": False, "error": str(e), "freqMhz": freq_mhz}
    finally:
        _check_lock.release()


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
    decoder: str | None = None,
    max_elevation: float | None = None,
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
        monitor_stop = threading.Event()
        base_state = {
            "active": True,
            "freqMhz": freq_mhz,
            "durationSec": duration_sec,
            "label": label,
            "passName": pass_name,
            "wav": str(wav.name),
            "startedTs": started,
            "message": f"Recording {pass_name or label} @ {freq_mhz} MHz",
            "signalState": "waiting",
            "signalLevel": 0,
        }
        _write_capture_state(base_state)

        def on_signal(patch: dict) -> None:
            _patch_capture_state(patch)

        monitor = threading.Thread(
            target=run_capture_monitor,
            args=(wav, monitor_stop, on_signal),
            daemon=True,
        )
        log.info("Manual capture %s %.3f MHz %ss", label, freq_mhz, duration_sec)
        supervisorctl("stop", "dump1090")
        time.sleep(2)
        monitor.start()
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
            monitor_stop.set()
            monitor.join(timeout=3)
            with _capture_lock:
                _capture_proc = None
            supervisorctl("start", "dump1090")

        ok = rc in (0, 124) and wav.exists() and wav.stat().st_size > 10000
        sig = analyze_wav(wav) if ok else {}
        result = {
            "active": False,
            "ok": ok,
            "freqMhz": freq_mhz,
            "durationSec": duration_sec,
            "label": label,
            "wav": wav.name if wav.exists() else None,
            "wavUrl": f"/api/captures/{wav.name}" if wav.exists() else None,
            "size": wav.stat().st_size if wav.exists() else 0,
            "message": sig.get("signalMessage") if sig and not sig.get("signalOk") else ("Recording saved" if ok else "Recording failed"),
            **sig,
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
        if ok and sig.get("signalOk"):
            try:
                from satellite_log import log_satellite_signal

                sat_name = _capture_satellite_name(label, pass_name)
                dec = _capture_decoder(label, decode_apt, decoder)
                if result.get("png"):
                    detail = f"APT {result['png']} · {wav.name} @ {freq_mhz} MHz"
                else:
                    detail = f"LRPT {wav.name} @ {freq_mhz} MHz · {duration_sec}s"
                log_satellite_signal(
                    sat_name,
                    detail,
                    decoder=dec,
                    max_elevation=max_elevation,
                )
            except Exception as e:
                log.warning("satellite log failed: %s", e)
        elif ok and sig and not sig.get("signalOk"):
            log.warning("capture saved but no satellite signal: %s", sig.get("signalMessage"))
        if ok:
            if sig.get("signalOk"):
                result["message"] = "Recording saved · satellite signal OK"
            elif sig:
                result["message"] = sig.get("signalMessage", "Recording saved")
        _write_capture_state(result)

    threading.Thread(target=worker, daemon=True).start()
    return {
        "ok": True,
        "message": f"Started {duration_sec}s capture @ {freq_mhz} MHz",
    }
