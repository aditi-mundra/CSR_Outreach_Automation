"""Infer a company's CSR focus areas from its own public CSR web pages.

No open dataset gives CSR focus for most companies (the National CSR
Portal does, but only as a manual download - see datasets.py). As a
fallback, this reads the company's *own* published CSR/sustainability
pages and looks for Schedule VII activity keywords. The result is always
labelled "inferred", with the pages it was inferred from, because keyword
counting can't tell "we fund 200 schools" from "our office is next to a
school".

Uses the same etiquette as the Phase 2 contact scraper (scraping.py):
identifiable User-Agent, robots.txt honoured per URL, a pause between
requests, the company's own domain only, and a hard page cap.
"""

from __future__ import annotations

import html as html_lib
import ipaddress
import re
import socket
import time
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

from .. import scraping
from .matching import CSR_FOCUS_KEYWORDS

CSR_PATHS = ["/csr", "/corporate-social-responsibility", "/sustainability", "/esg", "/about-us/csr"]
MAX_PAGES = 5
MIN_MENTIONS = 2
MAX_AREAS = 4

_CSR_URL_HINTS = ("csr", "social-responsib", "sustainab", "foundation", "esg", "community", "responsib")
_REPORT_HINTS = ("csr", "sustainab", "brsr", "business-responsibility", "esg", "annual-report", "annual_report")
_ANCHOR = re.compile(r"<a\s[^>]*href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)


def is_public_website(url: str) -> bool:
    """True only for http(s) URLs whose host resolves exclusively to public
    internet addresses. The CSR-focus endpoint fetches whatever URL it's
    given, so this stops it being pointed at the server's own network
    (localhost, 10.x/192.168.x, cloud metadata at 169.254.169.254, ...).
    """
    parsed = urlparse(url if "://" in url else f"https://{url}")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, ValueError):
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(ipaddress.ip_address(a.split("%", 1)[0]).is_global for a in addresses)


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip().lower()


def find_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """(absolute URL, lower-cased anchor text) for each link on the page."""
    links = []
    for href, label in _ANCHOR.findall(html):
        links.append((urljoin(base_url, href.strip()), html_to_text(label)))
    return links


def _same_site(url: str, base: str) -> bool:
    strip = lambda netloc: netloc.lower().removeprefix("www.")  # noqa: E731
    return strip(urlparse(url).netloc) == strip(urlparse(base).netloc)


def is_csr_page(url: str, text: str) -> bool:
    path = urlparse(url).path.lower()
    return any(h in path for h in _CSR_URL_HINTS) or "corporate social responsibility" in text


def score_focus_areas(text: str) -> dict[str, int]:
    counts = {}
    for area, keywords in CSR_FOCUS_KEYWORDS.items():
        hits = sum(len(re.findall(rf"\b{re.escape(k)}", text)) for k in keywords)
        if hits:
            counts[area] = hits
    return counts


def find_report_link(links: list[tuple[str, str]]) -> Optional[str]:
    for url, label in links:
        lowered = url.lower()
        if lowered.endswith(".pdf") and (any(h in lowered for h in _REPORT_HINTS) or any(
            h in label for h in ("csr", "sustainability", "business responsibility", "annual report", "esg")
        )):
            return url
    return None


def infer_csr_focus(website: str, fetch: Optional[Callable[[str], Optional[str]]] = None) -> dict:
    """Read a company's CSR pages and infer focus areas.

    Returns {csr_focus, areas: [{area, mentions}], source_urls,
    csr_report_url, pages_checked, message}. `message` explains an empty
    result in plain language. Never raises on network errors.
    """
    fetch = fetch or scraping._fetch_page
    base = scraping._base_url(website)
    result = {
        "csr_focus": None, "areas": [], "source_urls": [], "csr_report_url": None, "pages_checked": [],
        "message": None,
    }
    if base is None:
        result["message"] = "That doesn't look like a website address."
        return result

    robots = scraping._load_robots(base) if fetch is scraping._fetch_page else None
    allowed = lambda url: robots is None or robots.can_fetch(scraping.USER_AGENT, url)  # noqa: E731

    # Home page first: it usually links to the real CSR page, whatever it's called.
    queue = [base + "/"]
    queue += [urljoin(base, p) for p in CSR_PATHS]
    visited: set[str] = set()
    totals: dict[str, int] = {}
    report_link = None
    blocked = readable = csr_pages = 0

    while queue and len(result["pages_checked"]) < MAX_PAGES:
        url = queue.pop(0)
        if url in visited:
            continue
        if not allowed(url):
            visited.add(url)
            blocked += 1
            continue
        visited.add(url)
        if result["pages_checked"] and fetch is scraping._fetch_page:
            time.sleep(scraping.REQUEST_DELAY_SECONDS)
        html = fetch(url)
        result["pages_checked"].append(url)
        if not html or len(html_to_text(html)) < 40:
            continue  # error page, or a JavaScript-only shell with no text
        readable += 1

        links = [(u, label) for u, label in find_links(html, url) if _same_site(u, base) or u.lower().endswith(".pdf")]
        report_link = report_link or find_report_link(links)
        # Prioritise in-site links that look like the CSR page.
        csr_links = [
            u for u, label in links
            if _same_site(u, base) and not u.lower().endswith(".pdf")
            and (any(h in u.lower() for h in _CSR_URL_HINTS) or "csr" in label or "social responsibility" in label)
        ]
        queue = [u for u in csr_links if u not in visited] + queue

        text = html_to_text(html)
        if not is_csr_page(url, text):
            continue
        csr_pages += 1
        page_counts = score_focus_areas(text)
        if page_counts:
            result["source_urls"].append(url)
        for area, hits in page_counts.items():
            totals[area] = totals.get(area, 0) + hits

    ranked = sorted(((a, n) for a, n in totals.items() if n >= MIN_MENTIONS), key=lambda x: -x[1])[:MAX_AREAS]
    result["areas"] = [{"area": a, "mentions": n} for a, n in ranked]
    result["csr_focus"] = ", ".join(a for a, _ in ranked) or None
    result["csr_report_url"] = report_link
    if not ranked:
        if blocked and not result["pages_checked"]:
            result["message"] = (
                "This company's website asks automated tools not to read it (robots.txt), so its CSR "
                "focus wasn't checked. Open the website to look manually."
            )
        elif not readable:
            result["message"] = (
                "The website didn't return readable pages (it may load its content with JavaScript). "
                "Open the website to look manually."
            )
        elif not csr_pages:
            result["message"] = "No CSR page was found on the company's website."
        else:
            result["message"] = "The company's CSR pages don't clearly mention any Schedule VII focus area."
    return result
