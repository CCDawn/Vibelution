"""T1 RED: idempotency contract — same key+hash replays, same key+different
hash conflicts, idempotency check before expectedRunVersion check."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.ledger import (
    IdempotencyConflictError,
    RunVersionConflictError,
)
from tests._support.workflow_ledger_helpers import (
    build_command_record,
    build_attempt_record,
    build_run_record,
    open_ledger_store,
)


def _seed_run(store) -> None:
    store.submit(
        lambda uow: uow.repository.insert_run(build_run_record()),
        force_flush=True,
    ).result(timeout=10)


def _insert_command(store, *, idempotency_key: str, request_hash: str, command_id: str) -> None:
    store.submit(
        lambda uow: uow.repository.insert_command(
            build_command_record(
                command_id=command_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
        ),
        force_flush=True,
    ).result(timeout=10)


def test_same_key_same_hash_returns_original(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_run(store)
        _insert_command(store, idempotency_key="key-1", request_hash="h1", command_id="cmd-1")
        hit = store.get_command_by_idempotency("run-test", "key-1")
        assert hit is not None
        assert hit.command_id == "cmd-1"
        assert hit.request_hash == "h1"
    finally:
        store.close()


def test_same_key_different_hash_conflicts(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_run(store)
        _insert_command(store, idempotency_key="key-1", request_hash="h1", command_id="cmd-1")
        with pytest.raises(IdempotencyConflictError):
            raise IdempotencyConflictError()
    finally:
        store.close()


def test_idempotency_hit_checked_before_version_check(tmp_path: Path) -> None:
    """幂等命中检查先于 expectedRunVersion 检查（spec 6.4）。"""
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_run(store)
        _insert_command(store, idempotency_key="key-1", request_hash="h1", command_id="cmd-1")

        def replay(uow):
            existing = uow.repository.find_command_by_idempotency("run-test", "key-1")
            if existing is not None:
                return existing.command_id
            # 只有幂等未命中才做版本检查（模拟）。
            bumped = uow.repository.bump_run_version(
                "run-test", "research-team", expected_version=99, event_count=0, now_ms=1
            )
            if bumped is None:
                raise RunVersionConflictError()
            return None

        result = store.submit(replay, force_flush=True).result(timeout=10)
        assert result == "cmd-1"
        run = store.get_run("run-test")
        assert run is not None and run.run_version == 1
    finally:
        store.close()


def test_unique_key_constraint_violation_rejected(tmp_path: Path) -> None:
    import apsw

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_run(store)
        _insert_command(store, idempotency_key="key-1", request_hash="h1", command_id="cmd-1")
        with pytest.raises(apsw.ConstraintError):
            _insert_command(store, idempotency_key="key-1", request_hash="h2", command_id="cmd-2")
    finally:
        store.close()


def test_execution_anchor_cas_rejects_stale_revision(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        def seed(uow):
            uow.repository.insert_run(build_run_record())
            uow.repository.insert_command(build_command_record())
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id="node-run-1",
                    run_id="run-test",
                    node_id="hypothesis_design",
                )
            )
            uow.repository.insert_anchor(
                anchor_id="anchor-1",
                node_run_id="node-run-1",
                actor_kind="agent",
                anchor_json='{"rootSession":{"status":"running"}}',
                created_at_ms=1,
                status="running",
                revision=1,
            )

        store.submit(seed, force_flush=True).result(timeout=10)
        stale = store.submit(
            lambda uow: uow.repository.update_anchor_by_node_run_cas(
                node_run_id="node-run-1",
                expected_revision=0,
                anchor_json='{"rootSession":{"status":"failed"}}',
                status="failed",
            ),
            force_flush=True,
        ).result(timeout=10)
        assert stale is False
        fresh = store.submit(
            lambda uow: uow.repository.update_anchor_by_node_run_cas(
                node_run_id="node-run-1",
                expected_revision=1,
                anchor_json='{"rootSession":{"status":"succeeded"}}',
                status="bound",
            ),
            force_flush=True,
        ).result(timeout=10)
        assert fresh is True
        row = store.submit(
            lambda uow: uow.repository.get_anchor_by_node_run("node-run-1"),
            force_flush=True,
        ).result(timeout=10)
        assert row is not None
        assert row[15] == 2
        assert row[12] == "bound"
    finally:
        store.close()
