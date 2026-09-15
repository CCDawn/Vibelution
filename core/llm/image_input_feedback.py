"""Runtime image-input feedback learned from real LLM invocations.

A model's image-input capability is declared by curated presets, provider
discovery metadata, an operator override or an explicit probe. Real turns add
the missing evidence: when a request that actually carried image blocks
succeeds we can confirm support, and when the provider rejects it with an
"unsupported" style error we can deny it. Anything else (auth, rate limit,
timeout, network) proves nothing about image support and stays unwritten.
"""

from __future__ import annotations

from typing import Any

from config.model_catalog import classify_capability_error, make_model_key
from config.runtime_capabilities import record_model_image_input_capability

_IMAGE_BLOCK_TYPES = {"image", "image_url", "input_image", "image_input"}
_MAX_ERROR_TEXT = 2000


def messages_have_image_content(messages: Any) -> bool:
    """True when at least one message carries an image content block."""

    if not isinstance(messages, (list, tuple)):
        return False
    for item in messages:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, (list, tuple)):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "").strip().lower()
            if not block_type:
                continue
            if block_type in _IMAGE_BLOCK_TYPES or "image" in block_type:
                return True
    return False


def _error_text(error: Any) -> str:
    if error is None:
        return ""
    parts = [str(error)]
    details = getattr(error, "details", None)
    if isinstance(details, dict):
        for key in ("message", "error", "provider_message", "raw"):
            value = details.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value)
    return "\n".join(part for part in parts if part).strip()[:_MAX_ERROR_TEXT]


def record_image_input_turn_feedback(
    client: Any,
    messages: Any,
    *,
    ok: bool,
    error: Any = None,
    cache_path: Any = None,
) -> dict[str, Any]:
    """Persist image-input evidence from one real invoke; never guess."""

    if not messages_have_image_content(messages):
        return {}
    profile = getattr(client, "profile", None)
    provider = getattr(client, "provider", None)
    provider_id = str(
        getattr(profile, "provider_id", "") or getattr(provider, "provider_id", "") or ""
    ).strip()
    model = str(getattr(profile, "model", "") or "").strip()
    if not provider_id or not model:
        return {}
    model_ref = f"{provider_id}/{make_model_key(model)}"

    if ok:
        details: dict[str, Any] = {
            "supports_image_input": True,
            "capability_status": "supported",
        }
    else:
        error_text = _error_text(error)
        if not error_text or classify_capability_error(error_text) != "unsupported":
            return {}
        details = {
            "supports_image_input": False,
            "capability_status": "unsupported",
            "capability_error": error_text,
        }

    try:
        return record_model_image_input_capability(model_ref, details, cache_path=cache_path)
    except (OSError, ValueError):
        return {}


__all__ = ["messages_have_image_content", "record_image_input_turn_feedback"]
