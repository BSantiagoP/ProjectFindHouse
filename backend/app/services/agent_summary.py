"""Final per-property summary written by the LLM AFTER filtering, enrichment and scoring.

Grounding rules (checked in code, not just requested in the prompt):
- The model only sees a compact JSON of already-computed facts; it does no arithmetic.
- Every number it writes ($ amounts, %, minutes, scores) must appear in those facts,
  otherwise the summary is rejected and retried once, then left out.
- A property still needing verification can never be "recomendada" (verdict is capped).
- Regenerated only when the facts change (hash), so re-runs cost nothing.
"""

import hashlib
import json
import logging
import re
from typing import Any, Protocol

from app.models.analysis import AgentSummary, SummaryOutput
from app.models.preferences import SearchPreferences
from app.services.discovery import EvaluatedProperty
from app.services.filtering import FilterStatus
from app.services.scoring import CATEGORY_ES, CONDITION_ES, SCENARIO_ES

log = logging.getLogger(__name__)

PROMPT_VERSION = "summary-v3"  # v3: driving times; interest rate per scenario

FEATURE_ES = {
    "garage": "garaje", "driveway": "entrada para autos", "laundry": "lavandería",
    "finished_basement": "sótano terminado", "basement_bathroom": "baño en el sótano", "outdoor_space": "patio / espacio exterior",
}
STATE_ES = {"present": "sí", "absent": "no", "unknown": "desconocido"}
SOURCE_ES = {"provider": "datos MLS", "description": "texto del anuncio", "llm": "texto del anuncio (IA)",
             "photos": "fotos (IA)", "manual": "verificado"}

INSTRUCTIONS = """Eres un asesor que ayuda a una familia a decidir si visitar o descartar una casa en New Jersey.
Recibes un JSON con hechos YA calculados sobre la propiedad. Reglas:
- Escribe todo en español claro y directo.
- Usa SOLO los hechos del JSON. No inventes características, cifras, tasas, ni datos del vecindario.
- Si mencionas un número, cópialo exactamente como aparece en el JSON (por ejemplo "$4,756", "36%", "63 min").
- No hagas cálculos nuevos (no sumes, restes ni conviertas cifras).
- Si un dato es desconocido o está "por verificar", dilo como incertidumbre; no lo trates como positivo.
- verdict: "recomendada" si vale la pena visitarla pronto; "considerar" si tiene puntos fuertes pero dudas
  importantes; "no_recomendada" si los costos u otros problemas pesan más.
- El costo mensual frente a la meta mensual del usuario es el factor más importante para la decisión.
- Las citas del anuncio están en inglés; puedes resumirlas en español sin inventar detalles."""


class SummaryLLM(Protocol):
    def parse_summary(self, *, instructions: str, text: str) -> SummaryOutput: ...


class OpenAISummaryLLM:
    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, timeout=90, max_retries=2)
        self.model = model

    def parse_summary(self, *, instructions: str, text: str) -> SummaryOutput:
        resp = self._client.responses.parse(model=self.model, instructions=instructions, input=text,
                                            text_format=SummaryOutput)
        if resp.output_parsed is None:
            raise ValueError("Model returned no parsable output")
        return resp.output_parsed


def _money(n: float | int | None) -> str | None:
    return None if n is None else f"${n:,.0f}"


def build_facts(ev: EvaluatedProperty, prefs: SearchPreferences) -> dict[str, Any]:
    """Compact, pre-formatted facts. The model may only quote these values."""
    p, a = ev.property, ev.analysis
    primary = a.finance.get(a.primary_scenario) if a else None
    rent_ok = bool(p.rent_estimate and p.rent_estimate.status == "estimated")
    feats = {
        FEATURE_ES[name]: {"estado": STATE_ES[getattr(p.features, name).state.value],
                           "fuente": SOURCE_ES.get(getattr(p.features, name).source.value) if getattr(p.features, name).source else None}
        for name in FEATURE_ES
    }
    facts: dict[str, Any] = {
        "direccion": p.address.raw,
        "pueblo": p.town,
        "precio": _money(p.price),
        "tipo": "unifamiliar" if (p.units or 1) == 1 else f"{p.units} unidades",
        "estado_filtro": {"eligible": "elegible", "needs_verification": "por verificar", "rejected": "descartada"}[ev.filter.status.value],
        "por_verificar": ev.filter.unverified,
        "puntuacion_total": f"{a.score:.0f}/100" if a else None,
        "datos_completos": f"{a.confidence:.0%}" if a else None,
        "categorias": [
            {"nombre": CATEGORY_ES.get(c.name, c.name), "puntos": (f"{c.score:.1f}/10" if c.score is not None else "sin puntuar"),
             "razon": c.reason}
            for c in (a.categories if a else [])
        ],
        "preferencias_usuario": {"precio_maximo": _money(prefs.max_price), "meta_mensual_despues_de_renta": _money(prefs.target_monthly_cost)},
        "financiamiento_principal": None,
        "renta": None,
        "trayecto": None,
        "caracteristicas": feats,
        "estado_de_la_casa": CONDITION_ES.get(p.llm_analysis.condition) if p.llm_analysis else None,
        "alertas_del_anuncio": p.llm_analysis.red_flags if p.llm_analysis else [],
        "probable_segun_fotos": p.photo_analysis.likely if p.photo_analysis else [],
        "impuesto_anual": _money(p.annual_tax),
    }
    if primary:
        facts["financiamiento_principal"] = {
            "escenario": SCENARIO_ES.get(a.primary_scenario.value, a.primary_scenario.value),
            "enganche": _money(primary.down_payment),
            "costo_mensual_vivienda": _money(primary.monthly_housing_cost),
            "pagas_al_mes_despues_de_renta": _money(primary.effective_owner_cost) if rent_ok else "desconocido (renta no estimada)",
            "renta_cubre": f"{primary.rent_offset_pct:.0%}" if rent_ok and primary.rent_offset_pct is not None else None,
            "tasa": f"{a.rate * 100:.2f}%",
        }
    if p.rent_estimate:
        facts["renta"] = {
            "estado": "estimada" if rent_ok else "no estimada",
            "motivo": p.rent_estimate.reason,
            "unidad_del_dueno": p.rent_estimate.owner_unit,
            "unidades_alquiladas": [{"unidad": u.label, "recamaras": u.bedrooms, "renta": _money(u.rent)}
                                    for u in p.rent_estimate.rental_units],
            "total_mensual": _money(p.rent_estimate.monthly_rent_total),
        }
    if p.commute and p.commute.total_minutes is not None:
        facts["trayecto"] = {"total": f"{p.commute.total_minutes} min", "caminata": f"{p.commute.walk_minutes} min",
                             "parada": p.commute.nearest_stop, "ruta": p.commute.route, "destino": p.commute.destination}
    facts["en_auto"] = [{"destino": d.destination, "minutos_sin_trafico": f"{d.minutes} min"}
                        for d in p.drives if d.minutes is not None]
    return facts


def facts_hash(facts: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(facts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


_NUM = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\d+(?:[.,]\d+)?\s?%|\d+(?:\.\d+)?\s?(?:min|/100|/10)\b|\b\d{2,}\b")


def _norm_num(s: str) -> str:
    return re.sub(r"[\s$,]", "", s.lower())


def ungrounded_numbers(summary: SummaryOutput, facts: dict[str, Any]) -> list[str]:
    """Numbers in the summary that do not appear anywhere in the facts."""
    source = _norm_num(json.dumps(facts, ensure_ascii=False))
    text = " ".join([summary.headline, *summary.reasons_for, *summary.reasons_against, *summary.next_steps])
    bad = []
    for m in _NUM.finditer(text):
        token = _norm_num(m.group())
        core = re.sub(r"(min|/100|/10|%)$", "", token)
        if core and core not in source:
            bad.append(m.group())
    return bad


def summarize(ev: EvaluatedProperty, prefs: SearchPreferences, llm: SummaryLLM, *, model: str) -> AgentSummary | None:
    facts = build_facts(ev, prefs)
    h = facts_hash(facts)
    current = ev.property.agent_summary
    if current and current.facts_hash == h and current.prompt_version == PROMPT_VERSION:
        return current
    text = json.dumps(facts, ensure_ascii=False, indent=1)
    for attempt in range(2):
        out = llm.parse_summary(instructions=INSTRUCTIONS, text=text)
        bad = ungrounded_numbers(out, facts)
        if not bad:
            adjusted = False
            if ev.filter.status is not FilterStatus.ELIGIBLE and out.verdict == "recomendada":
                out = out.model_copy(update={"verdict": "considerar"})  # can't recommend before verification
                adjusted = True
            return AgentSummary(**out.model_dump(), model=model, prompt_version=PROMPT_VERSION,
                                facts_hash=h, verdict_adjusted=adjusted)
        log.info("Summary for %s cited numbers not in facts %s (attempt %d)", ev.property.address.raw, bad, attempt + 1)
        text += f"\n\nATENCIÓN: tu respuesta anterior incluyó cifras que no están en el JSON ({', '.join(bad)}). Usa solo cifras del JSON."
    return None
