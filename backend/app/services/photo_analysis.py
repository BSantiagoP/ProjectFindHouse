"""Limited photo analysis for features the listing text leaves unknown.

Pass 1 (triage): every photo at low detail, labeled by room. Cheap.
Pass 2 (inspect): at most MAX_DETAILED relevant photos at high detail, checking only the
still-unknown features. Photos can only CONFIRM presence (absence in photos proves nothing).
Every accepted finding must cite photo numbers that were actually sent and were triaged as
a relevant room; findings are stored with source=photos and the cited photo URLs.
Photo-use rights must be confirmed together with the HasData licensing review.
"""

import logging
import re
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.models.analysis import (
    Condition,
    PhotoAnalysis,
    PhotoFinding,
    PhotoFindings,
    PhotoTriage,
    Room,
)
from app.models.property import Feature, FeatureSource, FeatureState, Property, PropertyType

log = logging.getLogger(__name__)

PHOTO_VERSION = "photo-v3"  # v3: Spanish evidence wording (re-applied from stored output, no API calls)
CONFIDENCE_ES = {"high": "alta", "medium": "media", "low": "baja"}
MAX_TRIAGE = 60
MAX_DETAILED = 10

T = TypeVar("T", bound=BaseModel)

# Feature -> rooms where evidence can legitimately appear.
FEATURE_ROOMS: dict[str, set[Room]] = {
    "garage": {Room.GARAGE, Room.EXTERIOR_FRONT, Room.EXTERIOR_BACK_YARD, Room.DRIVEWAY},
    "driveway": {Room.DRIVEWAY, Room.EXTERIOR_FRONT, Room.GARAGE},
    "laundry": {Room.LAUNDRY, Room.BASEMENT, Room.KITCHEN, Room.BATHROOM, Room.OTHER},
    "finished_basement": {Room.BASEMENT},
    "basement_bathroom": {Room.BASEMENT, Room.BATHROOM},
    "outdoor_space": {Room.EXTERIOR_BACK_YARD, Room.EXTERIOR_FRONT},
}
CONDITION_ROOMS = {Room.KITCHEN, Room.BATHROOM, Room.LIVING_DINING}  # finishes show here, not bedrooms

TRIAGE_INSTRUCTIONS = """You label real-estate listing photos. For each numbered photo, list the areas visible.
Use "basement" for any below-grade space (exposed foundation, small high windows, utility equipment).
Use "laundry" if a washer, dryer or laundry sink is visible. Label every photo number you were given."""

INSPECT_INSTRUCTIONS = """You check listing photos for specific features for a home buyer.
Rules:
- Only report what is clearly visible. If unsure, answer "unknown". Never answer "absent".
- For every "present" finding, list the photo numbers that clearly show it.
- basement_bathroom: present only if the bathroom is clearly in the basement (below grade), not upstairs.
- finished_basement: present only for a below-grade space with finished walls, flooring and ceiling.
- garage: a garage door or garage interior belonging to this property.
- condition: judge finishes in kitchens/bathrooms/living areas: move_in_ready, updated, dated, needs_work,
  or unknown if the photos are not enough. Cite the photo numbers you used.
- Write every "observation" and "condition_observation" in Spanish."""


class VisionLLM(Protocol):
    model: str

    def parse_images(self, *, instructions: str, text: str, image_urls: list[str], detail: str,
                     schema: type[T]) -> T: ...


class OpenAIVisionLLM:
    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, timeout=180, max_retries=2)
        self.model = model

    def parse_images(self, *, instructions: str, text: str, image_urls: list[str], detail: str,
                     schema: type[T]) -> T:
        content: list[dict] = [{"type": "input_text", "text": text}]
        for i, url in enumerate(image_urls, start=1):
            content.append({"type": "input_text", "text": f"Photo {i}:"})
            content.append({"type": "input_image", "image_url": url, "detail": detail})
        resp = self._client.responses.parse(
            model=self.model, instructions=instructions,
            input=[{"role": "user", "content": content}], text_format=schema,
        )
        if resp.output_parsed is None:
            raise ValueError("Model returned no parsable output")
        return resp.output_parsed


def unknown_targets(prop: Property) -> list[str]:
    """Features (and condition) worth checking in photos."""
    f = prop.features
    targets: list[str] = []
    if not (f.garage.is_present or f.driveway.is_present):
        targets += [n for n in ("garage", "driveway") if getattr(f, n).state is FeatureState.UNKNOWN]
    elif f.garage.state is FeatureState.UNKNOWN:
        targets.append("garage")  # preference points
    for name in ("laundry", "finished_basement", "basement_bathroom", "outdoor_space"):
        if getattr(f, name).state is FeatureState.UNKNOWN:
            targets.append(name)
    la = prop.llm_analysis
    if la is None or la.condition is Condition.UNKNOWN:
        targets.append("condition")
    return targets


def _virtually_staged(prop: Property) -> bool:
    text = f"{prop.description or ''} {' '.join(prop.highlights)}".lower()
    return bool(re.search(r"virtual(ly)?[ -]stag", text))


def select_photos(triage: PhotoTriage, targets: list[str], n_photos: int) -> list[int]:
    """0-based indexes of the most relevant photos for the targets, at most MAX_DETAILED."""
    wanted: set[Room] = set()
    for t in targets:
        wanted |= CONDITION_ROOMS if t == "condition" else FEATURE_ROOMS.get(t, set())
    # Rarer, decisive rooms first (basement/laundry/garage), then the rest.
    priority = [Room.BASEMENT, Room.LAUNDRY, Room.GARAGE, Room.DRIVEWAY, Room.EXTERIOR_BACK_YARD,
                Room.BATHROOM, Room.KITCHEN, Room.EXTERIOR_FRONT, Room.LIVING_DINING, Room.BEDROOM, Room.OTHER]
    chosen: list[int] = []
    for room in priority:
        if room not in wanted:
            continue
        for label in triage.photos:
            idx = label.index - 1
            if 0 <= idx < n_photos and room in label.rooms and idx not in chosen:
                chosen.append(idx)
                if len(chosen) >= MAX_DETAILED:
                    return sorted(chosen)
    return sorted(chosen)


def required_features(prop: Property) -> set[str]:
    """Features that decide eligibility (hard filters) for this property."""
    req = {"laundry", "garage", "driveway"}
    if prop.property_type is PropertyType.SINGLE_FAMILY:
        req |= {"finished_basement", "basement_bathroom"}
    return req


def _reset_photo_features(prop: Property) -> Property:
    features = prop.features.model_copy(deep=True)
    for name in FEATURE_ROOMS:
        if getattr(features, name).source is FeatureSource.PHOTOS:
            setattr(features, name, Feature())
    return prop.model_copy(update={"features": features})


def analyze_photos(prop: Property, llm: VisionLLM) -> Property:
    pa = prop.photo_analysis
    if pa and pa.model != llm.model and pa.skipped_reason != "Nothing unknown":
        # Different photo model: redo from scratch so no findings from the old model remain.
        prop = _reset_photo_features(prop)
        pa = None
    if pa and pa.version == PHOTO_VERSION:
        return prop
    if pa and pa.raw_findings is None and pa.skipped_reason and pa.model == llm.model:
        # Nothing was found last time, so there is nothing to re-word: just mark it current.
        return prop.model_copy(update={"photo_analysis": pa.model_copy(update={"version": PHOTO_VERSION})})
    if pa and pa.raw_findings is not None:
        # Rules changed: re-apply stored model output, no new API calls.
        prop = _reset_photo_features(prop)
        base = dict(model=pa.model, version=PHOTO_VERSION, photos_total=pa.photos_total, photos_triaged=pa.photos_triaged)
        rooms = {int(k): set(v) for k, v in pa.rooms_by_sent.items()}
        return apply_photo_findings(prop, pa.raw_findings, pa.targets, pa.picked, rooms,
                                    prop.photo_urls[:MAX_TRIAGE], base, pa.staged)
    if pa is not None:
        prop = _reset_photo_features(prop)
    targets = unknown_targets(prop)
    staged = _virtually_staged(prop)
    if staged and "condition" in targets:
        targets.remove("condition")  # staged photos don't show real condition
    base = dict(model=llm.model, version=PHOTO_VERSION, photos_total=len(prop.photo_urls), photos_triaged=0)
    if not targets:
        return prop.model_copy(update={"photo_analysis": PhotoAnalysis(**base, skipped_reason="Nothing unknown")})
    if not prop.photo_urls:
        return prop.model_copy(update={"photo_analysis": PhotoAnalysis(**base, skipped_reason="No photos")})

    urls = prop.photo_urls[:MAX_TRIAGE]
    triage = llm.parse_images(instructions=TRIAGE_INSTRUCTIONS, text=f"{len(urls)} listing photos follow.",
                              image_urls=urls, detail="low", schema=PhotoTriage)
    picked = select_photos(triage, targets, len(urls))
    base["photos_triaged"] = len(urls)
    if not picked:
        return prop.model_copy(update={"photo_analysis": PhotoAnalysis(**base, skipped_reason="No relevant photos")})

    detail_urls = [urls[i] for i in picked]
    findings = llm.parse_images(
        instructions=INSPECT_INSTRUCTIONS,
        text="Check these features: " + ", ".join(targets) + f". {len(detail_urls)} photos follow.",
        image_urls=detail_urls, detail="high", schema=PhotoFindings,
    )
    rooms_by_sent = {}  # 1-based number in pass 2 -> rooms from triage
    triage_rooms = {lbl.index - 1: set(lbl.rooms) for lbl in triage.photos}
    for n, idx in enumerate(picked, start=1):
        rooms_by_sent[n] = triage_rooms.get(idx, set())
    return apply_photo_findings(prop, findings, targets, picked, rooms_by_sent, urls, base, staged)


def apply_photo_findings(prop: Property, findings: PhotoFindings, targets: list[str], picked: list[int],
                         rooms_by_sent: dict[int, set[Room]], urls: list[str], base: dict, staged: bool) -> Property:
    features = prop.features.model_copy(deep=True)
    accepted, rejected, likely = [], [], []
    required = required_features(prop)

    def cited_ok(nums: list[int], allowed: set[Room]) -> bool:
        return bool(nums) and all(n in rooms_by_sent for n in nums) and any(rooms_by_sent[n] & allowed for n in nums)

    for name in FEATURE_ROOMS:
        if name not in targets:
            continue
        f: PhotoFinding = getattr(findings, name)
        if f.state != "present":
            continue
        if f.confidence == "low":
            rejected.append(f"{name}: low confidence")
            continue
        if not cited_ok(f.photo_numbers, FEATURE_ROOMS[name]):
            rejected.append(f"{name}: cited photos {f.photo_numbers} not valid for this feature")
            continue
        original = [picked[n - 1] + 1 for n in f.photo_numbers]
        evidence = f"Foto {', '.join(map(str, original))}: {f.observation or 'visible'} (confianza {CONFIDENCE_ES[f.confidence]})"
        if f.confidence != "high" and name in required:
            # Eligibility needs a clear view; keep it as a lead for an in-person check.
            likely.append(f"{name} — {evidence}")
            continue
        if getattr(features, name).state is FeatureState.UNKNOWN:
            setattr(features, name, Feature(state=FeatureState.PRESENT, source=FeatureSource.PHOTOS, evidence=evidence))
            accepted.append(name)

    condition, note = Condition.UNKNOWN, None
    if "condition" in targets and not staged and findings.condition is not Condition.UNKNOWN:
        if cited_ok(findings.condition_photo_numbers, CONDITION_ROOMS):
            condition = findings.condition
            original = [picked[n - 1] + 1 for n in findings.condition_photo_numbers]
            note = f"Foto {', '.join(map(str, original))}: {findings.condition_observation or condition.value}"
            accepted.append("condition")
        else:
            rejected.append(f"condition: cited photos {findings.condition_photo_numbers} not valid")

    analysis = PhotoAnalysis(
        **base, photos_examined=[i + 1 for i in picked], accepted=accepted, rejected=rejected, likely=likely,
        condition=condition, condition_note=note,
        skipped_reason="Estado no evaluado: fotos con decoración virtual" if staged else None,
        raw_findings=findings, targets=targets, picked=picked,
        rooms_by_sent={n: sorted(r) for n, r in rooms_by_sent.items()}, staged=staged,
    )
    return prop.model_copy(update={"features": features, "photo_analysis": analysis})
