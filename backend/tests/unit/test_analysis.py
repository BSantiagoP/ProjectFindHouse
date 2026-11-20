"""Milestone 3: grounding checks, rent per rental unit with cap, commute, scoring, graph."""

import httpx
import pytest

from app.agents.graph import AnalysisDeps, run_analysis
from app.models.analysis import Condition, DescriptionAnalysis, QuotedFinding, UnitLayout
from app.models.preferences import OwnerUnit, SearchPreferences
from app.models.property import FeatureSource, FeatureState, PropertyFeatures, PropertyType
from app.providers.rentcast import RentCastClient, rental_units
from app.repositories.memory import MemoryRepository
from app.services.commute import estimate_commute
from app.services.description_analysis import apply_analysis, quote_supported
from app.services.discovery import DiscoveryRun, EvaluatedProperty
from app.services.filtering import FilterStatus, apply_hard_filters
from app.services.rates import MortgageRate, parse_fred_csv
from app.services.scoring import score_property
from tests.conftest import TODAY, make_property, present

DESC = (
    "Spacious two-family home. The first-floor unit features 3 bedrooms and 2 full bathrooms. "
    "The second-floor apartment offers 2 bedrooms and 1 full bathroom. Fully finished basement "
    "featuring a summer kitchen, full bathroom, and laundry room. Attached two-car garage. "
    "Fenced-in backyard. Sold as-is."
)
U = lambda s="unknown", q=None: QuotedFinding(state=s, quote=q)


def llm_result(**overrides) -> DescriptionAnalysis:
    base = dict(
        units=[
            UnitLayout(label="first floor", bedrooms=3, bathrooms=2, quote="first-floor unit features 3 bedrooms and 2 full bathrooms"),
            UnitLayout(label="second floor", bedrooms=2, bathrooms=1, quote="second-floor apartment offers 2 bedrooms and 1 full bathroom"),
        ],
        garage=U("present", "Attached two-car garage"),
        driveway=U(),
        laundry=U("present", "laundry room"),
        finished_basement=U("present", "Fully finished basement"),
        basement_bathroom=U("present", "basement featuring a summer kitchen, full bathroom"),
        outdoor_space=U("present", "Fenced-in backyard"),
        separate_utilities=U(),
        tenant_occupied=U(),
        condition=Condition.UNKNOWN,
        red_flags=["Sold as-is"],
        summary="A two-family home.",
    )
    base.update(overrides)
    return DescriptionAnalysis(**base)


def mf(**kw):
    base = dict(description=DESC, units=None, features=PropertyFeatures(), latitude=40.8, longitude=-74.1)
    return make_property(**(base | kw))


# ---- grounding ----------------------------------------------------------------------

def test_quote_check_tolerates_case_and_punctuation_only():
    assert quote_supported("attached TWO-CAR garage.", DESC)
    assert not quote_supported("attached three-car garage", DESC)
    assert not quote_supported("", DESC)


def test_supported_claims_fill_unknown_features_and_units():
    p = apply_analysis(mf(), llm_result(), model="m")
    assert p.features.basement_bathroom.state is FeatureState.PRESENT
    assert p.features.basement_bathroom.source is FeatureSource.DESCRIPTION
    assert p.units == 2
    assert [u.label for u in p.llm_analysis.units] == ["first floor", "second floor"]
    assert p.llm_analysis.red_flags == ["Sold as-is"]
    assert p.llm_analysis.rejected_claims == []


def test_hallucinated_claims_are_dropped():
    result = llm_result(
        driveway=U("present", "Long private driveway"),  # not in text
        units=[UnitLayout(label="unit 3", bedrooms=1, bathrooms=1, quote="third unit with 1 bedroom")],
        condition=Condition.MOVE_IN_READY, condition_quote="move-in ready",
        red_flags=["foreclosure"],
    )
    p = apply_analysis(mf(), result, model="m")
    assert p.features.driveway.state is FeatureState.UNKNOWN
    assert p.llm_analysis.units == [] and p.units is None
    assert p.llm_analysis.condition is Condition.UNKNOWN
    assert p.llm_analysis.red_flags == []
    assert len(p.llm_analysis.rejected_claims) == 3


def test_llm_never_overrides_provider_facts():
    prop = mf().model_copy(update={"features": PropertyFeatures(garage=present("MLS parkingFeatures"))})
    p = apply_analysis(prop, llm_result(garage=U("absent", "Fully finished basement")), model="m")
    assert p.features.garage.evidence == "MLS parkingFeatures"


def test_llm_resolves_single_family_basement_bath():
    sf = make_property(property_type=PropertyType.SINGLE_FAMILY, units=1, description=DESC,
                       features=PropertyFeatures(garage=present(), laundry=present(), finished_basement=present()))
    prefs = SearchPreferences()
    assert apply_hard_filters(sf, prefs, TODAY).status is FilterStatus.NEEDS_VERIFICATION
    p = apply_analysis(sf, llm_result(units=[]), model="m")
    assert apply_hard_filters(p, prefs, TODAY).status is FilterStatus.ELIGIBLE


# ---- rent ---------------------------------------------------------------------------

def rentcast(handler, repo=None, cap=45):
    repo = repo or MemoryRepository()
    client = httpx.Client(base_url="https://api.rentcast.io/v1", transport=httpx.MockTransport(handler))
    return RentCastClient("k", reserve=repo.reserve_api_request, monthly_cap=cap, client=client, today=lambda: TODAY), repo


def test_owner_takes_largest_unit_rent_only_the_rest():
    p = apply_analysis(mf(), llm_result(), model="m")
    owner, units = rental_units(p, OwnerUnit.LARGEST)
    assert owner == "first floor" and [u.label for u in units] == ["second floor"]


def test_rent_requested_per_rental_unit_as_apartment():
    seen = []

    def handler(req):
        seen.append(req.url.params)
        return httpx.Response(200, json={"rent": 2300, "rentRangeLow": 2100, "rentRangeHigh": 2500})

    client, repo = rentcast(handler)
    est = client.estimate(apply_analysis(mf(), llm_result(), model="m"), OwnerUnit.LARGEST)
    assert est.status == "estimated" and est.monthly_rent_total == 2300
    assert len(seen) == 1
    assert seen[0]["propertyType"] == "Apartment" and seen[0]["bedrooms"] == "2"
    assert repo.api_usage[("rentcast", "2026-11")] == 1


def test_rent_cap_blocks_requests():
    calls = []
    client, repo = rentcast(lambda r: calls.append(1) or httpx.Response(200, json={"rent": 1}), cap=0)
    est = client.estimate(apply_analysis(mf(), llm_result(), model="m"), OwnerUnit.LARGEST)
    assert est.status == "not_estimated" and "cap" in est.reason
    assert calls == []


def test_unknown_layout_makes_no_request():
    calls = []
    client, _ = rentcast(lambda r: calls.append(1) or httpx.Response(200, json={"rent": 1}))
    est = client.estimate(mf(), OwnerUnit.LARGEST)
    assert est.status == "not_estimated" and calls == []


# ---- commute, rates -----------------------------------------------------------------

class FakeStops:
    def __init__(self, meters=400):
        self.meters, self.calls = meters, []

    def nearest(self, lat, lon, access):
        self.calls.append(access)
        return ("Ridge Rd at Main", self.meters)


def test_commute_adds_walk_to_town_time_and_uses_rail_in_lyndhurst():
    stops = FakeStops(400)
    c = estimate_commute(mf(), SearchPreferences(), stops)
    assert stops.calls == ["rail"]
    assert c.walk_meters == 500 and c.walk_minutes == 7 and c.total_minutes == 45 + 7


def test_commute_without_coordinates_is_not_rewarded():
    c = estimate_commute(mf().model_copy(update={"latitude": None}), SearchPreferences(), FakeStops())
    assert c.total_minutes is None


def test_parse_fred_csv_skips_missing_values():
    csv_text = "observation_date,MORTGAGE30US\n2026-11-06,6.21\n2026-11-13,6.17\n2026-11-20,.\n"
    r = parse_fred_csv(csv_text)
    assert r.annual_rate == pytest.approx(0.0617) and r.as_of.isoformat() == "2026-11-13"


# ---- scoring ------------------------------------------------------------------------

RATE = MortgageRate(0.06, None, "test")


def scored_property(rent=2300):
    from app.models.analysis import RentEstimate, UnitRent

    p = apply_analysis(mf(price=700_000, annual_tax=12_000), llm_result(condition=Condition.UPDATED,
                                                                         condition_quote="Spacious two-family home"), model="m")
    p = p.model_copy(update={
        "commute": estimate_commute(p, SearchPreferences(), FakeStops(400)),
        "rent_estimate": RentEstimate(status="estimated", rental_units=[UnitRent(label="second floor", bedrooms=2, bathrooms=1, rent=rent)],
                                      monthly_rent_total=rent),
    })
    return p


def test_score_is_weighted_sum_and_fully_confident():
    a = score_property(scored_property(), SearchPreferences(), RATE)
    assert a.confidence == 1.0
    assert a.score == pytest.approx(sum(c.points for c in a.categories), abs=0.1)
    assert set(a.finance) == {"fha_3_5", "conventional_5", "conventional_20"}
    assert a.finance["fha_3_5"].net_rental_contribution == pytest.approx(2300 * 0.8)


def test_unknowns_score_zero_and_lower_confidence():
    p = scored_property().model_copy(update={"rent_estimate": None, "commute": None})
    a = score_property(p, SearchPreferences(), RATE)
    by = {c.name: c for c in a.categories}
    assert by["rental_potential"].score is None and by["location_commute"].score is None
    assert by["affordability"].score is None  # multifamily without rent can't be judged
    assert a.confidence == pytest.approx(0.30)
    assert any("Not yet scored" in line for line in a.explanation)


def test_target_monthly_cost_drives_affordability():
    cheap = score_property(scored_property(), SearchPreferences(target_monthly_cost=6000), RATE)
    tight = score_property(scored_property(), SearchPreferences(target_monthly_cost=3000), RATE)
    aff = lambda a: next(c for c in a.categories if c.name == "affordability").score
    assert aff(cheap) > aff(tight)


# ---- graph --------------------------------------------------------------------------

class FakeLLM:
    def __init__(self):
        self.calls = 0

    def parse(self, *, instructions, text):
        self.calls += 1
        return llm_result(condition=Condition.UPDATED, condition_quote="Spacious two-family home")


def test_graph_analyzes_enriches_scores_and_ranks():
    good = mf(external_id="a", features=PropertyFeatures(garage=present(), laundry=present()))
    cheaper = mf(external_id="b", price=600_000, features=PropertyFeatures(garage=present(), laundry=present()))
    rejected = mf(external_id="c", price=2_000_000)
    prefs = SearchPreferences()
    run = DiscoveryRun(id="r", started_at=None, status="succeeded",
                       results=[EvaluatedProperty(p, apply_hard_filters(p, prefs, TODAY)) for p in (good, cheaper, rejected)])
    llm = FakeLLM()
    client, repo = rentcast(lambda r: httpx.Response(200, json={"rent": 2300}))
    deps = AnalysisDeps(llm=llm, llm_model="m", rentcast=client, stops=FakeStops(), rate=RATE, today=TODAY)

    run = run_analysis(run, prefs, deps)
    ranks = {ev.property.external_id: ev.rank for ev in run.results}
    assert ranks == {"b": 1, "a": 2, "c": None}  # cheaper ranks first; rejected never analyzed
    assert llm.calls == 2
    assert repo.api_usage[("rentcast", "2026-11")] == 2
    assert run.results[2].analysis is None
    assert run.status == "succeeded", run.errors

    # Re-running uses cached analysis/rent: no new LLM or RentCast calls.
    run_analysis(run, prefs, deps)
    assert llm.calls == 2 and repo.api_usage[("rentcast", "2026-11")] == 2


def test_graph_without_llm_reports_and_continues():
    p = mf(features=PropertyFeatures(garage=present(), laundry=present()))
    prefs = SearchPreferences()
    run = DiscoveryRun(id="r", started_at=None, status="succeeded",
                       results=[EvaluatedProperty(p, apply_hard_filters(p, prefs, TODAY))])
    run = run_analysis(run, prefs, AnalysisDeps(llm=None, llm_model="m", rentcast=None, stops=None, rate=RATE, today=TODAY))
    assert run.status == "partial"
    assert run.results[0].analysis is not None  # still scored, with unknowns
