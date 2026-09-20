-- ---------------------------------------------------------------------------
-- Roleva migration 0003 — share-link views and cohort percentiles.
--
-- Idempotent, like the others: this file gets re-run by hand.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- bump_share_view
-- ---------------------------------------------------------------------------
-- The same atomicity argument as the rate limiter: a share link can be opened
-- by several people at once, and read-then-write from the application loses
-- views. One statement, and it returns nothing the caller needs.
--
-- SECURITY DEFINER because the reader is anonymous — they hold a token, not a
-- session — and share_links has RLS with an owner-only policy. The function is
-- the only door, and all it can do is add one to a counter for a token that
-- already exists.
create or replace function public.bump_share_view(p_token text)
returns void
language sql
security definer
set search_path = public
as $$
  update public.share_links
     set view_count = view_count + 1
   where token = p_token
     and revoked_at is null
     and expires_at > now();
$$;

revoke all on function public.bump_share_view(text) from public;
grant execute on function public.bump_share_view(text) to anon, authenticated;

-- ---------------------------------------------------------------------------
-- refresh_cohort_stats
-- ---------------------------------------------------------------------------
-- Turns the anonymous score_samples rows into the percentile table the report
-- reads from.
--
-- THE SAMPLE FLOOR IS ENFORCED HERE, not in the UI. A cohort under 30 samples
-- produces no row at all, so there is nothing for a frontend bug to render.
-- A percentile drawn from eleven people is a statistic in appearance only, and
-- this product's whole argument is against numbers that look more certain than
-- they are.
--
-- percentile_cont rather than percentile_disc: with 30-ish samples the
-- interpolated value is a better estimate than the nearest observed one.
create or replace function public.refresh_cohort_stats()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  affected integer := 0;
begin
  with cohorts as (
    select
      role_family,
      seniority,
      metric,
      count(*)                                                as sample_size,
      percentile_cont(0.10) within group (order by value)     as p10,
      percentile_cont(0.25) within group (order by value)     as p25,
      percentile_cont(0.50) within group (order by value)     as p50,
      percentile_cont(0.75) within group (order by value)     as p75,
      percentile_cont(0.90) within group (order by value)     as p90
    from (
      select role_family, seniority, 'overall'::text   as metric, overall::numeric   as value from public.score_samples
      union all
      select role_family, seniority, 'job_match'::text as metric, job_match::numeric as value from public.score_samples
      union all
      select role_family, seniority, 'quality'::text   as metric, quality::numeric   as value from public.score_samples
      union all
      select role_family, seniority, 'ats'::text       as metric, ats::numeric       as value from public.score_samples
    ) as flattened
    group by role_family, seniority, metric
    -- The floor. Below this, the cohort simply does not exist.
    having count(*) >= 30
  )
  insert into public.cohort_stats
    (role_family, seniority, metric, p10, p25, p50, p75, p90, sample_size, updated_at)
  select role_family, seniority, metric, p10, p25, p50, p75, p90, sample_size, now()
  from cohorts
  on conflict (role_family, seniority, metric) do update
    set p10 = excluded.p10,
        p25 = excluded.p25,
        p50 = excluded.p50,
        p75 = excluded.p75,
        p90 = excluded.p90,
        sample_size = excluded.sample_size,
        updated_at  = now();

  get diagnostics affected = row_count;

  -- A cohort that has fallen back under the floor (samples deleted, a role
  -- family renamed) must stop being reported rather than going stale.
  delete from public.cohort_stats cs
   where not exists (
     select 1 from public.score_samples s
      where s.role_family = cs.role_family
        and s.seniority   = cs.seniority
      group by s.role_family, s.seniority
     having count(*) >= 30
   );

  return affected;
end;
$$;

revoke all on function public.refresh_cohort_stats() from public;

notify pgrst, 'reload schema';
