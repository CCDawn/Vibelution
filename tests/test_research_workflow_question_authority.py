from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.research.competition.question_result_package import QuestionResultPackage
from core.research.competition.result_set import (
    CatalogScope,
    QuestionResult,
    compute_scope_hash,
)
from core.research.workflow.contracts import (
    ContractValidationError,
    WorkflowRunInputSnapshot,
)
from core.research.workflow.contracts.research_scope import (
    scope_hash_for,
    scope_locators_for,
)
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import team_service
from core.web.services.team_workflow import research_projects
from core.web.services.team_workflow.research_runtime import question_launch
from core.web.services.team_workflow.research_runtime import (
    service as runtime_service_module,
)
from core.web.services.team_workflow.research_runtime.runtime_factory import (
    build_workflow_runtime,
)
from core.web.services.team_workflow.research_runtime.service import (
    reset_research_workflow_runtime_service_for_tests,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore
from tests.test_catalog_execution_state_machine import _package


def _approved_detail(question_id: str = "SCI-096") -> dict:
    return {
        "teamId": "research-team",
        "questionId": question_id,
        "selectedRunId": "stage1-sci-096-v3",
        "record": {
            "questionId": question_id,
            "runId": "stage1-sci-096-v3",
            "schemaVersion": 2,
            "submissionEligible": True,
            "status": "approved",
            "humanGates": {
                "allApproved": True,
                "decisions": {
                    "H1_problem_understanding": "approved",
                    "H2_hypothesis_selection": "approved",
                    "H3_research_plan": "approved",
                    "H4_external_output": "approved",
                },
            },
            "validation": {
                "schemaValidation": "passed",
                "citationValidation": "passed",
                "officialModelCall": True,
            },
        },
        "output": {
            "schema_version": 2,
            "identity": {
                "catalog_id": "science-125-questions-2021",
                "question_id": question_id,
                "question_en": "How does the brain retrieve memories?",
            },
            "classification": {
                "domain": "neuroscience",
                "specialization_profile_id": "SPEC-COMP-INFO-NEURO-v1",
            },
            "scope": {
                "theme_id": "theme-sci-096",
                "campaign_id": "campaign-sci-096",
                "research_project_id": "project-sci-096",
                "memory_scope": "same_theme",
            },
            "problem_understanding": {"scope": "只讨论可证伪的记忆提取机制。"},
            "research_plan": {"failure_criteria": "无法区分"},
            "result_classification": {
                "status": "approved",
                "actual_execution": False,
                "classification": "proposal_only",
                "final_summary": {"next_validation_step": "执行对照。"},
            },
            "review": {"human_review_status": "passed", "question_review_digest_ids": []},
            "submission": {"eligible": True, "projection_version": "1.0-review.1", "blockers": []},
        },
        "artifact": {"sha256": "a" * 64, "immutable": True},
    }


def _safety_limits() -> dict:
    return {
        "stageTokens": {
            "knowledge_collection": 250000,
            "experiment_design": 250000,
            "execution_iteration": 250000,
        },
        "toolCalls": 300,
        "wallClockSeconds": 21600,
        "maxRetries": 2,
    }


def _package_bound_record(tmp_path: Path) -> dict:
    package = _package(CatalogScope.from_tracked_resources(), "SCI-096")
    package_path = tmp_path / "question-result-package.json"
    package_path.write_text(
        json.dumps(package.to_dict(), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    receipt_refs = QuestionResult.from_package(package).manifest_entry()["receipts"]
    return {
        "recordId": "SCI-096:run-sci-096-r1",
        "questionId": "SCI-096",
        "runId": "run-sci-096-r1",
        "schemaVersion": 2,
        "submissionEligible": True,
        "status": "approved",
        "humanGates": {
            "allApproved": True,
            "decisions": {
                "H1_problem_understanding": "approved",
                "H2_hypothesis_selection": "approved",
                "H3_research_plan": "approved",
                "H4_external_output": "approved",
            },
        },
        "validation": {
            "schemaValidation": "passed",
            "citationValidation": "passed",
            "officialModelCall": True,
            "modelInvocationReceipts": "passed",
        },
        "modelInvocationReceiptRefs": receipt_refs,
        "resultPackage": {
            "schemaVersion": package.schema_version,
            "packageId": package.package_id,
            "canonicalHash": package.canonical_hash,
            "idempotencyKey": package.idempotency_key,
            "modelPolicySha256": package.model_policy["policySha256"],
            "locator": str(package_path),
        },
    }


def _replace_record_package(
    record: dict,
    tmp_path: Path,
    package: QuestionResultPackage,
    *,
    filename: str,
) -> dict:
    replaced = deepcopy(record)
    package_path = tmp_path / filename
    package_path.write_text(
        json.dumps(package.to_dict(), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    replaced["modelInvocationReceiptRefs"] = QuestionResult.from_package(
        package
    ).manifest_entry()["receipts"]
    replaced["resultPackage"] = {
        "schemaVersion": package.schema_version,
        "packageId": package.package_id,
        "canonicalHash": package.canonical_hash,
        "idempotencyKey": package.idempotency_key,
        "modelPolicySha256": package.model_policy["policySha256"],
        "locator": str(package_path),
    }
    return replaced


def test_formal_record_requires_canonical_package_and_matching_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _package_bound_record(tmp_path)

    assert question_launch._formal_record_eligible(record) is True

    missing_package = deepcopy(record)
    missing_package.pop("resultPackage")
    assert question_launch._formal_record_eligible(missing_package) is False

    mismatched_refs = deepcopy(record)
    mismatched_refs["modelInvocationReceiptRefs"]["generation"]["receipt_id"] = "forged"
    assert question_launch._formal_record_eligible(mismatched_refs) is False

    failed_receipt_validation = deepcopy(record)
    failed_receipt_validation["validation"]["modelInvocationReceipts"] = "failed"
    assert question_launch._formal_record_eligible(failed_receipt_validation) is False

    mismatched_metadata = deepcopy(record)
    mismatched_metadata["resultPackage"]["schemaVersion"] = 1
    assert question_launch._formal_record_eligible(mismatched_metadata) is False
    mismatched_metadata = deepcopy(record)
    mismatched_metadata["resultPackage"]["packageId"] = "pkg-forged"
    assert question_launch._formal_record_eligible(mismatched_metadata) is False

    wrong_question_package = _package(
        CatalogScope.from_tracked_resources(), "SCI-091"
    )
    wrong_question_record = _replace_record_package(
        record,
        tmp_path,
        wrong_question_package,
        filename="wrong-question-result-package.json",
    )
    assert question_launch._formal_record_eligible(wrong_question_record) is False

    wrong_run_payload = deepcopy(
        _package(CatalogScope.from_tracked_resources(), "SCI-096").to_dict()
    )
    wrong_run_payload.pop("canonical_sha256")
    wrong_run_payload.pop("idempotency_key")
    wrong_run_payload["package_id"] = "pkg-sci-096-r2"
    wrong_run_payload["run_id"] = "run-sci-096-r2"
    for receipt in wrong_run_payload["model_invocation_receipts"].values():
        receipt["runId"] = "run-sci-096-r2"
        receipt["nodeRunId"] = f"{receipt['nodeRunId']}-r2"
        receipt["scope"]["runId"] = "run-sci-096-r2"
    wrong_run_package = QuestionResultPackage.create(wrong_run_payload)
    wrong_run_record = _replace_record_package(
        record,
        tmp_path,
        wrong_run_package,
        filename="wrong-run-result-package.json",
    )
    assert question_launch._formal_record_eligible(wrong_run_record) is False

    alternate_scope = CatalogScope(
        catalog_id="science-125-questions-alternate",
        catalog_version="1",
        catalog_sha256="e" * 64,
        scope_hash=compute_scope_hash(
            "science-125-questions-alternate",
            "1",
            "e" * 64,
        ),
    )
    with monkeypatch.context() as scope_patch:
        scope_patch.setattr(
            CatalogScope,
            "from_tracked_resources",
            classmethod(lambda _cls: alternate_scope),
        )
        alternate_scope_package = _package(alternate_scope, "SCI-096")
    alternate_scope_record = _replace_record_package(
        record,
        tmp_path,
        alternate_scope_package,
        filename="alternate-scope-result-package.json",
    )
    assert question_launch._formal_record_eligible(alternate_scope_record) is False


def _patch_approved_question(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_receipt_refs = {
        stage_id: {
            "receipt_id": f"fixture-{stage_id}",
            "node_run_id": f"fixture-node-{stage_id}",
            "evidence_locator": {
                "kind": "fixture",
                "evidenceId": f"fixture-evidence-{stage_id}",
                "outputRef": f"fixture://{stage_id}",
                "outputSha256": "a" * 64,
            },
            "evidence_locator_sha256": "b" * 64,
        }
        for stage_id in ("generation", "review", "revision")
    }
    fixture_package = {
        "schemaVersion": 2,
        "packageId": "fixture-question-result-package",
        "canonicalHash": "c" * 64,
        "idempotencyKey": "fixture-idempotency-key",
        "modelPolicySha256": "d" * 64,
        "locator": "fixture://question-result-package",
    }
    original_formal_record_eligible = question_launch._formal_record_eligible

    def fixture_formal_record_eligible(record: dict) -> bool:
        enriched = dict(record)
        enriched.setdefault("resultPackage", fixture_package)
        enriched.setdefault("modelInvocationReceiptRefs", fixture_receipt_refs)
        validation = dict(enriched.get("validation") or {})
        validation.setdefault("modelInvocationReceipts", "passed")
        enriched["validation"] = validation
        return original_formal_record_eligible(enriched)

    monkeypatch.setattr(
        question_launch,
        "_package_bound_model_invocation_receipt_refs",
        lambda _record: fixture_receipt_refs,
    )
    monkeypatch.setattr(
        question_launch,
        "_formal_record_eligible",
        fixture_formal_record_eligible,
    )
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {
            "completedQuestionIds": ["SCI-096"],
            "completedQuestionResults": [
                {
                    "questionId": "SCI-096",
                    "runId": "stage1-sci-096-v3",
                    "schemaVersion": 2,
                    "submissionEligible": True,
                    "status": "approved",
                    "humanGates": {
                        "allApproved": True,
                        "decisions": {
                            "H1_problem_understanding": "approved",
                            "H2_hypothesis_selection": "approved",
                            "H3_research_plan": "approved",
                            "H4_external_output": "approved",
                        },
                    },
                    "validation": {
                        "schemaValidation": "passed",
                        "citationValidation": "passed",
                        "officialModelCall": True,
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(
        question_launch,
        "get_challenge_question_run_detail",
        lambda _team_id, question_id, *, run_id="": _approved_detail(question_id),
    )
    monkeypatch.setattr(
        question_launch,
        "ensure_challenge_question_project",
        lambda _team_id, **_kwargs: {"project": {"projectId": "challenge-sci-096"}},
    )
    monkeypatch.setattr(
        question_launch,
        "get_theme_activation",
        lambda _team_id, theme_id: {
            "themeId": theme_id,
            "status": "active",
            "campaignId": (
                "cc-campaign-gpu-operator-001"
                if theme_id == "cc-gpu-operator-001"
                else "cc-campaign-neural-spike-001"
            ),
            "activatedBy": "operator",
            "activatedAt": "2026-08-18T00:00:00Z",
            "activationRef": "research-experiment://EXP-GPU-OPERATOR-001",
        },
    )


def _patch_team_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.web.services.team_service.assert_team_exists",
        lambda team_id: str(team_id or "").strip(),
    )


def _create_research_team(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    team = team_service.create_team(name="research-team")
    assert team["teamId"] == "research-team"


def test_launch_options_and_frozen_input_derive_from_one_approved_question(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_research_team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)

    options = question_launch.list_question_launch_options("research-team")
    run_input = question_launch.build_question_run_input(
        "research-team",
        question_id="SCI-096",
        safety_limits=_safety_limits(),
    )

    by_id = {item["questionId"]: item for item in options["questions"]}
    assert len(options["questions"]) == 125
    assert by_id["SCI-001"]["source"] == "catalog"
    assert by_id["SCI-001"]["launchable"] is True
    assert by_id["SCI-096"] == {
        "questionId": "SCI-096",
        "title": "How does the brain retrieve memories?",
        "scope": "只讨论可证伪的记忆提取机制。",
        "domain": "neuroscience",
        "catalogId": "science-125-questions-2021",
        "reviewRunId": "stage1-sci-096-v3",
        "artifactSha256": "a" * 64,
        "source": "approved_artifact",
        "launchable": True,
    }
    assert run_input["projectId"] == "challenge-sci-096"
    assert run_input["researchBriefHash"] == "a" * 64
    assert run_input["datasetRefs"] == [
        "challenge-question-artifact://science-125-questions-2021/SCI-096/stage1-sci-096-v3/" + "a" * 64
    ]
    assert run_input["researchObjectiveContract"]["question"] == "How does the brain retrieve memories?"
    assert run_input["budgetPolicy"]["stageBudgets"]["execution_iteration"]["tokens"] == 250000
    assert set(run_input["modelRoutingPolicy"].values()) == {"relay_openai/gpt-5.6-luna"}
    assert run_input["competitionProgramSnapshot"]["programContractVersion"] == "2.2.0"
    assert run_input["competitionProgramSnapshot"]["fullCatalogPolicyVersion"] == "1.2.0"
    assert run_input["competitionProgramSnapshot"]["catalogQuestionCount"] == 125
    assert run_input["competitionProgramSnapshot"]["questionSchemaVersion"] == 2
    assert run_input["competitionProgramSnapshot"]["directionMode"] == "a_plus_b"
    assert len(run_input["competitionProgramSnapshot"]["directions"]) == 2
    assert run_input["constraintSnapshot"]["competitionProgramSnapshot"] == run_input["competitionProgramSnapshot"]
    assert "projectId" not in options["questions"][0]


def test_new_question_input_freezes_typed_research_and_catalog_scopes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_research_team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)

    run_input = question_launch.build_question_run_input(
        "research-team",
        question_id="SCI-096",
        safety_limits=_safety_limits(),
    )

    scope = run_input["researchScopeEnvelope"]
    assert scope["question"] == "SCI-096"
    assert scope["agentId"] == "operator"
    assert scope["mode"] == "platform"
    assert len(scope["scopeHash"]) == 64
    assert scope["scopeHash"] in scope["artifactLocator"]
    assert scope["scopeHash"] in scope["ledgerRoot"]
    assert scope["scopeHash"] in scope["cacheKey"]
    assert run_input["catalogScope"] == CatalogScope.from_tracked_resources().to_dict()

    frozen = WorkflowRunInputSnapshot.from_dict(
        {
            **run_input,
            "workflowVersionId": "wv-test",
            "agentBindingSnapshot": [{"nodeId": "source_finding", "agentId": "agent-source"}],
            "createdAt": "2026-08-23T00:00:00Z",
        }
    )
    assert frozen.researchScopeEnvelope == scope
    assert frozen.catalogScope == run_input["catalogScope"]
    assert frozen.to_dict()["researchScopeEnvelope"] == scope
    assert frozen.to_dict()["catalogScope"] == run_input["catalogScope"]


def test_typed_scope_snapshot_rejects_tampering_and_partial_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_research_team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    run_input = question_launch.build_question_run_input(
        "research-team",
        question_id="SCI-096",
        safety_limits=_safety_limits(),
    )
    base = {
        **run_input,
        "workflowVersionId": "wv-test",
        "agentBindingSnapshot": [{"nodeId": "source_finding", "agentId": "agent-source"}],
        "createdAt": "2026-08-23T00:00:00Z",
    }

    tampered_scope = {
        **base,
        "researchScopeEnvelope": {
            **base["researchScopeEnvelope"],
            "scopeHash": "0" * 64,
        },
    }
    with pytest.raises(ContractValidationError, match="researchScopeEnvelope"):
        WorkflowRunInputSnapshot.from_dict(tampered_scope)

    case_tampered_scope = dict(base["researchScopeEnvelope"])
    case_tampered_scope["question"] = "sci-096"
    case_tampered_scope["scopeHash"] = scope_hash_for(
        program=case_tampered_scope["program"],
        theme=case_tampered_scope["theme"],
        campaign=case_tampered_scope["campaign"],
        question=case_tampered_scope["question"],
        branch=case_tampered_scope["branch"],
        workflow=case_tampered_scope["workflow"],
        agent_id=case_tampered_scope["agentId"],
        mode=case_tampered_scope["mode"],
    )
    case_tampered_scope.update(
        scope_locators_for(
            program=case_tampered_scope["program"],
            theme=case_tampered_scope["theme"],
            campaign=case_tampered_scope["campaign"],
            question=case_tampered_scope["question"],
            branch=case_tampered_scope["branch"],
            agent_id=case_tampered_scope["agentId"],
            scope_hash=case_tampered_scope["scopeHash"],
        )
    )
    with pytest.raises(ContractValidationError, match="question must match"):
        WorkflowRunInputSnapshot.from_dict(
            {**base, "researchScopeEnvelope": case_tampered_scope}
        )

    tampered_catalog = {
        **base,
        "catalogScope": {
            **base["catalogScope"],
            "scope_hash": "0" * 64,
        },
    }
    with pytest.raises(ContractValidationError, match="catalogScope"):
        WorkflowRunInputSnapshot.from_dict(tampered_catalog)

    partial = dict(base)
    partial.pop("catalogScope")
    with pytest.raises(ContractValidationError, match="catalogScope"):
        WorkflowRunInputSnapshot.from_dict(partial)


def test_legacy_run_input_snapshot_without_typed_scopes_remains_readable() -> None:
    payload = {
        "teamId": "legacy-team",
        "projectId": "legacy-project",
        "questionId": "legacy-question",
        "workflowVersionId": "legacy-workflow",
        "researchBriefHash": "a" * 64,
        "datasetRefs": ["fixture://legacy"],
        "metricContract": {"primary": "coverage"},
        "constraintSnapshot": {},
        "competitionRuleRef": "legacy-rule",
        "competitionRuleVersion": "1",
        "trackAndRubricSnapshot": {"track": "legacy"},
        "researchObjectiveContract": {"question": "legacy"},
        "sourcePolicy": {"minimumPrimarySources": 1},
        "budgetPolicy": {"tokens": 1},
        "stopPolicy": {"stopOnBudgetExhaustion": True},
        "environmentSnapshotRef": "fixture://legacy-env",
        "modelRoutingPolicy": {"reasoning": "fixture"},
        "evaluationContract": {"minimumClaimEvidenceCoverage": 0.0},
        "agentBindingSnapshot": [{"nodeId": "source_finding", "agentId": "legacy-agent"}],
        "createdBy": "legacy",
        "createdAt": "2026-08-22T00:00:00Z",
    }
    snapshot = WorkflowRunInputSnapshot.from_dict(payload)
    assert snapshot.researchScopeEnvelope == {}
    assert snapshot.catalogScope == {}
    assert "researchScopeEnvelope" not in snapshot.to_dict()
    assert "catalogScope" not in snapshot.to_dict()


def test_question_launch_rejects_unknown_questions_and_invalid_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_research_team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)

    catalog_seed = question_launch.build_question_run_input(
        "research-team",
        question_id="SCI-097",
        safety_limits=_safety_limits(),
    )
    with pytest.raises(question_launch.QuestionLaunchError) as missing_question:
        question_launch.build_question_run_input(
            "research-team",
            question_id="SCI-999",
            safety_limits=_safety_limits(),
        )
    with pytest.raises(question_launch.QuestionLaunchError) as unsafe_budget:
        question_launch.build_safety_budget_policy(
            {**_safety_limits(), "toolCalls": 601}
        )

    assert catalog_seed["questionId"] == "SCI-097"
    assert catalog_seed["researchScopeEnvelope"]["question"] == "SCI-097"
    assert catalog_seed["catalogScope"] == CatalogScope.from_tracked_resources().to_dict()
    assert catalog_seed["constraintSnapshot"]["launchSource"] == "catalog"
    assert catalog_seed["constraintSnapshot"]["formalWrites"] is False
    assert "catalog_seed_not_submission_eligible" in catalog_seed["trackAndRubricSnapshot"]["blockingRules"]
    assert missing_question.value.code == "challenge_question_not_launchable"
    assert unsafe_budget.value.code == "invalid_safety_limits"


def test_attach_question_run_checkpoints_uses_latest_run() -> None:
    questions = [
        {"questionId": "SCI-003", "title": "Is the Riemann hypothesis true?"},
        {"questionId": "SCI-004", "title": "Are there more color pigments to discover?"},
    ]
    attached = question_launch.attach_question_run_checkpoints(
        questions,
        [
            {
                "runId": "run-old",
                "questionId": "SCI-003",
                "status": "blocked",
                "activeNodeId": "source_finding",
                "updatedAtMs": 1,
            },
            {
                "runId": "run-new",
                "questionId": "SCI-003",
                "status": "waiting_human",
                "runtimeCurrentNodeIds": ["protocol_design"],
                "updatedAtMs": 9,
            },
        ],
    )

    assert attached[0]["checkpoint"]["runId"] == "run-new"
    assert attached[0]["checkpoint"]["currentNodeId"] == "protocol_design"
    assert attached[0]["checkpoint"]["currentNodeLabel"] == "协议设计"
    assert attached[0]["checkpoint"]["completedCount"] == 6
    assert attached[0]["checkpoint"]["resumable"] is True
    assert attached[0]["checkpoint"]["totalSteps"] == 16
    assert attached[1]["checkpoint"] is None

    finished = question_launch.attach_question_run_checkpoints(
        [{"questionId": "SCI-003"}],
        [
            {
                "runId": "run-iso",
                "questionId": "SCI-003",
                "status": "succeeded",
                "runtimeCurrentNodeIds": ["result_package"],
                "updatedAt": "2026-08-19T01:00:00Z",
            }
        ],
    )
    assert finished[0]["checkpoint"]["runId"] == "run-iso"
    assert finished[0]["checkpoint"]["resumable"] is False
    assert finished[0]["checkpoint"]["completedCount"] == 16


def test_attach_question_run_checkpoints_keeps_prior_success() -> None:
    """A failed retry must not erase an earlier succeeded run's artifacts view."""
    attached = question_launch.attach_question_run_checkpoints(
        [{"questionId": "SCI-003"}],
        [
            {
                "runId": "run-won",
                "questionId": "SCI-003",
                "status": "succeeded",
                "runtimeCurrentNodeIds": ["result_package"],
                "updatedAtMs": 1,
            },
            {
                "runId": "run-retry",
                "questionId": "SCI-003",
                "status": "failed",
                "runtimeCurrentNodeIds": ["source_finding"],
                "updatedAtMs": 9,
            },
        ],
    )
    checkpoint = attached[0]["checkpoint"]
    assert checkpoint["runId"] == "run-won"
    assert checkpoint["status"] == "succeeded"
    assert checkpoint["completedCount"] == 16
    assert checkpoint["resumable"] is False

    # An in-flight retry still surfaces as running/resumable.
    inflight = question_launch.attach_question_run_checkpoints(
        [{"questionId": "SCI-003"}],
        [
            {
                "runId": "run-won",
                "questionId": "SCI-003",
                "status": "succeeded",
                "runtimeCurrentNodeIds": ["result_package"],
                "updatedAtMs": 1,
            },
            {
                "runId": "run-retry",
                "questionId": "SCI-003",
                "status": "running",
                "runtimeCurrentNodeIds": ["protocol_design"],
                "updatedAtMs": 9,
            },
        ],
    )
    live = inflight[0]["checkpoint"]
    assert live["runId"] == "run-retry"
    assert live["status"] == "running"
    assert live["resumable"] is True

    # Without any success the latest failure keeps the failed view but the
    # deepest progress ever reached must not regress.
    deep = question_launch.attach_question_run_checkpoints(
        [{"questionId": "SCI-003"}],
        [
            {
                "runId": "run-deep",
                "questionId": "SCI-003",
                "status": "failed",
                "runtimeCurrentNodeIds": ["controlled_run"],
                "updatedAtMs": 1,
            },
            {
                "runId": "run-shallow",
                "questionId": "SCI-003",
                "status": "failed",
                "runtimeCurrentNodeIds": ["source_finding"],
                "updatedAtMs": 9,
            },
        ],
    )
    regressed = deep[0]["checkpoint"]
    assert regressed["runId"] == "run-shallow"
    assert regressed["status"] == "failed"
    assert regressed["completedCount"] > 1


def test_launch_options_overlay_live_checkpoints(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_approved_question(monkeypatch)
    _patch_team_exists(monkeypatch)
    detail_calls: list[tuple[str, str]] = []
    original_detail = question_launch.get_challenge_question_run_detail

    def _count_detail(team_id: str, question_id: str, *, run_id: str = "") -> dict:
        detail_calls.append((team_id, question_id))
        return original_detail(team_id, question_id, run_id=run_id)

    monkeypatch.setattr(question_launch, "get_challenge_question_run_detail", _count_detail)
    monkeypatch.setattr(
        question_launch,
        "list_experiment_launch_options",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launch-options must not load deep-experiment snapshots")
        ),
    )
    service = reset_research_workflow_runtime_service_for_tests(
        run_store=WorkflowRunStore(tmp_path / "runs"),
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )

    class _Query:
        def list_runs(self, *, team_id: str, workflow_id: str) -> dict:
            assert team_id == "research-team"
            assert workflow_id == CHALLENGE_CUP_WORKFLOW_ID
            return {
                "runs": [
                    {
                        "runId": "run-live",
                        "questionId": "SCI-001",
                        "status": "running",
                        "runtimeCurrentNodeIds": ["source_finding"],
                        "updatedAtMs": 42,
                    }
                ]
            }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.formal_read_runtime.get_query_service",
        lambda: _Query(),
    )

    payload = service.get_question_launch_options(team_id="research-team")
    by_id = {item["questionId"]: item for item in payload["questions"]}
    assert len(payload["questions"]) == 125
    assert payload["experiments"] == []
    assert detail_calls == []
    assert by_id["SCI-096"]["source"] == "catalog"
    assert by_id["SCI-001"]["checkpoint"]["runId"] == "run-live"
    assert by_id["SCI-001"]["checkpoint"]["currentNodeLabel"] == "资料寻找"
    assert by_id["SCI-001"]["checkpoint"]["resumable"] is True
    assert by_id["SCI-002"]["checkpoint"] is None


def test_canonical_question_project_collision_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(research_projects.team_service, "get_team", lambda _team_id: {})
    monkeypatch.setattr(
        research_projects,
        "_load_store",
        lambda _team_id: {
            "projects": [
                {
                    "projectId": "challenge-sci-096",
                    "challengeQuestionId": "SCI-097",
                }
            ],
            "activeProjectId": "legacy-default",
        },
    )

    with pytest.raises(research_projects.ResearchProjectQuestionMismatchError):
        research_projects.ensure_challenge_question_project(
            "research-team",
            question_id="SCI-096",
            title="How does the brain retrieve memories?",
            topic="只讨论可证伪的记忆提取机制。",
        )


def test_create_endpoint_forbids_client_authored_contract_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    _create_research_team(tmp_path, monkeypatch)
    reset_research_workflow_runtime_service_for_tests(
        run_store=WorkflowRunStore(tmp_path / "runs"),
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    formal_runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite",
        checkpoint_path=tmp_path / "formal-checkpoints.sqlite",
    )
    request.addfinalizer(formal_runtime.close)
    canonical_input = question_launch.build_question_run_input
    _patch_approved_question(monkeypatch)
    _patch_team_exists(monkeypatch)
    monkeypatch.setattr(
        runtime_service_module,
        "build_question_run_input",
        lambda team_id, **kwargs: canonical_input(
            team_id,
            question_id=str(kwargs["question_id"]),
            safety_limits=kwargs["safety_limits"],
        ),
    )
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    options = client.get(
        f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/launch-options",
        params={"teamId": "research-team"},
    )

    rejected = client.post(
        f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/runs",
        json={
            "teamId": "research-team",
            "projectId": "operator-chosen-project",
            "questionId": "SCI-096",
            "researchBriefHash": "operator-authored",
            "safetyLimits": _safety_limits(),
            "idempotencyKey": "question-authority-1",
        },
    )
    accepted = client.post(
        f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/runs",
        json={
            "teamId": "research-team",
            "questionId": "SCI-096",
            "safetyLimits": _safety_limits(),
            "idempotencyKey": "question-authority-1",
        },
    )

    assert options.status_code == 200
    question_ids = [item["questionId"] for item in options.json()["questions"]]
    assert "SCI-001" in question_ids
    assert "SCI-096" in question_ids
    assert len(question_ids) == 125
    assert options.json()["experiments"] == []
    assert rejected.status_code == 422
    assert accepted.status_code == 201
    body = accepted.json()
    assert body["projectId"] == "challenge-sci-096"
    assert body["questionId"] == "SCI-096"
    assert "researchBriefHash" not in body


def _isolate_research_projects_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(research_projects.team_service, "get_team", lambda _team_id: {})
    monkeypatch.setattr(research_projects.team_service, "assert_team_exists", lambda _team_id: None)
    monkeypatch.setattr(
        research_projects,
        "team_workspace_root",
        lambda team_id: tmp_path / "teams" / str(team_id),
    )
    monkeypatch.setattr(research_projects, "_record_project_event", lambda *args, **kwargs: None)


def test_experiment_options_stay_visible_when_questions_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionResults": []},
    )
    monkeypatch.setattr(question_launch, "get_theme_activation", lambda _team_id, _theme_id: {})
    monkeypatch.setattr(question_launch, "_dev_authorization_ready", lambda _team_id: True)

    options = question_launch.list_experiment_launch_options("research-team")
    experiments = options["experiments"]

    assert [item["questionId"] for item in experiments] == ["SCI-091", "SCI-096"]
    assert [item["experimentId"] for item in experiments] == [
        "EXP-GPU-OPERATOR-001",
        "EXP-NEURAL-SPIKE-001",
    ]
    for item in experiments:
        assert item["activated"] is False
        assert item["activationStatus"] == "not_activated"
        assert item["activationAllowed"] is True
        assert item["questionResultApproved"] is False
        assert item["launchable"] is False
        assert item["nextAction"] == "activate_campaign"
        assert "question result is not formally approved" in item["blockers"]


def test_experiment_activation_refuses_unconfirmed_or_dev_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_research_projects_store(tmp_path, monkeypatch)
    monkeypatch.setattr(question_launch, "_dev_authorization_ready", lambda _team_id: False)

    with pytest.raises(question_launch.QuestionLaunchError) as not_ready:
        question_launch.activate_experiment_campaign(
            "research-team",
            experiment_id="EXP-GPU-OPERATOR-001",
            confirmed=True,
        )
    assert not_ready.value.code == "experiment_activation_not_allowed"

    monkeypatch.setattr(question_launch, "_dev_authorization_ready", lambda _team_id: True)
    with pytest.raises(question_launch.QuestionLaunchError) as unconfirmed:
        question_launch.activate_experiment_campaign(
            "research-team",
            experiment_id="EXP-GPU-OPERATOR-001",
            confirmed=False,
        )
    assert unconfirmed.value.code == "experiment_activation_confirmation_required"

    with pytest.raises(question_launch.QuestionLaunchError) as unknown:
        question_launch.activate_experiment_campaign(
            "research-team",
            experiment_id="EXP-NOPE",
            confirmed=True,
        )
    assert unknown.value.code == "deep_experiment_not_found"


def test_experiment_activation_succeeds_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_research_projects_store(tmp_path, monkeypatch)
    monkeypatch.setattr(question_launch, "_dev_authorization_ready", lambda _team_id: True)

    first = question_launch.activate_experiment_campaign(
        "research-team",
        experiment_id="EXP-GPU-OPERATOR-001",
        confirmed=True,
    )
    second = question_launch.activate_experiment_campaign(
        "research-team",
        experiment_id="EXP-GPU-OPERATOR-001",
        confirmed=True,
    )

    assert first["experimentId"] == "EXP-GPU-OPERATOR-001"
    assert first["status"] == "active"
    assert first["themeId"] == "cc-gpu-operator-001"
    assert first["campaignId"] == "cc-campaign-gpu-operator-001"
    assert first["activationHash"] == second["activationHash"]
    assert (
        research_projects.get_theme_activation(
            "research-team", "cc-gpu-operator-001"
        )["status"]
        == "active"
    )

    options = question_launch.list_experiment_launch_options("research-team")
    activated = next(item for item in options["experiments"] if item["experimentId"] == "EXP-GPU-OPERATOR-001")
    assert activated["activated"] is True
    assert activated["activationStatus"] == "active"
    assert activated["activationAllowed"] is False
    assert activated["activatedAt"]


def test_deep_experiment_run_requires_activated_campaign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_research_team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    approved_keys = [
        "H1_problem_understanding",
        "H2_hypothesis_selection",
        "H3_research_plan",
        "H4_external_output",
    ]
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {
            "completedQuestionIds": ["SCI-096", "SCI-091"],
            "completedQuestionResults": [
                {
                    "questionId": question_id,
                    "runId": f"stage1-{question_id.lower()}-v1",
                    "schemaVersion": 2,
                    "submissionEligible": True,
                    "status": "approved",
                    "humanGates": {
                        "allApproved": True,
                        "decisions": {key: "approved" for key in approved_keys},
                    },
                    "validation": {
                        "schemaValidation": "passed",
                        "citationValidation": "passed",
                        "officialModelCall": True,
                    },
                }
                for question_id in ("SCI-096", "SCI-091")
            ],
        },
    )
    monkeypatch.setattr(question_launch, "get_theme_activation", lambda _team_id, _theme_id: {})

    for question_id in ("SCI-096", "SCI-091"):
        with pytest.raises(question_launch.QuestionLaunchError) as blocked:
            question_launch.build_question_run_input(
                "research-team",
                question_id=question_id,
                safety_limits=_safety_limits(),
            )
        assert blocked.value.code == "deep_experiment_campaign_not_activated"


def test_ordinary_approved_question_needs_no_campaign_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_research_team(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    approved_keys = [
        "H1_problem_understanding",
        "H2_hypothesis_selection",
        "H3_research_plan",
        "H4_external_output",
    ]
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {
            "completedQuestionIds": ["SCI-042"],
            "completedQuestionResults": [
                {
                    "questionId": "SCI-042",
                    "runId": "stage1-sci-042-v1",
                    "schemaVersion": 2,
                    "submissionEligible": True,
                    "status": "approved",
                    "humanGates": {
                        "allApproved": True,
                        "decisions": {key: "approved" for key in approved_keys},
                    },
                    "validation": {
                        "schemaValidation": "passed",
                        "citationValidation": "passed",
                        "officialModelCall": True,
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(
        question_launch,
        "get_challenge_question_run_detail",
        lambda _team_id, question_id, *, run_id="": _approved_detail(question_id),
    )
    monkeypatch.setattr(question_launch, "get_theme_activation", lambda _team_id, _theme_id: {})

    run_input = question_launch.build_question_run_input(
        "research-team",
        question_id="SCI-042",
        safety_limits=_safety_limits(),
    )
    assert run_input["questionId"] == "SCI-042"
    assert run_input["projectId"] == "challenge-sci-096"


def test_activate_experiment_endpoint_succeeds_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    reset_research_workflow_runtime_service_for_tests(
        run_store=WorkflowRunStore(tmp_path / "runs"),
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    formal_runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite",
        checkpoint_path=tmp_path / "formal-checkpoints.sqlite",
    )
    request.addfinalizer(formal_runtime.close)
    _isolate_research_projects_store(tmp_path, monkeypatch)
    monkeypatch.setattr(question_launch, "_dev_authorization_ready", lambda _team_id: True)
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    activated = client.post(
        f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/experiments/EXP-GPU-OPERATOR-001/activate",
        json={"teamId": "research-team", "confirmed": True},
    )
    assert activated.status_code == 200
    body = activated.json()
    assert body["experimentId"] == "EXP-GPU-OPERATOR-001"
    assert body["status"] == "active"
    assert body["themeId"] == "cc-gpu-operator-001"
    assert body["activationHash"]

    repeated = client.post(
        f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/experiments/EXP-GPU-OPERATOR-001/activate",
        json={"teamId": "research-team", "confirmed": True},
    )
    assert repeated.status_code == 200
    assert repeated.json()["activationHash"] == body["activationHash"]

    unconfirmed = client.post(
        f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/experiments/EXP-GPU-OPERATOR-001/activate",
        json={"teamId": "research-team", "confirmed": False},
    )
    assert unconfirmed.status_code == 422
    assert unconfirmed.json()["detail"]["code"] == "experiment_activation_confirmation_required"

    monkeypatch.setattr(question_launch, "_dev_authorization_ready", lambda _team_id: False)
    not_ready = client.post(
        f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/experiments/EXP-NEURAL-SPIKE-001/activate",
        json={"teamId": "research-team", "confirmed": True},
    )
    assert not_ready.status_code == 409
    assert not_ready.json()["detail"]["code"] == "experiment_activation_not_allowed"

    unknown = client.post(
        f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/experiments/EXP-NOPE/activate",
        json={"teamId": "research-team", "confirmed": True},
    )
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "deep_experiment_not_found"


def test_activate_experiment_endpoint_rejects_non_boolean_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    reset_research_workflow_runtime_service_for_tests(
        run_store=WorkflowRunStore(tmp_path / "runs"),
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    formal_runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite",
        checkpoint_path=tmp_path / "formal-checkpoints.sqlite",
    )
    request.addfinalizer(formal_runtime.close)
    _isolate_research_projects_store(tmp_path, monkeypatch)
    monkeypatch.setattr(question_launch, "_dev_authorization_ready", lambda _team_id: True)
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    for truthy_not_boolean in ("yes", "1", 1):
        rejected = client.post(
            f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/experiments/EXP-GPU-OPERATOR-001/activate",
            json={"teamId": "research-team", "confirmed": truthy_not_boolean},
        )
        assert rejected.status_code == 422
        detail = rejected.json()["detail"]
        assert isinstance(detail, list)
        assert any(
            "confirmed" in ".".join(str(part) for part in error.get("loc") or [])
            for error in detail
        )

    assert (
        research_projects.get_theme_activation(
            "research-team", "cc-gpu-operator-001"
        )
        == {}
    )

    activated = client.post(
        f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/experiments/EXP-GPU-OPERATOR-001/activate",
        json={"teamId": "research-team", "confirmed": True},
    )
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
