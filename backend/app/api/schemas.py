from datetime import datetime

from pydantic import BaseModel

from app.models.property import Property
from app.services.discovery import DiscoveryRun, EvaluatedProperty
from app.services.filtering import FilterStatus
from app.services.scoring import Analysis


class PropertyOut(BaseModel):
    id: str  # "<provider>:<external_id>"
    property_id: str | None  # database id; use for /history
    status: FilterStatus
    is_new: bool
    previous_price: int | None
    rank: int | None
    score: float | None
    confidence: float | None
    rejections: list[str]
    unverified: list[str]
    analysis: Analysis | None
    property: Property

    @classmethod
    def from_evaluated(cls, ev: EvaluatedProperty) -> "PropertyOut":
        p = ev.property
        return cls(
            id=f"{p.provider}:{p.external_id}",
            property_id=ev.property_id,
            status=ev.filter.status,
            is_new=ev.is_new,
            previous_price=ev.previous_price,
            rank=ev.rank,
            score=ev.analysis.score if ev.analysis else None,
            confidence=ev.analysis.confidence if ev.analysis else None,
            analysis=ev.analysis,
            rejections=ev.filter.rejections,
            unverified=ev.filter.unverified,
            property=p,
        )


class SearchRunOut(BaseModel):
    id: str
    status: str
    provider: str
    started_at: datetime
    completed_at: datetime | None
    requests_used: int
    request_budget: int
    details_reused: int
    errors: list[str]
    counts: dict[str, int]

    @classmethod
    def from_run(cls, run: DiscoveryRun) -> "SearchRunOut":
        return cls(
            id=run.id,
            status=run.status,
            provider=run.provider,
            started_at=run.started_at,
            completed_at=run.completed_at,
            requests_used=run.requests_used,
            request_budget=run.request_budget,
            details_reused=run.details_reused,
            errors=run.errors,
            counts=run.counts(),
        )
