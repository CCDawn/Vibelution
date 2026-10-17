"""Connection contracts for fixed presets, without reading credentials or config."""

from __future__ import annotations

import copy
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from config.llm_credentials import canonicalize_credential_ref
from config.llm_identity import normalize_provider_endpoint


def _service_class(kind: str, base_url: str) -> str:
    if kind in {"local", "local_runtime", "ollama", "llamacpp"}:
        return "local_runtime"
    if (urlsplit(base_url).hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}:
        return "local_runtime"
    if kind in {"relay", "openai_compatible"}:
        return "relay"
    return "aggregator" if kind in {"openrouter", "aggregator", "siliconflow"} else "official_api"


def _vendor(kind: str) -> str:
    token = kind.replace("-", "_")
    return "custom" if token in {"local", "local_runtime", "ollama", "llamacpp", "openai_compatible"} else token or "custom"


def _protocol_bundle(transports: set[str]) -> dict[str, Any]:
    allowed = sorted(transports) if transports else ["chat_completions"]
    return {"default": "chat_completions" if "chat_completions" in allowed else allowed[0], "allowed": allowed}


def normalize_provider_preset(
    raw_provider: dict[str, Any],
    raw_model: dict[str, Any],
    *,
    credential_env: str | None = None,
) -> dict[str, Any]:
    """Derive v2 fields from a fixed legacy preset; preserve explicit declarations.

    Legacy ``transport`` is a dialogue family, so a native Anthropic preset's
    chat_completions value does not select its outbound wire protocol.
    """
    kind = str(raw_provider.get("kind") or "").strip().lower()
    base_url = normalize_provider_endpoint(str(raw_provider.get("base_url") or ""))
    driver = str(raw_provider.get("driver") or ("anthropic" if kind == "anthropic" else "openai"))
    wire = str(raw_model.get("wire_protocol") or raw_provider.get("wire_protocol") or "").strip()
    if not wire:
        wire = "anthropic_messages" if driver == "anthropic" else str(raw_model.get("transport") or "chat_completions")
    protocols = raw_provider.get("protocols")
    protocols = copy.deepcopy(protocols) if isinstance(protocols, dict) and protocols else _protocol_bundle({wire})

    env_name = credential_env or str(raw_provider.get("api_key_env") or raw_model.get("api_key_env") or "").strip()
    requires = bool(raw_provider.get("requires_credential", raw_provider.get("requires_api_key", True)))
    reference = (
        f"env:{credential_env}" if credential_env else str(
            raw_provider.get("credential_ref") or (f"env:{env_name}" if env_name else "none")
        )
    )
    auth_kind = str(raw_provider.get("auth_kind") or ("api_key" if requires and reference != "none" else "none"))
    credential_ref = canonicalize_credential_ref("none" if auth_kind == "none" else reference)

    parsed = urlsplit(base_url)
    adapter = "openai_compatible"
    discovery: dict[str, Any] = {"mode": "auto", "adapter": adapter, "cache_ttl_seconds": 300}
    if driver == "anthropic":
        discovery["adapter"] = "anthropic"
    elif kind in {"google", "gemini"} and parsed.path.rstrip("/").endswith("/v1beta/openai"):
        discovery["adapter"] = "gemini"
        path = parsed.path.rstrip("/").removesuffix("/openai") + "/models"
        discovery["models_url_override"] = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    elif kind == "ollama" or (
        parsed.hostname in {"localhost", "127.0.0.1", "::1"} and parsed.port == 11434
    ):
        discovery["adapter"] = "ollama"
    if isinstance(raw_provider.get("discovery"), dict):
        explicit_discovery = copy.deepcopy(raw_provider["discovery"])
        # A different explicitly selected adapter owns its endpoint semantics.
        if explicit_discovery.get("adapter", discovery["adapter"]) != discovery["adapter"]:
            discovery.pop("models_url_override", None)
        discovery.update(explicit_discovery)
    connection = {
        "service_class": str(raw_provider.get("service_class") or _service_class(kind, base_url)),
        "vendor": str(raw_provider.get("vendor") or _vendor(kind)),
        "driver": driver,
        "base_url": base_url,
        "auth_kind": auth_kind,
        "credential_ref": credential_ref,
        "requires_credential": requires and auth_kind != "none",
        "protocols": protocols,
        "discovery": discovery,
    }
    for field in ("kind", "api", "compat_mode", "context_window", "extra_headers"):
        if field in raw_provider:
            connection[field] = copy.deepcopy(raw_provider[field])
    return connection
