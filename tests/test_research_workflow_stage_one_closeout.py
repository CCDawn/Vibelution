"""Task 1 contracts for a legal node-7 Challenge Cup stage-one closeout."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from langgraph.graph import END

from core.research.competition.stage_one_completion_policy import (
    load_stage_one_completion_policy,
)
from core.research.competition.stage_one_requirement_matrix import (
    G1_REQUIRED_EVIDENCE_KINDS,
    evaluate_stage_one_requirement_matrix,
    matrix_to_dict,
)
from core.research.workflow.challenge_cup_graph import ChallengeCupState
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
)
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.research.workflow.definition_registry import (
    definition_identity,
    registered_identities,
    resolve_definition_by_version_id,
)
from core.web.services.team_workflow.research_runtime import (
    knowledge_rollout,
    node_completion,
    program_candidate_handoff,
    result_package_system_adapter,
)
from core.web.services.team_workflow.research_runtime.checkpoint_lifecycle import (
    advance_checkpoint,
)
from core.web.services.team_workflow.research_runtime.node_command_adapter import (
    node_command_capabilities,
)
from core.web.services.team_workflow.research_runtime.node_execution_support import (
    NodeExecutionError,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowRuntimeService,
)
from core.web.services.team_workflow.research_runtime.stage_one_closeout import (
    STAGE_ONE_CLOSEOUT_COMMAND,
    _completion_manifest_sha256,
    evaluate_stage_one_closeout,
    finalize_stage_one_closeout,
    route_after_stage_one_closure,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


def _run_input() -> dict:
    return {
        "teamId": "challenge-stage-one-team",
        "projectId": "challenge-stage-one-project",
        "questionId": "SCI-091",
        "researchBriefHash": "1" * 64,
        "datasetRefs": ["fixture://challenge/stage-one"],
        "metricContract": {"primary": "quality", "direction": "maximize"},
        "constraintSnapshot": {"formalWrites": False},
        "competitionRuleRef": "fixture://challenge/rules",
        "competitionRuleVersion": "2026",
        "trackAndRubricSnapshot": {"track": "1A", "blockingRules": []},
        "researchObjectiveContract": {
            "question": "Can evidence-grounded generation improve the hypothesis?",
            "falsifiableOutcome": "The grounded hypothesis is not better.",
        },
        "sourcePolicy": {"minimumPrimarySources": 2, "requireCounterEvidence": True},
        "budgetPolicy": {
            "tokens": 100000,
            "toolCalls": 120,
            "wallClockSeconds": 14400,
            "experiments": 0,
            "computeUnits": 0,
            "maxParallelTasks": 3,
            "maxRetries": 2,
        },
        "stopPolicy": {"maxNoImprovementRounds": 2, "stopOnBudgetExhaustion": True},
        "environmentSnapshotRef": "fixture://challenge/environment",
        "modelRoutingPolicy": {"reasoning": "qwen", "extraction": "qwen"},
        "evaluationContract": {
            "minimumClaimEvidenceCoverage": 0.9,
            "requiredSeeds": [11],
        },
        "stageOneCompletionPolicy": load_stage_one_completion_policy().to_dict(),
        "createdBy": "stage-one-closeout-test",
    }


def _definition_for(schema_version: str):
    return next(
        resolve_definition_by_version_id(identity.workflowVersionId)
        for identity in registered_identities("challenge-cup-research")
        if resolve_definition_by_version_id(identity.workflowVersionId).schemaVersion
        == schema_version
    )


def _receipt(stage: str, run_id: str) -> dict:
    return ModelInvocationReceipt.from_invocation(
        receipt_id=f"receipt-{stage}",
        run_id=run_id,
        node_run_id=f"nr-{stage}",
        scope={
            "questionId": "SCI-091",
            "runId": run_id,
            "stageId": stage,
            "modelPolicySha256": "2" * 64,
        },
        provider="dashscope",
        model="qwen3.6-plus",
        model_version="2026-08",
        requested_model="qwen3.6-plus",
        status=ModelInvocationStatus.SUCCEEDED,
        request_content={"stage": stage},
        response_content={"stage": stage, "status": "ok"},
        started_at_ms=100,
        finished_at_ms=110,
        token_usage={"inputTokens": 10, "outputTokens": 10, "totalTokens": 20},
        evidence_locator={"kind": "workflow-ledger", "ref": f"receipt://{stage}"},
    ).to_dict()


def _approved_gate() -> dict:
    return {
        "required": True,
        "decision": "approved",
        "rationale": "The stage-one proposal is accepted.",
        "reviewer": "human-reviewer",
        "decided_at": "2026-09-01T00:00:00Z",
    }


def _manifest(kind: str, *, node_run_id: str, input_hash: str) -> dict:
    return {
        "artifactId": f"{kind}:{kind}-artifact",
        "contentHash": (kind.encode("utf-8").hex() + "0" * 64)[:64],
        "schemaVersion": "1.0.0",
        "producerNodeRunId": node_run_id,
        "producerAttempt": 1,
        "inputSnapshotHash": input_hash,
        "configHash": "3" * 64,
        "environmentSnapshotHash": "4" * 64,
        "toolVersionHash": "5" * 64,
        "sourceArtifactIds": [],
        "cacheDisposition": "produced",
        "createdAt": "2026-09-01T00:00:00Z",
    }


def _g1_matrix_evidence() -> dict[str, tuple[str, ...]]:
    return {
        requirement_id: tuple(f"{kind}:{kind}-artifact" for kind in kinds)
        for requirement_id, kinds in G1_REQUIRED_EVIDENCE_KINDS.items()
    }


def _payloads(run_id: str) -> dict[str, dict]:
    policy = load_stage_one_completion_policy()
    payloads = {
        f"{kind}:{kind}-artifact": {"status": "accepted"}
        for kind in policy.requiredArtifactKinds
    }
    payloads["hypothesis_set:hypothesis_set-artifact"] = {
        "selection": {"human_gate": _approved_gate()},
        "modelInvocationReceipts": [_receipt("generation", run_id)],
    }
    payloads["dimension_reviews:dimension_reviews-artifact"] = {
        "modelInvocationReceipts": [_receipt("review", run_id)]
    }
    payloads["feedback_iterations:feedback_iterations-artifact"] = {
        "modelInvocationReceipts": [_receipt("revision", run_id)]
    }
    payloads["stage1_research_plan:stage1_research_plan-artifact"] = {
        "proposal_only": True,
        "human_gate": _approved_gate(),
    }
    payloads["competition_alignment:competition_alignment-artifact"] = {
        "status": "accepted",
        "officialRequirementMatrix": matrix_to_dict(
            evaluate_stage_one_requirement_matrix(_g1_matrix_evidence()),
            scope_id=policy.scopeId,
        ),
    }
    return payloads


def _stage_one_record(run_id: str = "run-stage-one") -> dict:
    policy = load_stage_one_completion_policy()
    definition = _definition_for("2.1.0")
    identity = definition_identity(definition)
    payloads = _payloads(run_id)
    manifests = [
        _manifest(kind, node_run_id=f"nr-{kind}", input_hash="1" * 64)
        for kind in policy.requiredArtifactKinds
    ]
    return {
        "runId": run_id,
        "workflowId": definition.workflowId,
        "questionId": "SCI-091",
        "workflowVersionId": identity.workflowVersionId,
        "structureHash": identity.structureHash,
        "inputSnapshot": {"stageOneCompletionPolicy": policy.to_dict()},
        "artifactManifests": manifests,
        "artifactPayloads": payloads,
        "humanTasks": [
            {"taskId": "gate-knowledge", "status": "resolved_accept", "decision": "accept"}
        ],
        "nodeRuns": [],
    }


def test_closeout_evidence_is_only_ready_until_catalog_approval() -> None:
    record = _stage_one_record()

    outcome = evaluate_stage_one_closeout(record, node_id="hypothesis_design")

    assert outcome is not None
    assert outcome.status == "program_review_required"
    assert outcome.accepted is False
    assert outcome.completion_state == ""
    assert set(outcome.artifact_refs) == {
        item["artifactId"] for item in record["artifactManifests"]
    }
    assert set(outcome.receipt_stages) == {"generation", "review", "revision"}
    assert outcome.human_gate_count >= 2


def test_persisted_program_manifest_cannot_self_assert_terminal_acceptance() -> None:
    record = _stage_one_record()
    policy = load_stage_one_completion_policy()
    manifest = {
        "schemaVersion": 1,
        "manifestKind": "stage_one_completion",
        "workflowRunId": record["runId"],
        "questionId": record["questionId"],
        "policySha256": policy.policySha256,
        "programRecordId": f"{record['questionId']}:{record['runId']}",
        "programReviewStatus": "approved",
        "sourceResultPackageHash": "a" * 64,
        "canonicalPackageHash": "b" * 64,
        "officialModelCall": True,
        "receiptStatus": "passed",
        "humanGates": {"allApproved": True, "approvedCount": 4},
    }
    manifest["manifestSha256"] = _completion_manifest_sha256(manifest)
    record["stageOneCompletionManifest"] = manifest

    outcome = evaluate_stage_one_closeout(record, node_id="hypothesis_design")

    assert outcome is not None
    assert outcome.accepted is False
    assert outcome.status == "program_review_required"
    assert outcome.completion_state == ""
    assert outcome.completion_manifest_sha256 == ""


def test_fresh_program_handoff_is_required_for_terminal_acceptance() -> None:
    record = _stage_one_record()
    handoff = {
        "workflowRunId": record["runId"],
        "questionId": record["questionId"],
        "recordId": f"{record['questionId']}:{record['runId']}",
        "reviewStatus": "approved",
        "outputSha256": "e" * 64,
        "sourceResultPackageHash": "a" * 64,
        "resultPackage": {"canonicalHash": "b" * 64},
        "officialModelCall": True,
        "receiptStatus": "passed",
        "humanGates": {"allApproved": True, "approvedCount": 4},
    }

    outcome = evaluate_stage_one_closeout(
        record,
        node_id="hypothesis_design",
        program_handoff=handoff,
    )

    assert outcome is not None
    assert outcome.accepted is True
    assert outcome.completion_state == "STAGE1_G1_ACCEPTED"
    assert outcome.program_record_id == handoff["recordId"]


def test_finalize_rechecks_program_authority_before_terminal_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _stage_one_record()
    record.update(
        {
            "teamId": "challenge-stage-one-team",
            "status": "waiting_human",
            "stageOneCloseout": {"status": "program_review_required"},
            "systemActions": [
                {"command": STAGE_ONE_CLOSEOUT_COMMAND, "status": "pending_human"}
            ],
            "nodeRuns": [
                {
                    "nodeId": "hypothesis_design",
                    "nodeRunId": "nr-hypothesis-design",
                    "attempt": 1,
                    "status": "succeeded",
                    "inputSnapshotHash": "1" * 64,
                }
            ],
        }
    )
    store = WorkflowRunStore(tmp_path / "runs")
    stored = store.create_run(record)
    approved = {
        "status": "idempotent",
        "workflowRunId": stored["runId"],
        "questionId": stored["questionId"],
        "recordId": f"{stored['questionId']}:{stored['runId']}",
        "reviewStatus": "approved",
        "outputSha256": "e" * 64,
        "sourceResultPackageHash": "a" * 64,
        "resultPackage": {"canonicalHash": "b" * 64},
        "officialModelCall": True,
        "receiptStatus": "passed",
        "humanGates": {"allApproved": True, "approvedCount": 4},
    }
    monkeypatch.setattr(
        program_candidate_handoff,
        "handoff_result_package_to_challenge_program",
        lambda **_kwargs: approved,
    )
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store

    monkeypatch.setattr(
        workflow_artifact_store,
        "put_workflow_artifact",
        lambda *_args, **_kwargs: {},
    )

    finalized = finalize_stage_one_closeout(
        store,
        record=stored,
        payload={"idempotencyKey": "finalize-stage-one"},
    )

    assert finalized["status"] == "succeeded"
    assert finalized["completionState"] == "STAGE1_G1_ACCEPTED"
    assert finalized["stageOneCloseout"]["accepted"] is True
    assert finalized["formalCloseoutEnqueued"] is False
    assert finalized["stageOneCompletionManifest"]["programRecordId"] == approved["recordId"]
    assert finalized["stageOneCompletionManifestRef"].startswith(
        "stage_one_completion_manifest:"
    )
    assert finalized["systemActions"][0]["status"] == "succeeded"


def test_stage_one_package_registers_review_required_without_node_seventeen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _stage_one_record()
    record.update(
        {
            "teamId": "challenge-stage-one-team",
            "projectId": "challenge-stage-one-project",
            "status": "waiting_human",
            "stageOneCloseout": {
                "status": "program_review_required",
                "artifactRefs": [item["artifactId"] for item in record["artifactManifests"]],
            },
            "nodeRuns": [
                {
                    "nodeId": "hypothesis_design",
                    "nodeRunId": "nr-hypothesis-design",
                    "attempt": 1,
                    "status": "succeeded",
                    "inputSnapshotHash": "1" * 64,
                }
            ],
        }
    )
    store = WorkflowRunStore(tmp_path / "runs")
    stored = store.create_run(record)
    monkeypatch.setattr(
        result_package_system_adapter,
        "build_proposal_result_package_base",
        lambda _record: {"factChainHash": "f" * 64},
    )
    package = {
        "packageId": "rrp-v2-stage-one",
        "factChainHash": "f" * 64,
        "contentHash": "c" * 64,
    }
    monkeypatch.setattr(
        result_package_system_adapter,
        "build_challenge_result_package_v2",
        lambda **_kwargs: package,
    )
    from core.web.services.team_workflow.research_runtime import (
        artifact_readback_registry,
        workflow_artifact_store,
    )

    monkeypatch.setattr(
        artifact_readback_registry,
        "load_scoped_artifact_payload",
        lambda *_args, **_kwargs: {"payload": {"objective": "bounded plan"}},
    )
    writes: list[dict] = []
    monkeypatch.setattr(
        workflow_artifact_store,
        "put_workflow_artifact",
        lambda *_args, **kwargs: writes.append(kwargs) or {},
    )

    class _Manifest:
        artifactId = "research_result_package:stage-one"

        def to_dict(self):
            return {"artifactId": self.artifactId, "contentHash": "c" * 64}

    monkeypatch.setattr(
        result_package_system_adapter,
        "build_system_artifact",
        lambda **_kwargs: _Manifest(),
    )
    handoff = {
        "status": "registered",
        "reviewStatus": "review_required",
        "workflowRunId": stored["runId"],
    }
    monkeypatch.setattr(
        program_candidate_handoff,
        "handoff_result_package_to_challenge_program",
        lambda **_kwargs: handoff,
    )

    result = result_package_system_adapter.execute_stage_one_package_action(
        store,
        record=stored,
        payload={"idempotencyKey": "build-stage-one-package"},
    )

    assert result["programCandidateHandoff"]["reviewStatus"] == "review_required"
    updated = store.get_run(stored["runId"])
    assert updated is not None
    assert updated["status"] == "waiting_human"
    assert "completionState" not in updated
    assert updated["resultPackageRef"] == "research_result_package:stage-one"
    assert not any(item["nodeId"] == "result_package" for item in updated["nodeRuns"])
    assert {item["kind"] for item in writes} == {"research_plan", "research_result_package"}
    assert node_command_capabilities(
        updated, "hypothesis_design"
    )[0]["command"] == "finalize_stage_one"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda record: record["artifactManifests"].pop(),
            "stage_one_artifact_missing",
        ),
        (
            lambda record: record["artifactPayloads"][
                "feedback_iterations:feedback_iterations-artifact"
            ].clear(),
            "stage_one_receipt_missing",
        ),
        (
            lambda record: record["artifactPayloads"][
                "stage1_research_plan:stage1_research_plan-artifact"
            ]["human_gate"].update({"decision": "pending"}),
            "stage_one_human_gate_not_approved",
        ),
        (
            lambda record: record["nodeRuns"].append(
                {"nodeId": "protocol_design", "status": "ready"}
            ),
            "stage_one_phase_two_attempt_exists",
        ),
    ],
)
def test_closeout_evidence_fails_closed(mutation, code: str) -> None:
    record = _stage_one_record()
    mutation(record)

    with pytest.raises(NodeExecutionError) as exc:
        evaluate_stage_one_closeout(record, node_id="hypothesis_design")

    assert exc.value.code == code


def test_non_stage_one_run_keeps_existing_completion_path() -> None:
    record = _stage_one_record()
    record["inputSnapshot"].pop("stageOneCompletionPolicy")

    assert evaluate_stage_one_closeout(record, node_id="hypothesis_design") is None


def test_checkpoint_route_stops_only_for_accepted_stage_one_state() -> None:
    route = route_after_stage_one_closure("protocol_design")

    assert route(ChallengeCupState()) == "protocol_design"
    assert route(
        ChallengeCupState(stage_one_completion_state="STAGE1_G1_ACCEPTED")
    ) == END


def test_node_completion_waits_for_program_review_without_phase_two_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = _definition_for("2.1.0")
    monkeypatch.setattr(
        knowledge_rollout,
        "creation_workflow_definition",
        lambda: (definition, definition_identity(definition)),
    )
    service = ResearchWorkflowRuntimeService(
        run_store=WorkflowRunStore(tmp_path / "runs"),
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        idempotency_key="stage-one-closeout",
    )
    node_order = [
        "problem_understanding",
        "source_finding",
        "source_extraction",
        "evidence_relations",
        "knowledge_ingestion",
        "knowledge_handoff",
    ]
    checkpoint_id = run["langGraph"]["checkpointId"]
    completed: list[str] = []
    for node_id in node_order:
        completed.append(node_id)
        checkpoint_id, next_ids = advance_checkpoint(
            str(tmp_path / "checkpoints.sqlite"),
            thread_id=run["threadId"],
            checkpoint_id=checkpoint_id,
            completed_node_id=node_id,
            state_patch={
                "current_node_id": node_id,
                "completed_node_ids": list(completed),
            },
            definition=definition,
        )
    assert next_ids == ["hypothesis_design"]

    policy = load_stage_one_completion_policy()
    snapshot_hash = run["inputSnapshot"]["snapshotHash"]
    node_run_id = f"nr-{run['runId']}-hypothesis_design-a1"
    payloads = _payloads(run["runId"])
    persisted_kinds = [
        kind for kind in policy.requiredArtifactKinds if kind != "hypothesis_set"
    ]
    persisted_manifests = [
        _manifest(kind, node_run_id=f"nr-{kind}", input_hash=snapshot_hash)
        for kind in persisted_kinds
    ]
    service._store.update_run(
        run["runId"],
        {
            "status": "running",
            "runtimeCurrentNodeIds": ["hypothesis_design"],
            "completedNodeIds": completed,
            "nodeRuns": [
                {
                    "nodeRunId": node_run_id,
                    "nodeId": "hypothesis_design",
                    "attempt": 1,
                    "status": "running",
                    "inputSnapshotHash": snapshot_hash,
                    "actorType": "agent",
                    "artifactRefs": [],
                }
            ],
            "taskLeases": [
                {
                    "leaseId": "lease-stage-one",
                    "nodeRunId": node_run_id,
                    "status": "running",
                    "leaseOwner": "stage-one-worker",
                    "idempotencyKey": "start-stage-one",
                }
            ],
            "artifactManifests": persisted_manifests,
            "artifactPayloads": {
                item["artifactId"]: payloads[item["artifactId"]]
                for item in persisted_manifests
            },
            "humanTasks": [
                {
                    "taskId": "gate-knowledge",
                    "status": "resolved_accept",
                    "decision": "accept",
                }
            ],
            "langGraph": {**run["langGraph"], "checkpointId": checkpoint_id},
        },
    )
    monkeypatch.setattr(node_completion, "validate_artifact_quality", lambda *_a, **_k: (None, {}))
    incoming = _manifest(
        "hypothesis_set",
        node_run_id=node_run_id,
        input_hash=snapshot_hash,
    )

    completed_run = service.apply_node_command(
        run["runId"],
        "hypothesis_design",
        "complete_execution",
        payload={
            "idempotencyKey": "complete-stage-one",
            "leaseOwner": "stage-one-worker",
            "artifactManifests": [incoming],
            "artifactPayloads": {incoming["artifactId"]: payloads[incoming["artifactId"]]},
        },
    )

    assert completed_run["status"] == "waiting_human"
    assert "completionState" not in completed_run
    assert completed_run["runtimeCurrentNodeIds"] == []
    assert completed_run["completedNodeIds"][-1] == "hypothesis_design"
    assert not any(
        item["nodeId"] in policy.deferredNodeIds for item in completed_run["nodeRuns"]
    )
    closeout = completed_run["stageOneCloseout"]
    assert closeout["policySha256"] == policy.policySha256
    assert closeout["completionState"] == ""
    assert closeout["status"] == "program_review_required"
    assert closeout["accepted"] is False
    action = next(
        item
        for item in completed_run["systemActions"]
        if item["command"] == STAGE_ONE_CLOSEOUT_COMMAND
    )
    assert action["status"] == "pending_human"
    assert action["nodeId"] == "hypothesis_design"
    assert node_command_capabilities(
        completed_run, "hypothesis_design"
    )[0]["command"] == "build_stage_one_package"

    replay = service.apply_node_command(
        run["runId"],
        "hypothesis_design",
        "complete_execution",
        payload={
            "idempotencyKey": "complete-stage-one",
            "leaseOwner": "stage-one-worker",
            "artifactManifests": [deepcopy(incoming)],
            "artifactPayloads": {incoming["artifactId"]: payloads[incoming["artifactId"]]},
        },
    )
    assert replay["runVersion"] == completed_run["runVersion"]
    assert len(replay["systemActions"]) == 1


# ---------------------------------------------------------------------------
# Hypothesis-first chain launches: the closure demand must match the launch
# shape.  A chain launch structurally cannot produce stage1_research_plan /
# competition_alignment (no approved question authority exists to project) or
# dimension_reviews (rows cite claim-evidence ledger ids, not canonical
# artifact refs).  The shape gate waives exactly those kinds -- with persisted
# evidence -- so closeout cannot block them forever; a question-driven run is
# never waived.
# ---------------------------------------------------------------------------


_CHAIN_CLOSEOUT_TEAM = "team-closeout-shape"
_CHAIN_WAIVED_KINDS = (
    "stage1_research_plan",
    "competition_alignment",
    "dimension_reviews",
)


def _chain_shape_closeout_record() -> dict:
    """Stage-one closeout record in the chain-driven hypothesis-first shape."""
    record = _stage_one_record()
    record["artifactManifests"] = [
        item
        for item in record["artifactManifests"]
        if str(item.get("artifactId") or "").split(":", 1)[0] not in _CHAIN_WAIVED_KINDS
    ]
    for kind in _CHAIN_WAIVED_KINDS:
        record["artifactPayloads"].pop(f"{kind}:{kind}-artifact", None)
    # The chain shape attaches the review-stage receipt to the
    # feedback-iterations authority (dev rounds carry no per-stage receipts).
    record["artifactPayloads"]["feedback_iterations:feedback_iterations-artifact"][
        "modelInvocationReceipts"
    ].append(_receipt("review", record["runId"]))
    record["teamId"] = _CHAIN_CLOSEOUT_TEAM
    record["inputSnapshot"]["researchObjectiveContract"] = {"hypothesisFirst": True}
    return record


def _patch_chain_shape_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.web.services.team_workflow.research_runtime import question_launch
    from core.web.services.team_workflow.research_runtime import stage_one_shape_gate

    monkeypatch.setattr(question_launch, "_approved_details", lambda _team_id: {})
    monkeypatch.setattr(
        stage_one_shape_gate, "_accepted_round_rows_complete", lambda *_a, **_k: True
    )


def test_hypothesis_first_closeout_waives_unproducible_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closeout demands exactly what a chain launch can produce, no more."""
    record = _chain_shape_closeout_record()
    _patch_chain_shape_lookup(monkeypatch)

    outcome = evaluate_stage_one_closeout(record, node_id="hypothesis_design")

    assert outcome is not None
    assert outcome.status == "program_review_required"
    waived_refs = {f"{kind}:{kind}-artifact" for kind in _CHAIN_WAIVED_KINDS}
    assert waived_refs.isdisjoint(set(outcome.artifact_refs))
    assert set(outcome.receipt_stages) == {"generation", "review", "revision"}


def test_closeout_without_hypothesis_first_marker_stays_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the launch marker the full policy demand stays untouched."""
    record = _chain_shape_closeout_record()
    record["inputSnapshot"]["researchObjectiveContract"] = {"hypothesisFirst": False}
    _patch_chain_shape_lookup(monkeypatch)

    with pytest.raises(NodeExecutionError) as exc:
        evaluate_stage_one_closeout(record, node_id="hypothesis_design")

    assert exc.value.code == "stage_one_artifact_missing"
