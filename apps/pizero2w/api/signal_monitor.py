import struct
import threading
import time
from pathlib import Path

WAV_HEADER = 44
SAMPLE_RATE = 48000
WINDOW_SEC = 2.0
CHECK_SEC = 5
RMS_SILENCE = 350
RMS_SIGNAL = 2200
RATIO_SIGNAL = 2.2
COVERAGE_OK = 0.12


def pcm16_rms(data: bytes) -> tuple[float, float]:
    n = len(data) // 2
    if n < 1:
        return 0.0, 0.0
    samples = struct.unpack(f"<{n}h", data[: n * 2])
    sq = sum(s * s for s in samples)
    rms = (sq / n) ** 0.5
    peak = max(abs(s) for s in samples)
    return rms, peak


def read_wav_tail_pcm(path: Path, tail_bytes: int) -> bytes:
    try:
        size = path.stat().st_size
        if size <= WAV_HEADER + 2:
            return b""
        with open(path, "rb") as f:
            f.seek(max(WAV_HEADER, size - tail_bytes))
            return f.read()
    except OSError:
        return b""


def read_wav_all_pcm(path: Path) -> bytes:
    try:
        size = path.stat().st_size
        if size <= WAV_HEADER + 2:
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
    return max(0, min(100, int((db - 20) * 2.2)))


def snapshot_signal(path: Path, baseline: float | None = None) -> dict:
    tail = int(SAMPLE_RATE * WINDOW_SEC * 2)
    pcm = read_wav_tail_pcm(path, tail)
    rms, peak = pcm16_rms(pcm)
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
    if len(pcm) < SAMPLE_RATE:
        return {
            "signalOk": False,
            "signalCoverage": 0.0,
            "signalMessage": "Recording too short to analyze",
        }
    chunk = int(SAMPLE_RATE * WINDOW_SEC * 2)
    baseline = None
    hits = 0
    total = 0
    max_rms = 0.0
    for i in range(0, len(pcm) - chunk, chunk):
        rms, _ = pcm16_rms(pcm[i : i + chunk])
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
    return [
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
        str(wav_path),
    ]


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
