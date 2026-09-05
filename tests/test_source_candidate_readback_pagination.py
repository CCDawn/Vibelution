"""Canonical candidate receipts are independent of presentation page limits."""

from core.web.services.team_workflow.research_runtime.artifact_readback_registry import load_scoped_artifact_payload
from core.web.services.team_workflow.source_collection import candidates


def test_readback_finds_current_run_after_500_older_candidates(monkeypatch):
    service = candidates._service()
    monkeypatch.setattr(service.team_service, "assert_team_exists", lambda *_: None)
    old = [{"candidateId": f"old-{i}", "teamId": "research-team", "sourceCollectionRunId": "old-run"} for i in range(600)]
    current = {"candidateId": "current", "candidateType": "source_manifest",
        "teamId": "research-team", "sourceCollectionRunId": "current-run"}
    other_team = {**current, "candidateId": "wrong-team", "teamId": "other-team"}
    graph = {**current, "candidateId": "graph", "candidateType": "candidate_graph"}
    monkeypatch.setattr(service, "_load_candidate_store", lambda *_args, **_kwargs: {
        "candidates": [*old, current, other_team, graph],
    })
    payload = load_scoped_artifact_payload("source_candidate_batch", team_id="research-team", authority_run_id="current-run")
    assert payload is not None
    assert payload["candidates"] == [current]
    assert payload["candidateCount"] == 1
