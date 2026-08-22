"""Focused correctness coverage for the P0 catalog/workflow fixes."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from core.research.competition.real_control_batch import real_plan
from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.challenge_cup_runtime import ChallengeCupGraphCoordinator
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime.catalog_run_authorization import (
    authorization_to_dict,
    readiness_report_sha256,
    record_catalog_run_authorization,
    validate_catalog_run_authorization,
)
from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    GraphDispatchWorker,
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
def test_created_run_reconciliation_requires_node_attempt_evidence(
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
                        status="accepted" if start_evidence == "accepted_command" else "failed",
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
        if start_evidence == "node_attempt":
            assert current is not None and current.status == "created"
            assert len(store.list_events(run.run_id)) == 1
        else:
            assert current is not None and current.status == "failed"
            assert current.terminal_reason == "dispatch_never_started"
            events = store.list_events(run.run_id)
            assert [event.event_type for event in events] == ["run_created", "run_failed"]
            assert json.loads(events[-1].payload_json)["terminalReason"] == (
                "dispatch_never_started"
            )
            assert worker.run_once() == 0
            assert len(store.list_events(run.run_id)) == 2
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
            reconciliation_event = build_event_record(
                2,
                run_id=run.run_id,
                event_id="evt-dispatch-never-started-run-created-partial-repair",
                event_type="run_failed",
            )
            uow.repository.insert_event(
                replace(
                    reconciliation_event,
                    payload_json=json.dumps(
                        {"terminalReason": "dispatch_never_started"}
                    ),
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


@pytest.mark.parametrize(
    ("event_type", "terminal_reason"),
    [("run_created", "dispatch_never_started"), ("run_failed", "other_reason")],
)
def test_created_run_with_conflicting_reconciliation_event_rolls_back(
    tmp_path: Path, event_type: str, terminal_reason: str
) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        run = build_run_record(
            run_id="run-created-conflicting-repair",
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
                    event_id="evt-created-run-created-conflicting-repair",
                )
            )
            reconciliation_event = build_event_record(
                2,
                run_id=run.run_id,
                event_id="evt-dispatch-never-started-run-created-conflicting-repair",
                event_type=event_type,
            )
            uow.repository.insert_event(
                replace(
                    reconciliation_event,
                    payload_json=json.dumps({"terminalReason": terminal_reason}),
                )
            )

        store.submit(seed, force_flush=True).result(timeout=10)
        worker = GraphDispatchWorker(
            store=store,
            coordinator=ChallengeCupGraphCoordinator(tmp_path / "checkpoints.sqlite"),
            now_provider=lambda: FIXED_NOW_MS + 2_000,
            start_deadline_ms=1_000,
        )

        with pytest.raises(RuntimeError, match="conflicts with dispatch_never_started"):
            worker.run_once()
        current = store.get_run(run.run_id)
        assert current is not None and current.status == "created"
        assert current.last_event_sequence == 2
        assert len(store.list_events(run.run_id)) == 2
    finally:
        store.close()


def test_sibling_binding_never_crosses_role_boundary() -> None:
    wrong_role = {
        "agentBindingSnapshot": [
            {"agentId": "agent-search", "roleKey": "source_finder"}
        ]
    }
    assert heal_agent_binding_from_sibling_freeze(wrong_role, "hypothesis_design") is None

    same_role = {
        "agentBindingSnapshot": [
            {"agentId": "agent-planner", "roleKey": "experiment_planner"}
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
        scope = {"planId": "real-1", "gateId": "G1", "questionIds": ["SCI-091"]}
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

        alias_scope = {"planId": "real-5", "gateId": "G5", "questionIds": ["SCI-096"]}
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
        run_input = {**fixture["runInput"], "questionId": "SCI-091"}
        created = run_creation.create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=run_input,
            binding_layers=AgentBindingLayers(),
            idempotency_key="p0-catalog-authorization-event",
            catalog_run_authorization=authorization_to_dict(authorization),
        )
        events = store.list_events(created["runId"])
        assert [event.event_type for event in events] == [
            "run_created",
            "catalog_run_authorized",
        ]
        payload = json.loads(events[-1].payload_json)
        assert payload["recordHash"] == authorization.record_hash
        assert payload["readinessReportSha256"] == authorization.readiness_report_sha256
    finally:
        store.close()


@pytest.mark.parametrize(
    "scope",
    [
        {"planId": "real-1", "gateId": "G1", "questionIds": ["SCI-091"]},
        ["SCI-091"],
    ],
)
def test_create_run_rejects_question_outside_or_malformed_authorization_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope
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
        evidence = {"status": "READY", "basis": "scope-membership-test"}
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
        run_input = {**fixture["runInput"], "questionId": "SCI-002"}
        with pytest.raises(
            run_creation.ResearchWorkflowError,
            match="outside the batch scope",
        ):
            run_creation.create_run(
                CHALLENGE_CUP_WORKFLOW_ID,
                run_input=run_input,
                binding_layers=AgentBindingLayers(),
                idempotency_key="scope-membership-rejection",
                catalog_run_authorization=authorization_to_dict(authorization),
            )
        assert store.list_runs_for_team(
            "acceptance-research-team", CHALLENGE_CUP_WORKFLOW_ID
        ) == []
    finally:
        store.close()


def test_legacy_run_replay_binds_catalog_authorization_event_once(
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
            idempotency_key="legacy-replay-authorization",
        )
        evidence = {"status": "READY", "basis": "legacy-replay-test"}
        authorization = record_catalog_run_authorization(
            "acceptance-research-team",
            plan_id="real-1",
            batch_scope={
                "planId": "real-1",
                "gateId": "G1",
                "questionIds": ["SCI-091"],
            },
            approved_by="server-operator",
            readiness_evidence=evidence,
            approved_at_ms=FIXED_NOW_MS,
        )
        replay = run_creation.create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=run_input,
            binding_layers=AgentBindingLayers(),
            idempotency_key="legacy-replay-authorization",
            catalog_run_authorization=authorization_to_dict(authorization),
        )
        assert replay["runId"] == legacy["runId"]
        events = store.list_events(legacy["runId"])
        assert [event.event_type for event in events] == [
            "run_created",
            "catalog_run_authorized",
        ]
        assert json.loads(events[-1].payload_json)["recordHash"] == authorization.record_hash
        assert store.get_run(legacy["runId"]).last_event_sequence == 2

        run_creation.create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=run_input,
            binding_layers=AgentBindingLayers(),
            idempotency_key="legacy-replay-authorization",
            catalog_run_authorization=authorization_to_dict(authorization),
        )
        assert len(store.list_events(legacy["runId"])) == 2
    finally:
        store.close()


def test_legacy_replay_rejects_conflicting_catalog_authorization_event(
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
            idempotency_key="legacy-replay-conflict",
        )
        evidence = {"status": "READY", "basis": "legacy-replay-conflict"}
        authorization = record_catalog_run_authorization(
            "acceptance-research-team",
            plan_id="real-1",
            batch_scope={
                "planId": "real-1",
                "gateId": "G1",
                "questionIds": ["SCI-091"],
            },
            approved_by="server-operator",
            readiness_evidence=evidence,
            approved_at_ms=FIXED_NOW_MS,
        )

        def seed_conflict(uow) -> None:
            sequence = uow.repository.advance_last_sequence(
                legacy["runId"], 1, FIXED_NOW_MS
            )
            assert sequence == 2
            uow.repository.insert_event(
                replace(
                    build_event_record(
                        sequence,
                        run_id=legacy["runId"],
                        event_id=f"evt-catalog-run-authorized-{legacy['runId']}",
                        event_type="catalog_run_authorized",
                    ),
                    payload_json=json.dumps({"recordHash": "conflict"}),
                )
            )

        store.submit(seed_conflict, force_flush=True).result(timeout=10)
        with pytest.raises(
            run_creation.ResearchWorkflowError,
            match="conflicts with the durable record",
        ):
            run_creation.create_run(
                CHALLENGE_CUP_WORKFLOW_ID,
                run_input=run_input,
                binding_layers=AgentBindingLayers(),
                idempotency_key="legacy-replay-conflict",
                catalog_run_authorization=authorization_to_dict(authorization),
            )
        assert len(store.list_events(legacy["runId"])) == 2
        assert store.get_run(legacy["runId"]).last_event_sequence == 2
    finally:
        store.close()


def test_legacy_replay_rejects_team_or_question_identity_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        from core.web.services.team_workflow.research_runtime import (
            catalog_run_authorization,
            run_creation,
            run_lifecycle,
        )

        monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
        monkeypatch.setattr(run_creation, "get_write_store", lambda: store)
        monkeypatch.setattr(
            run_creation,
            "research_workflow_data_root",
            lambda: tmp_path / "runtime-data",
        )
        idempotency_key = "legacy-replay-identity-mismatch"
        run_id = run_lifecycle.run_id_for_create(
            CHALLENGE_CUP_WORKFLOW_ID, idempotency_key
        )
        legacy_run = replace(
            build_run_record(
                run_id=run_id,
                team_id="acceptance-research-team",
                last_event_sequence=1,
            ),
            question_id="SCI-091",
        )

        def seed(uow) -> None:
            uow.repository.insert_run(legacy_run)
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run_id,
                    event_id=f"evt-created-{run_id}",
                )
            )

        store.submit(seed, force_flush=True).result(timeout=10)
        authorization = record_catalog_run_authorization(
            "acceptance-research-team",
            plan_id="real-5",
            batch_scope={
                "planId": "real-5",
                "gateId": "G5",
                "questionIds": ["SCI-091", "SCI-002"],
            },
            approved_by="server-operator",
            readiness_evidence={"status": "READY", "basis": "identity-mismatch"},
            approved_at_ms=FIXED_NOW_MS,
        )
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "research_workflow_v21_baseline_case.json")
            .read_text(encoding="utf-8")
        )
        mismatched_input = {
            **fixture["runInput"],
            "teamId": "acceptance-research-team",
            "questionId": "SCI-002",
        }
        with pytest.raises(
            run_creation.ResearchWorkflowError,
            match="idempotencyKey was already used with different run input",
        ):
            run_creation.create_run(
                CHALLENGE_CUP_WORKFLOW_ID,
                run_input=mismatched_input,
                binding_layers=AgentBindingLayers(),
                idempotency_key=idempotency_key,
                catalog_run_authorization=authorization_to_dict(authorization),
            )
        assert len(store.list_events(run_id)) == 1
        assert store.get_run(run_id).last_event_sequence == 1
    finally:
        store.close()
