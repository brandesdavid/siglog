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
SCHEDULER_STATE = "/app/data/scheduler_state.json"
POSITION_PATH = "/app/data/position.json"
POLL_INTERVAL = 2.0
FAKE_SIGNALS = os.getenv("FAKE_SIGNALS", "0") == "1"
ENABLE_GPS = os.getenv("ENABLE_GPS", "auto")

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
    "nextPass": None,
    "upcoming": [],
    "schedulerMessage": None,
    "mode": "ADS-B",
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
last_noaa_key = ""


def gps_enabled() -> bool:
    if ENABLE_GPS == "0":
        return False
    if ENABLE_GPS == "1":
        return True
    return os.path.exists("/var/run/gpsd.sock")


def write_position(lat: float, lng: float) -> None:
    os.makedirs("/app/data", exist_ok=True)
    with open(POSITION_PATH, "w", encoding="utf-8") as f:
        json.dump({"lat": lat, "lng": lng, "ts": int(time.time())}, f)


def merge_scheduler_state() -> None:
    try:
        with open(SCHEDULER_STATE, encoding="utf-8") as f:
            sch = json.load(f)
    except OSError:
        return
    with state_lock:
        state["nextPass"] = sch.get("nextPass")
        state["upcoming"] = sch.get("upcoming", [])
        state["schedulerMessage"] = sch.get("message")
        mode = sch.get("mode", "ADS-B")
        state["mode"] = mode
        if mode == "NOAA_RECORD":
            p = sch.get("pass") or {}
            state["type"] = "NOAA"
            state["callsign"] = p.get("name", "SAT")
            state["detail"] = sch.get("message", "Recording pass…")
            state["rarity"] = "RARE"
        elif mode == "NOAA_DECODE":
            p = sch.get("pass") or {}
            state["type"] = "NOAA"
            state["callsign"] = p.get("name", "SAT")
            state["detail"] = sch.get("message", "Decoding…")
            state["rarity"] = "RARE"
        last = sch.get("lastCapture")
        if last and mode == "ADS-B":
            global last_noaa_key
            key = f"{last.get('name')}_{last.get('ts')}"
            if key != last_noaa_key:
                last_noaa_key = key
                state["type"] = "NOAA"
                state["callsign"] = last.get("name", "NOAA")
                state["detail"] = last.get("detail", "APT capture")
                state["rarity"] = "RARE"


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
    merge_scheduler_state()
    with state_lock:
        if state.get("mode") in ("NOAA_RECORD", "NOAA_DECODE"):
            return
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
                            lat = getattr(report, "lat", None)
                            lng = getattr(report, "lon", None)
                            state["lat"] = lat
                            state["lng"] = lng
                            if lat is not None and lng is not None:
                                write_position(lat, lng)
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
        merge_scheduler_state()
        poll_dump1090()
        time.sleep(POLL_INTERVAL)


def fake_scheduler_loop():
    while True:
        with state_lock:
            state["nextPass"] = {
                "name": "NOAA 19",
                "startInMin": 8,
                "maxElevation": 42.0,
                "freqMhz": 137.1,
                "antennaCm": 54,
                "aptSat": "noaa_19",
            }
            state["upcoming"] = [state["nextPass"]]
            state["schedulerMessage"] = "NOAA 19 in 8 min — dipole ~54 cm"
        time.sleep(30)


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


@app.route("/api/passes")
def api_passes():
    merge_scheduler_state()
    with state_lock:
        return jsonify(
            {
                "nextPass": state.get("nextPass"),
                "upcoming": state.get("upcoming", []),
                "message": state.get("schedulerMessage"),
                "lat": state.get("lat"),
                "lng": state.get("lng"),
            }
        )


@app.route("/api/health")
def api_health():
    merge_scheduler_state()
    with state_lock:
        return jsonify(
            {
                "status": "ok",
                "total": state["total"],
                "fake": FAKE_SIGNALS,
                "mode": state.get("mode"),
                "gps": state.get("gpsLocked"),
            }
        )


if __name__ == "__main__":
    log.info("=== SIGLOG API starting ===")

    if FAKE_SIGNALS:
        threading.Thread(target=fake_gps_loop, daemon=True).start()
        threading.Thread(target=fake_scheduler_loop, daemon=True).start()
    elif gps_enabled():
        threading.Thread(target=poll_gps, daemon=True).start()
    else:
        write_position(
            float(os.getenv("SIGLOG_LAT", "52.52")),
            float(os.getenv("SIGLOG_LON", "13.405")),
        )

    threading.Thread(target=signal_loop, daemon=True).start()
    state["total"] = total_signals()

    log.info("API listening on port %s", API_PORT)
    app.run(host="0.0.0.0", port=API_PORT, debug=False, threaded=True)
