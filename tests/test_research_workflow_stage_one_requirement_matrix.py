"""Task 7 contracts for the official 3+7 direction-1A requirement matrix.

The matrix materializes contract section 2.5: every official requirement row
carries ``deliveryClass`` / ``coverageStatus`` / ``evidenceRefs`` /
``deferredOwner``, any unmet ``G1_REQUIRED`` row blocks stage-one G1, and
``direction1ASubmissionReady`` only aggregates to true once *every* delivery
class holds real evidence (counterexample 21: G1 acceptance alone must never
project as direction-1A submission ready).
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

import pytest

from core.research.competition.stage_one_completion_policy import (
    load_stage_one_completion_policy,
)
from core.research.competition.stage_one_requirement_matrix import (
    COVERAGE_EVIDENCED,
    COVERAGE_NOT_YET_EVIDENCED,
    DELIVERY_CLASS_G1_REQUIRED,
    DELIVERY_CLASS_PHASE2_USER,
    DELIVERY_CLASS_STAGE1_SCALE_OUT,
    DELIVERY_CLASS_SUBMISSION_PACKAGE,
    G1_REQUIRED_EVIDENCE_KINDS,
    REQUIREMENT_APPLICATION,
    REQUIREMENT_CORE_HYPOTHESIS,
    REQUIREMENT_PHASE2_EXPERIMENTS,
    REQUIREMENT_PLAN_EXECUTABILITY,
    REQUIREMENT_SCALE_OUT,
    REQUIREMENT_SUBMISSION_MATERIALS,
    REQUIREMENT_TECH_DEPTH,
    REQUIREMENT_TWO_ROUND_REVISION,
    STAGE_ONE_REQUIREMENT_MATRIX_KIND,
    STAGE_ONE_REQUIREMENT_MATRIX_SCHEMA_VERSION,
    StageOneRequirementItem,
    StageOneRequirementMatrixError,
    direction_1a_submission_ready,
    evaluate_stage_one_requirement_matrix,
    matrix_to_dict,
    not_yet_evidenced_ids,
    requirement_matrix_from_dict,
    stage_one_requirement_rows,
    unmet_g1_required,
)
from core.web.routes.team_workflows.hypothesis_first_state_models import (
    HypothesisFirstStateV2,
)
from core.web.services.team_workflow.research_runtime.hypothesis_first_state_v2 import (
    project_state_from_records,
)

def _refs(kind: str) -> str:
    return f"{kind}:team-a/source-run-a/{kind}-hash"


def _g1_evidence() -> dict[str, tuple[str, ...]]:
    return {
        requirement_id: tuple(_refs(kind) for kind in kinds)
        for requirement_id, kinds in G1_REQUIRED_EVIDENCE_KINDS.items()
    }


# ---------------------------------------------------------------------------
# Static rows: official 3 dimensions + 7 scoring points coverage (§2.5)
# ---------------------------------------------------------------------------


def test_static_rows_match_contract_delivery_table() -> None:
    rows = {row.requirementId: row for row in stage_one_requirement_rows()}

    assert set(rows) == {
        REQUIREMENT_CORE_HYPOTHESIS,
        REQUIREMENT_PLAN_EXECUTABILITY,
        REQUIREMENT_TWO_ROUND_REVISION,
        REQUIREMENT_SCALE_OUT,
        REQUIREMENT_TECH_DEPTH,
        REQUIREMENT_APPLICATION,
        REQUIREMENT_SUBMISSION_MATERIALS,
        REQUIREMENT_PHASE2_EXPERIMENTS,
    }
    assert rows[REQUIREMENT_CORE_HYPOTHESIS].deliveryClass == DELIVERY_CLASS_G1_REQUIRED
    assert (
        rows[REQUIREMENT_PLAN_EXECUTABILITY].deliveryClass
        == DELIVERY_CLASS_G1_REQUIRED
    )
    assert (
        rows[REQUIREMENT_TWO_ROUND_REVISION].deliveryClass
        == DELIVERY_CLASS_G1_REQUIRED
    )
    assert rows[REQUIREMENT_SCALE_OUT].deliveryClass == DELIVERY_CLASS_STAGE1_SCALE_OUT
    assert rows[REQUIREMENT_TECH_DEPTH].deliveryClass == DELIVERY_CLASS_SUBMISSION_PACKAGE
    assert (
        rows[REQUIREMENT_APPLICATION].deliveryClass == DELIVERY_CLASS_SUBMISSION_PACKAGE
    )
    assert (
        rows[REQUIREMENT_SUBMISSION_MATERIALS].deliveryClass
        == DELIVERY_CLASS_SUBMISSION_PACKAGE
    )
    assert rows[REQUIREMENT_PHASE2_EXPERIMENTS].deliveryClass == DELIVERY_CLASS_PHASE2_USER

    # Deferred rows always name an owner; G1 rows are owned by the current G1.
    for row in rows.values():
        if row.deliveryClass == DELIVERY_CLASS_G1_REQUIRED:
            assert row.deferredOwner == ""
        else:
            assert row.deferredOwner


def test_static_rows_cover_official_three_dimensions_and_seven_points() -> None:
    rows = stage_one_requirement_rows()

    dimensions = {
        row.officialDimension for row in rows if row.officialDimension
    }
    assert dimensions == {"科学价值", "技术深度", "应用潜力"}

    points = [
        point for row in rows for point in row.officialScoringPoints
    ]
    assert len(points) == 7
    assert len(set(points)) == 7
    assert set(points) == {
        "核心假设创新性与自洽性",
        "方案可落地验证性",
        "超级智能体或多智能体协作设计",
        "多模态大模型处理科学模态数据的成效",
        "实际场景问题支撑能力",
        "论文/专利成果转化潜力",
        "代码与结果可复现性",
    }


def test_g1_evidence_kinds_map_only_g1_rows() -> None:
    g1_rows = {
        row.requirementId
        for row in stage_one_requirement_rows()
        if row.deliveryClass == DELIVERY_CLASS_G1_REQUIRED
    }
    assert set(G1_REQUIRED_EVIDENCE_KINDS) == g1_rows
    for kinds in G1_REQUIRED_EVIDENCE_KINDS.values():
        assert kinds


# ---------------------------------------------------------------------------
# Evaluation: coverage status follows real evidence only
# ---------------------------------------------------------------------------


def test_evaluate_marks_g1_evidenced_and_other_classes_not_yet_evidenced() -> None:
    items = evaluate_stage_one_requirement_matrix(_g1_evidence())

    by_id = {item.requirementId: item for item in items}
    assert (
        by_id[REQUIREMENT_CORE_HYPOTHESIS].coverageStatus == COVERAGE_EVIDENCED
    )
    assert (
        by_id[REQUIREMENT_CORE_HYPOTHESIS].evidenceRefs
        == _g1_evidence()[REQUIREMENT_CORE_HYPOTHESIS]
    )
    assert (
        by_id[REQUIREMENT_PLAN_EXECUTABILITY].coverageStatus == COVERAGE_EVIDENCED
    )
    assert by_id[REQUIREMENT_TWO_ROUND_REVISION].coverageStatus == COVERAGE_EVIDENCED
    assert (
        by_id[REQUIREMENT_SCALE_OUT].coverageStatus == COVERAGE_NOT_YET_EVIDENCED
    )
    assert by_id[REQUIREMENT_SCALE_OUT].evidenceRefs == ()
    assert (
        by_id[REQUIREMENT_PHASE2_EXPERIMENTS].coverageStatus
        == COVERAGE_NOT_YET_EVIDENCED
    )
    assert direction_1a_submission_ready(items) is False
    assert unmet_g1_required(items) == ()
    assert set(not_yet_evidenced_ids(items)) == {
        REQUIREMENT_SCALE_OUT,
        REQUIREMENT_TECH_DEPTH,
        REQUIREMENT_APPLICATION,
        REQUIREMENT_SUBMISSION_MATERIALS,
        REQUIREMENT_PHASE2_EXPERIMENTS,
    }


def test_evaluate_without_evidence_keeps_every_row_not_yet_evidenced() -> None:
    items = evaluate_stage_one_requirement_matrix(None)

    assert all(item.coverageStatus == COVERAGE_NOT_YET_EVIDENCED for item in items)
    assert all(item.evidenceRefs == () for item in items)
    assert direction_1a_submission_ready(items) is False
    assert len(unmet_g1_required(items)) == 3


def _fully_evidenced_matrix() -> tuple[StageOneRequirementItem, ...]:
    return tuple(
        StageOneRequirementItem(
            requirementId=item.requirementId,
            requirement=item.requirement,
            officialDimension=item.officialDimension,
            officialScoringPoints=item.officialScoringPoints,
            deliveryClass=item.deliveryClass,
            coverageStatus=COVERAGE_EVIDENCED,
            evidenceRefs=(f"evidence://{item.requirementId}",),
            deferredOwner=item.deferredOwner,
        )
        for item in evaluate_stage_one_requirement_matrix(_g1_evidence())
    )


def test_evaluate_full_evidence_is_required_for_submission_ready() -> None:
    ready_items = _fully_evidenced_matrix()
    assert all(item.coverageStatus == COVERAGE_EVIDENCED for item in ready_items)
    assert all(item.evidenceRefs for item in ready_items)
    assert direction_1a_submission_ready(ready_items) is True
    assert unmet_g1_required(ready_items) == ()
    assert not_yet_evidenced_ids(ready_items) == ()


def test_evaluate_rejects_unknown_and_non_g1_evidence() -> None:
    with pytest.raises(StageOneRequirementMatrixError):
        evaluate_stage_one_requirement_matrix({"unknown_requirement": ("ref",)})
    with pytest.raises(StageOneRequirementMatrixError):
        evaluate_stage_one_requirement_matrix(
            {REQUIREMENT_PHASE2_EXPERIMENTS: ("evidence://fabricated",)}
        )
    with pytest.raises(StageOneRequirementMatrixError):
        evaluate_stage_one_requirement_matrix({REQUIREMENT_CORE_HYPOTHESIS: ()})


# ---------------------------------------------------------------------------
# Serialization: strict round trip and fail-closed parsing
# ---------------------------------------------------------------------------


def _serialized_matrix(
    items: tuple[StageOneRequirementItem, ...],
) -> dict[str, Any]:
    return matrix_to_dict(items, scope_id=load_stage_one_completion_policy().scopeId)


def test_matrix_round_trip_preserves_items_and_aggregate() -> None:
    payload = _serialized_matrix(evaluate_stage_one_requirement_matrix(_g1_evidence()))

    assert payload["schemaVersion"] == STAGE_ONE_REQUIREMENT_MATRIX_SCHEMA_VERSION
    assert payload["matrixKind"] == STAGE_ONE_REQUIREMENT_MATRIX_KIND
    assert payload["scopeId"] == "cc-xh-202619-stage1-hypothesis-v1"
    assert payload["direction1ASubmissionReady"] is False

    parsed = requirement_matrix_from_dict(payload)
    assert parsed == evaluate_stage_one_requirement_matrix(_g1_evidence())


def test_matrix_parse_rejects_drift_and_inconsistent_aggregates() -> None:
    base = _serialized_matrix(evaluate_stage_one_requirement_matrix(_g1_evidence()))

    unknown_field = deepcopy(base)
    unknown_field["predictedScore"] = 97
    with pytest.raises(StageOneRequirementMatrixError):
        requirement_matrix_from_dict(unknown_field)

    drifted_row = deepcopy(base)
    drifted_row["items"][0]["deliveryClass"] = DELIVERY_CLASS_PHASE2_USER
    with pytest.raises(StageOneRequirementMatrixError):
        requirement_matrix_from_dict(drifted_row)

    evidence_without_refs = deepcopy(base)
    evidence_without_refs["items"][0]["coverageStatus"] = COVERAGE_EVIDENCED
    evidence_without_refs["items"][0]["evidenceRefs"] = []
    with pytest.raises(StageOneRequirementMatrixError):
        requirement_matrix_from_dict(evidence_without_refs)

    wrong_aggregate = deepcopy(base)
    wrong_aggregate["direction1ASubmissionReady"] = True
    with pytest.raises(StageOneRequirementMatrixError):
        requirement_matrix_from_dict(wrong_aggregate)

    fabricated_ready = _serialized_matrix(_fully_evidenced_matrix())
    assert requirement_matrix_from_dict(fabricated_ready) is not None
    assert fabricated_ready["direction1ASubmissionReady"] is True


# ---------------------------------------------------------------------------
# Writer materialization into the competition_alignment artifact
# ---------------------------------------------------------------------------


def _canonical_stage_one_question_detail() -> dict[str, Any]:
    return {
        "record": {
            "schemaVersion": 2,
            "status": "approved",
            "questionId": "SCI-091",
            "runId": "question-run-1",
            "validation": {
                "schemaValidation": "passed",
                "citationValidation": "passed",
                "officialModelCall": True,
            },
        },
        "artifact": {"immutable": True, "sha256": "a" * 64},
        "output": {
            "schema_version": 2,
            "identity": {"question_id": "SCI-091", "catalog_id": "catalog-1"},
            "selection": {
                "selected_hypothesis_id": "hyp-a",
                "human_gate": {"decision": "approved"},
            },
            "hypotheses": [
                {"hypothesis_id": "hyp-a", "statement": "Canonical selected hypothesis"}
            ],
            "research_plan": {
                "proposal_only": True,
                "objective": "Test the selected hypothesis.",
                "human_gate": {"decision": "approved"},
            },
            "competition_result_view": {
                "problem_statement": "Canonical competition problem.",
                "rationale": "Why the selected hypothesis matters.",
                "technical_details": "Bounded technical approach.",
                "datasets": {"planned": ["dataset-a"], "used": ["not executed"]},
                "methods": ["planned method"],
                "experiments": ["planned experiment"],
                "results": ["not executed"],
                "references": ["source://canonical"],
                "paper_title": "Planned paper",
                "paper_abstract": "Proposal only.",
            },
        },
    }


def test_writer_materializes_requirement_matrix_into_alignment_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        stage_one_plan_artifact_writer as writer,
    )

    rows: list[dict[str, Any]] = []

    def fake_put(team_id: str, **kwargs):
        record = {
            "recordId": kwargs["artifact_identity"],
            "teamId": team_id,
            "kind": kwargs["kind"],
            "workflowRunId": kwargs["workflow_run_id"],
            "sourceCollectionRunId": kwargs["source_collection_run_id"],
            "contentHash": writer.canonical_sha256(kwargs["payload"]),
            "payload": kwargs["payload"],
        }
        rows.append(record)
        return record

    def fake_list(team_id: str, *, kind: str, workflow_run_id: str = "", **_):
        assert kind in (
            G1_REQUIRED_EVIDENCE_KINDS[REQUIREMENT_CORE_HYPOTHESIS]
            + G1_REQUIRED_EVIDENCE_KINDS[REQUIREMENT_TWO_ROUND_REVISION]
        )
        return [
            {
                "kind": kind,
                "workflowRunId": workflow_run_id,
                "sourceCollectionRunId": "source-authorities",
                "contentHash": hashlib.sha256(kind.encode("utf-8")).hexdigest(),
            }
        ]

    monkeypatch.setattr(writer, "put_workflow_artifact", fake_put)
    monkeypatch.setattr(writer, "list_workflow_artifacts", fake_list)

    result = writer.write_stage_one_plan_artifacts(
        team_id="team-requirement-matrix",
        workflow_run_id="workflow-requirement-matrix",
        node_run_id="node-requirement-matrix",
        question_id="SCI-091",
        selected_candidate_id="hyp-a",
        question_detail=_canonical_stage_one_question_detail(),
        source_collection_run_id="source-authorities",
    )

    assert result["status"] == "written"
    alignment = next(
        row["payload"] for row in rows if row["kind"] == "competition_alignment"
    )
    matrix = alignment["officialRequirementMatrix"]
    assert matrix["matrixKind"] == STAGE_ONE_REQUIREMENT_MATRIX_KIND
    assert matrix["direction1ASubmissionReady"] is False
    items = {item["requirementId"]: item for item in matrix["items"]}
    assert len(items) == 8
    # Every row carries the four §2.5 fields.
    for item in items.values():
        assert set(item) == {
            "requirementId",
            "requirement",
            "officialDimension",
            "officialScoringPoints",
            "deliveryClass",
            "coverageStatus",
            "evidenceRefs",
            "deferredOwner",
        }
    assert items[REQUIREMENT_CORE_HYPOTHESIS]["coverageStatus"] == COVERAGE_EVIDENCED
    assert items[REQUIREMENT_CORE_HYPOTHESIS]["evidenceRefs"] == [
        "{kind}://team-requirement-matrix/source-authorities/{sha}".format(
            kind=kind,
            sha=hashlib.sha256(kind.encode("utf-8")).hexdigest(),
        )
        for kind in G1_REQUIRED_EVIDENCE_KINDS[REQUIREMENT_CORE_HYPOTHESIS]
    ]
    plan_ref = items[REQUIREMENT_PLAN_EXECUTABILITY]["evidenceRefs"][0]
    assert plan_ref.startswith("stage1_research_plan://team-requirement-matrix/")
    assert items[REQUIREMENT_SCALE_OUT]["coverageStatus"] == COVERAGE_NOT_YET_EVIDENCED
    # The materialized matrix must parse back through the strict contract.
    assert requirement_matrix_from_dict(matrix) is not None


def test_writer_without_g1_store_evidence_keeps_rows_not_yet_evidenced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        stage_one_plan_artifact_writer as writer,
    )

    rows: list[dict[str, Any]] = []

    def fake_put(team_id: str, **kwargs):
        record = {
            "recordId": kwargs["artifact_identity"],
            "teamId": team_id,
            "kind": kwargs["kind"],
            "workflowRunId": kwargs["workflow_run_id"],
            "sourceCollectionRunId": kwargs["source_collection_run_id"],
            "contentHash": writer.canonical_sha256(kwargs["payload"]),
            "payload": kwargs["payload"],
        }
        rows.append(record)
        return record

    monkeypatch.setattr(writer, "put_workflow_artifact", fake_put)
    monkeypatch.setattr(writer, "list_workflow_artifacts", lambda *a, **k: [])

    result = writer.write_stage_one_plan_artifacts(
        team_id="team-requirement-matrix",
        workflow_run_id="workflow-requirement-matrix",
        node_run_id="node-requirement-matrix",
        question_id="SCI-091",
        selected_candidate_id="hyp-a",
        question_detail=_canonical_stage_one_question_detail(),
        source_collection_run_id="source-authorities",
    )

    assert result["status"] == "written"
    alignment = next(
        row["payload"] for row in rows if row["kind"] == "competition_alignment"
    )
    items = {
        item["requirementId"]: item
        for item in alignment["officialRequirementMatrix"]["items"]
    }
    # Only the plan row can be evidenced from the writer's own artifact.
    assert items[REQUIREMENT_PLAN_EXECUTABILITY]["coverageStatus"] == COVERAGE_EVIDENCED
    assert items[REQUIREMENT_CORE_HYPOTHESIS]["coverageStatus"] == (
        COVERAGE_NOT_YET_EVIDENCED
    )
    assert alignment["officialRequirementMatrix"]["direction1ASubmissionReady"] is False


# ---------------------------------------------------------------------------
# Closeout: unmet G1_REQUIRED rows block stage-one acceptance
# ---------------------------------------------------------------------------


def _closeout_record_with_matrix(
    matrix_items: tuple[StageOneRequirementItem, ...] | None,
) -> dict[str, Any]:
    from tests.test_research_workflow_stage_one_closeout import (
        _manifest,
        _payloads,
        _stage_one_record,
    )

    record = _stage_one_record(run_id="run-requirement-matrix")
    payloads = _payloads("run-requirement-matrix")
    if matrix_items is None:
        payloads["competition_alignment:competition_alignment-artifact"] = {
            "status": "accepted"
        }
    else:
        payloads["competition_alignment:competition_alignment-artifact"] = {
            "status": "accepted",
            "officialRequirementMatrix": _serialized_matrix(matrix_items),
        }
    record["artifactPayloads"] = payloads
    record["artifactManifests"] = [
        _manifest(kind, node_run_id=f"nr-{kind}", input_hash="1" * 64)
        for kind in load_stage_one_completion_policy().requiredArtifactKinds
    ]
    return record


def test_closeout_accepts_matrix_with_all_g1_rows_evidenced() -> None:
    from core.web.services.team_workflow.research_runtime.stage_one_closeout import (
        evaluate_stage_one_closeout,
    )

    record = _closeout_record_with_matrix(
        evaluate_stage_one_requirement_matrix(_g1_evidence())
    )

    outcome = evaluate_stage_one_closeout(record, node_id="hypothesis_design")

    assert outcome is not None
    assert outcome.status == "program_review_required"
    assert outcome.accepted is False


def test_closeout_blocks_when_matrix_is_missing() -> None:
    from core.web.services.team_workflow.research_runtime.node_execution_support import (
        NodeExecutionError,
    )
    from core.web.services.team_workflow.research_runtime.stage_one_closeout import (
        evaluate_stage_one_closeout,
    )

    record = _closeout_record_with_matrix(None)

    with pytest.raises(NodeExecutionError) as exc:
        evaluate_stage_one_closeout(record, node_id="hypothesis_design")

    assert exc.value.code == "stage_one_requirement_matrix_missing"


def test_closeout_blocks_when_g1_required_row_is_not_evidenced() -> None:
    from core.web.services.team_workflow.research_runtime.node_execution_support import (
        NodeExecutionError,
    )
    from core.web.services.team_workflow.research_runtime.stage_one_closeout import (
        evaluate_stage_one_closeout,
    )

    record = _closeout_record_with_matrix(
        evaluate_stage_one_requirement_matrix(None)
    )

    with pytest.raises(NodeExecutionError) as exc:
        evaluate_stage_one_closeout(record, node_id="hypothesis_design")

    assert exc.value.code == "stage_one_g1_requirement_not_evidenced"


# ---------------------------------------------------------------------------
# State V2 projection: G1 accepted is not direction-1A submission ready
# ---------------------------------------------------------------------------


def _projection_records() -> dict[str, Any]:
    return {
        "team_id": "team-1",
        "question_id": "SCI-001",
        "reset_boundary": None,
        "chain_records": [],
        "selection_records": [],
        "meeting_records": [],
        "digest_records": [],
        "decision_records": [],
        "hypothesis_round_records": [],
    }


def _state(requirement_matrix: dict[str, Any] | None) -> HypothesisFirstStateV2:
    return HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            **_projection_records(),
            requirement_matrix=requirement_matrix,
        )
    )


def test_state_v2_projects_default_matrix_as_not_ready() -> None:
    state = _state(None)

    assert state.direction1ASubmissionReady is False
    assert state.direction1aSubmission.source == "not_materialized"
    assert state.direction1aSubmission.submissionReady is False
    assert len(state.direction1aSubmission.g1RequiredUnmet) == 3
    assert len(state.direction1aSubmission.items) == 8


def test_state_v2_keeps_submission_false_after_g1_rows_are_evidenced() -> None:
    matrix = _serialized_matrix(evaluate_stage_one_requirement_matrix(_g1_evidence()))
    state = _state(matrix)

    # Counterexample 21: all G1_REQUIRED rows closed, yet scale-out,
    # submission-package and phase-two rows keep the direction-1A submission
    # projection explicitly not ready.
    assert state.direction1aSubmission.g1RequiredUnmet == []
    assert state.direction1ASubmissionReady is False
    assert state.direction1aSubmission.source == "competition_alignment"
    assert len(state.direction1aSubmission.notYetEvidenced) == 5


def test_state_v2_projects_ready_only_for_full_evidence_matrix() -> None:
    matrix = _serialized_matrix(_fully_evidenced_matrix())
    state = _state(matrix)

    assert state.direction1ASubmissionReady is True
    assert state.direction1aSubmission.submissionReady is True
    assert state.direction1aSubmission.notYetEvidenced == []
    assert state.direction1aSubmission.g1RequiredUnmet == []


def test_state_v2_rejects_malformed_matrix_payload_fail_closed() -> None:
    records = _projection_records()

    with pytest.raises(StageOneRequirementMatrixError):
        project_state_from_records(
            **records,
            requirement_matrix={"schemaVersion": 99},
        )
