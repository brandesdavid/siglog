import json
import logging
import sqlite3
import time
from pathlib import Path

from rarity import classify_satellite_rarity

log = logging.getLogger("siglog.satellite_log")

DB_PATH = Path("/app/data/signals.db")
POSITION_PATH = Path("/app/data/position.json")
DEFAULT_LAT = 52.52
DEFAULT_LON = 13.405


def read_position() -> tuple[float | None, float | None]:
    try:
        with open(POSITION_PATH, encoding="utf-8") as f:
            p = json.load(f)
        if p.get("lat") is not None and p.get("lng") is not None:
            return float(p["lat"]), float(p["lng"])
    except OSError:
        pass
    return DEFAULT_LAT, DEFAULT_LON


def log_satellite_signal(
    name: str,
    detail: str,
    decoder: str = "lrpt",
    max_elevation: float | None = None,
) -> str:
    rarity = classify_satellite_rarity(name, decoder, max_elevation)
    sig_type = "NOAA" if decoder == "apt" else "METEOR"
    lat, lng = read_position()
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO signals (ts,type,callsign,detail,rarity,lat,lng) "
        "VALUES (?,?,?,?,?,?,?)",
        (int(time.time()), sig_type, name, detail[:120], rarity, lat, lng),
    )
    con.commit()
    con.close()
    log.info("Logged %s [%s] %s — %s", sig_type, rarity, name, detail[:60])
    return rarity


def refresh_satellite_rarities(con: sqlite3.Connection) -> int:
    rows = con.execute(
        "SELECT DISTINCT callsign, type FROM signals WHERE type IN ('NOAA', 'METEOR')"
    ).fetchall()
    n = 0
    for name, sig_type in rows:
        decoder = "apt" if sig_type == "NOAA" else "lrpt"
        rarity = classify_satellite_rarity(name, decoder)
        cur = con.execute(
            "UPDATE signals SET rarity = ? WHERE callsign = ? AND type = ?",
            (rarity, name, sig_type),
        )
        n += cur.rowcount
    con.commit()
    return n
