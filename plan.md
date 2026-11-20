# HomeScout AI — Finalized Development Plan

**Status:** Architecture finalized; provider validation and production approvals pending  
**Purpose:** Private AI-powered home-search application that discovers, evaluates, ranks, and sends up to five matching properties to three consenting phone numbers.  
**Development target:** 14 days, contingent on data permissions and SMS approval.  
**Target operating budget:** $10–35/month during MVP testing; not a guaranteed production price.

## 1. Goals and scope

HomeScout AI will search newly listed houses in selected New Jersey towns, prioritize multifamily properties, estimate financial fit, explain tradeoffs, and send a daily digest to three recipients. It will track previously seen properties and price changes to avoid repetitive alerts.

### Working search preferences

| Setting | Initial value |
|---|---|
| Towns | Cliffside Park, Lyndhurst, Fairview, Elmwood Park, Saddle Brook, NJ |
| Property type | Multifamily 2–4 units; single-family **only** with a fully finished basement that has a bathroom; condos and townhouses excluded |
| Maximum purchase price | **$900,000**; editable in app |
| Parking | Required: garage or driveway (garage scores higher); street-only fails |
| Laundry | **Required** (in-unit, in-building, or hookups) |
| Basement | Finished basement with bathroom preferred (required for single-family) |
| Commute | Public transit to **7 World Trade Center, 250 Greenwich St, New York, NY 10007**; destinations stored as a list (one per recipient possible) |
| Financing | Three scenarios side by side: FHA 3.5%, conventional 5%, conventional 20%; user picks the primary one for scoring |
| Mortgage rate | Weekly Freddie Mac 30-yr average (FRED) + FHA spread, with manual override |
| Listing recency | Past 7 days |
| Search schedule | Daily at 8:00 AM America/New_York |
| Maximum recommendations | 5 per report; fewer if insufficient matches |
| Notification recipients | 3 consenting phone numbers, configured securely |
| Delivery | SMS summary with authenticated dashboard link |

These are working defaults and must be confirmed before production. Unknown property features should be flagged for verification, not silently treated as absent or present. For unknown required fields (laundry, parking, basement), the photo analyzer runs first; if they are still unknown, the property goes to a verification queue and is not texted.

### MVP functionality

1. Discover active listings from an approved provider.
2. Filter by town, price, property type, parking, and preferences.
3. Normalize provider records and deduplicate across searches and towns.
4. Detect new listings and meaningful price changes.
5. Enrich promising candidates with permitted property and location data.
6. Calculate mortgage, expenses, and potential rent offset.
7. Analyze listing descriptions with an LLM and cite underlying evidence.
   - Limited photo analysis (OpenAI vision) for shortlisted properties whose descriptions don't mention laundry, basement finish/bath, garage, or yard. Max ~10 photos; findings labeled "from photos" with confidence.
8. Score properties deterministically and explain rankings.
9. Save results and history in a private dashboard.
10. Deliver up to five top matches to three consenting SMS recipients.
11. Log search runs, API usage, failures, and notification status.
12. Capture user feedback on shortlisted properties.

### Later features (not MVP)

- Full image-based condition screening (the limited feature-check version is in the MVP; both subject to photo-use permissions).
- Rental comparables and sold comparables from licensed sources.
- Feedback-driven weight tuning (MVP stores feedback only; rejected properties are never re-sent).
- Price-drop re-alerts (MVP shows price changes in the dashboard only).
- Inspection and disclosure document analysis with retrieval/citations.
- Offer and renovation scenario modeling.
- More advanced property memory; knowledge graph only if it proves useful.

## 2. Provider decision and validation

**First provider to prototype: HasData Zillow API.** HasData is a third-party scraping-based service, **not an official Zillow API**. Its documented Zillow search and property-details features appear suitable for the MVP, but neither NJ coverage nor production rights have been independently established.

**Fallback: RentCast**, after verifying its coverage, freshness, license, and cost. An MLS-authorized integration may be preferable if available later.

**Production gates:**

- Confirm permitted collection, retention, analysis, and distribution/SMS use in writing or through sufficiently clear licensing terms.
- Verify accuracy and freshness with manually checked samples in the target towns.
- Confirm actual plan limits, pagination costs, and monthly usage projections.
- Do not assume paying for a scraper API grants rights to Zillow content.
- If licensing or data-quality checks fail, do not deploy HasData; switch the adapter to an approved provider.

**Acceptance targets (internal goals, not vendor guarantees):**

| Metric | Target |
|---|---|
| Eligible listing discovery recall | ≥95% on a manually sampled benchmark |
| Freshness | ≥95% within 24 hours of source updates |
| Critical field accuracy | ≥98% on validated sample |
| Scheduled-search success | ≥99% over test period |
| Duplicate property notifications | Zero |
| API budget | Within approved monthly ceiling |
| Licensing | Confirmed before production |

**Provider references:**

- HasData Zillow API: https://hasdata.com/apis/zillow-api
- RentCast API: https://www.rentcast.io/api
- Zillow Group developer APIs: https://www.zillowgroup.com/developers/
- RESO Web API standard: https://www.reso.org/reso-web-api/

## 3. Technology stack

| Layer | Choice | Responsibility |
|---|---|---|
| Backend | Python 3.12 + FastAPI | HTTP API and application services |
| Models | Pydantic | Typed normalized property contracts |
| AI orchestration | LangGraph | Conditional enrichment and analysis workflow |
| LLM | OpenAI API | Description interpretation and grounded explanations |
| Database | Supabase PostgreSQL | Properties, history, analyses, runs, reports |
| Authentication | Supabase Auth | Private dashboard access |
| Frontend | Next.js + TypeScript | Dashboard and preference management |
| Scheduling | Cron-based worker | Daily runs in Eastern time |
| SMS | Twilio | Three-recipient digest and delivery receipts |
| Testing | Pytest, HTTPX, mocks | Unit, contract, integration, evaluation, E2E |
| Monitoring | Structured logs and alerts | Run failures, spend, and delivery problems |
| Hosting | Railway (API + cron worker), Vercel (Next.js), Supabase | Deployment |
| Enrichment | RentCast (rent), Google Routes API (transit), FRED (rates), OpenAI vision (photos) | Analysis inputs |

Start Twilio A2P 10DLC registration on Day 1 so it runs alongside the build; until it's approved, reports appear only in the dashboard. For US SMS, verify A2P 10DLC or other applicable sender-registration obligations, opt-in/opt-out handling, and current Twilio fees before enabling live delivery. Do not collect recipient phone numbers in source control.

## 4. End-to-end architecture

```text
Daily scheduler (8 AM America/New_York)
  -> PropertyProvider interface
       -> HasData adapter (conditional approval)
       -> RentCast adapter (fallback)
  -> Normalize records with Pydantic
  -> Persist listing snapshots and deduplicate
  -> Apply mandatory filters and uncertainty flags
  -> Shortlist candidates for enrichment
  -> LangGraph analysis
       -> Route enrichment
       -> Fetch permitted detail / risk / commute data
       -> Calculate finances deterministically
       -> Interpret listing description
       -> Score candidates deterministically
       -> Generate grounded explanations
       -> Validate output and evidence
  -> Select up to five eligible new/changed properties
  -> Persist report and delivery jobs
  -> Twilio SMS to 3 consenting recipients
  -> Authenticated Next.js dashboard
```

### Workflow details

1. **Discovery:** Search each configured town within a rolling seven-day listing window; track the last successful run so temporary outages do not cause missed listings.
2. **Normalization:** Map all provider responses into one internal `Property` schema.
3. **Deduplication:** Use `(provider, listing_id)` and, where reliable, normalized address plus unit identifiers.
4. **Filtering:** Enforce known hard requirements; route missing parking/unit data to a verification queue.
5. **Enrichment:** Call additional services only for strong candidates to conserve API credits.
6. **Analysis:** Use deterministic Python for calculations; use the LLM for ambiguous descriptions and explanations.
7. **Validation:** Reject unsupported numeric claims, missing source URLs, schema violations, or inconsistent scoring.
8. **Selection:** Return at most five properties; never invent filler listings.
9. **Delivery:** Persist an idempotent notification job per recipient and report; retry failures without duplicate messages.

### Optional enrichment APIs

| Need | Candidate source | Caveat |
|---|---|---|
| Flood exposure | FEMA National Flood Hazard Layer | Interpret map layers carefully |
| Commute times | Google Maps Routes API (transit mode, to 7 WTC) | Usage-based billing; cache per property |
| Taxes | Provider or local public records | Jurisdiction-specific availability |
| Rent estimates | RentCast (MVP, shortlisted properties only) | Estimates, not guaranteed rent; verify free-tier limits |
| Mortgage rates | FRED (Freddie Mac PMMS 30-yr) | Weekly average; FHA spread applied; manual override |
| Comparable sales | Licensed property data provider | Coverage and rights must be validated |

## 5. Ranking and financial model

### Initial weighted scoring

| Criterion | Weight |
|---|---:|
| Financial affordability | 30% |
| Location and commute | 25% |
| Property condition | 20% |
| Rental potential | 15% |
| Personal preferences | 10% |
| **Total** | **100%** |

Each category receives a 0–10 score. Final score:

```text
final_score = sum(weight_percent * category_score / 10)
```

Hard filters run before ranking. Store confidence levels, missing fields, evidence references, and explicit rejection reasons. Avoid rewarding unknowns as if they were verified positives.

### Financial calculations

- Down payment = purchase price × down-payment percentage.
- Loan principal = purchase price − down payment.
- Mortgage principal-and-interest payment = standard amortization formula.
- Monthly property tax = annual tax / 12.
- Monthly insurance = annual insurance / 12.
- Monthly housing cost = principal + interest + taxes + insurance + HOA + relevant expenses.
- Net rental contribution = estimated rental income − rental operating costs, vacancies, and reserves.
- Effective owner cost = monthly housing cost − net rental contribution.
- Rent-offset percentage = net rental contribution / monthly housing cost (where denominator is positive).

Each property is calculated under three scenarios (FHA 3.5% down with MIP, conventional 5% down with PMI, conventional 20% down); affordability is scored on the user-selected primary scenario.

**Hard-filter rules:** max $900k; multifamily 2–4 units, or single-family only with a finished basement with a bathroom; garage or driveway required; laundry required.
**Preferences (10%):** finished basement with bath, backyard/outdoor space; garage scores above driveway.

Support configurable mortgage rates, down payment, maintenance, vacancy, insurance, closing costs, and renovation scenarios. A finished basement is **not** proof of a legal rental unit; verify local approvals before counting it as rentable.

## 6. Data model

| Table | Important fields |
|---|---|
| `search_preferences` | locations, max_price, property_types, required_features, weights, commute_destinations[] (address, mode), finance_scenarios, primary_scenario, rate_override, preference_keywords |
| `properties` | id, address, town, price, units, status |
| `provider_listings` | provider, external_id, property_id, source_url, last_seen |
| `property_snapshots` | property_id, price, status, observed_at |
| `property_analyses` | property_id, score, confidence, findings, model_version |
| `photo_findings` | property_id, feature, value, confidence, photo_url, model_version |
| `search_runs` | started_at, completed_at, status, api_calls, error |
| `reports` | id, search_run_id, created_at, status |
| `report_properties` | report_id, property_id, rank |
| `notification_recipients` | id, encrypted_phone, consent_status, enabled |
| `notifications` | report_id, recipient_id, provider_message_id, status |
| `property_feedback` | property_id, liked, rejected, reason, notes |

Enforce uniqueness on provider listing IDs and notification idempotency keys. Apply authentication, row-level security, secret management, and encryption of phone numbers. Observe source-provider retention restrictions.

## 7. API endpoints

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/properties` | List saved properties |
| GET | `/api/properties/{id}` | View property and analysis |
| POST | `/api/searches` | Trigger authorized manual search |
| GET | `/api/searches/{id}` | Search progress and result |
| GET | `/api/reports/latest` | Latest report |
| GET | `/api/preferences` | Read preferences |
| PUT | `/api/preferences` | Update preferences |
| POST | `/api/properties/{id}/feedback` | Save feedback |
| POST | `/api/webhooks/twilio` | Verify and process Twilio status events |

Protect all private endpoints with authentication and validate Twilio webhook signatures.

## 8. LangGraph specification

```text
load_candidates
  -> route_enrichment
  -> enrich_property (conditional / bounded parallelism)
  -> calculate_finances
  -> analyze_description
  -> analyze_photos (conditional: only if required/preferred features unknown)
  -> score_property
  -> generate_explanation
  -> validate_analysis
  -> select_top_five
  -> persist_report
```

The analysis graph should use typed state, retries with limits, structured LLM outputs, model/prompt version tracking, and deterministic validation. Where appropriate, financial calculation and description analysis can run concurrently. Do not use an LLM to perform basic search filtering or mortgage arithmetic.

## 9. Notifications

**Default:** one daily SMS digest per recipient at 8:00 AM Eastern, containing up to five properties and a link to the authenticated report.

Example (fictional):

```text
HomeScout AI — Daily Matches
3 new houses match your search.
1. Lyndhurst — $695,000 — 2-family, parking — 91/100
2. Fairview — $725,000 — 2-family, basement — 87/100
3. Cliffside Park — $749,000 — 2-family, parking — 83/100
View your private report: [authenticated URL]
```

Rules:

- Three separate, consenting recipients.
- One digest per scheduled run; no repeated unchanged listings.
- No price-drop re-alerts; price changes are shown in the dashboard only.
- No SMS on zero-match days (the run is still logged).
- Rejected properties are never re-sent.
- Delivery tracking and retry policy with idempotency.
- Opt-out handling and SMS compliance.
- Authentication required for full report; do not place sensitive analysis in public URLs.

## 10. Repository structure

```text
homescout-ai/
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py
│   │   ├── core/{config.py,security.py,logging.py}
│   │   ├── api/{properties.py,preferences.py,reports.py,searches.py}
│   │   ├── models/{property.py,preferences.py,analysis.py}
│   │   ├── providers/{base.py,hasdata.py,rentcast.py}
│   │   ├── services/{discovery.py,filtering.py,deduplication.py,finance.py,scoring.py,reporting.py}
│   │   ├── agents/{state.py,graph.py,nodes.py,prompts.py}
│   │   ├── notifications/{twilio_client.py,dispatcher.py}
│   │   ├── repositories/
│   │   └── jobs/daily_search.py
│   └── tests/{unit,integration,contract,evals}/
├── frontend/{app,components,lib}/
├── supabase/migrations/
├── docs/{architecture.md,api-contracts.md,acceptance-tests.md}
├── .github/workflows/
├── .env.example
├── .gitignore
└── README.md
```

## 11. QA and evaluation

- **Unit tests:** Pydantic validation, hard filters, scoring, finance formulas, date handling, and deduplication.
- **Contract tests:** Recorded/authorized API fixtures, missing fields, pagination, rate limits, and schema changes.
- **Integration tests:** Database transactions, scheduler behavior, authenticated routes, notification queue.
- **LLM evaluations:** Evidence grounding, uncertainty labels, no invented amenities or legal claims, and score explanation consistency.
- **End-to-end tests:** Discovery → analysis → report → three mocked SMS deliveries.
- **Security tests:** Authorization, secret leakage, webhook signature verification, rate limiting, and row-level security.
- **Operational tests:** Retries, outage recovery, idempotency, cost caps, and timezone/DST behavior.

## 12. Development roadmap

| Days | Milestone | Deliverable |
|---|---|---|
| 1–2 | Foundation and provider validation | FastAPI skeleton, provider interface, live API sample and rights review |
| 3–4 | Normalization, filtering, persistence | Saved, deduplicated candidate listings and contract tests |
| 5–7 | Financial analysis, scoring, LangGraph | Ranked, evidence-backed property analyses |
| 8–10 | Dashboard and notifications | Authenticated report UI and three-recipient staging SMS flow |
| 11–14 | QA, reliability, launch gates | Production-ready deployment if permissions and tests pass |

The schedule is a development target; data licensing and US SMS sender approval may extend production launch.

## 13. Cost model

**Initial target:** $10–35/month for a low-volume personal MVP, assuming an applicable free listing allowance. This excludes possible one-time SMS registration fees and is not guaranteed.

| Component | Planning range / decision |
|---|---|
| HasData | Start with actual account free allowance; verify current limits |
| OpenAI API | Approx. $1–5/month for limited text analysis |
| Supabase and hosting | Approx. $0–15/month at low usage |
| Twilio number, messages, recurring registration | Approx. $5–15+/month; confirm actual charges |
| Paid property provider | Additional expense if free quota or licensing inadequate |
| RentCast | Free tier first; shortlisted properties only |
| Google Routes (transit) | Usage-based; cached per property |
| OpenAI vision | ≤10 photos, shortlisted properties with unknown features only |
| Railway + Vercel | Approx. $5/month + free tier |

Five towns searched daily may require ~150 search calls in a 30-day month **before** pagination, retries, or property-detail requests. Enforce a request budget, cache permitted results, and enrich only shortlisted candidates.

## 14. Production release checklist

- [x] Confirm max purchase price ($900k), commute destination (7 WTC), and other search preferences.
- [ ] Confirm photo-use rights alongside HasData licensing.
- [ ] Start Twilio A2P 10DLC registration (Day 1).
- [ ] Confirm HasData data-use permissions or select approved fallback.
- [ ] Validate listing coverage and freshness in target NJ towns.
- [ ] Verify provider API quota and projected monthly cost.
- [ ] Implement and test hard filters and property deduplication.
- [ ] Verify deterministic financial formulas.
- [ ] Pass LLM grounding and uncertainty evaluations.
- [ ] Confirm authentication, database access controls, and secret storage.
- [ ] Obtain consent from all three SMS recipients.
- [ ] Complete applicable Twilio sender registration and compliance steps.
- [ ] Verify independent delivery to all three recipients.
- [ ] Verify retry, monitoring, and duplicate prevention.
- [ ] Deploy scheduler and dashboard only after all release gates pass.

## 15. First implementation milestone

1. Create the GitHub repository `homescout-ai`.
2. Set up Python 3.12, Poetry, FastAPI, Pydantic, and Pytest.
3. Create the `PropertyProvider` protocol and normalized `Property` model.
4. Obtain HasData development credentials and confirm applicable permissions.
5. Implement HasData search adapter with timeouts, rate limits, pagination, and errors.
6. Search the five configured towns using a small development request budget.
7. Compare returned listings with manually reviewed examples.
8. Save permitted sanitized test fixtures and build contract tests.

**Milestone 1 definition of done:** A local authenticated API request returns a validated, deduplicated JSON list of eligible properties, including source URL, price, town, listing date, and verified or unknown feature fields.

## 16. Final decisions and open items

| Decision | Status |
|---|---|
| Architecture | Finalized |
| Prototype listing provider | HasData |
| Fallback provider | RentCast |
| AI workflow | LangGraph |
| Database | Supabase PostgreSQL |
| Frontend | Next.js |
| SMS | Twilio, three recipients |
| Schedule | Daily 8 AM Eastern (editable) |
| Max properties | Five |
| Max purchase price | $900,000 |
| Townhouses | Excluded (confirmed 2026-11-20) |
| Commute destination | 7 WTC, public transit |
| Hosting | Railway + Vercel + Supabase |
| Rent data | RentCast |
| Photo analysis | MVP, limited |
| Financing | FHA 3.5% / conv 5% / conv 20%, FRED rate + override |
| Price-drop alerts | Off (dashboard only) |
| API keys and SMS recipients | **Provided as we go** |
| Provider data quality | Live test 2026-11-20: 13 listings across 5 towns; 4/4 eligible spot-checked by user as accurate |
| HasData plan | Free plan (1,000 credits/month) for now; upgrade when credits run out. A full daily run is ~18 requests (180 credits); ~8/day once seen listings skip detail calls |
| Data licensing | **Pending validation** |
| SMS registration | **Pending** |

**Bottom line:** Build the provider-independent discovery and ranking engine first. Prove that HasData is accurate and permissible for this use before deploying it. Then connect the private dashboard and compliant three-recipient SMS delivery.
