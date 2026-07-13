from __future__ import annotations

import json

import httpx
import pytest

from config.llm_identity import provider_discovery_fingerprint
from config.model_catalog import load_model_catalog_state
from config.models import ProviderDiscoverySettings
from core.llm.provider_discovery.adapters import (
    MAX_DISCOVERED_MODELS,
    MAX_DISCOVERY_RESPONSE_BYTES,
    resolve_discovery_endpoints,
)
from core.llm.provider_discovery.service import discover_provider_models
from core.llm.provider_discovery.types import ProviderDiscoveryRequest


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "config.llm_security.socket.getaddrinfo",
        lambda host, port, type=None: [(None, None, None, None, ("8.8.8.8", port))],
    )


def _config(adapter: str, *, base_url: str = "https://models.example/v1") -> dict:
    return {
        "llm": {
            "schema_version": 2,
            "providers": {
                "lab": {
                    "label": "Lab",
                    "service_class": "self_hosted",
                    "vendor": "custom",
                    "driver": "openai",
                    "base_url": base_url,
                    "auth_kind": "api_key",
                    "credential_ref": "env:VIBELUTION_LLM_PROVIDER_LAB_API_KEY",
                    "requires_credential": True,
                    "protocols": {"default": "chat_completions", "allowed": ["chat_completions"]},
                    "discovery": {"mode": "auto", "adapter": adapter, "cache_ttl_seconds": 60},
                    "models": {"pinned-gone": {"upstream_id": "pinned-gone", "label": "Pinned Gone"}},
                }
            },
            "profiles": {},
        }
    }


def test_request_repr_never_contains_credential() -> None:
    request = ProviderDiscoveryRequest(provider_id="lab", provider={}, credential="super-secret")
    assert "super-secret" not in repr(request)


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://relay.example", ("https://relay.example/v1/models",)),
        ("https://relay.example/v1", ("https://relay.example/v1/models",)),
        (
            "https://relay.example/v2",
            ("https://relay.example/v2/models", "https://relay.example/v1/models"),
        ),
        ("https://relay.example/v1/responses", ("https://relay.example/v1/models",)),
        (
            "https://relay.example/v1/chat/completions",
            ("https://relay.example/v1/models",),
        ),
    ],
)
def test_openai_model_endpoint_candidates_are_ordered_and_bounded(
    base_url: str,
    expected: tuple[str, ...],
) -> None:
    provider = {"base_url": base_url, "discovery": {"adapter": "openai_compatible"}}
    assert resolve_discovery_endpoints(provider, "openai_compatible") == expected


def test_explicit_models_url_override_is_the_only_candidate() -> None:
    provider = {
        "base_url": "https://relay.example/v1/responses",
        "discovery": {
            "adapter": "openai_compatible",
            "models_url_override": "https://catalog.example/custom/models",
        },
    }
    assert resolve_discovery_endpoints(provider, "openai_compatible") == (
        "https://catalog.example/custom/models",
    )


@pytest.mark.parametrize(
    ("adapter", "base_url", "expected"),
    [
        ("ollama", "http://127.0.0.1:11434/v1", ("http://127.0.0.1:11434/api/tags",)),
        ("anthropic", "https://models.example/v1", ("https://models.example/v1/models",)),
        ("gemini", "https://models.example/v1beta", ("https://models.example/v1beta/models",)),
        ("manual", "https://models.example/v1", ()),
    ],
)
def test_native_model_endpoint_defaults_are_resolved_by_adapter(
    adapter: str,
    base_url: str,
    expected: tuple[str, ...],
) -> None:
    provider = {"base_url": base_url, "discovery": {"adapter": adapter}}
    assert resolve_discovery_endpoints(provider, adapter) == expected


def test_provider_discovery_settings_exposes_typed_models_url_override() -> None:
    settings = ProviderDiscoverySettings(
        adapter="openai_compatible",
        models_url_override="https://catalog.example/custom/models",
    )
    assert settings.models_url_override == "https://catalog.example/custom/models"


def test_openai_compatible_adapter_normalizes_models_and_reconciles_pins(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret"
        assert request.url.path == "/v1/models"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "gpt-a",
                        "context_window": 128000,
                        "capabilities": {"vision": True},
                    }
                ]
            },
        )

    path = tmp_path / "model-catalog-state.json"
    result = discover_provider_models(
        _config("openai_compatible"),
        "lab",
        catalog_path=path,
        transport=httpx.MockTransport(handler),
    )
    assert result.models[0].upstream_id == "gpt-a"
    assert result.models[0].limits == {"context_window": 128000}
    state = load_model_catalog_state(path)
    provider = _config("openai_compatible")["llm"]["providers"]["lab"]
    assert state["providers"]["lab"]["providerFingerprint"] == provider_discovery_fingerprint(provider)
    assert state["providers"]["lab"]["models"]["pinned-gone"]["availability"] == "missing_remote"
    assert state["providers"]["lab"]["models"]["gpt-a"]["capabilities"]["vision"]["source"] == (
        "provider_endpoint"
    )


@pytest.mark.parametrize("route_mismatch_status", [404, 405])
def test_openai_compatible_tries_bounded_candidates_in_order(
    monkeypatch,
    tmp_path,
    route_mismatch_status: int,
) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/v2/models":
            return httpx.Response(route_mismatch_status, json={"error": "route mismatch"})
        return httpx.Response(200, json={"data": [{"id": "fallback-model"}]})

    result = discover_provider_models(
        _config("openai_compatible", base_url="https://models.example/v2"),
        "lab",
        catalog_path=tmp_path / "state.json",
        transport=httpx.MockTransport(handler),
    )
    assert seen == ["/v2/models", "/v1/models"]
    assert result.attempted_endpoints == (
        "https://models.example/v2/models",
        "https://models.example/v1/models",
    )


def test_explicit_models_url_override_is_validated_before_http(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")
    config = _config("openai_compatible")
    config["llm"]["providers"]["lab"]["discovery"]["models_url_override"] = (
        "https://169.254.169.254/latest/models"
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": [{"id": "must-not-run"}]})

    with pytest.raises(ValueError, match="non-public network address"):
        discover_provider_models(
            config,
            "lab",
            catalog_path=tmp_path / "state.json",
            transport=httpx.MockTransport(handler),
        )

    assert calls == 0


def test_ollama_adapter_uses_native_tags_surface(tmp_path) -> None:
    config = _config("ollama", base_url="http://127.0.0.1:11434")
    config["llm"]["providers"]["lab"].update(
        {
            "service_class": "local_runtime",
            "auth_kind": "none",
            "credential_ref": "none",
            "requires_credential": False,
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b", "details": {"family": "qwen3"}}]})

    result = discover_provider_models(
        config,
        "lab",
        catalog_path=tmp_path / "model-catalog-state.json",
        transport=httpx.MockTransport(handler),
    )
    assert [model.upstream_id for model in result.models] == ["qwen3:8b"]


@pytest.mark.parametrize(
    ("adapter", "path", "header", "expected_id"),
    [
        ("anthropic", "/v1/models", "x-api-key", "claude-native"),
        ("gemini", "/v1beta/models", "", "models/gemini-native"),
    ],
)
def test_native_adapters_use_native_auth_without_secret_in_endpoint_summary(
    monkeypatch, tmp_path, adapter: str, path: str, header: str, expected_id: str
) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "native-secret")
    config = _config(adapter, base_url="https://models.example")
    config["llm"]["providers"]["lab"]["driver"] = adapter

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == path
        if header:
            assert request.headers[header] == "native-secret"
            assert request.headers["anthropic-version"] == "2023-06-01"
            payload = {"data": [{"id": "claude-native"}]}
        else:
            assert request.url.params["key"] == "native-secret"
            payload = {"models": [{"name": "models/gemini-native"}]}
        return httpx.Response(200, json=payload)

    result = discover_provider_models(
        config,
        "lab",
        catalog_path=tmp_path / "state.json",
        transport=httpx.MockTransport(handler),
    )
    assert result.models[0].upstream_id == expected_id
    assert all("native-secret" not in endpoint for endpoint in result.attempted_endpoints)
    assert "native-secret" not in repr(result)


@pytest.mark.parametrize(
    ("adapter", "base_url", "override", "payload", "expected_id"),
    [
        (
            "anthropic",
            "https://models.example",
            "https://catalog.example/custom/anthropic-models",
            {"data": [{"id": "claude-override"}]},
            "claude-override",
        ),
        (
            "gemini",
            "https://models.example",
            "https://catalog.example/custom/gemini-models",
            {"models": [{"name": "models/gemini-override"}]},
            "models/gemini-override",
        ),
        (
            "ollama",
            "http://127.0.0.1:11434",
            "http://127.0.0.1:11434/custom/tags",
            {"models": [{"name": "ollama-override"}]},
            "ollama-override",
        ),
    ],
)
def test_http_native_adapters_use_override_as_the_only_real_endpoint(
    monkeypatch,
    tmp_path,
    adapter: str,
    base_url: str,
    override: str,
    payload: dict,
    expected_id: str,
) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "native-secret")
    config = _config(adapter, base_url=base_url)
    provider = config["llm"]["providers"]["lab"]
    provider["driver"] = adapter if adapter in {"anthropic", "gemini"} else "openai"
    provider["discovery"]["models_url_override"] = override
    if adapter == "ollama":
        provider.update(
            {
                "service_class": "local_runtime",
                "auth_kind": "none",
                "credential_ref": "none",
                "requires_credential": False,
            }
        )
    calls: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.scheme, request.url.host, request.url.path))
        return httpx.Response(200, json=payload)

    result = discover_provider_models(
        config,
        "lab",
        catalog_path=tmp_path / "state.json",
        transport=httpx.MockTransport(handler),
    )

    expected_url = httpx.URL(override)
    assert calls == [(expected_url.scheme, expected_url.host, expected_url.path)]
    assert result.attempted_endpoints == (override,)
    assert [model.upstream_id for model in result.models] == [expected_id]


def test_empty_refresh_marks_stale_and_preserves_previous_catalog(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")
    path = tmp_path / "model-catalog-state.json"
    success = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"id": "gpt-a"}]}))
    discover_provider_models(_config("openai_compatible"), "lab", catalog_path=path, transport=success)
    empty = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []}))
    with pytest.raises(ValueError, match="no usable models"):
        discover_provider_models(_config("openai_compatible"), "lab", catalog_path=path, transport=empty)
    state = load_model_catalog_state(path)
    assert state["providers"]["lab"]["status"] == "stale"
    assert "gpt-a" in state["providers"]["lab"]["models"]
    assert "secret" not in json.dumps(state)


def test_successful_empty_candidate_is_reported_as_empty_discovery(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/models":
            return httpx.Response(404)
        return httpx.Response(200, json={"data": []})

    with pytest.raises(ValueError, match="no usable models"):
        discover_provider_models(
            _config("openai_compatible", base_url="https://models.example/v2"),
            "lab",
            catalog_path=tmp_path / "state.json",
            transport=httpx.MockTransport(handler),
        )


def test_auth_failure_is_classified_without_losing_previous_models(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")
    path = tmp_path / "model-catalog-state.json"
    success = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"id": "gpt-a"}]}))
    discover_provider_models(_config("openai_compatible"), "lab", catalog_path=path, transport=success)
    unauthorized = httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "secret unauthorized"}))
    with pytest.raises(httpx.HTTPStatusError) as raised:
        discover_provider_models(_config("openai_compatible"), "lab", catalog_path=path, transport=unauthorized)
    assert "secret unauthorized" not in str(raised.value)
    assert "secret" not in repr(raised.value.request)
    state = load_model_catalog_state(path)
    assert state["providers"]["lab"]["status"] == "auth_failed"
    assert "gpt-a" in state["providers"]["lab"]["models"]


def test_gemini_http_error_redacts_query_credential(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "query-secret")
    config = _config("gemini", base_url="https://models.example")
    config["llm"]["providers"]["lab"]["driver"] = "gemini"
    transport = httpx.MockTransport(lambda request: httpx.Response(403, json={"error": "query-secret"}))
    with pytest.raises(httpx.HTTPStatusError) as raised:
        discover_provider_models(config, "lab", catalog_path=tmp_path / "state.json", transport=transport)
    assert "query-secret" not in str(raised.value)
    assert "query-secret" not in repr(raised.value.request)


def test_gemini_transport_error_redacts_query_credential(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "query-secret")
    config = _config("gemini", base_url="https://models.example")
    config["llm"]["providers"]["lab"]["driver"] = "gemini"

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("query-secret connection failed", request=request)

    path = tmp_path / "state.json"
    with pytest.raises(httpx.RequestError) as raised:
        discover_provider_models(
            config,
            "lab",
            catalog_path=path,
            transport=httpx.MockTransport(fail),
        )
    assert "query-secret" not in str(raised.value)
    assert "query-secret" not in repr(raised.value.request)
    assert load_model_catalog_state(path)["providers"]["lab"]["lastErrorType"] == "network"


@pytest.mark.parametrize(
    "echoed_model",
    [
        {"id": "credential-echo", "label": "safe"},
        {"id": "safe-id", "display_name": "credential-echo"},
        {"id": "safe-id", "capabilities": {"nested": ["safe", {"value": "credential-echo"}]}},
        {"id": "safe-id", "context_window": {"raw": "credential-echo"}},
    ],
)
def test_success_response_rejects_resolved_credential_taint_recursively(
    monkeypatch, tmp_path, echoed_model: dict
) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "credential-echo")
    path = tmp_path / "state.json"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [echoed_model]}))

    with pytest.raises(ValueError, match="provider discovery response contains credential material") as raised:
        discover_provider_models(_config("openai_compatible"), "lab", catalog_path=path, transport=transport)

    assert "credential-echo" not in str(raised.value)
    state = load_model_catalog_state(path)
    assert "credential-echo" not in json.dumps(state)
    assert state["providers"]["lab"]["models"] == {}


def test_success_response_rejects_one_time_override_taint(tmp_path) -> None:
    path = tmp_path / "state.json"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": [{"id": "safe", "label": "override-echo"}]})
    )

    with pytest.raises(ValueError, match="provider discovery response contains credential material") as raised:
        discover_provider_models(
            _config("openai_compatible"),
            "lab",
            credential_override="override-echo",
            catalog_path=path,
            transport=transport,
        )

    assert "override-echo" not in str(raised.value)
    assert "override-echo" not in json.dumps(load_model_catalog_state(path))


@pytest.mark.parametrize(
    ("statuses", "expected_calls"),
    [
        ((401, 404), 1),
        ((404, 403), 2),
    ],
)
def test_multi_candidate_discovery_preserves_safe_auth_failure_priority(
    monkeypatch, tmp_path, statuses: tuple[int, int], expected_calls: int
) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "auth-secret")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(statuses[len(calls) - 1], json={"error": "auth-secret echoed"})

    path = tmp_path / "state.json"
    with pytest.raises(httpx.HTTPStatusError) as raised:
        discover_provider_models(
            _config("openai_compatible", base_url="https://models.example/v2"),
            "lab",
            catalog_path=path,
            transport=httpx.MockTransport(handler),
        )

    assert len(calls) == expected_calls
    assert raised.value.response.status_code in {401, 403}
    assert "auth-secret" not in str(raised.value)
    state = load_model_catalog_state(path)
    assert state["providers"]["lab"]["status"] == "auth_failed"
    assert state["providers"]["lab"]["lastErrorType"] == "auth_failed"
    assert "auth-secret" not in json.dumps(state)


@pytest.mark.parametrize(
    ("failure_kind", "expected_exception", "expected_error_type"),
    [
        ("rate_limit", httpx.HTTPStatusError, "rate_limited"),
        ("server_error", httpx.HTTPStatusError, "service_unavailable"),
        ("upstream_error", httpx.HTTPStatusError, "upstream_unavailable"),
        ("timeout", httpx.TimeoutException, "timeout"),
        ("network", httpx.RequestError, "network"),
    ],
)
def test_non_route_failures_do_not_advance_discovery_candidates(
    monkeypatch,
    tmp_path,
    failure_kind: str,
    expected_exception: type[Exception],
    expected_error_type: str,
) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "failure-secret")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if failure_kind == "rate_limit":
            return httpx.Response(429, json={"error": "failure-secret"})
        if failure_kind == "server_error":
            return httpx.Response(503, json={"error": "failure-secret"})
        if failure_kind == "upstream_error":
            return httpx.Response(502, json={"error": "failure-secret"})
        if failure_kind == "timeout":
            raise httpx.ReadTimeout("failure-secret", request=request)
        raise httpx.ConnectError("failure-secret", request=request)

    path = tmp_path / "state.json"
    with pytest.raises(expected_exception) as raised:
        discover_provider_models(
            _config("openai_compatible", base_url="https://models.example/v2"),
            "lab",
            catalog_path=path,
            transport=httpx.MockTransport(handler),
        )

    assert calls == ["/v2/models"]
    assert "failure-secret" not in str(raised.value)
    state = load_model_catalog_state(path)
    assert state["providers"]["lab"]["lastErrorType"] == expected_error_type
    assert "failure-secret" not in json.dumps(state)


def test_exhausted_route_mismatches_are_classified_as_protocol_mismatch(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(404 if len(calls) == 1 else 405, json={"error": "route mismatch"})

    path = tmp_path / "state.json"
    with pytest.raises(httpx.HTTPStatusError) as raised:
        discover_provider_models(
            _config("openai_compatible", base_url="https://models.example/v2"),
            "lab",
            catalog_path=path,
            transport=httpx.MockTransport(handler),
        )

    assert calls == ["/v2/models", "/v1/models"]
    assert raised.value.response.status_code == 405
    provider = load_model_catalog_state(path)["providers"]["lab"]
    assert provider["status"] == "protocol_mismatch"
    assert provider["lastErrorType"] == "protocol_mismatch"


def test_malformed_candidate_response_does_not_fall_through(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, content=b"{")

    with pytest.raises(json.JSONDecodeError):
        discover_provider_models(
            _config("openai_compatible", base_url="https://models.example/v2"),
            "lab",
            catalog_path=tmp_path / "state.json",
            transport=httpx.MockTransport(handler),
        )

    assert calls == ["/v2/models"]


def test_discovery_include_and_exclude_filters_are_provider_scoped(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")
    config = _config("openai_compatible")
    config["llm"]["providers"]["lab"]["discovery"].update({"include": ["gpt-*"], "exclude": ["*-preview"]})
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"data": [{"id": "gpt-a"}, {"id": "gpt-a-preview"}, {"id": "claude-a"}]},
        )
    )
    result = discover_provider_models(config, "lab", catalog_path=tmp_path / "state.json", transport=transport)
    assert [model.upstream_id for model in result.models] == ["gpt-a"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"data": [{"id": "x" * 513}]}, "model id exceeds 512"),
        ({"data": [{"id": str(index)} for index in range(MAX_DISCOVERED_MODELS + 1)]}, "more than 5000 models"),
    ],
)
def test_discovery_rejects_bounded_model_limits(monkeypatch, tmp_path, payload: dict, message: str) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=json.dumps(payload).encode("utf-8")))
    with pytest.raises(ValueError, match=message):
        discover_provider_models(_config("openai_compatible"), "lab", catalog_path=tmp_path / "state.json", transport=transport)


def test_discovery_rejects_oversized_response_before_json_decode(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"{" + b"x" * MAX_DISCOVERY_RESPONSE_BYTES)
    )
    with pytest.raises(ValueError, match="exceeds 2 MiB"):
        discover_provider_models(_config("openai_compatible"), "lab", catalog_path=tmp_path / "state.json", transport=transport)


def test_discovery_does_not_follow_redirects(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    with pytest.raises(httpx.HTTPStatusError):
        discover_provider_models(
            _config("openai_compatible"),
            "lab",
            catalog_path=tmp_path / "state.json",
            transport=httpx.MockTransport(handler),
        )
    assert calls == 1


def test_manual_adapter_performs_no_http_and_does_not_write_catalog(monkeypatch, tmp_path) -> None:
    config = _config("manual")
    config["llm"]["providers"]["lab"].update(
        {"auth_kind": "none", "credential_ref": "none", "requires_credential": False}
    )
    path = tmp_path / "state.json"
    result = discover_provider_models(
        config,
        "lab",
        catalog_path=path,
        transport=httpx.MockTransport(lambda request: pytest.fail("manual adapter performed HTTP")),
    )
    assert result.adapter_id == "manual"
    assert result.models == ()
    assert not path.exists()


@pytest.mark.parametrize(
    "override",
    ["https://169.254.169.254/latest/models", "not-a-valid-models-url"],
)
def test_manual_adapter_ignores_override_without_http_or_override_security_probe(
    tmp_path,
    override: str,
) -> None:
    config = _config("manual")
    provider = config["llm"]["providers"]["lab"]
    provider.update({"auth_kind": "none", "credential_ref": "none", "requires_credential": False})
    provider["discovery"]["models_url_override"] = override
    path = tmp_path / "state.json"

    result = discover_provider_models(
        config,
        "lab",
        catalog_path=path,
        transport=httpx.MockTransport(lambda request: pytest.fail("manual adapter performed HTTP")),
    )

    assert result.attempted_endpoints == ()
    assert not path.exists()


def test_unsupported_adapter_error_precedes_unused_override_validation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")
    config = _config("unsupported")
    config["llm"]["providers"]["lab"]["discovery"]["models_url_override"] = (
        "https://169.254.169.254/latest/models"
    )

    with pytest.raises(ValueError, match="unsupported provider discovery adapter: unsupported"):
        discover_provider_models(config, "lab", catalog_path=tmp_path / "state.json")


def test_discovery_rejects_non_v2_provider_identity_without_guessing(tmp_path) -> None:
    with pytest.raises(ValueError, match="unknown schema v2 provider"):
        discover_provider_models({"llm": {"schema_version": 1}}, "guessed", catalog_path=tmp_path / "state.json")


def test_manual_discovery_still_requires_canonical_provider_id(tmp_path) -> None:
    config = _config("manual")
    provider = config["llm"]["providers"].pop("lab")
    config["llm"]["providers"]["Lab Display"] = provider
    provider.update({"auth_kind": "none", "credential_ref": "none", "requires_credential": False})
    with pytest.raises(ValueError, match="provider_id must match"):
        discover_provider_models(config, "Lab Display", catalog_path=tmp_path / "state.json")
