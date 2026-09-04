from types import SimpleNamespace

import pytest

from core.web.services.team_workflow import challenge_phase_boundary, research_loop
from core.web.services.team_workflow.challenge_phase_boundary import (
    PhaseTwoLockedError,
    approve_current_phase_one_manifest,
    build_phase_one_manifest,
    get_challenge_phase_boundary_status,
    project_challenge_phase_boundary,
    record_phase_one_knowledge_applied_receipt,
    require_phase_two_activation_from_projection,
)
from core.web.services.team_workflow.challenge_program import (
    build_competition_program_projection,
)
from core.web.services.team_workflow.experiment_api import plan as experiment_plan


def _complete_summary(*, changed_hash: str = "") -> dict:
    results = [
        {
            "questionId": f"SCI-{index:03d}",
            "runId": f"run-{index:03d}",
            "outputSha256": changed_hash if index == 125 and changed_hash else f"sha-{index:03d}",
        }
        for index in range(1, 126)
    ]
    return {
        "completedQuestionIds": [item["questionId"] for item in results],
        "completedQuestionResults": results,
    }


def test_complete_catalog_is_content_ready_but_not_approved_or_phase_two_active():
    manifest = build_phase_one_manifest(_complete_summary())

    projection = project_challenge_phase_boundary(manifest=manifest)

    assert projection["phase1ContentReady"] is True
    assert projection["phase1Approved"] is False
    assert projection["phase1KnowledgePublished"] is False
    assert projection["phase1Complete"] is False
    assert projection["phase2Activated"] is False
    assert projection["knowledgePublication"]["status"] == "not_requested"
    with pytest.raises(PhaseTwoLockedError, match="phase_one_approval_required"):
        require_phase_two_activation_from_projection(projection)


def test_approval_without_matching_applied_knowledge_receipt_keeps_phase_two_locked():
    manifest = build_phase_one_manifest(_complete_summary())
    approval = {
        "status": "approved",
        "manifestSha256": manifest["manifestSha256"],
        "contentSha256": manifest["contentSha256"],
        "approvedBy": "operator-1",
    }

    projection = project_challenge_phase_boundary(
        manifest=manifest,
        approvals=[approval],
        knowledge_receipts=[
            {
                "status": "applied",
                "manifestSha256": manifest["manifestSha256"],
                "contentSha256": "different-content",
            }
        ],
    )

    assert projection["phase1Approved"] is True
    assert projection["phase1KnowledgePublished"] is False
    assert projection["phase1Complete"] is True
    assert projection["phase2Activated"] is False
    assert projection["knowledgePublication"]["status"] == "pending"
    with pytest.raises(PhaseTwoLockedError, match="phase_one_knowledge_receipt_required"):
        require_phase_two_activation_from_projection(projection)


def test_matching_operator_approval_and_applied_receipt_unlock_phase_two():
    manifest = build_phase_one_manifest(_complete_summary())
    reference = {
        "manifestSha256": manifest["manifestSha256"],
        "contentSha256": manifest["contentSha256"],
    }

    projection = project_challenge_phase_boundary(
        manifest=manifest,
        approvals=[{"status": "approved", "approvedBy": "operator-1", **reference}],
        knowledge_receipts=[{"status": "applied", "receiptId": "receipt-1", **reference}],
    )

    assert projection["phase1Approved"] is True
    assert projection["phase1KnowledgePublished"] is True
    assert projection["phase2Activated"] is True
    assert projection["knowledgePublication"]["status"] == "applied"
    require_phase_two_activation_from_projection(projection)


def test_content_change_invalidates_prior_whole_package_approval_and_receipt():
    original = build_phase_one_manifest(_complete_summary())
    changed = build_phase_one_manifest(_complete_summary(changed_hash="new-output-sha"))
    reference = {
        "manifestSha256": original["manifestSha256"],
        "contentSha256": original["contentSha256"],
    }

    projection = project_challenge_phase_boundary(
        manifest=changed,
        approvals=[{"status": "approved", "approvedBy": "operator-1", **reference}],
        knowledge_receipts=[{"status": "applied", "receiptId": "receipt-1", **reference}],
    )

    assert changed["manifestSha256"] != original["manifestSha256"]
    assert projection["phase1ContentReady"] is True
    assert projection["phase1Approved"] is False
    assert projection["phase2Activated"] is False


def test_program_projection_does_not_activate_phase_two_from_count_alone():
    summary = _complete_summary()
    projection = build_competition_program_projection(question_run_summary=summary)

    assert projection["fullCatalogResultSet"]["complete"] is True
    assert projection["executionPhase"]["phase1ContentReady"] is True
    assert projection["executionPhase"]["phase1Approved"] is False
    assert projection["executionPhase"]["phase1KnowledgePublished"] is False
    assert projection["executionPhase"]["phase1Complete"] is False
    assert projection["executionPhase"]["phase2Activated"] is False
    assert projection["directions"][1]["activated"] is False


def test_experiment_stage_start_checks_the_shared_phase_two_gate_first(monkeypatch):
    service = SimpleNamespace(
        _normalize_required_id=lambda value, _message: value,
        team_service=SimpleNamespace(get_team=lambda _team_id: {}),
        _normalize_stage_type=lambda value: value,
    )
    monkeypatch.setattr(research_loop, "_service", lambda: service)
    monkeypatch.setattr(
        challenge_phase_boundary,
        "require_phase_two_activation",
        lambda _team_id: (_ for _ in ()).throw(
            PhaseTwoLockedError("phase_two_locked: phase_one_approval_required")
        ),
    )

    with pytest.raises(PhaseTwoLockedError, match="phase_one_approval_required"):
        research_loop.start_research_stage_round(
            "team-1",
            {"stageType": "experiment", "programPhase": 2},
        )


def test_experiment_plan_creation_checks_the_shared_phase_two_gate_first(monkeypatch):
    service = SimpleNamespace(
        _normalize_required_id=lambda value, _message: value,
        team_service=SimpleNamespace(get_team=lambda _team_id: {}),
    )
    monkeypatch.setattr(experiment_plan, "_service", lambda: service)
    monkeypatch.setattr(
        challenge_phase_boundary,
        "require_phase_two_activation",
        lambda _team_id: (_ for _ in ()).throw(
            PhaseTwoLockedError("phase_two_locked: phase_one_approval_required")
        ),
    )

    with pytest.raises(PhaseTwoLockedError, match="phase_one_approval_required"):
        experiment_plan.create_experiment_plan("team-1", {"programPhase": 2})


def test_persisted_approval_is_idempotent_and_applied_receipt_closes_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(
        challenge_phase_boundary,
        "resolve_team_program_root",
        lambda _team_id: tmp_path,
    )
    summary = _complete_summary()

    approved = approve_current_phase_one_manifest(
        "team-1",
        operator_id="operator-1",
        question_run_summary=summary,
    )
    repeated = approve_current_phase_one_manifest(
        "team-1",
        operator_id="operator-1",
        question_run_summary=summary,
    )

    assert approved["phase1Approved"] is True
    assert repeated["approval"]["approvalId"] == approved["approval"]["approvalId"]
    manifest = approved["manifest"]
    published = record_phase_one_knowledge_applied_receipt(
        "team-1",
        {
            "receiptId": "knowledge-receipt-1",
            "proposalId": "proposal-1",
            "status": "applied",
            "manifestSha256": manifest["manifestSha256"],
            "contentSha256": manifest["contentSha256"],
        },
        question_run_summary=summary,
    )

    assert published["phase1KnowledgePublished"] is True
    assert published["phase2Activated"] is True
    reloaded = get_challenge_phase_boundary_status(
        "team-1",
        question_run_summary=summary,
    )
    assert reloaded["knowledgeReceipt"]["receiptId"] == "knowledge-receipt-1"


def test_team_scoped_program_projection_reads_persisted_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(
        challenge_phase_boundary,
        "resolve_team_program_root",
        lambda _team_id: tmp_path,
    )
    summary = {"teamId": "team-1", **_complete_summary()}
    approved = approve_current_phase_one_manifest(
        "team-1",
        operator_id="operator-1",
        question_run_summary=summary,
    )
    manifest = approved["manifest"]
    record_phase_one_knowledge_applied_receipt(
        "team-1",
        {
            "receiptId": "knowledge-receipt-1",
            "status": "applied",
            "manifestSha256": manifest["manifestSha256"],
            "contentSha256": manifest["contentSha256"],
        },
        question_run_summary=summary,
    )

    projection = build_competition_program_projection(question_run_summary=summary)

    assert projection["executionPhase"]["phase1Approved"] is True
    assert projection["executionPhase"]["phase1KnowledgePublished"] is True
    assert projection["executionPhase"]["phase2Activated"] is True
