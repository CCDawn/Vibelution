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

from core.research.workflow.contracts import WorkflowCommandKind
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
    calls = []

    class FakeCommandService:
        def submit(self, request):
            calls.append(request)
            if request.command is WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION:
                return SimpleNamespace(
                    status="accepted",
                    result={
                        "invocationId": "kinv-1",
                        "childRunId": "collect-1",
                        "replayed": False,
                        "reused": False,
                        "invocationStatus": "child_created",
                        "handoffState": "pending",
                    },
                )
            return SimpleNamespace(
                status="accepted",
                result={
                    "invocationId": "kinv-1",
                    "invocations": [{"invocationId": "kinv-1"}],
                    "childRun": {"runId": "collect-1"},
                    "recoveryActions": ["none"],
                    "knowledgeSideflowMode": "on",
                },
            )

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.formal_write_runtime.get_command_service",
        lambda: FakeCommandService(),
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


def test_request_delegates_to_command_ensure_and_stays_advisory(bound_scope, facade_calls):
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
    assert result["collection"]["childRunId"] == "collect-1"
    assert result["advisory"]["blocking"] is False
    assert facade_calls[0].command is WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION
    assert facade_calls[0].team_id == "research-team"
    assert facade_calls[0].payload["searchEnvelope"]["keywords"] == [
        "predictive coding",
        "spike coding",
        "redundancy",
    ]
    assert facade_calls[0].run_id == "run-1"


def test_status_delegates_to_command_inspect(bound_scope, facade_calls):
    result = _parse(request_tools.research_knowledge_request_tool(action="status"))
    assert result["ok"] is True
    assert result["action"] == "status"
    assert facade_calls[0].command is WorkflowCommandKind.INSPECT_KNOWLEDGE_COLLECTION


def test_request_and_status_use_workflow_command_service(
    bound_scope, monkeypatch: pytest.MonkeyPatch
) -> None:
    """3.0 provisioning must use the Ledger command authority, never D03."""

    calls = []

    class FakeCommandService:
        def submit(self, request):
            calls.append(request)
            if request.command is WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION:
                return SimpleNamespace(
                    status="accepted",
                    result={
                        "invocationId": "kinv-1",
                        "childRunId": "run-child-1",
                        "replayed": False,
                        "reused": False,
                        "invocationStatus": "child_created",
                        "handoffState": "pending",
                    },
                )
            return SimpleNamespace(
                status="accepted",
                result={
                    "invocationId": "kinv-1",
                    "invocations": [{"invocationId": "kinv-1"}],
                    "childRun": {"runId": "run-child-1"},
                    "recoveryActions": ["none"],
                    "knowledgeSideflowMode": "on",
                },
            )

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.formal_write_runtime.get_command_service",
        lambda: FakeCommandService(),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.facade.research_knowledge_collection_facade",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy source-collection facade must not be called")
        ),
    )

    requested = _parse(
        request_tools.research_knowledge_request_tool(
            action="request", keywords="predictive coding, spike coding"
        )
    )
    inspected = _parse(
        request_tools.research_knowledge_request_tool(action="status")
    )

    assert requested["ok"] is True
    assert requested["collection"]["invocationId"] == "kinv-1"
    assert inspected["ok"] is True
    assert inspected["collection"]["childRun"]["runId"] == "run-child-1"
    assert [item.command for item in calls] == [
        WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION,
        WorkflowCommandKind.INSPECT_KNOWLEDGE_COLLECTION,
    ]
    ensure = calls[0]
    assert ensure.run_id == "run-1"
    assert ensure.node_id == "hypothesis_design"
    assert ensure.payload["questionId"] == "SCI-096"
    assert ensure.payload["searchEnvelope"]["keywords"] == [
        "predictive coding",
        "spike coding",
    ]


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


def test_request_status_through_real_command_service_and_scope(tmp_path, monkeypatch):
    """Composition test: bound tool -> command authority -> one child run."""

    from types import SimpleNamespace

    from tests._support.graph_helpers import GraphHarness

    harness = GraphHarness(tmp_path)
    harness.commands.seed_run("run-9", status="running")

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
            return {
                "runId": "run-9",
                "teamId": "research-team",
                "questionId": "SCI-096",
                "runVersion": 1,
            }

    monkeypatch.setattr(
        "tools.challenge_cup_operations_tools._project_task_binding", fake_binding
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.get_research_workflow_runtime_service",
        lambda: FakeRunService(),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.hypothesis_first_chain._question_scope_envelope",
        lambda _team_id, question_id: {
            "program": "XH-202619",
            "theme": f"dev-{question_id.lower()}",
            "campaign": "dev-campaign",
            "question": question_id,
            "branch": "main",
            "workflow": "hypothesis_first",
            "agentId": "operator",
            "mode": "dev",
        },
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_scope.resolve_research_scope",
        lambda _team_id, *, agent_id, scope_seed: {
            **scope_seed,
            "agentId": agent_id,
            "scopeHash": "e" * 64,
        },
    )

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.formal_write_runtime.get_command_service",
        lambda: harness.commands.command_service,
    )
    monkeypatch.setattr(
        "config.settings.get_config",
        lambda: SimpleNamespace(
            research=SimpleNamespace(
                knowledge_sideflow=SimpleNamespace(mode="on")
            )
        ),
    )

    try:
        first = _parse(
            request_tools.research_knowledge_request_tool(
                action="request", keywords="spike coding"
            )
        )
        second = _parse(
            request_tools.research_knowledge_request_tool(
                action="request", keywords="spike coding"
            )
        )
        status = _parse(
            request_tools.research_knowledge_request_tool(action="status")
        )

        assert first["ok"] is True, first
        assert first["scope"]["questionId"] == "SCI-096"
        assert first["scope"]["mode"] == "dev"
        assert second["ok"] is True
        assert second["collection"]["replayed"] is True
        assert second["collection"]["invocationId"] == first["collection"]["invocationId"]
        assert second["collection"]["childRunId"] == first["collection"]["childRunId"]
        assert status["ok"] is True
        assert status["collection"]["invocations"][0]["invocationId"] == (
            first["collection"]["invocationId"]
        )
        assert status["collection"]["childRun"]["runId"] == (
            first["collection"]["childRunId"]
        )
    finally:
        harness.close()
