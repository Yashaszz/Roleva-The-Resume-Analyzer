# Supabase Setup

Tasks **0.9** and **0.10**. About 20 minutes. Everything here is free tier.

Supabase gives Roleva three things in one product: the Postgres database, user
authentication, and Row Level Security. RLS is the reason it is worth using
rather than a bare database — it means the database itself refuses to hand one
user another user's resume, even if the API has a bug.

> Verify each step as you go with:
> ```bash
> node scripts/check-env.mjs --live
> ```

---

## 1. Create the account and project

1. Go to **https://supabase.com** → **Start your project** → sign in with GitHub.
2. Click **New project**.
3. Fill in:

| Field | Value |
|---|---|
| Name | `roleva-dev` |
| Database password | Generate one. **Save it in your password manager** — it is not recoverable and you will need it for direct DB access. |
| Region | Pick the one nearest you (e.g. `South Asia (Mumbai)`). |
| Plan | Free |

4. Wait ~2 minutes while it provisions.

> Create **only** `roleva-dev` for now. The production project comes at
> deployment time; a second idle project just risks being paused for inactivity.

---

## 2. Apply the database schema

1. In the left sidebar, open **SQL Editor**.
2. Click **New query**.
3. Open [`supabase/migrations/0001_initial_schema.sql`](../supabase/migrations/0001_initial_schema.sql)
   in your editor, copy the **entire** file, paste it into the SQL editor.
4. Click **Run**.

You should see `Success. No rows returned`.

> The script is safe to re-run. If a previous attempt failed partway through
> and left some tables behind, just run it again — it fills in whatever is
> missing rather than erroring on what already exists.

### Confirm it worked

Open **Table Editor** in the sidebar. You should see nine tables:

`profiles` · `resumes` · `job_targets` · `analyses` · `share_links` ·
`score_samples` · `cohort_stats` · `rate_limits` · `llm_usage`

### Confirm RLS is on

Go to **Authentication → Policies**. Every table should show **RLS enabled**.

This matters more than it looks. Without it, any leaked anon key exposes every
resume in the database. With it, the database refuses cross-user reads no matter
what the API does.

---

## 3. Configure authentication

### 3a. Email confirmation — required

1. **Authentication → Sign In / Providers → Email**.
2. Ensure **Enable Email provider** is on.
3. Ensure **Confirm email** is **ON**.

Do not skip this. Unverified accounts are the cheapest way to drain a shared
free-tier Gemini quota, and the backend already refuses analysis requests from
unverified users.

### 3b. Redirect URLs

**Authentication → URL Configuration**:

| Field | Value |
|---|---|
| Site URL | `http://localhost:3000` |
| Redirect URLs | `http://localhost:3000/**` |

Production URLs get added at deployment.

### 3c. Google sign-in — optional, recommended

Students overwhelmingly have Google accounts, and it removes password handling
entirely. It needs a Google Cloud OAuth client, which takes ~10 minutes.

**Skip it for now if you want** — email sign-in is enough to build against, and
this can be added at any point without code changes.

<details>
<summary>Steps, when you want it</summary>

1. **Authentication → Sign In / Providers → Google** → copy the **Callback URL**
   Supabase shows you.
2. Go to https://console.cloud.google.com → **APIs & Services → Credentials**.
3. **Create Credentials → OAuth client ID → Web application**.
4. Under **Authorized redirect URIs**, paste the callback URL from step 1.
5. Copy the **Client ID** and **Client Secret** back into Supabase, enable the
   provider, and save.

</details>

---

## 4. Collect the keys

Go to **Project Settings → API**.

| Copy this | Into `.env` as | Notes |
|---|---|---|
| Project URL | `SUPABASE_URL` | **The base URL only** — `https://abcdefgh.supabase.co`. Not the API/REST URL. Copying `.../rest/v1/` by mistake makes every request 404. |
| `anon` `public` key | `SUPABASE_ANON_KEY` | Safe in the browser — RLS is what protects the data |
| `service_role` key | `SUPABASE_SERVICE_ROLE_KEY` | **Bypasses RLS entirely.** Backend only. Never in frontend code, never in a commit |

### Then the JWT secret

Still in **Project Settings**, look for **JWT Keys** (newer projects) or
**API → JWT Settings** (older ones).

**Tell me which of these you see** — it changes how the backend verifies tokens:

| What you see | What it means |
|---|---|
| A **JWT Secret** field with a long random string | Legacy HS256. Copy it into `SUPABASE_JWT_SECRET`. |
| **Signing keys** with `ECC (P-256)` or `RSA`, and no plain secret | Newer asymmetric signing. **Leave `SUPABASE_JWT_SECRET` empty** — the backend fetches the public keys from the project's JWKS endpoint instead. |

Both are supported; the backend picks based on the token's own algorithm and
never mixes key sources between them.

The checker reports which scheme your project uses, so you do not have to guess:

```bash
node scripts/check-env.mjs --live
```

---

## 5. Fill in `.env`

Open `.env` in the project root and set these four lines. **Do not paste them
into chat** — the checker confirms they work without revealing them.

```
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_JWT_SECRET=
```

---

## 6. Verify

```bash
node scripts/check-env.mjs --live
```

Expected:

```
Live Supabase check
  OK       project reachable
  OK       schema applied (profiles table exists)
  INFO     legacy shared JWT secret in use (HS256)
```

| If you see | Fix |
|---|---|
| `schema NOT applied` | Re-run the SQL from step 2 — it is safe to run again. If the tables do exist in the Table Editor, PostgREST's cache is stale: run `notify pgrst, 'reload schema';` on its own and wait ten seconds. |
| `could not reach the project` | Check `SUPABASE_URL` for a typo or trailing slash. |
| `HTTP 401` | `SUPABASE_ANON_KEY` is wrong — recopy it. |
| `asymmetric JWT signing keys in use` | Expected on new projects. Tell me and I will switch the backend to JWKS verification. |

---

## Free tier limits worth knowing

| Limit | Value | Matters because |
|---|---|---|
| Database size | 500 MB | ~7,000 analyses. Plenty for launch. |
| **Pauses after 7 days idle** | — | A GitHub Actions cron ping keeps it awake; set up in Phase 5. |
| Projects | 2 | One dev, one prod. Why we are not creating prod yet. |
| Monthly active users | Unlimited | Not a constraint. |
| File storage | 50 MB | Irrelevant — Roleva never stores the PDF. |

---

## Security notes

- The **anon key is public by design**. It appears in browser code. RLS is what
  protects your data, which is why step 2 matters so much.
- The **service role key bypasses RLS completely**. It lives only in the backend
  environment. If it ever lands in a commit or in frontend code, rotate it
  immediately from **Project Settings → API**.
- `.env` is gitignored and verified as such. Never paste real keys into chat,
  an issue, or a screenshot.

---

## When you are done

Say **"Supabase is set up"** and paste the `check-env --live` output (it is safe
to share — it shows no secret values). I will then:

- switch token verification to JWKS if your project uses asymmetric keys
- write the cross-user RLS test that Gate 0 requires
- wire up sign-up and sign-in
