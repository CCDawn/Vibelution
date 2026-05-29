"""Small helpers for OpenAI-compatible image model discovery."""

from __future__ import annotations

import re
from typing import Any


IMAGE_MODEL_PLACEHOLDERS = {"image", "images", "image2", "default_image", "default-image"}
PREFERRED_IMAGE_MODELS = ("gpt-image-1.5", "gpt-image-2", "gpt-image-1", "dall-e-3")
_IMAGE_MODEL_TOKEN = re.compile(r"(?:^|[-_/.])(image|imagen|dall)(?:$|[-_/.0-9])", re.IGNORECASE)


def is_probable_image_model(model_id: str) -> bool:
    normalized = str(model_id or "").strip().lower()
    if not normalized or normalized in IMAGE_MODEL_PLACEHOLDERS:
        return False
    return bool(_IMAGE_MODEL_TOKEN.search(normalized))


def should_discover_image_model(configured_model: str) -> bool:
    return not is_probable_image_model(configured_model)


def image_models_discovery_url(base_url: str) -> str:
    root = str(base_url or "").strip().rstrip("/")
    if not root:
        return ""
    if root.lower().endswith("/v1"):
        return f"{root}/models"
    return f"{root}/v1/models"


def choose_image_model(discovered_models: list[str]) -> str:
    available = [str(model or "").strip() for model in discovered_models if str(model or "").strip()]
    if not available:
        return ""
    available_set = set(available)
    for preferred in PREFERRED_IMAGE_MODELS:
        if preferred in available_set:
            return preferred
    return available[0]


def discover_image_models(
    *,
    base_url: str,
    api_key: str = "",
    headers: dict[str, str] | None = None,
    timeout: int | float = 8,
    requests_module: Any | None = None,
) -> dict[str, Any]:
    """Return image-capable model ids from an OpenAI-compatible /models endpoint."""

    url = image_models_discovery_url(base_url)
    if not url:
        return _discovery_result(status="missing_base_url", url="", error="missing base_url")

    try:
        requests = requests_module
        if requests is None:
            import requests as requests  # type: ignore[no-redef]
    except Exception as exc:  # pragma: no cover
        return _discovery_result(status="failed", url=url, error=f"requests unavailable: {type(exc).__name__}")

    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update({str(key): str(value) for key, value in headers.items() if str(key).strip()})
    if api_key:
        request_headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.get(url, headers=request_headers, timeout=max(1, float(timeout or 8)))
    except Exception as exc:
        return _discovery_result(status="failed", url=url, error=_safe_error(f"{type(exc).__name__}: {str(exc)}", api_key))
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code >= 400:
        text = str(getattr(response, "text", "") or "")
        return _discovery_result(status="failed", url=url, error=_safe_error(f"HTTP {status_code}: {text}", api_key))
    try:
        payload = response.json()
    except Exception as exc:
        return _discovery_result(status="failed", url=url, error=_safe_error(f"invalid JSON: {type(exc).__name__}", api_key))

    model_ids = _extract_model_ids(payload)
    image_models = _unique([model_id for model_id in model_ids if is_probable_image_model(model_id)])
    selected = choose_image_model(image_models)
    return {
        **_discovery_result(status="succeeded" if image_models else "empty", url=url, error=""),
        "models": image_models,
        "selectedModel": selected,
    }


def resolve_image_model(
    *,
    configured_model: str,
    base_url: str,
    api_key: str = "",
    headers: dict[str, str] | None = None,
    timeout: int | float = 8,
    requests_module: Any | None = None,
) -> dict[str, Any]:
    configured = str(configured_model or "").strip()
    if not should_discover_image_model(configured):
        return {
            "model": configured,
            "configuredModel": configured,
            "discovery": _discovery_result(status="skipped", url=image_models_discovery_url(base_url), error=""),
        }
    discovery = discover_image_models(
        base_url=base_url,
        api_key=api_key,
        headers=headers,
        timeout=timeout,
        requests_module=requests_module,
    )
    resolved = str(discovery.get("selectedModel") or "").strip() or configured
    return {
        "model": resolved,
        "configuredModel": configured,
        "discovery": discovery,
    }


def _discovery_result(*, status: str, url: str, error: str) -> dict[str, Any]:
    return {
        "ok": status in {"succeeded", "skipped"},
        "status": status,
        "url": url,
        "models": [],
        "selectedModel": "",
        "error": error,
    }


def _extract_model_ids(payload: Any) -> list[str]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        return []
    ids: list[str] = []
    for item in data:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict):
            ids.append(str(item.get("id") or item.get("model") or "").strip())
    return [model_id for model_id in ids if model_id]


def _safe_error(value: str, api_key: str) -> str:
    text = str(value or "")
    if api_key:
        text = text.replace(api_key, "[redacted]")
    return text[:200]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
