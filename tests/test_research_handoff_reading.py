"""Handoff reading remains bound to the selected draft and workflow scope."""
from copy import deepcopy

import pytest

from core.web.services.team_workflow.research_runtime import handoff_query as query
from core.web.routes.team_workflows.research_runtime_models import ResearchWorkflowHandoffDetailResponse


@pytest.fixture
def reading(monkeypatch):
    payload = {"draft": {"proposalPayload": {"title": "Paper", "content": "Actual body"},
                         "sourceTrace": {"sourceUrl": "https://example.org/paper"},
                         "uncertainty": ["Unreviewed"]}}
    sha = query.artifacts.canonical_sha256(payload)
    record = {"runId": "child", "teamId": "team", "runVersion": 1, "handoffs": [
        {"handoffId": "h1", "status": "accepted", "outputArtifactRefs": [
            {"artifactId": "draft", "kind": "knowledge_package_draft", "contentHash": sha,
             "uri": f"knowledge_package_draft://team/authority/{sha}"}]},
        {"handoffId": "h2", "outputArtifactRefs": []}]}
    calls = []
    def load(kind, **scope):
        calls.append((kind, scope))
        return deepcopy(payload)
    monkeypatch.setattr(query.artifacts, "load_scoped_artifact_payload", load)
    return record, payload, calls


def test_reads_exact_handoff_without_changing_approval(reading):
    record, _, calls = reading
    result = query.get_handoff_detail(record, "h1")
    public = ResearchWorkflowHandoffDetailResponse.model_validate(result).model_dump()
    assert public["knowledgePackages"][0]["content"] == "Actual body"
    assert public["handoff"]["status"] == "accepted"
    assert calls[0][1]["workflow_run_id"] == "child"
    assert calls[0][1]["authority_run_id"] == "authority"
    assert calls[0][1]["team_id"] == "team"
    assert query.get_handoff_detail(record, "h2")["knowledgePackages"] == []
    assert len(calls) == 1


@pytest.mark.parametrize("mutation", ["team", "hash", "missing", "changed"])
def test_unverified_content_is_never_exposed(reading, monkeypatch, mutation):
    record, payload, calls = reading
    ref = record["handoffs"][0]["outputArtifactRefs"][0]
    if mutation == "team":
        ref["uri"] = ref["uri"].replace("://team/", "://other/")
    elif mutation == "hash":
        ref["contentHash"] = "a" * 64
    elif mutation == "missing":
        monkeypatch.setattr(query.artifacts, "load_scoped_artifact_payload", lambda *a, **kw: None)
    else:
        payload["draft"]["proposalPayload"]["content"] = "Changed"
    item = query.get_handoff_detail(record, "h1")["knowledgePackages"][0]
    assert item == {"artifactId": "draft", "status": "unavailable"}
    if mutation in {"team", "hash"}:
        assert not calls


def test_unknown_handoff_does_not_read_other_package(reading):
    record, _, calls = reading
    with pytest.raises(query.HandoffQueryError):
        query.get_handoff_detail(record, "other")
    assert not calls
