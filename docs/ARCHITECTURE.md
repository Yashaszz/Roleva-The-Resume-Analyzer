# Roleva — Architecture

The design record. Decisions, and the reasoning that would otherwise be lost.

---

## 1. What Roleva is

An **evidence-based resume diagnostic**. A user uploads a PDF resume and pastes
a target job description; Roleva returns scores, gaps and specific improvements,
where every number traces back to a line in their own resume.

The differentiator is not the AI — every competitor has an LLM. It is:

| Property | Meaning |
|---|---|
| **Determinism** | Same resume + same job description → same score, every time |
| **Traceability** | Any number expands to the components and evidence behind it |
| **Honesty** | Uncertainty is shown, not hidden; absent data is never fabricated |

### The rule everything else follows from

> **The LLM extracts and judges. The code computes.**
> No score in this system originates from a language model.

This single constraint is what makes scores reproducible, unit-testable,
explainable, and immune to prompt injection — an attacker cannot move a number
that no model produces.

### Scope

v1 analyses an existing resume. A **resume builder** comes later, so
`ResumeDocument` is designed to be builder-ready now: the analyser's output is
the builder's input, making that feature additive rather than a rewrite.

---

## 2. Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js 15, React 19, TypeScript | Design-heavy SPA; RSC for fast first paint |
| Styling | Tailwind v4 + CSS custom properties | Design tokens as a real system |
| Components | Radix primitives only | Accessibility for free, zero imposed visual style |
| Charts | Hand-authored SVG + d3 scales | Chart libraries have a recognisable look; the visuals are the brand |
| Backend | FastAPI, Python 3.12, Pydantic v2 | Runtime validation of LLM output is the key safety property |
| PDF parsing | PyMuPDF | Layout, fonts and **colour** — the last enables hidden-text detection |
| Database + Auth | Supabase (Postgres + RLS) | Postgres, auth and row-level isolation in one free product |
| LLM | Google Gemini, behind a provider adapter | Free tier; adapter makes the vendor swappable |
| Hosting | Vercel (web) + Render (api) | Free tiers |

### The split-stack decision

A second language and a second deploy target is real cost. It buys PyMuPDF,
rapidfuzz and the wider Python parsing ecosystem — and **parsing accuracy is the
product's quality ceiling**. A weak extraction library becomes an unfixable
limit on every downstream stage. Type safety across the boundary is recovered by
generating TypeScript from the API's OpenAPI schema.

### Rejected

| Rejected | Reason |
|---|---|
| shadcn/ui, MUI, Chakra | Instantly recognisable; contradicts the distinctiveness requirement |
| Recharts, Chart.js, Nivo | Generic chart aesthetics |
| LangChain / LlamaIndex | Heavy abstraction over ~6 direct API calls; obscures prompts and cost |
| A vector database | One resume against one job description. Cosine over ~200 vectors in memory |
| Redis | At <100 analyses/day, Postgres covers cache and rate limits |
| Celery / RabbitMQ | Enormous ops burden for a 20-second workload |

---

## 3. Analysis pipeline

```
PDF ─► validate ─► extract ─► normalise ─► sectionise ─► structure ─┐
                                                                    │
JD  ─► clean ─► extract requirements ─────────────────────────┐     │
                                                              ▼     ▼
                                                         MATCH CASCADE
                                                              │
                     ATS rules (deterministic) ───────┐       │
                     writing metrics (deterministic) ─┤       │
                     quality rubric (LLM, anchored) ──┤       │
                                                      ▼       ▼
                                              SCORING ENGINE (pure)
                                                      │
                                                      ▼
                                              ADVICE (LLM, grounded)
```

### Where the LLM is and is not used

| Stage | LLM | Deterministic |
|---|---|---|
| PDF extraction, column detection, normalisation | — | ✅ |
| Section detection | fallback only | ✅ primary |
| Resume structuring | ✅ extraction only | span verification |
| Date and duration arithmetic | ❌ **never** | ✅ |
| Requirement extraction | ✅ | priority cue-rule override |
| Skill matching | ✅ ambiguous band only | ✅ tiers 1–3 |
| Evidence strength | — | ✅ by location |
| ATS checks | ❌ **never** | ✅ 100% |
| **All scoring** | ❌ **never** | ✅ 100% |
| Bullet rewrites, summary | ✅ | grounding validation |

---

## 4. The matching cascade

A four-tier cascade, cheapest first. Roughly 75–85% of requirements resolve
without an LLM at all.

| Tier | Method | Cost |
|---|---|---|
| 1 | Canonical alias match (`k8s` ≡ `Kubernetes`) | ~0 |
| 2 | Fuzzy match, rapidfuzz ≥ 88 | ~0 |
| 3 | Embedding cosine: ≥0.82 accept, <0.62 reject | low |
| 4 | LLM adjudication — **only** the 0.62–0.82 band, batched into one call | moderate |

### Evidence strength — the key refinement

A match is not binary. *Where* the evidence sits decides what it is worth:

| Evidence location | Strength |
|---|---|
| Work-experience bullet with an outcome | 1.00 |
| Project bullet | 0.85 |
| Summary | 0.60 |
| **Skills list only** | **0.50** |
| Adjacent / transferable skill | 0.40 |

This produces the product's most valuable insight, and one no keyword matcher
can state:

> *"You list Docker in your skills section but never show using it."*

### Anti-hallucination

Every piece of evidence carries a `Span`, and `Span.verify()` asserts the quoted
text occurs verbatim at those offsets in the source. Items that fail are dropped
and logged, never displayed. **Hallucinated evidence is structurally impossible
to show a user.**

---

## 5. Scoring

| Score | Weight in Overall | Nature |
|---|---|---|
| Job Match | 45% | Weighted requirement coverage |
| Resume Quality | 35% | ~60% deterministic metrics, ~40% anchored rubric |
| ATS Readiness | 20% | 100% deterministic rule checklist |

**Job Match:**
```
raw = Σ(weight × strength) / Σ(weight) × 100     must=3, strong=2, nice=1
```

**The must-have gate:**
```
must_coverage < 0.50  →  capped at 55
must_coverage < 0.70  →  capped at 72
```

Without it, a candidate matching twelve nice-to-haves and zero must-haves scores
~70 and is told they are competitive. That would be actively harmful advice.

**Relative scoring** runs on three tracks: absolute rubric score, an
expected-band comparison available from day one, and true cohort percentiles
that **do not render below 30 samples**. Fabricating "top 20%" from no data
would be dishonest, so the UI shows nothing until the data exists.

The rubric lives in versioned YAML and is **published to users** — a defensible
score survives scrutiny; a mysterious one does not.

---

## 6. Privacy

Resumes are among the most PII-dense documents an ordinary person owns.

| Data | Policy |
|---|---|
| Raw PDF bytes | **Never stored.** In memory only, discarded after extraction |
| Full raw text | Never stored |
| Structured `ResumeDocument` | Stored, user-owned, RLS-protected |
| Evidence spans | Stored — the minimum needed for explainability |
| Logs | **Never contain content.** Enforced by a scrubbing processor |

### PII redaction at the LLM boundary

Gemini's free tier permits Google to use submitted content. So names, emails,
phones, locations, personal links and dates of birth are replaced with
placeholders before any request leaves the process, and restored locally
afterwards.

Job titles, employers, schools, skills, dates and bullet text stay — Roleva
scores *what you did*, not *who you are*, so the quality cost is near zero. A
side benefit: the model cannot see name-based signals, removing a bias vector.

Placeholders change text length, so `RedactionMap` carries an offset translation
table, keeping span verification intact.

### Defence in depth

Two independent layers, neither trusted alone:

1. **JWT verification** decides whether a request is authenticated.
2. **Row Level Security** means Postgres itself refuses cross-user reads, even
   if the API has a bug.

`score_samples` deliberately carries **no `user_id`** — cohort statistics cannot
be traced back to a person by schema design, not by policy.

### Prompt injection

The architecture is the primary defence: **no number comes from a model, so
injection has nothing to move.** Beyond that, hidden text (white-on-white,
zero-size) is detected, stripped before any LLM call, and reported to the user
as a manipulation red flag — turning the attack into a useful finding.

---

## 7. Free-tier constraints

| Constraint | Reality | Mitigation |
|---|---|---|
| Render sleeps after 15 min | 30–60s cold start | Warm-up ping on page load, while the user picks a file |
| Gemini limits **requests**, not tokens | RPM and RPD caps | **≤6 LLM calls per analysis**, heavily batched |
| Gemini free tier uses submitted data | Privacy exposure | PII redaction (above) |
| Supabase pauses after 7 days idle | Project sleeps | Cron ping |
| Shared free capacity | 503s are routine | Transient retry with backoff |

### The inverted optimisation

On a paid API the binding constraint is tokens, so you split work into many
small cheap calls. On a free tier the constraint is **requests**, so the correct
move is the opposite: batch several logical tasks into fewer, larger calls.
Per-requirement LLM adjudication would be fatal; all ambiguous requirements go
in one call.

Model versions are **pinned, never `-latest`** — a model changing under us would
break the promise that the same inputs give the same scores.

---

## 8. Testing strategy

| Corpus | Role | Standard |
|---|---|---|
| Synthetic resumes (19, generated) | Regression | 100% behave as the manifest says |
| Real resumes (20+, to collect) | Validation | ≥90% parse at confidence ≥0.7 |
| Job descriptions (15, authored) | Extraction ground truth | ≥85% agreement with hand-written expectations |

Synthetic PDFs cover structure and the adversarial cases that are hard to find
and easy to construct correctly. They **cannot** cover producer quirks — Canva's
fragmented text runs, LaTeX kerning, Word field codes — which is what actually
breaks parsers. Gate 1 therefore requires both; validating the parser against
documents its own author generated would prove very little.

Golden-file tests guard scoring: any rubric or prompt change must show its score
deltas in the diff.

---

## 9. Scaling path

Ordered by what breaks first.

| # | Bottleneck | Fix when it bites |
|---|---|---|
| 1 | LLM rate limits | Concurrency semaphore, backoff, paid tier |
| 2 | Cost per analysis | Model routing, content-hash caching |
| 3 | CPU-bound PDF parsing | Process pool, off the event loop |
| 4 | Long-lived SSE connections | Job queue + polling |
| 5 | Synchronous request model | ARQ workers — a routing change, not a redesign |

Decisions made now to keep this cheap later: pipeline stages are pure functions
with typed I/O, the orchestrator is separate from HTTP handlers, no database in
the request path, and cost accounting from day one.

---

## 10. Repository layout

```
apps/
  api/                    FastAPI backend
    roleva/
      models/             Domain models — the contract between everything
      parsing/            PDF → ResumeDocument
      jd/                 Job description → Requirements
      matching/           The four-tier cascade
      ats/                Deterministic rule registry
      scoring/            PURE. No I/O, no LLM.
      advice/             Grounded suggestions
      llm/                Provider adapter, budget guards, PII redaction
      api/                Routes, auth, error taxonomy
    tests/fixtures/       Corpora + hand-written ground truth
  web/                    Next.js frontend
packages/contracts/       Generated OpenAPI schema
supabase/migrations/      Database schema + RLS policies
docs/                     This file, the checklist, setup guides
```

### Enforced boundaries

- `scoring/` imports nothing that performs I/O.
- Prompts are versioned files, not inline strings.
- The frontend holds no business logic; the BFF exists so secrets stay server-side.
- Generated TypeScript types are checked in CI for drift against the models.

---

## 11. Decision log

| # | Decision | Reason |
|---|---|---|
| 1 | Scoring engine is a pure function | Reproducible, testable, explainable, injection-proof |
| 2 | Evidence strength varies by location | Produces the product's most valuable insight |
| 3 | Must-have gate on Job Match | Prevents actively harmful "you're competitive" advice |
| 4 | Span verification on all evidence | Makes hallucinated evidence undisplayable |
| 5 | PII redaction before every LLM call | Free-tier data policy; also removes a bias vector |
| 6 | Raw PDF never stored | Privacy as an architectural property, not a promise |
| 7 | `score_samples` has no `user_id` | Unlinkable by schema, not by policy |
| 8 | ≤6 LLM calls per analysis | Free tier limits requests, not tokens |
| 9 | Model versions pinned | Determinism would break if Google swapped the model |
| 10 | Both HS256 and JWKS auth supported | Supabase projects use either, and can migrate |
| 11 | No component or chart library | Visual identity is a stated product priority |
| 12 | Gate 1 split across two corpora | Synthetic alone grades the parser against its own author's work |
