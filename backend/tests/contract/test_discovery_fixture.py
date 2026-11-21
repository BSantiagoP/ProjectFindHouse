"""End-to-end discovery over the synthetic HasData fixtures (no network, no credits)."""

from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app
from app.models.preferences import SearchPreferences
from app.providers.fixture import make_fixture_provider
from app.repositories.factory import get_repository
from app.repositories.memory import MemoryRepository
from app.services.discovery import run_discovery
from app.services.filtering import FilterStatus
from tests.conftest import TODAY


def run(max_requests=20, fetch_details=True):
    return run_discovery(
        make_fixture_provider(today=lambda: TODAY),
        SearchPreferences(),
        max_requests=max_requests,
        fetch_details=fetch_details,
        today=TODAY,
    )


def ids(run_, status):
    return sorted(e.property.external_id for e in run_.by_status(status))


def test_pipeline_outcomes():
    r = run()
    assert r.status == "succeeded", r.errors
    # 12 raw records, one duplicated across Lyndhurst/Fairview searches
    assert len(r.results) == 11
    assert ids(r, FilterStatus.ELIGIBLE) == ["900001", "900002", "900004"]
    assert ids(r, FilterStatus.NEEDS_VERIFICATION) == ["900006"]
    assert ids(r, FilterStatus.REJECTED) == ["900003", "900005", "900007", "900008", "900009", "900010", "900011"]


def test_rejection_reasons_are_explained():
    r = run()
    reasons = {e.property.external_id: e.filter.rejections for e in r.results}
    assert reasons["900003"] == ["Sin garaje ni entrada para autos"]
    assert reasons["900005"] == ["Unifamiliar sin sótano completamente terminado"]
    assert "condo" in reasons["900007"][0]
    assert "hace más de 7 días" in reasons["900008"][0]
    assert "supera el máximo" in reasons["900009"][0]
    assert "Fuera de los pueblos elegidos" in reasons["900010"][0]
    assert "5 unidades" in reasons["900011"][0]


def test_eligible_have_required_output_fields_and_evidence():
    for e in run().by_status(FilterStatus.ELIGIBLE):
        p = e.property
        assert p.source_url and p.price and p.town and p.listed_date
        assert p.features.laundry.evidence
        assert (p.features.garage.evidence or p.features.driveway.evidence)


def test_details_only_fetched_for_prefiltered_candidates():
    r = run()
    # 5 town searches + 8 details (condo, over-price, out-of-town skipped)
    assert r.requests_used == 13


def test_budget_exhaustion_degrades_gracefully():
    r = run(max_requests=7)
    assert r.status == "partial"
    assert any("budget exhausted" in e for e in r.errors)
    # without details, nothing can be confirmed eligible
    assert r.requests_used == 7


def test_api_requires_token_and_returns_eligible():
    repo = MemoryRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, api_token="secret", provider="fixture", max_requests_per_run=20, analysis_enabled=False)
    try:
        client = TestClient(app)
        assert client.post("/api/searches").status_code == 401
        assert client.get("/api/properties", headers={"Authorization": "Bearer wrong"}).status_code == 401

        auth = {"Authorization": "Bearer secret"}
        created = client.post("/api/searches", headers=auth)
        assert created.status_code == 201
        body = created.json()
        assert body["counts"]["eligible"] >= 1

        props = client.get("/api/properties", headers=auth).json()
        assert props and all(p["status"] == "eligible" for p in props)
        first = props[0]["property"]
        for key in ("source_url", "price", "town", "listed_date", "features"):
            assert first[key] is not None
        assert first["features"]["laundry"]["state"] in ("present", "absent", "unknown")

        one = client.get(f"/api/properties/{props[0]['id']}", headers=auth)
        assert one.status_code == 200

        verify = client.get("/api/properties", params={"status": "needs_verification"}, headers=auth).json()
        assert all(p["unverified"] for p in verify)

        assert client.get(f"/api/searches/{body['id']}", headers=auth).status_code == 200
        assert client.get("/api/preferences", headers=auth).json()["max_price"] == 900_000
    finally:
        app.dependency_overrides.clear()


def test_api_fails_closed_without_configured_token():
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, api_token="")
    app.dependency_overrides[get_repository] = lambda: MemoryRepository()
    try:
        assert TestClient(app).get("/api/properties").status_code == 503
    finally:
        app.dependency_overrides.clear()
