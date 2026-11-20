from app.services.address import normalize_street, parse_address
from app.services.deduplication import deduplicate
from tests.conftest import make_property


def test_parse_basic():
    a = parse_address("12 Sampleton Avenue, Lyndhurst, NJ 07071")
    assert (a.street, a.city, a.state, a.zip_code, a.unit) == ("12 Sampleton Avenue", "Lyndhurst", "NJ", "07071", None)


def test_parse_unit_in_street():
    a = parse_address("200 Testview Ter APT 4B, Cliffside Park, NJ 07010")
    assert a.street == "200 Testview Ter"
    assert a.unit == "4B"
    assert a.city == "Cliffside Park"


def test_parse_incomplete():
    a = parse_address("12 Main St")
    assert a.street == "12 Main St" and a.city is None and a.zip_code is None


def test_normalize_street():
    assert normalize_street("12 Sampleton Avenue") == normalize_street("12 sampleton ave.")


def test_dedup_same_listing_id():
    a = make_property(external_id="1")
    b = make_property(external_id="1")
    assert len(deduplicate([a, b])) == 1


def test_dedup_same_address_different_ids_prefers_detailed():
    a = make_property(external_id="1")
    b = make_property(external_id="2", details_fetched=True)
    result = deduplicate([a, b])
    assert len(result) == 1 and result[0].external_id == "2"


def test_different_units_are_not_duplicates():
    from app.models.property import Address

    a = make_property(external_id="1", address=Address(raw="x", street="12 Main St", unit="1", zip_code="07071"))
    b = make_property(external_id="2", address=Address(raw="y", street="12 Main St", unit="2", zip_code="07071"))
    assert len(deduplicate([a, b])) == 2


def test_same_building_same_price_with_unit_suffix_is_duplicate():
    from app.models.property import Address

    a = make_property(external_id="1", price=819_900, address=Address(raw="x", street="188 N 6Th St", unit="2", zip_code="07663"))
    b = make_property(external_id="2", price=819_900, address=Address(raw="y", street="188 N 6th St", zip_code="07663"))
    result = deduplicate([a, b])
    assert len(result) == 1 and result[0].external_id == "2"


def test_same_building_different_price_kept():
    from app.models.property import Address

    a = make_property(external_id="1", price=500_000, address=Address(raw="x", street="12 Main St", unit="1", zip_code="07071"))
    b = make_property(external_id="2", price=520_000, address=Address(raw="y", street="12 Main St", unit="2", zip_code="07071"))
    assert len(deduplicate([a, b])) == 2
