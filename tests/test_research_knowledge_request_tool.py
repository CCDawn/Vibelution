"""Focused tests for the hypothesis-side research_knowledge_request_tool.

The tool wraps the D03 stage-1 collection facade with advisory,
non-blocking semantics for the experiment planner role. These tests pin:

- server-side scope resolution from the bound planner task (no caller scope);
- request/status facade delegation (ensure/inspect, keywords normalization);
- preview advisory semantics (dev fixture provider, formal provider,
  platform authorization refusal, no citable evidence fields);
- fail-closed error codes.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools import research_knowledge_request_tools as request_tools


def _parse(payload: str) -> dict:
    return json.loads(payload)


@pytest.fixture()
def bound_scope(monkeypatch):
    """Patch the binding/run/scope resolution chain to one dev question."""

    def fake_binding(workflow_service, **kwargs):
        assert kwargs.get("load_context") is True
        assert kwargs.get("allowed_task_kinds") == request_tools._PLANNER_TASK_KINDS
        return {"task": {"taskId": "task-1", "taskKind": "hypothesis_design", "workflowRunId": "run-1"}}

    class FakeRuntimeService:
        def get_run(self, run_id: str) -> dict:
            assert run_id == "run-1"
            return {"runId": "run-1", "teamId": "research-team", "questionId": "SCI-096"}

    def fake_seed(team_id: str, question_id: str) -> dict:
        return {
            "program": "XH-202619",
            "theme": f"dev-{question_id.lower()}",
            "campaign": "dev-campaign",
            "question": question_id,
            "branch": "main",
            "workflow": "hypothesis_first",
            "agentId": "operator",
            "mode": "dev",
        }

    def fake_resolve(team_id: str, *, agent_id: str, scope_seed: dict) -> dict:
        return {
            **scope_seed,
            "agentId": agent_id,
            "scopeHash": "a" * 64,
            "artifactLocator": "research-artifact://XH-202619/aaa",
            "ledgerRoot": "research-ledger://XH-202619/aaa",
            "cacheKey": "scope:aaa:main:operator",
        }

    monkeypatch.setattr(
        "tools.challenge_cup_operations_tools._project_task_binding", fake_binding
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.get_research_workflow_runtime_service",
        lambda: FakeRuntimeService(),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.hypothesis_first_chain._question_scope_envelope",
        fake_seed,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_scope.resolve_research_scope",
        fake_resolve,
    )
    return fake_resolve


@pytest.fixture()
def facade_calls(monkeypatch):
    calls: list[dict] = []

    def fake_facade(**kwargs):
        calls.append(kwargs)
        return {
            "action": kwargs["action"],
            "status": "ok",
            "created": True,
            "idempotent": False,
            "locator": {"runId": "collect-1"},
            "summary": {"stage": "search", "recordCount": 3},
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.facade.research_knowledge_collection_facade",
        fake_facade,
    )
    return calls


def test_unknown_action_fails_closed():
    result = _parse(request_tools.research_knowledge_request_tool(action="ensure"))
    assert result["ok"] is False
    assert result["error"] == "unsupported_action"


def test_missing_binding_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "tools.challenge_cup_operations_tools._project_task_binding", lambda *a, **k: None
    )
    result = _parse(request_tools.research_knowledge_request_tool(action="status"))
    assert result["ok"] is False
    assert result["error"] == "no_bound_task"


def test_run_team_mismatch_fails_closed(monkeypatch, bound_scope):
    class OtherTeamService:
        def get_run(self, run_id: str) -> dict:
            return {"runId": "run-1", "teamId": "other-team", "questionId": "SCI-096"}

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.get_research_workflow_runtime_service",
        lambda: OtherTeamService(),
    )
    result = _parse(request_tools.research_knowledge_request_tool(action="status"))
    assert result["ok"] is False
    assert result["error"] == "run_team_mismatch"


def test_request_requires_keywords(bound_scope, facade_calls):
    result = _parse(request_tools.research_knowledge_request_tool(action="request", keywords="  "))
    assert result["ok"] is False
    assert result["error"] == "keywords_required"
    assert facade_calls == []


def test_request_delegates_to_facade_ensure_and_stays_advisory(bound_scope, facade_calls):
    result = _parse(
        request_tools.research_knowledge_request_tool(
            action="request",
            keywords="predictive coding, spike coding\nredundancy; predictive coding",
        )
    )
    assert result["ok"] is True
    assert result["action"] == "request"
    assert result["keywords"] == ["predictive coding", "spike coding", "redundancy"]
    assert result["scope"]["questionId"] == "SCI-096"
    assert result["scope"]["mode"] == "dev"
    assert result["scope"]["scopeHash"] == "a" * 64
    assert result["collection"]["runId"] == "collect-1"
    assert result["advisory"]["blocking"] is False
    assert facade_calls[0]["action"] == "ensure"
    assert facade_calls[0]["team_id"] == "research-team"
    assert facade_calls[0]["searchEnvelope"]["keywords"] == [
        "predictive coding",
        "spike coding",
        "redundancy",
    ]
    assert facade_calls[0]["scope"]["scopeHash"] == "a" * 64


def test_status_delegates_to_facade_inspect(bound_scope, facade_calls):
    result = _parse(request_tools.research_knowledge_request_tool(action="status"))
    assert result["ok"] is True
    assert result["action"] == "status"
    assert facade_calls[0]["action"] == "inspect"


def test_preview_requires_query_and_kind(bound_scope):
    assert _parse(request_tools.research_knowledge_request_tool(action="preview"))[
        "error"
    ] == "preview_query_required"
    assert _parse(
        request_tools.research_knowledge_request_tool(
            action="preview", preview_query="x", preview_kind="video"
        )
    )["error"] == "preview_kind_invalid"


def test_preview_dev_mode_uses_fixture_provider_and_stays_advisory(bound_scope, monkeypatch):
    provider = SimpleNamespace(
        provider_name="deterministic-research-search",
        search_papers=lambda query: [
            SimpleNamespace(
                title="Fixture paper",
                url="https://example.com/paper",
                summary="Deterministic DEV fixture abstract.",
            )
        ],
    )
    monkeypatch.setattr(request_tools, "_dev_preview_provider", lambda: provider)
    result = _parse(
        request_tools.research_knowledge_request_tool(
            action="preview", preview_query="spike coding", preview_kind="paper"
        )
    )
    assert result["ok"] is True
    preview = result["preview"]
    assert preview["advisoryOnly"] is True
    assert "allowedEvidenceRefs" in preview["citationPolicy"]
    assert preview["provider"] == "deterministic-research-search"
    assert preview["items"] == [
        {
            "title": "Fixture paper",
            "url": "https://example.com/paper",
            "summary": "Deterministic DEV fixture abstract.",
        }
    ]
    flat = json.dumps(result)
    assert "evidenceRef" not in flat
    assert "sourceIds" not in flat


def test_preview_formal_mode_uses_public_provider(bound_scope, monkeypatch):
    provider = SimpleNamespace(
        provider_name="public-research-search",
        search_datasets=lambda query: [
            SimpleNamespace(title="Dataset", url="https://example.com/d", summary="s")
        ],
    )
    monkeypatch.setattr(request_tools, "_formal_preview_provider", lambda: provider)
    envelope_mode = bound_scope

    def formal_resolve(team_id: str, *, agent_id: str, scope_seed: dict) -> dict:
        payload = envelope_mode(team_id, agent_id=agent_id, scope_seed=scope_seed)
        payload["mode"] = "formal"
        return payload

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_scope.resolve_research_scope",
        formal_resolve,
    )
    result = _parse(
        request_tools.research_knowledge_request_tool(
            action="preview", preview_query="dataset", preview_kind="dataset"
        )
    )
    assert result["ok"] is True
    assert result["scope"]["mode"] == "formal"
    assert result["preview"]["provider"] == "public-research-search"


def test_preview_platform_mode_refuses_before_authorization(bound_scope, monkeypatch):
    def platform_resolve(team_id: str, *, agent_id: str, scope_seed: dict) -> dict:
        payload = bound_scope(team_id, agent_id=agent_id, scope_seed=scope_seed)
        payload["mode"] = "platform"
        return payload

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_scope.resolve_research_scope",
        platform_resolve,
    )
    monkeypatch.setattr(
        request_tools, "_formal_preview_provider", lambda: pytest.fail("must not run")
    )
    result = _parse(
        request_tools.research_knowledge_request_tool(
            action="preview", preview_query="anything"
        )
    )
    assert result["ok"] is False
    assert result["error"] == "research_authorization_required"


def test_keyword_split_is_bounded_and_deduplicated():
    keywords = request_tools._split_keywords("a, " + "x" * 300 + "\nb, a, b; c")
    assert len(keywords) <= request_tools._MAX_KEYWORDS
    assert len(set(keywords)) == len(keywords)
    assert all(len(item) <= request_tools._MAX_KEYWORD_LENGTH for item in keywords)


def test_request_status_through_real_facade_and_scope(tmp_path, monkeypatch):
    """Composition test mirroring the hypothesis-first e2e pattern.

    Only the task-anchoring seams (project task binding, workflow run lookup)
    and the data-processing run layer are faked; the scope seed, envelope
    resolution, facade normalization, and scope-hash idempotency all run the
    real production code. SCI-099 is not in the frozen theme registry, so the
    real resolution takes the dev-theme fallback without touching storage.
    """

    from core.web.services import data_processing_service
    from core.web.services.team_workflow.source_collection import runs as collection_runs

    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))

    def fake_binding(workflow_service, **kwargs):
        return {
            "task": {
                "taskId": "task-9",
                "taskKind": "hypothesis_design",
                "workflowRunId": "run-9",
            }
        }

    class FakeRunService:
        def get_run(self, run_id: str) -> dict:
            assert run_id == "run-9"
            return {"runId": "run-9", "teamId": "research-team", "questionId": "SCI-099"}

    monkeypatch.setattr(
        "tools.challenge_cup_operations_tools._project_task_binding", fake_binding
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.get_research_workflow_runtime_service",
        lambda: FakeRunService(),
    )

    created: list[dict] = []

    def fake_start(team_id, payload=None):
        created.append(dict(payload or {}))
        return {"runId": f"dprun-kr-{len(created)}", "status": "accepted"}

    def fake_list_runs(*, limit=200, metadata_filters=None, scope_filters=None, **_):
        scope_hash = str((scope_filters or {}).get("researchScopeHash") or "")
        expected_fingerprint = str(
            (metadata_filters or {}).get("searchEnvelopeFingerprint") or ""
        )
        runs = []
        for index, item in enumerate(created):
            if (
                scope_hash
                and str(item.get("scope", {}).get("researchScopeHash") or "") != scope_hash
            ):
                continue
            run_fingerprint = str(item.get("searchEnvelopeFingerprint") or "")
            if expected_fingerprint and run_fingerprint != expected_fingerprint:
                continue
            runs.append(
                {
                    "runId": f"dprun-kr-{index + 1}",
                    "createdAt": "2026-08-21T00:00:00Z",
                    "updatedAt": "2026-08-21T00:00:00Z",
                    "metadata": (
                        {
                            "startedFrom": "team_workflow_source_collection",
                            "searchEnvelopeFingerprint": run_fingerprint,
                        }
                        if run_fingerprint
                        else {}
                    ),
                }
            )
        return {"runs": runs}

    def fake_summary(team_id, run_id=""):
        return {
            "status": "accepted",
            "runId": run_id,
            "run": {"runId": run_id, "status": "accepted"},
            "runStatus": {"status": "accepted", "currentPhase": "queued"},
            "summary": {"recordCount": 0, "sourceCandidateCount": 0},
            "stageCards": [],
        }

    monkeypatch.setattr(collection_runs, "start_source_collection_run", fake_start)
    monkeypatch.setattr(collection_runs, "get_source_collection_summary", fake_summary)
    monkeypatch.setattr(data_processing_service, "list_processing_runs", fake_list_runs)

    first = _parse(
        request_tools.research_knowledge_request_tool(action="request", keywords="spike coding")
    )
    second = _parse(
        request_tools.research_knowledge_request_tool(action="request", keywords="spike coding")
    )
    status = _parse(request_tools.research_knowledge_request_tool(action="status"))

    assert first["ok"] is True
    assert first["collection"]["created"] is True
    assert first["scope"]["questionId"] == "SCI-099"
    assert first["scope"]["mode"] == "dev"
    assert first["scope"]["themeId"].startswith("dev-")
    assert second["ok"] is True
    assert second["collection"]["idempotent"] is True
    assert second["collection"]["runId"] == first["collection"]["runId"]
    assert len(created) == 1
    assert created[0]["scope"]["researchScopeHash"] == first["scope"]["scopeHash"]
    assert status["ok"] is True
    assert status["collection"]["facadeStatus"] == "ok"
    assert status["collection"]["runId"] == first["collection"]["runId"]
