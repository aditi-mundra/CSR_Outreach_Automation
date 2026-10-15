"""Read CSR Committee members out of a company's CSR / annual report PDF.

Indian companies must publish their CSR Committee's composition (Annual
Report on CSR, Companies (CSR Policy) Rules) and, for listed companies,
the person responsible for business-responsibility policies (BRSR
Section B). Those are the most reliable public statement of who decides
CSR - but they sit inside 200+ page PDFs, so this is opt-in ("also scan
the CSR report") and bounded: size cap, page cap, time budget, and only
pages that mention the CSR Committee or the BRSR authority are parsed.

Needs `pypdf`; without it the option is reported as unavailable.
"""

from __future__ import annotations

import io
import logging
import re
import time
import unicodedata
from typing import Callable, Optional

import requests

from .. import scraping
from . import extract, roles

logger = logging.getLogger("contact_discovery.reports")
# pypdf logs a warning for every font it can't fully decode; the text it
# extracts is still usable, so keep the server log readable.
logging.getLogger("pypdf").setLevel(logging.ERROR)

MAX_REPORT_BYTES = 25 * 1024 * 1024
MAX_REPORT_PAGES = 600
REPORT_TIME_BUDGET_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 30

_RELEVANT_PAGE = re.compile(
    r"(csr|corporate social responsibility)\s+(and\s+\w+\s+)?committee|highest authority responsible|"
    r"responsible for (the )?implementation and oversight",
    re.IGNORECASE,
)
# "1 Mr. N. Chandrasekaran Chairman Non-Executive Director 3 3" - PDF text
# loses table cell borders, so committee rows arrive as one run of words.
_COMMITTEE_ROW = re.compile(
    r"^\s*(?:\d{1,2}[.)]?\s+)?"
    r"((?:(?:Mr|Ms|Mrs|Dr|Shri|Smt|Prof)\.?\s+)?(?:[A-Z][A-Za-z'’\-]*\.?\s*){1,5}?)"
    r"[\s,\-–(]+(Chair\w*|Member|Convenor|Convener)\b",
)
_BRSR_AUTHORITY = re.compile(
    r"Name\s*[:\-]?\s*((?:(?:Mr|Ms|Mrs|Dr|Shri|Smt)\.?\s*)?[A-Z][A-Za-z.'’\- ]{2,45}?)\s+"
    r"Designation\s*[:\-]?\s*([A-Za-z ,&()\-]{3,80}?)(?=\s+(?:Telephone|Tel|Email|E-mail|Phone|DIN|\d)|$)",
    re.MULTILINE,
)


def is_available() -> bool:
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return False
    return True


def fetch_pdf(url: str) -> tuple[Optional[bytes], Optional[str]]:
    """(PDF bytes, None) or (None, plain-language reason)."""
    try:
        with requests.get(
            url, headers={"User-Agent": scraping.USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS, stream=True
        ) as response:
            if response.status_code != 200:
                return None, f"The report link returned HTTP {response.status_code}."
            declared = int(response.headers.get("Content-Length") or 0)
            if declared > MAX_REPORT_BYTES:
                return None, "The report is larger than 25 MB, so it wasn't scanned - open it to check the CSR Committee."
            chunks, total = [], 0
            for chunk in response.iter_content(64 * 1024):
                total += len(chunk)
                if total > MAX_REPORT_BYTES:
                    return None, "The report is larger than 25 MB, so it wasn't scanned - open it to check the CSR Committee."
                chunks.append(chunk)
    except requests.RequestException as exc:
        logger.info("Could not fetch report %s: %s", url, exc)
        return None, "The report couldn't be downloaded."
    data = b"".join(chunks)
    if not data.startswith(b"%PDF"):
        return None, "The report link isn't a PDF file."
    return data, None


def relevant_pages(data: bytes, time_budget: float = REPORT_TIME_BUDGET_SECONDS) -> tuple[list[tuple[int, str]], int, bool]:
    """([(page number, text)] for pages about the CSR Committee / BRSR
    authority, pages read, whether the time/page budget ran out).
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    started = time.monotonic()
    found: list[tuple[int, str]] = []
    read = 0
    for index, page in enumerate(reader.pages):
        if index >= MAX_REPORT_PAGES or time.monotonic() - started > time_budget:
            return found, read, True
        try:
            text = page.extract_text() or ""
        except Exception:  # a single malformed page shouldn't end the scan
            continue
        read += 1
        if _RELEVANT_PAGE.search(text):
            found.append((index + 1, text))
    return found, read, False


_NUMBERED = re.compile(r"^\s*\d{1,2}[.)]\s+(.+?)\s*$")
# "Meher Pudumjee   2 2 100" - a meetings-attended table row.
_ATTENDANCE = re.compile(r"^(.+?)\s+\d{1,3}(?:\s+\d{1,3}(?:\.\d+)?%?)+\s*$")
_NAME_ROLE_SPLIT = re.compile(r"\s+[-–—]\s+|\s*,\s*|\s{2,}")


def _committee_member(text: str, next_line: str) -> tuple[Optional[str], str]:
    """(name, text naming their role) for one line inside a CSR Committee
    section, in the layouts annual reports actually use:

        1 Mr. N. Chandrasekaran Chairman, Non-Executive Director 3 3
        1. Meher Pudumjee - Chairperson
        2. Dr. S. B. (Ravi) Pandit                  <- member, role implied
        1. Meher Pudumjee  /  Chairperson Non Executive Promoter Director
        Shyamak R. Tata   2 2 100                   <- attendance table
    """
    match = _COMMITTEE_ROW.match(text)
    if match:
        name = extract.clean_person_name(match.group(1))
        if name:
            return name, match.group(2)
    match = _NUMBERED.match(text)
    if match:
        parts = _NAME_ROLE_SPLIT.split(match.group(1), maxsplit=1)
        name = extract.clean_person_name(parts[0])
        if name:
            role = parts[1] if len(parts) > 1 else (next_line if not _NUMBERED.match(next_line) else "")
            return name, role
    match = _ATTENDANCE.match(text)
    if match:
        return extract.clean_person_name(match.group(1)), ""
    return None, ""


def parse_report_text(text: str, source_url: str) -> list[extract.PersonHit]:
    """People named on one report page: CSR Committee members and the
    BRSR "highest authority" for business-responsibility policies.
    """
    text = unicodedata.normalize("NFKC", text)  # PDF ligatures: "Oﬃcer" -> "Officer"
    lines = extract.text_to_lines(text)
    hits = extract.extract_people_from_lines(lines, source_url, company_domain="")
    seen = {extract.name_key(h.name) for h in hits}

    committee_until = -1
    for i, line in enumerate(lines):
        if roles.is_csr_committee_heading(line.text):
            committee_until = i + 40
        elif roles.is_other_committee_heading(line.text):
            committee_until = -1
        if i > committee_until:
            continue
        name, role_text = _committee_member(line.text, lines[i + 1].text if i + 1 < len(lines) else "")
        if name and extract.name_key(name) not in seen:
            seen.add(extract.name_key(name))
            hits.append(
                extract.PersonHit(name, roles.committee_designation(role_text), "CSR Committee", 1, "report", source_url)
            )

    flat = re.sub(r"[ \t]+", " ", text)
    for raw_name, raw_title in _BRSR_AUTHORITY.findall(flat):
        name = extract.clean_person_name(raw_name)
        title = raw_title.strip(" ,-")
        if not name or extract.name_key(name) in seen:
            continue
        seen.add(extract.name_key(name))
        match = roles.classify(title)
        category, priority = (match.category, match.priority) if match else ("Sustainability Head", 1)
        hits.append(
            extract.PersonHit(
                name, f"{title} (responsible for business-responsibility policies, per BRSR)", category, priority,
                "report", source_url,
            )
        )
    for hit in hits:
        if hit.method in ("committee", "listing", "inline"):
            hit.method = "report"
    return hits


def scan_report(
    url: str,
    fetch: Callable[[str], tuple[Optional[bytes], Optional[str]]] = fetch_pdf,
    time_budget: float = REPORT_TIME_BUDGET_SECONDS,
) -> dict:
    """{people, pages_read, relevant_pages, message} for one report URL."""
    result = {"people": [], "pages_read": 0, "relevant_pages": [], "message": None}
    if not is_available():
        result["message"] = "Report scanning needs the 'pypdf' package on the server."
        return result
    data, reason = fetch(url)
    if data is None:
        result["message"] = reason
        return result
    try:
        pages, read, truncated = relevant_pages(data, time_budget)
    except Exception as exc:
        logger.info("Could not read report %s: %s", url, exc)
        result["message"] = "The report PDF couldn't be read (it may be scanned images or protected)."
        return result
    result["pages_read"] = read
    result["relevant_pages"] = [n for n, _ in pages]
    for page_number, text in pages:
        result["people"] += parse_report_text(text, f"{url}#page={page_number}")
    if pages and not result["people"]:
        result["message"] = (
            f"The report mentions the CSR Committee (page {', '.join(str(n) for n, _ in pages[:3])}) but doesn't "
            "list its members there - open it to check."
        )
    if not pages:
        result["message"] = (
            f"Read {read} pages of the report; none named the CSR Committee"
            + (" before the time limit - open the report to check the rest." if truncated else ".")
        )
    elif truncated:
        result["message"] = f"Read the first {read} pages of the report (time limit reached)."
    return result
