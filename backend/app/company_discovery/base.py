"""Provider interface and shared types for real-company discovery.

Discovery searches *public* sources for companies that are not (yet) in
the NGO's own database. Nothing found here is persisted until a user
clicks "Save as lead" - see routers/company_discovery.py.

Every field on a discovered company carries a provenance status so the
UI can be honest about how much to trust it:

    verified     - taken directly from a named public source record
                   (Wikidata statement, MCA registry row, an official
                   dataset file the NGO downloaded). The source is always
                   attached so staff can check it.
    inferred     - derived by this app rather than stated by a source
                   (e.g. state worked out from the HQ city's admin
                   hierarchy, CSR focus guessed from keywords on the
                   company's own CSR page).
    unavailable  - no configured source has it.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

VERIFIED = "verified"
INFERRED = "inferred"
UNAVAILABLE = "unavailable"

# Fields that carry per-field provenance. These are the ones that map onto
# the Company model when a result is saved as a lead.
TRACKED_FIELDS = (
    "industry",
    "city",
    "state",
    "website",
    "csr_focus",
    "csr_spending",
    "employee_count",
    "csr_report_url",
)


@dataclass
class DiscoveryQuery:
    name: str = ""
    industry: str = ""
    city: str = ""
    state: str = ""
    csr_focus: str = ""

    def __post_init__(self) -> None:
        for attr in ("name", "industry", "city", "state", "csr_focus"):
            setattr(self, attr, (getattr(self, attr) or "").strip())

    def is_empty(self) -> bool:
        return not any((self.name, self.industry, self.city, self.state, self.csr_focus))

    def cache_key(self) -> tuple:
        return tuple(v.lower() for v in (self.name, self.industry, self.city, self.state, self.csr_focus))


@dataclass
class FieldProvenance:
    status: str
    source: Optional[str] = None
    source_url: Optional[str] = None


@dataclass
class SourceRef:
    name: str
    url: Optional[str] = None


@dataclass
class DiscoveredCompany:
    name: str
    provider: str
    description: Optional[str] = None
    aliases: list[str] = field(default_factory=list)
    values: dict = field(default_factory=dict)
    provenance: dict[str, FieldProvenance] = field(default_factory=dict)
    # Stable cross-source identifiers used for merging (wikidata QID, CIN,
    # ISIN, NSE/BSE symbols, ...) and shown to staff as reference.
    identifiers: dict[str, str] = field(default_factory=dict)
    listed_on: list[str] = field(default_factory=list)
    # Extra read-only facts worth showing but not saved onto the Company
    # model (registry status, paid-up capital, registration date, ...).
    details: dict[str, str] = field(default_factory=dict)
    sources: list[SourceRef] = field(default_factory=list)
    # Extra place names the city filter should also match (an HQ's
    # district/parent city, a registered-office address). Not displayed.
    location_hints: list[str] = field(default_factory=list)

    def set(self, name: str, value, status: str, source: str, source_url: Optional[str] = None) -> None:
        """Record a field value with its provenance; empty values are ignored."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return
        self.values[name] = value.strip() if isinstance(value, str) else value
        self.provenance[name] = FieldProvenance(status=status, source=source, source_url=source_url)


@dataclass
class ProviderResult:
    companies: list[DiscoveredCompany] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class CompanyDiscoveryProvider(ABC):
    """A public source of company records.

    Providers own *name* matching (they know their own search semantics -
    Wikidata matches aliases like "TCS", the MCA registry needs exact
    registered names). Industry/city/state/CSR-focus filtering is applied
    uniformly by the service afterwards, so providers may return a
    superset for those.
    """

    key: str = ""
    label: str = ""
    description: str = ""
    requires_api_key: bool = False
    setup_hint: str = ""

    def is_configured(self) -> bool:
        return True

    def status(self) -> Optional[str]:
        """Short human-readable state for the "Data sources" panel."""
        return None

    @abstractmethod
    def search(self, query: DiscoveryQuery) -> ProviderResult:
        ...


# ----------------------------------------------------------------------------
# Normalization helpers shared by providers and the merge step
# ----------------------------------------------------------------------------
_LEGAL_SUFFIXES = {
    "limited",
    "ltd",
    "private",
    "pvt",
    "pvt.",
    "plc",
    "inc",
    "incorporated",
    "corporation",
    "corp",
    "company",
    "co",
    "the",
}


def normalize_company_name(name: str) -> str:
    """Name key for cross-source merging: "TATA STEEL LIMITED", "Tata Steel
    Ltd." and "Tata Steel" all normalize to "tata steel".
    """
    if not name:
        return ""
    lowered = name.lower().replace("&", " and ")
    lowered = re.sub(r"\([^)]*\)", " ", lowered)  # "(India)", "(Formerly ...)"
    words = re.findall(r"[a-z0-9]+", lowered)
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    while words and words[0] == "the":
        words.pop(0)
    return " ".join(words)


def name_contains(normalized_name: str, normalized_query: str) -> bool:
    """Query matches at word starts: "tata" finds "tata steel" and "the
    tata power", but not "vitatalk".
    """
    if not normalized_query:
        return True
    return re.search(rf"(?:^| ){re.escape(normalized_query)}", normalized_name) is not None


def normalize_domain(website: Optional[str]) -> str:
    if not website:
        return ""
    domain = website.strip().lower()
    domain = re.sub(r"^[a-z]+://", "", domain)
    domain = re.sub(r"^www\.", "", domain)
    return domain.split("/", 1)[0]


def smart_title(text: str) -> str:
    """Title-case an ALL-CAPS registry name for display without mangling
    already mixed-case names ("HDFC Bank" stays as-is).
    """
    if not text or not text.isupper():
        return text
    keep_upper = {"ii", "iii", "iv", "llp", "it", "hdfc", "icici", "lic", "ntpc", "ongc", "bhel", "gail", "sbi"}
    words = []
    for word in text.split():
        stripped = re.sub(r"[^a-z]", "", word.lower())
        words.append(word if stripped in keep_upper else word.capitalize())
    return " ".join(words)
