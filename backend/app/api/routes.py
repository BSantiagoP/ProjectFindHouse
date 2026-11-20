from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.schemas import PropertyOut, SearchRunOut
from app.core.config import Settings, get_settings
from app.core.security import require_auth
from app.models.preferences import SearchPreferences
from app.providers.base import PropertyProvider, ProviderAuthError
from app.repositories.memory import MemoryStore, get_store
from app.services.discovery import run_discovery
from app.services.filtering import FilterStatus

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])

StoreDep = Annotated[MemoryStore, Depends(get_store)]


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


@router.post("/searches", response_model=SearchRunOut, status_code=status.HTTP_201_CREATED)
def create_search(
    store: StoreDep,
    provider: Annotated[PropertyProvider, Depends(get_provider)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchRunOut:
    run = run_discovery(
        provider,
        store.preferences,
        max_requests=settings.max_requests_per_run,
        fetch_details=settings.fetch_details,
    )
    store.save_run(run)
    return SearchRunOut.from_run(run)


@router.get("/searches/{run_id}", response_model=SearchRunOut)
def get_search(run_id: str, store: StoreDep) -> SearchRunOut:
    run = store.runs.get(run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Search run not found")
    return SearchRunOut.from_run(run)


@router.get("/properties", response_model=list[PropertyOut])
def list_properties(
    store: StoreDep,
    status_filter: Annotated[FilterStatus, Query(alias="status")] = FilterStatus.ELIGIBLE,
) -> list[PropertyOut]:
    run = store.latest_run()
    if run is None:
        return []
    return [PropertyOut.from_evaluated(ev) for ev in run.by_status(status_filter)]


@router.get("/properties/{property_id}", response_model=PropertyOut)
def get_property(property_id: str, store: StoreDep) -> PropertyOut:
    run = store.latest_run()
    if run is not None:
        for ev in run.results:
            if f"{ev.property.provider}:{ev.property.external_id}" == property_id:
                return PropertyOut.from_evaluated(ev)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Property not found")


@router.get("/preferences", response_model=SearchPreferences)
def read_preferences(store: StoreDep) -> SearchPreferences:
    return store.preferences


@router.put("/preferences", response_model=SearchPreferences)
def update_preferences(prefs: SearchPreferences, store: StoreDep) -> SearchPreferences:
    store.preferences = prefs
    return prefs
