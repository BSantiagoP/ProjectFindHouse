"""Offline provider: serves recorded HasData-shaped JSON through the real HasData adapter.

Used for local development and tests so no credits are spent. Fixtures under
tests/fixtures are synthetic until replaced with sanitized recordings of live responses.
"""

import json
from pathlib import Path

import httpx

from app.providers.hasdata import HasDataProvider

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def _transport(listing: dict, details: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/scrape/zillow/listing":
            keyword = request.url.params.get("keyword", "")
            page = int(request.url.params.get("page", "1"))
            body = listing.get(keyword, {"properties": [], "pagination": {}}) if page == 1 else {"properties": []}
            return httpx.Response(200, json=body)
        if request.url.path == "/scrape/zillow/property":
            url = request.url.params.get("url", "")
            return httpx.Response(200, json=details.get(url, {"error": "Property not found"}))
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def make_fixture_provider(
    listing_file: Path = FIXTURE_DIR / "hasdata_listing_synthetic.json",
    details_file: Path = FIXTURE_DIR / "hasdata_property_synthetic.json",
    **kwargs,
) -> HasDataProvider:
    listing = json.loads(listing_file.read_text())
    details = json.loads(details_file.read_text())
    client = httpx.Client(base_url="https://api.hasdata.com", transport=_transport(listing, details))
    return HasDataProvider("fixture-key", client=client, **kwargs)
