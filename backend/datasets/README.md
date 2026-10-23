# Official datasets folder

Drop CSV files you download from **official publishers** into this folder
and the Companies page's "Discover companies" search will include them,
alongside Wikidata and the MCA registry. Files are read straight from
disk (re-read automatically when they change) and are **never copied
into the database** - only companies you click "Save as lead" on are.

Everything here except this README is git-ignored, so downloaded data
never ends up in the repository.

Why download by hand instead of fetching automatically? Several of these
publishers' website terms forbid automated scraping, but they explicitly
offer the files as downloads. Downloading them yourself keeps the app on
the right side of those terms.

## Recommended files

Site layouts change, so these say *what* to look for rather than exact menu paths.

| File | Where to get it | What it adds |
|---|---|---|
| NSE equity list (`EQUITY_L.csv`) | nseindia.com - the downloadable list of securities available for trading in the equity segment | Every NSE-listed company, with NSE symbol and ISIN (results get an **NSE** tag and merge with Wikidata via ISIN) |
| BSE list of scrips | bseindia.com - the "List of Scrips" download, filtered to active equity | Every BSE-listed company, with BSE code, ISIN, industry |
| **National CSR Portal** company-wise CSR data | csr.gov.in - the company-wise / development-sector-wise CSR spend reports, exported to CSV | **The only official source of what a company actually spends CSR money on, and in which Schedule VII sectors** - fills the CSR focus and CSR spending columns as *verified* |
| MCA company master data | data.gov.in - search "Company Master Data" and download the CSV/zip | Registered companies in that state, with CIN, status, principal business activity |

## Recognised columns

Column headers are matched case-insensitively, ignoring punctuation. A
file needs at least a company-name column; everything else is optional.

| Meaning | Accepted headers (any of) |
|---|---|
| Company name | `name`, `company name`, `name of company`, `company`, `issuer name` |
| Industry | `industry`, `sector`, `principal business activity`, `nature of business` |
| City | `city`, `district`, `hq city` |
| State | `state`, `registered state`, `state name`, `state/UT` |
| Website | `website`, `url`, `company website` |
| CSR focus | `csr focus`, `development sector`, `focus area`, `thematic area`, `schedule vii` |
| CSR spending | `csr spending`, `csr spent`, `amount spent`, `total amount spent`, `csr expenditure`, … |
| CSR report link | `csr report url`, `csr report`, `csr report link` |
| Employees | `employees`, `employee count`, `no of employees` |
| Identifiers | `cin`, `isin` / `isin number` / `isin no`, `symbol` (NSE), `security code` (BSE) |
| Financial year | `financial year`, `fy`, `year` |

**CSR spending units:** if the spending header mentions crore (`Cr`,
`crore`) or lakh (`lakh`, `lacs`) - e.g. `Amount Spent (INR Cr.)` - the
values are converted to rupees. Otherwise they're taken as rupees.

**One row per sector/year is fine.** National CSR Portal exports usually
have one row per company × development sector × financial year. Rows for
the same company are combined: sectors are merged into one CSR focus
list, and spending is summed over the **latest financial year only**
(never across years).

## Your own list

You can also put a CSV of your own here (e.g. a list from a partner
organisation) using the column names above. Results from it are
labelled with the file name as their source, so staff can see where each
value came from. Only add data you're allowed to use.
