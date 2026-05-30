import json
import logging
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from satellite_passes import next_pass, predict_passes

log = logging.getLogger("siglog.scheduler")

DATA = Path("/app/data")
STATE_PATH = DATA / "scheduler_state.json"
POSITION_PATH = DATA / "position.json"
DB_PATH = DATA / "signals.db"
NOAA_DIR = DATA / "noaa"
SUPERVISOR_CONF = os.getenv(
    "SUPERVISOR_CONFIG", "/etc/supervisor/conf.d/siglog-no-gps.conf"
)
NOAA_APT = os.getenv("NOAA_APT_BIN", "/usr/local/bin/noaa-apt")
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "1") == "1"
MIN_ELEV = float(os.getenv("NOAA_MIN_ELEVATION", "15"))
NOTIFY_MIN = int(os.getenv("NOAA_NOTIFY_MINUTES", "15"))
RECORD_LEAD_SEC = int(os.getenv("NOAA_RECORD_LEAD_SEC", "30"))
DEFAULT_LAT = float(os.getenv("SIGLOG_LAT", "52.52"))
DEFAULT_LON = float(os.getenv("SIGLOG_LON", "13.405"))


def read_position() -> tuple[float, float]:
    try:
        with open(POSITION_PATH, encoding="utf-8") as f:
            p = json.load(f)
        if p.get("lat") is not None and p.get("lng") is not None:
            return float(p["lat"]), float(p["lng"])
    except OSError:
        pass
    return DEFAULT_LAT, DEFAULT_LON


def write_state(payload: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    tmp.replace(STATE_PATH)


def supervisorctl(*args: str) -> None:
    subprocess.run(
        ["supervisorctl", "-c", SUPERVISOR_CONF, *args],
        check=False,
        timeout=30,
    )


def log_noaa_signal(name: str, detail: str, image: str, max_elevation: float | None = None) -> None:
    from satellite_log import log_satellite_signal

    log_satellite_signal(name, detail, decoder="apt", max_elevation=max_elevation)
    write_state(
        {
            "mode": "ADS-B",
            "active": False,
            "lastCapture": {
                "name": name,
                "detail": detail,
                "image": image,
                "ts": int(time.time()),
            },
            "nextPass": None,
        }
    )


def record_pass(pass_info) -> bool:
    if pass_info.decoder != "apt" or not pass_info.apt_sat:
        log.info(
            "Pass %s uses %s — auto-decode not supported yet (WAV only skipped)",
            pass_info.name,
            pass_info.decoder,
        )
        write_state(
            {
                "mode": "ADS-B",
                "active": False,
                "nextPass": pass_info.to_dict(),
                "message": f"{pass_info.name} pass — LRPT decode coming soon",
            }
        )
        return False

    NOAA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    wav = NOAA_DIR / f"{pass_info.apt_sat}_{stamp}.wav"
    png = NOAA_DIR / f"{pass_info.apt_sat}_{stamp}.png"
    freq = pass_info.freq_mhz
    duration = min(pass_info.duration_sec + 60, 900)

    write_state(
        {
            "mode": "NOAA_RECORD",
            "active": True,
            "pass": pass_info.to_dict(),
            "message": f"Recording {pass_info.name} @ {freq} MHz — dipole ~54 cm",
        }
    )

    log.info("Stopping dump1090 for NOAA pass %s", pass_info.name)
    supervisorctl("stop", "dump1090")
    time.sleep(2)

    cmd = [
        "timeout",
        str(duration),
        "rtl_fm",
        "-d",
        "0",
        "-f",
        f"{freq}M",
        "-M",
        "fm",
        "-s",
        "48k",
        "-g",
        "40",
        "-E",
        "wav",
        str(wav),
    ]
    log.info("Recording: %s", " ".join(cmd))
    rec = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 30)
    if rec.returncode not in (0, 124) or not wav.exists() or wav.stat().st_size < 50000:
        log.error("Recording failed rc=%s stderr=%s", rec.returncode, rec.stderr[-500:])
        supervisorctl("start", "dump1090")
        return False

    write_state(
        {
            "mode": "NOAA_DECODE",
            "active": True,
            "pass": pass_info.to_dict(),
            "message": f"Decoding {pass_info.name}…",
        }
    )

    dec = subprocess.run(
        [
            NOAA_APT,
            str(wav),
            "-o",
            str(png),
            "-q",
            "-p",
            "fast",
            "-s",
            pass_info.apt_sat,
            "-t",
            pass_info.aos.strftime("%Y-%m-%dT%H:%M:%SZ"),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    supervisorctl("start", "dump1090")

    if dec.returncode != 0 or not png.exists():
        log.error("noaa-apt failed: %s", dec.stderr[-800:])
        return False

    detail = f"APT image {png.name} maxEl {pass_info.max_elevation:.0f}°"
    log_noaa_signal(pass_info.name, detail, str(png), pass_info.max_elevation)
    log.info("NOAA capture OK: %s", png)
    return True


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    if not SCHEDULER_ENABLED:
        log.info("Scheduler disabled")
        return

    log.info("Satellite scheduler started (Meteor-M + legacy NOAA TLE)")
    captured: set[str] = set()

    while True:
        try:
            lat, lon = read_position()
            nxt = next_pass(lat, lon, MIN_ELEV)
            upcoming = [p.to_dict() for p in predict_passes(lat, lon, hours=24, min_el=MIN_ELEV)[:8]]
            base_state = {
                "mode": "ADS-B",
                "active": False,
                "observerLat": lat,
                "observerLng": lon,
                "upcoming": upcoming,
            }

            if nxt is None:
                msg = None
                if not upcoming:
                    msg = (
                        "No satellite passes in range. NOAA 15/18/19 were decommissioned in 2025; "
                        "expect Meteor-M passes when TLE refresh works."
                    )
                write_state({**base_state, "nextPass": None, "message": msg})
                time.sleep(60)
                continue

            now = datetime.now(timezone.utc)
            key = f"{nxt.name}_{nxt.aos.isoformat()}"
            mins_to_aos = (nxt.aos - now).total_seconds() / 60

            write_state(
                {
                    **base_state,
                    "nextPass": nxt.to_dict(),
                    "notify": mins_to_aos <= NOTIFY_MIN,
                    "message": (
                        f"{nxt.name} in {int(mins_to_aos)} min @ {nxt.freq_mhz} MHz — dipole ~54 cm"
                        if mins_to_aos <= NOTIFY_MIN
                        else None
                    ),
                }
            )

            if key in captured:
                time.sleep(30)
                continue

            if now >= nxt.aos - timedelta(seconds=RECORD_LEAD_SEC) and now <= nxt.los:
                ok = record_pass(nxt)
                captured.add(key)
                if not ok:
                    write_state(
                        {
                            "mode": "ADS-B",
                            "active": False,
                            "nextPass": nxt.to_dict(),
                            "lastError": "NOAA capture failed",
                        }
                    )
            time.sleep(15)
        except Exception as e:
            log.exception("scheduler loop: %s", e)
            time.sleep(60)


if __name__ == "__main__":
    main()
