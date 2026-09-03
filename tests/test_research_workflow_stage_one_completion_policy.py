from __future__ import annotations

import copy
from pathlib import Path

import pytest

from core.research.competition.catalog_execution import CatalogExecutionPlan
from core.research.competition.question_result_package import canonical_model_policy
from core.research.competition.real_control_batch import real_plan
from core.research.competition.stage_one_completion_policy import (
    StageOneCompletionPolicy,
    StageOneCompletionPolicyError,
    load_stage_one_completion_policy,
    stage_one_policy_snapshot_for,
)
from core.research.workflow.contracts import ContractValidationError
from core.research.workflow.contracts.run_input import WorkflowRunInputSnapshot
from core.research.workflow.definition_registry import (
    registered_identities,
    resolve_definition_by_version_id,
)
from core.web.services.team_workflow import challenge_cup_real_batch
from core.web.services.team_workflow.research_runtime import (
    catalog_run_authorization,
    run_creation,
)
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS, open_ledger_store

WORKFLOW_DEFINITION_ID = "challenge-cup-research@2.1.0"


def _registry_version(schema_version: str) -> str:
    return next(
        identity.workflowVersionId
        for identity in registered_identities("challenge-cup-research")
        if resolve_definition_by_version_id(identity.workflowVersionId).schemaVersion
        == schema_version
    )


WORKFLOW_VERSION_ID = _registry_version("2.1.0")


def _run_input_payload(policy: dict[str, object]) -> dict[str, object]:
    return {
        "teamId": "team-stage-one",
        "projectId": "project-stage-one",
        "questionId": "SCI-091",
        "workflowVersionId": WORKFLOW_VERSION_ID,
        "researchBriefHash": "brief-sha",
        "datasetRefs": ["catalog://SCI-091"],
        "metricContract": {"primary": "evidence_coverage"},
        "constraintSnapshot": {},
        "competitionRuleRef": "science-125-questions-2021",
        "competitionRuleVersion": "catalog-seed-v1",
        "trackAndRubricSnapshot": {"track": "direction-1a"},
        "researchObjectiveContract": {"question": "SCI-091"},
        "sourcePolicy": {"minimumPrimarySources": 3},
        "budgetPolicy": {"tokens": 1000},
        "stopPolicy": {"stopOnBudgetExhaustion": True},
        "environmentSnapshotRef": "catalog://SCI-091",
        "modelRoutingPolicy": {"modelPolicySha256": "a" * 64},
        "evaluationContract": {"minimumClaimEvidenceCoverage": 0.9},
        "agentBindingSnapshot": [{"nodeId": "problem_understanding"}],
        "createdBy": "operator",
        "createdAt": "2026-09-01T00:00:00Z",
        "stageOneCompletionPolicy": policy,
    }


def test_tracked_policy_is_exact_question_scope_contract() -> None:
    policy = load_stage_one_completion_policy()

    assert policy.scopeId == "cc-xh-202619-stage1-hypothesis-v1"
    assert policy.workflowDefinitionId == WORKFLOW_DEFINITION_ID
    assert policy.questionIds == ("SCI-003", "SCI-091")
    assert policy.closureNodeId == "hypothesis_design"
    assert policy.completionState == "STAGE1_G1_ACCEPTED"
    assert policy.allowPhaseTwoAdvance is False
    assert policy.deferredNodeIds[0] == "protocol_design"
    assert policy.deferredNodeIds[-1] == "result_package"
    assert len(policy.deferredNodeIds) == 10
    assert "core_hypothesis_coherence" in policy.requiredArtifactKinds
    assert policy.requiredReceiptStages == ("generation", "review", "revision")
    assert len(policy.policySha256) == 64
    assert StageOneCompletionPolicy.from_dict(policy.to_dict()) == policy


def test_policy_snapshot_only_applies_to_the_frozen_g1_identity() -> None:
    assert stage_one_policy_snapshot_for("SCI-003", WORKFLOW_DEFINITION_ID)
    assert stage_one_policy_snapshot_for("SCI-091", WORKFLOW_DEFINITION_ID)
    assert stage_one_policy_snapshot_for("SCI-042", WORKFLOW_DEFINITION_ID) is None
    assert stage_one_policy_snapshot_for("SCI-092", WORKFLOW_DEFINITION_ID) is None
    assert stage_one_policy_snapshot_for("SCI-091", "challenge-cup-research@3.0.0") is None


def test_run_input_snapshot_freezes_policy_and_rejects_tampering() -> None:
    policy = load_stage_one_completion_policy().to_dict()
    snapshot = WorkflowRunInputSnapshot.from_dict(_run_input_payload(policy))

    assert snapshot.stageOneCompletionPolicy == policy
    assert snapshot.to_dict()["stageOneCompletionPolicy"] == policy

    tampered = copy.deepcopy(policy)
    tampered["closureNodeId"] = "protocol_design"
    with pytest.raises(ContractValidationError, match="stageOneCompletionPolicy"):
        WorkflowRunInputSnapshot.from_dict(_run_input_payload(tampered))

    wrong_workflow = _run_input_payload(policy)
    wrong_workflow["workflowVersionId"] = _registry_version("3.0.0")
    with pytest.raises(ContractValidationError, match="workflowDefinitionId"):
        WorkflowRunInputSnapshot.from_dict(wrong_workflow)


def test_real_one_authorization_scope_requires_the_exact_tracked_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        challenge_cup_real_batch,
        "resolve_catalog_model_policy",
        lambda _team_id: canonical_model_policy(
            {
                "family": "qwen",
                "providerIds": ["dashscope"],
                "modelIds": ["qwen3-max"],
                "requireOfficialProvider": True,
            }
        ),
    )
    scope = challenge_cup_real_batch._batch_scope("team-stage-one", "real-1")
    policy = load_stage_one_completion_policy().to_dict()

    assert scope["stageOneCompletionPolicy"] == policy
    normalized = catalog_run_authorization._canonical_batch_scope(
        "real-1",
        scope,
        require_stage_one_policy=True,
    )
    assert normalized["stageOneCompletionPolicy"] == policy

    without_policy = dict(scope)
    without_policy.pop("stageOneCompletionPolicy")
    with pytest.raises(
        catalog_run_authorization.CatalogRunAuthorizationError,
        match="stage-one completion policy",
    ):
        catalog_run_authorization._canonical_batch_scope(
            "real-1",
            without_policy,
            require_stage_one_policy=True,
        )

    monkeypatch.setattr(
        challenge_cup_real_batch,
        "stage_one_policy_snapshot_for",
        lambda *_args: pytest.fail("non-G1 plans must not read stage-one policy"),
    )
    assert "stageOneCompletionPolicy" not in challenge_cup_real_batch._batch_scope(
        "team-stage-one",
        "real-5",
    )

    drifted_policy = copy.deepcopy(scope)
    drifted_policy["stageOneCompletionPolicy"]["policySha256"] = "0" * 64
    with pytest.raises(
        catalog_run_authorization.CatalogRunAuthorizationError,
        match="stage-one completion policy",
    ):
        catalog_run_authorization._canonical_batch_scope(
            "real-1",
            drifted_policy,
            require_stage_one_policy=True,
        )


def _single_question_plan(question_id: str) -> CatalogExecutionPlan:
    return CatalogExecutionPlan(
        plan_id="real-1",
        gate_id="G1",
        question_ids=(question_id,),
    )


def _patch_single_question_plan(
    monkeypatch: pytest.MonkeyPatch, question_id: str
) -> None:
    monkeypatch.setattr(
        challenge_cup_real_batch,
        "resolve_catalog_model_policy",
        lambda _team_id: canonical_model_policy(
            {
                "family": "qwen",
                "providerIds": ["dashscope"],
                "modelIds": ["qwen3-max"],
                "requireOfficialProvider": True,
            }
        ),
    )
    plan = _single_question_plan(question_id)
    monkeypatch.setattr(challenge_cup_real_batch, "real_plan", lambda _plan_id: plan)
    monkeypatch.setattr(catalog_run_authorization, "real_plan", lambda _plan_id: plan)


def test_policy_covered_plan_keeps_snapshot_and_authorization_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_single_question_plan(monkeypatch, "SCI-003")
    policy = load_stage_one_completion_policy().to_dict()

    scope = challenge_cup_real_batch._batch_scope("team-stage-one", "real-1")
    assert scope["stageOneCompletionPolicy"] == policy

    normalized = catalog_run_authorization._canonical_batch_scope(
        "real-1",
        scope,
        require_stage_one_policy=True,
    )
    assert normalized["stageOneCompletionPolicy"] == policy


def test_policy_out_of_scope_plan_gets_no_snapshot_and_fails_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_single_question_plan(monkeypatch, "SCI-042")
    policy = load_stage_one_completion_policy().to_dict()

    scope = challenge_cup_real_batch._batch_scope("team-stage-one", "real-1")
    assert "stageOneCompletionPolicy" not in scope

    with pytest.raises(
        catalog_run_authorization.CatalogRunAuthorizationError,
        match="does not cover the plan",
    ):
        catalog_run_authorization._canonical_batch_scope(
            "real-1",
            {**scope, "stageOneCompletionPolicy": policy},
            require_stage_one_policy=True,
        )


def test_stage_one_run_creation_requires_matching_authorization_policy() -> None:
    policy = load_stage_one_completion_policy().to_dict()
    run_input = _run_input_payload(policy)
    authorization = {"batchScope": {"stageOneCompletionPolicy": policy}}

    run_creation._require_stage_one_authorization_binding(run_input, authorization)

    with pytest.raises(
        run_creation.ResearchWorkflowError,
        match="stage-one completion policy authorization is required",
    ):
        run_creation._require_stage_one_authorization_binding(run_input, None)

    drifted = copy.deepcopy(authorization)
    drifted["batchScope"]["stageOneCompletionPolicy"]["policySha256"] = "0" * 64
    with pytest.raises(
        run_creation.ResearchWorkflowError,
        match="does not match",
    ):
        run_creation._require_stage_one_authorization_binding(run_input, drifted)


def test_policy_parser_rejects_unknown_fields() -> None:
    policy = load_stage_one_completion_policy().to_dict()
    policy["futureEscapeHatch"] = True

    with pytest.raises(StageOneCompletionPolicyError, match="unsupported fields"):
        StageOneCompletionPolicy.from_dict(policy)


def test_real_one_is_the_policy_question() -> None:
    assert tuple(real_plan("real-1").question_ids) == ("SCI-091",)


def _record_policy_covered_real_one_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        challenge_cup_real_batch,
        "resolve_catalog_model_policy",
        lambda _team_id: canonical_model_policy(
            {
                "family": "qwen",
                "providerIds": ["dashscope"],
                "modelIds": ["qwen3-max"],
                "requireOfficialProvider": True,
            }
        ),
    )
    scope = challenge_cup_real_batch._batch_scope("team-stage-one", "real-1")
    assert scope["questionIds"] == ["SCI-091"]
    assert scope["stageOneCompletionPolicy"] == load_stage_one_completion_policy().to_dict()

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        monkeypatch.setattr(
            catalog_run_authorization, "get_write_store", lambda: store
        )
        return catalog_run_authorization.record_catalog_run_authorization(
            "team-stage-one",
            plan_id="real-1",
            batch_scope=scope,
            approved_by="server-operator",
            readiness_evidence={"status": "READY", "basis": "report-v1"},
            approved_at_ms=FIXED_NOW_MS,
            require_model_policy=True,
            require_stage_one_policy=True,
        )
    finally:
        store.close()


def test_policy_question_outside_plan_questions_is_authorized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record_policy_covered_real_one_authorization(tmp_path, monkeypatch)

    # SCI-003 is not a real-1 plan question but the approved stage-one policy
    # scope covers it, so formal run creation for it must validate.
    assert catalog_run_authorization.validate_catalog_run_authorization(
        record,
        team_id="team-stage-one",
        plan_id="real-1",
        question_id="SCI-003",
        require_model_policy=True,
        require_stage_one_policy=True,
    )
    assert catalog_run_authorization.validate_catalog_run_authorization(
        record,
        team_id="team-stage-one",
        plan_id="real-1",
        question_id="SCI-091",
        require_model_policy=True,
        require_stage_one_policy=True,
    )


def test_question_outside_plan_and_policy_scope_stays_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record_policy_covered_real_one_authorization(tmp_path, monkeypatch)

    assert not catalog_run_authorization.validate_catalog_run_authorization(
        record,
        team_id="team-stage-one",
        plan_id="real-1",
        question_id="SCI-042",
        require_model_policy=True,
        require_stage_one_policy=True,
    )
