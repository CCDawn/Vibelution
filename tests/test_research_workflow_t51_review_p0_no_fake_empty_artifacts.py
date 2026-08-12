"""P0: unwired artifact kinds must not fake successful empty read-back."""

from __future__ import annotations

from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
    build_canonical_ref,
    load_scoped_artifact_payload,
    read_domain_artifact,
)
from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
    canonical_sha256,
)


def test_unwired_kinds_do_not_invent_empty_records_for_forged_refs() -> None:
    team_id = "team-does-not-exist"
    run_id = "run-does-not-exist"
    for kind in ("run_artifacts", "research_result_package"):
        payload = load_scoped_artifact_payload(
            kind,
            team_id=team_id,
            authority_run_id=run_id,
            workflow_run_id=run_id,
        )
        assert payload is None, kind

        # Even a forged canonical ref must not successfully read back.
        forged_hash = canonical_sha256(
            {
                "teamId": team_id,
                "sourceCollectionRunId": run_id,
                "kind": kind,
                "records": [],
            }
        )
        forged_ref = build_canonical_ref(
            kind=kind,
            team_id=team_id,
            authority_run_id=run_id,
            content_hash=forged_hash,
        )
        assert read_domain_artifact(forged_ref) is None, kind
