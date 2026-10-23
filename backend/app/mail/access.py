"""Optional shared-secret guard for endpoints that act on the mailbox.

This app has no user login (see docs/TASKS.md). Once a real Gmail account
is connected, anyone who can reach the API could otherwise connect a
different mailbox, send as the NGO, or disconnect it. Setting
APP_ACCESS_TOKEN makes those endpoints require the token in the
`X-App-Access-Token` header; the React app asks for it once and keeps it
in the browser.
"""

from __future__ import annotations

import hmac
from typing import Optional

from fastapi import Header, HTTPException

from ..config import settings


def require_mailbox_access(x_app_access_token: Optional[str] = Header(default=None)) -> None:
    expected = settings.app_access_token
    if not expected:
        return
    if not x_app_access_token or not hmac.compare_digest(x_app_access_token.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "access_token_required",
                "message": "This action needs the app access token (APP_ACCESS_TOKEN).",
            },
        )
