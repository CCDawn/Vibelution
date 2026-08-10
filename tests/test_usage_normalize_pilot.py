"""Pilot normalize pilot: Python reference + optional Rust parity."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from core.llm.usage import usage_diagnostic_summary_from_payload, usage_stats_from_payload
from core.llm.usage_normalize import normalize_usage_dict, normalize_usage_payload, resolve_usage_normalize_binary

ROOT = Path(__file__).resolve().parents[1]


def test_openai_shape_hit_rate():
    raw = {
        "prompt_tokens": 10000,
        "completion_tokens": 100,
        "total_tokens": 10100,
        "prompt_tokens_details": {"cached_tokens": 9000},
    }
    n = normalize_usage_dict(raw)
    assert n["inputTokens"] == 10000
    assert n["cachedInputTokens"] == 9000
    assert n["cacheHitRate"] == pytest.approx(0.9)
    assert n["uncachedInputTokens"] == 1000


def test_anthropic_native_tail_is_not_capped_to_100_percent():
    raw = {
        "input_tokens": 200,
        "output_tokens": 80,
        "cache_creation_input_tokens": 500,
        "cache_read_input_tokens": 4000,
    }
    n = normalize_usage_dict(raw)
    assert n["inputTokens"] == 4700
    assert n["cachedInputTokens"] == 4000
    assert n["cacheCreationInputTokens"] == 500
    assert n["uncachedInputTokens"] == 700
    assert n["cacheHitRate"] == pytest.approx(4000 / 4700, rel=1e-4)

    stats = usage_stats_from_payload(raw)
    assert stats.input_tokens == 4700
    assert stats.cached_input_tokens == 4000
    diag = usage_diagnostic_summary_from_payload(raw)
    assert diag["cacheHitRate"] == pytest.approx(4000 / 4700, rel=1e-4)


def test_existing_openai_style_input_total_contract():
    """When input_tokens is already full total and read < input, keep 80/200=0.4."""
    raw = {
        "input_tokens": 200,
        "output_tokens": 10,
        "cache_read_input_tokens": 80,
        "cache_creation_input_tokens": 40,
    }
    n = normalize_usage_dict(raw)
    assert n["inputTokens"] == 200
    assert n["cachedInputTokens"] == 80
    assert n["cacheHitRate"] == pytest.approx(0.4)


def test_missing_provider_cache_counters_are_unknown_instead_of_zero_hit():
    raw = {
        "prompt_tokens": 200,
        "completion_tokens": 10,
        "total_tokens": 210,
    }

    normalized = normalize_usage_dict(raw)
    diagnostic = usage_diagnostic_summary_from_payload(raw)

    assert normalized["cacheUsageObserved"] is False
    assert normalized["cacheUsageMissingReason"] == "provider_cache_usage_missing"
    assert normalized["uncachedInputTokens"] == 0
    assert normalized["cacheHitRate"] == 0.0
    assert diagnostic["cacheUsageObserved"] is False
    assert diagnostic["cacheUsageMissingReason"] == "provider_cache_usage_missing"


def test_explicit_deepseek_zero_hit_remains_an_observed_zero():
    raw = {
        "prompt_tokens": 200,
        "completion_tokens": 10,
        "total_tokens": 210,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 200,
    }

    normalized = normalize_usage_dict(raw)

    assert normalized["cacheUsageObserved"] is True
    assert normalized["cacheUsageMissingReason"] == ""
    assert normalized["cachedInputTokens"] == 0
    assert normalized["uncachedInputTokens"] == 200
    assert normalized["cacheHitRate"] == 0.0


def test_relay_prompt_tokens_dominates_tail_input():
    raw = {
        "prompt_tokens": 4700,
        "completion_tokens": 80,
        "input_tokens": 200,
        "cache_creation_input_tokens": 500,
        "cache_read_input_tokens": 4000,
    }
    n = normalize_usage_dict(raw)
    assert n["inputTokens"] == 4700
    assert n["cachedInputTokens"] == 4000
    assert n["cacheHitRate"] == pytest.approx(4000 / 4700, rel=1e-4)


def test_rust_usage_normalize_spawn_uses_create_no_window(monkeypatch):
    """CUI rust sidecar must not flash a console on every LLM usage event."""

    import subprocess as sp

    from core.llm import usage_normalize as un

    captured: dict = {}

    def fake_run(*_args, **kwargs):
        captured.update(kwargs)

        class _Result:
            returncode = 0
            stdout = (
                '{"inputTokens":1,"outputTokens":2,"totalTokens":3,'
                '"cachedInputTokens":0,"cacheCreationInputTokens":0}'
            )
            stderr = ""

        return _Result()

    monkeypatch.setattr(un, "resolve_usage_normalize_binary", lambda: Path("fake-usage-normalize.exe"))
    monkeypatch.setattr(sp, "run", fake_run)
    result = un.normalize_usage_payload_via_rust({"prompt_tokens": 1})
    assert result is not None
    flags = int(captured.get("creationflags") or 0)
    assert flags & int(getattr(sp, "CREATE_NO_WINDOW", 0x08000000))
    assert captured.get("startupinfo") is not None


@pytest.mark.skipif(resolve_usage_normalize_binary() is None, reason="Rust binary not built")
def test_rust_binary_parity_with_python():
    cases = [
        {
            "prompt_tokens": 10000,
            "completion_tokens": 100,
            "prompt_tokens_details": {"cached_tokens": 9000},
        },
        {
            "input_tokens": 200,
            "output_tokens": 80,
            "cache_creation_input_tokens": 500,
            "cache_read_input_tokens": 4000,
        },
        {
            "input_tokens": 200,
            "output_tokens": 10,
            "cache_read_input_tokens": 80,
            "cache_creation_input_tokens": 40,
        },
    ]
    binary = resolve_usage_normalize_binary()
    assert binary is not None
    for raw in cases:
        py = normalize_usage_dict(raw, engine="python")
        from scripts.windowless_subprocess import no_window_subprocess_kwargs

        completed = subprocess.run(
            [str(binary)],
            input=json.dumps({"usage": raw}),
            text=True,
            capture_output=True,
            check=True,
            **no_window_subprocess_kwargs(),
        )
        rust = json.loads(completed.stdout)
        assert rust["inputTokens"] == py["inputTokens"]
        assert rust["cachedInputTokens"] == py["cachedInputTokens"]
        assert rust["cacheCreationInputTokens"] == py["cacheCreationInputTokens"]
        assert rust["uncachedInputTokens"] == py["uncachedInputTokens"]
        assert rust["cacheHitRate"] == pytest.approx(py["cacheHitRate"], rel=1e-4)


def test_prefer_python_engine_env(monkeypatch):
    monkeypatch.setenv("VIBELUTION_USAGE_NORMALIZE_ENGINE", "python")
    raw = {"input_tokens": 200, "cache_read_input_tokens": 80, "cache_creation_input_tokens": 40}
    n = normalize_usage_payload(raw)
    assert n["engine"] == "python"
