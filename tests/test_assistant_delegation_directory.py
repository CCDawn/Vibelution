"""Discover finite goal grants without treating metadata as source proof."""
import asyncio
import json
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from core.assistant_runtime import native, delegation
from core.infrastructure import native_runtime
from core.assistant_runtime.dispatch import DispatchError
from tests.test_assistant_delegation import setup_goal, child


@pytest.fixture
def directory(setup_goal, monkeypatch):
    owner, dispatch, runtime, goal, now, seen = setup_goal
    root = owner.root.parent
    sessions = SimpleNamespace(PROJECT_ROOT=root)
    agent_directory = SimpleNamespace(PROJECT_ROOT=root, current_agent_runtime=lambda: runtime)
    directory_runtime = SimpleNamespace(directory_store_project_root=lambda: root, get_open_directory_store=lambda: object())

    @contextmanager
    def source_command():
        yield sessions, "session"

    monkeypatch.setattr(native, "_source_command", source_command)
    monkeypatch.setattr(native, "_services", lambda: (agent_directory, None, sessions, directory_runtime))
    monkeypatch.setattr(native, "_AGENT_ID", "assistant")
    monkeypatch.setattr(native, "_SESSION_ID", "session")
    monkeypatch.setattr(native_runtime, "assistant_native_root", lambda: root)
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    return owner, dispatch, runtime, goal, now, seen


def test_directory_recovers_goal_ids_after_restart_without_reading_journal_or_bodies(directory):
    owner, dispatch, runtime, goal, now, seen = directory
    owner.create(goal, runtime)
    restored = delegation.DelegationManager(dispatch, source_reader=lambda *_: pytest.fail("list must not read source"),
                                           clock=lambda: now[0])
    before = len(seen)
    page = asyncio.run(restored.list({}, runtime))
    assert page["complete"] is True and page["status"] == "ok"
    assert page["goals"] == [{"goalId": "goal-1", "targetCount": 1, "permissionProfile": "workspace_write",
        "maxTasks": 2, "usedTasks": 0, "remainingTasks": 2, "expiresAt": 1600.0,
        "revoked": False, "active": True, "sourceVerified": False}]
    assert len(seen) == before


@pytest.mark.parametrize("changes", [{"offset": True}, {"offset": 513}, {"limit": 0}, {"limit": 7},
    {"expected_digest": "bad"}, {"project_id": "forbidden"}, {"root": "C:/forbidden"}, {"sourceVerified": True}])
def test_closed_directory_contract_and_read_only_discovery(changes):
    with pytest.raises(ValueError):
        delegation.GoalList.model_validate(changes)
    contract = delegation.contracts()["delegation_goal_list"]
    assert contract["governed"] is False
    assert contract["parameters"]["additionalProperties"] is False
    assert "sourceVerified=false" in contract["description"]


def test_digest_paging_uses_persisted_rows_and_not_the_observation_clock(directory):
    owner, _, runtime, goal, now, _ = directory
    for index in range(8):
        owner.create({**goal, "goal_id": "g-" + str(index) + "x" * 90}, runtime)
    first = asyncio.run(owner.list({"limit": 6}, runtime))
    assert first["nextOffset"] == 6 and first["limit"] == 6
    assert len(json.dumps({"source": "launcher-assistant", **first}, ensure_ascii=False)) <= 3400
    now[0] = 2000  # Clock expiry changes active, not persisted grant identity.
    second = asyncio.run(owner.list({"offset": 6, "expected_digest": first["snapshotDigest"]}, runtime))
    assert second["snapshotDigest"] == first["snapshotDigest"] and second["nextOffset"] is None
    assert len(second["goals"]) == 2 and all(not row["active"] and row["sourceVerified"] is False for row in second["goals"])
    assert len({row["goalId"] for row in first["goals"] + second["goals"]}) == 8


def test_quota_change_invalidates_continuation_and_revocation_is_visible_metadata(directory):
    owner, _, runtime, goal, _, _ = directory
    owner.create(goal, runtime)
    owner.create({**goal, "goal_id": "goal-2"}, runtime)
    first = asyncio.run(owner.list({"limit": 1}, runtime))
    asyncio.run(owner.derived(child(), runtime))
    with pytest.raises(DispatchError) as error:
        asyncio.run(owner.list({"offset": 1, "expected_digest": first["snapshotDigest"]}, runtime))
    assert error.value.code == "DELEGATION_DIRECTORY_CHANGED"
    asyncio.run(owner.revoke("goal-1", runtime))
    current = asyncio.run(owner.list({}, runtime))
    row = next(row for row in current["goals"] if row["goalId"] == "goal-1")
    assert row["revoked"] and not row["active"] and row["usedTasks"] == 1 and row["remainingTasks"] == 1
    assert "targets" not in row and "sourceTurnId" not in row and "sourceHash" not in row


@pytest.mark.parametrize("change", ["project", "binding"])
def test_one_revoked_or_rebound_target_filters_the_whole_goal_and_old_ids(directory, change):
    owner, dispatch, runtime, goal, _, _ = directory
    dispatch.projects["project-2"] = owner.root.parent / "project-two"
    owner.create({**goal, "targets": [*goal["targets"], {"project_id": "project-2", "agent_id": "worker-two"}]}, runtime)
    first = asyncio.run(owner.list({}, runtime))
    assert first["goals"][0]["targetCount"] == 2
    if change == "project":
        dispatch.projects.pop("project-2")
    else:
        dispatch.projects["project-2"] = owner.root.parent / "other-project"
    assert asyncio.run(owner.list({}, runtime))["goals"] == []
    with pytest.raises(DispatchError) as error:
        asyncio.run(owner.list({"expected_digest": first["snapshotDigest"]}, runtime))
    assert error.value.code == "DELEGATION_DIRECTORY_CHANGED"


def test_revocation_during_record_scan_is_rechecked_before_any_goal_is_returned(directory, monkeypatch):
    owner, dispatch, runtime, goal, _, _ = directory
    owner.create(goal, runtime)
    read = owner._read

    def revoke_after_read(*args, **kwargs):
        result = read(*args, **kwargs)
        dispatch.projects.clear()
        return result

    monkeypatch.setattr(owner, "_read", revoke_after_read)
    assert asyncio.run(owner.list({}, runtime))["goals"] == []


@pytest.mark.parametrize("field", ["agentId", "sessionId"])
def test_other_agent_or_session_source_metadata_never_leaks_goal_ids(directory, field):
    owner, _, runtime, goal, _, _ = directory
    owner.create(goal, runtime)
    row = owner._read("goal-1")
    row["source"][field] = "another-identity"
    row["fingerprint"] = delegation._hash([row["parameters"], row["source"], row["bindings"]])
    owner._save("goal-1", row)
    assert asyncio.run(owner.list({}, runtime))["goals"] == []


def test_current_native_profile_or_turn_cannot_be_spoofed_by_list_parameters(directory, monkeypatch):
    owner, _, runtime, goal, _, _ = directory
    owner.create(goal, runtime)
    with pytest.raises(DispatchError) as error:
        asyncio.run(owner.list({}, {**runtime, "turnId": "other-turn"}))
    assert error.value.code == "DELEGATION_DIRECTORY_IDENTITY_INVALID"
    monkeypatch.setattr(native_runtime, "assistant_native_root", lambda: owner.root / "different-profile")
    with pytest.raises(DispatchError):
        asyncio.run(owner.list({}, runtime))


def test_bad_records_produce_partial_coverage_instead_of_an_empty_complete_census(directory):
    owner, _, runtime, goal, _, _ = directory
    owner.create(goal, runtime)
    (owner.root / ("0" * 64 + ".json")).write_text("{bad", encoding="utf-8")
    (owner.root / "unbound-name.json").write_text("{}", encoding="utf-8")
    page = asyncio.run(owner.list({}, runtime))
    assert page["status"] == "partial" and page["complete"] is False
    assert page["coverage"]["invalidRecords"] == 2 and len(page["goals"]) == 1
    owner._path("goal-1").unlink()
    page = asyncio.run(owner.list({}, runtime))
    assert page["goals"] == [] and page["status"] == "partial" and not page["complete"]


def test_file_scan_and_native_metadata_io_are_bounded_and_off_host_loop(directory, monkeypatch):
    owner, _, runtime, goal, _, _ = directory
    for index in range(4):
        owner.create({**goal, "goal_id": f"goal-{index}"}, runtime)
    monkeypatch.setattr(delegation, "_DIRECTORY_FILES", 2)
    seen_threads = []
    original = owner._directory_identity

    def check_identity(current):
        seen_threads.append(threading.get_ident())
        return original(current)

    monkeypatch.setattr(owner, "_directory_identity", check_identity)
    main_thread = threading.get_ident()
    page = asyncio.run(owner.list({}, runtime))
    assert page["coverage"]["scannedFiles"] == 2 and page["coverage"]["scanComplete"] is False
    assert not page["complete"] and page["status"] == "partial" and len(page["goals"]) == 2
    assert seen_threads and all(thread != main_thread for thread in seen_threads)


def test_derived_source_verification_runs_in_worker_without_changing_quota(directory):
    owner, dispatch, runtime, goal, _, _ = directory
    owner.create(goal, runtime)
    source = owner._source_reader
    seen_threads = []

    def verify(current, reference):
        seen_threads.append(threading.get_ident())
        return source(current, reference)

    owner._source_reader = verify
    main_thread = threading.get_ident()
    asyncio.run(owner.derived(child(), runtime))
    assert len(seen_threads) == 2 and all(thread != main_thread for thread in seen_threads)
    assert len(dispatch.calls) == 1 and owner._read("goal-1")["children"].keys() == {"child-1"}
