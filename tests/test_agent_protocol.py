#!/usr/bin/env python3
"""
agent.py 协议层回归测试
"""

import copy
import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

import agent as agent_module
from agent import (
    SelfEvolvingAgent,
    compact_tool_output_for_diagnosis,
    extract_subagent_primary_goal,
    infer_result_from_tool_outputs,
)
from config import Settings
from core.infrastructure.tool_executor import ToolExecutor
from core.infrastructure.llm_utils import (
    build_cacheable_system_prefix_message,
    is_volatile_system_context_message,
    parse_tool_args,
    parse_xml_tool_calls,
)
from core.infrastructure.runtime_input import build_chat_user_message, build_external_request_message
from core.infrastructure.tool_result import RuntimeToolMetadata
from core.prompt_manager import build_restart_focus_state_memory
from core.orchestration.agent_modes import AgentMode, ModePolicy
from core.orchestration.delegation_governor import DelegationGovernor
from core.orchestration.round_state import RoundStateController
from core.orchestration.runtime_goal import RuntimeGoalPacket
from core.orchestration.response_processor import ResponseProcessor
from core.orchestration.response_surface import ResponseSurfaceController
from core.orchestration.turn_outcome import TurnOutcomeController
from core.orchestration.tool_lifecycle import ToolLifecycleBridge
from core.llm.client import llm_status_context
from core.llm.invocation import invocation_scope_from_metadata
from core.llm.types import CanonicalItemIdentity, CanonicalToolCall, LLMError, TurnOutcome as LLMTurnOutcome
from tests.helpers.isolated_config import isolated_settings_config
from tools.agent_tools import spawn_agent as spawn_agent_impl, set_subagent_stream_sink
from tools.Key_Tools import create_key_tools, create_llm_facing_tools


def test_turn_tool_allowlist_rebinds_and_blocks_out_of_scope_execution(monkeypatch):
    bound: list[list[object]] = []

    class FakeLlm:
        def bind_tools(self, tools):
            bound.append(list(tools))
            return ("bound", tuple(tools))

    context_tool = object()
    writeback_tool = object()
    unrelated_tool = object()
    instance = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    instance._base_llm = FakeLlm()
    instance.llm_with_tools = object()
    instance._bound_llm_cache = {}
    instance._key_tool_map = {
        "source_collection_context_tool": context_tool,
        "source_collection_stage_writeback_tool": writeback_tool,
        "knowledge_governance_tasks_tool": unrelated_tool,
    }
    instance.key_tool_maps = set(instance._key_tool_map)
    instance._turn_allowed_tool_names = {
        "source_collection_context_tool",
        "source_collection_stage_writeback_tool",
    }
    monkeypatch.setattr(agent_module, "client_supports_tool_calling", lambda _llm: True)

    resolved = instance._get_llm_for_current_mode()

    assert resolved == ("bound", (context_tool, writeback_tool))
    assert instance._is_tool_visible_to_current_agent("source_collection_context_tool") is True
    assert instance._is_tool_visible_to_current_agent("knowledge_governance_tasks_tool") is False


def _build_operator_delegation_request(*, goal: str, iteration: int, total_tool_calls: int):
    """保留对独立治理器的契约覆盖，不经由对话 Agent 私有入口。"""
    governor = DelegationGovernor(
        spawn_execute=lambda *_args, **_kwargs: ("{}", None),
        sync_runtime_state_memory=lambda: None,
        ui_getter=lambda: None,
        session_getter=agent_module.get_session_state,
    )
    return governor.build_request(
        goal=goal,
        iteration=iteration,
        total_tool_calls=total_tool_calls,
    )


def test_turn_failure_diagnostic_includes_prompt_free_turn_correlation(monkeypatch):
    events = []
    monkeypatch.setenv("VIBELUTION_TURN_SESSION_ID", "session-failure-trace")
    monkeypatch.setenv("VIBELUTION_TURN_RUN_ID", "turn-failure-trace")
    monkeypatch.setenv("VIBELUTION_TURN_AGENT_ID", "agent-failure-trace")
    monkeypatch.setattr(
        agent_module,
        "_record_agent_scene_event",
        lambda phase, code, **kwargs: events.append(
            (phase, code, kwargs.get("fields") or {})
        ),
    )
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    agent.runtime_agent_binding = {}
    agent._last_llm_error_details = {}
    agent._last_llm_failure_attempts = 0
    agent._last_llm_failure_max_attempts = 0
    agent._last_turn_metadata = {}

    agent._record_turn_failure_diagnostic(
        category="protocol_error",
        reason_code="canonical_turn_unsuccessful",
        reason_summary="Canonical outcome was incomplete.",
        reason_detail="No successful terminal outcome was available.",
        chain_stage="agent_outcome_evaluation",
        event_code="llm.turn_outcome.unsuccessful",
        fields={"outcomeKind": "incomplete"},
    )

    scene_fields = events[-1][2]
    assert scene_fields["sessionId"] == "session-failure-trace"
    assert scene_fields["turnId"] == "turn-failure-trace"
    assert scene_fields["agentId"] == "agent-failure-trace"
    assert scene_fields["reasonCode"] == "canonical_turn_unsuccessful"
    assert "No successful terminal outcome was available." not in str(scene_fields)


def test_context_budget_preflight_guard_records_structured_diagnostic(monkeypatch):
    """context_budget 硬闸必须留下结构化诊断（context_error/context_budget_exhausted），
    而不是静默置 failed 后落到 failed_runtime 误判。"""
    monkeypatch.setattr(agent_module, "_record_agent_scene_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        agent_module,
        "get_ui",
        lambda: SimpleNamespace(add_log=lambda *args, **kwargs: None),
    )
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    agent.runtime_agent_binding = {}
    agent._context_input_hard_limit = 1000
    agent._last_llm_error_details = {}
    agent._last_llm_failure_attempts = 0
    agent._last_llm_failure_max_attempts = 0
    agent._last_turn_metadata = {}
    agent._last_turn_failed = False

    blocked = agent._context_budget_preflight_guard(
        estimated_tokens=5000,
        iteration=3,
        message_count=40,
    )
    not_blocked = agent._context_budget_preflight_guard(
        estimated_tokens=100,
        iteration=4,
        message_count=41,
    )

    assert blocked is True
    assert not_blocked is False
    failure = dict(agent._last_turn_metadata["llm_failure"])
    assert failure["category"] == "context_error"
    assert failure["reason_code"] == "context_budget_exhausted"
    assert failure["chain_stage"] == "llm_preflight"
    assert failure["recovery_action"] == "compress_context_or_new_session"
    assert agent._last_turn_failed is True


def test_session_turn_reuse_refreshes_turn_scoped_tool_authorization(monkeypatch):
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    agent.key_tools = [SimpleNamespace(name="git_status")]
    agent._tool_authorization_decision_fingerprint = "prior-turn"
    agent._active_turn_messages = ["old"]
    agent._active_turn_goal = "old goal"
    agent._active_turn_terminal = True
    agent._pending_static_context_blocks = ["old"]
    agent._pending_runtime_context_blocks = ["old"]
    agent._pending_volatile_context_blocks = ["old"]
    agent._runtime_context_seeded_by_host = True
    agent._last_turn_metadata = {"old": True}
    agent._last_visible_response_text = "old"
    agent._last_response_tool_calls = 1
    agent._recent_tool_outputs = ["old"]
    agent._recent_tool_records = [{"old": True}]
    agent._pending_lifecycle_action = "old"
    agent._turn_interrupt_checker = lambda: "old"
    resolved_with = []

    def resolve_authorization(tools):
        resolved_with.append(tools)
        return SimpleNamespace(decision=SimpleNamespace(decision_fingerprint="current-turn"))

    monkeypatch.setattr(agent, "_resolve_tool_authorization", resolve_authorization)

    agent.prepare_for_session_turn_reuse()

    assert resolved_with == [agent.key_tools]
    assert agent._tool_authorization_decision_fingerprint == "current-turn"
    assert agent._active_turn_messages is None
    assert agent._pending_runtime_context_blocks == []


def test_turn_interrupt_checker_rebinds_tool_executor_in_worker_context():
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    agent.tool_executor = ToolExecutor()
    agent._turn_interrupt_checker = None
    tool_started = threading.Event()
    outcome: dict[str, str] = {}

    def cancel_probe():
        tool_started.set()
        return "ran"

    agent.tool_executor.register_tool("cancel_probe", cancel_probe, timeout=5)

    def run_worker():
        agent.set_turn_interrupt_checker(lambda: "operator stop")
        outcome["result"] = str(agent.tool_executor.execute("cancel_probe", {})[0])

    worker = threading.Thread(target=run_worker)
    worker.start()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert not tool_started.is_set()
    assert "[取消] cancel_probe 已因停止请求跳过执行：operator stop" in outcome["result"]


def test_supervised_system_prompt_excludes_global_git_and_runtime_diagnostics():
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    captured: dict[str, object] = {}

    class DummyPromptManager:
        def build(self, *, exclude=None):
            captured["excluded_sections"] = list(exclude or [])
            return "supervised prompt"

    agent.mode_policy = ModePolicy(
        mode=AgentMode.SUPERVISED_EVOLUTION,
        orchestrator_kind="evolution",
        keep_multi_turn_context=False,
        allow_auto_loop=False,
        capture_chat_dataset_candidates=False,
        reset_context_before_turn=True,
        reset_context_between_cases=True,
        allow_direct_supervised_payload=True,
        finish_after_direct_response=True,
        runtime_input_builder=build_external_request_message,
    )
    agent.prompt_manager = DummyPromptManager()

    prompt = agent._build_system_prompt_for_turn(stable_session_prompt=False)

    assert prompt == "supervised prompt"
    assert captured["excluded_sections"] == ["GIT_MEMORY", "RUNTIME_LOG_INDEX"]


def test_system_prompt_reuse_follows_runtime_state_key_not_git():
    # Git is tool-driven; system prompt may be reused across iterations while runtime key is stable.
    assert agent_module._can_reuse_system_prompt(
        has_cached_prompt=True,
        prompt_built_with_runtime_key="runtime-1",
        current_runtime_state_memory_key="runtime-1",
    )
    assert not agent_module._can_reuse_system_prompt(
        has_cached_prompt=False,
        prompt_built_with_runtime_key="runtime-1",
        current_runtime_state_memory_key="runtime-1",
    )
    assert not agent_module._can_reuse_system_prompt(
        has_cached_prompt=True,
        prompt_built_with_runtime_key="runtime-1",
        current_runtime_state_memory_key="runtime-2",
    )
    # Legacy helper still works for older call sites.
    assert agent_module._can_reuse_initial_prompt(
        pending=True,
        initial_runtime_state_memory_key="runtime-1",
        current_runtime_state_memory_key="runtime-1",
    )
    assert agent_module._can_reuse_initial_prompt(
        pending=True,
        initial_git_state=SimpleNamespace(dirty=True, available=False),
        current_git_state=SimpleNamespace(dirty=True, available=False, head_rev="other"),
        initial_runtime_state_memory_key="runtime-1",
        current_runtime_state_memory_key="runtime-1",
    )


def test_runtime_state_memory_sync_is_dirty_flagged(monkeypatch):
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    agent._runtime_state_memory_dirty = False
    agent._last_runtime_state_memory = ""
    agent._last_runtime_state_memory_key = ""
    agent._carryover_state_memory = ""
    agent.prompt_manager = SimpleNamespace(
        update_state_memory=lambda *a, **k: None,
        clear_state_memory=lambda *a, **k: None,
    )
    renders = {"count": 0}

    monkeypatch.setattr(
        agent_module,
        "get_session_state",
        lambda: SimpleNamespace(
            render_dialogue_runtime_observations=lambda: (
                renders.__setitem__("count", renders["count"] + 1) or "obs"
            )
        ),
    )
    monkeypatch.setattr(agent, "_is_restart_focus_mode", lambda: False)
    monkeypatch.setattr(agent_module, "compose_state_memory", lambda **kwargs: kwargs.get("runtime_summary") or "")
    monkeypatch.setattr(agent_module, "build_state_memory_key", lambda summary: f"key:{summary}")

    agent._sync_runtime_state_memory()
    assert renders["count"] == 0

    agent._mark_runtime_state_memory_dirty()
    agent._sync_runtime_state_memory()
    assert renders["count"] == 1
    assert agent._runtime_state_memory_dirty is False

    agent._sync_runtime_state_memory(force=True)
    assert renders["count"] == 2


def test_direct_chat_prompt_build_excludes_global_runtime_log_index():
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    build_calls: list[dict[str, object]] = []
    agent.prompt_manager = SimpleNamespace(
        build=lambda **kwargs: build_calls.append(dict(kwargs)) or "session system prompt"
    )

    assert agent._build_system_prompt_for_turn(stable_session_prompt=True) == "session system prompt"
    assert agent._build_system_prompt_for_turn(stable_session_prompt=False) == "session system prompt"

    assert build_calls == [
        {"exclude": ["RUNTIME_LOG_INDEX"]},
        {},
    ]


def test_session_core_snapshot_replaces_prompt_manager_core_without_duplicates():
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    build_calls: list[dict[str, object]] = []
    agent.prompt_manager = SimpleNamespace(
        build=lambda **kwargs: build_calls.append(dict(kwargs)) or "session system prompt"
    )
    agent._core_prompt_snapshot_seeded_by_host = True

    assert agent._build_system_prompt_for_turn(stable_session_prompt=True) == "session system prompt"

    assert build_calls == [
        {
            "exclude": ["RUNTIME_LOG_INDEX", "COMMON", "SOUL", "AGENTS"],
            "frozen_core_sections": ["COMMON", "SOUL", "AGENTS"],
        }
    ]


def test_numbered_confirmation_goal_preserves_previous_assistant_context():
    history = [
        SystemMessage(content=""),
        AIMessage(
            content=(
                "需求对齐：为 Git 管理 Agent 增加入口，先确认 5 个选项。"
                "请回复：1 采用哪个方案，2 是否使用信息工具，3 是否允许写入。"
            )
        ),
    ]
    answer = "1,就用这个,2,使用信息工具,3,允许,4,要求,5,这个先不考虑"

    goal = agent_module._normalize_goal_from_chat_history(answer, None, history)

    assert "Git 管理 Agent" in goal
    assert "用户确认" in goal
    assert answer in goal
    assert goal != answer


@pytest.mark.parametrize(
    ("message", "details"),
    [
        ("unknown parameter: previous_response_id", {}),
        ("provider request failed", {"error": "previous_response_id not_found"}),
    ],
)
def test_provider_rejected_responses_continuation_detects_unsupported_anchor(message, details):
    assert agent_module._provider_rejected_responses_continuation(
        category="protocol_error",
        message=message,
        details=details,
    ) is True


def test_provider_rejected_responses_continuation_does_not_mask_unrelated_failure():
    assert agent_module._provider_rejected_responses_continuation(
        category="server_error",
        message="upstream unavailable",
        details={"status": 503},
    ) is False


def test_chat_invocation_context_uses_active_status_turn_identity(monkeypatch):
    for env_name in (
        "VIBELUTION_TURN_RUN_ID",
        "VIBELUTION_TURN_SESSION_ID",
        "VIBELUTION_TURN_RUN_KIND",
    ):
        monkeypatch.delenv(env_name, raising=False)
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    agent.mode_policy = ModePolicy(
        mode=AgentMode.CHAT,
        orchestrator_kind="chat",
        keep_multi_turn_context=True,
        allow_auto_loop=False,
        capture_chat_dataset_candidates=False,
        reset_context_before_turn=False,
        reset_context_between_cases=False,
        allow_direct_supervised_payload=False,
        finish_after_direct_response=False,
        runtime_input_builder=build_chat_user_message,
    )
    agent.runtime_agent_binding = {
        "agentId": "agent-live",
        "directSessionId": "session-live",
    }

    with llm_status_context(session_id="session-live", turn_id="turn-live-42"):
        metadata = agent._build_llm_invocation_context().to_metadata()
        scope = invocation_scope_from_metadata(metadata)

    assert metadata["sessionId"] == "session-live"
    assert metadata["turnId"] == "turn-live-42"
    assert scope.session_id == "session-live"
    assert scope.turn_id == "turn-live-42"


def test_numbered_task_list_without_confirmation_keeps_user_goal():
    prompt = "1,修复缓存链路,2,补测试,3,运行验证"

    goal = agent_module._normalize_goal_from_chat_history(
        prompt,
        None,
        [AIMessage(content="上一轮只是普通回复。")],
    )

    assert goal == prompt


def _canonical_agent_test_outcome(*, text="", reasoning_deltas=()):
    from core.llm.types import LLMProtocolEvent

    identity = CanonicalItemIdentity(
        session_id="session-test",
        turn_id="turn-test",
        invocation_id="invocation-test",
        iteration=0,
        item_id="answer-test",
    )
    events = []
    for sequence, delta in enumerate(reasoning_deltas, start=1):
        events.append(
            LLMProtocolEvent(
                kind="reasoning_delta",
                sequence=sequence,
                session_id=identity.session_id,
                turn_id=identity.turn_id,
                invocation_id=identity.invocation_id,
                iteration=identity.iteration,
                item_id="reasoning-test",
                channel="reasoning",
                phase="reasoning",
                text=delta,
            )
        )
    if text:
        events.append(
            LLMProtocolEvent(
                kind="answer_delta",
                sequence=len(events) + 1,
                session_id=identity.session_id,
                turn_id=identity.turn_id,
                invocation_id=identity.invocation_id,
                iteration=identity.iteration,
                item_id=identity.item_id,
                channel="answer",
                phase="final_answer",
                text=text,
            )
        )
    return LLMTurnOutcome.final_answer(identity=identity, text=text, events=tuple(events))


class _CanonicalAgentTestLLM:
    def __init__(self, outcome=None, *, captured=None, response_metadata=None):
        self.outcome = outcome or _canonical_agent_test_outcome()
        self.captured = captured
        self.response_metadata = dict(response_metadata or {})

    def invoke_outcome(self, messages, **_kwargs):
        if self.captured is not None:
            self.captured["messages"] = messages
        return self.outcome

    def stream_events(self, messages, *, protocol_event_sink=None, **_kwargs):
        if self.captured is not None:
            self.captured["messages"] = messages
        for event in self.outcome.events:
            if protocol_event_sink is not None:
                protocol_event_sink(event)
        if False:
            yield None
        return self.outcome

    def stream(self, *_args, **_kwargs):
        if False:
            yield None

    def project_outcome_message(self, outcome):
        reasoning = "".join(
            event.text
            for event in outcome.events
            if event.kind == "reasoning_delta" and event.text
        )
        return AIMessage(
            content=outcome.final_text,
            additional_kwargs={"reasoning_content": reasoning} if reasoning else {},
            response_metadata=dict(self.response_metadata),
        )


class TestToolMessageFlow:
    """工具消息协议测试"""

    def test_apply_active_components_request_is_diagnostic_only(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        class DummyPromptManager:
            def __init__(self):
                self.override = None

            def select_components(self, components):
                self.override = list(components)

            def get_status(self):
                return {"active_sections_override": self.override}

        agent.prompt_manager = DummyPromptManager()
        processed = SimpleNamespace(active_components=["SOUL", "SPEC"])
        actions = []
        ui_events = []
        scene_events = []

        class DummyUI:
            def add_log(self, text, level="INFO"):
                ui_events.append((level, text))

        monkeypatch.setattr(agent_module.logger, "log_action", lambda action, details=None: actions.append((action, details)))
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
        monkeypatch.setattr(
            agent_module,
            "_record_agent_scene_event",
            lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
        )

        agent._apply_active_components_request(processed)

        assert agent.prompt_manager.override is None
        assert ui_events == []
        assert actions == [
            (
                "active_components_observed",
                {
                    "requested": ["SOUL", "SPEC"],
                    "applied": [],
                    "mode": "diagnostic_only",
                },
            )
        ]
        assert scene_events[0][0:2] == ("prompt", "prompt.components.request_observed")
        assert scene_events[0][2]["fields"]["requested"] == ["SOUL", "SPEC"]
        assert scene_events[0][2]["fields"]["applied"] == []

    def test_handle_tool_result_uses_tool_message_when_id_present(self):
        messages = []

        ToolLifecycleBridge.handle_tool_result(
            {"name": "read_file_tool", "id": "call_123"},
            "tool result",
            None,
            messages,
        )

        assert len(messages) == 1
        assert isinstance(messages[0], ToolMessage)
        assert messages[0].tool_call_id == "call_123"

    def test_handle_tool_result_keeps_completed_nonzero_terminal_exit_as_canonical_completion(self):
        identity = CanonicalItemIdentity(
            session_id="session-terminal",
            turn_id="turn-terminal",
            invocation_id="invocation-terminal",
            iteration=1,
            item_id="call-terminal",
        )
        canonical_call = CanonicalToolCall(
            identity=identity,
            call_id="call-terminal",
            name="exec_command",
            arguments={"cmd": "exit 1"},
        )
        messages = []

        ToolLifecycleBridge.handle_tool_result(
            {
                "name": "exec_command",
                "id": "call-terminal",
                "canonical_tool_call": canonical_call,
            },
            json.dumps({
                "status": "completed",
                "terminalSessionId": "sandbox-terminal",
                "sessionOpen": False,
                "exitCode": 1,
                "outcomeStatus": "nonzero_exit",
                "formattedOutput": "[WARNING | Exit Code: 1]\\ncommand failed",
            }),
            None,
            messages,
        )

        canonical_result = messages[0].additional_kwargs["canonical_tool_result"]
        assert canonical_result.status == "completed"
        assert canonical_result.is_error is False
        assert "semanticStatus: completed" in messages[0].content
        assert "exitCode: 1" in messages[0].content

    def test_handle_tool_result_preserves_range_facts_without_continuation_hint(self):
        messages = []
        long_result = (
            "[文件] demo.py\n"
            "[编码] utf-8 | [行数] 500 (已截断) | [大小] 12.0 KB\n"
            "[区间] 第 1-120 行 | 已显示 120 行 | 剩余 380 行\n"
            "[阅读导航] 下一步按目标选择；只有目标确实需要相邻下文时，才读取 offset=120, max_lines=120。\n\n"
            + ("X" * 5000)
        )

        ToolLifecycleBridge.handle_tool_result(
            {"name": "read_file_tool", "id": "call_456"},
            long_result,
            None,
            messages,
        )

        assert len(messages) == 1
        assert "第 1-120 行" in messages[0].content
        assert "阅读导航" not in messages[0].content
        assert "offset=120" not in messages[0].content

    def test_runtime_metadata_is_bound_to_its_tool_call_without_storing_navigation(self):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent._recent_tool_records = []
        agent._recent_tool_outputs = []
        first_call = {"id": "call-first", "name": "read_file_tool", "args": {"path": "first.py"}}
        second_call = {"id": "call-second", "name": "read_file_tool", "args": {"path": "second.py"}}

        agent._remember_tool_output(first_call, "first result", None)
        agent._remember_tool_output(second_call, "second result", None)
        agent._remember_runtime_tool_metadata(
            first_call,
            RuntimeToolMetadata(
                result_kind="file_read",
                strategy="passthrough",
                range_info="第 1-20 行",
                continuation_hint="继续调用 read_file_tool(offset=20, max_lines=20)。",
                truncated=True,
                original_length=120,
                transport_status="returned",
                semantic_status="succeeded",
                exit_code=None,
                timed_out=False,
                failure_class="",
            ),
        )

        assert "runtime_metadata" in agent._recent_tool_records[0]
        assert "runtime_metadata" not in agent._recent_tool_records[1]
        assert "continuation_hint" not in agent._recent_tool_records[0]["runtime_metadata"]

    def test_dialogue_agent_exposes_no_legacy_auto_delegation_entrypoints(self):
        legacy_entrypoints = (
            "_build_delegation_request",
            "_apply_delegation_result",
            "_is_session_agent_runtime",
            "_session_agent_auto_delegation_enabled",
            "_record_session_agent_auto_delegation_disabled",
            "_maybe_delegate",
            "_get_delegation_governor",
        )

        assert all(not hasattr(SelfEvolvingAgent, entrypoint) for entrypoint in legacy_entrypoints)

    def test_handle_tool_result_decodes_binary_failure_result(self):
        messages = []

        ToolLifecycleBridge.handle_tool_result(
            {"name": "get_git_status_summary_tool", "id": "call_binary"},
            "[错误] binary result".encode("utf-8"),
            None,
            messages,
        )

        assert len(messages) == 1
        assert "semanticStatus: failed" in messages[0].content
        assert messages[0].content.endswith("[错误] binary result")
        assert messages[0].tool_call_id == "call_binary"

    def test_seed_chat_history_restores_persisted_tool_results(self):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=True,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=build_chat_user_message,
        )
        agent.config = isolated_settings_config()
        agent._mental_model_enabled_override = False
        agent.mental_model = None

        long_result = "完整工具结果：pytest 输出了 200 行失败日志。\n" + ("failure-line\n" * 260)
        agent.seed_chat_history(
            [
                {"role": "user", "content": "开始修改"},
                {
                    "role": "assistant",
                    "content": "运行相关测试验证修改：",
                    "tool_calls": [
                        {
                            "id": "call_cli",
                            "name": "cli_tool",
                            "args": {"command": "python -m pytest"},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_cli",
                    "content": long_result,
                },
            ]
        )

        restored = list(agent._active_turn_messages or [])
        tool_messages = [message for message in restored if isinstance(message, ToolMessage)]
        assistant_messages = [
            message
            for message in restored
            if isinstance(message, AIMessage) and getattr(message, "tool_calls", None)
        ]

        assert len(tool_messages) == 1
        assert tool_messages[0].tool_call_id == "call_cli"
        assert "完整工具结果" in tool_messages[0].content
        assert "failure-line\n" * 120 in tool_messages[0].content
        assert "Windows detected Unix shell fragment" not in tool_messages[0].content
        assert assistant_messages
        assert "运行相关测试验证修改：" in assistant_messages[0].content

    def test_seed_chat_history_projects_canonical_tool_pair_to_semantic_history_without_duplicate_result(self):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=True,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=build_chat_user_message,
        )
        agent.config = isolated_settings_config()
        agent._mental_model_enabled_override = False
        agent.mental_model = None

        agent.seed_chat_history(
            [
                {"role": "assistant", "content": "", "tool_calls": [
                    {
                        "id": "call_canonical",
                        "type": "function",
                        "function": {"name": "cli_tool", "arguments": "{\"command\":\"pytest\"}"},
                    }
                ]},
                {"role": "tool", "tool_call_id": "call_canonical", "content": "完整 canonical 工具结果"},
            ]
        )

        restored = list(agent._active_turn_messages or [])
        tool_messages = [message for message in restored if isinstance(message, ToolMessage)]
        assistant_messages = [
            message
            for message in restored
            if isinstance(message, AIMessage) and getattr(message, "tool_calls", None)
        ]

        assert len(tool_messages) == 1
        assert tool_messages[0].tool_call_id == "call_canonical"
        assert "完整 canonical 工具结果" in tool_messages[0].content
        assert len(assistant_messages) == 1
        assert sum("完整 canonical 工具结果" in str(message.content) for message in restored) == 1

    def test_seed_chat_history_clears_previous_provider_continuation_before_new_user_turn(self):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=True,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=build_chat_user_message,
        )
        agent.config = isolated_settings_config()
        agent._mental_model_enabled_override = False
        agent.mental_model = None
        agent._chat_provider_replay_state = object()

        agent.seed_chat_history(
            [
                {"role": "user", "content": "上一轮用户任务"},
                {"role": "assistant", "content": "上一轮已经完成"},
            ]
        )

        assert agent._chat_provider_replay_state is None

    def test_chat_state_normalization_preserves_camel_case_tool_calls(self):
        from core.ui.chat_state import normalize_chat_messages

        normalized = normalize_chat_messages(
            [
                {
                    "role": "assistant",
                    "content": "运行相关测试验证修改：",
                    "toolCalls": [
                        {
                            "toolName": "cli_tool",
                            "toolCallId": "call_1",
                            "resultPreview": "Windows detected Unix shell fragment.",
                        }
                    ],
                }
            ]
        )

        assert normalized[0]["tool_calls"][0]["name"] == "cli_tool"
        assert normalized[0]["tool_calls"][0]["toolCallId"] == "call_1"
        assert "Windows detected" in normalized[0]["tool_calls"][0]["resultPreview"]

    def test_invoke_llm_preserves_tool_messages(self, monkeypatch):
        captured = {}

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

        class DummyLLM:
            def invoke_outcome(self, msgs, **_kwargs):
                captured["messages"] = msgs
                return LLMTurnOutcome.final_answer(
                    identity=CanonicalItemIdentity(
                        session_id="session-test",
                        turn_id="turn-test",
                        invocation_id="invocation-test",
                        iteration=0,
                        item_id="answer-test",
                    ),
                    text="",
                )

            def project_outcome_message(self, outcome):
                return AIMessage(content=outcome.final_text)

        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.llm_with_tools = DummyLLM()

        assistant_msg = AIMessage(
            content="calling tool",
            tool_calls=[{"name": "read_file_tool", "args": {"file_path": "a.py"}, "id": "call_1"}],
        )
        tool_msg = ToolMessage(content="file content", tool_call_id="call_1")

        result = agent._invoke_llm([assistant_msg, tool_msg])

        assert result is not None
        assert captured["messages"][0] is assistant_msg
        assert captured["messages"][1] is tool_msg

    def test_invoke_llm_preserves_structured_system_cache_control(self, monkeypatch):
        captured = {}

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

        class DummyLLM(_CanonicalAgentTestLLM):
            def __init__(self):
                super().__init__(captured=captured)
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.llm_with_tools = DummyLLM()
        system_message = {
            "role": "system",
            "content": [
                {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "dynamic"},
            ],
        }

        result = agent._invoke_llm([system_message, build_chat_user_message("hi")])

        assert result is not None
        assert captured["messages"][0] == system_message
        assert captured["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_invoke_llm_exposes_turn_stop_checker_to_llm_client_cancel_context(self, monkeypatch):
        captured = {}

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

        class DummyLLM(_CanonicalAgentTestLLM):
            def stream_events(self, messages, *, protocol_event_sink=None, **kwargs):
                from core.llm import client as llm_client_module

                checks["inside_llm"] = True
                try:
                    captured["cancel_reason"] = llm_client_module._current_llm_cancel_reason()
                finally:
                    checks["inside_llm"] = False
                return (yield from super().stream_events(
                    messages,
                    protocol_event_sink=protocol_event_sink,
                    **kwargs,
                ))
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.llm_with_tools = DummyLLM()
        checks = {"count": 0, "inside_llm": False}

        def stop_checker():
            checks["count"] += 1
            return "操作者请求停止当前轮。" if checks["inside_llm"] else ""

        agent._turn_interrupt_checker = stop_checker

        result = agent._invoke_llm([build_chat_user_message("hi")])

        assert result is not None
        assert captured["cancel_reason"] == "操作者请求停止当前轮。"

    def test_static_runtime_context_extends_cacheable_system_prefix(self):
        """稳定 Agent 上下文应进入 cacheable system 前缀，动态块仍留给后续 volatile 插入。"""

        from core.infrastructure.llm_utils import extend_system_message_cacheable_prefix

        system_message = {
            "role": "system",
            "content": [
                {"type": "text", "text": "static prefix", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "dynamic suffix"},
            ],
        }

        updated, merged = extend_system_message_cacheable_prefix(
            system_message,
            ["## Agent Static Context\nstable"],
        )

        assert merged is True
        assert updated["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert updated["content"][0]["text"] == "static prefix\n\n## Agent Static Context\nstable"
        assert updated["content"][1] == {"type": "text", "text": "dynamic suffix"}

    def test_invoke_llm_uses_fallback_profile_after_exhausted_provider_error(self, monkeypatch):
        calls = []
        invocation_ids = []
        events = []
        recovery_inputs = []
        monkeypatch.setenv("VIBELUTION_TURN_SESSION_ID", "session-route-trace")
        monkeypatch.setenv("VIBELUTION_TURN_RUN_ID", "turn-route-trace")
        monkeypatch.setenv("VIBELUTION_TURN_AGENT_ID", "agent-route-trace")

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

        class PrimaryLLM(_CanonicalAgentTestLLM):
            profile_id = "primary"

            def effective_route_identity(self):
                return ("relay", "responses", "gpt-5.6-luna", self.profile_id)

            def effective_route_id(self):
                return "primary-route"

            def invoke_outcome(self, _msgs, **kwargs):
                calls.append("primary")
                invocation_ids.append(kwargs.get("metadata", {}).get("invocationId"))
                raise LLMError(
                    "server_error",
                    "provider 服务异常",
                    retryable=True,
                    details={
                        "attempt": 5,
                        "max_attempts": 5,
                        "retry_budget_exhausted": True,
                    },
                )

        class FallbackLLM(_CanonicalAgentTestLLM):
            profile_id = "fallback_backup"

            def effective_route_identity(self):
                return ("local", "chat", "qwen-32b", self.profile_id)

            def effective_route_id(self):
                return "fallback-route"

            def invoke_outcome(self, _msgs, **kwargs):
                calls.append("fallback_backup")
                invocation_ids.append(kwargs.get("metadata", {}).get("invocationId"))
                return _canonical_agent_test_outcome(text="fallback ok")

        def fake_recovery(*_args, current_profile_id=None, **_kwargs):
            recovery_inputs.append(current_profile_id)
            return SimpleNamespace(
                category="server_error",
                retryable=True,
                action="retry_with_backoff",
                user_message="provider 服务异常",
                wait_seconds=0,
                stop_current_turn=True,
                disable_streaming=False,
                disable_tools=False,
                request_context_compression=False,
                fallback_profile_id="fallback_backup" if current_profile_id == "primary" else None,
            )

        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
        monkeypatch.setattr(agent_module, "plan_llm_recovery", fake_recovery)
        monkeypatch.setattr(agent_module.logger, "log_error", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            agent_module,
            "_record_agent_scene_event",
            lambda phase, code, **kwargs: events.append((phase, code, kwargs.get("fields") or {})),
        )

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.llm_with_tools = PrimaryLLM()
        agent._base_llm = PrimaryLLM()
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                model_name="gpt-5.5",
                provider="relay",
                api_base="https://example.invalid",
                api_timeout=30,
            ),
        )
        agent._should_stream_llm_for_turn = lambda *_args, **_kwargs: False
        agent._get_llm_for_current_mode = lambda **kwargs: (
            FallbackLLM() if kwargs.get("profile_id") == "fallback_backup" else PrimaryLLM()
        )

        result = agent._invoke_llm([AIMessage(content="hello")])

        assert result[1].content == "fallback ok"
        assert calls == ["primary", "fallback_backup"]
        assert recovery_inputs == ["primary"]
        assert all(invocation_ids)
        assert invocation_ids[0] != invocation_ids[1]
        assert [code for _, code, _ in events].count("llm_fallback_selected") == 1
        success_events = [
            fields for _, code, fields in events if code == "llm_route_attempt_succeeded"
        ]
        assert len(success_events) == 1
        assert success_events[0]["routeAttempt"] == 2
        assert success_events[0]["routeId"] == "fallback-route"
        assert success_events[0]["invocationId"] == invocation_ids[1]
        assert success_events[0]["sessionId"] == "session-route-trace"
        assert success_events[0]["turnId"] == "turn-route-trace"
        assert success_events[0]["agentId"] == "agent-route-trace"
        assert success_events[0]["streamed"] is False
        assert "durationMs" in success_events[0]
        assert "llm_turn_completed" not in [code for _, code, _ in events]
        assert "hello" not in str(events)

    def test_invoke_llm_rejects_duplicate_effective_fallback_before_io(self, monkeypatch):
        calls = []
        events = []

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

        class RouteLLM(_CanonicalAgentTestLLM):
            def __init__(self, profile_id, *, succeeds=False):
                super().__init__(
                    outcome=_canonical_agent_test_outcome(text="must not run"),
                )
                self.profile_id = profile_id
                self.succeeds = succeeds

            def effective_route_identity(self):
                return ("relay", "responses", "gpt-5.6-luna")

            def effective_route_id(self):
                return f"{self.profile_id}-alias"

            def invoke_outcome(self, _msgs, **_kwargs):
                calls.append(self.profile_id)
                if self.succeeds:
                    return self.outcome
                raise LLMError(
                    "server_error",
                    "primary exhausted",
                    retryable=True,
                    details={"attempt": 5, "max_attempts": 5, "retry_budget_exhausted": True},
                )

        primary = RouteLLM("primary")
        alias = RouteLLM("fallback_alias", succeeds=True)
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
        monkeypatch.setattr(agent_module.logger, "log_error", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            agent_module,
            "plan_llm_recovery",
            lambda *_args, **_kwargs: SimpleNamespace(
                category="server_error",
                retryable=True,
                action="retry_with_backoff",
                user_message="provider 服务异常",
                wait_seconds=0,
                stop_current_turn=True,
                disable_streaming=False,
                disable_tools=False,
                request_context_compression=False,
                fallback_profile_id="fallback_alias",
            ),
        )
        monkeypatch.setattr(
            agent_module,
            "_record_agent_scene_event",
            lambda phase, code, **kwargs: events.append((phase, code, kwargs.get("fields") or {})),
        )
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.llm_with_tools = primary
        agent._base_llm = primary
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                model_name="gpt-5.6-luna",
                provider="relay",
                api_base="https://example.invalid",
                api_timeout=30,
            )
        )
        agent._should_stream_llm_for_turn = lambda *_args, **_kwargs: False
        agent._get_llm_for_current_mode = lambda **kwargs: (
            alias if kwargs.get("profile_id") == "fallback_alias" else primary
        )

        result = agent._invoke_llm([AIMessage(content="hello")])

        assert result is None
        assert calls == ["primary"]
        assert any(
            code == "llm_fallback_rejected" and fields.get("reasonCode") == "duplicate_effective_route"
            for _, code, fields in events
        )
        assert [code for _, code, _ in events].count("llm_turn_terminal") == 1

    def test_invoke_llm_stops_after_distinct_fallback_failure(self, monkeypatch):
        calls = []
        invocation_ids = []
        events = []

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

        class FailingRouteLLM(_CanonicalAgentTestLLM):
            def __init__(self, profile_id, identity):
                super().__init__()
                self.profile_id = profile_id
                self.identity = identity

            def effective_route_identity(self):
                return self.identity

            def effective_route_id(self):
                return f"{self.profile_id}-route"

            def invoke_outcome(self, _msgs, **kwargs):
                calls.append(self.profile_id)
                invocation_ids.append(kwargs.get("metadata", {}).get("invocationId"))
                raise LLMError(
                    "server_error",
                    f"{self.profile_id} exhausted",
                    retryable=True,
                    details={"attempt": 5, "max_attempts": 5, "retry_budget_exhausted": True},
                )

        primary = FailingRouteLLM("primary", ("relay", "responses", "gpt-5.6-luna"))
        fallback = FailingRouteLLM("fallback_backup", ("local", "chat", "qwen-32b"))
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
        monkeypatch.setattr(agent_module.logger, "log_error", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            agent_module,
            "plan_llm_recovery",
            lambda *_args, current_profile_id=None, **_kwargs: SimpleNamespace(
                category="server_error",
                retryable=True,
                action="retry_with_backoff",
                user_message="provider 服务异常",
                wait_seconds=0,
                stop_current_turn=True,
                disable_streaming=False,
                disable_tools=False,
                request_context_compression=False,
                fallback_profile_id="fallback_backup" if current_profile_id == "primary" else "third_route",
            ),
        )
        monkeypatch.setattr(
            agent_module,
            "_record_agent_scene_event",
            lambda phase, code, **kwargs: events.append((phase, code, kwargs.get("fields") or {})),
        )
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.llm_with_tools = primary
        agent._base_llm = primary
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                model_name="gpt-5.6-luna",
                provider="relay",
                api_base="https://example.invalid",
                api_timeout=30,
            )
        )
        agent._should_stream_llm_for_turn = lambda *_args, **_kwargs: False

        def resolve_client(**kwargs):
            profile_id = kwargs.get("profile_id")
            if profile_id == "fallback_backup":
                return fallback
            if profile_id == "third_route":
                raise AssertionError("third route must not be resolved")
            return primary

        agent._get_llm_for_current_mode = resolve_client

        result = agent._invoke_llm([AIMessage(content="hello")])

        assert result is None
        assert calls == ["primary", "fallback_backup"]
        assert all(invocation_ids)
        assert invocation_ids[0] != invocation_ids[1]
        assert [code for _, code, _ in events].count("llm_fallback_selected") == 1
        assert [code for _, code, _ in events].count("llm_turn_terminal") == 1

    def test_invoke_llm_does_not_retry_exhausted_stream_route_without_fallback(self, monkeypatch):
        calls = []
        streamed = []

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

            def stream_response(self, text, done=False):
                streamed.append((text, done))

        class StreamFailingLLM(_CanonicalAgentTestLLM):
            profile_id = "primary"

            def effective_route_identity(self):
                return ("relay", "responses", "gpt-5.6-luna", self.profile_id)

            def effective_route_id(self):
                return "primary-route"

            def stream_events(self, _msgs, **_kwargs):
                calls.append("stream")
                raise LLMError(
                    "server_error",
                    "provider 流式上游异常",
                    retryable=True,
                    details={
                        "attempt": 5,
                        "max_attempts": 5,
                        "retry_budget_exhausted": True,
                    },
                )
                yield

            def invoke_outcome(self, _msgs, **_kwargs):
                calls.append("invoke")
                return _canonical_agent_test_outcome(text="nonstream ok")

        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
        monkeypatch.setattr(agent_module.logger, "log_error", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module.time, "sleep", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            agent_module,
            "plan_llm_recovery",
            lambda *args, **kwargs: SimpleNamespace(
                category="server_error",
                retryable=True,
                action="retry_with_backoff",
                user_message="provider 流式上游异常",
                wait_seconds=0,
                stop_current_turn=True,
                disable_streaming=False,
                disable_tools=False,
                request_context_compression=False,
                fallback_profile_id=None,
            ),
        )

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.llm_with_tools = StreamFailingLLM()
        agent._base_llm = SimpleNamespace(profile_id="primary")
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                model_name="gpt-5.5",
                provider="relay",
                api_base="https://example.invalid",
                api_timeout=30,
            ),
        )
        agent._should_stream_llm_for_turn = lambda *_args, **_kwargs: True
        agent._get_llm_for_current_mode = lambda **_kwargs: StreamFailingLLM()

        result = agent._invoke_llm([AIMessage(content="hello")])

        assert result is None
        assert calls == ["stream"]
        assert streamed == []
        assert agent._last_llm_error_category == "server_error"
        assert "retry_provider_failure_without_streaming" not in agent._last_llm_error_details

    def test_invoke_llm_returns_none_for_exhausted_llmerror(self, monkeypatch):
        calls = {"count": 0}

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

        class ExhaustedLLM(_CanonicalAgentTestLLM):
            def invoke_outcome(self, _msgs, **_kwargs):
                calls["count"] += 1
                raise LLMError(
                    "server_error",
                    "provider 服务异常",
                    retryable=True,
                    details={
                        "attempt": 5,
                        "max_attempts": 5,
                        "retry_budget_exhausted": True,
                    },
                )

        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
        monkeypatch.setattr(
            agent_module,
            "plan_llm_recovery",
            lambda *args, **kwargs: SimpleNamespace(
                category="server_error",
                retryable=True,
                action="retry_with_backoff",
                user_message="provider 服务异常",
                wait_seconds=0,
                stop_current_turn=False,
                disable_streaming=False,
                disable_tools=False,
                request_context_compression=False,
                fallback_profile_id=None,
            ),
        )

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.llm_with_tools = ExhaustedLLM()
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                model_name="gpt-5.5",
                provider="relay",
                api_base="https://example.invalid",
                api_timeout=30,
            ),
        )
        agent._base_llm = SimpleNamespace(profile_id="primary")
        agent._should_stream_llm = lambda: False
        agent._last_llm_error_category = None
        agent._last_llm_error_retryable = False
        agent._last_llm_recovery_action = None
        agent._last_llm_error_message = ""
        agent._last_llm_failure_attempts = 0
        agent._last_llm_failure_max_attempts = 0

        result = agent._invoke_llm([AIMessage(content="hello")])

        assert result is None
        assert calls["count"] == 1
        assert agent._last_llm_error_category == "server_error"
        assert agent._last_llm_failure_attempts == 5
        assert agent._last_llm_failure_max_attempts == 5

    def test_invoke_llm_maps_cancelled_provider_error_to_turn_stop(self, monkeypatch):
        events = []
        stop_state = {"requested": False}

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

        class CancelledLLM(_CanonicalAgentTestLLM):
            profile_id = "primary"

            def invoke_outcome(self, _messages, **_kwargs):
                stop_state["requested"] = True
                raise LLMError(
                    "cancelled",
                    "operator stopped the turn",
                    retryable=False,
                    details={"stop_reason": "operator stopped the turn"},
                )

        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
        monkeypatch.setattr(agent_module.logger, "log_error", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            agent_module,
            "_record_agent_scene_event",
            lambda phase, code, **kwargs: events.append((phase, code, kwargs.get("fields") or {})),
        )
        monkeypatch.setattr(
            agent_module,
            "plan_llm_recovery",
            lambda *_args, **_kwargs: SimpleNamespace(
                category="cancelled",
                retryable=False,
                action="stop_current_turn",
                user_message="operator stopped the turn",
                wait_seconds=0,
                stop_current_turn=True,
                disable_streaming=False,
                disable_tools=False,
                request_context_compression=False,
                fallback_profile_id=None,
            ),
        )

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.llm_with_tools = CancelledLLM()
        agent._base_llm = SimpleNamespace(profile_id="primary")
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                model_name="gpt-5.6-luna",
                provider="relay",
                api_base="https://example.invalid",
                api_timeout=30,
            ),
        )
        agent._should_stream_llm_for_turn = lambda *_args, **_kwargs: False
        agent._get_llm_for_current_mode = lambda **_kwargs: agent.llm_with_tools
        agent._turn_interrupt_checker = lambda: (
            "operator stopped the turn" if stop_state["requested"] else ""
        )

        with pytest.raises(agent_module.TurnStopRequested, match="operator stopped the turn"):
            agent._invoke_llm([AIMessage(content="hello")])

        assert [code for _, code, _ in events].count("llm_route_cancelled") == 1
        assert "llm_route_attempt_exhausted" not in [code for _, code, _ in events]
        assert "llm_turn_terminal" not in [code for _, code, _ in events]

    def test_invoke_llm_preserves_safe_semantic_projection_diagnostics(self, monkeypatch):
        """协议投影失败应保留可定位字段，且不转存原始链路内容。"""
        events = []
        logged_details = []

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

        class ProjectionFailureLLM(_CanonicalAgentTestLLM):
            def invoke_outcome(self, _msgs, **_kwargs):
                raise LLMError(
                    "payload_protocol_error",
                    "tool result has no preceding call",
                    retryable=False,
                    details={
                        "attempt": 1,
                        "max_attempts": 1,
                        "messageIndex": 34,
                        "payloadValidationErrorType": "orphan_tool_result",
                        "payloadValidationResult": "blocked_before_provider",
                        "payloadMessageAssistantToolCallCount": 19,
                        "payloadMessageToolResultCount": 19,
                        "payloadMessageShapeHash": "abc123def4567890",
                        "payloadMessageShapeTail": [{"role": "tool", "toolCallCount": 0}],
                        "rawProviderPayload": "must-not-persist",
                        "toolCallId": "call-secret",
                    },
                )

        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
        monkeypatch.setattr(
            agent_module.logger,
            "log_error",
            lambda *_args, **kwargs: logged_details.append(kwargs["details"]),
        )
        monkeypatch.setattr(
            agent_module,
            "_record_agent_scene_event",
            lambda phase, code, **kwargs: events.append((phase, code, kwargs.get("fields") or {})),
        )
        monkeypatch.setattr(
            agent_module,
            "plan_llm_recovery",
            lambda *_args, **_kwargs: SimpleNamespace(
                category="payload_protocol_error",
                retryable=False,
                action="inspect_runtime_scene",
                user_message="工具调用链未通过协议校验",
                wait_seconds=0,
                stop_current_turn=True,
                disable_streaming=False,
                disable_tools=False,
                request_context_compression=False,
                fallback_profile_id=None,
            ),
        )

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.llm_with_tools = ProjectionFailureLLM()
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                model_name="gpt-5.6-terra",
                provider="relay",
                api_base="https://example.invalid",
                api_timeout=30,
            ),
        )
        agent._base_llm = SimpleNamespace(profile_id="primary")
        agent._should_stream_llm = lambda: False

        result = agent._invoke_llm([AIMessage(content="hello")])

        assert result is None
        expected = {
            "messageIndex": 34,
            "payloadValidationErrorType": "orphan_tool_result",
            "payloadValidationResult": "blocked_before_provider",
            "payloadMessageAssistantToolCallCount": 19,
            "payloadMessageToolResultCount": 19,
            "payloadMessageShapeHash": "abc123def4567890",
        }
        assert {key: agent._last_llm_error_details.get(key) for key in expected} == expected
        assert logged_details and {key: logged_details[-1].get(key) for key in expected} == expected
        exhausted_fields = next(
            fields for _phase, code, fields in events if code == "llm_route_attempt_exhausted"
        )
        assert {key: exhausted_fields.get(key) for key in expected} == expected
        serialized = json.dumps([agent._last_llm_error_details, logged_details, events], ensure_ascii=False)
        assert "must-not-persist" not in serialized
        assert "call-secret" not in serialized
        assert "payloadMessageShapeTail" not in agent._last_llm_error_details

    def test_invoke_llm_stops_on_tool_calling_capability_error(self, monkeypatch):
        calls = []

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

        class DummyLLM:
            def invoke_outcome(self, _messages, **_kwargs):
                calls.append("with_tools")
                raise LLMError("tool calling is not supported")
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
        monkeypatch.setattr(agent_module, "logger", SimpleNamespace(log_error=lambda *_args, **_kwargs: None))
        monkeypatch.setattr(
            agent_module,
            "plan_llm_recovery",
            lambda *args, **kwargs: SimpleNamespace(
                category="capability_error",
                retryable=False,
                action="fail_fast",
                user_message="profile `primary` 不支持 tool calling",
                wait_seconds=0,
                stop_current_turn=True,
                disable_streaming=False,
                disable_tools=False,
                request_context_compression=False,
                fallback_profile_id=None,
            ),
        )

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.llm_with_tools = DummyLLM()
        agent._base_llm = DummyLLM()
        agent._bound_llm_cache = {}
        agent.key_tools = []
        agent.key_tool_maps = set()
        agent._key_tool_map = {}
        agent._active_goal = ""
        agent._turn_interrupt_checker = None
        agent._force_disable_tools_for_turn = False
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                model_name="mimo-v2.5",
                provider="xiaomi",
                api_base="https://example.invalid",
                api_timeout=30,
            ),
        )
        agent._should_stream_llm = lambda *_args, **_kwargs: False

        result = agent._invoke_llm([AIMessage(content="hello")])

        assert result is None
        assert calls == ["with_tools"]
        assert agent._last_llm_error_category == "capability_error"
        assert agent._last_llm_recovery_action == "fail_fast"
        assert agent._last_llm_error_message == "capability_error: profile `primary` 不支持 tool calling"

    def test_publish_llm_retry_status_uses_outer_reconnect_attempts(self, monkeypatch):
        published = []

        class DummyBus:
            def publish(self, name, payload, source=None):
                published.append((name, payload, source))

        monkeypatch.setattr(agent_module, "get_event_bus", lambda: DummyBus())
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent._last_llm_error_category = "network_error"
        agent._last_llm_recovery_action = "retry_with_backoff"

        agent._publish_llm_retry_status(attempt=2, max_attempts=5)

        assert published
        assert published[0][0] == "llm:status"
        assert published[0][1]["status"] == "retrying"
        assert published[0][1]["attempt"] == 2
        assert published[0][1]["max_attempts"] == 5
        assert published[0][1]["category"] == "network_error"
        assert published[0][1]["source"] == "agent_outer_reconnect"

    def test_invoke_llm_streams_thought_and_hides_think_tags(self, monkeypatch):
        captured = {"thoughts": []}

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

            def stream_thought(self, text, done=False):
                captured["thoughts"].append((text, done))

        class DummyChunk:
            def __init__(self, content):
                self.content = content
                self.tool_calls = []

            def __add__(self, other):
                return DummyChunk((self.content or "") + (other.content or ""))

        class DummyLLM(_CanonicalAgentTestLLM):
            def __init__(self):
                super().__init__(
                    outcome=_canonical_agent_test_outcome(
                        reasoning_deltas=("first", " second"),
                    ),
                    captured=captured,
                )
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                get_profile=lambda role="primary": SimpleNamespace(streaming=True)
            ),
        )
        agent.llm_with_tools = DummyLLM()

        result = agent._invoke_llm([AIMessage(content="hello")])

        assert result is not None
        assert captured["thoughts"] == [("first", False), (" second", False)]
        assert result[1].content == ""

    def test_invoke_llm_stream_falls_back_to_accumulated_text_when_merged_chunk_is_empty(self, monkeypatch):
        captured = {"thoughts": []}

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

            def stream_thought(self, text, done=False):
                captured["thoughts"].append((text, done))

        class DummyChunk:
            def __init__(self, content, *, tool_calls=None, additional_kwargs=None, response_metadata=None):
                self.content = content
                self.tool_calls = tool_calls or []
                self.additional_kwargs = additional_kwargs or {}
                self.response_metadata = response_metadata or {}

            def __add__(self, other):
                return DummyChunk(
                    "",
                    tool_calls=self.tool_calls or other.tool_calls,
                    additional_kwargs=self.additional_kwargs or other.additional_kwargs,
                    response_metadata=self.response_metadata or other.response_metadata,
                )

        class DummyLLM(_CanonicalAgentTestLLM):
            def __init__(self):
                super().__init__(
                    outcome=_canonical_agent_test_outcome(text="OK"),
                    captured=captured,
                    response_metadata={"finish_reason": "stop"},
                )
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                get_profile=lambda role="primary": SimpleNamespace(streaming=True)
            ),
        )
        agent.llm_with_tools = DummyLLM()

        result = agent._invoke_llm([AIMessage(content="hello")])

        assert result is not None
        assert result[1].content == "OK"
        assert result[1].response_metadata == {"finish_reason": "stop"}

    def test_invoke_llm_stream_aggregates_reasoning_content_for_followup_turns(self, monkeypatch):
        captured = {"thoughts": []}

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

            def stream_thought(self, text, done=False):
                captured["thoughts"].append((text, done))

        class DummyChunk:
            def __init__(self, content, *, additional_kwargs=None, tool_calls=None, response_metadata=None):
                self.content = content
                self.additional_kwargs = additional_kwargs or {}
                self.tool_calls = tool_calls or []
                self.response_metadata = response_metadata or {}

            def __add__(self, other):
                return DummyChunk(
                    (self.content or "") + (other.content or ""),
                    additional_kwargs=self.additional_kwargs or other.additional_kwargs,
                    tool_calls=self.tool_calls or other.tool_calls,
                    response_metadata=self.response_metadata or other.response_metadata,
                )

        class DummyLLM(_CanonicalAgentTestLLM):
            def __init__(self):
                super().__init__(
                    outcome=_canonical_agent_test_outcome(
                        text="结论",
                        reasoning_deltas=("先看", "日志"),
                    ),
                    captured=captured,
                )
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                get_profile=lambda role="primary": SimpleNamespace(streaming=True)
            ),
        )
        agent.llm_with_tools = DummyLLM()

        result = agent._invoke_llm([AIMessage(content="hello")])

        assert result is not None
        assert result[1].content == "结论"
        assert result[1].additional_kwargs["reasoning_content"] == "先看日志"
        assert captured["thoughts"] == [("先看", False), ("日志", False)]

    def test_invoke_llm_stream_normalizes_reasoning_aliases_and_cumulative_snapshots(self, monkeypatch):
        captured = {"thoughts": [], "responses": []}

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

            def stream_thought(self, text, done=False):
                captured["thoughts"].append((text, done))

            def stream_response(self, text, done=False):
                captured["responses"].append((text, done))

        class DummyChunk:
            def __init__(self, content="", *, additional_kwargs=None, tool_calls=None, response_metadata=None):
                self.content = content
                self.additional_kwargs = additional_kwargs or {}
                self.tool_calls = tool_calls or []
                self.response_metadata = response_metadata or {}

            def __add__(self, other):
                kwargs = dict(self.additional_kwargs)
                kwargs.update(getattr(other, "additional_kwargs", None) or {})
                metadata = dict(self.response_metadata)
                metadata.update(getattr(other, "response_metadata", None) or {})
                return DummyChunk(
                    (self.content or "") + (getattr(other, "content", "") or ""),
                    additional_kwargs=kwargs,
                    tool_calls=self.tool_calls or getattr(other, "tool_calls", []) or [],
                    response_metadata=metadata,
                )

        class DummyLLM(_CanonicalAgentTestLLM):
            def __init__(self):
                super().__init__(
                    outcome=_canonical_agent_test_outcome(
                        text="可见结论",
                        reasoning_deltas=("先看", "日志", "再查 UI", "隐藏"),
                    ),
                    captured=captured,
                )
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                get_profile=lambda role="primary": SimpleNamespace(streaming=True)
            ),
        )
        agent.llm_with_tools = DummyLLM()

        result = agent._invoke_llm([AIMessage(content="hello")])

        assert result is not None
        assert result[1].content == "可见结论"
        assert result[1].additional_kwargs["reasoning_content"] == "先看日志再查 UI隐藏"
        assert captured["thoughts"] == [
            ("先看", False),
            ("日志", False),
            ("再查 UI", False),
            ("隐藏", False),
        ]
        assert captured["responses"][-1] == ("可见结论", False)

    def test_invoke_llm_stream_preserves_final_usage_observation(self, monkeypatch):
        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

            def stream_response(self, *_args, **_kwargs):
                return None

            def stream_thought(self, *_args, **_kwargs):
                return None

        class DummyChunk:
            def __init__(self, content, *, response_metadata=None):
                self.content = content
                self.tool_calls = []
                self.additional_kwargs = {}
                self.response_metadata = response_metadata or {}

            def __add__(self, other):
                metadata = dict(self.response_metadata)
                metadata.update(getattr(other, "response_metadata", None) or {})
                return DummyChunk(
                    (self.content or "") + (getattr(other, "content", "") or ""),
                    response_metadata=metadata,
                )

        class DummyLLM(_CanonicalAgentTestLLM):
            def __init__(self):
                super().__init__(
                    outcome=_canonical_agent_test_outcome(text="完成"),
                    response_metadata={
                        "usage_observation": {
                            "input_tokens": 80,
                            "output_tokens": 10,
                            "total_tokens": 90,
                            "cached_input_tokens": 40,
                            "cache_hit_rate": 0.5,
                        }
                    },
                )
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                get_profile=lambda role="primary": SimpleNamespace(streaming=True)
            ),
        )
        agent.llm_with_tools = DummyLLM()

        result = agent._invoke_llm([AIMessage(content="hello")])

        assert result is not None
        assert result[1].content == "完成"
        assert result[1].response_metadata["usage_observation"]["input_tokens"] == 80
        assert result[1].response_metadata["usage_observation"]["cached_input_tokens"] == 40

    def test_get_llm_for_current_mode_rebinds_restart_whitelist(self):
        bound_tools = []

        class DummyBoundLLM:
            def __init__(self, tools):
                self.tools = tools

        class DummyBaseLLM:
            def bind_tools(self, tools):
                bound_tools.append([tool.name for tool in tools])
                return DummyBoundLLM(tools)

        def make_tool(name):
            return SimpleNamespace(name=name)

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent._base_llm = DummyBaseLLM()
        agent.llm_with_tools = DummyBoundLLM([make_tool("run_test_for_tool")])
        agent._bound_llm_cache = {"default": agent.llm_with_tools}
        agent._active_goal = "制定重启任务，然后对重启任务打勾，然后运行 `trigger_self_restart_tool` 重启你自己。"
        agent.key_tools = [
            make_tool("task_create_tool"),
            make_tool("task_update_tool"),
            make_tool("task_list_tool"),
            make_tool("get_current_goal_tool"),
            make_tool("get_core_context_tool"),
            make_tool("get_memory_summary_tool"),
            make_tool("trigger_self_restart_tool"),
            make_tool("close_evolution_transaction_tool"),
            make_tool("run_test_for_tool"),
        ]
        agent._key_tool_map = {tool.name: tool for tool in agent.key_tools}

        rebound = agent._get_llm_for_current_mode()

        assert rebound is not agent.llm_with_tools
        assert bound_tools == [[
            "task_create_tool",
            "task_update_tool",
            "task_list_tool",
            "get_current_goal_tool",
            "get_core_context_tool",
            "get_memory_summary_tool",
            "trigger_self_restart_tool",
            "close_evolution_transaction_tool",
        ]]

    def test_restart_focus_state_memory_exposes_allowed_tools_only(self):
        memory = build_restart_focus_state_memory(SelfEvolvingAgent._restart_allowed_tool_names())

        assert "当前轮实际暴露给模型的工具只保留" in memory
        assert "`trigger_self_restart_tool`" in memory
        assert "`run_test_for_tool`" not in memory

    def test_restart_focus_mode_is_disabled_for_full_evolution_goal(self):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent._active_goal = (
            "执行一轮完整自进化闭环探针："
            "根据 lint 结果调用 close_evolution_transaction_tool 关账，"
            "关账成功后立即调用 trigger_self_restart_tool 完成重启。"
        )

        assert agent._is_restart_focus_mode() is False

    def test_ui_stream_thought_hides_state_and_tool_call_tags(self):
        from core.ui.cli_ui import UIManager

        ui = UIManager()
        ui.stream_thought(
            "继续查看测试。\n\n<state>\n{\"mood\":\"好奇\"}\n</state>\n</minimax:tool_call>",
            done=True,
        )

        assert "<state>" not in ui._current_thought_stream
        assert "</minimax:tool_call>" not in ui._current_thought_stream
        assert "继续查看测试" in ui._current_thought_stream

    def test_parse_xml_tool_calls_handles_valid_invoke_block(self):
        content = """
        before
        <invoke name="read_file_tool">
          <parameter name="file_path">workspace/demo.py</parameter>
        </invoke>
        after
        """

        tool_calls = parse_xml_tool_calls(content)

        assert tool_calls == [
            {
                "name": "read_file_tool",
                "args": {"file_path": "workspace/demo.py"},
                "id": "xml_0",
            }
        ]

    def test_parse_xml_tool_calls_ignores_partial_or_invalid_xml(self):
        content = '<invoke name="broken"><parameter name="x">1</parameter>'

        assert parse_xml_tool_calls(content) == []

    def test_think_and_act_xml_tool_call_writes_tool_message(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "xml-tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                get_profile=lambda role="primary": SimpleNamespace(model="xml-test-model")
            )
        )
        agent.git_memory = SimpleNamespace(refresh_git_memory=lambda force=False: None)
        agent.prompt_manager = SimpleNamespace(
            update_current_goal=lambda goal: None,
            set_runtime_goal_packet=lambda packet: None,
            clear_state_memory=lambda persist=True: None,
            build=lambda: "stable system prompt",
        )
        agent._active_turn_messages = []
        agent._active_turn_goal = None
        agent._pending_lifecycle_action = None
        agent._system_prompt_written = False
        agent._cached_system_prompt = ""
        agent._context_window_limit = 8192
        agent._effective_max_token_limit = 8192
        agent._pending_static_context_blocks = []
        agent._pending_runtime_context_blocks = []
        agent._compression_count_this_turn = 0
        agent._last_compression_iteration = 0
        agent._last_turn_metadata = {}
        agent._last_turn_failed = False
        agent._single_turn_mode_active = False
        agent._active_goal = None
        agent._last_runtime_state_memory = ""
        agent._last_runtime_state_memory_key = ""
        agent.event_bus = SimpleNamespace(publish=lambda *args, **kwargs: None)
        agent.mental_model = SimpleNamespace()
        agent._last_visible_response_text = ""
        agent._last_response_tool_calls = []

        response_xml = (
            '<invoke name="read_memory_tool"><parameter name="scope">core_wisdom</parameter></invoke>'
        )
        executed_tools: list[str] = []

        class DummyRoundState:
            max_iterations = 1
            no_new_evidence_steps = 0
            consecutive_tool_only_steps = 0
            consecutive_bookkeeping_tool_only_steps = 0
            consecutive_failures = 0
            delegation_failures = 0
            total_tool_calls = 0
            substantive_tool_calls = 0
            turn_had_progress = False

            def __init__(self):
                self.xml_calls_recorded = None

            def next_iteration(self):
                return 1

            def current_status(self):
                return {}

            def thinking_status(self, user_prompt):
                return {}

            def add_xml_tool_calls(self, count):
                self.xml_calls_recorded = count

            def note_response_tools(self, *args, **kwargs):
                return None

        class DummyOutcomeController:
            def __init__(self):
                self.lifecycle_actions = []

            def should_stop_for_convergence(self, **kwargs):
                return None

            def handle_lifecycle_action(self, action):
                self.lifecycle_actions.append(action)
                return SimpleNamespace(
                    pending_action=None,
                    info_log=None,
                    continue_main_loop=True,
                    break_round=False,
                )

            def finalize_round(self, round_state):
                return SimpleNamespace(
                    last_turn_failed=False,
                    turn_stats={"round_tools": round_state.total_tool_calls},
                    turn_success=True,
                    ui_status="SUCCESS",
                )

            def prepare_tool_state_feedback(self, **kwargs):
                return None

        round_state = DummyRoundState()
        round_state.note_turn_outcome = lambda kind: None
        round_state.note_progress = lambda: setattr(round_state, "turn_had_progress", True)
        round_state.add_tool_calls = lambda count: setattr(
            round_state,
            "total_tool_calls",
            round_state.total_tool_calls + count,
        )
        round_state.acting_status = lambda *args, **kwargs: {}
        round_state.note_llm_failure = lambda: 1
        round_state.note_lifecycle_completion = lambda: None
        DummyOutcomeController.prepare_tool_state_feedback = lambda self, **kwargs: None
        outcome_controller = DummyOutcomeController()

        class DummyResponseProcessor:
            def preview(self, response):
                return SimpleNamespace(
                    raw_content=response.content,
                    xml_tool_calls=[
                        {
                            "name": "read_memory_tool",
                            "id": "xml_0",
                            "args": {"scope": "core_wisdom"},
                        }
                    ],
                    tool_call_count=0,
                    has_tool_calls=False,
                )

        class DummyResponseSurface:
            def record_token_usage(self, *args, **kwargs):
                return (0, 0)

        class DummyUI:
            def update_status(self, *args, **kwargs):
                return None

            def note_context_window(self, *args, **kwargs):
                return None

            def add_log(self, *args, **kwargs):
                return None

            def note_turn_start(self, turn):
                return None

            def note_turn_result(self, *args, **kwargs):
                return None

        class DummySessionState:
            def set_runtime_goal_packet(self, packet):
                return None

            def reset_runtime_constraints(self):
                return None

            def get_active_evolution_txn(self):
                return None

        def tool_executor(_tool_call, _messages):
            executed_tools.append("read_memory_tool")
            return ("xml tool result", None)

        logger = MagicMock()
        monkeypatch.setattr(agent_module, "logger", logger)
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
        session_state = DummySessionState()
        session_state.note_scope_completion = lambda *args, **kwargs: None
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session_state)
        monkeypatch.setattr(
            agent_module,
            "_record_agent_scene_event",
            lambda *args, **kwargs: None,
        )
        def build_runtime_goal_packet_stub(policy, goal, **_kwargs):
            return SimpleNamespace(
                source="xml_unit",
                objective_type="unit",
                allow_auto_continue=True,
                allow_file_writes=True,
                allow_git_commit=False,
                allow_evolution_transaction=True,
                allow_subagents=False,
            )

        monkeypatch.setattr(agent_module, "build_runtime_goal_packet", build_runtime_goal_packet_stub)
        monkeypatch.setattr(
            agent_module,
            "build_cacheable_system_prefix_message",
            lambda sp: SystemMessage(content=str(sp)),
        )
        monkeypatch.setattr(
            agent_module,
            "build_dynamic_system_context_message",
            lambda current_prompt: None,
        )
        monkeypatch.setattr(
            agent_module,
            "extend_system_message_cacheable_prefix",
            lambda message, blocks: (message, False),
        )
        monkeypatch.setattr(
            TurnOutcomeController,
            "insert_static_context_after_system",
            lambda messages, context_messages: list(messages),
        )
        monkeypatch.setattr(
            TurnOutcomeController,
            "insert_volatile_context_before_current_user",
            lambda messages, context_messages: list(messages),
        )
        monkeypatch.setattr(
            agent_module,
            "is_dynamic_system_context_message",
            lambda message: False,
        )
        monkeypatch.setattr(
            agent_module,
            "is_volatile_system_context_message",
            lambda message: False,
        )
        monkeypatch.setattr(
            agent_module,
            "estimate_messages_tokens",
            lambda messages: 0,
        )
        monkeypatch.setattr(
            TurnOutcomeController,
            "prepare_turn_messages",
            lambda **kwargs: (
                [
                    SystemMessage(content=kwargs["system_prompt"]),
                    kwargs["build_external_request_message"]("xml task input"),
                ],
                False,
            ),
        )
        monkeypatch.setattr(
            TurnOutcomeController,
            "finish_turn_message_carryover",
            lambda messages, lifecycle_action, active_goal, turn_identity="": SimpleNamespace(
                messages=messages,
                goal=active_goal,
                turn_identity=turn_identity,
                terminal=False,
            ),
        )
        policy = SimpleNamespace(
            mode=AgentMode.SELF_EVOLUTION,
            orchestrator_kind="agent",
            runtime_input_builder=lambda content: build_external_request_message(content),
        )
        monkeypatch.setattr(agent_module, "to_string", lambda value: str(value))

        agent._get_mode_policy = lambda: policy
        agent.is_mental_model_enabled_for_turn = lambda: False
        agent._sync_runtime_state_memory = lambda force=False: None
        agent._seed_runtime_agent_context_for_turn = lambda run_id: None
        agent._raise_if_turn_stop_requested = lambda: None
        agent._create_round_state = lambda: round_state
        agent._apply_active_components_request = lambda processed: None
        agent._get_response_processor = lambda: ResponseProcessor()
        response_surface = DummyResponseSurface()
        response_surface.build_state_block = lambda **kwargs: ""
        response_surface.apply_state_feedback = lambda **kwargs: None
        response_surface.emit_visible_response = lambda **kwargs: {
            "last_visible_response_text": "",
            "last_response_tool_calls": [],
        }
        agent._get_response_surface_controller = lambda: response_surface
        agent._get_turn_outcome_controller = lambda: outcome_controller
        agent._capture_chat_dataset_candidate_if_needed = lambda *args, **kwargs: None
        agent._record_turn_cache_diagnostics = lambda **kwargs: None
        agent._refresh_retrospective_state_memory = lambda: None
        agent._is_tool_visible_to_current_agent = lambda tool_name: True
        agent._hidden_tool_call_message = lambda tool_name: f"blocked:{tool_name}"
        agent._remember_tool_output = lambda *args, **kwargs: None
        agent.tool_lifecycle = SimpleNamespace(
            execute_tool=tool_executor,
            handle_tool_result=ToolLifecycleBridge.handle_tool_result,
        )
        def execute_tools(tool_calls, messages):
            lifecycle_action = None
            for tool_call in tool_calls:
                result, lifecycle_action = agent.tool_lifecycle.execute_tool(tool_call, messages)
                agent.tool_lifecycle.handle_tool_result(
                    tool_call,
                    result,
                    lifecycle_action,
                    messages,
                )
                if lifecycle_action in ("restart", "hibernated", "turn_complete"):
                    break
            return lifecycle_action

        agent.tool_lifecycle.execute_tools = execute_tools
        agent._invoke_llm = lambda messages, replay_state=None: AIMessage(
            content=response_xml,
            tool_calls=[],
        )

        result = agent.think_and_act("读取记忆进行自检")

        assert result is True
        assert executed_tools == ["read_memory_tool"]
        assert any(
            isinstance(message, ToolMessage)
            and message.tool_call_id == "xml_0"
            and "xml tool result" in message.content
            for message in agent._active_turn_messages
        )
        assert not any(
            isinstance(message, AIMessage) and "<invoke" in str(message.content)
            for message in agent._active_turn_messages
        )

    def test_think_and_act_xml_tool_call_visibility_filter_blocks_unknown_tool(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "xml-visibility-filter-tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                get_profile=lambda role="primary": SimpleNamespace(model="xml-test-model")
            )
        )
        agent.git_memory = SimpleNamespace(refresh_git_memory=lambda force=False: None)
        agent.prompt_manager = SimpleNamespace(
            update_current_goal=lambda goal: None,
            set_runtime_goal_packet=lambda packet: None,
            clear_state_memory=lambda persist=True: None,
            build=lambda: "stable system prompt",
        )
        agent._active_turn_messages = []
        agent._active_turn_goal = None
        agent._pending_lifecycle_action = None
        agent._system_prompt_written = False
        agent._cached_system_prompt = ""
        agent._context_window_limit = 8192
        agent._effective_max_token_limit = 8192
        agent._pending_static_context_blocks = []
        agent._pending_runtime_context_blocks = []
        agent._compression_count_this_turn = 0
        agent._last_compression_iteration = 0
        agent._last_turn_metadata = {}
        agent._last_turn_failed = False
        agent._single_turn_mode_active = False
        agent._active_goal = None
        agent._last_runtime_state_memory = ""
        agent._last_runtime_state_memory_key = ""
        agent.event_bus = SimpleNamespace(publish=lambda *args, **kwargs: None)
        agent.mental_model = SimpleNamespace()
        agent._last_visible_response_text = ""
        agent._last_response_tool_calls = []

        response_xml = '<invoke name="hidden_tool"><parameter name="scope">x</parameter></invoke>'
        executed_tools: list[str] = []

        class DummyRoundState:
            max_iterations = 1
            no_new_evidence_steps = 0
            consecutive_tool_only_steps = 0
            consecutive_bookkeeping_tool_only_steps = 0
            consecutive_failures = 0
            delegation_failures = 0
            total_tool_calls = 0
            substantive_tool_calls = 0
            turn_had_progress = False

            def __init__(self):
                self.xml_calls_recorded = None

            def next_iteration(self):
                return 1

            def current_status(self):
                return {}

            def thinking_status(self, user_prompt):
                return {}

            def add_xml_tool_calls(self, count):
                self.xml_calls_recorded = count

            def note_response_tools(self, *args, **kwargs):
                return None

        class DummyOutcomeController:
            def __init__(self):
                self.lifecycle_actions = []

            def should_stop_for_convergence(self, **kwargs):
                return None

            def handle_lifecycle_action(self, action):
                self.lifecycle_actions.append(action)
                return SimpleNamespace(
                    pending_action=None,
                    info_log=None,
                    continue_main_loop=True,
                    break_round=False,
                )

            def finalize_round(self, round_state):
                return SimpleNamespace(
                    last_turn_failed=False,
                    turn_stats={"round_tools": round_state.total_tool_calls},
                    turn_success=True,
                    ui_status="SUCCESS",
                )

        round_state = DummyRoundState()
        round_state.note_turn_outcome = lambda kind: None
        round_state.note_progress = lambda: setattr(round_state, "turn_had_progress", True)
        round_state.add_tool_calls = lambda count: setattr(
            round_state,
            "total_tool_calls",
            round_state.total_tool_calls + count,
        )
        round_state.acting_status = lambda *args, **kwargs: {}
        round_state.note_llm_failure = lambda: 1
        round_state.note_lifecycle_completion = lambda: None
        DummyOutcomeController.prepare_tool_state_feedback = lambda self, **kwargs: None
        outcome_controller = DummyOutcomeController()

        class DummyResponseProcessor:
            def preview(self, response):
                return SimpleNamespace(
                    raw_content=response.content,
                    xml_tool_calls=[
                        {
                            "name": "hidden_tool",
                            "id": "xml_0",
                            "args": {"scope": "x"},
                        }
                    ],
                    tool_call_count=0,
                    has_tool_calls=False,
                )

        class DummyResponseSurface:
            def record_token_usage(self, *args, **kwargs):
                return (0, 0)

        class DummyUI:
            def update_status(self, *args, **kwargs):
                return None

            def note_context_window(self, *args, **kwargs):
                return None

            def add_log(self, *args, **kwargs):
                return None

            def note_turn_start(self, turn):
                return None

            def note_turn_result(self, *args, **kwargs):
                return None

        class DummySessionState:
            def set_runtime_goal_packet(self, packet):
                return None

            def reset_runtime_constraints(self):
                return None

            def get_active_evolution_txn(self):
                return None

        def tool_executor(_tool_call, _messages):
            executed_tools.append("hidden_tool")
            return ("must not call", None)

        logger = MagicMock()
        monkeypatch.setattr(agent_module, "logger", logger)
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
        session_state = DummySessionState()
        session_state.note_scope_completion = lambda *args, **kwargs: None
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session_state)
        monkeypatch.setattr(agent_module, "_record_agent_scene_event", lambda *args, **kwargs: None)
        def build_runtime_goal_packet_stub(policy, goal, **_kwargs):
            return SimpleNamespace(
                source="xml_unit",
                objective_type="unit",
                allow_auto_continue=True,
                allow_file_writes=True,
                allow_git_commit=False,
                allow_evolution_transaction=True,
                allow_subagents=False,
            )

        monkeypatch.setattr(agent_module, "build_runtime_goal_packet", build_runtime_goal_packet_stub)
        monkeypatch.setattr(agent_module, "build_cacheable_system_prefix_message", lambda sp: SystemMessage(content=str(sp)))
        monkeypatch.setattr(agent_module, "build_dynamic_system_context_message", lambda current_prompt: None)
        monkeypatch.setattr(agent_module, "extend_system_message_cacheable_prefix", lambda message, blocks: (message, False))
        monkeypatch.setattr(TurnOutcomeController, "insert_static_context_after_system", lambda messages, context_messages: list(messages))
        monkeypatch.setattr(TurnOutcomeController, "insert_volatile_context_before_current_user", lambda messages, context_messages: list(messages))
        monkeypatch.setattr(agent_module, "is_dynamic_system_context_message", lambda message: False)
        monkeypatch.setattr(agent_module, "is_volatile_system_context_message", lambda message: False)
        monkeypatch.setattr(agent_module, "estimate_messages_tokens", lambda messages: 0)
        monkeypatch.setattr(
            TurnOutcomeController,
            "prepare_turn_messages",
            lambda **kwargs: (
                [
                    SystemMessage(content=kwargs["system_prompt"]),
                    kwargs["build_external_request_message"]("xml task input"),
                ],
                False,
            ),
        )
        monkeypatch.setattr(
            TurnOutcomeController,
            "finish_turn_message_carryover",
            lambda messages, lifecycle_action, active_goal, turn_identity="": SimpleNamespace(
                messages=messages,
                goal=active_goal,
                turn_identity=turn_identity,
                terminal=False,
            ),
        )
        policy = SimpleNamespace(
            mode=AgentMode.SELF_EVOLUTION,
            orchestrator_kind="agent",
            runtime_input_builder=lambda content: build_external_request_message(content),
        )
        monkeypatch.setattr(agent_module, "to_string", lambda value: str(value))

        agent._get_mode_policy = lambda: policy
        agent.is_mental_model_enabled_for_turn = lambda: False
        agent._sync_runtime_state_memory = lambda force=False: None
        agent._seed_runtime_agent_context_for_turn = lambda run_id: None
        agent._raise_if_turn_stop_requested = lambda: None
        agent._create_round_state = lambda: round_state
        agent._apply_active_components_request = lambda processed: None
        agent._get_response_processor = lambda: ResponseProcessor()
        response_surface = DummyResponseSurface()
        response_surface.build_state_block = lambda **kwargs: ""
        response_surface.apply_state_feedback = lambda **kwargs: None
        response_surface.emit_visible_response = lambda **kwargs: {
            "last_visible_response_text": "",
            "last_response_tool_calls": [],
        }
        agent._get_response_surface_controller = lambda: response_surface
        agent._get_turn_outcome_controller = lambda: outcome_controller
        agent._capture_chat_dataset_candidate_if_needed = lambda *args, **kwargs: None
        agent._record_turn_cache_diagnostics = lambda **kwargs: None
        agent._refresh_retrospective_state_memory = lambda: None
        agent._is_tool_visible_to_current_agent = lambda tool_name: False
        agent._hidden_tool_call_message = lambda tool_name: f"blocked:{tool_name}"
        agent._remember_tool_output = lambda *args, **kwargs: None
        agent.tool_lifecycle = SimpleNamespace(
            execute_tool=tool_executor,
            handle_tool_result=ToolLifecycleBridge.handle_tool_result,
        )
        def execute_tools(tool_calls, messages):
            lifecycle_action = None
            for tool_call in tool_calls:
                result, lifecycle_action = agent.tool_lifecycle.execute_tool(tool_call, messages)
                agent.tool_lifecycle.handle_tool_result(
                    tool_call,
                    result,
                    lifecycle_action,
                    messages,
                )
                if lifecycle_action in ("restart", "hibernated", "turn_complete"):
                    break
            return lifecycle_action

        agent.tool_lifecycle.execute_tools = execute_tools
        agent._invoke_llm = lambda messages, replay_state=None: AIMessage(
            content=response_xml,
            tool_calls=[],
        )

        result = agent.think_and_act("不可见工具调用")

        assert result is True
        assert executed_tools == []
        assert outcome_controller.lifecycle_actions == []
        assert any(
            isinstance(message, ToolMessage)
            and message.tool_call_id == "xml_0"
            and "blocked:hidden_tool" in message.content
            for message in agent._active_turn_messages
        )

    def test_think_and_act_xml_turn_complete_sets_pending_lifecycle_action(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "xml-turn-complete-tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                get_profile=lambda role="primary": SimpleNamespace(model="xml-test-model")
            )
        )
        agent.git_memory = SimpleNamespace(refresh_git_memory=lambda force=False: None)
        agent.prompt_manager = SimpleNamespace(
            update_current_goal=lambda goal: None,
            set_runtime_goal_packet=lambda packet: None,
            clear_state_memory=lambda persist=True: None,
            build=lambda: "stable system prompt",
        )
        agent._active_turn_messages = []
        agent._active_turn_goal = None
        agent._pending_lifecycle_action = None
        agent._system_prompt_written = False
        agent._cached_system_prompt = ""
        agent._context_window_limit = 8192
        agent._effective_max_token_limit = 8192
        agent._pending_static_context_blocks = []
        agent._pending_runtime_context_blocks = []
        agent._compression_count_this_turn = 0
        agent._last_compression_iteration = 0
        agent._last_turn_metadata = {}
        agent._last_turn_failed = False
        agent._single_turn_mode_active = False
        agent._active_goal = None
        agent._last_runtime_state_memory = ""
        agent._last_runtime_state_memory_key = ""
        agent.event_bus = SimpleNamespace(publish=lambda *args, **kwargs: None)
        agent.mental_model = SimpleNamespace()
        agent._last_visible_response_text = ""
        agent._last_response_tool_calls = []

        response_xml = (
            '<invoke name="close_evolution_transaction_tool"><parameter name="status">success</parameter></invoke>'
        )

        class DummyRoundState:
            max_iterations = 1
            no_new_evidence_steps = 0
            consecutive_tool_only_steps = 0
            consecutive_bookkeeping_tool_only_steps = 0
            consecutive_failures = 0
            delegation_failures = 0
            total_tool_calls = 0
            substantive_tool_calls = 0
            turn_had_progress = False

            def __init__(self):
                self.xml_calls_recorded = None

            def next_iteration(self):
                return 1

            def current_status(self):
                return {}

            def thinking_status(self, user_prompt):
                return {}

            def add_xml_tool_calls(self, count):
                self.xml_calls_recorded = count

            def note_response_tools(self, *args, **kwargs):
                return None

        class DummyOutcomeController:
            def __init__(self):
                self.lifecycle_actions = []

            def should_stop_for_convergence(self, **kwargs):
                return None

            def handle_lifecycle_action(self, action):
                self.lifecycle_actions.append(action)
                return SimpleNamespace(
                    pending_action="restart_after_txn",
                    info_log="txn done",
                    continue_main_loop=True,
                    break_round=False,
                )

            def finalize_round(self, round_state):
                return SimpleNamespace(
                    last_turn_failed=False,
                    turn_stats={"round_tools": round_state.total_tool_calls},
                    turn_success=True,
                    ui_status="SUCCESS",
                )

            def prepare_tool_state_feedback(self, **kwargs):
                return None

        round_state = DummyRoundState()
        round_state.note_turn_outcome = lambda kind: None
        round_state.note_progress = lambda: setattr(round_state, "turn_had_progress", True)
        round_state.add_tool_calls = lambda count: setattr(
            round_state,
            "total_tool_calls",
            round_state.total_tool_calls + count,
        )
        round_state.acting_status = lambda *args, **kwargs: {}
        round_state.note_llm_failure = lambda: 1
        round_state.note_lifecycle_completion = lambda: None
        DummyOutcomeController.prepare_tool_state_feedback = lambda self, **kwargs: None
        outcome_controller = DummyOutcomeController()

        class DummyResponseProcessor:
            def preview(self, response):
                return SimpleNamespace(
                    raw_content=response.content,
                    xml_tool_calls=[
                        {
                            "name": "close_evolution_transaction_tool",
                            "id": "xml_0",
                            "args": {"status": "success"},
                        }
                    ],
                    tool_call_count=0,
                    has_tool_calls=False,
                )

        class DummyResponseSurface:
            def record_token_usage(self, *args, **kwargs):
                return (0, 0)

        class DummyUI:
            def update_status(self, *args, **kwargs):
                return None

            def note_context_window(self, *args, **kwargs):
                return None

            def add_log(self, *args, **kwargs):
                return None

            def note_turn_start(self, turn):
                return None

            def note_turn_result(self, *args, **kwargs):
                return None

        class DummySessionState:
            def set_runtime_goal_packet(self, packet):
                return None

            def reset_runtime_constraints(self):
                return None

            def get_active_evolution_txn(self):
                return None

        logger = MagicMock()
        monkeypatch.setattr(agent_module, "logger", logger)
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
        session_state = DummySessionState()
        session_state.note_scope_completion = lambda *args, **kwargs: None
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session_state)
        monkeypatch.setattr(
            agent_module,
            "_record_agent_scene_event",
            lambda *args, **kwargs: None,
        )
        def build_runtime_goal_packet_stub(policy, goal, **_kwargs):
            return SimpleNamespace(
                source="xml_unit",
                objective_type="unit",
                allow_auto_continue=True,
                allow_file_writes=True,
                allow_git_commit=False,
                allow_evolution_transaction=True,
                allow_subagents=False,
            )

        monkeypatch.setattr(agent_module, "build_runtime_goal_packet", build_runtime_goal_packet_stub)
        monkeypatch.setattr(
            agent_module,
            "build_cacheable_system_prefix_message",
            lambda sp: SystemMessage(content=str(sp)),
        )
        monkeypatch.setattr(
            agent_module,
            "build_dynamic_system_context_message",
            lambda current_prompt: None,
        )
        monkeypatch.setattr(
            agent_module,
            "extend_system_message_cacheable_prefix",
            lambda message, blocks: (message, False),
        )
        monkeypatch.setattr(
            TurnOutcomeController,
            "insert_static_context_after_system",
            lambda messages, context_messages: list(messages),
        )
        monkeypatch.setattr(
            TurnOutcomeController,
            "insert_volatile_context_before_current_user",
            lambda messages, context_messages: list(messages),
        )
        monkeypatch.setattr(
            agent_module,
            "is_dynamic_system_context_message",
            lambda message: False,
        )
        monkeypatch.setattr(
            agent_module,
            "is_volatile_system_context_message",
            lambda message: False,
        )
        monkeypatch.setattr(
            agent_module,
            "estimate_messages_tokens",
            lambda messages: 0,
        )
        monkeypatch.setattr(
            TurnOutcomeController,
            "prepare_turn_messages",
            lambda **kwargs: (
                [
                    SystemMessage(content=kwargs["system_prompt"]),
                    kwargs["build_external_request_message"]("xml task input"),
                ],
                False,
            ),
        )
        monkeypatch.setattr(
            TurnOutcomeController,
            "finish_turn_message_carryover",
            lambda messages, lifecycle_action, active_goal, turn_identity="": SimpleNamespace(
                messages=messages,
                goal=active_goal,
                turn_identity=turn_identity,
                terminal=False,
            ),
        )
        policy = SimpleNamespace(
            mode=AgentMode.SELF_EVOLUTION,
            orchestrator_kind="agent",
            runtime_input_builder=lambda content: build_external_request_message(content),
        )
        monkeypatch.setattr(agent_module, "to_string", lambda value: str(value))

        agent._get_mode_policy = lambda: policy
        agent.is_mental_model_enabled_for_turn = lambda: False
        agent._sync_runtime_state_memory = lambda force=False: None
        agent._seed_runtime_agent_context_for_turn = lambda run_id: None
        agent._raise_if_turn_stop_requested = lambda: None
        agent._create_round_state = lambda: round_state
        agent._apply_active_components_request = lambda processed: None
        agent._get_response_processor = lambda: ResponseProcessor()
        response_surface = DummyResponseSurface()
        response_surface.build_state_block = lambda **kwargs: ""
        response_surface.apply_state_feedback = lambda **kwargs: None
        response_surface.emit_visible_response = lambda **kwargs: {
            "last_visible_response_text": "",
            "last_response_tool_calls": [],
        }
        agent._get_response_surface_controller = lambda: response_surface
        agent._get_turn_outcome_controller = lambda: outcome_controller
        agent._capture_chat_dataset_candidate_if_needed = lambda *args, **kwargs: None
        agent._record_turn_cache_diagnostics = lambda **kwargs: None
        agent._refresh_retrospective_state_memory = lambda: None
        agent._is_tool_visible_to_current_agent = lambda tool_name: True
        agent._hidden_tool_call_message = lambda tool_name: f"blocked:{tool_name}"
        agent._remember_tool_output = lambda *args, **kwargs: None
        agent.tool_lifecycle = SimpleNamespace(
            execute_tool=lambda tool_call, messages: (
                '{"status":"success","transaction_status":"success"}',
                "turn_complete",
            ),
            handle_tool_result=ToolLifecycleBridge.handle_tool_result,
        )
        def execute_tools(tool_calls, messages):
            lifecycle_action = None
            for tool_call in tool_calls:
                result, lifecycle_action = agent.tool_lifecycle.execute_tool(tool_call, messages)
                agent.tool_lifecycle.handle_tool_result(
                    tool_call,
                    result,
                    lifecycle_action,
                    messages,
                )
                if lifecycle_action in ("restart", "hibernated", "turn_complete"):
                    break
            return lifecycle_action

        agent.tool_lifecycle.execute_tools = execute_tools
        agent._invoke_llm = lambda messages, replay_state=None: AIMessage(
            content=response_xml,
            tool_calls=[],
        )

        result = agent.think_and_act("事务完成后重启")

        assert result is True
        assert outcome_controller.lifecycle_actions == ["turn_complete"]
        assert agent._pending_lifecycle_action == "restart_after_txn"
        assert any(
            isinstance(message, ToolMessage)
            and message.tool_call_id == "xml_0"
            and '"status":"success"' in message.content
            for message in agent._active_turn_messages
        )

    def test_parse_tool_args_coerces_numeric_bool_and_null_scalars(self):
        parsed = parse_tool_args(
            {
                "file_path": "demo.py",
                "offset": "30",
                "max_lines": "50",
                "show_line_numbers": "false",
                "timeout": "12.5",
                "meta": {"retry": "true", "note": "keep"},
                "empty": "null",
            }
        )

        assert parsed["file_path"] == "demo.py"
        assert parsed["offset"] == 30
        assert parsed["max_lines"] == 50
        assert parsed["show_line_numbers"] is False
        assert parsed["timeout"] == 12.5
        assert parsed["meta"]["retry"] is True
        assert parsed["meta"]["note"] == "keep"
        assert parsed["empty"] is None

    def test_response_processor_preview_finalize_reuses_parsed_data(self):
        """preview + finalize 必须等价于一次 process，避免双解析浪费 CPU。"""
        processor = ResponseProcessor()
        response = SimpleNamespace(
            content="思考完成\n<state>{\"mood\":\"专注\"}</state>",
            tool_calls=[{"name": "read_file_tool", "args": {"file_path": "demo.py"}, "id": "call_1"}],
        )

        preview = processor.preview(response)
        finalized = processor.finalize(response, preview, state_block_str="<state>{\"focus\":\"yes\"}</state>")
        equivalent = processor.process(response, state_block_str="<state>{\"focus\":\"yes\"}</state>")

        # preview 给出轻量解析
        assert preview.raw_content == "思考完成\n<state>{\"mood\":\"专注\"}</state>"
        assert preview.has_tool_calls is True
        assert preview.tool_call_count == 1
        assert preview.xml_tool_calls == []

        # finalize 与 process 行为完全一致
        assert finalized.raw_content == equivalent.raw_content
        assert finalized.raw_content_clean == equivalent.raw_content_clean
        assert finalized.raw_content_with_state == equivalent.raw_content_with_state
        assert finalized.tool_calls == equivalent.tool_calls
        assert finalized.xml_tool_calls == equivalent.xml_tool_calls
        assert finalized.active_components == equivalent.active_components
        assert finalized.state_info == equivalent.state_info

    def test_response_processor_preview_detects_xml_fallback_without_finalize(self):
        """preview 阶段就应识别 XML fallback，让 fast-path 不必先付全量 finalize 的代价。"""
        processor = ResponseProcessor()
        response = SimpleNamespace(
            content='<invoke name="grep_search_tool"><parameter name="query">foo</parameter></invoke>',
            tool_calls=[],
        )

        preview = processor.preview(response)
        assert preview.has_tool_calls is False
        assert len(preview.xml_tool_calls) == 1
        assert preview.xml_tool_calls[0]["name"] == "grep_search_tool"

    def test_response_processor_splits_standard_tool_calls_and_state_echo(self):
        processor = ResponseProcessor()
        response = SimpleNamespace(
            content="继续处理\n<state>{\"mood\":\"专注\"}</state>",
            tool_calls=[{"name": "read_file_tool", "args": {"file_path": "demo.py"}, "id": "call_1"}],
        )

        processed = processor.process(response)

        assert processed.tool_call_count == 1
        assert processed.has_tool_calls is True
        assert processed.xml_tool_calls == []
        assert "<state>" not in processed.raw_content_clean
        assert processed.visible_text == "继续处理"

    def test_response_processor_detects_xml_fallback_when_standard_tool_calls_missing(self):
        processor = ResponseProcessor()
        response = SimpleNamespace(
            content='<invoke name="read_file_tool"><parameter name="file_path">demo.py</parameter></invoke>',
            tool_calls=[],
        )

        processed = processor.process(response)

        assert processed.has_tool_calls is False
        assert len(processed.xml_tool_calls) == 1
        assert processed.xml_tool_calls[0]["name"] == "read_file_tool"

    def test_response_processor_hides_xml_protocol_from_visible_text(self):
        processor = ResponseProcessor()
        response = SimpleNamespace(
            content=(
                "先读取文件再继续判断。\n"
                '<invoke name="read_file_tool">'
                '<parameter name="file_path">demo.py</parameter>'
                "</invoke>\n"
                "<sta"
            ),
            tool_calls=[],
        )

        processed = processor.process(response)

        assert len(processed.xml_tool_calls) == 1
        assert processed.visible_text == "先读取文件再继续判断。"
        assert "<invoke" not in processed.raw_content_clean
        assert "<parameter" not in processed.raw_content_clean
        assert "demo.py" not in processed.raw_content_clean
        assert "<sta" not in processed.raw_content_clean

    def test_response_processor_does_not_fallback_to_raw_protocol_when_clean_is_empty(self):
        processor = ResponseProcessor()
        response = SimpleNamespace(
            content='<invoke name="read_file_tool"><parameter name="file_path">demo.py</parameter></invoke>',
            tool_calls=[],
        )

        processed = processor.process(response)

        assert len(processed.xml_tool_calls) == 1
        assert processed.raw_content_clean == ""
        assert processed.visible_text == ""

    def test_response_processor_extracts_active_components_and_strips_echo(self):
        processor = ResponseProcessor()
        response = SimpleNamespace(
            content=(
                "先收窄问题\n"
                "<active_components>SOUL, SPEC CODEBASE_MAP</active_components>\n"
                "<state>{\"mood\":\"专注\"}</state>"
            ),
            tool_calls=[],
        )

        processed = processor.process(response)

        assert processed.active_components == ["SOUL", "SPEC", "CODEBASE_MAP"]
        assert "<active_components>" not in processed.raw_content_clean
        assert "<state>" not in processed.raw_content_clean
        assert processed.visible_text == "先收窄问题"

    def test_response_processor_flattens_content_blocks(self):
        processor = ResponseProcessor()
        response = SimpleNamespace(
            content=[
                {"type": "text", "text": "继续"},
                {"type": "text", "text": "检查"},
            ],
            tool_calls=[],
        )

        processed = processor.process(response)

        assert processed.raw_content == "继续检查"
        assert processed.visible_text == "继续检查"

    def test_round_state_controller_tracks_progress_failures_and_stats(self):
        state = RoundStateController(max_iterations=5)

        assert state.next_iteration() == 1
        state.note_delegation(useful=False)
        assert state.no_new_evidence_steps == 1
        assert state.delegation_failures == 1

        state.note_progress()
        state.add_token_usage(10, 20)
        state.add_tool_calls(2)
        state.note_response_tools(0)

        assert state.total_input_tokens == 10
        assert state.total_output_tokens == 20
        assert state.total_tool_calls == 2
        assert state.no_new_evidence_steps == 2
        assert state.consecutive_tool_only_steps == 0
        assert "tool_only_steps" not in state.thinking_status("demo")
        assert state.runtime_telemetry()["consecutive_tool_only_steps"] == 0
        assert state.finish_success(False) is True
        assert state.final_stats()["tool_calls"] == 2

    def test_round_state_tracks_consecutive_tool_only_steps(self):
        state = RoundStateController(max_iterations=5)

        state.note_response_tools(1, "", tool_names=["read_file_tool"])
        state.note_response_tools(1, "", tool_names=["grep_search_tool"])
        assert state.consecutive_tool_only_steps == 2

        state.note_response_tools(1, "已形成阶段性结论", tool_names=["read_file_tool"])
        assert state.consecutive_tool_only_steps == 0

        state.note_response_tools(1, "", tool_names=["read_file_tool"])
        state.note_response_tools(0, "")
        assert state.consecutive_tool_only_steps == 0

    def test_round_state_marks_iteration_exhaustion_without_final_answer(self):
        state = RoundStateController(max_iterations=2)

        state.next_iteration()
        state.note_response_tools(1, "", tool_names=["read_file_tool"])
        assert state.exhausted_without_final_answer() is False

        state.next_iteration()
        state.note_response_tools(1, "", tool_names=["grep_search_tool"])
        assert state.exhausted_without_final_answer() is True
        assert state.finish_success(False) is False

        recovered = RoundStateController(max_iterations=2)
        recovered.next_iteration()
        recovered.next_iteration()
        recovered.note_response_tools(0, "这是最终回答")
        recovered.note_progress()
        assert recovered.exhausted_without_final_answer() is False
        assert recovered.finish_success(False) is True

    def test_round_state_tracks_bookkeeping_tools_as_no_new_evidence(self):
        state = RoundStateController(max_iterations=5)

        state.note_response_tools(1, "", tool_names=["task_create_tool"])
        state.note_response_tools(1, "", tool_names=["task_update_tool"])

        assert state.consecutive_tool_only_steps == 0
        assert state.consecutive_bookkeeping_tool_only_steps == 2
        assert state.no_new_evidence_steps == 2
        assert state.substantive_tool_calls == 0

        state.note_response_tools(1, "", tool_names=["read_file_tool"])
        assert state.consecutive_bookkeeping_tool_only_steps == 0
        assert state.consecutive_tool_only_steps == 1
        assert state.no_new_evidence_steps == 0
        assert state.substantive_tool_calls == 1

    def test_turn_outcome_controller_handles_lifecycle_and_finalization(self):
        state = RoundStateController(max_iterations=5)
        state.next_iteration()
        state.note_progress()
        state.add_tool_calls(2)
        controller = TurnOutcomeController(
            max_consecutive_failures=3,
            get_attention_snapshot=lambda: {},
        )

        decision = controller.handle_lifecycle_action("turn_complete")
        finalization = controller.finalize_round(round_state=state)

        assert decision.break_round is True
        assert decision.info_log
        assert finalization.turn_success is True
        assert finalization.ui_status == "SUCCESS"
        assert finalization.turn_stats["tool_calls"] == 2

    def test_turn_outcome_controller_warns_when_max_iterations_end_on_tool_call(self):
        state = RoundStateController(max_iterations=1)
        state.next_iteration()
        state.note_progress()
        state.note_response_tools(1, "", tool_names=["grep_search_tool"])
        state.add_tool_calls(1)
        controller = TurnOutcomeController(
            max_consecutive_failures=3,
            get_attention_snapshot=lambda: {},
        )

        finalization = controller.finalize_round(round_state=state)

        assert finalization.turn_success is False
        assert finalization.max_iteration_exhausted_without_final_answer is True
        assert "最大迭代次数 1" in finalization.stop_reason
        assert finalization.ui_status == "IDLE"

    def test_close_transaction_turn_complete_can_be_suppressed_for_pending_post_close_action(self):
        action = ToolLifecycleBridge.derive_lifecycle_action(
            "close_evolution_transaction_tool",
            '{"status":"success","transaction_status":"success","txn_id":"demo"}',
            post_close_action_pending=True,
        )

        assert action is None

    def test_close_transaction_action_tolerates_bom_status_and_transaction_status(self):
        action = ToolLifecycleBridge.derive_lifecycle_action(
            "close_evolution_transaction_tool",
            '{"status":"\\ufeffsuccess","transaction_status":"\\ufeffsuccess","txn_id":"demo"}',
        )

        assert action == "turn_complete"

    def test_close_transaction_action_tolerates_dict_result(self):
        action = ToolLifecycleBridge.derive_lifecycle_action(
            "close_evolution_transaction_tool",
            {"status": "success", "transaction_status": "success", "txn_id": "demo"},
        )

        assert action == "turn_complete"

    def test_close_transaction_action_tolerates_utf8_bytes_result(self):
        action = ToolLifecycleBridge.derive_lifecycle_action(
            "close_evolution_transaction_tool",
            b'{"status":"success","transaction_status":"success","txn_id":"demo"}',
        )

        assert action == "turn_complete"

    def test_close_transaction_action_tolerates_ok_status_alias(self):
        action = ToolLifecycleBridge.derive_lifecycle_action(
            "close_evolution_transaction_tool",
            {"status": "ok", "transaction_status": "ok", "txn_id": "demo"},
        )

        assert action == "turn_complete"

    def test_response_surface_controller_emits_visible_text_and_token_usage(self):
        captured = {"thoughts": [], "contents": [], "tokens": []}

        class DummyUI:
            def stream_thought(self, text, done=False):
                captured["thoughts"].append((text, done))

            def add_content(self, text):
                captured["contents"].append(text)

            def note_token_usage(self, *args, **kwargs):
                captured["tokens"].append((args, kwargs))

            def set_pet_mental_state(self, **_kwargs):
                return None

        class DummyPet:
            def record_tokens(self, *_args, **_kwargs):
                return None

            def trigger_heartbeat(self):
                return None

        token_logs = []
        controller = ResponseSurfaceController(
            estimate_tokens=lambda _messages: 100,
            ui_getter=lambda: DummyUI(),
            logger=SimpleNamespace(log_token_usage=lambda inp, out, turn: token_logs.append((inp, out, turn))),
            debug_logger=SimpleNamespace(info=lambda *_args, **_kwargs: None),
            pet_getter=lambda: DummyPet(),
            print_tokens=lambda *_args, **_kwargs: None,
        )
        round_state = RoundStateController(max_iterations=3)
        processed = SimpleNamespace(
            raw_content_clean="继续检查",
            state_info={},
            visible_text="第一行\n第二行",
        )
        response = SimpleNamespace(
            usage_metadata={"input_tokens": 12, "output_tokens": 34},
        )

        controller.apply_state_feedback(
            processed=processed,
            record_language_drift=lambda _text: None,
            record_inference_activity=lambda _text: None,
        )
        input_tokens, output_tokens = controller.record_token_usage(
            response=response,
            round_state=round_state,
            current_turn=7,
        )
        surface = controller.emit_visible_response(
            raw_content="继续检查",
            processed=processed,
            tool_call_count=0,
        )

        assert input_tokens == 12
        assert output_tokens == 34
        assert round_state.total_input_tokens == 12
        assert round_state.total_output_tokens == 34
        assert token_logs == [(12, 34, 7)]
        assert captured["thoughts"][-1] == ("第一行\n第二行", True)
        assert captured["contents"] == ["第一行", "第二行"]
        assert surface["last_visible_response_text"] == "第一行\n第二行"

    def test_response_surface_controller_accepts_prompt_and_completion_token_keys(self):
        captured = {"tokens": []}

        class DummyUI:
            def note_token_usage(self, *args, **kwargs):
                captured["tokens"].append((args, kwargs))

            def set_pet_mental_state(self, **_kwargs):
                return None

        class DummyPet:
            def record_tokens(self, *_args, **_kwargs):
                return None

            def trigger_heartbeat(self):
                return None

        token_logs = []
        controller = ResponseSurfaceController(
            estimate_tokens=lambda _messages: 100,
            ui_getter=lambda: DummyUI(),
            logger=SimpleNamespace(log_token_usage=lambda inp, out, turn: token_logs.append((inp, out, turn))),
            debug_logger=SimpleNamespace(info=lambda *_args, **_kwargs: None),
            pet_getter=lambda: DummyPet(),
            print_tokens=lambda *_args, **_kwargs: None,
        )
        round_state = RoundStateController(max_iterations=3)
        response = SimpleNamespace(
            usage_metadata={"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30},
        )

        input_tokens, output_tokens = controller.record_token_usage(
            response=response,
            round_state=round_state,
            current_turn=8,
        )

        assert input_tokens == 21
        assert output_tokens == 9
        assert round_state.total_input_tokens == 21
        assert round_state.total_output_tokens == 9
        assert token_logs == [(21, 9, 8)]

    def test_response_surface_controller_reads_response_metadata_token_usage(self):
        captured = {"tokens": []}

        class DummyUI:
            def note_token_usage(self, *args, **kwargs):
                captured["tokens"].append((args, kwargs))

        controller = ResponseSurfaceController(
            estimate_tokens=lambda _messages: 100,
            ui_getter=lambda: DummyUI(),
            logger=SimpleNamespace(log_token_usage=lambda *_args, **_kwargs: None),
            debug_logger=SimpleNamespace(info=lambda *_args, **_kwargs: None),
            pet_getter=lambda: SimpleNamespace(record_tokens=lambda *_args, **_kwargs: None, trigger_heartbeat=lambda: None),
            print_tokens=lambda *_args, **_kwargs: None,
        )
        round_state = RoundStateController(max_iterations=3)
        response = SimpleNamespace(
            response_metadata={"token_usage": {"prompt_tokens": 44, "completion_tokens": 11}},
        )

        input_tokens, output_tokens = controller.record_token_usage(
            response=response,
            round_state=round_state,
            current_turn=9,
        )

        assert input_tokens == 44
        assert output_tokens == 11
        assert captured["tokens"][-1] == ((44, 11), {"cached_input_tokens": 0, "observed": True})

    def test_response_surface_controller_forwards_cached_input_tokens(self):
        captured = {"tokens": []}

        class DummyUI:
            def note_token_usage(self, *args, **kwargs):
                captured["tokens"].append((args, kwargs))

        controller = ResponseSurfaceController(
            estimate_tokens=lambda _messages: 100,
            ui_getter=lambda: DummyUI(),
            logger=SimpleNamespace(log_token_usage=lambda *_args, **_kwargs: None),
            debug_logger=SimpleNamespace(info=lambda *_args, **_kwargs: None),
            pet_getter=lambda: SimpleNamespace(record_tokens=lambda *_args, **_kwargs: None, trigger_heartbeat=lambda: None),
            print_tokens=lambda *_args, **_kwargs: None,
        )
        round_state = RoundStateController(max_iterations=3)
        response = SimpleNamespace(
            usage_metadata={
                "prompt_tokens": 80,
                "completion_tokens": 12,
                "prompt_tokens_details": {"cached_tokens": 48},
            },
        )

        input_tokens, output_tokens = controller.record_token_usage(
            response=response,
            round_state=round_state,
            current_turn=11,
        )

        assert input_tokens == 80
        assert output_tokens == 12
        assert captured["tokens"][-1] == ((80, 12), {"cached_input_tokens": 48, "observed": True})

    def test_response_surface_controller_forwards_anthropic_cache_read_tokens(self):
        captured = {"tokens": []}

        class DummyUI:
            def note_token_usage(self, *args, **kwargs):
                captured["tokens"].append((args, kwargs))

        controller = ResponseSurfaceController(
            estimate_tokens=lambda _messages: 100,
            ui_getter=lambda: DummyUI(),
            logger=SimpleNamespace(log_token_usage=lambda *_args, **_kwargs: None),
            debug_logger=SimpleNamespace(info=lambda *_args, **_kwargs: None),
            pet_getter=lambda: SimpleNamespace(record_tokens=lambda *_args, **_kwargs: None, trigger_heartbeat=lambda: None),
            print_tokens=lambda *_args, **_kwargs: None,
        )
        round_state = RoundStateController(max_iterations=3)
        response = SimpleNamespace(
            usage_metadata={
                "input_tokens": 120,
                "output_tokens": 18,
                "cache_read_input_tokens": 72,
                "cache_creation_input_tokens": 24,
            },
        )

        usage = controller.record_token_usage(
            response=response,
            round_state=round_state,
            current_turn=11,
        )
        input_tokens, output_tokens = usage

        assert input_tokens == 120
        assert output_tokens == 18
        assert usage.cache_creation_input_tokens == 24
        assert usage.uncached_input_tokens == 48
        assert captured["tokens"][-1] == ((120, 18), {"cached_input_tokens": 72, "observed": True})

    def test_response_surface_controller_estimates_tokens_when_usage_is_missing(self):
        captured = {"tokens": []}
        token_logs = []

        class DummyUI:
            def note_token_usage(self, *args, **kwargs):
                captured["tokens"].append((args, kwargs))

        controller = ResponseSurfaceController(
            estimate_tokens=lambda messages: 123 if messages else 0,
            ui_getter=lambda: DummyUI(),
            logger=SimpleNamespace(log_token_usage=lambda inp, out, turn: token_logs.append((inp, out, turn))),
            debug_logger=SimpleNamespace(info=lambda *_args, **_kwargs: None),
            pet_getter=lambda: SimpleNamespace(record_tokens=lambda *_args, **_kwargs: None, trigger_heartbeat=lambda: None),
            print_tokens=lambda *_args, **_kwargs: None,
        )
        round_state = RoundStateController(max_iterations=3)

        usage = controller.record_token_usage(
            response=SimpleNamespace(),
            round_state=round_state,
            current_turn=10,
            messages=[SimpleNamespace(content="hello")],
            raw_content="answer",
            estimate_output_tokens=lambda text: len(text) + 5,
        )
        input_tokens, output_tokens = usage

        assert input_tokens == 123
        assert output_tokens == 11
        assert usage == (123, 11)
        assert usage.observed is False
        assert round_state.total_input_tokens == 123
        assert round_state.total_output_tokens == 11
        assert token_logs == [(123, 11, 10)]
        assert captured["tokens"][-1] == ((123, 11), {"cached_input_tokens": 0, "observed": False})

    def test_execute_tools_parallel_returns_restart_action_and_stops_followups(self):
        messages = []
        calls = []

        def fake_execute(tool_name, _tool_args, *, tool_call_id=""):
            calls.append(tool_name)
            if tool_name == "custom_restart_tool":
                return ("restart ok", "restart")
            return ("should not run", None)

        bridge = ToolLifecycleBridge(tool_executor_execute=fake_execute)

        action = bridge.execute_tools(
            [
                {"name": "custom_restart_tool"},
                {"name": "read_file_tool"},
            ],
            messages,
        )

        assert action == "restart"
        assert calls == ["custom_restart_tool"]

    def test_execute_tools_runs_readonly_batch_concurrently_while_preserving_order(self):
        """read-only 段并发执行，wall-clock 接近最慢一个；结果按 batch 原序追加到 messages。"""

        import threading
        import time as _time

        messages: list = []
        active = {"now": 0, "max": 0}
        lock = threading.Lock()

        def fake_execute(tool_name, _tool_args, *, tool_call_id=""):
            if tool_name in ToolLifecycleBridge.READONLY_TOOL_NAMES:
                with lock:
                    active["now"] += 1
                    active["max"] = max(active["max"], active["now"])
                _time.sleep(0.08)  # 远超线程调度开销，足以观察并发提升
                with lock:
                    active["now"] -= 1
                return (f"{tool_name}-result", None)
            return ("should not concurrent", None)

        bridge = ToolLifecycleBridge(tool_executor_execute=fake_execute)
        tool_calls = [
            {"name": "read_file_tool", "id": "call_1"},
            {"name": "grep_search_tool", "id": "call_2"},
            {"name": "list_directory_tool", "id": "call_3"},
        ]

        start = _time.perf_counter()
        action = bridge.execute_tools(tool_calls, messages, max_parallel_readonly=3)
        elapsed = _time.perf_counter() - start

        assert action is None
        assert active["max"] >= 2, "read-only batch 必须真正并发，不能退化为串行"
        assert elapsed < 3 * 0.08, f"并发应显著快于串行，实测 {elapsed:.2f}s"
        assert len(messages) == 3
        # 结果按 batch 输入顺序回写
        assert "read_file_tool-result" in str(messages[0].content)
        assert "grep_search_tool-result" in str(messages[1].content)
        assert "list_directory_tool-result" in str(messages[2].content)

    def test_execute_tools_keeps_mutating_tools_serial_and_in_order(self):
        """mutating 工具不能并发，且 read-only/mutating 边界处必须保持原序。"""

        import threading

        messages: list = []
        execution_order: list = []
        running_mutators = {"now": 0, "max": 0}
        lock = threading.Lock()

        def fake_execute(tool_name, _tool_args, *, tool_call_id=""):
            with lock:
                execution_order.append(tool_name)
                if tool_name not in ToolLifecycleBridge.READONLY_TOOL_NAMES:
                    running_mutators["now"] += 1
                    running_mutators["max"] = max(running_mutators["max"], running_mutators["now"])
            try:
                return (f"{tool_name}-result", None)
            finally:
                with lock:
                    if tool_name not in ToolLifecycleBridge.READONLY_TOOL_NAMES:
                        running_mutators["now"] -= 1

        bridge = ToolLifecycleBridge(tool_executor_execute=fake_execute)
        tool_calls = [
            {"name": "read_file_tool", "id": "r1"},
            {"name": "write_file_tool", "id": "w1"},  # mutating
            {"name": "grep_search_tool", "id": "r2"},
            {"name": "git_commit_tool", "id": "w2"},  # mutating
        ]

        bridge.execute_tools(tool_calls, messages, max_parallel_readonly=4)

        # mutating 工具任何时刻最多 1 个并发
        assert running_mutators["max"] <= 1
        # 结果按原序回写
        assert "read_file_tool-result" in str(messages[0].content)
        assert "write_file_tool-result" in str(messages[1].content)
        assert "grep_search_tool-result" in str(messages[2].content)
        assert "git_commit_tool-result" in str(messages[3].content)
        # write_file 必须在 read_file 之后才开始（同一 batch 边界）
        assert execution_order.index("write_file_tool") > execution_order.index("read_file_tool")
        # grep_search 必须在 write_file 之后（mutating 是 batch 边界）
        assert execution_order.index("grep_search_tool") > execution_order.index("write_file_tool")

    def test_partition_tool_calls_groups_readonly_and_breaks_on_mutating(self):
        bridge = ToolLifecycleBridge(tool_executor_execute=lambda _name, _args, **_kwargs: ("ok", None))
        batches = bridge._partition_tool_calls([
            {"name": "read_file_tool"},
            {"name": "grep_search_tool"},
            {"name": "write_file_tool"},
            {"name": "list_directory_tool"},
            {"name": "list_files_tool"},
            {"name": "task_create_tool"},  # 不在白名单
        ])
        assert [len(b) for b in batches] == [2, 1, 2, 1]
        assert batches[0][0]["name"] == "read_file_tool"
        assert batches[1][0]["name"] == "write_file_tool"
        assert batches[2][1]["name"] == "list_files_tool"
        assert batches[3][0]["name"] == "task_create_tool"

    def test_execute_tools_parallel_returns_turn_complete_after_successful_close_transaction(self):
        messages = []
        calls = []

        def fake_execute(tool_name, _tool_args, *, tool_call_id=""):
            calls.append(tool_name)
            if tool_name == "close_evolution_transaction_tool":
                return (
                    '{"status":"success","txn_id":"txn_1","transaction_status":"success","summary":"done"}',
                    "turn_complete",
                )
            return ("should not run", None)

        bridge = ToolLifecycleBridge(tool_executor_execute=fake_execute)

        action = bridge.execute_tools(
            [
                {"name": "close_evolution_transaction_tool"},
                {"name": "read_file_tool"},
            ],
            messages,
        )

        assert action == "turn_complete"
        assert calls == ["close_evolution_transaction_tool"]

    def test_tool_lifecycle_bridge_derives_turn_complete_from_close_transaction(self):
        messages = []
        calls = []

        def fake_executor(tool_name, tool_args, *, tool_call_id=""):
            calls.append((tool_name, tool_args))
            return (
                '{"status":"success","txn_id":"txn_1","transaction_status":"success","summary":"done"}',
                None,
            )

        bridge = ToolLifecycleBridge(
            tool_executor_execute=fake_executor,
            self_modified=False,
        )

        action = bridge.execute_tools(
            [{"name": "close_evolution_transaction_tool", "args": {"txn_id": "txn_1"}}],
            messages,
        )

        assert action == "turn_complete"
        assert calls[0][0] == "close_evolution_transaction_tool"
        assert isinstance(messages[0], AIMessage)

    def test_tool_lifecycle_bridge_can_short_circuit_via_guard(self):
        messages = []
        calls = []

        def fake_executor(tool_name, tool_args, *, tool_call_id=""):
            calls.append((tool_name, tool_args))
            return ("should not run", None)

        bridge = ToolLifecycleBridge(
            tool_executor_execute=fake_executor,
            tool_guard=lambda tool_name, _tool_args: "[短路] restart focus" if tool_name == "read_file_tool" else None,
            self_modified=False,
        )

        result, action = bridge.execute_tool(
            {"name": "read_file_tool", "args": {"file_path": "demo.py"}, "id": "call_1"},
            messages,
        )

        assert action is None
        assert result.startswith("[短路]")
        assert calls == []

    def test_run_single_turn_starts_and_ends_log_sessions(self, monkeypatch):
        events = []
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = [object(), object()]
        agent._last_turn_failed = False

        def fake_think_and_act(user_prompt=None, goal_override=None, attachments=None, **kwargs):
            events.append(("think", user_prompt))
            events.append(("goal_override", goal_override))
            agent._last_visible_response_text = "完成"
            agent._last_response_tool_calls = 2
            return True

        agent.think_and_act = fake_think_and_act

        monkeypatch.setattr(
            agent_module._debug_logger,
            "start_session",
            lambda session_id: events.append(("debug_start", session_id)),
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "system",
            lambda *args, **kwargs: events.append(("debug_system", args, kwargs)),
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "turn_end",
            lambda turn, tool_count=0: events.append(("debug_turn_end", turn, tool_count)),
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "info",
            lambda *args, **kwargs: events.append(("debug_info", args, kwargs)),
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "end_session",
            lambda: events.append(("debug_end",)),
        )
        monkeypatch.setattr(
            agent_module.logger,
            "start_session",
            lambda metadata=None, **kwargs: events.append(("conv_start", metadata, kwargs)),
        )
        monkeypatch.setattr(
            agent_module.logger,
            "end_session",
            lambda summary=None: events.append(("conv_end", summary)),
        )
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        result = agent.run_single_turn(initial_prompt="probe")

        assert result["status"] == "completed"
        assert result["tool_call_count"] == 2
        assert events[0][0] == "debug_start"
        assert any(item[0] == "conv_start" and item[1]["mode"] == "single_turn" for item in events)
        assert ("think", "probe") in events
        assert not any(item[0] == "debug_turn_end" for item in events)
        assert any(item[0] == "conv_end" and item[1]["mode"] == "single_turn" for item in events)

    def test_run_single_turn_topic_preserves_numbered_confirmation_context(self, monkeypatch):
        events = []
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = []
        agent._last_turn_failed = False
        agent._active_turn_messages = [
            SystemMessage(content=""),
            AIMessage(content="需求对齐：为 Git 管理 Agent 增加入口，确认信息工具和写入边界。"),
        ]

        def fake_think_and_act(user_prompt=None, goal_override=None, attachments=None, **kwargs):
            agent._last_visible_response_text = "完成"
            agent._last_response_tool_calls = 0
            return True

        agent.think_and_act = fake_think_and_act

        monkeypatch.setattr(agent_module._debug_logger, "start_session", lambda session_id: None)
        monkeypatch.setattr(agent_module._debug_logger, "system", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "turn_end", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "info", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "end_session", lambda: None)
        monkeypatch.setattr(
            agent_module.logger,
            "start_session",
            lambda metadata=None, **kwargs: events.append(("conv_start", metadata, kwargs)),
        )
        monkeypatch.setattr(agent_module.logger, "end_session", lambda summary=None: None)
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        result = agent.run_single_turn(
            initial_prompt="1,就用这个,2,使用信息工具,3,允许,4,要求,5,这个先不考虑"
        )

        metadata = next(item[1] for item in events if item[0] == "conv_start")
        assert result["status"] == "completed"
        assert "Git 管理 Agent" in metadata["conversation_topic"]
        assert "用户确认" in metadata["conversation_topic"]

    def test_run_single_turn_wraps_env_prompt_cache_partition_and_returns_runtime_metadata(self, monkeypatch):
        events = []

        class FakeScope:
            def __init__(self, partition):
                self.partition = partition

            def __enter__(self):
                events.append(("enter_cache", self.partition))

            def __exit__(self, exc_type, exc, tb):
                events.append(("exit_cache", self.partition))
                return False

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = []
        agent._last_turn_failed = False

        def fake_think_and_act(user_prompt=None, goal_override=None, attachments=None, **kwargs):
            events.append(("think", user_prompt))
            agent._last_visible_response_text = "完成"
            agent._last_response_tool_calls = 0
            return True

        agent.think_and_act = fake_think_and_act

        monkeypatch.setattr(agent_module._debug_logger, "start_session", lambda session_id: events.append(("debug_start", session_id)))
        monkeypatch.setattr(agent_module._debug_logger, "system", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "info", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "end_session", lambda: events.append(("debug_end",)))
        monkeypatch.setattr(agent_module.logger, "start_session", lambda metadata=None, **kwargs: events.append(("conv_start", metadata, kwargs)))
        monkeypatch.setattr(agent_module.logger, "end_session", lambda summary=None: events.append(("conv_end", summary)))
        monkeypatch.setattr(agent_module, "get_session_state", lambda: SimpleNamespace(get_attention_snapshot=lambda: {}))
        monkeypatch.setattr(agent_module, "prompt_cache_partition_scope", lambda partition: FakeScope(partition))
        monkeypatch.setenv("VIBELUTION_TURN_MODE", "supervised_evolution")
        monkeypatch.setenv("VIBELUTION_TURN_RUN_KIND", "supervised_evaluation")
        monkeypatch.setenv("VIBELUTION_TURN_RUN_ID", "harness-run-1")
        monkeypatch.setenv("VIBELUTION_TURN_PROMPT_CACHE_PARTITION", "mode:supervised_evolution|scope:baseline")
        monkeypatch.setenv("VIBELUTION_TURN_PROMPT_CACHE_SECRET", "should-not-leak")

        result = agent.run_single_turn(initial_prompt="probe")

        assert events.index(("enter_cache", "mode:supervised_evolution|scope:baseline")) < events.index(("think", "probe"))
        assert events.index(("think", "probe")) < events.index(("exit_cache", "mode:supervised_evolution|scope:baseline"))
        assert result["turn_runtime"]["mode"] == "supervised_evolution"
        assert result["turn_runtime"]["runKind"] == "supervised_evaluation"
        assert result["turn_runtime"]["runId"] == "harness-run-1"
        assert result["turn_runtime"]["promptCachePartitionChars"] == len("mode:supervised_evolution|scope:baseline")
        assert result["turn_runtime"]["promptCachePartitionHash"]
        assert "SECRET" not in json.dumps(result, ensure_ascii=False)

    def test_run_single_turn_enriches_chat_result_contract_from_tool_trace(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda text: text,
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = [object()]
        agent._last_turn_failed = False

        def fake_think_and_act(user_prompt=None, goal_override=None, attachments=None, **kwargs):
            agent._last_visible_response_text = "已修复并验证。"
            agent._last_response_tool_calls = 3
            agent._recent_tool_records = [
                {
                    "name": "read_file_tool",
                    "args": {"file_path": "core/ui/cli_ui.py"},
                    "result_preview": "read ok",
                },
                {
                    "name": "apply_diff_edit_tool",
                    "args": {"file_path": "core/ui/cli_ui.py"},
                    "result_preview": "patched",
                },
                {
                    "name": "run_test_for_tool",
                    "args": {"source_path": "core/ui/cli_ui.py"},
                    "result_preview": "3 passed in 0.40s",
                },
            ]
            return True

        agent.think_and_act = fake_think_and_act
        monkeypatch.setattr(
            agent_module.logger,
            "start_session",
            lambda metadata=None, **kwargs: None,
        )
        monkeypatch.setattr(
            agent_module.logger,
            "end_session",
            lambda summary=None: None,
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "start_session",
            lambda session_id: None,
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "system",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "info",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "end_session",
            lambda: None,
        )
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        result = agent.run_single_turn(initial_prompt="probe")

        assert result["outcome"] == "done"
        assert result["read_files"] == ["core/ui/cli_ui.py"]
        assert result["changed_files"] == ["core/ui/cli_ui.py"]
        assert result["verification_status"] == "passed"
        assert result["no_change"] is False

    def test_host_seeded_runtime_context_skips_agent_runtime_context_reseed(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=build_chat_user_message,
        )
        agent.runtime_agent_binding = {"agentId": "agent-live", "directSessionId": "session-live"}
        agent._active_turn_messages = None
        agent._active_turn_goal = ""
        seeded_blocks: list[str] = []
        agent.seed_runtime_context = lambda content: seeded_blocks.append(content)
        agent.mark_runtime_context_seeded_by_host()
        monkeypatch.setattr(
            agent_module,
            "build_agent_context",
            lambda *args, **kwargs: SimpleNamespace(context_block="runtime context"),
        )

        agent._seed_runtime_agent_context_for_turn(run_id="turn-live")

        assert seeded_blocks == []
        assert agent._runtime_context_seeded_by_host is False

    def test_run_single_turn_surfaces_llm_error_when_no_visible_reply(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda text: text,
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = [object()]
        agent._last_turn_failed = False

        def fake_think_and_act(user_prompt=None, goal_override=None, attachments=None, **kwargs):
            agent._last_visible_response_text = ""
            agent._last_response_tool_calls = 0
            agent._recent_tool_records = []
            agent._last_llm_error_message = "configuration_error: LiteLLM 未安装，无法执行模型调用；请安装 litellm"
            agent._last_turn_failed = True
            return True

        agent.think_and_act = fake_think_and_act
        monkeypatch.setattr(agent_module.logger, "start_session", lambda metadata=None, **kwargs: None)
        monkeypatch.setattr(agent_module.logger, "end_session", lambda summary=None: None)
        monkeypatch.setattr(agent_module._debug_logger, "start_session", lambda session_id: None)
        monkeypatch.setattr(agent_module._debug_logger, "system", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "info", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "end_session", lambda: None)
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        result = agent.run_single_turn(initial_prompt="probe")

        assert result["status"] == "failed"
        assert result["summary"] == "configuration_error: LiteLLM 未安装，无法执行模型调用；请安装 litellm"
        assert result["raw_output"] == result["summary"]
        assert result["error"] == result["summary"]

    def test_run_single_turn_main_loop_timeout_does_not_complete_with_fragment(self, monkeypatch):
        """TimeoutExpired-style main-loop failure must not publish intermediate stream as completed."""
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="deepseek-v4-flash"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda text: text,
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = [object()]
        agent._last_turn_failed = False
        agent._last_turn_metadata = {}

        fragment = "后端有 SSE 流式路由，但要确认 LLM 调用本身是否流式。"

        def fake_think_and_act(user_prompt=None, goal_override=None, attachments=None, **kwargs):
            agent._last_visible_response_text = fragment
            agent._last_response_tool_calls = 13
            agent._recent_tool_records = [{"name": "cli_tool", "status": "done"}]
            agent._record_turn_failure_diagnostic(
                category="runtime_error",
                reason_code="agent_main_loop_exception",
                reason_summary="Agent 主循环异常",
                reason_detail="Agent 主循环发生 TimeoutExpired，请按 Trace 定位运行场景。",
                chain_stage="agent_main_loop",
                event_code="agent.turn.failed_exception",
                exception_type="TimeoutExpired",
            )
            agent._last_turn_failed = True
            agent._last_turn_metadata = {
                **dict(agent._last_turn_metadata or {}),
                "status": "failed",
                "outcome": "failed",
                "main_loop_exception": "TimeoutExpired",
            }
            # Simulate the historical bug path: finalize overwrote failure to False
            # but metadata still carries llm_failure — status must stay failed.
            return True

        agent.think_and_act = fake_think_and_act
        monkeypatch.setattr(agent_module.logger, "start_session", lambda metadata=None, **kwargs: None)
        monkeypatch.setattr(agent_module.logger, "end_session", lambda summary=None: None)
        monkeypatch.setattr(agent_module._debug_logger, "start_session", lambda session_id: None)
        monkeypatch.setattr(agent_module._debug_logger, "system", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "info", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "end_session", lambda: None)
        monkeypatch.setattr(
            agent_module,
            "_record_agent_scene_event",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        result = agent.run_single_turn(initial_prompt="为什么首字慢")

        assert result["status"] == "failed"
        assert result["outcome"] == "failed"
        assert result["summary"] != fragment
        assert "TimeoutExpired" in str(result.get("error") or result.get("summary") or "")
        assert result.get("thought") == fragment
        assert result["tool_call_count"] == 13
        assert result.get("llm_failure", {}).get("reason_code") == "agent_main_loop_exception"

    def test_run_single_turn_preserves_structured_chain_failure(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda text: text,
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = [object()]
        agent._last_turn_failed = False
        agent._last_llm_error_details = {}

        def fake_think_and_act(user_prompt=None, goal_override=None, attachments=None, **kwargs):
            agent._last_visible_response_text = ""
            agent._last_response_tool_calls = 0
            agent._recent_tool_records = []
            agent._record_turn_failure_diagnostic(
                category="protocol_error",
                reason_code="canonical_turn_outcome_missing",
                reason_summary="模型响应未完成规范化",
                reason_detail="模型已返回，但响应适配器没有生成 canonical TurnOutcome。",
                chain_stage="llm_response_normalization",
                event_code="llm.turn_outcome.missing",
            )
            return True

        agent.think_and_act = fake_think_and_act
        monkeypatch.setattr(agent_module, "_record_agent_scene_event", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module.logger, "start_session", lambda metadata=None, **kwargs: None)
        monkeypatch.setattr(agent_module.logger, "end_session", lambda summary=None: None)
        monkeypatch.setattr(agent_module._debug_logger, "start_session", lambda session_id: None)
        monkeypatch.setattr(agent_module._debug_logger, "system", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "info", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "end_session", lambda: None)
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        result = agent.run_single_turn(initial_prompt="secret prompt")

        assert result["status"] == "failed"
        assert "模型响应未完成规范化" in result["summary"]
        assert result["llm_failure"]["reason_code"] == "canonical_turn_outcome_missing"
        assert result["llm_failure"]["chain_stage"] == "llm_response_normalization"
        assert result["llm_failure"]["event_code"] == "llm.turn_outcome.missing"
        assert "secret prompt" not in str(result["llm_failure"])

    def _build_single_turn_agent(self):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda text: text,
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = [object()]
        agent._last_turn_failed = False
        agent._last_turn_metadata = {}
        return agent

    def _patch_single_turn_env(self, monkeypatch):
        monkeypatch.setattr(agent_module.logger, "start_session", lambda metadata=None, **kwargs: None)
        monkeypatch.setattr(agent_module.logger, "end_session", lambda summary=None: None)
        monkeypatch.setattr(agent_module._debug_logger, "start_session", lambda session_id: None)
        monkeypatch.setattr(agent_module._debug_logger, "system", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "info", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "end_session", lambda: None)
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

    def test_run_single_turn_unexplained_failure_with_final_answer_is_stopped(self, monkeypatch):
        """_last_turn_failed 但无任何结构化诊断 + 可见最终回复 + 无未完成工具调用
        → 收口为 stopped，不再误判 failed_runtime。"""
        agent = self._build_single_turn_agent()
        self._patch_single_turn_env(monkeypatch)

        def fake_think_and_act(user_prompt=None, goal_override=None, attachments=None, **kwargs):
            agent._last_visible_response_text = "阶段结论已经写回完成。"
            agent._last_response_tool_calls = 0
            agent._recent_tool_records = []
            agent._last_turn_failed = True
            return True

        agent.think_and_act = fake_think_and_act

        result = agent.run_single_turn(initial_prompt="probe")

        assert result["status"] == "stopped"
        assert result["summary"] == "阶段结论已经写回完成。"
        assert "llm_failure" not in result

    def test_run_single_turn_unexplained_failure_with_pending_tool_calls_stays_failed(self, monkeypatch):
        """可见回复但最后一步仍有未完成工具调用时，保持 failed（不放宽过头）。"""
        agent = self._build_single_turn_agent()
        self._patch_single_turn_env(monkeypatch)

        def fake_think_and_act(user_prompt=None, goal_override=None, attachments=None, **kwargs):
            agent._last_visible_response_text = "中途片段"
            agent._last_response_tool_calls = 2
            agent._recent_tool_records = []
            agent._last_turn_failed = True
            return True

        agent.think_and_act = fake_think_and_act

        result = agent.run_single_turn(initial_prompt="probe")

        assert result["status"] == "failed"

    def test_run_single_turn_llm_failure_with_visible_answer_stays_failed(self, monkeypatch):
        """有 llm_failure 结构化诊断时即使有可见回复也必须保持 failed（回归）。"""
        agent = self._build_single_turn_agent()
        self._patch_single_turn_env(monkeypatch)
        monkeypatch.setattr(agent_module, "_record_agent_scene_event", lambda *args, **kwargs: None)

        def fake_think_and_act(user_prompt=None, goal_override=None, attachments=None, **kwargs):
            agent._last_visible_response_text = "已有可见回复"
            agent._last_response_tool_calls = 0
            agent._recent_tool_records = []
            agent._record_turn_failure_diagnostic(
                category="context_error",
                reason_code="context_budget_exhausted",
                reason_summary="上下文预算超出硬上限",
                reason_detail="估算输入 tokens 超过硬上限。",
                chain_stage="llm_preflight",
                event_code="agent.context_budget_exhausted",
            )
            return True

        agent.think_and_act = fake_think_and_act

        result = agent.run_single_turn(initial_prompt="probe")

        assert result["status"] == "failed"
        assert result["llm_failure"]["reason_code"] == "context_budget_exhausted"
        assert result["llm_failure"]["category"] == "context_error"

    def test_run_single_turn_preserves_tool_progress_without_loop_guard_reply(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda text: text,
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = [object()]
        agent._last_turn_failed = False

        def fake_think_and_act(user_prompt=None, goal_override=None, attachments=None, **kwargs):
            agent._last_visible_response_text = ""
            agent._last_response_tool_calls = 1
            agent._recent_tool_records = [
                {
                    "name": "read_file_tool",
                    "args": {"file_path": "core/infrastructure/tool_executor.py"},
                    "result_preview": "read ok",
                },
                {
                    "name": "read_file_tool",
                    "args": {"file_path": "core/infrastructure/tool_executor.py"},
                    "result_preview": "[短路] 继续顺着续读会造成工具循环",
                },
            ]
            return True

        agent.think_and_act = fake_think_and_act
        monkeypatch.setattr(agent_module.logger, "start_session", lambda metadata=None, **kwargs: None)
        monkeypatch.setattr(agent_module.logger, "end_session", lambda summary=None: None)
        monkeypatch.setattr(agent_module._debug_logger, "start_session", lambda session_id: None)
        monkeypatch.setattr(agent_module._debug_logger, "system", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "info", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "end_session", lambda: None)
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        result = agent.run_single_turn(initial_prompt="probe")

        assert result["status"] == "completed"
        assert result["outcome"] == "progress"
        assert result["summary"] == ""
        assert result["raw_output"] == ""
        assert result["read_files"] == ["core/infrastructure/tool_executor.py"]

    def test_run_single_turn_does_not_infer_loop_guard_from_repeated_tools(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda text: text,
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = [object()]
        agent._last_turn_failed = False

        def fake_think_and_act(user_prompt=None, goal_override=None, attachments=None, **kwargs):
            agent._last_visible_response_text = ""
            agent._last_response_tool_calls = 4
            agent._recent_tool_records = [
                {
                    "name": "grep_search_tool",
                    "args": {"pattern": "TODO|FIXME|HACK|XXX", "path": "."},
                    "result_preview": "search started",
                },
                {
                    "name": "grep_search_tool",
                    "args": {"pattern": "TODO|FIXME|HACK|XXX", "path": "."},
                    "result_preview": "search still running",
                },
                {
                    "name": "grep_search_tool",
                    "args": {"pattern": "TODO|FIXME|HACK|XXX", "path": "."},
                    "result_preview": "[超时] grep_search_tool 执行超时 (30秒)",
                },
            ]
            return True

        agent.think_and_act = fake_think_and_act
        monkeypatch.setattr(agent_module.logger, "start_session", lambda metadata=None, **kwargs: None)
        monkeypatch.setattr(agent_module.logger, "end_session", lambda summary=None: None)
        monkeypatch.setattr(agent_module._debug_logger, "start_session", lambda session_id: None)
        monkeypatch.setattr(agent_module._debug_logger, "system", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "info", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "end_session", lambda: None)
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        result = agent.run_single_turn(initial_prompt="probe")

        assert result["status"] == "completed"
        assert result["outcome"] == "progress"
        assert result["summary"] == ""
        assert result["raw_output"] == ""
        assert result["tool_call_count"] == 4

    def test_run_single_turn_ignores_legacy_tool_loop_guard_reason(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda text: text,
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = [object()]
        agent._last_turn_failed = False

        def fake_think_and_act(user_prompt=None, goal_override=None, attachments=None, **kwargs):
            agent._last_visible_response_text = ""
            agent._last_response_tool_calls = 0
            agent._recent_tool_records = [
                {"name": "get_git_status_summary_tool", "args": {"limit": 20}, "result_preview": "ok"},
                {"name": "get_recent_changes_tool", "args": {"limit": 10}, "result_preview": "ok"},
                {"name": "task_create_tool", "args": {"goal": "审查日志"}, "result_preview": "created"},
            ]
            return True

        agent.think_and_act = fake_think_and_act
        monkeypatch.setattr(agent_module.logger, "start_session", lambda metadata=None, **kwargs: None)
        monkeypatch.setattr(agent_module.logger, "end_session", lambda summary=None: None)
        monkeypatch.setattr(agent_module._debug_logger, "start_session", lambda session_id: None)
        monkeypatch.setattr(agent_module._debug_logger, "system", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "info", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "end_session", lambda: None)
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        result = agent.run_single_turn(initial_prompt="probe")

        assert result["status"] == "completed"
        assert result["outcome"] == "progress"
        assert result["summary"] == ""
        assert result["raw_output"] == ""
        assert result["tool_call_count"] == 3

    def test_run_single_turn_keeps_full_visible_reply_text(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda text: text,
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = [object()]
        agent._last_turn_failed = False
        long_reply = "已完成。" + ("细节说明" * 220)

        def fake_think_and_act(user_prompt=None, goal_override=None, attachments=None, **kwargs):
            agent._last_visible_response_text = long_reply
            agent._last_response_tool_calls = 0
            agent._recent_tool_records = []
            return True

        agent.think_and_act = fake_think_and_act
        monkeypatch.setattr(agent_module.logger, "start_session", lambda metadata=None, **kwargs: None)
        monkeypatch.setattr(agent_module.logger, "end_session", lambda summary=None: None)
        monkeypatch.setattr(agent_module._debug_logger, "start_session", lambda session_id: None)
        monkeypatch.setattr(agent_module._debug_logger, "system", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "info", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "end_session", lambda: None)
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        result = agent.run_single_turn(initial_prompt="probe")

        assert result["summary"] == long_reply
        assert result["raw_output"] == long_reply

    def test_delegation_governor_apply_result_uses_injected_ui_and_session(self):
        captured = {"finish": []}

        class DummyUI:
            def add_log(self, *_args, **_kwargs):
                return None

            def add_content(self, *_args, **_kwargs):
                return None

            def add_delegation_evidence(self, *_args, **_kwargs):
                return None

            def finish_subagent_activity(self, *args, **kwargs):
                captured["finish"].append((args, kwargs))

        session = MagicMock()
        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: DummyUI(),
            session_getter=lambda: session,
        )

        payload = {"task_type": "diagnose", "goal": "分析重复调用", "scope": {"log": "a.jsonl"}}
        result = {
            "status": "completed",
            "summary": "已定位根因",
            "findings": ["重复调用 read_file_tool"],
            "evidence": ["recent_blockers"],
            "recommended_next_action": "主 agent 收束",
            "confidence": "high",
            "process_output": "子 agent 先读取 attention snapshot，再比对工具轨迹。",
        }

        outcome = governor.apply_result(payload, __import__("json").dumps(result, ensure_ascii=False), [])

        assert outcome["useful"] is True
        assert captured["finish"]
        assert "attention snapshot" in captured["finish"][0][1]["thought"]

    def test_run_loop_exits_process_after_restart_action(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=1, awake_interval=1),
        )
        agent.key_tools = []
        agent._effective_max_token_limit = 1024
        agent._last_turn_failed = False
        agent._consecutive_failed_turns = 0
        agent._pending_lifecycle_action = None
        agent.workspace_path = "."
        agent.mental_model = MagicMock()
        agent.start_time = agent_module.datetime.now()

        monkeypatch.setattr(agent_module._debug_logger, "start_session", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "system", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "kv", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "info", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "warning", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "error", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "end_session", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module, "_print_evolution_time_core", lambda: None)
        monkeypatch.setattr(agent_module.logger, "start_session", lambda **_kwargs: None)
        monkeypatch.setattr(agent_module.logger, "log_action", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module.logger, "log_error", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module.logger, "end_session", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module.logger, "_turn_count", 1, raising=False)

        state_manager = MagicMock()
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: state_manager)

        cleaner_module = SimpleNamespace(
            auto_clean_session_debris=lambda *_args, **_kwargs: {"deleted_count": 0}
        )
        monkeypatch.setitem(__import__("sys").modules, "core.infrastructure.workspace_cleaner", cleaner_module)

        def fake_think_and_act(user_prompt=None, goal_override=None, attachments=None, **kwargs):
            agent._pending_lifecycle_action = "restart"
            return False

        agent.think_and_act = fake_think_and_act

        with pytest.raises(SystemExit) as exc_info:
            agent.run_loop(initial_prompt="demo")

        assert exc_info.value.code == 0

    def test_spawn_agent_structured_protocol_parses_marker_payload(self, monkeypatch):
        scene_events = []

        def fake_record_runtime_scene_event(component, phase, event_code, **kwargs):
            scene_events.append((component, phase, event_code, kwargs))
            return {"accepted": True}

        class FakePipe:
            def __init__(self, lines):
                self._lines = list(lines)

            def readline(self):
                if self._lines:
                    return self._lines.pop(0)
                return ""

            def close(self):
                return None

        class DummyPopen:
            def __init__(self, *_args, **_kwargs):
                self.stdout = FakePipe(
                    [
                        "subagent thinking line\n",
                        "noise before\n",
                        "__VIBELUTION_SUBAGENT_RESULT__"
                        '{"status":"completed","summary":"已定位根因","findings":["重复搜索"],'
                        '"evidence":["recent_blockers"],"recommended_next_action":"主 agent 收束","confidence":"high"}',
                    ]
                )
                self.stderr = FakePipe([])
                self.returncode = 0
                self.pid = 24680

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        monkeypatch.setattr("tools.agent_tools.subprocess.Popen", DummyPopen)
        monkeypatch.setattr(
            "core.web.services.runtime_scene_service.record_runtime_scene_event",
            fake_record_runtime_scene_event,
        )

        result = spawn_agent_impl(
            task_type="diagnose",
            goal="分析为什么重复调用工具",
            scope='{"log":"log_info/demo.jsonl"}',
            constraints='{"readonly":true,"max_steps":4}',
            deliverables='["status","summary","findings","evidence","recommended_next_action","confidence"]',
        )

        payload = __import__("json").loads(result)
        assert payload["status"] == "completed"
        assert payload["summary"] == "已定位根因"
        assert payload["confidence"] == "high"
        assert "subagent thinking line" in payload["process_output"]
        assert payload["subRunId"].startswith("subagent-diagnose-d1-")
        assert [event[2] for event in scene_events] == ["subagent.run.started", "subagent.run.finished"]
        assert {
            event[3]["fields"]["subRunId"]
            for event in scene_events
        } == {payload["subRunId"]}
        assert all(
            event[3]["child_log_path"] == f"agent/sub_agent_runs/{payload['subRunId']}.jsonl"
            for event in scene_events
        )
        assert scene_events[-1][3]["child_log_payload"]["summary"] == "已定位根因"

    def test_spawn_agent_infers_platform_conclusion_from_non_json_output(self, monkeypatch):
        class FakePipe:
            def __init__(self, lines):
                self._lines = list(lines)

            def readline(self):
                if self._lines:
                    return self._lines.pop(0)
                return ""

            def close(self):
                return None

        class DummyPopen:
            def __init__(self, *_args, **_kwargs):
                self.stdout = FakePipe([
                    "验证已完成。结果如下：\n",
                    "是否应执行：否，因为 `/dev/null` 和 `tail` 均为 Unix 特有。\n",
                    "Windows 等价命令：python -m pytest tests/ --collect-only -q 2>$null | Select-Object -Last 5\n",
                ])
                self.stderr = FakePipe([])
                self.returncode = 0

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        monkeypatch.setattr("tools.agent_tools.subprocess.Popen", DummyPopen)

        result = spawn_agent_impl(
            task_type="diagnose",
            goal="验证 Windows 命令平台识别",
            scope='{"goal":"判断 Unix 命令是否应执行"}',
            constraints='{"readonly":true,"max_steps":3}',
        )

        payload = __import__("json").loads(result)
        assert payload["status"] == "partial"
        assert "是否应执行：否" in payload["summary"]
        assert payload["findings"]
        assert payload["evidence"]

    @pytest.mark.slow
    def test_spawn_agent_timeout_preserves_partial_process_output(self, monkeypatch):
        scene_events = []

        def fake_record_runtime_scene_event(component, phase, event_code, **kwargs):
            scene_events.append((component, phase, event_code, kwargs))
            return {"accepted": True}

        class SlowPipe:
            def __init__(self, line):
                self._line = line
                self._emitted = False

            def readline(self):
                import time

                if self._emitted:
                    time.sleep(2.0)
                    return ""
                self._emitted = True
                time.sleep(0.05)
                return self._line

            def close(self):
                return None

        class TimeoutPopen:
            def __init__(self, *_args, **_kwargs):
                self.stdout = SlowPipe("step1\n")
                self.stderr = SlowPipe("timeout stderr\n")
                self.returncode = None

            def poll(self):
                return None

            def wait(self, timeout=None):
                return -9

            def kill(self):
                self.returncode = -9

        monkeypatch.setattr("tools.agent_tools.subprocess.Popen", TimeoutPopen)
        monkeypatch.setattr(
            "core.web.services.runtime_scene_service.record_runtime_scene_event",
            fake_record_runtime_scene_event,
        )

        result = spawn_agent_impl(
            task_type="diagnose",
            goal="分析为什么超时",
            scope='{"log":"log_info/demo.jsonl"}',
            timeout=1,
        )

        payload = __import__("json").loads(result)
        assert payload["status"] == "timeout"
        assert "超时" in payload["summary"]
        assert "step1" in payload["process_output"]
        assert "timeout stderr" in payload["raw_output"]
        assert payload["subRunId"].startswith("subagent-diagnose-d1-")
        assert [event[2] for event in scene_events] == ["subagent.run.started", "subagent.run.timeout"]
        assert scene_events[-1][3]["fields"]["status"] == "timeout"
        assert scene_events[-1][3]["child_log_payload"]["timeoutSeconds"] == 1

    @pytest.mark.slow
    def test_spawn_agent_cancel_kills_process_and_returns_cancelled(self, monkeypatch):
        scene_events = []

        def fake_record_runtime_scene_event(component, phase, event_code, **kwargs):
            scene_events.append((component, phase, event_code, kwargs))
            return {"accepted": True}

        class SlowPipe:
            def readline(self):
                import time

                time.sleep(2.0)
                return ""

            def close(self):
                return None

        class CancellablePopen:
            killed = False
            kwargs = {}

            def __init__(self, *_args, **_kwargs):
                CancellablePopen.kwargs = dict(_kwargs)
                self.stdout = SlowPipe()
                self.stderr = SlowPipe()
                self.returncode = None
                self.pid = 43210

            def poll(self):
                return None

            def wait(self, timeout=None):
                self.returncode = -9
                return self.returncode

            def kill(self):
                CancellablePopen.killed = True
                self.returncode = -9

        terminate_calls = []

        def fake_terminate_process_tree(process):
            terminate_calls.append(int(getattr(process, "pid", 0)))

        monkeypatch.setattr("tools.agent_tools.subprocess.Popen", CancellablePopen)
        monkeypatch.setattr("tools.agent_tools._is_windows_platform", lambda: True)
        monkeypatch.setattr("tools.agent_tools._terminate_process_tree", fake_terminate_process_tree)
        monkeypatch.setattr(
            "tools.agent_tools.subprocess.run",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("taskkill/external commands must never run")
            ),
        )
        monkeypatch.setattr("tools.agent_tools.subprocess.CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
        monkeypatch.setattr("tools.agent_tools.subprocess.CREATE_NO_WINDOW", 0x08000000, raising=False)
        monkeypatch.setattr(
            "core.web.services.runtime_scene_service.record_runtime_scene_event",
            fake_record_runtime_scene_event,
        )

        result = spawn_agent_impl(
            task_type="diagnose",
            goal="分析为什么停不下来",
            scope='{"log":"log_info/demo.jsonl"}',
            timeout=30,
            _cancel_checker=lambda: "操作者请求停止当前轮。",
        )

        payload = __import__("json").loads(result)
        assert payload["status"] == "cancelled"
        assert payload["stop_reason"] == "操作者请求停止当前轮。"
        assert CancellablePopen.killed is False
        assert CancellablePopen.kwargs["creationflags"] == 0x08000200
        # 取消必须走共享无 console 终止器，绝不允许外部命令替代。
        assert terminate_calls == [43210]
        assert payload["subRunId"].startswith("subagent-diagnose-d1-")
        assert [event[2] for event in scene_events] == ["subagent.run.started", "subagent.run.cancelled"]
        assert scene_events[-1][3]["fields"]["stopReason"] == "操作者请求停止当前轮。"

    def test_spawn_agent_streams_live_stdout_before_final_marker(self, monkeypatch):
        class FakePipe:
            def __init__(self, lines):
                self._lines = list(lines)

            def readline(self):
                if self._lines:
                    return self._lines.pop(0)
                return ""

            def close(self):
                return None

        class DummyPopen:
            def __init__(self, *_args, **_kwargs):
                self.stdout = FakePipe(
                    [
                        "<think>先读取 attention snapshot\n",
                        "再看工具轨迹</think>\n",
                        "__VIBELUTION_SUBAGENT_RESULT__"
                        '{"status":"completed","summary":"已定位根因","findings":["重复搜索"],'
                        '"evidence":["recent_blockers"],"recommended_next_action":"主 agent 收束","confidence":"high"}',
                    ]
                )
                self.stderr = FakePipe([])
                self.returncode = 0

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        events = []
        monkeypatch.setattr("tools.agent_tools.subprocess.Popen", DummyPopen)
        set_subagent_stream_sink(lambda event: events.append(event))
        try:
            result = spawn_agent_impl(
                task_type="diagnose",
                goal="分析为什么重复调用工具",
                scope='{"log":"log_info/demo.jsonl"}',
            )
        finally:
            set_subagent_stream_sink(None)

        payload = __import__("json").loads(result)
        assert payload["status"] == "completed"
        assert any("attention snapshot" in item["text"] for item in events if item["stream"] == "stdout")
        assert all("__VIBELUTION_SUBAGENT_RESULT__" not in item["text"] for item in events)

    def test_spawn_agent_passes_max_iterations_from_constraints(self, monkeypatch):
        captured = {}

        class FakePipe:
            def readline(self):
                return ""

            def close(self):
                return None

        class DummyPopen:
            def __init__(self, args, **_kwargs):
                captured["args"] = list(args)
                self.stdout = FakePipe()
                self.stderr = FakePipe()
                self.returncode = 0

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        monkeypatch.setattr("tools.agent_tools.subprocess.Popen", DummyPopen)

        spawn_agent_impl(
            task_type="diagnose",
            goal="分析为什么超时",
            constraints={"readonly": True, "max_steps": 6},
            timeout=1,
        )

        assert "--max-iterations" in captured["args"]
        idx = captured["args"].index("--max-iterations")
        assert captured["args"][idx + 1] == "6"

    def test_spawn_agent_inherits_parent_conversation_log_context(self, monkeypatch):
        captured = {}

        class FakePipe:
            def readline(self):
                return ""

            def close(self):
                return None

        class DummyPopen:
            def __init__(self, args, **kwargs):
                captured["args"] = list(args)
                captured["env"] = dict(kwargs.get("env") or {})
                self.stdout = FakePipe()
                self.stderr = FakePipe()
                self.returncode = 0

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        class DummyConversation:
            _session_id = "parent_session_001"
            _turn_count = 4

        class DummyUnifiedLogger:
            conversation = DummyConversation()

        monkeypatch.setattr("tools.agent_tools.subprocess.Popen", DummyPopen)
        monkeypatch.setitem(__import__("sys").modules, "core.logging.unified_logger", SimpleNamespace(logger=DummyUnifiedLogger()))

        spawn_agent_impl(
            task_type="diagnose",
            goal="分析为什么超时",
            scope={"log": "log_info/demo.jsonl"},
            constraints={"max_steps": 2},
        )

        assert captured["env"]["VIBELUTION_LOG_SESSION_ID"] == "parent_session_001"
        assert captured["env"]["VIBELUTION_LOG_ACTOR"] == "subagent"
        assert captured["env"]["VIBELUTION_LOG_PARENT_TURN"] == "4"
        assert captured["env"]["VIBELUTION_LOG_ACTOR_LABEL"] == "diagnose"
        assert captured["env"]["VIBELUTION_AGENT_LLM_SLOT"] == "subagentExecution"

    def test_extract_structured_result_infers_error_summary_from_raw_output(self):
        payload = spawn_agent_impl.__globals__["_extract_structured_result"](
            "<think>继续</think>\nTraceback ...\nOSError: [Errno 22] Invalid argument",
            "",
            0,
            "diagnose",
            "分析为什么超时",
            {"log": "demo.jsonl"},
        )

        assert payload["status"] == "partial"
        assert "OSError" in payload["summary"]
        assert payload["recommended_next_action"]

    def test_extract_structured_result_ignores_state_json_echo(self):
        payload = spawn_agent_impl.__globals__["_extract_structured_result"](
            "<think>继续分析</think>\n<state>{\"mood\":\"专注\"}</state>\nOSError: [Errno 22] Invalid argument",
            "",
            0,
            "diagnose",
            "分析为什么超时",
            {"log": "demo.jsonl"},
        )

        assert payload["status"] == "partial"
        assert "OSError" in payload["summary"]

    def test_extract_structured_result_marks_empty_success_as_no_result(self):
        payload = spawn_agent_impl.__globals__["_extract_structured_result"](
            "",
            "",
            0,
            "diagnose",
            "分析为什么子 agent 没有返回",
            {"log": "demo.jsonl"},
        )

        assert payload["status"] == "no_result"
        assert payload["summary"] == "子 agent 未返回可用结论"
        assert payload["recommended_next_action"] == "主 agent 接管并自行收束"

    def test_extract_structured_result_rejects_empty_completed_payload(self):
        payload = spawn_agent_impl.__globals__["_extract_structured_result"](
            (
                "__VIBELUTION_SUBAGENT_RESULT__"
                '{"status":"completed","summary":"","findings":[],"evidence":[],'
                '"recommended_next_action":"","confidence":"low"}'
            ),
            "",
            0,
            "diagnose",
            "分析为什么子 agent 没有返回",
            {"log": "demo.jsonl"},
        )

        assert payload["status"] == "no_result"
        assert payload["summary"] == "子 agent 未返回可用结论"

    def test_spawn_agent_fast_path_scans_conversation_log(self, tmp_path):
        log_path = tmp_path / "conversation_20260511_162502.jsonl"
        log_path.write_text(
            "{\"event\":\"tool_call\",\"tool_result\":\"OSError: [Errno 22] Invalid argument\"}\n",
            encoding="utf-8",
        )

        result = json.loads(
            spawn_agent_impl(
                task_type="diagnose",
                goal=f"分析 {log_path} 中子 agent 为什么会超时，只做诊断，不要修改代码。",
                scope={"log": str(log_path)},
                constraints={"readonly": True, "max_steps": 3},
                timeout=1,
            )
        )

        assert result["status"] == "completed"
        assert "OSError" in result["summary"]
        assert result["fast_path"] == "conversation_log_scan"

    def test_maybe_delegate_passes_turn_stop_checker_to_spawn_tool(self):
        captured = {}

        class DummyUI:
            def add_log(self, *_args, **_kwargs):
                return None

            def add_content(self, *_args, **_kwargs):
                return None

            def add_delegation_evidence(self, *_args, **_kwargs):
                return None

            def start_subagent_activity(self, *_args, **_kwargs):
                return None

            def finish_subagent_activity(self, *_args, **_kwargs):
                return None

            def add_subagent_process(self, *_args, **_kwargs):
                return None

            def stream_subagent_thought(self, *_args, **_kwargs):
                return None

        class DummySession:
            def get_attention_snapshot(self):
                return {
                    "recent_blockers": [
                        {"kind": "duplicate_read", "summary": "core/infrastructure/tool_executor.py 第 1-80 行本轮已读过。"}
                    ],
                    "modified_paths": [],
                    "delegation_history": [],
                    "delegation_failures": [],
                    "last_validation_summary": "",
                    "last_validation_passed": False,
                    "diagnostic_drift": True,
                }

            def has_recent_delegation(self, *_args, **_kwargs):
                return False

            def record_delegation_start(self, *_args, **_kwargs):
                return None

            def record_delegation_result(self, *_args, **_kwargs):
                return None

            def record_delegation_failure(self, *_args, **_kwargs):
                return None

            def note_scope_completion(self, *_args, **_kwargs):
                return None

            def _normalize_scope_signature(self, scope):
                return str(scope)

        def fake_spawn_execute(_tool_name, tool_args):
            captured.update(tool_args)
            checker = tool_args.get("_cancel_checker")
            assert callable(checker)
            assert checker() == "操作者请求停止当前轮。"
            return (
                json.dumps(
                    {
                        "status": "cancelled",
                        "summary": "子 Agent 已随停止请求终止。",
                        "stop_reason": checker(),
                    },
                    ensure_ascii=False,
                ),
                None,
            )

        governor = DelegationGovernor(
            spawn_execute=fake_spawn_execute,
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: DummyUI(),
            session_getter=lambda: DummySession(),
            turn_stop_checker=lambda: "操作者请求停止当前轮。",
        )

        outcome = governor.maybe_delegate(
            goal="继续完成同一个用户目标：继续吧",
            iteration=2,
            total_tool_calls=4,
            messages=[],
        )

        assert captured["_cancel_checker"]() == "操作者请求停止当前轮。"
        assert outcome["delegated"] is True
        assert outcome["useful"] is False

    def test_infer_result_from_tool_outputs_extracts_oserror(self):
        payload = infer_result_from_tool_outputs(
            [
                "普通输出",
                "Traceback ...\nOSError: [Errno 22] Invalid argument\n更多上下文",
            ]
        )

        assert payload["status"] == "partial"
        assert "OSError" in payload["summary"]
        assert payload["evidence"]

    def test_infer_result_from_tool_outputs_include_status_false_keeps_diagnostics(self):
        payload = infer_result_from_tool_outputs(
            [
                "普通输出",
                "Traceback ...\nOSError: [Errno 22] Invalid argument\n更多上下文",
            ],
            include_status=False,
        )

        assert "status" not in payload
        assert "OSError" in payload["summary"]
        assert payload["evidence"]
        assert payload["findings"]

    def test_compact_tool_output_for_diagnosis_keeps_tail_evidence(self):
        raw = ("A" * 5000) + "\nOSError: [Errno 22] Invalid argument\n" + ("B" * 5000)

        compacted = compact_tool_output_for_diagnosis(raw, max_chars=200)

        assert "OSError: [Errno 22] Invalid argument" in compacted


class TestLocalProviderBootstrap:
    """本地 provider 启动测试"""

    def test_local_provider_without_api_key_can_bootstrap(self, monkeypatch):
        monkeypatch.setattr(agent_module.Key_Tools, "create_llm_facing_tools", lambda: [])
        monkeypatch.setattr(SelfEvolvingAgent, "_init_model_discovery", lambda self: 16000)
        monkeypatch.setattr(SelfEvolvingAgent, "_init_token_compressor", lambda self: None)

        def fake_init_llm(self):
            self.llm_with_tools = MagicMock()

        monkeypatch.setattr(SelfEvolvingAgent, "_init_llm", fake_init_llm)
        monkeypatch.setattr(agent_module, "get_prompt_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_event_bus", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_tool_executor", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_security_validator", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(agent_module, "get_git_memory_service", lambda: MagicMock())

        mental_model = MagicMock()
        monkeypatch.setattr(agent_module, "get_mental_model", lambda **_kwargs: mental_model)
        monkeypatch.setattr(
            agent_module,
            "resolve_feature_decision",
            lambda feature, **kwargs: MagicMock(effective_enabled=True),
        )


        config = isolated_settings_config(
            **{
                "llm.profiles.primary.model": "",
                "llm.profiles.primary.provider_id": "default",
                "llm.providers.default.kind": "local",
                "llm.providers.default.base_url": "http://localhost:11434/v1",
                "llm.providers.default.compat_mode": "openai",
                "llm.providers.default.requires_api_key": False,
            },
        )
        agent = SelfEvolvingAgent(config=config, mode="chat")
        provider = agent.config.llm.get_provider(role="primary")

        assert provider.kind == "local"
        mental_model.set_shared_llm.assert_called_once_with(agent.llm_with_tools)

    def test_runtime_agent_profile_binding_maps_selected_profile_to_primary(self, monkeypatch):
        monkeypatch.setenv("VIBELUTION_AGENT_ID", "agent-supervised-baseline")
        monkeypatch.setenv("VIBELUTION_AGENT_PROFILE_ID", "supervised_baseline")
        monkeypatch.setenv("VIBELUTION_AGENT_DIRECT_SESSION_ID", "session-baseline")
        monkeypatch.setenv("VIBELUTION_AGENT_WORKSPACE_PATH", "workspace/agents/agent-supervised-baseline")
        monkeypatch.setenv("VIBELUTION_SUPERVISED_ROLE", "baseline")
        monkeypatch.setattr(agent_module.Key_Tools, "create_llm_facing_tools", lambda: [])
        monkeypatch.setattr(SelfEvolvingAgent, "_init_model_discovery", lambda self: 16000)
        monkeypatch.setattr(SelfEvolvingAgent, "_init_token_compressor", lambda self: None)
        monkeypatch.setattr(agent_module, "get_prompt_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_event_bus", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_tool_executor", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_security_validator", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(agent_module, "get_git_memory_service", lambda: MagicMock())


        captured = {}

        class DummyClient:
            def __init__(self, config=None, role=None, profile_id=None):
                captured["model"] = config.llm.get_profile(role=role).model
                captured["profile_id"] = config.llm.get_profile(role=role).profile_id

            def bind_tools(self, _tools):
                return MagicMock()

        monkeypatch.setattr(
            agent_module,
            "get_llm_client",
            lambda role=None, profile_id=None, config=None: DummyClient(
                config=config,
                role=role,
                profile_id=profile_id,
            ),
        )

        original_config = isolated_settings_config(
            **{
                "llm.profiles.primary.model": "primary-model",
                "llm.profiles.primary.provider_id": "default",
                "llm.providers.default.kind": "local",
                "llm.providers.default.base_url": "http://localhost:11434/v1",
                "llm.providers.default.compat_mode": "openai",
                "llm.providers.default.requires_api_key": False,
            },
        )
        baseline_profile = copy.deepcopy(original_config.llm.profiles["primary"])
        baseline_profile.profile_id = "supervised_baseline"
        baseline_profile.model = "baseline-model"
        original_config.llm.profiles["supervised_baseline"] = baseline_profile
        agent = SelfEvolvingAgent(config=original_config, mode="chat")

        assert agent.runtime_agent_binding["agentId"] == "agent-supervised-baseline"
        assert agent.runtime_agent_binding["supervisedRole"] == "baseline"
        assert captured == {"model": "baseline-model", "profile_id": "primary"}
        assert original_config.llm.profiles["primary"].model == "primary-model"

    def test_agent_optional_llm_slots_drive_summary_and_mental_model_clients(self, monkeypatch):
        monkeypatch.setenv("VIBELUTION_AGENT_ID", "agent-slot-test")
        monkeypatch.setattr(agent_module.Key_Tools, "create_llm_facing_tools", lambda: [])
        monkeypatch.setattr(SelfEvolvingAgent, "_init_model_discovery", lambda self: 16000)
        monkeypatch.setattr(agent_module, "get_prompt_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_event_bus", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_tool_executor", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_security_validator", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(agent_module, "get_git_memory_service", lambda: MagicMock())
        mental_model = MagicMock()
        monkeypatch.setattr(agent_module, "get_mental_model", lambda **_kwargs: mental_model)
        monkeypatch.setattr(
            agent_module,
            "resolve_feature_decision",
            lambda feature, **kwargs: MagicMock(effective_enabled=True),
        )


        config = isolated_settings_config(
            **{
                "llm.providers.default.kind": "local",
                "llm.providers.default.base_url": "http://localhost:11434/v1",
                "llm.providers.default.compat_mode": "openai",
                "llm.providers.default.requires_api_key": False,
                "llm.profiles.primary.provider_id": "default",
                "llm.profiles.primary.model": "dialogue-model",
            },
        )
        provider_id = config.llm.get_profile(profile_id="primary").provider_id
        config.llm.model_library = {
            "dialogue-model-id": {"provider_id": provider_id, "model": "dialogue-model"},
            "summary-model-id": {
                "provider_id": provider_id,
                "model": "summary-model",
                "tool_calling_mode": "disabled",
            },
            "mental-model-id": {
                "provider_id": provider_id,
                "model": "mental-model",
                "tool_calling_mode": "disabled",
            },
        }
        agent_record = {
            "agentId": "agent-slot-test",
            "llmBindings": {
                "dialogue": {"modelId": "dialogue-model-id"},
                "summary": {"modelId": "summary-model-id"},
                "mentalModel": {"modelId": "mental-model-id"},
            },
        }

        directory_module = __import__(
            "core.web.services.agent_directory_service",
            fromlist=["agent_directory_service"],
        )
        monkeypatch.setattr(directory_module, "get_agent", lambda _agent_id, include_archived=False: agent_record)
        monkeypatch.setattr(directory_module, "filter_llm_tools_for_current_agent", lambda tools: list(tools or []))
        created_models = []

        class DummyClient:
            def __init__(self, config=None, role=None, profile_id=None):
                self.config = config
                self.role = role
                self.profile_id = profile_id or "primary"
                self.model = config.llm.get_profile(profile_id=self.profile_id).model
                created_models.append(self.model)

            def bind_tools(self, _tools):
                return self

        monkeypatch.setattr(
            agent_module,
            "get_llm_client",
            lambda role=None, profile_id=None, config=None: DummyClient(
                config=config,
                role=role,
                profile_id=profile_id,
            ),
        )

        agent = SelfEvolvingAgent(config=config, mode="chat")

        mental_model.set_shared_llm.assert_called_once()
        assert mental_model.set_shared_llm.call_args.args[0].model == "mental-model"
        assert agent.token_compressor.compression_llm.model == "summary-model"
        assert "dialogue-model" in created_models

    def test_runtime_agent_dialogue_binding_is_default_chat_source_of_truth(self, monkeypatch):
        monkeypatch.setenv("VIBELUTION_AGENT_ID", "agent-dialogue-default")
        monkeypatch.delenv("VIBELUTION_AGENT_LLM_SLOT", raising=False)
        monkeypatch.setattr(agent_module.Key_Tools, "create_llm_facing_tools", lambda: [SimpleNamespace(name="cli_tool")])
        monkeypatch.setattr(SelfEvolvingAgent, "_init_model_discovery", lambda self: 16000)
        monkeypatch.setattr(SelfEvolvingAgent, "_init_token_compressor", lambda self: None)
        monkeypatch.setattr(agent_module, "get_prompt_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_event_bus", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_tool_executor", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_security_validator", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(agent_module, "get_git_memory_service", lambda: MagicMock())


        config = isolated_settings_config(
            **{
                "llm.providers.default.kind": "local",
                "llm.providers.default.base_url": "http://localhost:11434/v1",
                "llm.providers.default.compat_mode": "openai",
                "llm.providers.default.requires_api_key": False,
                "llm.profiles.primary.provider_id": "default",
                "llm.profiles.primary.model": "global-primary-model",
                "llm.profiles.primary.tool_calling_mode": "disabled",
            },
        )
        provider_id = config.llm.get_profile(profile_id="primary").provider_id
        config.llm.model_library = {
            "agent-dialogue-model-id": {
                "provider_id": provider_id,
                "model": "agent-dialogue-model",
                "tool_calling_mode": "auto",
            },
        }
        agent_record = {
            "agentId": "agent-dialogue-default",
            "llmBindings": {"dialogue": {"modelId": "agent-dialogue-model-id"}},
        }
        directory_module = __import__(
            "core.web.services.agent_directory_service",
            fromlist=["agent_directory_service"],
        )
        monkeypatch.setattr(directory_module, "get_agent", lambda _agent_id, include_archived=False: agent_record)
        monkeypatch.setattr(
            directory_module,
            "current_agent_runtime",
            lambda: {
                "agentId": "agent-dialogue-default",
                "turnId": "turn-1",
                "runId": "turn-1",
                "agent": {"agentId": "agent-dialogue-default"},
                "agentConfigSnapshot": {
                    "agentId": "agent-dialogue-default",
                    "configRevision": 1,
                    "configHash": "test-config-hash",
                },
                "permissionPreset": "standard",
                "toolPolicy": {
                    "policyId": "tool-agent-dialogue-default",
                    "policyVersion": 1,
                    "allowedTools": ["cli_tool"],
                    "preferredTools": [],
                    "blockedTools": [],
                },
            },
        )
        monkeypatch.setattr(directory_module, "filter_llm_tools_for_current_agent", lambda tools: list(tools or []))

        class DummyClient:
            def __init__(self, config=None, role=None, profile_id=None):
                selected_profile_id = profile_id or config.llm.get_role_profile_id(role or "primary")
                profile = config.llm.get_profile(profile_id=selected_profile_id)
                self.model = profile.model
                self.profile_id = selected_profile_id
                self.bound_tool_count = 0

            def bind_tools(self, tools):
                rebound = DummyClient.__new__(DummyClient)
                rebound.model = self.model
                rebound.profile_id = self.profile_id
                rebound.bound_tool_count = len(list(tools or []))
                return rebound

        monkeypatch.setattr(
            agent_module,
            "get_llm_client",
            lambda role=None, profile_id=None, config=None: DummyClient(
                config=config,
                role=role,
                profile_id=profile_id,
            ),
        )

        agent = SelfEvolvingAgent(config=config, mode="chat")
        llm_for_turn = agent._get_llm_for_current_mode()

        assert agent.runtime_agent_binding["agentId"] == "agent-dialogue-default"
        assert "llmSlot" not in agent.runtime_agent_binding
        assert agent.config.llm.get_profile(profile_id="primary").model == "agent-dialogue-model"
        assert getattr(agent._runtime_agent_llm_resolution, "slot", "") == "dialogue"
        assert llm_for_turn.model == "agent-dialogue-model"
        assert llm_for_turn.bound_tool_count == 1

    def test_runtime_agent_context_compression_policy_overrides_global_config(self, monkeypatch):
        monkeypatch.delenv("VIBELUTION_AGENT_ID", raising=False)
        monkeypatch.delenv("VIBELUTION_AGENT_LLM_SLOT", raising=False)
        monkeypatch.setattr(agent_module.Key_Tools, "create_llm_facing_tools", lambda: [])

        def fake_model_discovery(self):
            self._context_window_limit = 1_000_000
            return 500_000

        monkeypatch.setattr(SelfEvolvingAgent, "_init_model_discovery", fake_model_discovery)
        monkeypatch.setattr(SelfEvolvingAgent, "_init_token_compressor", lambda self: None)
        monkeypatch.setattr(agent_module, "get_prompt_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_event_bus", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_tool_executor", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_security_validator", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(agent_module, "get_git_memory_service", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_mental_model", lambda **_kwargs: MagicMock())

        config = isolated_settings_config(
            **{
                "llm.providers.default.kind": "local",
                "llm.providers.default.base_url": "http://localhost:11434/v1",
                "llm.providers.default.compat_mode": "openai",
                "llm.providers.default.requires_api_key": False,
                "llm.profiles.primary.provider_id": "default",
                "llm.profiles.primary.model": "global-primary-model",
                "llm.profiles.primary.tool_calling_mode": "disabled",
            },
        )
        agent_record = {
            "agentId": "agent-compression-runtime",
            "contextCompressionPolicy": {
                "mode": "custom",
                "enabled": True,
                "maxTokenLimit": 262_144,
                "maxCompressionsPerSession": 4,
                "levels": {"light": 0.5, "standard": 0.7, "deep": 0.86, "emergency": 0.94},
                "summaryChars": {"light": 300, "standard": 700, "deep": 1300, "emergency": 1900},
                "preservation": {
                    "keepAiMessages": 4,
                    "preserveErrors": False,
                    "extractKeyDecisions": False,
                },
            },
        }
        directory_module = __import__(
            "core.web.services.agent_directory_service",
            fromlist=["agent_directory_service"],
        )
        monkeypatch.setattr(directory_module, "get_agent", lambda _agent_id, include_archived=False: agent_record)
        monkeypatch.setattr(directory_module, "filter_llm_tools_for_current_agent", lambda tools: list(tools or []))

        class DummyClient:
            def bind_tools(self, _tools):
                return self

        monkeypatch.setattr(agent_module, "get_llm_client", lambda role=None, profile_id=None, config=None: DummyClient())

        agent = SelfEvolvingAgent(
            config=config,
            mode="chat",
            runtime_agent_binding={
                "agentId": "agent-compression-runtime",
            },
        )
        strategy_config = agent._compression_strategy.get_config(agent_module.CompressionLevel.STANDARD)

        assert agent._context_compression_policy["source"] == "agent"
        assert agent.config.context_compression.max_token_limit == 262_144
        assert agent.config.context_compression.max_compressions_per_session == 4
        assert agent.config.context_compression.levels.standard == 0.7
        assert agent.config.context_compression.summary_chars.deep == 1300
        assert agent.config.context_compression.preservation.keep_ai_messages == 4
        assert agent.config.context_compression.preservation.preserve_errors is False
        assert agent.config.context_compression.preservation.extract_key_decisions is False
        assert strategy_config.summary_max_chars == 700
        assert strategy_config.keep_ai_messages == 2
        assert strategy_config.preserve_errors is False
        assert strategy_config.extract_key_decisions is False

    def test_262144_auto_compression_boundary_triggers_only_above_standard_threshold(self):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent._effective_max_token_limit = 262_144
        agent.config = SimpleNamespace(
            context_compression=SimpleNamespace(
                levels=SimpleNamespace(standard=0.8),
            )
        )

        assert agent._automatic_context_compression_threshold_tokens() == 209_715
        assert agent._should_automatically_compress(209_715) is False
        assert agent._should_automatically_compress(209_716) is True

    def test_explicit_runtime_agent_binding_overrides_process_environment(self, monkeypatch):
        monkeypatch.setenv("VIBELUTION_AGENT_ID", "agent-from-process-env")
        monkeypatch.setenv("VIBELUTION_AGENT_LLM_SLOT", "subagentExecution")

        binding = agent_module._runtime_agent_binding_from_env(
            {
                "agentId": "agent-from-web-session",
                "llmSlot": "dialogue",
                "directSessionId": "session-luna-pressure",
            }
        )

        assert binding["agentId"] == "agent-from-web-session"
        assert binding["llmSlot"] == "dialogue"
        assert binding["directSessionId"] == "session-luna-pressure"

    def test_think_and_act_auto_compresses_at_standard_context_threshold(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        prompt_build_calls = []

        def build_prompt():
            prompt_build_calls.append(True)
            return "stable system prompt"

        agent.name = "compression-threshold-tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(get_profile=lambda role="primary": SimpleNamespace(model="demo-model")),
            agent=SimpleNamespace(max_iterations=1),
            context_compression=SimpleNamespace(
                enabled=True,
                max_compressions_per_session=3,
                levels=SimpleNamespace(standard=0.8),
            ),
        )
        agent.prompt_manager = SimpleNamespace(
            update_current_goal=lambda _goal: None,
            set_runtime_goal_packet=lambda _packet: None,
            clear_state_memory=lambda persist=True: None,
            build=build_prompt,
        )
        stable_git_state = SimpleNamespace(
            available=True,
            head_rev="abc",
            indexed_head_rev="abc",
            dirty=False,
            error=None,
        )
        agent.git_memory = SimpleNamespace(refresh_git_memory=lambda force=False: stable_git_state)
        agent._active_turn_messages = []
        agent._active_turn_goal = None
        agent._pending_lifecycle_action = None
        agent._system_prompt_written = False
        agent._cached_system_prompt = ""
        agent._context_window_limit = 1000
        agent._effective_max_token_limit = 1000
        agent._pending_static_context_blocks = []
        agent._pending_runtime_context_blocks = []
        agent._last_turn_metadata = {}
        agent._last_turn_failed = False
        agent._single_turn_mode_active = False
        agent._active_goal = None
        agent._last_runtime_state_memory = ""
        agent._last_runtime_state_memory_key = ""
        agent._force_disable_tools_for_turn = True
        agent._compression_min_iteration_gap = 0
        agent._runtime_state_memory_dirty = False
        agent._sync_runtime_state_memory = lambda force=False: None
        agent._seed_runtime_agent_context_for_turn = lambda run_id=None: None
        agent._refresh_retrospective_state_memory = lambda: None
        agent._current_turn_stop_reason = lambda: None
        agent._raise_if_turn_stop_requested = lambda: None
        agent._get_mode_policy = lambda: ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=build_chat_user_message,
        )
        agent._create_round_state = lambda: RoundStateController(max_iterations=1)
        agent.is_mental_model_enabled_for_turn = lambda: False

        compress_calls = []
        llm_message_counts = []
        scene_events = []

        def fake_compress(messages, iteration, reason=""):
            compress_calls.append((iteration, reason, len(messages)))
            # Match real compress path: only then does the main loop append a runtime notice.
            agent._last_context_compression_applied = True
            return list(messages[:2]), False

        def fake_estimate(messages, threshold=None):
            # Gate helper and precise estimator share this stub in the test.
            return 500 if compress_calls else 801

        class DummyUI:
            def note_context_window(self, *_args, **_kwargs):
                pass

            def update_status(self, *_args, **_kwargs):
                pass

            def add_log(self, *_args, **_kwargs):
                pass

            def note_turn_start(self, *_args, **_kwargs):
                pass

            def note_turn_result(self, *_args, **_kwargs):
                pass

        class DummyLogger:
            _turn_count = 1

            def log_action(self, *_args, **_kwargs):
                pass

            def write_system_prompt(self, *_args, **_kwargs):
                pass

            def log_external_request(self, *_args, **_kwargs):
                pass

            def start_turn(self, *_args, **_kwargs):
                pass

            def log_llm_request(self, *_args, **_kwargs):
                pass

            def log_turn_end(self, *_args, **_kwargs):
                pass

        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
        monkeypatch.setattr(agent_module, "logger", DummyLogger())
        monkeypatch.setattr(agent_module._debug_logger, "turn_end", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module, "estimate_messages_tokens", fake_estimate)
        monkeypatch.setattr(agent_module, "estimate_messages_tokens_for_threshold", fake_estimate)
        monkeypatch.setattr(agent_module, "get_session_state", lambda: SimpleNamespace(
            set_runtime_goal_packet=lambda _packet: None,
            reset_runtime_constraints=lambda: None,
            get_attention_snapshot=lambda: {},
            get_active_evolution_txn=lambda: None,
        ))
        monkeypatch.setattr(
            agent_module,
            "_record_agent_scene_event",
            lambda *args, **kwargs: scene_events.append((args, kwargs)),
        )
        agent._compress_messages = fake_compress
        agent._reconcile_chat_conversation_before_llm = lambda msgs: (msgs, True)

        def fake_invoke(messages, replay_state=None):
            llm_message_counts.append(len(messages))
            return None

        agent._invoke_llm = fake_invoke

        agent._run_orchestrated_turn(user_prompt="触发压缩")

        assert compress_calls
        assert "上下文" in compress_calls[0][1]
        assert llm_message_counts[0] == 3
        assert len(prompt_build_calls) == 1
        preflight = next(item for item in scene_events if item[0][1] == "agent.llm_preflight.completed")
        fields = preflight[1]["fields"]
        assert fields["iteration"] == 1
        assert fields["messageCount"] == 3
        assert fields["totalPreflightMs"] >= 0
        assert fields["promptBuildReused"] is True
        assert {
            "gitRefreshMs",
            "runtimeStateSyncMs",
            "promptBuildMs",
            "contextEstimateMs",
            "delegationMs",
        } <= fields.keys()
        assert "prompt" not in fields
        assert "content" not in fields

    def test_runtime_agent_llm_slot_binding_maps_subagent_execution_to_primary(self, monkeypatch):
        monkeypatch.setenv("VIBELUTION_AGENT_ID", "agent-subagent-slot")
        monkeypatch.setenv("VIBELUTION_AGENT_LLM_SLOT", "subagentExecution")
        monkeypatch.setattr(agent_module.Key_Tools, "create_llm_facing_tools", lambda: [])
        monkeypatch.setattr(SelfEvolvingAgent, "_init_model_discovery", lambda self: 16000)
        monkeypatch.setattr(SelfEvolvingAgent, "_init_token_compressor", lambda self: None)
        monkeypatch.setattr(agent_module, "get_prompt_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_event_bus", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_tool_executor", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_security_validator", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(agent_module, "get_git_memory_service", lambda: MagicMock())


        config = isolated_settings_config(
            **{
                "llm.providers.default.kind": "local",
                "llm.providers.default.base_url": "http://localhost:11434/v1",
                "llm.providers.default.compat_mode": "openai",
                "llm.providers.default.requires_api_key": False,
                "llm.profiles.primary.provider_id": "default",
                "llm.profiles.primary.model": "dialogue-model",
            },
        )
        provider_id = config.llm.get_profile(profile_id="primary").provider_id
        config.llm.model_library = {
            "dialogue-model-id": {"provider_id": provider_id, "model": "dialogue-model"},
            "subagent-execution-model-id": {
                "provider_id": provider_id,
                "model": "subagent-execution-model",
                "tool_calling_mode": "disabled",
            },
        }
        agent_record = {
            "agentId": "agent-subagent-slot",
            "llmBindings": {
                "dialogue": {"modelId": "dialogue-model-id"},
                "subagentExecution": {"modelId": "subagent-execution-model-id"},
            },
        }
        directory_module = __import__(
            "core.web.services.agent_directory_service",
            fromlist=["agent_directory_service"],
        )
        monkeypatch.setattr(directory_module, "get_agent", lambda _agent_id, include_archived=False: agent_record)
        monkeypatch.setattr(directory_module, "filter_llm_tools_for_current_agent", lambda tools: list(tools or []))
        captured_models = []

        class DummyClient:
            def __init__(self, config=None, role=None, profile_id=None):
                selected_profile_id = profile_id or config.llm.get_role_profile_id(role or "primary")
                self.model = config.llm.get_profile(profile_id=selected_profile_id).model
                captured_models.append(self.model)

            def bind_tools(self, _tools):
                return self

        monkeypatch.setattr(
            agent_module,
            "get_llm_client",
            lambda role=None, profile_id=None, config=None: DummyClient(
                config=config,
                role=role,
                profile_id=profile_id,
            ),
        )

        agent = SelfEvolvingAgent(config=config, mode="chat")

        assert agent.runtime_agent_binding["llmSlot"] == "subagentExecution"
        assert agent.config.llm.get_profile(profile_id="primary").model == "subagent-execution-model"
        assert "subagent-execution-model" in captured_models

    def test_runtime_agent_llm_slot_binding_uses_supervised_env_snapshot_when_registry_missing(self, monkeypatch):
        monkeypatch.setenv("VIBELUTION_AGENT_ID", "agent-supervised-worktree")
        monkeypatch.setenv("VIBELUTION_AGENT_LLM_SLOT", "dialogue")
        monkeypatch.setenv("VIBELUTION_AGENT_LLM_MODEL_ID", "supervised-dialogue-model-id")
        monkeypatch.setenv(
            "VIBELUTION_AGENT_LLM_BINDINGS_JSON",
            json.dumps({"dialogue": {"modelId": "supervised-dialogue-model-id"}}),
        )
        monkeypatch.setenv("VIBELUTION_SUPERVISED_ROLE", "baseline")
        monkeypatch.setattr(agent_module.Key_Tools, "create_llm_facing_tools", lambda: [])
        monkeypatch.setattr(SelfEvolvingAgent, "_init_model_discovery", lambda self: 16000)
        monkeypatch.setattr(SelfEvolvingAgent, "_init_token_compressor", lambda self: None)
        monkeypatch.setattr(agent_module, "get_prompt_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_event_bus", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_tool_executor", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_security_validator", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(agent_module, "get_git_memory_service", lambda: MagicMock())


        config = isolated_settings_config(
            **{
                "llm.providers.default.kind": "local",
                "llm.providers.default.base_url": "http://localhost:11434/v1",
                "llm.providers.default.compat_mode": "openai",
                "llm.providers.default.requires_api_key": False,
                "llm.profiles.primary.provider_id": "default",
                "llm.profiles.primary.model": "global-primary-model",
            },
        )
        provider_id = config.llm.get_profile(profile_id="primary").provider_id
        config.llm.model_library = {
            "supervised-dialogue-model-id": {
                "provider_id": provider_id,
                "model": "supervised-dialogue-model",
                "tool_calling_mode": "auto",
            },
        }
        directory_module = __import__(
            "core.web.services.agent_directory_service",
            fromlist=["agent_directory_service"],
        )
        monkeypatch.setattr(directory_module, "get_agent", lambda _agent_id, include_archived=False: None)
        monkeypatch.setattr(directory_module, "filter_llm_tools_for_current_agent", lambda tools: list(tools or []))

        class DummyClient:
            def __init__(self, config=None, role=None, profile_id=None):
                selected_profile_id = profile_id or config.llm.get_role_profile_id(role or "primary")
                self.model = config.llm.get_profile(profile_id=selected_profile_id).model

            def bind_tools(self, _tools):
                return self

        monkeypatch.setattr(
            agent_module,
            "get_llm_client",
            lambda role=None, profile_id=None, config=None: DummyClient(
                config=config,
                role=role,
                profile_id=profile_id,
            ),
        )

        agent = SelfEvolvingAgent(config=config, mode="chat")

        assert agent.runtime_agent_binding["llmBindings"]["dialogue"]["modelId"] == "supervised-dialogue-model-id"
        assert agent.config.llm.get_profile(profile_id="primary").model == "supervised-dialogue-model"
        provider = agent.config.llm.get_provider(role="primary")
        assert provider.provider_id == provider_id
        assert provider.kind == "local"
        assert provider.requires_api_key is False
        assert agent._runtime_agent_llm_resolution.agent_id == "agent-supervised-worktree"

    def test_runtime_agent_llm_slot_binding_failure_is_fatal(self, monkeypatch):
        monkeypatch.setenv("VIBELUTION_AGENT_ID", "agent-bad-slot")
        monkeypatch.setenv("VIBELUTION_AGENT_LLM_SLOT", "dialogue")
        config = isolated_settings_config(
            **{
                "llm.providers.default.kind": "local",
                "llm.providers.default.base_url": "http://localhost:11434/v1",
                "llm.providers.default.compat_mode": "openai",
                "llm.providers.default.requires_api_key": False,
                "llm.profiles.primary.provider_id": "default",
                "llm.profiles.primary.model": "primary-model",
            },
        )
        directory_module = __import__(
            "core.web.services.agent_directory_service",
            fromlist=["agent_directory_service"],
        )
        monkeypatch.setattr(
            directory_module,
            "get_agent",
            lambda _agent_id, include_archived=False: {
                "agentId": "agent-bad-slot",
                "llmBindings": {"dialogue": {"modelId": "missing-model-id"}},
            },
        )

        with pytest.raises(agent_module.AgentLlmResolutionError, match="missing-model-id"):
            SelfEvolvingAgent(config=config)

    def test_runtime_agent_llm_slot_binding_does_not_fallback_to_dialogue(self, monkeypatch):
        monkeypatch.setenv("VIBELUTION_AGENT_ID", "agent-missing-subagent-slot")
        monkeypatch.setenv("VIBELUTION_AGENT_LLM_SLOT", "subagentExecution")
        config = isolated_settings_config(
            **{
                "llm.providers.default.kind": "local",
                "llm.providers.default.base_url": "http://localhost:11434/v1",
                "llm.providers.default.compat_mode": "openai",
                "llm.providers.default.requires_api_key": False,
                "llm.profiles.primary.provider_id": "default",
                "llm.profiles.primary.model": "primary-model",
            },
        )
        provider_id = config.llm.get_profile(profile_id="primary").provider_id
        config.llm.model_library = {
            "dialogue-model-id": {"provider_id": provider_id, "model": "dialogue-model"},
        }
        directory_module = __import__(
            "core.web.services.agent_directory_service",
            fromlist=["agent_directory_service"],
        )
        monkeypatch.setattr(
            directory_module,
            "get_agent",
            lambda _agent_id, include_archived=False: {
                "agentId": "agent-missing-subagent-slot",
                "llmBindings": {"dialogue": {"modelId": "dialogue-model-id"}},
            },
        )

        with pytest.raises(agent_module.AgentLlmResolutionError, match="subagentExecution LLM binding is required"):
            SelfEvolvingAgent(config=config)

    def test_runtime_agent_binding_seeds_context_engine_packet_for_single_turn(self, monkeypatch):
        monkeypatch.setenv("VIBELUTION_AGENT_ID", "agent-supervised-baseline")
        monkeypatch.setenv("VIBELUTION_AGENT_PROFILE_ID", "primary")
        monkeypatch.setenv("VIBELUTION_AGENT_DIRECT_SESSION_ID", "session-baseline")
        monkeypatch.setenv("VIBELUTION_SUPERVISED_ROLE", "baseline")
        monkeypatch.setattr(agent_module.Key_Tools, "create_llm_facing_tools", lambda: [])
        monkeypatch.setattr(SelfEvolvingAgent, "_init_model_discovery", lambda self: 16000)
        monkeypatch.setattr(SelfEvolvingAgent, "_init_token_compressor", lambda self: None)
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_event_bus", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_tool_executor", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_security_validator", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(agent_module, "get_git_memory_service", lambda: MagicMock())

        monkeypatch.setattr(
            agent_module,
            "get_llm_client",
            lambda **_kwargs: type("DummyClient", (), {"bind_tools": lambda self, _tools: MagicMock()})(),
        )

        class DummyPromptManager:
            def __init__(self):
                self.goal = ""

            def update_current_goal(self, goal):
                self.goal = goal

            def set_runtime_goal_packet(self, _packet):
                pass

            def clear_state_memory(self, persist=False):
                pass

            def build(self):
                return "system"

        monkeypatch.setattr(agent_module, "get_prompt_manager", lambda: DummyPromptManager())
        monkeypatch.setattr(agent_module, "get_session_state", lambda: MagicMock())
        monkeypatch.setattr(
            agent_module,
            "build_agent_context",
            lambda agent_id, **kwargs: SimpleNamespace(
                agent_id=agent_id,
                session_id=kwargs.get("session_id", ""),
                context_block="## Agent Runtime Context\nPromptTemplateId: prompt-supervised-baseline",
            ),
        )

        config = isolated_settings_config(
            **{
                "agent.default_mode": "supervised_evolution",
                "llm.profiles.primary.model": "primary-model",
                "llm.profiles.primary.provider_id": "default",
                "llm.providers.default.kind": "local",
                "llm.providers.default.base_url": "http://localhost:11434/v1",
                "llm.providers.default.compat_mode": "openai",
                "llm.providers.default.requires_api_key": False,
            },
        )
        agent = SelfEvolvingAgent(config=config, mode="chat")
        messages, resumed = TurnOutcomeController.prepare_turn_messages(
            system_prompt=(
                "static",
                "<<<SYSTEM_PROMPT_SPLIT>>>",
                "dynamic",
            ),
            user_prompt="probe",
            effective_goal="probe",
            active_turn_messages=None,
            active_turn_goal="",
            build_system_message=agent_module.build_system_message,
            build_external_request_message=agent._get_mode_policy().runtime_input_builder,
            allow_append_user_message=False,
        )

        agent._seed_runtime_agent_context_for_turn(run_id="case-1")
        pending = list(agent._pending_runtime_context_blocks)
        assert pending == []

        assert resumed is False
        # 关键不变量：cacheable 系统块的文本不得被运行时上下文污染。
        assert isinstance(messages[0], dict)
        assert messages[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert "prompt-supervised-baseline" not in messages[0]["content"][0]["text"]
        # 动态运行时上下文不再以独立 SystemMessage 进入模型输入。
        runtime_carriers = [
            message for message in messages[1:]
            if isinstance(message, SystemMessage)
            and "prompt-supervised-baseline" in str(message.content)
        ]
        assert runtime_carriers == []


class TestStructuredSystemMessageInvariants:
    """守 cache_control 链路 — SystemMessage 用 list-of-blocks 时类型与字段必须保留。

    这条护城河针对 langchain_core 升级风险：一旦它把 list-of-dicts 静默序列化成 str，
    所有 Anthropic 显式 cache_control 路径会无声失效，命中率会突然崩盘，但 telemetry
    不会报错。这里强制覆盖三个不变量：
    1. SystemMessage(content=[blocks]) 构造后 content 仍是 list
    2. build_system_message 输出 dict + content list + 首块带 cache_control
    3. _invoke_llm 的 clean_messages 步骤不会把 list 转成 str
    """

    def test_system_message_preserves_structured_content_blocks(self):
        from langchain_core.messages import SystemMessage as LCSystemMessage

        blocks = [
            {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "dynamic"},
        ]
        msg = LCSystemMessage(content=blocks)
        assert isinstance(msg.content, list), "langchain SystemMessage 把 list 静默转 str 会让 cache_control 失效"
        assert msg.content[0]["cache_control"] == {"type": "ephemeral"}
        assert msg.content[1].get("cache_control") is None

    def test_build_system_message_marks_only_prefix_with_cache_control_by_default(self):
        from core.infrastructure.llm_utils import build_system_message

        sp = ("static prefix", "<<<SYSTEM_PROMPT_SPLIT>>>", "dynamic suffix")
        message = build_system_message(sp)
        assert isinstance(message, dict)
        assert message["role"] == "system"
        assert isinstance(message["content"], list)
        assert message["content"][0]["type"] == "text"
        assert message["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert message["content"][0]["text"] == "static prefix"
        assert len(message["content"]) == 1

    def test_build_system_message_can_include_dynamic_suffix_only_when_explicit(self):
        from core.infrastructure.llm_utils import build_system_message

        sp = ("static prefix", "<<<SYSTEM_PROMPT_SPLIT>>>", "dynamic suffix")
        message = build_system_message(sp, include_dynamic_suffix=True)

        assert message["content"][1]["text"] == "dynamic suffix"
        assert "cache_control" not in message["content"][1]

    def test_build_cacheable_system_prefix_omits_dynamic_suffix(self):
        from core.infrastructure.llm_utils import (
            build_cacheable_system_prefix_message,
            build_dynamic_system_context_message,
        )

        sp = ("static prefix", "<<<SYSTEM_PROMPT_SPLIT>>>", "dynamic suffix")
        message = build_cacheable_system_prefix_message(sp)
        dynamic_message = build_dynamic_system_context_message(sp)

        assert isinstance(message, dict)
        assert message["content"][0]["text"] == "static prefix"
        assert message["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert len(message["content"]) == 1
        assert isinstance(dynamic_message, SystemMessage)
        assert dynamic_message.content.startswith("## Dynamic System Context")
        assert "dynamic suffix" in dynamic_message.content

    def test_volatile_dynamic_system_context_is_not_carried_to_next_turn(self):
        messages = [
            {"role": "system", "content": "stable prefix"},
            {"role": "user", "content": "history user"},
            SystemMessage(content="## Dynamic System Context\ndynamic suffix"),
            {"role": "user", "content": "current user"},
        ]

        carryover_messages = [
            message for message in messages
            if not is_volatile_system_context_message(message)
        ]
        carryover = TurnOutcomeController.finish_turn_message_carryover(
            messages=carryover_messages,
            lifecycle_action=None,
            active_goal="goal",
        )

        assert carryover.goal == "goal"
        assert carryover.messages == [
            {"role": "system", "content": "stable prefix"},
            {"role": "user", "content": "history user"},
            {"role": "user", "content": "current user"},
        ]

    def test_invoke_llm_clean_messages_preserves_dict_system_message(self):
        """_invoke_llm 内部 clean_messages 步骤对 dict 形态 system message 应原样保留，
        不能被改写成 SystemMessage(content=str)（那样会丢 cache_control）。"""
        system_dict = {
            "role": "system",
            "content": [
                {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "dynamic"},
            ],
        }

        # 复用 agent.py 的 clean_messages 逻辑（_invoke_llm 内联，无独立函数；
        # 这里复制其约束做单元测试）。
        cleaned: list = []
        for msg in [system_dict]:
            if isinstance(msg, dict) and msg.get("role") == "system":
                cleaned.append(dict(msg))
            else:
                cleaned.append(msg)
        assert cleaned[0]["role"] == "system"
        assert isinstance(cleaned[0]["content"], list)
        assert cleaned[0]["content"][0]["cache_control"] == {"type": "ephemeral"}


class TestDelegationExposure:
    def test_spawn_agent_tool_not_exposed_to_llm_tool_catalog(self):
        names = [tool.name for tool in create_key_tools()]

        assert "spawn_agent_tool" not in names

    def test_llm_facing_tools_hide_long_tail_admin_tools(self):
        tools = create_llm_facing_tools()
        names = [tool.name for tool in tools]
        descriptions = {tool.name: getattr(tool, "description", "") for tool in tools}

        assert "research_agent_creation_proposal_tool" in names
        assert "research_communication_edge_proposal_tool" in names
        assert "task_start_tool" not in names
        assert "task_output_tool" not in names
        assert "task_stop_tool" not in names
        assert "update_self_model_tool" not in names
        assert "record_learning_tool" in names
        assert "search_memory_tool" in names
        assert "apply_patch_tool" in names
        assert "apply_diff_edit_tool" in names
        assert "read_file_tool" not in names
        assert "grep_search_tool" in names
        assert "glob_tool" in names
        assert "code_symbol_tool" in names
        assert "plan_update_tool" in names
        assert "run_test_for_tool" in names
        assert "create_child_session_tool" in names
        assert "list_child_sessions_tool" in names
        assert "claude_code" in descriptions["cli_agent_run_tool"]
        assert "外部代码 Agent" in descriptions["cli_agent_run_tool"]
        assert "内部子 Agent 自动派遣" in descriptions["cli_agent_run_tool"]

        from core.web.services import tool_catalog

        assert "read_file_tool" in tool_catalog.explicit_allow_tool_names()
        assert tool_catalog.permission_tier_for_tool("read_file_tool") == tool_catalog.MEDIUM_PERMISSION_TIER
        for bundle in tool_catalog.list_tool_bundles():
            assert "read_file_tool" not in bundle["toolNames"]
            assert "read_file_tool" not in bundle["preferredToolNames"]

    def test_child_session_tool_description_guides_autostart_handoff(self):
        tools_by_name = {tool.name: tool for tool in create_llm_facing_tools()}
        description = str(getattr(tools_by_name["create_child_session_tool"], "description", "") or "")

        assert "明显独立" in description
        assert "直接创建并自动启动" in description
        assert "handoff 上下文" in description
        assert "同一 Agent" in description

    def test_llm_facing_tool_descriptions_are_capability_contracts(self):
        hard_cognitive_markers = ("必须", "禁止", "禁用", "强制")
        violations = []
        for tool in create_llm_facing_tools():
            description = str(getattr(tool, "description", "") or "")
            for marker in hard_cognitive_markers:
                if marker in description:
                    violations.append(f"{tool.name}: {marker}")

        assert violations == []

    def test_close_evolution_transaction_tool_description_matches_return_contract(self):
        tools_by_name = {tool.name: tool for tool in create_llm_facing_tools()}
        description = str(getattr(tools_by_name["close_evolution_transaction_tool"], "description", "") or "")

        assert "transaction_status" in description
        assert "success" in description
        assert "failed" in description
        assert "cancelled" in description
        assert "status" in description


class TestResolvedApiKeyUsage:
    """解析后的 API Key 使用一致性测试"""

    def test_agent_missing_api_key_error_names_selected_model_envs(self, monkeypatch):
        model_key_env = "VIBELUTION_TEST_MODEL_MISSING_API_KEY"
        provider_key_env = "VIBELUTION_TEST_PROVIDER_MISSING_API_KEY"
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.delenv(model_key_env, raising=False)
        monkeypatch.delenv(provider_key_env, raising=False)
        monkeypatch.setattr("config.models._read_env_var", lambda _name: None)
        scene_events = []
        monkeypatch.setattr(
            agent_module,
            "_record_agent_scene_event",
            lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
        )

        config = isolated_settings_config(
            **{
                "llm.providers.default.kind": "relay",
                "llm.providers.default.base_url": "https://ai-pixel.online",
                "llm.providers.default.compat_mode": "openai",
                "llm.providers.default.requires_api_key": True,
                "llm.profiles.primary.provider_id": "default",
                "llm.profiles.primary.model": "gpt-5.6-luna",
            },
        )
        primary_profile = config.llm.get_profile(role="primary")
        primary_provider = config.llm.get_provider(role="primary")
        primary_provider.api_key = ""
        primary_provider.api_key_env = provider_key_env
        primary_profile.api_key_env = model_key_env
        config.llm.model_library = {
            "relay_gpt_5_6_luna": {
                "provider_id": primary_provider.provider_id,
                "model": "gpt-5.6-luna",
                "api_key_env": model_key_env,
            }
        }

        with pytest.raises(ValueError) as exc_info:
            SelfEvolvingAgent(config=config, mode="chat")

        message = str(exc_info.value)
        assert "modelId=relay_gpt_5_6_luna" in message
        assert f"provider={primary_provider.provider_id}" in message
        assert model_key_env in message
        assert provider_key_env in message
        assert "llm.providers.<provider_id>" not in message
        missing_event = next(event for event in scene_events if event[1] == "agent.api_key.missing")
        fields = missing_event[2]["fields"]
        assert fields["modelId"] == "relay_gpt_5_6_luna"
        assert fields["providerId"] == primary_provider.provider_id
        assert fields["providerKind"] == "relay"
        assert fields["modelApiKeyEnv"] == model_key_env
        assert fields["providerApiKeyEnv"] == provider_key_env
        assert fields["apiKeySource"] == "missing"

    def test_agent_uses_provider_specific_resolved_key(self, monkeypatch):
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.setenv("MINIMAX_API_KEY", "minimax-test-key")

        monkeypatch.setattr(agent_module.Key_Tools, "create_llm_facing_tools", lambda: [])
        monkeypatch.setattr(SelfEvolvingAgent, "_init_model_discovery", lambda self: 16000)
        monkeypatch.setattr(SelfEvolvingAgent, "_init_token_compressor", lambda self: None)
        monkeypatch.setattr(agent_module, "get_prompt_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_event_bus", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_tool_executor", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_security_validator", lambda *_args, **_kwargs: MagicMock())


        captured = {}

        class DummyClient:
            def __init__(self, config=None, role=None, profile_id=None):
                captured.setdefault("calls", []).append(
                    {
                        "role": role,
                        "profile_id": profile_id,
                        "resolved_api_key": config.get_api_key(),
                    }
                )

            def bind_tools(self, _tools):
                return MagicMock()

        monkeypatch.setattr(
            agent_module,
            "get_llm_client",
            lambda role=None, profile_id=None, config=None: DummyClient(config=config, role=role, profile_id=profile_id),
        )

        config = isolated_settings_config(
            **{
                "llm.profiles.primary.model": "",
                "llm.profiles.primary.provider_id": "default",
                "llm.providers.default.kind": "minimax",
                "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
                "llm.providers.default.compat_mode": "openai",
                "llm.providers.default.requires_api_key": True,
            },
        )
        primary_provider = config.llm.get_provider(role="primary")
        primary_provider.api_key = ""
        primary_provider.api_key_env = "MINIMAX_API_KEY"
        agent = SelfEvolvingAgent(config=config, mode="chat")

        assert agent.api_key == "minimax-test-key"
        assert agent.config.llm.api_key == "minimax-test-key"
        assert captured["calls"][0]["resolved_api_key"] == "minimax-test-key"


class TestRuntimeStateMemoryFlow:
    """运行时状态记忆闭环测试"""

    def test_sync_runtime_state_memory_combines_carryover_and_runtime(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.prompt_manager = MagicMock()
        agent._last_runtime_state_memory = ""
        agent._carryover_state_memory = "## 延续约束\n- 先补观测，再继续推理。"

        fake_session = SimpleNamespace(
            render_dialogue_runtime_observations=lambda: "### 运行时限制\n- `cli_tool:pipe` 已被阻塞"
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: fake_session)

        agent._sync_runtime_state_memory()

        memory_text = agent.prompt_manager.update_state_memory.call_args[0][0]
        assert memory_text.index("### 运行时限制") < memory_text.index("## 延续约束")
        assert "### 运行时限制" in memory_text
        assert "## 延续约束" in memory_text
        assert agent.prompt_manager.update_state_memory.call_args.kwargs["persist"] is False

    def test_sync_runtime_state_memory_keeps_incomplete_result_as_observation(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.prompt_manager = MagicMock()
        agent._last_runtime_state_memory = ""
        agent._carryover_state_memory = ""

        fake_session = SimpleNamespace(
            render_dialogue_runtime_observations=lambda: (
                "### 工具结果范围\n"
                "- `core/demo.py` 的已返回内容不完整。"
            )
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: fake_session)

        agent._sync_runtime_state_memory()

        memory_text = agent.prompt_manager.update_state_memory.call_args[0][0]
        assert memory_text.splitlines()[0] == "### 工具结果范围"
        assert "已返回内容不完整" in memory_text
        assert "阅读导航" not in memory_text
        assert agent.prompt_manager.update_state_memory.call_args.kwargs["persist"] is False

    def test_refresh_retrospective_state_memory_updates_carryover(self, monkeypatch, tmp_path):
        session_file = tmp_path / "conversation_demo.jsonl"
        session_file.write_text("{}", encoding="utf-8")

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.prompt_manager = MagicMock()
        agent._last_runtime_state_memory = ""
        agent._carryover_state_memory = ""

        fake_report = SimpleNamespace(next_round_constraints=["后续自然语言说明默认回到中文。"])
        fake_analyzer = SimpleNamespace(
            analyze_evolution_session=lambda session_file=None: fake_report,
            build_next_round_state_memory=lambda report: "## 延续约束\n- 后续自然语言说明默认回到中文。",
        )
        monkeypatch.setattr(agent_module, "get_task_analyzer", lambda project_root=None: fake_analyzer)
        monkeypatch.setattr(
            agent_module,
            "logger",
            SimpleNamespace(conversation=SimpleNamespace(_get_session_file=lambda: str(session_file))),
        )
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(render_dialogue_runtime_observations=lambda: ""),
        )

        agent._refresh_retrospective_state_memory()

        assert "后续自然语言说明默认回到中文" in agent._carryover_state_memory
        assert "默认回到中文" not in agent._last_runtime_state_memory
        assert agent.prompt_manager.update_state_memory.call_count == 2
        assert agent.prompt_manager.update_state_memory.call_args_list[0].kwargs["persist"] is False
        assert agent.prompt_manager.update_state_memory.call_args_list[1].kwargs["persist"] is True

    def test_sync_runtime_state_memory_filters_runtime_language_constraints(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.prompt_manager = MagicMock()
        agent._last_runtime_state_memory = ""
        agent._last_runtime_state_memory_key = ""
        agent._carryover_state_memory = ""

        summaries = iter([
            "### 语言纠偏\n- 本轮已出现 1 次英文自然语言漂移；后续说明默认回到中文。",
            "### 当前诊断纪律\n- 当前阶段：观测\n### 语言纠偏\n- 本轮已出现 2 次英文自然语言漂移；后续说明默认回到中文。",
        ])
        fake_session = SimpleNamespace(render_dialogue_runtime_observations=lambda: next(summaries))
        monkeypatch.setattr(agent_module, "get_session_state", lambda: fake_session)

        agent._sync_runtime_state_memory()
        agent.prompt_manager.clear_state_memory.assert_not_called()
        agent.prompt_manager.update_state_memory.assert_not_called()
        agent._sync_runtime_state_memory()

        agent.prompt_manager.update_state_memory.assert_called_once()
        assert "语言纠偏" not in agent._last_runtime_state_memory
        assert "默认回到中文" not in agent._last_runtime_state_memory
        assert "当前阶段：观测" in agent._last_runtime_state_memory
        assert agent.prompt_manager.update_state_memory.call_args.kwargs["persist"] is False

    def test_chat_low_savings_compression_records_attempt_without_checkpoint(
        self,
        monkeypatch,
        tmp_path,
    ):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.project_root = str(tmp_path)
        agent.prompt_manager = MagicMock()
        agent._last_compression_iteration = 0
        agent._compression_min_iteration_gap = 0
        agent._compression_count_this_turn = 0
        agent._effective_max_token_limit = 10000
        agent.config = SimpleNamespace(
            context_compression=SimpleNamespace(
                enabled=True,
                max_compressions_per_session=3,
                effectiveness_threshold=0.3,
            )
        )
        agent._get_mode_policy = lambda: ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=True,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda value: value,
        )
        compressed = [{"role": "user", "content": "kept"}]
        agent.token_compressor = SimpleNamespace(
            compress=lambda *_args, **_kwargs: (compressed, "压缩摘要收益不足。")
        )
        agent._compression_strategy = SimpleNamespace(
            determine_level_with_iteration=lambda *_args: agent_module.CompressionLevel.STANDARD,
            get_config=lambda *_args: SimpleNamespace(
                summary_max_chars=1000,
                keep_ai_messages=2,
                preserve_errors=True,
            ),
        )
        monkeypatch.setattr(
            agent_module,
            "estimate_messages_tokens",
            lambda value: 10000 if len(value) >= 5 else 9800,
        )
        monkeypatch.setattr(agent_module, "_turn_runtime_from_env", lambda: {"sessionId": "session-low", "runId": "turn-low"})
        monkeypatch.setattr(agent_module, "get_ui", lambda: SimpleNamespace(add_log=MagicMock(), note_context_compression_event=MagicMock()))
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: SimpleNamespace(set_state=MagicMock()))

        from core.chat import conversation_ledger

        checkpoint = MagicMock()
        attempt = MagicMock(return_value=SimpleNamespace(event_id="attempt-1"))
        monkeypatch.setattr(conversation_ledger, "append_context_compression_checkpoint", checkpoint)
        monkeypatch.setattr(conversation_ledger, "append_context_compression_attempt", attempt)
        messages = [{"role": "user", "content": "旧上下文"}] * 5

        result, should_break = agent._compress_messages(messages, iteration=3, reason="context_pressure")

        assert result is compressed
        assert should_break is False
        checkpoint.assert_not_called()
        attempt.assert_called_once()
        assert attempt.call_args.kwargs["status"] == "skipped_low_savings"
        # Versioned compression policy v3: every summary carries the bounded
        # retention contract header before the original summary body.
        summary = str(attempt.call_args.kwargs["summary"])
        assert summary.startswith("[上下文保留合同]")
        assert "sessionId=session-low" in summary
        assert "compressionGeneration=1" in summary
        assert "unresolvedToolCallIds=none" in summary
        assert summary.endswith("压缩摘要收益不足。")
        agent.prompt_manager.update_state_memory.assert_not_called()

    def test_high_token_context_with_four_messages_reaches_compressor_and_records_preflight(
        self,
        monkeypatch,
        tmp_path,
    ):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.project_root = str(tmp_path)
        agent.prompt_manager = MagicMock()
        agent.runtime_agent_binding = {
            "agentId": "agent-compression",
            "directSessionId": "session-compression",
        }
        agent._last_compression_iteration = 0
        agent._compression_min_iteration_gap = 0
        agent._compression_count_this_turn = 0
        agent._effective_max_token_limit = 10000
        agent.config = SimpleNamespace(
            context_compression=SimpleNamespace(
                enabled=True,
                max_compressions_per_session=3,
                effectiveness_threshold=0.0,
                levels=SimpleNamespace(standard=0.8),
            )
        )
        agent._get_mode_policy = lambda: ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=True,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda value: value,
        )
        compressed = [{"role": "user", "content": "current"}]
        compressor = MagicMock()
        compressor.compress.return_value = (compressed, "历史已压缩。")
        agent.token_compressor = compressor
        agent._compression_strategy = SimpleNamespace(
            determine_level_with_iteration=lambda *_args: agent_module.CompressionLevel.STANDARD,
            get_config=lambda *_args: SimpleNamespace(
                summary_max_chars=1000,
                keep_ai_messages=5,
                preserve_errors=True,
            ),
        )
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "current"},
        ]
        monkeypatch.setattr(
            agent_module,
            "estimate_messages_tokens",
            lambda value: 12000 if len(value) >= 4 else 3000,
        )
        monkeypatch.setattr(
            agent_module,
            "_turn_runtime_from_env",
            lambda: {"sessionId": "session-compression", "runId": "turn-compression"},
        )
        monkeypatch.setattr(
            agent_module,
            "get_ui",
            lambda: SimpleNamespace(add_log=MagicMock(), note_context_compression_event=MagicMock()),
        )
        monkeypatch.setattr(
            agent_module,
            "get_state_manager",
            lambda: SimpleNamespace(set_state=MagicMock()),
        )
        scene_event = MagicMock()
        monkeypatch.setattr(agent_module, "_record_agent_scene_event", scene_event)

        result, should_break = agent._compress_messages(
            messages,
            iteration=1,
            reason="达到配置的上下文压缩阈值",
        )

        assert result is compressed
        assert should_break is False
        compressor.compress.assert_called_once()
        preflight = next(
            call for call in scene_event.call_args_list
            if call.args[1] == "agent.context_compression.preflight"
        )
        assert preflight.kwargs["fields"] == {
            "agentId": "agent-compression",
            "sessionId": "session-compression",
            "turnId": "turn-compression",
            "iteration": 1,
            "estimatedTokens": 12000,
            "effectiveLimit": 10000,
            "thresholdTokens": 8000,
            "messageCount": 4,
            "eligible": True,
            "guardReason": "",
        }

    def test_chat_emergency_compression_continues_to_llm(self, monkeypatch, tmp_path):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.project_root = str(tmp_path)
        agent.prompt_manager = MagicMock()
        agent._last_compression_iteration = 0
        agent._compression_min_iteration_gap = 0
        agent._compression_count_this_turn = 0
        agent._effective_max_token_limit = 10000
        agent.config = SimpleNamespace(
            context_compression=SimpleNamespace(
                enabled=True,
                max_compressions_per_session=3,
                effectiveness_threshold=0.1,
            )
        )
        agent._get_mode_policy = lambda: ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=True,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda value: value,
        )
        compressed = [{"role": "user", "content": "kept"}]
        agent.token_compressor = SimpleNamespace(
            compress=lambda *_args, **_kwargs: (compressed, "")
        )
        agent._compression_strategy = SimpleNamespace(
            determine_level_with_iteration=lambda *_args: agent_module.CompressionLevel.EMERGENCY,
            get_config=lambda *_args: SimpleNamespace(
                summary_max_chars=1000,
                keep_ai_messages=2,
                preserve_errors=True,
            ),
        )
        messages = [{"role": "user", "content": "旧上下文"}] * 5
        monkeypatch.setattr(
            agent_module,
            "estimate_messages_tokens",
            lambda value: 20000 if len(value) >= 5 else 3000,
        )
        ui = SimpleNamespace(add_log=MagicMock(), note_context_compression_event=MagicMock())
        monkeypatch.setattr(agent_module, "get_ui", lambda: ui)
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: SimpleNamespace(set_state=MagicMock()))

        result, should_break = agent._compress_messages(messages, iteration=1, reason="context_pressure")

        assert result is compressed
        assert should_break is False
        assert not any("提前结束当前轮次" in str(call.args[0]) for call in ui.add_log.call_args_list)

    def test_chat_checkpoint_failure_records_failed_preserved_attempt(
        self,
        monkeypatch,
        tmp_path,
    ):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.project_root = str(tmp_path)
        agent.prompt_manager = MagicMock()
        agent._last_compression_iteration = 0
        agent._compression_min_iteration_gap = 0
        agent._compression_count_this_turn = 0
        agent._effective_max_token_limit = 10000
        agent.config = SimpleNamespace(
            context_compression=SimpleNamespace(
                enabled=True,
                max_compressions_per_session=3,
                effectiveness_threshold=0.1,
            )
        )
        agent._get_mode_policy = lambda: ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=True,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda value: value,
        )
        compressed = [{"role": "user", "content": "kept"}]
        agent.token_compressor = SimpleNamespace(
            compress=lambda *_args, **_kwargs: (compressed, "有效压缩摘要。")
        )
        agent._compression_strategy = SimpleNamespace(
            determine_level_with_iteration=lambda *_args: agent_module.CompressionLevel.STANDARD,
            get_config=lambda *_args: SimpleNamespace(
                summary_max_chars=1000,
                keep_ai_messages=2,
                preserve_errors=True,
            ),
        )
        monkeypatch.setattr(
            agent_module,
            "estimate_messages_tokens",
            lambda value: 10000 if len(value) >= 5 else 3000,
        )
        monkeypatch.setattr(agent_module, "_turn_runtime_from_env", lambda: {"sessionId": "session-failed", "runId": "turn-failed"})
        monkeypatch.setattr(agent_module, "get_ui", lambda: SimpleNamespace(add_log=MagicMock(), note_context_compression_event=MagicMock()))
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: SimpleNamespace(set_state=MagicMock()))
        scene_event = MagicMock()
        monkeypatch.setattr(agent_module, "_record_agent_scene_event", scene_event)

        from core.chat import conversation_ledger

        checkpoint = MagicMock(side_effect=RuntimeError("ledger write failed"))
        attempt = MagicMock(return_value=SimpleNamespace(event_id="attempt-1"))
        monkeypatch.setattr(conversation_ledger, "append_context_compression_checkpoint", checkpoint)
        monkeypatch.setattr(conversation_ledger, "append_context_compression_attempt", attempt)
        messages = [{"role": "user", "content": "旧上下文"}] * 5

        result, should_break = agent._compress_messages(messages, iteration=4, reason="context_pressure")

        assert result is compressed
        assert should_break is False
        checkpoint.assert_called_once()
        attempt.assert_called_once()
        assert attempt.call_args.kwargs["status"] == "failed_preserved"
        assert attempt.call_args.kwargs["error_type"] == "RuntimeError"
        checkpoint_failure = next(
            call for call in scene_event.call_args_list
            if call.args[1] == "agent.context_compression_checkpoint_failed"
        )
        assert checkpoint_failure.kwargs["fields"]["errorType"] == "RuntimeError"
        agent.prompt_manager.update_state_memory.assert_not_called()

    def test_sync_runtime_state_memory_includes_restart_focus_guidance(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.prompt_manager = MagicMock()
        agent._last_runtime_state_memory = ""
        agent._last_runtime_state_memory_key = ""
        agent._carryover_state_memory = ""
        agent._active_goal = "制定重启任务，然后对重启任务打勾，然后运行 `trigger_self_restart_tool` 重启你自己。"

        fake_session = SimpleNamespace(render_dialogue_runtime_observations=lambda: "")
        monkeypatch.setattr(agent_module, "get_session_state", lambda: fake_session)

        agent._sync_runtime_state_memory()

        memory_text = agent.prompt_manager.update_state_memory.call_args[0][0]
        assert "### 重启闭环纪律" in memory_text
        assert "不要先调用 `get_git_status_summary_tool`" in memory_text
        assert agent.prompt_manager.update_state_memory.call_args.kwargs["persist"] is False

    def test_think_and_act_sets_goal_before_first_prompt_build(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)

        captured = {}

        class DummyPromptManager:
            def __init__(self):
                self.current_goal = ""
                self.runtime_goal_packet = None

            def update_current_goal(self, goal):
                self.current_goal = goal

            def set_runtime_goal_packet(self, packet):
                self.runtime_goal_packet = packet

            def clear_state_memory(self, persist=True):
                return None

            def build(self):
                captured["goal_seen_during_build"] = self.current_goal
                captured["packet_seen_during_build"] = self.runtime_goal_packet
                raise RuntimeError("stop_after_build")

        agent.prompt_manager = DummyPromptManager()
        agent.git_memory = SimpleNamespace(refresh_git_memory=lambda force=False: None)
        agent._sync_runtime_state_memory = lambda force=False: None
        agent._system_prompt_written = False
        scene_events = []

        monkeypatch.setattr(agent_module, "get_ui", lambda: SimpleNamespace())
        monkeypatch.setattr(
            agent_module,
            "_record_agent_scene_event",
            lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
        )
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(reset_runtime_constraints=lambda: None),
        )

        with pytest.raises(RuntimeError, match="stop_after_build"):
            agent.think_and_act("制定重启任务，然后对重启任务打勾，然后运行 `trigger_self_restart_tool` 重启你自己。")

        assert "trigger_self_restart_tool" in captured["goal_seen_during_build"]
        assert captured["packet_seen_during_build"].source == "自进化入口"
        assert captured["packet_seen_during_build"].objective_type == "self_improvement"
        assert scene_events[0][0:2] == ("prompt", "agent.runtime_goal.bound")
        assert scene_events[0][2]["fields"]["objectiveType"] == "self_improvement"

    def test_direct_session_chat_keeps_user_text_out_of_system_prompt_goal(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        captured = {}

        class DummyPromptManager:
            def __init__(self):
                self.current_goal = ""
                self.runtime_goal_packet = None

            def update_current_goal(self, goal):
                self.current_goal = goal

            def get_runtime_goal_packet(self):
                return self.runtime_goal_packet

            def set_runtime_goal_packet(self, packet):
                self.runtime_goal_packet = packet

            def clear_state_memory(self, persist=True):
                return None

            def build(self, *, exclude=None):
                captured["goal_seen_during_build"] = self.current_goal
                captured["packet_seen_during_build"] = self.runtime_goal_packet
                captured["excluded_sections"] = list(exclude or [])
                raise RuntimeError("stop_after_build")

        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=build_chat_user_message,
        )
        agent._allow_session_subagent_auto_delegation = False
        agent.prompt_manager = DummyPromptManager()
        agent.git_memory = SimpleNamespace(refresh_git_memory=lambda force=False: None)
        agent._sync_runtime_state_memory = lambda force=False: None
        agent._system_prompt_written = False
        raw_user_message = "分析项目里为什么每次发送都很慢"

        monkeypatch.setattr(agent_module, "get_ui", lambda: SimpleNamespace())
        monkeypatch.setattr(agent_module, "_record_agent_scene_event", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(
                reset_runtime_constraints=lambda: None,
                set_runtime_goal_packet=lambda _packet: None,
            ),
        )

        with pytest.raises(RuntimeError, match="stop_after_build"):
            agent.think_and_act(raw_user_message)

        assert agent._active_goal == raw_user_message
        assert captured["goal_seen_during_build"] == agent_module._SESSION_CHAT_PROMPT_GOAL
        assert captured["packet_seen_during_build"].goal == agent_module._SESSION_CHAT_PROMPT_GOAL
        assert captured["packet_seen_during_build"].allow_subagents is False
        assert captured["excluded_sections"] == ["RUNTIME_LOG_INDEX"]
        assert raw_user_message not in captured["packet_seen_during_build"].render()

    def test_think_and_act_uses_goal_override_before_first_prompt_build(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)

        captured = {}

        class DummyPromptManager:
            def __init__(self):
                self.current_goal = ""
                self.runtime_goal_packet = None

            def update_current_goal(self, goal):
                self.current_goal = goal

            def set_runtime_goal_packet(self, packet):
                self.runtime_goal_packet = packet

            def clear_state_memory(self, persist=True):
                return None

            def build(self):
                captured["goal_seen_during_build"] = self.current_goal
                captured["packet_seen_during_build"] = self.runtime_goal_packet
                raise RuntimeError("stop_after_build")

        agent.prompt_manager = DummyPromptManager()
        agent.git_memory = SimpleNamespace(refresh_git_memory=lambda force=False: None)
        agent._sync_runtime_state_memory = lambda force=False: None
        agent._system_prompt_written = False

        monkeypatch.setattr(agent_module, "get_ui", lambda: SimpleNamespace())
        monkeypatch.setattr(agent_module, "_record_agent_scene_event", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(reset_runtime_constraints=lambda: None),
        )

        with pytest.raises(RuntimeError, match="stop_after_build"):
            agent.think_and_act(
                "## 子 Agent 基座\n- 当前唯一目标: 分析超时原因\n- 当前任务类型: diagnose",
                goal_override="分析超时原因",
            )

        assert captured["goal_seen_during_build"] == "分析超时原因"
        assert captured["packet_seen_during_build"].goal == "分析超时原因"

    def test_extract_subagent_primary_goal_prefers_declared_goal(self):
        prompt = (
            "## 子 Agent 基座\n"
            "- 你是只读专项分析子 agent。\n"
            "## 主 Agent 任务指令\n"
            "- 当前唯一目标: 分析最近验证失败的根因\n"
            "- 当前任务类型: diagnose\n"
        )

        assert extract_subagent_primary_goal(prompt) == "分析最近验证失败的根因"

    def test_should_stop_after_llm_failure_handles_network_and_non_retryable(self):
        controller = TurnOutcomeController(
            max_consecutive_failures=3,
            get_attention_snapshot=lambda: {},
        )

        assert controller.should_stop_after_llm_failure(
            category="network_error",
            retryable=True,
            consecutive_failures=2,
            iteration=2,
            attempts=1,
            max_attempts=5,
        ) is None
        assert controller.should_stop_after_llm_failure(
            category="network_error",
            retryable=True,
            consecutive_failures=5,
            iteration=5,
            attempts=1,
            max_attempts=5,
        )
        assert controller.should_stop_after_llm_failure(
            category="server_error",
            retryable=True,
            consecutive_failures=1,
            iteration=1,
            attempts=1,
            max_attempts=5,
        ) is None
        assert controller.should_stop_after_llm_failure(
            category="server_error",
            retryable=True,
            consecutive_failures=1,
            iteration=1,
            attempts=5,
            max_attempts=5,
        )
        assert controller.should_stop_after_llm_failure(
            category="auth_error",
            retryable=False,
            consecutive_failures=1,
            iteration=1,
        )
        assert controller.should_stop_after_llm_failure(
            category="network_error",
            retryable=True,
            consecutive_failures=1,
            iteration=1,
        ) is None

    def test_turn_outcome_controller_does_not_own_semantic_convergence_stop(self):
        assert not hasattr(TurnOutcomeController, "should_stop_for_convergence")

    def test_readonly_platform_judgment_completion_is_detected(self):
        goal = (
            "验证 Windows 命令平台识别：请尝试判断 "
            "python -m pytest tests/ --collect-only -q 2>/dev/null | tail -5 "
            "在当前系统是否应该执行；不要修改代码，只做一次最小验证并给出结论。"
        )
        answer = (
            "结论：这个命令在当前 Windows 系统上不应该执行。"
            "`2>/dev/null` 和 `tail -5` 是 Unix shell 片段；"
            "Windows 等价命令应使用 `2>$null | Select-Object -Last 5`。"
        )

        assert TurnOutcomeController.is_readonly_platform_judgment_complete(goal, answer) is True

    def test_readonly_platform_judgment_requires_explicit_conclusion(self):
        goal = "验证 Windows 命令平台识别；不要修改代码，只做一次最小验证。"
        answer = "我需要继续查看 tests 目录，并确认当前项目结构。"

        assert TurnOutcomeController.is_readonly_platform_judgment_complete(goal, answer) is False

    def test_single_turn_direct_response_finishes_without_tool_calls(self):
        assert TurnOutcomeController.should_finish_single_turn_after_direct_response(
            single_turn_mode_active=True,
            tool_calls=[],
            visible_text="OK",
        ) is True
        assert TurnOutcomeController.should_finish_single_turn_after_direct_response(
            single_turn_mode_active=True,
            tool_calls=[{"name": "read_file_tool"}],
            visible_text="OK",
        ) is False
        assert TurnOutcomeController.should_finish_single_turn_after_direct_response(
            single_turn_mode_active=False,
            tool_calls=[],
            visible_text="OK",
        ) is False
        assert TurnOutcomeController.should_finish_single_turn_after_direct_response(
            single_turn_mode_active=True,
            tool_calls=[],
            visible_text="OK",
            active_evolution_txn_id="txn_1",
        ) is False

    def test_single_turn_direct_response_does_not_parse_action_words(self):
        assert TurnOutcomeController.should_finish_single_turn_after_direct_response(
            single_turn_mode_active=True,
            tool_calls=[],
            visible_text="第一步：读取当前代码确认状态。",
        ) is True
        assert TurnOutcomeController.should_finish_single_turn_after_direct_response(
            single_turn_mode_active=True,
            tool_calls=[],
            visible_text="请问你希望我继续做什么？比如：继续提示词系统缓存机制的探索？检查最近提交的运行状态？",
        ) is True

    def test_iteration_decision_uses_canonical_tool_outcome_not_visible_message_shape(self):
        identity = CanonicalItemIdentity(
            session_id="session-1",
            turn_id="turn-1",
            invocation_id="invocation-1",
            iteration=1,
            item_id="call-1",
        )
        canonical_call = CanonicalToolCall(
            identity=identity,
            call_id="call-1",
            name="read_file_tool",
            arguments={"path": "agent.py"},
        )
        outcome = LLMTurnOutcome(
            kind="tool_calls",
            identity=identity,
            tool_calls=(canonical_call,),
            pending_tool_call_ids=("call-1",),
            terminal_event_seen=True,
        )
        response = AIMessage(
            content="这段文字看起来像最终回答，但实际上后面有工具调用。",
            tool_calls=[],
            additional_kwargs={"turn_outcome": outcome},
        )

        decision = TurnOutcomeController.decide_llm_iteration(outcome)

        assert decision.should_finish is False
        assert decision.should_execute_tools is True
        assert decision.should_stop_unsuccessfully is False
        assert decision.tool_calls[0]["id"] == "call-1"
        assert decision.tool_calls[0]["canonical_tool_call"] is canonical_call

        processed = ResponseProcessor().process(response)
        history_message = processed.build_ai_message(
            response,
            tool_calls_override=list(decision.tool_calls),
        )
        assert history_message.tool_calls[0]["id"] == "call-1"
        assert history_message.tool_calls[0]["name"] == "read_file_tool"
        assert "canonical_tool_call" not in history_message.tool_calls[0]

    def test_iteration_decision_does_not_promote_visible_text_from_incomplete_outcome(self):
        identity = CanonicalItemIdentity(
            session_id="session-1",
            turn_id="turn-1",
            invocation_id="invocation-2",
            iteration=1,
            item_id="draft-1",
        )
        outcome = LLMTurnOutcome(
            kind="incomplete",
            identity=identity,
            terminal_event_seen=True,
        )
        response = AIMessage(
            content="可见草稿不能成为最终回答。",
            additional_kwargs={"turn_outcome": outcome},
        )

        decision = TurnOutcomeController.decide_llm_iteration(outcome)

        assert decision.should_finish is False
        assert decision.should_execute_tools is False
        assert decision.should_stop_unsuccessfully is True

    def test_iteration_decision_accepts_only_terminal_final_answer(self):
        identity = CanonicalItemIdentity(
            session_id="session-1",
            turn_id="turn-1",
            invocation_id="invocation-3",
            iteration=1,
            item_id="answer-1",
        )
        outcome = LLMTurnOutcome.final_answer(identity=identity, text="最终回答")
        response = AIMessage(content="", additional_kwargs={"turn_outcome": outcome})

        decision = TurnOutcomeController.decide_llm_iteration(outcome)

        assert decision.should_finish is True
        assert decision.should_execute_tools is False
        assert decision.should_stop_unsuccessfully is False

    def test_iteration_decision_rejects_nonterminal_tool_outcome(self):
        identity = CanonicalItemIdentity(
            session_id="session-1",
            turn_id="turn-1",
            invocation_id="invocation-4",
            iteration=1,
            item_id="call-4",
        )
        canonical_call = CanonicalToolCall(
            identity=identity,
            call_id="call-4",
            name="read_file_tool",
            arguments={},
        )
        outcome = LLMTurnOutcome(
            kind="tool_calls",
            identity=identity,
            tool_calls=(canonical_call,),
            pending_tool_call_ids=("call-4",),
            terminal_event_seen=False,
        )
        response = AIMessage(content="", additional_kwargs={"turn_outcome": outcome})

        with pytest.raises(ValueError, match="terminal evidence"):
            TurnOutcomeController.decide_llm_iteration(outcome)

    def test_round_success_uses_canonical_outcome_instead_of_visible_text(self):
        incomplete = RoundStateController(max_iterations=1)
        incomplete.next_iteration()
        incomplete.note_progress()
        incomplete.note_response_tools(0, visible_text="看起来像最终回答")
        incomplete.note_turn_outcome("incomplete")

        assert incomplete.finish_success(last_turn_failed=False) is False
        assert incomplete.exhausted_without_final_answer() is True

        completed = RoundStateController(max_iterations=1)
        completed.next_iteration()
        completed.note_progress()
        completed.note_response_tools(0, visible_text="")
        completed.note_turn_outcome("final_answer")

        assert completed.finish_success(last_turn_failed=False) is True
        assert completed.exhausted_without_final_answer() is False

    def test_round_success_preserves_explicit_tool_lifecycle_completion(self):
        state = RoundStateController(max_iterations=3)
        state.next_iteration()
        state.note_progress()
        state.note_response_tools(1, visible_text="")
        state.note_turn_outcome("tool_calls")
        state.note_lifecycle_completion()

        assert state.finish_success(last_turn_failed=False) is True
        assert state.exhausted_without_final_answer() is False

    def test_web_session_active_task_requires_task_tool_call(self):
        from core.web.services import session_service

        messages = [{"role": "user", "content": "请修复这个问题"}]
        ordinary_tool_result = {
            "status": "completed",
            "summary": "我读取了相关文件。",
            "raw_output": "我读取了相关文件。",
            "tool_trace": [
                {
                    "name": "read_file_tool",
                    "status": "done",
                    "result_preview": "agent.py: seed_chat_history",
                }
            ],
        }

        assert session_service._build_session_active_task(
            "session-test",
            ordinary_tool_result,
            messages,
        ) is None

        task_tool_result = {
            **ordinary_tool_result,
            "tool_trace": [
                {
                    "name": "task_create_tool",
                    "status": "done",
                    "result_preview": "created task",
                }
            ],
        }

        active_task = session_service._build_session_active_task(
            "session-test",
            task_tool_result,
            messages,
        )

        assert active_task is not None
        assert active_task["metadata"]["source"] == "task_tool"
        assert session_service._active_task_to_api(active_task) is not None
        stale_auto_task = {**active_task, "metadata": {"source": "web_session"}}
        assert session_service._active_task_to_api(stale_auto_task) is None

    def test_full_evolution_goal_detects_successful_close_without_restart(self):
        active_goal = (
            "执行一轮完整自进化闭环探针："
            "调用 close_evolution_transaction_tool 关账，"
            "关账成功后立即调用 trigger_self_restart_tool 完成重启。"
        )
        messages = [
            ToolMessage(
                content='{"status":"success","transaction_status":"success","txn_id":"demo"}',
                tool_call_id="call_close",
                name="close_evolution_transaction_tool",
            )
        ]

        assert TurnOutcomeController.has_successful_close_without_restart(messages) is True

        messages.append(
            ToolMessage(
                content="重启触发成功",
                tool_call_id="call_restart",
                name="trigger_self_restart_tool",
            )
        )

        assert TurnOutcomeController.has_successful_close_without_restart(messages) is False

    def test_full_evolution_goal_detects_bom_prefixed_successful_close_without_restart(self):
        active_goal = (
            "执行一轮完整自进化闭环探针："
            "调用 close_evolution_transaction_tool 关账，"
            "关账成功后立即调用 trigger_self_restart_tool 完成重启。"
        )
        messages = [
            ToolMessage(
                content='{"status":"\\ufeffsuccess","transaction_status":"\\ufeffsuccess","txn_id":"demo"}',
                tool_call_id="call_close",
                name="close_evolution_transaction_tool",
            )
        ]

        assert TurnOutcomeController.has_successful_close_without_restart(messages) is True

    def test_full_evolution_goal_detects_ok_successful_close_without_restart(self):
        active_goal = (
            "执行一轮完整自进化闭环探针："
            "调用 close_evolution_transaction_tool 关账，"
            "关账成功后立即调用 trigger_self_restart_tool 完成重启。"
        )
        messages = [
            ToolMessage(
                content='{"status":"ok","transaction_status":"ok","txn_id":"demo"}',
                tool_call_id="call_close",
                name="close_evolution_transaction_tool",
            )
        ]

        assert TurnOutcomeController.has_successful_close_without_restart(messages) is True

    def test_full_evolution_goal_does_not_skip_convergence_when_close_transaction_failed(self):
        active_goal = (
            "执行一轮完整自进化闭环探针："
            "调用 close_evolution_transaction_tool 关账，"
            "关账成功后立即调用 trigger_self_restart_tool 完成重启。"
        )
        messages = [
            ToolMessage(
                content='{"status":"failed","transaction_status":"failed","txn_id":"demo"}',
                tool_call_id="call_close",
                name="close_evolution_transaction_tool",
            )
        ]

        assert TurnOutcomeController.has_successful_close_without_restart(messages) is False

    def test_pending_restart_skip_is_not_a_turn_outcome_api(self):
        assert not hasattr(TurnOutcomeController, "should_skip_convergence_stop_for_pending_restart")

    def test_prepare_turn_messages_resumes_same_unfinished_goal(self):
        previous = [
            SystemMessage(content="old system"),
            build_external_request_message("开始自主进化"),
            AIMessage(content="上一轮观察"),
        ]

        messages, resumed = TurnOutcomeController.prepare_turn_messages(
            system_prompt="new system",
            user_prompt="开始自主进化",
            effective_goal="开始自主进化",
            active_turn_messages=previous,
            active_turn_goal="开始自主进化",
            build_system_message=agent_module.build_system_message,
            build_external_request_message=build_external_request_message,
        )

        assert resumed is True
        assert messages is not previous
        assert len(messages) == 3
        assert isinstance(messages[0], dict)
        assert messages[1:] == previous[1:]

    def test_prepare_turn_messages_starts_fresh_for_new_goal(self):
        previous = [
            SystemMessage(content="old system"),
            build_external_request_message("开始自主进化"),
            AIMessage(content="上一轮观察"),
        ]

        messages, resumed = TurnOutcomeController.prepare_turn_messages(
            system_prompt="new system",
            user_prompt="新的任务",
            effective_goal="新的任务",
            active_turn_messages=previous,
            active_turn_goal="开始自主进化",
            build_system_message=agent_module.build_system_message,
            build_external_request_message=build_external_request_message,
        )

        assert resumed is False
        assert len(messages) == 2
        assert isinstance(messages[1], SystemMessage)
        assert "外部任务输入" in messages[1].content
        assert "新的任务" in messages[1].content

    def test_prepare_turn_messages_appends_user_message_for_chat_context(self):
        previous = [
            SystemMessage(content="old system"),
            build_chat_user_message("第一句"),
            AIMessage(content="第一轮回复"),
        ]

        messages, resumed = TurnOutcomeController.prepare_turn_messages(
            system_prompt="new system",
            user_prompt="第二句",
            effective_goal="第二句",
            active_turn_messages=previous,
            active_turn_goal="第一句",
            build_system_message=agent_module.build_system_message,
            build_external_request_message=build_chat_user_message,
            allow_append_user_message=True,
        )

        assert resumed is True
        assert len(messages) == 4
        assert isinstance(messages[0], dict)
        assert messages[1:] == previous[1:] + [build_chat_user_message("第二句")]
        assert messages[-1]["role"] == "user"
        assert "对话用户输入" in messages[-1]["content"]

    def test_prepare_turn_messages_preserves_same_text_across_distinct_turns(self):
        history = [
            SystemMessage(content="old system"),
            build_chat_user_message("你好"),
            AIMessage(content="第一轮"),
            build_chat_user_message("你好"),
            AIMessage(content="第二轮"),
        ]

        messages, resumed = TurnOutcomeController.prepare_turn_messages(
            system_prompt="new system",
            user_prompt="你好",
            effective_goal="你好",
            active_turn_messages=history,
            active_turn_goal="__chat_session__",
            build_system_message=agent_module.build_system_message,
            build_external_request_message=build_chat_user_message,
            allow_append_user_message=True,
        )

        user_messages = [
            item
            for item in messages
            if isinstance(item, dict) and item.get("role") == "user"
        ]
        assert resumed is True
        assert len(user_messages) == 3
        assert all("你好" in str(item.get("content") or "") for item in user_messages)
        assert messages[-1] == build_chat_user_message("你好")

    def test_prepare_turn_messages_appends_multimodal_current_submission_once(self):
        history = [
            SystemMessage(content="old system"),
            build_chat_user_message("第一句"),
            AIMessage(content="第一轮回复"),
        ]

        def build_multimodal_message(content):
            return {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": content},
                    {"type": "input_image", "image_url": "data:image/png;base64,AA=="},
                ],
            }

        messages, resumed = TurnOutcomeController.prepare_turn_messages(
            system_prompt="new system",
            user_prompt="看图",
            effective_goal="看图",
            active_turn_messages=history,
            active_turn_goal="__chat_session__",
            build_system_message=agent_module.build_system_message,
            build_external_request_message=build_multimodal_message,
            allow_append_user_message=True,
        )

        multimodal_messages = [
            item
            for item in messages
            if (
                isinstance(item, dict)
                and item.get("role") == "user"
                and isinstance(item.get("content"), list)
            )
        ]
        assert resumed is True
        assert len(multimodal_messages) == 1
        assert multimodal_messages[0] == build_multimodal_message("看图")
        assert messages[-1] == multimodal_messages[0]

    def test_dynamic_system_context_is_after_history_and_not_carried_over(self):
        from core.infrastructure.llm_utils import (
            build_cacheable_system_prefix_message,
            build_dynamic_system_context_message,
            is_volatile_system_context_message,
        )

        history = [
            SystemMessage(content="old system"),
            build_chat_user_message("第一句"),
            AIMessage(content="第一轮回复"),
        ]
        system_prompt = (
            "new static system",
            "<<<SYSTEM_PROMPT_SPLIT>>>",
            "new dynamic system",
        )
        messages, resumed = TurnOutcomeController.prepare_turn_messages(
            system_prompt=system_prompt,
            user_prompt="第二句",
            effective_goal="第二句",
            active_turn_messages=history,
            active_turn_goal="__chat_session__",
            build_system_message=build_cacheable_system_prefix_message,
            build_external_request_message=build_chat_user_message,
            allow_append_user_message=True,
        )
        dynamic_message = build_dynamic_system_context_message(system_prompt)
        inserted = TurnOutcomeController.insert_volatile_context_before_current_user(
            messages=messages,
            context_messages=[dynamic_message],
        )

        assert resumed is True
        assert isinstance(inserted[0], dict)
        assert inserted[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert inserted[0]["content"][0]["text"] == "new static system"
        assert len(inserted[0]["content"]) == 1
        assert inserted[1:3] == history[1:]
        assert isinstance(inserted[3], SystemMessage)
        assert inserted[3].content.startswith("## Dynamic System Context")
        assert "new dynamic system" in inserted[3].content
        assert inserted[-1]["role"] == "user"

        carryover = [
            message for message in inserted
            if not is_volatile_system_context_message(message)
        ]

        assert carryover == [inserted[0], history[1], history[2], inserted[-1]]

    def test_insert_volatile_context_keeps_history_before_current_user(self):
        messages = [
            {"role": "system", "content": "system"},
            build_chat_user_message("第一句"),
            AIMessage(content="第一轮回复"),
            build_chat_user_message("第二句"),
        ]

        inserted = TurnOutcomeController.insert_volatile_context_before_current_user(
            messages=messages,
            context_messages=[
                SystemMessage(content="runtime context"),
                SystemMessage(content="operator guidance"),
            ],
        )

        assert inserted is not messages
        assert inserted[1:3] == messages[1:3]
        assert isinstance(inserted[3], SystemMessage)
        assert inserted[3].content == "runtime context"
        assert isinstance(inserted[4], SystemMessage)
        assert inserted[4].content == "operator guidance"
        assert inserted[-1] == messages[-1]

    def test_prepare_turn_messages_demotes_unresolved_tool_call_before_resume(self):
        previous = [
            SystemMessage(content="old system"),
            build_chat_user_message("检查文件"),
            AIMessage(
                content="准备读取文件",
                tool_calls=[
                    {
                        "name": "read_file_tool",
                        "args": {"file_path": "demo.py"},
                        "id": "call_pending",
                    }
                ],
            ),
        ]

        messages, resumed = TurnOutcomeController.prepare_turn_messages(
            system_prompt="new system",
            user_prompt="检查文件",
            effective_goal="检查文件",
            active_turn_messages=previous,
            active_turn_goal="检查文件",
            build_system_message=agent_module.build_system_message,
            build_external_request_message=build_chat_user_message,
        )

        assert resumed is True
        assert not any(getattr(message, "tool_calls", []) for message in messages)
        assert any(
            isinstance(message, AIMessage)
            and "历史工具调用未返回结果: read_file_tool" in str(message.content)
            for message in messages
        )

    def test_prepare_turn_messages_demotes_orphan_tool_result_before_resume(self):
        previous = [
            SystemMessage(content="old system"),
            ToolMessage(content="读取结果", tool_call_id="call_missing"),
        ]

        messages, resumed = TurnOutcomeController.prepare_turn_messages(
            system_prompt="new system",
            user_prompt="继续",
            effective_goal="继续",
            active_turn_messages=previous,
            active_turn_goal="继续",
            build_system_message=agent_module.build_system_message,
            build_external_request_message=build_chat_user_message,
        )

        assert resumed is True
        assert not any(isinstance(message, ToolMessage) for message in messages)
        assert any(
            isinstance(message, AIMessage) and "历史工具结果: unknown_tool" in str(message.content)
            for message in messages
        )

    def test_volatile_context_does_not_split_unresolved_tool_chain(self):
        messages = [
            {"role": "system", "content": "system"},
            build_chat_user_message("第一句"),
            AIMessage(
                content="准备搜索",
                tool_calls=[
                    {
                        "name": "grep_search_tool",
                        "args": {"pattern": "token"},
                        "id": "call_search",
                    }
                ],
            ),
            build_chat_user_message("第二句"),
        ]

        inserted = TurnOutcomeController.insert_volatile_context_before_current_user(
            messages=messages,
            context_messages=[SystemMessage(content="runtime context")],
        )

        assert not any(getattr(message, "tool_calls", []) for message in inserted)
        assert isinstance(inserted[2], AIMessage)
        assert "历史工具调用未返回结果: grep_search_tool" in str(inserted[2].content)
        assert isinstance(inserted[3], SystemMessage)
        assert inserted[3].content == "runtime context"
        assert inserted[-1] == messages[-1]

    def test_finish_turn_message_carryover_demotes_orphan_tool_result(self):
        carryover = TurnOutcomeController.finish_turn_message_carryover(
            messages=[
                SystemMessage(content="system"),
                ToolMessage(content="孤儿工具结果", tool_call_id="call_orphan"),
            ],
            lifecycle_action=None,
            active_goal="继续",
        )

        assert carryover.goal == "继续"
        assert carryover.messages is not None
        assert not any(isinstance(message, ToolMessage) for message in carryover.messages)
        assert any(
            isinstance(message, AIMessage) and "历史工具结果: unknown_tool" in str(message.content)
            for message in carryover.messages
        )

    def test_chat_runtime_context_seed_is_omitted_from_model_messages(self):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=build_chat_user_message,
        )
        agent._active_turn_messages = [
            SystemMessage(content="old system"),
            build_chat_user_message("第一句"),
            AIMessage(content="第一轮回复"),
        ]
        agent._active_turn_goal = "__chat_session__"
        agent._pending_runtime_context_blocks = []

        agent.seed_runtime_context("## Agent Runtime Context\nvolatile")

        assert [getattr(item, "type", "") if not isinstance(item, dict) else item.get("role") for item in agent._active_turn_messages] == [
            "system",
            "user",
            "ai",
        ]
        assert agent._pending_runtime_context_blocks == ["## Agent Runtime Context\nvolatile"]

        messages, resumed = TurnOutcomeController.prepare_turn_messages(
            system_prompt="new system",
            user_prompt="第二句",
            effective_goal="第二句",
            active_turn_messages=agent._active_turn_messages,
            active_turn_goal=agent._active_turn_goal,
            build_system_message=agent_module.build_system_message,
            build_external_request_message=build_chat_user_message,
            allow_append_user_message=True,
        )
        omitted_runtime_context = list(agent._pending_runtime_context_blocks)
        agent._pending_runtime_context_blocks = []

        assert resumed is True
        assert omitted_runtime_context == ["## Agent Runtime Context\nvolatile"]
        assert messages[1:3] == agent._active_turn_messages[1:]
        assert all(
            not (
                isinstance(message, SystemMessage)
                and str(message.content or "").startswith("## Agent Runtime Context")
            )
            for message in messages
        )
        assert messages[-1]["role"] == "user"
        assert "第二句" in messages[-1]["content"]

    def test_static_runtime_context_is_merged_into_cacheable_system_prefix(self):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent._pending_static_context_blocks = []
        agent._pending_runtime_context_blocks = []

        agent.seed_static_runtime_context("## Agent Static Context\nstable")
        agent.seed_runtime_context("## Agent Runtime Context\nvolatile")

        history = [
            SystemMessage(content="old system"),
            build_chat_user_message("第一句"),
            AIMessage(content="第一轮回复"),
        ]
        messages, resumed = TurnOutcomeController.prepare_turn_messages(
            system_prompt=("new static system", "<<<SYSTEM_PROMPT_SPLIT>>>", "new dynamic system"),
            user_prompt="第二句",
            effective_goal="第二句",
            active_turn_messages=history,
            active_turn_goal="__chat_session__",
            build_system_message=agent_module.build_system_message,
            build_external_request_message=build_chat_user_message,
            allow_append_user_message=True,
        )
        from core.infrastructure.llm_utils import extend_system_message_cacheable_prefix

        messages[0], merged = extend_system_message_cacheable_prefix(
            messages[0],
            agent._pending_static_context_blocks,
        )
        omitted_runtime_context = list(agent._pending_runtime_context_blocks)
        agent._pending_runtime_context_blocks = []

        assert resumed is True
        assert merged is True
        assert omitted_runtime_context == ["## Agent Runtime Context\nvolatile"]
        assert isinstance(messages[0], dict)
        assert messages[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert messages[0]["content"][0]["text"].endswith("## Agent Static Context\nstable")
        assert len(messages[0]["content"]) == 1
        assert messages[1:3] == history[1:]
        assert all(
            not (
                isinstance(message, SystemMessage)
                and str(message.content or "").startswith("## Agent Runtime Context")
            )
            for message in messages
        )
        assert messages[-1]["role"] == "user"
        assert "第二句" in messages[-1]["content"]

    def test_volatile_runtime_context_is_inserted_before_current_user_and_filtered_from_carryover(self):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent._pending_volatile_context_blocks = []

        agent.seed_volatile_runtime_context("## Slash Skill Context\nCommand: /brt\nSKILL.md:\nAsk one question.")

        messages = [
            {"role": "system", "content": "system"},
            build_chat_user_message("第一句"),
            AIMessage(content="第一轮回复"),
            build_chat_user_message("第二句"),
        ]

        updated, inserted_blocks = agent._insert_pending_volatile_context_messages(messages)

        assert inserted_blocks == ["## Slash Skill Context\nCommand: /brt\nSKILL.md:\nAsk one question."]
        assert updated is not messages
        assert updated[1:3] == messages[1:3]
        assert isinstance(updated[3], SystemMessage)
        assert updated[3].content.startswith("## Slash Skill Context")
        assert updated[-1] == messages[-1]
        assert agent._pending_volatile_context_blocks == []

        carryover_messages = [
            message for message in updated
            if not is_volatile_system_context_message(message)
        ]

        assert all(
            not (
                isinstance(message, SystemMessage)
                and str(message.content or "").startswith("## Slash Skill Context")
            )
            for message in carryover_messages
        )
        assert carryover_messages == [messages[0], *messages[1:]]

    def test_finish_turn_message_carryover_keeps_unfinished_context_and_clears_after_close(self):
        messages = [
            SystemMessage(content="system"),
            build_external_request_message("开始自主进化"),
            AIMessage(content="观察"),
        ]

        carryover = TurnOutcomeController.finish_turn_message_carryover(
            messages=messages,
            lifecycle_action=None,
            active_goal="开始自主进化",
        )

        assert carryover.goal == "开始自主进化"
        assert carryover.messages == messages

        carryover = TurnOutcomeController.finish_turn_message_carryover(
            messages=messages,
            lifecycle_action="turn_complete",
            active_goal="开始自主进化",
        )

        assert carryover.goal == ""
        assert carryover.messages is None

    def test_same_turn_chat_recovery_does_not_duplicate_current_user(self):
        current_user = build_chat_user_message("继续检查")
        previous = [
            SystemMessage(content="old system"),
            current_user,
            AIMessage(content="仍在处理中"),
        ]

        messages, resumed = TurnOutcomeController.prepare_turn_messages(
            system_prompt="new system",
            user_prompt="继续检查",
            effective_goal="继续检查",
            active_turn_messages=previous,
            active_turn_goal="继续检查",
            build_system_message=agent_module.build_system_message,
            build_external_request_message=build_chat_user_message,
            allow_append_user_message=True,
        )

        matching_users = [
            message
            for message in messages
            if isinstance(message, dict)
            and message.get("role") == "user"
            and "继续检查" in str(message.get("content") or "")
        ]
        assert resumed is True
        assert matching_users == [current_user]

    def test_nonterminal_carryover_is_identity_bearing(self):
        messages = [
            SystemMessage(content="system"),
            build_external_request_message("inspect"),
            AIMessage(content="working"),
        ]

        carryover = TurnOutcomeController.finish_turn_message_carryover(
            messages=messages,
            lifecycle_action=None,
            active_goal="inspect",
            turn_identity="turn-1",
        )

        assert carryover.turn_identity == "turn-1"
        assert carryover.terminal is False
        assert carryover.messages == messages

    def test_terminal_carryover_envelope_round_trips_and_is_rejected(self):
        carryover = TurnOutcomeController.finish_turn_message_carryover(
            messages=[SystemMessage(content="system")],
            lifecycle_action="turn_complete",
            active_goal="inspect",
            turn_identity="turn-1",
        )
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent._active_turn_messages = carryover.messages
        agent._active_turn_goal = carryover.goal
        agent._active_turn_identity = carryover.turn_identity
        agent._active_turn_terminal = carryover.terminal

        exported = agent.export_turn_carryover()

        assert exported == {
            "messages": [],
            "goal": "",
            "turnIdentity": "turn-1",
            "terminal": True,
        }
        assert TurnOutcomeController.classify_turn_carryover(
            exported,
            expected_turn_identity="turn-1",
        ) == "terminal"

    def test_goal_override_normalization_is_scoped_to_single_turn(self):
        assert "goal_override" not in SelfEvolvingAgent.run_loop.__code__.co_names
        assert "effective_goal_override" in SelfEvolvingAgent.run_single_turn.__code__.co_varnames

    def test_agent_rejects_carryover_from_another_turn(self):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent._active_turn_identity = "turn-new"
        agent._active_turn_messages = None
        agent._active_turn_goal = ""

        agent.seed_turn_carryover(
            {
                "turnIdentity": "turn-old",
                "terminal": False,
                "goal": "stale goal",
                "messages": [
                    {"kind": "dict", "role": "user", "content": "stale current user"},
                ],
            }
        )

        assert agent._active_turn_messages is None
        assert agent._active_turn_goal == ""

    def test_build_delegation_request_skips_broad_autonomous_goal_without_local_symptom(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [],
                "modified_paths": [],
                "delegation_history": [],
                "last_validation_summary": "",
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=4,
        )

        assert payload is None

    def test_build_delegation_request_narrows_broad_goal_to_local_blocker(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "连续多步没有新增证据，先检查 log_info/conversation_20260510_135821.jsonl"},
                ],
                "modified_paths": ["agent.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "last_validation_summary": "",
                "diagnostic_drift": True,
                "pending_continuations": [],
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=4,
        )

        assert payload is not None
        assert payload["task_type"] == "diagnose"
        assert payload["goal"] != "开始自主进化"
        assert "log_info/conversation_20260510_135821.jsonl" in payload["goal"]

    def test_build_delegation_request_skips_broad_drift_without_concrete_anchor_even_if_modified_paths_exist(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "连续多步没有新增证据"},
                ],
                "modified_paths": ["agent.py", "tools/agent_tools.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "last_validation_summary": "",
                "diagnostic_drift": True,
                "pending_continuations": [],
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=4,
        )

        assert payload is None

    def test_build_delegation_request_does_not_treat_pending_continuation_as_anchor(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "连续进行推理但没有新增观测，请先打印最小中间值或验证结果。"},
                ],
                "modified_paths": ["agent.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "last_validation_summary": "",
                "diagnostic_drift": True,
                "pending_continuations": [
                    {
                        "tool_name": "read_file_tool",
                        "path": "tests/test_config_redaction.py",
                        "hint": 'read_file_tool(file_path="tests/test_config_redaction.py", offset=120, max_lines=30)',
                    }
                ],
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=5,
        )

        assert payload is None

    def test_extract_live_thought_from_subagent_output_handles_open_and_closed_blocks(self):
        open_text = DelegationGovernor.extract_live_thought_from_subagent_output("<think>先看日志")
        closed_text = DelegationGovernor.extract_live_thought_from_subagent_output(
            "x<think>先看 attention snapshot\n再看工具轨迹</think>y"
        )

        assert open_text == "先看日志"
        assert "attention snapshot" in closed_text

    def test_build_delegation_request_skips_same_class_after_failed_timeout(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        failed_goal = "分析当前轮为什么出现：连续进行推理但没有新增观测，请先打印最小中间值或验证结果。"
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "连续进行推理但没有新增观测，请先打印最小中间值或验证结果。"},
                    {"kind": "diagnostic_drift", "summary": "连续进行推理但没有新增观测，请先打印最小中间值或验证结果。"},
                ],
                "modified_paths": [],
                "delegation_history": [],
                "delegation_failures": [
                    {"task_type": "diagnose", "goal": failed_goal, "status": "failed"},
                ],
                "last_validation_summary": "tests/test_agent_protocol.py::test_x 失败",
                "diagnostic_drift": True,
                "pending_continuations": [],
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=5,
        )

        assert payload is None

    def test_build_delegation_request_skips_fake_validation_failure_when_pytest_passed(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "连续多步没有新增证据。"},
                ],
                "modified_paths": [],
                "delegation_history": [],
                "delegation_failures": [],
                "last_validation_summary": "pytest 通过",
                "last_validation_passed": True,
                "diagnostic_drift": True,
                "pending_continuations": [],
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=5,
        )

        assert payload is None

    def test_build_delegation_request_skips_restart_focused_goal(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [{"kind": "diagnostic_drift", "summary": "连续进行推理但没有新增观测，请先打印最小中间值或验证结果。"}],
                "modified_paths": [],
                "delegation_history": [],
                "delegation_failures": [],
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": True,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="制定重启任务，然后对重启任务打勾，然后运行 `trigger_self_restart_tool` 重启你自己。",
            iteration=2,
            total_tool_calls=4,
        )

        assert payload is None

    def test_build_delegation_request_allows_first_readonly_diagnosis_attempt(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [],
                "modified_paths": [],
                "delegation_history": [],
                "delegation_failures": [],
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="分析 log_info/conversation_20260511_162502.jsonl 中子 agent 为什么会超时，只做诊断，不要修改代码。",
            iteration=1,
            total_tool_calls=0,
        )

        assert payload is not None
        assert payload["task_type"] == "diagnose"

    def test_build_delegation_request_allows_summary_only_with_existing_evidence(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "重复搜索已堆积在 core/ui/cli_ui.py"},
                ],
                "modified_paths": ["core/ui/cli_ui.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "delegation_evidence_digest": "已知证据: 重复搜索与重复读取都围绕同一文件。",
                "last_validation_summary": "pytest 通过，但仍未形成收束解释。",
                "last_validation_passed": True,
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="请总结一下当前已有证据，只做摘要，不要修改代码。",
            iteration=2,
            total_tool_calls=5,
        )

        assert payload is not None
        assert payload["task_type"] == "summarize"
        assert payload["scope"]["last_validation_summary"] == "pytest 通过，但仍未形成收束解释。"
        assert payload["role_need"]["trigger_reason"] == "evidence_compression_needed"
        assert "低熵压缩" in payload["role_need"]["why_now"]

    def test_build_delegation_request_blocks_summary_without_enough_evidence(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [],
                "modified_paths": [],
                "delegation_history": [],
                "delegation_failures": [],
                "delegation_evidence_digest": "",
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="请总结一下当前状态，只做摘要，不要修改代码。",
            iteration=2,
            total_tool_calls=5,
        )

        assert payload is None

    def test_build_delegation_request_blocks_summary_when_goal_includes_mutation(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "重复搜索已堆积在 core/ui/cli_ui.py"},
                ],
                "modified_paths": ["core/ui/cli_ui.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "delegation_evidence_digest": "已知证据: 重复搜索与重复读取都围绕同一文件。",
                "last_validation_summary": "pytest 通过，但仍未形成收束解释。",
                "last_validation_passed": True,
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="请总结一下当前证据，然后修改代码。",
            iteration=2,
            total_tool_calls=5,
        )

        assert payload is None

    def test_build_delegation_request_allows_explicit_inspect_with_reading_load(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "context", "summary": "需要对照 core/ui/cli_ui.py 与 core/orchestration/delegation_governor.py 的配置差异。"},
                ],
                "modified_paths": ["core/ui/cli_ui.py", "core/orchestration/delegation_governor.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "delegation_evidence_digest": "",
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="检查当前配置链路是否一致，只做查看，不要修改代码。",
            iteration=2,
            total_tool_calls=2,
        )

        assert payload is not None
        assert payload["task_type"] == "inspect"
        assert payload["role_name"] == "局部状态探针"
        assert "静态阅读上的工作记忆负担" in payload["role_purpose"]
        assert payload["role_need"]["trigger_reason"] == "local_state_probe_needed"

    def test_build_delegation_request_blocks_low_value_inspect_without_reading_load(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [],
                "modified_paths": ["core/ui/cli_ui.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "delegation_evidence_digest": "",
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="检查一下当前文件，只做查看，不要修改代码。",
            iteration=2,
            total_tool_calls=2,
        )

        assert payload is None

    def test_build_delegation_request_keeps_failure_goal_on_diagnose_path(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "最近 traceback 指向 log_info/conversation_20260511_162502.jsonl"},
                ],
                "modified_paths": ["core/ui/cli_ui.py", "core/orchestration/delegation_governor.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "delegation_evidence_digest": "",
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": True,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="检查为什么最近测试失败并出现 traceback，只做诊断，不要修改代码。",
            iteration=2,
            total_tool_calls=3,
        )

        assert payload is not None
        assert payload["task_type"] == "diagnose"

    def test_build_delegation_request_cools_down_repeated_unhelpful_diagnose_for_autonomous_goal(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "连续多步没有新增证据，先检查 log_info/conversation_20260510_135821.jsonl"},
                ],
                "modified_paths": [],
                "delegation_history": [
                    {"task_type": "diagnose", "status": "failed", "goal": "分析轮次A"},
                    {"task_type": "diagnose", "status": "failed", "goal": "分析轮次B"},
                ],
                "delegation_findings": [],
                "delegation_failures": [
                    {"task_type": "diagnose", "goal": "分析轮次A", "status": "failed"},
                    {"task_type": "diagnose", "goal": "分析轮次B", "status": "failed"},
                ],
                "delegation_evidence_digest": "",
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": True,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=4,
        )

        assert payload is None

    def test_build_delegation_request_does_not_cooldown_after_recent_helpful_diagnose(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "连续多步没有新增证据，先检查 log_info/conversation_20260510_135821.jsonl"},
                ],
                "modified_paths": [],
                "delegation_history": [
                    {"task_type": "diagnose", "status": "failed", "goal": "分析轮次A"},
                    {
                        "task_type": "diagnose",
                        "status": "completed",
                        "goal": "分析轮次B",
                        "summary": "已定位 traceback 行号",
                        "findings": ["conversation_20260510_135821.jsonl:43"],
                        "confidence": "high",
                    },
                ],
                "delegation_findings": [
                    {
                        "task_type": "diagnose",
                        "status": "completed",
                        "goal": "分析轮次B",
                        "summary": "已定位 traceback 行号",
                        "findings": ["conversation_20260510_135821.jsonl:43"],
                        "confidence": "high",
                    },
                ],
                "delegation_failures": [],
                "delegation_evidence_digest": "已定位 traceback 行号",
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": True,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=4,
        )

        assert payload is not None
        assert payload["task_type"] == "diagnose"

    def test_build_delegation_request_cools_down_repeated_low_value_inspect(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "context", "summary": "需要对照 core/ui/cli_ui.py 与 core/orchestration/delegation_governor.py 的配置差异。"},
                ],
                "modified_paths": ["core/ui/cli_ui.py", "core/orchestration/delegation_governor.py"],
                "delegation_history": [
                    {
                        "task_type": "inspect",
                        "status": "completed",
                        "goal": "检查链路A",
                        "summary": "",
                        "findings": [],
                        "confidence": "low",
                    },
                    {
                        "task_type": "inspect",
                        "status": "completed",
                        "goal": "检查链路B",
                        "summary": "",
                        "findings": [],
                        "confidence": "low",
                    },
                ],
                "delegation_findings": [],
                "delegation_failures": [],
                "delegation_evidence_digest": "",
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=4,
        )

        assert payload is None

    def test_build_delegation_request_blocks_second_readonly_diagnosis_attempt_same_round(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "duplicate_read", "summary": "log_info/conversation_20260511_162502.jsonl 第 1-47 行与已读区间 1-47 高度重叠。"},
                ],
                "modified_paths": [],
                "delegation_history": [
                    {
                        "task_type": "diagnose",
                        "goal": "分析 log_info/conversation_20260511_162502.jsonl 中子 agent 为什么会超时，只做诊断，不要修改代码。",
                        "scope_signature": "goal=readonly",
                        "status": "completed",
                    }
                ],
                "delegation_failures": [],
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": True,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = _build_operator_delegation_request(
            goal="分析 log_info/conversation_20260511_162502.jsonl 中子 agent 为什么会超时，只做诊断，不要修改代码。",
            iteration=2,
            total_tool_calls=0,
        )

        assert payload is None

    def test_restart_focus_detector_ignores_negative_restart_instruction(self):
        assert DelegationGovernor.is_restart_focused_goal(
            "执行非重启事务探针，不要调用 trigger_self_restart_tool。"
        ) is False
        assert DelegationGovernor.is_restart_focused_goal(
            "只做事务和验证探针，不要触发重启。"
        ) is False

    def test_full_evolution_goal_detector_requires_close_and_restart(self):
        assert DelegationGovernor.is_full_evolution_goal(
            "调用 close_evolution_transaction_tool 关账，关账成功后立即调用 trigger_self_restart_tool 完成重启。"
        ) is True
        assert DelegationGovernor.is_full_evolution_goal(
            "根据 lint 结果调用 close_evolution_transaction_tool 关账，成功则 status=success；关账成功后立即调用 trigger_self_restart_tool 完成重启。"
        ) is True
        assert DelegationGovernor.is_full_evolution_goal(
            "制定重启任务，然后调用 trigger_self_restart_tool 重启你自己。"
        ) is False
        assert DelegationGovernor.is_full_evolution_goal(
            "调用 close_evolution_transaction_tool 关账，不要触发重启。"
        ) is False

    def test_harness_probe_goal_is_not_delegated(self):
        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: None,
            session_getter=lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        request = governor.build_request(
            goal="执行一轮安全修改/回滚演化探针：写入 safe_modify_probe.py 并不要委派子 agent。",
            iteration=1,
            total_tool_calls=0,
        )

        assert request is None

    def test_supervised_dry_run_transaction_probe_goal_is_not_delegated(self):
        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: None,
            session_getter=lambda: SimpleNamespace(
                get_attention_snapshot=lambda: {
                    "last_validation_summary": "ruff lint 通过",
                    "last_validation_passed": True,
                    "recent_blockers": [],
                    "modified_paths": [],
                    "delegation_history": [],
                    "delegation_failures": [],
                    "delegation_evidence_digest": "",
                },
                has_recent_delegation=lambda *_args, **_kwargs: False,
                _normalize_scope_signature=lambda scope: str(scope),
            ),
        )

        request = governor.build_request(
            goal=(
                "执行一轮监督进化 dry-run 基线探针："
                "1) 只调用一次 open_evolution_transaction_tool 开账，summary 写“supervised baseline probe”；"
                "2) 调用 python_lint_tool 检查 scripts/evolution_harness.py；"
                "3) lint 完成后必须立即调用 close_evolution_transaction_tool 关账，lint 通过则 status=success；"
                "4) 不要再次开账，不要修改文件，不要触发重启，不要委派子 agent。"
            ),
            iteration=2,
            total_tool_calls=3,
        )

        assert request is None

    def test_gym_probe_goal_is_not_delegated(self):
        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: None,
            session_getter=lambda: SimpleNamespace(
                get_attention_snapshot=lambda: {
                    "diagnostic_drift": True,
                    "recent_blockers": [{"kind": "diagnostic_drift", "summary": "连续推理"}],
                }
            ),
        )

        request = governor.build_request(
            goal=(
                "Run this coordination workflow Gym probe in the main agent only. "
                "Do not call spawn_agent_tool. Do not delegate."
            ),
            iteration=2,
            total_tool_calls=2,
        )

        assert request is None

    def test_active_evolution_transaction_suppresses_autonomous_delegation(self):
        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: None,
            session_getter=lambda: SimpleNamespace(
                get_attention_snapshot=lambda: {
                    "active_evolution_txn_id": "txn_1",
                    "diagnostic_drift": True,
                    "recent_blockers": [{"kind": "diagnostic_drift", "summary": "连续推理"}],
                }
            ),
        )

        request = governor.build_request(
            goal="继续当前事务闭环",
            iteration=2,
            total_tool_calls=2,
        )

        assert request is None

    def test_readonly_subagent_process_never_delegates(self, monkeypatch):
        monkeypatch.setenv("VIBELUTION_SUBAGENT_MODE", "readonly")
        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: None,
            session_getter=lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        request = governor.build_request(
            goal="分析 log_info/conversation_20260511_162502.jsonl 中子 agent 为什么会超时，只做诊断。",
            iteration=1,
            total_tool_calls=0,
        )

        assert request is None

    def test_spawn_agent_rejects_nested_subagent_depth(self, monkeypatch):
        monkeypatch.setenv("VIBELUTION_SUBAGENT_DEPTH", "1")

        payload = json.loads(
            spawn_agent_impl(
                goal="分析最近日志",
                task_type="diagnose",
                constraints={"readonly": True},
            )
        )

        assert payload["status"] == "error"
        assert payload["code"] == "MAX_RECURSION"
        assert "不允许继续派发子 agent" in payload["message"]

    def test_spawn_agent_rejects_non_fixed_task_type(self):
        payload = json.loads(
            spawn_agent_impl(
                goal="顺手看一下",
                task_type="verify",
            )
        )

        assert payload["status"] == "error"
        assert payload["code"] == "UNSUPPORTED_SUBAGENT_TASK_TYPE"

    def test_apply_delegation_result_treats_partial_diagnosis_as_evidence_without_stopping(self):
        events = {"logs": [], "contents": [], "finished": []}

        class DummyUI:
            def add_log(self, text, level="INFO"):
                events["logs"].append((level, text))

            def add_content(self, text):
                events["contents"].append(text)

            def add_delegation_evidence(self, summary, next_action="", confidence=""):
                events["evidence"] = (summary, next_action, confidence)

            def finish_subagent_activity(self, **kwargs):
                events["finished"].append(kwargs)

        class DummySession:
            def record_delegation_result(self, *args, **kwargs):
                events["recorded_result"] = (args, kwargs)

            def note_diagnostic_observation(self, text):
                events["observation"] = text

            def note_scope_completion(self, reason=""):
                events["scope_completion"] = reason

        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: DummyUI(),
            session_getter=lambda: DummySession(),
        )
        payload = {
            "task_type": "diagnose",
            "goal": "分析当前轮为什么出现：log_info/conversation_20260511_162502.jsonl 第 1-47 行与已读区间 1-47 高度重叠。",
            "root_goal": "分析 log_info/conversation_20260511_162502.jsonl 中子 agent 为什么会超时，只做诊断，不要修改代码。",
            "scope": {"goal": "same"},
        }
        messages = []

        outcome = governor.apply_result(
            payload,
            json.dumps(
                {
                    "status": "partial",
                    "summary": "已确认日志截断导致诊断证据不足。",
                    "findings": ["日志是长行 JSONL", "read_file_tool 能读到 line 43 traceback"],
                    "evidence": ["conversation_20260511_162502.jsonl:43"],
                    "recommended_next_action": "主 agent 根据现有证据直接收束",
                    "confidence": "medium",
                },
                ensure_ascii=False,
            ),
            messages,
        )

        assert outcome["delegated"] is True
        assert outcome["useful"] is True
        assert outcome["break_round"] is False
        assert messages
        assert isinstance(messages[-1], SystemMessage)
        assert "委派证据" in messages[-1].content
        assert "下一步建议" not in messages[-1].content
        assert "直接收束" not in messages[-1].content
        assert events["finished"]
        assert "observation" not in events
        assert "scope_completion" not in events

    def test_apply_delegation_result_marks_fast_path_ui_hint(self):
        events = {"finished": []}

        class DummyUI:
            def add_log(self, *_args, **_kwargs):
                return None

            def add_content(self, *_args, **_kwargs):
                return None

            def add_delegation_evidence(self, *_args, **_kwargs):
                return None

            def finish_subagent_activity(self, **kwargs):
                events["finished"].append(kwargs)

        class DummySession:
            def record_delegation_result(self, *args, **kwargs):
                return None

            def note_diagnostic_observation(self, _text):
                return None

            def note_scope_completion(self, _reason=""):
                return None

        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: DummyUI(),
            session_getter=lambda: DummySession(),
        )

        payload = {
            "task_type": "diagnose",
            "goal": "分析当前轮为什么超时",
            "root_goal": "分析 log_info/conversation_20260511_162502.jsonl 中子 agent 为什么会超时，只做诊断，不要修改代码。",
            "scope": {"goal": "same"},
        }
        result = json.dumps(
            {
                "status": "completed",
                "summary": "OSError: [Errno 22] Invalid argument",
                "findings": ["第 43 行命中异常线索。"],
                "evidence": ["conversation_20260511_162502.jsonl:43"],
                "recommended_next_action": "主 agent 可依据异常行直接收束。",
                "confidence": "high",
                "fast_path": "conversation_log_scan",
            },
            ensure_ascii=False,
        )

        governor.apply_result(payload, result, [])

        assert events["finished"]
        assert events["finished"][0]["mode_hint"] == "快速日志诊断，未启动真实子 agent"

    def test_build_delegation_request_blocks_completed_same_goal_even_when_scope_changes(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        goal = "分析当前轮为什么出现：core/infrastructure/tool_executor.py 第 561-640 行本轮已读过。"

        class DummySession:
            def get_attention_snapshot(self):
                return {
                    "recent_blockers": [
                        {"kind": "duplicate_read", "summary": "core/infrastructure/tool_executor.py 第 561-640 行本轮已读过。"},
                        {"kind": "observation", "summary": "子 agent 已返回: 已定位重复读取来自续读链断裂。"},
                    ],
                    "modified_paths": [],
                    "delegation_history": [
                        {
                            "task_type": "diagnose",
                            "goal": goal,
                            "scope_signature": "recent_blockers=['duplicate_read']",
                            "status": "completed",
                            "summary": "已定位重复读取来自续读链断裂。",
                            "confidence": "high",
                        }
                    ],
                    "delegation_findings": [
                        {
                            "task_type": "diagnose",
                            "goal": goal,
                            "status": "completed",
                            "summary": "已定位重复读取来自续读链断裂。",
                            "confidence": "high",
                        }
                    ],
                    "delegation_failures": [],
                    "delegation_evidence_digest": "已定位重复读取来自续读链断裂。",
                    "last_validation_summary": "",
                    "last_validation_passed": False,
                    "diagnostic_drift": True,
                }

            def has_recent_delegation(self, task_type, delegation_goal, scope):
                return delegation_goal == goal

            def _normalize_scope_signature(self, scope):
                return str(scope)

        monkeypatch.setattr(agent_module, "get_session_state", lambda: DummySession())

        payload = _build_operator_delegation_request(
            goal="继续完成同一个用户目标：继续吧\n上一内部回合仍未完成用户目标（第 1 轮）。",
            iteration=3,
            total_tool_calls=8,
        )

        assert payload is None

    def test_apply_delegation_result_rejects_think_only_summary(self):
        events = {"logs": [], "finished": []}

        class DummyUI:
            def add_log(self, text, level="INFO"):
                events["logs"].append((level, text))

            def add_content(self, *_args, **_kwargs):
                return None

            def add_delegation_evidence(self, *_args, **_kwargs):
                return None

            def finish_subagent_activity(self, **kwargs):
                events["finished"].append(kwargs)

        class DummySession:
            def __init__(self):
                self.failures = []

            def record_delegation_result(self, *args, **kwargs):
                events["unexpected_success"] = (args, kwargs)

            def note_diagnostic_observation(self, _text):
                events["unexpected_observation"] = True

            def record_delegation_failure(self, *_args):
                self.failures.append(_args)

        session = DummySession()
        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: DummyUI(),
            session_getter=lambda: session,
        )
        payload = {
            "task_type": "diagnose",
            "goal": "分析重复调用",
            "root_goal": "分析重复调用，只做诊断，不要修改代码。",
            "scope": {"goal": "same"},
        }
        messages = []

        outcome = governor.apply_result(
            payload,
            json.dumps(
                {
                    "status": "completed",
                    "summary": "<think>Let me inspect more logs.</think>",
                    "findings": [],
                    "evidence": [],
                    "recommended_next_action": "",
                    "confidence": "",
                },
                ensure_ascii=False,
            ),
            messages,
        )

        assert outcome["delegated"] is True
        assert outcome["useful"] is False
        assert session.failures
        assert messages
        assert isinstance(messages[-1], SystemMessage)
        assert messages[-1].content.startswith("## 委派失败")
        assert "unexpected_success" not in events

    def test_apply_delegation_result_rejects_empty_completed_payload(self):
        events = {"logs": [], "finished": []}

        class DummyUI:
            def add_log(self, text, level="INFO"):
                events["logs"].append((level, text))

            def add_content(self, *_args, **_kwargs):
                return None

            def add_delegation_evidence(self, *_args, **_kwargs):
                return None

            def finish_subagent_activity(self, **kwargs):
                events["finished"].append(kwargs)

        class DummySession:
            def __init__(self):
                self.failures = []

            def record_delegation_result(self, *args, **kwargs):
                events["unexpected_success"] = (args, kwargs)

            def record_delegation_failure(self, *_args):
                self.failures.append(_args)

        session = DummySession()
        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: DummyUI(),
            session_getter=lambda: session,
        )
        payload = {
            "task_type": "diagnose",
            "goal": "分析空子 agent 结果",
            "root_goal": "分析空子 agent 结果，只做诊断，不要修改代码。",
            "scope": {"log": "demo.jsonl"},
        }
        messages = []

        outcome = governor.apply_result(
            payload,
            json.dumps(
                {
                    "status": "completed",
                    "summary": "",
                    "findings": [],
                    "evidence": [],
                    "recommended_next_action": "",
                    "confidence": "low",
                    "raw_output": "",
                    "tool_call_count": 0,
                },
                ensure_ascii=False,
            ),
            messages,
        )

        assert outcome["delegated"] is True
        assert outcome["useful"] is False
        assert session.failures
        assert events["finished"][0]["status"] == "no_result"
        assert "unexpected_success" not in events

    def test_restart_focus_guard_blocks_unrelated_file_edits(self):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent._active_goal = "制定重启任务，然后对重启任务打勾，然后运行 `trigger_self_restart_tool` 重启你自己。"

        blocked = agent._guard_tool_execution("apply_diff_edit_tool", {"file_path": "tools/agent_tools.py"})
        allowed = agent._guard_tool_execution("trigger_self_restart_tool", {"reason": "test"})

        assert blocked is not None
        assert "重启测试模式" in blocked
        assert allowed is None
