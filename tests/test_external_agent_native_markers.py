from pathlib import Path
from types import SimpleNamespace

import pytest

from core.infrastructure import developer_sandbox
from core.ui.chat_state import load_session_chat_state
from core.web.services import agent_directory_service, session_service
from core.web.services.external_agent.approval_binding import is_external_session
from core.web.services.external_management.native import NativeAgentGateway
from core.web.services.external_management.store import digest
from tests.test_configured_agent_creation import configured_env  # noqa: F401


def test_native_external_management_new_agent_can_submit(configured_env, monkeypatch):
    from core.web.services.session import title_generation
    env = configured_env
    gateway = NativeAgentGateway(env["root"])
    monkeypatch.setattr(gateway, "_model", lambda *_: None)
    monkeypatch.setattr(session_service, "_session_context_limit_payload", lambda _: {"limit": 128000, "source": "test"})
    monkeypatch.setattr(session_service, "_resolve_session_agent_llm", lambda *_: SimpleNamespace(
        model_ref="model-primary", reasoning_effort_requested=""))
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda _: None)
    monkeypatch.setattr(session_service, "_enqueue_direct_session_submit_kernel_trace", lambda **_: None)
    monkeypatch.setattr(title_generation, "maybe_schedule_session_title_generation", lambda **_: False)
    key = digest(["subject", "agent_create", "request-1"])
    agent = gateway.create({"display_name": "Created worker", "mission": "test", "model_id": "model-primary"},
                           {"requestKey": key})
    session_id = agent["directSessionId"]
    state = load_session_chat_state(env["root"], session_id)
    assert state["metadata"] == {"source": "external_operator_management", "externalTaskId": key}
    assert not is_external_session(state)
    result = session_service.submit_session_message(session_id, "Hello", lightweight_response=True)
    assert result["accepted"] is True


@pytest.mark.parametrize("source,task_id,extra", [
    ("virtual_human_self_wake", "companion-owner", {}),
    ("virtual_human_life_steward", "companion-owner", {}),
    ("self_evolution_candidate_review", "review-run", {"runtimeRevision": "a" * 40}),
])
def test_real_session_accepts_other_native_metadata(tmp_path, monkeypatch, source, task_id, extra):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    for module in (session_service, agent_directory_service, developer_sandbox):
        monkeypatch.setattr(module, "PROJECT_ROOT", Path(tmp_path))
    monkeypatch.setattr(session_service, "_session_context_limit_payload", lambda _: {"limit": 128000, "source": "test"})
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda _: None)
    monkeypatch.setattr(session_service, "_enqueue_direct_session_submit_kernel_trace", lambda **_: None)
    session = session_service.create_chat_session(title="Native", created_by=source,
        session_metadata={"source": source, "externalTaskId": task_id, **extra}, lightweight=True)
    state = load_session_chat_state(tmp_path, session["id"])
    assert not is_external_session(state)
    result = session_service.submit_session_message(session["id"], "Native request", message_source=source,
                                                     lightweight_response=True)
    assert result["accepted"] is True


@pytest.mark.parametrize("source", ["external_operator_management", "virtual_human_self_wake",
    "virtual_human_life_steward", "self_evolution_candidate_review", "generic_team_workflow"])
def test_real_external_task_residue_cannot_use_native_source_exemption(source):
    state = {"conversation_id": "session-test", "metadata": {
        "source": source, "externalTaskId": "eat-" + "a" * 32,
    }}
    assert is_external_session(state)
    state["metadata"]["externalTaskId"] = "correlation-key"
    state["metadata"]["effectivePermissionProfile"] = "read_only"
    assert is_external_session(state)


@pytest.mark.parametrize("source", ["external_operator_management", "virtual_human_self_wake",
    "virtual_human_life_steward", "self_evolution_candidate_review", "generic_team_workflow"])
def test_damaged_external_task_cannot_submit_with_native_source(tmp_path, monkeypatch, source):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    for module in (session_service, agent_directory_service, developer_sandbox):
        monkeypatch.setattr(module, "PROJECT_ROOT", Path(tmp_path))
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda _: None)
    session = session_service.create_chat_session(title="Damaged", created_by=source, lightweight=True,
        session_metadata={"source": source, "externalTaskId": "eat-a12", "runtimeRevision": "a" * 40})
    with pytest.raises(session_service.SessionValidationError):
        session_service.submit_session_message(session["id"], "must not run", lightweight_response=True)


@pytest.mark.parametrize("metadata", [
    {"runtimeRevision": "a" * 40},
    {"source": "external_operator_management", "externalTaskId": "bad-key"},
    {"source": "virtual_human_self_wake", "externalTaskId": "person", "runtimeRevision": "a" * 40},
    {"source": "self_evolution_candidate_review", "externalTaskId": "review-run"},
    {"source": "self_evolution_candidate_review", "externalTaskId": "review-run", "runtimeRevision": "bad"},
])
def test_incomplete_metadata_cannot_use_native_exemption(metadata):
    assert is_external_session({"conversation_id": "session-test", "metadata": metadata})
