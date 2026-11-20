from datetime import datetime

from pydantic import BaseModel

from app.models.property import Property
from app.services.discovery import DiscoveryRun, EvaluatedProperty
from app.services.filtering import FilterStatus


class PropertyOut(BaseModel):
    id: str  # "<provider>:<external_id>"
    status: FilterStatus
    rejections: list[str]
    unverified: list[str]
    property: Property

    @classmethod
    def from_evaluated(cls, ev: EvaluatedProperty) -> "PropertyOut":
        p = ev.property
        return cls(
            id=f"{p.provider}:{p.external_id}",
            status=ev.filter.status,
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
            errors=run.errors,
            counts={s.value: len(run.by_status(s)) for s in FilterStatus},
        )
