"""Uniform, forgiving text matching for discovery filters.

Different sources spell the same thing differently: Wikidata says
"Bengaluru" and "pharmaceutical industry", the MCA registry says
"BANGALORE" and "Manufacturing (Metals & Chemicals, and products
thereof)", NGO staff type "Bangalore" and "pharma". These helpers keep
the matching rules in one place so every provider is filtered the same
way.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

# Renamed Indian cities - either spelling should find the other.
_CITY_ALIASES = [
    {"bengaluru", "bangalore"},
    {"mumbai", "bombay"},
    {"chennai", "madras"},
    {"kolkata", "calcutta"},
    {"gurugram", "gurgaon"},
    {"pune", "poona"},
    {"mysuru", "mysore"},
    {"vadodara", "baroda"},
    {"thiruvananthapuram", "trivandrum"},
    {"kochi", "cochin"},
    {"puducherry", "pondicherry"},
    {"prayagraj", "allahabad"},
    {"new delhi", "delhi"},
    {"navi mumbai", "new bombay"},
    {"visakhapatnam", "vizag"},
]

_STATE_ALIASES = [
    {"delhi", "national capital territory of delhi", "nct of delhi", "new delhi"},
    {"odisha", "orissa"},
    {"uttarakhand", "uttaranchal"},
    {"puducherry", "pondicherry"},
    {"tamil nadu", "tamilnadu"},
]

# Short or jargon industry terms staff commonly type, expanded to the words
# sources actually use. Matching is still substring-based on the expansions.
_INDUSTRY_SYNONYMS = {
    "it": ["information technology", "software", "it service", "it consulting"],
    "ites": ["information technology", "outsourcing", "business process"],
    "bpo": ["business process", "outsourcing"],
    "fmcg": ["consumer goods", "fast-moving", "food", "personal care"],
    "pharma": ["pharma"],
    "auto": ["automotive", "automobile", "vehicle"],
    "automobile": ["automotive", "automobile", "vehicle"],
    "bank": ["bank", "financial"],
    "banking": ["bank", "financial"],
    "finance": ["financ", "bank", "insurance", "investment"],
    "nbfc": ["financ", "non-banking"],
    "telecom": ["telecom", "communication"],
    "infra": ["infrastructure", "construction"],
    "steel": ["steel", "metal"],
    "energy": ["energy", "power", "electricity", "oil", "gas"],
    "power": ["power", "electricity", "energy"],
    "food": ["food"],
    "textile": ["textile", "apparel", "garment"],
    "cement": ["cement", "building material"],
    "chemical": ["chemical"],
    "media": ["media", "broadcast", "entertainment", "publishing"],
}

# Schedule VII (Companies Act, 2013) aligned CSR focus areas and the
# keywords that indicate them. Used both to match the CSR-focus filter
# against free-text focus values and to infer focus areas from a
# company's own CSR web page.
CSR_FOCUS_KEYWORDS: dict[str, list[str]] = {
    "Education": ["education", "school", "scholarship", "literacy", "learning", "students", "teacher"],
    "Healthcare": ["health", "hospital", "medical", "healthcare", "nutrition", "malnutrition", "disease"],
    "Environment": ["environment", "climate", "tree plantation", "afforestation", "biodiversity", "renewable", "conservation"],
    "Rural Development": ["rural development", "village", "rural"],
    "Women Empowerment": ["women empowerment", "women", "gender", "girl child"],
    "Water & Sanitation": ["sanitation", "drinking water", "water conservation", "toilet", "hygiene", "swachh"],
    "Skill Development": ["skill development", "vocational", "skilling", "employability", "livelihood"],
    "Hunger & Poverty": ["hunger", "poverty", "food security", "mid-day meal"],
    "Arts & Culture": ["heritage", "culture", "arts", "handicraft"],
    "Sports": ["sports", "athlete"],
    "Disaster Relief": ["disaster", "relief", "flood"],
    "Animal Welfare": ["animal welfare", "animal"],
    "Armed Forces Veterans": ["veterans", "armed forces", "war widows"],
}


def _norm(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _alias_set(term: str, groups: list[set[str]]) -> set[str]:
    term = _norm(term)
    for group in groups:
        if term in group:
            return set(group)
    return {term}


def matches_city(query_city: str, *candidates: Optional[str]) -> bool:
    """True if any candidate (HQ city, registered address, ...) contains
    the queried city or one of its alternate spellings.
    """
    if not query_city:
        return True
    haystack = " | ".join(_norm(c) for c in candidates if c)
    if not haystack:
        return False
    return any(re.search(rf"\b{re.escape(alias)}\b", haystack) for alias in _alias_set(query_city, _CITY_ALIASES))


def matches_state(query_state: str, state: Optional[str]) -> bool:
    if not query_state:
        return True
    if not state:
        return False
    haystack = _norm(state)
    return any(alias in haystack for alias in _alias_set(query_state, _STATE_ALIASES))


def industry_terms(query_industry: str) -> list[str]:
    term = _norm(query_industry)
    if not term:
        return []
    return _INDUSTRY_SYNONYMS.get(term, [term])


def matches_industry(query_industry: str, *candidates: Optional[str]) -> bool:
    """Substring match of the queried industry (or its synonym expansion)
    against industry labels and the company's description.
    """
    terms = industry_terms(query_industry)
    if not terms:
        return True
    haystack = " | ".join(_norm(c) for c in candidates if c)
    if not haystack:
        return False
    for term in terms:
        # Very short terms ("it") must match as whole words, otherwise they
        # match inside every other word ("capital", "unit", ...).
        pattern = rf"\b{re.escape(term)}\b" if len(term) <= 3 else re.escape(term)
        if re.search(pattern, haystack):
            return True
    return False


def csr_focus_areas_for_text(text: str) -> list[str]:
    """Canonical Schedule VII focus areas mentioned in a free-text value."""
    lowered = _norm(text)
    return [area for area, keywords in CSR_FOCUS_KEYWORDS.items() if any(k in lowered for k in keywords)]


def matches_csr_focus(query_focus: str, focus_value: Optional[str]) -> bool:
    if not query_focus:
        return True
    if not focus_value:
        return False
    if _norm(query_focus) in _norm(focus_value):
        return True
    wanted = set(csr_focus_areas_for_text(query_focus))
    return bool(wanted & set(csr_focus_areas_for_text(focus_value)))


def is_known_city(text: Optional[str], cities: Iterable[str]) -> bool:
    """Exact (alias-aware) match - "Bengaluru" or "Bangalore" yes, but not
    "Bombay House", which merely *contains* a city's old name.
    """
    wanted = _norm(text)
    return any(wanted in _alias_set(city, _CITY_ALIASES) for city in cities)


def first_known_city(text: Optional[str], cities: Iterable[str]) -> Optional[str]:
    """The city from `cities` mentioned in a free-text address. When several
    appear ("Mumbai-Pune Highway, Pune 411001") the last one wins, since
    Indian addresses end with the city, state and PIN code.
    """
    haystack = _norm(text)
    if not haystack:
        return None
    best, best_pos = None, -1
    for city in cities:
        for alias in _alias_set(city, _CITY_ALIASES):
            for match in re.finditer(rf"\b{re.escape(alias)}\b", haystack):
                if match.start() > best_pos:
                    best, best_pos = city, match.start()
    return best


# Major Indian cities, used only to *infer* a city from an unstructured
# registered-office address (marked "inferred", never "verified").
MAJOR_INDIAN_CITIES = [
    "Mumbai", "Navi Mumbai", "Thane", "Pune", "Nagpur", "Nashik", "Aurangabad",
    "New Delhi", "Delhi", "Noida", "Gurugram", "Faridabad", "Ghaziabad",
    "Bengaluru", "Mysuru", "Mangaluru", "Hyderabad", "Secunderabad", "Visakhapatnam",
    "Vijayawada", "Chennai", "Coimbatore", "Madurai", "Kolkata", "Howrah",
    "Ahmedabad", "Surat", "Vadodara", "Rajkot", "Jaipur", "Jodhpur", "Udaipur",
    "Lucknow", "Kanpur", "Varanasi", "Prayagraj", "Chandigarh", "Ludhiana",
    "Amritsar", "Bhopal", "Indore", "Raipur", "Bhubaneswar", "Patna", "Ranchi",
    "Jamshedpur", "Guwahati", "Kochi", "Thiruvananthapuram", "Kozhikode",
    "Goa", "Panaji", "Dehradun", "Shimla", "Srinagar", "Jammu", "Puducherry",
]
