"""Third-party contact-enrichment integrations (Phase 2).

Looks up verified names/emails for CSR-relevant titles ("CSR Manager",
"Sustainability Head", "Foundation Director", "HR Head", "Corporate
Communications Head", ...) at a company's domain via Hunter.io and/or
Apollo.io. Both are optional - each is skipped when its API key isn't
configured (see app/config.py, HUNTER_API_KEY / APOLLO_API_KEY).
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional
from urllib.parse import urlparse

import requests

from .config import settings

logger = logging.getLogger("enrichment")

REQUEST_TIMEOUT_SECONDS = 8

CSR_TITLE_KEYWORDS = [
    "csr",
    "corporate social responsibility",
    "sustainability",
    "foundation",
    "community",
    "hr",
    "human resources",
    "corporate communications",
]


def is_configured() -> bool:
    return bool(settings.hunter_api_key or settings.apollo_api_key)


def extract_domain(website: str) -> Optional[str]:
    if not website:
        return None
    parsed = urlparse(website if "://" in website else f"https://{website}")
    domain = parsed.netloc or parsed.path
    return re.sub(r"^www\.", "", domain).strip().lower() or None


def _title_matches_csr(title: Optional[str]) -> bool:
    if not title:
        return False
    lowered = title.lower()
    return any(keyword in lowered for keyword in CSR_TITLE_KEYWORDS)


TitleFilter = Callable[[Optional[str]], bool]


def parse_hunter_response(data: dict, domain: str, title_filter: TitleFilter = _title_matches_csr) -> list[dict]:
    """Pure parsing of Hunter.io's domain-search response body.

    `title_filter` decides which positions are kept - contact discovery
    passes its own role classifier (app/contact_discovery/roles.py).
    """
    emails = (data.get("data") or {}).get("emails") or []
    results = []
    for entry in emails:
        position = entry.get("position")
        if not title_filter(position):
            continue
        name = " ".join(filter(None, [entry.get("first_name"), entry.get("last_name")])) or None
        results.append(
            {
                "name": name,
                "designation": position,
                "email": entry.get("value"),
                "phone": entry.get("phone_number"),
                "linkedin_url": entry.get("linkedin"),
                "source_url": f"https://hunter.io/domain-search/{domain}",
            }
        )
    return results


def hunter_domain_search(domain: str, title_filter: TitleFilter = _title_matches_csr) -> list[dict]:
    if not settings.hunter_api_key:
        return []
    try:
        response = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": settings.hunter_api_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Hunter.io lookup failed for %s: %s", domain, exc)
        return []
    return parse_hunter_response(response.json(), domain, title_filter)


def parse_apollo_response(data: dict, title_filter: TitleFilter = _title_matches_csr) -> list[dict]:
    """Pure parsing of Apollo.io's people-search response body."""
    people = data.get("people") or []
    results = []
    for person in people:
        title = person.get("title")
        if not title_filter(title):
            continue
        results.append(
            {
                "name": person.get("name"),
                "designation": title,
                "email": person.get("email"),
                "phone": person.get("sanitized_phone"),
                "linkedin_url": person.get("linkedin_url"),
                "source_url": "https://app.apollo.io/",
            }
        )
    return results


def apollo_people_search(domain: str, title_filter: TitleFilter = _title_matches_csr) -> list[dict]:
    if not settings.apollo_api_key:
        return []
    try:
        response = requests.post(
            "https://api.apollo.io/v1/mixed_people/search",
            json={"api_key": settings.apollo_api_key, "q_organization_domains": domain, "page": 1},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Apollo.io lookup failed for %s: %s", domain, exc)
        return []
    return parse_apollo_response(response.json(), title_filter)


def enrich_company_contacts(website: str) -> list[dict]:
    domain = extract_domain(website)
    if not domain:
        return []
    return hunter_domain_search(domain) + apollo_people_search(domain)
