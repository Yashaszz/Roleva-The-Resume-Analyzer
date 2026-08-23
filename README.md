# Roleva

**Evidence-based resume analyzer.** Upload a PDF resume, paste a job description, get a scored, explainable assessment where every number traces back to a specific line in your resume.

> Core principle: **the LLM extracts and judges; the code computes.** No score in this system originates from a language model.

---

## Status

Pre-alpha. See [docs/CHECKLIST.md](docs/CHECKLIST.md) for build progress.

---

## Structure

| Path | What |
|---|---|
| `apps/web` | Next.js frontend |
| `apps/api` | FastAPI backend + analysis pipeline |
| `packages/contracts` | Shared API types (generated from OpenAPI) |
| `supabase/migrations` | Database schema |
| `docs` | Architecture, scoring rubric, checklist |

---

## Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 15, React 19, TypeScript, Tailwind v4, Radix, Motion |
| Backend | FastAPI, Python 3.12, Pydantic v2 |
| Parsing | PyMuPDF |
| Database + Auth | Supabase (Postgres + RLS) |
| LLM | Google Gemini (free tier), behind a provider adapter |
| Hosting | Vercel (web) + Render (api) |

---

## Local setup

**Prerequisites:** Node 20+, pnpm, Python 3.12

```bash
# 1. env
cp .env.example .env

# 2. backend
cd apps/api
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
uvicorn roleva.main:app --reload --port 8000

# 3. frontend
pnpm install
pnpm dev:web
```

---

## Docs

- [Architecture](docs/ARCHITECTURE.md)
- [Build checklist](docs/CHECKLIST.md)
