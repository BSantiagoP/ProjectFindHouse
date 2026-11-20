-- HomeScout AI — Milestone 4: SMS notifications (idempotent, no repeats).
-- Paste into Supabase Dashboard -> SQL Editor -> Run. Safe to re-run.
-- Phone numbers are NOT stored here: recipients live in the server's .env as RECIPIENT1..N.

-- One row per (run, recipient). Inserted BEFORE sending, so a retry can never double-send.
create table if not exists public.notifications (
  search_run_id   uuid not null references public.search_runs (id) on delete cascade,
  recipient_key   text not null,             -- e.g. 'RECIPIENT1'
  recipient_last2 text,
  status          text not null,             -- reserved | sent | failed | opted_out
  twilio_sid      text,
  error           text,
  property_ids    jsonb not null default '[]'::jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  primary key (search_run_id, recipient_key)
);

-- Which properties each recipient has already been sent (never re-sent).
create table if not exists public.sent_properties (
  recipient_key  text not null,
  property_id    uuid not null references public.properties (id) on delete cascade,
  first_sent_at  timestamptz not null default now(),
  primary key (recipient_key, property_id)
);

-- Recipients who replied STOP (Twilio error 21610) are skipped until they opt back in.
create table if not exists public.recipient_status (
  recipient_key  text primary key,
  opted_out      boolean not null default false,
  updated_at     timestamptz not null default now()
);

alter table public.notifications    enable row level security;
alter table public.sent_properties  enable row level security;
alter table public.recipient_status enable row level security;
