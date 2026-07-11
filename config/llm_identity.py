from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from .llm_credentials import canonicalize_credential_ref


_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SAFE_MODEL_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def normalize_provider_endpoint(base_url: str) -> str:
    value = str(base_url or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("provider base_url must be an absolute http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("provider base_url cannot contain userinfo, query, or fragment")
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    display_host = f"[{host}]" if ":" in host else host
    port = parsed.port
    if port is not None and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        display_host = f"{display_host}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, display_host, path, "", ""))


def provider_identity_fingerprint(
    base_url: str,
    credential_ref: str,
    *,
    auth_kind: str,
    windows_env: bool | None = None,
) -> str:
    normalized_auth = str(auth_kind or "").strip().lower()
    canonical_ref = (
        "none"
        if normalized_auth == "none"
        else canonicalize_credential_ref(
            credential_ref,
            windows_env=windows_env,
        )
    )
    payload = normalize_provider_endpoint(base_url) + "\0" + canonical_ref
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_provider_id(provider_id: str) -> str:
    value = str(provider_id or "").strip()
    if not _PROVIDER_ID_RE.fullmatch(value):
        raise ValueError("provider_id must match [a-z][a-z0-9_-]{0,63}")
    return value


def make_model_key(upstream_id: str, *, max_length: int = 96) -> str:
    exact = unicodedata.normalize("NFKC", str(upstream_id or "").strip())
    if not exact:
        raise ValueError("upstream_id is required")
    if _SAFE_MODEL_KEY_RE.fullmatch(exact) and len(exact) <= max_length:
        return exact
    digest = hashlib.sha256(exact.encode("utf-8")).hexdigest()[:8]
    slug = re.sub(r"[^a-z0-9._-]+", "_", exact.lower()).strip("_.-") or "model"
    suffix = f"~{digest}"
    return f"{slug[: max_length - len(suffix)]}{suffix}"


def make_model_ref(provider_id: str, model_key: str) -> str:
    provider = validate_provider_id(provider_id)
    key = str(model_key or "").strip()
    if not key or "/" in key or len(key) > 96:
        raise ValueError("model_key must be a non-empty provider-scoped key of at most 96 characters")
    return f"{provider}/{key}"


def split_model_ref(model_ref: str) -> tuple[str, str]:
    provider_id, separator, model_key = str(model_ref or "").strip().partition("/")
    if not separator:
        raise ValueError("model_ref must use provider_id/model_key")
    canonical = make_model_ref(provider_id, model_key)
    return tuple(canonical.split("/", 1))


__all__ = [
    "make_model_key",
    "make_model_ref",
    "normalize_provider_endpoint",
    "provider_identity_fingerprint",
    "split_model_ref",
    "validate_provider_id",
]
