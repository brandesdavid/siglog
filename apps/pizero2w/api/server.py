import os
import json
import time
import sqlite3
import logging
import threading
import random
import gps
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

from plan_cache import enrich_plan_passes, pass_capture_params, read_plan_cache, write_plan_cache
from satellite_log import refresh_satellite_rarities
from satellite_passes import passes_with_tracks
from hex_lookup import (
    all_lookups,
    decode_all_pending,
    decode_hex as lookup_decode_hex,
    ensure_table as ensure_hex_table,
    get_cached,
    is_icao_hex,
    normalize_hex_only_rarity,
    reclassify_all_decoded,
)
from rarity import classify_rarity
from manual_capture import (
    CAPTURE_DIR,
    capture_busy,
    delete_capture,
    list_captures,
    queue_host_command,
    read_capture_state,
    read_host_result,
    quick_signal_check,
    start_capture,
    stop_capture,
    supervisorctl,
)
from log_reader import read_logs
from storage_stats import storage_stats

DUMP1090_JSON = os.getenv("DUMP1090_JSON", "/app/data/dump1090/aircraft.json")
API_PORT = int(os.getenv("API_PORT", 80))
DB_PATH = "/app/data/signals.db"
SCHEDULER_STATE = "/app/data/scheduler_state.json"
POSITION_PATH = "/app/data/position.json"
POLL_INTERVAL = 2.0
LOG_COOLDOWN_SEC = float(os.getenv("LOG_COOLDOWN_SEC", "1800"))
FAKE_SIGNALS = os.getenv("FAKE_SIGNALS", "0") == "1"
ENABLE_GPS = os.getenv("ENABLE_GPS", "auto")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("siglog")

WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")

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
    cols = {r[1] for r in con.execute("PRAGMA table_info(signals)")}
    if "gps_fix" not in cols:
        con.execute(
            "ALTER TABLE signals ADD COLUMN gps_fix INTEGER NOT NULL DEFAULT 0"
        )
        con.commit()
    cols = {r[1] for r in con.execute("PRAGMA table_info(signals)")}
    if "aircraft_key" not in cols:
        con.execute("ALTER TABLE signals ADD COLUMN aircraft_key TEXT")
        con.commit()
    cols = {r[1] for r in con.execute("PRAGMA table_info(signals)")}
    if "hex" not in cols:
        con.execute("ALTER TABLE signals ADD COLUMN hex TEXT")
        con.commit()
    con.execute(
        "UPDATE signals SET aircraft_key = callsign WHERE aircraft_key IS NULL"
    )
    con.execute(
        "UPDATE signals SET hex = aircraft_key "
        "WHERE hex IS NULL AND callsign = 'UNKNOWN' "
        "AND length(aircraft_key) = 6"
    )
    con.commit()
    return con


db_con = init_db()
ensure_hex_table(db_con)
fixed = normalize_hex_only_rarity(db_con)
if fixed:
    log.info("Set %d hex-only log entries from RARE to COMMON", fixed)
reclassify_all_decoded(db_con)
sat_updated = refresh_satellite_rarities(db_con)
if sat_updated:
    log.info("Refreshed rarity on %d satellite log entries", sat_updated)
EXPORT_DIR = "/app/data/exports"


def icao_hex(ac: dict) -> str:
    return (ac.get("hex") or "").strip().lower()


def aircraft_key(ac: dict) -> str:
    hex_id = icao_hex(ac)
    if hex_id:
        return hex_id
    callsign = (ac.get("flight") or "").strip().upper()
    return callsign or "UNKNOWN"


def is_hex_only_row(callsign: str, hex_id: Optional[str], key: str) -> bool:
    if callsign != "UNKNOWN":
        return False
    if hex_id and is_icao_hex(hex_id):
        return True
    return is_icao_hex(key or "")


HISTORY_HEX_SQL = (
    "callsign = 'UNKNOWN' "
    "AND length(COALESCE(NULLIF(hex, ''), aircraft_key)) = 6 "
    "AND lower(COALESCE(NULLIF(hex, ''), aircraft_key)) "
    "GLOB '[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'"
)
HISTORY_CALLSIGN_SQL = "callsign != 'UNKNOWN'"


def catch_count(key: str) -> int:
    row = db_con.execute(
        "SELECT COUNT(*) FROM signals WHERE aircraft_key = ?", (key,)
    ).fetchone()
    return int(row[0]) if row else 0


def log_signal(sig: dict):
    db_con.execute(
        "INSERT INTO signals (ts,type,callsign,detail,rarity,lat,lng,gps_fix,aircraft_key,hex) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            int(time.time()),
            sig["type"],
            sig["callsign"],
            sig["detail"],
            sig["rarity"],
            sig.get("lat"),
            sig.get("lng"),
            1 if sig.get("gpsFix") else 0,
            sig.get("aircraftKey"),
            sig.get("hex"),
        ),
    )
    db_con.commit()


def total_signals() -> int:
    row = db_con.execute("SELECT COUNT(*) FROM signals").fetchone()
    return row[0] if row else 0


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
last_logged_ts: dict[str, float] = {}


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
        if sch.get("observerLat") is not None:
            state["lat"] = sch.get("observerLat")
            state["lng"] = sch.get("observerLng")
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


def should_log_aircraft(ac: dict) -> bool:
    key = aircraft_key(ac)
    now = time.time()
    last = last_logged_ts.get(key)
    if last is not None and now - last < LOG_COOLDOWN_SEC:
        return False
    row = db_con.execute(
        "SELECT MAX(ts) FROM signals WHERE aircraft_key = ?", (key,)
    ).fetchone()
    if row and row[0] is not None and now - row[0] < LOG_COOLDOWN_SEC:
        return False
    last_logged_ts[key] = now
    return True


def apply_aircraft(best: dict):
    global last_callsign

    callsign = best.get("flight", "UNKNOWN").strip() or "UNKNOWN"
    hex_id = icao_hex(best)
    key = aircraft_key(best)
    rarity = best.get("_rarity", classify_rarity(best))
    detail = format_detail(best)
    prev_catches = catch_count(key)
    hex_only = is_hex_only_row(callsign, hex_id, key)
    display_call = callsign
    if hex_only and hex_id:
        display_call = hex_id.upper()

    with state_lock:
        state["type"] = "ADS-B"
        state["callsign"] = callsign
        state["displayCall"] = display_call
        state["hex"] = hex_id or None
        state["hexOnly"] = hex_only
        state["detail"] = detail
        state["rarity"] = rarity
        state["aircraftKey"] = key
        state["catchCount"] = prev_catches
        state["knownAircraft"] = prev_catches > 0
        gps_fix = bool(state.get("gpsLocked"))
        lat = state.get("lat") if gps_fix else None
        lng = state.get("lng") if gps_fix else None

    if callsign == "UNKNOWN" and not hex_id:
        return

    if should_log_aircraft(best):
        last_callsign = callsign
        log_signal(
            {
                "type": "ADS-B",
                "callsign": callsign,
                "detail": detail,
                "rarity": rarity,
                "lat": lat,
                "lng": lng,
                "gpsFix": gps_fix,
                "aircraftKey": key,
                "hex": hex_id or None,
            }
        )
        with state_lock:
            state["total"] = total_signals()
            state["catchCount"] = catch_count(key)
            state["knownAircraft"] = True
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


def stats_dict() -> dict:
    total = total_signals()
    by_rarity = {
        r[0]: r[1]
        for r in db_con.execute(
            "SELECT rarity, COUNT(*) FROM signals GROUP BY rarity"
        ).fetchall()
    }
    by_type = {
        r[0]: r[1]
        for r in db_con.execute(
            "SELECT type, COUNT(*) FROM signals GROUP BY type"
        ).fetchall()
    }
    with_gps_fix = db_con.execute(
        "SELECT COUNT(*) FROM signals WHERE gps_fix = 1"
    ).fetchone()[0]
    unique = db_con.execute(
        "SELECT COUNT(DISTINCT COALESCE(aircraft_key, callsign)) FROM signals"
    ).fetchone()[0]
    hex_only = db_con.execute(
        f"SELECT COUNT(*) FROM signals WHERE {HISTORY_HEX_SQL}"
    ).fetchone()[0]
    callsign_entries = db_con.execute(
        f"SELECT COUNT(*) FROM signals WHERE {HISTORY_CALLSIGN_SQL}"
    ).fetchone()[0]
    decoded = db_con.execute("SELECT COUNT(*) FROM hex_lookup").fetchone()[0]
    row = db_con.execute("SELECT MIN(ts), MAX(ts) FROM signals").fetchone()
    return {
        "total": total,
        "withGpsFix": with_gps_fix,
        "uniqueAircraft": unique,
            "identified": total - hex_only,
            "hexOnly": hex_only,
            "callsignEntries": callsign_entries,
            "hexDecoded": decoded,
        "byRarity": by_rarity,
        "byType": by_type,
        "firstTs": row[0],
        "lastTs": row[1],
        "logCooldownSec": LOG_COOLDOWN_SEC,
    }


@app.route("/api/stats")
def api_stats():
    return jsonify(stats_dict())


def lookup_fields(hex_id: str) -> dict:
    if not hex_id or not is_icao_hex(hex_id):
        return {}
    row = get_cached(db_con, hex_id.lower())
    if not row:
        return {}
    parts = [p for p in (row.get("registration"), row.get("aircraftType")) if p]
    resolved = " · ".join(parts) if parts else None
    return {
        "resolved": resolved,
        "registration": row.get("registration"),
        "aircraftType": row.get("aircraftType"),
        "operator": row.get("operator"),
    }


def row_to_signal(r: tuple) -> dict:
    callsign = r[2]
    hex_id = (r[9] or "").lower() if r[9] else ""
    if not hex_id and is_icao_hex((r[8] or "")):
        hex_id = (r[8] or "").lower()
    hex_only = is_hex_only_row(callsign, hex_id, r[8] or "")
    display = callsign
    if hex_only and hex_id:
        display = hex_id.upper()
    item = {
        "ts": r[0],
        "type": r[1],
        "callsign": callsign,
        "displayCall": display,
        "hex": hex_id or None,
        "hexOnly": hex_only,
        "detail": r[3],
        "rarity": r[4],
        "lat": r[5],
        "lng": r[6],
        "gpsFix": bool(r[7]),
    }
    item.update(lookup_fields(hex_id))
    return item


@app.route("/api/history")
def api_history():
    limit = min(int(request.args.get("limit", "40")), 500)
    page = max(int(request.args.get("page", "1")), 1)
    offset = (page - 1) * limit
    filt = request.args.get("filter", "all")
    if filt == "hex":
        where = HISTORY_HEX_SQL
    elif filt == "callsign":
        where = HISTORY_CALLSIGN_SQL
    else:
        where = "1=1"
    total = db_con.execute(f"SELECT COUNT(*) FROM signals WHERE {where}").fetchone()[0]
    rows = db_con.execute(
        "SELECT ts,type,callsign,detail,rarity,lat,lng,gps_fix,aircraft_key,hex "
        f"FROM signals WHERE {where} ORDER BY ts DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    total_pages = max(1, (total + limit - 1) // limit)
    if page > total_pages:
        page = total_pages
        offset = (page - 1) * limit
        rows = db_con.execute(
            "SELECT ts,type,callsign,detail,rarity,lat,lng,gps_fix,aircraft_key,hex "
            f"FROM signals WHERE {where} ORDER BY ts DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return jsonify(
        {
            "items": [row_to_signal(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
            "totalPages": total_pages,
            "filter": filt,
        }
    )


def build_export_payload() -> dict:
    rows = db_con.execute(
        "SELECT ts,type,callsign,detail,rarity,lat,lng,gps_fix,aircraft_key,hex "
        "FROM signals ORDER BY ts ASC"
    ).fetchall()
    signals = []
    for r in rows:
        callsign = r[2]
        hex_id = (r[9] or "").lower() if r[9] else ""
        if not hex_id and is_icao_hex((r[8] or "")):
            hex_id = (r[8] or "").lower()
        hex_only = is_hex_only_row(callsign, hex_id, r[8] or "")
        item = {
            "ts": r[0],
            "type": r[1],
            "callsign": callsign,
            "detail": r[3],
            "rarity": r[4],
            "lat": r[5],
            "lng": r[6],
            "gpsFix": bool(r[7]),
            "aircraftKey": r[8],
            "hex": hex_id or None,
            "hexOnly": hex_only,
        }
        item.update(lookup_fields(hex_id))
        signals.append(item)
    return {
        "version": 1,
        "exportedAt": int(time.time()),
        "stats": stats_dict(),
        "signals": signals,
        "hexLookup": all_lookups(db_con),
    }


@app.route("/api/decode", methods=["POST"])
def api_decode():
    body = request.get_json(silent=True) or {}
    if body.get("all"):
        return jsonify(decode_all_pending(db_con))
    hex_id = (body.get("hex") or "").strip().lower()
    if hex_id:
        return jsonify(
            lookup_decode_hex(db_con, hex_id, force=bool(body.get("force")))
        )
    return jsonify({"ok": False, "error": "send {\"all\": true} or {\"hex\": \"abcdef\"}"}), 400


@app.route("/api/export")
def api_export():
    payload = build_export_payload()
    os.makedirs(EXPORT_DIR, exist_ok=True)
    path = os.path.join(EXPORT_DIR, "latest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return jsonify(payload)


@app.route("/")
def web_home():
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/api/map")
def api_map():
    merge_scheduler_state()
    with state_lock:
        lat = state.get("lat")
        lng = state.get("lng")
    if request.args.get("lat") is not None:
        lat = float(request.args.get("lat"))
    elif lat is None:
        lat = float(os.getenv("SIGLOG_LAT", "52.52"))
    if request.args.get("lng") is not None:
        lng = float(request.args.get("lng"))
    elif lng is None:
        lng = float(os.getenv("SIGLOG_LON", "13.405"))
    hours = float(request.args.get("hours", "48"))
    min_el = float(request.args.get("minEl", os.getenv("NOAA_MIN_ELEVATION", "15")))
    try:
        passes = passes_with_tracks(lat, lng, hours=hours, min_el=min_el)
    except Exception as e:
        log.exception("api_map: %s", e)
        passes = []
    with state_lock:
        latest = {
            "type": state.get("type"),
            "callsign": state.get("callsign"),
            "detail": state.get("detail"),
            "rarity": state.get("rarity"),
            "total": state.get("total"),
        }
        message = state.get("schedulerMessage")
    return jsonify(
        {
            "observer": {"lat": lat, "lng": lng},
            "passes": passes,
            "latest": latest,
            "message": message,
        }
    )


def _plan_coords() -> tuple[float, float]:
    merge_scheduler_state()
    with state_lock:
        lat = state.get("lat")
        lng = state.get("lng")
    body = request.get_json(silent=True) or {}
    if body.get("lat") is not None:
        lat = float(body["lat"])
    elif request.args.get("lat") is not None:
        lat = float(request.args.get("lat"))
    elif lat is None:
        lat = float(os.getenv("SIGLOG_LAT", "52.52"))
    if body.get("lng") is not None:
        lng = float(body["lng"])
    elif request.args.get("lng") is not None:
        lng = float(request.args.get("lng"))
    elif lng is None:
        lng = float(os.getenv("SIGLOG_LON", "13.405"))
    return lat, lng


@app.route("/api/plan", methods=["GET"])
def api_plan_get():
    data = read_plan_cache()
    if not data:
        return jsonify({"ok": False, "passes": [], "message": "No saved plan"}), 404
    data = enrich_plan_passes(data)
    data["ok"] = True
    data["fromCache"] = True
    return jsonify(data)


@app.route("/api/plan/fetch", methods=["POST"])
def api_plan_fetch():
    lat, lng = _plan_coords()
    hours = float(request.args.get("hours", "48"))
    min_el = float(request.args.get("minEl", os.getenv("NOAA_MIN_ELEVATION", "15")))
    try:
        passes = passes_with_tracks(lat, lng, hours=hours, min_el=min_el)
    except Exception as e:
        log.exception("api_plan_fetch: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 502
    payload = {
        "observer": {"lat": lat, "lng": lng},
        "passes": passes,
        "hours": hours,
        "minEl": min_el,
    }
    write_plan_cache(payload)
    out = enrich_plan_passes(payload)
    out["ok"] = True
    out["fromCache"] = False
    return jsonify(out)


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


CAPTURE_PRESETS = {
    "lrpt1379": (137.9, "lrpt1379"),
    "lrpt1371": (137.1, "lrpt1371"),
    "apt1371": (137.1, "apt1371"),
}


def parse_wifi_from_host(text: str | None) -> dict:
    if not text:
        return {"mode": "unknown", "label": "WiFi unknown"}
    if "Auto-Modus aktiv" in text:
        return {"mode": "auto", "label": "WiFi auto"}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Modus:"):
            detail = stripped.split("Modus:", 1)[1].strip()
            if "Hotspot" in detail:
                return {"mode": "hotspot", "label": "Hotspot"}
            if "Heim-WLAN" in detail:
                return {"mode": "home", "label": "Home WiFi"}
    return {"mode": "unknown", "label": "WiFi unknown"}


def build_system_status(
    cap: dict, sch_mode: str, host_text: str | None, gps_locked: bool
) -> dict:
    if cap.get("active"):
        msg = cap.get("message") or ""
        if "Decoding" in msg:
            signal = "APT_DECODE"
        else:
            signal = "RECORD"
        signal_detail = msg or f"Recording {cap.get('label', '')}"
    elif sch_mode == "NOAA_RECORD":
        signal = "NOAA_RECORD"
        signal_detail = "NOAA recording"
    elif sch_mode == "NOAA_DECODE":
        signal = "NOAA_DECODE"
        signal_detail = "NOAA decoding"
    else:
        signal = "ADS-B"
        signal_detail = "ADS-B"
    wifi = parse_wifi_from_host(host_text)
    return {
        "signal": signal,
        "signalDetail": signal_detail,
        "wifi": wifi["mode"],
        "wifiLabel": wifi["label"],
        "gps": bool(gps_locked),
    }


@app.route("/api/control/status")
def api_control_status():
    merge_scheduler_state()
    cap = read_capture_state()
    host_text = read_host_result()
    with state_lock:
        sched = {
            "nextPass": state.get("nextPass"),
            "message": state.get("schedulerMessage"),
            "mode": state.get("mode"),
        }
        system = build_system_status(
            cap, state.get("mode", "ADS-B"), host_text, state.get("gpsLocked")
        )
    return jsonify(
        {
            "capture": cap,
            "captureBusy": capture_busy(),
            "captures": list_captures(),
            "storage": storage_stats(),
            "hostResult": host_text,
            "scheduler": sched,
            "system": system,
        }
    )


@app.route("/api/control/signal-check", methods=["POST"])
def api_control_signal_check():
    body = request.get_json(silent=True) or {}
    if body.get("passIndex") is not None:
        cached = read_plan_cache()
        idx = int(body["passIndex"])
        passes = (cached or {}).get("passes") or []
        if idx < 0 or idx >= len(passes):
            return jsonify({"ok": False, "error": "pass not found"}), 404
        freq = float(passes[idx]["freqMhz"])
    elif body.get("freqMhz") is not None:
        freq = float(body["freqMhz"])
    elif body.get("preset") in CAPTURE_PRESETS:
        freq, _ = CAPTURE_PRESETS[body["preset"]]
    else:
        return jsonify({"ok": False, "error": "passIndex, freqMhz, or preset required"}), 400
    duration = int(body.get("durationSec", 5))
    return jsonify(quick_signal_check(freq, duration))


@app.route("/api/control/capture", methods=["POST"])
def api_control_capture():
    body = request.get_json(silent=True) or {}
    if body.get("passIndex") is not None or body.get("pass"):
        if body.get("pass"):
            pass_row = body["pass"]
        else:
            cached = read_plan_cache()
            idx = int(body["passIndex"])
            passes = (cached or {}).get("passes") or []
            if idx < 0 or idx >= len(passes):
                return jsonify({"ok": False, "error": "pass not found"}), 404
            pass_row = passes[idx]
        freq, duration, label, decode_apt = pass_capture_params(pass_row)
        return jsonify(
            start_capture(
                freq,
                duration,
                label,
                decode_apt=decode_apt,
                pass_name=pass_row.get("name"),
                decoder=pass_row.get("decoder"),
                max_elevation=pass_row.get("maxElevation"),
            )
        )
    preset = body.get("preset", "lrpt1379")
    if preset not in CAPTURE_PRESETS:
        return jsonify({"ok": False, "error": "unknown preset"}), 400
    freq, label = CAPTURE_PRESETS[preset]
    duration = int(body.get("durationSec", 600))
    decode_apt = bool(body.get("decodeApt")) and preset.startswith("apt")
    return jsonify(
        start_capture(freq, duration, label, decode_apt=decode_apt)
    )


@app.route("/api/control/stop", methods=["POST"])
def api_control_stop():
    return jsonify(stop_capture())


@app.route("/api/control/restart", methods=["POST"])
def api_control_restart():
    body = request.get_json(silent=True) or {}
    target = body.get("target", "dump1090")
    allowed = {"dump1090", "api", "scheduler", "all"}
    if target not in allowed:
        return jsonify({"ok": False, "error": "unknown target"}), 400
    if target == "all":
        r = supervisorctl("restart", "dump1090", "scheduler")
    else:
        r = supervisorctl("restart", target)
    return jsonify(
        {
            "ok": r.returncode == 0,
            "stdout": r.stdout[-500:] if r.stdout else "",
            "stderr": r.stderr[-500:] if r.stderr else "",
        }
    )


@app.route("/api/control/host", methods=["POST"])
def api_control_host():
    body = request.get_json(silent=True) or {}
    cmd = body.get("cmd", "status")
    try:
        queue_host_command(cmd)
        return jsonify({"ok": True, "message": f"Queued siglog-net {cmd}"})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/captures/<path:name>", methods=["DELETE"])
def api_capture_delete(name):
    return jsonify(delete_capture(name))


@app.route("/api/history/purge-satellite", methods=["POST"])
def api_history_purge_satellite():
    body = request.get_json(silent=True) or {}
    sig_type = body.get("type", "METEOR")
    if sig_type not in ("METEOR", "NOAA"):
        return jsonify({"ok": False, "error": "type must be METEOR or NOAA"}), 400
    cur = db_con.execute("DELETE FROM signals WHERE type = ?", (sig_type,))
    db_con.commit()
    with state_lock:
        state["total"] = total_signals()
    return jsonify({"ok": True, "deleted": cur.rowcount, "type": sig_type})


@app.route("/api/captures/<path:name>")
def api_capture_file(name):
    safe = os.path.basename(name)
    path = CAPTURE_DIR / safe
    if not path.is_file():
        return jsonify({"error": "not found"}), 404
    return send_from_directory(CAPTURE_DIR, safe, as_attachment=True)


@app.route("/api/logs")
def api_logs():
    service = request.args.get("service", "all")
    lines = int(request.args.get("lines", "200"))
    return jsonify(read_logs(service=service, max_lines=lines))


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
