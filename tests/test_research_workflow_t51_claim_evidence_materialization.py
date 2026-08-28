from __future__ import annotations

from pathlib import Path

import pytest

from core.research.evidence import ClaimEvidenceStore
from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow import claim_ledger
from core.web.services.team_workflow.research_runtime.agent_claim_evidence_materializer import (
    EvidenceMaterializationError,
    build_formal_evidence_retry_contract,
    materialize_claim_evidence_from_task,
)
from core.web.services.team_workflow.research_runtime.domain_ports import (
    AgentTaskHandle,
    BindingResolution,
)

_QUESTION_ID = "SCI-MTZ-1"


def _claim_bridge_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, dict]:
    """One tmp project root owning the team, claim ledger and evidence store.

    The chain module's project root is aligned too, so the real claim belief
    gate reads the same ledger and evidence stores the materializer wrote.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain as chain,
    )

    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(claim_ledger, "PROJECT_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path, raising=False)
    team_id = team_service.create_team(name="claim bridge team")["teamId"]
    return team_id, chain._question_scope_envelope(team_id, _QUESTION_ID)


def _v2_source_fields(**overrides: object) -> dict[str, object]:
    return {
        "title": "A bounded source",
        "source_type": "peer_reviewed_paper",
        "source_url": "https://example.org/paper-a",
        "retrieved_at": "2026-08-10T00:00:00Z",
        "fact": "The abstract reports a bounded result.",
        "relation": "supports",
        "verification_status": "metadata_checked",
        **overrides,
    }


def _verified_task(*, team_id: str = "team-a") -> dict:
    return {
        "taskId": "task-extract-1",
        "teamId": team_id,
        "runId": "sc-run-a",
        "stageId": "extraction",
        "agentId": "agent-a",
        "result": {
            "candidateExtractions": [
                {
                    "candidateId": "candidate-a",
                    "decision": "keep",
                    "evidenceStatus": "verified_abstract",
                    **_v2_source_fields(),
                    "claims": [
                        {
                            "fact": "The abstract reports a bounded result.",
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
                    **_v2_source_fields(
                        source_url="https://example.org/paper-gap",
                        fact="This is only a model summary.",
                    ),
                    "claims": [
                        {
                            "fact": "This is only a model summary.",
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id, scope = _claim_bridge_env(tmp_path, monkeypatch)
    created = materialize_claim_evidence_from_task(
        project_root=tmp_path,
        team_id=team_id,
        workflow_run_id="wf-run-a",
        source_collection_run_id="sc-run-a",
        task=_verified_task(team_id=team_id),
        model_ref="provider/model-a",
        question_scope=scope,
    )

    assert len(created) == 1
    records = ClaimEvidenceStore(tmp_path).list(team_id)
    assert len(records) == 1
    assert records[0]["candidateId"] == "candidate-a"
    assert records[0]["quote"] == "A bounded verbatim excerpt from the abstract."
    assert records[0]["workflowRunId"] == "wf-run-a"
    assert records[0]["sourceCollectionRunId"] == "sc-run-a"
    assert records[0]["reviewStatus"] == "pending"
    assert records[0]["formalKnowledgeWriteAllowed"] is False
    assert created[0]["challengeEvidence"] == {
        "sourceId": "candidate-a",
        "candidateId": "candidate-a",
        "title": "A bounded source",
        "source_type": "peer_reviewed_paper",
        "source_url": "https://example.org/paper-a",
        "retrieved_at": "2026-08-10T00:00:00Z",
        "fact": "The abstract reports a bounded result.",
        "relation": "supports",
        "verification_status": "metadata_checked",
    }

    duplicate = materialize_claim_evidence_from_task(
        project_root=tmp_path,
        team_id=team_id,
        workflow_run_id="wf-run-a",
        source_collection_run_id="sc-run-a",
        task=_verified_task(team_id=team_id),
        model_ref="provider/model-a",
        question_scope=scope,
    )
    assert duplicate[0]["claimEvidenceId"] == created[0]["claimEvidenceId"]
    assert duplicate[0]["claimId"] == created[0]["claimId"]
    assert duplicate[0]["claimLedgerStatus"] == "reused"
    assert len(ClaimEvidenceStore(tmp_path).list(team_id)) == 1


def test_materializes_canonical_key_findings_without_requiring_parallel_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = {
        "taskId": "task-extract-key-findings",
        "teamId": "team-a",
        "runId": "sc-run-a",
        "stageId": "extraction",
        "agentId": "agent-a",
        "result": {
            "candidateExtractions": [
                {
                    "candidateId": "candidate-key-finding",
                    "decision": "keep",
                    "evidenceStatus": "anchored",
                    **_v2_source_fields(
                        title="Temporal coding study",
                        source_url="https://example.org/paper-key-finding",
                        fact="Temporal and rate codes can be multiplexed.",
                        verification_status="full_text_checked",
                    ),
                    "keyFindings": [
                        {
                            "fact": "Temporal and rate codes can be multiplexed.",
                            "quote": "Synchronous and asynchronous spiking can multiplex temporal and rate coding.",
                            "sourceRef": "https://example.org/paper-key-finding",
                            "evidenceRef": "Abstract",
                        }
                    ],
                },
                {
                    "candidateId": "candidate-unanchored",
                    "decision": "keep",
                    "evidenceStatus": "missing_evidence_anchor",
                    **_v2_source_fields(
                        title="Unanchored study",
                        source_url="https://example.org/paper-unanchored",
                        fact="This summary has no acceptable anchor.",
                    ),
                    "keyFindings": [
                        {
                            "fact": "This summary has no acceptable anchor.",
                            "sourceRef": "https://example.org/paper-unanchored",
                        }
                    ],
                },
            ]
        },
    }

    team_id, scope = _claim_bridge_env(tmp_path, monkeypatch)
    task["teamId"] = team_id
    created = materialize_claim_evidence_from_task(
        project_root=tmp_path,
        team_id=team_id,
        workflow_run_id="wf-run-a",
        source_collection_run_id="sc-run-a",
        task=task,
        model_ref="provider/model-a",
        question_scope=scope,
    )

    assert len(created) == 1
    assert created[0]["candidateId"] == "candidate-key-finding"
    assert created[0]["quote"].startswith("Synchronous and asynchronous")
    assert created[0]["locator"] == {
        "kind": "evidence_ref",
        "anchor": "Abstract",
        "url": "https://example.org/paper-key-finding",
    }


def test_materializes_flat_extractions_with_evidence_ref_quotes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = {
        "taskId": "task-extract-flat",
        "teamId": "team-a",
        "runId": "sc-run-a",
        "stageId": "extraction",
        "agentId": "agent-a",
        "result": {
            "candidateExtractions": [
                {
                    "candidateId": "candidate-flat",
                    "decision": "keep",
                    **_v2_source_fields(
                        source_url="https://example.org/paper-flat",
                        fact="The fetched abstract reports an elementary equivalence.",
                    ),
                    "evidenceRefs": [
                        {
                            "id": "dprec-flat-abstract",
                            "type": "abstract",
                            "label": "arXiv abstract",
                            "quote": "A verbatim excerpt from the fetched abstract.",
                        }
                    ],
                },
                {
                    "candidateId": "candidate-flat-unanchored",
                    "decision": "keep",
                    **_v2_source_fields(
                        source_url="https://example.org/paper-flat-gap",
                        fact="A summary without any verbatim anchor.",
                    ),
                    "evidenceRefs": [
                        {
                            "id": "dprec-flat-gap",
                            "type": "abstract",
                            "label": "arXiv abstract",
                        }
                    ],
                },
            ]
        },
    }

    team_id, scope = _claim_bridge_env(tmp_path, monkeypatch)
    task["teamId"] = team_id
    created = materialize_claim_evidence_from_task(
        project_root=tmp_path,
        team_id=team_id,
        workflow_run_id="wf-run-a",
        source_collection_run_id="sc-run-a",
        task=task,
        model_ref="provider/model-a",
        question_scope=scope,
    )

    assert len(created) == 1
    assert created[0]["candidateId"] == "candidate-flat"
    assert created[0]["quote"] == "A verbatim excerpt from the fetched abstract."
    assert created[0]["locator"]["anchor"] == "dprec-flat-abstract"


def test_verified_materialization_fails_closed_when_v2_fields_are_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id, scope = _claim_bridge_env(tmp_path, monkeypatch)
    task = _verified_task()
    task["teamId"] = team_id
    claim = task["result"]["candidateExtractions"][0]["claims"][0]
    del claim["fact"]
    claim["claim"] = "A summary must not substitute for fact."

    with pytest.raises(ValueError, match="missing explicit fact"):
        materialize_claim_evidence_from_task(
            project_root=tmp_path,
            team_id=team_id,
            workflow_run_id="wf-run-a",
            source_collection_run_id="sc-run-a",
            task=task,
            model_ref="provider/model-a",
            question_scope=scope,
        )
    # Nothing was proposed into the ledger for the failed claim.
    assert claim_ledger.list_claims(team_id)["claimCount"] == 0


def test_rejects_cross_run_task_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, scope = _claim_bridge_env(tmp_path, monkeypatch)
    task = _verified_task()
    task["teamId"] = team_id
    with pytest.raises(EvidenceMaterializationError, match="source collection run"):
        materialize_claim_evidence_from_task(
            project_root=tmp_path,
            team_id=team_id,
            workflow_run_id="wf-run-a",
            source_collection_run_id="sc-run-other",
            task=task,
            model_ref="provider/model-a",
            question_scope=scope,
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
    for field in (
        "title",
        "source_type",
        "source_url",
        "retrieved_at",
        "fact",
        "relation",
        "verification_status",
    ):
        assert field in prompt
    assert "sourceId" in prompt
    assert "不能用 URL" in prompt


# ---------------------------------------------------------------------------
# extraction → claim ledger bridge (production writer for the belief gate)
# ---------------------------------------------------------------------------


def test_materialized_claims_bridge_ledger_row_and_allow_belief_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real extraction output satisfies the claim belief gate end to end.

    The materialized claim is proposed in the question-scoped claim ledger
    (the production writer the gate reads), the ClaimEvidence record carries
    the ledger claim id, and ``evaluate_claim_belief_gate`` allows the
    candidate on the real stores — no seam stubs.
    """
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain as chain,
    )

    team_id, scope = _claim_bridge_env(tmp_path, monkeypatch)
    created = materialize_claim_evidence_from_task(
        project_root=tmp_path,
        team_id=team_id,
        workflow_run_id="wf-run-a",
        source_collection_run_id="sc-run-a",
        task=_verified_task(team_id=team_id),
        model_ref="provider/model-a",
        question_scope=scope,
    )
    assert created[0]["claimLedgerStatus"] == "created"
    ledger_claim_id = created[0]["claimId"]

    # 1. The ledger row exists, scoped to the question the run serves.
    listing = claim_ledger.list_claims(team_id)
    assert listing["claimCount"] == 1
    row = listing["claims"][0]
    assert row["claimId"] == ledger_claim_id
    assert row["question"] == _QUESTION_ID
    assert row["status"] == "proposed"
    assert row["claim"] == "The abstract reports a bounded result."

    # 2. The evidence record references the same claim id.
    stored = ClaimEvidenceStore(tmp_path).list(team_id)
    assert len(stored) == 1
    assert stored[0]["claimId"] == ledger_claim_id
    assert stored[0]["claimEvidenceId"] == created[0]["claimEvidenceId"]

    # 3. The gate allows the candidate on the real ledger + evidence stores.
    verdict = chain.evaluate_claim_belief_gate(team_id, _QUESTION_ID, ["candidate-a"])[
        "candidate-a"
    ]
    assert verdict["status"] == "allowed", verdict
    assert [item["claimId"] for item in verdict["claims"]] == [ledger_claim_id]

    # 4. Idempotent replay: same content + scope reuses the same ledger row.
    replay = materialize_claim_evidence_from_task(
        project_root=tmp_path,
        team_id=team_id,
        workflow_run_id="wf-run-a",
        source_collection_run_id="sc-run-a",
        task=_verified_task(team_id=team_id),
        model_ref="provider/model-a",
        question_scope=scope,
    )
    assert replay[0]["claimId"] == ledger_claim_id
    assert replay[0]["claimEvidenceId"] == created[0]["claimEvidenceId"]
    assert replay[0]["claimLedgerStatus"] == "reused"
    assert claim_ledger.list_claims(team_id)["claimCount"] == 1
    assert len(ClaimEvidenceStore(tmp_path).list(team_id)) == 1


def test_materialization_without_question_scope_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No unbridged evidence may be produced: scope is mandatory."""
    team_id, _scope = _claim_bridge_env(tmp_path, monkeypatch)
    task = _verified_task()
    task["teamId"] = team_id
    with pytest.raises(EvidenceMaterializationError, match="question claim scope"):
        materialize_claim_evidence_from_task(
            project_root=tmp_path,
            team_id=team_id,
            workflow_run_id="wf-run-a",
            source_collection_run_id="sc-run-a",
            task=task,
            model_ref="provider/model-a",
            question_scope=None,  # type: ignore[arg-type]
        )
    assert claim_ledger.list_claims(team_id)["claimCount"] == 0
    assert ClaimEvidenceStore(tmp_path).list(team_id) == []


def test_materialization_surfaces_ledger_proposal_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing ledger proposal is structured, never swallowed."""
    team_id, scope = _claim_bridge_env(tmp_path, monkeypatch)

    def _broken_propose(_team_id: str, _payload: dict) -> dict:
        raise claim_ledger.ClaimLedgerError("ledger disk unavailable")

    monkeypatch.setattr(claim_ledger, "propose_claim", _broken_propose)
    task = _verified_task()
    task["teamId"] = team_id
    with pytest.raises(
        EvidenceMaterializationError, match="claim ledger proposal failed"
    ):
        materialize_claim_evidence_from_task(
            project_root=tmp_path,
            team_id=team_id,
            workflow_run_id="wf-run-a",
            source_collection_run_id="sc-run-a",
            task=task,
            model_ref="provider/model-a",
            question_scope=scope,
        )
    # The failed claim registered no evidence either: fail-closed, not partial.
    assert ClaimEvidenceStore(tmp_path).list(team_id) == []


def test_completed_extraction_resolves_question_scope_from_run_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production entry scopes proposals via the frozen run→question binding."""
    from types import SimpleNamespace

    from core.web.services.team_workflow.research_runtime import (
        agent_claim_evidence_materializer as materializer,
    )

    captured: dict = {}

    class _FakeStore:
        def get_run(self, run_id: str):
            captured["runId"] = run_id
            return SimpleNamespace(question_id="sci-0042")

    import core.web.services.team_workflow.research_runtime.formal_write_runtime as fwrt

    monkeypatch.setattr(fwrt, "get_write_store", lambda: _FakeStore())
    scope = materializer._formal_question_scope("team-a", "wf-run-9")
    assert captured["runId"] == "wf-run-9"
    assert scope["question"] == "SCI-0042"
    assert all(
        str(scope.get(field) or "").strip()
        for field in (
            "program",
            "theme",
            "campaign",
            "question",
            "branch",
            "workflow",
            "agentId",
            "mode",
        )
    )


def test_completed_extraction_fails_closed_without_run_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from core.web.services.team_workflow.research_runtime import (
        agent_claim_evidence_materializer as materializer,
    )
    import core.web.services.team_workflow.research_runtime.formal_write_runtime as fwrt

    monkeypatch.setattr(
        fwrt, "get_write_store", lambda: SimpleNamespace(
            get_run=lambda _run_id: SimpleNamespace(question_id="")
        )
    )
    with pytest.raises(EvidenceMaterializationError, match="does not carry a question"):
        materializer._formal_question_scope("team-a", "wf-run-9")
