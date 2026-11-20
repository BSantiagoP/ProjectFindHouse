# HomeScout AI

Private home-search assistant: finds new multifamily (and qualifying single-family) listings in selected NJ towns, filters them against hard requirements, and explains every decision. See `plan.md` for the full spec.

## Backend (Milestone 1)

```bash
cd backend
poetry env use python3.12
poetry install
cp ../.env.example .env        # set API_TOKEN; PROVIDER=fixture uses free sample data
poetry run pytest
poetry run uvicorn app.main:app --reload
```

```bash
TOKEN=...   # value of API_TOKEN
curl -X POST -H "Authorization: Bearer $TOKEN" localhost:8000/api/searches
curl -H "Authorization: Bearer $TOKEN" localhost:8000/api/properties                          # eligible
curl -H "Authorization: Bearer $TOKEN" "localhost:8000/api/properties?status=needs_verification"
curl -H "Authorization: Bearer $TOKEN" "localhost:8000/api/properties?status=rejected"         # with reasons
```

Every property is `eligible`, `needs_verification` (a required feature is unknown), or `rejected` (with reasons). Features are `present`, `absent`, or `unknown`, and each carries the listing text it came from as evidence.

### Live data

Set `PROVIDER=hasdata` and `HASDATA_API_KEY`. Each HasData request costs 10 credits; `MAX_REQUESTS_PER_RUN` caps each run. The sample fixtures in `backend/tests/fixtures` are **synthetic** and should be replaced with sanitized recordings of real responses once access is approved.
