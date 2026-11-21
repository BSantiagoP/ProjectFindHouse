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
  - **Compared against units in 2–4 family houses** (RentCast "Multi-Family"), not apartment
    complexes. A check on 2026-11-20 showed "Apartment" comparables came 11 of 15 from one large
    complex (520 Cliff St, Fairview) and overstated a 2-bed by about $600–$1,000/month ($3,510 vs.
    $2,900). Rents were re-estimated with the corrected method.
  - Each rent shows RentCast's low–high range and **up to 8 comparable rentals** (address, rent,
    beds/baths, size, distance, age) under "Ver rentas comparables", so you can judge it yourself.
- **Then, conservatively, the app deducts:** 5% vacancy, 10% repairs/management, 5% reserves.
  So "net rent" is 80% of the estimate.
- **Limits:**
  - It's an estimate, not a lease. Real rent depends on unit condition, and the actual tenant
    situation (some listings are tenant-occupied until 2027).
  - Glance at the comparables: if they're bigger, newer or have more baths than the unit, the
    real rent is likely lower. A local agent can confirm.

## Financing (3 scenarios)

All three are shown on each report. **The score and the cards use conventional 20% down**:
20% down payment, no mortgage insurance, the weekly Freddie Mac rate.

All math is plain formulas in code (no AI): standard 30-year amortization, checked in tests
against hand calculations ($100,000 at 6% = $599.55/month).

| Input | Value | Source / trust |
|---|---|---|
| Mortgage rate | Weekly Freddie Mac 30-yr average (shown per scenario as "Tasa de interés") | FRED (official), or your manual rate in Preferencias |
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

## Commute: driving time to 576 Bergen Blvd, Ridgefield

- **This is the only commute measured.** 7 WTC was dropped on 2026-11-20.
- **Source:** the road route from each home to the address, using **LocationIQ Directions**
  (OpenStreetMap roads; free plan, 5,000 requests/day). If LocationIQ is down, the public OSRM
  server is used as a backup, and each time records which service produced it.
- **Destination coordinates** come from the official US Census geocoder.
- **Why it's reasonable:** it uses real road distances and speed limits, not straight lines.
- **Limits:** it is **free-flow time, with no traffic**. Rush hour will be longer, sometimes much
  longer on Route 46 or Route 1&9.
- **How it's scored:** the location category (25% of the score) uses this time only: 10/10 at
  5 min or less, 0 at 35 min or more, linear in between. The scale is an **assumption** that leaves
  room for traffic. If a time couldn't be computed, the category counts as 0.

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

## Discarded homes

"Descartar" hides a home from every list right away, and the top 5 refills with the next
best home. It is also excluded from ranking on later searches. Use "Ver descartadas" at the
bottom of the page to restore one.

## Score (0–100)

- **Weights:** Asequibilidad 30%, Ubicación y trayecto 25%, Estado 20%, Potencial de renta 15%,
  Preferencias 10%.
- **Deterministic:** the same data always gives the same score. Each category shows its reason.
- **Asequibilidad compares "pagas al mes" to your monthly target, using the conventional loan with
  20% down** (changed from FHA on 2026-11-20; editable in Preferencias). Rent is deducted for multifamily
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

## Running HomeScout

### Run it manually (current setup)

There is **no automatic schedule right now**; you start each search yourself. From Terminal:

```bash
cd ~/Projects/FindingAHouse/backend
poetry run python -m app.jobs.daily_search --force
```

- `--force` runs now. Without it, the job only runs if the last search was 2 or more days ago
  and it's after 8 AM Eastern.
- It takes about 1–3 minutes and prints progress in the terminal. The last line shows the result,
  e.g. `Run … succeeded {'eligible': 6, …}`.
- When it finishes, refresh **https://homescout-delta.vercel.app** to see new homes ("Nueva").
- **Cost per run:** about 50 HasData credits for the 5 town searches, plus 10 per new listing.
  New listings also use a few cents of OpenAI and possibly RentCast lookups (capped at 45 a month).
  Driving times are free. Re-running on the same day mostly re-uses saved results.
- **Texts are off** (`SMS_ENABLED=false`), so nothing is sent.

### Turn the schedule on your Mac back on (optional)

Every other day from 8 AM, catching up when the Mac wakes:

```bash
cp ~/Projects/FindingAHouse/backend/scripts/launchd/com.homescout.daily.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.homescout.daily.plist
```

The log is at `~/Library/Logs/HomeScout/daily.log`. To turn it off again:

```bash
launchctl bootout gui/$(id -u)/com.homescout.daily
rm ~/Library/LaunchAgents/com.homescout.daily.plist
```

### Move the scheduled search to Railway (when you decide)

Railway runs the same job in the cloud, so your Mac doesn't need to be on. The dashboard stays on
Vercel and the data stays in Supabase; only the search job moves.

1. **Create a Railway account** at railway.app and a new project, then **deploy from the GitHub repo**
   `BSantiagoP/ProjectFindHouse`.
2. In the service's **Settings**:
   - **Root directory:** `backend`
   - **Start command:** `python -m app.jobs.daily_search`
   - **Cron schedule:** `0 13 * * *`. Railway cron uses **UTC**: 13:00 UTC is 8 AM Eastern in
     winter and 9 AM in summer. The job runs daily but only searches every other day, by its own rule.
   - Railway detects Python from `pyproject.toml` / `poetry.lock`. The job needs **Python 3.12**; if
     the build picks another version, set the Python version in the service settings.
3. In the service's **Variables**, add the same values as your local `.env` (copy them from `.env`;
   never commit them):
   - `PROVIDER=hasdata`, `HASDATA_API_KEY`
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
   - `OPENAI_API_KEY` (optional: `OPENAI_MODEL`, `OPENAI_VISION_MODEL`)
   - `RENTCAST_API_KEY`, `LOCATIONIQ_API_KEY`
   - `MAX_REQUESTS_PER_RUN=25`, `MAX_PAGES_PER_TOWN=1`, `FETCH_DETAILS=true`
   - `SMS_ENABLED=false`, `DASHBOARD_URL=https://homescout-delta.vercel.app`
   - Not needed on Railway: `API_TOKEN` (only for the local API) and the `RECIPIENT*` / `TWILIO_*` values.
4. **Test once:** in Railway, run the service manually and check its logs for `Run … succeeded`.
   Then check the dashboard.
5. **Avoid double runs:** keep the Mac schedule off, as it is now, once Railway is running.
   Both would spend HasData credits.

Railway's hobby plan costs about $5/month. A cron job that runs a few minutes every other day uses
very little of that.

---

## What you should still verify yourself

1. **Get a lender quote:** the real rate, FHA vs. conventional, PMI or MIP, and closing costs.
2. **Get a homeowners insurance quote** for a 2-family home (replace the $2,400 default in Preferencias).
3. **Check rent:** look at 3–5 current rentals near the home with the same bedrooms, and the
   current lease status.
4. **Visit:** confirm laundry, parking, basement and bathroom, especially anything marked
   "Fotos (IA)" or "Probable según fotos".
5. **Drive to Ridgefield once at rush hour** from your top choice.
6. **Get an inspection:** condition, and whether a basement unit is legal.

## How it's tested

- 168 automated tests cover every rule above.
- Tests block all real network calls.
- Real-data checks were run and the bugs they found were fixed. See the git history for details.
