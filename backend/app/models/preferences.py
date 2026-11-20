from enum import StrEnum

from pydantic import BaseModel, Field


class CommuteMode(StrEnum):
    TRANSIT = "transit"
    DRIVE = "drive"


class CommuteDestination(BaseModel):
    label: str
    address: str
    mode: CommuteMode = CommuteMode.TRANSIT


class FinanceScenarioName(StrEnum):
    FHA_3_5 = "fha_3_5"
    CONVENTIONAL_5 = "conventional_5"
    CONVENTIONAL_20 = "conventional_20"


class ScoringWeights(BaseModel):
    affordability: int = 30
    location_commute: int = 25
    condition: int = 20
    rental_potential: int = 15
    preferences: int = 10


class SearchPreferences(BaseModel):
    state: str = "NJ"
    towns: list[str] = Field(
        default_factory=lambda: [
            "Cliffside Park",
            "Lyndhurst",
            "Fairview",
            "Elmwood Park",
            "Saddle Brook",
        ]
    )
    max_price: int = 900_000
    listing_window_days: int = 7
    min_units: int = 2
    max_units: int = 4
    commute_destinations: list[CommuteDestination] = Field(
        default_factory=lambda: [
            CommuteDestination(
                label="7 WTC",
                address="7 World Trade Center, 250 Greenwich St, New York, NY 10007",
            )
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
