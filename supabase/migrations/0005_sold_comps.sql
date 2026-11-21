-- HomeScout AI — sold comparables cache for suggested offers.
-- Paste into Supabase Dashboard -> SQL Editor -> Run. Safe to re-run. Creates one table; changes no data.
-- One HasData "sold" search per town + home type, reused for 7 days (10 credits per refresh).

create table if not exists public.sold_comps_cache (
  town        text not null,
  home_type   text not null,              -- multiFamily | house
  fetched_at  timestamptz not null default now(),
  comps       jsonb not null,
  primary key (town, home_type)
);
alter table public.sold_comps_cache enable row level security;

drop policy if exists dashboard_read on public.sold_comps_cache;
create policy dashboard_read on public.sold_comps_cache
  for select to authenticated using (public.is_dashboard_user());
