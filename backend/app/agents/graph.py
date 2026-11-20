"""LangGraph analysis workflow (plan.md section 8).

load_candidates -> analyze_description -> refilter -> enrich (rent, commute)
  -> score -> validate -> select_top

Paid/slow calls are cached on the Property, so re-runs only analyze new listings.
analyze_photos slots in after analyze_description in a later step.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.models.preferences import SearchPreferences
from app.models.property import PropertyType
from app.providers.rentcast import RentCastClient
from app.services.commute import StopFinder, estimate_commute
from app.models.analysis import CommuteEstimate
from app.services.description_analysis import PROMPT_VERSION, StructuredLLM, analyze_description, reset_text_features
from app.services.discovery import DiscoveryRun, EvaluatedProperty
from app.services.filtering import FilterStatus, apply_hard_filters
from app.services.rates import MortgageRate
from app.services.scoring import score_property

log = logging.getLogger(__name__)


@dataclass
class AnalysisDeps:
    llm: StructuredLLM | None
    llm_model: str
    rentcast: RentCastClient | None
    stops: StopFinder | None
    rate: MortgageRate
    today: date = field(default_factory=date.today)


class State(TypedDict):
    run: DiscoveryRun
    prefs: SearchPreferences
    candidates: list[EvaluatedProperty]
    errors: list[str]


def build_graph(deps: AnalysisDeps):
    def load_candidates(state: State) -> dict[str, Any]:
        # A property may have been rejected using findings from an outdated analysis version
        # (live run 2026-11-20: a wrong "no basement bathroom" rejected a single-family).
        # Clear those findings and re-filter before choosing candidates.
        for ev in state["run"].results:
            la = ev.property.llm_analysis
            if la is not None and la.prompt_version != PROMPT_VERSION:
                ev.property = reset_text_features(ev.property)
                ev.filter = apply_hard_filters(ev.property, state["prefs"], deps.today)
        keep = (FilterStatus.ELIGIBLE, FilterStatus.NEEDS_VERIFICATION)
        return {"candidates": [ev for ev in state["run"].results if ev.filter.status in keep]}

    def has_candidates(state: State) -> str:
        return "analyze_description" if state["candidates"] else END

    def analyze_description_node(state: State) -> dict[str, Any]:
        errors = list(state["errors"])
        if deps.llm is None:
            errors.append("Description analysis skipped: OpenAI not configured")
            return {"errors": errors}
        for ev in state["candidates"]:
            try:
                ev.property = analyze_description(ev.property, deps.llm, model=deps.llm_model)
            except Exception as exc:
                log.warning("LLM analysis failed for %s: %s", ev.property.address.raw, exc)
                errors.append(f"Description analysis failed for {ev.property.address.raw}: {exc}")
        return {"errors": errors}

    def refilter(state: State) -> dict[str, Any]:
        # New evidence can resolve "needs verification" either way.
        for ev in state["candidates"]:
            ev.filter = apply_hard_filters(ev.property, state["prefs"], deps.today)
        keep = (FilterStatus.ELIGIBLE, FilterStatus.NEEDS_VERIFICATION)
        return {"candidates": [ev for ev in state["candidates"] if ev.filter.status in keep]}

    def enrich(state: State) -> dict[str, Any]:
        prefs, errors = state["prefs"], list(state["errors"])
        for ev in state["candidates"]:
            p = ev.property
            current_source = CommuteEstimate.model_fields["source"].default
            if p.commute is None or p.commute.total_minutes is None or p.commute.source != current_source:
                p = p.model_copy(update={"commute": estimate_commute(p, prefs, deps.stops)})
                if p.commute and (p.commute.nearest_stop or "").startswith("lookup failed"):
                    errors.append(f"Commute not estimated for {p.address.raw}: {p.commute.nearest_stop}")
            # Rent costs money: only for eligible multifamily, and only if not already estimated.
            needs_rent = (
                ev.filter.status is FilterStatus.ELIGIBLE
                and p.property_type is not PropertyType.SINGLE_FAMILY
                and (p.rent_estimate is None or p.rent_estimate.status != "estimated")
            )
            if needs_rent and deps.rentcast is not None:
                p = p.model_copy(update={"rent_estimate": deps.rentcast.estimate(p, prefs.owner_unit)})
                reason = p.rent_estimate.reason or ""
                if reason.startswith(("RentCast error", "Monthly RentCast cap")):
                    errors.append(f"Rent not estimated for {p.address.raw}: {reason[:160]}")
            elif needs_rent:
                errors.append("Rent estimate skipped: RentCast not configured")
            ev.property = p
        return {"errors": errors}

    def score(state: State) -> dict[str, Any]:
        for ev in state["candidates"]:
            ev.analysis = score_property(ev.property, state["prefs"], deps.rate)
        return {}

    def validate(state: State) -> dict[str, Any]:
        errors = list(state["errors"])
        for ev in state["candidates"]:
            a = ev.analysis
            total_w = sum(c.weight for c in a.categories)
            recomputed = round(sum(c.points for c in a.categories) * 100 / total_w, 1)
            bad = (
                abs(recomputed - a.score) > 0.11
                or not 0 <= a.score <= 100
                or any(c.score is not None and not 0 <= c.score <= 10 for c in a.categories)
                or not ev.property.source_url
            )
            if bad:
                errors.append(f"Analysis failed validation for {ev.property.address.raw}; excluded from ranking")
                ev.analysis = None
        return {"errors": errors}

    def select_top(state: State) -> dict[str, Any]:
        ranked = sorted(
            (ev for ev in state["candidates"] if ev.analysis and ev.filter.status is FilterStatus.ELIGIBLE),
            key=lambda ev: (ev.analysis.score, ev.analysis.confidence),
            reverse=True,
        )
        for i, ev in enumerate(ranked[: state["prefs"].max_recommendations], start=1):
            ev.rank = i
        return {}

    g = StateGraph(State)
    g.add_node("load_candidates", load_candidates)
    g.add_node("analyze_description", analyze_description_node)
    g.add_node("refilter", refilter)
    g.add_node("enrich", enrich)
    g.add_node("score", score)
    g.add_node("validate", validate)
    g.add_node("select_top", select_top)
    g.add_edge(START, "load_candidates")
    g.add_conditional_edges("load_candidates", has_candidates, ["analyze_description", END])
    g.add_edge("analyze_description", "refilter")
    g.add_edge("refilter", "enrich")
    g.add_edge("enrich", "score")
    g.add_edge("score", "validate")
    g.add_edge("validate", "select_top")
    g.add_edge("select_top", END)
    return g.compile()


def run_analysis(run: DiscoveryRun, prefs: SearchPreferences, deps: AnalysisDeps) -> DiscoveryRun:
    graph = build_graph(deps)
    final = graph.invoke({"run": run, "prefs": prefs, "candidates": [], "errors": []})
    run.errors.extend(final["errors"])
    if final["errors"] and run.status == "succeeded":
        run.status = "partial"
    return run
