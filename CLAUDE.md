# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project Structure

```
CSR_Outreach_Automation/
├── backend/                    # FastAPI + PostgreSQL API (active development)
│   ├── app/                      # main.py, models.py, schemas.py, crud.py, routers/
│   └── tests/                     # pytest suite (SQLite in-memory, no live Postgres needed)
├── frontend/                   # React + Tailwind (Vite) UI, proxies /api to backend on :8000
├── docs/                        # project docs, see below
├── legacy-streamlit-prototype/    # superseded prototype — NOT counted toward phase completion
└── CLAUDE.md
```

`backend/` is a standard FastAPI + SQLAlchemy app: `app/models.py` (ORM
models) → `app/schemas.py` (Pydantic I/O) → `app/crud.py` (data access) →
`app/routers/*.py` (HTTP endpoints), wired in `app/main.py`. The app
targets **PostgreSQL** via `DATABASE_URL`; only the test suite substitutes
an in-memory SQLite database (dependency override in `tests/conftest.py`)
so tests don't require a live Postgres server. Don't add Docker,
Kubernetes, or other infra — `docs/PROJECT_OVERVIEW.md` explicitly calls
this out as out of scope; a local Postgres install or a free managed
instance (Neon/Supabase) is the intended path.

`legacy-streamlit-prototype/` is reference-only. Per explicit user
instruction, it does not count toward any phase's completion status in
`docs/TASKS.md` / `docs/ROADMAP.md` — new phase work always means
building in `backend/` + `frontend/`, never crediting or extending the
legacy prototype.

## Project Docs

Authoritative project documentation lives in [`docs/`](docs/). Read these
before making non-trivial changes:

- [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) — what this
  product is and does (merged product spec), plus how the shipped code
  currently differs from the original plan.
- [`docs/TASKS.md`](docs/TASKS.md) — feature-by-feature build status
  against the spec.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — phased forward plan.
- [`docs/CHANGELOG.md`](docs/CHANGELOG.md) — history of shipped changes.

When you finish work that changes what's built, update `TASKS.md` (and
`ROADMAP.md`/`CHANGELOG.md` where relevant) to keep them in sync with
the code — they're meant to reflect actual state, not just the plan.

## Git Commits

**Never add Claude/Anthropic as a co-author, byline, or attribution of
any kind in git commits, PRs, or any other git history in this repo.**
Do not include `Co-Authored-By: Claude`, a Claude session link, or any
similar trailer. Commit authorship must show only the human author.
