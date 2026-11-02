"""Research management uses the formal native Ledger, CAS and operator actor."""
from __future__ import annotations

import importlib
import json

import pytest

from core.web.services.external_management.service import ManagementError
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests.test_launcher_assistant_runtime_operations import env, research  # native isolated owners
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS, build_attempt_record, build_command_record


def control():
    return importlib.import_module("core.web.services.external_management.research_control")


def query(research, **kwargs):
    return {"run_id": "run-test", **research.refs, **kwargs}


def request(research, command, **kwargs):
    return {**query(research), "command": command, "expected_revision": "2", **kwargs}


def fail_attempt(research):
    harness = research.harness
    attempt = harness.store.latest_attempt("run-test", "problem_understanding")

    def mutate(uow):
        uow.repository.update_attempt_status(attempt.node_run_id, "failed", FIXED_NOW_MS + 2000)
        uow.repository.update_run_status("run-test", "research-team", "blocked", FIXED_NOW_MS + 2000)

    harness.store.submit(mutate, force_flush=True).result(timeout=10)
    return attempt


def human_task(research, *, task_id="human-a", run_id="run-human"):
    harness = research.harness
    if harness.store.get_run(run_id) is None:
        harness.seed_run(run_id=run_id, status="waiting_human")

    def mutate(uow):
        command_id, attempt_id = "seed-" + task_id, "attempt-" + task_id
        uow.repository.insert_command(build_command_record(command_id=command_id, run_id=run_id,
            node_id="protocol_freeze", idempotency_key=command_id))
        uow.repository.insert_attempt(build_attempt_record(node_run_id=attempt_id, run_id=run_id,
            node_id="protocol_freeze", command_id=command_id, actor_kind="human", status="waiting_human"))
        uow.repository.insert_human_task(task_id=task_id, run_id=run_id, node_run_id=attempt_id,
            handoff_id=None, task_kind="knowledge_gate", prompt_json='{"secret":"SECRET human prompt"}',
            created_at_ms=FIXED_NOW_MS)

    harness.store.submit(mutate, force_flush=True).result(timeout=10)
    return {"run_id": run_id, **research.refs}


def test_retry_real_native_attempt_uses_cas_actor_and_stable_id(env, research):
    before = fail_attempt(research)
    params = request(research, "retry_node", node_id="problem_understanding")
    with server_operator_scope("human-operator", roles=("operator",)):
        metadata = control().read(env.gateway, query(research))
        assert metadata["nodes"][0]["commands"] == ["retry_node"]
        accepted = control().command(env.gateway, params, request_id="retry-a")
        replay = control().command(env.gateway, params, request_id="retry-a")
    assert accepted == replay
    assert accepted["operation"]["revision"] == "3"
    assert accepted["receipt"]["requestId"] == "retry-a"
    assert accepted["revisionCheck"] == "native_cas"
    attempts = research.harness.store.list_attempts("run-test")
    assert len(attempts) == 2
    assert next(item for item in attempts if item.node_run_id == before.node_run_id).status == "stale"
    assert research.harness.store.latest_attempt("run-test", "problem_understanding").attempt == 2
    record = research.harness.store.get_command_by_idempotency("run-test", "retry-a")
    assert json.loads(record.requested_by_json) == {"actorType": "user", "actorId": "human-operator"}
    assert json.loads(record.request_json)["payload"] == {"reason": "launcher_assistant_operator_control"}


@pytest.mark.parametrize("decision,target", [("accept", "accepted"), ("reject", "rejected")])
def test_resolve_real_human_task_is_exactly_bound_and_has_no_prompt_projection(env, research, decision, target):
    refs = human_task(research)
    params = {**refs, "command": "resolve_human_task", "node_id": "protocol_freeze", "task_id": "human-a",
              "decision": decision, "expected_revision": "1"}
    with server_operator_scope("human-operator", roles=("operator",)):
        metadata = control().read(env.gateway, refs)
        assert metadata["humanTasks"] == [{"taskId": "human-a", "nodeId": "protocol_freeze",
            "nodeRunId": "attempt-human-a", "status": "pending", "commands": ["resolve_human_task"],
            "decisions": ["accept", "reject"], "checkpointId": ""}]
        result = control().command(env.gateway, params, request_id="decide-a")
        assert control().command(env.gateway, params, request_id="decide-a") == result
    assert research.harness.store.read(lambda repo: repo.get_human_task("human-a"))[6] == target
    assert result["receipt"]["acceptedRevision"] == "2"
    assert result["receipt"]["decision"] == decision
    assert "SECRET" not in json.dumps([metadata, result])
    assert "prompt" not in json.dumps(metadata).lower()


def test_reconcile_real_ledger_is_idempotent_and_stale_version_writes_nothing(env, research):
    fail_attempt(research)
    params = request(research, "reconcile_run")
    with server_operator_scope("human-operator", roles=("operator",)):
        with pytest.raises(ManagementError, match="run_version_conflict"):
            control().command(env.gateway, {**params, "expected_revision": "1"}, request_id="stale-reconcile")
        assert research.harness.store.get_command_by_idempotency("run-test", "stale-reconcile") is None
        result = control().command(env.gateway, params, request_id="reconcile-a")
        assert control().command(env.gateway, params, request_id="reconcile-a") == result
    assert result["receipt"]["command"] == "reconcile_run"
    assert research.harness.store.get_run("run-test").run_version == 3


@pytest.mark.parametrize("extra", [{"actor": "forged"}, {"payload": {"force": True}},
    {"request_id": "model-key"}, {"checkpoint_id": "forged"}, {"reason": "SECRET"}])
def test_model_cannot_supply_actor_key_body_or_checkpoint(env, research, extra):
    fail_attempt(research)
    with server_operator_scope("human-operator", roles=("operator",)):
        with pytest.raises(ManagementError, match="INVALID_INPUT"):
            control().command(env.gateway, request(research, "retry_node", node_id="problem_understanding", **extra),
                              request_id="trusted-a")
    assert research.harness.store.get_run("run-test").run_version == 2


@pytest.mark.parametrize("roles", [None, (), ("agent",)])
def test_no_privileged_server_operator_cannot_control_even_retry(env, research, roles):
    from contextlib import nullcontext
    fail_attempt(research)
    with nullcontext() if roles is None else server_operator_scope("reader", roles=roles):
        assert control().read(env.gateway, query(research))["nodes"][0]["commands"] == []
        with pytest.raises(ManagementError, match="command_forbidden"):
            control().command(env.gateway, request(research, "retry_node", node_id="problem_understanding"),
                              request_id="trusted-a")
    assert research.harness.store.get_run("run-test").run_version == 2


def test_human_target_cannot_cross_run_or_node_and_stale_is_no_write(env, research):
    refs = human_task(research)
    with server_operator_scope("human-operator", roles=("operator",)):
        for params in (
            request(research, "resolve_human_task", node_id="protocol_freeze", task_id="human-a", decision="accept"),
            {**refs, "command": "resolve_human_task", "node_id": "smoke_gate", "task_id": "human-a",
             "decision": "accept", "expected_revision": "1"},
        ):
            with pytest.raises(ManagementError, match="task_not_found"):
                control().command(env.gateway, params, request_id="wrong-target")
    assert research.harness.store.read(lambda repo: repo.get_human_task("human-a"))[6] == "pending"


def test_lost_ack_is_unknown_and_receipt_read_recovers_without_second_native_submit(env, research, monkeypatch):
    fail_attempt(research)
    params = request(research, "retry_node", node_id="problem_understanding")
    owner = research.harness.command_service
    submit, calls = owner.submit, []

    def lost_ack(request):
        calls.append(request)
        submit(request)
        raise OSError("SECRET native acknowledgement disappeared")

    monkeypatch.setattr(owner, "submit", lost_ack)
    with server_operator_scope("human-operator", roles=("operator",)):
        with pytest.raises(ManagementError, match="OPERATION_UNCONFIRMED"):
            control().command(env.gateway, params, request_id="lost-ack-a")
        result = control().read_receipt(env.gateway, params, request_id="lost-ack-a")
        assert result["receipt"]["acceptedRevision"] == "3"
        assert control().command(env.gateway, params, request_id="lost-ack-a") == result
    assert len(calls) == 1
    assert len(research.harness.store.list_attempts("run-test")) == 2


def test_same_id_different_action_or_operator_cannot_reuse_receipt(env, research):
    fail_attempt(research)
    params = request(research, "retry_node", node_id="problem_understanding")
    with server_operator_scope("human-operator", roles=("operator",)):
        control().command(env.gateway, params, request_id="stable-a")
        with pytest.raises(ManagementError, match="idempotency_conflict"):
            control().command(env.gateway, request(research, "reconcile_run"), request_id="stable-a")
    with server_operator_scope("another-operator", roles=("operator",)):
        with pytest.raises(ManagementError, match="idempotency_conflict"):
            control().read_receipt(env.gateway, params, request_id="stable-a")


@pytest.mark.parametrize("change", [{"team_id": "other-team"}, {"flow_id": "other-flow"}])
def test_research_owner_refs_cannot_cross_authority(env, research, change):
    fail_attempt(research)
    with server_operator_scope("human-operator", roles=("operator",)):
        with pytest.raises(ManagementError, match="run_not_found"):
            control().read(env.gateway, query(research, **change))
        with pytest.raises(ManagementError, match="run_not_found"):
            control().command(env.gateway, request(research, "retry_node", node_id="problem_understanding", **change),
                              request_id="wrong-owner")
    assert research.harness.store.get_command_by_idempotency("run-test", "wrong-owner") is None


def test_native_second_cas_rejects_racing_command_with_no_second_attempt(env, research, monkeypatch):
    import dataclasses
    from core.research.workflow.contracts import WorkflowCommandKind
    fail_attempt(research)
    owner = research.harness.command_service
    submit = owner.submit

    def race(request):
        submit(dataclasses.replace(request, command=WorkflowCommandKind.RECONCILE_RUN, node_id=None,
                                   idempotency_key="racing-command"))
        return submit(request)

    monkeypatch.setattr(owner, "submit", race)
    with server_operator_scope("human-operator", roles=("operator",)):
        with pytest.raises(ManagementError, match="run_version_conflict"):
            control().command(env.gateway, request(research, "retry_node", node_id="problem_understanding"),
                              request_id="raced-retry")
    assert research.harness.store.get_command_by_idempotency("run-test", "raced-retry") is None
    assert len(research.harness.store.list_attempts("run-test")) == 1


def test_metadata_uses_fixed_columns_without_loading_any_content(env, research, monkeypatch):
    human_refs = human_task(research)
    original, statements = research.harness.store.read, []

    class MetadataRepository:
        def __init__(self, repo):
            self.repo = repo

        def execute(self, sql, parameters=()):
            statements.append(sql)
            assert all(column not in sql.lower() for column in (
                "prompt_json", "input_snapshot_json", "decision_json", "problem_json", "select *", "count(*)"))
            cursor = self.repo.execute(sql, parameters)

            class MetadataCursor:
                def fetchone(self):
                    return cursor.fetchone()

                def __iter__(self):
                    return iter(cursor)

                def fetchall(self):
                    pytest.fail("directory metadata must stream, not materialize the full cursor")

            return MetadataCursor()

    monkeypatch.setattr(research.harness.store, "read", lambda callback: original(lambda repo: callback(MetadataRepository(repo))))
    result = control().read(env.gateway, human_refs)
    assert result["humanTaskTotal"] == 1 and len(statements) == 3


def test_human_pages_are_bounded_and_exact_without_repair(env, research):
    refs = human_task(research)

    def seed(uow):
        for index in range(5):
            uow.repository.insert_human_task(task_id=f"pending-{index}", run_id="run-human", node_run_id="attempt-human-a",
                handoff_id=None, task_kind="knowledge_gate", prompt_json='{"secret":"SECRET"}', created_at_ms=FIXED_NOW_MS)

    research.harness.store.submit(seed, force_flush=True).result(timeout=10)
    events = research.harness.store.list_events("run-human")
    seen, offset, revision, snapshot = [], 0, "", None
    while offset is not None:
        page = control().read(env.gateway, {**refs, "human_task_offset": offset, "limit": 2,
                                          "expected_revision": revision, "expected_snapshot": snapshot})
        revision = page["operation"]["revision"]
        if snapshot is not None:
            assert page["snapshot"] == snapshot
        snapshot = page["snapshot"]
        assert page["complete"] is True and page["humanTaskTotal"] == 6
        assert len(page["humanTasks"]) <= 2
        seen.extend(row["taskId"] for row in page["humanTasks"])
        offset = page["nextHumanTaskOffset"]
    assert seen == ["human-a", "pending-0", "pending-1", "pending-2", "pending-3", "pending-4"]
    assert research.harness.store.list_events("run-human") == events


def test_research_continuation_rejects_changed_revision_instead_of_skipping_resolved_tasks(env, research):
    refs = human_task(research)
    page = control().read(env.gateway, refs)
    revision = page["operation"]["revision"]
    with pytest.raises(ManagementError) as missing:
        control().read(env.gateway, {**refs, "human_task_offset": 1})
    assert missing.value.code == "INVALID_INPUT"
    with server_operator_scope("human-operator", roles=("operator",)):
        control().command(env.gateway, {**refs, "command": "resolve_human_task", "node_id": "protocol_freeze",
            "task_id": "human-a", "decision": "accept", "expected_revision": revision}, request_id="pagination-resolution")
    with pytest.raises(ManagementError) as changed:
        control().read(env.gateway, {**refs, "human_task_offset": 1, "expected_revision": revision,
                                    "expected_snapshot": page["snapshot"]})
    assert changed.value.code == "RESEARCH_REVISION_CHANGED"


def test_worker_human_insert_without_run_version_bump_invalidates_directory_snapshot(env, research):
    refs = human_task(research)

    def seed_second_page(uow):
        uow.repository.insert_human_task(task_id="zzz-existing-task", run_id="run-human", node_run_id="attempt-human-a",
            handoff_id=None, task_kind="knowledge_gate", prompt_json='{"secret":"SECRET"}', created_at_ms=FIXED_NOW_MS)

    research.harness.store.submit(seed_second_page, force_flush=True).result(timeout=10)
    first = control().read(env.gateway, {**refs, "limit": 1})
    assert first["nextHumanTaskOffset"] == 1
    before = research.harness.store.get_run("run-human")

    def worker_commit(uow):
        # AdapterDispatchWorker._commit_human uses this worker-side sequence
        # path, which deliberately does not bump the native command CAS version.
        sequence = uow.repository.advance_last_sequence("run-human", 1, FIXED_NOW_MS + 1)
        assert sequence == before.last_event_sequence + 1
        uow.repository.insert_human_task(task_id="000-worker-task", run_id="run-human", node_run_id="attempt-human-a",
            handoff_id=None, task_kind="knowledge_gate", prompt_json='{"secret":"SECRET worker prompt"}',
            created_at_ms=FIXED_NOW_MS + 1)

    research.harness.store.submit(worker_commit, force_flush=True).result(timeout=10)
    after = research.harness.store.get_run("run-human")
    assert after.run_version == before.run_version
    assert after.last_event_sequence == before.last_event_sequence + 1
    with pytest.raises(ManagementError) as changed:
        control().read(env.gateway, {**refs, "human_task_offset": 1, "limit": 1,
            "expected_revision": first["operation"]["revision"], "expected_snapshot": first["snapshot"]})
    assert changed.value.status_code == 409 and changed.value.code == "RESEARCH_SNAPSHOT_CHANGED"
    restarted = control().read(env.gateway, {**refs, "limit": 1})
    assert restarted["operation"]["revision"] == first["operation"]["revision"]
    assert restarted["snapshot"] != first["snapshot"]
    assert restarted["humanTasks"][0]["taskId"] == "000-worker-task"
    current_second = control().read(env.gateway, {**refs, "limit": 1, "human_task_offset": 1,
        "expected_revision": restarted["operation"]["revision"], "expected_snapshot": restarted["snapshot"]})
    # The unchanged numeric offset now repeats the old first-page task. Only
    # the directory snapshot detects the changed continuation interpretation.
    assert current_second["humanTasks"] == first["humanTasks"]
    assert "SECRET" not in json.dumps(restarted)


@pytest.mark.parametrize("change", ["same-total-human-directory", "off-page-latest-node"])
def test_snapshot_hashes_full_directory_even_without_version_or_sequence_change(env, research, change):
    refs = human_task(research)

    def seed(uow):
        uow.repository.insert_human_task(task_id="zzz-human", run_id="run-human", node_run_id="attempt-human-a",
            handoff_id=None, task_kind="knowledge_gate", prompt_json='{"secret":"SECRET"}', created_at_ms=FIXED_NOW_MS)
        uow.repository.insert_command(build_command_record(command_id="seed-later", run_id="run-human",
            node_id="zzz-node", idempotency_key="seed-later"))
        uow.repository.insert_attempt(build_attempt_record(node_run_id="attempt-later", run_id="run-human",
            node_id="zzz-node", command_id="seed-later", status="running"))

    research.harness.store.submit(seed, force_flush=True).result(timeout=10)
    first = control().read(env.gateway, {**refs, "limit": 1})
    before = research.harness.store.get_run("run-human")

    def mutate(uow):
        if change == "same-total-human-directory":
            uow.repository.execute("UPDATE human_tasks SET task_id=? WHERE task_id=?", ("000-replacement", "zzz-human"))
        else:
            uow.repository.update_attempt_status("attempt-later", "failed", FIXED_NOW_MS + 1)

    research.harness.store.submit(mutate, force_flush=True).result(timeout=10)
    after = research.harness.store.get_run("run-human")
    assert (before.run_version, before.last_event_sequence) == (after.run_version, after.last_event_sequence)
    current = control().read(env.gateway, {**refs, "limit": 1})
    assert (current["nodeTotal"], current["humanTaskTotal"]) == (first["nodeTotal"], first["humanTaskTotal"])
    assert current["snapshot"] != first["snapshot"]
    offset = "human_task_offset" if change == "same-total-human-directory" else "node_offset"
    with pytest.raises(ManagementError, match="RESEARCH_SNAPSHOT_CHANGED"):
        control().read(env.gateway, {**refs, offset: 1, "expected_revision": first["operation"]["revision"],
                                    "expected_snapshot": first["snapshot"]})


@pytest.mark.parametrize("extra", [
    {"human_task_offset": 1, "expected_revision": "1"},
    {"node_offset": 1, "expected_snapshot": "a" * 64},
    {"expected_snapshot": "A" * 64}, {"expected_snapshot": "a" * 63},
    {"expected_snapshot": True}, {"expected_snapshot": ["a" * 64]},
])
def test_research_snapshot_binding_is_strict_before_native_reads(env, research, extra, monkeypatch):
    monkeypatch.setattr(control(), "_store", lambda *_: pytest.fail("invalid query reached native owner"))
    with pytest.raises(ManagementError, match="INVALID_INPUT"):
        control().read(env.gateway, query(research, **extra))


def test_forged_or_foreign_snapshot_cannot_bind_even_the_first_page(env, research):
    refs = human_task(research)
    own = control().read(env.gateway, refs)
    foreign = control().read(env.gateway, query(research))
    assert own["snapshot"] != foreign["snapshot"]
    for snapshot in ("0" * 64, foreign["snapshot"]):
        with pytest.raises(ManagementError, match="RESEARCH_SNAPSHOT_CHANGED"):
            control().read(env.gateway, {**refs, "expected_snapshot": snapshot})


def test_unavailable_authority_never_becomes_an_empty_success(env, research, monkeypatch):
    from core.web.services.team_workflow.research_runtime import formal_read_runtime
    monkeypatch.setattr(formal_read_runtime, "get_formal_read_store", lambda: (_ for _ in ()).throw(OSError("SECRET")))
    with pytest.raises(ManagementError, match="RESEARCH_UNAVAILABLE"):
        control().read(env.gateway, query(research))


def test_missing_native_receipt_is_unknown_and_cannot_submit(env, research, monkeypatch):
    fail_attempt(research)
    monkeypatch.setattr(research.harness.command_service, "submit", lambda request: pytest.fail("receipt read wrote"))
    with server_operator_scope("human-operator", roles=("operator",)):
        with pytest.raises(ManagementError, match="OPERATION_UNCONFIRMED"):
            control().read_receipt(env.gateway, request(research, "retry_node", node_id="problem_understanding"),
                                   request_id="never-received")


@pytest.mark.parametrize("invalid", ["", "../forged", "bad key", "x" * 161])
def test_research_command_requires_out_of_band_bounded_key(env, research, invalid):
    fail_attempt(research)
    with server_operator_scope("human-operator", roles=("operator",)):
        with pytest.raises(ManagementError, match="INVALID_INPUT"):
            control().command(env.gateway, request(research, "retry_node", node_id="problem_understanding"), request_id=invalid)
    assert research.harness.store.get_run("run-test").run_version == 2


def checkpoint_files(folder):
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in folder.iterdir() if path.is_file()}


def test_checkpoint_identity_read_of_missing_path_does_not_create_anything(tmp_path):
    from core.research.workflow import checkpoint_store
    target = tmp_path / "missing" / "checkpoints.sqlite"
    assert checkpoint_store.read_latest_checkpoint_id(target, "run-a") == ""
    assert not target.parent.exists()


def test_checkpoint_identity_reads_real_native_checkpoint_without_setup_body_or_writes(tmp_path, monkeypatch):
    from core.research.workflow import checkpoint_store
    from core.web.services.team_workflow.research_runtime import checkpoint_lifecycle
    path = tmp_path / "checkpoints.sqlite"
    expected = checkpoint_lifecycle.prepare_initial_checkpoint(str(path), "run-a")
    checkpoint_lifecycle.prepare_initial_checkpoint(str(path), "other-run")
    before = checkpoint_files(tmp_path)
    monkeypatch.setattr(checkpoint_store, "open_sqlite_checkpointer", lambda *args: pytest.fail("write-capable saver used"))
    monkeypatch.setattr(checkpoint_lifecycle, "open_sqlite_checkpointer", lambda *args: pytest.fail("write-capable saver used"))
    assert checkpoint_store.read_latest_checkpoint_id(path, "run-a") == expected
    assert checkpoint_lifecycle.latest_checkpoint_metadata_id(str(path), "run-a") == expected
    assert checkpoint_files(tmp_path) == before


def test_checkpoint_identity_never_ignores_an_active_wal(tmp_path):
    import sqlite3
    from core.research.workflow import checkpoint_store
    from core.web.services.team_workflow.research_runtime import checkpoint_lifecycle
    path = tmp_path / "checkpoints.sqlite"
    checkpoint_lifecycle.prepare_initial_checkpoint(str(path), "run-a")
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE pending_change(value)")
        connection.commit()
        assert path.with_name(path.name + "-wal").exists()
        before = checkpoint_files(tmp_path)
        assert checkpoint_store.read_latest_checkpoint_id(path, "run-a") == ""
        assert checkpoint_files(tmp_path) == before
    finally:
        connection.close()


@pytest.fixture
def revise_checkpoint(env, research, tmp_path, monkeypatch):
    from core.web.services.team_workflow.research_runtime import checkpoint_lifecycle, formal_read_runtime
    from core.web.services.team_workflow.research_runtime.query_service import WorkflowQueryService
    refs = human_task(research)
    path = tmp_path / "checkpoints.sqlite"
    checkpoint_id = checkpoint_lifecycle.prepare_initial_checkpoint(str(path), "run-human")
    service = WorkflowQueryService(store=research.harness.store, readiness_service=research.harness.readiness,
        readiness_context=lambda: research.harness.context,
        revise_checkpoint_resolver=lambda thread: checkpoint_lifecycle.latest_checkpoint_metadata_id(str(path), thread))
    monkeypatch.setattr(formal_read_runtime, "get_query_service", lambda: service)
    return refs, checkpoint_id, service, path


def test_revise_real_native_fork_uses_scoped_readonly_checkpoint_identity(env, research, revise_checkpoint):
    refs, checkpoint_id, service, path = revise_checkpoint
    before = checkpoint_files(path.parent)
    with server_operator_scope("human-operator", roles=("operator",)):
        metadata = control().read(env.gateway, refs)
        task = metadata["humanTasks"][0]
        assert task["checkpointId"] == checkpoint_id and task["decisions"] == ["accept", "reject", "revise"]
        params = {**refs, "command": "resolve_human_task", "node_id": task["nodeId"], "task_id": task["taskId"],
                  "decision": "revise", "checkpoint_id": checkpoint_id, "expected_revision": "1"}
        result = control().command(env.gateway, params, request_id="revise-a")
        assert control().command(env.gateway, params, request_id="revise-a") == result
    children = research.harness.store.read(lambda repo: repo.execute(
        "SELECT run_id,active_node_id,forked_from_checkpoint_id FROM workflow_runs WHERE parent_run_id=?",
        ("run-human",)).fetchall())
    assert len(children) == 1 and children[0][1:] == ("protocol_freeze", checkpoint_id)
    assert result["receipt"]["checkpointId"] == checkpoint_id
    # Ledger writes are expected; the independent checkpoint owner stays unchanged.
    after = checkpoint_files(path.parent)
    assert after[path.name] == before[path.name]
    assert research.harness.store.read(lambda repo: repo.get_human_task("human-a"))[6] == "revised"


@pytest.mark.parametrize("change", ["wrong_task", "wrong_node", "wrong_team", "wrong_flow", "stale", "forged_checkpoint"])
def test_revise_checkpoint_ref_is_bound_to_exact_native_target(env, research, revise_checkpoint, change):
    refs, checkpoint_id, service, path = revise_checkpoint
    params = {**refs, "command": "resolve_human_task", "node_id": "protocol_freeze", "task_id": "human-a",
              "decision": "revise", "checkpoint_id": checkpoint_id, "expected_revision": "1"}
    updates = {"wrong_task": {"task_id": "unknown-task"}, "wrong_node": {"node_id": "smoke_gate"},
               "wrong_team": {"team_id": "other-team"}, "wrong_flow": {"flow_id": "other-flow"},
               "stale": {"expected_revision": "2"}, "forged_checkpoint": {"checkpoint_id": "forged-checkpoint"}}
    with server_operator_scope("human-operator", roles=("operator",)):
        with pytest.raises(ManagementError):
            control().command(env.gateway, {**params, **updates[change]}, request_id="bad-revise")
    assert research.harness.store.get_command_by_idempotency("run-human", "bad-revise") is None
    assert research.harness.store.read(lambda repo: repo.get_human_task("human-a"))[6] == "pending"


def test_checkpoint_identity_does_not_deserialize_checkpoint_body_or_read_foreign_namespace(tmp_path):
    import sqlite3
    from core.research.workflow import checkpoint_store
    from core.web.services.team_workflow.research_runtime import checkpoint_lifecycle
    path = tmp_path / "checkpoints.sqlite"
    expected = checkpoint_lifecycle.prepare_initial_checkpoint(str(path), "run-a")
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE checkpoints SET checkpoint=?", (b"SECRET deliberately invalid serialized body",))
        connection.execute("INSERT INTO checkpoints(thread_id,checkpoint_ns,checkpoint_id,type,checkpoint,metadata) "
            "SELECT thread_id,'foreign-branch','zzzz',type,checkpoint,metadata FROM checkpoints LIMIT 1")
    connection.close()
    before = checkpoint_files(tmp_path)
    assert checkpoint_store.read_latest_checkpoint_id(path, "run-a") == expected
    assert checkpoint_files(tmp_path) == before


def test_checkpoint_identity_rejects_linked_database_without_touching_target(tmp_path):
    from core.research.workflow import checkpoint_store
    from core.web.services.team_workflow.research_runtime import checkpoint_lifecycle
    target = tmp_path / "checkpoints.sqlite"
    checkpoint_lifecycle.prepare_initial_checkpoint(str(target), "run-a")
    link = tmp_path / "linked.sqlite"
    try:
        link.symlink_to(target)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symbolic-link privilege unavailable")
        raise
    before = checkpoint_files(tmp_path)
    assert checkpoint_store.read_latest_checkpoint_id(link, "run-a") == ""
    assert checkpoint_files(tmp_path) == before


def test_checkpoint_identity_rejects_database_changed_during_metadata_read(tmp_path, monkeypatch):
    import os
    from core.research.workflow import checkpoint_store
    from core.web.services.team_workflow.research_runtime import checkpoint_lifecycle
    path = tmp_path / "checkpoints.sqlite"
    checkpoint_lifecycle.prepare_initial_checkpoint(str(path), "run-a")
    original = checkpoint_store.sqlite3.connect

    class ChangedConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, params):
            result = self.connection.execute(sql, params)
            info = path.stat()
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
            return result

        def close(self):
            self.connection.close()

    monkeypatch.setattr(checkpoint_store.sqlite3, "connect", lambda *args, **kwargs: ChangedConnection(original(*args, **kwargs)))
    assert checkpoint_store.read_latest_checkpoint_id(path, "run-a") == ""


def test_revise_unavailable_checkpoint_does_not_disable_accept_reject(env, research, revise_checkpoint, monkeypatch):
    refs, checkpoint_id, service, path = revise_checkpoint
    monkeypatch.setattr(service, "_revise_checkpoint_resolver", lambda thread: "")
    with server_operator_scope("human-operator", roles=("operator",)):
        metadata = control().read(env.gateway, refs)
        assert metadata["humanTasks"][0]["decisions"] == ["accept", "reject"]
        with pytest.raises(ManagementError, match="COMMAND_UNAVAILABLE"):
            control().command(env.gateway, {**refs, "command": "resolve_human_task", "node_id": "protocol_freeze",
                "task_id": "human-a", "decision": "revise", "checkpoint_id": checkpoint_id,
                "expected_revision": "1"}, request_id="unavailable-revise")
        result = control().command(env.gateway, {**refs, "command": "resolve_human_task", "node_id": "protocol_freeze",
            "task_id": "human-a", "decision": "reject", "expected_revision": "1"}, request_id="available-reject")
        assert result["accepted"] is True
