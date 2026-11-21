-- HomeScout AI — Dashboard: owner-only access via Supabase Auth + feedback.
-- Paste into Supabase Dashboard -> SQL Editor -> Run. Safe to re-run.
--
-- Access model: RLS stays ON everywhere. The backend job uses the service-role key (bypasses RLS).
-- The dashboard uses the public anon key + a logged-in user; it can only read/write rows if
-- that user's id is listed in dashboard_users. No policy grants anything to anonymous visitors.

create table if not exists public.dashboard_users (
  user_id  uuid primary key references auth.users (id) on delete cascade,
  added_at timestamptz not null default now()
);
alter table public.dashboard_users enable row level security;

create or replace function public.is_dashboard_user()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (select 1 from public.dashboard_users where user_id = auth.uid());
$$;
revoke all on function public.is_dashboard_user() from public, anon;
grant execute on function public.is_dashboard_user() to authenticated;

-- Likes / rejections. Rejected properties are never texted again.
create table if not exists public.property_feedback (
  property_id  uuid primary key references public.properties (id) on delete cascade,
  liked        boolean not null default false,
  rejected     boolean not null default false,
  notes        text,
  updated_at   timestamptz not null default now(),
  check (not (liked and rejected))
);
alter table public.property_feedback enable row level security;

-- Read policies (dashboard user only)
do $$
declare t text;
begin
  foreach t in array array['properties','provider_listings','search_runs','property_snapshots',
                           'run_results','search_preferences','property_feedback','dashboard_users']
  loop
    execute format('drop policy if exists dashboard_read on public.%I', t);
    execute format('create policy dashboard_read on public.%I for select to authenticated using (public.is_dashboard_user())', t);
  end loop;
end $$;

-- Write policies: only preferences and feedback are editable from the dashboard.
drop policy if exists dashboard_update_prefs on public.search_preferences;
create policy dashboard_update_prefs on public.search_preferences
  for update to authenticated using (public.is_dashboard_user()) with check (public.is_dashboard_user() and id = 1);

drop policy if exists dashboard_insert_feedback on public.property_feedback;
create policy dashboard_insert_feedback on public.property_feedback
  for insert to authenticated with check (public.is_dashboard_user());
drop policy if exists dashboard_update_feedback on public.property_feedback;
create policy dashboard_update_feedback on public.property_feedback
  for update to authenticated using (public.is_dashboard_user()) with check (public.is_dashboard_user());
drop policy if exists dashboard_delete_feedback on public.property_feedback;
create policy dashboard_delete_feedback on public.property_feedback
  for delete to authenticated using (public.is_dashboard_user());
