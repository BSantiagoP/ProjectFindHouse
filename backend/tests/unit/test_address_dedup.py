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


def test_parse_hash_unit_from_live_data():
    # Live listing 2026-11-20: unit given as "#2" was not recognized, creating a duplicate.
    a = parse_address("188 N 6Th St #2, Saddle Brook Twp., NJ 07663")
    assert a.street == "188 N 6Th St" and a.unit == "2"
    assert parse_address("10 Main St Unit 3B, Lyndhurst, NJ 07071").unit == "3B"
    assert parse_address("10 Main St Apt. 4, Lyndhurst, NJ 07071").unit == "4"
    assert parse_address("10 Unity Ave, Lyndhurst, NJ 07071").unit is None


def test_live_duplicate_pair_merges():
    from app.services.address import parse_address as pa

    a = make_property(external_id="2085266837", price=819_900, address=pa("188 N 6Th St #2, Saddle Brook Twp., NJ 07663"))
    b = make_property(external_id="38027096", price=819_900, address=pa("188 N 6th St, Saddle Brook, NJ 07663"))
    result = deduplicate([a, b])
    assert [p.external_id for p in result] == ["38027096"]
