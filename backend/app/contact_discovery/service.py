"""Find contacts for one company: crawl, extract, merge, score, explain.

Flow for one "Find contacts" run:
  1. read the company's own site - home page first, then the in-site
     pages it links to that look like CSR / committee / leadership /
     contact / press pages (robots.txt honoured per URL, identifiable
     User-Agent, a pause between requests, a page cap and a time budget);
  2. optionally read the CSR / annual report PDF for the CSR Committee;
  3. optionally ask Hunter.io / Apollo.io, when their keys are set;
  4. merge every sighting of the same person, attach per-field
     provenance (verified / inferred / unavailable) and a confidence
     score with its reasons, and sort by priority then confidence.

Nothing is stored here - the router logs the run and staff choose what
to save. LinkedIn is never fetched: when no profile link is published,
the result carries a LinkedIn *search* link staff can open themselves.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from .. import enrichment, scraping
from ..company_discovery.base import INFERRED, UNAVAILABLE, VERIFIED, normalize_company_name
from ..company_discovery.csr_focus import is_public_website
from . import extract, policy, reports, roles

logger = logging.getLogger("contact_discovery")

MAX_PAGES = 12
CRAWL_TIME_BUDGET_SECONDS = 45
CACHE_TTL_SECONDS = 600
CACHE_MAX_ENTRIES = 50

# (rank, pattern on URL path + anchor text) - lower rank is read first.
_PAGE_HINTS: list[tuple[int, re.Pattern]] = [
    (0, re.compile(r"committee", re.I)),
    (1, re.compile(r"csr|corporate[-_ ]social|social[-_ ]responsib|foundation|sustainab|esg|community", re.I)),
    (2, re.compile(r"leader|management|executive|our[-_ ]team|team|people|key[-_ ]person", re.I)),
    (3, re.compile(r"contact|reach[-_ ]us|get[-_ ]in[-_ ]touch|offices|locations", re.I)),
    # Directors matter only as CSR Committee members; committee pages rank first.
    (4, re.compile(r"board|director", re.I)),
    (5, re.compile(r"press|media|news|blog", re.I)),
    (6, re.compile(r"governance|about", re.I)),
]
# Most pages read per kind, so one large section (Wipro's dozens of
# /sustainability/* product pages) can't use up the whole page cap before
# the leadership and contact pages are reached.
_RANK_BUDGET = {0: 3, 1: 4, 2: 4, 3: 2, 4: 2, 5: 2, 6: 2}
_PRESS_PATH = _PAGE_HINTS[5][1]
MAX_REPORTS = 2
# Where a CSR Committee is named, best first: the annual report (CSR
# annexure + governance report), the BRSR, then CSR / sustainability reports.
_REPORT_RANK = [
    re.compile(r"annual[-_ %20]*report|integrated[-_ %20]*report", re.I),
    re.compile(r"brsr|business[-_ %20]*responsib", re.I),
    re.compile(r"csr", re.I),
    re.compile(r"sustainab|esg", re.I),
]


def rank_report_links(urls: list[str]) -> list[str]:
    """De-duplicated report PDFs, most likely to name the CSR Committee
    first. PDFs under press/news paths (press releases) are dropped.
    """
    unique = []
    for url in urls:
        if url and url not in unique and not _PRESS_PATH.search(urlparse(url).path.rsplit("/", 1)[0]):
            unique.append(url)
    rank = lambda url: next((i for i, p in enumerate(_REPORT_RANK) if p.search(url)), len(_REPORT_RANK))  # noqa: E731
    return sorted(unique, key=rank)
_SKIP_LINK = re.compile(
    r"career|job|login|signin|sign-in|register|privacy|terms|cookie|sitemap|disclaimer|financial|shareholding|"
    r"dividend|quarterly|results|postal-ballot|investor-services|directorships|\.(jpg|jpeg|png|gif|svg|zip|"
    r"docx?|xlsx?|pptx?|mp4|mp3)$|^mailto:|^tel:|^javascript:",
    re.I,
)
_REPORT_LINK = re.compile(r"csr|sustainab|brsr|business[-_ ]responsib|esg|annual[-_ ]?report", re.I)
FALLBACK_PATHS = [
    "/csr", "/sustainability", "/about-us/leadership", "/leadership", "/management", "/board-of-directors",
    "/contact-us", "/about-us",
]

_METHOD_RANK = {"structured": 0, "listing": 1, "inline": 1, "committee": 2, "report": 2, "prose": 3, "third_party": 4}
_METHOD_BASE = {"structured": 60, "listing": 50, "inline": 50, "committee": 55, "report": 60, "prose": 40, "third_party": 40}
_METHOD_LABEL = {
    "structured": "structured profile data on the company's website",
    "listing": "listed with this title on the company's website",
    "inline": "named with this title on the company's website",
    "committee": "CSR Committee member list on the company's website",
    "report": "named in the company's CSR / annual report",
    "prose": "quoted with this title in the company's own news/press page",
    "third_party": "returned by a contact-data provider",
}


@dataclass
class CompanyContext:
    name: str
    website: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    industry: Optional[str] = None
    csr_report_url: Optional[str] = None
    company_id: Optional[int] = None


@dataclass
class _Candidate:
    key: str
    name: str
    hits: list = field(default_factory=list)  # PersonHit / mailbox dicts
    is_mailbox: bool = False
    mailbox_email: Optional[str] = None
    mailbox_label: Optional[str] = None
    mailbox_priority: Optional[int] = None
    mailbox_url: Optional[str] = None


def _prov(status: str, source: Optional[str] = None, source_url: Optional[str] = None) -> dict:
    return {"status": status, "source": source, "source_url": source_url}


def _page_label(url: str) -> str:
    if "#page=" in url:
        return f"CSR / annual report, page {url.rsplit('#page=', 1)[1]}"
    if "hunter.io" in url:
        return "Hunter.io"
    if "apollo.io" in url:
        return "Apollo.io"
    path = urlparse(url).path.strip("/") or "home page"
    return f"company website ({path})"


def _source_type(url: str) -> str:
    if "#page=" in url:
        return "csr_report"
    if "hunter.io" in url or "apollo.io" in url:
        return "third_party"
    return "website"


def linkedin_search_url(*terms: str) -> str:
    return "https://www.linkedin.com/search/results/people/?keywords=" + quote_plus(" ".join(t for t in terms if t))


# ----------------------------------------------------------------------------
# Email pattern ("firstname.lastname@") - only from published examples
# ----------------------------------------------------------------------------
_PATTERNS = {
    "first.last": lambda f, l: f"{f}.{l}",
    "firstlast": lambda f, l: f"{f}{l}",
    "first_last": lambda f, l: f"{f}_{l}",
    "f.last": lambda f, l: f"{f[0]}.{l}",
    "flast": lambda f, l: f"{f[0]}{l}",
    "first": lambda f, l: f,
}


def _first_last(name: str) -> Optional[tuple[str, str]]:
    words = [w for w in re.findall(r"[a-z]+", extract.strip_honorific(name).lower()) if len(w) > 1]
    return (words[0], words[-1]) if len(words) >= 2 else None


def infer_email_pattern(pairs: list[tuple[str, str]]) -> Optional[str]:
    """The local-part pattern every published (name, email) pair agrees on."""
    agreed: Optional[set[str]] = None
    for name, email in pairs:
        parts = _first_last(name)
        if not parts:
            continue
        local = email.split("@", 1)[0].lower()
        fitting = {key for key, build in _PATTERNS.items() if build(*parts) == local}
        agreed = fitting if agreed is None else agreed & fitting
    if not agreed:
        return None
    return next(key for key in _PATTERNS if key in agreed)


# ----------------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------------
def load_robots(base: str) -> RobotFileParser:
    """robots.txt fetched with the same identifiable User-Agent as the pages.

    Python's RobotFileParser.read() fetches as "Python-urllib", which many
    corporate sites' bot protection answers with 403 - and a 403 makes it
    disallow the whole site, even when the real robots.txt allows us (Tata
    Steel's is "Allow: /"). Status handling follows RFC 9309, erring on the
    side of not crawling: 401/403, server errors and network failures mean
    "disallow everything"; 404/410 mean there are no restrictions.
    """
    parser = RobotFileParser()
    parser.set_url(base + "/robots.txt")
    try:
        response = requests.get(base + "/robots.txt", headers={"User-Agent": scraping.USER_AGENT}, timeout=10)
    except requests.RequestException:
        parser.disallow_all = True
        return parser
    if response.status_code in (401, 403) or response.status_code >= 500:
        parser.disallow_all = True
    elif response.status_code >= 400:
        parser.allow_all = True
    else:
        parser.parse(response.text.splitlines())
    return parser


def _default_third_party(domain: str) -> list[dict]:
    keep = lambda title: roles.classify(title) is not None  # noqa: E731
    return enrichment.hunter_domain_search(domain, keep) + enrichment.apollo_people_search(domain, keep)


class ContactDiscoveryService:
    def __init__(
        self,
        fetch: Optional[Callable[[str], Optional[str]]] = None,
        robots_for: Optional[Callable[[str], object]] = None,
        url_guard: Callable[[str], bool] = is_public_website,
        report_scanner: Callable[[str], dict] = reports.scan_report,
        third_party: Callable[[str], list[dict]] = _default_third_party,
        third_party_configured: Callable[[], bool] = enrichment.is_configured,
        delay_seconds: Optional[float] = None,
    ):
        self.fetch = fetch or scraping._fetch_page
        self.robots_for = robots_for or load_robots
        self.url_guard = url_guard
        self.report_scanner = report_scanner
        self.third_party = third_party
        self.third_party_configured = third_party_configured
        self.delay_seconds = scraping.REQUEST_DELAY_SECONDS if delay_seconds is None else delay_seconds
        self._cache: dict[tuple, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    # -- public ---------------------------------------------------------------
    def find(self, ctx: CompanyContext, include_reports: bool = False, refresh: bool = False) -> dict:
        domain = policy.domain_of(ctx.website)
        cache_key = ((domain or ctx.name).lower(), include_reports, (ctx.csr_report_url or "").lower())
        if not refresh:
            with self._lock:
                cached = self._cache.get(cache_key)
            if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
                return {**cached[1], "cached": True}

        started = time.monotonic()
        result = self._run(ctx, domain, include_reports)
        result["duration_ms"] = int((time.monotonic() - started) * 1000)
        result["cached"] = False
        with self._lock:
            if len(self._cache) >= CACHE_MAX_ENTRIES:
                self._cache.pop(min(self._cache, key=lambda k: self._cache[k][0]))
            self._cache[cache_key] = (time.time(), result)
        return result

    # -- crawl ----------------------------------------------------------------
    def _crawl(self, website: str, messages: list[str]) -> dict:
        crawl = {"pages": [], "checked": [], "blocked": [], "readable": 0, "report_links": []}
        base = scraping._base_url(website)
        if base is None:
            messages.append("The website address doesn't look valid, so it wasn't read.")
            return crawl
        robots = self.robots_for(base)
        site = urlparse(base).netloc.lower().removeprefix("www.")

        queue: list[tuple[int, int, int, str]] = [(-1, 0, 0, base + "/")]
        seen = {base + "/"}
        order = 0
        pages_by_rank: dict[int, int] = {}
        started = time.monotonic()

        def enqueue(url: str, label: str) -> None:
            nonlocal order
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or parsed.netloc.lower().removeprefix("www.") != site:
                return
            # Query strings are dropped: "?page=1" listings and "/search?key=" pages
            # are the same page (or no page) for our purposes.
            clean = url.split("#", 1)[0].split("?", 1)[0]
            if clean in seen or _SKIP_LINK.search(parsed.path) or _SKIP_LINK.search(url):
                return
            # Judge a link by the page's own (last) path segment and a short
            # anchor text - not by the whole path or a headline, so
            # "/sustainability/services/impact-intelligence" (a product) and
            # "/client-success/...-payments-foundation-for-a-fintech" (an
            # article) aren't taken for CSR pages.
            segments = [s for s in parsed.path.lower().split("/") if s]
            last = segments[-1] if segments else ""
            haystack = " ".join(
                part for part in (last if len(re.split(r"[-_.]", last)) <= 5 else "", label if len(label.split()) <= 6 else "")
                if part
            )
            # Press releases often mention CSR in their slug; they still count
            # against the press-page cap, not as CSR pages.
            if _PRESS_PATH.search(parsed.path):
                rank = 5
            else:
                rank = next((r for r, pattern in _PAGE_HINTS if pattern.search(haystack)), None)
            if rank is None:
                return
            seen.add(clean)
            order += 1
            # Within a kind, shallower pages first ("/sustainability" before
            # "/sustainability/services/<product>").
            queue.append((rank, len(segments), order, clean))

        fallback_added = False
        while queue and len(crawl["checked"]) < MAX_PAGES:
            if time.monotonic() - started > CRAWL_TIME_BUDGET_SECONDS:
                messages.append("Stopped reading the website after 45 seconds; results may be incomplete.")
                break
            queue.sort()
            rank, _, _, url = queue.pop(0)
            if rank >= 0:
                if pages_by_rank.get(rank, 0) >= _RANK_BUDGET[rank]:
                    continue
                pages_by_rank[rank] = pages_by_rank.get(rank, 0) + 1
            if not robots.can_fetch(scraping.USER_AGENT, url):
                crawl["blocked"].append(url)
                continue
            if crawl["checked"] and self.delay_seconds:
                time.sleep(self.delay_seconds)
            html = self.fetch(url)
            crawl["checked"].append(url)
            if not html or len(" ".join(line.text for line in extract.html_to_lines(html)[0])) < 40:
                # Error page, or a JavaScript-only shell with no text.
                if url == base + "/" and not fallback_added:
                    for path in FALLBACK_PATHS:
                        enqueue(urljoin(base, path), "")
                    fallback_added = True
                continue
            crawl["readable"] += 1
            crawl["pages"].append((url, html))
            links = extract.find_links(html, url)
            for link, label in links:
                if link.lower().split("?", 1)[0].endswith(".pdf"):
                    if _REPORT_LINK.search(link) or _REPORT_LINK.search(label):
                        crawl["report_links"].append(link)
                else:
                    enqueue(link, label)
            if url == base + "/" and not fallback_added and len(queue) < 3:
                for path in FALLBACK_PATHS:
                    enqueue(urljoin(base, path), "")
                fallback_added = True
        return crawl

    # -- one run ----------------------------------------------------------------
    def _run(self, ctx: CompanyContext, domain: str, include_reports: bool) -> dict:
        messages: list[str] = []
        sources: list[dict] = []
        pages: list[extract.PageExtract] = []
        report_people: list[extract.PersonHit] = []
        third_party_people: list[extract.PersonHit] = []
        crawl = {"checked": [], "blocked": [], "readable": 0, "report_links": [], "pages": []}

        website_ok = bool(ctx.website) and self.url_guard(ctx.website)
        if not ctx.website:
            messages.append(
                "No website is known for this company, so its pages couldn't be read. Add the website to the "
                "lead and search again."
            )
        elif not website_ok:
            messages.append("That website address can't be checked (it isn't a public internet address).")
        else:
            crawl = self._crawl(ctx.website, messages)
            for url, html in crawl["pages"]:
                pages.append(extract.extract_page(html, url, domain))
        website_people = sum(len(p.people) + len([m for m in p.mailboxes if m.priority]) for p in pages)
        sources.append(
            {
                "key": "website",
                "label": "Company website",
                "configured": bool(ctx.website),
                "used": bool(crawl["checked"]),
                "result_count": website_people,
                "message": None
                if crawl["checked"] or not ctx.website
                else ("Blocked by robots.txt" if crawl["blocked"] else None),
            }
        )

        # CSR / annual report: the saved report link first, then the most
        # promising PDFs linked from the site; stop at the first that names people.
        candidates = [ctx.csr_report_url] if ctx.csr_report_url else []
        candidates += [u for u in rank_report_links(crawl["report_links"]) if u not in candidates]
        report_info = {
            "url": candidates[0] if candidates else None, "scanned": False, "pages_read": 0,
            "relevant_pages": [], "message": None, "urls_tried": [],
        }
        if include_reports:
            if not candidates:
                report_info["message"] = "No CSR or annual report link is known for this company."
            for report_url in candidates[:MAX_REPORTS]:
                if not self.url_guard(report_url):
                    report_info["message"] = "The report link can't be checked (it isn't a public internet address)."
                    continue
                base = scraping._base_url(report_url)
                robots = self.robots_for(base) if base else None
                if robots is not None and not robots.can_fetch(scraping.USER_AGENT, report_url):
                    report_info["message"] = "The report's website asks automated tools not to read it (robots.txt)."
                    continue
                scanned = self.report_scanner(report_url)
                report_info["urls_tried"].append(report_url)
                report_info.update(
                    url=report_url,
                    scanned=True,
                    pages_read=report_info["pages_read"] + scanned["pages_read"],
                    relevant_pages=scanned["relevant_pages"],
                    message=scanned["message"],
                )
                if scanned["people"]:
                    report_people = scanned["people"]
                    break
        sources.append(
            {
                "key": "report",
                "label": "CSR / annual report (PDF)",
                "configured": reports.is_available(),
                "used": report_info["scanned"],
                "result_count": len(report_people),
                "message": report_info["message"] if include_reports else None,
            }
        )

        # Hunter.io / Apollo.io
        configured = self.third_party_configured()
        if configured and domain:
            for row in self.third_party(domain):
                match = roles.classify(row.get("designation"))
                name = extract.clean_person_name(row.get("name") or "")
                if not match or not name:
                    continue
                hit = extract.PersonHit(
                    name, row["designation"], match.category, match.priority, "third_party", row.get("source_url") or ""
                )
                if policy.is_company_email(row.get("email"), domain):
                    hit.email, hit.email_status = row["email"].lower(), "verified"
                # Third-party phone numbers are never kept: there's no way to
                # tell a direct mobile from an office line.
                if policy.is_linkedin_profile(row.get("linkedin_url")):
                    hit.linkedin_url = row["linkedin_url"]
                third_party_people.append(hit)
        sources.append(
            {
                "key": "third_party",
                "label": "Hunter.io / Apollo.io",
                "configured": configured,
                "used": bool(configured and domain),
                "result_count": len(third_party_people),
                "message": None if configured else "Not set up (HUNTER_API_KEY / APOLLO_API_KEY).",
            }
        )

        contacts, contact_points = self._merge(ctx, domain, pages, report_people + third_party_people)
        self._explain(ctx, crawl, contacts, messages, website_ok)

        return {
            "company": {
                "company_id": ctx.company_id,
                "name": ctx.name,
                "website": ctx.website,
                "city": ctx.city,
                "state": ctx.state,
                "industry": ctx.industry,
                "csr_report_url": ctx.csr_report_url,
            },
            "contacts": contacts,
            "contact_points": contact_points,
            "suggested_searches": suggested_searches(ctx.name),
            "pages_checked": crawl["checked"],
            "pages_blocked": crawl["blocked"],
            "report": report_info,
            "report_links": rank_report_links(crawl["report_links"])[:5],
            "sources": sources,
            "messages": messages,
        }

    def _explain(self, ctx, crawl, contacts, messages, website_ok) -> None:
        if not website_ok:
            return
        if crawl["blocked"] and not crawl["checked"]:
            messages.append(
                "This company's website asks automated tools not to read it (robots.txt), so it wasn't read. "
                "Open the website, or use the LinkedIn searches below."
            )
        elif crawl["checked"] and not crawl["readable"]:
            messages.append(
                "The website didn't return readable pages (it may load its content with JavaScript). "
                "Open it to look manually, or try the CSR report."
            )
        elif crawl["blocked"]:
            messages.append(f"{len(crawl['blocked'])} page(s) were skipped because robots.txt disallows them.")
        if crawl["readable"] and not contacts:
            messages.append(
                "No named CSR, HR or regional decision makers are published on the pages checked. "
                "Try scanning the CSR report, or the LinkedIn searches below."
            )

    # -- merge & score -----------------------------------------------------------
    def _merge(self, ctx, domain, pages, extra_people) -> tuple[list[dict], list[dict]]:
        company_key = normalize_company_name(ctx.name)
        candidates: dict[str, _Candidate] = {}

        def add_person(hit: extract.PersonHit) -> None:
            key = extract.name_key(hit.name)
            if not key or (company_key and (key == company_key or company_key in key)):
                return
            candidate = candidates.setdefault(key, _Candidate(key=key, name=hit.name))
            candidate.hits.append(hit)

        for page in pages:
            for hit in page.people:
                add_person(hit)
        for hit in extra_people:
            add_person(hit)

        person_emails = {h.email for c in candidates.values() for h in c.hits if h.email}
        general_emails: list[extract.MailboxHit] = []
        for page in pages:
            for box in page.mailboxes:
                if box.email in person_emails:
                    continue
                if box.priority is None:
                    if box.email not in {g.email for g in general_emails}:
                        general_emails.append(box)
                    continue
                key = f"mailbox:{box.email}"
                if key not in candidates:
                    candidates[key] = _Candidate(
                        key=key, name=box.label, is_mailbox=True, mailbox_email=box.email,
                        mailbox_label=box.label, mailbox_priority=box.priority, mailbox_url=box.source_url,
                    )

        # Company-level facts used as labelled fallbacks for each person.
        contact_pages = [p for p in pages if re.search(r"contact|reach|office", p.url, re.I)]
        # Indian lines before overseas offices' (a contact page listing New
        # York first shouldn't make that the Indian company's number).
        all_phones = sorted(
            (ph for p in contact_pages + pages for ph in p.phones), key=lambda ph: policy.indian_number_rank(ph.phone)
        )
        office_phone = next(iter(all_phones), None)
        office_city_page = next((p for p in contact_pages + pages if p.office_city), None)

        # Email pattern from published person addresses on the company's domain.
        pairs = [
            (c.name, h.email) for c in candidates.values() if not c.is_mailbox
            for h in c.hits if h.email and h.email_status == "verified" and h.method != "third_party"
        ]
        pattern = infer_email_pattern(pairs) if domain else None

        contacts = [
            self._build(c, ctx, domain, office_phone, office_city_page, pattern, len(pairs))
            for c in candidates.values()
        ]
        contacts.sort(key=lambda c: (c["priority"], -c["confidence"], c["name"].lower()))

        points = [
            {"kind": "email", "value": g.email, "label": "General enquiries", "source_url": g.source_url}
            for g in general_emails[:5]
        ]
        seen_phones: set[str] = set()
        for ph in all_phones:
            digits = policy.phone_key(ph.phone)
            if digits in seen_phones or len(seen_phones) >= 5:
                continue
            seen_phones.add(digits)
            points.append({"kind": "phone", "value": ph.phone, "label": "Office phone", "source_url": ph.source_url})
        return contacts, points

    def _build(self, c: _Candidate, ctx, domain, office_phone, office_city_page, pattern, pattern_examples) -> dict:
        provenance: dict[str, dict] = {}
        reasons: list[str] = []
        source_map: dict[str, dict] = {}

        def note_source(url: str, fields: list[str]) -> None:
            if not url:
                return
            entry = source_map.setdefault(
                url, {"url": url, "source_type": _source_type(url), "label": _page_label(url), "fields": []}
            )
            entry["fields"] += [f for f in fields if f not in entry["fields"]]

        email = phone = linkedin = location = None
        if c.is_mailbox:
            name, designation = c.mailbox_label, f"{c.mailbox_label} (shared mailbox)"
            category = c.mailbox_label
            priority = c.mailbox_priority
            email = c.mailbox_email
            source_url = c.mailbox_url
            label = _page_label(source_url)
            local = email.split("@")[0]
            provenance["name"] = _prov(INFERRED, f"named by the app after the {local}@ mailbox", source_url)
            provenance["designation"] = _prov(INFERRED, f"named by the app after the {local}@ mailbox", source_url)
            provenance["email"] = _prov(VERIFIED, label, source_url)
            note_source(source_url, ["email"])
            confidence = 55
            reasons.append(f"Official {local}@ mailbox published on the {label}")
        else:
            hits = sorted(c.hits, key=lambda h: (h.priority, _METHOD_RANK.get(h.method, 9)))
            best = hits[0]
            name, designation, category, priority = c.name, best.designation, best.role_category, best.priority
            source_url = best.source_url
            label = _page_label(source_url)
            provenance["name"] = _prov(VERIFIED, label, source_url)
            provenance["designation"] = _prov(VERIFIED, label, source_url)
            for hit in hits:
                note_source(hit.source_url, ["name", "designation"])

            confidence = max(_METHOD_BASE.get(h.method, 40) for h in hits)
            reasons.append(f"Name and title {_METHOD_LABEL.get(best.method, 'found publicly')}")
            distinct = {h.source_url.split("#", 1)[0] for h in hits}
            if len(distinct) > 1:
                confidence += min(20, 10 * (len(distinct) - 1))
                reasons.append(f"Confirmed by {len(distinct)} separate sources")

            email_hit = next((h for h in hits if h.email), None)
            if email_hit:
                email = email_hit.email
                provenance["email"] = _prov(VERIFIED, f"published with this person on the {_page_label(email_hit.source_url)}", email_hit.source_url)
                note_source(email_hit.source_url, ["email"])
                confidence += 10
                reasons.append("Work email published with their name")
            elif pattern and domain and _first_last(name):
                email = _PATTERNS[pattern](*_first_last(name)) + "@" + domain
                provenance["email"] = _prov(
                    INFERRED,
                    f"guessed from the {pattern}@{domain} format seen in {pattern_examples} published address(es) - verify before sending",
                    None,
                )
                confidence += 3
                reasons.append("Work email guessed from the company's published email format")

            linkedin_hit = next((h for h in hits if h.linkedin_url), None)
            if linkedin_hit:
                linkedin = linkedin_hit.linkedin_url
                provenance["linkedin_url"] = _prov(VERIFIED, f"linked from the {_page_label(linkedin_hit.source_url)}", linkedin_hit.source_url)
                note_source(linkedin_hit.source_url, ["linkedin_url"])
                confidence += 5
                reasons.append("LinkedIn profile linked from an official source")

            phone_hit = next((h for h in hits if h.phone), None)
            if phone_hit:
                phone = phone_hit.phone
                provenance["phone"] = _prov(VERIFIED, f"office line listed with this person on the {_page_label(phone_hit.source_url)}", phone_hit.source_url)
                note_source(phone_hit.source_url, ["phone"])

            location_hit = next((h for h in hits if h.location), None)
            if location_hit:
                location = location_hit.location
                provenance["office_location"] = _prov(VERIFIED, f"stated with this person on the {_page_label(location_hit.source_url)}", location_hit.source_url)
                note_source(location_hit.source_url, ["office_location"])

            if best.method != "third_party" and any(extract.PROFILE_PAGE_HINT.search(h.source_url) for h in hits):
                confidence += 5
            if best.method == "prose":
                reasons.append("Only mentioned in passing - check the title is still current")

        if not phone and office_phone:
            phone = office_phone.phone
            provenance["phone"] = _prov(
                VERIFIED, f"company's published office number on the {_page_label(office_phone.source_url)} (not a direct line)",
                office_phone.source_url,
            )
        if not location:
            if office_city_page:
                location = office_city_page.office_city
                provenance["office_location"] = _prov(
                    INFERRED, "company office on its contact page; this person's own office isn't stated", office_city_page.url
                )
            elif ctx.city:
                location = ", ".join(v for v in (ctx.city, ctx.state) if v)
                provenance["office_location"] = _prov(INFERRED, "company's head-office city; this person's own office isn't stated")

        provenance["company"] = _prov(VERIFIED, label, source_url)
        provenance["source_url"] = _prov(VERIFIED, label, source_url)
        for field_name in ("email", "phone", "linkedin_url", "office_location"):
            provenance.setdefault(field_name, _prov(UNAVAILABLE))

        return {
            "candidate_id": c.key,
            "name": name,
            "designation": designation,
            "company": ctx.name,
            "role_category": category,
            "priority": priority,
            "priority_label": roles.PRIORITY_LABELS.get(priority, ""),
            "office_location": location,
            "email": email,
            "phone": phone,
            "linkedin_url": linkedin,
            "linkedin_search_url": None if linkedin or c.is_mailbox else linkedin_search_url(name, ctx.name),
            "source_url": source_url,
            "sources": list(source_map.values()),
            "provenance": provenance,
            "confidence": max(10, min(95, confidence)),
            "confidence_reasons": reasons,
            "is_shared_mailbox": c.is_mailbox,
            "saved_contact_id": None,
        }


def suggested_searches(company_name: str) -> list[dict]:
    """Links staff can open themselves - the app never reads these sites."""
    quoted = f'"{company_name}"'
    return [
        {"name": f"LinkedIn: CSR at {company_name}", "url": linkedin_search_url("CSR", company_name)},
        {"name": f"LinkedIn: Sustainability / ESG at {company_name}", "url": linkedin_search_url("Sustainability", company_name)},
        {"name": f"LinkedIn: HR leadership at {company_name}", "url": linkedin_search_url("HR Head", company_name)},
        {"name": f"LinkedIn: Corporate Communications at {company_name}", "url": linkedin_search_url("Corporate Communications", company_name)},
        {
            "name": "Web: CSR Committee in the annual report",
            "url": "https://www.google.com/search?q=" + quote_plus(f'{quoted} "CSR Committee" annual report'),
        },
        {"name": "National CSR Portal (company-wise CSR data)", "url": "https://www.csr.gov.in/"},
    ]


_default_service: Optional[ContactDiscoveryService] = None


def get_default_service() -> ContactDiscoveryService:
    global _default_service
    if _default_service is None:
        _default_service = ContactDiscoveryService()
    return _default_service
