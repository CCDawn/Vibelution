"""Regression coverage for real-catalog authorization evidence."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS, open_ledger_store

TEAM_ID = "acceptance-research-team"


def _approval_for_real_1(
    monkeypatch: pytest.MonkeyPatch,
    store,
    *,
    readiness: dict[str, str] | None = None,
):
    from core.web.services.team_workflow.research_runtime import (
        catalog_run_authorization,
    )

    monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
    return catalog_run_authorization.record_catalog_run_authorization(
        "acceptance-research-team",
        plan_id="real-1",
        batch_scope=catalog_run_authorization.expected_batch_scope("real-1"),
        approved_by="research-lead",
        readiness_evidence=readiness or {"status": "READY", "revision": "r1"},
        approved_at_ms=FIXED_NOW_MS,
    )


def _real_1_run_input() -> dict:
    fixture_path = Path(__file__).parent / "fixtures" / "research_workflow_v21_baseline_case.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    return {**fixture["runInput"], "questionId": "SCI-091"}


def test_persists_exact_auditable_authorization_record(
    tmp_path: Path, monkeypatch
) -> None:
    """A real batch approval is immutable evidence, not a readiness boolean."""
    from core.web.services.team_workflow.research_runtime import (
        catalog_run_authorization,
    )

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
        scope = catalog_run_authorization.expected_batch_scope("real-1")
        approval = catalog_run_authorization.record_catalog_run_authorization(
            "team-catalog-auth",
            plan_id="real-1",
            batch_scope=scope,
            approved_by="research-lead",
            readiness_evidence={"status": "READY", "revision": "r1"},
            approved_at_ms=FIXED_NOW_MS,
        )

        assert approval.approved_by == "research-lead"
        assert approval.approved_at_ms == FIXED_NOW_MS
        assert approval.batch_scope_json
        assert approval.readiness_report_sha256
        assert approval.record_hash
        assert catalog_run_authorization.find_catalog_run_authorization(
            "team-catalog-auth",
            plan_id="real-1",
            batch_scope=scope,
            readiness_report_sha256_value=approval.readiness_report_sha256,
        ) == approval
    finally:
        store.close()


@pytest.mark.parametrize(
    "scope",
    [
        {"planId": "real-1", "gateId": "G1", "questionIds": ["SCI-096"]},
        {"planId": "real-1", "gateId": "G1", "questionIds": ["SCI-091", "SCI-002"]},
        {"planId": "real-5", "gateId": "G1", "questionIds": ["SCI-091"]},
    ],
)
def test_rejects_scope_that_drifts_from_the_frozen_real_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope: dict
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        catalog_run_authorization,
    )

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
        with pytest.raises(catalog_run_authorization.CatalogRunAuthorizationError):
            catalog_run_authorization.record_catalog_run_authorization(
                "team-catalog-auth",
                plan_id="real-1",
                batch_scope=scope,
                approved_by="research-lead",
                readiness_evidence={"status": "READY"},
                approved_at_ms=FIXED_NOW_MS,
            )
    finally:
        store.close()


def test_run_event_binds_exact_approval_and_replay_cannot_upgrade_legacy_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        catalog_run_authorization,
        run_creation,
    )

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        approval = _approval_for_real_1(monkeypatch, store)
        monkeypatch.setattr(run_creation, "get_write_store", lambda: store)
        monkeypatch.setattr(
            run_creation,
            "research_workflow_data_root",
            lambda: tmp_path / "runtime-data",
        )
        run_input = _real_1_run_input()
        created = run_creation.create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=run_input,
            binding_layers=AgentBindingLayers(),
            idempotency_key="catalog-authorization-event",
            catalog_run_authorization=catalog_run_authorization.authorization_to_dict(approval),
        )
        events = store.list_events(created["runId"])
        assert [event.event_type for event in events] == [
            "run_created",
            "catalog_run_authorized",
        ]
        audit = json.loads(events[-1].payload_json)
        assert audit["authorizationId"] == approval.authorization_id
        assert audit["recordHash"] == approval.record_hash
        assert audit["readinessReportSha256"] == approval.readiness_report_sha256

        replay = run_creation.create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=run_input,
            binding_layers=AgentBindingLayers(),
            idempotency_key="catalog-authorization-event",
            catalog_run_authorization=catalog_run_authorization.authorization_to_dict(approval),
        )
        assert replay["runId"] == created["runId"]
        assert len(store.list_events(created["runId"])) == 2

        legacy = run_creation.create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=run_input,
            binding_layers=AgentBindingLayers(),
            idempotency_key="catalog-authorization-legacy",
        )
        with pytest.raises(run_creation.ResearchWorkflowError) as replay_error:
            run_creation.create_run(
                CHALLENGE_CUP_WORKFLOW_ID,
                run_input=run_input,
                binding_layers=AgentBindingLayers(),
                idempotency_key="catalog-authorization-legacy",
                catalog_run_authorization=catalog_run_authorization.authorization_to_dict(approval),
            )
        assert replay_error.value.code == "catalog_run_authorization_replay_mismatch"
        assert [event.event_type for event in store.list_events(legacy["runId"])] == [
            "run_created"
        ]
    finally:
        store.close()


def test_authorized_run_replay_requires_the_same_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        catalog_run_authorization,
        run_creation,
    )

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        first = _approval_for_real_1(monkeypatch, store)
        second = _approval_for_real_1(
            monkeypatch,
            store,
            readiness={"status": "READY", "revision": "r2"},
        )
        monkeypatch.setattr(run_creation, "get_write_store", lambda: store)
        monkeypatch.setattr(
            run_creation,
            "research_workflow_data_root",
            lambda: tmp_path / "runtime-data",
        )
        run_input = _real_1_run_input()
        run_creation.create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=run_input,
            binding_layers=AgentBindingLayers(),
            idempotency_key="catalog-authorization-exact-replay",
            catalog_run_authorization=catalog_run_authorization.authorization_to_dict(first),
        )
        for supplied in (None, catalog_run_authorization.authorization_to_dict(second)):
            with pytest.raises(run_creation.ResearchWorkflowError) as replay_error:
                run_creation.create_run(
                    CHALLENGE_CUP_WORKFLOW_ID,
                    run_input=run_input,
                    binding_layers=AgentBindingLayers(),
                    idempotency_key="catalog-authorization-exact-replay",
                    catalog_run_authorization=supplied,
                )
            assert replay_error.value.code == "catalog_run_authorization_replay_mismatch"
    finally:
        store.close()


def test_concurrent_create_cannot_reuse_a_run_under_a_different_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        catalog_run_authorization,
        run_creation,
    )

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        first = _approval_for_real_1(monkeypatch, store)
        second = _approval_for_real_1(
            monkeypatch,
            store,
            readiness={"status": "READY", "revision": "r2"},
        )
        monkeypatch.setattr(run_creation, "get_write_store", lambda: store)
        monkeypatch.setattr(
            run_creation,
            "research_workflow_data_root",
            lambda: tmp_path / "runtime-data",
        )
        run_input = _real_1_run_input()

        def create(supplied: dict) -> object:
            try:
                return run_creation.create_run(
                    CHALLENGE_CUP_WORKFLOW_ID,
                    run_input=run_input,
                    binding_layers=AgentBindingLayers(),
                    idempotency_key="catalog-authorization-concurrent",
                    catalog_run_authorization=supplied,
                )
            except run_creation.ResearchWorkflowError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    create,
                    [
                        catalog_run_authorization.authorization_to_dict(first),
                        catalog_run_authorization.authorization_to_dict(second),
                    ],
                )
            )
        successful = [item for item in results if isinstance(item, dict)]
        rejected = [item for item in results if not isinstance(item, dict)]
        assert len(successful) == 1
        assert len(rejected) == 1
        assert isinstance(rejected[0], run_creation.ResearchWorkflowError)
        assert rejected[0].code == "catalog_run_authorization_replay_mismatch"
        assert [event.event_type for event in store.list_events(successful[0]["runId"])] == [
            "run_created",
            "catalog_run_authorized",
        ]
    finally:
        store.close()


def test_real_batch_requires_record_and_revalidates_before_retry_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow import challenge_cup_real_batch as real_batch
    from core.web.services.team_workflow.research_runtime import (
        catalog_run_authorization,
    )

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    report = {"status": "READY", "revision": "r1"}
    start_attempts: list[str] = []
    try:
        monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
        monkeypatch.setattr(real_batch, "team_workspace_root", lambda _team_id: tmp_path)
        monkeypatch.setattr(
            real_batch.team_service,
            "get_team",
            lambda team_id: {"teamId": team_id},
        )
        monkeypatch.setattr(
            real_batch,
            "get_challenge_cup_dev_control_snapshot",
            lambda team_id: {
                "teamId": team_id,
                "nextLegalAction": "RESEARCH_AUTHORIZATION_REQUIRED",
                "report": dict(report),
            },
        )

        def launcher(_team_id: str, question_id: str, _key: str) -> dict:
            return {
                "runId": f"run-{question_id.lower()}",
                "activeNodeId": "source_finding",
                "runVersion": 1,
            }

        def failing_dispatcher(_team_id: str, run: dict, _node: str, _key: str) -> dict:
            start_attempts.append(str(run["runId"]))
            raise RuntimeError("temporary dispatcher failure")

        with pytest.raises(real_batch.ChallengeCupRealBatchError) as missing:
            real_batch.start_real_batch(
                TEAM_ID,
                plan_id="real-1",
                confirmed=True,
                launcher=launcher,
                start_dispatcher=failing_dispatcher,
            )
        assert missing.value.code == "catalog_run_authorization_required"

        authorization = real_batch.record_catalog_run_authorization(
            TEAM_ID,
            plan_id="real-1",
            approved_by="research-lead",
        )
        assert authorization["approvedBy"] == "research-lead"
        started = real_batch.start_real_batch(
            TEAM_ID,
            plan_id="real-1",
            confirmed=True,
            launcher=launcher,
            start_dispatcher=failing_dispatcher,
        )
        assert started["launched"] == [{"questionId": "SCI-091", "outcome": "launched"}]
        assert start_attempts == ["run-sci-091"]

        report["revision"] = "r2"
        with pytest.raises(real_batch.ChallengeCupRealBatchError) as stale:
            real_batch.poll_real_batch(
                TEAM_ID,
                plan_id="real-1",
                launcher=launcher,
                run_status_reader=lambda _team_id: {
                    "run-sci-091": {"runId": "run-sci-091", "status": "running"}
                },
                start_dispatcher=failing_dispatcher,
            )
        assert stale.value.code == "catalog_run_authorization_required"
        assert start_attempts == ["run-sci-091"]
    finally:
        store.close()


def test_question_launch_requires_exact_marker_hash_and_persisted_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow import challenge_cup_dev_controls
    from core.web.services.team_workflow.research_runtime import (
        catalog_run_authorization,
        question_launch,
    )

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    report = {"status": "READY", "revision": "r1"}
    try:
        monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
        snapshot = {
            "teamId": TEAM_ID,
            "nextLegalAction": "RESEARCH_AUTHORIZATION_REQUIRED",
            "report": dict(report),
        }
        monkeypatch.setattr(
            challenge_cup_dev_controls,
            "get_challenge_cup_dev_control_snapshot",
            lambda _team_id: dict(snapshot),
        )
        assert question_launch._dev_authorization_ready(TEAM_ID) is False

        _approval_for_real_1(monkeypatch, store, readiness=report)
        assert question_launch._dev_authorization_ready(TEAM_ID) is True

        # The snapshot's team identity cannot redirect a request to another
        # team's approval record.
        assert question_launch._dev_authorization_ready("other-research-team") is False

        # A stale digest must not override changed readiness content.
        approval_hash = catalog_run_authorization.readiness_report_sha256(report)
        snapshot["report"] = {"status": "READY", "revision": "r2"}
        snapshot["readinessReportSha256"] = approval_hash
        assert question_launch._dev_authorization_ready(TEAM_ID) is False
        snapshot.pop("readinessReportSha256")
        snapshot["report"] = dict(report)

        snapshot["nextLegalAction"] = "BOGUS_AUTHORIZATION_REQUIRED"
        assert question_launch._dev_authorization_ready(TEAM_ID) is False
        snapshot["nextLegalAction"] = "RESEARCH_AUTHORIZATION_REQUIRED"
        snapshot["readinessReportSha256"] = "not-a-hash"
        assert question_launch._dev_authorization_ready(TEAM_ID) is False
    finally:
        store.close()


def test_real_batch_rejects_a_report_that_disagrees_with_its_snapshot_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow import challenge_cup_real_batch as real_batch
    from core.web.services.team_workflow.research_runtime import (
        catalog_run_authorization,
    )

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    report = {"status": "READY", "revision": "r1"}
    launched: list[str] = []
    try:
        monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
        monkeypatch.setattr(real_batch, "team_workspace_root", lambda _team_id: tmp_path)
        monkeypatch.setattr(
            real_batch.team_service,
            "get_team",
            lambda team_id: {"teamId": team_id},
        )
        _approval_for_real_1(monkeypatch, store, readiness=report)
        monkeypatch.setattr(
            real_batch,
            "get_challenge_cup_dev_control_snapshot",
            lambda team_id: {
                "teamId": team_id,
                "nextLegalAction": "RESEARCH_AUTHORIZATION_REQUIRED",
                "report": {"status": "READY", "revision": "r2"},
                "readinessReportSha256": catalog_run_authorization.readiness_report_sha256(
                    report
                ),
            },
        )

        def launcher(_team_id: str, question_id: str, _key: str) -> dict:
            launched.append(question_id)
            return {"runId": f"run-{question_id.lower()}", "activeNodeId": "source_finding"}

        with pytest.raises(real_batch.ChallengeCupRealBatchError) as rejected:
            real_batch.start_real_batch(
                TEAM_ID,
                plan_id="real-1",
                confirmed=True,
                launcher=launcher,
            )
        assert rejected.value.code == "catalog_run_authorization_required"
        assert launched == []
    finally:
        store.close()


def test_real_batch_rejects_a_snapshot_from_another_team(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow import challenge_cup_real_batch as real_batch
    from core.web.services.team_workflow.research_runtime import (
        catalog_run_authorization,
    )

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    report = {"status": "READY", "revision": "r1"}
    try:
        monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
        monkeypatch.setattr(real_batch, "team_workspace_root", lambda _team_id: tmp_path)
        monkeypatch.setattr(
            real_batch.team_service,
            "get_team",
            lambda team_id: {"teamId": team_id},
        )
        _approval_for_real_1(monkeypatch, store, readiness=report)
        monkeypatch.setattr(
            real_batch,
            "get_challenge_cup_dev_control_snapshot",
            lambda _team_id: {
                "teamId": "another-research-team",
                "nextLegalAction": "RESEARCH_AUTHORIZATION_REQUIRED",
                "report": report,
            },
        )

        with pytest.raises(real_batch.ChallengeCupRealBatchError) as rejected:
            real_batch.start_real_batch(TEAM_ID, plan_id="real-1", confirmed=True)
        assert rejected.value.code == "platform_not_authorized"
    finally:
        store.close()


def test_authorization_route_derives_server_operator_and_rejects_client_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from core.web.app import create_app
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.services.team_workflow import challenge_cup_real_batch as real_batch
    from core.web.services.team_workflow.research_runtime import (
        catalog_run_authorization,
    )

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        monkeypatch.setattr(catalog_run_authorization, "get_write_store", lambda: store)
        monkeypatch.setattr(real_batch, "team_workspace_root", lambda _team_id: tmp_path)
        monkeypatch.setattr(
            real_batch.team_service,
            "get_team",
            lambda team_id: {"teamId": team_id},
        )
        monkeypatch.setattr(
            real_batch,
            "get_challenge_cup_dev_control_snapshot",
            lambda team_id: {
                "teamId": team_id,
                "nextLegalAction": "RESEARCH_AUTHORIZATION_REQUIRED",
                "report": {"status": "READY", "revision": "r1"},
            },
        )
        base = (
            "/api/teams/acceptance-research-team/workflow-orchestration/"
            "challenge-program/real-batches/real-1/authorize"
        )
        with TestClient(
            create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()}
        ) as client:
            rejected = client.post(base, json={"approvedBy": "forged-client"})
            assert rejected.status_code == 422
            recorded = client.post(base)
        assert recorded.status_code == 200
        payload = recorded.json()
        assert payload["approvedBy"] == "local-control-operator"
        assert payload["planId"] == "real-1"
        assert payload["recordHash"]
    finally:
        store.close()
