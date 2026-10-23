"""Wikidata provider - keyless, CC0-licensed, the default discovery source.

Wikidata holds structured records for ~3,500 notable Indian companies
(listed companies, PSUs, large private groups - the ones that actually
meet the Companies Act Section 135 CSR thresholds) with industry,
headquarters, official website, stock-exchange listings and ISIN.

How it's queried, and why:

* A live SPARQL query that filters *all* Indian companies by industry or
  location takes 15-45s on query.wikidata.org - too slow for a search
  box. So instead the provider keeps a small local index (one JSON file
  in DISCOVERY_CACHE_DIR, not the database) of every Indian company,
  built in the background in ~10 minutes of polite, paced requests
  and refreshed weekly (WIKIDATA_REFRESH_HOURS). Searches then filter
  that index locally - instant, and with full recall for industry/city/
  state filters.
* Until the first index build finishes, searches fall back to Wikidata's
  live full-text search (top 50 matches) so the feature works
  immediately; the response carries a note saying results are partial.

Usage policies followed: identifiable User-Agent (http.user_agent()),
sequential requests with a pause between batches, results cached so
repeat searches never hit Wikidata.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import requests

from ..config import settings
from .base import (
    INFERRED,
    VERIFIED,
    CompanyDiscoveryProvider,
    DiscoveredCompany,
    DiscoveryQuery,
    ProviderResult,
    SourceRef,
    name_contains,
    normalize_company_name,
)
from .http import get_json, resolve_backend_path, retry_delay, user_agent
from .matching import MAJOR_INDIAN_CITIES, first_known_city, is_known_city

logger = logging.getLogger("company_discovery.wikidata")

API_URL = "https://www.wikidata.org/w/api.php"
SPARQL_URL = "https://query.wikidata.org/sparql"
SOURCE_NAME = "Wikidata"
INDEX_VERSION = 3  # 3: all entities kept with their types; non-companies filtered at search time
DETAIL_BATCH_SIZE = 50
SEARCH_PAGE_SIZE = 500
LIVE_SEARCH_LIMIT = 50
BATCH_PAUSE_SECONDS = 2.0
RETRY_AFTER_FAILURE_SECONDS = 30 * 60

# "Located in India" plus "is some kind of company" - has an industry, is
# an instance of a business/company/bank/... class, or is listed on NSE
# or BSE. Used as a CirrusSearch filter (fast, index-backed) rather than a
# SPARQL subclass walk (slow).
_COMPANY_CLASSES = [
    "Q4830453",  # business
    "Q891723",  # public company
    "Q6881511",  # enterprise
    "Q783794",  # company
    "Q167037",  # corporation
    "Q219577",  # holding company
    "Q658255",  # subsidiary
    "Q22687",  # bank
]
NSE_QID = "Q638740"
BSE_QID = "Q638398"
INDIA_COMPANY_FILTER = "haswbstatement:P17=Q668 haswbstatement:" + "|".join(
    ["P452"] + [f"P31={q}" for q in _COMPANY_CLASSES] + [f"P414={NSE_QID}", f"P414={BSE_QID}"]
)
# Admin-territory classes that count as an Indian "state" for the HQ walk.
_STATE_CLASSES = ["Q12443800", "Q467745"]  # state of India, union territory of India
_EXCHANGE_SHORT_NAMES = {
    "National Stock Exchange of India": "NSE",
    "Bombay Stock Exchange": "BSE",
}


# Entity types ("instance of" labels) decide whether a Wikidata entity is a
# company you'd pitch for CSR funds. NGOs, universities and government
# bodies can carry an "industry" statement and so slip into the search.
#
# Hard exclusions always win, even over a business type: Agastya
# International Foundation is typed both "nonprofit organization" and
# "business".
_HARD_EXCLUDE_WORDS = (
    "nonprofit", "non-profit", "non-governmental", "charit", "foundation", "religious", "political party",
    "trade union", "government agency", "government department", "government organization",
    "governmental organization", "ministry", "statutory body", "think tank", "learned society",
    "trade association", "umbrella organization", "sports club", "stock exchange",
)
# Soft exclusions lose to an explicit legal company form: Apollo Hospitals
# is a "hospital network" *and* a "public company"; a coaching business can
# be an "educational institution" *and* a "privately held company".
_SOFT_EXCLUDE_WORDS = (
    "university", "college", "school", "higher education", "educational institution", "research institute",
    "hospital", "museum", "railway line", "stadium", "cricket field",
    # Real regulators (SEBI, RBI) aren't "Limited"; a state power company
    # mistyped "regulatory agency" (Gujarat Urja Vikas Nigam Limited) is.
    "regulatory",
)
_EXPLICIT_COMPANY_TYPES = (
    "privately held company", "public company", "public limited company", "private limited company",
    "joint-stock company", "listed company", "limited company", "state-owned enterprise",
    "public sector undertaking", "government-owned corporation", "multinational corporation",
)
# Matched as whole labels, not substrings ("human" vs "human resources company").
_NON_COMPANY_TYPES = {"human", "website", "family", "dynasty"}
_COMPANY_TYPE_WORDS = (
    "company", "business", "enterprise", "corporation", "bank", "manufacturer", "conglomerate", "firm",
    "insurer", "chain", "brand", "startup", "operator", "producer", "publisher", "airline", "cooperative",
    "utility", "retailer", "subsidiary", "group", "maker", "provider", "agency", "developer", "studio",
    "television", "channel", "broadcast", "newspaper", "record label", "distributor", "shipyard",
    "streaming", "network",
)
_FINANCIAL_INDUSTRY_WORDS = ("bank", "insurance", "financ")
_LEGAL_SUFFIX = re.compile(r"\b(limited|ltd\.?|pvt\.?|private limited)\s*$", re.IGNORECASE)


def looks_like_company(types: Optional[list[str]], name: str = "", industries: Optional[list[str]] = None) -> bool:
    """Keep businesses; drop NGOs, universities, government bodies,
    associations and untyped oddities (a person, a railway line). Records
    without type data (live results) are kept.
    """
    if not types:
        return True
    lowered = [t.lower() for t in types]
    has = lambda words: any(word in t for t in lowered for word in words)  # noqa: E731
    if has(_HARD_EXCLUDE_WORDS):
        return False
    # A registered legal name ("Indian Immunologicals Limited") outweighs a
    # mistaken type on Wikidata.
    if _LEGAL_SUFFIX.search(name or ""):
        return True
    if has(_SOFT_EXCLUDE_WORDS):
        return has(_EXPLICIT_COMPANY_TYPES)
    if any(t in _NON_COMPANY_TYPES for t in lowered) and not has(_COMPANY_TYPE_WORDS):
        return False
    if has(_COMPANY_TYPE_WORDS):
        return True
    # Vaguely typed ("organization") but clearly in banking/insurance, e.g.
    # regional rural banks.
    industry_text = " ".join(industries or []).lower()
    return any(word in industry_text for word in _FINANCIAL_INDUSTRY_WORDS)


def is_company_record(record: dict) -> bool:
    return looks_like_company(record.get("types"), record.get("name", ""), record.get("industries"))


def entity_url(qid: str) -> str:
    return f"https://www.wikidata.org/wiki/{qid}"


# ----------------------------------------------------------------------------
# Raw Wikidata access (network)
# ----------------------------------------------------------------------------
def _sparql(query: str, patient: bool = False) -> list[dict]:
    """Run a SPARQL query. The query service enforces a per-client budget of
    query time and answers 429 with Retry-After when it's exceeded; the
    background index build (patient=True) waits that out, an interactive
    search gives up quickly instead of making the user wait.
    """
    attempts = 6 if patient else 2
    for attempt in range(attempts):
        response = requests.post(
            SPARQL_URL,
            data={"query": query},
            headers={"User-Agent": user_agent(), "Accept": "application/sparql-results+json"},
            timeout=60,
        )
        if response.status_code in (429, 503) and attempt < attempts - 1:
            delay = retry_delay(response, attempt) if patient else 2.0
            logger.info("Wikidata query service busy (%s); retrying in %.0fs", response.status_code, delay)
            time.sleep(delay)
            continue
        response.raise_for_status()
        return response.json()["results"]["bindings"]
    raise RuntimeError("unreachable")


def cirrus_search(text: str, limit: int, offset: int = 0, patient: bool = False) -> tuple[list[str], Optional[int]]:
    """Wikidata full-text search restricted to Indian companies.

    Returns (QIDs, next offset or None when exhausted).
    """
    search = f"{text} {INDIA_COMPANY_FILTER}".strip()
    data = get_json(
        API_URL,
        {
            "action": "query",
            "list": "search",
            "srsearch": search,
            "srlimit": limit,
            "sroffset": offset,
            "srprop": "",
            "format": "json",
        },
        retries=5 if patient else 0,
    )
    qids = [hit["title"] for hit in data.get("query", {}).get("search", [])]
    next_offset = (data.get("continue") or {}).get("sroffset")
    return qids, next_offset


def build_detail_query(qids: list[str]) -> str:
    values = " ".join(f"wd:{q}" for q in qids)
    return f"""
SELECT ?c ?label ?desc
  (GROUP_CONCAT(DISTINCT ?alias; separator="|") AS ?aliases)
  (GROUP_CONCAT(DISTINCT ?indLabel; separator="|") AS ?industries)
  (SAMPLE(?hqItem) AS ?hqId) (SAMPLE(?hqLabel) AS ?hq)
  (SAMPLE(?site) AS ?website)
  (GROUP_CONCAT(DISTINCT ?exLabel; separator="|") AS ?exchanges)
  (SAMPLE(?isinValue) AS ?isin)
  (MAX(?emp) AS ?employees)
  (GROUP_CONCAT(DISTINCT ?typeLabel; separator="|") AS ?types)
WHERE {{
  VALUES ?c {{ {values} }}
  ?c rdfs:label ?label . FILTER(LANG(?label) = "en")
  OPTIONAL {{ ?c schema:description ?desc . FILTER(LANG(?desc) = "en") }}
  OPTIONAL {{ ?c skos:altLabel ?alias . FILTER(LANG(?alias) = "en") }}
  OPTIONAL {{ ?c wdt:P452 ?ind . ?ind rdfs:label ?indLabel . FILTER(LANG(?indLabel) = "en") }}
  OPTIONAL {{ ?c wdt:P159 ?hqItem . ?hqItem rdfs:label ?hqLabel . FILTER(LANG(?hqLabel) = "en") }}
  OPTIONAL {{ ?c wdt:P856 ?site }}
  OPTIONAL {{ ?c wdt:P414 ?ex . ?ex rdfs:label ?exLabel . FILTER(LANG(?exLabel) = "en") }}
  OPTIONAL {{ ?c wdt:P946 ?isinValue }}
  OPTIONAL {{ ?c wdt:P1128 ?emp }}
  OPTIONAL {{ ?c wdt:P31 ?type . ?type rdfs:label ?typeLabel . FILTER(LANG(?typeLabel) = "en") }}
}}
GROUP BY ?c ?label ?desc
"""


def build_state_query(hq_qids: list[str]) -> str:
    """For each HQ item: its Indian state, plus the labels of every place it
    sits inside (district, city, ...) - HQs are often a building or a
    locality ("Bombay House", "Hinjawadi") rather than the city itself.
    """
    values = " ".join(f"wd:{q}" for q in hq_qids)
    state_classes = " ".join(f"wd:{q}" for q in _STATE_CLASSES)
    return f"""
SELECT ?hq (SAMPLE(?stateLabel) AS ?state) (GROUP_CONCAT(DISTINCT ?placeLabel; separator="|") AS ?places) WHERE {{
  VALUES ?hq {{ {values} }}
  OPTIONAL {{
    VALUES ?stateClass {{ {state_classes} }}
    ?hq wdt:P131* ?st . ?st wdt:P31 ?stateClass .
    ?st rdfs:label ?stateLabel . FILTER(LANG(?stateLabel) = "en")
  }}
  OPTIONAL {{ ?hq wdt:P131+ ?place . ?place rdfs:label ?placeLabel . FILTER(LANG(?placeLabel) = "en") }}
}}
GROUP BY ?hq
"""


def _value(binding: dict, key: str) -> Optional[str]:
    cell = binding.get(key)
    return cell["value"] if cell and cell.get("value") else None


def _split(value: Optional[str]) -> list[str]:
    return [part for part in (value or "").split("|") if part]


def _qid(uri: Optional[str]) -> Optional[str]:
    return uri.rsplit("/", 1)[-1] if uri else None


def parse_detail_bindings(bindings: list[dict]) -> list[dict]:
    """Pure parsing of the detail query's JSON bindings into index records."""
    records = []
    for b in bindings:
        qid = _qid(_value(b, "c"))
        name = _value(b, "label")
        if not qid or not name:
            continue
        employees = _value(b, "employees")
        try:
            employee_count = int(float(employees)) if employees else None
        except ValueError:
            employee_count = None
        records.append(
            {
                "qid": qid,
                "name": name,
                "aliases": _split(_value(b, "aliases")),
                "description": _value(b, "desc"),
                "industries": _split(_value(b, "industries")),
                "hq": _value(b, "hq"),
                "hq_qid": _qid(_value(b, "hqId")),
                "state": None,
                "hq_places": [],
                "website": _value(b, "website"),
                "exchanges": _split(_value(b, "exchanges")),
                "isin": _value(b, "isin"),
                "employees": employee_count,
                "types": _split(_value(b, "types")),
            }
        )
    return records


def parse_state_bindings(bindings: list[dict]) -> dict[str, dict]:
    locations = {}
    for b in bindings:
        hq = _qid(_value(b, "hq"))
        if hq:
            places = [p for p in _split(_value(b, "places")) if p != "India"]
            locations[hq] = {"state": _value(b, "state"), "places": places}
    return locations


def fetch_records(
    qids: list[str], location_cache: Optional[dict[str, dict]] = None, pause: float = 0, patient: bool = False
) -> list[dict]:
    """Full records (with HQ state/admin places resolved) for a list of QIDs."""
    location_cache = location_cache if location_cache is not None else {}
    records: list[dict] = []
    for start in range(0, len(qids), DETAIL_BATCH_SIZE):
        if start and pause:
            time.sleep(pause)
        records.extend(
            parse_detail_bindings(_sparql(build_detail_query(qids[start : start + DETAIL_BATCH_SIZE]), patient))
        )

    missing = sorted({r["hq_qid"] for r in records if r["hq_qid"] and r["hq_qid"] not in location_cache})
    for start in range(0, len(missing), DETAIL_BATCH_SIZE):
        if pause:
            time.sleep(pause)
        batch = missing[start : start + DETAIL_BATCH_SIZE]
        location_cache.update(parse_state_bindings(_sparql(build_state_query(batch), patient)))

    for record in records:
        location = location_cache.get(record["hq_qid"] or "") or {}
        record["state"] = location.get("state")
        record["hq_places"] = location.get("places", [])
    return records


# ----------------------------------------------------------------------------
# Local index
# ----------------------------------------------------------------------------
class WikidataIndex:
    """All Indian companies on Wikidata, cached as one JSON file."""

    def __init__(self, cache_path: Path, refresh_hours: int, builder: Optional[Callable[[], list[dict]]] = None):
        self.cache_path = cache_path
        self.refresh_seconds = max(refresh_hours, 1) * 3600
        self._builder = builder or self._build_from_wikidata
        self._records: list[dict] = []
        self._built_at: float = 0.0
        self._lock = threading.Lock()
        self._building = False
        self.last_error: Optional[str] = None
        self._last_failure_at: float = 0.0
        self._loaded_from_disk = False

    # -- state ---------------------------------------------------------------
    @property
    def records(self) -> list[dict]:
        self._load_from_disk_once()
        return self._records

    def is_ready(self) -> bool:
        return bool(self.records)

    def is_building(self) -> bool:
        return self._building

    @property
    def built_at(self) -> float:
        return self._built_at

    def is_stale(self) -> bool:
        return not self.is_ready() or (time.time() - self._built_at) > self.refresh_seconds

    def set_records(self, records: list[dict], built_at: Optional[float] = None) -> None:
        self._loaded_from_disk = True
        self._records = records
        self._built_at = built_at if built_at is not None else time.time()

    def _load_from_disk_once(self) -> None:
        if self._loaded_from_disk:
            return
        self._loaded_from_disk = True
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(payload.get("records"), list):
            self._records = payload["records"]
            # An index from an older format keeps serving searches, but
            # counts as stale so a rebuild in the new format starts.
            current = payload.get("version") == INDEX_VERSION
            self._built_at = float(payload.get("built_at") or 0) if current else 0.0

    # -- building --------------------------------------------------------------
    def ensure_fresh(self, background: bool = True) -> None:
        """Kick off a rebuild if the index is missing or stale. Never blocks
        a search when background=True.
        """
        if not self.is_stale():
            return
        with self._lock:
            if self._building:
                return
            # After a failed build (Wikidata down, no network), wait before
            # trying again rather than starting a fresh 10-minute build on
            # every search.
            if time.time() - self._last_failure_at < RETRY_AFTER_FAILURE_SECONDS:
                return
            self._building = True
        if background:
            threading.Thread(target=self._rebuild, name="wikidata-index", daemon=True).start()
        else:
            self._rebuild()

    def _rebuild(self) -> None:
        try:
            started = time.time()
            records = self._builder()
            if not records:
                raise RuntimeError("Wikidata returned no companies")
            self.set_records(records, time.time())
            self._write_to_disk()
            self.last_error = None
            logger.info("Wikidata index built: %d companies in %.0fs", len(records), time.time() - started)
        except Exception as exc:  # network/parse failure - keep serving the old index
            self.last_error = str(exc)
            self._last_failure_at = time.time()
            logger.warning("Wikidata index build failed: %s", exc)
        finally:
            self._building = False

    def _write_to_disk(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"version": INDEX_VERSION, "built_at": self._built_at, "records": self._records}),
                encoding="utf-8",
            )
            tmp.replace(self.cache_path)
        except OSError as exc:
            # Read-only/ephemeral disk (e.g. some free hosting tiers): the
            # in-memory index still works, it's just rebuilt after a restart.
            logger.warning("Could not write Wikidata index cache: %s", exc)

    @staticmethod
    def _build_from_wikidata() -> list[dict]:
        qids: list[str] = []
        offset: Optional[int] = 0
        while offset is not None:
            batch, offset = cirrus_search("", SEARCH_PAGE_SIZE, offset, patient=True)
            qids.extend(batch)
            if offset is not None:
                time.sleep(BATCH_PAUSE_SECONDS)
        unique = list(dict.fromkeys(qids))
        # Every entity is kept, with its types; is_company_record() filters at
        # search time, so refining that rule never needs a rebuild.
        return fetch_records(unique, pause=BATCH_PAUSE_SECONDS, patient=True)


# ----------------------------------------------------------------------------
# Provider
# ----------------------------------------------------------------------------
def record_matches_name(record: dict, query_name: str) -> bool:
    wanted = normalize_company_name(query_name)
    if not wanted:
        return True
    names = [record["name"], *record.get("aliases", [])]
    return any(name_contains(normalize_company_name(n), wanted) for n in names) or any(
        query_name.strip().lower() == alias.lower() for alias in record.get("aliases", [])
    )


def record_to_company(record: dict) -> DiscoveredCompany:
    qid = record["qid"]
    url = entity_url(qid)
    company = DiscoveredCompany(
        name=record["name"],
        provider="wikidata",
        description=record.get("description"),
        aliases=record.get("aliases", []),
    )
    industries = record.get("industries") or []
    company.set("industry", ", ".join(industries[:3]) or None, VERIFIED, SOURCE_NAME, url)
    hq = record.get("hq")
    places = record.get("hq_places") or []
    if hq and not is_known_city(hq, MAJOR_INDIAN_CITIES):
        # HQ is a building/locality ("Bombay House"): show the city it's in,
        # derived from Wikidata's admin hierarchy - hence "inferred".
        parent_city = first_known_city(" | ".join(places), MAJOR_INDIAN_CITIES)
        if not parent_city and hq.lower().endswith(" district"):
            parent_city = first_known_city(hq, MAJOR_INDIAN_CITIES)  # "Mumbai City district"
        if parent_city:
            company.set("city", parent_city, INFERRED, f"{SOURCE_NAME} (from headquarters location)", url)
            company.details["headquarters"] = hq
        else:
            company.set("city", hq, VERIFIED, SOURCE_NAME, url)
    else:
        company.set("city", hq, VERIFIED, SOURCE_NAME, url)
    company.location_hints = [p for p in [hq, *places] if p]
    company.set("state", record.get("state"), INFERRED, f"{SOURCE_NAME} (from headquarters location)", url)
    company.set("website", record.get("website"), VERIFIED, SOURCE_NAME, url)
    company.set("employee_count", record.get("employees"), VERIFIED, SOURCE_NAME, url)
    company.identifiers["wikidata"] = qid
    if record.get("isin"):
        company.identifiers["isin"] = record["isin"]
    company.listed_on = [_EXCHANGE_SHORT_NAMES.get(ex, ex) for ex in record.get("exchanges", [])]
    company.sources.append(SourceRef(SOURCE_NAME, url))
    return company


class WikidataProvider(CompanyDiscoveryProvider):
    key = "wikidata"
    label = "Wikidata"
    description = (
        "Open, CC0-licensed knowledge base. Covers ~3,500 notable Indian companies "
        "(listed companies, PSUs, large groups) with industry, HQ and website."
    )
    requires_api_key = False
    setup_hint = "No key needed. Set DISCOVERY_CONTACT to an email/URL so Wikimedia can reach you."

    def __init__(self, index: Optional[WikidataIndex] = None, live_search: Optional[Callable] = None):
        self.index = index or WikidataIndex(
            resolve_backend_path(settings.discovery_cache_dir) / "wikidata_companies.json",
            settings.wikidata_refresh_hours,
        )
        self._live_search = live_search or self._live_search_wikidata

    def is_configured(self) -> bool:
        return settings.wikidata_enabled

    def status(self) -> Optional[str]:
        if self.index.is_ready():
            if self.index.built_at > 0:
                updated = "updated " + time.strftime("%d %b %Y", time.localtime(self.index.built_at))
            else:
                updated = "from an earlier app version"
            if self.index.is_building():
                suffix = " (refreshing now)"
            elif self.index.last_error:
                suffix = " (last refresh failed - will retry later; current index still in use)"
            else:
                suffix = ""
            return f"{len(self.index.records):,} Indian companies indexed, {updated}{suffix}"
        if self.index.is_building():
            return "Preparing the company index (first run takes about 10 minutes); live search works meanwhile"
        if self.index.last_error:
            return f"Index unavailable ({self.index.last_error}); using live search"
        return "Company index will be prepared on first search"

    def search(self, query: DiscoveryQuery) -> ProviderResult:
        self.index.ensure_fresh(background=True)
        if self.index.is_ready():
            records = [
                r for r in self.index.records
                if is_company_record(r) and record_matches_name(r, query.name)
            ]
            return ProviderResult(companies=[record_to_company(r) for r in records])

        records = self._live_search(query)
        note = (
            "The full Wikidata company index is still being prepared (first run takes about "
            "10 minutes), so Wikidata results are limited to the top matches for now."
        )
        if self.index.last_error:
            note = f"Wikidata index could not be built ({self.index.last_error}); showing live top matches only."
        return ProviderResult(companies=[record_to_company(r) for r in records], notes=[note])

    @staticmethod
    def _live_search_wikidata(query: DiscoveryQuery) -> list[dict]:
        # Full-text search on the most specific term available; the service
        # applies the remaining filters to whatever comes back.
        text = query.name or query.industry or query.city or query.state
        if not query.name and query.industry and " " not in text and len(text) >= 4:
            text += "*"  # "pharma" should find "pharmaceutical company" descriptions
        qids, _ = cirrus_search(text, LIVE_SEARCH_LIMIT)
        records = fetch_records(qids) if qids else []
        return [r for r in records if is_company_record(r)]
