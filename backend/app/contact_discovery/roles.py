"""Which job titles count as CSR outreach targets, and how important each is.

Priority 1 - people who decide CSR spending: CSR / Sustainability / ESG
             heads, Foundation directors, the board's CSR Committee and
             the CSR team itself.
Priority 2 - people who can route an NGO to them: HR, Corporate
             Communications, Public Relations, Corporate Affairs.
Priority 3 - local leadership who can sponsor a regional project:
             Regional/Branch/General Managers, Business Unit and
             Operations heads.

A title only counts when it pairs a role area ("CSR", "HR", ...) with a
role word ("Head", "Manager", ...) - so "CSR Policy" or "HR Solutions"
(a page heading, a product) never become a contact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

PRIORITY_LABELS = {
    1: "CSR & Sustainability",
    2: "HR & Communications",
    3: "Regional & Operations",
}

_SENIOR = (
    r"head|director|chief|vp|vice president|president|gm|general manager|lead|leader|chair|chairman|"
    r"chairperson|chairwoman|trustee|ceo|coo|avp|svp|evp|dgm|agm|in charge|incharge|principal|convenor|convener"
)
_JUNIOR = r"manager|officer|executive|coordinator|co ordinator|specialist|associate|analyst|consultant|advisor|adviser|secretary"
# A person's title needs a person-level role word: "CSR Team" or "CSR Cell"
# alone is a page heading, not somebody's designation.
_ROLE_WORD = re.compile(rf"\b({_SENIOR}|{_JUNIOR})\b")
_SENIOR_WORD = re.compile(rf"\b({_SENIOR})\b")
_ADDRESS = re.compile(r"\b(head|registered|corporate|branch|regional|zonal) offices?\b|\b(ltd|limited|pvt|llp|inc)\b")
_EXCLUDED = re.compile(r"\b(intern|trainee|student|apprentice|recruit\w*|talent acquisition|candidate)\b")

_CSR = r"csr|corporate social responsibilit\w*|social responsibilit\w*|social impact|community (development|relations|affairs|engagement|initiatives|investment)"
_CSR_COMMITTEE = re.compile(rf"\b({_CSR})( and [a-z]+)?( \(?csr\)?)? committee\b")
_COMMITTEE_ROLE = re.compile(r"\b(chair\w*|member|convenor|convener|secretary)\b")
# Board committees other than CSR - their member lists must not be read as
# the CSR committee's.
OTHER_COMMITTEE = re.compile(
    r"\b(audit|nomination|remuneration|stakeholders?|risk|finance|investment|share ?transfer|executive|"
    r"allotment|banking|ethics|it strategy|borrowing)\b[a-z &,]*\bcommittee\b"
)


@dataclass(frozen=True)
class RoleMatch:
    category: str
    priority: int
    senior: bool


# (pattern on the normalized title, senior category, non-senior category, priority)
# Checked in order; Priority 1 first, so "GM - CSR" is a CSR Head, not a
# General Manager.
_RULES: list[tuple[re.Pattern, str, str, int]] = [
    (re.compile(r"\bfoundation\b"), "Foundation Director", "Foundation Team", 1),
    (re.compile(r"\besg\b"), "ESG Head", "ESG Manager", 1),
    (re.compile(r"\bsustainab\w*"), "Sustainability Head", "Sustainability Manager", 1),
    (re.compile(rf"\b({_CSR})\b"), "CSR Head", "CSR Manager", 1),
    (
        re.compile(r"\b(hr|hrd|human resources?|human capital|people (and|&) culture|people officer|chro|chief people)\b"),
        "HR Director",
        "HR Manager",
        2,
    ),
    (
        re.compile(r"\b(corporate communications?|corp comm|communications?|brand and communications?)\b"),
        "Corporate Communications Head",
        "Corporate Communications",
        2,
    ),
    (re.compile(r"\b(public relations|pr|media relations)\b"), "Public Relations Head", "Public Relations", 2),
    (
        re.compile(r"\b(corporate|public|external|government|regulatory) affairs\b"),
        "Corporate Affairs Head",
        "Corporate Affairs",
        2,
    ),
    (re.compile(r"\b(regional|region|zonal|zone|circle|cluster|area)\b"), "Regional Manager", "Regional Manager", 3),
    (re.compile(r"\bbranch\b"), "Branch Manager", "Branch Manager", 3),
    (
        re.compile(r"\b(business unit|bu head|business head|sbu|strategic business unit|division head)\b"),
        "Business Unit Head",
        "Business Unit Head",
        3,
    ),
    (re.compile(r"\b(operations|ops|chief operating officer|coo|plant head|works)\b"), "Operations Head", "Operations Manager", 3),
    (re.compile(r"\b(general manager|gm)\b"), "General Manager", "General Manager", 3),
]


def normalize_title(text: Optional[str]) -> str:
    lowered = (text or "").lower().replace("&", " and ")
    lowered = re.sub(r"[^a-z0-9()]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def classify(title: Optional[str], committee_context: bool = False) -> Optional[RoleMatch]:
    """Target role for a job title, or None if it isn't one.

    `committee_context` is set while reading a page section about the CSR
    Committee, where a bare "Chairman" or "Member" means a CSR Committee
    seat.
    """
    norm = normalize_title(title)
    # Office addresses ("Wipro Ltd (APMEA Head office) (DWTCA Branch)") are
    # places, not people: "head office" / "branch" there aren't job titles,
    # and a real designation never contains a company's legal suffix.
    if _ADDRESS.search(norm):
        return None
    if not norm or len(norm) > 140 or _EXCLUDED.search(norm):
        return None
    if _CSR_COMMITTEE.search(norm):
        # "Chairman, CSR Committee" is a seat; "CSR Committee" alone is a heading.
        return RoleMatch("CSR Committee", 1, True) if _COMMITTEE_ROLE.search(norm) else None
    if committee_context and _COMMITTEE_ROLE.search(norm):
        return RoleMatch("CSR Committee", 1, True)
    if not _ROLE_WORD.search(norm):
        return None
    senior = bool(_SENIOR_WORD.search(norm))
    for pattern, senior_category, other_category, priority in _RULES:
        if pattern.search(norm):
            return RoleMatch(senior_category if senior else other_category, priority, senior)
    return None


def committee_designation(row_text: str) -> str:
    """'Chairperson, CSR Committee' / 'Member, CSR Committee' from a
    committee-table row or line.
    """
    norm = normalize_title(row_text)
    if re.search(r"\bchair\w*", norm):
        return "Chairperson, CSR Committee"
    if re.search(r"\b(convenor|convener|secretary)\b", norm):
        return "Secretary, CSR Committee"
    return "Member, CSR Committee"


def is_csr_committee_heading(text: str) -> bool:
    return bool(_CSR_COMMITTEE.search(normalize_title(text)))


def is_other_committee_heading(text: str) -> bool:
    norm = normalize_title(text)
    return bool(OTHER_COMMITTEE.search(norm)) and not _CSR_COMMITTEE.search(norm)


# ----------------------------------------------------------------------------
# Role mailboxes (csr@, hr@, corpcomm@ ...) published on the company's site
# ----------------------------------------------------------------------------
_MAILBOX_ROLES: list[tuple[set[str], str, int]] = [
    (
        {"csr", "csrteam", "csrcell", "csrinfo", "csrindia", "sustainability", "esg", "foundation", "community",
         "socialresponsibility", "corporatesocialresponsibility", "csrdesk"},
        "CSR Team",
        1,
    ),
    ({"hr", "hrd", "humanresources", "hrteam", "people", "hrdesk"}, "HR Team", 2),
    (
        {"corpcomm", "corporatecommunications", "corpcomms", "communications", "media", "mediarelations",
         "pr", "press", "publicrelations", "corporateaffairs", "brand"},
        "Corporate Communications Team",
        2,
    ),
]
# General office inboxes - shown as company contact points, not as people.
GENERAL_MAILBOXES = {
    "info", "contact", "contactus", "enquiry", "enquiries", "inquiry", "inquiries", "query", "queries",
    "mail", "office", "corporate", "headoffice", "ho", "hello", "reception", "communication",
}


def mailbox_role(local_part: str) -> Optional[tuple[str, int]]:
    """(team label, priority) for a role mailbox's local part, matched on
    whole tokens so "prakash@" is never read as "pr@".
    """
    local = local_part.lower()
    tokens = re.split(r"[._\-+]", local)
    joined = re.sub(r"[._\-+]", "", local)
    for keys, label, priority in _MAILBOX_ROLES:
        if joined in keys or tokens[0] in keys:
            return label, priority
    return None


def is_general_mailbox(local_part: str) -> bool:
    local = local_part.lower()
    return re.sub(r"[._\-+]", "", local) in GENERAL_MAILBOXES or re.split(r"[._\-+]", local)[0] in GENERAL_MAILBOXES
