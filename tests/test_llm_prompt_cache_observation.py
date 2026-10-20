# -*- coding: utf-8 -*-
"""Per-turn prompt cache hit observation closed-loop tests.

Covers the ``core.llm.prompt_cache_observation`` module and its wiring at
``core.llm.client._record_usage_ledger_event``: observed-event fields, the
human summary line landing in the conversation debug jsonl sink, warmup /
probe traffic skipping, and the adjacent-call hit-ratio-drop warning.
"""

from __future__ import annotations

import pytest

from core.llm.prompt_cache_observation import (
    PROMPT_CACHE_DROP_PREVIOUS_RATIO_MIN,
    PROMPT_CACHE_HIT_DROP_EVENT_CODE,
    PROMPT_CACHE_OBSERVED_EVENT_CODE,
    _log_human_line,
    observe_prompt_cache_usage,
    reset_prompt_cache_baselines_for_tests,
)
from core.llm.types import UsageStats


@pytest.fixture(autouse=True)
def _clean_baselines():
    reset_prompt_cache_baselines_for_tests()
    yield
    reset_prompt_cache_baselines_for_tests()


@pytest.fixture(autouse=True)
def emitters(monkeypatch):
    """Capture scene events and conversation jsonl lines instead of writing."""

    scene_events: list[dict] = []
    debug_lines: list[tuple[str, str]] = []  # (level, message)

    monkeypatch.setattr(
        "core.llm.prompt_cache_observation._record_scene_event",
        lambda phase, code, **kwargs: scene_events.append(
            {"phase": phase, "code": code, **kwargs}
        ),
    )
    monkeypatch.setattr(
        "core.llm.prompt_cache_observation._log_human_line",
        lambda message, *, level="info": debug_lines.append((level, message)),
    )
    return {"scene": scene_events, "debug": debug_lines}


def _cached_usage(*, input_tokens=1000, cached=800, output=50):
    return UsageStats(
        input_tokens=input_tokens,
        output_tokens=output,
        total_tokens=input_tokens + output,
        cached_input_tokens=cached,
        provider_raw_usage={
            "prompt_tokens": input_tokens,
            "prompt_tokens_details": {"cached_tokens": cached},
        },
    )


def _uncached_usage(*, input_tokens=1000, output=50):
    return UsageStats(
        input_tokens=input_tokens,
        output_tokens=output,
        total_tokens=input_tokens + output,
        provider_raw_usage={
            "prompt_tokens": input_tokens,
            "prompt_tokens_details": {"cached_tokens": 0},
        },
    )


def test_observed_event_fields_and_human_summary_line(emitters):
    observe_prompt_cache_usage(
        usage=_cached_usage(input_tokens=1000, cached=700),
        metadata={"sessionId": "s1", "turnId": "t1", "invocationId": "inv-1"},
        provider="aliyun",
        model="qwen-plus",
        profile_id="primary",
    )

    observed = [e for e in emitters["scene"] if e["code"] == PROMPT_CACHE_OBSERVED_EVENT_CODE]
    assert len(observed) == 1
    fields = observed[0]["fields"]
    assert observed[0]["phase"] == "cache"
    assert observed[0]["level"] == "info"
    assert fields["sessionId"] == "s1"
    assert fields["turnId"] == "t1"
    assert fields["profileId"] == "primary"
    assert fields["model"] == "qwen-plus"
    assert fields["provider"] == "aliyun"
    assert fields["cacheHitTokens"] == 700
    assert fields["cacheMissTokens"] == 300
    assert fields["hitRatio"] == 0.7
    assert fields["inputTokens"] == 1000
    assert fields["cacheUsageObserved"] is True

    # 人读摘要行对齐 LLM TTFT breakdown 的落盘链路（level, tag=LLM message）。
    assert len(emitters["debug"]) == 1
    level, message = emitters["debug"][0]
    assert level == "info"
    assert message.startswith("LLM prompt cache:")
    assert "session=s1" in message and "turn=t1" in message
    assert "hit=700" in message and "miss=300" in message and "ratio=0.7" in message


def test_usage_ledger_finalize_emits_one_observation_per_call(monkeypatch, emitters):
    """The hook sits at the usage-ledger finalize point (non-warmup traffic)."""

    from core.llm.client import _record_usage_ledger_event

    recorded: list[object] = []
    monkeypatch.setattr("core.llm.client.record_usage_event", lambda event: recorded.append(event))

    _record_usage_ledger_event(
        usage=_cached_usage(),
        metadata={"sessionId": "s1", "turnId": "t1"},
        provider="relay",
        model="m",
        profile_id="primary",
        transport="chat_completions",
    )

    assert len(recorded) == 1
    observed = [e for e in emitters["scene"] if e["code"] == PROMPT_CACHE_OBSERVED_EVENT_CODE]
    assert len(observed) == 1
    assert observed[0]["fields"]["sessionId"] == "s1"


def test_warmup_and_probe_traffic_never_emit_observation(monkeypatch, emitters):
    from core.llm.client import _record_usage_ledger_event

    recorded: list[object] = []
    monkeypatch.setattr("core.llm.client.record_usage_event", lambda event: recorded.append(event))

    # startup warmup：与 ledger 同源的 llmWarmup 标记，不发观测。
    _record_usage_ledger_event(
        usage=_cached_usage(),
        metadata={"llmWarmup": True, "sessionId": "warm-session"},
        provider="relay",
        model="m",
        profile_id="primary",
        transport="chat_completions",
    )
    # 显式探测（qwen inflight cache keepalive probe 等）：promptPurpose 标记。
    observe_prompt_cache_usage(
        usage=_cached_usage(),
        metadata={
            "sessionId": "s1",
            "turnId": "t1",
            "promptPurpose": "qwen_inflight_cache_keepalive",
        },
        provider="relay",
        model="m",
        profile_id="primary",
    )

    assert recorded == []  # warmup 也没有进 ledger（上一批过滤保持不变）
    assert emitters["scene"] == []
    assert emitters["debug"] == []
    # 且 warmup 轮不污染基线：同会话下一次真实调用不会误判骤降。
    observe_prompt_cache_usage(
        usage=_uncached_usage(),
        metadata={"sessionId": "warm-session", "turnId": "t2"},
        provider="relay",
        model="m",
        profile_id="primary",
    )
    drops = [e for e in emitters["scene"] if e["code"] == PROMPT_CACHE_HIT_DROP_EVENT_CODE]
    assert drops == []


def test_hit_ratio_drop_warning_triggers_only_on_sharp_drop(emitters):
    observe_prompt_cache_usage(
        usage=_cached_usage(input_tokens=1000, cached=900),
        metadata={"sessionId": "s1", "turnId": "t1"},
        provider="relay",
        model="m",
        profile_id="primary",
    )
    assert [e["code"] for e in emitters["scene"]] == [PROMPT_CACHE_OBSERVED_EVENT_CODE]

    # 相邻轮命中率从 >0.5 跌到 0：补一条 warning 级骤降观测。
    observe_prompt_cache_usage(
        usage=_uncached_usage(input_tokens=1100),
        metadata={"sessionId": "s1", "turnId": "t2"},
        provider="relay",
        model="m",
        profile_id="primary",
    )
    drops = [e for e in emitters["scene"] if e["code"] == PROMPT_CACHE_HIT_DROP_EVENT_CODE]
    assert len(drops) == 1
    assert drops[0]["level"] == "warning"
    assert drops[0]["fields"]["previousTurnId"] == "t1"
    assert drops[0]["fields"]["previousHitRatio"] == 0.9
    assert drops[0]["fields"]["previousCacheHitTokens"] == 900
    assert drops[0]["fields"]["hitRatio"] == 0.0
    warning_lines = [line for line in emitters["debug"] if line[0] == "warning"]
    assert len(warning_lines) == 1
    assert "prompt prefix drift" in warning_lines[0][1]

    # 骤降后基线已更新为 0：后续持续 0 命中不重复告警（避免刷屏）。
    observe_prompt_cache_usage(
        usage=_uncached_usage(input_tokens=1200),
        metadata={"sessionId": "s1", "turnId": "t3"},
        provider="relay",
        model="m",
        profile_id="primary",
    )
    drops = [e for e in emitters["scene"] if e["code"] == PROMPT_CACHE_HIT_DROP_EVENT_CODE]
    assert len(drops) == 1


def test_drop_threshold_edges_are_not_triggered(emitters):
    # 上轮命中率恰好等于阈值（> 0.5 为严格大于）不触发。
    observe_prompt_cache_usage(
        usage=_cached_usage(input_tokens=1000, cached=500),
        metadata={"sessionId": "s-edge", "turnId": "t1"},
        provider="relay",
        model="m",
        profile_id="primary",
    )
    observe_prompt_cache_usage(
        usage=_uncached_usage(),
        metadata={"sessionId": "s-edge", "turnId": "t2"},
        provider="relay",
        model="m",
        profile_id="primary",
    )
    assert [e for e in emitters["scene"] if e["code"] == PROMPT_CACHE_HIT_DROP_EVENT_CODE] == []

    # 高命中率 -> 低但非零命中率（0.2）不是骤降到 0，不触发。
    observe_prompt_cache_usage(
        usage=_cached_usage(input_tokens=1000, cached=900),
        metadata={"sessionId": "s-partial", "turnId": "t1"},
        provider="relay",
        model="m",
        profile_id="primary",
    )
    observe_prompt_cache_usage(
        usage=_cached_usage(input_tokens=1000, cached=200),
        metadata={"sessionId": "s-partial", "turnId": "t2"},
        provider="relay",
        model="m",
        profile_id="primary",
    )
    assert [e for e in emitters["scene"] if e["code"] == PROMPT_CACHE_HIT_DROP_EVENT_CODE] == []


def test_missing_cache_telemetry_round_keeps_previous_baseline(emitters):
    # t1 高命中；t2 provider 漏报 cache 计数（observed=False，ratio 0.0）。
    observe_prompt_cache_usage(
        usage=_cached_usage(input_tokens=1000, cached=900),
        metadata={"sessionId": "s-miss", "turnId": "t1"},
        provider="relay",
        model="m",
        profile_id="primary",
    )
    no_telemetry = UsageStats(
        input_tokens=1100,
        output_tokens=10,
        total_tokens=1110,
        provider_raw_usage={"prompt_tokens": 1100},
    )
    observe_prompt_cache_usage(
        usage=no_telemetry,
        metadata={"sessionId": "s-miss", "turnId": "t2"},
        provider="relay",
        model="m",
        profile_id="primary",
    )
    assert [e for e in emitters["scene"] if e["code"] == PROMPT_CACHE_HIT_DROP_EVENT_CODE] == []

    # t3 遥测恢复且 0 命中：此时才对 t1 的基线触发骤降（漏报轮不覆盖基线）。
    observe_prompt_cache_usage(
        usage=_uncached_usage(input_tokens=1200),
        metadata={"sessionId": "s-miss", "turnId": "t3"},
        provider="relay",
        model="m",
        profile_id="primary",
    )
    drops = [e for e in emitters["scene"] if e["code"] == PROMPT_CACHE_HIT_DROP_EVENT_CODE]
    assert len(drops) == 1
    assert drops[0]["fields"]["previousTurnId"] == "t1"

    # 漏报轮自身的观测事件仍照发，但带 cacheUsageMissingReason。
    missing = [
        e
        for e in emitters["scene"]
        if e["code"] == PROMPT_CACHE_OBSERVED_EVENT_CODE and e["fields"]["turnId"] == "t2"
    ]
    assert missing[0]["fields"]["cacheUsageObserved"] is False
    assert missing[0]["fields"]["cacheUsageMissingReason"]
    assert missing[0]["fields"]["hitRatio"] == 0.0


def test_session_without_context_emits_but_never_compares(emitters):
    observe_prompt_cache_usage(
        usage=_cached_usage(input_tokens=1000, cached=900),
        metadata={},
        provider="relay",
        model="m",
        profile_id="tool-probe",
    )
    observe_prompt_cache_usage(
        usage=_uncached_usage(),
        metadata={},
        provider="relay",
        model="m",
        profile_id="tool-probe",
    )

    observed = [e for e in emitters["scene"] if e["code"] == PROMPT_CACHE_OBSERVED_EVENT_CODE]
    assert len(observed) == 2
    assert all(e["fields"]["sessionId"] == "" for e in observed)
    assert [e for e in emitters["scene"] if e["code"] == PROMPT_CACHE_HIT_DROP_EVENT_CODE] == []
    # 无会话上下文的人读行用 '-' 占位，保持可 grep。
    assert any("session=-" in line[1] for line in emitters["debug"])


def test_drop_detection_is_per_profile_and_model(emitters):
    common = {"sessionId": "s-multi"}
    for profile, model in (("primary", "qwen-plus"), ("research", "qwen-max")):
        observe_prompt_cache_usage(
            usage=_cached_usage(input_tokens=1000, cached=900),
            metadata={**common, "turnId": f"t1-{profile}"},
            provider="relay",
            model=model,
            profile_id=profile,
        )
    # primary 跌 0 触发；research 的基线不受影响，下一次高命中仍正常。
    observe_prompt_cache_usage(
        usage=_uncached_usage(),
        metadata={**common, "turnId": "t2-primary"},
        provider="relay",
        model="qwen-plus",
        profile_id="primary",
    )
    drops = [e for e in emitters["scene"] if e["code"] == PROMPT_CACHE_HIT_DROP_EVENT_CODE]
    assert len(drops) == 1
    assert drops[0]["fields"]["profileId"] == "primary"


def test_observation_failure_never_breaks_usage_ledger(monkeypatch):
    """The hook at the ledger finalize point swallows emitter failures."""

    from core.llm.client import _record_usage_ledger_event

    def _boom(*_args, **_kwargs):
        raise RuntimeError("scene service down")

    monkeypatch.setattr("core.llm.client.observe_prompt_cache_usage", _boom)
    recorded: list[object] = []
    monkeypatch.setattr("core.llm.client.record_usage_event", lambda event: recorded.append(event))

    _record_usage_ledger_event(
        usage=_cached_usage(),
        metadata={"sessionId": "s1", "turnId": "t1"},
        provider="relay",
        model="m",
        profile_id="primary",
        transport="chat_completions",
    )

    assert len(recorded) == 1


def test_human_line_lands_in_conversation_debug_jsonl_sink(monkeypatch):
    """End-to-end sink check: _log_human_line -> debug(tag=LLM) -> log_debug."""

    captured: list[tuple] = []

    class _SpyConversationLogger:
        def log_debug(self, tag, msg, level):
            captured.append((tag, msg, level))

    # core.logging 包属性 logger（UnifiedLogger 实例）会遮蔽同名子模块，
    # 用 importlib 显式取子模块对象，避免取到 UnifiedLogger。
    import importlib

    logger_module = importlib.import_module("core.logging.logger")
    monkeypatch.setattr(logger_module, "conversation_logger", _SpyConversationLogger())

    # 注意：_log_human_line 必须用模块顶层 import 的原函数引用；autouse 的
    # emitters fixture 会把模块属性替换为 spy，函数内 import 会拿到 spy。
    _log_human_line("LLM prompt cache: session=s1 hit=1 ratio=1.0")
    _log_human_line("LLM prompt cache hit ratio drop: ...", level="warning")

    # 无关的 [Workspace]/sandbox 日志行可能并发混入同一 sink，按消息前缀过滤。
    mine = [entry for entry in captured if str(entry[1]).startswith("LLM prompt cache")]
    assert mine[0] == ("LLM", "LLM prompt cache: session=s1 hit=1 ratio=1.0", "INFO")
    assert mine[1][0] == "LLM"
    assert mine[1][1] == "LLM prompt cache hit ratio drop: ..."
    assert mine[1][2] == "WARN"


def test_drop_threshold_constant_pinned():
    assert PROMPT_CACHE_DROP_PREVIOUS_RATIO_MIN == 0.5
