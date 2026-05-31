import struct
import threading
from pathlib import Path

from capture_format import CAPTURE_BYTES_PER_SEC, CAPTURE_SAMPLE_RATE, rtl_fm_lrpt_cmd

WAV_HEADER = 44
WINDOW_SEC = 2.0
CHECK_SEC = 5
RMS_SILENCE = 800
RMS_SIGNAL = 8000
RATIO_SIGNAL = 2.5
COVERAGE_OK = 0.12


def iq_power_rms(data: bytes) -> tuple[float, float]:
    n = len(data) // 4
    if n < 1:
        return 0.0, 0.0
    sq = 0.0
    peak = 0.0
    for i in range(0, n * 4, 4):
        i_val, q_val = struct.unpack_from("<hh", data, i)
        mag = (i_val * i_val + q_val * q_val) ** 0.5
        sq += mag * mag
        peak = max(peak, mag)
    rms = (sq / n) ** 0.5
    return rms, peak


def read_wav_tail_pcm(path: Path, tail_bytes: int) -> bytes:
    try:
        size = path.stat().st_size
        if size <= WAV_HEADER + 4:
            return b""
        with open(path, "rb") as f:
            f.seek(max(WAV_HEADER, size - tail_bytes))
            return f.read()
    except OSError:
        return b""


def read_wav_all_pcm(path: Path) -> bytes:
    try:
        size = path.stat().st_size
        if size <= WAV_HEADER + 4:
            return b""
        with open(path, "rb") as f:
            f.seek(WAV_HEADER)
            return f.read()
    except OSError:
        return b""


def _state_from_rms(rms: float, baseline: float | None) -> str:
    if rms < RMS_SILENCE:
        return "silence"
    if rms >= RMS_SIGNAL:
        return "strong"
    if baseline and baseline > 0 and rms / baseline >= RATIO_SIGNAL:
        return "signal"
    if rms >= RMS_SIGNAL * 0.55:
        return "signal"
    return "noise"


def _level_from_rms(rms: float) -> int:
    if rms <= 0:
        return 0
    import math

    db = 20 * math.log10(max(rms, 1))
    return max(0, min(100, int((db - 30) * 1.8)))


def snapshot_signal(path: Path, baseline: float | None = None) -> dict:
    tail = int(CAPTURE_SAMPLE_RATE * WINDOW_SEC * 4)
    pcm = read_wav_tail_pcm(path, tail)
    rms, peak = iq_power_rms(pcm)
    state = _state_from_rms(rms, baseline)
    return {
        "signalRms": round(rms),
        "signalPeak": int(peak),
        "signalState": state,
        "signalLevel": _level_from_rms(rms),
        "signalOk": state in ("signal", "strong"),
    }


def analyze_wav(path: Path) -> dict:
    pcm = read_wav_all_pcm(path)
    min_bytes = int(CAPTURE_SAMPLE_RATE * 4 * 0.5)
    if len(pcm) < min_bytes:
        return {
            "signalOk": False,
            "signalCoverage": 0.0,
            "signalMessage": "Recording too short to analyze",
        }
    chunk = int(CAPTURE_SAMPLE_RATE * WINDOW_SEC * 4)
    baseline = None
    hits = 0
    total = 0
    max_rms = 0.0
    for i in range(0, len(pcm) - chunk, chunk):
        rms, _ = iq_power_rms(pcm[i : i + chunk])
        if baseline is None:
            baseline = max(rms, 1.0)
        max_rms = max(max_rms, rms)
        total += 1
        if _state_from_rms(rms, baseline) in ("signal", "strong"):
            hits += 1
    coverage = hits / total if total else 0.0
    ok = coverage >= COVERAGE_OK
    if ok:
        msg = f"Satellite signal detected ({int(coverage * 100)}% of pass)"
    elif max_rms < RMS_SILENCE:
        msg = "No signal — silence only (antenna, frequency, or pass timing?)"
    else:
        msg = f"Weak or no satellite signal ({int(coverage * 100)}% above noise)"
    return {
        "signalOk": ok,
        "signalCoverage": round(coverage, 3),
        "signalMaxRms": round(max_rms),
        "signalMessage": msg,
    }


def run_capture_monitor(
    wav_path: Path,
    stop_event: threading.Event,
    update_fn,
) -> None:
    baseline = None
    hits = 0
    windows = 0
    while not stop_event.wait(2.0):
        snap = snapshot_signal(wav_path, baseline)
        rms = snap["signalRms"]
        if baseline is None and rms > 0:
            baseline = float(rms)
        windows += 1
        if snap["signalOk"]:
            hits += 1
        coverage = hits / windows if windows else 0.0
        update_fn(
            {
                **snap,
                "signalBaseline": round(baseline or 0),
                "signalHits": hits,
                "signalWindows": windows,
                "signalCoverageLive": round(coverage, 3),
            }
        )


def quick_check_cmd(freq_mhz: float, duration_sec: int, wav_path: Path) -> list[str]:
    return rtl_fm_lrpt_cmd(freq_mhz, duration_sec, str(wav_path))


def interpret_check(snap: dict) -> dict:
    state = snap["signalState"]
    ok = state in ("signal", "strong")
    labels = {
        "silence": "No RF — check antenna and frequency",
        "noise": "Noise only — satellite not visible yet or wrong azimuth",
        "signal": "Satellite signal detected — good to record",
        "strong": "Strong satellite signal — ideal",
    }
    return {
        "ok": ok,
        "freqMhz": snap.get("freqMhz"),
        "signalRms": snap["signalRms"],
        "signalPeak": snap["signalPeak"],
        "signalState": state,
        "signalLevel": snap["signalLevel"],
        "message": labels.get(state, "Unknown"),
    }
