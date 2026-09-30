"""Unit tests for the unified runtime task registry."""

from __future__ import annotations

import json
import threading

import pytest

from core.web.services import runtime_task_registry as registry


def _store(tmp_path, *, generations=None):
    def reader(session_id: str):
        if generations is None:
            return 0
        return generations.get(session_id)

    return registry.RuntimeTaskStore(tmp_path / "runtime_tasks", branch_generation_reader=reader)


def test_register_task_stamps_branch_generation_from_session(tmp_path):
    store = _store(tmp_path, generations={"session-a": 5})
    snapshot = store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CLI_AGENT,
            task_id="task-stamp-1",
            status="running",
            source_session_id="session-a",
        )
    )

    assert snapshot["branchGeneration"] == 5
    assert snapshot["branchGenerationStampSource"] == "session"
    persisted = store.load_state("task-stamp-1")
    assert persisted["branchGeneration"] == 5
    assert store.active_task_ids() == ["task-stamp-1"]


def test_register_task_always_stamps_int_even_when_session_missing(tmp_path):
    # The legacy escape hatch (branchGeneration None -> fencing disabled) is
    # gone: fresh registration must produce an integer stamp.
    store = _store(tmp_path, generations={"session-gone": None})
    unreadable = store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CHILD_SESSION,
            task_id="task-stamp-2",
            status="queued",
            source_session_id="session-gone",
        )
    )
    no_session = store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_RESEARCH_TASK,
            task_id="task-stamp-3",
            status="queued",
            source_session_id="",
        )
    )

    assert unreadable["branchGeneration"] == 0
    assert unreadable["branchGenerationStampSource"] == "reader_error_default_zero"
    assert no_session["branchGeneration"] == 0
    assert no_session["branchGenerationStampSource"] == "no_session_default_zero"
    assert isinstance(store.load_state("task-stamp-2")["branchGeneration"], int)


def test_explicit_branch_generation_wins_over_reader(tmp_path):
    store = _store(tmp_path, generations={"session-a": 7})
    snapshot = store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CHILD_SESSION,
            task_id="task-stamp-4",
            status="queued",
            source_session_id="session-a",
            branch_generation=3,
        )
    )

    assert snapshot["branchGeneration"] == 3
    assert snapshot["branchGenerationStampSource"] == "explicit"


def test_completion_fencing_drops_stale_generation(tmp_path):
    store = _store(tmp_path, generations={"session-a": 2})
    store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CLI_AGENT,
            task_id="task-fence-1",
            status="running",
            source_session_id="session-a",
        )
    )
    # Session forked/rewound: generation moved on while the task ran.
    store._branch_generation_reader = lambda _session_id: 3

    allowed, audit = store.evaluate_completion_fencing(store.load_state("task-fence-1"))

    assert allowed is False
    assert audit["fencingDecision"] == registry.FENCING_DECISION_DROPPED
    assert audit["fencingReason"] == "stale_branch_generation"
    assert audit["fencingTaskBranchGeneration"] == 2
    assert audit["fencingCurrentBranchGeneration"] == 3
    assert audit["fencingAuditedAt"]


def test_completion_fencing_allows_matching_generation_and_audits(tmp_path):
    store = _store(tmp_path, generations={"session-a": 2})
    store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CLI_AGENT,
            task_id="task-fence-2",
            status="running",
            source_session_id="session-a",
        )
    )

    allowed, audit = store.evaluate_completion_fencing(store.load_state("task-fence-2"))

    assert allowed is True
    assert audit["fencingDecision"] == registry.FENCING_DECISION_ALLOWED
    assert audit["fencingReason"] == "generation_match"
    assert audit["fencingCurrentBranchGeneration"] == 2


def test_completion_fencing_fails_open_for_legacy_and_unreadable(tmp_path):
    store = _store(tmp_path, generations={})
    legacy = store.save_state(
        {
            "kind": registry.KIND_CLI_AGENT,
            "taskId": "task-fence-3",
            "status": "running",
            "sourceSessionId": "session-a",
            # Legacy row written before mandatory stamping.
            "branchGeneration": None,
        }
    )
    allowed_legacy, legacy_audit = store.evaluate_completion_fencing(legacy)
    assert allowed_legacy is True
    assert legacy_audit["fencingReason"] == "legacy_unstamped_fail_open"

    store._branch_generation_reader = lambda _session_id: None
    stamped = store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_RESEARCH_TASK,
            task_id="task-fence-5",
            status="running",
            source_session_id="session-b",
            branch_generation=1,
        )
    )
    allowed_unreadable, unreadable_audit = store.evaluate_completion_fencing(stamped)
    assert allowed_unreadable is True
    assert unreadable_audit["fencingReason"] == "generation_unreadable_fail_open"


def test_completion_fencing_without_target_session_is_allowed(tmp_path):
    store = _store(tmp_path, generations={})
    state = store.save_state(
        {
            "kind": registry.KIND_RESEARCH_TASK,
            "taskId": "task-fence-4",
            "status": "running",
            "sourceSessionId": "",
            "branchGeneration": 4,
            "branchGenerationStampSource": "no_session_default_zero",
        }
    )

    allowed, audit = store.evaluate_completion_fencing(state)

    assert allowed is True
    assert audit["fencingReason"] == "no_target_session"


def test_mailbox_queues_and_drains_in_order(tmp_path):
    store = _store(tmp_path)
    store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CLI_AGENT,
            task_id="task-mail-1",
            status="running",
            source_session_id="",
        )
    )

    first = store.queue_message("task-mail-1", message="先看这条", origin="coordinator")
    second = store.queue_message("task-mail-1", message="再看这条", message_id="fixed-id")
    assert first["pendingMessages"][0]["id"] and first["pendingMessages"][0]["queuedAt"]
    assert second["pendingMessages"][-1]["id"] == "fixed-id"

    drained = store.drain_messages("task-mail-1")
    assert [item["message"] for item in drained] == ["先看这条", "再看这条"]
    assert store.drain_messages("task-mail-1") == []
    assert store.load_state("task-mail-1")["pendingMessages"] == []


def test_mailbox_rejects_empty_message_and_missing_task(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(ValueError):
        store.queue_message("task-mail-2", message="   ")
    assert store.queue_message("task-mail-missing", message="hello") is None


def test_mailbox_is_bounded(tmp_path):
    store = _store(tmp_path)
    store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CLI_AGENT,
            task_id="task-mail-3",
            status="running",
            source_session_id="",
        )
    )
    for index in range(registry.MAX_PENDING_MESSAGES + 25):
        store.queue_message("task-mail-3", message=f"m{index}")

    pending = store.load_state("task-mail-3")["pendingMessages"]
    assert len(pending) == registry.MAX_PENDING_MESSAGES
    assert pending[0]["message"] == "m25"


def test_terminal_update_leaves_active_index_and_notifies_waiter(tmp_path):
    store = _store(tmp_path)
    store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CHILD_SESSION,
            task_id="child-term-1",
            status="queued",
            source_session_id="",
        )
    )
    assert store.active_task_ids() == ["child-term-1"]
    assert store.has_active_tasks() is True

    terminal = store.mark_task_terminal("child-term-1", status="completed", reason="child_session_return")

    assert terminal["status"] == "completed"
    assert terminal["completedAt"]
    assert store.active_task_ids() == []
    assert store.has_active_tasks() is False
    assert store.wait_for_terminal("child-term-1", timeout_seconds=0.1)["status"] == "completed"


def test_wait_for_terminal_unblocks_when_saved_terminal(tmp_path):
    store = _store(tmp_path)
    store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CLI_AGENT,
            task_id="task-wait-1",
            status="running",
            source_session_id="",
        )
    )

    def finish_later():
        store.mark_task_terminal("task-wait-1", status="timeout")

    thread = threading.Thread(target=finish_later, daemon=True)
    thread.start()
    state = store.wait_for_terminal("task-wait-1", timeout_seconds=2.0)
    thread.join(timeout=2.0)

    assert state is not None and state["status"] == "timeout"


def test_reconcile_index_adopts_legacy_active_snapshot(tmp_path):
    store = _store(tmp_path)
    legacy_path = store.task_state_path("legacy-task-1")
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "taskId": "legacy-task-1",
                "status": "running",
                "terminalSessionId": "legacy-term",
                "sourceSessionId": "",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert store.active_task_ids() == []

    states = store.reconcile_index()

    assert [state["taskId"] for state in states] == ["legacy-task-1"]
    assert store.active_task_ids() == ["legacy-task-1"]
    # Legacy rows stay unstamped: fencing fails open for in-flight legacy work.
    assert store.load_state("legacy-task-1")["branchGeneration"] is None


def test_iter_task_states_skips_index_and_lock_files(tmp_path):
    store = _store(tmp_path)
    store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CLI_AGENT,
            task_id="task-scan-1",
            status="failed",
            source_session_id="",
        )
    )
    (store.root / "_index.json").write_text("{}", encoding="utf-8")

    states = store.iter_task_states()

    assert [state["taskId"] for state in states] == ["task-scan-1"]


def test_active_task_states_reuses_mtime_cache_until_file_changes(tmp_path):
    store = _store(tmp_path)
    store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CLI_AGENT,
            task_id="task-cache-1",
            status="running",
            source_session_id="",
        )
    )
    cache: dict[str, tuple[float, dict]] = {}

    first = store.active_task_states(mtime_cache=cache)
    second = store.active_task_states(mtime_cache=cache)

    assert first and second
    # Same mtime -> the cached parsed object is reused without re-reading.
    assert second[0] is cache[str(store.task_state_path("task-cache-1"))][1]

    store.mark_task_terminal("task-cache-1", status="completed")
    assert store.active_task_states(mtime_cache=cache) == []
    # Cache entries for finished tasks are pruned.
    assert str(store.task_state_path("task-cache-1")) not in cache


def test_concurrent_read_modify_write_keeps_snapshot_consistent(tmp_path):
    store = _store(tmp_path)
    store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_RESEARCH_TASK,
            task_id="task-rmw-1",
            status="running",
            source_session_id="",
        )
    )
    threads = []
    errors: list[Exception] = []

    def bump():
        try:
            for _ in range(15):
                store.update_task(
                    "task-rmw-1",
                    lambda snapshot: {**snapshot, "output": str(int(snapshot.get("output") or 0) + 1)},
                )
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    for _ in range(8):
        thread = threading.Thread(target=bump, daemon=True)
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert store.load_state("task-rmw-1")["output"] == "120"
    payload = json.loads(store.task_state_path("task-rmw-1").read_text(encoding="utf-8"))
    assert payload["output"] == "120"


def test_request_stop_records_initiator_and_rejects_unknown(tmp_path):
    store = _store(tmp_path)
    store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CLI_AGENT,
            task_id="task-stop-1",
            status="running",
            source_session_id="",
        )
    )

    state = store.request_stop("task-stop-1", "user")
    assert state["stopInitiator"] == "user"
    assert state["stopRequestedAt"]

    with pytest.raises(ValueError):
        store.request_stop("task-stop-1", "robot")
    # Terminal tasks are not re-armed.
    store.mark_task_terminal("task-stop-1", status="stopped", stop_initiator="model")
    assert store.request_stop("task-stop-1", "model") is None


def test_normalize_snapshot_adopts_legacy_rows_as_cli_agent():
    normalized = registry.normalize_snapshot({"taskId": "legacy", "status": "RUNNING"})

    assert normalized["kind"] == registry.KIND_CLI_AGENT
    assert normalized["status"] == "running"
    assert normalized["pendingMessages"] == []
    assert normalized["stopInitiator"] is None
    assert normalized["branchGeneration"] is None


def test_new_snapshot_rejects_unknown_kind():
    with pytest.raises(ValueError):
        registry.new_snapshot(kind="mystery", task_id="t", status="queued")


def test_seal_and_request_stop_seals_idempotently_with_cascade_audit(tmp_path):
    store = _store(tmp_path)
    store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CHILD_SESSION,
            task_id="child-seal-1",
            status="running",
            source_session_id="",
        )
    )

    first = store.seal_and_request_stop(
        "child-seal-1",
        reason=registry.SEAL_REASON_PARENT_TURN_CANCELLED,
        turn_id="turn-1",
        cascaded_from="root-session",
    )
    second = store.seal_and_request_stop(
        "child-seal-1",
        reason="later_attempt",
        turn_id="turn-2",
        cascaded_from="other-session",
    )

    assert first["notificationSealed"] is True
    assert first["notificationSealedReason"] == registry.SEAL_REASON_PARENT_TURN_CANCELLED
    assert first["notificationSealedByTurnId"] == "turn-1"
    assert first["stopInitiator"] == "user"
    assert first["cascadeStop"]["cascadedFrom"] == "root-session"
    # Keep-first: the second seal neither moves the audit nor re-arms the stop.
    assert second["notificationSealedAt"] == first["notificationSealedAt"]
    assert second["notificationSealedReason"] == registry.SEAL_REASON_PARENT_TURN_CANCELLED
    assert second["cascadeStop"]["cascadedFrom"] == "root-session"
    assert store.is_notification_sealed("child-seal-1") is True
    assert store.is_notification_sealed("task-never-sealed") is False

    with pytest.raises(ValueError):
        store.seal_and_request_stop("child-seal-1", reason="")


def test_seal_lands_on_terminal_task_without_rearming_stop(tmp_path):
    store = _store(tmp_path)
    store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CLI_AGENT,
            task_id="task-seal-term-1",
            status="running",
            source_session_id="",
        )
    )
    store.mark_task_terminal("task-seal-term-1", status="completed", stop_initiator="model")

    state = store.seal_and_request_stop(
        "task-seal-term-1",
        reason=registry.SEAL_REASON_PARENT_TURN_CANCELLED,
    )

    assert state["notificationSealed"] is True
    # A settled task keeps its original terminal outcome and initiator.
    assert state["status"] == "completed"
    assert state["stopInitiator"] == "model"


def test_collect_cascade_targets_walks_two_levels_breaks_cycles_and_caps_depth(tmp_path):
    store = _store(tmp_path)

    def register(task_id, *, parent, kind):
        store.register_task(
            registry.new_snapshot(
                kind=kind,
                task_id=task_id,
                status="running",
                source_session_id="",
                parent_session_id=parent,
            )
        )

    # Two-level tree under the root: child session + cli task, and a
    # grandchild cli task spawned by the child session.
    register("child-1", parent="root", kind=registry.KIND_CHILD_SESSION)
    register("cli-1", parent="root", kind=registry.KIND_CLI_AGENT)
    register("cli-2", parent="child-1", kind=registry.KIND_CLI_AGENT)
    # Corrupted cycle: two child-session tasks that are each other's parent.
    register("SA", parent="SB", kind=registry.KIND_CHILD_SESSION)
    register("SB", parent="SA", kind=registry.KIND_CHILD_SESSION)
    # Deep chain beyond the default cap.
    register("chain-1", parent="root", kind=registry.KIND_CHILD_SESSION)
    register("chain-2", parent="chain-1", kind=registry.KIND_CHILD_SESSION)
    register("chain-3", parent="chain-2", kind=registry.KIND_CHILD_SESSION)
    register("chain-4", parent="chain-3", kind=registry.KIND_CHILD_SESSION)

    targets = store.collect_cascade_targets("root", max_depth=3)

    assert [state["taskId"] for state in targets] == [
        "child-1",
        "cli-1",
        "chain-1",
        "cli-2",
        "chain-2",
        "chain-3",
    ]
    assert [state["cascadeDepth"] for state in targets] == [0, 0, 0, 1, 1, 2]
    # Terminal tasks never join the cascade.
    store.mark_task_terminal("cli-1", status="completed")
    remaining = store.collect_cascade_targets("root", max_depth=3)
    assert "cli-1" not in [state["taskId"] for state in remaining]
    assert store.collect_cascade_targets("") == []
    assert store.collect_cascade_targets("root", max_depth=0) == []
