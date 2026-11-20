"""LLM description analysis with deterministic grounding checks.

The model reads the listing text and returns structured findings. Every claim must quote
the listing verbatim; quotes are verified against the source text and unsupported claims
are dropped (feature stays UNKNOWN). The LLM never does filtering or arithmetic.
"""

import logging
import re
from typing import Protocol

from app.models.analysis import Condition, DescriptionAnalysis, LLMAnalysis, QuotedFinding, UnitLayout
from app.models.property import Feature, FeatureSource, FeatureState, Property

log = logging.getLogger(__name__)

PROMPT_VERSION = "desc-v1"

INSTRUCTIONS = """You extract facts from a real-estate listing for a home buyer.
Rules:
- Use ONLY the listing text provided. Never infer from typical homes, the town, or the price.
- For every finding that is not "unknown", copy an exact, verbatim quote from the listing text.
- If the text does not clearly say something, answer "unknown". Do not guess.
- "absent" requires the text to explicitly say the feature is missing (e.g. "no garage", "street parking only").
- finished_basement is "present" only for a fully finished basement; "partially finished" is "unknown".
- units: list each dwelling unit the text describes with its bedrooms/bathrooms. Do not split totals yourself.
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


def apply_analysis(prop: Property, result: DescriptionAnalysis, *, model: str) -> Property:
    """Validate quotes, fill only UNKNOWN features, and cache the analysis on the property."""
    source = listing_text(prop)
    rejected: list[str] = []
    features = prop.features.model_copy(deep=True)

    for name in FEATURES:
        finding: QuotedFinding = getattr(result, name)
        if finding.state == "unknown":
            continue
        if not quote_supported(finding.quote, source):
            rejected.append(f"{name}={finding.state} (quote not found: {finding.quote!r})")
            continue
        if getattr(features, name).state is FeatureState.UNKNOWN:
            setattr(features, name, Feature(
                state=FeatureState(finding.state), source=FeatureSource.DESCRIPTION, evidence=finding.quote,
            ))

    units: list[UnitLayout] = []
    for u in result.units:
        if quote_supported(u.quote, source):
            units.append(u)
        else:
            rejected.append(f"unit {u.label!r} (quote not found)")

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


def analyze_description(prop: Property, llm: StructuredLLM, *, model: str) -> Property:
    """Run once per property; skipped if already analyzed with the current prompt or no text."""
    if prop.llm_analysis and prop.llm_analysis.prompt_version == PROMPT_VERSION:
        return prop
    text = listing_text(prop)
    if not text:
        return prop
    result = llm.parse(instructions=INSTRUCTIONS, text=text)
    return apply_analysis(prop, result, model=model)
