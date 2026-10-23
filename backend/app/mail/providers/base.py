"""The interface every mailbox provider implements.

The rest of the app (app/mail/service.py) only talks to this interface:
OAuth, sending one message, and reading the messages of one conversation.
Providers also declare which tracking signals they can actually report,
so the UI never pretends to know about deliveries or opens it can't see.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class ProviderError(RuntimeError):
    """A call to the provider failed (network, quota, bad request)."""


class ProviderAuthError(ProviderError):
    """The stored grant no longer works (revoked, expired) - reconnect."""


@dataclass
class TokenSet:
    access_token: str
    refresh_token: Optional[str]
    expires_at: Optional[datetime]
    scopes: str = ""
    email_address: str = ""


@dataclass
class OutgoingMessage:
    from_email: str
    from_name: Optional[str]
    to_email: str
    to_name: Optional[str]
    subject: str
    body: str
    provider_thread_id: Optional[str] = None
    # RFC 822 Message-ID being replied to, so it threads in the recipient's inbox.
    in_reply_to: Optional[str] = None


@dataclass
class SentMessage:
    provider_message_id: str
    provider_thread_id: Optional[str]
    rfc822_message_id: Optional[str] = None


@dataclass
class ThreadMessage:
    provider_message_id: str
    from_email: str
    from_name: Optional[str]
    to_email: Optional[str]
    subject: str
    body: str
    sent_at: Optional[datetime]
    rfc822_message_id: Optional[str] = None
    is_bounce: bool = False


@dataclass
class Capabilities:
    delivery: bool = False
    opens: bool = False
    clicks: bool = False
    replies: bool = True
    bounces: bool = True
    notes: list[str] = field(default_factory=list)


class EmailProvider(ABC):
    key: str = ""
    label: str = ""
    capabilities = Capabilities()

    @abstractmethod
    def is_configured(self) -> bool:
        """True when the server has this provider's OAuth client settings."""

    @abstractmethod
    def setup_hint(self) -> str: ...

    @abstractmethod
    def authorization_url(self, state: str) -> str: ...

    @abstractmethod
    def exchange_code(self, code: str) -> TokenSet: ...

    @abstractmethod
    def refresh_access_token(self, refresh_token: str) -> TokenSet: ...

    @abstractmethod
    def send(self, access_token: str, message: OutgoingMessage) -> SentMessage: ...

    @abstractmethod
    def thread_messages(self, access_token: str, provider_thread_id: str) -> list[ThreadMessage]: ...

    def revoke(self, token: str) -> None:
        """Best effort; disconnecting must succeed even if this fails."""
