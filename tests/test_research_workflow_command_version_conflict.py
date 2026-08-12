"""T3 RED: version conflicts and not-ready rejection with zero side effects."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.ledger import RunVersionConflictError
from core.web.services.team_workflow.research_runtime.command_service import (
    NodeNotReadyError,
)
from tests._support.command_helpers import CommandHarness


def test_stale_expected_version_conflicts(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        with pytest.raises(RunVersionConflictError):
            harness.service.submit(harness.request(expected_run_version=2))
        # 拒绝不产生任何行。
        assert harness.store.latest_event_sequence("run-test") == 1
        assert harness.store.list_attempts("run-test") == []
        assert harness.store.list_pending_outbox("run-test") == []
        run = harness.store.get_run("run-test")
        assert run is not None and run.run_version == 1
    finally:
        harness.close()


def test_version_conflict_after_concurrent_accept(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))
        with pytest.raises(RunVersionConflictError):
            harness.service.submit(harness.request(idempotency_key="ui:key-2"))
    finally:
        harness.close()


def test_not_ready_node_rejected_without_side_effects(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        # SCI-096 无候选 -> source_extraction 不可执行。
        harness.context._candidate_stats = None
        with pytest.raises(NodeNotReadyError) as excinfo:
            harness.service.submit(
                harness.request(node_id="source_extraction", idempotency_key="ui:key-1")
            )
        readiness = excinfo.value.readiness
        assert readiness.ready is False
        assert any(b.code == "source_candidates_missing" for b in readiness.blockers)

        # 零副作用断言：无 attempt、无 outbox、无新 event、无新 command。
        assert harness.store.list_attempts("run-test") == []
        assert harness.store.list_pending_outbox("run-test") == []
        assert harness.store.latest_event_sequence("run-test") == 1
        assert harness.store.get_command_by_idempotency("run-test", "ui:key-1") is None
        run = harness.store.get_run("run-test")
        assert run is not None and run.run_version == 1
    finally:
        harness.close()


def test_ready_node_accepts_even_with_blocked_sibling(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.context._candidate_stats = None
        with pytest.raises(NodeNotReadyError):
            harness.service.submit(
                harness.request(node_id="source_extraction", idempotency_key="ui:key-1")
            )
        # 同一 run 的 source_finding 仍可执行。
        receipt = harness.service.submit(
            harness.request(node_id="source_finding", idempotency_key="ui:key-2")
        )
        assert receipt.accepted_run_version == 2
    finally:
        harness.close()


def test_run_version_conflict_surfaces_on_second_submit_after_replay(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))
        # 新 key 用旧版本 -> 冲突（幂等 key 不同，无法重放）。
        with pytest.raises(RunVersionConflictError):
            harness.service.submit(harness.request(idempotency_key="ui:key-new"))
    finally:
        harness.close()
