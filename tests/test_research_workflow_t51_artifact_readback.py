"""T5.1-2 RED: real Artifact read-back + required-output contract.

Synthetic read-back (any non-empty ref → version=1.0, empty hash) must die.
Required producesArtifactKinds with zero materialized refs must block.
System nodes must not succeed with empty refs / empty runnerId.
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


def test_materialize_then_read_back_returns_real_hash_and_revision(tmp_path: Path) -> None:
    from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
        materialize_domain_artifact,
        read_domain_artifact,
    )

    root = tmp_path / "domain-artifacts"
    payload = {
        "perspectives": ["p1", "p2"],
        "queries": ["q1"],
        "candidateSources": [{"sourceId": "s1"}],
        "counterEvidenceCandidateSources": [{"sourceId": "c1", "perspective": "falsification"}],
    }
    ref = materialize_domain_artifact(
        kind="source_candidate_batch",
        payload=payload,
        team_id="research-team",
        authority_run_id="sc-run-1",
        root=root,
    )
    assert ref["kind"] == "source_candidate_batch"
    assert len(ref["sha256"]) == 64
    assert ref["canonicalRef"]

    read_back = read_domain_artifact(ref["canonicalRef"], root=root)
    assert read_back is not None
    assert read_back.content_hash == ref["sha256"]
    assert read_back.version
    assert read_back.domain_revision
    assert read_back.content_hash != ""
    assert read_back.domain_revision != ""


def test_read_back_hash_mismatch_path_returns_none(tmp_path: Path) -> None:
    from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
        materialize_domain_artifact,
        read_domain_artifact,
    )

    root = tmp_path / "domain-artifacts"
    ref = materialize_domain_artifact(
        kind="evidence_card_batch",
        payload={"evidenceCards": [{"sourceId": "s1", "claim": "c", "citationLocator": {"page": 1}}]},
        team_id="research-team",
        authority_run_id="sc-run-1",
        root=root,
    )
    # Corrupt the identity in the canonical ref.
    bad_ref = ref["canonicalRef"].replace(ref["sha256"][:16], "0" * 16)
    assert read_domain_artifact(bad_ref, root=root) is None


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
        {"canonicalRef": "source_candidate_batch:abc", "kind": "source_candidate_batch", "sha256": "a" * 64}
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
        with pytest.raises(RuntimeError, match="system node|no system executor|runner"):
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
