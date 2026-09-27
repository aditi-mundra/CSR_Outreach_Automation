# Pre-Deployment Checklist

Run through this before following [`DEPLOYMENT.md`](DEPLOYMENT.md) for a
real launch (as opposed to local development).

## Code / tests

- [ ] `cd backend && pytest -q` passes (116 tests as of 2026-09-27 — see
      [`TASKS.md`](TASKS.md) for what they cover).
- [ ] `cd frontend && npm run build` succeeds with no errors.
- [ ] `cd frontend && npm run lint` (oxlint) is clean.
- [ ] `python backend/scripts/load_test.py` run at least once and
      reviewed — no endpoint should be multiple seconds at the company
      count you actually expect (see the script's own caveat: it runs
      against SQLite, treat it as a smoke check, not a Postgres
      guarantee).

## Environment variables (see each `.env.example` for the full list)

- [ ] `DATABASE_URL` points at the real Neon/Supabase Postgres instance,
      using the `postgresql+psycopg2://` scheme.
- [ ] `CORS_ORIGINS` is set to the real deployed frontend URL (not
      `localhost`) once the frontend is deployed.
- [ ] `NGO_NAME` / `NGO_WORK_AREA` / `NGO_FOCUS_AREAS` / `NGO_CITY` /
      `NGO_STATE` reflect the real NGO, not the placeholder defaults —
      these seed the editable NGO Profile screen on first run.
- [ ] Decide whether `GEMINI_API_KEY` / `HUNTER_API_KEY` /
      `APOLLO_API_KEY` are being used at launch; leave blank
      deliberately (not accidentally) if not — every feature that needs
      them reports `configured: false` in the UI rather than erroring.
- [ ] `VITE_API_BASE_URL` (frontend) is set to the deployed backend's
      origin, no trailing slash, no `/api` suffix.

## Data

- [ ] No leftover test/dummy companies from local development are
      present in the production database (a fresh Neon database starts
      empty — this only matters if you tested against it before
      go-live).
- [ ] If migrating from an existing NGO spreadsheet, do a trial CSV
      import against the deployed backend first (small batch) before
      importing the full list — see the CSV column format in
      [`TASKS.md`](TASKS.md)'s Phase 4 section.

## Security / access

- [ ] There is no authentication in this app (see `TASKS.md`'s
      "Near-Term Engineering Tasks" — this is a known, deliberate gap
      for a single-NGO internal tool). Do not deploy the frontend URL
      publicly/discoverably until that's addressed, if the data is
      sensitive.
- [ ] API keys are only set as Render environment variables, never
      committed to git (`backend/.env` is gitignored; `.env.example`
      files contain no real secrets).

## Sign-off

- [ ] [`UAT_CHECKLIST.md`](UAT_CHECKLIST.md) completed by actual NGO
      staff against the deployed environment, not just by the
      developer.
