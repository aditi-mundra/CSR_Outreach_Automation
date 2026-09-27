# Roadmap

Forward-looking plan, reconciling the phased "Development Order" from
both planning docs with what's actually built (see
[`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md) and current status in
[`TASKS.md`](TASKS.md)). Phases are sequential; scope inside a phase can
move around.

**Stack:** React + Tailwind (`frontend/`) + FastAPI + PostgreSQL
(`backend/`), per explicit decision — not the Streamlit/SQLite stack in
`legacy-streamlit-prototype/`, which is reference-only and does not
count toward any phase below. AI features (Phase 3) use **Google
Gemini**, also per explicit decision.

## Phase 1 — Core Application ✅ Complete

- [x] Create database (PostgreSQL: `companies`, `contacts`, `notes` —
      `backend/app/models.py`)
- [x] Create simple web interface (React + Tailwind, `frontend/`)
- [x] Build company search (`GET /api/companies` with name/industry/
      state/city/csr_focus/status/spending/revenue/employee filters)
- [x] Build company profile page (`CompanyDetailPage.jsx`)
- [x] Build contact database (first-class `Contact` model, many per
      company, full CRUD)
- [x] Add notes and status tracking (`Note` model + lead `status` /
      `follow_up_date` / `last_contacted_date` on `Company`)

## Phase 2 — CSR Contact Discovery ✅ Complete

- [x] Add CSR decision-maker search (site crawler for `/`, `/contact-us`,
      `/contact`, `/csr`, `/sustainability`, `/about/contact`,
      respecting `robots.txt`)
- [x] Add source-link tracking (`Contact.source_url`, populated from
      every scrape/enrichment candidate)
- [x] Save discovered contacts into the Phase 1 contact database
      (review-then-add via `DiscoverContactsPanel.jsx`, not auto-saved)
- [x] Add duplicate detection (by name/website) at company-create time
      (`409` + `?force=true` override)
- [x] Hunter.io / Apollo.io enrichment lookups, surfaced in the company
      detail UI

## Phase 3 — AI Features ✅ Complete

Decision made explicitly with the user (not drifted into): **Google
Gemini** as the LLM provider; lead scoring is a **deterministic
formula + LLM-written explanation**, not a fully LLM-driven score.

- [x] Lead scoring — deterministic 0-100 formula (`app/scoring.py`),
      returned inline on every company response
- [x] Lead priority labels (High/Medium/Low) derived from the score
- [x] AI email generator (First Outreach / Follow-up / Meeting Request /
      Thank You variants), draft-only per the plan's rule — Copy/
      Regenerate buttons, editable before use, never auto-sent
- [x] AI Company Summary (business overview, CSR initiatives, NGO
      compatibility, talking points)
- [x] AI Meeting Brief (background, priorities, discussion points,
      questions, collaboration ideas — uses the company's saved notes)

## Phase 4 — Outreach Tracking ✅ Complete

- [x] Dashboard view with headline KPI tiles (Total Companies,
      Contacted, Replies, Meetings, Proposals, Successful) —
      `GET /api/dashboard`, now the app's landing page
- [x] Follow-up section with due-today/upcoming/overdue grouping,
      built on Phase 1's `follow_up_date`
- [x] Recent-activity feed (company/contact/note/status changes,
      new `ActivityLog` model)
- [x] CSV import/export (company list, respects active filters on
      export; duplicate-skip + per-row error reporting on import)

## Phase 5 — MVP+ Features (from the V2 plan) ✅ Complete

- [x] NGO Profile (org name/mission/focus stored once via
      `GET/PATCH /api/ngo-profile`, reused automatically in lead
      scoring and generated emails)
- [x] Document storage (proposals, CSR reports, MoUs, receipts per
      company — stored in Postgres, no separate file-storage infra)
- [x] Tags (reusable, many-to-many, filterable on the company list)
- [x] Proposal Tracker (Requested → Drafting → Sent → Approved/Rejected,
      per company, activity-logged on stage change)
- [x] Activity Timeline UI (per-company, on the Company Detail page)

## Phase 6 — Final Testing & Deployment 🟡 In progress

- [x] Expand automated tests as features grow (116 backend tests now,
      up from 95 — added validation/edge-case coverage found while
      preparing for larger-volume use, CSV round-trip regression tests
      from the full-phase re-verification, plus contact-duplicate and
      `csr_report_url` coverage)
- [x] Test with real company data at larger volume (`backend/scripts/
      load_test.py` — see results in `TASKS.md`; caveat: run against
      SQLite, not the production Postgres target, since no live
      Postgres instance is available in this environment)
- [ ] Test with actual NGO staff; simplify confusing screens — **not
      done**, needs real staff on a deployed environment; see
      [`UAT_CHECKLIST.md`](UAT_CHECKLIST.md) for the checklist to run
      when that happens
- [ ] Deploy (target per the plan: Vercel for the frontend, Render for
      the backend, Neon for PostgreSQL) — **not done**; deployment is
      prepared but not executed (needs the user's own hosting
      accounts/credentials) — see [`DEPLOYMENT.md`](DEPLOYMENT.md) and
      [`PRE_DEPLOYMENT_CHECKLIST.md`](PRE_DEPLOYMENT_CHECKLIST.md)
- [x] Write a one-page user guide for non-technical staff —
      [`USER_GUIDE.md`](USER_GUIDE.md)

---

## Explicitly Out of Scope (per the planning docs)

- Docker, Kubernetes, CI/CD pipelines, microservices, or other
  infrastructure complexity. (Phase 1's backend was verified with
  pytest + a manual local run — no Docker involved in the app itself.)
- Collecting private/personal contact info (personal emails, private
  phone numbers) — public professional info only.
- Auto-sending outreach emails — the tool only ever produces drafts for
  a human to review and send.
