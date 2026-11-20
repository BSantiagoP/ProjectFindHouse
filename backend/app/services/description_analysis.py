"""LLM description analysis with deterministic grounding checks.

The model reads the listing text and returns structured findings. Every claim must quote
the listing verbatim; quotes are verified against the source text and unsupported claims
are dropped (feature stays UNKNOWN). The LLM never does filtering or arithmetic.
"""

import logging
import re
from typing import Protocol

from app.models.analysis import Condition, DescriptionAnalysis, LLMAnalysis, QuotedFinding, UnitLayout
from app.models.property import Feature, FeatureSource, FeatureState, Property, PropertyFeatures

log = logging.getLogger(__name__)

PROMPT_VERSION = "desc-v2"  # v2: relevance + explicit-negation validation, unit cleanup

INSTRUCTIONS = """You extract facts from a real-estate listing for a home buyer.
Rules:
- Use ONLY the listing text provided. Never infer from typical homes, the town, or the price.
- For every finding that is not "unknown", copy an exact, verbatim quote from the listing text.
- If the text does not clearly say something, answer "unknown". Do not guess.
- "absent" requires the text to explicitly say the feature is missing (e.g. "no garage", "street parking only").
  Never mark something absent just because it is not mentioned.
- Each quote must itself mention the feature (e.g. a basement_bathroom quote must mention both the basement and a bath).
- finished_basement is "present" only for a fully finished basement; "partially finished" is "unknown".
- units: list each separate dwelling unit (apartment/floor) the text describes with its bedrooms/bathrooms.
  A finished basement, guest suite or in-law area is NOT a separate unit unless the text calls it a legal unit.
  Do not split totals yourself.
- Disclosures like virtual staging or tenant occupancy are not red flags unless they limit the sale."""

FEATURES = ("garage", "driveway", "laundry", "finished_basement", "basement_bathroom", "outdoor_space")


class StructuredLLM(Protocol):
    def parse(self, *, instructions: str, text: str) -> DescriptionAnalysis: ...


class OpenAIStructuredLLM:
    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, timeout=90, max_retries=2)
        self.model = model

    def parse(self, *, instructions: str, text: str) -> DescriptionAnalysis:
        resp = self._client.responses.parse(
            model=self.model,
            instructions=instructions,
            input=text,
            text_format=DescriptionAnalysis,
        )
        if resp.output_parsed is None:
            raise ValueError("Model returned no parsable output")
        return resp.output_parsed


def listing_text(prop: Property) -> str:
    parts = [prop.description or ""]
    if prop.highlights:
        parts.append("Highlights: " + "; ".join(prop.highlights))
    return "\n".join(p for p in parts if p).strip()


def _norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[^\w\s'/-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def quote_supported(quote: str | None, source: str) -> bool:
    """Verbatim check, tolerant only of case, punctuation and whitespace differences."""
    if not quote or len(_norm(quote)) < 4:
        return False
    return _norm(quote) in _norm(source)


# A quote must be ABOUT the feature, not just exist in the text. Live run 2026-11-20:
# "basement bathroom: present" was quoted with a sentence about the first-floor unit.
_RELEVANT: dict[str, list[re.Pattern[str]]] = {
    "garage": [re.compile(r"garage")],
    "driveway": [re.compile(r"driveway|off[- ]?street|private parking|parking pad|parking for")],
    "laundry": [re.compile(r"laundry|washer|dryer|w/d")],
    "finished_basement": [re.compile(r"basement|lower level"), re.compile(r"finish")],
    "basement_bathroom": [re.compile(r"basement|lower level"), re.compile(r"bath|powder|toilet|half bath")],
    "outdoor_space": [re.compile(r"yard|deck|patio|terrace|garden|porch|outdoor|balcony")],
}
# "absent" needs an explicit negation in the quote. Live run 2026-11-20: a single-family was
# rejected because a basement description simply did not mention a bathroom.
_NEGATION = re.compile(r"\b(no|not|without|lacks?|none|only)\b|unfinished|street parking")
_NON_UNIT = re.compile(r"basement|lower level|ground level|guest suite|in-law|mother|suite|attic", re.I)


def finding_valid(name: str, finding: QuotedFinding, source: str) -> tuple[bool, str]:
    if not quote_supported(finding.quote, source):
        return False, f"{name}={finding.state} (quote not found: {finding.quote!r})"
    q = _norm(finding.quote or "")
    if not all(p.search(q) for p in _RELEVANT.get(name, [])):
        return False, f"{name}={finding.state} (quote is not about {name}: {finding.quote!r})"
    if finding.state == "absent" and not _NEGATION.search(q):
        return False, f"{name}=absent (no explicit negation in quote: {finding.quote!r})"
    return True, ""


def _clean_units(units: list[UnitLayout], mls_units: int | None) -> tuple[list[UnitLayout], list[str]]:
    """Basement/guest 'units' are not proof of a legal rental unit: drop them when they push
    the count above the MLS unit count."""
    if mls_units is None or len(units) <= mls_units:
        return units, []
    kept = [u for u in units if not _NON_UNIT.search(f"{u.label} {u.quote}")]
    dropped = [f"unit {u.label!r} (not a legal unit per MLS count {mls_units})" for u in units if u not in kept]
    return kept, dropped


def apply_analysis(prop: Property, result: DescriptionAnalysis, *, model: str) -> Property:
    """Validate quotes, fill only UNKNOWN features, and cache the analysis on the property."""
    source = listing_text(prop)
    rejected: list[str] = []
    features = prop.features.model_copy(deep=True)

    for name in FEATURES:
        finding: QuotedFinding = getattr(result, name)
        if finding.state == "unknown":
            continue
        ok, why = finding_valid(name, finding, source)
        if not ok:
            rejected.append(why)
            continue
        if getattr(features, name).state is FeatureState.UNKNOWN:
            setattr(features, name, Feature(
                state=FeatureState(finding.state), source=FeatureSource.LLM, evidence=finding.quote,
            ))

    units: list[UnitLayout] = []
    for u in result.units:
        if quote_supported(u.quote, source):
            units.append(u)
        else:
            rejected.append(f"unit {u.label!r} (quote not found)")
    units, dropped = _clean_units(units, prop.units)
    rejected += dropped

    def checked(f: QuotedFinding) -> QuotedFinding | None:
        if f.state == "unknown":
            return None
        if quote_supported(f.quote, source):
            return f
        rejected.append(f"{f.state} claim (quote not found: {f.quote!r})")
        return None

    condition, condition_quote = result.condition, result.condition_quote
    if condition is not Condition.UNKNOWN and not quote_supported(condition_quote, source):
        rejected.append(f"condition={condition.value} (quote not found)")
        condition, condition_quote = Condition.UNKNOWN, None

    red_flags = [q for q in result.red_flags if quote_supported(q, source)]

    updates: dict = {
        "features": features,
        "llm_analysis": LLMAnalysis(
            units=units,
            separate_utilities=checked(result.separate_utilities),
            tenant_occupied=checked(result.tenant_occupied),
            condition=condition,
            condition_quote=condition_quote,
            red_flags=red_flags,
            summary=result.summary,
            rejected_claims=rejected,
            model=model,
            prompt_version=PROMPT_VERSION,
        ),
    }
    if prop.units is None and len(units) >= 2:
        updates["units"] = len(units)
        updates["units_evidence"] = "; ".join(u.quote for u in units)[:240]
    if rejected:
        log.info("Dropped %d unsupported claims for %s", len(rejected), prop.address.raw)
    return prop.model_copy(update=updates)


def reset_text_features(prop: Property) -> Property:
    """Clear text-derived features (keeps MLS/provider, photo and manual facts) and recompute
    the deterministic keyword pass, so an outdated analysis can be redone from scratch."""
    from app.services.features import apply_description_features

    features = prop.features.model_copy(deep=True)
    for name in PropertyFeatures.model_fields:
        if getattr(features, name).source in (FeatureSource.DESCRIPTION, FeatureSource.LLM):
            setattr(features, name, Feature())
    reset = prop.model_copy(update={"features": features, "llm_analysis": None})
    if prop.units_evidence and not prop.units_evidence.startswith("MLS"):
        reset = reset.model_copy(update={"units": None, "units_evidence": None})
    return apply_description_features(reset)


def analyze_description(prop: Property, llm: StructuredLLM, *, model: str) -> Property:
    """Run once per property; redone if the prompt/validation version changed."""
    if prop.llm_analysis and prop.llm_analysis.prompt_version == PROMPT_VERSION:
        return prop
    if prop.llm_analysis is not None:
        prop = reset_text_features(prop)
    text = listing_text(prop)
    if not text:
        return prop
    result = llm.parse(instructions=INSTRUCTIONS, text=text)
    return apply_analysis(prop, result, model=model)
