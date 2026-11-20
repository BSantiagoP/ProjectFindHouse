from app.models.property import Property
from app.services.address import normalize_street


def address_key(prop: Property) -> tuple[str, str, str] | None:
    """Normalized (street, unit, zip). None when the address is too incomplete to trust."""
    a = prop.address
    if not a.street or not a.zip_code:
        return None
    return (normalize_street(a.street), (a.unit or "").upper(), a.zip_code)


def deduplicate(props: list[Property]) -> list[Property]:
    """Collapse duplicates by (provider, listing id) and by normalized address.

    When duplicates collide, keep the record with detail data, else the first seen.
    """
    by_key: dict[tuple[str, str], Property] = {}
    for p in props:
        existing = by_key.get(p.key)
        if existing is None or (p.details_fetched and not existing.details_fetched):
            by_key[p.key] = p

    by_address: dict[tuple[str, str, str], Property] = {}
    result: list[Property] = []
    for p in by_key.values():
        key = address_key(p)
        if key is None:
            result.append(p)
            continue
        existing = by_address.get(key)
        if existing is None:
            by_address[key] = p
            result.append(p)
        elif p.details_fetched and not existing.details_fetched:
            result[result.index(existing)] = p
            by_address[key] = p
    return result
