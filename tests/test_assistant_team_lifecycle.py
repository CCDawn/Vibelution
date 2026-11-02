"""Team lifecycle commands use native records, admission and cascade semantics."""
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.web.services import (agent_bulk_delete_service, agent_directory_service as directory,
    agent_mode_binding_service, chat_room_service, project_agent_bus_service, session_service, team_service)
from core.web.services.external_management import team_lifecycle_contracts as contracts
from core.web.services.external_management.service import ManagementError
from core.web.services.external_management.team_lifecycle_control import TeamLifecycleControl
from core.web.services.team import team_admission
from core.web.services.team.team_crud import team_record_fingerprint
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests.test_assistant_asset_control import Native
from tests.test_team_knowledge_service import isolate_developer_sandbox_config, knowledge_env


@pytest.fixture
def lifecycle_env(knowledge_env, monkeypatch):
    # The knowledge fixture pins Team/directory/chat/KB roots. Native archive
    # also owns session, bulk-reference and mode-binding work: isolate all of it.
    for module in (agent_bulk_delete_service, agent_mode_binding_service, session_service, project_agent_bus_service):
        monkeypatch.setattr(module, "PROJECT_ROOT", directory.PROJECT_ROOT)
    return knowledge_env


def _control():
    return TeamLifecycleControl(Native())


def _row(team_id):
    return deepcopy(team_service._find_team(team_service._load_index(), team_id))


def _archive_parameters(preview):
    return {"team_id": preview["teamId"], "expected_team_fingerprint": preview["fingerprint"],
            "expected_member_agent_ids": preview["memberAgentIds"],
            "expected_linked_chat_room_id": preview["linkedChatRoomId"]}


def _tree(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in Path(root).rglob("*") if path.is_file()}


def test_team_lifecycle_models_are_closed_and_archive_requires_all_bindings():
    member = {"agentId": "agent-a"}
    with pytest.raises(ValidationError):
        contracts.TeamCreate(name="Team", team_source="manual")
    with pytest.raises(ValidationError):
        contracts.TeamCreate(name="Team", members=[member, member])
    with pytest.raises(ValidationError):
        contracts.TeamCreate(name="Team", members=[{"agentId": f"agent-{index}"} for index in range(121)])
    with pytest.raises(ValidationError):
        contracts.TeamMemberAdd(team_id="team-a", expected_team_fingerprint="a" * 64,
                                member={**member, "agentStatus": "active"})
    complete = {"team_id": "team-a", "expected_team_fingerprint": "a" * 64,
                "expected_member_agent_ids": ["agent-a"], "expected_linked_chat_room_id": ""}
    for field in ("expected_member_agent_ids", "expected_linked_chat_room_id"):
        with pytest.raises(ValidationError):
            contracts.TeamArchive.model_validate({key: value for key, value in complete.items() if key != field})
    with pytest.raises(ValidationError):
        contracts.TeamArchive.model_validate({**complete, "expected_member_agent_ids": ["agent-a", "agent-a"]})
    with pytest.raises(ValidationError):
        contracts.TeamArchive.model_validate({**complete, "expected_linked_chat_room_id": "../other"})
    assert contracts.TEAM_LIFECYCLE_ACTION_SCOPES == {
        "team_create": "teams:create", "team_member_add": "teams:write",
        "team_member_remove": "teams:write", "team_archive": "teams:archive"}


def test_lifecycle_requires_real_operator_and_matching_native_root(lifecycle_env):
    control = _control()
    with pytest.raises(ManagementError) as denied:
        control.create_team({"name": "unauthorized"})
    assert denied.value.code == "OPERATOR_CONTROL_REQUIRED"
    control.native.project_root = Path(control.native.project_root) / "different-root"
    with server_operator_scope("operator-test", roles=("operator",)):
        with pytest.raises(ManagementError) as changed:
            control.read_archive_preview(lifecycle_env["team"]["teamId"])
    assert changed.value.code == "TARGET_BINDING_CHANGED"


def test_create_add_remove_and_archive_use_real_native_owners(lifecycle_env):
    control = _control()
    agent_id = lifecycle_env["outsider"]["agentId"]
    with server_operator_scope("operator-test", roles=("operator",)):
        created = control.create_team({"name": "Lifecycle Team", "description": "Native owner", "purpose": "Test"})
        team_id = created["resourceId"]
        assert _row(team_id)["teamKind"] == "custom"
        added = control.add_member({"team_id": team_id, "expected_team_fingerprint": created["fingerprint"],
                                   "member": {"agentId": agent_id, "role": "reviewer"}})
        before_remove = deepcopy(directory._find_agent(directory.load_state(), agent_id))
        removed = control.remove_member({"team_id": team_id, "expected_team_fingerprint": added["fingerprint"],
                                         "agent_id": agent_id})
        assert directory._find_agent(directory.load_state(), agent_id) == before_remove
        assert removed["action"] == "team_member_remove" and _row(team_id)["members"] == []
        control.add_member({"team_id": team_id, "expected_team_fingerprint": removed["fingerprint"],
                            "member": {"agentId": agent_id, "role": "reviewer"}})
        preview = control.read_archive_preview(team_id)
        result = control.archive_team(_archive_parameters(preview))
        assert result["action"] == "team_archive" and result["verified"] is True
        assert result["fingerprint"] == team_record_fingerprint(_row(team_id))
    assert _row(team_id)["status"] == "archived"
    assert directory.get_agent(agent_id, include_archived=True)["status"] == "archived"
    assert chat_room_service.get_chat_room_detail(preview["linkedChatRoomId"]) is None


def test_create_does_not_reuse_unrelated_manual_empty_team(lifecycle_env):
    control = _control()
    existing = team_service.create_team(name="Same name")
    with server_operator_scope("operator-test", roles=("operator",)):
        created = control.create_team({"name": "Same name"})
    assert created["resourceId"] != existing["teamId"]
    assert _row(created["resourceId"])["teamSource"] != _row(existing["teamId"])["teamSource"]


def test_member_remove_keeps_session_history_and_archive_seals_real_session(lifecycle_env):
    control = _control()
    session = session_service.create_chat_session(title="Lifecycle real Session")
    with server_operator_scope("operator-test", roles=("operator",)):
        created = control.create_team({"name": "Lifecycle session owner", "members": [{"agentId": session["agentId"]}]})
        removed = control.remove_member({"team_id": created["resourceId"],
            "expected_team_fingerprint": created["fingerprint"], "agent_id": session["agentId"]})
        detail = session_service.get_session_detail(session["id"])
        assert detail is not None and detail["readOnly"] is False
        assert directory.get_agent(session["agentId"])["status"] == "active"
        control.add_member({"team_id": created["resourceId"], "expected_team_fingerprint": removed["fingerprint"],
                            "member": {"agentId": session["agentId"]}})
        preview = control.read_archive_preview(created["resourceId"])
        control.archive_team(_archive_parameters(preview))
    detail = session_service.get_session_detail(session["id"])
    assert detail is not None and detail["readOnly"] is True
    assert detail["archiveState"]["status"] == "archived"
    assert detail["archiveState"]["agentId"] == session["agentId"]


def test_create_source_is_bound_to_operator_request(lifecycle_env, monkeypatch):
    control = _control()
    acknowledgements = []
    monkeypatch.setattr(control, "_acknowledge", lambda *args: acknowledgements.append(args) or args[-1])
    first_marker = {"subjectType": "operator", "subjectId": "ops-" + "a" * 32, "requestKey": "a" * 64,
                    "requestFingerprint": "c" * 64}
    with server_operator_scope("operator-test", roles=("operator",)):
        first = control.create_team({"name": "Same request name"}, first_marker)
        second = control.create_team({"name": "Same request name"}, {**first_marker, "requestKey": "b" * 64})
        third = control.create_team({"name": "Same request name"}, {**first_marker, "subjectId": "ops-" + "b" * 32})
    assert len({first["resourceId"], second["resourceId"], third["resourceId"]}) == 3
    assert len({_row(result["resourceId"])["teamSource"] for result in (first, second, third)}) == 3
    assert len(acknowledgements) == 3


def test_create_partial_failure_or_wrong_native_result_is_unconfirmed(lifecycle_env, monkeypatch):
    control = _control()
    original_get = team_service.get_team
    def lost_detail(*_args, **_kwargs):
        raise team_service.TeamServiceError("detail failed after native index commit")
    monkeypatch.setattr(team_service, "get_team", lost_detail)
    with server_operator_scope("operator-test", roles=("operator",)):
        with pytest.raises(ManagementError) as unknown:
            control.create_team({"name": "Persisted before follow-up failure"})
        assert unknown.value.code == "OPERATION_UNCONFIRMED"
        assert any(row["name"] == "Persisted before follow-up failure" for row in team_service._load_index()["teams"])
        monkeypatch.setattr(team_service, "get_team", original_get)
        monkeypatch.setattr(team_service, "create_team", lambda **_kwargs: lifecycle_env["team"])
        with pytest.raises(ManagementError) as mismatch:
            control.create_team({"name": "Unexpected Team"})
        assert mismatch.value.code == "OPERATION_UNCONFIRMED"


def test_member_delta_preserves_untouched_raw_member_rows(lifecycle_env, monkeypatch):
    control = _control()
    team_id = lifecycle_env["team"]["teamId"]
    before = _row(team_id)
    original_update = team_service.update_team
    calls = []
    def capture(team_id, **kwargs):
        calls.append(deepcopy(kwargs))
        return original_update(team_id, **kwargs)
    monkeypatch.setattr(team_service, "update_team", capture)
    with server_operator_scope("operator-test", roles=("operator",)):
        result = control.add_member({"team_id": team_id, "expected_team_fingerprint": team_record_fingerprint(before),
                                     "member": {"agentId": lifecycle_env["outsider"]["agentId"], "role": "peer"}})
        assert calls[0]["members"][:-1] == before["members"]
        assert _row(team_id)["members"][:-1] == before["members"]
        control.remove_member({"team_id": team_id, "expected_team_fingerprint": result["fingerprint"],
                               "agent_id": lifecycle_env["outsider"]["agentId"]})
    assert calls[1]["members"] == before["members"]
    assert _row(team_id)["members"] == before["members"]


def test_duplicate_absent_cross_team_and_stale_members_are_rejected_without_write(lifecycle_env):
    control = _control()
    team_id = lifecycle_env["team"]["teamId"]
    before = _row(team_id)
    other = team_service.create_team(name="Other Team", members=[{"agentId": lifecycle_env["outsider"]["agentId"]}])
    with server_operator_scope("operator-test", roles=("operator",)):
        for member_id in (lifecycle_env["lead"]["agentId"], lifecycle_env["outsider"]["agentId"]):
            with pytest.raises(ManagementError) as rejected:
                control.add_member({"team_id": team_id, "expected_team_fingerprint": team_record_fingerprint(before),
                                     "member": {"agentId": member_id}})
            assert rejected.value.code == "INVALID_INPUT"
        with pytest.raises(ManagementError) as missing:
            control.remove_member({"team_id": team_id, "expected_team_fingerprint": team_record_fingerprint(before),
                                   "agent_id": lifecycle_env["outsider"]["agentId"]})
        assert missing.value.code == "INVALID_INPUT"
        with pytest.raises(ManagementError) as stale:
            control.remove_member({"team_id": team_id, "expected_team_fingerprint": "0" * 64,
                                   "agent_id": lifecycle_env["member"]["agentId"]})
        assert stale.value.code == "STATE_CONFLICT"
    assert _row(team_id) == before and _row(other["teamId"])["status"] == "active"


def test_member_native_cas_rejects_preflight_to_commit_change(lifecycle_env, monkeypatch):
    control = _control()
    team_id = lifecycle_env["team"]["teamId"]
    before = _row(team_id)
    original_update = team_service.update_team
    def race(team_id, **kwargs):
        original_update(team_id, description="Concurrent update")
        return original_update(team_id, **kwargs)
    monkeypatch.setattr(team_service, "update_team", race)
    with server_operator_scope("operator-test", roles=("operator",)):
        with pytest.raises(ManagementError) as stale:
            control.add_member({"team_id": team_id, "expected_team_fingerprint": team_record_fingerprint(before),
                                 "member": {"agentId": lifecycle_env["outsider"]["agentId"]}})
        assert stale.value.code == "STATE_CONFLICT"
    assert _row(team_id)["members"] == before["members"]
    assert _row(team_id)["description"] == "Concurrent update"


def test_member_and_archive_obey_native_archive_lease(lifecycle_env):
    control = _control()
    team_id = lifecycle_env["team"]["teamId"]
    with server_operator_scope("operator-test", roles=("operator",)):
        preview = control.read_archive_preview(team_id)
        with team_admission.archive_admission(team_id):
            for operation, parameters in (
                (control.add_member, {"team_id": team_id, "expected_team_fingerprint": preview["fingerprint"],
                                      "member": {"agentId": lifecycle_env["outsider"]["agentId"]}}),
                (control.remove_member, {"team_id": team_id, "expected_team_fingerprint": preview["fingerprint"],
                                         "agent_id": lifecycle_env["member"]["agentId"]}),
                (control.archive_team, _archive_parameters(preview)),
            ):
                with pytest.raises(ManagementError) as locked:
                    operation(parameters)
                assert locked.value.code == "TEAM_LOCKED"


@pytest.mark.parametrize("archived", [False, True])
def test_system_and_archived_teams_are_locked(lifecycle_env, archived):
    control = _control()
    team_id = lifecycle_env["team"]["teamId"]
    state = team_service._load_index()
    row = team_service._find_team(state, team_id)
    if archived:
        row["status"] = "archived"
    else:
        row["teamKind"] = "research"
        row["teamSource"] = "research_organization"
    team_service._save_index(state)
    with server_operator_scope("operator-test", roles=("operator",)):
        with pytest.raises(ManagementError) as locked:
            control.read_archive_preview(team_id)
        assert locked.value.code == "TEAM_LOCKED"
        for operation, parameters in (
            (control.remove_member, {"team_id": team_id, "expected_team_fingerprint": team_record_fingerprint(row),
                                     "agent_id": lifecycle_env["member"]["agentId"]}),
            (control.archive_team, {"team_id": team_id, "expected_team_fingerprint": team_record_fingerprint(row),
                "expected_member_agent_ids": [member["agentId"] for member in row["members"]],
                "expected_linked_chat_room_id": row["linkedChatRoomId"]}),
        ):
            with pytest.raises(ManagementError) as denied:
                operation(parameters)
            assert denied.value.code == "TEAM_LOCKED"


def test_archive_preview_reads_existing_snapshot_without_repair_or_writes(lifecycle_env, monkeypatch):
    control = _control()
    team_id = lifecycle_env["team"]["teamId"]
    before = _tree(directory.PROJECT_ROOT)
    monkeypatch.setattr(team_service, "get_team", lambda *_args: pytest.fail("Preview must not hydrate or repair Team"))
    with server_operator_scope("operator-test", roles=("operator",)):
        preview = control.read_archive_preview(team_id)
    assert preview["memberAgentIds"] == [member["agentId"] for member in _row(team_id)["members"]]
    assert preview["effects"] == list(contracts.TEAM_ARCHIVE_EFFECTS)
    assert preview["untrustedContent"] is True
    assert _tree(directory.PROJECT_ROOT) == before


@pytest.mark.parametrize("field,value", [("expected_team_fingerprint", "0" * 64),
    ("expected_member_agent_ids", []), ("expected_linked_chat_room_id", "wrong-room")])
def test_archive_exact_preview_bindings_precede_all_native_side_effects(lifecycle_env, monkeypatch, field, value):
    control = _control()
    team_id = lifecycle_env["team"]["teamId"]
    monkeypatch.setattr(team_service, "archive_team", lambda *_args, **_kwargs: pytest.fail("Stale archive reached native write"))
    with server_operator_scope("operator-test", roles=("operator",)):
        preview = control.read_archive_preview(team_id)
        with pytest.raises(ManagementError) as stale:
            control.archive_team({**_archive_parameters(preview), field: value})
        assert stale.value.code == "STATE_CONFLICT"


def test_archive_preflight_to_native_admission_roster_race_has_zero_cascade(lifecycle_env, monkeypatch):
    control = _control()
    team_id = lifecycle_env["team"]["teamId"]
    original_archive = team_service.archive_team
    before_agents = deepcopy(directory.load_state())
    before_rooms = deepcopy(chat_room_service.read_chat_rooms_snapshot())
    def race(team_id, **kwargs):
        state = team_service._load_index()
        row = team_service._find_team(state, team_id)
        row["members"].append(team_service._normalize_members(
            [{"agentId": lifecycle_env["outsider"]["agentId"], "role": "racing member"}], require_active=True)[0])
        team_service._save_index(state)
        return original_archive(team_id, **kwargs)
    monkeypatch.setattr(team_service, "archive_team", race)
    monkeypatch.setattr(team_service, "_cascade_archive_member_agents_unlocked",
                        lambda *_args, **_kwargs: pytest.fail("CAS race entered Agent archive cascade"))
    with server_operator_scope("operator-test", roles=("operator",)):
        preview = control.read_archive_preview(team_id)
        with pytest.raises(ManagementError) as stale:
            control.archive_team(_archive_parameters(preview))
        assert stale.value.code == "STATE_CONFLICT"
    assert directory.load_state() == before_agents
    assert chat_room_service.read_chat_rooms_snapshot() == before_rooms
    assert _row(team_id)["status"] == "active"


def test_busy_workflow_or_protected_member_is_rejected_before_native_archive(lifecycle_env, monkeypatch):
    control = _control()
    team_id = lifecycle_env["team"]["teamId"]
    monkeypatch.setattr(team_service, "archive_team", lambda *_args, **_kwargs: pytest.fail("Unsafe Team reached archive"))
    with server_operator_scope("operator-test", roles=("operator",)):
        preview = control.read_archive_preview(team_id)
        monkeypatch.setattr(team_admission, "_workflow_records", lambda _id: [{"status": "running"}])
        with pytest.raises(ManagementError) as busy:
            control.archive_team(_archive_parameters(preview))
        assert busy.value.code == "TEAM_LOCKED"
        monkeypatch.setattr(team_admission, "_workflow_records", lambda _id: [])
        def protected(*_args):
            raise team_service.TeamServiceError("Protected core Agent cannot be archived")
        monkeypatch.setattr(team_service, "_ensure_team_member_agents_can_archive", protected)
        with pytest.raises(ManagementError) as denied:
            control.archive_team(_archive_parameters(preview))
        assert denied.value.code == "INVALID_INPUT"


def test_member_followup_and_partial_native_archive_failures_are_unknown(lifecycle_env, monkeypatch):
    control = _control()
    team_id = lifecycle_env["team"]["teamId"]
    original_get = team_service.get_team
    def detail_failure(*_args):
        raise team_service.TeamServiceError("follow-up failure")
    with server_operator_scope("operator-test", roles=("operator",)):
        before = control.read_team(team_id)
        monkeypatch.setattr(team_service, "get_team", detail_failure)
        with pytest.raises(ManagementError) as unknown:
            control.remove_member({"team_id": team_id, "expected_team_fingerprint": before["fingerprint"],
                                   "agent_id": lifecycle_env["member"]["agentId"]})
        assert unknown.value.code == "OPERATION_UNCONFIRMED"
        assert lifecycle_env["member"]["agentId"] not in {row["agentId"] for row in _row(team_id)["members"]}
        monkeypatch.setattr(team_service, "get_team", original_get)
        preview = control.read_archive_preview(team_id)
        def partial(team_id, **_kwargs):
            directory.archive_agent_instance(lifecycle_env["lead"]["agentId"], repair_mode_bindings=False)
            raise team_service.TeamServiceError("next cascade item failed")
        monkeypatch.setattr(team_service, "archive_team", partial)
        with pytest.raises(ManagementError) as partial_failure:
            control.archive_team(_archive_parameters(preview))
        assert partial_failure.value.code == "OPERATION_UNCONFIRMED"
    assert directory.get_agent(lifecycle_env["lead"]["agentId"], include_archived=True)["status"] == "archived"
    assert _row(team_id)["status"] == "active"


def test_real_archive_partial_cascade_preserves_earlier_success_and_returns_unknown(lifecycle_env, monkeypatch):
    control = _control()
    team_id = lifecycle_env["team"]["teamId"]
    original_archive = agent_bulk_delete_service.archive_agent_instance
    def fail_second(agent_id, **kwargs):
        if agent_id == lifecycle_env["member"]["agentId"]:
            raise directory.AgentDirectoryError("Injected second member archive failure")
        return original_archive(agent_id, **kwargs)
    monkeypatch.setattr(agent_bulk_delete_service, "archive_agent_instance", fail_second)
    monkeypatch.setattr(control, "_acknowledge", lambda *_args: pytest.fail("Partial cascade cannot acknowledge success"))
    with server_operator_scope("operator-test", roles=("operator",)):
        preview = control.read_archive_preview(team_id)
        with pytest.raises(ManagementError) as unknown:
            control.archive_team(_archive_parameters(preview))
        assert unknown.value.code == "OPERATION_UNCONFIRMED"
    assert directory.get_agent(lifecycle_env["lead"]["agentId"], include_archived=True)["status"] == "archived"
    assert directory.get_agent(lifecycle_env["member"]["agentId"])["status"] == "active"
    assert _row(team_id)["status"] == "active"


def test_real_native_skipped_member_never_acknowledges_completed_team_archive(lifecycle_env, tmp_path, monkeypatch):
    from core.web.services.external_management import operation_receipts
    native = Native()
    outcome = operation_receipts.NativeOutcomeStore(tmp_path / "skipped-team-outcomes", project_root=native.project_root)
    native.operation_receipts = lambda: outcome
    control = TeamLifecycleControl(native)
    team_id = lifecycle_env["team"]["teamId"]
    skipped_agent_id = lifecycle_env["member"]["agentId"]
    original_check = agent_bulk_delete_service.ensure_agent_archive_allowed
    original_bulk = agent_bulk_delete_service.bulk_archive_agents
    bulk_results = []
    def protect_at_bulk_admission(agent_id):
        if agent_id == skipped_agent_id:
            with directory._STATE_LOCK:
                state = directory.load_state()
                directory._find_agent(state, agent_id).setdefault("metadata", {})["protected"] = True
                directory.save_state(state)
        return original_check(agent_id)
    def track_bulk(*args, **kwargs):
        result = original_bulk(*args, **kwargs)
        bulk_results.append(deepcopy(result))
        return result
    monkeypatch.setattr(agent_bulk_delete_service, "ensure_agent_archive_allowed", protect_at_bulk_admission)
    monkeypatch.setattr(agent_bulk_delete_service, "bulk_archive_agents", track_bulk)
    monkeypatch.setattr(operation_receipts, "record_success",
                        lambda *_args: pytest.fail("Skipped Agent must not produce a causal success receipt"))
    with server_operator_scope("operator-test", roles=("operator",)):
        parameters = _archive_parameters(control.read_archive_preview(team_id))
        with pytest.raises(ManagementError) as unknown:
            control.archive_team(parameters, marker=_proof(parameters, "team_archive"))
        assert unknown.value.code == "OPERATION_UNCONFIRMED"
    assert len(bulk_results) == 1 and bulk_results[0]["failed"] == []
    assert [row["agentId"] for row in bulk_results[0]["skipped"]] == [skipped_agent_id]
    assert directory._find_agent(directory.load_state(), skipped_agent_id)["status"] == "active"
    assert directory._find_agent(directory.load_state(), lifecycle_env["lead"]["agentId"])["status"] == "archived"
    assert _row(team_id)["status"] == "archived" and _row(team_id)["linkedChatRoomId"] == ""
    assert not list(outcome.root.rglob("*.json"))


@pytest.mark.parametrize("damage", ["missing_member", "unreadable_authority"])
def test_archive_post_commit_agent_authority_failure_is_unknown_without_success_ack(lifecycle_env, monkeypatch, damage):
    control = _control()
    team_id = lifecycle_env["team"]["teamId"]
    original_archive = team_service.archive_team
    calls = []
    def damage_after_native_archive(*args, **kwargs):
        result = original_archive(*args, **kwargs)
        calls.append("native archive")
        path = directory.registry_path()
        if damage == "missing_member":
            state = directory.load_state()
            state["agents"] = [row for row in state["agents"] if row["agentId"] != lifecycle_env["member"]["agentId"]]
            directory.save_state(state)
        else:
            path.write_text("{unreadable existing Agent authority", encoding="utf-8")
        return result
    monkeypatch.setattr(team_service, "archive_team", damage_after_native_archive)
    monkeypatch.setattr(control, "_acknowledge", lambda *_args: pytest.fail("Unreadable Agent state cannot acknowledge success"))
    with server_operator_scope("operator-test", roles=("operator",)):
        preview = control.read_archive_preview(team_id)
        with pytest.raises(ManagementError) as unknown:
            control.archive_team(_archive_parameters(preview))
        assert unknown.value.code == "OPERATION_UNCONFIRMED"
    assert calls == ["native archive"] and _row(team_id)["status"] == "archived"


def _proof(parameters, action):
    from core.web.services.external_management.store import digest
    return {"subjectType": "operator", "subjectId": "ops-" + "a" * 32,
            "requestKey": digest([action, "original-request"]), "requestFingerprint": digest(parameters)}


def test_four_lifecycle_actions_have_original_causal_receipts_and_do_not_replay(lifecycle_env, tmp_path, monkeypatch):
    from core.web.services.external_management import platform_actions
    from core.web.services.external_management.operation_receipts import NativeOutcomeStore
    native = Native()
    outcome = NativeOutcomeStore(tmp_path / "native-team-outcomes", project_root=native.project_root)
    native.operation_receipts = lambda: outcome
    calls = []
    for name in ("create_team", "update_team", "archive_team"):
        original = getattr(team_service, name)
        def tracked(*args, _method=original, _name=name, **kwargs):
            calls.append(_name)
            return _method(*args, **kwargs)
        monkeypatch.setattr(team_service, name, tracked)
    with server_operator_scope("operator-test", roles=("operator",)):
        parameters = {"name": "Causally acknowledged Team"}
        for action in ("team_create", "team_member_add", "team_member_remove", "team_archive"):
            marker = _proof(parameters, action)
            result = platform_actions.execute(native, action, parameters, marker)
            assert outcome.read(action, parameters, marker) == result
            assert platform_actions.execute(native, action, parameters, marker) == result
            confirmed = platform_actions.reconcile(native, action, parameters, marker)
            assert confirmed["state"] == "confirmed" and confirmed["evidence"] == "native_outcome"
            assert confirmed["result"] == result
            other = platform_actions.reconcile(native, action, parameters, {**marker, "requestKey": "f" * 64})
            assert other["state"] == "requires_review" and other["result"] is None
            parameters = {"team_id": result["resourceId"], "expected_team_fingerprint": result["fingerprint"]}
            if action == "team_create":
                parameters["member"] = {"agentId": lifecycle_env["outsider"]["agentId"]}
            elif action == "team_member_add":
                parameters["agent_id"] = lifecycle_env["outsider"]["agentId"]
            elif action == "team_member_remove":
                parameters = _archive_parameters(TeamLifecycleControl(native).read_archive_preview(result["resourceId"]))
    assert calls == ["create_team", "update_team", "update_team", "archive_team"]
    assert len(list(outcome.root.rglob("*.json"))) == 4


@pytest.mark.parametrize("failure", ["native_followup", "acknowledgement"])
def test_creation_without_causal_acknowledgement_requires_review_and_never_infers_from_current_state(
    lifecycle_env, tmp_path, monkeypatch, failure,
):
    from core.web.services.external_management import platform_actions
    from core.web.services.external_management.operation_receipts import NativeOutcomeStore
    native = Native()
    outcome = NativeOutcomeStore(tmp_path / "native-team-outcomes", project_root=native.project_root)
    native.operation_receipts = lambda: outcome
    def lost_ack(*_args, **_kwargs):
        raise OSError("Native creation acknowledgement unavailable")
    if failure == "native_followup":
        monkeypatch.setattr(team_service, "get_team", lost_ack)
    else:
        monkeypatch.setattr(outcome, "write", lost_ack)
    parameters = {"name": "Persisted Team without causal acknowledgement"}
    marker = _proof(parameters, "team_create")
    with server_operator_scope("operator-test", roles=("operator",)):
        with pytest.raises(ManagementError) as unknown:
            platform_actions.execute(native, "team_create", parameters, marker)
        assert unknown.value.code == "OPERATION_UNCONFIRMED"
        before = _tree(directory.PROJECT_ROOT)
        unconfirmed = platform_actions.reconcile(native, "team_create", parameters, marker)
        assert unconfirmed["state"] == "requires_review" and unconfirmed["result"] is None
        assert _tree(directory.PROJECT_ROOT) == before
    assert sum(row["name"] == parameters["name"] for row in team_service._load_index()["teams"]) == 1
    assert outcome.read("team_create", parameters, marker) is None
