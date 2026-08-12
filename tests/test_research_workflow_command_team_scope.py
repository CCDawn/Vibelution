"""T3 RED: team scope — missing or mismatched teamId fails explicitly."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.web.services.team_workflow.research_runtime.command_service import (
    RunNotFoundError,
    TeamScopeMismatchError,
    WorkflowCommandError,
)
from tests._support.command_helpers import CommandHarness


def test_missing_team_id_rejected(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        request = harness.request(team_id="")
        with pytest.raises(TeamScopeMismatchError):
            harness.service.submit(request)
        assert harness.store.latest_event_sequence("run-test") == 1
    finally:
        harness.close()


def test_mismatched_team_id_rejected(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        request = harness.request(team_id="other-team")
        with pytest.raises(TeamScopeMismatchError):
            harness.service.submit(request)
        assert harness.store.latest_event_sequence("run-test") == 1
    finally:
        harness.close()


def test_unknown_run_rejected(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        with pytest.raises(RunNotFoundError):
            harness.service.submit(harness.request(run_id="run-nope"))
    finally:
        harness.close()


def test_human_task_outside_run_rejected(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-b")
        harness.service.submit(
            harness.request(run_id="run-b", idempotency_key="ui:key-1")
        )

        def create_task(uow):
            attempts = uow.repository.list_attempts("run-b")
            uow.repository.insert_human_task(
                task_id="ht-1",
                run_id="run-b",
                node_run_id=attempts[0].node_run_id,
                handoff_id=None,
                task_kind="knowledge_gate",
                prompt_json="{}",
                created_at_ms=1,
            )

        harness.store.submit(create_task, force_flush=True).result(timeout=10)

        # 在 run-test 上解析属于 run-b 的 task -> scope 显式失败。
        harness.seed_run(run_id="run-test")
        with pytest.raises(TeamScopeMismatchError):
            harness.service.submit(
                harness.request(
                    run_id="run-test",
                    command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                    node_id=None,
                    expected_run_version=1,
                    idempotency_key="ui:ht-1",
                    payload={"taskId": "ht-1", "decision": "accept"},
                )
            )
    finally:
        harness.close()


def test_resolve_human_task_accept_path(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))

        def create_task(uow):
            attempts = uow.repository.list_attempts("run-test")
            uow.repository.insert_human_task(
                task_id="ht-1",
                run_id="run-test",
                node_run_id=attempts[0].node_run_id,
                handoff_id=None,
                task_kind="knowledge_gate",
                prompt_json="{}",
                created_at_ms=1,
            )

        harness.store.submit(create_task, force_flush=True).result(timeout=10)

        receipt = harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                node_id=None,
                expected_run_version=2,
                idempotency_key="ui:ht-1",
                payload={"taskId": "ht-1", "decision": "accept", "reason": "ok"},
            )
        )
        assert receipt.accepted_run_version == 3

        def read(uow):
            return uow.repository.get_human_task("ht-1")

        row = harness.store.submit(read, force_flush=True).result(timeout=10)
        assert row is not None and row[6] == "accepted"
        attempts = harness.store.list_attempts("run-test")
        assert attempts[0].status == "succeeded"
    finally:
        harness.close()


def test_unknown_command_kind_rejected(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        with pytest.raises(WorkflowCommandError):
            harness.service.submit(
                harness.request(command=WorkflowCommandKind.FORK_REVISION)
            )
    finally:
        harness.close()
