# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## 2026-09-27

### Added — `feat: track a company's CSR report link`

- **`csr_report_url` on companies.** `PROJECT_OVERVIEW.md`'s Company
  Profile page lists a "CSR report link" alongside the general website,
  and it's the artifact staff actually research from, so it gets its own
  field rather than being buried in notes — this was a real gap against
  the spec, not a new idea. Plumbed end to end: column
  (`models.py`), `CompanyCreate`/`CompanyUpdate`, the `_CSV_COLUMNS`
  list and export writer so it survives an export/import round trip, an
  input on `CompanyForm.jsx`, and a link on `CompanyDetailPage.jsx`.

### Added — `feat: flag duplicate contacts with an "add anyway" override`

- **Contact-level duplicate detection.** Re-scanning a company's site
  re-surfaces the same people, and the contact form is easy to
  double-submit, so companies were quietly accumulating duplicate
  contact rows with no signal that it had happened. New
  `crud.py::find_duplicate_contact` is the counterpart to the existing
  `find_duplicate_company`: `POST /api/companies/{id}/contacts` now
  returns `409` with the existing contact's id/name/email on a
  case-insensitive email or name match, and `?force=true` bypasses it.
- **Scoped per company on purpose.** The same professional appearing
  under two different companies is a real (if odd) situation; the same
  email twice under one company is almost always a re-scan or a
  double-submit. Email is checked before name, since two genuinely
  different people can share a common name but an email is the identity.
- **Both frontend entry points surface it inline** rather than failing:
  `ContactsSection.jsx`'s form, and `DiscoverContactsPanel.jsx`, where
  the warning attaches to the one candidate row — a duplicate is routine
  enough there that it must not take down the whole candidate list. The
  panel clears all its warnings after a successful add, because removing
  a candidate shifts the remaining indices and index-keyed warnings
  would otherwise point at the wrong row.
- `addContact()` in `frontend/src/api/client.js` takes an options
  argument (`{ force }`); the existing `request()` helper already
  exposed `error.status`/`error.detail`, which is what the 409 handling
  reads.
- 6 new tests in `backend/tests/` (5 contact-duplicate cases covering
  email match, name match, `force`, cross-company allowance, and
  name-only matching when neither side has an email; 1 covering the
  `csr_report_url` CSV round trip). **116/116 backend tests passing**
  (up from 110).

### Documentation

- `README.md`: added a two-terminal local-dev quickstart, and an explicit
  heads-up that `DATABASE_URL` has no usable default — a fresh checkout
  has no `backend/.env` and the fallback in `app/config.py` points at a
  local Postgres that probably isn't running, so the backend fails with
  a connection error that reads like a broken app rather than a missing
  config. Documents the SQLite escape hatch and the Postgres path.
- Added `CLAUDE.md` recording repo conventions that aren't derivable
  from the code: which directories are active development, that
  `legacy-streamlit-prototype/` is reference-only and never counts
  toward phase completion, and that container infra is out of scope.

## 2026-09-26 (3)

### Fixed — `fix: preserve outreach fields on CSV import, seed on a fresh DB`

Found by re-verifying every phase end-to-end against a live backend
(all six phases exercised over real HTTP, not just via the test suite).

- **CSV export/import round-trip silently dropped outreach state.** The
  export writes `status`, `last_contacted_date` and `follow_up_date`
  (`_CSV_COLUMNS`), but the import builds rows through `CompanyCreate`,
  which had none of those fields — so exporting the company list,
  editing it in Excel and re-importing reset every company to "New"
  with no dates, reporting `errors: []` as if it had worked. The three
  fields are now part of `CompanyCreate`, so the round-trip preserves
  them.
- **Invalid `status` was silently swallowed on company create.** Because
  `CompanyCreate` had no `status` field, `POST /api/companies` accepted
  `{"status": "Nonsense"}` with `201` and quietly stored "New" instead.
  It now returns `422`, matching the existing behaviour of the status
  *filter* and *update* paths. A valid status is accepted at create time
  (which is what makes the CSV round-trip above work).
- **`scripts/seed_demo_data.py` crashed on a fresh database** with
  `no such table: companies`. Table creation only happened in the app's
  FastAPI lifespan, so the script worked only against a database the app
  had already booted against — not against the freshly provisioned
  Postgres its own docstring points it at. It now calls
  `Base.metadata.create_all` first, like `load_test.py` already did.
- 3 new regression tests in `backend/tests/test_csv.py` (round-trip
  preservation, invalid status as a per-row import error, status
  accepted/validated at create). 110/110 backend tests passing.

## 2026-09-26 (2)

### Added — `feat: harden validation/uploads and prepare deployment (Phase 6)`

- Validation: `csr_spending`/`revenue`/`employee_count` (companies) and
  `amount` (proposals) now reject negative values (`ge=0` on the
  relevant Pydantic schemas); a CSV import row that fails this
  validation is now reported as a per-row error instead of raising and
  500ing the whole import.
- Upload caps: document upload and CSV import now enforce a max size
  (10 MB / 5 MB, `MAX_DOCUMENT_UPLOAD_BYTES` / `MAX_CSV_IMPORT_BYTES`),
  returning `413` — previously unbounded.
- `GET /api/companies`'s `limit` is now capped at 500 (was unbounded);
  `skip`/`limit` reject negative/zero values.
- `backend/tests/test_validation.py`: 12 new pytest cases covering all
  of the above. 107/107 backend tests passing (up from 95).
- `backend/scripts/load_test.py`: seeds 3,000 companies and times the
  real endpoints against them (SQLite, since no live Postgres is
  available here) — see results in `TASKS.md`'s Phase 6 section.
- `backend/scripts/seed_demo_data.py`: ten realistic demo companies for
  showing the app or running UAT sessions; idempotent.
- Deployment prep (not executed — needs the user's own hosting
  accounts): `render.yaml` (backend Blueprint), `frontend/vercel.json`
  (SPA rewrite), `frontend/src/api/client.js` now reads
  `VITE_API_BASE_URL` so the frontend can target a separately-hosted
  backend (falls back to the existing relative `/api` path — local dev
  unaffected). New docs: `docs/DEPLOYMENT.md`,
  `docs/PRE_DEPLOYMENT_CHECKLIST.md`, `docs/UAT_CHECKLIST.md`,
  `docs/USER_GUIDE.md`.
- `npm run build` / `npm run lint` clean on the frontend after the
  `client.js` change.

## 2026-09-26

### Added — `feat: add NGO profile, tags, documents, and proposal tracker (Phase 5)`

- `NGOProfile` model (single row, `backend/app/models.py`), replacing
  the env-only `NGO_*` settings as the thing NGO staff actually edit.
  `GET/PATCH /api/ngo-profile`; every read/write mirrors the row onto
  the live `settings` object (`crud.py`'s `_sync_settings_from_ngo_profile`)
  so `scoring.py` and `ai.py` pick up profile edits immediately without
  a db session threaded through either module, and re-syncs from the DB
  on app startup so edits survive a restart.
- `Tag` model + `company_tags` many-to-many association: reusable,
  get-or-create by case-insensitive name, filterable on the company
  list (`GET /api/companies?tag=...`), managed via `/api/tags` and
  `/api/companies/{id}/tags[/​{tag_id}]`.
- `Document` model: file bytes stored directly in Postgres
  (`LargeBinary`, deferred-loaded so listing documents doesn't pull
  file contents into memory) - no separate file-storage infra needed.
  Upload/download/delete via `routers/documents.py`.
- `Proposal` model with its own stage pipeline (Requested → Drafting →
  Sent → Approved/Rejected), separate from the company's overall lead
  `status` since a company can have several proposals over time; stage
  changes are activity-logged.
- `CompanyDetail` now embeds the company's own `activity_logs` (full
  per-company history), rendered as a timeline on the Company Detail
  page. Fixed a same-second activity-ordering bug found while verifying
  this live - added an `id DESC` tiebreaker alongside `created_at DESC`.
- Frontend: `NGOProfilePage.jsx` (new `/ngo-profile` route, linked from
  the nav), `TagsSection.jsx`, `DocumentsSection.jsx`,
  `ProposalsSection.jsx`, `ActivityTimeline.jsx` on the Company Detail
  page; tag chips + a tag filter dropdown on the Companies page.
- 21 new pytest cases; full backend suite now 95/95 passing. Verified
  live against the real dev stack (Vite proxy → FastAPI → SQLite),
  including byte-for-byte document round-tripping and an NGO profile
  edit changing a newly-created company's lead score. `npm run build`
  and `oxlint` clean.

## 2026-09-25

### Added — `feat: add outreach dashboard, activity feed, and CSV import/export (Phase 4)`

- New `ActivityLog` model (`backend/app/models.py`), cascade-deleted with
  its company. Written as a side effect of `crud.py`'s company/contact/
  note create + status-change logic, and by `routers/ai.py` after a
  successful email draft - no separate "log this" call needed anywhere.
- `GET /api/dashboard` (`backend/app/routers/dashboard.py`): headline
  KPI tiles (Total Companies, Contacted, Replies Received, Meetings
  Scheduled, Proposals Sent, Successful Partnerships), follow-ups
  bucketed into Overdue/Due Today/Upcoming (excludes closed-out leads),
  and the latest 20 activity-feed entries - one call for the whole
  dashboard screen. KPIs beyond raw counts read the `LeadStatus`
  pipeline in order (documented in `crud.py`) so e.g. a company at
  "Proposal Sent" still counts toward "Meetings Scheduled", without
  adding new schema just to track historical funnel stages.
- `GET /api/companies/export` / `POST /api/companies/import`
  (`backend/app/routers/companies.py`): CSV export respects the same
  filters as the company list; import reuses the existing duplicate
  check (skips rather than overwrites) and reports per-row errors
  (missing name, bad numbers) instead of failing the whole upload.
- `frontend/src/pages/DashboardPage.jsx` is now the app's landing page
  (`/`); Companies moved to `/companies`. Export/Import CSV buttons
  added to the Companies page toolbar.
- 10 new pytest cases (KPI-pipeline math, follow-up bucketing, activity
  feed ordering/cascade-delete, CSV export/import incl. duplicates and
  bad rows, activity logging on email generation); full backend suite
  now 74/74 passing. Verified live against the real dev stack (Vite
  proxy → FastAPI → SQLite). `npm run build` and `oxlint` clean.

### Added — `feat: add revenue/employee filters and pagination to company list`

- `CompanyFilters.jsx`: revenue and employee-count are now exposed in
  the UI as an optional "More filters" toggle (min/max revenue, min/max
  employees) — closes the gap where the spec's "Optional filters:
  Revenue, Employee Count" (`docs/PROJECT_OVERVIEW.md`) had no frontend
  filter UI at all, despite backend support in `search_companies`.
- `CompaniesPage.jsx`: Previous/Next pagination (25 per page) using the
  `skip`/`limit` params the backend already supported; page resets to 0
  whenever filters change.
- Verified live against the real dev stack (Vite proxy → FastAPI →
  SQLite): seeded companies with varying revenue/employee counts,
  confirmed filtering and paging return the expected slices over HTTP.
  `npm run build` and `oxlint` clean; full 64/64 backend suite still
  passing (no backend changes needed - the filter/pagination params
  already existed).

### Docs — `docs: update project docs for Phase 3 completion`

- Marked Phase 3 (AI Features) complete in `TASKS.md` and `ROADMAP.md`,
  recording the explicit provider decision (Google Gemini) and scoring
  approach (deterministic formula + LLM explanation) made with the
  user, plus verification notes.

### Added — `feat: add AI lead-score explanations, email/summary/brief generation (Phase 3)`

- `app/scoring.py`: deterministic 0-100 lead score from CSR-focus
  match, CSR spending, location match with the NGO's own city/state,
  and company size. Returned inline (`lead_score`) on every company
  list/detail response - no separate request needed. Priority label
  (High ≥70 / Medium ≥40 / Low) derived from the score.
- `app/ai.py`: Google Gemini integration (`GEMINI_API_KEY`,
  `GEMINI_MODEL`) for everything that needs an LLM - score
  explanations, email drafts, company summaries, meeting briefs. Every
  function returns `None`/reports `configured: false` when no key is
  set, same graceful-degradation pattern as Hunter/Apollo in Phase 2.
  Nothing here sends an email or takes any outreach action on its own.
- New endpoints: `POST /api/companies/{id}/score/explain`,
  `/generate-email` (First Outreach / Follow-up / Meeting Request /
  Thank You, optionally personalized to a contact), `/summary`,
  `/meeting-brief` (uses the company's saved notes as context).
- NGO profile fields (`NGO_NAME`, `NGO_WORK_AREA`, `NGO_FOCUS_AREAS`,
  `NGO_CITY`, `NGO_STATE`) added to `app/config.py`/`.env.example` -
  env-configured for now; Phase 5 will turn this into a proper profile.
- 26 new pytest cases (scoring-formula units, `ai.py` prompt/parsing
  units with mocked Gemini responses, AI-router tests incl. the
  "not configured" path); full backend suite now 64/64 passing.

### Added — `feat: add lead score, priority badges, and AI panel to frontend`

- `LeadScoreBadge.jsx`: score/priority badge on the company detail
  header with an on-demand "Why?" explanation (not auto-fetched, to
  avoid an LLM call on every page load).
- `AIPanel.jsx` (`AITextCard.jsx` + `EmailGeneratorPanel.jsx`) on the
  company detail page: Company Summary and Meeting Brief cards
  (generate/regenerate), and an email generator with a type selector,
  optional contact personalization, editable subject/body, and a Copy
  button - draft-only, no send action anywhere in the app.
- Lead Score column added to the company list table.

### Docs — `docs: update project docs for Phase 2 completion`

- Marked Phase 2 (CSR Contact Discovery) complete in `TASKS.md` and
  `ROADMAP.md`, with verification notes (test counts, the live
  robots.txt/scraping check against a local test site).

### Added — `feat: add contact discovery UI and duplicate-warning flow to frontend`

- New `DiscoverContactsPanel.jsx` on the company detail page: "Scan
  website" and "Enrich (Hunter/Apollo)" buttons surface candidate
  contacts (email/phone/LinkedIn/source), each addable to the Phase 1
  contact list after staff name them — nothing is auto-saved.
- `CompanyForm.jsx` now handles the backend's `409` duplicate response:
  shows the existing company's name with a "View existing" link and a
  "Create anyway" override that resubmits with `force=true`.
- `api/client.js`: `createCompany` accepts a `force` option; failed
  requests now carry `status` and structured `detail` on the thrown
  error so callers can branch on them; added `scrapeCompany` /
  `enrichCompany`.

### Added — `feat: add CSR contact discovery to backend (scraping, enrichment, duplicate detection)`

- `app/scraping.py`: crawls a company's own site (home, `/contact-us`,
  `/contact`, `/csr`, `/sustainability`, `/about/contact`) for public
  emails, phone numbers, and LinkedIn URLs. Identifiable User-Agent,
  `robots.txt` checked per path, fixed delay between requests, results
  deduped across pages. `POST /api/companies/{id}/scrape`.
- `app/enrichment.py`: Hunter.io domain-search and Apollo.io
  people-search integrations, filtered to CSR-relevant titles. Gated
  behind `HUNTER_API_KEY`/`APOLLO_API_KEY`; reports `configured: false`
  when neither is set rather than silently returning nothing. `POST
  /api/companies/{id}/enrich`.
- `crud.py::find_duplicate_company`: case-insensitive name match or
  normalized-website match. `POST /api/companies` now returns `409`
  with the existing company's id/name unless `?force=true` is passed.
- 25 new backend pytest cases (12 discovery-endpoint, 7 scraping unit,
  6 enrichment unit); full backend suite now 38/38 passing.

### Docs — `docs: add project docs for Phase 1`

- Added root `README.md` (setup/run instructions for both the backend
  and frontend) and a `docs/` folder (`PROJECT_OVERVIEW.md`, `TASKS.md`,
  `ROADMAP.md`, this changelog).
- Merged the old `PROJECT_OVERVIEW_V1.md` / `_V2.md` planning docs into
  `docs/PROJECT_OVERVIEW.md`, then updated it, `TASKS.md`, and
  `ROADMAP.md` to reflect Phase 1 completion on the FastAPI/PostgreSQL +
  React stack.

### Added — `feat: add React + Tailwind frontend for Phase 1 core application`

- New `frontend/` React + Tailwind (Vite) SPA: a Companies list page
  (search/filter, add-company modal, status badges) and a Company
  detail page (contacts CRUD, notes CRUD, status/follow-up editing),
  routed with `react-router-dom`. Dev server proxies `/api/*` to the
  backend on `:8000`.
- Verified: `npm run build` and `oxlint` clean; full create-company →
  add-contact → add-note → update-status → fetch-detail → filtered-list
  workflow exercised end-to-end over real HTTP through the dev proxy
  against the live backend.

### Added — `feat: add FastAPI + PostgreSQL backend for Phase 1 core application`

- New `backend/` FastAPI app: SQLAlchemy models for `Company`, `Contact`
  (many per company), and `Note`; full CRUD via `app/crud.py`; REST
  endpoints under `/api/companies`, `/api/contacts`, `/api/notes`
  (`app/routers/`). Targets PostgreSQL via `DATABASE_URL`.
- Company search endpoint with filters: name, industry, city, state,
  CSR focus, status, and CSR-spending/revenue/employee-count ranges.
- Lead status tracking (`New` → ... → `Successful`/`Not Interested`)
  plus `last_contacted_date` / `follow_up_date` on each company.
- 13 backend pytest cases (company/contact/note CRUD, filters, cascade
  delete, 404s), run against an isolated in-memory SQLite database via
  dependency override — no live Postgres required for tests.

### Changed — `chore: move legacy Streamlit prototype into legacy-streamlit-prototype/`

- Moved the earlier Streamlit/SQLite prototype (`app.py`, its `src/`
  package, `data/`, `tests/`) into `legacy-streamlit-prototype/` as a
  unit, once the new `backend/`/`frontend/` build superseded it —
  reference-only, explicitly excluded from phase-completion accounting
  per user instruction.

## 2026-09-02

### Fixed — `7ff86c8` fix: resolve module imports and safe-handle missing phone column in directory view

- Fixed `ModuleNotFoundError` by standardizing project folder structure
  and module imports (dropped the `modules/` sub-package in favor of
  top-level modules).
- Added a fallback check for the `phone` column in `app.py` to prevent a
  `KeyError` during directory rendering.
- Updated SQLite schema and migration logic to cleanly support phone
  fields.
- Split business logic out into standalone `compliance_engine.py`,
  `config.py`, `enrichment.py`, and `scraper.py` modules.
- Verified Streamlit UI rendering across the Lead Directory, Scraper,
  and Pitch Generator tabs.

### Added — `d5a48e1` feat: implement outreach dashboard, database schema, and compliance engine

- Implemented the outreach dashboard / analytics view in `app.py`.
- Expanded the SQLite database schema (`database.py`), including the
  `interaction_logs` table.
- Added the CSR compliance engine (`modules/compliance_engine.py` at
  this point in history) — CSR-1 / 80G / 12A badges and Q4 financial-year
  urgency calculation.

### Added — `b91c902` feat: Initial Prototype of website

- Initial Streamlit prototype: `app.py` and `database.py`.
- Basic company directory and SQLite persistence.
