import json

import pytest

from core.web.services.external_agent.approval_binding import (
    ApprovalBindingError, freeze_approval, freeze_execution_arguments, validate_approval,
)


def binding(**changes):
    values = dict(task_id="task-1", session_id="session-1", agent_id="agent-1",
                  request_id="request-1", turn_id="turn-1", call_id="call-1",
                  tool_name="exec_command", decision_fingerprint="policy-1", config_revision=1,
                  config_hash="config-1", approval="always", risk="destructive",
                  permission_preset="request_approval", arguments={"cmd": "x" * 800, "n": 2**80})
    values.update(changes)
    return freeze_approval(**values)


def check(presented, current=None, **kwargs):
    options = dict(presented=presented, current=current or presented,
                   expected_revision=presented.revision, status="pending", expired=False)
    options.update(kwargs)
    return validate_approval(**options)


def test_preview_freezes_complete_input_and_keeps_large_integer_as_json_text():
    source = {"nested": [{"command": "末" * 900}], "integer": 2**80}
    snapshot = binding(arguments=source)
    original = snapshot.revision
    source["nested"][0]["command"] = "changed"
    preview = snapshot.preview()
    assert json.loads(preview["argumentsJson"]) == {"nested": [{"command": "末" * 900}], "integer": 2**80}
    preview["argumentsJson"] = "{}"
    assert snapshot.revision == original
    check(snapshot)


@pytest.mark.parametrize("change", [
    {"task_id": "task-2"}, {"session_id": "session-2"}, {"agent_id": "agent-2"},
    {"request_id": "request-2"}, {"turn_id": "turn-2"}, {"call_id": "call-2"},
    {"tool_name": "write_file_tool"}, {"decision_fingerprint": "policy-2"},
    {"config_revision": 2}, {"config_hash": "config-2"}, {"approval": "once"},
    {"risk": "network"}, {"permission_preset": "auto_review"},
    {"arguments": {"cmd": "x" * 800 + "extra", "n": 2**80}},
])
def test_changed_fact_rejects_stale_preview(change):
    with pytest.raises(ApprovalBindingError):
        check(binding(), binding(**change))


@pytest.mark.parametrize("change", [
    {"expected_revision": ""}, {"expected_revision": "f" * 64},
    {"expected_revision": "é" * 64}, {"status": "accepted"},
    {"expired": True}, {"expired": 1},
])
def test_missing_stale_or_terminal_request_is_rejected(change):
    with pytest.raises(ApprovalBindingError):
        check(binding(), **change)


@pytest.mark.parametrize("arguments", [
    {"bad": object()}, {"bad": float("nan")}, {"bad": float("inf")},
    {1: "bad"}, {"bad": (1, 2)}, {"bad": b"bytes"},
])
def test_unsupported_arguments_are_not_lossily_stringified(arguments):
    with pytest.raises(ApprovalBindingError):
        binding(arguments=arguments)


def test_cycles_rejected_and_shared_noncyclic_subtrees_allowed():
    cycle = []
    cycle.append(cycle)
    with pytest.raises(ApprovalBindingError):
        binding(arguments={"cycle": cycle})
    subtree = [1, {"x": True}]
    snapshot = binding(arguments={"left": subtree, "right": subtree})
    assert json.loads(snapshot.arguments_json) == {"left": subtree, "right": subtree}


def test_order_and_types_are_part_of_binding():
    assert binding(arguments={"a": 1, "b": 2}).revision != binding(arguments={"b": 2, "a": 1}).revision
    assert binding(arguments={"a": True}).revision != binding(arguments={"a": 1}).revision


def test_binding_includes_effective_default_values():
    def tool(command, timeout=60, _cancel_checker=None):
        pass
    execution = json.loads(freeze_execution_arguments(tool, {"command": "run", "force": True}))
    assert execution == {"command": "run", "timeout": 60}
    original = binding(arguments={"command": "run"}, execution_arguments=execution)
    changed = binding(arguments={"command": "run"}, execution_arguments={"command": "run", "timeout": 61})
    with pytest.raises(ApprovalBindingError):
        check(original, changed)


def test_unrepresentable_or_positional_only_defaults_fail_closed():
    def invalid_default(command, secret=object()):
        pass
    def positional_only(command="run", /):
        pass
    with pytest.raises(ApprovalBindingError):
        freeze_execution_arguments(invalid_default, {"command": "run"})
    with pytest.raises(ApprovalBindingError):
        freeze_execution_arguments(positional_only, {})


@pytest.mark.parametrize("change", [
    {"task_id": ""}, {"session_id": " s "}, {"request_id": None},
    {"config_revision": True}, {"config_revision": 0}, {"arguments": None},
])
def test_missing_or_ambiguous_context_fails_closed(change):
    with pytest.raises(ApprovalBindingError):
        binding(**change)
