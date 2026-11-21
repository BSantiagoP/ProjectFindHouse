"""Suggested offer: comparable selection, max affordable price, candidate choice validation, caching."""

import httpx
import pytest

from app.models.analysis import OfferChoice, RentEstimate, SoldComp, UnitRent
from app.models.preferences import SearchPreferences
from app.providers.base import RequestBudget
from app.providers.hasdata import HasDataProvider
from app.repositories.memory import MemoryRepository
from app.services.discovery import EvaluatedProperty
from app.services.filtering import FilterResult, FilterStatus
from app.services.offer import (
    SoldCompsService, build_candidates, max_affordable_price, select_comps, suggest_offer,
)
from app.services.rates import MortgageRate
from app.services.scoring import score_property
from tests.conftest import make_property

RATE = MortgageRate(0.0728, None, "t")
PREFS = SearchPreferences(target_monthly_cost=4000)


def subject(**kw):
    base = dict(price=850_000, units=2, beds=5, baths=3, latitude=40.8126, longitude=-73.9990, annual_tax=14_000,
                rent_estimate=RentEstimate(status="estimated", monthly_rent_total=2_700,
                                           rental_units=[UnitRent(label="2F", bedrooms=2, bathrooms=1, rent=2_700)]))
    return make_property(**(base | kw))


def comp(addr, price, lat=40.8130, lon=-73.9985, beds=5, days=100):
    return SoldComp(address=f"{addr}, Fairview, NJ 07022", price=price, beds=beds, latitude=lat, longitude=lon, days_since_sold=days)


SOLD = [comp("1 A St", 700_000), comp("2 B St", 760_000), comp("3 C St", 800_000), comp("4 D St", 840_000),
        comp("Far St", 2_000_000, lat=40.90), comp("Old St", 500_000, days=900), comp("Tiny St", 400_000, beds=1)]


def ev(p=None):
    p = p or subject()
    return EvaluatedProperty(p, FilterResult(FilterStatus.ELIGIBLE), property_id="pid", rank=1,
                             analysis=score_property(p, PREFS, RATE))


class FakeLLM:
    def __init__(self, *choices):
        self.choices, self.calls = list(choices), 0

    def parse_offer(self, *, instructions, text):
        self.calls += 1
        return self.choices[min(self.calls - 1, len(self.choices) - 1)]


def choice(o="comparables_bajo", t="comparables_mediana", w="lista_menos_5", win="precio_lista", **kw):
    return OfferChoice(opening_key=o, target_key=t, walk_away_key=w, win_key=win,
                       win_reason="Lleva pocos días en el mercado y la lista es $850,000.",
                       rationale=["La mediana de comparables es $780,000."], risks=["Confirmar con un agente."], **kw)


def test_select_comps_filters_distance_age_size():
    picked = select_comps(subject(), SOLD)
    assert [c.address.split(",")[0] for c in picked] == ["1 A St", "2 B St", "3 C St", "4 D St"]
    assert all(c.distance_mi is not None and c.distance_mi < 1.5 for c in picked)


def test_max_affordable_price_meets_target():
    from app.services.finance import CostInputs, evaluate_scenario, DEFAULT_SCENARIOS
    from app.services.scoring import scenarios_for

    p = subject()
    m = max_affordable_price(p, PREFS, RATE)
    s = next(x for x in DEFAULT_SCENARIOS if x.name == PREFS.primary_scenario)
    _, rates = scenarios_for(RATE, PREFS)
    cost = lambda price: evaluate_scenario(CostInputs(price=price, annual_rate=rates[s.name], annual_tax=14_000,
                                                      annual_insurance=PREFS.annual_insurance, monthly_gross_rent=2_700), s).effective_owner_cost
    assert cost(m) <= 4000 + 15 and cost(m + 10_000) > 4000
    assert max_affordable_price(subject(rent_estimate=None), PREFS, RATE) is None  # multifamily needs rent


def test_candidates_are_rounded_and_labeled():
    cand, labels = build_candidates(subject(), select_comps(subject(), SOLD), 600_000)
    assert cand["precio_lista"] == 850_000 and cand["lista_menos_5"] == 808_000
    assert cand["comparables_mediana"] == 780_000 and cand["maximo_para_meta_mensual"] == 600_000
    assert all(v % 1000 == 0 for v in cand.values()) and set(labels) == set(cand)


def test_offer_uses_model_choice_among_computed_prices():
    o = suggest_offer(ev(), PREFS, RATE, SOLD, FakeLLM(choice()), model="m")
    assert o.status == "ok" and (o.opening, o.target, o.walk_away) == (o.candidates["comparables_bajo"], 780_000, 808_000)
    assert len(o.comps) == 4


def test_out_of_order_choice_is_sorted_not_discarded():
    o = suggest_offer(ev(), PREFS, RATE, SOLD, FakeLLM(choice(o="precio_lista", t="comparables_bajo", w="lista_menos_8")), model="m")
    assert o.status == "ok" and o.order_adjusted
    assert o.opening <= o.target <= o.walk_away
    assert (o.opening_key, o.walk_away_key) == ("comparables_bajo", "precio_lista")


def test_invalid_keys_or_numbers_are_rejected_then_retried():
    invented = OfferChoice(opening_key="comparables_bajo", target_key="comparables_mediana", walk_away_key="lista_menos_5",
                           win_key="precio_lista", win_reason="Ok.", rationale=["Ofrece $123,456."], risks=[])
    o = suggest_offer(ev(), PREFS, RATE, SOLD, FakeLLM(invented, invented), model="m")
    assert o.status == "error" and o.opening is None
    unknown = choice(o="precio_inventado")
    assert suggest_offer(ev(), PREFS, RATE, SOLD, FakeLLM(unknown, unknown), model="m").status == "error"


def test_not_enough_comps_makes_no_model_call():
    llm = FakeLLM(choice())
    o = suggest_offer(ev(), PREFS, RATE, SOLD[:2], llm, model="m")
    assert o.status == "not_enough_comps" and llm.calls == 0


def test_cached_offer_reused_until_facts_change():
    e = ev()
    llm = FakeLLM(choice())
    e.property = e.property.model_copy(update={"offer": suggest_offer(e, PREFS, RATE, SOLD, llm, model="m")})
    suggest_offer(e, PREFS, RATE, SOLD, llm, model="m")
    assert llm.calls == 1


def test_sold_comps_cached_per_town_for_a_week():
    calls = []

    def handler(req):
        calls.append(req.url.params["type"])
        return httpx.Response(200, json={"properties": [
            {"id": "1", "url": "u", "price": 700000, "addressRaw": "1 A St, Fairview, NJ 07022", "latitude": 40.81, "longitude": -74.0, "daysOnZillow": 30},
            {"id": "2", "url": "u", "price": 700000, "addressRaw": "1 A St APT 2, Fairview, NJ 07022", "latitude": 40.81, "longitude": -74.0},
        ]})

    prov = HasDataProvider("k", client=httpx.Client(base_url="https://api.hasdata.com", transport=httpx.MockTransport(handler)))
    svc = SoldCompsService(MemoryRepository(), prov)
    first = svc.get("Fairview", "NJ", "multiFamily")
    svc.get("Fairview", "NJ", "multiFamily")
    assert calls == ["sold"] and len(first) == 1  # unit duplicate merged; second call cached


def test_facts_list_candidates_sorted_and_explain_missing_max():
    from app.services.offer import build_offer_facts

    e = ev(subject(rent_estimate=None))
    comps = select_comps(e.property, SOLD)
    cand, labels = build_candidates(e.property, comps, None)
    f = build_offer_facts(e, PREFS, comps, cand, labels)
    prices = [int(c["precio"].strip("$").replace(",", "")) for c in f["precios_candidatos"]]
    assert prices == sorted(prices)
    assert f["casa"]["precio_maximo_para_meta_mensual"].startswith("no calculable")


def test_price_to_win_with_monthly_cost_and_budget_flag():
    from app.services.offer import monthly_cost_at

    o = suggest_offer(ev(), PREFS, RATE, SOLD, FakeLLM(choice(win="lista_mas_3")), model="m")
    assert o.win_price == 876_000 and o.win_key == "lista_mas_3"
    assert o.win_monthly_cost == monthly_cost_at(subject(), PREFS, RATE, 876_000)
    assert o.win_over_budget is True  # above the max price for $4,000/month
    bad = choice(win="ganar_a_toda_costa")
    assert suggest_offer(ev(), PREFS, RATE, SOLD, FakeLLM(bad, bad), model="m").status == "error"


def test_win_finance_has_all_scenarios_at_win_price():
    from app.services.offer import attach_win_finance

    o = attach_win_finance(suggest_offer(ev(), PREFS, RATE, SOLD, FakeLLM(choice(win="lista_mas_3")), model="m"), subject(), PREFS, RATE)
    assert set(o.win_finance) == {"fha_3_5", "conventional_5", "conventional_20"}
    c20 = o.win_finance["conventional_20"]
    assert c20["down_payment"] == 876_000 * 0.20 and c20["effective_owner_cost"] == pytest.approx(o.win_monthly_cost, abs=1)
