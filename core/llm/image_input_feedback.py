"""Runtime image-input feedback learned from real LLM invocations.

A model's image-input capability is declared by curated presets, provider
discovery metadata, an operator override or an explicit probe. Real turns add
evidence on three levels:

- Confirmed: the request carried image blocks, the invoke succeeded and the
  model's reply actually referenced the image content. This is the only
  ok-path evidence strong enough to record ``supported``.
- Accepted-only: the request succeeded but the reply shows no sign the model
  saw the image. Providers and relays routinely accept image blocks and drop
  them silently, so this records ``unknown`` and never asserts support.
- Denied: the provider rejected the request with an "unsupported" style error,
  which records ``unsupported``. Anything else (auth, rate limit, timeout,
  network) proves nothing about image support and stays unwritten.
"""

from __future__ import annotations

from typing import Any

from config.model_catalog import classify_capability_error, make_model_key
from config.runtime_capabilities import record_model_image_input_capability

_IMAGE_BLOCK_TYPES = {"image", "image_url", "input_image", "image_input"}
_MAX_ERROR_TEXT = 2000
_MAX_REPLY_TEXT = 4000

# Replies that explicitly say the model cannot see or process the image.
# Checked first: a refusal always wins over any affirmative marker below.
_IMAGE_REPLY_REFUSAL_MARKERS = (
    "cannot see",
    "can't see",
    "cannot view",
    "can't view",
    "could not view",
    "couldn't view",
    "unable to view",
    "unable to see",
    "unable to process images",
    "cannot process images",
    "can't process images",
    "cannot analyze images",
    "can't analyze images",
    "cannot receive images",
    "can't receive images",
    "cannot access images",
    "can't access images",
    "cannot identify images",
    "can't identify images",
    "cannot interpret images",
    "not able to see",
    "not able to view",
    "do not support image",
    "doesn't support image",
    "don't support image",
    "does not support image",
    "do not support vision",
    "doesn't support vision",
    "text-only",
    "text only model",
    "无法查看",
    "看不到",
    "看不见",
    "无法识别图片",
    "无法识别图像",
    "无法处理图片",
    "无法处理图像",
    "无法分析图片",
    "无法分析图像",
    "无法接收图片",
    "无法读取图片",
    "无法读取图像",
    "不支持图片",
    "不支持图像",
)

# Nouns that indicate the reply is talking about an actual image. Kept
# conservative: generic words like "图" alone would match unrelated text.
_IMAGE_REPLY_EVIDENCE_MARKERS = (
    "image",
    "picture",
    "photo",
    "screenshot",
    "图片",
    "图像",
    "照片",
    "截图",
    "画面",
)

# Acts of visually describing or referring to what the image contains.
_IMAGE_REPLY_OBSERVATION_MARKERS = (
    "shows",
    "depicts",
    "appears",
    "i can see",
    "can be seen",
    "visible",
    "in the image",
    "in the picture",
    "in the photo",
    "in the screenshot",
    "displays",
    "显示",
    "可以看到",
    "看见",
    "看到",
    "图中",
    "图里",
    "画面中",
    "照片中",
    "图片中",
    "截图中",
    "描绘",
    "呈现",
)


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


def extract_response_text(response: Any) -> str:
    """Best-effort bounded text of one invoke result; never raises."""

    if response is None:
        return ""
    try:
        final_text = getattr(response, "final_text", None)
        if isinstance(final_text, str) and final_text.strip():
            return final_text[:_MAX_REPLY_TEXT]
        content = getattr(response, "content", None)
        if content is None and isinstance(response, dict):
            content = response.get("content")
        if isinstance(content, str):
            return content[:_MAX_REPLY_TEXT]
        if isinstance(content, (list, tuple)):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    text = block.get("text") or block.get("content")
                    if isinstance(text, str):
                        parts.append(text)
            return "\n".join(part for part in parts if part.strip())[:_MAX_REPLY_TEXT]
    except Exception:  # noqa: BLE001 - capability learning must never break a real invoke
        return ""
    return ""


def reply_confirms_image_content(reply_text: Any) -> bool:
    """Conservative check that a reply actually references image content.

    Requires both an image noun and an act of visual observation, and rejects
    any refusal phrasing. Bare affirmations ("ok", "done") prove nothing: a
    relay that silently dropped the image would produce them too.
    """

    lowered = str(reply_text or "").lower()
    if not lowered.strip():
        return False
    if any(marker in lowered for marker in _IMAGE_REPLY_REFUSAL_MARKERS):
        return False
    has_evidence = any(marker in lowered for marker in _IMAGE_REPLY_EVIDENCE_MARKERS)
    has_observation = any(marker in lowered for marker in _IMAGE_REPLY_OBSERVATION_MARKERS)
    return has_evidence and has_observation


def record_image_input_turn_feedback(
    client: Any,
    messages: Any,
    *,
    ok: bool,
    error: Any = None,
    response: Any = None,
    cache_path: Any = None,
) -> dict[str, Any]:
    """Persist image-input evidence from one real invoke; never guess.

    ``response`` is the invoke result when ``ok`` is true; its reply text is
    the only in-band signal that the model actually saw the image. Without it
    (or without a confirming reply) a successful image turn only records
    accepted-only evidence, which never flips ``supports_image_input`` to True.
    """

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
        if reply_confirms_image_content(extract_response_text(response)):
            details: dict[str, Any] = {
                "supports_image_input": True,
                "capability_status": "supported",
                "capability_confirmed": True,
            }
        else:
            details = {"capability_status": "unknown"}
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


__all__ = [
    "messages_have_image_content",
    "record_image_input_turn_feedback",
    "reply_confirms_image_content",
    "extract_response_text",
]
