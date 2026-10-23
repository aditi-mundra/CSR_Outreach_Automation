# Tasks

Status against the phased plan in [`ROADMAP.md`](ROADMAP.md), as of
2026-10-15. **The `legacy-streamlit-prototype/` code does not count
toward any phase's completion** (explicit user instruction) — all
status below reflects only `backend/` (FastAPI + PostgreSQL) and
`frontend/` (React + Tailwind). Legend: ✅ done · 🟡 partial · ⬜ not
started.

## Phase 1 — Core Application — ✅ Complete

- [x] **Database** — PostgreSQL via SQLAlchemy (`backend/app/models.py`):
      `companies`, `contacts` (many per company), `notes`. Tables are
      created automatically on app startup.
- [x] **Web interface** — React + Tailwind (Vite) SPA: a Companies list
      page and a Company detail page, routed with `react-router-dom`.
- [x] **Company search** — filter by name, industry, city, state,
      CSR focus, status, and CSR-spending/revenue/employee-count ranges
      (`GET /api/companies`, `backend/app/crud.py::search_companies`).
- [x] **Company profile page** — `frontend/src/pages/CompanyDetailPage.jsx`:
      company info, CSR focus/spending/revenue/employee stats, contacts,
      notes, and outreach status — all in one view. The spec's "CSR
      report link" (`PROJECT_OVERVIEW.md`'s Company Profile page) is a
      dedicated `csr_report_url` field, added 2026-09-27 — kept separate
      from the general `website` because the published CSR/sustainability
      report is the artifact staff actually research from. Editable on
      the company form, shown as a link on the detail page, and part of
      `_CSV_COLUMNS` so it survives an export/import round trip.
- [x] **Contact database** — first-class `Contact` model, many per
      company, full CRUD (add/edit/delete) via
      `frontend/src/components/ContactsSection.jsx` and
      `/api/companies/{id}/contacts`, `/api/contacts/{id}`.
- [x] **Notes and status tracking** — freeform `Note`s per company
      (`NotesSection.jsx`) plus a `status` (lead stage enum),
      `last_contacted_date`, and `follow_up_date` on each company,
      editable via `StatusPanel.jsx` / `PATCH /api/companies/{id}`.

**Verified:** 13/13 backend pytest cases passing (company CRUD/search,
contact CRUD, note CRUD, cascade delete, 404 handling); `npm run build`
and `oxlint` clean on the frontend; full create-company → add-contact →
add-note → update-status → fetch-detail → filtered-list workflow
exercised end-to-end through the real dev stack (Vite proxy → FastAPI →
DB) via HTTP, matching exactly what the UI calls.

**Update (2026-09-25):** revenue/employee-count are now exposed in the
UI as an *optional* "More filters" toggle in `CompanyFilters.jsx` (per
the spec's "Optional filters: Revenue, Employee Count"), and the company
list has Previous/Next pagination (`CompaniesPage.jsx`, 25 per page)
using the `skip`/`limit` params `search_companies` already supported.
Verified live against the real dev stack (Vite proxy → FastAPI →
SQLite): seeded companies with varying revenue/employee counts,
confirmed `min_revenue`/`max_revenue`/`min_employees`/`max_employees`
filtering and `skip`/`limit` paging return the expected slices over
HTTP. `npm run build` and `oxlint` clean.

**Gap closed (2026-10-15): real company discovery.** The "Company
search" item above only ever searched the NGO's *own* `companies` table,
so a fresh install showed nothing but the ten fictional companies from
`scripts/seed_demo_data.py`. The spec's Company Search data sources (MCA
public company data, NSE/BSE information, CSR reports, company websites)
were never integrated. Now they are. Full design, setup and limits:
[`COMPANY_DISCOVERY.md`](COMPANY_DISCOVERY.md).

- [x] **Discover tab on the Companies page** — the default tab now
      searches *public sources* by name/industry/city/state/CSR focus
      (`GET /api/discover/companies`). The existing CRM list moved,
      unchanged, to a "Saved leads" tab (`SavedLeadsView.jsx`).
- [x] **Provider interface** — `backend/app/company_discovery/base.py::
      CompanyDiscoveryProvider`, with three providers:
      **Wikidata** (keyless, ~3,400 Indian companies, locally indexed
      for instant filtering, refreshed weekly), **MCA company master
      data via data.gov.in** (`DATA_GOV_IN_API_KEY`), and **official
      CSV datasets** in `backend/datasets/` (NSE/BSE lists, National
      CSR Portal CSR-spend exports). A failing source is reported, not
      fatal.
- [x] **Verified / inferred / unavailable provenance** on every field,
      shown as badges with source links; merged across sources
      (ISIN/CIN/QID/domain/normalized name) preferring verified values.
- [x] **CSR focus inference** — `POST /api/discover/csr-focus` reads the
      company's own CSR pages (robots.txt honoured) for Schedule VII
      keywords and CSR/BRSR report links. Always labelled inferred, and
      explains an empty result (robots-blocked / JavaScript-only site /
      no CSR page).
- [x] **Save as lead** — `POST /api/discover/save` is the only path from
      discovery into the database. Same duplicate warning + "Save anyway"
      as manual adds. Attaches a provenance note to the lead. Lead
      scoring, AI features, notes, contacts, documents and outreach
      tracking all start from the saved row.
- [x] **Demo data is opt-in and removable** —
      `seed_demo_data.py --remove` deletes only rows matching both a demo
      name and its `*.example.com` website.

**Verified:** 61 new backend tests (`tests/test_company_discovery.py`:
matching/normalization, cross-source merging, provenance, all four
endpoints, every provider via fixtures/injected fetchers, no network) —
**179/179 passing**. Also verified live:
- The Wikidata index was built for real: 3,428 companies in ~9.5 min,
  no rate-limiting.
- Searches over real HTTP return in ~0.2s. Examples: pharma in
  Maharashtra gives Sun Pharma, Cipla, Lupin…; "TCS" resolves by alias;
  "Bangalore" matches Bengaluru.
- "Check CSR focus" was run against real company sites. Bajaj Auto gave
  Education/Skill Development/Sports/Healthcare plus its CSR report PDF.
  Infosys was correctly skipped (robots.txt 403). Cipla was correctly
  reported as JavaScript-only.
- Save as lead → 201 with lead score and provenance note; a repeat save
  returns 409; re-search flags the saved company; notes/contacts/AI
  endpoints work on it.
- UI checked in headless Chrome at desktop and 375px widths.
- `npm run build` and `oxlint` clean.

**Not verified live:** the MCA/data.gov.in provider. Only the shared
sample key was available, and it returned "Rate limit exceeded". It is
covered by fixture tests in the documented OGD response format and reads
field ids from the API's own metadata. Confirm with one name search once
a real `DATA_GOV_IN_API_KEY` is set.

## Phase 2 — CSR Contact Discovery — ✅ Complete

- [x] **CSR decision-maker search** — `backend/app/scraping.py`:
      crawls a company's own site (`/`, `/contact-us`, `/contact`,
      `/csr`, `/sustainability`, `/about/contact`) for public emails,
      phone numbers, and LinkedIn URLs. Identifiable User-Agent,
      `robots.txt` checked per path before fetching, fixed delay
      between requests, results deduped across pages.
- [x] **Source-link tracking** — every discovered candidate carries the
      `source_url` it was found on (`Contact.source_url` was already
      modeled in Phase 1).
- [x] **Save discovered contacts** — `frontend/src/components/
      DiscoverContactsPanel.jsx` on the company detail page: "Scan
      website" shows candidates, staff name each one and click "Add
      contact" to save via the existing Phase 1 contact endpoint —
      nothing is auto-saved without review.
- [x] **Duplicate detection** — `backend/app/crud.py::find_duplicate_company`
      (case-insensitive name match or normalized-website match).
      `POST /api/companies` returns `409` with the existing company's
      id/name unless `?force=true` is passed; the "Add company" form
      surfaces this as a warning with a "View existing" link and a
      "Create anyway" override. **Contact-level, added 2026-09-27:**
      `find_duplicate_contact` is the counterpart for contacts within a
      single company — case-insensitive email match checked first, then
      name (two different people can share a common name, but an email
      is the identity). `POST /api/companies/{id}/contacts` returns
      `409` with the existing contact's id/name/email unless
      `?force=true` is passed. Both entry points surface it inline with
      an "Add anyway" button: the contact form and
      `DiscoverContactsPanel.jsx`, where the warning is attached to the
      single candidate row rather than failing the whole panel, since
      re-scanning a site routinely re-surfaces people already saved.
      Deliberately scoped per company — the same professional appearing
      under two companies is legitimate, whereas the same email twice
      under one company is almost always a re-scan or a double-submit.
- [x] **Hunter.io / Apollo.io enrichment** — `backend/app/enrichment.py`:
      domain-search/people-search integrations, filtered to CSR-relevant
      titles (CSR/Sustainability/Foundation/HR/Corporate Communications).
      Gated behind `HUNTER_API_KEY`/`APOLLO_API_KEY`; `POST
      /api/companies/{id}/enrich` reports `configured: false` when
      neither key is set, surfaced in the UI rather than silently
      returning nothing. Same `DiscoverContactsPanel.jsx` UI as
      scraping.

**Verified:** 25 new backend pytest cases (12 discovery-endpoint tests,
7 scraping unit tests, 6 enrichment unit tests — 38 total for the
backend now) — all passing. The scraper was also run against a live,
locally-hosted test site with real contact content on one page and a
`robots.txt` `Disallow` rule on another, confirming the disallowed page
was genuinely skipped (not just coincidentally empty) while the allowed
pages' emails/phone/LinkedIn were correctly extracted. Duplicate
detection, scrape, and enrich were all exercised over real HTTP through
the dev proxy. `npm run build` and `oxlint` clean on the frontend.

**Gap closed (2026-10-15): CSR Contact Discovery.** The scraper above
found emails/phones/LinkedIn links but **no names or designations**, kept
mobile numbers, and read only six fixed paths. Now **Find contacts**
finds named decision makers in the spec's target roles from public
sources, with per-field provenance. Full design, sources, rules and
limits: [`CONTACT_DISCOVERY.md`](CONTACT_DISCOVERY.md).

- [x] **Find contacts button + panel** on each Discover result (company
      not yet saved), each Saved-leads row and the company detail page.
      `ContactDiscoveryPanel.jsx` groups contacts by priority, with
      per-row Save, Save selected, "already saved" flags and
      duplicate/"Save anyway". Replaces the old Scan website / Enrich card;
      both capabilities are inside the new panel.
- [x] **Target roles in 3 priority tiers** (`contact_discovery/roles.py`):
      CSR/Sustainability/ESG/Foundation/CSR Committee/CSR Team →
      HR/Corporate Communications/PR/Corporate Affairs → Regional/Branch/
      General Manager/BU/Operations heads.
- [x] **Sources:**
      - the company's own pages, crawled by hint and ranked: committee,
        CSR, leadership, contact, press (capped)
      - opt-in CSR/annual-report/BRSR PDF reading for the CSR Committee
      - Hunter/Apollo when configured
      - LinkedIn/web search *links* for staff (never fetched)
- [x] **Extraction** (`contact_discovery/extract.py`, `reports.py`):
      JSON-LD Person, name/title cards, inline titles, CSR Committee
      tables (other committees excluded), press quotes, role mailboxes,
      and the numbered-list / attendance-table / annexure layouts of real
      annual reports.
- [x] **Every field Verified / Inferred / Unavailable**, plus a 10–95%
      confidence score with reasons.
- [x] **Work-info-only rules** (`contact_discovery/policy.py`), applied on
      search *and* save: on-domain emails only, never free-mail; Indian
      mobiles and anything labelled mobile/WhatsApp dropped; phones from
      third parties dropped; LinkedIn never fetched.
- [x] **robots.txt fetched with our own User-Agent** (RFC 9309, erring
      towards not crawling). Python's `RobotFileParser.read()` sends
      `Python-urllib`, which Tata Steel, Mahindra and Thermax answer with
      403, so it wrongly treated their whole sites as disallowed.
- [x] **Save one or many** (`POST /api/contact-discovery/save`). Saving
      for an unsaved company saves the lead first, or attaches to the
      existing one. Duplicates are matched per company by email, then
      LinkedIn, then name.
- [x] **Contact profile** (`/contacts/:id`): fields with badges, View
      source, LinkedIn (or LinkedIn search), all source pages, per-contact
      notes, per-contact activity timeline, and Generate Email with the
      contact preselected.
- [x] **Contacts page** (`/contacts`): search all saved contacts by
      company, name, designation (or role category), industry, state,
      city and priority.
- [x] **Database:**
      - new columns on `contacts`
      - new `contact_sources` and `contact_discovery_logs` tables
      - nullable `contact_id` on `notes` / `activity_logs`
      - existing databases gain the new columns automatically at startup
        (`schema_upgrade.py`, nullable columns only)

**Verified:** 96 new backend tests (`tests/test_contact_discovery.py`,
no network) → **275/275 passing**. Also checked live against real company
sites:
- **Mphasis:** 4-member CSR Committee, the Head – CSR, the SVP & Head of
  CSR/ESG and the CHRO, from its own CSR-team and leadership pages.
- **Thermax:** its 2025-26 annual report found and ranked first, 235 pages
  read in about 60s, all 3 CSR Committee members cited to pages 74 and 106.
- **Mahindra:** EVP Group Public Affairs and Group CHRO.
- **Wipro:** CSR Committee chair, CHRO and COO.
- **Tata Steel:** CSR Committee chair.
- **Bajaj Auto and Asian Paints:** csr@ mailbox plus office lines, with
  the mobile numbers on the same pages dropped.
- **Godrej Industries and Kirloskar:** robots.txt answers 403/503, so
  they were skipped with an explanation.

Running against real sites found and fixed ten issues before release:
- false robots blocks
- press pages bypassing the cap
- article teasers read as people
- biography cities labelled as verified office locations
- overseas office numbers chosen for Indian companies
- the wrong report PDF chosen
- annual-report layouts not parsed
- office-address cards read as people
- foreign numbers without a `+` code taken as Indian
- Bengaluru/Ahmedabad landlines (area codes 80/79) dropped as mobiles

API flow checked end to end over HTTP against a copy of the existing dev
database, which upgraded in place: discover an unsaved company → save 2
contacts (lead auto-created) → re-search flags them → profile, notes,
timeline, search, logs. UI checked in headless Chrome at 1400px and
375px (no horizontal overflow). `npm run build` and `oxlint` clean.

## Phase 3 — AI Features — ✅ Complete

Provider decision (made explicitly with the user, not drifted into):
**Google Gemini**, and lead scoring is a **deterministic formula +
LLM-written explanation** — the 0-100 number is fixed/auditable
(`backend/app/scoring.py`), the LLM only writes the human-readable
"why" text. All AI calls are optional: every endpoint reports
`configured: false` when `GEMINI_API_KEY` isn't set rather than
erroring, same pattern as Hunter/Apollo in Phase 2.

- [x] **AI lead scoring** — `backend/app/scoring.py::compute_lead_score`:
      0-100 score from CSR-focus match (0-40), CSR spending (0-30),
      location match with the NGO's own city/state (0-15), and company
      size (0-15) — factors from `docs/PROJECT_OVERVIEW.md` that map to
      data actually on the `Company` record. Returned inline on every
      `GET/POST/PATCH /api/companies...` response (list and detail) —
      no configuration or extra request needed, matching "should
      automatically appear on every company profile."
- [x] **Lead priority labels** — High (≥70) / Medium (≥40) / Low,
      derived from the score, shown as a colored badge on both the
      company list and detail page.
- [x] **Score explanation** — `POST /api/companies/{id}/score/explain`:
      Gemini writes 2-3 plain-language bullets from the score
      breakdown. Lazy (on-demand "Why?" click), not fetched
      automatically, to avoid an LLM call on every page load.
- [x] **AI email generator** — `POST /api/companies/{id}/generate-email`:
      First Outreach / Follow-up / Meeting Request / Thank You variants,
      optionally personalized to a specific contact. Draft-only per the
      plan's rule — the UI has Generate/Regenerate/Copy buttons and an
      editable subject/body, no send action exists anywhere in the app.
- [x] **AI Company Summary** — `POST /api/companies/{id}/summary`:
      business overview, CSR initiatives, NGO-fit, talking points.
- [x] **AI Meeting Brief** — `POST /api/companies/{id}/meeting-brief`:
      background, likely priorities, discussion points, questions,
      collaboration ideas — includes the company's saved notes as
      context.

**Verified:** 26 new backend pytest cases (scoring formula unit tests,
`app/ai.py` prompt/parsing unit tests with mocked Gemini responses,
router tests for all 4 AI endpoints including the "not configured"
path — 64 total for the backend now) — all passing. Also called the
real Gemini API once with a deliberately invalid key to confirm the
request reaches Google's endpoint and a failure is caught and returned
as `None` rather than crashing (no valid `GEMINI_API_KEY` was available
to test an actual successful generation — that path is covered by the
mocked unit/router tests instead). Full create-company → lead-score →
explain/generate-email/summary/meeting-brief (all correctly reporting
`configured: false`) workflow replayed over real HTTP through the dev
proxy. `npm run build` and `oxlint` clean on the frontend.

**Known gap:** "Previous CSR activities" (the *target* company's own
CSR track record) was in the original factor list but isn't scored —
no structured data source for that is integrated (would need e.g. Form
CSR-2 filings or annual reports), so it's left out rather than faked.

## Phase 4 — Outreach Tracking — ✅ Complete

- [x] **Dashboard view with headline KPI tiles** — `GET /api/dashboard`
      (`backend/app/routers/dashboard.py`) returns Total Companies,
      Companies Contacted, Replies Received, Meetings Scheduled,
      Proposals Sent, and Successful Partnerships in one call, rendered
      on `frontend/src/pages/DashboardPage.jsx` (now the app's landing
      page, `/`). KPIs beyond "current status" use a documented ordered
      reading of the `LeadStatus` pipeline (`crud.py`'s
      `_REPLIED_OR_LATER`/`_MEETING_OR_LATER`/`_PROPOSAL_OR_LATER`) so a
      company at e.g. "Proposal Sent" still counts toward "Meetings
      Scheduled" — a lighter-weight substitute for full historical
      funnel tracking, deliberately chosen over adding more schema.
- [x] **Follow-up section** — same endpoint buckets every company with a
      `follow_up_date` into Overdue / Due Today / Upcoming
      (`crud.py::get_follow_ups`), excluding closed-out leads
      (Successful / Not Interested) since a reminder on a closed deal
      isn't actionable. Shown as three columns on the dashboard.
- [x] **Recent-activity feed** — new `ActivityLog` model
      (`backend/app/models.py`), written as a side effect of
      `crud.py`'s create/update functions (company added, contact
      added/updated, note added, status changed) and of a successful AI
      email generation (`routers/ai.py`). `GET /api/dashboard` returns
      the latest 20 system-wide, newest first; cascade-deletes with its
      company.
- [x] **CSV import/export** — `GET /api/companies/export` (respects the
      same filters as the company list) and `POST
      /api/companies/import` (`backend/app/routers/companies.py`,
      `crud.py::import_companies_from_rows`) on the Companies page.
      Import skips name/website duplicates via the existing
      `find_duplicate_company` check and reports per-row errors
      (missing name, unparseable numbers) rather than failing the whole
      upload.

**Verified:** 10 new backend pytest cases (KPI-pipeline math, follow-up
bucketing incl. today's real date via `date.today()`, activity-feed
ordering and cascade-delete, CSV export/import incl. duplicate-skip and
bad-row reporting, activity logging on email generation — 74 total for
the backend now) — all passing. Also exercised live against the real
dev stack (Vite proxy → FastAPI → SQLite): seeded companies across
different statuses/follow-up dates, confirmed dashboard KPIs/follow-up
buckets/activity feed, CSV export, and CSV import (create + duplicate
skip + bad-row report) all return correct results over HTTP matching
what the UI calls. `npm run build` and `oxlint` clean on the frontend.

## Phase 5 — MVP+ Features — ✅ Complete

- [x] **NGO Profile** — new single-row `NGOProfile` model
      (`backend/app/models.py`), replacing the env-only `NGO_*` settings
      as the thing NGO staff actually edit. `GET/PATCH /api/ngo-profile`
      (`routers/ngo_profile.py`); `frontend/src/pages/NGOProfilePage.jsx`
      (`/ngo-profile`, linked from the nav). Seeded from the existing env
      defaults on first access; every read/write mirrors the row onto
      the live `settings` object (`crud.py`'s
      `_sync_settings_from_ngo_profile`) so `scoring.py`'s
      location/focus match and `ai.py`'s generated content pick up edits
      immediately, without threading a db session through either module.
      Re-synced from the DB on app startup so edits survive a restart.
- [x] **Tags** — new `Tag` model + `company_tags` association table
      (many-to-many, reusable across companies). `GET/POST /api/tags`,
      `DELETE /api/tags/{id}` (`routers/tags.py`); attach/detach via
      `POST/DELETE /api/companies/{id}/tags[/​{tag_id}]`
      (`routers/companies.py`), get-or-create by case-insensitive name
      so re-adding "education" reuses "Education" rather than
      duplicating. `search_companies` gained a `tag` filter, surfaced as
      a dropdown in `CompanyFilters.jsx`; tags shown as chips on both
      the company list and detail page (`TagsSection.jsx`).
- [x] **Document storage** — new `Document` model, file bytes stored
      directly in Postgres (`LargeBinary`, deferred-loaded so listing
      documents doesn't pull file contents into memory) rather than
      standing up separate file-storage infra. `POST
      /{company_id}/documents` (upload), `GET /api/documents/{id}`
      (download, streamed), `DELETE /api/documents/{id}`
      (`routers/documents.py`); `DocumentsSection.jsx` on the company
      detail page.
- [x] **Proposal Tracker** — new `Proposal` model with its own stage
      enum (Requested → Drafting → Sent → Approved/Rejected), separate
      from the company's overall lead `status` since a company can have
      several proposals over time. `POST /{company_id}/proposals`,
      `PATCH/DELETE /api/proposals/{id}` (`routers/proposals.py`);
      `ProposalsSection.jsx` (add + inline stage dropdown) on the
      company detail page. Stage changes are activity-logged.
- [x] **Activity Timeline** — `CompanyDetail` now embeds that company's
      own `activity_logs` (full history, not just the dashboard's
      system-wide latest-20), rendered as `ActivityTimeline.jsx` on the
      company detail page. Fixed a same-second ordering bug found while
      verifying this live: SQLite/Postgres `created_at` ties (multiple
      events in the same second, common when several actions fire back
      to back) weren't deterministically newest-first without a
      secondary `id DESC` sort key - added to both the `ActivityLog`
      relationship ordering and `crud.get_recent_activity`.

**Verified:** 21 new backend pytest cases (tags incl. case-insensitive
reuse and company filtering, document upload/download/delete incl.
cascade-delete with the company, proposal CRUD and stage-change activity
logging, NGO profile seed/update/settings-sync incl. its effect on live
lead scoring — 95 total for the backend now) — all passing. Also
exercised live against the real dev stack (Vite proxy → FastAPI →
SQLite): tag create/attach/detach/filter, document upload+download with
byte-for-byte content verification, proposal stage transitions, and NGO
profile edits changing a newly-created company's lead score, all
confirmed over real HTTP. `npm run build` and `oxlint` clean on the
frontend.

## Phase 5b — Email Automation — ✅ Built (Gmail not live-tested)

Added 2026-10-15. Full design, setup, APIs and limits:
[`EMAIL_AUTOMATION.md`](EMAIL_AUTOMATION.md). The outreach flow no longer
stops at a copy-only draft: generate → review → **manually approve and
send** → track replies → AI classification → follow-ups → dashboard.

- [x] **Manual approval only.** `POST /api/emails/{id}/send` is the single
      sending path. It needs `confirm: true` plus the exact recipient,
      subject and body the person reviewed. The UI's "Review & send" step
      shows the sending account and recipient before "Confirm & send".
      Background work only reads mail and creates drafts.
- [x] **Provider abstraction** (`backend/app/mail/providers/`): Gmail via
      OAuth 2.0 and the Gmail REST API (`gmail.send` + `gmail.readonly`).
      Outlook can be added as another `EmailProvider`.
- [x] **Secure token storage:** Fernet-encrypted with `TOKEN_ENCRYPTION_KEY`,
      never returned by the API; HMAC-signed OAuth state; revoke on
      disconnect; optional `APP_ACCESS_TOKEN` guarding connect / send /
      sync, since the app has no login.
- [x] **Drafting:** Gemini or editable default templates (sender name and
      signature from Settings), edit, save draft, duplicate, follow-up
      in the same thread. The old copy-only generator gained "Save as draft".
- [x] **Safeguards:** recipients must be the company's saved contacts;
      hourly send cap (`MAX_EMAILS_PER_HOUR`); sent emails can't be edited
      or deleted.
- [x] **Tracking:** Draft / Sent / Failed (send error or bounce); replies
      and mail sent from Gmail directly are recorded; conversation outcomes
      No Reply → Replied → Positive / Neutral / Negative / Needs Follow-up →
      Meeting Requested / Scheduled → Proposal Requested / Sent →
      Partnership Confirmed / Closed. Outcomes move the company's lead
      status forward only.
- [x] **AI reply classification** (classification, confidence, reasoning,
      meeting/proposal intent) with a keyword fallback when Gemini isn't
      configured, and manual override keeping the history.
- [x] **Follow-ups:** 3/7/14/30 days (configurable) or a date; due ones
      become drafts for approval; cancelled automatically when a reply
      arrives. **Meetings** with date, place and status.
- [x] **Timeline:** email generated, draft saved, sent, reply received,
      meeting scheduled, proposal sent and status updates on both the
      company and contact timelines (existing `activity_logs`).
- [x] **Dashboard:** outreach metrics (companies, leads, contacts,
      emails generated/sent, replies, positive/negative, meetings,
      proposals, partnerships, pending/overdue follow-ups, reply /
      positive-reply / conversion rates) and the New → Lost pipeline.
      Existing dashboard fields kept.
- [x] **UI:** Emails page (drafts, sent, replies, follow-ups, meetings,
      "Check for replies"), Settings page (Gmail, access token, sender,
      signature, intervals, templates), emails section on company and
      contact pages.
- [x] **Database:** new tables `email_accounts`, `email_settings`,
      `email_templates`, `email_threads`, `emails`, `email_events`,
      `reply_classifications`, `followups`, `meetings`; created on startup.

**Verified:** 37 new backend tests (`tests/test_email_automation.py`, a
fake provider, no network) → **312/312 passing**. Full browser
click-through on the real app and a copy of the dev database with only
Gmail faked: generate → review → confirm & send (exactly one send, only
after confirmation) → simulated reply → "Check for replies" →
classification → lead status Meeting → dashboard metrics. Checked at
1400px and 375px with no horizontal overflow. `npm run build` and
`oxlint` clean.

**Not verified:** a real Gmail account. No Google OAuth client was
available. After setting `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` /
`TOKEN_ENCRYPTION_KEY`, connect Gmail in Settings and send one test email
to your own address, reply to it, then click "Check for replies".

## Phase 6 — Final Testing & Deployment — 🟡 In progress

- [x] **Expand automated tests** — added `backend/tests/test_validation.py`
      (12 new cases): negative-number rejection on company/proposal
      numeric fields, pagination bounds (`skip`/`limit` now validated,
      `limit` capped at 500), oversized-upload rejection (documents and
      CSV import), a CSV row with a validation error now reported as a
      per-row error instead of 500ing the whole import, empty-CSV
      handling, and invalid-enum rejection on `status`. 107/107 backend
      tests passing (up from 95).
- [x] **Hardening found via this testing** — three real gaps fixed, not
      just tested around: (1) `CompanyCreate`/`CompanyUpdate`/
      `ProposalCreate`/`ProposalUpdate` had no lower bound on
      `csr_spending`/`revenue`/`employee_count`/`amount`, so a bad CSV
      row or typo could silently store negative values that would
      corrupt lead scoring — added `ge=0` validation
      (`backend/app/schemas.py`); (2) document upload and CSV import had
      no size limit, so one oversized file could be stored unbounded in
      Postgres or exhaust the free-tier backend's memory — added
      `MAX_DOCUMENT_UPLOAD_BYTES` (10 MB) / `MAX_CSV_IMPORT_BYTES` (5 MB)
      caps returning `413`; (3) `GET /api/companies`'s `limit` was
      unbounded, so a client could request an arbitrarily large page —
      capped at 500.
- [x] **Test with real company data at larger volume** —
      `backend/scripts/load_test.py` seeds 3,000 companies (varied
      industries/cities/statuses, contacts/notes/tags) and times the
      actual endpoints the UI calls. Run once during this phase: default
      list ~184ms, filtered/tag/paginated queries 15-25ms, full CSV
      export of all 3,000 rows ~218ms, dashboard ~22ms, single company
      detail ~16ms — nothing pathological at this volume. **Caveat:**
      run against SQLite (no live Postgres instance available in this
      environment); re-run against the real Postgres target before
      treating these numbers as production guidance.
- [x] **Demo/seed data** — `backend/scripts/seed_demo_data.py`: ten
      realistic Indian companies across industries/states with a few
      contacts and tags, for demoing the app or running UAT sessions.
      Safe to re-run (skips companies that already exist via the same
      duplicate-detection path the API uses). These companies are
      fictional (`*.example.com` websites) and are for demos only. Real
      companies come from the Discover tab, and `--remove` (added
      2026-10-15) clears the demo rows from a database in real use.
- [ ] **Test with actual NGO staff; simplify confusing screens** — not
      done. This needs real NGO staff using the *deployed* app, which
      hasn't happened. [`UAT_CHECKLIST.md`](UAT_CHECKLIST.md) has the
      specific tasks/observations to run through when it does — don't
      mark this done until that session has actually happened.
- [ ] **Deploy** — not done; deployment is prepared, not executed. Added
      `render.yaml` (backend Blueprint), `frontend/vercel.json` (SPA
      rewrite so client-side routes survive a hard refresh), and
      `frontend/src/api/client.js` now reads `VITE_API_BASE_URL` (falls
      back to the existing relative `/api` path, so local dev is
      unaffected) so the frontend can call a separately-hosted backend
      in production. Full step-by-step in
      [`DEPLOYMENT.md`](DEPLOYMENT.md) and
      [`PRE_DEPLOYMENT_CHECKLIST.md`](PRE_DEPLOYMENT_CHECKLIST.md) —
      executing it needs the user's own Neon/Render/Vercel accounts and
      credentials.
- [x] **Write a one-page user guide for non-technical staff** —
      [`USER_GUIDE.md`](USER_GUIDE.md).

**Verified:** `pytest -q` → 110/110 passing. `npm run build` and
`npm run lint` (oxlint) clean on the frontend after the `client.js`
change. `backend/scripts/seed_demo_data.py` and `load_test.py` both run
end-to-end (against a scratch SQLite database, cleaned up afterward —
no changes to any real database).

**Full-phase re-verification (2026-09-26):** every phase was re-exercised
against a live backend over real HTTP (not just through the pytest
dependency override) — 54 endpoint-level checks covering Phase 1 CRUD/
search, Phase 2 duplicate-detection/scrape/enrich, Phase 3 scoring and
all four AI endpoints, Phase 4 dashboard/follow-ups/activity/CSV, Phase 5
tags/documents/proposals/NGO-profile/timeline, and Phase 6's validation
caps. The frontend was re-checked too: `npm run build` + `oxlint` clean,
every path in `src/api/client.js` maps to a real backend route, and every
field the Dashboard and Company Detail pages read exists in the live
payloads. Three defects were found and fixed — see the 2026-09-26 (3)
entry in [`CHANGELOG.md`](CHANGELOG.md):

- CSV export → import silently dropped `status`, `last_contacted_date`
  and `follow_up_date` (the export writes them; `CompanyCreate` had no
  such fields, so re-importing an edited export reset every company to
  "New"). Now round-trips intact.
- `POST /api/companies` silently swallowed an invalid `status` and stored
  "New" instead of rejecting it; now `422`.
- `scripts/seed_demo_data.py` crashed on a fresh database (no table
  creation) — the exact case its docstring advertises. Now creates
  tables first.

The load-test numbers below were also re-confirmed on the current code
(3,000 companies: default list 43ms, filters 18-24ms, full CSV export
237ms, dashboard 24ms).

**Update (2026-09-27):** two gaps against the spec closed since the
re-verification above — the company `csr_report_url` field (Phase 1's
profile page) and contact-level duplicate detection (Phase 2). 6 new
backend tests covering both; `pytest -q` → **116/116 passing**. Phase 6's
two open items are unchanged: executing the deploy and running the
NGO-staff UAT session both still need the user's own hosting accounts and
real users, so this phase stays 🟡.

---

## Near-Term Engineering Tasks

- [x] Add pagination controls to the company list UI (backend already
      supports `skip`/`limit`) — done 2026-09-25.
- [ ] Consider Alembic migrations once the schema needs to evolve after
      real data exists (Phase 1 uses `Base.metadata.create_all` for
      simplicity, matching the "avoid infra complexity" principle).
- [ ] Decide on auth before this goes anywhere multi-user (Phase 1 has
      none — fine for a single NGO's internal tool for now).
- [x] ~~Scraper title/name extraction is heuristic-free~~. Done
      2026-10-15: contact discovery extracts named people and
      designations (structured data, cards, inline titles, committee
      tables, report PDFs). See [`CONTACT_DISCOVERY.md`](CONTACT_DISCOVERY.md).
- [ ] Point "Check CSR focus" (`company_discovery/csr_focus.py`) at
      `contact_discovery.service.load_robots`. It still uses
      `scraping._load_robots`, whose `Python-urllib` fetch gets 403 from
      some corporate sites and is then treated as "disallow all". This was
      left unchanged so company discovery's behaviour didn't shift.

See [`ROADMAP.md`](ROADMAP.md) for how these fit into upcoming phases and
[`CHANGELOG.md`](CHANGELOG.md) for what's already shipped.
