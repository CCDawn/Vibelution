"""Formal knowledge handoff acceptance must carry a canonical package receipt."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.web.services.team_workflow.research_runtime.command_service import (
    WorkflowCommandError,
)
from core.web.services.team_workflow.research_runtime.human_acceptance_artifact import (
    prepare_knowledge_handoff_artifact,
)
from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
    canonical_sha256,
)
from core.web.services.team_workflow.research_runtime.knowledge_artifact_authority import (
    _accepted_package_payload,
    load_knowledge_package_payload,
)
from core.web.services.team_workflow.research_runtime.readiness.common import (
    HandoffSnapshot,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_event_record,
    build_run_record,
)


def _seed_pending_knowledge_gate(harness: CommandHarness, *, terminal: bool = False) -> None:
    run = replace(
        build_run_record(last_event_sequence=1),
        input_snapshot_json=json.dumps(
            {
                "snapshotHash": "a" * 64,
                "sourceCollectionRunId": "sc-run-1",
            }
        ),
    )
    if terminal:
        from core.research.workflow.knowledge_sideflow_definition import (
            build_knowledge_sideflow_workflow_definition,
        )
        from core.research.workflow.definition_registry import register_or_resolve

        definition = build_knowledge_sideflow_workflow_definition()
        identity = register_or_resolve(definition)
        run = replace(
            run,
            workflow_id=definition.workflowId,
            workflow_version_id=identity.workflowVersionId,
            structure_hash=identity.structureHash,
        )
    attempt = replace(
        build_attempt_record(
            node_run_id="nr-run-test-knowledge_handoff-a1",
            node_id="knowledge_handoff",
            actor_kind="human",
            status="waiting_human",
        ),
        pending_action_id="act-knowledge-human",
    )

    def mutate(uow):
        uow.repository.insert_run(run)
        uow.repository.insert_event(
            build_event_record(
                sequence=1,
                event_id="evt-created-run-test",
            )
        )
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-1",
                command_kind="start_node",
                node_id="knowledge_handoff",
            )
        )
        uow.repository.insert_attempt(attempt)
        if not terminal:
            uow.repository.insert_handoff(
                handoff_id="ho-knowledge-hypothesis",
                run_id="run-test",
                edge_id="knowledge_handoff->hypothesis_design",
                from_node_run_id=attempt.node_run_id,
                to_node_id="hypothesis_design",
                to_node_run_id=None,
                gate_kind="knowledge_package",
                input_snapshot_hash="a" * 64,
                offered_at_ms=FIXED_NOW_MS,
            )
            uow.repository.update_handoff_status(
                "ho-knowledge-hypothesis",
                "waiting_human",
                FIXED_NOW_MS,
            )
        uow.repository.insert_human_task(
            task_id="ht-knowledge",
            run_id="run-test",
            node_run_id=attempt.node_run_id,
            handoff_id=None if terminal else "ho-knowledge-hypothesis",
            task_kind="gate:knowledge_handoff",
            prompt_json='{"nodeId":"knowledge_handoff"}',
            created_at_ms=FIXED_NOW_MS,
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _package() -> dict[str, object]:
    return {
        "teamId": "research-team",
        "sourceCollectionRunId": "sc-run-1",
        "accepted": True,
        "knowledgeItems": [
            {"knowledgeItemId": "ki-1", "contentHash": "b" * 64}
        ],
    }


@pytest.mark.parametrize("terminal", [False, True])
def test_accept_materializes_and_binds_knowledge_package_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: bool
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_pending_knowledge_gate(harness, terminal=terminal)
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime."
            "human_acceptance_artifact.load_scoped_artifact_payload",
            lambda *args, **kwargs: _package(),
        )

        receipt = harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                node_id="knowledge_handoff",
                expected_run_version=1,
                idempotency_key="ui:accept-knowledge",
                payload={"taskId": "ht-knowledge", "decision": "accept"},
            )
        )
        assert receipt.status == "accepted"

        def read(repo):
            artifact_rows = repo.list_receipts_for_node_run(
                "nr-run-test-knowledge_handoff-a1"
            )
            handoff_rows = repo.list_handoff_artifact_refs_for_run("run-test")
            outbox = repo.list_pending_outbox("run-test", 20)
            return artifact_rows, handoff_rows, outbox

        artifact_rows, handoff_rows, outbox = harness.store.read(read)
        assert len(artifact_rows) == 1
        assert artifact_rows[0][4] == "knowledge_package"
        assert handoff_rows == ([] if terminal else [
            (
                "ho-knowledge-hypothesis",
                artifact_rows[0][0],
                "knowledge_package",
                artifact_rows[0][5],
                "1.0.0",
                artifact_rows[0][7],
            )
        ])
        graph_payload = next(
            json.loads(item.payload_json)
            for item in outbox
            if item.action_kind == "graph_dispatch"
        )
        execution_receipt = graph_payload["receipt"]
        assert execution_receipt["artifactReceiptIds"] == [artifact_rows[0][0]]
    finally:
        harness.close()


@pytest.mark.parametrize("terminal", [False, True])
def test_accept_fails_without_materialized_knowledge_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: bool
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_pending_knowledge_gate(harness, terminal=terminal)
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime."
            "human_acceptance_artifact.load_scoped_artifact_payload",
            lambda *args, **kwargs: None,
        )

        with pytest.raises(WorkflowCommandError, match="knowledge_package_not_materialized"):
            harness.service.submit(
                harness.request(
                    command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                    node_id="knowledge_handoff",
                    expected_run_version=1,
                    idempotency_key="ui:accept-missing",
                    payload={"taskId": "ht-knowledge", "decision": "accept"},
                )
            )

        human = harness.store.read(lambda repo: repo.get_human_task("ht-knowledge"))
        assert human is not None and human[6] == "pending"
        assert harness.store.read(
            lambda repo: repo.list_receipts_for_node_run(
                "nr-run-test-knowledge_handoff-a1"
            )
        ) == []
    finally:
        harness.close()


def test_retry_preparation_recovers_accepted_handoff_without_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_pending_knowledge_gate(harness)

        def accept_without_receipt(uow):
            uow.repository.update_handoff_status(
                "ho-knowledge-hypothesis",
                "accepted",
                FIXED_NOW_MS + 1,
            )

        harness.store.submit(accept_without_receipt, force_flush=True).result(timeout=10)
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime."
            "human_acceptance_artifact.load_scoped_artifact_payload",
            lambda *args, **kwargs: _package(),
        )
        run = harness.store.get_run("run-test")
        assert run is not None

        prepared = prepare_knowledge_handoff_artifact(
            store=harness.store,
            run=run,
            task_id="",
            target_node_id="hypothesis_design",
        )

        assert prepared is not None
        assert prepared.handoff_id == "ho-knowledge-hypothesis"
        assert prepared.artifact_kind == "knowledge_package"
    finally:
        harness.close()


def test_retry_command_backfills_historical_accepted_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_pending_knowledge_gate(harness)

        def seed_failed_hypothesis(uow):
            uow.repository.update_handoff_status(
                "ho-knowledge-hypothesis",
                "accepted",
                FIXED_NOW_MS + 1,
            )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-hypothesis-a1",
                    command_kind="start_node",
                    node_id="hypothesis_design",
                    idempotency_key="seed-hypothesis",
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id="nr-run-test-hypothesis_design-a1",
                    node_id="hypothesis_design",
                    status="failed",
                    command_id="cmd-hypothesis-a1",
                )
            )

        harness.store.submit(seed_failed_hypothesis, force_flush=True).result(timeout=10)
        harness.context._knowledge_package = _package()
        harness.context.handoffs["hypothesis_design"] = [
            HandoffSnapshot(
                handoff_id="ho-knowledge-hypothesis",
                from_node_run_id="nr-run-test-knowledge_handoff-a1",
                status="accepted",
            )
        ]
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime."
            "human_acceptance_artifact.load_scoped_artifact_payload",
            lambda *args, **kwargs: _package(),
        )

        receipt = harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.RETRY_NODE,
                node_id="hypothesis_design",
                expected_run_version=1,
                idempotency_key="ui:retry-hypothesis",
            )
        )

        assert receipt.status == "accepted"
        refs = harness.store.read(
            lambda repo: repo.list_handoff_artifact_refs_for_run("run-test")
        )
        assert len(refs) == 1
        assert refs[0][0] == "ho-knowledge-hypothesis"
        assert refs[0][2] == "knowledge_package"
        attempts = harness.store.list_attempts("run-test")
        assert next(
            item for item in attempts if item.node_id == "hypothesis_design" and item.attempt == 2
        ).status == "starting"
    finally:
        harness.close()


def test_approved_team_knowledge_is_the_package_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = {
        "candidateId": "candidate-draft-1",
        "teamId": "research-team",
        "metadata": {
            "taskType": "steward_pack_draft",
            "output": {
                "approvalRequired": True,
                "sourceTrace": {
                    "teamId": "research-team",
                    "sourceCollectionRunId": "sc-run-1",
                    "workflowRunId": "run-test",
                },
            },
            "validation": {"valid": True},
            "knowledgeIngestion": {
                "status": "official_synced",
                "knowledgeBaseId": "team:research-team:kb-1",
                "knowledgeItemIds": ["ki-1"],
                "sourceArtifactId": "src-1",
                "proposalId": "kp-1",
                "batchId": "kb-1",
                "reviewedAt": "2026-08-14T00:00:00Z",
                "reviewedByAgentId": "agent-reviewer",
            },
        },
        "updatedAt": "2026-08-14T00:00:00Z",
    }
    item = {
        "knowledgeItemId": "ki-1",
        "knowledgeBaseId": "kb-1",
        "title": "Coding principles",
        "summary": "Evidence-grounded package",
        "content": "Stable approved content",
        "sourceArtifactIds": ["src-1"],
        "createdAt": "2026-08-14T00:00:00Z",
        "metadata": {"mutableLabel": "first"},
    }
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.candidates."
        "list_candidate_store_authority_records",
        lambda team_id, run_id, metadata_task_type: [candidate],
    )
    monkeypatch.setattr(
        "core.web.services.team_knowledge_service.list_knowledge_items",
        lambda knowledge_base_id, agent_id: {"items": [item]},
    )

    first = load_knowledge_package_payload(
        team_id="research-team",
        authority_run_id="sc-run-1",
        workflow_run_id="run-test",
    )
    assert first is not None
    assert first["accepted"] is True
    assert first["sourceArtifactIds"] == ["src-1"]
    assert first["knowledgeItems"][0]["knowledgeItemId"] == "ki-1"
    issued_hash = canonical_sha256(first)

    item["metadata"] = {"mutableLabel": "later"}
    replay = load_knowledge_package_payload(
        team_id="research-team",
        authority_run_id="sc-run-1",
        workflow_run_id="run-test",
        content_hash=issued_hash,
    )
    assert replay == first


def _steward_package_candidate(
    index: int,
    *,
    source_collection_run_id: str = "sc-run-1",
    workflow_run_id: str = "run-test",
    ingestion_status: str = "official_synced",
) -> dict[str, object]:
    candidate_id = f"candidate-draft-{index}"
    item_id = f"ki-{index}"
    return {
        "candidateId": candidate_id,
        "teamId": "research-team",
        "updatedAt": f"2026-08-14T00:00:{index:02d}Z",
        "metadata": {
            "taskType": "steward_pack_draft",
            "output": {
                "approvalRequired": True,
                "claims": [
                    {
                        "claim": f"Accepted evidence claim {index}.",
                        "sourceRef": f"source-{index}",
                    }
                ],
                "sourceTrace": {
                    "teamId": "research-team",
                    "sourceCollectionRunId": source_collection_run_id,
                    "workflowRunId": workflow_run_id,
                },
            },
            "validation": {"valid": True},
            "knowledgeIngestion": {
                "status": ingestion_status,
                "knowledgeBaseId": "team:research-team:kb-1",
                "knowledgeItemIds": [item_id],
                "sourceArtifactId": f"artifact-{index}",
                "proposalId": f"proposal-{index}",
                "batchId": f"batch-{index}",
                "reviewedAt": f"2026-08-14T00:00:{index:02d}Z",
                "reviewedByAgentId": "agent-reviewer",
            },
        },
    }


def _steward_package_item(index: int) -> dict[str, object]:
    item_id = f"ki-{index}"
    return {
        "knowledgeItemId": item_id,
        "knowledgeBaseId": "team:research-team:kb-1",
        "title": f"Accepted source {index}",
        "summary": f"Evidence-grounded package {index}",
        "content": f"Stable approved content {index}",
        "sourceArtifactIds": [f"artifact-{index}"],
        "createdAt": f"2026-08-14T00:00:{index:02d}Z",
    }


@pytest.mark.parametrize("different_reviewers", [False, True])
def test_accepted_package_aggregates_current_official_steward_drafts(
    monkeypatch: pytest.MonkeyPatch,
    different_reviewers: bool,
) -> None:
    current = [_steward_package_candidate(index) for index in range(8)]
    if different_reviewers:
        current[3]["metadata"]["knowledgeIngestion"]["reviewedByAgentId"] = "agent-reviewer-two"
    pending = _steward_package_candidate(8, ingestion_status="pending_review")
    old_run = _steward_package_candidate(
        9,
        source_collection_run_id="sc-run-old",
    )
    records = [*current, pending, old_run]
    items = [_steward_package_item(index) for index in range(8)]

    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.candidates."
        "list_candidate_store_authority_records",
        lambda *_args, **_kwargs: records,
    )
    monkeypatch.setattr(
        "core.web.services.team_knowledge_service.list_knowledge_items",
        lambda *_args, **_kwargs: {"items": items},
    )

    package = load_knowledge_package_payload(
        team_id="research-team",
        authority_run_id="sc-run-1",
        workflow_run_id="run-test",
    )

    assert package is not None
    assert package["accepted"] is True
    assert len({approval["reviewedByAgentId"] for approval in package["approvals"]}) == (2 if different_reviewers else 1)
    assert package["candidateIds"] == [
        f"candidate-draft-{index}" for index in range(8)
    ]
    assert package["candidateId"] == "candidate-draft-0"
    assert [item["knowledgeItemId"] for item in package["knowledgeItems"]] == [
        f"ki-{index}" for index in range(8)
    ]
    assert package["sourceArtifactIds"] == [
        f"artifact-{index}" for index in range(8)
    ]
    assert "candidate-draft-8" not in package["candidateIds"]
    assert "candidate-draft-9" not in package["candidateIds"]

    aggregate_hash = canonical_sha256(package)
    replay = load_knowledge_package_payload(
        team_id="research-team",
        authority_run_id="sc-run-1",
        workflow_run_id="run-test",
        content_hash=aggregate_hash,
    )
    assert replay == package


def test_accepted_package_preserves_legacy_single_draft_hash_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = [_steward_package_candidate(index) for index in range(8)]
    items = [_steward_package_item(index) for index in range(8)]
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.candidates."
        "list_candidate_store_authority_records",
        lambda *_args, **_kwargs: current,
    )
    monkeypatch.setattr(
        "core.web.services.team_knowledge_service.list_knowledge_items",
        lambda *_args, **_kwargs: {"items": items},
    )

    legacy = _accepted_package_payload(
        current[7],
        team_id="research-team",
        authority_run_id="sc-run-1",
        knowledge_base_id="team:research-team:kb-1",
        item_ids=("ki-7",),
        item_by_id={"ki-7": items[7]},
    )
    legacy_hash = canonical_sha256(legacy)

    replay = load_knowledge_package_payload(
        team_id="research-team",
        authority_run_id="sc-run-1",
        workflow_run_id="run-test",
        content_hash=legacy_hash,
    )

    assert replay == legacy
