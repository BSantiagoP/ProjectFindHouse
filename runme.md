# HomeScout — why the numbers can be trusted (and where they can't)

This explains where every value on the dashboard comes from, how it is checked, and its limits.
Short version: **facts come from named sources and are never invented; anything uncertain is
shown as unknown or "por verificar"; estimates are labeled as estimates.** Treat the dashboard
as a well-researched first filter. It does not replace a visit, a lender quote, or an inspection.

---

## The core rule: no unsupported claims

Every value is in one of three states: **present**, **absent**, or **unknown**. Unknown is never
treated as good. A missing laundry room is "por verificar", not "yes", and unknown score
categories count as **0** (the "% datos" badge shows how much of the score is backed by real data).

Every feature shows **where it came from**:

| Source (label on the site) | What it is | Trust |
|---|---|---|
| Datos MLS | Structured fields from the listing's MLS record (via HasData) | Highest |
| Texto del anuncio | An exact keyword match in the listing text | High |
| Texto del anuncio (IA, citado) | AI read the text, **and the code verified its quote exists in the listing and mentions that feature** | High |
| Fotos (IA) | AI looked at specific listing photos, cited by number | Medium; see Photos |

---

## Listing data (price, town, type, units, taxes)

- **Source:** Zillow listings through HasData (a scraping API, not an official Zillow feed).
- **Checked:** On 2026-11-20 you manually verified 4 of 4 eligible listings against Zillow:
  price, town, garage and laundry were all correct.
- **Safeguards found from live data:**
  - A listed price of $0 is treated as unknown.
  - The `hasGarage: false` field is ignored, because it contradicted real listings.
  - Duplicate listings of the same building are merged.
- **Limits:**
  - Data is as fresh as Zillow's listing. A property can go pending before the next search.
  - Annual tax is the listing's figure, which may predate a reassessment after sale.

---

## Rent (RentCast)

- **Source:** RentCast's rent estimate (an automated valuation model, AVM) built from nearby
  rental listings. It is the same kind of estimate landlords and lenders use as a starting point.
- **Why it's reasonable:**
  - **Only the rental unit(s) are priced.** You live in the largest unit, and each other unit is
    priced separately with its own bedroom count.
  - Live testing showed RentCast's whole-building number ($4,260 for a 5-bed 2-family) would have
    roughly **doubled** the apparent rent offset, so it is not used.
  - The unit layout comes from the listing text with verified quotes. "Basement suites" are not
    counted as legal rental units.
  - If bedrooms per unit aren't stated, rent is **not estimated** rather than guessed.
  - Each rent shows RentCast's low–high range.
- **Then, conservatively, the app deducts:** 5% vacancy, 10% repairs/management, 5% reserves.
  So "net rent" is 80% of the estimate.
- **Limits:**
  - It's an estimate, not a lease. Real rent depends on unit condition, and the actual tenant
    situation (some listings are tenant-occupied until 2027).
  - Check a few comparable listings or ask a local agent before counting on it.

## Financing (3 scenarios)

All math is plain formulas in code (no AI): standard 30-year amortization, checked in tests
against hand calculations ($100,000 at 6% = $599.55/month).

| Input | Value | Source / trust |
|---|---|---|
| Mortgage rate | Weekly Freddie Mac 30-yr average | FRED (official), or your manual rate in Preferencias |
| FHA rate | Freddie Mac rate − 0.25% | **Assumption.** FHA usually prices a bit lower; get a quote |
| FHA upfront MIP | 1.75%, financed | HUD standard |
| FHA annual MIP | 0.75% (loans > $726,200) / 0.55% (smaller) | HUD ML 2023-05; corrected 2026-11-20 |
| Conventional 5% PMI | 0.5%/year | **Assumption.** Real PMI depends on credit score |
| Property tax | From the listing | Listing / MLS |
| Home insurance | $2,400/year | **Assumption.** Editable in Preferencias; get a quote for 2-family |
| Maintenance | 1% of price per year | Common rule of thumb; **assumption** |

- **Limits:**
  - Closing costs are not included.
  - FHA loan limits are not checked. Bergen County limits are far above these prices, so this is
    not an issue today.
  - A lender may also count only ~75% of projected rent when qualifying you.

## Commute to 7 WTC

- **Method:**
  - A researched stop-to-WTC time for each town (from trip planners and NJ Transit route info).
  - **Plus** the walk to the nearest stop that has a **New York-bound** NJ Transit bus, or to the
    rail station (Lyndhurst). Stops come from NJ Transit's official GTFS data.
  - Walk = straight-line distance × 1.25, at 80 m per minute.
- **Limits:**
  - This is an estimate, **not door-to-door routing** (Google Maps is not connected).
  - Rush-hour traffic, transfer waits and service changes vary.
  - Town times are editable in Preferencias if your own experience differs.

## Features from photos (AI)

- **Method:** the photo model labels all photos by room, then closely inspects at most 10
  relevant ones.
- **Rules enforced in code:**
  - Photos can only **confirm** a feature, never mark it absent.
  - Every finding must cite photo numbers that were actually examined and show the right room.
  - **Required features** (laundry, parking, and the basement and bath for single-family homes)
    need **high** confidence. Medium findings appear as "Probable según fotos — verifícalo en
    persona" and don't make a home eligible.
  - Virtually staged photos are not used to judge condition.
- **Limits:**
  - This is the least reliable source. In testing, two AI models each made a confident mistake
    (one called an above-ground living room a "finished basement").
  - The same model can also answer differently on a second run, which is why each home is analyzed
    once and the result is saved.
  - Always verify photo-based findings in person.

## Score (0–100)

- **Weights:** Asequibilidad 30%, Ubicación y trayecto 25%, Estado 20%, Potencial de renta 15%,
  Preferencias 10%.
- **Deterministic:** the same data always gives the same score. Each category shows its reason.
- **Asequibilidad compares "pagas al mes" to your monthly target.** Rent is deducted for multifamily
  homes.
- **Missing data counts as 0,** so a home can't rank high on unknowns. The "% datos" badge shows
  how much of the score is backed by real data.

## Resumen del agente (AI summary)

- **Written last,** after filtering, enrichment and scoring, from a compact list of **already
  computed facts**. The AI does no math and sees no raw web data.
- **Checked in code:**
  - **Every number it writes must exist in those facts.** Otherwise it is asked once to fix it,
    and if it still invents a number, no summary is shown.
  - A home that still needs verification can never be "Recomendada" (it is capped at
    "Considerar", and the page says so).
- **Regenerated only when the underlying facts change.**
- **Limits:** it is a plain-language opinion built on the numbers above, so it inherits their
  assumptions. Use it to decide **which homes to visit**, not whether to buy.

---

## What you should still verify yourself

1. **Get a lender quote:** the real rate, FHA vs. conventional, PMI or MIP, and closing costs.
2. **Get a homeowners insurance quote** for a 2-family home (replace the $2,400 default in Preferencias).
3. **Check rent:** look at 3–5 current rentals near the home with the same bedrooms, and the
   current lease status.
4. **Visit:** confirm laundry, parking, basement and bathroom, especially anything marked
   "Fotos (IA)" or "Probable según fotos".
5. **Do the commute once at rush hour** from your top choice.
6. **Get an inspection:** condition, and whether a basement unit is legal.

## How it's tested

- 157 automated tests cover every rule above.
- Tests block all real network calls.
- Real-data checks were run and the bugs they found were fixed. See the git history for details.
