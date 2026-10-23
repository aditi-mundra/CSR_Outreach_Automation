"""Default email templates and placeholder filling.

Templates make drafting work without an AI key, and give staff a
consistent starting point they can edit in Settings. Placeholders:

    {contact_name} {contact_first_name} {contact_designation}
    {company_name} {csr_focus} {ngo_name} {ngo_work_area}
    {sender_name} {signature}

Unknown or empty placeholders render as sensible fallbacks ("there",
"your CSR team") rather than leaving "{...}" in an email.
"""

from __future__ import annotations

import re
import string

DEFAULT_TEMPLATES: list[dict] = [
    {
        "email_type": "first_outreach",
        "name": "First outreach",
        "subject": "Partnering with {company_name} on {csr_focus}",
        "body": (
            "Dear {contact_first_name},\n\n"
            "I'm writing from {ngo_name}, where we work on {ngo_work_area}. We've been following "
            "{company_name}'s CSR work in {csr_focus}, and we believe there is a real opportunity "
            "to create impact together.\n\n"
            "Would you be open to a short call in the coming weeks to explore whether a partnership "
            "could fit your CSR plans for this year?\n\n"
            "Thank you for your time.\n\n"
            "{signature}"
        ),
    },
    {
        "email_type": "follow_up",
        "name": "Follow-up",
        "subject": "Following up: {ngo_name} and {company_name}",
        "body": (
            "Dear {contact_first_name},\n\n"
            "I wanted to follow up on my earlier note about a possible CSR partnership between "
            "{company_name} and {ngo_name}. I understand things get busy, so I'm happy to share a "
            "short overview of our work in {ngo_work_area} if that would help.\n\n"
            "Would a brief call be possible sometime soon?\n\n"
            "{signature}"
        ),
    },
    {
        "email_type": "meeting_request",
        "name": "Meeting request",
        "subject": "Meeting request: {ngo_name} x {company_name}",
        "body": (
            "Dear {contact_first_name},\n\n"
            "Thank you for your interest. We would be glad to meet and walk you through our "
            "programmes in {ngo_work_area} and how they could align with {company_name}'s CSR "
            "priorities.\n\n"
            "Please let me know a few times that work for you, and whether you prefer to meet in "
            "person or online.\n\n"
            "{signature}"
        ),
    },
    {
        "email_type": "thank_you",
        "name": "Thank you",
        "subject": "Thank you from {ngo_name}",
        "body": (
            "Dear {contact_first_name},\n\n"
            "Thank you for taking the time to speak with us. We truly appreciate {company_name}'s "
            "interest in supporting {ngo_work_area}, and we look forward to the next steps.\n\n"
            "{signature}"
        ),
    },
    {
        "email_type": "proposal",
        "name": "Proposal",
        "subject": "CSR proposal for {company_name}",
        "body": (
            "Dear {contact_first_name},\n\n"
            "As discussed, please find our CSR proposal for {company_name}. It outlines the "
            "programme, expected outcomes and budget for our work in {ngo_work_area}.\n\n"
            "I'd be happy to answer any questions or adjust the proposal to your priorities.\n\n"
            "{signature}"
        ),
    },
]


class _Defaults(dict):
    def __missing__(self, key):
        return ""


def build_context(
    *,
    contact_name: str | None,
    contact_designation: str | None,
    company_name: str,
    csr_focus: str | None,
    ngo_name: str,
    ngo_work_area: str,
    sender_name: str | None,
    signature: str | None,
) -> dict:
    first = (contact_name or "").split()
    first_name = first[0] if first and not first[0].endswith(".") else (contact_name or "")
    sign_off = signature.strip() if signature and signature.strip() else (
        f"Warm regards,\n{sender_name or ngo_name}\n{ngo_name}"
    )
    return {
        "contact_name": contact_name or "there",
        "contact_first_name": first_name or "there",
        "contact_designation": contact_designation or "",
        "company_name": company_name,
        "csr_focus": (csr_focus or "").split(",")[0].strip() or "community development",
        "ngo_name": ngo_name,
        "ngo_work_area": ngo_work_area,
        "sender_name": sender_name or ngo_name,
        "signature": sign_off,
    }


def render(text: str, context: dict) -> str:
    """Fill {placeholders}; unknown ones become empty, stray braces are kept."""
    formatter = string.Formatter()
    out = []
    try:
        for literal, field, spec, conversion in formatter.parse(text):
            out.append(literal)
            if field is not None:
                out.append(str(_Defaults(context)[field]))
    except ValueError:  # unbalanced braces typed by staff - leave the text as-is
        return text
    return re.sub(r"[ \t]+\n", "\n", "".join(out))
