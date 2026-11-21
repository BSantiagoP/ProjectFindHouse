"""Deterministic scoring. Unknown inputs score 0 for their category (never rewarded) and
lower the confidence, which is the share of total weight backed by known data."""

from pydantic import BaseModel

from app.models.analysis import Condition
from app.models.preferences import FinanceScenarioName, SearchPreferences
from app.models.property import Property
from app.services.finance import (
    DEFAULT_SCENARIOS,
    CostInputs,
    LoanScenario,
    ScenarioResult,
    evaluate_all,
)
from app.services.rates import MortgageRate


class CategoryScore(BaseModel):
    name: str
    weight: int
    score: float | None  # 0-10; None = unknown
    reason: str

    @property
    def points(self) -> float:
        return self.weight * (self.score or 0) / 10


class Analysis(BaseModel):
    score: float  # 0-100
    confidence: float  # 0-1, share of weight with known inputs
    categories: list[CategoryScore]
    finance: dict[FinanceScenarioName, ScenarioResult]
    primary_scenario: FinanceScenarioName
    rate: float
    rate_source: str
    missing: list[str]
    explanation: list[str]


def _clamp(x: float) -> float:
    return max(0.0, min(10.0, x))


def _lerp_score(value: float, best: float, worst: float) -> float:
    """10 at `best`, 0 at `worst`, linear between."""
    return _clamp(10 * (worst - value) / (worst - best))


def scenarios_for(rate: MortgageRate, prefs: SearchPreferences) -> tuple[list[LoanScenario], dict[FinanceScenarioName, float]]:
    rates = {s.name: rate.annual_rate for s in DEFAULT_SCENARIOS}
    rates[FinanceScenarioName.FHA_3_5] = max(rate.annual_rate + prefs.fha_rate_adjustment, 0.0)
    return list(DEFAULT_SCENARIOS), rates


def finance_for(prop: Property, prefs: SearchPreferences, rate: MortgageRate) -> dict[FinanceScenarioName, ScenarioResult]:
    if prop.price is None:
        return {}
    rent = prop.rent_estimate.monthly_rent_total if prop.rent_estimate and prop.rent_estimate.status == "estimated" else 0
    scenarios, rates = scenarios_for(rate, prefs)
    out: dict[FinanceScenarioName, ScenarioResult] = {}
    for s in scenarios:
        inputs = CostInputs(
            price=prop.price,
            annual_rate=rates[s.name],
            annual_tax=prop.annual_tax or 0,
            annual_insurance=prefs.annual_insurance,
            annual_maintenance_pct=prefs.annual_maintenance_pct,
            monthly_gross_rent=rent or 0,
        )
        out.update(evaluate_all(inputs, (s,)))
    return out


# User-facing text is Spanish (dashboard language, 2026-11-20). Listing quotes stay verbatim.
CATEGORY_ES = {
    "affordability": "asequibilidad", "location_commute": "ubicación y trayecto", "condition": "estado",
    "rental_potential": "potencial de renta", "preferences": "preferencias",
}
CONDITION_ES = {
    Condition.MOVE_IN_READY: "listo para mudarse", Condition.UPDATED: "actualizado", Condition.DATED: "anticuado",
    Condition.NEEDS_WORK: "necesita trabajo", Condition.UNKNOWN: "desconocido",
}
SCENARIO_ES = {"fha_3_5": "FHA 3.5% de enganche", "conventional_5": "Convencional 5%", "conventional_20": "Convencional 20%"}

_CONDITION_SCORES = {
    Condition.MOVE_IN_READY: 10, Condition.UPDATED: 8, Condition.DATED: 4, Condition.NEEDS_WORK: 1,
}


def score_property(prop: Property, prefs: SearchPreferences, rate: MortgageRate) -> Analysis:
    w = prefs.weights
    finance = finance_for(prop, prefs, rate)
    primary = finance.get(prefs.primary_scenario)
    missing: list[str] = []
    cats: list[CategoryScore] = []
    rent_known = bool(prop.rent_estimate and prop.rent_estimate.status == "estimated")
    is_multi = (prop.units or 1) > 1

    # Affordability: effective monthly cost (after rent) vs target, else price vs max.
    if primary is None:
        cats.append(CategoryScore(name="affordability", weight=w.affordability, score=None, reason="Precio desconocido"))
        missing.append("price")
    elif is_multi and not rent_known:
        cats.append(CategoryScore(name="affordability", weight=w.affordability, score=None,
                                  reason="Aún no se estimó la renta de la(s) unidad(es) a alquilar"))
        missing.append("rent estimate")
    elif prefs.target_monthly_cost:
        t = prefs.target_monthly_cost
        s = _lerp_score(primary.effective_owner_cost, best=0.75 * t, worst=1.5 * t)
        cats.append(CategoryScore(name="affordability", weight=w.affordability, score=round(s, 1),
                                  reason=f"${primary.effective_owner_cost:,.0f}/mes después de la renta vs. meta de ${t:,}/mes"))
    else:
        s = _lerp_score(prop.price, best=0.6 * prefs.max_price, worst=prefs.max_price)
        cats.append(CategoryScore(name="affordability", weight=w.affordability, score=round(s, 1),
                                  reason=f"${prop.price:,} vs. máximo de ${prefs.max_price:,} (define una meta mensual para una mejor medida)"))

    # Location: average of each configured destination's sub-score. Currently one destination:
    # driving to 576 Bergen Blvd, Ridgefield (free-flow): 5 min -> 10, 35 min -> 0.
    # Transit destinations (40 min -> 10, 90 min -> 0) are supported if one is added back.
    # A destination that couldn't be estimated counts as 0 (never rewarded).
    parts: list[tuple[float | None, str]] = []
    c = prop.commute
    has_transit_dest = any(d.mode.value == "transit" for d in prefs.commute_destinations)
    if not has_transit_dest:
        pass
    elif c and c.total_minutes is not None:
        parts.append((_lerp_score(c.total_minutes, best=40, worst=90),
                      f"~{c.total_minutes} min en transporte a {c.destination} ({c.walk_minutes} min caminando a {c.nearest_stop}, luego {c.route})"))
    else:
        parts.append((None, "transporte a 7 WTC no estimado"))
    drive_dests = [d for d in prefs.commute_destinations if d.mode.value == "drive"]
    drives = {d.address: d for d in prop.drives}
    for dest in drive_dests:
        d = drives.get(dest.address)
        if d and d.minutes is not None:
            parts.append((_lerp_score(d.minutes, best=5, worst=35),
                          f"~{d.minutes} min en auto a {d.destination} (sin tráfico)"))
        else:
            parts.append((None, f"tiempo en auto a {dest.label} no estimado"))
    if not parts or all(sc is None for sc, _ in parts):
        cats.append(CategoryScore(name="location_commute", weight=w.location_commute, score=None,
                                  reason="Trayecto no estimado (sin coordenadas o sin parada cercana)"))
        missing.append("commute")
    else:
        s = sum((sc or 0) for sc, _ in parts) / len(parts)
        cats.append(CategoryScore(name="location_commute", weight=w.location_commute, score=round(s, 1),
                                  reason="; ".join(r for _, r in parts)))

    # Condition from the listing text; photos only when the text doesn't say.
    cond = prop.llm_analysis.condition if prop.llm_analysis else Condition.UNKNOWN
    photo = prop.photo_analysis
    if cond in _CONDITION_SCORES:
        quote = prop.llm_analysis.condition_quote
        cats.append(CategoryScore(name="condition", weight=w.condition, score=_CONDITION_SCORES[cond],
                                  reason=f"{CONDITION_ES[cond]}: \"{quote}\""))
    elif photo and photo.condition in _CONDITION_SCORES:
        cats.append(CategoryScore(name="condition", weight=w.condition, score=_CONDITION_SCORES[photo.condition],
                                  reason=f"{CONDITION_ES[photo.condition]} (según fotos) — {photo.condition_note}"))
    else:
        cats.append(CategoryScore(name="condition", weight=w.condition, score=None, reason="El anuncio no indica el estado"))
        missing.append("condition")

    # Rental potential: rent offset 0% -> 0, 60%+ -> 10.
    if not is_multi:
        cats.append(CategoryScore(name="rental_potential", weight=w.rental_potential, score=0,
                                  reason="Unifamiliar: sin unidad para alquilar"))
    elif rent_known and primary and primary.rent_offset_pct is not None:
        s = _clamp(10 * primary.rent_offset_pct / 0.6)
        units = ", ".join(f"{u.label} ${u.rent:,}" for u in prop.rent_estimate.rental_units)
        cats.append(CategoryScore(name="rental_potential", weight=w.rental_potential, score=round(s, 1),
                                  reason=f"La renta cubre el {primary.rent_offset_pct:.0%} del costo de vivienda ({units})"))
    else:
        reason = prop.rent_estimate.reason if prop.rent_estimate else "Renta aún no estimada"
        cats.append(CategoryScore(name="rental_potential", weight=w.rental_potential, score=None, reason=reason))

    # Preferences: finished basement w/ bath 5, outdoor space 3, garage (vs driveway) 2.
    f = prop.features
    pts, notes = 0.0, []
    if f.finished_basement.is_present and f.basement_bathroom.is_present:
        pts += 5; notes.append("sótano terminado con baño")
    elif f.finished_basement.is_present:
        pts += 2.5; notes.append("sótano terminado (baño sin confirmar)")
    if f.outdoor_space.is_present:
        pts += 3; notes.append("patio / espacio exterior")
    if f.garage.is_present:
        pts += 2; notes.append("garaje")
    cats.append(CategoryScore(name="preferences", weight=w.preferences, score=pts,
                              reason=", ".join(notes) if notes else "Ninguna característica preferida confirmada"))

    total_w = sum(c.weight for c in cats)
    known_w = sum(c.weight for c in cats if c.score is not None)
    score = round(sum(c.points for c in cats) * 100 / total_w, 1)
    explanation = _explain(prop, cats, primary, prefs)
    return Analysis(
        score=score, confidence=round(known_w / total_w, 2), categories=cats, finance=finance,
        primary_scenario=prefs.primary_scenario, rate=rate.annual_rate, rate_source=rate.source,
        missing=missing, explanation=explanation,
    )


def _explain(prop: Property, cats: list[CategoryScore], primary: ScenarioResult | None, prefs: SearchPreferences) -> list[str]:
    """Deterministic explanation built only from computed values and verified evidence."""
    lines = []
    known = sorted((c for c in cats if c.score is not None), key=lambda c: c.points, reverse=True)
    if known:
        lines.append(f"Lo más fuerte: {CATEGORY_ES.get(known[0].name, known[0].name)} — {known[0].reason}")
        if len(known) > 1 and known[-1].score is not None and known[-1].score < 5:
            lines.append(f"Lo más débil: {CATEGORY_ES.get(known[-1].name, known[-1].name)} — {known[-1].reason}")
    if primary:
        lines.append(
            f"{SCENARIO_ES.get(prefs.primary_scenario.value, prefs.primary_scenario.value)}: ${primary.down_payment:,.0f} de enganche, "
            f"${primary.monthly_housing_cost:,.0f}/mes de vivienda, ${primary.effective_owner_cost:,.0f}/mes después de la renta"
        )
    unknown = [CATEGORY_ES.get(c.name, c.name) for c in cats if c.score is None]
    if unknown:
        lines.append("Sin puntuar todavía (cuenta como 0): " + ", ".join(unknown))
    if prop.llm_analysis and prop.llm_analysis.red_flags:
        lines.append("Alertas del anuncio: " + "; ".join(f'"{q}"' for q in prop.llm_analysis.red_flags))
    return lines
