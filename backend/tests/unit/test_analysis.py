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
    assert p.features.basement_bathroom.source is FeatureSource.LLM
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
    assert est.status == "not_estimated" and "límite mensual" in est.reason
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
    from app.models.analysis import DriveEstimate

    p = p.model_copy(update={
        "commute": estimate_commute(p, SearchPreferences(), FakeStops(400)),
        "drives": [DriveEstimate(destination="576 Bergen Blvd", address="576 Bergen Blvd, Ridgefield, NJ 07657", minutes=10, miles=3.0)],
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
    p = scored_property().model_copy(update={"rent_estimate": None, "commute": None, "drives": []})
    a = score_property(p, SearchPreferences(), RATE)
    by = {c.name: c for c in a.categories}
    assert by["rental_potential"].score is None and by["location_commute"].score is None
    assert by["affordability"].score is None  # multifamily without rent can't be judged
    assert a.confidence == pytest.approx(0.30)
    assert any("Sin puntuar todavía" in line for line in a.explanation)


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


def test_rentcast_auth_failure_stops_further_requests():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(401, json={"error": "auth/api-key-invalid"})

    client, _ = rentcast(handler)
    p = apply_analysis(mf(), llm_result(), model="m")
    first = client.estimate(p, OwnerUnit.LARGEST)
    second = client.estimate(p, OwnerUnit.LARGEST)
    assert first.status == second.status == "not_estimated"
    assert "clave API rechazada" in first.reason
    assert len(calls) == 1  # second property never hits the API


def test_gtfs_finder_uses_ny_bound_bus_stops_and_rail(tmp_path):
    import json as _json
    from app.services.commute import GtfsStopFinder

    f = tmp_path / "stops.json"
    f.write_text(_json.dumps({
        "bus_ny_bound": [{"name": "Far St", "lat": 40.81, "lon": -74.1, "routes": ["156"]},
                         {"name": "Near St", "lat": 40.8005, "lon": -74.1, "routes": ["159", "156"]}],
        "rail": [{"name": "Lyndhurst", "lat": 40.802, "lon": -74.1}],
    }))
    finder = GtfsStopFinder(f)
    name, meters = finder.nearest(40.8, -74.1, "bus")
    assert name.startswith("Near St (autobús 159, 156)") and 50 < meters < 60
    assert finder.nearest(40.8, -74.1, "rail")[0] == "estación Lyndhurst"
    assert finder.nearest(41.5, -74.1, "bus") is None  # nothing within radius


def test_real_gtfs_extract_has_stops_near_each_town():
    from app.services.commute import GtfsStopFinder

    finder = GtfsStopFinder()
    centers = {"Cliffside Park": (40.8215, -73.9879), "Fairview": (40.8126, -73.9990),
               "Elmwood Park": (40.9040, -74.1185), "Saddle Brook": (40.8990, -74.0929)}
    for town, (lat, lon) in centers.items():
        found = finder.nearest(lat, lon, "bus")
        assert found and found[1] < 1200, town  # rough town-center coordinates
    assert finder.nearest(40.8142, -74.1227, "rail")[0] == "estación Lyndhurst"


def test_failed_stop_lookup_is_reported():
    class Broken:
        def nearest(self, *a):
            raise RuntimeError("all servers down")

    c = estimate_commute(mf(), SearchPreferences(), Broken())
    assert c.total_minutes is None and c.nearest_stop.startswith("lookup failed")


# ---- live-run regressions (2026-11-20) -------------------------------------------------

def test_real_quote_about_wrong_thing_is_rejected():
    text = "With 2 bedrooms, the first-floor unit offers even more room to spread out, with full access to the yard."
    p = mf(description=text)
    r = llm_result(units=[], garage=U(), laundry=U(), finished_basement=U(), outdoor_space=U(),
                   basement_bathroom=U("present", "the first-floor unit offers even more room to spread out"), red_flags=[])
    out = apply_analysis(p, r, model="m")
    assert out.features.basement_bathroom.state is FeatureState.UNKNOWN
    assert "not about basement_bathroom" in out.llm_analysis.rejected_claims[0]


def test_absent_from_silence_is_rejected_and_single_family_not_wrongly_rejected():
    text = "The finished basement offers a large rec room, laundry room/work room and storage."
    sf = make_property(property_type=PropertyType.SINGLE_FAMILY, units=1, description=text,
                       features=PropertyFeatures(garage=present(), laundry=present(), finished_basement=present()))
    r = llm_result(units=[], garage=U(), laundry=U(), finished_basement=U(), outdoor_space=U(), red_flags=[],
                   basement_bathroom=U("absent", "The finished basement offers a large rec room"))
    out = apply_analysis(sf, r, model="m")
    assert out.features.basement_bathroom.state is FeatureState.UNKNOWN
    assert apply_hard_filters(out, SearchPreferences(), TODAY).status is FilterStatus.NEEDS_VERIFICATION


def test_explicit_negation_still_counts_as_absent():
    text = "Large basement, no bathroom in the basement."
    r = llm_result(units=[], garage=U(), laundry=U(), finished_basement=U(), outdoor_space=U(), red_flags=[],
                   basement_bathroom=U("absent", "no bathroom in the basement"))
    out = apply_analysis(mf(description=text), r, model="m")
    assert out.features.basement_bathroom.state is FeatureState.ABSENT


def test_basement_suite_is_not_counted_as_rental_unit():
    text = ("First floor offers 3 bedrooms and 1 bath. Second floor offers 3 bedrooms and 1 bath. "
            "Ground level guest suite with 1 bedroom and 1 bath.")
    p = mf(description=text, units=2, units_evidence="MLS structure type: 2 Family")
    r = llm_result(red_flags=[], garage=U(), laundry=U(), finished_basement=U(), basement_bathroom=U(), outdoor_space=U(),
                   units=[UnitLayout(label="ground level guest suite", bedrooms=1, bathrooms=1, quote="Ground level guest suite with 1 bedroom and 1 bath"),
                          UnitLayout(label="first floor", bedrooms=3, bathrooms=1, quote="First floor offers 3 bedrooms and 1 bath"),
                          UnitLayout(label="second floor", bedrooms=3, bathrooms=1, quote="Second floor offers 3 bedrooms and 1 bath")])
    out = apply_analysis(p, r, model="m")
    assert [u.label for u in out.llm_analysis.units] == ["first floor", "second floor"]
    owner, rentals = rental_units(out, OwnerUnit.LARGEST)
    assert len(rentals) == 1


def test_unit_without_bedrooms_is_not_priced():
    p = mf().model_copy(update={"units": 2})
    r = llm_result(units=[UnitLayout(label="first unit", quote="Spacious two-family home"),
                          UnitLayout(label="second unit", quote="Spacious two-family home")])
    assert rental_units(apply_analysis(p, r, model="m"), OwnerUnit.LARGEST) is None


def test_outdated_analysis_is_redone_from_scratch():
    from app.models.analysis import LLMAnalysis
    from app.models.property import Feature, FeatureSource
    from app.services.description_analysis import analyze_description

    stale = mf().model_copy(update={
        "features": PropertyFeatures(
            garage=Feature(state=FeatureState.PRESENT, source=FeatureSource.PROVIDER, evidence="MLS"),
            basement_bathroom=Feature(state=FeatureState.ABSENT, source=FeatureSource.DESCRIPTION, evidence="wrong"),
        ),
        "llm_analysis": LLMAnalysis(model="m", prompt_version="desc-v1"),
    })
    llm = FakeLLM()
    out = analyze_description(stale, llm, model="m")
    assert llm.calls == 1
    assert out.features.garage.evidence == "MLS"  # provider fact kept
    assert out.features.basement_bathroom.state is FeatureState.PRESENT  # wrong v1 value replaced


def test_property_rejected_by_outdated_analysis_gets_reanalyzed():
    from app.models.analysis import LLMAnalysis
    from app.models.property import Feature

    sf = make_property(
        property_type=PropertyType.SINGLE_FAMILY, units=1, description=DESC,
        features=PropertyFeatures(garage=present(), laundry=present(), finished_basement=present(),
                                  basement_bathroom=Feature(state=FeatureState.ABSENT, source=FeatureSource.DESCRIPTION, evidence="wrong")),
        llm_analysis=LLMAnalysis(model="m", prompt_version="desc-v1"),
    )
    prefs = SearchPreferences()
    ev = EvaluatedProperty(sf, apply_hard_filters(sf, prefs, TODAY))
    assert ev.filter.status is FilterStatus.REJECTED
    llm = FakeLLM()
    run = DiscoveryRun(id="r", started_at=None, status="succeeded", results=[ev])
    run_analysis(run, prefs, AnalysisDeps(llm=llm, llm_model="m", rentcast=None, stops=FakeStops(), rate=RATE, today=TODAY))
    assert llm.calls == 1
    assert run.results[0].filter.status is FilterStatus.ELIGIBLE


# ---- Ridgefield driving, rate per scenario, discarded homes (2026-11-20) -----------------

class FakeRouter:
    def __init__(self, minutes=3.2, miles=1.2):
        self.calls, self.minutes, self.miles = 0, minutes, miles

    def drive(self, lat, lon, dlat, dlon):
        self.calls += 1
        return self.minutes, self.miles


def test_drive_time_to_ridgefield_computed_once():
    from app.services.driving import estimate_drives

    router = FakeRouter()
    p = mf()
    drives = estimate_drives(p, SearchPreferences(), router)
    assert [(d.destination, d.minutes, d.miles) for d in drives] == [("576 Bergen Blvd", 3, 1.2)]
    again = estimate_drives(p.model_copy(update={"drives": drives}), SearchPreferences(), router)
    assert router.calls == 1 and again == drives


def test_commute_score_is_ridgefield_drive_only():
    from app.models.analysis import DriveEstimate

    p = scored_property()  # 10 min drive -> (35-10)/30*10 = 8.3
    cat = lambda prop, prefs=SearchPreferences(): next(c for c in score_property(prop, prefs, RATE).categories if c.name == "location_commute")
    assert cat(p).score == pytest.approx(8.3, abs=0.05)
    assert "WTC" not in cat(p).reason and "en auto a 576 Bergen Blvd" in cat(p).reason
    assert cat(p.model_copy(update={"drives": []})).score is None  # unknown -> not scored


def test_transit_destination_still_supported_if_added_back():
    from app.models.preferences import CommuteDestination

    prefs = SearchPreferences()
    prefs = prefs.model_copy(update={"commute_destinations": [
        CommuteDestination(label="7 WTC", address="7 WTC, New York, NY"), *prefs.commute_destinations]})
    c = next(c for c in score_property(scored_property(), prefs, RATE).categories if c.name == "location_commute")
    assert c.score == pytest.approx((7.6 + 8.3) / 2, abs=0.1)


def test_locationiq_errors_never_leak_key_and_fallback_used():
    from app.services.driving import FallbackRouter, LocationIQRouter, OsrmRouter

    liq = LocationIQRouter("SECRETKEY123", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401))))
    osrm = OsrmRouter(client=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"code": "Ok", "routes": [{"duration": 600, "distance": 4828}]}))))
    fb = FallbackRouter(liq, osrm)
    minutes, miles = fb.drive(40.8, -74.0, 40.83, -73.99)
    assert round(minutes) == 10 and round(miles, 1) == 3.0 and fb.last_used == "osrm"
    try:
        liq.drive(40.8, -74.0, 40.83, -73.99)
    except RuntimeError as exc:
        assert "SECRETKEY123" not in str(exc)


def test_switching_to_locationiq_recomputes_osrm_times_once():
    from app.models.analysis import DriveEstimate
    from app.services.driving import estimate_drives

    class Liq(FakeRouter):
        name = "locationiq"

    old = [DriveEstimate(destination="576 Bergen Blvd", address="576 Bergen Blvd, Ridgefield, NJ 07657", minutes=4, miles=1.0, source="osrm")]
    router = Liq(minutes=5.0, miles=1.3)
    fresh = estimate_drives(mf().model_copy(update={"drives": old}), SearchPreferences(), router)
    assert router.calls == 1 and fresh[0].source == "locationiq" and fresh[0].minutes == 5
    estimate_drives(mf().model_copy(update={"drives": fresh}), SearchPreferences(), router)
    assert router.calls == 1


def test_scenarios_report_interest_rate_used():
    a = score_property(scored_property(), SearchPreferences(), RATE)
    assert a.finance["conventional_20"].annual_rate == pytest.approx(0.06)
    assert a.finance["fha_3_5"].annual_rate == pytest.approx(0.0575)  # FHA adjustment -0.25%


def test_discarded_home_not_ranked_and_next_one_moves_up():
    good = mf(external_id="a", features=PropertyFeatures(garage=present(), laundry=present()))
    cheaper = mf(external_id="b", price=600_000, features=PropertyFeatures(garage=present(), laundry=present()))
    prefs = SearchPreferences()
    run = DiscoveryRun(id="r", started_at=None, status="succeeded",
                       results=[EvaluatedProperty(p, apply_hard_filters(p, prefs, TODAY)) for p in (good, cheaper)])
    deps = AnalysisDeps(llm=FakeLLM(), llm_model="m", rentcast=None, stops=FakeStops(), rate=RATE, today=TODAY,
                        rejected_keys={("test", "b")})
    run = run_analysis(run, prefs, deps)
    assert {ev.property.external_id: ev.rank for ev in run.results} == {"a": 1, "b": None}


def test_locationiq_paces_and_retries_rate_limit():
    from app.services.driving import LocationIQRouter

    responses = iter([httpx.Response(429), httpx.Response(200, json={"code": "Ok", "routes": [{"duration": 120, "distance": 1609}]})])
    slept = []
    liq = LocationIQRouter("k", client=httpx.Client(transport=httpx.MockTransport(lambda r: next(responses))),
                           sleep=slept.append, clock=lambda: 0.0)
    minutes, _ = liq.drive(40.8, -74.0, 40.83, -73.99)
    assert minutes == 2 and any(s >= 1.5 for s in slept)
