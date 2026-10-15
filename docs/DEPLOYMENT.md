# Deployment Guide

Step-by-step instructions to put the app online, following the stack
decision in [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md): **Neon**
(PostgreSQL) + **Render** (backend) + **Vercel** (frontend). No Docker,
no Kubernetes, no CI pipeline — three free-tier signups and some copy/
pasted env vars.

Config files already in the repo to support this:

- `render.yaml` — Render Blueprint for the backend web service.
- `frontend/vercel.json` — SPA rewrite so client-side routes (e.g.
  `/companies/5`) don't 404 on a hard refresh.
- `backend/.env.example` / `frontend/.env.example` — every environment
  variable either service reads, with comments.

This is a plan to follow yourself when you're ready — nothing here has
been deployed; it needs your own Neon/Render/Vercel accounts.

---

## 1. Database — Neon (PostgreSQL)

1. Create a free account at [neon.tech](https://neon.tech) and a new
   project (any region close to your Render region is fine).
2. Neon gives you a connection string that looks like:
   ```
   postgresql://<user>:<password>@<host>/<dbname>?sslmode=require
   ```
3. Rewrite it for SQLAlchemy's psycopg2 driver (the app expects the
   `+psycopg2` dialect, see `backend/app/config.py`):
   ```
   postgresql+psycopg2://<user>:<password>@<host>/<dbname>?sslmode=require
   ```
   Save this — it's your `DATABASE_URL`.
4. No migration step needed: the backend calls
   `Base.metadata.create_all()` on startup (`app/main.py`'s `lifespan`),
   which creates every table if they don't already exist. The very
   first deploy will create the schema automatically.

## 2. Backend — Render

1. Push this repo to GitHub (Render deploys from a git remote).
2. In the Render dashboard: **New +** → **Blueprint**, point it at the
   repo. Render will read `render.yaml` at the repo root and propose a
   single web service, `csr-outreach-backend`, rooted at `backend/`.
3. Before the first deploy, fill in the environment variables Render
   marks as required (blank/`sync: false` in `render.yaml`):

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | the Neon connection string from step 1 |
   | `CORS_ORIGINS` | your Vercel frontend URL, e.g. `https://csr-outreach.vercel.app` (comma-separate if you also want to allow `http://localhost:5173` for local testing against the deployed backend) |
   | `NGO_NAME`, `NGO_WORK_AREA`, `NGO_FOCUS_AREAS`, `NGO_CITY`, `NGO_STATE` | your NGO's defaults — only seed the `ngo_profile` row on first run; staff can edit them afterwards from the NGO Profile screen |
   | `GEMINI_API_KEY` | optional — leave blank to ship without AI features; get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
   | `HUNTER_API_KEY` / `APOLLO_API_KEY` | optional — leave blank to ship without contact-enrichment lookups |
   | `DISCOVERY_CONTACT` | optional, recommended — an email/URL sent in the User-Agent to Wikidata/data.gov.in for company discovery |
   | `DATA_GOV_IN_API_KEY` | optional — enables the MCA company registry in company discovery; free key from [data.gov.in](https://data.gov.in). Wikidata discovery works without it. See [`COMPANY_DISCOVERY.md`](COMPANY_DISCOVERY.md) |

4. Deploy. Render builds with `pip install -r requirements.txt` and
   runs `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
5. Once live, confirm it's healthy:
   ```
   curl https://<your-service>.onrender.com/api/health
   # {"status": "ok"}
   ```

**Free-tier note:** Render's free web services spin down after ~15
minutes idle and take a few seconds to wake on the next request — the
first request after a quiet period will be slow. That's a Render
free-tier behavior, not an app bug.

## 3. Frontend — Vercel

1. In the Vercel dashboard: **Add New** → **Project**, import the same
   repo, and set the project's **Root Directory** to `frontend/`.
   Vercel auto-detects the Vite framework preset (build command
   `npm run build`, output directory `dist`).
2. Add one environment variable, in Vercel's project settings:

   | Variable | Value |
   |---|---|
   | `VITE_API_BASE_URL` | your Render backend's URL from step 2, e.g. `https://csr-outreach-backend.onrender.com` — **no trailing slash, no `/api` suffix** |

   (See `frontend/src/api/client.js` — it appends `/api` itself and
   falls back to a relative path when this is unset, which is what
   makes local dev work unchanged.)
3. Deploy. `frontend/vercel.json`'s rewrite ensures every route falls
   back to `index.html`, so react-router's client-side routes survive a
   direct link or a hard refresh.
4. Go back to Render and update `CORS_ORIGINS` to the real Vercel URL
   you were just given (Vercel assigns the final URL after first
   deploy), then redeploy the backend so CORS actually allows it.

## 4. Smoke test after both are live

1. Open the Vercel URL. The Dashboard (landing page) should load with
   zero companies — that's expected on a fresh database.
2. Add one test company, add a contact and a note, set a follow-up
   date, generate an email draft (if `GEMINI_API_KEY` is set — you
   should see `configured: false` handled gracefully if not).
3. Refresh on a deep link (e.g. that company's detail page URL) to
   confirm the Vercel rewrite is working (no blank page / 404).
4. Delete the test company once satisfied.
5. Walk through [`UAT_CHECKLIST.md`](UAT_CHECKLIST.md) with real NGO
   staff before treating this as production-ready — everything above
   only proves the deploy works, not that the app is usable by its
   actual users.

## 5. Ongoing operation

- **Schema changes:** this app has no migration tool (Alembic isn't
  set up; see the "Near-Term Engineering Tasks" note in
  [`TASKS.md`](TASKS.md)). On startup, `create_all()` adds missing
  tables, and `app/schema_upgrade.py` adds any missing **nullable**
  column to an existing table. That covers contact discovery's new
  `contacts` / `notes` / `activity_logs` columns, so no manual SQL is
  needed for this release. Renames, type changes or NOT NULL columns
  still need to be applied to the Neon database by hand, or Alembic
  introduced first.
- **Backups:** Neon's free tier keeps point-in-time recovery for a
  short window — check current retention on their pricing page before
  relying on it for anything you can't afford to lose.
- **Rotating a leaked key:** if `GEMINI_API_KEY`/`HUNTER_API_KEY`/
  `APOLLO_API_KEY` ever leak, revoke at the provider and update the
  Render env var — no code change needed.
