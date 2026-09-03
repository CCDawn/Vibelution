"""D03 stage-1 knowledge collection facade contract tests.

Verifies that the single facade validates the ResearchScopeEnvelope and the
search envelope, is idempotent for ``ensure``, strictly read-only for
``inspect``, and returns only distilled summary/status/locator.
"""

from __future__ import annotations

import json

import pytest

from core.research.workflow.contracts import scope_hash_for
from core.web.services import (
    agent_directory_service,
    data_processing_service,
    session_service,
    team_service,
    team_workflow_orchestration_service,
)
from core.web.services.team_workflow.source_collection import facade
from core.web.services.team_workflow.source_collection import runs as source_collection_runs
from tests._support.team_workflow.helpers import (
    _use_fake_local_research_config,
    _use_tmp_project_root,
)


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


def _normalized_search(search_raw=None) -> dict:
    return facade._normalize_search_envelope(search_raw or _valid_search_envelope())


def _request_fingerprint(search_raw=None, requirements=None) -> str:
    return facade.search_envelope_fingerprint(
        _normalized_search(search_raw),
        facade._normalize_requirements(requirements),
    )


def _stored_run(
    run_id: str,
    *,
    updated_at: str,
    fingerprint: str = "",
    status: str = "",
) -> dict:
    """Build a stored source-collection run as list_processing_runs returns it."""
    metadata: dict = {
        "startedFrom": "team_workflow_source_collection",
        "teamId": "research-team",
    }
    if fingerprint:
        metadata["searchEnvelopeFingerprint"] = fingerprint
    run = {
        "runId": run_id,
        "updatedAt": updated_at,
        "createdAt": updated_at,
        "metadata": metadata,
        "scope": {"researchScopeHash": _valid_envelope()["scopeHash"]},
    }
    if status:
        run["status"] = status
    return run


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
    existing = _stored_run(
        "dprun-existing",
        updated_at="2026-08-17T00:00:00Z",
        fingerprint=_request_fingerprint(),
    )
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs([existing]),
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
    expected_fingerprint = _request_fingerprint()

    def fake_list(**kwargs):
        assert kwargs["scope_filters"] == {"researchScopeHash": _valid_envelope()["scopeHash"]}
        assert kwargs["metadata_filters"] == {
            "startedFrom": "team_workflow_source_collection",
            "teamId": "research-team",
            "searchEnvelopeFingerprint": expected_fingerprint,
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
    assert payload["searchEnvelopeFingerprint"] == expected_fingerprint
    assert payload["scope"]["researchScopeHash"] == _valid_envelope()["scopeHash"]
    assert payload["scope"]["researchScopeCacheKey"].startswith("scope:")
    assert payload["scope"]["searchEnvelope"]["keywords"] == ["predictive coding", "neural plasticity"]
    assert payload["scope"]["writebackPolicy"]["providerWriteback"] is False
    assert payload["agentRoles"] == ["source_finder"]
    assert payload["requestedByAgent"] == "agent-alpha"
    assert payload["ownerAgentId"] == "agent-alpha"


def test_facade_ensure_persists_hypothesis_candidate_ids_on_run_scope(monkeypatch):
    """ensure persists the gate's candidate dimension without breaking reuse.

    ``hypothesisCandidateIds`` are normalized (strip/dedupe) onto the created
    run's scope; they deliberately do NOT participate in the ensure
    fingerprint, so the same evidence request stays idempotent regardless of
    which hypothesis candidates a replay carries.
    """
    created_payloads = []

    def fake_start(team_id, payload):
        created_payloads.append((team_id, dict(payload)))
        return {"runId": "dprun-hf", "run": {"runId": "dprun-hf"}}

    monkeypatch.setattr(data_processing_service, "list_processing_runs", _fake_list_runs())
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
        hypothesisCandidateIds=[
            "sci-091-c1a2b3c4",
            "sci-091-c1a2b3c4",
            " ",
            "sci-091-c9f8e7d6c",
        ],
    )

    assert result["created"] is True
    assert created_payloads[0][1]["scope"]["hypothesisCandidateIds"] == [
        "sci-091-c1a2b3c4",
        "sci-091-c9f8e7d6c",
    ]

    # Default (no candidates) keeps the field present but empty.
    created_payloads.clear()
    facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
    )
    assert created_payloads[0][1]["scope"]["hypothesisCandidateIds"] == []

    # Replays with different candidates reuse the same run (fingerprint only
    # covers the evidence request itself).
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs(
            [
                _stored_run(
                    "dprun-hf",
                    updated_at="2026-08-28T00:00:00Z",
                    fingerprint=_request_fingerprint(),
                )
            ]
        ),
    )
    created_payloads.clear()
    replay = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
        hypothesisCandidateIds=["sci-091-cdeadbeef"],
    )
    assert replay["idempotent"] is True
    assert replay["locator"]["runId"] == "dprun-hf"
    assert created_payloads == []


def test_facade_ensure_pins_workflow_run_and_question_project_on_payload(monkeypatch):
    """Chain collection pins the question's formal run and canonical project.

    ``workflowRunId`` reaches the created run payload's scope so extraction-claim
    materialization and formal node discovery can find the run by scope alone;
    ``researchProjectId`` travels top-level so ``start_source_collection_run``
    binds the question-owned project instead of the team's active-project
    pointer.  Omitted or blank values keep the legacy payload unchanged, and
    neither field participates in the ensure fingerprint.
    """
    created_payloads = []

    def fake_start(team_id, payload):
        created_payloads.append(dict(payload))
        return {"runId": "dprun-pinned", "run": {"runId": "dprun-pinned"}}

    monkeypatch.setattr(data_processing_service, "list_processing_runs", _fake_list_runs())
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
        workflowRunId=" run-hf-formal ",
        researchProjectId="challenge-sci-003",
    )

    assert result["status"] == "ok"
    assert result["created"] is True
    payload = created_payloads[0]
    assert payload["scope"]["workflowRunId"] == "run-hf-formal"
    assert payload["researchProjectId"] == "challenge-sci-003"
    # The ensure fingerprint (reuse identity) must not cover the binding.
    assert payload["searchEnvelopeFingerprint"] == _request_fingerprint()

    # Blank bindings keep the legacy payload shape (no empty scope noise).
    created_payloads.clear()
    facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
        workflowRunId="   ",
        researchProjectId="",
    )
    legacy_payload = created_payloads[0]
    assert "workflowRunId" not in legacy_payload["scope"]
    assert "researchProjectId" not in legacy_payload

    # A replay that reuses the existing run never reaches run creation again.
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs(
            [
                _stored_run(
                    "dprun-pinned",
                    updated_at="2026-08-28T00:00:00Z",
                    fingerprint=_request_fingerprint(),
                )
            ]
        ),
    )
    created_payloads.clear()
    replay = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
        workflowRunId="run-hf-formal",
        researchProjectId="challenge-sci-003",
    )
    assert replay["idempotent"] is True
    assert replay["locator"]["runId"] == "dprun-pinned"
    assert created_payloads == []


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


def test_facade_ensure_policy_version_bump_does_not_reuse_pre_arxiv_runs(monkeypatch):
    """The arXiv-provider policy bump invalidates v1 evidence fingerprints.

    A run fingerprinted under source policy v1 was collected without arXiv
    coverage, so an ensure replay under v2 must create a fresh run instead of
    silently reusing the stale one; runs fingerprinted under v2 still reuse.
    """
    legacy_fingerprint = facade.search_envelope_fingerprint(
        facade._normalize_search_envelope(_valid_search_envelope()),
        facade._normalize_requirements({}),
        source_policy_version="1",
    )
    assert legacy_fingerprint != _request_fingerprint()

    created_payloads = []

    def fake_start(team_id, payload):
        created_payloads.append((team_id, dict(payload)))
        return {"runId": "dprun-v2", "run": {"runId": "dprun-v2"}}

    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs(
            [
                _stored_run(
                    "dprun-v1",
                    updated_at="2026-08-28T00:00:00Z",
                    fingerprint=legacy_fingerprint,
                )
            ]
        ),
    )
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

    assert result["created"] is True
    assert created_payloads != []

    # A run fingerprinted under the current (v2) policy still reuses.
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs(
            [
                _stored_run(
                    "dprun-v2",
                    updated_at="2026-08-28T00:00:00Z",
                    fingerprint=_request_fingerprint(),
                )
            ]
        ),
    )
    created_payloads.clear()
    replay = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
    )
    assert replay["idempotent"] is True
    assert replay["locator"]["runId"] == "dprun-v2"
    assert created_payloads == []


def test_facade_ensure_policy_version_bump_does_not_reuse_pre_openalex_runs(monkeypatch):
    """The OpenAlex-provider policy bump invalidates v2 evidence fingerprints.

    A run fingerprinted under source policy v2 was collected without OpenAlex
    coverage, so an ensure replay under v3 must create a fresh run instead of
    silently reusing the stale one; runs fingerprinted under v3 still reuse.
    """
    legacy_fingerprint = facade.search_envelope_fingerprint(
        facade._normalize_search_envelope(_valid_search_envelope()),
        facade._normalize_requirements({}),
        source_policy_version="2",
    )
    assert legacy_fingerprint != _request_fingerprint()

    created_payloads = []

    def fake_start(team_id, payload):
        created_payloads.append((team_id, dict(payload)))
        return {"runId": "dprun-v3", "run": {"runId": "dprun-v3"}}

    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs(
            [
                _stored_run(
                    "dprun-v2",
                    updated_at="2026-08-28T00:00:00Z",
                    fingerprint=legacy_fingerprint,
                )
            ]
        ),
    )
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

    assert result["created"] is True
    assert created_payloads != []

    # A run fingerprinted under the current (v3) policy still reuses.
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs(
            [
                _stored_run(
                    "dprun-v3",
                    updated_at="2026-08-28T00:00:00Z",
                    fingerprint=_request_fingerprint(),
                )
            ]
        ),
    )
    created_payloads.clear()
    replay = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
    )
    assert replay["idempotent"] is True
    assert replay["locator"]["runId"] == "dprun-v3"
    assert created_payloads == []


def test_search_envelope_fingerprint_is_canonical_and_order_insensitive():
    a = facade.search_envelope_fingerprint(
        facade._normalize_search_envelope({"keywords": ["b 关键词", "a keyword"]}),
        {},
    )
    b = facade.search_envelope_fingerprint(
        facade._normalize_search_envelope({"keywords": ["a keyword", "b 关键词"]}),
        {},
    )
    assert a == b
    assert len(a) == 64
    assert a == a.lower()


def test_search_envelope_fingerprint_changes_with_keywords_and_requirements():
    base = facade.search_envelope_fingerprint(
        facade._normalize_search_envelope({"keywords": ["alpha"]}),
        {},
    )
    other_keywords = facade.search_envelope_fingerprint(
        facade._normalize_search_envelope({"keywords": ["alpha", "beta"]}),
        {},
    )
    other_requirements = facade.search_envelope_fingerprint(
        facade._normalize_search_envelope({"keywords": ["alpha"]}),
        {"minEvidenceLevel": "primary"},
    )
    other_policy = facade.search_envelope_fingerprint(
        facade._normalize_search_envelope({"keywords": ["alpha"]}),
        {},
        # v4 became the default when the qwen deep-search supplement landed;
        # the fingerprint must still react to any other explicit version.
        source_policy_version="5",
    )
    assert base != other_keywords
    assert base != other_requirements
    assert base != other_policy


def test_facade_ensure_creates_new_run_for_new_keywords(monkeypatch):
    created_payloads = []
    stale = _stored_run(
        "dprun-old",
        updated_at="2026-08-27T00:00:00Z",
        fingerprint=_request_fingerprint({"keywords": ["old topic"]}),
    )
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs([stale]),
    )

    def fake_start(team_id, payload):
        created_payloads.append(dict(payload))
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
        searchEnvelope={"keywords": ["new topic"]},
    )

    assert result["status"] == "ok"
    assert result["created"] is True
    assert result["idempotent"] is False
    assert result["locator"]["runId"] == "dprun-new"
    assert len(created_payloads) == 1
    assert created_payloads[0]["searchEnvelopeFingerprint"] == _request_fingerprint(
        {"keywords": ["new topic"]}
    )


def test_facade_ensure_replays_same_envelope_idempotently(monkeypatch):
    created = []
    fingerprint = _request_fingerprint()
    existing = _stored_run(
        "dprun-same",
        updated_at="2026-08-27T00:00:00Z",
        fingerprint=fingerprint,
    )
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs([existing]),
    )
    monkeypatch.setattr(
        source_collection_runs,
        "start_source_collection_run",
        lambda *args, **kwargs: created.append(args) or {},
    )
    monkeypatch.setattr(
        source_collection_runs,
        "get_source_collection_summary",
        _fake_summary(record_count=7),
    )

    result = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
    )

    assert result["status"] == "ok"
    assert result["created"] is False
    assert result["idempotent"] is True
    assert result["locator"]["runId"] == "dprun-same"
    assert created == []


def test_facade_ensure_creates_new_run_after_cancelled_attempt(monkeypatch):
    """A cancelled attempt is dead state: ensure must re-create, not re-bind.

    Regression guard for the stop→retry livelock: recovery reused the cancelled
    run id, restarted a search on a terminal run, and every retry settled back
    to failed/cancelled without executing anything.
    """
    created = []
    fingerprint = _request_fingerprint()
    cancelled = _stored_run(
        "dprun-stopped",
        updated_at="2026-09-01T23:49:00Z",
        fingerprint=fingerprint,
        status="cancelled",
    )
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs([cancelled]),
    )
    monkeypatch.setattr(
        source_collection_runs,
        "start_source_collection_run",
        lambda *args, **kwargs: created.append(args) or {"runId": "dprun-fresh", "run": {"runId": "dprun-fresh"}},
    )
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

    assert result["created"] is True
    assert result["idempotent"] is False
    assert result["locator"]["runId"] == "dprun-fresh"
    assert created


def test_facade_ensure_creates_new_run_after_failed_attempt(monkeypatch):
    created = []
    failed = _stored_run(
        "dprun-errored",
        updated_at="2026-09-01T23:49:00Z",
        fingerprint=_request_fingerprint(),
        status="failed",
    )
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs([failed]),
    )
    monkeypatch.setattr(
        source_collection_runs,
        "start_source_collection_run",
        lambda *args, **kwargs: created.append(args) or {"runId": "dprun-retry", "run": {"runId": "dprun-retry"}},
    )
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

    assert result["created"] is True
    assert result["locator"]["runId"] == "dprun-retry"


def test_facade_ensure_still_reuses_completed_run(monkeypatch):
    """Completed runs remain idempotent reusable state (double-click guard)."""
    created = []
    fingerprint = _request_fingerprint()
    completed = _stored_run(
        "dprun-done",
        updated_at="2026-09-01T22:16:03Z",
        fingerprint=fingerprint,
        status="completed",
    )
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs([completed]),
    )
    monkeypatch.setattr(
        source_collection_runs,
        "start_source_collection_run",
        lambda *args, **kwargs: created.append(args) or {},
    )
    monkeypatch.setattr(
        source_collection_runs,
        "get_source_collection_summary",
        _fake_summary(record_count=7),
    )

    result = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
    )

    assert result["created"] is False
    assert result["idempotent"] is True
    assert result["locator"]["runId"] == "dprun-done"
    assert created == []


def test_facade_inspect_still_finds_latest_cancelled_run(monkeypatch):
    """inspect keeps surfacing the latest run regardless of terminal status."""
    cancelled = _stored_run(
        "dprun-stopped",
        updated_at="2026-09-01T23:49:00Z",
        status="cancelled",
    )
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs([cancelled]),
    )
    monkeypatch.setattr(
        source_collection_runs,
        "get_source_collection_summary",
        _fake_summary(),
    )

    result = facade.research_knowledge_collection_facade(
        action="inspect",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
    )

    assert result["found"] is True
    assert result["locator"]["runId"] == "dprun-stopped"


def test_facade_ensure_creates_new_run_for_new_requirements(monkeypatch):
    created = []
    existing = _stored_run(
        "dprun-relaxed",
        updated_at="2026-08-27T00:00:00Z",
        fingerprint=_request_fingerprint(requirements={}),
    )
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs([existing]),
    )
    monkeypatch.setattr(
        source_collection_runs,
        "start_source_collection_run",
        lambda *args, **kwargs: created.append(args) or {"runId": "dprun-new"},
    )
    monkeypatch.setattr(
        source_collection_runs,
        "get_source_collection_summary",
        _fake_summary(),
    )

    result = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
        requirements={"minEvidenceLevel": "primary"},
    )

    assert result["created"] is True
    assert result["idempotent"] is False
    assert created


def test_facade_ensure_never_reuses_run_without_fingerprint(monkeypatch):
    created = []
    legacy = _stored_run("dprun-legacy", updated_at="2026-08-27T00:00:00Z")
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs([legacy]),
    )
    monkeypatch.setattr(
        source_collection_runs,
        "start_source_collection_run",
        lambda *args, **kwargs: created.append(args) or {"runId": "dprun-new"},
    )
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

    assert result["created"] is True
    assert result["idempotent"] is False
    assert result["locator"]["runId"] == "dprun-new"
    assert created


def test_facade_ensure_picks_latest_run_within_same_fingerprint(monkeypatch):
    fingerprint = _request_fingerprint()
    runs_list = [
        _stored_run(
            "dprun-older",
            updated_at="2026-08-26T00:00:00Z",
            fingerprint=fingerprint,
        ),
        _stored_run(
            "dprun-newest",
            updated_at="2026-08-27T12:00:00Z",
            fingerprint=fingerprint,
        ),
    ]
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs(runs_list),
    )
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

    assert result["idempotent"] is True
    assert result["locator"]["runId"] == "dprun-newest"


def test_facade_inspect_still_finds_latest_run_regardless_of_fingerprint(monkeypatch):
    created = []
    differing = _stored_run(
        "dprun-inspect",
        updated_at="2026-08-27T00:00:00Z",
        fingerprint=_request_fingerprint({"keywords": ["unrelated topic"]}),
    )
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        _fake_list_runs([differing]),
    )
    monkeypatch.setattr(
        source_collection_runs,
        "start_source_collection_run",
        lambda *args, **kwargs: created.append(args) or {},
    )
    monkeypatch.setattr(
        source_collection_runs,
        "get_source_collection_summary",
        _fake_summary(record_count=4),
    )

    result = facade.research_knowledge_collection_facade(
        action="inspect",
        scope=_valid_envelope(),
        searchEnvelope=_valid_search_envelope(),
    )

    assert result["action"] == "inspect"
    assert result["found"] is True
    assert result["created"] is False
    assert result["locator"]["runId"] == "dprun-inspect"
    assert created == []


def test_start_source_collection_run_persists_search_envelope_fingerprint(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="知识搜集团队",
        members=[{"agentId": agent["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )
    fingerprint = facade.search_envelope_fingerprint(
        facade._normalize_search_envelope({"keywords": ["predictive coding"]}),
        {},
    )

    response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "知识搜集",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": agent["agentId"]},
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
            "searchEnvelopeFingerprint": fingerprint,
        },
    )

    run = response["run"]
    assert run["metadata"]["startedFrom"] == "team_workflow_source_collection"
    assert run["metadata"]["searchEnvelopeFingerprint"] == fingerprint


def test_start_source_collection_run_without_fingerprint_omits_metadata_key(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料寻找")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料寻找")
    team = team_service.create_team(
        name="普通搜集团队",
        members=[{"agentId": agent["agentId"], "role": "source_finder", "agentName": "资料寻找"}],
    )

    response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "常规搜集",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": agent["agentId"]},
            "querySeeds": ["sleep homeostasis"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )

    run = response["run"]
    assert "searchEnvelopeFingerprint" not in run["metadata"]