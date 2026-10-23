"""Runs the discovery providers, merges their records, and filters them.

Flow for one search:
  1. every configured provider is queried in parallel (a failing provider
     is reported in `sources` and skipped - it never fails the search);
  2. records describing the same company are merged - matched on shared
     identifiers (ISIN, CIN, Wikidata QID), website domain, or normalized
     name - keeping per-field provenance, preferring verified values over
     inferred ones;
  3. industry/city/state/CSR-focus filters are applied uniformly;
  4. the merged, filtered list is cached briefly so paging through it
     doesn't re-query external services.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Optional

from .base import (
    INFERRED,
    TRACKED_FIELDS,
    UNAVAILABLE,
    VERIFIED,
    CompanyDiscoveryProvider,
    DiscoveredCompany,
    DiscoveryQuery,
    FieldProvenance,
    normalize_company_name,
    normalize_domain,
)
from .matching import matches_city, matches_csr_focus, matches_industry, matches_state

CACHE_TTL_SECONDS = 600
CACHE_MAX_ENTRIES = 100
PROVIDER_TIMEOUT_SECONDS = 45
_IDENTIFIER_KEYS = ("isin", "cin", "wikidata", "nse_symbol", "bse_code")


# ----------------------------------------------------------------------------
# Merging
# ----------------------------------------------------------------------------
def _identity_keys(company: DiscoveredCompany) -> list[str]:
    keys = [f"{k}:{v.upper()}" for k, v in company.identifiers.items() if k in _IDENTIFIER_KEYS and v]
    domain = normalize_domain(company.values.get("website"))
    if domain:
        keys.append(f"domain:{domain}")
    name = normalize_company_name(company.name)
    if name:
        keys.append(f"name:{name}")
    return keys


def _conflicts(a: DiscoveredCompany, b: DiscoveredCompany) -> bool:
    """Two records with different values for the same hard identifier
    (e.g. two CINs) are different companies even if their names match.
    """
    return any(
        a.identifiers.get(k) and b.identifiers.get(k) and a.identifiers[k].upper() != b.identifiers[k].upper()
        for k in _IDENTIFIER_KEYS
    )


def _absorb(target: DiscoveredCompany, other: DiscoveredCompany) -> None:
    for field_name in TRACKED_FIELDS:
        if field_name not in other.values:
            continue
        current = target.provenance.get(field_name)
        incoming = other.provenance[field_name]
        if current is None or (current.status == INFERRED and incoming.status == VERIFIED):
            target.values[field_name] = other.values[field_name]
            target.provenance[field_name] = incoming
    target.description = target.description or other.description
    target.aliases += [a for a in other.aliases if a not in target.aliases]
    for key, value in other.identifiers.items():
        target.identifiers.setdefault(key, value)
    target.listed_on += [x for x in other.listed_on if x not in target.listed_on]
    for key, value in other.details.items():
        target.details.setdefault(key, value)
    known_sources = {s.name for s in target.sources}
    target.sources += [s for s in other.sources if s.name not in known_sources]
    target.location_hints += other.location_hints


def merge_companies(companies: list[DiscoveredCompany]) -> list[DiscoveredCompany]:
    """Merge records describing the same company. Input order is priority
    order: the first record's name is kept, and for each field the first
    verified value wins.
    """
    merged: list[DiscoveredCompany] = []
    index: dict[str, DiscoveredCompany] = {}
    for company in companies:
        target = None
        for key in _identity_keys(company):
            candidate = index.get(key)
            if candidate is not None and not _conflicts(candidate, company):
                target = candidate
                break
        if target is None:
            target = company
            merged.append(company)
        else:
            _absorb(target, company)
        for key in _identity_keys(target):
            index.setdefault(key, target)
    return merged


# ----------------------------------------------------------------------------
# Filtering and ranking
# ----------------------------------------------------------------------------
def apply_filters(companies: list[DiscoveredCompany], query: DiscoveryQuery) -> tuple[list[DiscoveredCompany], int]:
    """Returns (matching companies, how many were dropped only because
    they have no published CSR focus to match against).
    """
    kept, no_focus = [], 0
    for c in companies:
        v = c.values
        if not matches_industry(query.industry, v.get("industry"), c.description):
            continue
        if not matches_city(query.city, v.get("city"), *c.location_hints):
            continue
        if not matches_state(query.state, v.get("state") or " | ".join(c.location_hints)):
            continue
        if query.csr_focus:
            if not v.get("csr_focus"):
                no_focus += 1
                continue
            if not matches_csr_focus(query.csr_focus, v.get("csr_focus")):
                continue
        kept.append(c)
    return kept, no_focus


def _rank_key(company: DiscoveredCompany, query: DiscoveryQuery):
    wanted = normalize_company_name(query.name)
    name = normalize_company_name(company.name)
    if wanted and name == wanted:
        name_rank = 0
    elif wanted and name.startswith(wanted):
        name_rank = 1
    else:
        name_rank = 2
    # Listed and large companies first: they're the ones most likely to meet
    # the Companies Act Section 135 thresholds that make CSR spending mandatory.
    listed = bool({"NSE", "BSE"} & set(company.listed_on))
    employees = company.values.get("employee_count") or 0
    verified = sum(1 for p in company.provenance.values() if p.status == VERIFIED)
    return (name_rank, not listed, -len(company.sources), -employees, -verified, company.name.lower())


# ----------------------------------------------------------------------------
# Serialization
# ----------------------------------------------------------------------------
def to_result_dict(company: DiscoveredCompany) -> dict:
    provenance = {}
    for field_name in TRACKED_FIELDS:
        p = company.provenance.get(field_name) or FieldProvenance(status=UNAVAILABLE)
        provenance[field_name] = {"status": p.status, "source": p.source, "source_url": p.source_url}
    ident = next((f"{k}:{company.identifiers[k]}" for k in _IDENTIFIER_KEYS if company.identifiers.get(k)), None)
    return {
        "result_id": ident or f"name:{normalize_company_name(company.name)}",
        "name": company.name,
        "aliases": company.aliases[:5],
        "description": company.description,
        **{field_name: company.values.get(field_name) for field_name in TRACKED_FIELDS},
        "provenance": provenance,
        "identifiers": company.identifiers,
        "listed_on": company.listed_on,
        "details": company.details,
        "sources": [{"name": s.name, "url": s.url} for s in company.sources],
        "saved_company_id": None,
    }


# ----------------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------------
class DiscoveryService:
    def __init__(self, providers: list[CompanyDiscoveryProvider]):
        self.providers = providers
        self._cache: dict[tuple, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def source_statuses(self) -> list[dict]:
        statuses = []
        for p in self.providers:
            statuses.append(
                {
                    "key": p.key,
                    "label": p.label,
                    "description": p.description,
                    "requires_api_key": p.requires_api_key,
                    "configured": p.is_configured(),
                    "setup_hint": p.setup_hint,
                    "status": p.status() if p.is_configured() else None,
                }
            )
        return statuses

    def _run_provider(self, provider: CompanyDiscoveryProvider, query: DiscoveryQuery):
        try:
            return provider.search(query), None
        except Exception as exc:  # one source being down must not fail the search
            return None, f"{type(exc).__name__}: {exc}"

    def _collect(self, query: DiscoveryQuery) -> dict:
        active = [p for p in self.providers if p.is_configured()]
        source_reports = {
            p.key: {"key": p.key, "label": p.label, "configured": p.is_configured(), "used": False,
                    "result_count": 0, "error": None}
            for p in self.providers
        }
        notes: list[str] = []
        all_companies: list[DiscoveredCompany] = []

        if active:
            # Not a `with` block: its exit waits for every thread, which would
            # make the per-provider timeout meaningless. A slow source is
            # reported as timed out and left to finish in the background.
            pool = ThreadPoolExecutor(max_workers=len(active))
            try:
                futures = [(p, pool.submit(self._run_provider, p, query)) for p in active]
                deadline = time.time() + PROVIDER_TIMEOUT_SECONDS
                for provider, future in futures:  # provider order == merge priority
                    report = source_reports[provider.key]
                    try:
                        result, error = future.result(timeout=max(deadline - time.time(), 0))
                    except FutureTimeout:
                        result, error = None, f"timed out after {PROVIDER_TIMEOUT_SECONDS}s"
                    if error:
                        report["error"] = error
                        continue
                    report["used"] = True
                    report["result_count"] = len(result.companies)
                    notes.extend(result.notes)
                    all_companies.extend(result.companies)
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

        merged = merge_companies(all_companies)
        filtered, no_focus = apply_filters(merged, query)
        filtered.sort(key=lambda c: _rank_key(c, query))
        if no_focus:
            notes.append(
                f"{no_focus:,} compan{'y was' if no_focus == 1 else 'ies were'} hidden because no configured "
                "source publishes their CSR focus. Clear the CSR focus filter to see them and use "
                "\"Check CSR focus\" on a result, or add National CSR Portal data (see Data sources)."
            )
        if not active:
            notes.append("No discovery sources are enabled. See the setup notes under \"Data sources\".")
        return {
            "results": [to_result_dict(c) for c in filtered],
            "notes": list(dict.fromkeys(notes)),
            "sources": list(source_reports.values()),
        }

    def search(self, query: DiscoveryQuery, page: int = 0, page_size: int = 25) -> dict:
        if query.is_empty():
            raise ValueError("Enter at least one search filter.")
        key = query.cache_key()
        now = time.time()
        with self._lock:
            cached = self._cache.get(key)
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            payload = cached[1]
        else:
            payload = self._collect(query)
            with self._lock:
                if len(self._cache) >= CACHE_MAX_ENTRIES:
                    oldest = min(self._cache, key=lambda k: self._cache[k][0])
                    self._cache.pop(oldest, None)
                self._cache[key] = (now, payload)

        start = page * page_size
        return {
            "results": [dict(r) for r in payload["results"][start : start + page_size]],
            "total": len(payload["results"]),
            "page": page,
            "page_size": page_size,
            "notes": payload["notes"],
            "sources": payload["sources"],
        }

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()


_default_service: Optional[DiscoveryService] = None


def get_default_service() -> DiscoveryService:
    """Process-wide service: local datasets first (the NGO's own official
    downloads, often the only source of CSR spend/focus), then the MCA
    registry, then Wikidata - that order is also merge priority.
    """
    global _default_service
    if _default_service is None:
        from .datasets import DatasetProvider
        from .mca import McaProvider
        from .wikidata import WikidataProvider

        _default_service = DiscoveryService([DatasetProvider(), McaProvider(), WikidataProvider()])
    return _default_service
