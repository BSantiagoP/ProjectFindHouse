"""Contract tests against the response shape observed in live HasData calls (2026-11-20).

Values are fictional; structure and field names mirror the real responses.
"""

import httpx

from app.models.property import FeatureSource, FeatureState, PropertyType
from app.providers.base import RequestBudget, SearchQuery
from app.providers.hasdata import HasDataProvider
from tests.conftest import TODAY

LISTING_PAGE = {
    "requestMetadata": {"id": "x", "status": "ok"},
    "searchInformation": {"totalResults": 1},
    "properties": [
        {
            "id": "1001",
            "url": "https://www.zillow.com/homedetails/10-Sample-Ave-Lyndhurst-NJ-07071/1001_zpid/",
            "homeType": "MULTI_FAMILY",
            "status": "FOR_SALE",
            "currency": "$",
            "price": 850000,
            "daysOnZillow": 0,
            "addressRaw": "10 Sample Avenue, Lyndhurst, NJ 07071",
            "address": {"street": "10 Sample Avenue", "city": "Lyndhurst", "state": "NJ", "zipcode": "07071"},
            "latitude": 40.81,
            "longitude": -74.12,
            "beds": 5,
            "baths": 3,
            "photos": ["https://photos.example/1.jpg", "https://photos.example/2.jpg"],
        }
    ],
    "pagination": {"currentPage": 1, "otherPages": {}},
}

DETAIL = {
    "requestMetadata": {"id": "y", "status": "ok"},
    "property": {
        "id": 1001,
        "homeType": "MULTI_FAMILY",
        "price": 850000,
        "geo": {"latitude": 40.81, "longitude": -74.12},
        "highlights": ["Fully finished basement", "Fenced-in backyard"],
        "datePosted": "2026-11-19",
        "description": "Two-family home with attached two-car garage.",
        "photos": ["https://photos.example/1.jpg", "https://photos.example/2.jpg", "https://photos.example/3.jpg"],
        "resoData": {
            # Real listings showed hasGarage=false alongside a garage in parkingFeatures.
            "hasGarage": False,
            "garageParkingCapacity": 2,
            "parkingFeatures": ["Garage"],
            "laundryFeatures": ["In Basement"],
            "structureType": "2 Family",
            "taxAnnualAmount": 12000,
            "onMarketDate": 1795046400000,
        },
        "taxHistory": [{"time": 1, "taxPaid": 9000}],
    },
}


def run(detail=DETAIL, listing=LISTING_PAGE):
    def handler(req):
        return httpx.Response(200, json=detail if req.url.path.endswith("/property") else listing)

    client = httpx.Client(base_url="https://api.hasdata.com", transport=httpx.MockTransport(handler))
    prov = HasDataProvider("k", client=client, today=lambda: TODAY, max_pages=3)
    budget = RequestBudget(10)
    props = prov.search(SearchQuery("Lyndhurst, NJ", 900_000, (PropertyType.MULTI_FAMILY,), 7), budget)
    return prov, budget, props


def test_listing_uses_structured_address_and_photos():
    _, budget, props = run()
    p = props[0]
    assert budget.used == 1  # empty otherPages => no second page
    assert p.address.city == "Lyndhurst" and p.address.zip_code == "07071" and p.address.state == "NJ"
    assert p.latitude == 40.81
    assert len(p.photo_urls) == 2


def test_other_pages_triggers_next_page():
    listing = dict(LISTING_PAGE, pagination={"currentPage": 1, "otherPages": {"2": "url"}})
    _, budget, _ = run(listing=listing)
    assert budget.used == 3  # follows until max_pages since fixture always reports more


def test_reso_data_mapped_to_features_and_fields():
    prov, budget, props = run()
    p = prov.enrich(props[0], budget)
    assert p.units == 2 and "2 Family" in p.units_evidence
    assert p.annual_tax == 12000  # resoData preferred over taxHistory
    assert p.listed_date.isoformat() == "2026-11-19"
    assert p.highlights == ["Fully finished basement", "Fenced-in backyard"]
    assert len(p.photo_urls) == 3
    assert p.features.garage.state is FeatureState.PRESENT
    assert p.features.garage.source is FeatureSource.PROVIDER
    assert p.features.laundry.state is FeatureState.PRESENT


def test_has_garage_false_alone_never_marks_absent():
    detail = {"property": {"resoData": {"hasGarage": False}}}
    prov, budget, props = run(detail=detail)
    assert prov.enrich(props[0], budget).features.garage.state is FeatureState.UNKNOWN


def test_street_only_parking_marks_absent():
    detail = {"property": {"resoData": {"parkingFeatures": ["On Street"]}}}
    prov, budget, props = run(detail=detail)
    f = prov.enrich(props[0], budget).features
    assert f.garage.is_absent and f.driveway.is_absent


def test_driveway_from_parking_features():
    detail = {"property": {"resoData": {"parkingFeatures": ["Driveway", "On Street"]}}}
    prov, budget, props = run(detail=detail)
    f = prov.enrich(props[0], budget).features
    assert f.driveway.is_present and f.garage.state is FeatureState.UNKNOWN


def test_laundry_none_marks_absent():
    detail = {"property": {"resoData": {"laundryFeatures": ["None"]}}}
    prov, budget, props = run(detail=detail)
    assert prov.enrich(props[0], budget).features.laundry.is_absent


def test_highlights_feed_description_extraction():
    from app.services.features import apply_description_features

    prov, budget, props = run()
    p = apply_description_features(prov.enrich(props[0], budget))
    assert p.features.finished_basement.state is FeatureState.PRESENT
    assert p.features.outdoor_space.state is FeatureState.PRESENT


def test_zero_price_is_unknown():
    listing = dict(LISTING_PAGE, properties=[dict(LISTING_PAGE["properties"][0], price=0)])
    _, _, props = run(listing=listing)
    assert props[0].price is None
