from __future__ import annotations

from pathlib import Path

import pytest

from core.research.evidence import ClaimEvidenceStore
from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.agent_claim_evidence_materializer import (
    EvidenceMaterializationError,
    build_formal_evidence_retry_contract,
    materialize_claim_evidence_from_task,
)
from core.web.services.team_workflow.research_runtime.domain_ports import (
    AgentTaskHandle,
    BindingResolution,
)


def _verified_task() -> dict:
    return {
        "taskId": "task-extract-1",
        "teamId": "team-a",
        "runId": "sc-run-a",
        "stageId": "extraction",
        "agentId": "agent-a",
        "result": {
            "candidateExtractions": [
                {
                    "candidateId": "candidate-a",
                    "decision": "keep",
                    "evidenceStatus": "verified_abstract",
                    "claims": [
                        {
                            "claim": "The abstract reports a bounded result.",
                            "quote": "A bounded verbatim excerpt from the abstract.",
                            "sourceRef": "https://example.org/paper-a",
                            "evidenceRef": "Abstract, sentences 2-3",
                        }
                    ],
                },
                {
                    "candidateId": "candidate-gap",
                    "decision": "keep",
                    "evidenceStatus": "missing_evidence_anchor",
                    "claims": [
                        {
                            "claim": "This is only a model summary.",
                            "sourceRef": "https://example.org/paper-gap",
                            "evidenceRef": "record-anchor-gap",
                        }
                    ],
                },
            ]
        },
    }


def test_materializes_only_exactly_anchored_claims_into_canonical_store(
    tmp_path: Path,
) -> None:
    created = materialize_claim_evidence_from_task(
        project_root=tmp_path,
        team_id="team-a",
        workflow_run_id="wf-run-a",
        source_collection_run_id="sc-run-a",
        task=_verified_task(),
        model_ref="provider/model-a",
    )

    assert len(created) == 1
    records = ClaimEvidenceStore(tmp_path).list("team-a")
    assert len(records) == 1
    assert records[0]["candidateId"] == "candidate-a"
    assert records[0]["quote"] == "A bounded verbatim excerpt from the abstract."
    assert records[0]["workflowRunId"] == "wf-run-a"
    assert records[0]["sourceCollectionRunId"] == "sc-run-a"
    assert records[0]["reviewStatus"] == "pending"
    assert records[0]["formalKnowledgeWriteAllowed"] is False

    duplicate = materialize_claim_evidence_from_task(
        project_root=tmp_path,
        team_id="team-a",
        workflow_run_id="wf-run-a",
        source_collection_run_id="sc-run-a",
        task=_verified_task(),
        model_ref="provider/model-a",
    )
    assert duplicate == created
    assert len(ClaimEvidenceStore(tmp_path).list("team-a")) == 1


def test_rejects_cross_run_task_materialization(tmp_path: Path) -> None:
    with pytest.raises(EvidenceMaterializationError, match="source collection run"):
        materialize_claim_evidence_from_task(
            project_root=tmp_path,
            team_id="team-a",
            workflow_run_id="wf-run-a",
            source_collection_run_id="sc-run-other",
            task=_verified_task(),
            model_ref="provider/model-a",
        )


def test_retry_contract_targets_all_candidates_missing_canonical_evidence() -> None:
    candidates = [
        {
            "candidateId": "candidate-a",
            "metadata": {
                "importedFromDataRecord": {"runId": "sc-run-a"},
            },
        },
        {
            "candidateId": "candidate-b",
            "metadata": {
                "sourceCollectionTrace": {"runId": "sc-run-a"},
            },
        },
        {
            "candidateId": "candidate-other",
            "metadata": {
                "importedFromDataRecord": {"runId": "sc-run-other"},
            },
        },
    ]
    evidence = [
        {
            "candidateId": "candidate-a",
            "sourceCollectionRunId": "sc-run-a",
            "workflowRunId": "wf-run-a",
        }
    ]

    contract = build_formal_evidence_retry_contract(
        workflow_run_id="wf-run-a",
        source_collection_run_id="sc-run-a",
        candidates=candidates,
        evidence_records=evidence,
    )

    assert contract["evidenceGapCandidateIds"] == ["candidate-b"]
    assert contract["scopeCandidateIds"] == ["candidate-b"]
    assert contract["requiredExistingLocatorFetch"] is True


def _pending_action(*, attempt: int = 2) -> PendingAction:
    return PendingAction(
        action_id="act-extract-2",
        run_id="wf-run-a",
        node_run_id=f"nr-extract-{attempt}",
        node_id="source_extraction",
        attempt=attempt,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id="binding-a",
        budget_policy_hash="b" * 64,
    )


def test_completed_extraction_materializes_before_collecting_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
        complete_agent_turn_outputs,
    )

    calls: list[str] = []
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.wait_for_agent_turn_terminal",
        lambda *_a, **_k: {"terminal": True, "terminalStatus": "completed"},
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_writeback.reconcile_source_collection_stage_session_task_after_turn",
        lambda *_a, **_k: calls.append("reconcile"),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_claim_evidence_materializer.materialize_completed_extraction_task",
        lambda **_k: calls.append("materialize"),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_turn_completion.collect_required_artifact_refs",
        lambda *_a, **_k: calls.append("collect") or [{"kind": "evidence_card_batch"}],
    )

    refs = complete_agent_turn_outputs(
        action=_pending_action(),
        handle=AgentTaskHandle(
            session_id="session-a",
            session_attempt=1,
            task_id="task-a",
            turn_id="turn-a",
        ),
        input_snapshot={
            "teamId": "team-a",
            "sourceCollectionRunId": "sc-run-a",
        },
    )

    assert refs == [{"kind": "evidence_card_batch"}]
    assert calls == ["reconcile", "materialize", "collect"]


def test_retry_attempt_passes_evidence_scope_without_forcing_session_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime.real_domain_ports import (
        _start_source_collection_agent_task,
    )

    captured: dict = {}
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.agent_claim_evidence_materializer.build_formal_evidence_retry_contract",
        lambda **_k: {
            "schemaVersion": 1,
            "evidenceGapCandidateIds": ["candidate-a"],
            "scopeCandidateIds": ["candidate-a"],
        },
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_session.start_source_collection_stage_session_task",
        lambda team_id, run_id, payload: captured.update(
            {"teamId": team_id, "runId": run_id, "payload": payload}
        )
        or {"taskId": "task-a"},
    )

    _start_source_collection_agent_task(
        team_id="team-a",
        project_id="project-a",
        input_snapshot={"sourceCollectionRunId": "sc-run-a"},
        action=_pending_action(attempt=8),
        binding=BindingResolution(
            agent_id="agent-a",
            role_key="source_extractor",
            binding_snapshot_id="binding-a",
        ),
        stage_id="extraction",
        role_key="source_extractor",
        idempotency_key="agent-task:nr-extract-8",
    )

    assert captured["payload"]["formalRetry"] is False
    assert captured["payload"]["evidenceRemediationContract"]["scopeCandidateIds"] == [
        "candidate-a"
    ]


def test_extraction_prompt_requires_verbatim_quote_for_claim_evidence() -> None:
    from core.web.services.team_workflow.source_collection.stage_writeback_prompt_contracts import (
        stage_writeback_prompt_lines,
    )

    prompt = "\n".join(stage_writeback_prompt_lines("extraction"))
    assert "quote" in prompt
    assert "不得为通过门禁" in prompt
