# Company Discovery

How the Companies page finds **real** companies across India, where the
data comes from, how to switch each source on, and what its limits are.

## Why this exists

Before this feature, the Companies page only ever listed rows from the
app's own `companies` table (`GET /api/companies`). Nothing outside that
table could be found, so a fresh install showed only the ten fictional
companies from `backend/scripts/seed_demo_data.py`, all with
`*.example.com` websites. There was no hard-coded limit of 10; there
was simply no external source at all.

The Companies page now has two tabs:

| Tab | What it searches | Stored in the database? |
|---|---|---|
| **Discover companies** (default) | Public sources: Wikidata, the MCA company registry, official CSV datasets | **No**, until you click **Save as lead** |
| **Saved leads** | The NGO's own `companies` table (the existing CRM list: filters, CSV import/export, "+ Add company") | Yes |

Lead scoring, AI summary/meeting brief/emails, notes, contacts,
documents, proposals, tags and outreach status all belong to a saved
`Company` row. They become available the moment a result is saved, and
not before.

## Workflow

1. Staff search by any of **company name, industry, city, state, CSR
   focus area**.
2. `GET /api/discover/companies` queries every configured source in
   parallel, merges records that describe the same company, applies the
   filters, and returns a page of results. Results already saved as
   leads are flagged and link straight to the lead.
3. Each result shows name, industry, location, website and CSR focus,
   plus CSR spending/report/employees when a source has them. Every
   field carries a **provenance badge** (see below).
4. Optional: **Check CSR focus** reads the company's own CSR web pages
   and infers focus areas (see "CSR focus inference").
5. **Save as lead** (`POST /api/discover/save`) creates the `Company`
   row and attaches a note recording where every value came from. Saving
   a company that already exists returns the standard duplicate warning,
   with "View existing" and "Save anyway".

## Verified / inferred / unavailable

Every discovered field has one of three statuses, shown as a badge
(hover it to see the source; click it to open the source record):

| Status | Meaning | Examples |
|---|---|---|
| **Verified** | Stated directly by a named public source record. The source is always attached. | Industry/HQ/website from a Wikidata statement; registered state and principal business activity from the MCA registry; CSR spend from a National CSR Portal export |
| **Inferred** | Worked out by this app, not stated by any source. Double-check before relying on it. | State derived from the HQ city's admin hierarchy; city parsed from a registered-office address; city of an HQ building ("Bombay House" → Mumbai); CSR focus from keywords on the company's CSR page |
| **Unavailable** | No configured source publishes it. Never guessed or filled with a default. | CSR focus/spending for most companies unless National CSR Portal data is loaded |

"Verified" means *attributable*, not *infallible*. Wikidata is
community-edited, and the MCA snapshot runs to November 2023. That's why
the source link is always one click away.

When a result is saved, this provenance is written into a note on the
lead ("Verified (stated by a public source): … / Inferred by the app -
please double-check: … / Not available from public sources: …"), so the
record of where each value came from survives after saving.

## Data sources

All three sit behind one provider interface
(`backend/app/company_discovery/base.py::CompanyDiscoveryProvider`). A
new source is a new class with `search(query) -> ProviderResult`,
registered in `service.py::get_default_service()`.

### 1. Wikidata (on by default, no key)

- **What:** the open, CC0-licensed knowledge base behind Wikipedia.
  Roughly 3,400 notable Indian companies (listed companies, PSUs, large
  groups, well-known private firms): industry, HQ, state, official
  website, NSE/BSE listing, ISIN, employee count, aliases (so "TCS"
  finds Tata Consultancy Services).
- **How:** live SPARQL filtering of all Indian companies takes 15-45s,
  too slow for a search box. Instead the backend keeps a **local index**
  of every Indian company. It's built in the background on startup in
  about 10 minutes of paced requests, cached as a JSON file in
  `backend/.cache/` (not the database), and refreshed weekly. Searches
  filter it in about 0.2s. Until the first build finishes, searches fall
  back to Wikidata's live full-text search (top 50 matches), with a note
  saying results are partial.
- **Filtering out non-companies:** Wikidata's "industry" statements also
  appear on NGOs, universities and associations. The index stores every
  entity with its types, and `wikidata.py::looks_like_company` filters
  at search time, so the rule can be refined without a rebuild:
  - **Always excluded:** nonprofits, foundations, religious bodies,
    government agencies, trade associations, sports clubs, stock
    exchanges.
  - **Excluded unless the entity also has an explicit company form or a
    legal-name suffix:** universities, colleges, research institutes,
    hospitals. So Apollo Hospitals (a "public company") and a coaching
    business (a "privately held company") stay, and so does a mistyped
    "…Limited".
  - PSUs and state-owned enterprises are kept.

  This was checked against random samples of the live index.
- **Etiquette:** identifiable User-Agent, sequential paced requests,
  honours `Retry-After` on HTTP 429 from both the search API and the
  query service, and waits 30 minutes after a failed
  build before trying again.
- **Setup:** nothing required. Recommended: set `DISCOVERY_CONTACT` to
  an email or URL so Wikimedia can reach the operator, as their API
  policy asks.

### 2. MCA company registry via data.gov.in (needs a free key)

- **What:** the Ministry of Corporate Affairs "Registrars of Companies
  (RoC)-wise Company Master Data" on India's Open Government Data
  platform (resource `4dbe5667-7b6b-41d7-82af-211562424d9a`). About 3.6
  million registered companies: CIN, registered state, principal
  business activity, status, class, paid-up capital, registered office
  address. Official data under the Government Open Data License - India.
- **Setup:** register free at <https://data.gov.in>, copy your API key
  from "My Account", and set `DATA_GOV_IN_API_KEY`. `MCA_RESOURCE_ID`
  only needs changing if MCA republishes under a new resource.
- **Limits:**
  - The OGD API only supports **exact-match** filters. A name search
    tries the registered forms MCA uses ("NAME", "NAME LIMITED", "NAME
    PRIVATE LIMITED").
  - A state search browses that state's registry (first 100 active
    companies).
  - Industry/city-only searches can't be served by this API, and the
    response says so.
  - The published snapshot runs to **November 2023**.
  - The shared sample key on data.gov.in is heavily rate-limited; use
    your own key.
- **Untested against the live API:** only the shared sample key was
  available while building this (it returned "Rate limit exceeded"), so
  this provider is tested against fixture responses in the documented
  OGD format. It reads field ids from the API's own `field` metadata
  rather than assuming them. Run one name search after adding a key to
  confirm.

### 3. Official datasets folder (local CSV files, no key)

- **What:** CSVs downloaded from official publishers and dropped into
  `backend/datasets/`: NSE/BSE company lists, **National CSR Portal**
  company-wise CSR spend by development sector, MCA master data.
  Searched alongside the online sources, merged with them by ISIN/CIN/
  name, and never copied into the database.
- **Why files:** some of the most useful public data (exchange lists,
  CSR Portal reports) is offered as a manual download, while the
  publishers' website terms forbid automated scraping. Downloading by
  hand respects that.
- **The only verified CSR focus/spend source.** Without National CSR
  Portal data, CSR focus is "Unavailable" for most companies until
  someone uses "Check CSR focus".
- **Setup and recognised columns:** [`backend/datasets/README.md`](../backend/datasets/README.md).

### CSR focus inference (company websites)

`POST /api/discover/csr-focus` (the **Check CSR focus** button) reads up
to 5 pages of the company's own site. It starts at the home page,
follows links that look like the CSR page, and tries `/csr`,
`/sustainability`, etc. It counts Schedule VII keywords (education,
healthcare, environment, rural development, …) on CSR-related pages
only. It also picks up a CSR/BRSR/sustainability report PDF link if one
is linked. It uses the same rules as the existing contact scraper:
identifiable User-Agent, robots.txt honoured, a pause between requests,
same domain only. URLs whose host resolves to a non-public address
(localhost, private ranges, cloud metadata) are refused. The result is
always **inferred** and is not stored unless staff then save the
company.

It explains an empty result in plain language:
- The site disallows automated reading (e.g. Infosys answers robots.txt
  with 403, which counts as "disallow all").
- The site is JavaScript-only with no readable text (e.g. Cipla).
- There is no CSR page.
- The CSR page names no clear focus area.

### Merging and ranking

Records for the same company are merged on shared identifiers (ISIN,
CIN, Wikidata QID, NSE/BSE codes), website domain, or normalized name
("TATA STEEL LIMITED" = "Tata Steel Ltd." = "Tata Steel"). Two records
with *different* CINs are never merged even if the names match. For
each field, a verified value beats an inferred one; otherwise the
higher-priority source wins (local datasets → MCA → Wikidata).

Results are ranked: exact name match first, then NSE/BSE-listed
companies, then by number of corroborating sources, then by employee
count. Listed and large companies are the ones most likely to meet the
Companies Act Section 135 thresholds that make CSR spending mandatory.

## Configuration reference

All optional. Set them in `backend/.env` locally, or as Render env vars.

| Variable | Default | Purpose |
|---|---|---|
| `DISCOVERY_CONTACT` | *(blank)* | Email/URL added to the User-Agent sent to Wikidata/data.gov.in |
| `WIKIDATA_ENABLED` | `true` | Turn the Wikidata source off |
| `WIKIDATA_REFRESH_HOURS` | `168` | How often the Wikidata index is rebuilt (weekly) |
| `DATA_GOV_IN_API_KEY` | *(blank)* | Enables the MCA registry source |
| `MCA_RESOURCE_ID` | `4dbe5667-…` | data.gov.in resource for MCA company master data |
| `DISCOVERY_DATASETS_DIR` | `datasets` | Folder of official CSVs (relative to `backend/`) |
| `DISCOVERY_CACHE_DIR` | `.cache` | Where the Wikidata index file is kept (relative to `backend/`) |

On hosts with an ephemeral disk (e.g. Render's free tier), the Wikidata
index is rebuilt after each restart or deploy. Live search covers the
roughly 10 minutes that takes.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/discover/sources` | Each source: configured?, status, setup hint |
| `GET /api/discover/companies?name=&industry=&city=&state=&csr_focus=&page=&page_size=` | Search (at least one filter required). Returns `results`, `total`, `notes`, and per-source `sources` reports (result count / error) |
| `POST /api/discover/csr-focus` `{website}` | Infer CSR focus from the company's own site |
| `POST /api/discover/save[?force=true]` | Save a result as a lead; `409` with the existing lead if it's a duplicate |

A source that errors (network failure, rate limit) is reported in that
search's `sources` and skipped. It never fails the whole search.

## Limitations

- **Coverage is notable companies plus whatever you add.** Wikidata
  covers about 3,400 notable Indian companies. That includes the large
  CSR spenders but not most small private companies. Broader coverage
  needs the MCA key (exact names/state browsing) or the official CSV
  files.
- **CSR focus/spend is mostly unavailable without National CSR Portal
  data.** No open API publishes it. Website inference is a keyword
  heuristic and is labelled as such.
- **Wikidata is community-edited**, so occasional stale websites or odd
  industry labels (e.g. "economics of banking") come straight from the
  source. Every value links back to its record.
- **The MCA snapshot is from November 2023**, and its API supports only
  exact matches.
- **The CSR-focus filter is strict:** it only matches companies whose
  focus is published by a configured source (in practice, a National CSR
  Portal file). Website inferences from "Check CSR focus" aren't stored,
  so they don't count. The response says how many companies were hidden
  for lacking that data.
- **No turnover/net-profit data**, so Section 135 CSR eligibility can't
  be computed. NSE/BSE listing and employee count are used as ranking
  proxies instead.
