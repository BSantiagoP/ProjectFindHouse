"""Analysis models: LLM output contracts and cached enrichment results stored on a Property."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


# ---- LLM structured output (description analysis) -------------------------------

class QuotedFinding(BaseModel):
    state: Literal["present", "absent", "unknown"]
    quote: str | None = Field(
        default=None,
        description="Exact, verbatim substring of the listing text supporting the state. Required unless unknown.",
    )


class UnitLayout(BaseModel):
    label: str = Field(description="How the listing names the unit, e.g. 'first floor', 'unit 2'")
    bedrooms: int | None = None
    bathrooms: float | None = None
    quote: str = Field(description="Exact, verbatim substring of the listing text describing this unit")


class Condition(StrEnum):
    MOVE_IN_READY = "move_in_ready"
    UPDATED = "updated"
    DATED = "dated"
    NEEDS_WORK = "needs_work"
    UNKNOWN = "unknown"


class DescriptionAnalysis(BaseModel):
    """What the model must return. Every non-unknown claim carries a verbatim quote."""

    units: list[UnitLayout] = Field(description="One entry per dwelling unit, only if the text describes units")
    garage: QuotedFinding
    driveway: QuotedFinding = Field(description="Driveway or private off-street parking")
    laundry: QuotedFinding = Field(description="Laundry in unit/building, or washer/dryer hookups")
    finished_basement: QuotedFinding = Field(description="Present only if FULLY finished; partially finished is unknown")
    basement_bathroom: QuotedFinding = Field(description="A bathroom (full or half) located in the basement")
    outdoor_space: QuotedFinding = Field(description="Yard, deck, patio, or other private outdoor space")
    separate_utilities: QuotedFinding
    tenant_occupied: QuotedFinding
    condition: Condition
    condition_quote: str | None = None
    red_flags: list[str] = Field(
        description="Verbatim quotes of concerns: as-is, cash only, foreclosure, fire/water damage, illegal unit, etc."
    )
    summary: str = Field(description="One neutral sentence summarizing the property, no claims beyond the text")


# ---- Cached enrichment stored on Property -------------------------------------------

class LLMAnalysis(BaseModel):
    """Validated description analysis (quotes checked against the source text)."""

    units: list[UnitLayout] = Field(default_factory=list)
    separate_utilities: QuotedFinding | None = None
    tenant_occupied: QuotedFinding | None = None
    condition: Condition = Condition.UNKNOWN
    condition_quote: str | None = None
    red_flags: list[str] = Field(default_factory=list)
    summary: str | None = None
    rejected_claims: list[str] = Field(default_factory=list)  # claims dropped for failing quote validation
    model: str
    prompt_version: str
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UnitRent(BaseModel):
    label: str
    bedrooms: int | None
    bathrooms: float | None
    rent: int | None
    range_low: int | None = None
    range_high: int | None = None


class RentEstimate(BaseModel):
    status: Literal["estimated", "not_estimated"]
    reason: str | None = None  # why not estimated (cap reached, no unit layout, error)
    owner_unit: str | None = None  # unit assumed owner-occupied
    rental_units: list[UnitRent] = Field(default_factory=list)
    monthly_rent_total: int | None = None
    source: str = "rentcast"
    estimated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CommuteEstimate(BaseModel):
    destination: str
    town_minutes: int  # stop/station to destination, from the configured town table
    route: str
    nearest_stop: str | None = None
    walk_meters: int | None = None
    walk_minutes: int | None = None
    total_minutes: int | None = None
    source: str = "town_table+njt_gtfs"
