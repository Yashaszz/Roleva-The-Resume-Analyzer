-- ---------------------------------------------------------------------------
-- Roleva migration 0002 — content-hash caching and atomic rate limiting.
--
-- Idempotent, like 0001: this file gets re-run by hand.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- analyses.content_hash
-- ---------------------------------------------------------------------------
-- Re-analysing the same resume against the same job description is the most
-- likely repeat action a user takes: they fix a bullet, re-upload, and want to
-- see whether the number moved. On a free tier every avoidable model call is
-- worth avoiding, so the inputs that determine the output are hashed and the
-- previous report is served when they are unchanged.
--
-- The hash includes the rubric version, so publishing new weights invalidates
-- every cached score rather than serving a number the current rubric cannot
-- explain.
alter table public.analyses
  add column if not exists content_hash text;

create index if not exists analyses_cache_idx
  on public.analyses (user_id, content_hash, created_at desc);

-- ---------------------------------------------------------------------------
-- bump_rate_limit
-- ---------------------------------------------------------------------------
-- Rate limiting has to be atomic. Reading a counter and then writing it back
-- from the application is a race that two browser tabs can win simultaneously,
-- and the thing being protected is a shared free-tier quota that a single
-- doubled request can eat into.
--
-- So the increment happens inside Postgres: one statement, insert-or-add,
-- returning the new value. The caller compares it against the limit.
--
-- SECURITY DEFINER because rate_limits has RLS enabled and no policy — it is
-- not a user-owned table and nobody should be able to read or edit their own
-- counter. The function is the only door, and it can only add one.
create or replace function public.bump_rate_limit(
  p_key          text,
  p_window_start timestamptz
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  new_count integer;
begin
  insert into public.rate_limits (key, window_start, count)
  values (p_key, p_window_start, 1)
  on conflict (key, window_start)
    do update set count = public.rate_limits.count + 1
  returning count into new_count;

  return new_count;
end;
$$;

revoke all on function public.bump_rate_limit(text, timestamptz) from public;
grant execute on function public.bump_rate_limit(text, timestamptz) to authenticated;

-- ---------------------------------------------------------------------------
-- bump_llm_usage
-- ---------------------------------------------------------------------------
-- The same race as the rate limiter, protecting the thing that actually runs
-- out: Gemini's daily request allowance. Two analyses starting together must
-- not both read "247 used" and both proceed.
--
-- Kept per model, because the free tier is per model and a fallback model has
-- its own allowance.
create or replace function public.bump_llm_usage(
  p_day    date,
  p_model  text,
  p_tokens bigint default 0
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  new_count integer;
begin
  insert into public.llm_usage (day, model, request_count, token_estimate)
  values (p_day, p_model, 1, p_tokens)
  on conflict (day, model)
    do update set
      request_count  = public.llm_usage.request_count + 1,
      token_estimate = public.llm_usage.token_estimate + p_tokens
  returning request_count into new_count;

  return new_count;
end;
$$;

revoke all on function public.bump_llm_usage(date, text, bigint) from public;
grant execute on function public.bump_llm_usage(date, text, bigint) to authenticated;

-- ---------------------------------------------------------------------------
-- Housekeeping
-- ---------------------------------------------------------------------------
-- Old windows are dead weight. Called opportunistically rather than scheduled,
-- because pg_cron is not available on the free tier.
create or replace function public.prune_rate_limits()
returns void
language sql
security definer
set search_path = public
as $$
  delete from public.rate_limits where window_start < now() - interval '2 days';
$$;

revoke all on function public.prune_rate_limits() from public;

notify pgrst, 'reload schema';
