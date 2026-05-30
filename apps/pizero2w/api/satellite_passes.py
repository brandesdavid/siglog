import logging
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from skyfield.api import Loader, wgs84

log = logging.getLogger("siglog.satellite_passes")

TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle"
TLE_CACHE = Path("/app/data/weather.tle")
TLE_MAX_AGE = 86400 * 2


@dataclass(frozen=True)
class AptTarget:
    label: str
    tle_names: tuple[str, ...]
    freq_mhz: float
    apt_sat: Optional[str]
    decoder: str


TARGETS: tuple[AptTarget, ...] = (
    AptTarget(
        "METEOR-M 2",
        ("METEOR-M 2",),
        137.100,
        None,
        "lrpt",
    ),
    AptTarget(
        "METEOR-M2 3",
        ("METEOR-M2 3",),
        137.900,
        None,
        "lrpt",
    ),
    AptTarget(
        "METEOR-M2 4",
        ("METEOR-M2 4",),
        137.900,
        None,
        "lrpt",
    ),
    AptTarget(
        "NOAA 19",
        ("NOAA 19",),
        137.1,
        "noaa_19",
        "apt",
    ),
    AptTarget(
        "NOAA 18",
        ("NOAA 18",),
        137.9125,
        "noaa_18",
        "apt",
    ),
    AptTarget(
        "NOAA 15",
        ("NOAA 15",),
        137.62,
        "noaa_15",
        "apt",
    ),
)


@dataclass
class Pass:
    name: str
    aos: datetime
    los: datetime
    max_elevation: float
    freq_mhz: float
    apt_sat: Optional[str]
    decoder: str

    @property
    def duration_sec(self) -> int:
        return int((self.los - self.aos).total_seconds())

    def to_dict(self) -> dict:
        now = datetime.now(timezone.utc)
        start_in = max(0, int((self.aos - now).total_seconds() // 60))
        return {
            "name": self.name,
            "aos": self.aos.isoformat(),
            "los": self.los.isoformat(),
            "maxElevation": round(self.max_elevation, 1),
            "freqMhz": self.freq_mhz,
            "antennaCm": 54,
            "startInMin": start_in,
            "aptSat": self.apt_sat,
            "decoder": self.decoder,
        }


def _fetch_tle() -> None:
    TLE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(TLE_URL, headers={"User-Agent": "siglog/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        TLE_CACHE.write_bytes(resp.read())


def _load_satellites():
    if not TLE_CACHE.exists() or time.time() - TLE_CACHE.stat().st_mtime > TLE_MAX_AGE:
        try:
            _fetch_tle()
            log.info("Downloaded TLE cache from Celestrak weather group")
        except OSError as e:
            if not TLE_CACHE.exists():
                raise
            log.warning("TLE refresh failed, using cache: %s", e)
    load = Loader("/app/data/skyfield")
    ts = load.timescale()
    by_name = {s.name.strip(): s for s in load.tle_file(str(TLE_CACHE))}
    return ts, by_name


def _resolve_target(by_name: dict, target: AptTarget):
    for tle_name in target.tle_names:
        if tle_name in by_name:
            return by_name[tle_name]
    for name, sat in by_name.items():
        if target.label.upper() in name.upper():
            return sat
    return None


def predict_passes(lat: float, lon: float, hours: float = 36, min_el: float = 15.0) -> list[Pass]:
    ts, by_name = _load_satellites()
    observer = wgs84.latlon(lat, lon)
    t0 = ts.now()
    t1 = ts.utc(t0.utc_datetime() + timedelta(hours=hours))
    passes: list[Pass] = []
    found_targets = 0

    for target in TARGETS:
        sat = _resolve_target(by_name, target)
        if sat is None:
            continue
        found_targets += 1
        times, events = sat.find_events(observer, t0, t1, altitude_degrees=min_el)
        i = 0
        while i < len(events):
            if events[i] != 0:
                i += 1
                continue
            aos_t = times[i]
            max_el = 0.0
            los_t = aos_t
            j = i + 1
            while j < len(events):
                if events[j] == 1:
                    el, _, _ = (sat - observer).at(times[j]).altaz()
                    max_el = float(el.degrees)
                elif events[j] == 2:
                    los_t = times[j]
                    j += 1
                    break
                j += 1
            aos_dt = aos_t.utc_datetime().replace(tzinfo=timezone.utc)
            los_dt = los_t.utc_datetime().replace(tzinfo=timezone.utc)
            if los_dt > datetime.now(timezone.utc):
                passes.append(
                    Pass(
                        name=target.label,
                        aos=aos_dt,
                        los=los_dt,
                        max_elevation=max_el,
                        freq_mhz=target.freq_mhz,
                        apt_sat=target.apt_sat,
                        decoder=target.decoder,
                    )
                )
            i = j + 1

    if found_targets == 0:
        log.warning(
            "No APT/LRPT satellites in TLE cache. NOAA 15/18/19 were decommissioned in 2025."
        )
    passes.sort(key=lambda p: p.aos)
    return passes


def next_pass(lat: float, lon: float, min_el: float = 15.0) -> Optional[Pass]:
    now = datetime.now(timezone.utc)
    for p in predict_passes(lat, lon, hours=48, min_el=min_el):
        if p.los > now:
            return p
    return None
