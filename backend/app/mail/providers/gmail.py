"""Gmail via Google OAuth 2.0 and the Gmail REST API (plain `requests`, no
Google SDK).

Scopes:
    gmail.send      - send the emails staff approve
    gmail.readonly  - read the conversations we started, to detect replies
                      and bounces (Gmail offers no narrower scope that
                      includes message bodies, which classification needs)
    openid, email   - learn which address was connected

What Gmail can and can't report: replies and bounces, yes. Delivery
receipts, opens and clicks, no - Gmail has no API for them, and this app
deliberately doesn't add tracking pixels or rewrite links.
"""

from __future__ import annotations

import base64
import html
import logging
import re
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from typing import Optional
from urllib.parse import urlencode

import requests

from ...config import settings
from .base import (
    Capabilities,
    EmailProvider,
    OutgoingMessage,
    ProviderAuthError,
    ProviderError,
    SentMessage,
    ThreadMessage,
    TokenSet,
)

logger = logging.getLogger("mail.gmail")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "openid",
    "email",
]
TIMEOUT = 20
_BOUNCE_SENDER = re.compile(r"mailer-daemon|postmaster|mail delivery subsystem", re.IGNORECASE)


def _expiry(expires_in) -> Optional[datetime]:
    try:
        return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in) - 60)
    except (TypeError, ValueError):
        return None


def _decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode()).decode("utf-8", errors="replace")


def _html_to_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", markup)
    return html.unescape(re.sub(r"<[^>]+>", " ", markup))


def message_body(payload: dict) -> str:
    """Plain-text body of a Gmail message payload (text/plain preferred,
    HTML converted as a fallback), searching nested multiparts.
    """
    plain, rich = [], []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            rich.append(_html_to_text(_decode(data)))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    text = "\n".join(plain) if plain else "\n".join(rich)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def strip_quoted(text: str) -> str:
    """Drop the quoted earlier message ("On Mon, X wrote:" / "> ...") so a
    reply is classified on what the person actually wrote.
    """
    lines = []
    for line in text.splitlines():
        if re.match(r"^\s*On .{5,200}wrote:\s*$", line) or re.match(r"^-{2,}\s*Original Message", line, re.I):
            break
        if line.lstrip().startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _headers(payload: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in payload.get("headers") or [] if "name" in h}


def parse_thread(data: dict) -> list[ThreadMessage]:
    """Pure parsing of a users.threads.get(format=full) response."""
    messages = []
    for item in data.get("messages") or []:
        payload = item.get("payload") or {}
        headers = _headers(payload)
        from_name, from_email = parseaddr(headers.get("from", ""))
        _, to_email = parseaddr(headers.get("to", ""))
        try:
            sent_at = datetime.fromtimestamp(int(item.get("internalDate", 0)) / 1000, tz=timezone.utc)
        except (TypeError, ValueError):
            sent_at = None
        messages.append(
            ThreadMessage(
                provider_message_id=item.get("id", ""),
                from_email=from_email.lower(),
                from_name=from_name or None,
                to_email=to_email.lower() or None,
                subject=headers.get("subject", ""),
                body=message_body(payload),
                sent_at=sent_at,
                rfc822_message_id=headers.get("message-id"),
                is_bounce=bool(_BOUNCE_SENDER.search(headers.get("from", ""))),
            )
        )
    return messages


def build_mime(message: OutgoingMessage) -> EmailMessage:
    mime = EmailMessage()
    mime["From"] = formataddr((message.from_name or "", message.from_email))
    mime["To"] = formataddr((message.to_name or "", message.to_email))
    mime["Subject"] = message.subject
    mime["Message-ID"] = make_msgid(domain=message.from_email.split("@")[-1])
    if message.in_reply_to:
        mime["In-Reply-To"] = message.in_reply_to
        mime["References"] = message.in_reply_to
    mime.set_content(message.body)
    return mime


class GmailProvider(EmailProvider):
    key = "gmail"
    label = "Gmail"
    capabilities = Capabilities(
        delivery=False,
        opens=False,
        clicks=False,
        replies=True,
        bounces=True,
        notes=[
            "Gmail doesn't report delivery, opens or clicks; the app doesn't add tracking pixels.",
            "Replies and bounces are detected by reading the conversations the app started.",
        ],
    )

    def is_configured(self) -> bool:
        return bool(settings.google_client_id and settings.google_client_secret)

    def setup_hint(self) -> str:
        return "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (see docs/EMAIL_AUTOMATION.md)."

    def authorization_url(self, state: str) -> str:
        return AUTH_URL + "?" + urlencode(
            {
                "client_id": settings.google_client_id,
                "redirect_uri": settings.gmail_redirect_uri,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "access_type": "offline",  # we need a refresh token
                "prompt": "consent",  # ...every time, or Google omits it on reconnect
                "include_granted_scopes": "true",
                "state": state,
            }
        )

    def _token_request(self, data: dict) -> dict:
        try:
            response = requests.post(TOKEN_URL, data=data, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise ProviderError(f"Could not reach Google: {exc}") from exc
        body = response.json() if response.content else {}
        if response.status_code == 400 and body.get("error") == "invalid_grant":
            raise ProviderAuthError("Google says the Gmail authorisation is no longer valid - reconnect Gmail.")
        if response.status_code != 200:
            raise ProviderError(f"Google token error: {body.get('error_description') or body.get('error') or response.status_code}")
        return body

    def exchange_code(self, code: str) -> TokenSet:
        body = self._token_request(
            {
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.gmail_redirect_uri,
                "grant_type": "authorization_code",
            }
        )
        tokens = TokenSet(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            expires_at=_expiry(body.get("expires_in")),
            scopes=body.get("scope", ""),
        )
        missing = [s for s in SCOPES[:2] if s not in tokens.scopes]
        if missing:
            raise ProviderError(
                "Gmail access wasn't fully granted. Reconnect and tick both 'send' and 'read' permissions."
            )
        tokens.email_address = self._get(tokens.access_token, "/profile").get("emailAddress", "")
        return tokens

    def refresh_access_token(self, refresh_token: str) -> TokenSet:
        body = self._token_request(
            {
                "refresh_token": refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
            }
        )
        return TokenSet(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            expires_at=_expiry(body.get("expires_in")),
            scopes=body.get("scope", ""),
        )

    def _request(self, method: str, access_token: str, path: str, **kwargs) -> dict:
        try:
            response = requests.request(
                method, API + path, headers={"Authorization": f"Bearer {access_token}"}, timeout=TIMEOUT, **kwargs
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Could not reach Gmail: {exc}") from exc
        if response.status_code == 401:
            raise ProviderAuthError("Gmail rejected the access token.")
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message")
            except ValueError:
                detail = None
            raise ProviderError(f"Gmail error {response.status_code}: {detail or response.reason}")
        return response.json() if response.content else {}

    def _get(self, access_token: str, path: str, **params) -> dict:
        return self._request("GET", access_token, path, params=params)

    def send(self, access_token: str, message: OutgoingMessage) -> SentMessage:
        mime = build_mime(message)
        payload = {"raw": base64.urlsafe_b64encode(mime.as_bytes()).decode()}
        if message.provider_thread_id:
            payload["threadId"] = message.provider_thread_id
        sent = self._request("POST", access_token, "/messages/send", json=payload)
        return SentMessage(
            provider_message_id=sent.get("id", ""),
            provider_thread_id=sent.get("threadId"),
            rfc822_message_id=mime["Message-ID"],
        )

    def thread_messages(self, access_token: str, provider_thread_id: str) -> list[ThreadMessage]:
        return parse_thread(self._get(access_token, f"/threads/{provider_thread_id}", format="full"))

    def revoke(self, token: str) -> None:
        try:
            requests.post(REVOKE_URL, params={"token": token}, timeout=TIMEOUT)
        except requests.RequestException:
            logger.info("Gmail token revoke failed; the grant can be removed at myaccount.google.com/permissions")
