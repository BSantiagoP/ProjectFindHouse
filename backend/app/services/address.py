import re

from app.models.property import Address

# "#" is not a word character, so it cannot sit behind \b; keep it as its own alternative.
_UNIT_RE = re.compile(r"\s*(?:,\s*)?(?:\b(?:APT|UNIT|STE|SUITE)\b\.?\s*#?|#)\s*([A-Z0-9-]+)\s*$", re.I)
_STATE_ZIP_RE = re.compile(r"^\s*([A-Z]{2})\s*(\d{5})?(?:-\d{4})?\s*$", re.I)

_SUFFIXES = {
    "AVENUE": "AVE",
    "STREET": "ST",
    "ROAD": "RD",
    "DRIVE": "DR",
    "BOULEVARD": "BLVD",
    "PLACE": "PL",
    "COURT": "CT",
    "LANE": "LN",
    "TERRACE": "TER",
    "PARKWAY": "PKWY",
    "HIGHWAY": "HWY",
    "CIRCLE": "CIR",
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
}


def parse_address(raw: str) -> Address:
    """Parse 'street [unit], city, ST zip' strings. Unparseable parts stay None."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    street = city = state = zip_code = unit = None
    if parts:
        street = parts[0]
        if m := _UNIT_RE.search(street):
            unit = m.group(1).upper()
            street = street[: m.start()].strip()
    if len(parts) >= 3:
        city = parts[-2]
        if m := _STATE_ZIP_RE.match(parts[-1]):
            state, zip_code = m.group(1).upper(), m.group(2)
        # a unit given as its own comma part: "12 Main St, Apt 2, City, NJ 07071"
        if len(parts) >= 4 and unit is None and (m := _UNIT_RE.search(parts[1])):
            unit = m.group(1).upper()
    elif len(parts) == 2:
        if m := _STATE_ZIP_RE.match(parts[1]):
            state, zip_code = m.group(1).upper(), m.group(2)
        else:
            city = parts[1]
    return Address(raw=raw, street=street, unit=unit, city=city, state=state, zip_code=zip_code)


def normalize_street(street: str) -> str:
    tokens = re.sub(r"[^\w\s]", " ", street.upper()).split()
    return " ".join(_SUFFIXES.get(t, t) for t in tokens)


def normalize_town(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())
