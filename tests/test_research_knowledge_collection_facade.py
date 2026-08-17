"""D03 stage-1 knowledge collection facade contract tests.

Verifies that the single facade validates the ResearchScopeEnvelope and the
search envelope, is idempotent for ``ensure``, strictly read-only for
``inspect``, and returns only distilled summary/status/locator.
"""

from __future__ import annotations

import json

import pytest

from core.research.workflow.contracts import scope_hash_for
from core.web.services import data_processing_service
from core.web.services.team_workflow.source_collection import facade
from core.web.services.team_workflow.source_collection import runs as source_collection_runs


def _valid_envelope() -> dict:
    scope_hash = scope_hash_for(
        program="XH-202619",
        theme="cc-gpu-operator-001",
        campaign="cc-campaign-gpu-operator-001",
        question="SCI-091",
        branch="main",
        workflow="hypothesis_and_plan",
        agent_id="agent-alpha",
        mode="formal",
    )
    return {
        "program": "XH-202619",
        "theme": "cc-gpu-operator-001",
        "campaign": "cc-campaign-gpu-operator-001",
        "question": "SCI-091",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-alpha",
        "mode": "formal",
        "scopeHash": scope_hash,
        "artifactLocator": (
            f"research-artifact://XH-202619/cc-gpu-operator-001/"
            f"cc-campaign-gpu-operator-001/main/SCI-091/{scope_hash}"
        ),
        "ledgerRoot": (
            f"research-ledger://XH-202619/cc-gpu-operator-001/"
            f"cc-campaign-gpu-operator-001/{scope_hash}"
        ),
        "cacheKey": f"scope:{scope_hash}:main:agent-alpha",
    }


def _valid_search_envelope() -> dict:
    return {
        "keywords": ["predictive coding", "neural plasticity"],
        "sourceTypes": ["paper", "dataset"],
        "timeRange": {"from": "2020-01-01", "to": "2026-08-17"},
        "domains": ["neuroscience"],
        "repos": ["repo-a"],
        "kb": ["kb-neuro"],
        "languages": ["en", "zh"],
        "evidenceLevels": ["primary", "peer_reviewed"],
        "forbiddenScope": [{"domain": "marketing"}],
    }


def _fake_list_runs(runs=None):
    return lambda **kwargs: {"runs": list(runs or [])}


def _fake_summary(*, record_count=0, candidate_count=0):
    def fake(team_id, *, run_id):
        return {
            "status": "collecting",
            "runId": run_id,
            "runStatus": {"status": "collecting", "currentPhase": "searching"},
            "summary": {
                "recordCount": record_count,
                "assignmentCount": 1,
                "outputCount": 3,
                "sourceCandidateCount": candidate_count,
                "approvedSourceCandidateCount": 2,
            },
            "stageCards": [{"stageId": "finding", "status": "running", "label": "资料寻找"}],
            "records": [{"fullText": "must-not-leak"}],
        }

    return fake


def test_facade_rejects_tampered_scope_hash(monkeypatch):
    envelope = _valid_envelope()
    envelope["scopeHash"] = "b" * 64
    with pytest.raises(facade.ResearchKnowledgeCollectionError) as exc:
        facade.research_knowledge_collection_facade(action="inspect", scope=envelope)
    assert exc.value.code == "scope_hash_mismatch"


def test_facade_rejects_missing_scope_identity_field(monkeypatch):
    envelope = _valid_envelope()
    del envelope["theme"]
    with pytest.raises(facade.ResearchKnowledgeCollectionError) as exc:
        facade.research_knowledge_collection_facade(action="inspect", scope=envelope)
    assert exc.value.code == "scope_invalid"


def test_facade_rejects_unsupported_action(monkeypatch):
    with pytest.raises(facade.ResearchKnowledgeCollectionError) as exc:
        facade.research_knowledge_collection_facade(action="delete", scope=_valid_envelope())
    assert exc.value.code == "unsupported_action"


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda s: s.__setitem__("sourceTypes", ["social_post"]), "search_sourceTypes_invalid"),
        (lambda s: s.__setitem__("evidenceLevels", ["expert_opinion"]), "search_evidenceLevels_invalid"),
        (lambda s: s.__setitem__("languages", ["not-a-lang"]), "search_language_invalid"),
        (lambda s: s.__setitem__("timeRange", {"from": "not-a-date"}), "search_time_range_invalid"),
        (lambda s: s.__setitem__("timeRange", {"to": "2026/08/17"}), "search_time_range_invalid"),
    ],
)
def test_facade_validates_search_envelope_dimensions(monkeypatch, mutate, expected_code):
    search = _valid_search_envelope()
    mutate(search)
    with pytest.raises(facade.ResearchKnowledgeCollectionError) as exc:
        facade.research_knowledge_collection_facade(
            action="inspect",
            scope=_valid_envelope(),
            searchEnvelope=search,
        )
    assert exc.value.code == expected_code


def test_facade_accepts_full_search_envelope_dimensions(monkeypatch):
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs([{"runId": "dprun-dim", "updatedAt": "2026-08-17T00:00:00Z"}]),
    )
    monkeypatch.setattr(
        source_collection_runs,
        "get_source_collection_summary",
        _fake_summary(record_count=12, candidate_count=5),
    )
    result = facade.research_knowledge_collection_facade(
        action="inspect",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
    )
    assert result["status"] == "ok"
    assert result["searchEnvelope"]["keywords"] == ["predictive coding", "neural plasticity"]
    assert result["searchEnvelope"]["sourceTypes"] == ["paper", "dataset"]
    assert result["searchEnvelope"]["timeRange"] == {"from": "2020-01-01", "to": "2026-08-17"}
    assert result["searchEnvelope"]["domains"] == ["neuroscience"]
    assert result["searchEnvelope"]["repos"] == ["repo-a"]
    assert result["searchEnvelope"]["kb"] == ["kb-neuro"]
    assert result["searchEnvelope"]["languages"] == ["en", "zh"]
    assert result["searchEnvelope"]["evidenceLevels"] == ["primary", "peer_reviewed"]
    assert result["searchEnvelope"]["forbiddenScope"] == ["marketing"]


def test_facade_ensure_requires_keywords(monkeypatch):
    with pytest.raises(facade.ResearchKnowledgeCollectionError) as exc:
        facade.research_knowledge_collection_facade(
            action="ensure",
            scope=_valid_envelope(),
            searchEnvelope={"sourceTypes": ["paper"]},
        )
    assert exc.value.code == "search_keywords_required"


def test_facade_rejects_provider_or_writeback_policy(monkeypatch):
    for key in (
        "writesFormalKnowledge",
        "writesRag",
        "writesOfficialGraph",
        "providerWriteback",
        "directStageWriteback",
        "networkExecution",
        "autoApply",
    ):
        with pytest.raises(facade.ResearchKnowledgeCollectionError) as exc:
            facade.research_knowledge_collection_facade(
                action="ensure",
                scope=_valid_envelope(),
                searchEnvelope=_valid_search_envelope(),
                writebackPolicy={key: True},
            )
        assert exc.value.code == "writeback_policy_rejected"


def test_facade_inspect_is_strictly_read_only_and_distilled(monkeypatch):
    created = []
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs(
            [
                {
                    "runId": "dprun-existing",
                    "updatedAt": "2026-08-17T00:00:00Z",
                    "createdAt": "2026-08-16T00:00:00Z",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        source_collection_runs,
        "start_source_collection_run",
        lambda *args, **kwargs: created.append(args) or {},
    )
    monkeypatch.setattr(
        source_collection_runs,
        "get_source_collection_summary",
        _fake_summary(record_count=12, candidate_count=5),
    )

    result = facade.research_knowledge_collection_facade(
        action="inspect",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
    )

    assert result["status"] == "ok"
    assert result["action"] == "inspect"
    assert result["found"] is True
    assert result["created"] is False
    assert result["locator"]["runId"] == "dprun-existing"
    assert result["locator"]["scopeHash"] == _valid_envelope()["scopeHash"]
    assert result["locator"]["artifactLocator"].startswith("research-artifact://")
    assert result["locator"]["ledgerRoot"].startswith("research-ledger://")
    assert result["locator"]["cacheKey"].startswith("scope:")
    assert result["summary"]["available"] is True
    assert result["summary"]["counts"]["recordCount"] == 12
    assert result["summary"]["counts"]["sourceCandidateCount"] == 5
    assert "fullText" not in json.dumps(result)
    assert created == []


def test_facade_inspect_returns_not_found_without_creating(monkeypatch):
    created = []
    monkeypatch.setattr(data_processing_service, "list_processing_runs", _fake_list_runs())
    monkeypatch.setattr(
        source_collection_runs,
        "start_source_collection_run",
        lambda *args, **kwargs: created.append(args) or {},
    )
    result = facade.research_knowledge_collection_facade(
        action="inspect",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
    )
    assert result["status"] == "not_found"
    assert result["found"] is False
    assert result["locator"]["runId"] == ""
    assert result["summary"]["available"] is False
    assert created == []


def test_facade_ensure_is_idempotent_when_state_exists(monkeypatch):
    created = []
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs([{"runId": "dprun-existing", "updatedAt": "2026-08-17T00:00:00Z"}]),
    )
    monkeypatch.setattr(
        source_collection_runs,
        "start_source_collection_run",
        lambda *args, **kwargs: created.append(args) or {},
    )
    monkeypatch.setattr(
        source_collection_runs,
        "get_source_collection_summary",
        _fake_summary(record_count=12),
    )

    first = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
    )
    second = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
    )

    assert first["status"] == "ok"
    assert first["created"] is False
    assert first["idempotent"] is True
    assert first["locator"]["runId"] == "dprun-existing"
    assert second["idempotent"] is True
    assert second["locator"]["runId"] == "dprun-existing"
    assert created == []


def test_facade_ensure_creates_run_when_missing(monkeypatch):
    created_payloads = []

    def fake_list(**kwargs):
        assert kwargs["scope_filters"] == {"researchScopeHash": _valid_envelope()["scopeHash"]}
        assert kwargs["metadata_filters"] == {
            "startedFrom": "team_workflow_source_collection",
            "teamId": "research-team",
        }
        return {"runs": []}

    monkeypatch.setattr(data_processing_service, "list_processing_runs", fake_list)

    def fake_start(team_id, payload):
        created_payloads.append((team_id, dict(payload)))
        return {"runId": "dprun-new", "run": {"runId": "dprun-new"}}

    monkeypatch.setattr(source_collection_runs, "start_source_collection_run", fake_start)
    monkeypatch.setattr(
        source_collection_runs,
        "get_source_collection_summary",
        _fake_summary(),
    )

    result = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
    )

    assert result["status"] == "ok"
    assert result["created"] is True
    assert result["idempotent"] is False
    assert result["locator"]["runId"] == "dprun-new"
    assert len(created_payloads) == 1
    team_id, payload = created_payloads[0]
    assert team_id == "research-team"
    assert payload["scope"]["researchScopeHash"] == _valid_envelope()["scopeHash"]
    assert payload["scope"]["researchScopeCacheKey"].startswith("scope:")
    assert payload["scope"]["searchEnvelope"]["keywords"] == ["predictive coding", "neural plasticity"]
    assert payload["scope"]["writebackPolicy"]["providerWriteback"] is False
    assert payload["agentRoles"] == ["source_finder"]
    assert payload["requestedByAgent"] == "agent-alpha"
    assert payload["ownerAgentId"] == "agent-alpha"


def test_facade_surfaces_run_lookup_failure(monkeypatch):
    def fail_list(**kwargs):
        raise data_processing_service.DataProcessingError("lookup failed")

    monkeypatch.setattr(data_processing_service, "list_processing_runs", fail_list)
    with pytest.raises(facade.ResearchKnowledgeCollectionError) as exc:
        facade.research_knowledge_collection_facade(
            action="inspect",
            scope=_valid_envelope(),
            searchEnvelope=_valid_search_envelope(),
        )
    assert exc.value.code == "run_lookup_failed"


def test_facade_surfaces_run_creation_failure(monkeypatch):
    monkeypatch.setattr(data_processing_service, "list_processing_runs", _fake_list_runs())

    def fail_start(team_id, payload):
        raise RuntimeError("start failed")

    monkeypatch.setattr(source_collection_runs, "start_source_collection_run", fail_start)
    with pytest.raises(facade.ResearchKnowledgeCollectionError) as exc:
        facade.research_knowledge_collection_facade(
            action="ensure",
            scope=_valid_envelope(),
            searchEnvelope=_valid_search_envelope(),
        )
    assert exc.value.code == "run_creation_failed"