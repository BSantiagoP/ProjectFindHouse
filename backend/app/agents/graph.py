"""LangGraph analysis workflow (plan.md section 8).

load_candidates -> analyze_description -> analyze_photos -> refilter -> enrich (rent, commute)
  -> score -> validate -> select_top -> suggest_offers (top 5) -> write_summaries

Paid/slow calls are cached on the Property, so re-runs only analyze new listings.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.models.preferences import SearchPreferences
from app.models.property import PropertyType
from app.providers.rentcast import RENT_METHOD, RentCastClient
from app.services.commute import StopFinder, estimate_commute
from app.models.analysis import CommuteEstimate
from app.services.description_analysis import PROMPT_VERSION, StructuredLLM, analyze_description, reset_text_features
from app.services.discovery import DiscoveryRun, EvaluatedProperty
from app.services.photo_analysis import VisionLLM, analyze_photos
from app.services.agent_summary import SummaryLLM, summarize
from app.services.driving import Router, estimate_drives
from app.services.offer import OfferLLM, sold_home_type, suggest_offer
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
    vision: VisionLLM | None = None
    summarizer: SummaryLLM | None = None
    router: Router | None = None
    sold_comps: Any = None  # SoldCompsService
    offer_llm: OfferLLM | None = None
    rejected_keys: set[tuple[str, str]] = field(default_factory=set)  # discarded in the dashboard


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

    def analyze_photos_node(state: State) -> dict[str, Any]:
        errors = list(state["errors"])
        if deps.vision is None:
            return {}
        for ev in state["candidates"]:
            try:
                ev.property = analyze_photos(ev.property, deps.vision)
            except Exception as exc:
                log.warning("Photo analysis failed for %s: %s", ev.property.address.raw, exc)
                errors.append(f"Photo analysis failed for {ev.property.address.raw}: {exc}"[:300])
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
            has_transit_dest = any(d.mode.value == "transit" for d in prefs.commute_destinations)
            if not has_transit_dest:
                p = p.model_copy(update={"commute": None})  # 7 WTC dropped 2026-11-20
            elif p.commute is None or p.commute.total_minutes is None or p.commute.source != current_source:
                p = p.model_copy(update={"commute": estimate_commute(p, prefs, deps.stops)})
                if p.commute and (p.commute.nearest_stop or "").startswith("lookup failed"):
                    errors.append(f"Commute not estimated for {p.address.raw}: {p.commute.nearest_stop}")
            p = p.model_copy(update={"drives": estimate_drives(p, prefs, deps.router)})
            # Rent costs money: only for eligible multifamily, and only if not already estimated.
            needs_rent = (
                ev.filter.status is FilterStatus.ELIGIBLE
                and p.property_type is not PropertyType.SINGLE_FAMILY
                and (p.rent_estimate is None or p.rent_estimate.status != "estimated"
                     or p.rent_estimate.method != RENT_METHOD)  # legacy Apartment-comps estimates are redone
            )
            if needs_rent and deps.rentcast is not None:
                p = p.model_copy(update={"rent_estimate": deps.rentcast.estimate(p, prefs.owner_unit)})
                reason = p.rent_estimate.reason or ""
                if reason.startswith(("Error de RentCast", "Se alcanzó el límite mensual")):
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
            (ev for ev in state["candidates"]
             if ev.analysis and ev.filter.status is FilterStatus.ELIGIBLE and ev.property.key not in deps.rejected_keys),
            key=lambda ev: (ev.analysis.score, ev.analysis.confidence),
            reverse=True,
        )
        for i, ev in enumerate(ranked[: state["prefs"].max_recommendations], start=1):
            ev.rank = i
        return {}

    def suggest_offers(state: State) -> dict[str, Any]:
        """Suggested offer for the top-ranked homes only (decided 2026-11-21)."""
        errors = list(state["errors"])
        if deps.sold_comps is None or deps.offer_llm is None:
            return {}
        for ev in state["candidates"]:
            if not ev.rank or ev.analysis is None or ev.property.town is None:
                continue
            p = ev.property
            try:
                sold = deps.sold_comps.get(p.town, state["prefs"].state, sold_home_type(p))
                offer = suggest_offer(ev, state["prefs"], deps.rate, sold, deps.offer_llm, model=deps.llm_model)
            except Exception as exc:
                log.warning("Offer failed for %s: %s", p.address.raw, exc)
                errors.append(f"Offer failed for {p.address.raw}: {exc}"[:300])
                continue
            ev.property = p.model_copy(update={"offer": offer})
        return {"errors": errors}

    def write_summaries(state: State) -> dict[str, Any]:
        """Final step: the agent's verdict, written from the computed facts only."""
        errors = list(state["errors"])
        if deps.summarizer is None:
            return {}
        for ev in state["candidates"]:
            if ev.analysis is None:
                continue
            try:
                summary = summarize(ev, state["prefs"], deps.summarizer, model=deps.llm_model)
            except Exception as exc:
                log.warning("Summary failed for %s: %s", ev.property.address.raw, exc)
                errors.append(f"Summary failed for {ev.property.address.raw}: {exc}"[:300])
                continue
            if summary is None:
                errors.append(f"Summary for {ev.property.address.raw} cited unsupported numbers; omitted")
            ev.property = ev.property.model_copy(update={"agent_summary": summary})
        return {"errors": errors}

    g = StateGraph(State)
    g.add_node("load_candidates", load_candidates)
    g.add_node("analyze_description", analyze_description_node)
    g.add_node("analyze_photos", analyze_photos_node)
    g.add_node("refilter", refilter)
    g.add_node("enrich", enrich)
    g.add_node("score", score)
    g.add_node("validate", validate)
    g.add_node("select_top", select_top)
    g.add_node("suggest_offers", suggest_offers)
    g.add_node("write_summaries", write_summaries)
    g.add_edge(START, "load_candidates")
    g.add_conditional_edges("load_candidates", has_candidates, ["analyze_description", END])
    g.add_edge("analyze_description", "analyze_photos")
    g.add_edge("analyze_photos", "refilter")
    g.add_edge("refilter", "enrich")
    g.add_edge("enrich", "score")
    g.add_edge("score", "validate")
    g.add_edge("validate", "select_top")
    g.add_edge("select_top", "suggest_offers")
    g.add_edge("suggest_offers", "write_summaries")
    g.add_edge("write_summaries", END)
    return g.compile()


def run_analysis(run: DiscoveryRun, prefs: SearchPreferences, deps: AnalysisDeps) -> DiscoveryRun:
    graph = build_graph(deps)
    final = graph.invoke({"run": run, "prefs": prefs, "candidates": [], "errors": []})
    run.errors.extend(final["errors"])
    if final["errors"] and run.status == "succeeded":
        run.status = "partial"
    return run
