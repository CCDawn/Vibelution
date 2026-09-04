"""Accepted knowledge package receipt is the only experiment-handoff authority."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from core.web.services.team_workflow.research_runtime.knowledge_artifact_authority import (
    load_knowledge_package_draft_payload,
)

from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
    build_canonical_ref,
)
from core.web.services.team_workflow.research_runtime.experiment_stage_bootstrap import (
    ExperimentStageBootstrapError,
    ensure_experiment_stage_round_for_agent_node,
)
from core.web.services.team_workflow.research_project_hypothesis_context import (
    build_hypothesis_input_context,
)
from core.web.services.team_workflow.research_runtime.human_acceptance_artifact import (
    load_accepted_knowledge_package_from_receipt,
)
from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
    canonical_sha256,
)
from core.web.services.team_workflow.research_runtime.real_readiness_context import (
    RealDomainReadinessContext,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_event_record,
    build_run_record,
)


def _accepted_package() -> dict[str, Any]:
    return {
        "teamId": "research-team",
        "sourceCollectionRunId": "sc-run-1",
        "accepted": True,
        "candidateId": "accepted-package",
        "knowledgeBaseId": "team:research-team:kb-1",
        "knowledgeItems": [
            {"knowledgeItemId": "ki-accepted", "contentHash": "b" * 64}
        ],
        "sourceArtifactIds": ["source-package-1"],
        "approval": {"reviewedByAgentId": "reviewer-1"},
    }


def test_draft_readback_searches_tail_beyond_public_candidate_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import nullcontext

    from core.web.services.team_workflow.source_collection import candidates as candidate_service

    noise = [
        {
            "candidateId": f"noise-{index:04d}",
            "teamId": "research-team",
            "candidateType": "local_model_output",
            "metadata": {"taskType": "other"},
        }
        for index in range(500)
    ]
    tail = {
        "candidateId": "draft-at-tail",
        "teamId": "research-team",
        "candidateType": "local_model_output",
        "updatedAt": "2026-09-04T12:00:00Z",
        "metadata": {
            "taskType": "steward_pack_draft",
            "output": {
                "claims": [{"claim": "Tail draft is authoritative."}],
                "requiresReview": True,
                "sourceTrace": {
                    "teamId": "research-team",
                    "sourceCollectionRunId": "sc-run-1",
                    "workflowRunId": "run-test",
                },
            },
            "validation": {"valid": True},
            "knowledgeIngestion": {"status": "official_synced"},
        },
    }

    class FakeTeamService:
        @staticmethod
        def assert_team_exists(_team_id: str) -> None:
            return None

    class FakeCandidateService:
        _WORKFLOW_LOCK = nullcontext()
        team_service = FakeTeamService()

        @staticmethod
        def _normalize_required_id(value: str, _message: str) -> str:
            return value

        @staticmethod
        def _trim_text(value: Any, *, max_length: int) -> str:
            return str(value or "")[:max_length]

        @staticmethod
        def _normalize_candidate_type(value: str) -> str:
            return value

        @staticmethod
        def _load_or_create_workflow(_team_id: str) -> dict[str, Any]:
            return {"workflowId": "workflow-test"}

        @staticmethod
        def _load_candidate_store(_team_id: str, *, run_id: str = "") -> dict[str, Any]:
            assert run_id == "sc-run-1"
            return {"candidates": [*noise, tail]}

        @staticmethod
        def _filtered_candidates(store: dict[str, Any], **_filters: Any) -> list[dict[str, Any]]:
            return list(store["candidates"])

    monkeypatch.setattr(candidate_service, "_service", lambda: FakeCandidateService())
    monkeypatch.setattr(
        candidate_service,
        "project_source_version_families",
        lambda values: (list(values), {}),
    )
    monkeypatch.setattr(
        candidate_service,
        "summarize_projected_source_version_families",
        lambda _values: {},
    )

    payload = load_knowledge_package_draft_payload(
        team_id="research-team",
        authority_run_id="sc-run-1",
        workflow_run_id="run-test",
    )

    assert payload is not None
    assert payload["candidateId"] == "draft-at-tail"


def _stale_inventory_package() -> dict[str, Any]:
    return {
        "teamId": "research-team",
        "sourceCollectionRunId": "sc-run-1",
        "accepted": True,
        "candidateId": "stale-package",
        "knowledgeBaseId": "team:research-team:kb-1",
        "knowledgeItems": [
            {"knowledgeItemId": "ki-stale", "contentHash": "c" * 64}
        ],
        "sourceArtifactIds": ["source-stale"],
        "approval": {"reviewedByAgentId": "reviewer-1"},
    }


def _seed_pending_knowledge_gate(harness: CommandHarness) -> None:
    run = replace(
        build_run_record(last_event_sequence=1),
        input_snapshot_json=json.dumps(
            {
                "snapshotHash": "a" * 64,
                "sourceCollectionRunId": "sc-run-1",
            }
        ),
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
            handoff_id="ho-knowledge-hypothesis",
            task_kind="gate:knowledge_handoff",
            prompt_json='{"nodeId":"knowledge_handoff"}',
            created_at_ms=FIXED_NOW_MS,
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _bind_accepted_receipt(
    harness: CommandHarness,
    package: dict[str, Any],
    *,
    canonical_hash: str | None = None,
    ledger_hash: str | None = None,
) -> str:
    content_hash = canonical_sha256(package)
    ref_hash = str(canonical_hash or content_hash)
    sha256 = str(ledger_hash or content_hash)
    canonical_ref = build_canonical_ref(
        kind="knowledge_package",
        team_id="research-team",
        authority_run_id="sc-run-1",
        content_hash=ref_hash,
    )

    def mutate(uow):
        uow.repository.update_handoff_status(
            "ho-knowledge-hypothesis",
            "accepted",
            FIXED_NOW_MS + 1,
        )
        uow.repository.insert_artifact_receipt(
            receipt_id="ar-kp-accepted",
            run_id="run-test",
            node_run_id="nr-run-test-knowledge_handoff-a1",
            team_id="research-team",
            artifact_kind="knowledge_package",
            canonical_ref_json=json.dumps(
                {"canonicalRef": canonical_ref},
                ensure_ascii=False,
            ),
            artifact_version="1.0.0",
            sha256=sha256,
            domain_revision="d" * 32,
            materialized=1,
            verified_at_ms=FIXED_NOW_MS + 1,
        )
        uow.repository.insert_handoff_receipt(
            "ho-knowledge-hypothesis",
            "ar-kp-accepted",
            0,
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)
    return sha256


def _patch_inventory(
    monkeypatch: pytest.MonkeyPatch,
    *,
    accepted: dict[str, Any],
    stale: dict[str, Any],
    accepted_hash: str,
) -> list[str]:
    loads: list[str] = []

    def fake_load(kind: str, **kwargs: Any) -> dict[str, Any] | None:
        content_hash = str(kwargs.get("content_hash") or "")
        loads.append(content_hash)
        if kind != "knowledge_package":
            return None
        if content_hash == accepted_hash:
            return accepted
        return stale

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime."
        "human_acceptance_artifact.load_scoped_artifact_payload",
        fake_load,
    )
    return loads


def _patch_hypothesis_lookups(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.candidates.list_candidate_store",
        lambda *_args, **_kwargs: {
            "candidates": [
                {
                    "candidateId": "accepted-package",
                    "metadata": {
                        "output": {
                            "claims": [
                                {
                                    "claim": "Accepted evidence claim.",
                                    "sourceRef": "source-accepted",
                                }
                            ]
                        }
                    },
                },
                {
                    "candidateId": "stale-package",
                    "metadata": {
                        "output": {
                            "claims": [
                                {
                                    "claim": "Stale inventory claim.",
                                    "sourceRef": "source-stale",
                                }
                            ]
                        }
                    },
                },
            ]
        },
    )
    monkeypatch.setattr(
        "core.web.services.team_knowledge_service.list_knowledge_items",
        lambda *_args, **_kwargs: {
            "items": [
                {
                    "knowledgeItemId": "ki-accepted",
                    "title": "Accepted",
                    "summary": "Bound receipt",
                },
                {
                    "knowledgeItemId": "ki-stale",
                    "title": "Stale",
                    "summary": "Inventory update",
                },
            ]
        },
    )


def test_accepted_receipt_is_the_only_knowledge_package_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        accepted = _accepted_package()
        stale = _stale_inventory_package()
        _seed_pending_knowledge_gate(harness)
        accepted_hash = _bind_accepted_receipt(harness, accepted)
        loads = _patch_inventory(
            monkeypatch,
            accepted=accepted,
            stale=stale,
            accepted_hash=accepted_hash,
        )

        payload = load_accepted_knowledge_package_from_receipt(
            harness.store,
            team_id="research-team",
            run_id="run-test",
        )
        context = RealDomainReadinessContext(harness.store)
        via_context = context.knowledge_package("research-team", "run-test")

        assert payload == accepted
        assert via_context == accepted
        assert accepted_hash in loads
        assert all(item == accepted_hash for item in loads)
    finally:
        harness.close()


def test_stale_inventory_must_not_win_over_accepted_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        accepted = _accepted_package()
        stale = _stale_inventory_package()
        _seed_pending_knowledge_gate(harness)
        accepted_hash = _bind_accepted_receipt(harness, accepted)
        _patch_inventory(
            monkeypatch,
            accepted=accepted,
            stale=stale,
            accepted_hash=accepted_hash,
        )

        context = RealDomainReadinessContext(harness.store)
        package = context.knowledge_package("research-team", "run-test")

        assert package is not None
        assert package["knowledgeItems"][0]["knowledgeItemId"] == "ki-accepted"
        assert package != stale
    finally:
        harness.close()


def test_inventory_without_receipt_does_not_unlock_experiment_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_pending_knowledge_gate(harness)
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime."
            "human_acceptance_artifact.load_scoped_artifact_payload",
            lambda *args, **kwargs: _stale_inventory_package(),
        )

        context = RealDomainReadinessContext(harness.store)
        assert context.knowledge_package("research-team", "run-test") is None
        assert (
            load_accepted_knowledge_package_from_receipt(
                harness.store,
                team_id="research-team",
                run_id="run-test",
            )
            is None
        )
        with pytest.raises(
            ExperimentStageBootstrapError,
            match="knowledge_package_not_materialized",
        ):
            ensure_experiment_stage_round_for_agent_node(
                node_id="hypothesis_design",
                team_id="research-team",
                project_id="challenge-sci-096",
                input_snapshot={"researchObjectiveContract": {"question": "研究问题"}},
                requested_by_agent="agent-hypothesis",
                store=harness.store,
                run_id="run-test",
            )
        hypothesis = build_hypothesis_input_context(
            "research-team",
            {
                "workflowRunId": "run-test",
                "sourceCollectionRunId": "sc-run-1",
            },
            store=harness.store,
        )
        assert hypothesis["status"] == "blocked"
        assert hypothesis["code"] == "knowledge_package_not_materialized"
    finally:
        harness.close()


def test_bootstrap_reads_bound_receipt_not_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        experiment_stage_bootstrap,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        accepted = _accepted_package()
        stale = _stale_inventory_package()
        _seed_pending_knowledge_gate(harness)
        accepted_hash = _bind_accepted_receipt(harness, accepted)
        loads = _patch_inventory(
            monkeypatch,
            accepted=accepted,
            stale=stale,
            accepted_hash=accepted_hash,
        )
        calls: list[tuple[str, dict[str, Any]]] = []
        monkeypatch.setattr(
            experiment_stage_bootstrap,
            "_start_research_stage_round",
            lambda team_id, payload: calls.append((team_id, payload)) or payload,
        )

        result = ensure_experiment_stage_round_for_agent_node(
            node_id="hypothesis_design",
            team_id="research-team",
            project_id="challenge-sci-096",
            input_snapshot={"researchObjectiveContract": {"question": "研究问题"}},
            requested_by_agent="agent-hypothesis",
            store=harness.store,
            run_id="run-test",
        )

        assert result == {
            "stageType": "experiment",
            "researchProjectId": "challenge-sci-096",
            "requestedByAgent": "agent-hypothesis",
            "topic": "研究问题",
        }
        assert calls == [("research-team", result)]
        assert loads == [accepted_hash]
    finally:
        harness.close()


def test_hypothesis_context_uses_bound_receipt_not_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        accepted = _accepted_package()
        stale = _stale_inventory_package()
        _seed_pending_knowledge_gate(harness)
        accepted_hash = _bind_accepted_receipt(harness, accepted)
        loads = _patch_inventory(
            monkeypatch,
            accepted=accepted,
            stale=stale,
            accepted_hash=accepted_hash,
        )
        _patch_hypothesis_lookups(monkeypatch)

        context = build_hypothesis_input_context(
            "research-team",
            {
                "workflowRunId": "run-test",
                "sourceCollectionRunId": "sc-run-1",
                # Candidate session isolation (584e68de9): the dispatching
                # task declares the candidate context; the returned
                # knowledgePackage mirrors the task's candidateId.
                "candidateId": "accepted-package",
            },
            store=harness.store,
        )

        assert context["status"] == "ready"
        assert context["knowledgePackage"]["candidateId"] == "accepted-package"
        assert context["knowledgePackage"]["knowledgeItems"] == [
            {
                "knowledgeItemId": "ki-accepted",
                "title": "Accepted",
                "summary": "Bound receipt",
            }
        ]
        assert context["evidenceClaims"] == [
            {"claim": "Accepted evidence claim.", "sourceRef": "source-accepted"}
        ]
        assert "source-stale" not in context["allowedEvidenceRefs"]
        assert loads == [accepted_hash]
    finally:
        harness.close()


def test_receipt_content_hash_mismatch_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        accepted = _accepted_package()
        stale = _stale_inventory_package()
        _seed_pending_knowledge_gate(harness)
        package_hash = canonical_sha256(accepted)
        _bind_accepted_receipt(
            harness,
            accepted,
            canonical_hash="e" * 64,
            ledger_hash=package_hash,
        )
        loads = _patch_inventory(
            monkeypatch,
            accepted=accepted,
            stale=stale,
            accepted_hash=package_hash,
        )
        _patch_hypothesis_lookups(monkeypatch)

        payload = load_accepted_knowledge_package_from_receipt(
            harness.store,
            team_id="research-team",
            run_id="run-test",
        )
        hypothesis = build_hypothesis_input_context(
            "research-team",
            {
                "workflowRunId": "run-test",
                "sourceCollectionRunId": "sc-run-1",
            },
            store=harness.store,
        )

        assert payload is None
        assert hypothesis["status"] == "blocked"
        assert hypothesis["code"] == "knowledge_package_not_materialized"
        assert loads == []
    finally:
        harness.close()
