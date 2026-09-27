# CSR Corporate Outreach Portal

Web application to help A Ray of Hope Foundation (Pune) find, prioritize,
and track outreach to companies for CSR partnerships.

## Structure

```
CSR_Outreach_Automation/
├── backend/                    # FastAPI + PostgreSQL API (Phase 1: core application)
│   ├── app/
│   │   ├── main.py               # app entrypoint
│   │   ├── models.py             # Company, Contact, Note (SQLAlchemy)
│   │   ├── schemas.py            # Pydantic request/response schemas
│   │   ├── crud.py               # data-access functions
│   │   └── routers/              # companies / contacts / notes endpoints
│   └── tests/                    # pytest suite
├── frontend/                   # React + Tailwind (Vite) UI
│   └── src/
│       ├── pages/                 # Companies list, Company detail
│       ├── components/            # filters, forms, contacts/notes/status panels
│       └── api/client.js          # backend API client
├── docs/                        # project docs (overview, tasks, roadmap, changelog)
├── legacy-streamlit-prototype/    # superseded early prototype — reference only, see its README
└── README.md
```

See [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) for the full
product spec, [`docs/TASKS.md`](docs/TASKS.md) for current build status,
and [`docs/ROADMAP.md`](docs/ROADMAP.md) for what's next.

## Quickstart (local dev)

Fastest way to get the app running on your machine. Two terminals.

**1. Backend** (`http://localhost:8000`):

```powershell
cd backend
python -m venv venv                       # first time only
.\venv\Scripts\python.exe -m pip install -r requirements.txt   # first time only
$env:DATABASE_URL = "sqlite:///./local.db"
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

On macOS/Linux use `source venv/bin/activate` and
`DATABASE_URL="sqlite:///./local.db" uvicorn app.main:app --reload --port 8000`.

**2. Frontend** (`http://localhost:5173`):

```bash
cd frontend
npm install                               # first time only
npm run dev
```

Open <http://localhost:5173>. Start the backend first — Vite proxies
`/api/*` to port 8000 (see `vite.config.js`), so the UI shows errors if
nothing is listening there.

**Want some data to look at?** With the backend's venv and the same
`DATABASE_URL` set:

```powershell
.\venv\Scripts\python.exe scripts\seed_demo_data.py
```

That loads ten realistic demo companies and is safe to re-run (it skips
ones that already exist).

### Heads-up: `DATABASE_URL` has no usable default

There is no `backend/.env` in a fresh checkout, and the fallback in
`app/config.py` points at `postgresql+psycopg2://csr_user:csr_password@
localhost:5432/csr_outreach`. If you start the backend without setting
`DATABASE_URL`, it will try to reach a Postgres server on localhost and
fail with a connection error — that's this default, not a broken app.

So pick one:

- **SQLite** (as above) — zero setup, fine for looking around and for
  local feature work. Not the production target.
- **PostgreSQL** — the real target (see
  [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md)). Copy
  `backend/.env.example` to `backend/.env` and set `DATABASE_URL` to a
  local install or a free Neon/Supabase instance. Everything else in
  that file is optional: leave `GEMINI_API_KEY`, `HUNTER_API_KEY` and
  `APOLLO_API_KEY` blank and those features report "not configured"
  rather than erroring.

Tables are created automatically on startup either way. To deploy, see
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Backend setup

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # source venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env         # then set DATABASE_URL to your PostgreSQL instance
```

`DATABASE_URL` must point at a real PostgreSQL database — a local
install, or a free managed instance (Neon / Supabase), per
[`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md)'s recommended
stack. No Docker is required or used by the app itself.

Run it:

```bash
uvicorn app.main:app --reload
```

Tables are created automatically on startup. Run the test suite (uses an
isolated in-memory SQLite database, no Postgres required for tests):

```bash
pytest -q
```

## Frontend setup

```bash
cd frontend
npm install
npm run dev
```

The dev server runs on `http://localhost:5173` and proxies `/api/*`
requests to the backend on `http://localhost:8000` (see
`vite.config.js`). Start the backend first.
