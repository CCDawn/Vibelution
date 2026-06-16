"""Shared model capability inference for web services."""

from __future__ import annotations

from typing import Any


VISION_MODEL_NAME_HINTS = (
    "gpt-4o",
    "gpt-4.1",
    "gpt-5.5",
    "gpt-5o",
    "vision",
    "vl",
    "qwen-vl",
    "qvq",
    "gemini",
    "claude-3",
    "claude-4",
    "glm-4v",
    "multimodal",
    "omni",
)


def _record_details(record: dict[str, Any]) -> dict[str, Any]:
    details = record.get("details")
    return details if isinstance(details, dict) else {}


def model_record_image_input_support(
    record: dict[str, Any],
    *,
    provider_kind: str = "",
) -> bool | None:
    """Infer image-input support from one model record.

    Explicit operator configuration wins over model-name heuristics. A return
    value of ``None`` means unknown; callers decide whether unknown is allowed.
    """

    details = _record_details(record)
    supports = record.get("supports_image_input")
    if not isinstance(supports, bool):
        supports = details.get("supports_image_input")
    if isinstance(supports, bool):
        return supports

    capability_status = (
        str(record.get("capability_status") or details.get("capability_status") or "")
        .strip()
        .lower()
    )
    if capability_status == "supported":
        return True
    if capability_status == "unsupported":
        return False

    lowered_model = str(record.get("model") or details.get("model") or "").strip().lower()
    lowered_provider = str(provider_kind or record.get("provider_kind") or "").strip().lower()
    provider = record.get("provider")
    if not lowered_provider and isinstance(provider, dict):
        lowered_provider = str(provider.get("kind") or "").strip().lower()

    if lowered_provider == "xiaomi" and lowered_model == "mimo-v2.5":
        return True
    if any(hint in lowered_model for hint in VISION_MODEL_NAME_HINTS):
        return True
    return None
