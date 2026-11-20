"""Photo analysis: triage -> select <=10 -> inspect; presence-only, citation validation."""

from app.models.analysis import Condition, PhotoFinding, PhotoFindings, PhotoLabel, PhotoTriage, Room
from app.models.property import FeatureSource, FeatureState, PropertyFeatures, PropertyType
from app.services.photo_analysis import MAX_DETAILED, analyze_photos, select_photos, unknown_targets
from tests.conftest import absent, make_property, present

UNK = PhotoFinding(state="unknown")


def photos(n):
    return [f"https://photos.example/{i}.jpg" for i in range(1, n + 1)]


class FakeVision:
    model = "fake"

    def __init__(self, triage, findings):
        self.triage, self.findings, self.calls = triage, findings, []

    def parse_images(self, *, instructions, text, image_urls, detail, schema):
        self.calls.append((detail, list(image_urls), text))
        return self.triage if schema is PhotoTriage else self.findings


def findings(**kw):
    base = dict(garage=UNK, driveway=UNK, laundry=UNK, finished_basement=UNK, basement_bathroom=UNK,
                outdoor_space=UNK, condition=Condition.UNKNOWN)
    return PhotoFindings(**(base | kw))


def sf_needing_bath():
    return make_property(
        property_type=PropertyType.SINGLE_FAMILY, units=1, photo_urls=photos(30),
        features=PropertyFeatures(garage=present(), laundry=present(), finished_basement=present(), outdoor_space=present()),
    )


TRIAGE = PhotoTriage(photos=[PhotoLabel(index=i, rooms=[Room.BEDROOM]) for i in range(1, 31)]
                     [:25] + [PhotoLabel(index=26, rooms=[Room.BASEMENT]), PhotoLabel(index=27, rooms=[Room.BASEMENT, Room.BATHROOM]),
                              PhotoLabel(index=28, rooms=[Room.KITCHEN]), PhotoLabel(index=29, rooms=[Room.BATHROOM]),
                              PhotoLabel(index=30, rooms=[Room.EXTERIOR_FRONT])])


def test_targets_only_unknowns():
    p = sf_needing_bath()
    assert unknown_targets(p) == ["basement_bathroom", "condition"]
    assert "laundry" in unknown_targets(make_property(features=PropertyFeatures(garage=present())))


def test_nothing_unknown_makes_no_calls():
    p = sf_needing_bath().model_copy(update={"features": PropertyFeatures(
        garage=present(), laundry=present(), finished_basement=present(), basement_bathroom=present(), outdoor_space=present())})
    from app.models.analysis import LLMAnalysis
    p = p.model_copy(update={"llm_analysis": LLMAnalysis(model="m", prompt_version="x", condition=Condition.UPDATED)})
    v = FakeVision(TRIAGE, findings())
    out = analyze_photos(p, v)
    assert v.calls == [] and out.photo_analysis.skipped_reason == "Nothing unknown"


def test_triage_low_then_at_most_ten_relevant_high():
    many = PhotoTriage(photos=[PhotoLabel(index=i, rooms=[Room.BASEMENT]) for i in range(1, 31)])
    assert len(select_photos(many, ["basement_bathroom"], 30)) == MAX_DETAILED
    v = FakeVision(TRIAGE, findings())
    analyze_photos(sf_needing_bath(), v)
    (d1, u1, _), (d2, u2, _) = v.calls
    assert d1 == "low" and len(u1) == 30
    assert d2 == "high" and u2 == [photos(30)[i] for i in (25, 26, 27, 28)]  # basement x2, kitchen, bathroom


def test_valid_presence_is_accepted_with_photo_evidence():
    f = findings(basement_bathroom=PhotoFinding(state="present", photo_numbers=[2], observation="toilet and shower in basement", confidence="high"))
    out = analyze_photos(sf_needing_bath(), FakeVision(TRIAGE, f))
    feat = out.features.basement_bathroom
    assert feat.state is FeatureState.PRESENT and feat.source is FeatureSource.PHOTOS
    assert feat.evidence.startswith("Photo 27:")  # mapped back to the listing's photo number
    assert out.photo_analysis.accepted == ["basement_bathroom"]


def test_low_confidence_and_wrong_room_citations_rejected():
    f = findings(basement_bathroom=PhotoFinding(state="present", photo_numbers=[3], observation="bath", confidence="high"))
    out = analyze_photos(sf_needing_bath(), FakeVision(TRIAGE, f))  # photo 3 in pass 2 = kitchen
    assert out.features.basement_bathroom.state is FeatureState.UNKNOWN
    f2 = findings(basement_bathroom=PhotoFinding(state="present", photo_numbers=[2], confidence="low"))
    out2 = analyze_photos(sf_needing_bath(), FakeVision(TRIAGE, f2))
    assert out2.features.basement_bathroom.state is FeatureState.UNKNOWN
    f3 = findings(basement_bathroom=PhotoFinding(state="present", photo_numbers=[99], confidence="high"))
    out3 = analyze_photos(sf_needing_bath(), FakeVision(TRIAGE, f3))
    assert out3.features.basement_bathroom.state is FeatureState.UNKNOWN
    assert len(out3.photo_analysis.rejected) == 1


def test_photos_never_mark_absent_or_override_known():
    p = make_property(photo_urls=photos(5), features=PropertyFeatures(garage=absent("MLS"), laundry=present()))
    tri = PhotoTriage(photos=[PhotoLabel(index=i, rooms=[Room.GARAGE]) for i in range(1, 6)])
    f = findings(garage=PhotoFinding(state="present", photo_numbers=[1], confidence="high"))
    out = analyze_photos(p, FakeVision(tri, f))
    assert out.features.garage.state is FeatureState.ABSENT  # MLS fact kept


def test_condition_from_photos_skipped_when_virtually_staged():
    p = sf_needing_bath().model_copy(update={"description": "Photos have been virtually staged."})
    f = findings(condition=Condition.MOVE_IN_READY, condition_photo_numbers=[3])
    v = FakeVision(TRIAGE, f)
    out = analyze_photos(p, v)
    assert out.photo_analysis.condition is Condition.UNKNOWN
    assert "condition" not in v.calls[1][2]


def test_condition_from_photos_scored_and_labeled():
    from app.models.preferences import SearchPreferences
    from app.services.rates import MortgageRate
    from app.services.scoring import score_property

    f = findings(condition=Condition.UPDATED, condition_photo_numbers=[3], condition_observation="new cabinets")
    out = analyze_photos(sf_needing_bath(), FakeVision(TRIAGE, f))
    a = score_property(out, SearchPreferences(), MortgageRate(0.06, None, "t"))
    cond = next(c for c in a.categories if c.name == "condition")
    assert cond.score == 8 and "(from photos)" in cond.reason and "Photo 28" in cond.reason


def test_cached_photo_analysis_not_repeated():
    v = FakeVision(TRIAGE, findings())
    once = analyze_photos(sf_needing_bath(), v)
    analyze_photos(once, v)
    assert len(v.calls) == 2  # triage + inspect, only the first time


def test_medium_confidence_cannot_satisfy_single_family_requirement():
    f = findings(basement_bathroom=PhotoFinding(state="present", photo_numbers=[2], observation="bath appears below grade", confidence="medium"))
    out = analyze_photos(sf_needing_bath(), FakeVision(TRIAGE, f))
    assert out.features.basement_bathroom.state is FeatureState.UNKNOWN
    assert out.photo_analysis.likely and out.photo_analysis.likely[0].startswith("basement_bathroom")


def test_medium_confidence_ok_for_multifamily_preference():
    mf = make_property(photo_urls=photos(30), features=PropertyFeatures(garage=present(), laundry=present(), outdoor_space=present(), finished_basement=present()))
    f = findings(basement_bathroom=PhotoFinding(state="present", photo_numbers=[2], confidence="medium"))
    out = analyze_photos(mf, FakeVision(TRIAGE, f))
    assert out.features.basement_bathroom.state is FeatureState.PRESENT


def test_rule_change_reapplies_stored_findings_without_api_calls():
    f = findings(basement_bathroom=PhotoFinding(state="present", photo_numbers=[2], confidence="medium"))
    v = FakeVision(TRIAGE, f)
    out = analyze_photos(sf_needing_bath(), v)
    stale = out.model_copy(update={"photo_analysis": out.photo_analysis.model_copy(update={"version": "photo-v1"})})
    again = analyze_photos(stale, v)
    assert len(v.calls) == 2  # no new calls
    assert again.photo_analysis.version != "photo-v1" and again.photo_analysis.likely
