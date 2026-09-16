"""Usage transparency projections: latency/tokens-per-second and turn usageStats.

Pins the context/token transparency contract:
- provider latency and derived tokens/s survive the llmUsage normalizers;
- the assistant turn DTO exposes `usageStats` only from provider-observed usage
  and degrades to absent (never invented) when a provider omits usage.
"""

from __future__ import annotations

from core.orchestration.cache_diagnostics import (
    build_llm_usage_from_observation,
    normalize_runtime_llm_usage,
)
from core.web.services import session_service


def _provider_observation(latency_ms: int | None = None) -> dict:
    observation = {
        "observed": True,
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "cached_input_tokens": 80,
        "cache_creation_input_tokens": 0,
    }
    if latency_ms is not None:
        observation["latency_ms"] = latency_ms
    return observation


def test_build_llm_usage_from_observation_derives_tokens_per_second():
    usage = build_llm_usage_from_observation(
        _provider_observation(latency_ms=10_000),
    )

    assert usage["source"] == "provider_usage"
    assert usage["latencyMs"] == 10_000
    assert usage["tokensPerSecond"] == 5.0


def test_build_llm_usage_from_observation_falls_back_to_response_metadata_latency():
    usage = build_llm_usage_from_observation(
        _provider_observation(),
        response_metadata={"usage_observation": {"latency_ms": 2_500}},
    )

    assert usage["latencyMs"] == 2_500
    assert usage["tokensPerSecond"] == 20.0


def test_build_llm_usage_from_observation_degrades_without_latency_or_usage():
    observed_without_latency = build_llm_usage_from_observation(
        _provider_observation(),
    )
    assert observed_without_latency["latencyMs"] == 0
    assert observed_without_latency["tokensPerSecond"] is None

    missing = build_llm_usage_from_observation({"observed": False})
    assert missing["source"] == "missing"
    assert missing["latencyMs"] == 0
    assert missing["tokensPerSecond"] is None


def test_normalize_runtime_llm_usage_passes_through_latency_and_speed():
    usage = normalize_runtime_llm_usage(
        {
            "inputTokens": 100,
            "outputTokens": 30,
            "totalTokens": 130,
            "latencyMs": 3_000,
        }
    )

    assert usage is not None
    assert usage["latencyMs"] == 3_000
    # Derived from output tokens + latency when tokensPerSecond itself is absent.
    assert usage["tokensPerSecond"] == 10.0


def test_normalize_turn_llm_usage_passthrough_keeps_speed_and_latency():
    normalized = session_service._normalize_turn_llm_usage(
        {
            "source": "provider_usage",
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "latencyMs": 4_000,
            "tokensPerSecond": 12.5,
        }
    )

    assert normalized is not None
    assert normalized["latencyMs"] == 4_000
    assert normalized["tokensPerSecond"] == 12.5


def test_assistant_usage_stats_payload_provider_vs_missing():
    provider_payload = session_service._assistant_usage_stats_payload(
        {
            "source": "provider_usage",
            "inputTokens": 120,
            "outputTokens": 60,
            "totalTokens": 180,
            "cachedInputTokens": 40,
            "latencyMs": 2_000,
            "tokensPerSecond": 30.0,
            "recordedAt": "2026-09-16T00:00:00Z",
        }
    )
    assert provider_payload == {
        "inputTokens": 120,
        "completionTokens": 60,
        "totalTokens": 180,
        "cachedInputTokens": 40,
        "elapsedMs": 2_000,
        "tokensPerSecond": 30.0,
        "recordedAt": "2026-09-16T00:00:00Z",
    }

    # Provider did not report usage: degrade to absent, never invent numbers.
    assert session_service._assistant_usage_stats_payload(None) is None
    assert (
        session_service._assistant_usage_stats_payload({"source": "missing"})
        is None
    )
    estimated = session_service._assistant_usage_stats_payload(
        {"source": "estimated", "inputTokens": 10, "outputTokens": 5}
    )
    assert estimated is None
