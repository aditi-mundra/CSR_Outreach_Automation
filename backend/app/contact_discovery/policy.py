"""What contact discovery is allowed to keep.

Only *official work* details are collected:

- emails must be on the company's own domain - free/personal mail
  providers (gmail, yahoo, rediffmail, ...) are always dropped;
- phone numbers must look like an office line: Indian mobile numbers are
  always dropped, as is anything labelled mobile/cell/WhatsApp;
- LinkedIn is never fetched - a profile link is kept only when the
  company's own site (or a configured enrichment API) published it.

These checks run when results are found *and* again when they are saved,
so a client can't post a personal number into a saved contact through
the discovery save endpoint.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

FREE_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "ymail.com", "rocketmail.com",
    "hotmail.com", "hotmail.co.in", "outlook.com", "outlook.in", "live.com", "live.in", "msn.com",
    "rediffmail.com", "rediff.com", "icloud.com", "me.com", "mac.com", "aol.com", "protonmail.com",
    "proton.me", "gmx.com", "gmx.net", "mail.com", "yandex.com", "yandex.ru", "zohomail.com", "zohomail.in",
    "tutanota.com", "sify.com", "vsnl.com", "vsnl.net", "indiatimes.com",
}
_MULTI_PART_SUFFIXES = (
    ".co.in", ".org.in", ".net.in", ".gov.in", ".ac.in", ".edu.in", ".firm.in", ".gen.in", ".ind.in",
    ".co.uk", ".org.uk", ".com.au", ".com.sg", ".co.jp",
)
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_ASSET_SUFFIX = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js)$", re.IGNORECASE)
_MOBILE_LABEL = re.compile(r"\b(mobile|mob|cell|cellphone|whatsapp|personal)\b", re.IGNORECASE)
_FAX_LABEL = re.compile(r"\bfax\b", re.IGNORECASE)


def domain_of(website: Optional[str]) -> str:
    if not website:
        return ""
    parsed = urlparse(website if "://" in website else f"https://{website}")
    return (parsed.hostname or "").lower().removeprefix("www.")


def organization_label(domain: str) -> str:
    """'tatasteel' for tatasteel.com, www.tatasteel.co.in, csr.tatasteel.com."""
    domain = domain.lower().strip(".")
    for suffix in _MULTI_PART_SUFFIXES:
        if domain.endswith(suffix):
            domain = domain[: -len(suffix)]
            break
    else:
        domain = domain.rsplit(".", 1)[0] if "." in domain else domain
    return domain.rsplit(".", 1)[-1]


def is_free_mail(email: str) -> bool:
    return email.rsplit("@", 1)[-1].lower() in FREE_MAIL_DOMAINS


def is_company_email(email: Optional[str], company_domain: str) -> bool:
    """True for a work address on the company's own domain (any subdomain,
    or a sibling country domain like acme.co.in for acme.com).
    """
    if not email or "@" not in email or not company_domain:
        return False
    email = email.strip().lower()
    if not EMAIL_PATTERN.fullmatch(email) or _ASSET_SUFFIX.search(email) or is_free_mail(email):
        return False
    email_domain = email.rsplit("@", 1)[1]
    if email_domain == company_domain or email_domain.endswith("." + company_domain):
        return True
    label = organization_label(company_domain)
    return len(label) >= 3 and organization_label(email_domain) == label


def is_acceptable_email(email: Optional[str], company_domain: str) -> bool:
    """Save-time check: an on-domain work address, or - when the company's
    domain isn't known - at least not a personal mail provider.
    """
    if not email:
        return False
    if company_domain:
        return is_company_email(email, company_domain)
    return bool(EMAIL_PATTERN.fullmatch(email.strip())) and not is_free_mail(email)


def phone_digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def phone_key(phone: str) -> str:
    """Same number, any format: '+912027407000' == '+91 (020) 2740 7000'."""
    digits = phone_digits(phone)
    if digits.startswith("91") and len(digits) > 10:
        digits = digits[2:]
    return digits.lstrip("0")


def indian_number_rank(phone: str) -> int:
    """0 = clearly Indian (+91, 0-prefixed STD code, 1800/000800 toll-free),
    1 = no country code and no Indian prefix (could be anywhere - a US
    "425-476-3335" looks just like this), 2 = another country's code.
    Used to pick an Indian company's office line before overseas ones.
    """
    stripped = (phone or "").strip()
    if stripped.startswith("+"):
        return 0 if stripped.startswith("+91") else 2
    digits = phone_digits(stripped)
    return 0 if digits.startswith(("0", "1800", "1860")) else 1


def is_indian_mobile(phone: str) -> bool:
    """True for a number that is (or may be) an Indian mobile.

    Mobiles are 10 digits starting 6-9 - but so are landlines whose area
    code starts 6-8 (Bengaluru 80, Ahmedabad 79: "080 2844 0011"). The
    digits can't tell them apart; how the number is written can. Landlines
    are written with the area code as its own group ("+91 80 2844 0011",
    "(080) 2844 0011"); mobiles as 5+5 or 10 digits in a row. No area code
    starts with 9, and anything still ambiguous counts as a mobile.
    """
    stripped = (phone or "").strip()
    groups = re.findall(r"\d+", stripped)
    if stripped.startswith("+"):
        if not groups or groups[0] != "91" and not groups[0].startswith("91"):
            return False  # another country's number
        groups[0] = groups[0][2:]
    elif len("".join(groups)) == 12 and "".join(groups).startswith("91"):
        groups[0] = groups[0][2:]
    groups = [g for g in groups if g]
    if groups and groups[0].startswith("0"):  # trunk prefix, "(0)" or "080"
        groups[0] = groups[0][1:]
        groups = [g for g in groups if g]
    digits = "".join(groups)
    if len(digits) != 10 or digits[0] not in "6789":
        return False
    if digits[0] == "9":
        return True
    return not (2 <= len(groups[0]) <= 4 and len(groups) > 1)


def is_office_phone(phone: Optional[str], context: str = "") -> bool:
    """A published office/board line we may keep. Mobile-looking numbers,
    or numbers the page itself labels mobile/WhatsApp/fax, are refused.
    """
    if not phone:
        return False
    digits = phone_digits(phone)
    # Ten digits minimum: an Indian STD landline is 10, toll-free 11 - shorter
    # runs are fragments ("000 800 100") or reference numbers.
    if not 10 <= len(digits) <= 15:
        return False
    if _MOBILE_LABEL.search(context) or _FAX_LABEL.search(context):
        return False
    if is_indian_mobile(phone):
        return False
    stripped = phone.strip()
    international = stripped.startswith("+") and not stripped.startswith("+91")
    if international:
        # Outside India we can't tell a mobile from a landline by its
        # digits, so only keep numbers the page labels as an office line.
        return bool(re.search(r"\b(tel|phone|board|office|telephone|ph)\b", context, re.IGNORECASE))
    return True


def clean_phone(phone: str) -> str:
    return re.sub(r"\s+", " ", phone.strip().replace(" ", " ")).strip(" .,;:")


def is_linkedin_profile(url: Optional[str]) -> bool:
    return bool(url) and re.match(r"https?://([a-z]{2,3}\.)?linkedin\.com/in/[^/?#\s]+", url.strip(), re.IGNORECASE) is not None
