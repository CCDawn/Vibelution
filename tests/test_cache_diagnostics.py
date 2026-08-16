"""Unit tests for prompt-cache diagnostics used by Agent, session, and runtime UI.

`core.orchestration.cache_diagnostics` had no focused tests. These pin token
normalization, repeated-metadata compaction, context segmentation, and the
provider-vs-computed cache calibration contract.
"""

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.orchestration.cache_diagnostics import (
    build_llm_usage_from_observation,
    build_runtime_cache_composition,
    build_runtime_context_composition,
    compact_repeated_metadata_text,
    estimate_segment_tokens,
    normalize_runtime_llm_usage,
)


def test_compact_repeated_metadata_text_collapses_exact_repeats_and_truncates():
    assert compact_repeated_metadata_text("abcabcabc") == "abc"
    assert compact_repeated_metadata_text("ababab") == "ababab"
    assert compact_repeated_metadata_text("") == ""
    assert compact_repeated_metadata_text(None) == ""
    assert compact_repeated_metadata_text("x" * 400, max_chars=12) == "xxxx"


def test_estimate_segment_tokens_never_goes_negative():
    assert estimate_segment_tokens(0) == 0
    assert estimate_segment_tokens(-9, item_count=-2) == 0
    assert estimate_segment_tokens(9, item_count=1) == 3 + 8


def test_normalize_runtime_llm_usage_accepts_snake_and_camel_and_clamps_cache():
    assert normalize_runtime_llm_usage("not-a-dict") is None

    usage = normalize_runtime_llm_usage(
        {
            "input_tokens": 100,
            "outputTokens": 20,
            "cached_input_tokens": 140,
            "cache_creation_input_tokens": 15,
            "provider": "openaiopenaiopenai",
            "model": "gpt-test",
        }
    )

    assert usage is not None
    assert usage["source"] == "provider_usage"
    assert usage["inputTokens"] == 100
    assert usage["outputTokens"] == 20
    assert usage["totalTokens"] == 120
    assert usage["cachedInputTokens"] == 100
    assert usage["cacheReadInputTokens"] == 100
    assert usage["cacheCreationInputTokens"] == 15
    assert usage["uncachedInputTokens"] == 0
    assert usage["cacheHitRate"] == 1.0
    assert usage["cacheUsageObserved"] is True
    assert usage["provider"] == "openai"
    assert usage["model"] == "gpt-test"


def test_normalize_runtime_llm_usage_marks_missing_cache_metrics():
    usage = normalize_runtime_llm_usage({"inputTokens": 80, "outputTokens": 10})

    assert usage is not None
    assert usage["source"] == "provider_usage"
    assert usage["cacheUsageObserved"] is False
    assert usage["cacheUsageMissingReason"] == "provider_cache_usage_missing"
    assert usage["uncachedInputTokens"] == 0
    assert usage["cacheHitRate"] == 0.0


def test_build_llm_usage_from_observation_zeros_unobserved_and_clamps_cached():
    missing = build_llm_usage_from_observation(
        SimpleNamespace(observed=False, input_tokens=99, output_tokens=3, total_tokens=102),
        response_metadata={"provider": "x", "model": "y"},
        recorded_at="2026-08-17T00:00:00",
    )
    assert missing["source"] == "missing"
    assert missing["inputTokens"] == 0
    assert missing["outputTokens"] == 0
    assert missing["totalTokens"] == 0
    assert missing["recordedAt"] == "2026-08-17T00:00:00"

    observed = build_llm_usage_from_observation(
        SimpleNamespace(
            observed=True,
            input_tokens=50,
            output_tokens=7,
            total_tokens=57,
            cached_input_tokens=80,
            cache_creation_input_tokens=4,
            uncached_input_tokens=0,
        )
    )
    assert observed["source"] == "provider_usage"
    assert observed["cachedInputTokens"] == 50
    assert observed["uncachedInputTokens"] == 0
    assert observed["cacheHitRate"] == 1.0


def test_build_runtime_context_composition_splits_cache_prefix_history_and_volatile():
    composition = build_runtime_context_composition(
        [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": "stable tools", "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": "dynamic suffix"},
                ],
            },
            HumanMessage(content="first question"),
            AIMessage(content="first answer"),
            SystemMessage(content="## Slash Skill Context\nCommand: /brt"),
            HumanMessage(content="second question"),
        ],
        turn_id="turn-1",
        prompt_cache_partition="part-a",
        context_limit=8000,
    )

    keys = [item["key"] for item in composition["segments"]]
    assert keys == [
        "system_cache_prefix",
        "system_dynamic_suffix",
        "history",
        "volatile_runtime_context",
        "current_user",
    ]
    by_key = {item["key"]: item for item in composition["segments"]}
    assert by_key["system_cache_prefix"]["cachePolicy"] == "prefix_candidate"
    assert by_key["system_dynamic_suffix"]["cachePolicy"] == "volatile"
    assert by_key["history"]["cachePolicy"] == "prefix_candidate"
    assert "first question" in by_key["history"]["contentPreview"]
    assert "first answer" in by_key["history"]["contentPreview"]
    assert by_key["volatile_runtime_context"]["cachePolicy"] == "volatile"
    assert by_key["current_user"]["cachePolicy"] == "never_cache"
    assert by_key["current_user"]["contentPreview"] == "second question"
    assert composition["turnId"] == "turn-1"
    assert composition["promptCachePartition"] == "part-a"
    assert composition["limitTokens"] == 8000
    assert composition["cache"]["cacheableSegmentCount"] == 2
    assert "current_turn_context" not in keys


def test_build_runtime_cache_composition_returns_missing_without_observed_cache():
    missing = build_runtime_cache_composition(
        turn_id="t1",
        llm_usage={"inputTokens": 40, "outputTokens": 5},
    )
    assert missing["source"] == "missing"
    assert missing["segments"][0]["status"] == "missing"
    assert missing["computedSegments"] == []


def test_build_runtime_cache_composition_calibrates_remainder_as_computed_hit():
    context = build_runtime_context_composition(
        [
            SystemMessage(content="stable system prompt for tools"),
            HumanMessage(content="hello"),
        ]
    )
    mapped = sum(item["tokens"] for item in context["segments"])
    cacheable = sum(
        item["tokens"]
        for item in context["segments"]
        if item["cachePolicy"] in {"prefix_candidate", "cacheable"}
    )
    uncached = mapped - cacheable
    composition = build_runtime_cache_composition(
        turn_id="t2",
        llm_usage={
            "source": "provider_usage",
            "inputTokens": mapped + 30,
            "cachedInputTokens": cacheable + 10,
            "cacheCreationInputTokens": 0,
            "outputTokens": 4,
        },
        context_composition=context,
    )

    assert composition["source"] == "provider_usage"
    remainder = next(
        item for item in composition["computedSegments"] if item["key"] == "provider_input_remainder"
    )
    assert remainder["tokens"] == 30
    assert remainder["status"] == "computed_hit"
    assert composition["computedCachedInputTokens"] == cacheable + 30
    assert composition["computedUncachedInputTokens"] == uncached
    assert composition["calibrationStatus"] == "provider_lower_than_computed"
    assert composition["computedOverestimatedInputTokens"] == 20
    assert composition["calibratedCachedInputTokens"] == cacheable + 10
