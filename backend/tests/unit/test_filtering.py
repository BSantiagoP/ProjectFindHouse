from datetime import timedelta

from app.models.property import Feature, PropertyFeatures, PropertyType
from app.services.filtering import FilterStatus, apply_hard_filters
from tests.conftest import TODAY, absent, make_property, present


def check(prop, prefs):
    return apply_hard_filters(prop, prefs, TODAY)


def test_eligible_two_family(prefs):
    assert check(make_property(), prefs).status is FilterStatus.ELIGIBLE


def test_price_over_max_rejected(prefs):
    r = check(make_property(price=900_001), prefs)
    assert r.status is FilterStatus.REJECTED
    assert "exceeds max" in r.rejections[0]


def test_price_at_max_passes(prefs):
    assert check(make_property(price=900_000), prefs).status is FilterStatus.ELIGIBLE


def test_outside_towns_rejected(prefs):
    assert check(make_property(town=None), prefs).status is FilterStatus.REJECTED


def test_stale_listing_rejected(prefs):
    r = check(make_property(listed_date=TODAY - timedelta(days=8)), prefs)
    assert r.status is FilterStatus.REJECTED


def test_five_units_rejected(prefs):
    assert check(make_property(units=5), prefs).status is FilterStatus.REJECTED


def test_unknown_units_needs_verification(prefs):
    r = check(make_property(units=None), prefs)
    assert r.status is FilterStatus.NEEDS_VERIFICATION
    assert "unit count" in r.unverified


def test_condo_rejected(prefs):
    assert check(make_property(property_type=PropertyType.CONDO), prefs).status is FilterStatus.REJECTED


def test_single_family_requires_finished_basement_and_bath(prefs):
    feats = PropertyFeatures(garage=present(), laundry=present(), finished_basement=present(), basement_bathroom=present())
    ok = make_property(property_type=PropertyType.SINGLE_FAMILY, units=1, features=feats)
    assert check(ok, prefs).status is FilterStatus.ELIGIBLE


def test_single_family_without_finished_basement_rejected(prefs):
    feats = PropertyFeatures(garage=present(), laundry=present(), finished_basement=absent(), basement_bathroom=present())
    r = check(make_property(property_type=PropertyType.SINGLE_FAMILY, units=1, features=feats), prefs)
    assert r.status is FilterStatus.REJECTED


def test_single_family_basement_bath_unknown_needs_verification(prefs):
    feats = PropertyFeatures(garage=present(), laundry=present(), finished_basement=present())
    r = check(make_property(property_type=PropertyType.SINGLE_FAMILY, units=1, features=feats), prefs)
    assert r.status is FilterStatus.NEEDS_VERIFICATION
    assert "basement bathroom" in r.unverified


def test_driveway_without_garage_passes(prefs):
    feats = PropertyFeatures(garage=absent(), driveway=present(), laundry=present())
    assert check(make_property(features=feats), prefs).status is FilterStatus.ELIGIBLE


def test_street_parking_only_rejected(prefs):
    feats = PropertyFeatures(garage=absent(), driveway=absent(), laundry=present())
    r = check(make_property(features=feats), prefs)
    assert r.status is FilterStatus.REJECTED
    assert "No garage or driveway" in r.rejections


def test_parking_unknown_needs_verification(prefs):
    feats = PropertyFeatures(laundry=present())
    r = check(make_property(features=feats), prefs)
    assert r.status is FilterStatus.NEEDS_VERIFICATION
    assert "garage or driveway" in r.unverified


def test_laundry_unknown_needs_verification(prefs):
    feats = PropertyFeatures(garage=present(), laundry=Feature())
    r = check(make_property(features=feats), prefs)
    assert r.status is FilterStatus.NEEDS_VERIFICATION
    assert r.unverified == ["laundry"]


def test_no_laundry_rejected(prefs):
    feats = PropertyFeatures(garage=present(), laundry=absent())
    assert check(make_property(features=feats), prefs).status is FilterStatus.REJECTED


def test_rejection_wins_over_unknowns(prefs):
    feats = PropertyFeatures()
    r = check(make_property(price=1_000_000, features=feats), prefs)
    assert r.status is FilterStatus.REJECTED
    assert "laundry" in r.unverified


def test_townhouse_rejected(prefs):
    # Confirmed by user 2026-11-20: townhouses are excluded, not treated as single-family.
    r = check(make_property(property_type=PropertyType.TOWNHOUSE), prefs)
    assert r.status is FilterStatus.REJECTED
