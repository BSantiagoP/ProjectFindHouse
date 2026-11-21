import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.schemas import PropertyOut, SearchRunOut
from app.core.config import Settings, get_settings
from app.core.security import require_auth
from app.models.preferences import SearchPreferences
from app.providers.base import PropertyProvider, ProviderAuthError
from app.repositories.base import PriceSnapshot, Repository, RepositoryError
from app.repositories.factory import get_repository
from app.agents.graph import AnalysisDeps, run_analysis
from app.providers.rentcast import RentCastClient
from app.services.commute import GtfsStopFinder
from app.services.description_analysis import OpenAIStructuredLLM
from app.services.photo_analysis import OpenAIVisionLLM
from app.services.agent_summary import OpenAISummaryLLM
from app.services.discovery import run_discovery
from app.services.rates import current_rate
from app.services.filtering import FilterStatus

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])

RepoDep = Annotated[Repository, Depends(get_repository)]


def get_provider(settings: Annotated[Settings, Depends(get_settings)]) -> PropertyProvider:
    if settings.provider == "fixture":
        from app.providers.fixture import make_fixture_provider

        return make_fixture_provider(max_pages=settings.max_pages_per_town)
    from app.providers.hasdata import HasDataProvider

    try:
        return HasDataProvider(
            settings.hasdata_api_key,
            base_url=settings.hasdata_base_url,
            timeout=settings.hasdata_timeout_seconds,
            max_pages=settings.max_pages_per_town,
        )
    except ProviderAuthError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


def build_analysis_deps(settings: Settings, repo: Repository, prefs: SearchPreferences) -> AnalysisDeps:
    llm = OpenAIStructuredLLM(settings.openai_api_key, settings.openai_model) if settings.openai_api_key else None
    rentcast = (
        RentCastClient(settings.rentcast_api_key, reserve=repo.reserve_api_request,
                       monthly_cap=settings.rentcast_monthly_cap)
        if settings.rentcast_api_key else None
    )
    vision = OpenAIVisionLLM(settings.openai_api_key, settings.openai_vision_model) if settings.openai_api_key and settings.photo_analysis_enabled else None
    return AnalysisDeps(
        llm=llm, llm_model=settings.openai_model, rentcast=rentcast, vision=vision,
        summarizer=OpenAISummaryLLM(settings.openai_api_key, settings.openai_model) if settings.openai_api_key else None,
        stops=GtfsStopFinder(), rate=current_rate(prefs.rate_override),
    )


def _storage_error(exc: RepositoryError) -> HTTPException:
    log.error("Storage error: %s", exc)
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Storage unavailable: {exc}")


@router.post("/searches", response_model=SearchRunOut, status_code=status.HTTP_201_CREATED)
def create_search(
    repo: RepoDep,
    provider: Annotated[PropertyProvider, Depends(get_provider)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchRunOut:
    try:
        prefs = repo.get_preferences()
    except RepositoryError as exc:
        raise _storage_error(exc) from exc
    run = run_discovery(
        provider,
        prefs,
        max_requests=settings.max_requests_per_run,
        fetch_details=settings.fetch_details,
        known_lookup=repo.known_properties,
    )
    if settings.analysis_enabled:
        run = run_analysis(run, prefs, build_analysis_deps(settings, repo, prefs))
    try:
        repo.save_run(run)
    except RepositoryError as exc:
        # Credits were spent; log the full summary so the run is not silently lost.
        log.error("Run %s completed but could not be saved: %s", run.id, SearchRunOut.from_run(run).model_dump_json())
        raise _storage_error(exc) from exc
    return SearchRunOut.from_run(run)


@router.get("/searches/{run_id}", response_model=SearchRunOut)
def get_search(run_id: str, repo: RepoDep) -> SearchRunOut:
    try:
        run = repo.get_run(run_id)
    except RepositoryError as exc:
        raise _storage_error(exc) from exc
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Search run not found")
    return SearchRunOut.from_run(run)


@router.get("/properties", response_model=list[PropertyOut])
def list_properties(
    repo: RepoDep,
    status_filter: Annotated[FilterStatus, Query(alias="status")] = FilterStatus.ELIGIBLE,
    new_only: bool = False,
) -> list[PropertyOut]:
    try:
        run = repo.latest_run()
    except RepositoryError as exc:
        raise _storage_error(exc) from exc
    if run is None:
        return []
    return [
        PropertyOut.from_evaluated(ev)
        for ev in run.by_status(status_filter)
        if not new_only or ev.is_new
    ]


@router.get("/properties/{property_id}", response_model=PropertyOut)
def get_property(property_id: str, repo: RepoDep) -> PropertyOut:
    """Accepts either the database property_id or "<provider>:<external_id>"."""
    try:
        run = repo.latest_run()
    except RepositoryError as exc:
        raise _storage_error(exc) from exc
    if run is not None:
        for ev in run.results:
            if property_id in (ev.property_id, f"{ev.property.provider}:{ev.property.external_id}"):
                return PropertyOut.from_evaluated(ev)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Property not found in the latest run")


@router.get("/properties/{property_id}/history", response_model=list[PriceSnapshot])
def get_price_history(property_id: str, repo: RepoDep) -> list[PriceSnapshot]:
    try:
        return repo.price_history(property_id)
    except RepositoryError as exc:
        raise _storage_error(exc) from exc


@router.get("/reports/latest", response_model=list[PropertyOut])
def latest_report(repo: RepoDep) -> list[PropertyOut]:
    """Top-ranked eligible properties from the latest run (at most max_recommendations)."""
    try:
        run = repo.latest_run()
    except RepositoryError as exc:
        raise _storage_error(exc) from exc
    if run is None:
        return []
    ranked = sorted((ev for ev in run.results if ev.rank), key=lambda ev: ev.rank)
    return [PropertyOut.from_evaluated(ev) for ev in ranked]


@router.post("/notifications/send-latest")
def send_latest_digest(repo: RepoDep, settings: Annotated[Settings, Depends(get_settings)]) -> list[dict]:
    """Send the latest run's digest to all recipients. Idempotent per run and recipient."""
    if not settings.sms_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "SMS is disabled (set SMS_ENABLED=true)")
    from app.core.config import load_recipients
    from app.jobs.daily_search import build_sender
    from app.notifications.digest import send_digest

    run = repo.latest_run()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No search run yet")
    reports = send_digest(run, load_recipients(), repo, build_sender(settings),
                          limit=repo.get_preferences().max_recommendations,
                          dashboard_url=settings.dashboard_url or None,
                          dashboard_recipients={k.strip() for k in settings.dashboard_recipients.split(',') if k.strip()})
    return [{"recipient": r.recipient_key, "status": r.status, "count": r.count, "error": r.error} for r in reports]


@router.get("/preferences", response_model=SearchPreferences)
def read_preferences(repo: RepoDep) -> SearchPreferences:
    try:
        return repo.get_preferences()
    except RepositoryError as exc:
        raise _storage_error(exc) from exc


@router.put("/preferences", response_model=SearchPreferences)
def update_preferences(prefs: SearchPreferences, repo: RepoDep) -> SearchPreferences:
    try:
        repo.save_preferences(prefs)
    except RepositoryError as exc:
        raise _storage_error(exc) from exc
    return prefs
