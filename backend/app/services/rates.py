"""Weekly 30-year fixed mortgage rate (Freddie Mac PMMS via FRED, no API key)."""

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date

import httpx

log = logging.getLogger(__name__)

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US"


@dataclass(frozen=True)
class MortgageRate:
    annual_rate: float  # e.g. 0.0625
    as_of: date | None
    source: str


def parse_fred_csv(text: str) -> MortgageRate | None:
    rows = list(csv.reader(io.StringIO(text)))
    for row in reversed(rows[1:]):
        if len(row) >= 2 and row[1] not in ("", "."):
            try:
                return MortgageRate(float(row[1]) / 100, date.fromisoformat(row[0]), "FRED MORTGAGE30US")
            except ValueError:
                continue
    return None


def current_rate(override: float | None, *, fallback: float = 0.065, client: httpx.Client | None = None) -> MortgageRate:
    if override is not None:
        return MortgageRate(override, None, "manual override")
    try:
        resp = (client or httpx.Client(timeout=20)).get(FRED_CSV)
        resp.raise_for_status()
        if rate := parse_fred_csv(resp.text):
            return rate
    except Exception as exc:
        log.warning("FRED rate fetch failed: %s", exc)
    return MortgageRate(fallback, None, "fallback default (FRED unavailable)")
