"""T3 RED: command transaction — command/status/outbox/event committed
together; crash injection never leaves a half commit."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.web.routes.team_workflows.research_runtime import _map_node_not_ready_error
from core.research.workflow.contracts import WorkflowCommandKind
from core.web.services.team_workflow.research_runtime.command_service import NodeNotReadyError
from tests._support.command_helpers import CommandHarness


def test_start_node_commits_command_attempt_outbox_events(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        request = harness.request()
        receipt = harness.service.submit(request)

        assert receipt.status == "accepted"
        assert receipt.accepted_run_version == 2
        assert receipt.latest_event_sequence == 3

        run = harness.store.get_run("run-test")
        assert run is not None
        assert run.run_version == 2
        assert run.status == "running"
        assert run.active_node_id == "source_finding"

        attempts = harness.store.list_attempts("run-test")
        assert len(attempts) == 1
        attempt = attempts[0]
        assert attempt.status == "starting"
        assert attempt.node_id == "source_finding"
        assert attempt.actor_kind == "agent"
        assert attempt.attempt == 1
        assert attempt.command_id == receipt.command_id

        outbox = harness.store.list_pending_outbox("run-test")
        assert len(outbox) == 1
        assert outbox[0].action_kind == "graph_dispatch"
        assert outbox[0].command_id == receipt.command_id
        assert outbox[0].node_run_id == attempt.node_run_id

        events = harness.store.list_events("run-test")
        assert [event.event_type for event in events] == [
            "run_created",
            "command_accepted",
            "node_starting",
        ]
        assert harness.wake_count == 1
    finally:
        harness.close()


def test_start_node_records_definition_actor_kind(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(
            harness.request(node_id="source_finding", idempotency_key="ui:agent")
        )
        agent = harness.store.latest_attempt("run-test", "source_finding")
        assert agent is not None and agent.actor_kind == "agent"

        harness.service.submit(
            harness.request(
                node_id="smoke_gate",
                expected_run_version=2,
                idempotency_key="ui:human",
            )
        )
        human = harness.store.latest_attempt("run-test", "smoke_gate")
        assert human is not None and human.actor_kind == "human"

        harness.service.submit(
            harness.request(
                node_id="controlled_run",
                expected_run_version=3,
                idempotency_key="ui:system",
            )
        )
        system = harness.store.latest_attempt("run-test", "controlled_run")
        assert system is not None and system.actor_kind == "system"
    finally:
        harness.close()


def test_command_transaction_crash_injection_rolls_back_everything(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        request = harness.request()

        def crash_after_writes(uow, req, request_hash):
            from core.web.services.team_workflow.research_runtime.command_service import (
                _attempt_record,
                _bump,
                _command_record,
            )

            from core.web.services.team_workflow.research_runtime.ids import new_id

            now_ms = 1
            bumped = _bump(uow, req, event_count=2, now_ms=now_ms)
            accepted_version, sequence = bumped
            command_id = new_id("cmd")
            uow.repository.insert_command(
                _command_record(
                    command_id=command_id,
                    request=req,
                    request_hash=request_hash,
                    accepted_run_version=accepted_version,
                    now_ms=now_ms,
                )
            )
            uow.repository.insert_attempt(
                _attempt_record(
                    node_run_id="nr-crash",
                    run_id=req.run_id,
                    node_id="source_finding",
                    attempt=1,
                    status="starting",
                    command_id=command_id,
                    input_snapshot_hash="a" * 64,
                    started_at_ms=now_ms,
                )
            )
            raise RuntimeError("simulated crash before commit")

        import json

        from core.research.workflow.contracts import CommandReceipt

        # 通过 service 的事务通道注入 crash：完整路径不可行，直接驱动 writer。
        from core.research.workflow.ledger import RunVersionConflictError

        def simulate(uow):
            crash_after_writes(uow, request, "h" * 64)
            return None

        import pytest

        with pytest.raises(RuntimeError):
            harness.store.submit(simulate, force_flush=True).result(timeout=10)

        run = harness.store.get_run("run-test")
        assert run is not None and run.run_version == 1
        assert harness.store.list_attempts("run-test") == []
        assert harness.store.list_pending_outbox("run-test") == []
        assert harness.store.latest_event_sequence("run-test") == 1
    finally:
        harness.close()


def test_double_click_creates_exactly_one_attempt(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        request = harness.request()
        first = harness.service.submit(request)
        second = harness.service.submit(request)
        assert first.command_id == second.command_id
        assert first.accepted_run_version == second.accepted_run_version
        assert len(harness.store.list_attempts("run-test")) == 1
        assert harness.store.latest_event_sequence("run-test") == 3
    finally:
        harness.close()


def test_live_attempt_blocks_second_start(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        request = harness.request(idempotency_key="ui:key-1")
        harness.service.submit(request)

        import pytest

        from core.web.services.team_workflow.research_runtime.command_service import (
            NodeNotReadyError,
        )

        with pytest.raises(NodeNotReadyError) as excinfo:
            harness.service.submit(
                harness.request(idempotency_key="ui:key-2", expected_run_version=2)
            )
        assert any(b.code == "node_live_attempt" for b in excinfo.value.readiness.blockers)
        # 拒绝零副作用。
        assert len(harness.store.list_attempts("run-test")) == 1
        assert harness.store.latest_event_sequence("run-test") == 3
    finally:
        harness.close()


def test_node_not_ready_http_detail_preserves_structured_blockers() -> None:
    readiness = SimpleNamespace(
        blockers=(
            SimpleNamespace(
                to_dict=lambda: {
                    "code": "node_live_attempt",
                    "title": "已有运行中的尝试",
                    "detail": "请等待当前尝试结束",
                    "category": "execution",
                }
            ),
            SimpleNamespace(
                to_dict=lambda: {
                    "code": "source_candidates_missing",
                    "title": "缺少候选材料",
                    "detail": "先补齐候选材料",
                    "category": "dependency",
                }
            ),
        )
    )

    mapped = _map_node_not_ready_error(NodeNotReadyError(readiness, 7))

    assert mapped.status_code == 412
    assert mapped.detail == {
        "code": "node_not_ready",
        "message": "node_not_ready",
        "blockers": [
            {
                "code": "node_live_attempt",
                "title": "已有运行中的尝试",
                "detail": "请等待当前尝试结束",
                "category": "execution",
            },
            {
                "code": "source_candidates_missing",
                "title": "缺少候选材料",
                "detail": "先补齐候选材料",
                "category": "dependency",
            },
        ],
    }


def test_retry_creates_new_attempt_with_retry_lineage(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))

        def fail_first(uow):
            attempts = uow.repository.list_attempts("run-test")
            uow.repository.update_attempt_status(
                attempts[0].node_run_id, "failed", 2, finished_at_ms=2
            )

        harness.store.submit(fail_first, force_flush=True).result(timeout=10)

        request = harness.request(
            command=WorkflowCommandKind.RETRY_NODE,
            expected_run_version=2,
            idempotency_key="ui:key-2",
        )
        receipt = harness.service.submit(request)
        assert receipt.accepted_run_version == 3

        attempts = harness.store.list_attempts("run-test")
        assert len(attempts) == 2
        assert {attempt.attempt for attempt in attempts} == {1, 2}
        retry = next(attempt for attempt in attempts if attempt.attempt == 2)
        original = next(attempt for attempt in attempts if attempt.attempt == 1)
        assert retry.retry_of_node_run_id == original.node_run_id
        assert original.status == "stale"
    finally:
        harness.close()
