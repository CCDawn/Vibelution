"""Session budget parameters: storage/API, execution resolution, and wiring.

Covers the per-session budget override surface:

* API GET/PATCH ``/api/sessions/{id}/budget-parameters`` (CAS revision, 409,
  422, null-clear semantics) — route contract plus service behavior.
* ``core.orchestration.session_budget_resolve`` resolution.
* Authorization install priority: 会话覆盖 > family 解析 > policy base, and
  the installed cap flowing into the Turn Status Bar display value.
* Thinking-budget injection stays workflow-scoped only (env > default);
  residual legacy ``thinkingBudgetChars`` storage keys are ignored on read
  and dropped on the next PATCH save.
* ``token_budget`` (used/total) reaching the Turn Status Bar payload through
  the worker → agent call chain.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage

from core.authorization.tool_authorization_service import (
    AuthorizationReport,
    clear_execution_authorization,
    install_execution_authorization,
)
from core.authorization.tool_policy_models import AuthorizationDecision
from core.orchestration import session_budget_resolve
from core.orchestration.session_budget_resolve import (
    SESSION_BUDGET_PARAMETERS_METADATA_KEY,
    SessionBudgetParameters,
    get_session_budget_parameters,
    normalize_session_budget_parameters,
    session_budget_parameters_from_agent,
    validate_session_budget_override,
)
from core.orchestration.turn_status_bar import (
    collect_turn_status_snapshot,
    format_turn_status_bar,
)
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import sessions as session_routes
from core.web.services import agent_directory_service, session_service
from core.web.services.session import worker as session_worker
from core.web.services.session.research_thinking_budget import (
    RESEARCH_THINKING_BUDGET_ENV,
    build_research_thinking_budget_segment,
)

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

pytestmark = pytest.mark.serial


# ---------------------------------------------------------------------------
# Route contract (thin layer, mirrors the model-parameters route tests)
# ---------------------------------------------------------------------------


def test_budget_parameters_get_returns_view(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = {"revision": 7, "maxCallsPerTurn": 64}
    monkeypatch.setattr(
        session_routes,
        "get_session_budget_parameters_view",
        lambda session_id: {**expected, "sessionId": session_id},
    )
    response = client.get("/api/sessions/session-active/budget-parameters")
    assert response.status_code == 200
    assert response.json() == expected


def test_budget_parameters_get_maps_not_found_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_not_found(_session_id: str):
        raise session_service.SessionNotFoundError("Session not found: session-active")

    monkeypatch.setattr(session_routes, "get_session_budget_parameters_view", raise_not_found)
    missing = client.get("/api/sessions/session-active/budget-parameters")
    assert missing.status_code == 404

    def raise_validation(_session_id: str):
        raise session_service.SessionValidationError("当前会话没有可用的 Agent 配置。")

    monkeypatch.setattr(session_routes, "get_session_budget_parameters_view", raise_validation)
    invalid = client.get("/api/sessions/session-active/budget-parameters")
    assert invalid.status_code == 422


def test_budget_parameters_patch_passes_only_provided_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def update(session_id, **kwargs):
        captured["session_id"] = session_id
        captured.update(kwargs)
        return {"revision": 8, "maxCallsPerTurn": kwargs.get("max_calls_per_turn")}

    monkeypatch.setattr(session_routes, "update_session_budget_parameters", update)

    only_max = client.patch(
        "/api/sessions/session-active/budget-parameters",
        json={"revision": 7, "maxCallsPerTurn": 64},
    )
    assert only_max.status_code == 200
    assert only_max.json() == {"revision": 8, "maxCallsPerTurn": 64}
    # Omitted fields must not be forwarded at all.
    assert captured == {
        "session_id": "session-active",
        "expected_revision": 7,
        "max_calls_per_turn": 64,
    }
    captured.clear()

    # An explicit null must reach the service as a clear request.
    explicit_null = client.patch(
        "/api/sessions/session-active/budget-parameters",
        json={"revision": 8, "maxCallsPerTurn": None},
    )
    assert explicit_null.status_code == 200
    assert captured == {
        "session_id": "session-active",
        "expected_revision": 8,
        "max_calls_per_turn": None,
    }
    # The removed thinking-budget override is no longer part of the contract.
    legacy = client.patch(
        "/api/sessions/session-active/budget-parameters",
        json={"revision": 7, "thinkingBudgetChars": 800},
    )
    assert legacy.status_code == 422


def test_budget_parameters_patch_maps_conflict_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_conflict(*_args, **_kwargs):
        raise session_service.SessionBudgetParametersConflictError(
            "Agent configuration changed. Refresh and retry."
        )

    monkeypatch.setattr(session_routes, "update_session_budget_parameters", raise_conflict)
    conflict = client.patch(
        "/api/sessions/session-active/budget-parameters",
        json={"revision": 7, "maxCallsPerTurn": 64},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Agent configuration changed. Refresh and retry."

    def raise_validation(*_args, **_kwargs):
        raise session_service.SessionValidationError("maxCallsPerTurn must be between 1 and 200, or null.")

    monkeypatch.setattr(session_routes, "update_session_budget_parameters", raise_validation)
    invalid = client.patch(
        "/api/sessions/session-active/budget-parameters",
        json={"revision": 7, "maxCallsPerTurn": 999},
    )
    assert invalid.status_code == 422


def test_budget_parameters_patch_rejects_malformed_payloads() -> None:
    base = {"revision": 7, "maxCallsPerTurn": 64}
    assert (
        client.patch(
            "/api/sessions/session-active/budget-parameters",
            json={**base, "unexpectedField": 1},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/sessions/session-active/budget-parameters",
            json={"revision": 7, "maxCallsPerTurn": "64"},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/sessions/session-active/budget-parameters",
            json={"revision": -1, "maxCallsPerTurn": 64},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/sessions/session-active/budget-parameters",
            json={"revision": 1.5, "maxCallsPerTurn": 64},
        ).status_code
        == 422
    )


# ---------------------------------------------------------------------------
# Service behavior (storage copy of the model-parameters CAS pattern)
# ---------------------------------------------------------------------------


class _BudgetRegistryStub:
    """In-memory stand-in for the Agent registry CAS mutation."""

    def __init__(self, agent: dict) -> None:
        self.agent = agent
        self.calls: list[dict] = []

    def __call__(self, agent_id: str, *, expected_config_revision: int, values) -> dict:
        self.calls.append(
            {
                "agentId": agent_id,
                "expectedConfigRevision": expected_config_revision,
                "values": dict(values or {}),
            }
        )
        current_revision = max(0, int(self.agent.get("configRevision") or 0))
        if current_revision != expected_config_revision:
            raise agent_directory_service.AgentStateConflictError(
                "Agent configuration changed. Refresh and retry."
            )
        metadata = dict(self.agent.get("metadata") or {})
        if values:
            metadata[SESSION_BUDGET_PARAMETERS_METADATA_KEY] = dict(values)
        else:
            metadata.pop(SESSION_BUDGET_PARAMETERS_METADATA_KEY, None)
        self.agent["metadata"] = metadata
        self.agent["configRevision"] = current_revision + 1
        return dict(self.agent)


@pytest.fixture()
def budget_service_env(monkeypatch: pytest.MonkeyPatch):
    agent = {
        "agentId": "agent-1",
        "status": "active",
        "configRevision": 7,
        "configHash": "hash-7",
        "metadata": {},
    }
    stub = _BudgetRegistryStub(agent)
    monkeypatch.setattr(session_service, "_ensure_session_conversation_record", lambda *_a, **_k: True)
    monkeypatch.setattr(session_service, "_session_agent_id_snapshot", lambda _sid: "agent-1")
    monkeypatch.setattr(session_service, "_ensure_session_mutable", lambda *_a, **_k: {})
    monkeypatch.setattr(session_service, "get_agent", lambda _aid, **_k: dict(agent))
    monkeypatch.setattr(
        agent_directory_service,
        "update_agent_budget_parameters_if_current",
        stub,
    )
    return {"agent": agent, "stub": stub}


def test_get_view_reports_configured_overrides_and_revision(budget_service_env) -> None:
    budget_service_env["agent"]["metadata"] = {
        SESSION_BUDGET_PARAMETERS_METADATA_KEY: {"maxCallsPerTurn": 64, "thinkingBudgetChars": 800}
    }
    view = session_service.get_session_budget_parameters_view("session-active")
    # The residual legacy thinkingBudgetChars key is ignored on read.
    assert view == {"revision": 7, "maxCallsPerTurn": 64}


def test_get_view_defaults_to_nulls_without_configuration(budget_service_env) -> None:
    view = session_service.get_session_budget_parameters_view("session-active")
    assert view == {"revision": 7, "maxCallsPerTurn": None}


def test_patch_writes_override_and_bumps_revision(budget_service_env) -> None:
    result = session_service.update_session_budget_parameters(
        "session-active",
        expected_revision=7,
        max_calls_per_turn=50,
    )
    assert result == {"revision": 8, "maxCallsPerTurn": 50}
    assert budget_service_env["stub"].calls == [
        {
            "agentId": "agent-1",
            "expectedConfigRevision": 7,
            "values": {"maxCallsPerTurn": 50},
        }
    ]


def test_patch_null_clears_back_to_defaults(budget_service_env) -> None:
    budget_service_env["agent"]["metadata"] = {
        SESSION_BUDGET_PARAMETERS_METADATA_KEY: {"maxCallsPerTurn": 64, "thinkingBudgetChars": 800}
    }
    result = session_service.update_session_budget_parameters(
        "session-active",
        expected_revision=7,
        max_calls_per_turn=None,
    )
    assert result == {"revision": 8, "maxCallsPerTurn": None}
    # A full clear removes the storage block entirely (empty values payload).
    assert budget_service_env["stub"].calls[0]["values"] == {}


def test_patch_drops_residual_thinking_budget_key_on_save(budget_service_env) -> None:
    budget_service_env["agent"]["metadata"] = {
        SESSION_BUDGET_PARAMETERS_METADATA_KEY: {"maxCallsPerTurn": 64, "thinkingBudgetChars": 800}
    }
    result = session_service.update_session_budget_parameters(
        "session-active",
        expected_revision=7,
    )
    # Omitted fields keep their current value, while the legacy
    # thinkingBudgetChars key disappears from the stored payload.
    assert result == {"revision": 8, "maxCallsPerTurn": 64}
    assert budget_service_env["stub"].calls[0]["values"] == {"maxCallsPerTurn": 64}


def test_patch_stale_revision_conflicts(budget_service_env) -> None:
    with pytest.raises(session_service.SessionBudgetParametersConflictError):
        session_service.update_session_budget_parameters(
            "session-active",
            expected_revision=6,
            max_calls_per_turn=50,
        )


@pytest.mark.parametrize(
    "field,kwargs",
    [
        ("maxCallsPerTurn", {"max_calls_per_turn": 0}),
        ("maxCallsPerTurn", {"max_calls_per_turn": 201}),
        ("maxCallsPerTurn", {"max_calls_per_turn": "64"}),
        ("maxCallsPerTurn", {"max_calls_per_turn": True}),
    ],
)
def test_patch_rejects_out_of_range_values(budget_service_env, field, kwargs) -> None:
    with pytest.raises(session_service.SessionValidationError):
        session_service.update_session_budget_parameters(
            "session-active",
            expected_revision=7,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Resolver (execution-layer read path)
# ---------------------------------------------------------------------------


def test_get_session_budget_parameters_resolves_session_to_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", object())
    monkeypatch.setattr(
        session_service,
        "load_session_chat_state",
        lambda _root, _sid: {"agentId": "agent-1"},
    )
    monkeypatch.setattr(
        session_service,
        "get_agent",
        lambda _aid, **_k: {
            "agentId": "agent-1",
            "metadata": {
                SESSION_BUDGET_PARAMETERS_METADATA_KEY: {
                    "maxCallsPerTurn": 50,
                    "thinkingBudgetChars": 800,
                }
            },
        },
    )
    parameters = get_session_budget_parameters("session-active")
    # The residual legacy thinkingBudgetChars key resolves away.
    assert parameters == SessionBudgetParameters(maxCallsPerTurn=50)


def test_get_session_budget_parameters_returns_none_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", object())
    monkeypatch.setattr(session_service, "load_session_chat_state", lambda _root, _sid: {"agentId": "agent-1"})
    monkeypatch.setattr(
        session_service,
        "get_agent",
        lambda _aid, **_k: {"agentId": "agent-1", "metadata": {}},
    )
    assert get_session_budget_parameters("session-active") is None


def test_get_session_budget_parameters_survives_read_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_loader(_root, _sid):
        raise RuntimeError("chat state unavailable")

    monkeypatch.setattr(session_service, "PROJECT_ROOT", object())
    monkeypatch.setattr(session_service, "load_session_chat_state", broken_loader)
    assert get_session_budget_parameters("session-active") is None


def test_normalize_drops_out_of_range_and_junk_values() -> None:
    assert normalize_session_budget_parameters(None) is None
    assert normalize_session_budget_parameters({}) is None
    assert normalize_session_budget_parameters({"maxCallsPerTurn": 201}) is None
    assert normalize_session_budget_parameters({"maxCallsPerTurn": "50"}) == SessionBudgetParameters(maxCallsPerTurn=50)
    # Legacy thinking-only payloads no longer resolve to anything.
    assert normalize_session_budget_parameters({"thinkingBudgetChars": 800}) is None
    assert session_budget_parameters_from_agent(None) is None
    assert session_budget_parameters_from_agent({"metadata": None}) is None


def test_validate_override_bounds() -> None:
    assert validate_session_budget_override(None, field="maxCallsPerTurn", minimum=1, maximum=200) is None
    assert validate_session_budget_override(64, field="maxCallsPerTurn", minimum=1, maximum=200) == 64
    with pytest.raises(session_budget_resolve.SessionBudgetParametersValueError):
        validate_session_budget_override(0, field="maxCallsPerTurn", minimum=1, maximum=200)
    with pytest.raises(session_budget_resolve.SessionBudgetParametersValueError):
        validate_session_budget_override(True, field="maxCallsPerTurn", minimum=1, maximum=200)


# ---------------------------------------------------------------------------
# Authorization install priority: session > family > base
# ---------------------------------------------------------------------------


def _authorization_report() -> AuthorizationReport:
    decision = AuthorizationDecision(
        agent_id="agent-1",
        turn_id="turn-1",
        policy_id="tool-primary",
        policy_version=1,
        registry_version=1,
        visible_tools=("read_file",),
        executable_tools=("read_file",),
        preferred_tools=(),
        denied=(),
        decision_fingerprint="fingerprint-1",
        generated_at="2026-10-18T00:00:00Z",
    )
    return AuthorizationReport(
        decision=decision,
        deny_code_counts=(),
        registry_fingerprint="registry-1",
        duration_ms=1,
    )


def _runtime(monkeypatch: pytest.MonkeyPatch, *, model: str, provider: str, session_id: str = "session-active") -> None:
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "agent-1",
            "sessionId": session_id,
            "turnId": "turn-1",
            "model": model,
            "provider": provider,
            "toolPolicy": {
                "maxCallsPerTurn": 32,
                "maxCallsPerTurnByModelFamily": {"deepseek": 64},
            },
            "agentConfigSnapshot": {
                "agentId": "agent-1",
                "configRevision": 5,
                "configHash": "hash-5",
            },
            "permissionPreset": "standard",
        },
    )


def _install(monkeypatch: pytest.MonkeyPatch, *, model: str, provider: str, override=None):
    _runtime(monkeypatch, model=model, provider=provider)
    monkeypatch.setattr(
        session_budget_resolve,
        "get_session_budget_parameters",
        lambda _sid: override,
    )
    try:
        return install_execution_authorization(_authorization_report())
    finally:
        clear_execution_authorization()


def test_install_priority_session_over_family_over_base(monkeypatch: pytest.MonkeyPatch) -> None:
    # family resolution wins over the base (deepseek family map -> 64)
    context = _install(monkeypatch, model="deepseek-v3", provider="deepseek", override=None)
    assert context.max_calls_per_turn == 64
    assert context.budget_profile == "deepseek"

    # base resolution when no family map entry matches (openai family default
    # equals the policy base, so the base 32 stays the effective cap)
    context = _install(monkeypatch, model="gpt-4.1", provider="openai", override=None)
    assert context.max_calls_per_turn == 32

    # session override wins over the family resolution (50 > deepseek's 64)
    context = _install(
        monkeypatch,
        model="deepseek-v3",
        provider="deepseek",
        override=SessionBudgetParameters(maxCallsPerTurn=50),
    )
    assert context.max_calls_per_turn == 50
    # The model family label stays informational; the installed cap is final.
    assert context.budget_profile == "deepseek"


def test_install_session_override_flows_into_status_bar_display(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _install(
        monkeypatch,
        model="deepseek-v3",
        provider="deepseek",
        override=SessionBudgetParameters(maxCallsPerTurn=50),
    )
    snapshot = collect_turn_status_snapshot(authorization=context)
    assert snapshot.tools_max == 50
    bar_text = format_turn_status_bar(snapshot)
    assert "used 0/50" in bar_text


def test_install_without_session_id_keeps_family_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "agent-1",
            "turnId": "turn-1",
            "model": "deepseek-v3",
            "provider": "deepseek",
            "toolPolicy": {
                "maxCallsPerTurn": 32,
                "maxCallsPerTurnByModelFamily": {"deepseek": 64},
            },
            "agentConfigSnapshot": {
                "agentId": "agent-1",
                "configRevision": 5,
                "configHash": "hash-5",
            },
            "permissionPreset": "standard",
        },
    )
    try:
        context = install_execution_authorization(_authorization_report())
    finally:
        clear_execution_authorization()
    assert context.max_calls_per_turn == 64


# ---------------------------------------------------------------------------
# Thinking-budget injection: workflow-scoped only, env > default
# ---------------------------------------------------------------------------


def _chat_state_loader(conversation: dict | None):
    def loader(_project_root, _session_id):
        return conversation

    return loader


_WORKFLOW_BINDING_CONVERSATION = {
    "experimentBinding": {"workflowRunId": "run-1", "workflowNodeId": "node-2"}
}


def test_workflow_session_keeps_env_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RESEARCH_THINKING_BUDGET_ENV, "800")
    segment = build_research_thinking_budget_segment(
        "session-node",
        project_root=object(),
        load_chat_state=_chat_state_loader(_WORKFLOW_BINDING_CONVERSATION),
    )
    assert segment is not None
    assert "必须控制在 800 字以内" in segment["block"]


def test_workflow_session_defaults_to_500_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(RESEARCH_THINKING_BUDGET_ENV, raising=False)
    segment = build_research_thinking_budget_segment(
        "session-node",
        project_root=object(),
        load_chat_state=_chat_state_loader(_WORKFLOW_BINDING_CONVERSATION),
    )
    assert segment is not None
    assert "必须控制在 500 字以内" in segment["block"]


def test_ordinary_session_with_residual_metadata_never_injects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RESEARCH_THINKING_BUDGET_ENV, "800")
    segment = build_research_thinking_budget_segment(
        "session-chat",
        project_root=object(),
        load_chat_state=_chat_state_loader({"experimentBinding": {"teamId": "team-1"}}),
    )
    assert segment is None


# ---------------------------------------------------------------------------
# token_budget (used/total) into the Turn Status Bar payload
# ---------------------------------------------------------------------------


class _TokenBudgetAgentStub:
    def __init__(self) -> None:
        self._session_token_budget = {"used": 123, "total": 2_000_000}

    def set_session_token_budget(self, *, used: int = 0, total: int = 0) -> None:
        import agent as agent_module

        agent_module.AgentRuntime.set_session_token_budget(self, used=used, total=total)


def test_worker_sync_helper_pushes_counters_into_agent() -> None:
    agent = _TokenBudgetAgentStub()
    session_worker._sync_agent_turn_status_token_budget(agent, used=5, total=2_000_000)
    assert agent._session_token_budget == {"used": 5, "total": 2_000_000}

    class _Broken:
        def set_session_token_budget(self, **_kwargs):
            raise RuntimeError("setter exploded")

    session_worker._sync_agent_turn_status_token_budget(_Broken(), used=1, total=2)  # must not raise

    class _Plain:
        pass

    session_worker._sync_agent_turn_status_token_budget(_Plain(), used=1, total=2)  # no setter, no raise


def test_worker_continuation_loop_refreshes_token_budget_each_iteration() -> None:
    source = inspect.getsource(session_worker._run_session_continuation_loop)
    assert "_sync_agent_turn_status_token_budget(" in source
    assert source.index("_sync_agent_turn_status_token_budget(") < source.index(
        "run_existing_agent_single_turn("
    )
    assert "cumulative_session_tokens" in source


def test_status_bar_payload_carries_token_budget_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent as agent_module

    captured: dict[str, object] = {}

    def fake_build(_snapshot, *, config=None, extras=None):
        captured["extras"] = dict(extras or {})
        return HumanMessage("status")

    monkeypatch.setattr(agent_module, "build_turn_status_bar_message", fake_build)

    class _StatusAgentStub(_TokenBudgetAgentStub):
        def is_runtime_status_inject_enabled_for_turn(self):
            return True

        def is_mental_model_enabled_for_turn(self):
            return False

        def _llm_identity_for_status(self):
            return "", "", ""

        mental_model = None

    stub = _StatusAgentStub()
    messages = agent_module.AgentRuntime._apply_turn_status_bar(stub, [HumanMessage("hi")], iteration=2)
    assert captured["extras"]["token_budget"] == {"used": 123, "total": 2_000_000}
    assert messages[-1] is not None

    # Without worker-pushed counters the payload has no token_budget field.
    stub._session_token_budget = None
    agent_module.AgentRuntime._apply_turn_status_bar(stub, [HumanMessage("hi")], iteration=3)
    assert "token_budget" not in captured["extras"]


def test_status_bar_renders_token_budget_from_agent_counters() -> None:
    import agent as agent_module

    class _StatusAgentStub(_TokenBudgetAgentStub):
        def is_runtime_status_inject_enabled_for_turn(self):
            return True

        def is_mental_model_enabled_for_turn(self):
            return False

        def _llm_identity_for_status(self):
            return "", "", ""

        mental_model = None

    stub = _StatusAgentStub()
    messages = agent_module.AgentRuntime._apply_turn_status_bar(stub, [HumanMessage("hi")], iteration=2)
    bar_text = str(getattr(messages[-1], "content", ""))
    # End-to-end through the real renderer: used/total land in the budget
    # section (123 tokens of the 2M session circuit-breaker line).
    assert "tokens: used 123/2.0M (0%)" in bar_text

    stub._session_token_budget = None
    cleared = agent_module.AgentRuntime._apply_turn_status_bar(stub, [HumanMessage("hi")], iteration=3)
    cleared_text = str(getattr(cleared[-1], "content", ""))
    assert "tokens: used" not in cleared_text
