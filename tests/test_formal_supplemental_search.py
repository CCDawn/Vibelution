import json
from collections import OrderedDict

import pytest

from core.web.services.team_workflow.source_collection import search_execution
from tools import research_search_tools


def test_finding_context_refreshes_receipts_even_when_context_is_cached(monkeypatch):
    from tools import source_collection_stage_tools as stage_tools
    from core.web.services import team_workflow_orchestration_service as service

    monkeypatch.setattr(stage_tools, "_SOURCE_CONTEXT_CACHE", OrderedDict())
    monkeypatch.setattr(stage_tools, "_resolve_source_collection_team_id", lambda **_: ("team-1", {}))
    monkeypatch.setattr(stage_tools, "_record_stage_tool_event", lambda *_a, **_kw: None)
    calls = []
    def context(*_a, **_kw):
        calls.append(1)
        return {"stageId": "finding", "runId": "source-1"}
    monkeypatch.setattr(service, "get_source_collection_stage_task_context", context)
    receipts = []
    monkeypatch.setattr(search_execution, "project_source_collection_search_trace", lambda *_: list(receipts))
    first = json.loads(stage_tools.source_collection_context_tool(team_id="team-1", run_id="source-1", stage_id="finding"))
    receipts.append({"resultRefs": ["https://example.org/new"]})
    second = json.loads(stage_tools.source_collection_context_tool(team_id="team-1", run_id="source-1", stage_id="finding"))
    assert first["searchReceipts"] == []
    assert second["searchReceipts"] == receipts
    assert "parent_query_id" in second["formalSearchPolicy"]["supplementalQueries"]
    assert len(calls) == 1


@pytest.fixture
def scoped_search(tmp_path, monkeypatch):
    service = search_execution._service()
    path = tmp_path / "search_events.jsonl"
    monkeypatch.setattr(service, "_source_collection_storage_artifact_paths", lambda *_: {
        "runDirectory": tmp_path, "artifactsDirectory": tmp_path, "searchEventsPath": path,
    })
    context = {"teamId": "team-1", "sourceCollectionRunId": "source-1", "taskId": "task-1",
        "sessionId": "session-1", "turnId": "turn-1", "assignments": [{
            "assignmentId": "assignment-1", "agentId": "agent-1", "agentRole": "source_finder",
            "scope": {"assignedQueries": [{"queryId": "base-1", "query": "approved question",
                "perspective": "mechanism"}]},
        }]}
    monkeypatch.setattr(search_execution, "resolve_bound_source_search_context", lambda *_: context)
    return context, path


def test_paper_search_registers_query_before_provider_and_preserves_all_result_refs(scoped_search, monkeypatch):
    context, path = scoped_search
    urls = [f"https://example.org/paper-{i}" for i in range(8)]

    def provider(query, *_args, **_kwargs):
        events = [json.loads(line) for line in path.read_text().splitlines()]
        assert events[0]["eventType"] == "search.query_registered"
        assert events[0]["parentQueryId"] == "base-1"
        assert events[0]["query"] == query == "question specific method 2026"
        return {"providers": [{"provider": "arxiv", "status": "ok"}],
            "results": [{"provider": "arxiv", "url": url, "title": "Method"} for url in urls]}

    monkeypatch.setattr(research_search_tools.research_search_backends, "collect_provider_results", provider)
    output = research_search_tools.paper_search("question specific method", year_hint=2026, parent_query_id="base-1")
    assert urls[-1] in output
    trace = search_execution.project_source_collection_search_trace("team-1", "source-1")
    assert set(urls).issubset(set(trace[0]["resultRefs"]))
    assert trace[0]["perspective"] == "mechanism"
    binding = search_execution.bind_formal_search_query(context, "question specific method 2026", parent_query_id="base-1")
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert sum(e["eventType"] == "search.query_registered" for e in events) == 1
    assert events[-1]["queryId"] == binding["query"]["queryId"]
    assert events[-1]["toolName"] == "paper_search_tool"


def test_foreign_parent_query_is_rejected_before_network(scoped_search, monkeypatch):
    _, path = scoped_search
    provider = lambda *_a, **_kw: pytest.fail("provider must not run for foreign scope")
    monkeypatch.setattr(research_search_tools.research_search_backends, "collect_provider_results", provider)
    with pytest.raises(RuntimeError, match="parent must belong"):
        research_search_tools.paper_search("unrelated", parent_query_id="other-task-query")
    assert not path.exists()


def test_repeated_query_persists_changed_provider_results(scoped_search, monkeypatch):
    _, path = scoped_search
    urls = iter(["https://example.org/first", "https://example.org/second"])
    monkeypatch.setattr(research_search_tools.research_search_backends, "collect_provider_results", lambda *_a, **_kw: {
        "providers": [{"provider": "arxiv", "status": "ok"}],
        "results": [{"provider": "arxiv", "url": next(urls), "title": "Result"}],
    })
    research_search_tools.paper_search("specific method", parent_query_id="base-1")
    research_search_tools.paper_search("specific method", parent_query_id="base-1")
    trace = search_execution.project_source_collection_search_trace("team-1", "source-1")
    assert {"https://example.org/first", "https://example.org/second"}.issubset(trace[0]["resultRefs"])
    assert len([json.loads(line) for line in path.read_text().splitlines()]) == 3


def test_receipt_persistence_failure_does_not_return_paper_results(scoped_search, monkeypatch):
    monkeypatch.setattr(research_search_tools.research_search_backends, "collect_provider_results", lambda *_a, **_kw: {
        "providers": [{"provider": "arxiv", "status": "ok"}],
        "results": [{"provider": "arxiv", "url": "https://example.org/result", "title": "Result"}],
    })
    def fail(*_args, **_kwargs):
        raise OSError("receipt disk failure")
    monkeypatch.setattr(search_execution, "append_bound_tool_search_receipts", fail)
    with pytest.raises(OSError, match="receipt disk failure"):
        research_search_tools.paper_search("specific method", parent_query_id="base-1")
