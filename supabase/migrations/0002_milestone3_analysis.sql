-- HomeScout AI — Milestone 3: analysis results and paid-API usage caps.
-- Paste into Supabase Dashboard -> SQL Editor -> Run. Safe to re-run.

-- Score breakdown, finance scenarios and explanation per property per run.
alter table public.run_results add column if not exists analysis jsonb;
alter table public.run_results add column if not exists rank int;

-- Monthly request counters for paid APIs (RentCast overage is billed per request).
create table if not exists public.api_usage (
  provider  text not null,
  period    text not null,           -- 'YYYY-MM'
  count     int  not null default 0,
  primary key (provider, period)
);
alter table public.api_usage enable row level security;

-- Atomically reserve one request if under the limit. Returns true if reserved.
create or replace function public.reserve_api_request(p_provider text, p_period text, p_limit int)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  reserved boolean;
begin
  insert into public.api_usage (provider, period, count)
  values (p_provider, p_period, 0)
  on conflict (provider, period) do nothing;

  update public.api_usage
     set count = count + 1
   where provider = p_provider and period = p_period and count < p_limit
  returning true into reserved;

  return coalesce(reserved, false);
end;
$$;

revoke all on function public.reserve_api_request(text, text, int) from public, anon, authenticated;
grant execute on function public.reserve_api_request(text, text, int) to service_role;
