"""ChatGPT plan OAuth; bearer access is intentionally backend-only."""

from __future__ import annotations

import threading

from .auth import ChatGPTSubscriptionAuth
from .errors import ChatGPTSubscriptionError

_default_auth: ChatGPTSubscriptionAuth | None = None
_default_guard = threading.Lock()


def get_chatgpt_subscription_auth() -> ChatGPTSubscriptionAuth:
    global _default_auth
    with _default_guard:
        if _default_auth is None:
            _default_auth = ChatGPTSubscriptionAuth()
        return _default_auth


__all__ = ["ChatGPTSubscriptionAuth", "ChatGPTSubscriptionError", "get_chatgpt_subscription_auth"]
