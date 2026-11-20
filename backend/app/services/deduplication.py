from app.models.property import Property
from app.services.address import normalize_street


def address_key(prop: Property) -> tuple[str, str, str] | None:
    """Normalized (street, unit, zip). None when the address is too incomplete to trust."""
    a = prop.address
    if not a.street or not a.zip_code:
        return None
    return (normalize_street(a.street), (a.unit or "").upper(), a.zip_code)


def building_price_key(prop: Property) -> tuple[str, str, int] | None:
    """Same building and same asking price, ignoring unit.

    Live data had one multifamily listed twice under different Zillow IDs:
    "188 N 6th St" and "188 N 6Th St #2", same price. For whole-building listings, a
    unit suffix with an identical price is the same sale.
    """
    a = prop.address
    if not a.street or not a.zip_code or prop.price is None:
        return None
    return (normalize_street(a.street), a.zip_code, prop.price)


def _prefer(new: Property, old: Property) -> bool:
    """True if `new` should replace `old`: detailed beats undetailed, then no-unit beats unit."""
    if new.details_fetched != old.details_fetched:
        return new.details_fetched
    return not new.address.unit and bool(old.address.unit)


def _collapse(props: list[Property], key_fn) -> list[Property]:
    kept: dict[object, int] = {}
    result: list[Property] = []
    for p in props:
        key = key_fn(p)
        if key is None:
            result.append(p)
            continue
        if key not in kept:
            kept[key] = len(result)
            result.append(p)
        elif _prefer(p, result[kept[key]]):
            result[kept[key]] = p
    return result


def _collapse_whole_building(props: list[Property]) -> list[Property]:
    """Merge a unit-suffixed listing into a no-unit listing of the same building and price.

    Two different explicit units (e.g. two condos at one price) are never merged.
    """
    whole: dict[tuple, Property] = {
        k: p for p in props if not p.address.unit and (k := building_price_key(p)) is not None
    }
    result: list[Property] = []
    for p in props:
        key = building_price_key(p)
        if p.address.unit and key in whole:
            base = whole[key]
            if p.details_fetched and not base.details_fetched:
                whole[key] = p  # keep the richer record in the base's position
            continue
        result.append(p)
    return [whole.get(building_price_key(p), p) if not p.address.unit else p for p in result]


def deduplicate(props: list[Property]) -> list[Property]:
    """Collapse duplicates by listing id, then normalized address+unit, then whole-building+price."""
    result = _collapse(props, lambda p: p.key)
    result = _collapse(result, address_key)
    return _collapse_whole_building(result)
