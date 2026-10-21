"""TTFT batch 5 task C: turn-independent decision template cache + scene dedupe."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from core.authorization import tool_authorization_service as service
from core.authorization.tool_authorization_service import (
    clear_turn_decision_template_cache,
    resolve_enforced_authorization,
)


def _registry_payload():
    return {
        "registryVersion": 1,
        "registryFingerprint": "registry-1",
        "descriptors": [
            {
                "name": "grep_search_tool",
                "enabled": True,
                "capabilities": ["read"],
                "risk": "read",
                "approval": "never",
                "aliases": [],
            },
            {
                "name": "web_search_tool",
                "enabled": True,
                "capabilities": ["network"],
                "risk": "network",
                "approval": "never",
                "aliases": [],
            },
        ],
        "tools": [
            {"name": "grep_search_tool", "enabled": True, "runtimeActive": True, "llmVisible": True},
            {"name": "web_search_tool", "enabled": True, "runtimeActive": True, "llmVisible": True},
        ],
    }


def _runtime(policy, turn_id="turn-auth"):
    return {
        "agentId": "agent-cache",
        "turnId": turn_id,
        "agent": {"agentId": "agent-cache", "primaryMode": "chat"},
        "toolPolicy": {"policyId": "tool-agent-cache", **policy},
    }


def test_turn_decision_template_cache_hit_is_equivalent_to_full_evaluation():
    clear_turn_decision_template_cache()
    runtime = _runtime({"allowedTools": ["grep_search_tool"], "preferredTools": []})
    payload = _registry_payload()

    first = resolve_enforced_authorization(runtime=runtime, registry_payload=payload, generated_at="2026-07-14T00:00:00Z")
    assert first.decision_cache_hit is False
    assert first.decision_cache_key

    second = resolve_enforced_authorization(runtime=runtime, registry_payload=payload, generated_at="2026-07-14T00:00:00Z")
    assert second.decision_cache_hit is True
    assert second.decision_cache_key == first.decision_cache_key
    # 等价性硬门：命中重建的决策与全量评估逐字段一致（含指纹）。
    assert second.decision == first.decision
    assert second.deny_code_counts == first.deny_code_counts

    # 与「清缓存后全量重算」也一致。
    clear_turn_decision_template_cache()
    fresh = resolve_enforced_authorization(runtime=runtime, registry_payload=payload, generated_at="2026-07-14T00:00:00Z")
    assert fresh.decision_cache_hit is False
    assert fresh.decision == second.decision


def test_turn_decision_template_cache_rebinds_turn_identity():
    clear_turn_decision_template_cache()
    payload = _registry_payload()
    policy = {"allowedTools": ["grep_search_tool"], "preferredTools": []}

    resolve_enforced_authorization(
        runtime=_runtime(policy, turn_id="turn-one"), registry_payload=payload, generated_at="2026-07-14T00:00:00Z"
    )
    reused = resolve_enforced_authorization(
        runtime=_runtime(policy, turn_id="turn-two"), registry_payload=payload, generated_at="2026-07-14T00:00:00Z"
    )
    assert reused.decision_cache_hit is True
    assert reused.decision.turn_id == "turn-two"

    # 与全量评估同回合输入的决策（含指纹）一致。
    clear_turn_decision_template_cache()
    fresh = resolve_enforced_authorization(
        runtime=_runtime(policy, turn_id="turn-two"), registry_payload=payload, generated_at="2026-07-14T00:00:00Z"
    )
    assert fresh.decision_cache_hit is False
    assert fresh.decision == reused.decision


def test_turn_decision_template_cache_invalidates_on_policy_change():
    clear_turn_decision_template_cache()
    payload = _registry_payload()

    resolve_enforced_authorization(
        runtime=_runtime({"allowedTools": ["grep_search_tool"], "preferredTools": []}),
        registry_payload=payload,
    )
    hit = resolve_enforced_authorization(
        runtime=_runtime({"allowedTools": ["grep_search_tool"], "preferredTools": []}),
        registry_payload=payload,
    )
    assert hit.decision_cache_hit is True

    changed = resolve_enforced_authorization(
        runtime=_runtime({"allowedTools": ["grep_search_tool", "web_search_tool"], "preferredTools": []}),
        registry_payload=payload,
    )
    assert changed.decision_cache_hit is False
    assert changed.decision.executable_tools == ("grep_search_tool", "web_search_tool")


def test_turn_decision_template_cache_invalidates_on_registry_change():
    clear_turn_decision_template_cache()
    policy = {"allowedTools": ["grep_search_tool", "web_search_tool"], "preferredTools": []}

    resolve_enforced_authorization(runtime=_runtime(policy), registry_payload=_registry_payload())
    hit = resolve_enforced_authorization(runtime=_runtime(policy), registry_payload=_registry_payload())
    assert hit.decision_cache_hit is True

    changed_payload = _registry_payload()
    changed_payload["registryFingerprint"] = "registry-2"
    changed = resolve_enforced_authorization(runtime=_runtime(policy), registry_payload=changed_payload)
    assert changed.decision_cache_hit is False


def test_turn_decision_template_cache_invalidates_on_externally_blocked_tools():
    clear_turn_decision_template_cache()
    payload = _registry_payload()
    policy = {"allowedTools": ["grep_search_tool", "web_search_tool"], "preferredTools": []}

    resolve_enforced_authorization(runtime=_runtime(policy), registry_payload=payload)
    hit = resolve_enforced_authorization(runtime=_runtime(policy), registry_payload=payload)
    assert hit.decision_cache_hit is True

    blocked = dict(_runtime(policy))
    blocked["externallyBlockedTools"] = ["web_search_tool"]
    changed = resolve_enforced_authorization(runtime=blocked, registry_payload=payload)
    assert changed.decision_cache_hit is False
    assert changed.decision.visible_tools == ("grep_search_tool",)


def test_resolve_turn_authorization_dedupes_identical_scene_events_and_keeps_install(monkeypatch):
    from core.logging import tool_authorization_events as events
    from core.orchestration import tool_authorization_binding as binding

    binding.clear_turn_authorization_telemetry_state()
    clear_turn_decision_template_cache()

    reports: list[Any] = []

    def fake_report(cache_key: str):
        return SimpleNamespace(
            decision=SimpleNamespace(agent_id="agent-dedupe", turn_id="turn-current"),
            decision_cache_key=cache_key,
            decision_cache_hit=True,
        )

    def fake_resolve(*, runtime):
        report = fake_report("key-stable")
        reports.append(report)
        return report

    recorded: list[Any] = []
    installed: list[Any] = []
    timing_events: list[dict[str, Any]] = []
    monkeypatch.setattr(service, "resolve_enforced_authorization", fake_resolve)
    monkeypatch.setattr(service, "install_execution_authorization", lambda report, **_kwargs: installed.append(report))
    monkeypatch.setattr(events, "record_authorization_decision", lambda report: recorded.append(report))
    monkeypatch.setattr(events, "record_authorization_timing", lambda **fields: timing_events.append(fields))

    turn_runtime = {"agentId": "agent-dedupe", "turnId": "turn-1", "runId": "run-1", "mode": "chat"}
    kwargs = dict(
        runtime_agent_binding={"agentId": "agent-dedupe"},
        turn_runtime_fn=lambda: dict(turn_runtime),
        current_runtime_fn=lambda: {"agentId": "agent-dedupe"},
    )

    first = binding.resolve_turn_authorization(**kwargs)
    second = binding.resolve_turn_authorization(**kwargs)

    # 首轮记录一次；同签名后续轮次跳过重复 scene 事件。
    assert len(recorded) == 1
    assert recorded[0] is first
    # install 每回合照常执行（回合级 ContextVar 与计数器不可跳过）。
    assert len(installed) == 2
    assert installed[0] is first and installed[1] is second
    timing = binding.last_turn_authorization_timing()
    assert timing is not None
    assert timing["turnAuthorizationCacheHit"] is True

    # 输入变化（决策签名变化）后的首个回合恢复记录。
    def fake_resolve_changed(*, runtime):
        report = fake_report("key-changed")
        reports.append(report)
        return report

    monkeypatch.setattr(service, "resolve_enforced_authorization", fake_resolve_changed)
    third = binding.resolve_turn_authorization(**kwargs)
    assert len(recorded) == 2
    assert recorded[1] is third
    # 再次同签名：跳过。
    binding.resolve_turn_authorization(**kwargs)
    assert len(recorded) == 2
    binding.clear_turn_authorization_telemetry_state()
    clear_turn_decision_template_cache()


def test_resolve_turn_authorization_emits_subanchor_timing_event_every_turn(monkeypatch):
    """TTFT 批六：子锚点 timing 事件每回合写出，且命中去重轮不缺席。"""

    from core.logging import tool_authorization_events as events
    from core.orchestration import tool_authorization_binding as binding

    binding.clear_turn_authorization_telemetry_state()
    clear_turn_decision_template_cache()

    def fake_resolve(*, runtime):
        return SimpleNamespace(
            decision=SimpleNamespace(agent_id="agent-timing", turn_id="turn-timing"),
            decision_cache_key="key-timing",
            decision_cache_hit=True,
            registry_ms=5,
        )

    recorded: list[Any] = []
    record_calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(service, "resolve_enforced_authorization", fake_resolve)
    monkeypatch.setattr(service, "install_execution_authorization", lambda report, **_kwargs: None)
    monkeypatch.setattr(events, "record_authorization_decision", lambda report: recorded.append(report))
    monkeypatch.setattr(events, "_record", lambda event_code, **kwargs: record_calls.append((event_code, kwargs)))

    kwargs = dict(
        runtime_agent_binding={"agentId": "agent-timing"},
        turn_runtime_fn=lambda: {"agentId": "agent-timing", "turnId": "turn-timing"},
        current_runtime_fn=lambda: {"agentId": "agent-timing"},
    )
    binding.resolve_turn_authorization(**kwargs)
    binding.resolve_turn_authorization(**kwargs)

    # decision 事件去重为 1 条，timing 事件每回合各写一条。
    assert len(recorded) == 1
    timing_events = [kwargs_ for event_code, kwargs_ in record_calls if event_code == "tool.authorization.timing"]
    assert len(timing_events) == 2
    for event in timing_events:
        assert event["outcome"] == "resolved"
        assert event["level"] == "info"
        fields = event["fields"]
        assert fields["agentId"] == "agent-timing"
        assert fields["turnId"] == "turn-timing"
        assert fields["cacheHit"] is True
        assert isinstance(fields["durationMs"], int) and fields["durationMs"] >= 0
        for anchor in (
            "bindMs",
            "registryMs",
            "resolveMs",
            "installMs",
            "recordMs",
            "identityMs",
            "maxCallsMs",
            "installCoreMs",
        ):
            assert isinstance(fields[anchor], int) and fields[anchor] >= 0
    # registryMs 透传 service 报告的注册表加载段。
    assert timing_events[0]["fields"]["registryMs"] == 5

    thread_timing = binding.last_turn_authorization_timing()
    assert thread_timing is not None
    assert thread_timing["turnAuthorizationCacheHit"] is True
    assert thread_timing["registryMs"] == 5
    for anchor in (
        "bindMs",
        "resolveMs",
        "installMs",
        "recordMs",
        "identityMs",
        "maxCallsMs",
        "installCoreMs",
    ):
        assert isinstance(thread_timing[anchor], int) and thread_timing[anchor] >= 0

    binding.clear_turn_authorization_telemetry_state()
    clear_turn_decision_template_cache()


def test_resolve_turn_authorization_timing_event_carries_real_install_subanchors(monkeypatch):
    """TTFT 批七：真实 install 执行后，timing 事件携带 install 内部细分锚点。"""

    from core.logging import tool_authorization_events as events
    from core.orchestration import session_budget_resolve
    from core.orchestration import tool_authorization_binding as binding

    binding.clear_turn_authorization_telemetry_state()
    service.clear_execution_authorization()
    service.clear_session_override_memo()
    clear_turn_decision_template_cache()

    override_calls = {"count": 0}

    def fake_session_override(session_id):
        override_calls["count"] += 1
        return None

    monkeypatch.setattr(session_budget_resolve, "get_session_budget_parameters", fake_session_override)

    def fake_resolve(*, runtime):
        return SimpleNamespace(
            decision=SimpleNamespace(
                agent_id="agent-install-timing",
                turn_id="turn-install-timing",
                decision_fingerprint="fingerprint-install-timing",
                executable_tools=("grep_search_tool",),
            ),
            decision_cache_key="key-install-timing",
            decision_cache_hit=True,
            registry_ms=0,
        )

    record_calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(service, "resolve_enforced_authorization", fake_resolve)
    monkeypatch.setattr(events, "record_authorization_decision", lambda report: None)
    monkeypatch.setattr(events, "_record", lambda event_code, **kwargs: record_calls.append((event_code, kwargs)))

    kwargs = dict(
        runtime_agent_binding={"agentId": "agent-install-timing"},
        turn_runtime_fn=lambda: {"agentId": "agent-install-timing", "turnId": "turn-install-timing"},
        current_runtime_fn=lambda: {
            "agentId": "agent-install-timing",
            "turnId": "turn-install-timing",
            "sessionId": "session-install-timing",
            "agent": {"agentId": "agent-install-timing"},
            "agentConfigSnapshot": {
                "agentId": "agent-install-timing",
                "configRevision": 4,
                "configHash": "hash-install-timing",
            },
            "permissionPreset": "request_approval",
            "llmModel": "install-timing-model",
            "llmProvider": "install-timing-provider",
            "toolPolicy": {"policyId": "tool-agent-install-timing", "maxCallsPerTurn": 32},
        },
    )
    binding.resolve_turn_authorization(**kwargs)

    timing_events = [kwargs_ for event_code, kwargs_ in record_calls if event_code == "tool.authorization.timing"]
    assert len(timing_events) == 1
    fields = timing_events[0]["fields"]
    # 真实 install 走过 identity/maxCalls/core 三段，线程局部非空并进入事件。
    assert fields["installMs"] >= 0
    for anchor in ("identityMs", "maxCallsMs", "installCoreMs"):
        assert isinstance(fields[anchor], int) and fields[anchor] >= 0
        assert fields[anchor] <= max(1, fields["installMs"] + 1)

    # memo 生效：同快照身份第二回合的 session override 查询不再触碰 store。
    binding.resolve_turn_authorization(**kwargs)
    assert override_calls["count"] == 1
    assert len([1 for event_code, _ in record_calls if event_code == "tool.authorization.timing"]) == 2

    binding.clear_turn_authorization_telemetry_state()
    service.clear_session_override_memo()
    service.clear_execution_authorization()
    clear_turn_decision_template_cache()
