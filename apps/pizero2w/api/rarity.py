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

RARE_AIRCRAFT_TYPES = {
    "A388",
    "B748",
    "AN124",
    "AN225",
    "C17",
    "MD11",
    "L101",
    "CONC",
    "A342",
    "A345",
    "A346",
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
        return "COMMON"

    if callsign.startswith("N") and 4 <= len(callsign) <= 6:
        return "UNCOMMON"

    return "COMMON"


def classify_rarity_decoded(info: dict) -> str:
    registration = (info.get("registration") or "").upper()
    operator = (info.get("operator") or "").upper()
    ac_type = (info.get("aircraftType") or "").upper()

    for prefix in MILITARY_PREFIXES:
        if registration.startswith(prefix):
            return "EPIC"

    for word in MILITARY_OPERATOR_WORDS:
        if word in operator:
            return "EPIC"

    if ac_type in RARE_AIRCRAFT_TYPES:
        return "RARE"

    for word in GOVERNMENT_OPERATOR_WORDS:
        if word in operator:
            return "RARE"

    if ac_type in GA_AIRCRAFT_TYPES:
        return "UNCOMMON"

    if registration.startswith("N") and 4 <= len(registration) <= 6:
        return "UNCOMMON"

    return "COMMON"
