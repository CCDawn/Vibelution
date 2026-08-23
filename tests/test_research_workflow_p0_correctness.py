"""Focused correctness coverage for the P0 catalog/workflow fixes."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from core.research.competition.real_control_batch import real_plan
from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.challenge_cup_runtime import ChallengeCupGraphCoordinator
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime.catalog_run_authorization import (
    CatalogRunAuthorizationError,
    authorization_to_dict,
    readiness_report_sha256,
    record_catalog_run_authorization,
    validate_catalog_run_authorization,
)
from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    GraphDispatchWorker,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
)
from core.web.services.team_workflow.research_runtime.team_role_source import (
    heal_agent_binding_from_sibling_freeze,
)
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_event_record,
    build_outbox_record,
    build_run_record,
    open_ledger_store,
)


def test_created_run_without_start_is_failed_once(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        run = build_run_record(
            run_id="run-created-zombie",
            status="created",
            last_event_sequence=1,
            created_at_ms=FIXED_NOW_MS,
        )

        def seed(uow) -> None:
            uow.repository.insert_run(run)
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run.run_id,
                    event_id="evt-created-run-created-zombie",
                )
            )

        store.submit(seed, force_flush=True).result(timeout=10)
        worker = GraphDispatchWorker(
            store=store,
            coordinator=ChallengeCupGraphCoordinator(tmp_path / "checkpoints.sqlite"),
            now_provider=lambda: FIXED_NOW_MS + 2_000,
            start_deadline_ms=1_000,
        )

        assert worker.run_once() == 1
        failed = store.get_run(run.run_id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.terminal_reason == "dispatch_never_started"
        events = store.list_events(run.run_id)
        assert [event.event_type for event in events] == ["run_created", "run_failed"]
        assert json.loads(events[-1].payload_json)["terminalReason"] == (
            "dispatch_never_started"
        )
        worker.run_once()
        assert len(store.list_events(run.run_id)) == 2
    finally:
        store.close()


@pytest.mark.parametrize("start_evidence", ["node_attempt", "accepted_command", "live_outbox"])
def test_created_run_with_start_evidence_is_not_reaped(
    tmp_path: Path, start_evidence: str
) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        run = build_run_record(
            run_id=f"run-created-{start_evidence}",
            status="created",
            last_event_sequence=1,
            created_at_ms=FIXED_NOW_MS,
        )

        def seed(uow) -> None:
            uow.repository.insert_run(run)
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run.run_id,
                    event_id=f"evt-created-{start_evidence}",
                )
            )
            if start_evidence in {"accepted_command", "live_outbox"}:
                uow.repository.insert_command(
                    build_command_record(
                        command_id=f"cmd-{start_evidence}",
                        run_id=run.run_id,
                        status="accepted",
                    )
                )
            if start_evidence == "node_attempt":
                uow.repository.insert_command(
                    build_command_record(
                        command_id="cmd-node-attempt",
                        run_id=run.run_id,
                        status="accepted",
                    )
                )
                uow.repository.insert_attempt(
                    build_attempt_record(
                        node_run_id=f"nr-{start_evidence}",
                        run_id=run.run_id,
                        command_id="cmd-node-attempt",
                    )
                )
            if start_evidence == "live_outbox":
                uow.repository.insert_outbox(
                    build_outbox_record(
                        action_id=f"act-{start_evidence}",
                        run_id=run.run_id,
                        command_id=f"cmd-{start_evidence}",
                        available_at_ms=FIXED_NOW_MS + 100_000,
                    )
                )

        store.submit(seed, force_flush=True).result(timeout=10)
        worker = GraphDispatchWorker(
            store=store,
            coordinator=ChallengeCupGraphCoordinator(tmp_path / "checkpoints.sqlite"),
            now_provider=lambda: FIXED_NOW_MS + 2_000,
            start_deadline_ms=1_000,
        )

        worker.run_once()
        current = store.get_run(run.run_id)
        assert current is not None and current.status == "created"
        assert len(store.list_events(run.run_id)) == 1
    finally:
        store.close()


def test_created_run_with_existing_reconciliation_event_fills_status_without_new_sequence(
    tmp_path: Path,
) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        run = build_run_record(
            run_id="run-created-partial-repair",
            status="created",
            last_event_sequence=2,
            created_at_ms=FIXED_NOW_MS,
        )

        def seed(uow) -> None:
            uow.repository.insert_run(run)
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run.run_id,
                    event_id="evt-created-partial-repair",
                )
            )
            uow.repository.insert_event(
                build_event_record(
                    2,
                    run_id=run.run_id,
                    event_id="evt-dispatch-never-started-run-created-partial-repair",
                    event_type="run_failed",
                )
            )

        store.submit(seed, force_flush=True).result(timeout=10)
        worker = GraphDispatchWorker(
            store=store,
            coordinator=ChallengeCupGraphCoordinator(tmp_path / "checkpoints.sqlite"),
            now_provider=lambda: FIXED_NOW_MS + 2_000,
            start_deadline_ms=1_000,
        )

        assert worker.run_once() == 1
        failed = store.get_run(run.run_id)
        assert failed is not None and failed.status == "failed"
        assert failed.last_event_sequence == 2
        assert len(store.list_events(run.run_id)) == 2
        assert worker.run_once() == 0
    finally:
        store.close()


def test_sibling_binding_never_crosses_role_boundary() -> None:
    wrong_role = {
        "agentBindingSnapshot": [
            {
                "nodeId": "source_finding",
                "agentId": "agent-search",
                "roleKey": "source_finder",
            }
        ]
    }
    assert heal_agent_binding_from_sibling_freeze(wrong_role, "hypothesis_design") is None

    same_role = {
        "agentBindingSnapshot": [
            {
                "nodeId": "protocol_design",
                "agentId": "agent-planner",
                "roleKey": "experiment_planner",
            }
        ]
    }
    bound = heal_agent_binding_from_sibling_freeze(same_role, "hypothesis_design")
    assert bound is not None
    assert bound["agentId"] == "agent-planner"
    assert bound["roleKey"] == "experiment_planner"


def test_catalog_run_authorization_is_hashed_and_idempotent(
    tmp_path: Path, monkeypatch
) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        from core.web.services.team_workflow.research_runtime import (
            catalog_run_authorization,
        )

        monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
        plan = real_plan("real-1")
        scope = {
            "planId": "real-1",
            "gateId": str(plan.gate_id),
            "questionIds": [str(question_id) for question_id in plan.question_ids],
        }
        evidence = {"status": "READY", "basis": "report-v1"}
        first = record_catalog_run_authorization(
            "team-p0",
            plan_id="real-1",
            batch_scope=scope,
            approved_by="server-operator",
            readiness_evidence=evidence,
            approved_at_ms=FIXED_NOW_MS,
        )
        repeated = record_catalog_run_authorization(
            "team-p0",
            plan_id="real-1",
            batch_scope=scope,
            approved_by="different-input-cannot-replace",
            readiness_evidence=evidence,
            approved_at_ms=FIXED_NOW_MS + 1,
        )
        assert repeated == first
        assert validate_catalog_run_authorization(first, team_id="team-p0", plan_id="real-1")
        assert first.record_hash
        assert store.list_catalog_run_authorizations("team-p0", "real-1") == [first]

        alias_plan = real_plan("real-5")
        alias_scope = {
            "planId": "real-5",
            "gateId": str(alias_plan.gate_id),
            "questionIds": [str(question_id) for question_id in alias_plan.question_ids],
        }
        alias = record_catalog_run_authorization(
            "team-p0",
            plan_id="real-5",
            batch_scope=alias_scope,
            approved_by="server-operator",
            readiness_report_hash=readiness_report_sha256(evidence),
            approved_at_ms=FIXED_NOW_MS,
        )
        assert alias.readiness_report_sha256 == readiness_report_sha256(evidence)
        assert validate_catalog_run_authorization(alias, team_id="team-p0", plan_id="real-5")
    finally:
        store.close()


def test_catalog_authorization_rejects_scope_that_does_not_match_canonical_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        from core.web.services.team_workflow.research_runtime import (
            catalog_run_authorization,
        )

        monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
        with pytest.raises(CatalogRunAuthorizationError, match="canonical"):
            record_catalog_run_authorization(
                "team-p0",
                plan_id="real-1",
                batch_scope={
                    "planId": "real-5",
                    "gateId": "G5",
                    "questionIds": ["SCI-096"],
                },
                approved_by="server-operator",
                readiness_evidence={"status": "READY"},
                approved_at_ms=FIXED_NOW_MS,
            )
    finally:
        store.close()


def test_catalog_authorization_rejects_unknown_scope_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        from core.web.services.team_workflow.research_runtime import (
            catalog_run_authorization,
        )

        monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
        plan = real_plan("real-1")
        with pytest.raises(CatalogRunAuthorizationError, match="scope"):
            record_catalog_run_authorization(
                "team-p0",
                plan_id="real-1",
                batch_scope={
                    "planId": "real-1",
                    "gateId": str(plan.gate_id),
                    "questionIds": [str(question_id) for question_id in plan.question_ids],
                    "untrustedExtension": "must-not-be-authorized",
                },
                approved_by="server-operator",
                readiness_evidence={"status": "READY"},
                approved_at_ms=FIXED_NOW_MS,
            )
    finally:
        store.close()


def test_catalog_authorization_rejects_question_outside_authorized_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        from core.web.services.team_workflow.research_runtime import (
            catalog_run_authorization,
        )

        monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
        plan = real_plan("real-1")
        authorization = record_catalog_run_authorization(
            "team-p0",
            plan_id="real-1",
            batch_scope={
                "planId": "real-1",
                "gateId": str(plan.gate_id),
                "questionIds": list(plan.question_ids),
            },
            approved_by="server-operator",
            readiness_evidence={"status": "READY"},
            approved_at_ms=FIXED_NOW_MS,
        )
        assert not validate_catalog_run_authorization(
            authorization,
            team_id="team-p0",
            plan_id="real-1",
            question_id="SCI-096",
        )
    finally:
        store.close()


def test_catalog_authorization_hash_is_recorded_on_run_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        from core.web.services.team_workflow.research_runtime import (
            catalog_run_authorization,
            run_creation,
        )

        monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
        monkeypatch.setattr(run_creation, "get_write_store", lambda: store)
        monkeypatch.setattr(
            run_creation,
            "research_workflow_data_root",
            lambda: tmp_path / "runtime-data",
        )
        evidence = {"status": "READY", "basis": "run-event-test"}
        plan = real_plan("real-1")
        scope = {
            "planId": "real-1",
            "gateId": str(plan.gate_id),
            "questionIds": [str(question_id) for question_id in plan.question_ids],
        }
        authorization = record_catalog_run_authorization(
            "acceptance-research-team",
            plan_id="real-1",
            batch_scope=scope,
            approved_by="server-operator",
            readiness_evidence=evidence,
            approved_at_ms=FIXED_NOW_MS,
        )
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "research_workflow_v21_baseline_case.json")
            .read_text(encoding="utf-8")
        )
        run_input = {
            **fixture["runInput"],
            "questionId": str(plan.question_ids[0]),
        }
        authorization_payload = authorization_to_dict(authorization)
        created = run_creation.create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=run_input,
            binding_layers=AgentBindingLayers(),
            idempotency_key="p0-catalog-authorization-event",
            catalog_run_authorization=authorization_payload,
        )
        events = store.list_events(created["runId"])
        assert [event.event_type for event in events] == [
            "run_created",
            "catalog_run_authorized",
        ]
        payload = json.loads(events[-1].payload_json)
        assert payload["recordHash"] == authorization.record_hash
        assert payload["readinessReportSha256"] == authorization.readiness_report_sha256
        replayed = run_creation.create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=run_input,
            binding_layers=AgentBindingLayers(),
            idempotency_key="p0-catalog-authorization-event",
            catalog_run_authorization=authorization_payload,
        )
        assert replayed["runId"] == created["runId"]
        with pytest.raises(ResearchWorkflowError, match="authorization"):
            run_creation.create_run(
                CHALLENGE_CUP_WORKFLOW_ID,
                run_input=run_input,
                binding_layers=AgentBindingLayers(),
                idempotency_key="p0-catalog-authorization-event",
            )
        with pytest.raises(ResearchWorkflowError, match="authorization"):
            run_creation.create_run(
                CHALLENGE_CUP_WORKFLOW_ID,
                run_input=run_input,
                binding_layers=AgentBindingLayers(),
                idempotency_key="p0-catalog-authorization-event",
                catalog_run_authorization={
                    **authorization_payload,
                    "recordHash": "f" * 64,
                },
            )
    finally:
        store.close()


def test_concurrent_replay_cannot_reuse_another_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The writer transaction must enforce the same auth identity as preflight."""

    from core.web.services.team_workflow.research_runtime import (
        catalog_run_authorization,
        run_creation,
    )

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
        monkeypatch.setattr(run_creation, "get_write_store", lambda: store)
        monkeypatch.setattr(
            run_creation,
            "research_workflow_data_root",
            lambda: tmp_path / "runtime-data",
        )
        plan = real_plan("real-1")
        scope = {
            "planId": "real-1",
            "gateId": str(plan.gate_id),
            "questionIds": [str(question_id) for question_id in plan.question_ids],
        }
        first = record_catalog_run_authorization(
            "acceptance-research-team",
            plan_id="real-1",
            batch_scope=scope,
            approved_by="server-operator",
            readiness_evidence={"status": "READY", "revision": "one"},
            approved_at_ms=FIXED_NOW_MS,
        )
        second = record_catalog_run_authorization(
            "acceptance-research-team",
            plan_id="real-1",
            batch_scope=scope,
            approved_by="server-operator",
            readiness_evidence={"status": "READY", "revision": "two"},
            approved_at_ms=FIXED_NOW_MS,
        )
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "research_workflow_v21_baseline_case.json")
            .read_text(encoding="utf-8")
        )
        run_input = {**fixture["runInput"], "questionId": str(plan.question_ids[0])}
        idempotency_key = "p0-concurrent-catalog-authorization"
        run_id = run_creation.run_id_for_create(CHALLENGE_CUP_WORKFLOW_ID, idempotency_key)
        original_get_run = store.get_run
        first_reads = 0
        first_reads_lock = threading.Lock()
        first_read_barrier = threading.Barrier(2)

        def synchronized_get_run(candidate_run_id: str):
            nonlocal first_reads
            if candidate_run_id == run_id:
                with first_reads_lock:
                    should_wait = first_reads < 2
                    if should_wait:
                        first_reads += 1
                if should_wait:
                    first_read_barrier.wait(timeout=5)
                    return None
            return original_get_run(candidate_run_id)

        monkeypatch.setattr(store, "get_run", synchronized_get_run)

        def create(authorization):
            try:
                return run_creation.create_run(
                    CHALLENGE_CUP_WORKFLOW_ID,
                    run_input=run_input,
                    binding_layers=AgentBindingLayers(),
                    idempotency_key=idempotency_key,
                    catalog_run_authorization=authorization_to_dict(authorization),
                )
            except ResearchWorkflowError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, (first, second)))
        successful = [result for result in results if isinstance(result, dict)]
        rejected = [result for result in results if isinstance(result, ResearchWorkflowError)]
        assert len(successful) == 1
        assert len(rejected) == 1
        assert rejected[0].code == "catalog_run_authorization_replay_mismatch"
        assert [event.event_type for event in store.list_events(successful[0]["runId"])] == [
            "run_created",
            "catalog_run_authorized",
        ]
    finally:
        store.close()


def test_legacy_run_cannot_be_signed_after_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        from core.web.services.team_workflow.research_runtime import (
            catalog_run_authorization,
            run_creation,
        )

        monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
        monkeypatch.setattr(run_creation, "get_write_store", lambda: store)
        monkeypatch.setattr(
            run_creation,
            "research_workflow_data_root",
            lambda: tmp_path / "runtime-data",
        )
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "research_workflow_v21_baseline_case.json")
            .read_text(encoding="utf-8")
        )
        run_input = {**fixture["runInput"], "questionId": "SCI-091"}
        legacy = run_creation.create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=run_input,
            binding_layers=AgentBindingLayers(),
            idempotency_key="p0-legacy-no-post-sign",
        )
        authorization = record_catalog_run_authorization(
            "acceptance-research-team",
            plan_id="real-1",
            batch_scope={
                "planId": "real-1",
                "gateId": "G1",
                "questionIds": ["SCI-091"],
            },
            approved_by="server-operator",
            readiness_evidence={"status": "READY", "revision": "post-sign"},
            approved_at_ms=FIXED_NOW_MS,
        )
        with pytest.raises(ResearchWorkflowError) as rejected:
            run_creation.create_run(
                CHALLENGE_CUP_WORKFLOW_ID,
                run_input=run_input,
                binding_layers=AgentBindingLayers(),
                idempotency_key="p0-legacy-no-post-sign",
                catalog_run_authorization=authorization_to_dict(authorization),
            )
        assert rejected.value.code == "catalog_run_authorization_replay_mismatch"
        assert [event.event_type for event in store.list_events(legacy["runId"])] == [
            "run_created"
        ]
    finally:
        store.close()
