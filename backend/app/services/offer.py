"""Suggested offer for top-ranked homes, from recent sold comparables.

All prices are computed here (comparable stats, list-price discounts, your max price for the
monthly target). The model only CHOOSES which computed price to use for opening / target /
walk-away and explains why; the code checks its choices exist and are in order. This is
guidance for talking with an agent, not an appraisal.
"""

import json
import logging
import statistics
from typing import Any, Protocol

from app.models.analysis import OfferAnalysis, OfferChoice, SoldComp
from app.models.preferences import SearchPreferences
from app.models.property import Property, PropertyType
from app.services.agent_summary import facts_hash, ungrounded_numbers
from app.services.commute import haversine_m
from app.services.discovery import EvaluatedProperty
from app.services.finance import DEFAULT_SCENARIOS, CostInputs, evaluate_scenario
from app.services.rates import MortgageRate
from app.services.scoring import scenarios_for

log = logging.getLogger(__name__)

PROMPT_VERSION = "offer-v1"
MAX_DISTANCE_MI = 1.5
MAX_DAYS_SINCE_SOLD = 365
MIN_COMPS = 3
SHOW_COMPS = 8

INSTRUCTIONS = """Ayudas a una familia a preparar una oferta para una casa en New Jersey.
Recibes un JSON con datos ya calculados y una lista 'precios_candidatos' (clave -> precio).
Reglas:
- Elige opening_key, target_key y walk_away_key SOLO de las claves de 'precios_candidatos'.
- La oferta inicial debe ser menor o igual al objetivo, y el objetivo menor o igual al máximo.
- Básate en las ventas comparables (precio, recámaras, distancia, antigüedad de la venta), los días
  en el mercado y el precio máximo que mantiene la meta mensual del usuario.
- Si el precio máximo para la meta mensual está por debajo de las ventas comparables, dilo claramente.
- Escribe 'rationale' y 'risks' en español. Si mencionas cifras, cópialas exactamente del JSON.
- No inventes datos del mercado ni de la casa. Recomienda confirmar con un agente local."""


class OfferLLM(Protocol):
    def parse_offer(self, *, instructions: str, text: str) -> OfferChoice: ...


class OpenAIOfferLLM:
    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, timeout=90, max_retries=2)
        self.model = model

    def parse_offer(self, *, instructions: str, text: str) -> OfferChoice:
        resp = self._client.responses.parse(model=self.model, instructions=instructions, input=text, text_format=OfferChoice)
        if resp.output_parsed is None:
            raise ValueError("Model returned no parsable output")
        return resp.output_parsed


def sold_home_type(prop: Property) -> str:
    return "house" if prop.property_type is PropertyType.SINGLE_FAMILY else "multiFamily"


def select_comps(prop: Property, sold: list[SoldComp]) -> list[SoldComp]:
    """Nearby, recent, similar-size sales, closest first."""
    out = []
    for c in sold:
        if c.latitude is None or prop.latitude is None:
            continue
        dist = haversine_m(prop.latitude, prop.longitude, c.latitude, c.longitude) / 1609.344
        if dist > MAX_DISTANCE_MI:
            continue
        if c.days_since_sold is not None and c.days_since_sold > MAX_DAYS_SINCE_SOLD:
            continue
        if prop.beds and c.beds and abs(c.beds - prop.beds) > 2:
            continue
        if c.address.split(",")[0].lower() == prop.address.raw.split(",")[0].lower():
            continue  # the subject itself
        out.append(c.model_copy(update={"distance_mi": round(dist, 2)}))
    return sorted(out, key=lambda c: (c.distance_mi, c.days_since_sold or 0))


def _round_k(x: float) -> int:
    return int(round(x / 1000.0) * 1000)


def max_affordable_price(prop: Property, prefs: SearchPreferences, rate: MortgageRate) -> int | None:
    """Highest price whose monthly cost after rent (primary loan) stays at/below the target.
    Keeps the current tax bill, insurance and rent; maintenance scales with price."""
    target = prefs.target_monthly_cost
    if not target or prop.price is None:
        return None
    is_multi = (prop.units or 1) > 1
    rent_ok = bool(prop.rent_estimate and prop.rent_estimate.status == "estimated")
    if is_multi and not rent_ok:
        return None
    rent = prop.rent_estimate.monthly_rent_total if rent_ok else 0
    _, rates = scenarios_for(rate, prefs)
    scenario = next(s for s in DEFAULT_SCENARIOS if s.name == prefs.primary_scenario)

    def cost(price: float) -> float:
        return evaluate_scenario(CostInputs(
            price=int(price), annual_rate=rates[scenario.name], annual_tax=prop.annual_tax or 0,
            annual_insurance=prefs.annual_insurance, annual_maintenance_pct=prefs.annual_maintenance_pct,
            monthly_gross_rent=rent or 0), scenario).effective_owner_cost

    lo, hi = 50_000.0, 3_000_000.0
    if cost(lo) > target:
        return 0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cost(mid) <= target else (lo, mid)
    return _round_k(lo)


def build_candidates(prop: Property, comps: list[SoldComp], max_price: int | None) -> tuple[dict[str, int], dict[str, str]]:
    prices = sorted(c.price for c in comps)
    cand: dict[str, int] = {}
    labels: dict[str, str] = {}

    def add(key: str, value: float | None, label: str) -> None:
        if value and value > 0:
            cand[key] = _round_k(value)
            labels[key] = label

    add("precio_lista", prop.price, "Precio de lista")
    for pct in (3, 5, 8):
        add(f"lista_menos_{pct}", prop.price * (1 - pct / 100) if prop.price else None, f"Lista −{pct}%")
    if len(prices) >= MIN_COMPS:
        q = statistics.quantiles(prices, n=4)
        add("comparables_bajo", q[0], "Comparables: rango bajo (25%)")
        add("comparables_mediana", statistics.median(prices), "Comparables: mediana")
        add("comparables_alto", q[2], "Comparables: rango alto (75%)")
    add("maximo_para_meta_mensual", max_price, "Tu precio máximo para la meta mensual")
    return cand, labels


def _usd(x: int | None) -> str | None:
    return None if x is None else f"${x:,}"


def build_offer_facts(ev: EvaluatedProperty, prefs: SearchPreferences, comps: list[SoldComp],
                      cand: dict[str, int], labels: dict[str, str]) -> dict[str, Any]:
    p, a = ev.property, ev.analysis
    primary = a.finance.get(a.primary_scenario) if a else None
    rent_ok = bool(p.rent_estimate and p.rent_estimate.status == "estimated")
    return {
        "casa": {
            "direccion": p.address.raw, "precio_lista": _usd(p.price), "dias_en_el_mercado": p.days_on_market,
            "recamaras": p.beds, "banos": p.baths, "unidades": p.units,
            "estado": p.llm_analysis.condition.value if p.llm_analysis else None,
            "pagas_al_mes_a_precio_de_lista": (f"${primary.effective_owner_cost:,.0f}" if primary and rent_ok
                                               else f"${primary.monthly_housing_cost:,.0f}" if primary else None),
            "meta_mensual": _usd(prefs.target_monthly_cost),
        },
        "ventas_comparables": [
            {"direccion": c.address, "precio_vendido": _usd(c.price), "recamaras": c.beds, "banos": c.baths,
             "distancia": f"{c.distance_mi} mi", "vendida_hace_aprox": f"{c.days_since_sold} días" if c.days_since_sold is not None else None}
            for c in comps[:12]
        ],
        "precios_candidatos": {k: {"etiqueta": labels[k], "precio": _usd(v)} for k, v in cand.items()},
    }


def suggest_offer(ev: EvaluatedProperty, prefs: SearchPreferences, rate: MortgageRate, sold: list[SoldComp],
                  llm: OfferLLM, *, model: str) -> OfferAnalysis:
    prop = ev.property
    comps = select_comps(prop, sold)
    max_price = max_affordable_price(prop, prefs, rate)
    cand, labels = build_candidates(prop, comps, max_price)
    base = dict(comps=comps[:SHOW_COMPS], max_affordable_price=max_price, candidates=cand, candidate_labels=labels)
    prices = sorted(c.price for c in comps)
    if len(prices) >= MIN_COMPS:
        q = statistics.quantiles(prices, n=4)
        base.update(comps_median=_round_k(statistics.median(prices)), comps_low=_round_k(q[0]), comps_high=_round_k(q[2]))
    if len(comps) < MIN_COMPS:
        return OfferAnalysis(**base, status="not_enough_comps",
                             reason=f"Solo {len(comps)} venta(s) comparable(s) cercana(s) en el último año; se necesitan {MIN_COMPS}.")

    facts = build_offer_facts(ev, prefs, comps, cand, labels)
    h = facts_hash({"facts": facts, "v": PROMPT_VERSION})
    if prop.offer and prop.offer.facts_hash == h and prop.offer.status == "ok":
        return prop.offer
    text = json.dumps(facts, ensure_ascii=False, indent=1)
    for attempt in range(2):
        choice = llm.parse_offer(instructions=INSTRUCTIONS, text=text)
        keys_ok = all(k in cand for k in (choice.opening_key, choice.target_key, choice.walk_away_key))
        order_ok = keys_ok and cand[choice.opening_key] <= cand[choice.target_key] <= cand[choice.walk_away_key]
        bad_numbers = ungrounded_numbers(
            _AsSummary(choice.rationale + choice.risks), facts) if keys_ok else []
        if keys_ok and order_ok and not bad_numbers:
            return OfferAnalysis(
                **base, opening=cand[choice.opening_key], target=cand[choice.target_key], walk_away=cand[choice.walk_away_key],
                opening_key=choice.opening_key, target_key=choice.target_key, walk_away_key=choice.walk_away_key,
                rationale=choice.rationale, risks=choice.risks, model=model, facts_hash=h,
            )
        problem = ("claves inexistentes" if not keys_ok else "orden incorrecto (inicial ≤ objetivo ≤ máximo)" if not order_ok
                   else f"cifras que no están en el JSON: {', '.join(bad_numbers)}")
        log.info("Offer for %s rejected (%s), attempt %d", prop.address.raw, problem, attempt + 1)
        text += f"\n\nATENCIÓN: tu respuesta anterior tuvo {problem}. Corrígelo."
    return OfferAnalysis(**base, status="error", reason="La sugerencia de la IA no pasó las verificaciones.")


class _AsSummary:
    """Adapter so ungrounded_numbers() can check free text lists."""

    def __init__(self, lines: list[str]) -> None:
        self.headline, self.reasons_for, self.reasons_against, self.next_steps = "", lines, [], []


class SoldCompsService:
    """Per-town sold comparables, cached in the database for CACHE_DAYS (10 HasData credits per refresh)."""

    CACHE_DAYS = 7

    def __init__(self, repo, provider, *, max_requests: int = 6) -> None:
        from app.providers.base import RequestBudget

        self._repo, self._provider = repo, provider
        self._budget = RequestBudget(max_requests)

    def get(self, town: str, state: str, home_type: str) -> list[SoldComp]:
        from datetime import datetime, timedelta, timezone

        cached = self._repo.get_sold_cache(town, home_type)
        if cached is not None:
            fetched_at, comps = cached
            if datetime.now(timezone.utc) - fetched_at < timedelta(days=self.CACHE_DAYS):
                return comps
        comps = self._provider.search_sold(f"{town}, {state}", home_type, self._budget)
        self._repo.save_sold_cache(town, home_type, comps)
        return comps
