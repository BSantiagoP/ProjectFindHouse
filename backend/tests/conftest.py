from datetime import date

import pytest

from app.models.preferences import SearchPreferences
from app.models.property import Address, Feature, FeatureState, Property, PropertyFeatures, PropertyType

TODAY = date(2026, 11, 20)


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Tests must never call real APIs (paid keys live in .env). MockTransport is unaffected."""
    import httpx

    def blocked(self, request):
        raise RuntimeError(f"Real network call blocked in tests: {request.url.host}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)


@pytest.fixture
def prefs() -> SearchPreferences:
    return SearchPreferences()


def present(evidence: str = "test") -> Feature:
    return Feature(state=FeatureState.PRESENT, evidence=evidence)


def absent(evidence: str = "test") -> Feature:
    return Feature(state=FeatureState.ABSENT, evidence=evidence)


def make_property(**overrides) -> Property:
    """An eligible 2-family in Lyndhurst unless overridden."""
    base = dict(
        provider="test",
        external_id="1",
        source_url="https://example.com/listing/1",
        address=Address(raw="12 Main St, Lyndhurst, NJ 07071", street="12 Main St", city="Lyndhurst", state="NJ", zip_code="07071"),
        town="Lyndhurst",
        price=700_000,
        property_type=PropertyType.MULTI_FAMILY,
        units=2,
        listed_date=TODAY,
        features=PropertyFeatures(garage=present(), laundry=present()),
    )
    base.update(overrides)
    return Property(**base)
