"""Milestone 2: seen-listing memory, credit savings, price-change detection."""

import json

import httpx

from app.models.preferences import SearchPreferences
from app.providers.fixture import FIXTURE_DIR, make_fixture_provider
from app.repositories.memory import MemoryRepository
from app.repositories.supabase import SupabaseRepository, _in
from app.services.discovery import run_discovery
from app.services.filtering import FilterStatus
from tests.conftest import TODAY


def discover(repo, provider=None):
    run = run_discovery(
        provider or make_fixture_provider(today=lambda: TODAY),
        SearchPreferences(),
        max_requests=20,
        today=TODAY,
        known_lookup=repo.known_properties,
    )
    repo.save_run(run)
    return run


def test_first_run_everything_new():
    run = discover(MemoryRepository())
    assert all(r.is_new for r in run.results)
    assert run.details_reused == 0
    assert all(r.property_id for r in run.results)


def test_second_run_reuses_details_and_saves_credits():
    repo = MemoryRepository()
    first = discover(repo)
    second = discover(repo)
    assert first.requests_used == 13
    assert second.requests_used == 5  # town searches only
    assert second.details_reused == 8
    assert not any(r.is_new for r in second.results)
    # Same outcomes as the first run, from stored details
    status = lambda run: sorted((r.property.external_id, r.filter.status.value) for r in run.results)
    assert status(first) == status(second)
    # Same physical properties keep the same ids
    ids = lambda run: {r.property.external_id: r.property_id for r in run.results}
    assert ids(first) == ids(second)


def test_price_change_detected_and_history_recorded(tmp_path):
    repo = MemoryRepository()
    discover(repo)

    listing = json.loads((FIXTURE_DIR / "hasdata_listing_synthetic.json").read_text())
    for rec in listing["Lyndhurst, NJ"]["properties"]:
        if rec["id"] == "900001":
            rec["price"] = 675000
    for rec in listing["Fairview, NJ"]["properties"]:
        if rec["id"] == "900001":
            rec["price"] = 675000
    changed = tmp_path / "listing.json"
    changed.write_text(json.dumps(listing))

    run = discover(repo, make_fixture_provider(listing_file=changed, today=lambda: TODAY))
    ev = next(r for r in run.results if r.property.external_id == "900001")
    assert ev.price_changed and ev.previous_price == 695000 and ev.property.price == 675000
    assert ev.filter.status is FilterStatus.ELIGIBLE
    assert run.counts()["price_changed"] == 1
    assert [s.price for s in repo.price_history(ev.property_id)] == [695000, 675000]


def test_latest_run_skips_failed():
    repo = MemoryRepository()
    ok = discover(repo)
    failed = discover(repo)
    failed.status = "failed"
    repo.runs[failed.id].status = "failed"
    assert repo.latest_run().id == ok.id


# ---- Supabase request formation (no network) ------------------------------------


def _capture(handler_body=None):
    seen: list[httpx.Request] = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=handler_body if handler_body is not None else [])

    return seen, httpx.Client(base_url="https://x.supabase.co/rest/v1", transport=httpx.MockTransport(handler))


def test_secret_key_not_sent_as_bearer():
    seen, client = _capture()
    SupabaseRepository("https://x.supabase.co", "sb_secret_abc", client=client).get_preferences()
    assert seen[0].headers["apikey"] == "sb_secret_abc"
    assert "authorization" not in seen[0].headers


def test_legacy_jwt_key_sent_as_bearer():
    seen, client = _capture()
    SupabaseRepository("https://x.supabase.co", "eyJabc", client=client).get_preferences()
    assert seen[0].headers["authorization"] == "Bearer eyJabc"


def test_in_filter_quotes_values():
    assert _in(["12 MAIN ST||07071", 'a"b']) == 'in.("12 MAIN ST||07071","a\\"b")'


def test_known_properties_parses_embedded_data():
    from tests.conftest import make_property

    prop = make_property(external_id="42", details_fetched=True)
    body = [{"provider": "test", "external_id": "42", "properties": {"data": prop.model_dump(mode="json")}}]
    seen, client = _capture(body)
    known = SupabaseRepository("https://x.supabase.co", "sb_secret_abc", client=client).known_properties([("test", "42")])
    assert known[("test", "42")].external_id == "42"
    params = seen[0].url.params
    assert params["provider"] == "eq.test" and params["external_id"] == 'in.("42")'


def test_accepts_rest_url_form():
    for url in ("https://x.supabase.co", "https://x.supabase.co/", "https://x.supabase.co/rest/v1/"):
        repo = SupabaseRepository(url, "sb_secret_abc")
        assert str(repo._client.base_url).rstrip("/") == "https://x.supabase.co/rest/v1"
