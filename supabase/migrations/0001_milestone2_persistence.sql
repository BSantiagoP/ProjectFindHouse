-- HomeScout AI — Milestone 2: persistence, seen-listing memory, price history.
-- Paste into Supabase Dashboard -> SQL Editor -> Run. Safe to re-run.
--
-- Row-level security is ON for every table with NO policies: only the backend's
-- service-role key can read/write. Dashboard-user policies come with Supabase Auth later.

create extension if not exists pgcrypto;

-- One row per physical property (deduplicated across providers/listing IDs).
create table if not exists public.properties (
  id               uuid primary key default gen_random_uuid(),
  address_key      text unique,               -- normalized "street|unit|zip"; null if address incomplete
  town             text,
  property_type    text,
  units            int,
  current_price    int,
  status           text,
  listed_date      date,
  data             jsonb not null,            -- full normalized Property (features, evidence, photos, ...)
  details_fetched_at timestamptz,
  first_seen_at    timestamptz not null default now(),
  last_seen_at     timestamptz not null default now()
);
create index if not exists properties_town_idx on public.properties (town);

-- Provider listing IDs pointing at a property.
create table if not exists public.provider_listings (
  provider       text not null,
  external_id    text not null,
  property_id    uuid not null references public.properties (id) on delete cascade,
  source_url     text not null,
  first_seen_at  timestamptz not null default now(),
  last_seen_at   timestamptz not null default now(),
  primary key (provider, external_id)
);
create index if not exists provider_listings_property_idx on public.provider_listings (property_id);

-- One row per search run (scheduled or manual).
create table if not exists public.search_runs (
  id              uuid primary key,
  provider        text not null,
  status          text not null,               -- running | succeeded | partial | failed
  started_at      timestamptz not null,
  completed_at    timestamptz,
  requests_used   int not null default 0,
  request_budget  int not null default 0,
  errors          jsonb not null default '[]'::jsonb,
  counts          jsonb not null default '{}'::jsonb
);
create index if not exists search_runs_started_idx on public.search_runs (started_at desc);

-- Price/status history. A row is written only when a property is first seen or changes.
create table if not exists public.property_snapshots (
  id             bigint generated always as identity primary key,
  property_id    uuid not null references public.properties (id) on delete cascade,
  search_run_id  uuid references public.search_runs (id) on delete set null,
  price          int,
  status         text,
  observed_at    timestamptz not null default now()
);
create index if not exists property_snapshots_property_idx on public.property_snapshots (property_id, observed_at desc);

-- Filter outcome for each property in each run.
create table if not exists public.run_results (
  search_run_id   uuid not null references public.search_runs (id) on delete cascade,
  property_id     uuid not null references public.properties (id) on delete cascade,
  filter_status   text not null,               -- eligible | needs_verification | rejected
  rejections      jsonb not null default '[]'::jsonb,
  unverified      jsonb not null default '[]'::jsonb,
  is_new          boolean not null,
  previous_price  int,
  primary key (search_run_id, property_id)
);

-- Single-row editable search preferences.
create table if not exists public.search_preferences (
  id          int primary key default 1 check (id = 1),
  data        jsonb not null,
  updated_at  timestamptz not null default now()
);

alter table public.properties         enable row level security;
alter table public.provider_listings  enable row level security;
alter table public.search_runs        enable row level security;
alter table public.property_snapshots enable row level security;
alter table public.run_results        enable row level security;
alter table public.search_preferences enable row level security;
