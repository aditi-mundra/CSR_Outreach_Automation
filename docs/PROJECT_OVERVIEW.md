# CSR Lead Generation Platform — Project Overview

> Merged from `PROJECT_OVERVIEW_V1.md` (Simple Project Roadmap) and
> `PROJECT_OVERVIEW_V2.md` (MVP+ Roadmap). This is the combined, canonical
> description of what the product is meant to do. See the note on
> **actual implementation** at the bottom for how the shipped code
> currently differs from this plan.

## Project Goal

Build a simple web application that helps NGO staff:

- Find companies suitable for CSR outreach
- Identify relevant CSR decision-makers
- Save useful contact information
- Prioritize the best leads
- Generate personalized outreach emails
- Track communication and follow-ups

The application should be easy enough for non-technical users to operate
without training. It should feel closer to a simple CRM than a technical
analytics platform.

---

## Core Features (MVP)

### 1. Company Search

Allow NGO staff to quickly find companies that may be suitable for CSR
partnerships.

**Search filters** (simple): Company Name, Industry, State, City, CSR
Focus Area, CSR Spending Range.
**Optional filters:** Revenue, Employee Count.

**Each result displays:** Company Name, Industry, Location, Website, CSR
Focus, CSR Spending (if available), Lead Score, View Details button.

**Data sources:** company websites, CSR reports, MCA/public company data,
NSE/BSE company information, publicly available corporate reports.

**Flow:** select filters → click Search → view matching companies → open
a company → save it as a lead.

### 2. CSR Decision Maker Finder

Help NGO staff identify the right person to contact inside a company.

**Target roles:** CSR Head, Sustainability Head, Foundation Director, HR
Head, Corporate Communications Head.

**Information shown (when available):** Person Name, Designation,
Company, Official Work Email, Company Phone Number, LinkedIn Profile,
Source Link.

**Public sources:** company CSR pages, leadership pages, annual reports,
sustainability reports, press releases, public professional profiles.

**Important rule:** only save publicly available professional
information. Do not collect private phone numbers, personal email
addresses, or hidden/restricted information.

**Flow:** open a company → click "Find CSR Contacts" → system displays
the best publicly available contacts.

### 3. Contact Database

One simple place for the NGO to manage all company and contact
information.

- **Company:** Name, Industry, City, State, Website, CSR Focus
- **Contact:** Name, Designation, Official Email, Company Phone,
  LinkedIn, Source URL
- **Outreach info:** Last Contacted Date, Current Status, Follow-up Date,
  Notes

**Actions:** add / edit / delete / search contact, add notes, export
contacts to CSV.

**Layout:** avoid complex tables — keep it simple: Company → Contact →
Status → Notes.

### 4. AI Lead Scoring

Help NGO staff understand which companies should be contacted first,
with no configuration required from the user — the score appears
automatically on every company profile.

**Factors:** match with NGO focus area, company CSR spending, company
location, previous CSR activities, company size.

**Output:** a simple score (e.g. "Lead Score: 87/100") plus a short
explanation (e.g. strong match with NGO focus, active CSR programs,
relevant geographic presence, good CSR spending).

**Priority labels:** High / Medium / Low Priority.

### 5. AI Email Generator

Help NGO staff create professional CSR outreach emails quickly.

**Inputs (auto-filled):** NGO Name, NGO Work Area, Company Name, Contact
Name, Contact Designation, Company's CSR Focus.

**Email types:** First Outreach, Follow-up, Meeting Request, Thank You.

**Output:** Subject Line + personalized email body.

**Actions:** Generate Email, Regenerate, Copy Email; optionally edit
before copying.

**Important rule:** the system generates draft emails only — NGO staff
must review before sending.

### 6. Outreach Dashboard

A simple overview of all CSR outreach activity.

**Headline numbers:** Total Companies, Companies Contacted, Replies
Received, Meetings Scheduled, Proposals Sent, Successful Partnerships.

**Lead status stages:** New → Contacted → Follow-up → Meeting → Proposal
Sent → Successful / Not Interested.

**Follow-up section:** Company, Contact Person, Follow-up Date, Status —
with overdue follow-ups highlighted.

**Recent activity feed:** email drafted, contact updated, follow-up
completed, meeting scheduled, proposal sent.

---

## Extended / High-Value Features (MVP+)

Added in the V2 plan on top of the six core features above:

- **NGO Profile** — store NGO name, mission, focus areas and contact
  details once; reuse automatically in AI-generated emails.
- **Company Profile page** — Overview, CSR focus, CSR report link,
  Contacts, Lead score, Notes, Uploaded documents.
- **Company Notes** — rich notes for meetings, calls and discussions.
- **Document Storage** — upload proposals, CSR reports, MoUs, meeting
  minutes and receipts per company.
- **Follow-up Reminders** — dashboard section for Due Today / Upcoming /
  Overdue.
- **Tags** — e.g. Education, Healthcare, Environment, High Priority,
  Pune.
- **Proposal Tracker** — stages: Requested → Drafting → Sent → Approved
  / Rejected.
- **Activity Timeline** — auto-recorded events: company added, contact
  added, email generated, proposal uploaded, status changed.
- **Duplicate Detection** — warn on duplicate companies, contacts or
  emails.
- **AI Company Summary** — business overview, CSR initiatives, CSR
  focus, NGO compatibility, key talking points.
- **AI Meeting Brief** — company background, past CSR work, suggested
  discussion points, questions to ask, collaboration ideas.
- **CSV Import & Export** — import existing NGO Excel/CSV data, export
  filtered results.

---

## Application Screens

1. **Dashboard** — outreach summary, follow-ups, recent activity.
2. **Companies** — search, filters, company results, lead scores.
3. **Company Details** — company info, CSR info, decision makers, lead
   score, notes, Generate Email button.
4. **Contacts** — saved contacts, search, status, follow-up date.
5. **Outreach** — all leads, current stage, follow-ups, notes.

## End-to-End User Workflow

1. Search for companies
2. Open a relevant company / company profile
3. Find CSR decision-makers
4. Save the company and contact
5. Read AI company summary
6. Check the AI lead score
7. Generate a personalized outreach email
8. Upload proposal/documents
9. Contact the company
10. Update the outreach status and track the proposal
11. Add a follow-up date
12. Monitor progress from the dashboard

---

## Recommended Technical Approach (planning docs)

Keep the infrastructure as simple as possible.

| Layer     | Choice                                   |
|-----------|-------------------------------------------|
| Frontend  | React + Tailwind CSS                      |
| Backend   | FastAPI                                   |
| Database  | PostgreSQL                                |
| AI        | Gemini API or OpenAI API                  |
| Hosting   | Vercel (frontend), Render/Railway (backend), Neon/Supabase (Postgres) |

Avoid unnecessary infrastructure: Docker, Kubernetes, CI/CD pipelines,
microservices, complex cloud architecture, authentication complexity
beyond what's needed. Priority is reliability and ease of use over
infrastructure complexity.

## Design Principle

Every major action should require as few clicks as possible.

**Prefer:** clear buttons, simple language, large search boxes, dropdown
filters, automatic AI results, minimal forms, mobile-friendly pages.

**Avoid:** technical terminology, complicated settings, too many
dashboards, large forms, hidden features, unnecessary configuration.

---

## Note on Actual Implementation (as of 2026-09-25)

The product targets a specific NGO ("A Ray of Hope Foundation", based in
Pune) rather than a generic multi-NGO platform. The **active**
implementation now follows the plan's recommended stack literally:

| Layer     | Choice                                   |
|-----------|-------------------------------------------|
| Frontend  | React + Tailwind (Vite) — `frontend/`      |
| Backend   | FastAPI — `backend/app/`                   |
| Database  | PostgreSQL (SQLAlchemy) — `backend/app/models.py` |

Phase 1 (core application: company search, profile page, contact
database, notes/status tracking) is complete on this stack — see
[`TASKS.md`](TASKS.md) for verification details and
[`ROADMAP.md`](ROADMAP.md) for what's next.

**Company Search data sources (2026-10-15).** Company search now finds
real companies from public sources (Wikidata, MCA company master data
via data.gov.in, and official CSV downloads such as NSE/BSE lists and
National CSR Portal exports) instead of only the NGO's own saved
records. Every value is labelled verified / inferred / unavailable, and
companies enter the database only via "Save as lead". See
[`COMPANY_DISCOVERY.md`](COMPANY_DISCOVERY.md).

**CSR Decision Maker Finder (2026-10-15).** The "Find CSR Contacts" flow
above is built as **Find contacts**, available on discovered companies,
saved leads and the company page. It extends the target roles into three
priority tiers (adding ESG, CSR Committee, PR, Corporate Affairs and
regional/operations heads).
- **Sources:** the company's own pages, CSR/annual-report/BRSR PDFs, and
  optional Hunter/Apollo.
- **Fields:** each one is labelled verified / inferred / unavailable,
  plus a confidence score.
- **Work details only,** enforced in code.
- **Saved contacts** get a profile (notes, activity timeline, Generate
  Email) and a cross-company Contacts search.

See [`CONTACT_DISCOVERY.md`](CONTACT_DISCOVERY.md).

An earlier prototype (Streamlit + SQLite, plus a CSR-1/80G/12A
compliance engine not in either original overview doc) lives in
`legacy-streamlit-prototype/` (kept locally, no longer tracked in git) for
reference. **It is superseded and does not count toward any phase's
completion** — all current and future phase work targets `backend/` and
`frontend/` only.
