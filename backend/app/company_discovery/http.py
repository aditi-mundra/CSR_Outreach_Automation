"""Shared HTTP etiquette for discovery providers."""

from __future__ import annotations

import time
from pathlib import Path

import requests

from ..config import settings

REQUEST_TIMEOUT_SECONDS = 20
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def user_agent() -> str:
    """Identifiable User-Agent, as Wikimedia's and data.gov.in's API
    policies ask for - never a spoofed browser string.
    """
    contact = settings.discovery_contact.strip()
    suffix = f"; {contact}" if contact else ""
    return f"CSROutreachPortal/1.0 (NGO CSR outreach tool{suffix}) python-requests/{requests.__version__}"


MAX_RETRY_WAIT_SECONDS = 60.0


def retry_delay(response: requests.Response, attempt: int) -> float:
    """Seconds to wait before retrying a 429/503: the server's Retry-After
    if it sent one, else exponential backoff - capped either way.
    """
    try:
        return min(float(response.headers.get("Retry-After", "")), MAX_RETRY_WAIT_SECONDS)
    except ValueError:
        return min(5.0 * (2**attempt), MAX_RETRY_WAIT_SECONDS)


def get_json(
    url: str,
    params: dict,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
    headers: dict | None = None,
    retries: int = 0,
):
    """GET JSON. With retries > 0, a 429/503 is waited out (honouring
    Retry-After) instead of failing - for background jobs, not for
    requests a user is waiting on.
    """
    for attempt in range(retries + 1):
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": user_agent(), "Accept": "application/json", **(headers or {})},
            timeout=timeout,
        )
        if response.status_code in (429, 503) and attempt < retries:
            time.sleep(retry_delay(response, attempt))
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError("unreachable")


def resolve_backend_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else BACKEND_DIR / candidate
