"""Hard filters. Each property ends up ELIGIBLE, NEEDS_VERIFICATION, or REJECTED.

Unknown required features never pass silently: they route to NEEDS_VERIFICATION so
photo analysis or a human can resolve them. Only ELIGIBLE properties may be texted.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

from app.models.preferences import SearchPreferences
from app.models.property import FeatureState, Property, PropertyType


class FilterStatus(StrEnum):
    ELIGIBLE = "eligible"
    NEEDS_VERIFICATION = "needs_verification"
    REJECTED = "rejected"


@dataclass
class FilterResult:
    status: FilterStatus
    rejections: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)


def apply_hard_filters(prop: Property, prefs: SearchPreferences, today: date) -> FilterResult:
    rejections: list[str] = []
    unverified: list[str] = []
    f = prop.features

    # Location
    if prop.town is None:
        rejections.append(f"Fuera de los pueblos elegidos ({prop.address.city or 'ciudad desconocida'})")

    # Price
    if prop.price is None:
        unverified.append("precio")
    elif prop.price > prefs.max_price:
        rejections.append(f"Precio ${prop.price:,} supera el máximo de ${prefs.max_price:,}")

    # Recency
    if prop.listed_date is not None and prop.listed_date < today - timedelta(days=prefs.listing_window_days):
        rejections.append(f"Publicada el {prop.listed_date.isoformat()}, hace más de {prefs.listing_window_days} días")

    # Property type and units
    match prop.property_type:
        case PropertyType.MULTI_FAMILY:
            if prop.units is None:
                unverified.append("número de unidades")
            elif not prefs.min_units <= prop.units <= prefs.max_units:
                rejections.append(
                    f"{prop.units} unidades está fuera del rango {prefs.min_units}-{prefs.max_units}"
                )
        case PropertyType.SINGLE_FAMILY:
            for name, label in (("finished_basement", "sótano completamente terminado"), ("basement_bathroom", "baño en el sótano")):
                state = getattr(f, name).state
                if state is FeatureState.ABSENT:
                    rejections.append(f"Unifamiliar sin {label}")
                elif state is FeatureState.UNKNOWN:
                    unverified.append(label)
        case PropertyType.UNKNOWN:
            unverified.append("tipo de propiedad")
        case other:
            rejections.append(f"Tipo de propiedad {other.value}: no es multifamiliar ni unifamiliar")

    # Parking: garage or driveway
    if f.garage.is_present or f.driveway.is_present:
        pass
    elif f.garage.is_absent and f.driveway.is_absent:
        rejections.append("Sin garaje ni entrada para autos")
    else:
        unverified.append("garaje o entrada para autos")

    # Laundry
    if f.laundry.is_absent:
        rejections.append("Sin lavandería")
    elif not f.laundry.is_present:
        unverified.append("lavandería")

    if rejections:
        return FilterResult(FilterStatus.REJECTED, rejections, unverified)
    if unverified:
        return FilterResult(FilterStatus.NEEDS_VERIFICATION, rejections, unverified)
    return FilterResult(FilterStatus.ELIGIBLE)


def passes_prefilter(prop: Property, prefs: SearchPreferences) -> bool:
    """Cheap checks before spending credits on a details request."""
    if prop.town is None:
        return False
    if prop.price is not None and prop.price > prefs.max_price:
        return False
    return prop.property_type in (PropertyType.MULTI_FAMILY, PropertyType.SINGLE_FAMILY, PropertyType.UNKNOWN)
