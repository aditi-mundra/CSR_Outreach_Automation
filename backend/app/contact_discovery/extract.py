"""Pull named decision makers out of a company's public web pages.

Pure functions over HTML/text - no network. The page is first flattened
into "lines" (one per block element; one per table row, cells joined by
" | "), each remembering the links inside it. People are then found by:

    structured  schema.org Person records in JSON-LD
    listing     a name line next to a title line - the usual leadership /
                team card ("Priya Sharma" / "Head - CSR")
    inline      name and title on one line ("Priya Sharma, Head - CSR")
    committee   rows of a CSR Committee table or list ("Mr. A. Rao |
                Chairman"), only inside a section headed CSR Committee
    prose       press-release style mentions ("..., said Priya Sharma,
                Head of Sustainability, Acme")

Only titles that classify as a target role (roles.py) are kept. Emails,
LinkedIn links, office phones and a city are attached from the lines
belonging to that person's block, after the policy.py checks.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Iterable, Optional
from urllib.parse import unquote, urljoin

from ..company_discovery.matching import MAJOR_INDIAN_CITIES, first_known_city
from . import policy, roles

_BLOCK_TAGS = {
    "p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header",
    "footer", "aside", "nav", "table", "tbody", "thead", "tfoot", "dl", "dt", "dd", "figure", "figcaption",
    "blockquote", "address", "main", "form", "br", "hr", "caption",
}
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "select", "option", "iframe", "head", "title"}

_HONORIFIC = re.compile(
    r"^(?:(?:mr|mrs|ms|miss|dr|prof|shri|smt|sri|kum|km|ca|cs|cma|adv|capt|col|lt|maj|gen|er|sh)\.?\s+|\(\s*(?:mr|mrs|ms|dr)\.?\s*\)\s*)+",
    re.IGNORECASE,
)
_NAME_TOKEN = re.compile(r"^(?:[A-Z][a-z'’]+(?:-[A-Z]?[a-z'’]+)*|[A-Z]['’][A-Z][a-z]+|[A-Z]{2,}|(?:[A-Z]\.){1,3}[A-Z]?\.?|[A-Z]\.?|[A-Z][a-z]?[A-Z][a-z]+)$")
_NOT_NAME_WORDS = {
    # role / org / page vocabulary that never appears in a person's name
    "csr", "corporate", "social", "responsibility", "committee", "head", "manager", "director", "directors",
    "officer", "chairman", "chairperson", "chairwoman", "member", "members", "board", "team", "our", "the",
    "and", "of", "for", "in", "at", "to", "with", "on", "by", "limited", "ltd", "pvt", "private", "plc", "inc",
    "llp", "india", "foundation", "trust", "trusts", "sustainability", "esg", "policy", "policies", "report",
    "reports", "annual", "contact", "us", "about", "home", "leadership", "management", "human", "resources",
    "communications", "communication", "public", "relations", "affairs", "investor", "investors", "media",
    "news", "press", "careers", "career", "privacy", "terms", "group", "company", "services", "solutions",
    "products", "read", "more", "view", "profile", "download", "click", "here", "chief", "executive",
    "president", "vice", "general", "regional", "branch", "operations", "business", "unit", "independent",
    "non", "whole", "time", "managing", "secretary", "compliance", "registered", "office", "address", "email",
    "phone", "tel", "fax", "mobile", "department", "division", "global", "national", "international",
    "corporation", "industries", "technologies", "bank", "sr", "jr", "senior", "junior", "vp", "avp", "svp",
    "evp", "gm", "agm", "dgm", "hr", "pr", "ceo", "cfo", "coo", "cto", "chro", "cso", "md", "nominee",
    "promoter", "executive", "sitemap", "login", "search", "menu", "share", "follow", "linkedin", "twitter",
    "facebook", "instagram", "youtube", "copyright", "all", "rights", "reserved", "overview", "mission",
    "vision", "values", "story", "history", "awards", "governance", "community", "environment", "education",
    "health", "healthcare", "programme", "programmes", "program", "programs", "initiatives", "impact",
    "project", "projects", "partners", "partner", "partnership", "strategy", "approach", "focus", "areas",
    "plant", "works", "zone", "region", "regions", "office", "offices", "location", "locations", "sales",
    "marketing", "finance", "legal", "people", "culture", "talent", "learning", "development", "brand",
    "chair", "committees", "meeting", "meetings", "attended", "held", "name", "designation", "category",
    # card / teaser vocabulary ("Client Success", "Latest Insights", ...)
    "client", "clients", "success", "case", "study", "studies", "stories", "blog", "blogs", "insights",
    "event", "events", "webinar", "webinars", "podcast", "whitepaper", "recognition", "digital",
    "engineering", "cloud", "data", "platform", "platforms", "technology", "innovation", "customer",
    "customers", "latest", "featured", "highlights", "key", "quick", "links", "explore", "discover",
    "learn", "join", "apply", "subscribe", "newsletter", "industry", "industries", "solution",
    "sl", "no", "sr.no", "status", "nature", "directorship", "din", "dear", "hello", "welcome", "message",
}
_PROSE = re.compile(
    r"(?:(?:Mr|Ms|Mrs|Dr|Shri|Smt)\.?\s+)?"
    r"((?:[A-Z][a-z'’\-]+|[A-Z]\.)(?:\s+(?:[A-Z][a-z'’\-]+|[A-Z]\.)){1,3})"
    r",\s+([^,;.]{4,90}?)(?=,|;|\.(?:\s|$)| at | said)"
)
_LOCATION_CUE = re.compile(r"\b(?:based (?:in|at|out of)|located (?:in|at)|office (?:in|at)|location:?)\s+[A-Z][\w ]{2,30}")
_INLINE_SPLIT = re.compile(r"\s*(?:\||,|:|\s[-–—]\s|[–—])\s*")
PROFILE_PAGE_HINT = re.compile(
    r"leader|management|board|director|team|people|csr|sustainab|foundation|committee|governance|esg|about",
    re.IGNORECASE,
)


@dataclass
class Line:
    text: str
    links: list[str] = field(default_factory=list)
    is_row: bool = False
    cells: list[str] = field(default_factory=list)


@dataclass
class PersonHit:
    name: str
    designation: str
    role_category: str
    priority: int
    method: str
    source_url: str
    email: Optional[str] = None
    email_status: Optional[str] = None  # "verified" | "inferred"
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    location: Optional[str] = None


@dataclass
class MailboxHit:
    email: str
    label: str
    priority: Optional[int]  # None for general office inboxes (info@, contact@)
    source_url: str


@dataclass
class PhoneHit:
    phone: str
    source_url: str
    context: str


@dataclass
class PageExtract:
    url: str
    people: list[PersonHit] = field(default_factory=list)
    mailboxes: list[MailboxHit] = field(default_factory=list)
    phones: list[PhoneHit] = field(default_factory=list)
    office_city: Optional[str] = None
    is_profile_page: bool = False


# ----------------------------------------------------------------------------
# HTML -> lines
# ----------------------------------------------------------------------------
class _LineParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[Line] = []
        self.json_ld: list[str] = []
        self._buf: list[str] = []
        self._links: list[str] = []
        self._skip = 0
        self._in_json_ld = False
        self._row: Optional[list[str]] = None
        self._row_links: list[str] = []
        self._cell: list[str] = []

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if text or self._links:
            self.lines.append(Line(text=text, links=self._links))
        self._buf, self._links = [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and (attrs.get("type") or "").lower() == "application/ld+json":
            self._in_json_ld = True
            self._buf_json: list[str] = []
            return
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "a" and attrs.get("href"):
            (self._row_links if self._row is not None else self._links).append(attrs["href"].strip())
        if tag == "tr":
            self._flush()
            self._row, self._row_links, self._cell = [], [], []
        elif tag in ("td", "th") and self._row is not None:
            self._end_cell()
        elif tag in _BLOCK_TAGS:
            if self._row is not None:
                self._cell.append(" ")
            else:
                self._flush()

    def handle_startendtag(self, tag, attrs):
        if tag in ("br", "hr") and not self._skip:
            if self._row is not None:
                self._cell.append(" ")
            else:
                self._flush()

    def handle_endtag(self, tag):
        if tag == "script" and self._in_json_ld:
            self.json_ld.append("".join(self._buf_json))
            self._in_json_ld = False
            return
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in ("td", "th") and self._row is not None:
            self._end_cell()
        elif tag == "tr" and self._row is not None:
            self._end_cell()
            cells = [c for c in self._row if c]
            if cells or self._row_links:
                self.lines.append(Line(text=" | ".join(cells), links=self._row_links, is_row=True, cells=cells))
            self._row = None
        elif tag in _BLOCK_TAGS and self._row is None:
            self._flush()

    def _end_cell(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
        if self._row is not None and text:
            self._row.append(text)
        self._cell = []

    def handle_data(self, data):
        if self._in_json_ld:
            self._buf_json.append(data)
            return
        if self._skip:
            return
        if self._row is not None:
            self._cell.append(data)
        else:
            self._buf.append(data)

    def close(self):
        super().close()
        if self._row is not None:
            self.handle_endtag("tr")
        self._flush()


def html_to_lines(html: str) -> tuple[list[Line], list[str]]:
    """(lines, raw JSON-LD blocks) for a page."""
    parser = _LineParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # malformed markup - keep whatever was parsed
        pass
    return parser.lines, parser.json_ld


def text_to_lines(text: str) -> list[Line]:
    """Lines from already-extracted text (a PDF page). NFKC undoes PDF
    ligatures ("Oﬃcer" -> "Officer") so titles still classify.
    """
    text = unicodedata.normalize("NFKC", text)
    return [Line(text=re.sub(r"\s+", " ", t).strip()) for t in text.splitlines() if t.strip()]


# ----------------------------------------------------------------------------
# Names
# ----------------------------------------------------------------------------
def strip_honorific(text: str) -> str:
    return _HONORIFIC.sub("", text.strip()).strip()


def clean_person_name(text: str) -> Optional[str]:
    """The person's name if `text` is plausibly just a name, else None.

    Accepts "Priya Sharma", "Dr. (Ms.) Priya Sharma", "N. Chandrasekaran",
    "K.V. Ramana Rao", "PRIYA SHARMA" (returned title-cased); rejects
    headings, menu items and anything containing role/org vocabulary.
    """
    text = re.sub(r"\s+", " ", (text or "").strip(" \t-–—|,:;•*")).strip()
    text = re.sub(r"\s*\((?:DIN|din)[^)]*\)\s*$", "", text)
    # Nicknames / honorifics in brackets: "Dr. S. B. (Ravi) Pandit", "Dr. (Ms.) Priya Sharma".
    text = re.sub(r"^((?:\w+\.?\s+)*?)\((?:mr|mrs|ms|dr)\.?\)\s*", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\([^)]{1,25}\)\s*", " ", text).strip()
    name = strip_honorific(text)
    name = re.sub(r",?\s+(?:ph\.?d|mba|ca|fca|cpa)\.?$", "", name, flags=re.IGNORECASE)
    if not name or len(name) > 45 or re.search(r"[\d@/\\:;!?|]", name):
        return None
    # "K.V. Ramana" -> tokens "K.V." "Ramana"; "K. V. Ramana" also fine.
    tokens = name.replace(".", ". ").split()
    tokens = [t for t in tokens if t]
    if not 2 <= len(tokens) <= 5:
        return None
    if any(t.lower().strip(".") in _NOT_NAME_WORDS for t in tokens):
        return None
    if not all(_NAME_TOKEN.match(t) for t in tokens):
        return None
    full_words = [t for t in tokens if len(t.strip(".")) >= 2 and not t.endswith(".")]
    if not full_words:
        return None
    all_caps = all(t.isupper() for t in full_words)
    if all_caps and len(tokens) < 2:
        return None
    if all_caps:
        tokens = [t.capitalize() if len(t.strip(".")) > 1 and not t.endswith(".") else t for t in tokens]
    return re.sub(r"\.\s+(?=[A-Z]\.)", ".", " ".join(tokens))


def name_key(name: str) -> str:
    """'S.B. Pandit' == 'S. B Pandit' == 'Dr. S. B. Pandit'."""
    key = re.sub(r"[^a-z ]", "", strip_honorific(name).lower().replace(".", " "))
    return re.sub(r"\s+", " ", key).strip()


# ----------------------------------------------------------------------------
# Line-level helpers
# ----------------------------------------------------------------------------
def _is_title(text: str, committee: bool) -> Optional[roles.RoleMatch]:
    # Digits / percentages mean a headline ("... Leader Achieves 10% Growth
    # by Modernizing Operations"), never a designation.
    if not text or len(text) > 120 or len(text.split()) > 14 or re.search(r"\d|%", text):
        return None
    return roles.classify(text, committee_context=committee)


_COMPANY_SUFFIX = re.compile(r",\s*[^,]*\b(?:ltd|limited|pvt|private|inc|llp|plc)\b\.?\s*$", re.IGNORECASE)
_TITLE_STRIP = " ,;:|()-\u2013\u2014"


def _tidy_title(title: str) -> str:
    title = _COMPANY_SUFFIX.sub("", title.strip(_TITLE_STRIP))
    title = re.sub(r"\s+", " ", title).strip(_TITLE_STRIP)
    if title.count("(") > title.count(")"):
        title += ")"
    return title


_DEPARTMENT_WORD = re.compile(r"^(?:[A-Z][\w'’.]*|[A-Z0-9&/]+|of|and|&|for)$")


def _title_end(text: str, committee: bool = False) -> Optional[int]:
    """Where the title at the start of `text` ends.

    "General Manager, EV Strategy, - Interaction with NDTV Profit" ->
    "General Manager, EV Strategy": the shortest leading run of segments
    that is a target title, plus following segments that read like a
    department ("EV Strategy", "West Region"), stopping at ordinary prose.
    """
    separators = list(_INLINE_SPLIT.finditer(text))
    cuts = [m.start() for m in separators] + [len(text)]
    starts = [0] + [m.end() for m in separators]
    for k, cut in enumerate(cuts):
        if not _is_title(_tidy_title(text[:cut]), committee):
            continue
        end = cut
        for start, next_cut in zip(starts[k + 1 :], cuts[k + 1 :]):
            words = text[start:next_cut].split()
            if not words:
                continue
            if len(words) > 4 or not all(_DEPARTMENT_WORD.match(w) for w in words):
                break
            end = next_cut
        return end
    return None


def _split_inline(text: str, committee: bool) -> Optional[tuple[str, str, roles.RoleMatch]]:
    """'Priya Sharma, Head - CSR' / 'Head CSR: Priya Sharma' / 'Mr. A. Rao (Chairman)'."""
    if len(text) > 160:
        return None
    flat = re.sub(r"[()\[\]]", ",", text)
    separators = list(_INLINE_SPLIT.finditer(flat))
    if not separators:
        return None
    first, last = separators[0], separators[-1]
    # `flat` only swaps brackets for commas (same length), so positions found
    # on it slice the original text - keeping "President (Intracity BU)" intact.
    def title_after_name() -> Optional[str]:
        end = _title_end(flat[first.end():], committee)
        return None if end is None else _tidy_title(text[first.end() : first.end() + end])

    # Name first ("Priya Sharma, Head - CSR"), then name last ("Head CSR: Priya Sharma").
    attempts = (
        (flat[: first.start()], title_after_name),
        (flat[last.end():], lambda: _tidy_title(text[: last.start()])),
    )
    for name_text, read_title in attempts:
        name = clean_person_name(name_text)
        if not name:
            continue
        title = read_title() or ""
        match = _is_title(title, committee)
        if match:
            return name, title, match
    return None


def _designation_for(title: str, match: roles.RoleMatch) -> str:
    """Bare committee roles ("Chairman" under a CSR Committee heading) get
    the committee spelled out; anything else keeps the page's own wording.
    """
    if match.category == "CSR Committee" and not roles.is_csr_committee_heading(title):
        return roles.committee_designation(title)
    return title


def _emails_in(line: Line) -> list[str]:
    found = []
    for href in line.links:
        if href.lower().startswith("mailto:"):
            found.append(unquote(href[7:].split("?", 1)[0]).strip())
    # Obfuscations like "csr [at] acme [dot] com" are deliberately not decoded.
    found += policy.EMAIL_PATTERN.findall(line.text)
    return [e.strip().strip(".").lower() for e in found]


# "(0)" after a country code ("+44 (0)20 7717 4444") is part of the number -
# without it the match would start at "20 ..." and lose the country code.
_PHONE_TEXT = re.compile(r"(?:\+\s?\d{1,3}[\s\-.]?(?:\(0\)\s?)?)?\(?\d{2,5}\)?[\s\-.]?\d{3,5}[\s\-.]?\d{3,5}")


def _phones_in(line: Line) -> list[tuple[str, str]]:
    out = []
    for href in line.links:
        if href.lower().startswith("tel:"):
            out.append((policy.clean_phone(unquote(href[4:])), line.text + " tel"))
    if re.search(r"\b(tel|phone|ph|telephone|board|call|toll)\b", line.text, re.IGNORECASE) or re.search(
        r"\+\s?\d", line.text
    ):
        for match in _PHONE_TEXT.finditer(line.text):
            # Judge each number by its own label ("Tel:" vs "Mobile:"), not
            # by everything else on the line.
            label = line.text[max(0, match.start() - 30) : match.start()]
            label = re.split(r"\d[\d\s\-.()+]{6,}\d", label)[-1]
            out.append((policy.clean_phone(match.group()), label))
    return out


def _linkedin_in(line: Line) -> Optional[str]:
    for href in line.links:
        if policy.is_linkedin_profile(href):
            return href.split("?", 1)[0]
    return None


# ----------------------------------------------------------------------------
# Structured data
# ----------------------------------------------------------------------------
def _walk_json(value) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _people_from_json_ld(blocks: list[str], page_url: str, company_domain: str) -> list[PersonHit]:
    hits = []
    for raw in blocks:
        try:
            data = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        for node in _walk_json(data):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Person" not in types:
                continue
            name = clean_person_name(str(node.get("name") or ""))
            title = str(node.get("jobTitle") or "")
            match = roles.classify(title)
            if not name or not match:
                continue
            hit = PersonHit(name, title.strip(), match.category, match.priority, "structured", page_url)
            email = str(node.get("email") or "").removeprefix("mailto:")
            if policy.is_company_email(email, company_domain):
                hit.email, hit.email_status = email.lower(), "verified"
            phone = str(node.get("telephone") or "")
            if policy.is_office_phone(phone, "telephone"):
                hit.phone = policy.clean_phone(phone)
            same_as = node.get("sameAs") or []
            for url in same_as if isinstance(same_as, list) else [same_as]:
                if policy.is_linkedin_profile(str(url)):
                    hit.linkedin_url = str(url)
            address = node.get("address") or node.get("workLocation") or {}
            if isinstance(address, dict):
                hit.location = first_known_city(json.dumps(address), MAJOR_INDIAN_CITIES)
            hits.append(hit)
    return hits


# ----------------------------------------------------------------------------
# Page extraction
# ----------------------------------------------------------------------------
_COMMITTEE_SPAN = 40  # lines after a "CSR Committee" heading treated as its member list


def extract_people_from_lines(lines: list[Line], page_url: str, company_domain: str) -> list[PersonHit]:
    hits: list[tuple[int, PersonHit]] = []
    used: set[int] = set()
    committee_until = -1

    def committee_at(i: int) -> bool:
        return i <= committee_until

    def nearest(i: int, step: int) -> Optional[int]:
        j = i + step
        while 0 <= j < len(lines) and not lines[j].text:
            j += step  # skip link-only lines (icons)
        return j if 0 <= j < len(lines) else None

    for i, line in enumerate(lines):
        text = line.text
        if not text:
            continue
        if len(text) <= 150 and roles.is_csr_committee_heading(text) and not clean_person_name(text):
            committee_until = i + _COMMITTEE_SPAN
            # A heading line can itself carry the role ("Chairman, CSR Committee") -
            # fall through so inline parsing still sees it.
        elif len(text) <= 150 and roles.is_other_committee_heading(text):
            committee_until = -1
        committee = committee_at(i)

        # Table rows: one cell is the name, another the title / committee role.
        if line.is_row and len(line.cells) >= 2:
            name = next((n for n in map(clean_person_name, line.cells) if n), None)
            if name:
                others = [c for c in line.cells if clean_person_name(c) != name]
                title = next((c for c in others if _is_title(c, committee)), None)
                if title:
                    match = _is_title(title, committee)
                    method = "committee" if match.category == "CSR Committee" else "listing"
                    hits.append((i, PersonHit(name, _designation_for(title, match), match.category, match.priority, method, page_url)))
                    used.add(i)
                    continue

        inline = _split_inline(text, committee)
        if inline:
            name, title, match = inline
            method = "committee" if match.category == "CSR Committee" else "inline"
            hits.append((i, PersonHit(name, _designation_for(title, match), match.category, match.priority, method, page_url)))
            used.add(i)
            continue

        match = _is_title(text, committee)
        if match and not clean_person_name(text):
            for step in (-1, 1):
                j = nearest(i, step)
                if j is None or j in used:
                    continue
                name = clean_person_name(lines[j].text)
                if name and not _is_title(lines[j].text, committee):
                    method = "committee" if match.category == "CSR Committee" else "listing"
                    hits.append((min(i, j), PersonHit(name, _designation_for(text, match), match.category, match.priority, method, page_url)))
                    used.update({i, j})
                    break
            continue

        if len(text) > 60:
            for name_text, raw_title in _PROSE.findall(text):
                name = clean_person_name(name_text)
                title = _tidy_title(raw_title)
                match = roles.classify(title)
                if name and match:
                    hits.append((i, PersonHit(name, title, match.category, match.priority, "prose", page_url)))

    # Attach details from each person's own block: the lines from their
    # name/title up to the next person (capped), never further.
    hits.sort(key=lambda pair: pair[0])
    starts = [start for start, _ in hits]
    for n, (start, hit) in enumerate(hits):
        if hit.method == "prose":
            continue
        end = min(starts[n + 1] if n + 1 < len(starts) else len(lines), start + 8)
        end = max(end, start + 1)
        block = lines[start:end]
        if lines[start].is_row:
            block = [lines[start]]
        for line in block:
            if not hit.email:
                for email in _emails_in(line):
                    if policy.is_company_email(email, company_domain) and not roles.is_general_mailbox(email.split("@")[0]):
                        hit.email, hit.email_status = email, "verified"
                        break
            hit.linkedin_url = hit.linkedin_url or _linkedin_in(line)
            if not hit.phone:
                for phone, context in _phones_in(line):
                    if policy.is_office_phone(phone, context):
                        hit.phone = phone
                        break
            # A city counts as their office only on a short line ("Regional
            # Manager - West, Pune") or an explicit one ("based in Pune") -
            # never from a biography paragraph ("graduated from ... Kolkata").
            if not hit.location and (len(line.text) <= 80 or _LOCATION_CUE.search(line.text)):
                hit.location = first_known_city(
                    line.text if len(line.text) <= 80 else _LOCATION_CUE.search(line.text).group(0),
                    MAJOR_INDIAN_CITIES,
                )
    return [hit for _, hit in hits]


def extract_page(html: str, page_url: str, company_domain: str) -> PageExtract:
    lines, json_ld = html_to_lines(html)
    result = PageExtract(url=page_url, is_profile_page=bool(PROFILE_PAGE_HINT.search(page_url)))
    result.people = _people_from_json_ld(json_ld, page_url, company_domain)
    result.people += extract_people_from_lines(lines, page_url, company_domain)

    person_emails = {p.email for p in result.people if p.email}
    seen_emails: set[str] = set()
    for line in lines:
        for email in _emails_in(line):
            if email in seen_emails or email in person_emails or not policy.is_company_email(email, company_domain):
                continue
            seen_emails.add(email)
            local = email.split("@")[0]
            role = roles.mailbox_role(local)
            if role:
                result.mailboxes.append(MailboxHit(email, role[0], role[1], page_url))
            elif roles.is_general_mailbox(local):
                result.mailboxes.append(MailboxHit(email, "General enquiries", None, page_url))
            # Anything else looks like an individual's address with no title
            # beside it - not a target role, so it isn't kept.
        for phone, context in _phones_in(line):
            if policy.is_office_phone(phone, context):
                result.phones.append(PhoneHit(phone, page_url, context[:160]))

    if re.search(r"contact|reach|office|location", page_url, re.IGNORECASE):
        for line in lines:
            if re.search(r"\b(registered|corporate|head)\s+office\b|\baddress\b", line.text, re.IGNORECASE) or re.search(
                r"\b\d{3}\s?\d{3}\b", line.text
            ):
                city = first_known_city(line.text, MAJOR_INDIAN_CITIES)
                if city:
                    result.office_city = city
                    break
    return result


def find_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """(absolute URL, lower-cased anchor text) for each link on a page."""
    out = []
    for match in re.finditer(r"<a\s[^>]*href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", html, re.IGNORECASE | re.DOTALL):
        label = re.sub(r"\s+", " ", unescape(re.sub(r"(?s)<[^>]+>", " ", match.group(2)))).strip().lower()
        out.append((urljoin(base_url, match.group(1).strip()), label))
    return out
