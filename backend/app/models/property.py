"""Normalized, provider-independent property contract."""

from datetime import date, datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl

from app.models.analysis import CommuteEstimate, LLMAnalysis, RentEstimate


class FeatureState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class FeatureSource(StrEnum):
    PROVIDER = "provider"  # structured provider field
    DESCRIPTION = "description"  # listing text
    PHOTOS = "photos"  # vision analysis (later milestone)
    MANUAL = "manual"  # user-verified


class Feature(BaseModel):
    """A property feature that may be unknown. Unknown is never treated as present or absent."""

    state: FeatureState = FeatureState.UNKNOWN
    source: FeatureSource | None = None
    evidence: str | None = None  # quoted text the state was derived from

    @property
    def is_present(self) -> bool:
        return self.state is FeatureState.PRESENT

    @property
    def is_absent(self) -> bool:
        return self.state is FeatureState.ABSENT


class PropertyFeatures(BaseModel):
    garage: Feature = Field(default_factory=Feature)
    driveway: Feature = Field(default_factory=Feature)  # includes private off-street parking
    laundry: Feature = Field(default_factory=Feature)  # in-unit, in-building, or hookups
    finished_basement: Feature = Field(default_factory=Feature)  # fully finished
    basement_bathroom: Feature = Field(default_factory=Feature)
    outdoor_space: Feature = Field(default_factory=Feature)  # yard, deck, patio


class PropertyType(StrEnum):
    SINGLE_FAMILY = "single_family"
    MULTI_FAMILY = "multi_family"
    CONDO = "condo"
    TOWNHOUSE = "townhouse"
    LAND = "land"
    OTHER = "other"
    UNKNOWN = "unknown"


class Address(BaseModel):
    raw: str
    street: str | None = None
    unit: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None


class Property(BaseModel):
    provider: str
    external_id: str
    source_url: HttpUrl
    address: Address
    town: str | None  # normalized town name if it matches a configured town
    price: int | None
    property_type: PropertyType = PropertyType.UNKNOWN
    units: int | None = None
    units_evidence: str | None = None
    beds: float | None = None
    baths: float | None = None
    living_area_sqft: int | None = None
    year_built: int | None = None
    listed_date: date | None = None
    days_on_market: int | None = None
    status: str | None = None
    description: str | None = None
    highlights: list[str] = Field(default_factory=list)  # short listing bullet points
    photo_urls: list[str] = Field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None
    provider_estimated_rent: int | None = None  # provider estimate; RentCast is the scoring source
    annual_tax: int | None = None
    features: PropertyFeatures = Field(default_factory=PropertyFeatures)
    details_fetched: bool = False
    # Cached analysis (computed once per property, persisted, reused on later runs)
    llm_analysis: LLMAnalysis | None = None
    rent_estimate: RentEstimate | None = None
    commute: CommuteEstimate | None = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def key(self) -> tuple[str, str]:
        return (self.provider, self.external_id)
