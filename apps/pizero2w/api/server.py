import os
import json
import time
import sqlite3
import logging
import threading
import random
import gps
from flask import Flask, jsonify

DUMP1090_JSON = os.getenv("DUMP1090_JSON", "/app/data/dump1090/aircraft.json")
API_PORT = int(os.getenv("API_PORT", 80))
DB_PATH = "/app/data/signals.db"
POLL_INTERVAL = 2.0
FAKE_SIGNALS = os.getenv("FAKE_SIGNALS", "0") == "1"

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("siglog")

app = Flask(__name__)

state = {
    "type": "---",
    "callsign": "SCANNING",
    "detail": "Waiting for signals...",
    "rarity": "COMMON",
    "total": 0,
    "gpsLocked": False,
    "battery": 100,
    "lat": None,
    "lng": None,
}
state_lock = threading.Lock()

MILITARY_PREFIXES = [
    "GAF",
    "NAF",
    "RFR",
    "RAF",
    "USAF",
    "CTM",
    "CASA",
    "SVF",
]

EMERGENCY_SQUAWKS = {"7700", "7600", "7500"}

FAKE_AIRCRAFT = [
    {"flight": "DLH456  ", "alt_baro": 10500, "gs": 420, "t": "A320", "squawk": "1000", "hex": "3c6750"},
    {"flight": "GAF686  ", "alt_baro": 7400, "gs": 310, "t": "A310", "squawk": "2000", "hex": "3f4a12"},
    {"flight": "N123AB  ", "alt_baro": 3200, "gs": 180, "t": "C172", "squawk": "1200", "hex": "a1b2c3"},
    {"flight": "        ", "alt_baro": 28000, "gs": 520, "squawk": "7700", "hex": ""},
]


def init_db():
    os.makedirs("/app/data", exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS signals (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        INTEGER NOT NULL,
            type      TEXT,
            callsign  TEXT,
            detail    TEXT,
            rarity    TEXT,
            lat       REAL,
            lng       REAL
        )
        """
    )
    con.commit()
    return con


db_con = init_db()


def log_signal(sig: dict):
    db_con.execute(
        "INSERT INTO signals (ts,type,callsign,detail,rarity,lat,lng) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            int(time.time()),
            sig["type"],
            sig["callsign"],
            sig["detail"],
            sig["rarity"],
            sig.get("lat"),
            sig.get("lng"),
        ),
    )
    db_con.commit()


def total_signals() -> int:
    row = db_con.execute("SELECT COUNT(*) FROM signals").fetchone()
    return row[0] if row else 0


def classify_rarity(ac: dict) -> str:
    callsign = ac.get("flight", "").strip().upper()
    squawk = ac.get("squawk", "")
    hex_id = ac.get("hex", "")

    if squawk in EMERGENCY_SQUAWKS:
        return "LEGEND"

    if not hex_id and not callsign:
        return "LEGEND"

    if not hex_id:
        return "EPIC"

    for prefix in MILITARY_PREFIXES:
        if callsign.startswith(prefix):
            return "EPIC"

    if not callsign:
        return "RARE"

    if callsign.startswith("N") and 4 <= len(callsign) <= 6:
        return "UNCOMMON"

    return "COMMON"


def format_detail(ac: dict) -> str:
    parts = []
    alt = ac.get("alt_baro") or ac.get("altitude")
    if alt:
        parts.append(f"{int(alt)}ft")
    spd = ac.get("gs") or ac.get("speed")
    if spd:
        parts.append(f"{int(spd)}kt")
    t = ac.get("t") or ac.get("type", "")
    if t:
        parts.append(t)
    return " ".join(parts)[:30] or "Unknown"


last_callsign = ""


def apply_aircraft(best: dict):
    global last_callsign

    callsign = best.get("flight", "UNKNOWN").strip() or "UNKNOWN"
    rarity = best.get("_rarity", classify_rarity(best))
    detail = format_detail(best)
    is_new = callsign != last_callsign

    with state_lock:
        state["type"] = "ADS-B"
        state["callsign"] = callsign
        state["detail"] = detail
        state["rarity"] = rarity

    if is_new:
        last_callsign = callsign
        sig = {**state, "lat": state.get("lat"), "lng": state.get("lng")}
        log_signal(sig)
        state["total"] = total_signals()
        log.info("New signal: %s [%s] — %s", callsign, rarity, detail)


def poll_dump1090():
    if FAKE_SIGNALS:
        ac = random.choice(FAKE_AIRCRAFT).copy()
        ac["_rarity"] = classify_rarity(ac)
        apply_aircraft(ac)
        return

    try:
        with open(DUMP1090_JSON, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log.debug("dump1090 json read failed: %s", e)
        return

    aircraft = data.get("aircraft", [])
    if not aircraft:
        return

    score_map = {"LEGEND": 5, "EPIC": 4, "RARE": 3, "UNCOMMON": 2, "COMMON": 1}

    best = None
    best_sc = 0
    for ac in aircraft:
        rarity = classify_rarity(ac)
        sc = score_map[rarity]
        callsign = ac.get("flight", "").strip()
        if callsign != last_callsign:
            sc += 0.5
        if sc > best_sc:
            best_sc = sc
            best = ac
            best["_rarity"] = rarity

    if best:
        apply_aircraft(best)


def poll_gps():
    while True:
        try:
            session = gps.gps(mode=gps.WATCH_ENABLE | gps.WATCH_NEWSTYLE)
            log.info("GPS session started")
            for report in session:
                if report["class"] == "TPV":
                    locked = getattr(report, "mode", 0) >= 2
                    with state_lock:
                        state["gpsLocked"] = locked
                        if locked:
                            state["lat"] = getattr(report, "lat", None)
                            state["lng"] = getattr(report, "lon", None)
        except Exception as e:
            log.warning("GPS error: %s — retrying in 5s", e)
            time.sleep(5)


def fake_gps_loop():
    while True:
        with state_lock:
            state["gpsLocked"] = True
            state["lat"] = 52.52 + random.uniform(-0.01, 0.01)
            state["lng"] = 13.405 + random.uniform(-0.01, 0.01)
        time.sleep(5)


def signal_loop():
    log.info("Signal poller started (fake=%s)", FAKE_SIGNALS)
    while True:
        poll_dump1090()
        time.sleep(POLL_INTERVAL)


@app.route("/api/latest")
def api_latest():
    with state_lock:
        return jsonify(dict(state))


@app.route("/api/history")
def api_history():
    rows = db_con.execute(
        "SELECT ts,type,callsign,detail,rarity,lat,lng "
        "FROM signals ORDER BY ts DESC LIMIT 100"
    ).fetchall()
    signals = [
        {
            "ts": r[0],
            "type": r[1],
            "callsign": r[2],
            "detail": r[3],
            "rarity": r[4],
            "lat": r[5],
            "lng": r[6],
        }
        for r in rows
    ]
    return jsonify(signals)


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok", "total": state["total"], "fake": FAKE_SIGNALS})


if __name__ == "__main__":
    log.info("=== SIGLOG API starting ===")

    if FAKE_SIGNALS:
        threading.Thread(target=fake_gps_loop, daemon=True).start()
    else:
        threading.Thread(target=poll_gps, daemon=True).start()

    threading.Thread(target=signal_loop, daemon=True).start()
    state["total"] = total_signals()

    log.info("API listening on port %s", API_PORT)
    app.run(host="0.0.0.0", port=API_PORT, debug=False, threaded=True)
