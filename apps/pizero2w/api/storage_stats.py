import shutil
from pathlib import Path

from capture_format import CAPTURE_BYTES_PER_SEC, CAPTURE_SAMPLE_RATE

DATA = Path("/app/data")
CAPTURE_DIR = DATA / "captures"
WAV_BYTES_PER_SEC = CAPTURE_BYTES_PER_SEC


def _dir_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def _file_bytes(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def storage_stats() -> dict:
    total, used, free = shutil.disk_usage(DATA)
    captures_bytes = _dir_bytes(CAPTURE_DIR)
    capture_files = [p for p in CAPTURE_DIR.glob("*") if p.is_file()] if CAPTURE_DIR.is_dir() else []
    data_bytes = _dir_bytes(DATA)
    db_bytes = _file_bytes(DATA / "signals.db")
    logs_bytes = _dir_bytes(DATA / "logs")
    free_pct = round(free / total * 100, 1) if total else 0.0
    warn_low = free < 200 * 1024 * 1024
    est_10 = round(WAV_BYTES_PER_SEC * 600 / 1024 / 1024, 1)
    est_15 = round(WAV_BYTES_PER_SEC * 900 / 1024 / 1024, 1)
    return {
        "diskTotal": total,
        "diskFree": free,
        "diskUsedFs": used,
        "dataBytes": data_bytes,
        "capturesBytes": captures_bytes,
        "capturesCount": len(capture_files),
        "dbBytes": db_bytes,
        "logsBytes": logs_bytes,
        "freePct": free_pct,
        "warnLow": warn_low,
        "estimateMeteor10MinMb": est_10,
        "estimateMeteor15MinMb": est_15,
        "wavBytesPerSec": WAV_BYTES_PER_SEC,
        "captureSampleRate": CAPTURE_SAMPLE_RATE,
        "captureFormat": "iq_s16_stereo",
    }
