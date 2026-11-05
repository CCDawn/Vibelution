"""Provider consent uses the executable DTO and the actual native approval gate."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import re
import time
import tomllib
from types import SimpleNamespace

import pytest

from core.assistant_runtime.provider_approval import (
    provider_model_resolve_approval_summary,
    validate_provider_model_resolve,
)
from core.authorization import tool_authorization_service as authorization
from core.infrastructure.tool_executor import ToolExecutor
from core.web.services.local_assistant import management_approval
from core.web.services.session import tool_approvals

ACTION = "provider_model_resolve"
TOOL = "personal_assistant_manage_tool"
DEFAULTS = {"provider_id": "pixel_relay", "model_query": "", "upstream_id": "",
            "verify": True, "offset": 0, "limit": 20}
SUMMARY_KEYS = {"assistantAction", "assistantProviderPreviewVersion", "assistantParametersDigest",
                "assistantTargets", "assistantDetailsOmitted", "assistantOperationDescription"}


def tool_args(parameters=None, *, raw=None):
    return {"action": ACTION, "arguments_json": raw if raw is not None else json.dumps(
        parameters if parameters is not None else {"provider_id": "pixel_relay"}, ensure_ascii=False)}


def summary_for(args):
    summary = tool_approvals._argument_summary(TOOL, args)
    assert summary.pop("argumentKeys") == sorted(args)
    return summary


def test_summary_displays_all_effective_arguments_and_fixed_impact():
    summary = summary_for(tool_args())
    assert set(summary) == SUMMARY_KEYS
    assert summary["assistantAction"] == ACTION
    assert summary["assistantProviderPreviewVersion"] == 1
    assert summary["assistantDetailsOmitted"] is False
    assert summary["assistantTargets"] == {
        "provider_id": "pixel_relay", "model_query": "", "upstream_id": "",
        "verify": "true", "offset": "0", "limit": "20",
    }
    assert re.fullmatch("[a-f0-9]{64}", summary["assistantParametersDigest"])
    assert "固定" in summary["assistantOperationDescription"]
    assert "付费" in summary["assistantOperationDescription"]
    explicit = provider_model_resolve_approval_summary(DEFAULTS)
    assert explicit == summary
    unverified = provider_model_resolve_approval_summary({**DEFAULTS, "verify": False})
    assert "不发起文本连接测试" in unverified["assistantOperationDescription"]
    assert unverified["assistantTargets"]["verify"] == "false"
    assert unverified["assistantParametersDigest"] != summary["assistantParametersDigest"]


def test_summary_preserves_unicode_and_dto_lengths_without_truncation():
    parameters = {**DEFAULTS, "provider_id": "供/应 商😀" + "供" * 58,
                  "model_query": "模😀" * 60, "upstream_id": "型😀" * 100,
                  "offset": 10000, "limit": 30}
    assert len(parameters["provider_id"]) == 64
    summary = provider_model_resolve_approval_summary(parameters)
    assert summary["assistantTargets"] == {
        **{key: parameters[key] for key in ("provider_id", "model_query", "upstream_id")},
        "verify": "true", "offset": "10000", "limit": "30",
    }


@pytest.mark.parametrize("field,value", [
    ("provider_id", ""), ("provider_id", "供" * 65), ("provider_id", 123),
    ("model_query", "模" * 121), ("model_query", []),
    ("upstream_id", "型" * 201), ("upstream_id", None),
    ("verify", "true"), ("verify", 1), ("offset", True), ("offset", "0"),
    ("offset", -1), ("offset", 10001), ("limit", False), ("limit", 0), ("limit", 31),
    ("unknown", "SECRET"), ("key", "SECRET"), ("credential_token", "SECRET"),
])
def test_exact_executable_dto_rejects_wrong_types_bounds_and_unknown_fields(field, value):
    parameters = {**DEFAULTS, field: value}
    with pytest.raises(ValueError):
        validate_provider_model_resolve(parameters)
    summary = summary_for(tool_args(parameters))
    assert summary == {"assistantAction": ACTION, "assistantArgumentsInvalid": True}
    assert "SECRET" not in str(summary)


@pytest.mark.parametrize("field", ["provider_id", "model_query", "upstream_id"])
@pytest.mark.parametrize("character", ["\n", "\x00", "\x7f", "\u202e", "\u200b", "\ud800", "\u2028", "\u2029"])
def test_summary_fails_closed_for_non_displayable_format_characters(field, character):
    summary = summary_for(tool_args({**DEFAULTS, field: "safe" + character}))
    assert summary == {"assistantAction": ACTION, "assistantArgumentsInvalid": True}


@pytest.mark.parametrize("raw", [
    '{"provider_id":"pixel_relay","provider_id":"spoof"}',
    '{"provider_id":"pixel_relay","verify":true,"verify":false}',
    '{"provider_id":"pixel_relay","offset":NaN}',
    '{"provider_id":"pixel_relay","offset":Infinity}',
    "[]", "null", "{broken", "x" * 16001,
    {"provider_id": "pixel_relay"},
])
def test_raw_json_is_unambiguous_bounded_and_object_only(raw):
    assert summary_for(tool_args(raw=raw)) == {
        "assistantAction": ACTION, "assistantArgumentsInvalid": True,
    }


def test_unknown_outer_fields_cannot_silently_disappear_from_approval():
    summary = summary_for({**tool_args(), "unknown": "SECRET"})
    assert summary == {"assistantAction": ACTION, "assistantArgumentsInvalid": True}


@pytest.mark.parametrize("mode", ["request_approval", "auto_review", "full_access"])
def test_provider_write_requires_each_approval_in_every_mode(monkeypatch, mode):
    from core.web.services.local_assistant import management_permissions
    monkeypatch.setattr(management_permissions, "read", lambda _agent: {"preset": mode})
    assert management_approval.approval_requirement({"agentId": "agent-a"}, tool_args()) == ("always", "write")
    assert management_approval.approval_requirement({"agentId": "agent-a"}, {
        "action": "unknown_future_action", "arguments_json": "{}",
    }) == ("always", "destructive")


@pytest.fixture
def native_provider_gate(tmp_path, monkeypatch):
    from config import operator_config_transaction as transaction
    from core.assistant_runtime import actions
    from core.infrastructure import native_runtime
    from core.web.services import agent_directory_service as directory
    from core.web.services.local_assistant import consent, management_permissions
    from tools import personal_assistant_tools

    path = tmp_path / "operator.toml"
    fixture = Path(__file__).parent / "fixtures/config/llm_schema_v2_provider.toml"
    path.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(path))
    monkeypatch.setattr(transaction, "reload_config", lambda *_: None)
    # Isolate only host identity/policy and event recording. The native gate,
    # management dispatch, resolver and configuration transaction remain real.
    runtime = {"agentId": "agent-a", "sessionId": "session-a", "turnId": "turn-a",
               "agentConfigSnapshot": {"agentId": "agent-a", "configRevision": 3, "configHash": "config-hash-a"},
               "permissionPreset": "full_access", "runtimePermissions": {"preset": "full_access",
                   "sandboxMode": "danger_full_access", "approvalPolicy": "never", "approvalsReviewer": "none"},
               "toolPolicy": {"policyId": "tool-agent-a", "allowedTools": [TOOL], "blockedTools": [],
                              "preferredTools": [], "maxCallsPerTurn": 20}}
    monkeypatch.setattr(directory, "current_agent_runtime", lambda: runtime)
    monkeypatch.setattr(personal_assistant_tools, "_identity", lambda: runtime)
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    monkeypatch.setattr(consent, "_native_launcher", lambda _runtime: True)
    monkeypatch.setattr(management_permissions, "read", lambda _agent: {"preset": "full_access"})
    monkeypatch.setattr(tool_approvals, "_record_approval_event", lambda *a, **kw: None)
    monkeypatch.setattr(actions, "_binding", None)
    service = object()
    actions.bind_actions(service, None)
    tool_approvals.reset_tool_approval_state(clear_durable=False)
    executor = ToolExecutor()
    executor.register_tool(TOOL, personal_assistant_tools.personal_assistant_manage_tool, timeout=5)

    def execute(args):
        decision = SimpleNamespace(agent_id="agent-a", turn_id="turn-a", decision_fingerprint="decision-a",
            executable_tools=(TOOL,), approval_requirements=((TOOL, "always", "destructive"),))
        authorization.install_execution_authorization(SimpleNamespace(decision=decision), runtime=runtime)
        try:
            return executor.execute(TOOL, args, tool_call_id="provider-call")
        finally:
            authorization.clear_execution_authorization()

    @contextmanager
    def pending(args):
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(execute, args)
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                requests = tool_approvals.list_tool_approval_requests("session-a", status="pending")
                if requests:
                    break
                if future.done():
                    raise AssertionError(f"Execution completed without approval: {future.result()}")
                time.sleep(0.01)
            else:
                raise AssertionError("Native approval was not published")
            yield requests[0], future
        finally:
            for request in tool_approvals.list_tool_approval_requests("session-a", status="pending"):
                tool_approvals.resolve_tool_approval_request("session-a", request["requestId"], decision="cancel")
            pool.shutdown(wait=True)

    yield path, pending
    actions.unbind_actions(service)
    tool_approvals.reset_tool_approval_state(clear_durable=False)
    authorization.clear_execution_authorization()


def test_native_construction_accept_and_real_model_pin(native_provider_gate):
    path, pending = native_provider_gate
    original = path.read_bytes()
    parameters = {"provider_id": "pixel_relay", "model_query": "Opus5.5",
                  "upstream_id": "approval-model", "verify": False, "offset": 2, "limit": 3}
    with pending(tool_args(parameters)) as (request, future):
        assert not future.done()
        assert path.read_bytes() == original
        assert request["approval"] == "always" and request["risk"] == "write"
        assert request["permissionPreset"] == "request_approval"
        assert request["argumentSummary"] == {"argumentKeys": ["action", "arguments_json"],
                                               **provider_model_resolve_approval_summary(parameters)}
        assert re.fullmatch("[a-f0-9]{64}", request["argumentsHash"])
        for decision in ("acceptForSession", "acceptAlways", "acceptForSessionTool", "acceptWithActionWindow"):
            with pytest.raises(tool_approvals.ToolApprovalConflictError):
                tool_approvals.resolve_tool_approval_request("session-a", request["requestId"], decision=decision)
        resolved = tool_approvals.resolve_tool_approval_request("session-a", request["requestId"], decision="accept")
        assert resolved["status"] == "accepted"
        value, side_effect = future.result(timeout=5)
    result = json.loads(value)
    assert side_effect is None
    assert result["ok"] is True and result["configured"] is True
    assert result["connectionVerified"] is False and result["ready"] is False
    assert result["modelRef"] == "pixel_relay/approval-model"
    saved = tomllib.loads(path.read_text(encoding="utf-8"))
    assert saved["llm"]["providers"]["pixel_relay"]["models"]["approval-model"]["upstream_id"] == "approval-model"
    assert saved["llm"]["profiles"]["primary"]["model_ref"] == "pixel_relay/gpt-5.6-luna"


def test_native_decline_keeps_operator_configuration_unchanged(native_provider_gate):
    path, pending = native_provider_gate
    original = path.read_bytes()
    with pending(tool_args({"provider_id": "pixel_relay", "upstream_id": "never-save", "verify": False})) as (request, future):
        tool_approvals.resolve_tool_approval_request("session-a", request["requestId"], decision="decline")
        result, _ = future.result(timeout=5)
    assert "用户拒绝了本次工具调用" in result
    assert path.read_bytes() == original


@pytest.mark.parametrize("raw", [
    '{"provider_id":"pixel_relay","verify":"false"}',
    '{"provider_id":"pixel_relay","upstream_id":"x","key":"SECRET"}',
    '{"provider_id":"pixel_relay","verify":true,"verify":false}',
    '{"provider_id":"pixel_relay","model_query":"spoof\\u202e"}',
])
def test_invalid_native_preview_cannot_be_accepted_by_direct_api(native_provider_gate, raw):
    path, pending = native_provider_gate
    original = path.read_bytes()
    with pending(tool_args(raw=raw)) as (request, future):
        assert request["argumentSummary"] == {"argumentKeys": ["action", "arguments_json"],
                                               "assistantAction": ACTION, "assistantArgumentsInvalid": True}
        assert "SECRET" not in str(request)
        with pytest.raises(tool_approvals.ToolApprovalConflictError, match="cannot be verified"):
            tool_approvals.resolve_tool_approval_request("session-a", request["requestId"], decision="accept")
        assert not future.done()
        tool_approvals.resolve_tool_approval_request("session-a", request["requestId"], decision="decline")
        result, _ = future.result(timeout=5)
    assert "用户拒绝了本次工具调用" in result
    assert path.read_bytes() == original


def test_native_arguments_hash_rejects_mutated_call_before_execution(native_provider_gate):
    path, pending = native_provider_gate
    parameters = {"provider_id": "pixel_relay", "upstream_id": "approved-model", "verify": False}
    with pending(tool_args(parameters)) as (request, future):
        with pytest.raises(tool_approvals.ToolApprovalConflictError, match="different approval facts"):
            tool_approvals.authorize_or_wait(session_id="session-a", turn_id="turn-a", agent_id="agent-a",
                call_id="provider-call", tool_name=TOOL,
                tool_args=tool_args({**parameters, "upstream_id": "unapproved-model"}), approval="always", risk="write",
                decision_fingerprint="decision-a", config_revision=3, config_hash="config-hash-a",
                permission_preset="request_approval", timeout_seconds=0.1)
        assert not future.done()
        tool_approvals.resolve_tool_approval_request("session-a", request["requestId"], decision="accept")
        result, _ = future.result(timeout=5)
    assert json.loads(result)["modelRef"] == "pixel_relay/approved-model"
    models = tomllib.loads(path.read_text(encoding="utf-8"))["llm"]["providers"]["pixel_relay"]["models"]
    assert "approved-model" in models and "unapproved-model" not in models
