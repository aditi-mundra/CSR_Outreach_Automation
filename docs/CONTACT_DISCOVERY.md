# CSR Contact Discovery

How **Find contacts** finds the publicly listed people to approach for
CSR at a company, where each detail comes from, what it will never
collect, and its limits.

## Why this exists

Phase 2's "Scan website" read six fixed paths on a company's site and
returned raw emails, phone numbers and LinkedIn links, with **no names or
designations**. Staff had to type a name for each one, and it kept any
phone number it saw, mobile numbers included. The spec's CSR Decision
Maker Finder asks for named people in specific roles (CSR Head,
Sustainability Head, Foundation Director, HR, Corporate Communications)
with name, designation, work email, company phone, LinkedIn and source.

## Workflow

```
Discover company ─┬─> Save as lead (optional) ─┐
                  └────────────────────────────┴─> Find contacts ─> select ─> Save ─> Generate Email
```

**Find contacts** is on:

| Where | Company state |
|---|---|
| Each **Discover companies** result | Not saved yet. Saving the first contact also saves the company as a lead (with the usual provenance note), or attaches it to the matching existing lead. |
| Each **Saved leads** row | Saved lead |
| **Company detail** page, in the CSR contacts card | Saved lead |

The panel searches, then shows contacts grouped by priority. Each has a
checkbox, **Save contact**, and **Save selected (n)** at the top.
Contacts already saved for that company show "✓ Saved · Open profile";
a likely duplicate gets the usual "Already saved as … / Save anyway".

## Target roles and priority

`backend/app/contact_discovery/roles.py`. A title counts only when it
pairs a role *area* with a person-level role *word* ("Head", "Manager",
"Officer", "Director", "Chairperson", …). So "CSR Policy", "HR
Solutions", "Our CSR Team" or a bare "CSR Committee" heading never
becomes a person.

| Priority | Roles |
|---|---|
| **1 · CSR & Sustainability** | CSR Head / Manager, Sustainability Head, ESG Head, Foundation Director, CSR Committee (chair/members), CSR Team (csr@ mailbox), BRSR responsible authority |
| **2 · HR & Communications** | HR Director / Manager, Corporate Communications, Public Relations, Corporate Affairs (also HR / corporate-communications mailboxes) |
| **3 · Regional & Operations** | Regional / Zonal Manager, Branch Manager, General Manager, Business Unit Head, Operations Head |

Priority 1 is checked first, so "GM – CSR" is a CSR Head, not a General
Manager. Interns, trainees and recruiters are excluded.

## Data sources

| Source | What it gives | When |
|---|---|---|
| **Company website** | Leadership / team / board pages, CSR & sustainability pages, CSR Committee pages, contact pages, up to 2 press pages | Always, when a website is known |
| **CSR / annual report PDF** | CSR Committee composition (Annual Report on CSR, Corporate Governance Report) and the BRSR "highest authority responsible" for business-responsibility policies | Opt-in: **Also scan CSR report (slower)** |
| **Hunter.io / Apollo.io** | People at the company's domain with titles, work emails, LinkedIn | Only when `HUNTER_API_KEY` / `APOLLO_API_KEY` are set (the existing Phase 2 integration) |
| **Search links** | LinkedIn people searches, a web search for the CSR Committee, the National CSR Portal | Always shown. These are links staff open themselves; the app never fetches them. |

### How the website is read

`backend/app/contact_discovery/service.py`:

- **Home page first**, then in-site links ranked: CSR committee →
  CSR / sustainability / foundation / ESG → leadership / board / team →
  contact → press (max 2) → about / governance.
- A link is judged by its **own path segment and short anchor text**,
  not the whole path. So `/sustainability/services/<product>` and
  `/client-success/…-payments-foundation-…` articles are skipped, and
  deeper pages wait behind shallower ones.
- If the home page is a JavaScript shell or links nowhere useful, common
  paths are tried (`/csr`, `/leadership`, `/board-of-directors`,
  `/contact-us`, …).
- **Caps:** 12 pages, 45 seconds, 1s pause between requests, the
  company's own domain only.
- Results are cached for 10 minutes. **Search again** bypasses the cache.

### How people are extracted

`backend/app/contact_discovery/extract.py`. The page is flattened into
lines (one per block element, one per table row), and people are found
by:

| Method | Example |
|---|---|
| Structured data | schema.org `Person` with `jobTitle` in JSON-LD |
| Listing | a name line next to a title line: the usual leadership card |
| Inline | "Priya Sharma, Head – CSR" · "Head CSR: Priya Sharma" |
| Committee | rows of a CSR Committee table or list, only inside a section headed CSR Committee; it ends at the next Audit / Risk / Nomination … committee heading |
| Prose | "…said Sunil Mehta, Head of Foundation Initiatives, at…" (lower confidence) |

Work emails, LinkedIn links, office phones and a city are attached only
from the lines of that person's own block (up to the next person).

### How reports are read

`backend/app/contact_discovery/reports.py`, needs `pypdf`.

- **Report order:** the lead's saved CSR report link first, then PDFs
  linked from the site ranked annual report → BRSR → CSR report →
  sustainability/ESG. Press-release PDFs and duplicates are dropped.
- **Caps:** at most 2 reports, stopping at the first that names people;
  25 MB, 600 pages, 60 seconds per report.
- **Pages read:** only pages mentioning the CSR Committee or the BRSR
  authority are parsed. The layouts handled come from real FY2025-26
  annual reports:
  - numbered member lists ("1. Meher Pudumjee - Chairperson" /
    "2. Dr. S. B. (Ravi) Pandit")
  - attendance tables ("Name 2 2 100")
  - the CSR annexure, with the role on the next line
- **Source links:** each found person links to the exact page
  (`…report.pdf#page=74`).

## Verified / inferred / unavailable

Every field shows one of three badges, with the same meaning and styling
as company discovery:

| Field | Verified | Inferred | Unavailable |
|---|---|---|---|
| Name, designation | Stated on the source page | A shared mailbox, named by the app ("CSR Team") | n/a |
| Office location | City stated with the person: a short line or "based in …", **never** a biography paragraph | The company office from its contact page, or its HQ city | Neither known |
| Work email | Published with the person, on the company's domain | Guessed from the company's email format, **only** when published addresses agree on one pattern (e.g. first.last@); labelled "verify before sending" | Not published |
| Company phone | An office line published by the company: with the person, or its main number (labelled "not a direct line"). Clearly Indian lines (+91, 0-prefixed, 1800) are preferred over numbers with no code, then overseas offices. | n/a | None published |
| LinkedIn | A profile link published by the company / provider | n/a | Not published (a "Search LinkedIn" link is offered instead) |
| Source, company | Always verified | | |

**Confidence (10–95%)** is about how sure we are this person holds this
title. Hover the badge for the reasons. It is built from:
- a base for how it was found (structured data and reports highest, prose lowest)
- +10 per extra independent source
- +10 for a published work email
- +5 for an official LinkedIn link
- +5 for being on a leadership / CSR page

## What is never collected

Enforced in `backend/app/contact_discovery/policy.py`, both when results
are found **and again when they're saved**. The save endpoint re-checks
what the browser sends, and reports anything it dropped.

- **Personal emails:** only addresses on the company's own domain
  (subdomains and sibling country domains like `acme.co.in` count).
  gmail, yahoo, rediffmail, outlook and similar are always dropped. An
  individual's address published with no title next to it isn't kept
  either.
- **Personal phone numbers:**
  - Indian mobile numbers are always dropped, as is anything labelled
    Mobile / Cell / WhatsApp / Fax. A 10-digit number starting 6–8 can
    also be a landline (Bengaluru 080, Ahmedabad 079), so the written
    form decides: an area code in its own group ("+91 80 2844 0011") is
    a landline; 5+5 or 10 digits in a row is treated as a mobile.
    Anything ambiguous counts as a mobile.
  - Overseas numbers are kept only when labelled as an office line.
  - Numbers under 10 digits are treated as fragments and dropped.
  - Phone numbers from Hunter/Apollo are never kept.
- **LinkedIn is never fetched or scraped.**
- **robots.txt is always honoured.** It is fetched with the same
  identifiable User-Agent as the pages, following RFC 9309 but erring
  towards not crawling: 401/403, server errors and network failures mean
  "read nothing"; 404 means "no restrictions".

  This is deliberately *not* Python's `RobotFileParser.read()`, which
  fetches as `Python-urllib`. Many corporate sites' bot protection
  answers that User-Agent with 403, which Python treats as "disallow
  everything". Tata Steel's real robots.txt is `Allow: /`.
- No logins, paywalls or CAPTCHAs are bypassed, and no off-site pages
  are crawled.

## Saving, the contact profile, and search

- **Database:** see [Database](#database).
- **Contact profile** (`/contacts/:id`) shows:
  - every field with its badge
  - **View source**, and a **LinkedIn** profile link (or a LinkedIn
    search link)
  - "Where this contact was found": every source page, what it stated,
    and when
  - **Notes** about the contact. These are company notes tagged with the
    contact, so they also show on the company page and survive if the
    contact is removed.
  - the contact's own **activity timeline**: saved, updated, notes,
    emails drafted for them
  - **Generate Email**: the existing generator, with the contact
    preselected
- **Contacts page** (`/contacts`, top nav): every saved contact across
  all leads.
  - **Search by:** company, name, designation (also matches the role
    category, so "Regional Manager" finds "Zonal Head – West"),
    industry, state, city, and priority.
  - **City and state** match the contact's own office location or the
    company's.
- **Duplicates:** checked per company by email, then **LinkedIn
  profile**, then name, so the same person found again isn't saved
  twice. "Save anyway" overrides.

## API

| Method & path | Purpose |
|---|---|
| `POST /api/contact-discovery/search` | Body `{company_id}` for a saved lead, or `{name, website, city, state, industry, csr_report_url}` for a discovered company; plus `include_reports`, `refresh`. Returns contacts (with provenance, confidence and reasons, `saved_contact_id`), company contact points, suggested searches, pages read/blocked, report scan info, source report and messages. Logged in `contact_discovery_logs`. |
| `POST /api/contact-discovery/save` | `{company_id | company, contacts[], force}` → `{company_id, company_created, saved[], duplicates[], dropped[]}` |
| `GET /api/contact-discovery/logs?company_id=` | Past runs: pages read and blocked, sources used, count, duration |
| `GET /api/contacts` | Contact search (`company, name, designation, industry, state, city, priority, company_id, skip, limit`) |
| `GET /api/contacts/{id}` | Contact profile: contact + company summary + sources + notes + activity |
| `POST /api/contacts/{id}/notes` | Add a note about the contact |

Unchanged: `POST/PATCH/DELETE` contact endpoints, and the Phase 2
`POST /api/companies/{id}/scrape` and `/enrich` (no longer used by the
UI; see Changes to existing behaviour).

## Database

All additions; nothing renamed or removed.

- **`contacts`**: new nullable columns `office_location`,
  `role_category`, `priority`, `confidence`, `provenance` (JSON) and
  `origin` (`manual` / `discovery`).
- **`contact_sources`** (new): one row per page a saved contact was
  found on: `url`, `source_type`, `label`, `fields`, `found_at`.
- **`contact_discovery_logs`** (new): one row per run.
  - Records `company_id` (null until the company is saved; earlier runs
    are linked when saving contacts creates the lead), pages checked and
    blocked, sources used, candidates found, messages and duration.
- **`notes.contact_id`, `activity_logs.contact_id`** (new, nullable,
  `ON DELETE SET NULL`): per-contact notes and timeline on the existing
  tables.
- **Existing databases upgrade themselves:** on startup
  `backend/app/schema_upgrade.py` adds any *nullable* model column
  missing from an existing table (`ALTER TABLE … ADD COLUMN`). This was
  verified on a copy of a pre-existing dev database. Anything else
  (renames, type changes, NOT NULL columns) still needs a manual change.

## Changes to existing behaviour

- The company page's old **Find CSR contacts** card (Scan website /
  Enrich (Hunter/Apollo)) is replaced by **Find contacts**, which covers
  both:
  - the same site plus more page types
  - named people
  - role mailboxes, and office phones / general inboxes as "company
    contact points"
  - Hunter/Apollo when configured

  The old raw scan kept mobile numbers and unnamed personal emails,
  which the new rules forbid. Its endpoints still exist.
- The provenance badge label **"Not available" is now "Unavailable"**
  everywhere, company discovery included, to match the spec.
- `Modal` takes an optional `size="wide"` and scrolls when its content
  is taller than the screen.
- `find_duplicate_contact` also matches on LinkedIn profile. Manual
  contacts get `origin: "manual"`, and note/email activity about a
  contact is tagged with it.

## Limits

- **Many sites can't be read.** Godrej Industries and Kirloskar answer
  robots.txt with 403/503, so nothing is read. Some sites render
  leadership pages with JavaScript, which isn't executed. The panel says
  which case applies and offers the LinkedIn / report links.
- **Most companies don't publish CSR staff below board level.**
  - The CSR Committee (directors) is reliably public, via the website or
    annual report.
  - A named CSR Manager or HR Head often isn't. Expect Priority 1 to
    often be the committee plus the csr@ mailbox.
- **Annual reports often aren't linked** from the pages read (they sit
  in investor sections). Add the report link to the lead's "CSR report"
  field (or paste the annual report there) and scan it.
- **Emails:** personal work emails are rarely published. Pattern-guessed
  emails are labelled inferred and should be verified before use.
- **Heuristic extraction:** unusual layouts can still be missed, and a
  card heading can occasionally be misread as a name. Every result links
  its source and is never saved automatically.
- **Report scanning** is slow (about 30–60s for a 250-page annual
  report) and only reads text PDFs, not scanned images.
- **The "Check CSR focus" button** still uses Phase 2's robots.txt
  loader, so it can wrongly skip sites like Tata Steel. Switching it to
  `contact_discovery.service.load_robots` is a one-line follow-up, left
  out to keep company discovery's behaviour unchanged.
