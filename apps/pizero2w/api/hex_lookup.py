import json
import logging
import sqlite3
import time
import urllib.error
import urllib.request

from rarity import classify_rarity_decoded

log = logging.getLogger("siglog.hex_lookup")

ADSDB_URL = "https://api.adsbdb.com/v0/aircraft/{hex_id}"


def ensure_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS hex_lookup (
            hex TEXT PRIMARY KEY,
            registration TEXT,
            aircraft_type TEXT,
            operator TEXT,
            fetched_ts INTEGER NOT NULL
        )
        """
    )
    con.commit()


def is_icao_hex(value: str) -> bool:
    return len(value) == 6 and all(c in "0123456789abcdef" for c in value.lower())


def get_cached(con: sqlite3.Connection, hex_id: str) -> dict | None:
    row = con.execute(
        "SELECT hex, registration, aircraft_type, operator, fetched_ts "
        "FROM hex_lookup WHERE hex = ?",
        (hex_id.lower(),),
    ).fetchone()
    if not row:
        return None
    return {
        "hex": row[0],
        "registration": row[1],
        "aircraftType": row[2],
        "operator": row[3],
        "fetchedTs": row[4],
    }


def fetch_remote(hex_id: str) -> dict:
    hex_id = hex_id.lower()
    url = ADSDB_URL.format(hex_id=hex_id)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "siglog/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = json.load(resp)
    ac = (raw.get("response") or {}).get("aircraft")
    if not ac:
        raise ValueError("aircraft not in database")
    registration = ac.get("registration") or ""
    aircraft_type = ac.get("icao_type") or ac.get("type") or ""
    operator = ac.get("registered_owner") or ac.get("registered_owner_country_name") or ""
    return {
        "hex": hex_id,
        "registration": str(registration).strip() or None,
        "aircraftType": str(aircraft_type).strip() or None,
        "operator": str(operator).strip() or None,
    }


def store(con: sqlite3.Connection, info: dict) -> None:
    con.execute(
        "INSERT INTO hex_lookup (hex, registration, aircraft_type, operator, fetched_ts) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(hex) DO UPDATE SET "
        "registration=excluded.registration, "
        "aircraft_type=excluded.aircraft_type, "
        "operator=excluded.operator, "
        "fetched_ts=excluded.fetched_ts",
        (
            info["hex"].lower(),
            info.get("registration"),
            info.get("aircraftType"),
            info.get("operator"),
            int(time.time()),
        ),
    )
    con.commit()


def decode_hex(con: sqlite3.Connection, hex_id: str, force: bool = False) -> dict:
    hex_id = hex_id.lower()
    if not is_icao_hex(hex_id):
        return {"hex": hex_id, "ok": False, "error": "invalid hex"}
    if not force:
        cached = get_cached(con, hex_id)
        if cached:
            rarity = refresh_signal_rarity_for_hex(con, hex_id)
            return {"ok": True, "cached": True, "rarity": rarity, **cached}
    try:
        info = fetch_remote(hex_id)
        store(con, info)
        row = get_cached(con, hex_id)
        rarity = refresh_signal_rarity_for_hex(con, hex_id)
        return {"ok": True, "cached": False, "rarity": rarity, **(row or info)}
    except urllib.error.HTTPError as e:
        log.warning("adsbdb HTTP %s for %s", e.code, hex_id)
        return {"hex": hex_id, "ok": False, "error": f"HTTP {e.code}"}
    except (OSError, ValueError, json.JSONDecodeError) as e:
        log.warning("adsbdb failed for %s: %s", hex_id, e)
        return {"hex": hex_id, "ok": False, "error": str(e)}


def pending_hex_list(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        """
        SELECT DISTINCT lower(COALESCE(NULLIF(hex, ''), aircraft_key)) AS h
        FROM signals
        WHERE callsign = 'UNKNOWN'
          AND length(COALESCE(NULLIF(hex, ''), aircraft_key)) = 6
          AND lower(COALESCE(NULLIF(hex, ''), aircraft_key)) NOT IN (
            SELECT hex FROM hex_lookup
          )
        """
    ).fetchall()
    return [r[0] for r in rows if is_icao_hex(r[0])]


def decode_all_pending(con: sqlite3.Connection) -> dict:
    pending = pending_hex_list(con)
    ok = 0
    failed = 0
    results = []
    for hex_id in pending:
        out = decode_hex(con, hex_id)
        results.append(out)
        if out.get("ok"):
            ok += 1
        else:
            failed += 1
        time.sleep(0.5)
    reclassify_all_decoded(con)
    return {"decoded": ok, "failed": failed, "pending": len(pending), "results": results}


def refresh_signal_rarity_for_hex(con: sqlite3.Connection, hex_id: str) -> str | None:
    info = get_cached(con, hex_id)
    if not info:
        return None
    rarity = classify_rarity_decoded(info)
    con.execute(
        "UPDATE signals SET rarity = ? "
        "WHERE lower(COALESCE(NULLIF(hex, ''), aircraft_key)) = ?",
        (rarity, hex_id.lower()),
    )
    con.commit()
    return rarity


def normalize_hex_only_rarity(con: sqlite3.Connection) -> int:
    cur = con.execute(
        "UPDATE signals SET rarity = 'COMMON' "
        "WHERE callsign = 'UNKNOWN' AND rarity = 'RARE'"
    )
    con.commit()
    return cur.rowcount


def reclassify_all_decoded(con: sqlite3.Connection) -> int:
    n = 0
    for hex_id in all_lookups(con):
        if refresh_signal_rarity_for_hex(con, hex_id):
            n += 1
    return n


def all_lookups(con: sqlite3.Connection) -> dict[str, dict]:
    rows = con.execute(
        "SELECT hex, registration, aircraft_type, operator, fetched_ts FROM hex_lookup"
    ).fetchall()
    out = {}
    for row in rows:
        out[row[0]] = {
            "hex": row[0],
            "registration": row[1],
            "aircraftType": row[2],
            "operator": row[3],
            "fetchedTs": row[4],
        }
    return out
