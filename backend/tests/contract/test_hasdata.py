import httpx
import pytest

from app.models.property import PropertyType
from app.providers.base import (
    BudgetExceededError,
    ProviderAuthError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderUnavailableError,
    RequestBudget,
    SearchQuery,
)
from app.providers.hasdata import HasDataProvider
from tests.conftest import TODAY

QUERY = SearchQuery("Lyndhurst, NJ", 900_000, (PropertyType.MULTI_FAMILY, PropertyType.SINGLE_FAMILY), 7)
LISTING = {
    "id": "1",
    "url": "https://www.zillow.com/homedetails/1_zpid/",
    "homeType": "MULTI_FAMILY",
    "status": "FOR_SALE",
    "price": 700000,
    "daysOnZillow": 3,
    "area": 2400,
    "addressRaw": "12 Main St, Lyndhurst, NJ 07071",
}


def provider(handler, **kw) -> HasDataProvider:
    client = httpx.Client(base_url="https://api.hasdata.com", transport=httpx.MockTransport(handler))
    return HasDataProvider("k", client=client, sleep=lambda _: None, today=lambda: TODAY, **kw)


def test_search_sends_documented_params_and_auth():
    seen: list[httpx.Request] = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"properties": [LISTING], "pagination": {}})

    props = provider(handler).search(QUERY, RequestBudget(5))
    req = seen[0]
    assert req.url.path == "/scrape/zillow/listing"
    assert req.headers["x-api-key"] == "k"
    params = req.url.params
    assert params["keyword"] == "Lyndhurst, NJ"
    assert params["type"] == "forSale"
    assert params["price[max]"] == "900000"
    assert params["daysOnZillow"] == "7"
    assert params.get_list("homeTypes[]") == ["MULTI_FAMILY", "SINGLE_FAMILY"]
    assert len(props) == 1


def test_normalizes_listing():
    p = provider(lambda r: httpx.Response(200, json=[LISTING])).search(QUERY, RequestBudget(5))[0]
    assert p.external_id == "1"
    assert p.price == 700_000
    assert p.property_type is PropertyType.MULTI_FAMILY
    assert p.address.city == "Lyndhurst" and p.address.zip_code == "07071"
    assert p.days_on_market == 3
    assert p.listed_date == TODAY.replace(day=17)
    assert str(p.source_url) == LISTING["url"]


def test_bare_array_response_supported():
    props = provider(lambda r: httpx.Response(200, json=[LISTING, LISTING])).search(QUERY, RequestBudget(5))
    assert len(props) == 2


def test_records_missing_required_fields_skipped():
    bad = {k: v for k, v in LISTING.items() if k != "url"}
    assert provider(lambda r: httpx.Response(200, json=[bad])).search(QUERY, RequestBudget(5)) == []


def test_unknown_home_type_and_bad_numbers():
    rec = dict(LISTING, homeType="MANUFACTURED", price="n/a")
    p = provider(lambda r: httpx.Response(200, json=[rec])).search(QUERY, RequestBudget(5))[0]
    assert p.property_type is PropertyType.OTHER
    assert p.price is None


def test_pagination_follows_total_pages_up_to_max():
    pages: list[str] = []

    def handler(req):
        pages.append(req.url.params["page"])
        rec = dict(LISTING, id=req.url.params["page"])
        return httpx.Response(200, json={"properties": [rec], "pagination": {"totalPages": 5}})

    props = provider(handler, max_pages=2).search(QUERY, RequestBudget(10))
    assert pages == ["1", "2"]
    assert len(props) == 2


@pytest.mark.parametrize(
    "code,exc",
    [(401, ProviderAuthError), (403, ProviderQuotaError), (422, ProviderRequestError)],
)
def test_non_retryable_errors(code, exc):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(code, text="err")

    with pytest.raises(exc):
        provider(handler).search(QUERY, RequestBudget(5))
    assert len(calls) == 1


def test_retries_then_succeeds():
    responses = iter([httpx.Response(429), httpx.Response(200, json=[LISTING])])
    budget = RequestBudget(5)
    assert len(provider(lambda r: next(responses)).search(QUERY, budget)) == 1
    assert budget.used == 2  # 429 is not documented as free, so it counts


def test_uncharged_failures_refund_budget():
    responses = iter([httpx.Response(504), httpx.Response(400), httpx.Response(200, json=[LISTING])])
    budget = RequestBudget(5)
    provider(lambda r: next(responses)).search(QUERY, budget)
    assert budget.used == 1


def test_gives_up_after_retries():
    with pytest.raises(ProviderUnavailableError):
        provider(lambda r: httpx.Response(500), max_retries=2).search(QUERY, RequestBudget(10))


def test_budget_cap_enforced():
    with pytest.raises(BudgetExceededError):
        provider(lambda r: httpx.Response(200, json=[])).search(QUERY, RequestBudget(0))


def test_enrich_applies_details():
    detail = {
        "property": {
            "description": "Two-family with garage.",
            "datePosted": "2026-11-18",
            "beds": 5,
            "yearBuilt": 1925,
            "area": {"livingArea": 2500},
            "taxHistory": [{"time": 1, "taxPaid": 9000}, {"time": 2, "taxPaid": 11000}],
        }
    }

    def handler(req):
        if req.url.path.endswith("/property"):
            assert req.url.params["url"] == LISTING["url"]
            return httpx.Response(200, json=detail)
        return httpx.Response(200, json=[LISTING])

    prov = provider(handler)
    budget = RequestBudget(5)
    p = prov.enrich(prov.search(QUERY, budget)[0], budget)
    assert p.details_fetched
    assert p.description == "Two-family with garage."
    assert p.listed_date.isoformat() == "2026-11-18"
    assert p.living_area_sqft == 2500
    assert p.annual_tax == 11000


def test_enrich_missing_property_keeps_listing():
    def handler(req):
        if req.url.path.endswith("/property"):
            return httpx.Response(200, json={"error": "Property not found"})
        return httpx.Response(200, json=[LISTING])

    prov = provider(handler)
    budget = RequestBudget(5)
    p = prov.enrich(prov.search(QUERY, budget)[0], budget)
    assert not p.details_fetched


def test_missing_api_key_rejected():
    with pytest.raises(ProviderAuthError):
        HasDataProvider("")
