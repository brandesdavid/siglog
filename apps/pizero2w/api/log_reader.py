import logging
from pathlib import Path

log = logging.getLogger("siglog.log_reader")

LOG_DIR = Path("/app/data/logs")

SERVICE_FILES: dict[str, list[str]] = {
    "api": ["api.log", "api.err"],
    "dump1090": ["dump1090.log", "dump1090.err"],
    "scheduler": ["scheduler.log", "scheduler.err"],
    "gpsd": ["gpsd.log", "gpsd.err"],
    "capture": ["capture.log"],
}


def tail_lines(path: Path, max_lines: int = 200) -> list[str]:
    if not path.is_file():
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            block = 8192
            data = b""
            while size > 0 and data.count(b"\n") <= max_lines + 1:
                step = min(block, size)
                size -= step
                f.seek(size)
                data = f.read(step) + data
        lines = data.decode("utf-8", errors="replace").splitlines()
        return lines[-max_lines:]
    except OSError as e:
        log.debug("tail %s: %s", path, e)
        return []


def read_logs(service: str = "all", max_lines: int = 200) -> dict:
    max_lines = min(max(max_lines, 20), 500)
    if service != "all" and service not in SERVICE_FILES:
        return {"ok": False, "error": "unknown service", "lines": []}

    services = SERVICE_FILES.keys() if service == "all" else [service]
    combined: list[str] = []
    sources: list[str] = []

    for name in services:
        for fname in SERVICE_FILES.get(name, []):
            path = LOG_DIR / fname
            if not path.is_file():
                continue
            chunk = tail_lines(path, max_lines)
            if not chunk:
                continue
            sources.append(fname)
            header = f"--- {fname} ---"
            combined.extend([header, *chunk, ""])

    if not combined:
        combined = ["(no log files yet — redeploy image to enable file logging)"]

    if len(combined) > max_lines + len(sources) * 3:
        combined = combined[-(max_lines + len(sources) * 3) :]

    return {
        "ok": True,
        "service": service,
        "lines": combined,
        "sources": sources,
    }
