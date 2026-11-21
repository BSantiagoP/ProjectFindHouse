from enum import StrEnum

from pydantic import BaseModel, Field


class CommuteMode(StrEnum):
    TRANSIT = "transit"
    DRIVE = "drive"


class CommuteDestination(BaseModel):
    label: str
    address: str
    mode: CommuteMode = CommuteMode.TRANSIT
    lat: float | None = None
    lon: float | None = None


class FinanceScenarioName(StrEnum):
    FHA_3_5 = "fha_3_5"
    CONVENTIONAL_5 = "conventional_5"
    CONVENTIONAL_20 = "conventional_20"


class OwnerUnit(StrEnum):
    LARGEST = "largest"  # owner occupies the unit with the most bedrooms
    SMALLEST = "smallest"


class TownCommute(BaseModel):
    minutes: int = Field(ge=5, le=240)  # stop/station -> 7 WTC, including transfers and typical waits
    route: str
    access: str = "bus"  # "bus" -> walk to nearest bus stop; "rail" -> walk to nearest rail station


DEFAULT_TOWN_COMMUTES = {
    "Lyndhurst": TownCommute(minutes=45, route="tren NJ Transit Lyndhurst → Hoboken, PATH → WTC", access="rail"),
    "Cliffside Park": TownCommute(minutes=60, route="autobús NJ Transit 156 → Port Authority, tren E → WTC (alternativa: ferry desde Edgewater)"),
    "Fairview": TownCommute(minutes=65, route="autobús NJ Transit 156/159 → Port Authority, tren E → WTC"),
    "Elmwood Park": TownCommute(minutes=75, route="autobús NJ Transit 160/144 → Port Authority, tren E → WTC"),
    "Saddle Brook": TownCommute(minutes=75, route="autobús NJ Transit por la Ruta 46 → Port Authority, tren E → WTC"),
}


class ScoringWeights(BaseModel):
    affordability: int = 30
    location_commute: int = 25
    condition: int = 20
    rental_potential: int = 15
    preferences: int = 10


class SearchPreferences(BaseModel):
    state: str = "NJ"
    towns: list[str] = Field(
        min_length=1,
        default_factory=lambda: [
            "Cliffside Park",
            "Lyndhurst",
            "Fairview",
            "Elmwood Park",
            "Saddle Brook",
        ]
    )
    max_price: int = Field(default=900_000, ge=100_000, le=5_000_000)
    listing_window_days: int = 7
    min_units: int = 2
    max_units: int = 4
    commute_destinations: list[CommuteDestination] = Field(
        default_factory=lambda: [
            CommuteDestination(
                label="7 WTC",
                address="7 World Trade Center, 250 Greenwich St, New York, NY 10007",
            ),
            # Added 2026-11-20; coordinates from the US Census geocoder.
            CommuteDestination(
                label="576 Bergen Blvd",
                address="576 Bergen Blvd, Ridgefield, NJ 07657",
                mode=CommuteMode.DRIVE,
                lat=40.827193095372,
                lon=-73.995480873132,
            ),
        ]
    )
    primary_scenario: FinanceScenarioName = FinanceScenarioName.FHA_3_5
    # None means use the weekly FRED rate (later milestone).
    rate_override: float | None = None
    preference_keywords: list[str] = Field(
        default_factory=lambda: ["finished basement with bathroom", "backyard", "outdoor space"]
    )
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    max_recommendations: int = 5

    # Commute (until Google Routes is available): minutes from the town's NYC-bound
    # stop/station to 7 WTC at morning rush, researched 2026-11-20. Editable.
    town_commutes: dict[str, TownCommute] = Field(default_factory=lambda: dict(DEFAULT_TOWN_COMMUTES))

    # Rent: owner always lives in one unit and rents the others.
    owner_unit: OwnerUnit = OwnerUnit.LARGEST

    # Finance assumptions (estimates; editable)
    annual_insurance: int = 2_400
    annual_maintenance_pct: float = 0.01
    fha_rate_adjustment: float = -0.0025  # FHA rate relative to the conventional 30-yr average
    # Monthly all-in housing cost (after rent) you'd be comfortable with; drives affordability.
    target_monthly_cost: int | None = Field(default=None, ge=500, le=50_000)
