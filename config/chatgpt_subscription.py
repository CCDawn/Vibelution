"""Identity and destination constraints for ChatGPT plan inference.

The OAuth grant is for the public Responses resource. It is never an API key
for arbitrary OpenAI-compatible services or a credential for Codex Desktop.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CHATGPT_CREDENTIAL_REF = "oauth:chatgpt"
CHATGPT_API_BASE = "https://api.openai.com/v1"


def _field(provider: Any, key: str, default: Any = "") -> Any:
    return provider.get(key, default) if isinstance(provider, Mapping) else getattr(provider, key, default)


def is_subscription_provider(provider: Any) -> bool:
    from .llm_credentials import canonicalize_credential_ref

    try:
        reference = canonicalize_credential_ref(str(_field(provider, "credential_ref") or ""))
    except ValueError:
        return False
    return reference == CHATGPT_CREDENTIAL_REF


def validate_subscription_provider(provider: Any) -> None:
    if not is_subscription_provider(provider):
        return
    if (str(_field(provider, "auth_kind")) != "oauth"
            or str(_field(provider, "driver")) != "openai"
            or str(_field(provider, "service_class")) != "official_api"
            or str(_field(provider, "base_url")).rstrip("/") != CHATGPT_API_BASE):
        raise ValueError("ChatGPT subscription requires OAuth and the official Responses API origin")
    protocols = _field(provider, "protocols", {})
    if (_field(protocols, "default") != "responses"
            or list(_field(protocols, "allowed", [])) != ["responses"]):
        raise ValueError("ChatGPT subscription supports only the Responses protocol")
    routes = dict(_field(protocols, "routes", {}) or {})
    if any(key != "responses" or str(value).strip() != "responses" for key, value in routes.items()):
        raise ValueError("ChatGPT subscription routes cannot redirect the OAuth credential")
    discovery = _field(provider, "discovery", {})
    if str(_field(discovery, "adapter") or "") != "openai":
        raise ValueError("ChatGPT subscription model discovery requires the official bearer adapter")
    if str(_field(discovery, "models_url_override") or "").strip():
        raise ValueError("ChatGPT subscription model discovery cannot override the official resource")


def build_subscription_provider() -> dict[str, Any]:
    """A draft provider; neither registers a login nor changes active defaults."""
    return {
        "label": "ChatGPT 订阅",
        "service_class": "official_api",
        "vendor": "openai",
        "driver": "openai",
        "auth_kind": "oauth",
        "credential_ref": CHATGPT_CREDENTIAL_REF,
        "requires_credential": True,
        "base_url": CHATGPT_API_BASE,
        "protocols": {"default": "responses", "allowed": ["responses"], "routes": {"responses": "responses"}},
        "discovery": {"adapter": "openai"},
        "models": {},
    }
