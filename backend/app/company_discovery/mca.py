"""MCA company master data via India's Open Government Data platform.

Source: "Registrars of Companies (RoC)-wise Company Master Data" published
by the Ministry of Corporate Affairs on data.gov.in (resource
4dbe5667-7b6b-41d7-82af-211562424d9a, all India, ~3.6M companies; the
published snapshot runs to November 2023). Official government open data
under the Government Open Data License - India.

Columns: CORPORATE_IDENTIFICATION_NUMBER, DATE_OF_REGISTRATION,
COMPANY_NAME, COMPANY_STATUS, COMPANY_CLASS, COMPANY_CATEGORY,
AUTHORIZED_CAPITAL, PAIDUP_CAPITAL, REGISTERED_STATE,
REGISTRAR_OF_COMPANIES, PRINCIPAL_BUSINESS_ACTIVITY,
REGISTERED_OFFICE_ADDRESS, SUB_CATEGORY.

Needs a free API key (DATA_GOV_IN_API_KEY): register at data.gov.in and
copy the key from "My Account". The OGD API only supports *exact-match*
filters, so:
  - a name search tries the registered-name forms MCA uses
    ("<NAME>", "<NAME> LIMITED", "<NAME> PRIVATE LIMITED");
  - a state search browses that state's registry (first 100 active
    companies) and the service applies industry/city filters on top;
  - industry/city-only searches can't be served by this API and say so.

The API's JSON field ids are read from the response's own `field`
metadata rather than hard-coded, so a change in id casing on the
platform doesn't silently break parsing.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from ..config import settings
from .base import (
    INFERRED,
    VERIFIED,
    CompanyDiscoveryProvider,
    DiscoveredCompany,
    DiscoveryQuery,
    ProviderResult,
    SourceRef,
    normalize_company_name,
    smart_title,
)
from .http import get_json
from .matching import MAJOR_INDIAN_CITIES, first_known_city

logger = logging.getLogger("company_discovery.mca")

API_BASE = "https://api.data.gov.in/resource/"
SOURCE_NAME = "MCA company master data (data.gov.in)"
DEFAULT_RESOURCE_PAGE = "https://www.data.gov.in/resource/registrars-companies-roc-wise-company-master-data"
STATE_BROWSE_LIMIT = 100
NAME_LOOKUP_LIMIT = 10
_INACTIVE_MARKERS = ("strike", "struck", "dissolv", "liquidat", "amalgamat", "converted", "dormant")

COLUMNS = (
    "CORPORATE_IDENTIFICATION_NUMBER",
    "DATE_OF_REGISTRATION",
    "COMPANY_NAME",
    "COMPANY_STATUS",
    "COMPANY_CLASS",
    "COMPANY_CATEGORY",
    "AUTHORIZED_CAPITAL",
    "PAIDUP_CAPITAL",
    "REGISTERED_STATE",
    "REGISTRAR_OF_COMPANIES",
    "PRINCIPAL_BUSINESS_ACTIVITY",
    "REGISTERED_OFFICE_ADDRESS",
    "SUB_CATEGORY",
)


class OGDError(RuntimeError):
    pass


def field_ids_from_metadata(payload: dict) -> dict[str, str]:
    """Map column NAME -> API field id from the response's `field` list,
    defaulting to the lower-cased column name (the platform's usual id)."""
    ids = {name: name.lower() for name in COLUMNS}
    for entry in payload.get("field") or []:
        name = str(entry.get("name") or "").strip().upper()
        if name in ids and entry.get("id"):
            ids[name] = entry["id"]
    return ids


def get_column(record: dict, column: str, field_ids: dict[str, str]) -> Optional[str]:
    for key in (field_ids.get(column), column, column.lower()):
        if key and record.get(key) not in (None, "", "NA"):
            return str(record[key]).strip()
    return None


def is_active(status: Optional[str]) -> bool:
    lowered = (status or "").lower()
    return not any(marker in lowered for marker in _INACTIVE_MARKERS)


def _format_inr(value: Optional[str]) -> Optional[str]:
    try:
        amount = float(value) if value else None
    except ValueError:
        return value
    if amount is None:
        return None
    if amount >= 1e7:
        return f"₹{amount / 1e7:,.2f} crore"
    if amount >= 1e5:
        return f"₹{amount / 1e5:,.2f} lakh"
    return f"₹{amount:,.0f}"


def record_to_company(record: dict, field_ids: dict[str, str], source_url: str) -> Optional[DiscoveredCompany]:
    col = lambda c: get_column(record, c, field_ids)  # noqa: E731
    raw_name = col("COMPANY_NAME")
    if not raw_name:
        return None
    company = DiscoveredCompany(name=smart_title(raw_name), provider="mca")
    company.set("industry", col("PRINCIPAL_BUSINESS_ACTIVITY"), VERIFIED, SOURCE_NAME, source_url)
    company.set("state", smart_title(col("REGISTERED_STATE") or ""), VERIFIED, SOURCE_NAME, source_url)
    address = col("REGISTERED_OFFICE_ADDRESS")
    city = first_known_city(address, MAJOR_INDIAN_CITIES)
    company.set("city", city, INFERRED, f"{SOURCE_NAME} (from registered office address)", source_url)
    if address:
        company.location_hints.append(address)
        company.details["Registered office"] = smart_title(address)

    cin = col("CORPORATE_IDENTIFICATION_NUMBER")
    if cin:
        company.identifiers["cin"] = cin
    for label, column in (
        ("Registry status", "COMPANY_STATUS"),
        ("Company class", "COMPANY_CLASS"),
        ("Category", "COMPANY_CATEGORY"),
        ("Registered on", "DATE_OF_REGISTRATION"),
        ("Registrar", "REGISTRAR_OF_COMPANIES"),
    ):
        value = col(column)
        if value:
            company.details[label] = value
    paid_up = _format_inr(col("PAIDUP_CAPITAL"))
    if paid_up:
        company.details["Paid-up capital"] = paid_up
    company.sources.append(SourceRef(SOURCE_NAME, source_url))
    return company


def name_variants(name: str) -> list[str]:
    """Registered-name forms to try for an exact-match registry lookup."""
    typed = " ".join(name.upper().split())
    base = normalize_company_name(name).upper()
    variants = [typed]
    if base:
        variants += [f"{base} LIMITED", f"{base} PRIVATE LIMITED"]
    return list(dict.fromkeys(v for v in variants if v))


class McaProvider(CompanyDiscoveryProvider):
    key = "mca"
    label = "MCA company registry"
    description = (
        "Ministry of Corporate Affairs company master data on data.gov.in (official, "
        "~3.6M registered companies, snapshot to Nov 2023): CIN, registered state, "
        "principal business activity, status, paid-up capital."
    )
    requires_api_key = True
    setup_hint = "Set DATA_GOV_IN_API_KEY (free: register at data.gov.in, copy the key from My Account)."

    def __init__(self, fetch: Optional[Callable[[dict], dict]] = None):
        self._fetch_override = fetch
        self._field_ids: Optional[dict[str, str]] = None

    def is_configured(self) -> bool:
        return bool(settings.data_gov_in_api_key and settings.mca_resource_id)

    @property
    def source_url(self) -> str:
        if settings.mca_resource_id == "4dbe5667-7b6b-41d7-82af-211562424d9a":
            return DEFAULT_RESOURCE_PAGE
        return f"https://www.data.gov.in/resource/{settings.mca_resource_id}"

    # -- API access ----------------------------------------------------------
    def _fetch(self, params: dict) -> dict:
        if self._fetch_override:
            payload = self._fetch_override(params)
        else:
            payload = get_json(
                API_BASE + settings.mca_resource_id,
                {"api-key": settings.data_gov_in_api_key, "format": "json", **params},
            )
        if isinstance(payload, dict) and payload.get("error"):
            raise OGDError(str(payload["error"]))
        return payload

    def _ids(self) -> dict[str, str]:
        if self._field_ids is None:
            self._field_ids = field_ids_from_metadata(self._fetch({"limit": 1}))
        return self._field_ids

    def _query(self, filters: dict[str, str], limit: int) -> list[dict]:
        ids = self._ids()
        params = {"limit": limit, "offset": 0}
        for column, value in filters.items():
            params[f"filters[{ids[column]}]"] = value
        payload = self._fetch(params)
        return payload.get("records") or []

    # -- search ----------------------------------------------------------------
    def search(self, query: DiscoveryQuery) -> ProviderResult:
        notes: list[str] = []
        if query.name:
            records: list[dict] = []
            for variant in name_variants(query.name):
                records.extend(self._query({"COMPANY_NAME": variant}, NAME_LOOKUP_LIMIT))
        elif query.state:
            records = self._query({"REGISTERED_STATE": smart_title(query.state.upper())}, STATE_BROWSE_LIMIT)
            if not records:
                records = self._query({"REGISTERED_STATE": query.state.upper()}, STATE_BROWSE_LIMIT)
            records = [r for r in records if is_active(get_column(r, "COMPANY_STATUS", self._ids()))]
            notes.append(
                f"The government registry can only be browsed by exact state, so it contributes up to "
                f"{STATE_BROWSE_LIMIT} active companies registered in {smart_title(query.state.upper())}. "
                "Add a company name for a precise registry lookup."
            )
        else:
            return ProviderResult(
                notes=["The government registry (MCA) only supports searching by exact company name or state."]
            )

        ids = self._ids()
        seen: set[str] = set()
        companies = []
        for record in records:
            company = record_to_company(record, ids, self.source_url)
            if company is None:
                continue
            key = company.identifiers.get("cin") or company.name
            if key in seen:
                continue
            seen.add(key)
            companies.append(company)
        return ProviderResult(companies=companies, notes=notes)
