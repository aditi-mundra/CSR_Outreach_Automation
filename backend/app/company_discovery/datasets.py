"""Local official-dataset provider: CSV files the NGO downloads itself.

Some of the most useful public data has no open API, or has one whose
terms forbid automated access - but the publishers do offer it as a
manual download:

  * NSE equity list (EQUITY_L.csv) / BSE scrip list - every listed company
  * National CSR Portal (csr.gov.in) company-wise CSR spend by
    development sector - the *only* official source of what a company
    actually spends CSR money on
  * MCA company master data CSVs (data.gov.in "Zip download")

Drop any of these into DISCOVERY_DATASETS_DIR (default backend/datasets/)
and they're searched alongside the online sources. Files are read from
disk, cached in memory until they change, and never copied into the
database. See datasets/README.md for download links and the column
names that are recognised.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from pathlib import Path
from typing import Optional

from ..config import settings
from .base import (
    VERIFIED,
    CompanyDiscoveryProvider,
    DiscoveredCompany,
    DiscoveryQuery,
    ProviderResult,
    SourceRef,
    name_contains,
    normalize_company_name,
    smart_title,
)
from .http import resolve_backend_path
from .matching import matches_city, matches_csr_focus, matches_industry, matches_state

logger = logging.getLogger("company_discovery.datasets")

MAX_ROWS_PER_FILE = 500_000
MAX_MATCHES = 2_000

# Normalized header -> canonical column. Headers are normalized by
# lower-casing and collapsing non-alphanumerics to single spaces.
COLUMN_ALIASES: dict[str, list[str]] = {
    "name": ["name", "company name", "name of company", "company", "companyname", "issuer name", "name of the company"],
    "industry": [
        "industry", "sector", "principal business activity", "companyindustrialclassification",
        "industry new name", "industry name", "nature of business",
    ],
    "city": ["city", "district", "hq city", "headquarters"],
    "state": ["state", "registered state", "companystatecode", "state name", "state ut"],
    "website": ["website", "url", "web site", "company website", "website url"],
    "csr_focus": [
        "csr focus", "csr focus area", "csr focus areas", "development sector", "development sectors",
        "focus area", "focus areas", "csr sector", "thematic area", "schedule vii",
    ],
    "csr_spending": [
        "csr spending", "csr spent", "amount spent", "total amount spent", "csr expenditure",
        "amount spent inr cr", "amount spent in inr cr", "csr spent inr cr", "actual csr spent",
        "amount spent inr", "csr amount spent", "total csr spent", "amount spent for the financial year",
    ],
    "csr_report_url": ["csr report url", "csr report", "csr report link", "sustainability report url"],
    "employee_count": ["employees", "employee count", "no of employees", "number of employees"],
    "cin": ["cin", "corporate identification number", "corporate identity number"],
    "isin": ["isin", "isin number", "isin no", "isin code"],
    "nse_symbol": ["symbol", "nse symbol"],
    "bse_code": ["security code", "bse code", "scrip code"],
    "address": ["registered office address", "address", "registered office"],
    "status": ["company status", "companystatus"],
    "year": ["financial year", "fy", "year"],
    "listed_on": ["listed on", "exchange"],
}


def _normalize_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (header or "").lower()).strip()


def map_columns(headers: list[str]) -> dict[str, str]:
    """canonical column -> actual header, for headers this provider knows."""
    normalized = {_normalize_header(h): h for h in headers if h}
    mapping: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[canonical] = normalized[alias]
                break
    return mapping


def spending_multiplier(header: str) -> float:
    """CSR portal exports state amounts in crore or lakh in the header."""
    norm = _normalize_header(header)
    if re.search(r"\b(cr|crore|crores)\b", norm):
        return 1e7
    if re.search(r"\b(lakh|lakhs|lac|lacs)\b", norm):
        return 1e5
    return 1.0


def _to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", str(value))
    try:
        return float(cleaned) if cleaned not in ("", ".", "-") else None
    except ValueError:
        return None


def _exchange_for(mapping: dict[str, str]) -> Optional[str]:
    if "nse_symbol" in mapping and "isin" in mapping:
        return "NSE"
    if "bse_code" in mapping:
        return "BSE"
    return None


def parse_rows(rows: list[dict], mapping: dict[str, str], filename: str) -> list[dict]:
    """Collapse raw rows into one record per company. National CSR Portal
    exports have one row per company x development sector (x year): the
    sectors are unioned into the CSR focus, and spending is summed over
    the latest financial year present (all rows when there's no year
    column) - never across years.
    """
    exchange = _exchange_for(mapping)
    multiplier = spending_multiplier(mapping["csr_spending"]) if "csr_spending" in mapping else 1.0
    get = lambda row, col: (row.get(mapping[col]) or "").strip() if col in mapping else ""  # noqa: E731

    latest_year = None
    if "year" in mapping and "csr_spending" in mapping:
        years = sorted({get(r, "year") for r in rows if get(r, "year")})
        latest_year = years[-1] if years else None

    records: dict[str, dict] = {}
    for row in rows:
        name = get(row, "name")
        if not name:
            continue
        key = get(row, "cin") or normalize_company_name(name)
        record = records.setdefault(
            key,
            {"name": name, "focus": [], "spending": None, "file": filename, "exchange": exchange},
        )
        for col in ("industry", "city", "state", "website", "csr_report_url", "cin", "isin",
                    "nse_symbol", "bse_code", "address", "status", "listed_on"):
            value = get(row, col)
            if value and not record.get(col):
                record[col] = value
        employees = _to_float(get(row, "employee_count"))
        if employees is not None and record.get("employee_count") is None:
            record["employee_count"] = int(employees)
        for focus in re.split(r"[;,|]", get(row, "csr_focus")):
            focus = focus.strip()
            if focus and focus.lower() not in (f.lower() for f in record["focus"]):
                record["focus"].append(focus)
        amount = _to_float(get(row, "csr_spending"))
        if amount is not None and (latest_year is None or get(row, "year") == latest_year):
            record["spending"] = (record["spending"] or 0) + amount * multiplier
        if latest_year:
            record["year"] = latest_year
    return list(records.values())


def record_to_company(record: dict) -> DiscoveredCompany:
    source = f"Dataset: {record['file']}"
    company = DiscoveredCompany(name=smart_title(record["name"]), provider="datasets")
    for field_name, key in (("industry", "industry"), ("city", "city"), ("state", "state"),
                            ("website", "website"), ("csr_report_url", "csr_report_url")):
        value = record.get(key)
        company.set(field_name, smart_title(value) if field_name in ("city", "state") else value, VERIFIED, source)
    company.set("csr_focus", ", ".join(record["focus"]) or None, VERIFIED, source)
    company.set("csr_spending", round(record["spending"]) if record.get("spending") else None, VERIFIED, source)
    company.set("employee_count", record.get("employee_count"), VERIFIED, source)
    for ident in ("cin", "isin", "nse_symbol", "bse_code"):
        if record.get(ident):
            company.identifiers[ident] = record[ident]
    listed = record.get("listed_on") or record.get("exchange")
    if listed:
        company.listed_on = [part.strip() for part in re.split(r"[;,|/]", listed) if part.strip()]
    if record.get("address"):
        company.location_hints.append(record["address"])
    if record.get("status"):
        company.details["Registry status"] = record["status"]
    if record.get("year") and record.get("spending"):
        company.details["CSR spend year"] = record["year"]
    company.sources.append(SourceRef(source))
    return company


class _CachedFile:
    def __init__(self, signature: tuple, records: list[dict], truncated: bool):
        self.signature = signature
        self.records = records
        self.truncated = truncated


class DatasetProvider(CompanyDiscoveryProvider):
    key = "datasets"
    label = "Official datasets (local files)"
    description = (
        "CSV files downloaded from official publishers - NSE/BSE company lists, National CSR "
        "Portal CSR-spend exports, MCA master data - placed in the datasets folder."
    )
    requires_api_key = False
    setup_hint = "Download official CSVs into backend/datasets/ - see datasets/README.md."

    def __init__(self, directory: Optional[Path] = None):
        self._directory = directory
        self._cache: dict[Path, _CachedFile] = {}

    @property
    def directory(self) -> Path:
        return self._directory or resolve_backend_path(settings.discovery_datasets_dir)

    def files(self) -> list[Path]:
        if not self.directory.is_dir():
            return []
        return sorted(p for p in self.directory.iterdir() if p.suffix.lower() == ".csv" and p.is_file())

    def is_configured(self) -> bool:
        return bool(self.files())

    def status(self) -> Optional[str]:
        names = [p.name for p in self.files()]
        return f"{len(names)} file{'s' if len(names) != 1 else ''}: {', '.join(names)}" if names else None

    def _load(self, path: Path) -> _CachedFile:
        stat = path.stat()
        signature = (stat.st_mtime, stat.st_size)
        cached = self._cache.get(path)
        if cached and cached.signature == signature:
            return cached

        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        reader = csv.DictReader(io.StringIO(text))
        mapping = map_columns(reader.fieldnames or [])
        rows, truncated = [], False
        if "name" in mapping:
            for index, row in enumerate(reader):
                if index >= MAX_ROWS_PER_FILE:
                    truncated = True
                    break
                rows.append(row)
        else:
            logger.warning("Skipping %s: no company-name column recognised", path.name)
        cached = _CachedFile(signature, parse_rows(rows, mapping, path.name) if rows else [], truncated)
        self._cache[path] = cached
        return cached

    def search(self, query: DiscoveryQuery) -> ProviderResult:
        notes: list[str] = []
        wanted_name = normalize_company_name(query.name)
        matches: list[DiscoveredCompany] = []
        for path in self.files():
            try:
                loaded = self._load(path)
            except OSError as exc:
                notes.append(f"Could not read dataset {path.name}: {exc}")
                continue
            if loaded.truncated:
                notes.append(f"Dataset {path.name} is very large; only its first {MAX_ROWS_PER_FILE:,} rows are searched.")
            for record in loaded.records:
                # Cheap pre-filter on raw values so huge files don't build
                # thousands of objects; the service re-applies every filter.
                if not name_contains(normalize_company_name(record["name"]), wanted_name):
                    continue
                if not matches_state(query.state, record.get("state") or record.get("address")):
                    continue
                if not matches_city(query.city, record.get("city"), record.get("address")):
                    continue
                if not matches_industry(query.industry, record.get("industry")):
                    continue
                if query.csr_focus and not matches_csr_focus(query.csr_focus, ", ".join(record["focus"])):
                    continue
                matches.append(record_to_company(record))
                if len(matches) >= MAX_MATCHES:
                    notes.append(f"Local datasets matched more than {MAX_MATCHES:,} companies; narrow your search.")
                    return ProviderResult(companies=matches, notes=notes)
        return ProviderResult(companies=matches, notes=notes)
