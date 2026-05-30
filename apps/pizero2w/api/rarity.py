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
INTERCEPT_SQUAWKS = {"7777"}

NATO_CALLSIGN_PREFIXES = ("NATO", "MAGIC")

MILITARY_OPERATOR_WORDS = (
    "AIR FORCE",
    "LUFTWAFFE",
    "NATO",
    "MILITARY",
    "ARMY",
    "NAVY",
    "MARINES",
    "BUNDESWEHR",
)

LEGEND_AIRCRAFT_TYPES = {
    "CONC",
    "AN225",
}

LEGEND_REGISTRATIONS = {
    "N140SC",
}

EPIC_AIRCRAFT_TYPES = {
    "E3CF",
    "E3TF",
    "E3",
    "R135",
    "E6",
    "B52",
    "B1",
    "B2",
    "K35R",
    "K35E",
    "P8",
    "U2",
    "A400",
    "C30J",
    "C17",
    "F15",
    "F16",
    "F18",
    "F22",
    "F35",
    "A10",
    "H64",
    "V22",
}

RARE_AIRCRAFT_TYPES = {
    "A388",
    "B748",
    "AN124",
    "AN12",
    "IL76",
    "MD11",
    "L101",
    "A342",
    "A345",
    "A346",
    "A3ST",
    "BLCF",
    "DC3",
    "DC3S",
    "DC3T",
    "JU52",
    "B17",
    "SPIT",
    "P51",
    "P51D",
}

GOVERNMENT_OPERATOR_WORDS = (
    "GOVERNMENT",
    "POLICE",
    "BUNDESPOLIZEI",
    "STATE OF",
    "MINISTRY",
)

GA_AIRCRAFT_TYPES = {
    "C172",
    "C152",
    "C182",
    "P28A",
    "P28B",
    "DV20",
    "DA40",
    "DA42",
    "GLID",
    "DG80",
    "ASK21",
    "TB20",
    "SR22",
    "M20P",
}

UNCOMMON_AIRCRAFT_TYPES = {
    "GLF6",
    "GLEX",
    "GLF5",
    "GLF4",
    "CL60",
    "C56X",
    "C550",
    "C680",
    "C750",
    "LJ45",
    "LJ60",
    "LJ75",
    "E55P",
    "B752",
    "B722",
    "MD80",
    "MD81",
    "MD82",
    "MD83",
    "MD88",
    "MD90",
}

SATELLITE_RARITY = {
    "METEOR-M 2": "UNCOMMON",
    "METEOR-M2 3": "UNCOMMON",
    "METEOR-M2 4": "UNCOMMON",
    "NOAA 15": "COMMON",
    "NOAA 18": "COMMON",
    "NOAA 19": "COMMON",
    "ISS": "COMMON",
    "TIANGONG": "UNCOMMON",
    "HUBBLE": "UNCOMMON",
    "X-37B": "EPIC",
    "USA": "EPIC",
}


def _nato_callsign(callsign: str) -> bool:
    for prefix in NATO_CALLSIGN_PREFIXES:
        if callsign.startswith(prefix):
            return True
    return False


def classify_rarity(ac: dict) -> str:
    callsign = ac.get("flight", "").strip().upper()
    squawk = str(ac.get("squawk", "")).strip()
    hex_id = ac.get("hex", "")

    if squawk in EMERGENCY_SQUAWKS or squawk in INTERCEPT_SQUAWKS:
        return "LEGEND"

    if not hex_id and not callsign:
        return "LEGEND"

    if not hex_id:
        return "EPIC"

    for prefix in MILITARY_PREFIXES:
        if callsign.startswith(prefix):
            return "EPIC"

    if _nato_callsign(callsign):
        return "EPIC"

    if not callsign:
        return "COMMON"

    if callsign.startswith("N") and 4 <= len(callsign) <= 6:
        return "UNCOMMON"

    return "COMMON"


def classify_rarity_decoded(info: dict) -> str:
    registration = (info.get("registration") or "").upper()
    operator = (info.get("operator") or "").upper()
    ac_type = (info.get("aircraftType") or "").upper()

    if ac_type in LEGEND_AIRCRAFT_TYPES or registration in LEGEND_REGISTRATIONS:
        return "LEGEND"

    if ac_type in EPIC_AIRCRAFT_TYPES:
        return "EPIC"

    for prefix in MILITARY_PREFIXES:
        if registration.startswith(prefix):
            return "EPIC"

    for word in MILITARY_OPERATOR_WORDS:
        if word in operator:
            return "EPIC"

    if ac_type in RARE_AIRCRAFT_TYPES:
        return "RARE"

    if registration.startswith("F-WW"):
        return "RARE"

    for word in GOVERNMENT_OPERATOR_WORDS:
        if word in operator:
            return "RARE"

    if ac_type in UNCOMMON_AIRCRAFT_TYPES:
        return "UNCOMMON"

    if ac_type in GA_AIRCRAFT_TYPES:
        return "UNCOMMON"

    if registration.startswith("N") and 4 <= len(registration) <= 6:
        return "UNCOMMON"

    return "COMMON"


def classify_satellite_rarity(
    name: str,
    decoder: str = "lrpt",
    max_elevation: float | None = None,
) -> str:
    upper = (name or "").upper()
    for key, tier in SATELLITE_RARITY.items():
        if key.upper() in upper:
            return tier
    if upper.startswith("USA-"):
        return "EPIC"
    if decoder == "apt":
        return "COMMON"
    if decoder == "lrpt":
        return "UNCOMMON"
    if max_elevation is not None and max_elevation >= 75:
        return "RARE"
    return "UNCOMMON"
