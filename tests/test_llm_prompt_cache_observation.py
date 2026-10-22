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

    import core.llm.prompt_cache_observation as pco

    originals = {
        "record_scene_event": pco._record_scene_event,
        "log_human_line": pco._log_human_line,
    }
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
    return {
        "scene": scene_events,
        "debug": debug_lines,
        "originals": originals,
    }


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


def _real_form_metadata(**overrides):
    """Metadata exactly as ``LLMInvocationContext.to_metadata`` produces it.

    真实轮次恒带 ``promptPurpose``（默认 main_reply）等目的字段；这是
    2026-10-22 复盘的断点形态，回归测试必须用这份形状而不是裸 metadata。
    """

    base = {
        "sessionId": "session-20261022-133947-431818",
        "turnId": "session-20261022-133947-431818-20261022053950756188",
        "invocationId": "inv-1",
        "agentId": "agent-1",
        "llmSlot": "dialogue",
        "llmRunKind": "chat_turn",
        "promptPurpose": "main_reply",
        "conversationBound": True,
        "promptCacheScope": "chat_agent_static",
    }
    base.update(overrides)
    return base


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
    assert fields["cachedInputTokens"] == 700
    assert fields["uncachedInputTokens"] == 300
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


def test_real_form_prompt_purpose_metadata_still_observes(monkeypatch, emitters):
    """真实轮次恒带 promptPurpose（to_metadata 默认 main_reply）。

    2026-10-22 复盘断点：旧判定把「带 promptPurpose」当探测，真实会话
    观测全部被跳过（48h 0 条事件）。回归钉死：main_reply 形态必须照常
    发观测并推进骤降基线。
    """

    from core.llm.client import _record_usage_ledger_event

    recorded: list[object] = []
    monkeypatch.setattr("core.llm.client.record_usage_event", lambda event: recorded.append(event))

    _record_usage_ledger_event(
        usage=_cached_usage(input_tokens=1000, cached=700),
        metadata=_real_form_metadata(),
        provider="aliyun",
        model="qwen3.8-flash",
        profile_id="primary",
        transport="chat_completions",
    )

    assert len(recorded) == 1
    observed = [e for e in emitters["scene"] if e["code"] == PROMPT_CACHE_OBSERVED_EVENT_CODE]
    assert len(observed) == 1
    fields = observed[0]["fields"]
    assert fields["sessionId"].startswith("session-20261022")
    assert fields["hitRatio"] == 0.7
    assert fields["cacheUsageObserved"] is True


def test_business_prompt_purposes_other_than_keepalive_still_observe(emitters):
    """promptPurpose 是调用目的而非探测标记：业务目的照常观测。"""

    observe_prompt_cache_usage(
        usage=_cached_usage(input_tokens=1000, cached=800),
        metadata=_real_form_metadata(promptPurpose="commit_message"),
        provider="relay",
        model="m",
        profile_id="primary",
    )
    observed = [e for e in emitters["scene"] if e["code"] == PROMPT_CACHE_OBSERVED_EVENT_CODE]
    assert len(observed) == 1


def test_real_form_hit_ratio_drop_warning_fires(emitters):
    """骤降告警在真实形态 metadata 下照原语义触发。"""

    observe_prompt_cache_usage(
        usage=_cached_usage(input_tokens=1000, cached=900),
        metadata=_real_form_metadata(turnId="t1"),
        provider="aliyun",
        model="qwen3.8-flash",
        profile_id="primary",
    )
    observe_prompt_cache_usage(
        usage=_uncached_usage(input_tokens=1100),
        metadata=_real_form_metadata(turnId="t2"),
        provider="aliyun",
        model="qwen3.8-flash",
        profile_id="primary",
    )
    drops = [e for e in emitters["scene"] if e["code"] == PROMPT_CACHE_HIT_DROP_EVENT_CODE]
    assert len(drops) == 1
    assert drops[0]["level"] == "warning"
    assert drops[0]["fields"]["previousTurnId"] == "t1"
    assert drops[0]["fields"]["hitRatio"] == 0.0


def _restore_real_scene_path(monkeypatch, emitters):
    """让观测走真实 scene 记录函数（undo emitters 的 scene spy，保留人读行 spy）。"""

    import core.llm.prompt_cache_observation as pco

    monkeypatch.setattr(
        pco, "_record_scene_event", emitters["originals"]["record_scene_event"]
    )


def test_ledger_finalize_lands_scene_event_when_scene_context_present(monkeypatch, emitters):
    """收口路径（scene 上下文在）：观测事件经 runtime scene 记录器落活跃场景。"""

    from core.llm.client import _record_usage_ledger_event

    _restore_real_scene_path(monkeypatch, emitters)
    captured: list[dict] = []

    def _spy_record(component, phase, event_code, **kwargs):
        captured.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                **kwargs,
            }
        )
        return {"accepted": True, "runtimeSceneId": "scene-1"}

    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event_quietly",
        _spy_record,
    )
    monkeypatch.setattr("core.llm.client.record_usage_event", lambda event: [])

    _record_usage_ledger_event(
        usage=_cached_usage(input_tokens=1000, cached=700),
        metadata=_real_form_metadata(),
        provider="aliyun",
        model="qwen3.8-flash",
        profile_id="primary",
        transport="chat_completions",
    )

    events = [e for e in captured if e["eventCode"] == PROMPT_CACHE_OBSERVED_EVENT_CODE]
    assert len(events) == 1
    assert events[0]["component"] == "llm"
    assert events[0]["phase"] == "cache"
    # 观测属于刚收口的轮次：允许落到最近完成场景（sealed 窗口兜底）。
    assert events[0]["allow_recent_completed"] is True
    assert events[0]["fields"]["sessionId"].startswith("session-20261022")
    assert events[0]["lifecycle"] is False


def test_ledger_finalize_survives_scene_context_missing(monkeypatch, emitters):
    """收口路径（scene 上下文缺）：无场景可落时收口照常完成、人读行照发。"""

    from core.llm.client import _record_usage_ledger_event

    _restore_real_scene_path(monkeypatch, emitters)
    recorded: list[object] = []
    monkeypatch.setattr("core.llm.client.record_usage_event", lambda event: recorded.append(event))

    def _no_scene(*_args, **_kwargs):
        # 与 _record_runtime_scene_event_impl 无场景时的返回一致。
        return {"accepted": False, "reason": "no_runtime_scene"}

    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event_quietly",
        _no_scene,
    )

    _record_usage_ledger_event(
        usage=_cached_usage(input_tokens=1000, cached=700),
        metadata=_real_form_metadata(),
        provider="aliyun",
        model="qwen3.8-flash",
        profile_id="primary",
        transport="chat_completions",
    )

    assert len(recorded) == 1
    # 场景落点缺失不阻断观测的另一半 sink：人读摘要行照常落到 conversation jsonl。
    assert any(
        line[1].startswith("LLM prompt cache:") for line in emitters["debug"]
    )


def test_ledger_finalize_survives_scene_recorder_crash(monkeypatch, emitters):
    """收口路径（scene 记录器抛异常）：best-effort，不影响 ledger 收口。"""

    from core.llm.client import _record_usage_ledger_event

    _restore_real_scene_path(monkeypatch, emitters)
    recorded: list[object] = []
    monkeypatch.setattr("core.llm.client.record_usage_event", lambda event: recorded.append(event))

    def _boom(*_args, **_kwargs):
        raise RuntimeError("scene service down")

    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event_quietly",
        _boom,
    )

    _record_usage_ledger_event(
        usage=_cached_usage(input_tokens=1000, cached=700),
        metadata=_real_form_metadata(),
        provider="aliyun",
        model="qwen3.8-flash",
        profile_id="primary",
        transport="chat_completions",
    )

    assert len(recorded) == 1


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
    # 显式 cache keepalive 探测：精确的 qwen_inflight_cache_keepalive 目的值，
    # 探测命中率恒高，混入会污染相邻轮对比基线。
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


def test_scene_token_counter_fields_survive_redaction_allowlist():
    """落盘字段名必须在 scene 遥测的安全计数键白名单内。

    SENSITIVE_FIELD_KEYWORDS 含 "token"：不在白名单的 token 计数键落地时
    会被打成 [redacted]，观测就失去了命中量证据。回归钉死规范名。
    """

    from core.web.services.runtime_scene.record import _is_safe_usage_counter_key

    for key in ("cachedInputTokens", "uncachedInputTokens", "inputTokens", "outputTokens"):
        assert _is_safe_usage_counter_key(str(key).strip().lower()), key
