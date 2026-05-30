import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

PLAN_CACHE = Path("/app/data/plan_cache.json")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "sat"


def pass_capture_params(pass_row: dict) -> tuple[float, int, str, bool]:
    aos = datetime.fromisoformat(pass_row["aos"])
    los = datetime.fromisoformat(pass_row["los"])
    duration = int((los - aos).total_seconds()) + 60
    duration = min(900, max(60, duration))
    freq = float(pass_row["freqMhz"])
    decoder = pass_row.get("decoder", "lrpt")
    slug = _slug(pass_row["name"])
    if decoder == "apt":
        label = f"{slug}_apt"
        decode_apt = False
    else:
        band = "1379" if freq >= 137.5 else "1371"
        label = f"{slug}_lrpt{band}"
        decode_apt = False
    return freq, duration, label, decode_apt


def read_plan_cache() -> dict | None:
    try:
        with open(PLAN_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return None


def write_plan_cache(data: dict) -> None:
    PLAN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["savedAt"] = int(time.time())
    tmp = PLAN_CACHE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    tmp.replace(PLAN_CACHE)


def enrich_plan_passes(data: dict) -> dict:
    now = datetime.now(timezone.utc)
    out = dict(data)
    passes = []
    for p in data.get("passes") or []:
        row = dict(p)
        aos = datetime.fromisoformat(row["aos"])
        los = datetime.fromisoformat(row["los"])
        start_sec = int((aos - now).total_seconds())
        end_sec = int((los - now).total_seconds())
        row["startInMin"] = max(0, start_sec // 60)
        row["endInMin"] = max(0, end_sec // 60)
        row["startInSec"] = max(0, start_sec)
        row["endInSec"] = max(0, end_sec)
        row["inPass"] = start_sec <= 0 <= end_sec
        row["ended"] = end_sec < 0
        passes.append(row)
    out["passes"] = passes
    return out
