from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx

from .types import (
    DiscoveredProviderModel,
    ProviderDiscoveryAdapter,
    ProviderDiscoveryRequest,
    ProviderDiscoveryResult,
)


MAX_DISCOVERY_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_DISCOVERED_MODELS = 5000
MAX_UPSTREAM_ID_LENGTH = 512


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_endpoint(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _join_endpoint(base_url: str, suffix: str) -> str:
    return f"{str(base_url).rstrip('/')}/{suffix.lstrip('/')}"


def _service_root(base_url: str) -> str:
    value = str(base_url).rstrip("/")
    for suffix in ("/v1beta", "/v1"):
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


def _bounded_json_get(
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, str] | None,
    request: ProviderDiscoveryRequest,
) -> Any:
    timeout = min(max(float(request.timeout_seconds), 0.5), 15.0)
    try:
        with httpx.Client(
            timeout=timeout,
            headers=headers,
            follow_redirects=False,
            transport=request.transport,
        ) as client:
            with client.stream("GET", url, params=params) as response:
                if response.is_error or response.is_redirect:
                    safe_request = httpx.Request("GET", _safe_endpoint(str(response.request.url)))
                    safe_response = httpx.Response(response.status_code, request=safe_request)
                    raise httpx.HTTPStatusError(
                        f"provider discovery request failed with HTTP {response.status_code}",
                        request=safe_request,
                        response=safe_response,
                    )
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_DISCOVERY_RESPONSE_BYTES:
                        raise ValueError("model discovery response exceeds 2 MiB")
                    chunks.append(chunk)
    except httpx.TimeoutException:
        raise httpx.TimeoutException(
            "provider discovery request timed out",
            request=httpx.Request("GET", _safe_endpoint(url)),
        ) from None
    except httpx.RequestError as exc:
        safe_request = httpx.Request("GET", _safe_endpoint(url))
        error_type = type(exc)
        try:
            sanitized_error = error_type("provider discovery request failed", request=safe_request)
        except TypeError:
            sanitized_error = httpx.RequestError("provider discovery request failed", request=safe_request)
        raise sanitized_error from None
    return json.loads(b"".join(chunks))


def _validate_models(models: list[DiscoveredProviderModel]) -> tuple[DiscoveredProviderModel, ...]:
    if len(models) > MAX_DISCOVERED_MODELS:
        raise ValueError("model discovery returned more than 5000 models")
    seen: set[str] = set()
    normalized: list[DiscoveredProviderModel] = []
    for model in models:
        if len(model.upstream_id) > MAX_UPSTREAM_ID_LENGTH:
            raise ValueError("model id exceeds 512 Unicode code points")
        if model.upstream_id and model.upstream_id not in seen:
            seen.add(model.upstream_id)
            normalized.append(model)
    return tuple(normalized)


def _model(raw: Any, *, id_field: str = "id", strip_prefix: str = "") -> DiscoveredProviderModel | None:
    if not isinstance(raw, dict):
        return None
    upstream_id = str(raw.get(id_field) or "").strip()
    if strip_prefix and upstream_id.startswith(strip_prefix):
        upstream_id = upstream_id[len(strip_prefix) :]
    if not upstream_id:
        return None
    limits = {}
    if raw.get("context_window") is not None:
        limits["context_window"] = raw["context_window"]
    capabilities = copy.deepcopy(raw.get("capabilities")) if isinstance(raw.get("capabilities"), dict) else {}
    return DiscoveredProviderModel(
        upstream_id=upstream_id,
        label=str(raw.get("display_name") or raw.get("label") or upstream_id),
        capabilities=capabilities,
        limits=limits,
    )


def _discover_candidates(
    request: ProviderDiscoveryRequest,
    adapter_id: str,
    endpoints: list[str],
    *,
    headers: dict[str, str],
    params: dict[str, str] | None,
    normalize: Callable[[Any], list[DiscoveredProviderModel]],
) -> ProviderDiscoveryResult:
    attempted: list[str] = []
    last_error: Exception | None = None
    saw_empty_response = False
    for endpoint in endpoints:
        attempted.append(_safe_endpoint(endpoint))
        try:
            payload = _bounded_json_get(endpoint, headers=headers, params=params, request=request)
            models = _validate_models(normalize(payload))
        except Exception as exc:
            last_error = exc
            continue
        if models:
            return ProviderDiscoveryResult(
                provider_id=request.provider_id,
                adapter_id=adapter_id,
                attempted_endpoints=tuple(attempted),
                discovered_at=_utcnow_iso(),
                models=models,
            )
        saw_empty_response = True
    if last_error is not None and not saw_empty_response:
        raise last_error
    return ProviderDiscoveryResult(
        provider_id=request.provider_id,
        adapter_id=adapter_id,
        attempted_endpoints=tuple(attempted),
        discovered_at=_utcnow_iso(),
        models=(),
    )


@dataclass(frozen=True)
class OpenAICompatibleDiscoveryAdapter:
    adapter_id: str

    def discover(self, request: ProviderDiscoveryRequest) -> ProviderDiscoveryResult:
        base = str(request.provider.get("base_url") or "").rstrip("/")
        endpoints = [_join_endpoint(base, "models")] if base.endswith("/v1") else [
            _join_endpoint(base, "v1/models"),
            _join_endpoint(base, "models"),
        ]
        headers = {"Authorization": f"Bearer {request.credential}"} if request.credential else {}
        return _discover_candidates(
            request,
            self.adapter_id,
            endpoints,
            headers=headers,
            params=None,
            normalize=lambda payload: [
                model
                for raw in payload.get("data", []) if isinstance(payload, dict)
                if (model := _model(raw)) is not None
            ],
        )


class OllamaDiscoveryAdapter:
    adapter_id = "ollama"

    def discover(self, request: ProviderDiscoveryRequest) -> ProviderDiscoveryResult:
        endpoint = _join_endpoint(_service_root(str(request.provider.get("base_url") or "")), "api/tags")

        def normalize(payload: Any) -> list[DiscoveredProviderModel]:
            if not isinstance(payload, dict):
                return []
            return [model for raw in payload.get("models", []) if (model := _model(raw, id_field="name")) is not None]

        return _discover_candidates(
            request,
            self.adapter_id,
            [endpoint],
            headers={},
            params=None,
            normalize=normalize,
        )


class AnthropicDiscoveryAdapter:
    adapter_id = "anthropic"

    def discover(self, request: ProviderDiscoveryRequest) -> ProviderDiscoveryResult:
        endpoint = _join_endpoint(_service_root(str(request.provider.get("base_url") or "")), "v1/models")
        return _discover_candidates(
            request,
            self.adapter_id,
            [endpoint],
            headers={"x-api-key": request.credential, "anthropic-version": "2023-06-01"},
            params=None,
            normalize=lambda payload: [
                model
                for raw in payload.get("data", []) if isinstance(payload, dict)
                if (model := _model(raw)) is not None
            ],
        )


class GeminiDiscoveryAdapter:
    adapter_id = "gemini"

    def discover(self, request: ProviderDiscoveryRequest) -> ProviderDiscoveryResult:
        endpoint = _join_endpoint(_service_root(str(request.provider.get("base_url") or "")), "v1beta/models")
        return _discover_candidates(
            request,
            self.adapter_id,
            [endpoint],
            headers={},
            params={"key": request.credential},
            normalize=lambda payload: [
                model
                for raw in payload.get("models", []) if isinstance(payload, dict)
                if (model := _model(raw, id_field="name")) is not None
            ],
        )


class ManualDiscoveryAdapter:
    adapter_id = "manual"

    def discover(self, request: ProviderDiscoveryRequest) -> ProviderDiscoveryResult:
        return ProviderDiscoveryResult(
            provider_id=request.provider_id,
            adapter_id=self.adapter_id,
            attempted_endpoints=(),
            discovered_at=_utcnow_iso(),
            models=(),
        )


ADAPTERS: dict[str, ProviderDiscoveryAdapter] = {
    "openai": OpenAICompatibleDiscoveryAdapter("openai"),
    "openai_compatible": OpenAICompatibleDiscoveryAdapter("openai_compatible"),
    "ollama": OllamaDiscoveryAdapter(),
    "llamacpp": OpenAICompatibleDiscoveryAdapter("llamacpp"),
    "lmstudio": OpenAICompatibleDiscoveryAdapter("lmstudio"),
    "vllm": OpenAICompatibleDiscoveryAdapter("vllm"),
    "sglang": OpenAICompatibleDiscoveryAdapter("sglang"),
    "anthropic": AnthropicDiscoveryAdapter(),
    "gemini": GeminiDiscoveryAdapter(),
    "manual": ManualDiscoveryAdapter(),
}


def get_provider_discovery_adapter(adapter_id: str) -> ProviderDiscoveryAdapter:
    key = str(adapter_id or "").strip().lower()
    try:
        return ADAPTERS[key]
    except KeyError:
        raise ValueError(f"unsupported provider discovery adapter: {key or 'empty'}") from None


__all__ = [
    "ADAPTERS",
    "MAX_DISCOVERED_MODELS",
    "MAX_DISCOVERY_RESPONSE_BYTES",
    "MAX_UPSTREAM_ID_LENGTH",
    "get_provider_discovery_adapter",
]
