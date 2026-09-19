# Roleva — Session Handoff

**Purpose:** everything a fresh session needs to resume without re-reading the repo.
Read this first, then `docs/CHECKLIST.md`, then `docs/ARCHITECTURE.md` only if a design
decision is unclear.

Last updated: 2026-09-19 · Phase 3 complete · all pushed.

---

## 1. What Roleva is

Upload a PDF resume + paste a job description → a scored, explainable report where
**every number traces back to a line in the user's own resume**.

Not "your resume is good". It says *which* skills matched, which are missing, and
**where in the document the evidence was found**.

**Scope for v1:** analyzer + improvement suggestions.
**Later phase:** resume builder. The models are already builder-shaped, but no builder
code is to be written yet.

---

## 2. Non-negotiable principles

| Principle | What it means in code |
|---|---|
| **The LLM extracts and judges. The code computes.** | No number originates from a language model. The rubric call returns levels 1–5; weights live in `rubric.yaml` and are applied in Python. |
| **Pure scoring engine** | `scoring/engine.py` has no network, DB, clock, randomness or model. Same inputs → identical output, always. |
| **Span verification** | Every evidence quote must occur verbatim at its recorded offsets or it is dropped. Hallucinated evidence is structurally undisplayable. |
| **Evidence strength by location** | work bullet 1.0 · project 0.85 · certification 0.80 · summary 0.60 · skills-list 0.50 · adjacent 0.40. This produces the signature insight: *"You list Docker in your skills section but never show using it."* |
| **Honesty over polish** | Percentiles hidden below N=30. Parse confidence degrades the report rather than hiding uncertainty. Expected bands are labelled "typical range", never "top 20%". |
| **PII redaction at the LLM boundary** | Mandatory — Gemini's free tier may use submitted content. |
| **Free-tier inversion** | Gemini limits *requests*, not tokens → batch into fewer, larger calls. ≤6 LLM calls per analysis. |

---

## 3. User's standing instructions

1. **Keep chat replies short.** Long content goes into files. (`concise-replies.md` in memory)
2. **End every reply with a progress summary** and tick `docs/CHECKLIST.md` in the same commit. (`progress-summary-each-reply.md`)
3. **No uncontrolled vibe coding** — analyse, justify, state trade-offs before generating.
4. **Frontend must not look like a generic AI/SaaS template.** Explicitly forbidden shape: navbar → hero → gradient → feature cards → testimonials → pricing → footer. Multiple visual directions must be explored before one is chosen. Backend stays conventional and boring; the frontend is the differentiator.
5. **Never print or expose secrets.** Verification must prove access without revealing values.
6. Zero budget. Every choice must survive on free tiers.

---

## 4. Stack

**Frontend (not started):** Next.js 15 · React 19 · TypeScript · Tailwind v4 · Radix · Motion
**Backend:** FastAPI · Python 3.12 · Pydantic v2 · PyMuPDF · rapidfuzz
**Data:** Supabase (Postgres + Auth + RLS) — live, migrated, RLS proven with 18 cross-user tests
**LLM:** Gemini behind a provider adapter. Pinned versions, never `-latest`:
`gemini-3.6-flash` (main) · `gemini-3.5-flash-lite` (light) · `gemini-3.5-flash` (fallback) · `gemini-embedding-2`
**Deploy:** Vercel (web) + Render (api) — neither configured yet

---

## 5. Repo map

```
docs/            CHECKLIST.md (living tracker) · ARCHITECTURE.md · SUPABASE_SETUP.md
                 Roleva-Checklist.pdf · HANDOFF.md (this file)
scripts/         check-env.mjs (masked verification, --live probes)
                 gen-types.mjs (OpenAPI → TS)
supabase/migrations/0001_initial_schema.sql   idempotent; RLS on every user table
apps/api/roleva/
  models/        THE CONTRACT — common(Span.verify) resume job evidence ats scoring report
  parsing/       pdf_reader normalizer sectionizer contact dates spans structurer
                 confidence validators _pymupdf(typed shim)
  jd/            cleaner cues requirement_extractor
  matching/      taxonomy(~200 skills/~400 aliases, FUZZY_THRESHOLD=82)
                 cascade semantic adjudicator pipeline
  ats/           signals(tables, margins, fonts, images) rules(15 registered checks)
  quality/       metrics(7 deterministic) rubric_judge(anchored 1–5)
                 proofread(closed-set flags, unscored)
  scoring/       rubric.yaml (published, v1.0.0) engine.py (pure)
  llm/           client(failover+repair retry) sanitize(PII+injection) budget
  api/           auth(ES256+HS256) errors
  storage/       samples(anonymous cohort rows, no user_id)
  advice/        selection impact recommendations summary grounding writer
  orchestration/                             ← empty, next up
apps/api/tests/unit/     22 test modules
apps/api/tests/golden/scores.json        6 pinned scenarios
```

**`.env`** holds real Gemini + Supabase keys. Gitignored, verified with `git check-ignore`.
Never print its values. Verify with `node scripts/check-env.mjs`.

---

## 6. Where the work stands

**826 tests passing · ruff clean · mypy clean · 99/217 checklist tasks (46%)**

| Phase | Status |
|---|---|
| 0 Foundations | complete |
| 1 Parsing | complete (Gate 1 blocked on real PDFs) |
| 2 JD + matching | complete |
| 3 Scoring & ATS | complete (Gate 3 blocked on the calibration set) |
| 4 Advice engine | complete (Gate 4 needs a live 10-analysis spot check) |
| 5 API & orchestration | **next** |
| 6–11 | design exploration, frontend, sharing, hardening, deploy, launch |

### Immediate next tasks

Phase 5, API and orchestration. The pieces all exist; nothing is wired together
yet. There is no pipeline, no endpoint and no persistence — `orchestration/` is
still an empty package.

Order that avoids rework:

1. **5.1 the orchestrator first**, with per-stage isolation. Every stage can
   fail independently and the report must degrade rather than disappear.
2. **5.8 persistence** — structured data only. The raw PDF is never stored;
   that was an explicit user decision.
3. **5.3/5.4 SSE** after the pipeline works synchronously. Progress events are
   a designed experience, not a spinner.
4. **5.13/5.14 warm-up** — Render's free tier sleeps, so the first analysis of
   the day would otherwise take 50 seconds.

Gate 3's last criterion — *no number anywhere originates from an LLM* — can now
be ticked on review: `projected_gain` was the final risk and it is computed by
re-running the scoring engine.

---

## 7. Blocked on the user

| Blocker | Why it cannot be faked |
|---|---|
| **Gate 1:** 20+ **real** resume PDFs (Canva / LaTeX / Word) | A parser validated only against documents I generated is validated against my own assumptions. Real exports break differently. |
| **Gate 2:** 20 hand-ranked resume pairs | Calibration needs a human's rank order to agree with. |
| Vercel + Render accounts, optional Google OAuth, optional Sentry DSN | Account creation is the user's to do. |

---

## 8. Hard-won lessons (do not relearn these)

- Gemini keys can look like `AQ.Ab8RN6...` — **not** only `AIzaSy...`.
- `git log origin/main..HEAD` returning nothing looks identical to "nothing to push" when the tracking ref is unset. Check the ref before reporting push status.
- Run **mypy as well as pytest** before committing. Green tests are not a green build.
- Heredocs mangle `\b` into a literal backspace (0x08). Use the Write tool for anything with regexes.
- Migrations must be idempotent — the user re-runs them.
- `SUPABASE_URL` is the project URL, *not* the `/rest/v1/` endpoint.
- Supabase issues **ES256** asymmetric JWTs here; HS256-only verification rejects every real login. Key source must be bound to the algorithm to block algorithm confusion.
- A Gemini model can appear in the listing and still 404 on use. Prove models with a real request.
- Fuzzy threshold: typos score 82–95, distinct-skill collisions 40–77. 82 is the seam. Guard against two *known-distinct* skills matching.
- Longest-match-wins on requirement tiers, or `"Preferred qualifications"` becomes a MUST.
- PyMuPDF's `text` table strategy invents tables. Only trust vector-line detection.
- `taxonomy.find_in_text` returns offsets into the **normalised** text, not the
  text you passed in. Slicing the original with them yields garbage like
  `' Kubernete'`. Use the canonical name, or read back out of the same
  normalised string.
- A resume proofreader must be closed-set. A dictionary flags the candidate's own
  surname; `Excel at communication` is not a spreadsheet. Every term on the casing
  list needs its lowercase form checked against ordinary English first.
- The must-have gate has to cap **overall**, not just job match. A golden case caught this: a resume matching zero must-haves still scored 75.4 "Competitive" because ATS and quality carried it. Now 55.0.

---

## 9. Restart commands

```bash
cd "C:/Users/yasha/OneDrive/Desktop/Roleva"
node scripts/check-env.mjs                    # masked config verification
cd apps/api && python -m pytest -q            # 695 tests
cd apps/api && python -m mypy roleva && python -m ruff check .
```
