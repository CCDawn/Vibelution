"""T5.1-2: real Artifact read-back + required-output contract.

Synthetic read-back (any non-empty ref → version=1.0, empty hash) must die.
Required producesArtifactKinds with zero materialized refs must block.
System nodes must not succeed with empty refs / empty runnerId.

Read-back is authority-scoped via Source Collection candidates — never a
parallel domain_artifacts filesystem.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.contracts import PendingAction
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
    AgentActionAdapter,
    SystemActionAdapter,
)
from core.web.services.team_workflow.research_runtime.domain_ports import (
    ArtifactReadBack,
)
from core.web.services.team_workflow.research_runtime.real_domain_ports import (
    RealDomainPorts,
    _read_back_real_artifact,
)
from tests._support.adapter_fakes import FakeDomainPorts
from tests._support.command_helpers import CommandHarness


def test_synthetic_read_back_no_longer_accepts_arbitrary_ref() -> None:
    """Former stub returned ArtifactReadBack with empty hash for any string."""
    result = _read_back_real_artifact("source_candidate_batch:deadbeefdeadbeef")
    assert result is None or (
        bool(result.content_hash.strip()) and bool(result.domain_revision.strip())
    )
    if result is not None:
        assert result.content_hash != ""
        assert result.domain_revision != ""


def test_artifact_readback_registry_rejects_missing_kind() -> None:
    from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
        read_domain_artifact,
    )

    assert read_domain_artifact("") is None
    assert read_domain_artifact("not_a_registered_kind:abc") is None


def _seed_scoped_sc_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    team_name: str = "T51 Readback Team",
    sc_run_id: str = "sc-run-1",
    workflow_run_id: str = "wf-run-1",
) -> str:
    from tests._support.team_workflow.helpers import _use_tmp_project_root

    _use_tmp_project_root(tmp_path, monkeypatch)
    import core.infrastructure.path_containment as path_containment

    monkeypatch.setattr(path_containment, "PROJECT_ROOT", tmp_path)

    from core.web.services import agent_directory_service, team_service
    from core.web.services.team_workflow.source_collection.candidates import (
        register_candidate_source,
    )

    agent = agent_directory_service.create_agent_instance(
        display_name="T51 Readback Agent",
        role_key="source_finder",
        created_by="t51-readback",
    )
    team = team_service.create_team(
        name=team_name,
        members=[{"agentId": agent["agentId"], "role": "source_finder"}],
    )
    team_id = str(team["teamId"])
    register_candidate_source(
        team_id,
        {
            "title": "Scoped paper",
            "sourceUrl": "https://doi.org/10.0/t51-readback",
            "candidateType": "source_manifest",
            "sourceKind": "paper",
            "metadata": {
                "sourceCollectionRunId": sc_run_id,
                "workflowRunId": workflow_run_id,
            },
        },
    )
    return team_id


def test_seeded_sc_candidate_read_back_returns_real_hash_and_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
        build_canonical_ref,
        load_scoped_artifact_payload,
        read_domain_artifact,
    )
    from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
        canonical_sha256,
    )

    team_id = _seed_scoped_sc_candidates(tmp_path, monkeypatch)
    payload = load_scoped_artifact_payload(
        "source_candidate_batch",
        team_id=team_id,
        authority_run_id="sc-run-1",
        workflow_run_id="",
    )
    assert payload is not None
    assert int(payload.get("candidateCount") or 0) >= 1
    content_hash = canonical_sha256(payload)
    ref = build_canonical_ref(
        kind="source_candidate_batch",
        team_id=team_id,
        authority_run_id="sc-run-1",
        content_hash=content_hash,
    )

    read_back = read_domain_artifact(ref)
    assert read_back is not None
    assert read_back.content_hash == content_hash
    assert read_back.version
    assert read_back.domain_revision
    assert read_back.content_hash != ""
    assert read_back.domain_revision != ""


def test_read_back_rejects_forged_team_run_and_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
        build_canonical_ref,
        load_scoped_artifact_payload,
        read_domain_artifact,
    )
    from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
        canonical_sha256,
    )

    team_id = _seed_scoped_sc_candidates(tmp_path, monkeypatch)
    payload = load_scoped_artifact_payload(
        "source_candidate_batch",
        team_id=team_id,
        authority_run_id="sc-run-1",
        workflow_run_id="",
    )
    assert payload is not None
    content_hash = canonical_sha256(payload)
    real_ref = build_canonical_ref(
        kind="source_candidate_batch",
        team_id=team_id,
        authority_run_id="sc-run-1",
        content_hash=content_hash,
    )
    assert read_domain_artifact(real_ref) is not None

    forged_team_run = build_canonical_ref(
        kind="source_candidate_batch",
        team_id="team-forged",
        authority_run_id="sc-run-forged",
        content_hash=content_hash,
    )
    assert read_domain_artifact(forged_team_run) is None

    forged_hash = build_canonical_ref(
        kind="source_candidate_batch",
        team_id=team_id,
        authority_run_id="sc-run-1",
        content_hash=("0" * 64),
    )
    assert read_domain_artifact(forged_hash) is None


def test_knowledge_draft_readback_uses_scoped_authority_and_preserves_old_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
        collect_required_artifact_refs,
    )
    from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
        load_scoped_artifact_payload,
        read_domain_artifact,
    )

    candidates = [
        _knowledge_draft_candidate(
            candidate_id="draft-1",
            team_id="team-a",
            source_collection_run_id="sc-run-1",
            workflow_run_id="wf-run-1",
            updated_at="2026-08-13T10:00:00Z",
        )
    ]
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.candidates.list_candidate_store",
        lambda team_id, **_: {"teamId": team_id, "candidates": list(candidates)},
    )

    payload = load_scoped_artifact_payload(
        "knowledge_package_draft",
        team_id="team-a",
        authority_run_id="sc-run-1",
        workflow_run_id="wf-run-1",
    )
    assert payload is not None
    assert payload["candidateId"] == "draft-1"
    assert payload["draft"]["sourceTrace"]["sourceCollectionRunId"] == "sc-run-1"
    assert "knowledgeIngestion" not in payload

    refs = collect_required_artifact_refs(
        "knowledge_ingestion",
        team_id="team-a",
        workflow_run_id="wf-run-1",
        source_collection_run_id="sc-run-1",
    )
    assert len(refs) == 1
    assert refs[0]["kind"] == "knowledge_package_draft"
    old_ref = refs[0]["canonicalRef"]
    assert read_domain_artifact(old_ref) is not None

    candidates.append(
        _knowledge_draft_candidate(
            candidate_id="draft-2",
            team_id="team-a",
            source_collection_run_id="sc-run-1",
            workflow_run_id="wf-run-1",
            updated_at="2026-08-13T11:00:00Z",
        )
    )
    assert read_domain_artifact(old_ref) is not None
    assert (
        load_scoped_artifact_payload(
            "knowledge_package_draft",
            team_id="team-b",
            authority_run_id="sc-run-1",
            workflow_run_id="wf-run-1",
        )
        is None
    )
    assert (
        load_scoped_artifact_payload(
            "knowledge_package_draft",
            team_id="team-a",
            authority_run_id="sc-run-other",
            workflow_run_id="wf-run-other",
        )
        is None
    )


def _knowledge_draft_candidate(
    *,
    candidate_id: str,
    team_id: str,
    source_collection_run_id: str,
    workflow_run_id: str,
    updated_at: str,
) -> dict[str, object]:
    return {
        "candidateId": candidate_id,
        "candidateType": "review_record",
        "teamId": team_id,
        "currentState": "official_synced",
        "updatedAt": updated_at,
        "metadata": {
            "taskType": "steward_pack_draft",
            "validation": {"valid": True, "schemaVersion": 1},
            "knowledgeIngestion": {
                "status": "official_synced",
                "knowledgeBaseId": "team:team-a:kb-1",
                "proposalId": f"proposal-{candidate_id}",
            },
            "output": {
                "title": f"Knowledge draft {candidate_id}",
                "claims": [{"claim": f"claim-{candidate_id}"}],
                "sourceTrace": {
                    "teamId": team_id,
                    "sourceCollectionRunId": source_collection_run_id,
                    "workflowRunId": workflow_run_id,
                },
            },
        },
    }


def test_agent_verify_blocks_when_required_outputs_missing() -> None:
    ports = FakeDomainPorts()
    ports.turn_results_by_action["act-empty"] = []  # force empty refs
    adapter = AgentActionAdapter(ports)
    action = PendingAction(
        action_id="act-empty",
        run_id="run-test",
        node_run_id="nr-run-test-source_finding-a1",
        node_id="source_finding",
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="p-1",
    )
    result = adapter.execute(action)
    assert result.materialized_refs == ()
    verified = adapter.verify(action, result)
    assert verified.outcome == "blocked"
    assert (verified.problem or {}).get("code") == "required_artifact_missing"


def test_agent_verify_blocks_empty_hash_readback() -> None:
    ports = FakeDomainPorts()
    ports.turn_results_by_action["act-hash"] = [
        {
            "canonicalRef": "source_candidate_batch:abc",
            "kind": "source_candidate_batch",
            "sha256": "a" * 64,
        }
    ]
    ports.artifact_store["source_candidate_batch:abc"] = ArtifactReadBack(
        canonical_ref="source_candidate_batch:abc",
        version="1.0",
        content_hash="",  # synthetic incomplete
        domain_revision="",
    )
    adapter = AgentActionAdapter(ports)
    action = PendingAction(
        action_id="act-hash",
        run_id="run-test",
        node_run_id="nr-run-test-source_finding-a1",
        node_id="source_finding",
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="p-1",
    )
    result = adapter.execute(action)
    verified = adapter.verify(action, result)
    assert verified.outcome == "blocked"
    assert (verified.problem or {}).get("code") in {
        "artifact_incomplete_readback",
        "artifact_hash_mismatch",
    }


def test_real_ports_system_action_does_not_return_empty_success(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        ports = RealDomainPorts(harness.store)
        action = PendingAction(
            action_id="act-sys",
            run_id="run-test",
            node_run_id="nr-run-test-controlled_run-a1",
            node_id="controlled_run",
            attempt=1,
            actor_kind=ActorKind.SYSTEM,
            action_kind="system_action:controlled_run",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="p-1",
        )
        # Missing teamId/planId/campaign must fail — never empty success stubs.
        with pytest.raises(
            RuntimeError,
            match="teamId|planId|ExperimentCampaign|no system executor|system node",
        ):
            ports.execute_system_action(action=action)
    finally:
        harness.close()


def test_system_adapter_verify_requires_outputs() -> None:
    ports = FakeDomainPorts()
    ports.system_results["act-sys"] = ([], {"systemActionId": "sys-1", "runnerId": ""})
    adapter = SystemActionAdapter(ports, node_id="controlled_run")
    action = PendingAction(
        action_id="act-sys",
        run_id="run-test",
        node_run_id="nr-run-test-controlled_run-a1",
        node_id="controlled_run",
        attempt=1,
        actor_kind=ActorKind.SYSTEM,
        action_kind="system_action:controlled_run",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="p-1",
    )
    result = adapter.execute(action)
    verified = adapter.verify(action, result)
    assert verified.outcome == "blocked"
    assert (verified.problem or {}).get("code") in {
        "required_artifact_missing",
        "system_runner_missing",
    }


def test_every_produced_kind_has_authority_mapping() -> None:
    from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
        resolve_artifact_authority,
    )

    kinds = {
        kind
        for node in build_challenge_cup_workflow_definition().nodes
        for kind in node.producesArtifactKinds
    }
    missing = [kind for kind in sorted(kinds) if resolve_artifact_authority(kind) is None]
    assert missing == [], f"Artifact kinds missing authority mapping: {missing}"
