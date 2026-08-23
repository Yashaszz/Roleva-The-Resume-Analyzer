-- ============================================================================
-- Roleva — initial schema
--
-- Privacy posture: the raw PDF is NEVER stored. Only the structured document
-- extracted from it is persisted, and only under the owning user's row.
-- Row Level Security is enabled on every user-owned table so that even a bug
-- in the API cannot leak one user's resume to another.
-- ============================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- profiles — 1:1 with auth.users
-- ---------------------------------------------------------------------------
create table public.profiles (
  id                  uuid primary key references auth.users (id) on delete cascade,
  display_name        text,
  daily_quota_used    integer     not null default 0,
  quota_reset_at      timestamptz not null default (now() + interval '1 day'),
  accepted_terms_at   timestamptz,
  created_at          timestamptz not null default now(),
  last_active_at      timestamptz not null default now()
);

-- Create a profile automatically on signup.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, new.raw_user_meta_data ->> 'full_name');
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- resumes — structured document only, never the source file
-- ---------------------------------------------------------------------------
create table public.resumes (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid        not null references auth.users (id) on delete cascade,
  label             text,
  file_hash         text,              -- enables cache hits on re-upload
  document          jsonb       not null,
  schema_version    integer     not null default 1,
  parse_confidence  real        not null default 0,
  page_count        integer     not null default 0,
  created_at        timestamptz not null default now()
);

create index resumes_user_idx      on public.resumes (user_id, created_at desc);
create index resumes_file_hash_idx on public.resumes (user_id, file_hash);

-- ---------------------------------------------------------------------------
-- job_targets — parsed job descriptions (requirement extraction is cached)
-- ---------------------------------------------------------------------------
create table public.job_targets (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid        not null references auth.users (id) on delete cascade,
  title          text,
  company        text,
  role_family    text        not null default 'general',
  seniority      text        not null default 'unknown',
  jd_text        text        not null,
  jd_hash        text        not null,
  requirements   jsonb       not null default '[]'::jsonb,
  created_at     timestamptz not null default now()
);

create index job_targets_user_idx on public.job_targets (user_id, created_at desc);
create index job_targets_hash_idx on public.job_targets (jd_hash);

-- ---------------------------------------------------------------------------
-- analyses — the core record
-- ---------------------------------------------------------------------------
create table public.analyses (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid        not null references auth.users (id) on delete cascade,
  resume_id       uuid        not null references public.resumes (id)     on delete cascade,
  job_target_id   uuid        not null references public.job_targets (id) on delete cascade,
  status          text        not null default 'pending',
  report          jsonb,
  scores          jsonb,
  rubric_version  text,
  prompt_version  text,
  llm_call_count  integer     not null default 0,
  duration_ms     integer,
  created_at      timestamptz not null default now(),
  completed_at    timestamptz
);

create index analyses_user_idx on public.analyses (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- share_links — revocable, expiring, redacted by default
-- ---------------------------------------------------------------------------
create table public.share_links (
  id              uuid primary key default gen_random_uuid(),
  analysis_id     uuid        not null references public.analyses (id) on delete cascade,
  user_id         uuid        not null references auth.users (id)      on delete cascade,
  token           text        not null unique,
  visibility_mode text        not null default 'full_redacted'
                    check (visibility_mode in ('scores_only', 'full_redacted', 'full_identified')),
  expires_at      timestamptz not null default (now() + interval '7 days'),
  revoked_at      timestamptz,
  view_count      integer     not null default 0,
  created_at      timestamptz not null default now()
);

create index share_links_token_idx on public.share_links (token);
create index share_links_user_idx  on public.share_links (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- score_samples — deliberately has NO user_id, so it cannot be traced back.
-- Powers cohort percentiles once a role family reaches 30 samples.
-- ---------------------------------------------------------------------------
create table public.score_samples (
  id           bigserial primary key,
  role_family  text        not null,
  seniority    text        not null,
  overall      real        not null,
  job_match    real        not null,
  ats          real        not null,
  quality      real        not null,
  must_coverage real       not null,
  created_at   timestamptz not null default now()
);

create index score_samples_cohort_idx on public.score_samples (role_family, seniority);

-- ---------------------------------------------------------------------------
-- cohort_stats — aggregated percentiles, refreshed periodically
-- ---------------------------------------------------------------------------
create table public.cohort_stats (
  role_family  text        not null,
  seniority    text        not null,
  metric       text        not null,
  p10 real, p25 real, p50 real, p75 real, p90 real,
  sample_size  integer     not null default 0,
  updated_at   timestamptz not null default now(),
  primary key (role_family, seniority, metric)
);

-- ---------------------------------------------------------------------------
-- rate_limits — replaces Redis at this scale
-- ---------------------------------------------------------------------------
create table public.rate_limits (
  key          text        not null,
  window_start timestamptz not null,
  count        integer     not null default 0,
  primary key (key, window_start)
);

-- ---------------------------------------------------------------------------
-- llm_usage — free-tier budget guard
-- ---------------------------------------------------------------------------
create table public.llm_usage (
  day             date    not null,
  model           text    not null,
  request_count   integer not null default 0,
  token_estimate  bigint  not null default 0,
  primary key (day, model)
);

-- ============================================================================
-- Row Level Security
-- ============================================================================
alter table public.profiles     enable row level security;
alter table public.resumes      enable row level security;
alter table public.job_targets  enable row level security;
alter table public.analyses     enable row level security;
alter table public.share_links  enable row level security;

-- Operational tables are service-role only: no policies means no client access.
alter table public.score_samples enable row level security;
alter table public.cohort_stats  enable row level security;
alter table public.rate_limits   enable row level security;
alter table public.llm_usage     enable row level security;

create policy "own profile" on public.profiles
  for all using (auth.uid() = id) with check (auth.uid() = id);

create policy "own resumes" on public.resumes
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "own job targets" on public.job_targets
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "own analyses" on public.analyses
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "own share links" on public.share_links
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Anyone may read cohort statistics; they contain no personal data.
create policy "cohort stats are public" on public.cohort_stats
  for select using (true);
