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


class DriveEstimate(BaseModel):
    destination: str  # label, e.g. "576 Bergen Blvd"
    address: str
    minutes: int | None  # free-flow driving time (no live traffic)
    miles: float | None
    source: str = "osrm"
    error: str | None = None


class CommuteEstimate(BaseModel):
    destination: str
    town_minutes: int  # stop/station to destination, from the configured town table
    route: str
    nearest_stop: str | None = None
    walk_meters: int | None = None
    walk_minutes: int | None = None
    total_minutes: int | None = None
    source: str = "town_table+njt_gtfs:es"  # bump recomputes stored commutes (free, local)


# ---- Photo analysis -------------------------------------------------------------------

class Room(StrEnum):
    EXTERIOR_FRONT = "exterior_front"
    EXTERIOR_BACK_YARD = "exterior_back_yard"
    GARAGE = "garage"
    DRIVEWAY = "driveway"
    KITCHEN = "kitchen"
    BATHROOM = "bathroom"
    BEDROOM = "bedroom"
    LIVING_DINING = "living_dining"
    BASEMENT = "basement"
    LAUNDRY = "laundry"
    OTHER = "other"


class PhotoLabel(BaseModel):
    index: int = Field(description="The photo number exactly as given in the input")
    rooms: list[Room] = Field(description="Areas visible; use basement for any below-grade space")


class PhotoTriage(BaseModel):
    photos: list[PhotoLabel]


class PhotoFinding(BaseModel):
    state: Literal["present", "unknown"] = Field(description="Photos can confirm presence only; never 'absent'")
    photo_numbers: list[int] = Field(default_factory=list, description="Photo numbers that clearly show it")
    observation: str | None = Field(default=None, description="What is visible, in a few words")
    confidence: Literal["high", "medium", "low"] = "low"


class PhotoFindings(BaseModel):
    garage: PhotoFinding
    driveway: PhotoFinding
    laundry: PhotoFinding = Field(description="Washer/dryer, laundry room or visible hookups")
    finished_basement: PhotoFinding = Field(description="Below-grade space with finished walls, floors and ceiling")
    basement_bathroom: PhotoFinding = Field(description="A bathroom that is clearly in the basement")
    outdoor_space: PhotoFinding
    condition: Condition
    condition_photo_numbers: list[int] = Field(default_factory=list)
    condition_observation: str | None = None


class PhotoAnalysis(BaseModel):
    model: str
    version: str
    photos_total: int
    photos_triaged: int
    photos_examined: list[int] = Field(default_factory=list)  # 1-based photo numbers sent at full detail
    accepted: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    likely: list[str] = Field(default_factory=list)  # medium-confidence findings on required features
    condition: Condition = Condition.UNKNOWN
    condition_note: str | None = None
    skipped_reason: str | None = None
    # Raw model output + photo mapping, so rule changes re-apply without new API calls.
    raw_findings: PhotoFindings | None = None
    targets: list[str] = Field(default_factory=list)
    picked: list[int] = Field(default_factory=list)  # 0-based indexes sent in pass 2
    rooms_by_sent: dict[int, list[Room]] = Field(default_factory=dict)
    staged: bool = False
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---- Agent summary (final verdict written after all analysis) ---------------------------

class SummaryOutput(BaseModel):
    """What the model returns. Spanish, built only from the facts it is given."""

    verdict: Literal["recomendada", "considerar", "no_recomendada"]
    headline: str = Field(description="Una oración en español con la conclusión principal")
    reasons_for: list[str] = Field(description="2-4 razones a favor, en español, cada una basada en los datos")
    reasons_against: list[str] = Field(description="1-4 razones en contra o riesgos, en español")
    next_steps: list[str] = Field(description="1-3 pasos concretos a seguir antes de decidir, en español")


class AgentSummary(SummaryOutput):
    model: str
    prompt_version: str
    facts_hash: str  # summary is regenerated only when these facts change
    verdict_adjusted: bool = False  # True if a rule capped the model's verdict
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
