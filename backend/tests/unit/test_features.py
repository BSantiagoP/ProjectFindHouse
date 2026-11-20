import pytest

from app.models.property import FeatureState, PropertyType
from app.services.features import apply_description_features, extract_units
from tests.conftest import make_property
from app.models.property import PropertyFeatures


def feats(description: str, **kw):
    prop = make_property(description=description, features=PropertyFeatures(), units=None, **kw)
    return apply_description_features(prop)


def test_garage_and_laundry_present_with_evidence():
    p = feats("Detached 1-car garage. Shared laundry in the basement.")
    assert p.features.garage.state is FeatureState.PRESENT
    assert "garage" in p.features.garage.evidence
    assert p.features.laundry.state is FeatureState.PRESENT


def test_negated_garage_is_absent():
    p = feats("Charming home with no garage but a long driveway.")
    assert p.features.garage.state is FeatureState.ABSENT
    assert p.features.driveway.state is FeatureState.PRESENT


def test_negation_covers_or_list():
    p = feats("Sold as-is: no garage or driveway.")
    assert p.features.garage.state is FeatureState.ABSENT
    assert p.features.driveway.state is FeatureState.ABSENT


def test_street_parking_only():
    p = feats("Street parking only.")
    assert p.features.garage.state is FeatureState.ABSENT
    assert p.features.driveway.state is FeatureState.ABSENT


def test_hookups_count_as_laundry():
    assert feats("Washer/dryer hookups in each unit.").features.laundry.state is FeatureState.PRESENT


def test_laundromat_is_not_laundry():
    assert feats("Walk to the laundromat.").features.laundry.state is FeatureState.UNKNOWN


def test_unfinished_basement_absent():
    assert feats("Unfinished basement.").features.finished_basement.state is FeatureState.ABSENT


def test_partially_finished_basement_stays_unknown_with_evidence():
    f = feats("Partially finished basement.").features.finished_basement
    assert f.state is FeatureState.UNKNOWN
    assert f.evidence


def test_finished_basement_with_bath():
    p = feats("Fully finished basement with a full bathroom and laundry room.")
    assert p.features.finished_basement.state is FeatureState.PRESENT
    assert p.features.basement_bathroom.state is FeatureState.PRESENT


def test_bath_in_same_sentence_but_not_basement_is_not_matched():
    p = feats("Full basement, 3 bedrooms and 2 baths upstairs.")
    assert p.features.basement_bathroom.state is FeatureState.UNKNOWN


def test_unknown_when_not_mentioned():
    p = feats("Lovely home near the park.")
    assert all(getattr(p.features, n).state is FeatureState.UNKNOWN for n in PropertyFeatures.model_fields)


def test_does_not_override_known_state():
    prop = make_property(description="No garage.")  # make_property sets garage PRESENT
    assert apply_description_features(prop).features.garage.state is FeatureState.PRESENT


@pytest.mark.parametrize(
    "text,units",
    [("Two-family home", 2), ("3 family", 3), ("Rare 5-unit building", 5), ("Classic duplex", 2), ("A 4-unit gem", 4)],
)
def test_extract_units(text, units):
    assert extract_units(text)[0] == units


def test_single_family_units_default_to_one():
    p = feats("Colonial.", property_type=PropertyType.SINGLE_FAMILY)
    assert p.units == 1
