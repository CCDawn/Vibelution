"""Fixture-only native adapter contracts; no product process or model calls."""
from __future__ import annotations

import copy
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import pa_workspace_actions as actions


RUNTIME = {"agentId": "assistant", "sessionId": "assistant-session"}
PRIVATE = "PRIVATE_TRANSCRIPT_TOKEN"


@pytest.fixture
def native(monkeypatch):
    rows = {"session": {"id": "session", "sessionId": "session", "title": "Discussion", "agentId": "worker",
                        "status": "idle", "pinned": False, "archiveState": {}, "summary": PRIVATE,
                        "messages": [{"content": PRIVATE}], "path": PRIVATE}}
    llm = {"sessionId": "session", "agentId": "worker", "currentModelId": "provider/model", "configRevision": 7,
           "contextWindow": 4096, "maxContextWindow": 64000, "currentReasoningEffort": "medium", "choices": [PRIVATE],
           "model": {"api_key": PRIVATE, "reasoningEffortValues": ["low", "medium", "high"]}}
    budget = {"revision": 7, "maxCallsPerTurn": 12, "private": PRIVATE}
    team = {"teamId": "team", "name": "Helpers", "description": "Keep description", "purpose": "Help",
            "status": "active", "members": [{"agentId": "worker", "responsibilities": [PRIVATE]}],
            "linkedChatRoom": {"status": "idle"}, "canvasPath": PRIVATE}
    room = {"roomId": "room", "title": "Lounge", "purpose": "discussion", "status": "idle",
            "config": {"secret": PRIVATE}, "participants": [{"agentId": "worker"}], "body": PRIVATE}
    directory = SimpleNamespace(current_agent_runtime=Mock(return_value=RUNTIME.copy()),
                                get_agent=Mock(return_value={"agentId": "worker", "roleKey": "worker", "metadata": {}}))

    def pin(session_id, *, pinned):
        rows[session_id]["pinned"] = pinned
        return {"id": session_id, "pinned": pinned}  # Deliberately partial native response.

    def model_update(session_id, **kwargs):
        assert session_id == "session"
        assert kwargs["expected_agent_id"] == "worker"
        assert kwargs["expected_model_ref"] == "provider/model"
        assert kwargs["expected_config_revision"] == 7
        llm.update(contextWindow=kwargs["context_window"], currentReasoningEffort=kwargs["reasoning_effort"], configRevision=8)
        return {"sessionId": session_id}

    def budget_update(session_id, *, expected_revision, max_calls_per_turn):
        assert session_id == "session" and expected_revision == 7
        budget.update(revision=8, maxCallsPerTurn=max_calls_per_turn)
        return {}

    # Patch only an actual native export. Pin is deliberately absent from the
    # session_service facade and must keep using its dedicated owning module.
    from core.web.services.session import session_pin_ops
    monkeypatch.setattr(session_pin_ops, "set_chat_session_pinned", Mock(side_effect=pin))
    sessions = SimpleNamespace(
        get_session_llm_options=Mock(side_effect=lambda _: copy.deepcopy(llm)),
        get_session_budget_parameters_view=Mock(side_effect=lambda _: copy.deepcopy(budget)),
        update_session_model_parameters=Mock(side_effect=model_update),
        update_session_budget_parameters=Mock(side_effect=budget_update),
        list_active_session_work_runs=Mock(return_value=[]),
        query_sessions=Mock(return_value={"items": list(rows.values()), "nextCursor": "next-page", "totalEstimate": 2}),
        select_chat_session=Mock(side_effect=AssertionError("Operator selection is forbidden")))

    def archive(session_id):
        rows[session_id].update(archiveState={"status": "archived", "source": "session_archive"}, pinned=False)
        return {"sessionId": session_id, "status": "archived"}

    def unarchive(session_id):
        rows[session_id]["archiveState"] = {}
        return {"sessionId": session_id, "status": ""}

    archives = SimpleNamespace(archive_session=Mock(side_effect=archive), unarchive_session=Mock(side_effect=unarchive),
        list_archived_sessions=Mock(return_value={"items": list(rows.values()), "nextCursor": "", "totalEstimate": 1}))
    teams = SimpleNamespace(get_team_light=Mock(side_effect=lambda _: copy.deepcopy(team)),
        update_team=Mock(side_effect=lambda _, **kwargs: team.update(**kwargs)),
        archive_team=Mock(side_effect=lambda _, **kwargs: team.update(status="archived")),
        list_teams_compact=Mock(return_value={"teams": [team], "storage": {"root": PRIVATE}}))
    rooms = SimpleNamespace(get_chat_room_compact=Mock(side_effect=lambda _: copy.deepcopy(room)),
        update_chat_room=Mock(side_effect=lambda _, **kwargs: room.update(**kwargs)),
        list_chat_rooms_compact=Mock(return_value=[room]), list_chat_room_purposes=Mock(return_value=[{"id": "discussion", "label": "Discussion"}, {"id": "brainstorm", "label": "Brainstorm"}]))
    monkeypatch.setattr(actions, "_native", lambda: (directory, sessions, archives, teams, rooms))
    monkeypatch.setattr(actions, "_read_session", lambda session_id, _: copy.deepcopy(rows[session_id]))
    monkeypatch.setattr(actions, "_team_runs", Mock(return_value=[]))
    return SimpleNamespace(rows=rows, llm=llm, budget=budget, team=team, room=room,
                           directory=directory, sessions=sessions, pins=session_pin_ops, archives=archives, teams=teams, rooms=rooms)


def execute(action, parameters, *, governed=True, runtime=None):
    return actions.execute(action, parameters, RUNTIME.copy() if runtime is None else runtime, governed=governed)


def test_catalog_has_closed_schemas_and_actual_native_methods():
    catalog = actions.contracts()
    assert len(catalog) == 15
    for name, item in catalog.items():
        assert item["action"] == name and item["parameters"]["additionalProperties"] is False
        assert item["apiMethods"] and all(method["path"].startswith("/api/") for method in item["apiMethods"])
    assert catalog["team_archive"]["apiMethods"] == [{"method": "DELETE", "path": "/api/teams/{team_id}"}]
    assert "级联归档" in catalog["team_archive"]["description"]
    assert "room_create" not in catalog
    assert catalog["session_model_parameters_update"]["parameters"]["properties"]["context_window"]["type"] == "integer"
    assert catalog["session_budget_update"]["parameters"]["properties"]["max_calls_per_turn"]["anyOf"][-1]["type"] == "null"


@pytest.mark.parametrize("action", [name for name, item in actions.contracts().items() if item["governed"]])
def test_every_write_requires_native_approval_before_native_import(monkeypatch, action):
    monkeypatch.setattr(actions, "_native", Mock(side_effect=AssertionError("No native access before approval")))
    assert execute(action, {}, governed=False)["error"] == "native_approval_required"


@pytest.mark.parametrize("action,parameters", [
    ("session_pin", {"session_id": "session", "actor": "operator"}),
    ("session_model_parameters_update", {"session_id": "session", "expected_agent_id": "worker", "expected_model_ref": "provider/model", "expected_config_revision": True, "context_window": 123}),
    ("session_budget_update", {"session_id": "session", "revision": "7", "max_calls_per_turn": 20}),
    ("session_budget_update", {"session_id": "session", "revision": 7, "max_calls_per_turn": 201}),
    ("team_update", {"team_id": "team", "members": []}),
    ("team_update", {"team_id": "team", "name": "new", "toolPolicy": {}}),
    ("team_update", {"team_id": "team", "status": "archived"}),
    ("team_update", {"team_id": "team", "description": None}),
    ("room_update", {"room_id": "room", "title": "New", "config": {}}),
    ("room_update", {"room_id": "room", "participant_session_ids": []}),
    ("session_pin", {"session_id": "  "}),
    ("session_model_parameters_update", {"session_id": "session", "expected_agent_id": "worker", "expected_model_ref": "provider/model", "expected_config_revision": 7}),
    ("session_model_parameters_update", {"session_id": "session", "expected_agent_id": "worker", "expected_model_ref": "provider/model", "expected_config_revision": 7, "context_window": None}),
    ("team_update", {"team_id": "team"}),
    ("room_update", {"room_id": "room"}),
])
def test_strict_inputs_do_not_reach_native(native, action, parameters):
    assert execute(action, parameters)["error"] == "invalid_input"
    native.pins.set_chat_session_pinned.assert_not_called()
    native.teams.update_team.assert_not_called()
    native.rooms.update_chat_room.assert_not_called()


def test_runtime_is_bound_without_operator_active_session(native):
    result = execute("session_pin", {"session_id": "session"}, runtime={"agentId": "operator", "sessionId": "other"})
    assert result["error"] == "runtime_identity_mismatch"
    result = execute("session_pin", {"session_id": "session"})
    assert result["ok"] and result["session"]["agentId"] == "worker"
    native.sessions.select_chat_session.assert_not_called()


@pytest.mark.parametrize("role,metadata", [("personal_assistant", {}), ("worker", {"personalAssistantProfile": "builtin"})])
def test_other_canonical_assistant_sessions_are_protected(native, role, metadata):
    native.directory.get_agent.return_value = {"roleKey": role, "metadata": metadata}
    assert execute("session_pin", {"session_id": "session"})["error"] == "assistant_protected"
    native.pins.set_chat_session_pinned.assert_not_called()


def test_current_assistant_session_is_protected(native):
    native.rows["session"]["agentId"] = "assistant"
    assert execute("session_archive", {"session_id": "session"})["error"] == "assistant_protected"
    native.archives.archive_session.assert_not_called()


def test_pin_unpin_reads_complete_metadata_after_partial_native_response(native):
    for action, expected in (("session_pin", True), ("session_unpin", False)):
        result = execute(action, {"session_id": "session"})
        assert result["ok"] and result["verified"] and result["session"]["pinned"] is expected
        assert result["session"]["title"] == "Discussion"
        assert set(result["session"]) == {"id", "title", "agentId", "pinned", "status", "archived"}
        assert PRIVATE not in json.dumps(result)
    native.pins.set_chat_session_pinned.assert_called_with("session", pinned=False)


def test_archive_and_unarchive_delegate_native_lifecycle_and_read_back(native):
    native.rows["session"]["pinned"] = True
    assert execute("session_archive", {"session_id": "session"})["session"]["archived"] is True
    result = execute("session_unarchive", {"session_id": "session"})
    assert result["session"]["archived"] is False and result["session"]["pinned"] is False
    native.archives.archive_session.assert_called_once_with("session")
    native.archives.unarchive_session.assert_called_once_with("session")


def test_false_pin_receipt_never_claims_verified(native):
    native.pins.set_chat_session_pinned.side_effect = lambda *args, **kwargs: {"pinned": True}
    result = execute("session_pin", {"session_id": "session"})
    assert result["ok"] is False and result["status"] == "unknown" and result["error"] == "verification_failed"


@pytest.mark.parametrize("edit,context,effort", [({"context_window": 8192}, 8192, "medium"), ({"reasoning_effort": "high"}, 4096, "high")])
def test_partial_model_update_merges_complete_native_view_and_preserves_cas(native, edit, context, effort):
    parameters = {"session_id": "session", "expected_agent_id": "worker", "expected_model_ref": "provider/model", "expected_config_revision": 7, **edit}
    result = execute("session_model_parameters_update", parameters)
    assert result["ok"] and result["parameters"]["configRevision"] == 8
    native.sessions.update_session_model_parameters.assert_called_once_with("session", expected_agent_id="worker",
        expected_model_ref="provider/model", expected_config_revision=7, context_window=context, reasoning_effort=effort)
    assert PRIVATE not in json.dumps(result)


def test_stale_model_conditions_are_not_replaced_by_current_values(native):
    parameters = {"session_id": "session", "expected_agent_id": "worker", "expected_model_ref": "provider/model", "expected_config_revision": 6, "context_window": 8192}
    assert execute("session_model_parameters_update", parameters)["error"] == "state_conflict"
    native.sessions.update_session_model_parameters.assert_not_called()


def test_session_agent_change_during_parameter_preparation_is_rejected(native):
    native.llm["agentId"] = "assistant"
    parameters = {"session_id": "session", "expected_agent_id": "assistant", "expected_model_ref": "provider/model", "expected_config_revision": 7, "context_window": 8192}
    assert execute("session_model_parameters_update", parameters)["error"] == "state_conflict"
    native.sessions.update_session_model_parameters.assert_not_called()


def test_native_model_cas_conflict_is_sanitized_and_never_retried(native):
    class SessionModelParametersConflictError(RuntimeError):
        pass
    native.sessions.update_session_model_parameters.side_effect = SessionModelParametersConflictError(PRIVATE)
    parameters = {"session_id": "session", "expected_agent_id": "worker", "expected_model_ref": "provider/model", "expected_config_revision": 7, "context_window": 8192}
    result = execute("session_model_parameters_update", parameters)
    assert result["error"] == "state_conflict" and PRIVATE not in json.dumps(result)
    native.sessions.update_session_model_parameters.assert_called_once()


def test_reasoning_update_uses_complete_native_model_cas_for_future_turns(native):
    native.rows["session"]["status"] = "running"
    result = execute("session_reasoning_update", {"session_id": "session", "reasoning_effort": "high"})
    assert result["ok"] and result["parameters"]["reasoningEffort"] == "high"
    native.sessions.update_session_model_parameters.assert_called_once_with("session", expected_agent_id="worker",
        expected_model_ref="provider/model", expected_config_revision=7, context_window=4096, reasoning_effort="high")
    assert not hasattr(native.sessions, "update_session_reasoning_effort")


def test_reasoning_update_native_cas_conflict_is_not_retried(native):
    class SessionModelParametersConflictError(RuntimeError):
        pass
    native.sessions.update_session_model_parameters.side_effect = SessionModelParametersConflictError(PRIVATE)
    result = execute("session_reasoning_update", {"session_id": "session", "reasoning_effort": "low"})
    assert result["error"] == "state_conflict" and PRIVATE not in json.dumps(result)
    native.sessions.update_session_model_parameters.assert_called_once()


def test_unsupported_reasoning_does_not_call_native_write(native):
    assert execute("session_reasoning_update", {"session_id": "session", "reasoning_effort": "ultra"})["error"] == "invalid_reasoning_effort"
    native.sessions.update_session_model_parameters.assert_not_called()


@pytest.mark.parametrize("value", [0, 20, None])
def test_budget_preserves_revision_and_explicit_null(native, value):
    result = execute("session_budget_update", {"session_id": "session", "revision": 7, "max_calls_per_turn": value})
    assert result["ok"] and result["budget"] == {"revision": 8, "maxCallsPerTurn": value}
    native.sessions.update_session_budget_parameters.assert_called_once_with("session", expected_revision=7, max_calls_per_turn=value)


def test_parameter_reads_project_only_public_scalars(native):
    native.llm["model"]["reasoningEffortValues"] += ["high", None, {"secret": PRIVATE}, "x" * 41, "private\nvalue", ""]
    result = execute("session_parameters_get", {"session_id": "session"}, governed=False)
    assert result["ok"] and PRIVATE not in json.dumps(result)
    assert "choices" not in result["parameters"] and "model" not in result["parameters"]
    assert result["parameters"]["reasoningEffortValues"] == ["low", "medium", "high"]


@pytest.mark.parametrize("kind", ["sessions", "teams", "rooms"])
def test_lists_are_metadata_only_without_body_search(native, kind):
    result = execute("workspace_list", {"kind": kind, "limit": 1}, governed=False)
    assert result["ok"] and len(result["items"]) == 1 and PRIVATE not in json.dumps(result)
    if kind == "sessions":
        native.sessions.query_sessions.assert_called_once_with(limit=1, cursor="")
    elif kind == "teams":
        assert result["items"][0]["members"] == ["worker"]


def test_archived_list_uses_native_archive_page(native):
    result = execute("workspace_list", {"kind": "sessions", "archived": True, "cursor": "20"}, governed=False)
    assert result["items"][0]["archived"] is True
    native.archives.list_archived_sessions.assert_called_once_with(limit=20, cursor="20")


def test_team_partial_update_preserves_members_permissions_and_unmentioned_fields(native):
    result = execute("team_update", {"team_id": "team", "name": " New team "})
    native.teams.update_team.assert_called_once_with("team", name="New team")
    assert result["ok"] and native.team["description"] == "Keep description"
    assert result["team"]["members"] == ["worker"] and PRIVATE not in json.dumps(result)


def test_team_description_uses_the_native_whitespace_normalization(native):
    result = execute("team_update", {"team_id": "team", "description": " First line \n\n  Second line "})
    assert result["ok"]
    native.teams.update_team.assert_called_once_with("team", description="First line\nSecond line")


@pytest.mark.parametrize("action,parameters,key", [("session_get", {"session_id": "session"}, "session"), ("team_get", {"team_id": "team"}, "team"), ("room_get", {"room_id": "room"}, "room")])
def test_object_gets_only_return_public_metadata(native, action, parameters, key):
    result = execute(action, parameters, governed=False)
    assert result["ok"] and result[key]["id"] and PRIVATE not in json.dumps(result)


def test_team_archive_delegates_to_native_shared_admission_with_runtime_protected_id(native):
    result = execute("team_archive", {"team_id": "team"})
    assert result["ok"] is True and result["team"]["status"] == "archived"
    native.teams.archive_team.assert_called_once_with("team", protected_agent_ids=("assistant",))
    native.sessions.list_active_session_work_runs.assert_called_once_with(reconcile=False)


@pytest.mark.parametrize("condition", ["assistant_member", "native_active_session", "running_workflow", "waiting_workflow", "linked_room_busy", "incomplete_runs"])
def test_team_archive_rejects_self_and_active_or_incompletely_checked_teams(native, monkeypatch, condition):
    if condition == "assistant_member":
        native.team["members"].append({"agentId": "assistant"})
    elif condition == "native_active_session":
        native.sessions.list_active_session_work_runs.return_value = [{"sessionId": "session", "status": "running", "summary": PRIVATE}]
    elif condition == "linked_room_busy":
        native.team["linkedChatRoom"]["status"] = "running"
    elif condition == "incomplete_runs":
        monkeypatch.setattr(actions, "_team_runs", lambda _: [{"status": "completed"}] * 201)
    else:
        monkeypatch.setattr(actions, "_team_runs", lambda _: [{"status": "running" if condition == "running_workflow" else "waiting", "content": PRIVATE}])
    with pytest.raises(PermissionError) as rejection:
        actions._assert_team_archive_safe(native.team, native.directory, native.sessions, RUNTIME)
    assert str(rejection.value) in {"assistant_protected", "team_busy", "team_activity_check_incomplete"}
    native.teams.archive_team.assert_not_called()


def test_room_metadata_update_does_not_replace_native_config_or_roster(native):
    original = copy.deepcopy(native.room)
    result = execute("room_update", {"room_id": "room", "title": "New room", "purpose": "brainstorm"})
    assert result["ok"] and PRIVATE not in json.dumps(result)
    native.rooms.update_chat_room.assert_called_once_with("room", title="New room", purpose="brainstorm")
    assert native.room["config"] == original["config"] and native.room["participants"] == original["participants"]


def test_invalid_room_purpose_is_rejected_before_write(native):
    assert execute("room_update", {"room_id": "room", "purpose": "run_commands"})["error"] == "invalid_purpose"
    native.rooms.update_chat_room.assert_not_called()


def test_native_exception_never_leaks_details_and_uncertain_write_is_not_retried(native):
    native.teams.update_team.side_effect = RuntimeError(PRIVATE)
    result = execute("team_update", {"team_id": "team", "name": "New"})
    assert result["status"] == "unknown" and PRIVATE not in json.dumps(result)
    native.teams.update_team.assert_called_once()


def test_directory_read_uses_native_archive_and_runtime_metadata_without_detail(monkeypatch):
    from core.web.services.session import directory_runtime
    repository = SimpleNamespace(get_session=Mock(return_value={"sessionId": "session", "title": "Saved", "agentId": "worker", "pinnedAtMs": 7, "status": "active", "lastPreview": PRIVATE}),
        get_session_runtime_state=Mock(return_value={"last_turn_status": "ready", "messages": [PRIVATE]}))
    monkeypatch.setattr(directory_runtime, "get_open_directory_store", lambda: SimpleNamespace(repository=repository))
    sessions = SimpleNamespace(_CHAT_STATE_LOCK=threading.RLock(), PROJECT_ROOT="unused",
        load_session_chat_state=Mock(return_value={"archive_state": {"status": "archived", "source": "session_archive"}, "messages": [PRIVATE]}),
        _active_session_work_run_statuses=Mock(return_value={"session": "queued"}))
    result = actions._session_public(actions._read_session("session", sessions))
    assert result == {"id": "session", "title": "Saved", "agentId": "worker", "pinned": True, "status": "queued", "archived": True}
    repository.get_session.assert_called_once_with("session", include_archived=True)
    assert PRIVATE not in json.dumps(result)


def test_all_native_names_used_by_adapter_are_real_exports():
    """Catch mock-only attributes before any model or product integration run."""
    from core.web.services.session import session_pin_ops
    directory, sessions, archives, teams, rooms = actions._native()
    required = {
        directory: ("current_agent_runtime", "get_agent"),
        sessions: ("get_session_llm_options", "get_session_budget_parameters_view", "update_session_model_parameters",
                   "update_session_budget_parameters", "query_sessions", "list_active_session_work_runs",
                   "load_session_chat_state", "_active_session_work_run_statuses"),
        archives: ("archive_session", "unarchive_session", "list_archived_sessions"),
        teams: ("get_team_light", "update_team", "archive_team", "list_teams_compact"),
        rooms: ("get_chat_room_compact", "update_chat_room", "list_chat_rooms_compact", "list_chat_room_purposes"),
        session_pin_ops: ("set_chat_session_pinned",),
    }
    for owner, names in required.items():
        for name in names:
            assert callable(getattr(owner, name)), f"Missing native owner export: {owner.__name__}.{name}"
