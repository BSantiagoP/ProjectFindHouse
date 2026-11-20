"""Conservative, deterministic feature extraction from listing descriptions.

This is a first pass. It only sets a feature when the text explicitly mentions it,
and it records the sentence as evidence. Anything ambiguous stays UNKNOWN for the
LLM description analysis and photo analysis to resolve later.
"""

import re

from app.models.property import Feature, FeatureSource, FeatureState, Property, PropertyType

# A negation word shortly before the match, with no conjunction in between
# ("no garage but a driveway" must not negate "driveway").
_NEGATION = re.compile(
    r"\b(no|without|not|lacks?)\b(?:(?!\b(?:but|and|with|plus|however|while)\b)[\w\s/-]){0,20}$",
    re.I,
)

_PATTERNS: dict[str, re.Pattern[str]] = {
    "garage": re.compile(r"\bgarages?\b", re.I),
    "driveway": re.compile(r"\bdriveways?\b|\boff[- ]street parking\b|\bprivate parking\b", re.I),
    "laundry": re.compile(
        r"\blaundry\b|\bwasher\b|\bdryer\b|\bw/d\b|\bwasher/dryer\b|\bw/d hook-?ups?\b", re.I
    ),
    "outdoor_space": re.compile(r"\b(back)?yard\b|\bdeck\b|\bpatio\b|\bterrace\b", re.I),
}
_STREET_ONLY = re.compile(r"\bstreet parking only\b|\bonly street parking\b", re.I)
_FINISHED_BSMT = re.compile(
    r"\b(fully\s+)?finished\s+(walk[- ]?out\s+)?basement\b|\bbasement\s+(is\s+)?(fully\s+)?finished\b", re.I
)
_UNFINISHED_BSMT = re.compile(r"\bunfinished\s+basement\b|\bbasement\s+(is\s+)?unfinished\b", re.I)
_PARTIAL_BSMT = re.compile(r"\bpartially\s+finished\s+basement\b|\bbasement\s+(is\s+)?partially\s+finished\b", re.I)
_NO_BSMT = re.compile(r"\bno\s+basement\b|\bslab\b", re.I)
# Requires the bath to be tied to the basement ("basement with a full bath", "bath in the
# basement", "basement bathroom"), not merely in the same sentence as "basement".
_BSMT_BATH = re.compile(
    r"\bbasement\s+(full\s+|half\s+)?bath(room)?s?\b"
    r"|\bbasement\b[^.;]{0,50}\b(with|has|includes|including|features|offers|plus)\b[^.;,]{0,30}\b(bath(room)?s?|powder room)\b"
    r"|\b(bath(room)?s?|powder room)\b[^.;,]{0,20}\b(in|on)\s+the\s+(finished\s+)?(basement|lower level)\b",
    re.I,
)

_WORD_NUM = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6}
_UNITS = re.compile(r"\b(two|three|four|five|six|[2-6])[- ]?(family|fam|unit)s?\b", re.I)
_PLEX = {"duplex": 2, "triplex": 3, "fourplex": 4, "quadplex": 4, "4-plex": 4, "3-plex": 3}


def _sentence(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("!", 0, start), text.rfind("\n", 0, start)) + 1
    right_candidates = [i for i in (text.find(".", end), text.find("!", end), text.find("\n", end)) if i != -1]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    return text[left:right].strip()[:240]


def _found(text: str, m: re.Match[str], state: FeatureState) -> Feature:
    return Feature(state=state, source=FeatureSource.DESCRIPTION, evidence=_sentence(text, m.start(), m.end()))


def _first_mention(text: str, pattern: re.Pattern[str]) -> Feature | None:
    """PRESENT on an affirmative mention; ABSENT only for an explicit negation like 'no garage'."""
    negated: Feature | None = None
    for m in pattern.finditer(text):
        if _NEGATION.search(text[max(0, m.start() - 30) : m.start()]):
            negated = negated or _found(text, m, FeatureState.ABSENT)
            continue
        return _found(text, m, FeatureState.PRESENT)
    return negated


def extract_units(text: str) -> tuple[int | None, str | None]:
    if m := _UNITS.search(text):
        return _WORD_NUM[m.group(1).lower()], _sentence(text, m.start(), m.end())
    lowered = text.lower()
    for word, n in _PLEX.items():
        if (i := lowered.find(word)) != -1:
            return n, _sentence(text, i, i + len(word))
    return None, None


def apply_description_features(prop: Property) -> Property:
    """Fill UNKNOWN features from the description. Never overrides a known state."""
    highlights = ". ".join(h.rstrip(".") for h in prop.highlights)
    text = "\n".join(t for t in (prop.description, highlights + "." if highlights else "") if t)
    features = prop.features.model_copy(deep=True)
    updates: dict = {}

    def set_if_unknown(name: str, feat: Feature | None) -> None:
        if feat is not None and getattr(features, name).state is FeatureState.UNKNOWN:
            setattr(features, name, feat)

    if text:
        for name, pattern in _PATTERNS.items():
            set_if_unknown(name, _first_mention(text, pattern))

        if m := _STREET_ONLY.search(text):
            set_if_unknown("garage", _found(text, m, FeatureState.ABSENT))
            set_if_unknown("driveway", _found(text, m, FeatureState.ABSENT))

        # Basement: explicit "unfinished"/"no basement" beat partial, which beats finished.
        if (m := _UNFINISHED_BSMT.search(text)) or (m := _NO_BSMT.search(text)):
            set_if_unknown("finished_basement", _found(text, m, FeatureState.ABSENT))
        elif m := _PARTIAL_BSMT.search(text):
            # Partially finished does not satisfy "fully finished"; leave for human/photo review.
            features.finished_basement = Feature(
                state=FeatureState.UNKNOWN, source=FeatureSource.DESCRIPTION, evidence=_sentence(text, m.start(), m.end())
            )
        elif m := _FINISHED_BSMT.search(text):
            set_if_unknown("finished_basement", _found(text, m, FeatureState.PRESENT))

        if m := _BSMT_BATH.search(text):
            set_if_unknown("basement_bathroom", _found(text, m, FeatureState.PRESENT))

    if prop.units is None:
        if prop.property_type is PropertyType.SINGLE_FAMILY:
            updates["units"] = 1
        elif text:
            units, evidence = extract_units(text)
            if units is not None:
                updates["units"], updates["units_evidence"] = units, evidence

    updates["features"] = features
    return prop.model_copy(update=updates)
