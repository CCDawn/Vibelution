from types import SimpleNamespace

import pytest

from core.web.services import (
    agent_directory_service,
    team_knowledge_service,
    team_service,
)
from core.web.services.team_workflow import challenge_phase_boundary, research_loop
from core.web.services.team_workflow.challenge_phase_boundary import (
    ChallengePhaseBoundaryError,
    PhaseTwoLockedError,
    approve_current_phase_one_manifest,
    build_phase_one_manifest,
    get_challenge_phase_boundary_status,
    project_challenge_phase_boundary,
    research_project_targets_challenge_phase_two,
    record_phase_one_knowledge_applied_receipt,
    require_phase_two_activation_from_projection,
)
from core.web.services.team_workflow.challenge_phase_knowledge_publisher import (
    load_published_phase_one_knowledge_package,
    publish_approved_phase_one_to_team_knowledge,
)
from core.web.services.team_workflow.challenge_program import (
    build_competition_program_projection,
)
from core.web.services.team_workflow.experiment_api import plan as experiment_plan
from core.web.services.team_workflow.research_runtime import (
    question_launch,
)


def _complete_summary(*, changed_hash: str = "") -> dict:
    results = [
        {
            "questionId": f"SCI-{index:03d}",
            "runId": f"run-{index:03d}",
            "outputSha256": changed_hash if index == 125 and changed_hash else f"sha-{index:03d}",
            "artifactPath": f"artifacts/SCI-{index:03d}.json",
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


def test_phase_one_manifest_is_not_ready_without_a_complete_artifact_binding():
    summary = _complete_summary()
    summary["completedQuestionResults"][-1]["artifactPath"] = ""

    manifest = build_phase_one_manifest(summary)

    assert manifest["questionCount"] == 125
    assert manifest["contentReady"] is False


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
        _trim_text=lambda value, **_kwargs: str(value or "").strip(),
        resolve_research_project_identity=lambda _team_id, _project_id: {
            "projectId": "ordinary-project",
            "name": "Ordinary experiment",
            "challengeQuestionId": "",
        },
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


def test_challenge_project_experiment_stage_cannot_hide_phase_two_intent(monkeypatch):
    service = SimpleNamespace(
        _normalize_required_id=lambda value, _message: value,
        team_service=SimpleNamespace(get_team=lambda _team_id: {}),
        _normalize_stage_type=lambda value: value,
        _trim_text=lambda value, **_kwargs: str(value or "").strip(),
        resolve_research_project_identity=lambda _team_id, project_id: {
            "projectId": project_id,
            "name": "SCI-091 benchmark",
            "challengeQuestionId": "SCI-091",
        },
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
            {
                "stageType": "experiment",
                "researchProjectId": "challenge-sci-091",
            },
        )


def test_experiment_plan_creation_checks_the_shared_phase_two_gate_first(monkeypatch):
    service = SimpleNamespace(
        _normalize_required_id=lambda value, _message: value,
        team_service=SimpleNamespace(get_team=lambda _team_id: {}),
        _trim_text=lambda value, **_kwargs: str(value or "").strip(),
        resolve_research_project_identity=lambda _team_id, _project_id: {
            "projectId": "ordinary-project",
            "name": "Ordinary experiment",
            "challengeQuestionId": "",
        },
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


def test_challenge_project_plan_cannot_hide_phase_two_intent(monkeypatch):
    service = SimpleNamespace(
        _normalize_required_id=lambda value, _message: value,
        team_service=SimpleNamespace(get_team=lambda _team_id: {}),
        _trim_text=lambda value, **_kwargs: str(value or "").strip(),
        resolve_research_project_identity=lambda _team_id, project_id: {
            "projectId": project_id,
            "name": "SCI-096 spike coding",
            "challengeQuestionId": "SCI-096",
        },
    )
    monkeypatch.setattr(experiment_plan, "_service", lambda: service)
    monkeypatch.setattr(
        challenge_phase_boundary,
        "require_phase_two_activation",
        lambda _team_id: (_ for _ in ()).throw(
            PhaseTwoLockedError("phase_two_locked: phase_one_knowledge_receipt_required")
        ),
    )

    with pytest.raises(
        PhaseTwoLockedError,
        match="phase_one_knowledge_receipt_required",
    ):
        experiment_plan.create_experiment_plan(
            "team-1",
            {"researchProjectId": "challenge-sci-096"},
        )


def test_only_declared_deep_experiment_projects_use_the_phase_two_boundary():
    assert research_project_targets_challenge_phase_two(
        {"projectId": "challenge-sci-091", "challengeQuestionId": "SCI-091"}
    )
    assert research_project_targets_challenge_phase_two(
        {"projectId": "challenge-sci-096", "challengeQuestionId": "sci-096"}
    )
    assert not research_project_targets_challenge_phase_two(
        {"projectId": "challenge-sci-020", "challengeQuestionId": "SCI-020"}
    )


def test_agent_declared_identity_cannot_freeze_an_experiment_plan(monkeypatch):
    service = SimpleNamespace(
        _normalize_required_id=lambda value, _message: value,
    )
    monkeypatch.setattr(experiment_plan, "_service", lambda: service)

    with pytest.raises(PermissionError, match="command_forbidden"):
        experiment_plan.freeze_experiment_design(
            "team-1",
            "plan-1",
            {"frozenByAgent": "Experiment Planning Agent"},
        )


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
            "knowledgeBaseId": "kb-1",
            "knowledgeItemIds": ["item-1"],
            "batchId": "batch-1",
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


def test_applied_receipt_requires_real_team_knowledge_identifiers(tmp_path, monkeypatch):
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

    with pytest.raises(
        ChallengePhaseBoundaryError,
        match="knowledge_applied_receipt_required",
    ):
        record_phase_one_knowledge_applied_receipt(
            "team-1",
            {
                "receiptId": "synthetic-receipt",
                "status": "applied",
                "manifestSha256": approved["manifest"]["manifestSha256"],
                "contentSha256": approved["manifest"]["contentSha256"],
            },
            question_run_summary=summary,
        )


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
            "knowledgeBaseId": "kb-1",
            "knowledgeItemIds": ["item-1"],
            "batchId": "batch-1",
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


def test_approved_package_is_applied_to_team_knowledge_once(tmp_path, monkeypatch):
    monkeypatch.setattr(
        challenge_phase_boundary,
        "resolve_team_program_root",
        lambda _team_id: tmp_path,
    )
    summary = _complete_summary()
    approve_current_phase_one_manifest(
        "team-1",
        operator_id="operator-1",
        question_run_summary=summary,
    )

    class FakeKnowledgeService:
        def __init__(self):
            self.items = []
            self.collect_count = 0

        def get_or_create_team_knowledge_base(self, *_args, **_kwargs):
            return {"knowledgeBase": {"knowledgeBaseId": "kb-1"}, "created": False}

        def ensure_knowledge_base_review_grant(self, *_args, **_kwargs):
            return {}

        def ensure_owner_source_review_grant(self, *_args, **_kwargs):
            return {}

        def list_knowledge_items(self, *_args, **_kwargs):
            return {"items": list(self.items)}

        def collect_source_to_inbox(self, *_args, **_kwargs):
            self.collect_count += 1
            return {"inboxSourceId": "source-1"}

        def review_owner_inbox_source(self, *_args, **kwargs):
            item = {
                "knowledgeItemId": "item-1",
                "batchId": "batch-1",
                "appliedAt": "2026-09-05T00:00:00Z",
                "tags": list(kwargs["tags"]),
            }
            self.items.append(item)
            return {
                "directIngestion": {
                    "status": "ingested",
                    "batch": {"batchId": "batch-1", "status": "applied"},
                    "item": item,
                }
            }

    knowledge = FakeKnowledgeService()
    team = {
        "teamId": "team-1",
        "members": [
            {"agentId": "research-agent", "roleKey": "research_coordinator"},
            {"agentId": "knowledge-manager", "roleKey": "challenge_cup_knowledge_manager"},
        ],
    }

    first = publish_approved_phase_one_to_team_knowledge(
        "team-1",
        question_run_summary=summary,
        knowledge_service=knowledge,
        team_snapshot=team,
    )
    second = publish_approved_phase_one_to_team_knowledge(
        "team-1",
        question_run_summary=summary,
        knowledge_service=knowledge,
        team_snapshot=team,
    )

    assert first["phase2Activated"] is True
    assert second["phase2Activated"] is True
    assert knowledge.collect_count == 1
    assert second["knowledgeReceipt"]["knowledgeBaseId"] == "kb-1"
    assert second["knowledgeReceipt"]["knowledgeItemIds"] == ["item-1"]


def test_knowledge_publish_failure_preserves_approval_and_keeps_phase_two_locked(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        challenge_phase_boundary,
        "resolve_team_program_root",
        lambda _team_id: tmp_path,
    )
    summary = _complete_summary()
    approve_current_phase_one_manifest(
        "team-1",
        operator_id="operator-1",
        question_run_summary=summary,
    )

    class FailingKnowledgeService:
        def get_or_create_team_knowledge_base(self, *_args, **_kwargs):
            from core.web.services.team_knowledge_service import TeamKnowledgeError

            raise TeamKnowledgeError("knowledge store unavailable")

    team = {
        "teamId": "team-1",
        "members": [
            {"agentId": "research-agent", "roleKey": "research_coordinator"},
            {"agentId": "knowledge-manager", "roleKey": "challenge_cup_knowledge_manager"},
        ],
    }

    with pytest.raises(
        ChallengePhaseBoundaryError,
        match="phase_one_knowledge_publish_failed",
    ):
        publish_approved_phase_one_to_team_knowledge(
            "team-1",
            question_run_summary=summary,
            knowledge_service=FailingKnowledgeService(),
            team_snapshot=team,
        )

    boundary = get_challenge_phase_boundary_status(
        "team-1",
        question_run_summary=summary,
    )
    assert boundary["phase1Approved"] is True
    assert boundary["knowledgePublication"]["status"] == "pending"
    assert boundary["phase2Activated"] is False


def test_phase_one_publication_reaches_real_team_knowledge_store(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        challenge_phase_boundary,
        "resolve_team_program_root",
        lambda _team_id: tmp_path / "program",
    )
    proposer = agent_directory_service.create_agent_instance(
        display_name="Research Agent",
        direct_session_id="session-research",
    )
    reviewer = agent_directory_service.create_agent_instance(
        display_name="Knowledge Manager",
        direct_session_id="session-knowledge",
    )
    team = team_service.create_team(
        name="Challenge Cup Team",
        members=[
            {"agentId": proposer["agentId"], "role": "lead"},
            {
                "agentId": reviewer["agentId"],
                "role": "challenge_cup_knowledge_manager",
            },
        ],
    )
    summary = _complete_summary()
    approve_current_phase_one_manifest(
        team["teamId"],
        operator_id="operator-1",
        question_run_summary=summary,
    )

    published = publish_approved_phase_one_to_team_knowledge(
        team["teamId"],
        question_run_summary=summary,
    )

    receipt = published["knowledgeReceipt"]
    assert published["phase2Activated"] is True
    items = team_knowledge_service.list_knowledge_items(
        receipt["knowledgeBaseId"],
        agent_id=reviewer["agentId"],
    )
    assert [item["knowledgeItemId"] for item in items["items"]] == receipt[
        "knowledgeItemIds"
    ]
    assert items["items"][0]["batchId"] == receipt["batchId"]
    assert published["manifest"]["manifestSha256"] in items["items"][0]["content"]

    package = load_published_phase_one_knowledge_package(
        team["teamId"],
        question_run_summary=summary,
    )
    assert package == {
        "knowledgeBaseId": receipt["knowledgeBaseId"],
        "knowledgeItemIds": receipt["knowledgeItemIds"],
        "batchId": receipt["batchId"],
        "receiptId": receipt["receiptId"],
        "manifestSha256": published["manifest"]["manifestSha256"],
        "contentSha256": published["manifest"]["contentSha256"],
        "datasetRefs": [
            "team-knowledge://"
            f"{receipt['knowledgeBaseId']}/{receipt['knowledgeItemIds'][0]}"
            f"?batchId={receipt['batchId']}"
            f"&manifestSha256={published['manifest']['manifestSha256']}"
            f"&contentSha256={published['manifest']['contentSha256']}"
        ],
    }

    monkeypatch.setattr(
        team_knowledge_service,
        "get_knowledge_trace",
        lambda *_args, **_kwargs: {"nodes": {"batches": [], "sourceArtifacts": []}},
    )
    with pytest.raises(ChallengePhaseBoundaryError, match="phase_one_knowledge_lineage_invalid"):
        load_published_phase_one_knowledge_package(
            team["teamId"],
            question_run_summary=summary,
        )


def test_deep_experiment_input_consumes_published_phase_one_lineage(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        challenge_phase_boundary,
        "resolve_team_program_root",
        lambda _team_id: tmp_path / "program",
    )
    proposer = agent_directory_service.create_agent_instance(
        display_name="Research Agent",
        direct_session_id="session-research",
    )
    reviewer = agent_directory_service.create_agent_instance(
        display_name="Knowledge Manager",
        direct_session_id="session-knowledge",
    )
    team = team_service.create_team(
        name="Challenge Cup Team",
        members=[
            {"agentId": proposer["agentId"], "role": "lead"},
            {
                "agentId": reviewer["agentId"],
                "role": "challenge_cup_knowledge_manager",
            },
        ],
    )
    summary = _complete_summary()
    approve_current_phase_one_manifest(
        team["teamId"],
        operator_id="operator-1",
        question_run_summary=summary,
    )
    published = publish_approved_phase_one_to_team_knowledge(
        team["teamId"],
        question_run_summary=summary,
    )
    from core.web.services.team_workflow import challenge_question_runs

    monkeypatch.setattr(
        challenge_question_runs,
        "challenge_question_run_summary",
        lambda _team_id: summary,
    )
    monkeypatch.setattr(
        question_launch,
        "_approved_details",
        lambda _team_id: {
            "SCI-096": {
                "selectedRunId": "run-096",
                "artifact": {"sha256": "a" * 64},
                "output": {
                    "schema_version": 2,
                    "identity": {
                        "catalog_id": "science-125-questions-2021",
                        "question_id": "SCI-096",
                        "question_en": "How does the brain retrieve memories?",
                    },
                    "problem_understanding": {"scope": "memory retrieval"},
                },
            }
        },
    )
    monkeypatch.setattr(question_launch, "_is_campaign_active", lambda *_args: True)
    monkeypatch.setattr(
        question_launch,
        "ensure_challenge_question_project",
        lambda *_args, **_kwargs: {"project": {"projectId": "challenge-sci-096"}},
    )
    monkeypatch.setattr(question_launch, "_server_model_routing_policy", lambda _team_id: {})
    monkeypatch.setattr(question_launch, "_hypothesis_first_scope", lambda *_args: {})
    monkeypatch.setattr(question_launch, "_hypothesis_first_flag", lambda *_args, **_kwargs: False)

    run_input = question_launch.build_question_run_input(
        team["teamId"],
        question_id="SCI-096",
        safety_limits={
            "stageTokens": {
                "knowledge_collection": 1,
                "experiment_design": 1,
                "execution_iteration": 1,
            },
            "toolCalls": 1,
            "wallClockSeconds": 1,
            "maxRetries": 1,
        },
    )

    package = load_published_phase_one_knowledge_package(team["teamId"])
    assert run_input["datasetRefs"] == [
        "challenge-question-artifact://science-125-questions-2021/SCI-096/run-096/" + "a" * 64,
        *package["datasetRefs"],
    ]
    assert run_input["constraintSnapshot"]["phaseOneKnowledgePackage"] == package
    assert package["manifestSha256"] == published["manifest"]["manifestSha256"]
