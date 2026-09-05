from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.web.services.team_workflow.research_runtime.action_registry import AdapterResult
from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import AgentActionAdapter, SystemActionAdapter
from core.web.services.team_workflow.research_runtime.domain_ports import ArtifactReadBack
from tests.test_research_workflow_adapter_idempotency import _action


@pytest.mark.parametrize("adapter_type", [AgentActionAdapter, SystemActionAdapter])
@pytest.mark.parametrize("mismatch,expected_code", [
    ("hash", "artifact_hash_mismatch"),
    ("version", "artifact_version_mismatch"),
    ("required_kind", "required_artifact_missing"),
    (None, None),
])
def test_agent_and_system_verify_the_same_output_contract(adapter_type, mismatch, expected_code):
    action = replace(_action(), node_id="controlled_run")
    readback = ArtifactReadBack(
        canonical_ref="canonical:run-artifacts", version="v1",
        content_hash="a" * 64, domain_revision="revision-1",
    )
    ports = SimpleNamespace(
        required_artifact_kinds=lambda _: ("run_artifacts", "metrics") if mismatch == "required_kind" else ("run_artifacts",),
        read_back_artifact=lambda _: readback,
    )
    result = AdapterResult(
        action_id=action.action_id, outcome="succeeded",
        materialized_refs=({
            "canonicalRef": readback.canonical_ref, "kind": "run_artifacts",
            "sha256": "b" * 64 if mismatch == "hash" else readback.content_hash,
            "version": "v2" if mismatch == "version" else readback.version,
        },),
        usage={"compute": "runner-1"},
    )
    verified = adapter_type(ports).verify(action, result)
    if expected_code is not None:
        assert verified.outcome == "blocked"
        assert verified.problem["code"] == expected_code
        assert verified.artifact_receipts == ()
        assert verified.budget_receipt is None
    else:
        assert verified.outcome == "succeeded"
        assert len(verified.artifact_receipts) == 1
        assert verified.artifact_receipts[0]["sha256"] == readback.content_hash
