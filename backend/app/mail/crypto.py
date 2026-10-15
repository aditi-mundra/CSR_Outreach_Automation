"""Encryption for stored OAuth tokens, and signed OAuth `state` values.

Tokens are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) using
TOKEN_ENCRYPTION_KEY, which lives only in the server environment - a
leaked database dump alone can't be used to read or send mail. Without a
key, connecting a mailbox is refused rather than storing tokens in clear.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings

STATE_TTL_SECONDS = 600


class EncryptionNotConfigured(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = settings.token_encryption_key.strip()
    if not key:
        raise EncryptionNotConfigured(
            "TOKEN_ENCRYPTION_KEY is not set. Generate one with: python -c \"from cryptography.fernet "
            "import Fernet; print(Fernet.generate_key().decode())\" and add it to the backend's .env."
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise EncryptionNotConfigured(f"TOKEN_ENCRYPTION_KEY is not a valid Fernet key ({exc}).") from exc


def is_configured() -> bool:
    try:
        _fernet()
    except EncryptionNotConfigured:
        return False
    return True


def encrypt(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: Optional[str]) -> Optional[str]:
    """Plaintext, or None if missing or unreadable (e.g. the key changed)."""
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


def _state_secret() -> bytes:
    # Derived from the encryption key so there's no second secret to manage.
    return hashlib.sha256(b"oauth-state:" + settings.token_encryption_key.encode()).digest()


def make_state(provider: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"p": provider, "t": int(time.time()), "n": secrets.token_urlsafe(8)}).encode()
    ).decode()
    signature = hmac.new(_state_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_state(state: str, provider: str) -> bool:
    """True only for a state this server issued, for this provider, recently."""
    try:
        payload, signature = state.rsplit(".", 1)
    except (ValueError, AttributeError):
        return False
    expected = hmac.new(_state_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode()))
    except (ValueError, TypeError):
        return False
    return data.get("p") == provider and time.time() - data.get("t", 0) <= STATE_TTL_SECONDS
