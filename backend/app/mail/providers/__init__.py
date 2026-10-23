"""Email providers. Gmail is implemented; adding Outlook means writing an
`OutlookProvider(EmailProvider)` and registering it in `PROVIDERS`.
"""

from .base import EmailProvider, ProviderAuthError, ProviderError  # noqa: F401
from .gmail import GmailProvider

PROVIDERS: dict[str, EmailProvider] = {"gmail": GmailProvider()}


def get_provider(key: str) -> EmailProvider:
    provider = PROVIDERS.get(key)
    if provider is None:
        raise KeyError(key)
    return provider
