"""Post-run delivery orchestration: evidence index -> projection -> export -> PDF.

The chain runs as a decoupled outbox worker after ``sync_run_succeeded`` closes
the run. The run stays ``succeeded``; delivery outcomes land as
``delivery_orchestration_*`` events plus one ``delivery_orchestration_result``
artifact. Preview export success closes the chain; formal stays fail-closed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.web.services.team_workflow import challenge_question_runs
from core.web.services.team_workflow.research_runtime import (
    delivery_orchestration,
    workflow_artifact_store,
)
from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
    load_scoped_artifact_payload,
)
from core.web.services.team_workflow.research_runtime.delivery_orchestration import (
    DELIVERY_ARTIFACT_KIND,
    DELIVERY_OUTBOX_KIND,
    delivery_idempotency_key,
)
from core.web.services.team_workflow.research_runtime.delivery_worker import (
    DeliveryOrchestrationWorker,
)
from tests._support.graph_helpers import GraphHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_outbox_record,
)

PDF_LIMIT = 20 * 1024 * 1024


@pytest.fixture()
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        challenge_question_runs,
        "challenge_question_run_summary",
        lambda team_id: {
            "completedQuestionIds": ["SCI-001", "SCI-002", "SCI-003"],
            "approvedDeepExperimentQuestionIds": [],
        },
    )
    graph = GraphHarness(tmp_path)
    clock = [FIXED_NOW_MS + 5000]
    worker = DeliveryOrchestrationWorker(
        store=graph.commands.store,
        owner_id="delivery-worker-test",
        now_provider=lambda: clock[0],
    )
    try:
        yield graph, worker, clock
    finally:
        graph.close()


def _seed_succeeded_package(graph: GraphHarness, run_id: str) -> None:
    def mutate(uow):
        uow.repository.execute(
            "UPDATE workflow_runs SET active_node_id = ? WHERE run_id = ?",
            ("result_package", run_id),
        )
        uow.repository.insert_command(
            build_command_record(
                command_id=f"cmd-{run_id}",
                run_id=run_id,
                node_id="result_package",
                command_kind="retry_node",
                idempotency_key=f"retry:result_package:{run_id}",
            )
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=f"nr-{run_id}-result_package-a2",
                run_id=run_id,
                node_id="result_package",
                attempt=2,
                actor_kind="system",
                status="succeeded",
                command_id=f"cmd-{run_id}",
                started_at_ms=FIXED_NOW_MS,
            )
        )

    graph.commands.store.submit(mutate, force_flush=True).result(timeout=10)


def _set_input_snapshot(graph: GraphHarness, run_id: str, snapshot: dict) -> None:
    def mutate(uow):
        uow.repository.execute(
            "UPDATE workflow_runs SET input_snapshot_json = ? WHERE run_id = ?",
            (json.dumps(snapshot, ensure_ascii=False), run_id),
        )

    graph.commands.store.submit(mutate, force_flush=True).result(timeout=10)


def _close_run(graph: GraphHarness, run_id: str) -> None:
    graph.seed(run_id=run_id, status="running")
    _seed_succeeded_package(graph, run_id)
    assert graph.worker.run_once() >= 1
    run = graph.commands.store.get_run(run_id)
    assert run is not None and run.status == "succeeded"


def _delivery_events(graph: GraphHarness, run_id: str) -> list[dict]:
    events = graph.commands.store.list_events(run_id)
    out = []
    for event in events:
        if event.event_type.startswith("delivery_orchestration_"):
            out.append(
                {
                    "type": event.event_type,
                    "payload": json.loads(event.payload_json),
                }
            )
    return out


def _outbox_row(graph: GraphHarness, run_id: str) -> dict | None:
    def query(uow):
        return uow.repository.execute(
            "SELECT status, attempt_count, last_problem_json FROM outbox_actions "
            "WHERE run_id = ? AND action_kind = ?",
            (run_id, DELIVERY_OUTBOX_KIND),
        ).fetchall()

    rows = graph.commands.store.submit(query, force_flush=True).result(timeout=10)
    if not rows:
        return None
    status, attempts, problem = rows[0]
    return {
        "status": status,
        "attempts": attempts,
        "problem": json.loads(problem) if problem else None,
    }


def test_run_close_enqueues_and_completes_delivery(harness) -> None:
    graph, worker, _clock = harness
    run_id = "run-delivery-ok"
    _close_run(graph, run_id)

    pending = graph.commands.store.list_pending_outbox(run_id)
    delivery = [r for r in pending if r.action_kind == DELIVERY_OUTBOX_KIND]
    assert len(delivery) == 1
    assert delivery[0].idempotency_key == delivery_idempotency_key(run_id)

    assert worker.run_once() == 1

    run = graph.commands.store.get_run(run_id)
    assert run is not None and run.status == "succeeded"

    events = _delivery_events(graph, run_id)
    assert [item["type"] for item in events] == ["delivery_orchestration_completed"]
    payload = events[0]["payload"]
    assert payload["deliveryStatus"] == "succeeded"
    assert payload["nodeId"] == "result_package"
    assert payload["previewPackStatus"] == "preview"
    assert payload["approvedQuestionCount"] == 3
    # DEV gates are not attested: formal stays refused but diagnosable.
    assert "catalog_incomplete" in payload["formalBlockers"]
    assert "r0_not_pass" in payload["formalBlockers"]
    assert payload["pdfCheck"]["withinLimit"] is True
    assert payload["artifactRef"].startswith(
        f"{DELIVERY_ARTIFACT_KIND}://research-team/"
    )

    envelope = load_scoped_artifact_payload(
        DELIVERY_ARTIFACT_KIND,
        team_id="research-team",
        authority_run_id=run_id,
        workflow_run_id=run_id,
    )
    assert envelope is not None
    body = envelope["payload"]
    assert body["deliveryStatus"] == "succeeded"
    assert body["steps"]["previewPack"]["status"] == "preview"
    assert body["steps"]["formalPack"]["status"] == "refused"
    assert body["steps"]["submissionProjection"]["allowedPackMode"] == "preview"

    row = _outbox_row(graph, run_id)
    assert row is not None and row["status"] == "succeeded"

    # The event survives the typed replay path that feeds the UI timeline API.
    from core.web.services.team_workflow.research_runtime.event_replay_service import (
        WorkflowEventReplayService,
    )

    page = WorkflowEventReplayService(store=graph.commands.store).list_events(
        team_id="research-team", run_id=run_id
    )
    replayed = [item for item in page.to_dict()["events"] if item["type"].startswith("delivery_")]
    assert [item["type"] for item in replayed] == ["delivery_orchestration_completed"]
    assert replayed[0]["payload"]["deliveryStatus"] == "succeeded"

    # Re-driving both workers is a no-op: run already terminal, action acked.
    assert graph.worker.run_once() >= 0
    assert worker.run_once() == 0
    assert len(_delivery_events(graph, run_id)) == 1


def test_delivery_blocked_when_pdf_over_limit(harness) -> None:
    graph, worker, _clock = harness
    run_id = "run-delivery-pdf"
    graph.seed(run_id=run_id, status="running")
    _set_input_snapshot(
        graph,
        run_id,
        {
            "teamId": "research-team",
            "deliveryRequest": {"deliveryPdfSizeBytes": PDF_LIMIT + 1},
        },
    )
    _seed_succeeded_package(graph, run_id)
    assert graph.worker.run_once() >= 1

    assert worker.run_once() == 1

    run = graph.commands.store.get_run(run_id)
    assert run is not None and run.status == "succeeded"

    events = _delivery_events(graph, run_id)
    assert [item["type"] for item in events] == ["delivery_orchestration_blocked"]
    payload = events[0]["payload"]
    assert payload["deliveryStatus"] == "blocked"
    assert payload["code"] == "pdf_limit_exceeded"
    assert payload["pdfCheck"]["withinLimit"] is False
    assert payload["pdfCheck"]["sizeBytes"] == PDF_LIMIT + 1
    # Preview still exported: the chain closes with a diagnosable block.
    assert payload["previewPackStatus"] == "preview"
    assert payload["artifactRef"]

    row = _outbox_row(graph, run_id)
    assert row is not None and row["status"] == "succeeded"


def test_delivery_failed_on_unsafe_evidence_path(harness) -> None:
    graph, worker, _clock = harness
    run_id = "run-delivery-escape"
    graph.seed(run_id=run_id, status="running")
    _set_input_snapshot(
        graph,
        run_id,
        {
            "teamId": "research-team",
            "deliveryRequest": {
                "extraEvidence": [{"path": "../escape.txt", "kind": "notes"}]
            },
        },
    )
    _seed_succeeded_package(graph, run_id)
    assert graph.worker.run_once() >= 1

    assert worker.run_once() == 1

    run = graph.commands.store.get_run(run_id)
    assert run is not None and run.status == "succeeded"

    events = _delivery_events(graph, run_id)
    assert [item["type"] for item in events] == ["delivery_orchestration_failed"]
    payload = events[0]["payload"]
    assert payload["deliveryStatus"] == "failed"
    assert payload["code"] == "evidence_path_unsafe"
    assert payload["failedStep"] == "evidence_index"
    assert "../escape.txt" in payload["detail"]

    row = _outbox_row(graph, run_id)
    assert row is not None and row["status"] == "failed"
    assert row["problem"]["code"] == "evidence_path_unsafe"

    # Permanent failure is never retried.
    assert worker.run_once() == 0


def test_delivery_fail_closed_when_program_state_unreadable(
    harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, worker, _clock = harness

    def _boom(team_id: str):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(
        challenge_question_runs, "challenge_question_run_summary", _boom
    )
    run_id = "run-delivery-degraded"
    _close_run(graph, run_id)

    assert worker.run_once() == 1

    events = _delivery_events(graph, run_id)
    assert [item["type"] for item in events] == ["delivery_orchestration_completed"]
    payload = events[0]["payload"]
    # Unknown program state never counts toward formal completion.
    assert payload["approvedQuestionCount"] == 0
    assert "catalog_incomplete" in payload["formalBlockers"]
    assert any(
        item.startswith("program_projection_unavailable")
        for item in payload["diagnostics"]
    )


def test_transient_error_retries_then_fails_diagnosably(harness) -> None:
    graph, worker, clock = harness
    run_id = "run-delivery-transient"
    _close_run(graph, run_id)

    def _boom(entries):
        raise RuntimeError("ledger read flake")

    original = delivery_orchestration.build_evidence_index
    delivery_orchestration.build_evidence_index = _boom
    try:
        for _ in range(3):
            clock[0] += 10_000
            worker.run_once()
    finally:
        delivery_orchestration.build_evidence_index = original

    events = _delivery_events(graph, run_id)
    assert [item["type"] for item in events] == ["delivery_orchestration_failed"]
    payload = events[0]["payload"]
    assert payload["code"] == "delivery_orchestration_exception"
    assert "ledger read flake" in payload["detail"]

    row = _outbox_row(graph, run_id)
    assert row is not None and row["status"] == "failed"
    assert row["attempts"] == 3


def test_delivery_skipped_when_run_not_succeeded(harness) -> None:
    graph, worker, _clock = harness
    run_id = "run-delivery-running"
    graph.seed(run_id=run_id, status="running")

    def mutate(uow):
        uow.repository.insert_outbox(
            build_outbox_record(
                "act-delivery-manual",
                run_id=run_id,
                command_id=None,
                action_kind=DELIVERY_OUTBOX_KIND,
                idempotency_key=delivery_idempotency_key(run_id),
            )
        )
        uow.repository.execute(
            "UPDATE outbox_actions SET payload_json = ? WHERE action_id = ?",
            (
                json.dumps({"schemaVersion": 1, "runId": run_id}),
                "act-delivery-manual",
            ),
        )

    graph.commands.store.submit(mutate, force_flush=True).result(timeout=10)

    assert worker.run_once() == 1
    assert _delivery_events(graph, run_id) == []
    row = _outbox_row(graph, run_id)
    assert row is not None and row["status"] == "succeeded"
