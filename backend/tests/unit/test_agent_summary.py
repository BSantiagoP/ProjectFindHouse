"""Agent summary: grounded numbers, verdict cap, caching by facts hash."""

from app.models.analysis import SummaryOutput
from app.models.preferences import SearchPreferences
from app.services.agent_summary import build_facts, summarize, ungrounded_numbers
from app.services.discovery import EvaluatedProperty
from app.services.filtering import FilterResult, FilterStatus
from app.services.rates import MortgageRate
from app.services.scoring import score_property
from tests.conftest import make_property

PREFS = SearchPreferences(target_monthly_cost=4000)


def ev(status=FilterStatus.ELIGIBLE, **kw):
    p = make_property(price=799_900, units=2, **kw)
    return EvaluatedProperty(p, FilterResult(status, unverified=["lavandería"] if status is FilterStatus.NEEDS_VERIFICATION else []),
                             property_id="pid", analysis=score_property(p, PREFS, MortgageRate(0.0728, None, "t")))


def out(verdict="recomendada", headline="Buena opción a $799,900 en Lyndhurst.", **kw):
    base = dict(verdict=verdict, headline=headline, reasons_for=["Precio de $799,900."],
                reasons_against=["Renta no estimada."], next_steps=["Visitar la casa."])
    return SummaryOutput(**(base | kw))


class FakeLLM:
    def __init__(self, *outs):
        self.outs, self.calls, self.texts = list(outs), 0, []

    def parse_summary(self, *, instructions, text):
        self.calls += 1
        self.texts.append(text)
        return self.outs[min(self.calls - 1, len(self.outs) - 1)]


def test_facts_are_preformatted_and_in_spanish():
    f = build_facts(ev(), PREFS)
    assert f["precio"] == "$799,900" and f["preferencias_usuario"]["meta_mensual_despues_de_renta"] == "$4,000"
    assert f["estado_filtro"] == "elegible" and "posicion_en_ranking" not in f


def test_numbers_must_come_from_facts():
    f = build_facts(ev(), PREFS)
    assert ungrounded_numbers(out(), f) == []
    assert ungrounded_numbers(out(headline="Pagarías $3,200 al mes."), f) == ["$3,200"]
    assert ungrounded_numbers(out(reasons_for=["Cubre el 55% del costo."]), f) == ["55%"]


def test_ungrounded_summary_retried_then_omitted():
    llm = FakeLLM(out(headline="Ahorras $9,999."), out(headline="Ahorras $9,999."))
    assert summarize(ev(), PREFS, llm, model="m") is None and llm.calls == 2
    assert "ATENCIÓN" in llm.texts[1]


def test_retry_succeeds_when_corrected():
    llm = FakeLLM(out(headline="Ahorras $9,999."), out())
    s = summarize(ev(), PREFS, llm, model="m")
    assert s is not None and s.headline.startswith("Buena opción") and llm.calls == 2


def test_cannot_recommend_before_verification():
    s = summarize(ev(FilterStatus.NEEDS_VERIFICATION), PREFS, FakeLLM(out("recomendada")), model="m")
    assert s.verdict == "considerar" and s.verdict_adjusted


def test_cached_until_facts_change():
    e = ev()
    llm = FakeLLM(out())
    e.property = e.property.model_copy(update={"agent_summary": summarize(e, PREFS, llm, model="m")})
    summarize(e, PREFS, llm, model="m")
    assert llm.calls == 1
    summarize(e, SearchPreferences(target_monthly_cost=3000), llm, model="m")  # facts changed
    assert llm.calls == 2
