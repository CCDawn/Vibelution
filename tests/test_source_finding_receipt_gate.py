from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.web.services.team_workflow.research_runtime.action_registry import (
    AdapterResult,
)
from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
    AgentActionAdapter,
)
from core.web.services.team_workflow.research_runtime.domain_ports import (
    ArtifactReadBack,
)
from core.web.services.team_workflow.source_collection import search_execution
from tools import research_search_tools

PERSPECTIVES = (
    "mechanism",
    "independent_baseline",
    "limitation_or_null",
    "falsification",
)


def _receipt_payload() -> dict:
    trace = []
    candidates = []
    for index, perspective in enumerate(PERSPECTIVES, start=1):
        url = f"https://example.test/{perspective}"
        trace.append(
            {
                "query": f"query {index}",
                "perspective": perspective,
                "status": "found",
                "resultRefs": [url],
                "eventIds": [f"evt-{index}"],
            }
        )
        candidates.append(
            {
                "candidateId": f"candidate-{index}",
                "sourceUrl": url,
                "perspective": perspective,
            }
        )
    return {
        "perspectives": list(PERSPECTIVES),
        "queries": [f"query {index}" for index in range(1, 5)],
        "candidateSources": candidates,
        "counterEvidenceCandidateSources": candidates[2:],
        "searchTrace": trace,
    }


def test_source_finding_quality_gate_rejects_candidates_without_receipts() -> None:
    payload = _receipt_payload()
    payload["searchTrace"] = []

    with pytest.raises(ValueError, match="missingTerminalTraces"):
        search_execution.validate_source_finding_receipt_payload(payload)


def test_receipt_readback_can_report_exact_gap_to_active_agent(monkeypatch):
    from core.web.services.team_workflow.research_runtime import artifact_readback_registry as registry

    payload = _receipt_payload()
    payload["candidateSources"][0]["sourceUrl"] = "https://missing.test/source"
    monkeypatch.setattr(registry, "load_scoped_artifact_payload", lambda *_a, **_kw: {
        "candidates": payload["candidateSources"],
    })
    monkeypatch.setattr(search_execution, "project_source_collection_search_trace", lambda *_: payload["searchTrace"])
    assert registry.load_source_finding_receipt_payload(team_id="team", authority_run_id="source") is None
    with pytest.raises(ValueError, match="unboundCandidates=.*candidate-1"):
        registry.load_source_finding_receipt_payload(team_id="team", authority_run_id="source", raise_on_invalid=True)
    payload["searchTrace"][0]["resultRefs"].append("https://missing.test/source")
    assert registry.load_source_finding_receipt_payload(team_id="team", authority_run_id="source", raise_on_invalid=True)["quality"]["candidateCount"] == 4


@pytest.mark.parametrize("requested_status", ["completed", "running", "needs_review"])
def test_finding_writeback_rejects_unreceipted_batch_before_materialization(monkeypatch, requested_status):
    from core.web.services.team_workflow.source_collection import stage_writeback, writeback_materialize

    s = stage_writeback._service()
    task = {"taskId": "task", "stageId": "finding", "agentRole": "source_finder",
            "workflowRunId": "workflow", "status": "running"}
    monkeypatch.setattr(s.team_service, "get_team", lambda *_: {})
    monkeypatch.setattr(s, "_find_source_collection_stage_session_task_by_id", lambda *_: (task, "source"))
    monkeypatch.setattr(
        s,
        "_merge_source_collection_stage_writeback_result_payload",
        lambda *args: args[-1],
    )
    monkeypatch.setattr(s, "_source_collection_stage_writeback_candidate_coverage", lambda *_: {})
    materialize_calls = []
    monkeypatch.setattr(
        s,
        "_materialize_source_collection_stage_writeback_sources",
        lambda *_a, **_kw: materialize_calls.append(True) or {},
    )
    for name in ["_materialize_source_collection_stage_writeback_content_extraction",
                 "_materialize_source_collection_stage_writeback_quality",
                 "_materialize_source_collection_stage_writeback_candidate_graph",
                 "_materialize_source_collection_stage_writeback_knowledge_ingestion"]:
        monkeypatch.setattr(s, name, lambda *_a, **_kw: {})
    monkeypatch.setattr(s, "_source_collection_stage_writeback_closure_summary", lambda *_a, **_kw: {
        "artifactComplete": True, "taskChecklistComplete": True,
    })
    monkeypatch.setattr(s, "_source_collection_stage_completion_gate", lambda **_: {"passed": True})
    monkeypatch.setattr(writeback_materialize, "source_collection_finding_writeback_close_status", lambda *_: "completed")
    payload = _receipt_payload()
    monkeypatch.setattr(search_execution, "project_source_collection_search_trace", lambda *_: payload["searchTrace"])
    incoming = {
        "candidateLeads": [
            {
                "leadId": "candidate-1",
                "title": "Unreceipted source",
                "sourceUrl": "https://missing.test/source",
                "perspective": "mechanism",
            }
        ]
    }
    with pytest.raises(s.TeamWorkflowOrchestrationError, match="source_search_receipt_missing.*candidate-1") as error:
        stage_writeback.writeback_source_collection_stage_session_task(
            "team",
            "task",
            {"status": requested_status, "result": incoming},
        )
    assert "parent_query_id" in str(error.value)
    assert materialize_calls == []
    assert task["status"] == "running"


def test_source_finding_quality_gate_rejects_candidate_not_linked_to_receipt() -> None:
    payload = _receipt_payload()
    payload["candidateSources"][0]["sourceUrl"] = "https://forged.test/not-returned"

    with pytest.raises(ValueError, match="unboundCandidates=.*candidate-1"):
        search_execution.validate_source_finding_receipt_payload(
            payload,
            require_candidate_receipt_binding=True,
        )


def test_source_finding_quality_gate_binds_publisher_presentation_url_to_doi() -> None:
    payload = _receipt_payload()
    candidate = payload["candidateSources"][0]
    candidate["sourceUrl"] = "https://doi.org/10.3389/fcell.2026.1891553"
    candidate["metadata"] = {"sourceIdentityKey": "doi:10.3389/fcell.2026.1891553"}
    payload["searchTrace"][0]["resultRefs"] = [
        "https://www.frontiersin.org/journals/cell-and-developmental-biology/articles/10.3389/fcell.2026.1891553/full",
        "identity:doi:10.3389/fcell.2026.1891553/full",
    ]

    search_execution.validate_source_finding_receipt_payload(
        payload,
        require_candidate_receipt_binding=True,
    )


def test_source_finding_quality_gate_requires_url_and_doi_in_one_receipt_event() -> None:
    payload = _receipt_payload()
    candidate = payload["candidateSources"][0]
    candidate["sourceUrl"] = "https://publisher.test/article/4580"
    candidate["metadata"] = {"sourceIdentityKey": "doi:10.1038/4580"}
    payload["searchTrace"][0]["resultRefs"] = [candidate["sourceUrl"]]
    payload["searchTrace"].append(
        {
            "query": "query with split DOI receipt",
            "perspective": "mechanism",
            "status": "found",
            "resultRefs": ["identity:doi:10.1038/4580"],
            "eventIds": ["evt-split-doi"],
        }
    )

    with pytest.raises(ValueError, match="unboundCandidates=.*candidate-1"):
        search_execution.validate_source_finding_receipt_payload(
            payload,
            require_candidate_receipt_binding=True,
        )


def test_source_finding_quality_gate_accepts_url_and_doi_from_one_receipt_event() -> None:
    payload = _receipt_payload()
    candidate = payload["candidateSources"][0]
    candidate["sourceUrl"] = "https://publisher.test/article/4580"
    candidate["metadata"] = {"sourceIdentityKey": "doi:10.1038/4580"}
    payload["searchTrace"][0]["resultRefs"] = [
        candidate["sourceUrl"],
        "identity:doi:10.1038/4580",
    ]
    payload["searchTrace"][0]["receiptRefSets"] = [
        [candidate["sourceUrl"], "identity:doi:10.1038/4580"],
    ]

    search_execution.validate_source_finding_receipt_payload(
        payload,
        require_candidate_receipt_binding=True,
    )


def test_source_finding_quality_gate_binds_arxiv_url_across_http_schemes() -> None:
    payload = _receipt_payload()
    candidate = payload["candidateSources"][0]
    candidate["sourceUrl"] = "https://arxiv.org/abs/2607.20544v3"
    candidate["metadata"] = {
        "sourceIdentityKey": "url:https://arxiv.org/abs/2607.20544v3"
    }
    payload["searchTrace"][0]["resultRefs"] = [
        "http://arxiv.org/abs/2607.20544v3",
        "identity:url:http://arxiv.org/abs/2607.20544v3",
    ]

    search_execution.validate_source_finding_receipt_payload(
        payload,
        require_candidate_receipt_binding=True,
    )


def test_source_finding_quality_gate_rejects_conflicting_doi_hidden_by_matching_url() -> None:
    payload = _receipt_payload()
    candidate = payload["candidateSources"][0]
    candidate["sourceRef"] = "https://doi.org/10.9999/wrong-doi"
    candidate["sourceUrl"] = "https://publisher.test/articles/10.1038/4580"
    payload["searchTrace"][0]["resultRefs"] = [candidate["sourceUrl"]]
    payload["searchTrace"].append(
        {
            "query": "query with wrong DOI",
            "perspective": "mechanism",
            "status": "found",
            "resultRefs": [candidate["sourceRef"]],
            "eventIds": ["evt-wrong-doi"],
        }
    )

    with pytest.raises(ValueError, match="unboundCandidates=.*candidate-1"):
        search_execution.validate_source_finding_receipt_payload(
            payload,
            require_candidate_receipt_binding=True,
        )


def test_source_finding_quality_gate_rejects_agent_identity_key_conflict() -> None:
    payload = _receipt_payload()
    candidate = payload["candidateSources"][0]
    candidate["sourceUrl"] = "https://doi.org/10.1038/4580"
    candidate["metadata"] = {"sourceIdentityKey": "doi:10.9999/wrong-doi"}
    payload["searchTrace"][0]["resultRefs"] = [candidate["sourceUrl"]]

    with pytest.raises(ValueError, match="unboundCandidates=.*candidate-1"):
        search_execution.validate_source_finding_receipt_payload(
            payload,
            require_candidate_receipt_binding=True,
        )


def test_candidate_receipt_registry_rejects_conflicting_doi_before_writeback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import artifact_readback_registry as registry

    payload = _receipt_payload()
    candidate = dict(payload["candidateSources"][0])
    candidate["sourceRef"] = "https://doi.org/10.9999/wrong-doi"
    candidate["sourceUrl"] = "https://publisher.test/articles/10.1038/4580"
    payload["searchTrace"][0]["resultRefs"] = [candidate["sourceUrl"]]
    payload["searchTrace"].append(
        {
            "query": "query with wrong DOI",
            "perspective": "mechanism",
            "status": "found",
            "resultRefs": [candidate["sourceRef"]],
            "eventIds": ["evt-wrong-doi"],
        }
    )
    monkeypatch.setattr(
        search_execution,
        "project_source_collection_search_trace",
        lambda *_: payload["searchTrace"],
    )

    binding = registry.inspect_source_finding_candidate_receipts(
        team_id="team",
        authority_run_id="source",
        candidate_sources=[candidate],
    )

    assert binding["passed"] is False
    assert binding["unboundCandidateIds"] == ["candidate-1"]


def test_formal_search_context_uses_message_only_as_canonical_task_locator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assignment = {
        "assignmentId": "assignment-1",
        "agentId": "agent-1",
        "scope": {
            "assignedQueries": [
                {
                    "queryId": "query-1",
                    "query": "assigned query",
                    "perspective": "mechanism",
                }
            ]
        },
    }
    fake = SimpleNamespace(
        _trim_text=lambda value, *, max_length: str(value or "").strip()[:max_length],
        SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND="source_collection_stage_session_task",
        session_service=SimpleNamespace(
            get_session_detail=lambda *_args, **_kwargs: {
                "messages": [
                    {
                        "metadata": {
                            "kind": "source_collection_stage_session_task",
                            "teamId": "team-1",
                            "sourceCollectionStageTaskId": "task-1",
                            "turnId": "turn-1",
                            # These untrusted values intentionally disagree.
                            "runId": "forged-run",
                            "assignmentIds": ["forged-assignment"],
                        }
                    }
                ]
            }
        ),
        data_processing_service=SimpleNamespace(
            list_collection_assignments=lambda run_id: {
                "assignments": [assignment] if run_id == "canonical-run" else []
            }
        ),
    )
    monkeypatch.setattr(search_execution, "_service", lambda: fake)
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_session._read_source_collection_stage_session_task_record",
        lambda team_id, task_id: {
            "teamId": team_id,
            "taskId": task_id,
            "runId": "canonical-run",
            "workflowRunId": "workflow-1",
            "stageId": "finding",
            "agentId": "agent-1",
            "sessionId": "session-1",
            "turn": {"turnId": "turn-1"},
            "assignmentIds": ["assignment-1"],
        },
    )

    resolved = search_execution.resolve_bound_source_search_context(
        {"sessionId": "session-1", "turnId": "turn-1", "agentId": "agent-1"}
    )

    assert resolved is not None
    assert resolved["sourceCollectionRunId"] == "canonical-run"
    assert [item["assignmentId"] for item in resolved["assignments"]] == ["assignment-1"]


def test_formal_search_context_fails_closed_when_canonical_task_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = SimpleNamespace(
        _trim_text=lambda value, *, max_length: str(value or "").strip()[:max_length],
        SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND="source_collection_stage_session_task",
        session_service=SimpleNamespace(
            get_session_detail=lambda *_args, **_kwargs: {
                "messages": [
                    {
                        "metadata": {
                            "kind": "source_collection_stage_session_task",
                            "teamId": "team-1",
                            "sourceCollectionStageTaskId": "missing-task",
                            "turnId": "turn-1",
                        }
                    }
                ]
            }
        ),
    )
    monkeypatch.setattr(search_execution, "_service", lambda: fake)
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_session._read_source_collection_stage_session_task_record",
        lambda _team_id, _task_id: None,
    )

    with pytest.raises(RuntimeError, match="canonical task is unavailable"):
        search_execution.resolve_bound_source_search_context(
            {"sessionId": "session-1", "turnId": "turn-1", "agentId": "agent-1"}
        )


def test_bound_tool_receipt_is_persisted_idempotently_before_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events_path = tmp_path / "search_events.jsonl"
    written: list[dict] = []

    def trim(value, *, max_length):
        return str(value or "").strip()[:max_length]

    fake = SimpleNamespace(
        _trim_text=trim,
        _source_collection_identity_key=lambda **kwargs: "url:bound-result",
        _new_record_id=lambda _prefix: f"evt-{len(written) + 1}",
        utc_now_iso=lambda: "2026-09-05T00:00:00Z",
        _normalize_text_list=lambda values, **_kwargs: list(dict.fromkeys(str(v) for v in values if v)),
        _normalize_metadata=lambda value: dict(value or {}),
        _source_collection_storage_artifact_paths=lambda _team, _run: {
            "runDirectory": tmp_path,
            "artifactsDirectory": tmp_path,
            "searchEventsPath": events_path,
        },
        _WORKFLOW_LOCK=threading.RLock(),
        _read_jsonl=lambda _path: list(written),
        _append_jsonl=lambda _path, rows: written.extend(dict(row) for row in rows),
    )
    monkeypatch.setattr(search_execution, "_service", lambda: fake)
    context = {
        "teamId": "team-1",
        "sourceCollectionRunId": "sc-run-1",
        "taskId": "task-1",
        "sessionId": "session-1",
        "turnId": "turn-1",
    }
    binding = {
        "assignment": {"assignmentId": "assignment-1", "agentId": "agent-1", "agentRole": "source_finder"},
        "query": {"queryId": "query-1", "query": "bounded query", "perspective": "mechanism"},
    }
    provider_payload = {
        "providers": [{"provider": "ddgs", "status": "ok", "resultCount": 1}],
        "results": [
            {
                "provider": "ddgs",
                "title": "Bound result",
                "url": "https://example.test/bound-result",
            }
        ],
    }

    first = search_execution.append_bound_tool_search_receipts(
        context,
        binding=binding,
        provider_payload=provider_payload,
        tool_call_id="call-1",
    )
    second = search_execution.append_bound_tool_search_receipts(
        context,
        binding=binding,
        provider_payload=provider_payload,
        tool_call_id="call-1",
    )

    assert len(written) == 1
    assert first and second
    assert written[0]["eventType"] == "search.tool_result_returned"
    assert written[0]["queryId"] == "query-1"
    assert written[0]["perspective"] == "mechanism"
    assert written[0]["toolCallId"] == "call-1"
    assert "identity:url:bound-result" in written[0]["refs"]


def test_bound_tool_receipt_preserves_each_provider_result_binding_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = search_execution._service()
    events_path = tmp_path / "search_events.jsonl"
    monkeypatch.setattr(
        service,
        "_source_collection_storage_artifact_paths",
        lambda _team, _run: {
            "runDirectory": tmp_path,
            "artifactsDirectory": tmp_path,
            "searchEventsPath": events_path,
        },
    )
    context = {
        "teamId": "team-1",
        "sourceCollectionRunId": "source-1",
        "taskId": "task-1",
        "sessionId": "session-1",
        "turnId": "turn-1",
    }
    binding = {
        "assignment": {"assignmentId": "assignment-1", "agentId": "agent-1", "agentRole": "source_finder"},
        "query": {"queryId": "query-1", "query": "two papers", "perspective": "mechanism"},
    }
    provider_payload = {
        "providers": [{"provider": "ddgs", "status": "ok", "resultCount": 2}],
        "results": [
            {
                "provider": "ddgs",
                "title": "Paper A",
                "url": "https://publisher.test/articles/10.1038/paper-a",
                "doi": "10.1038/paper-a",
            },
            {
                "provider": "ddgs",
                "title": "Paper B",
                "url": "https://doi.org/10.1038/paper-b",
                "doi": "10.1038/paper-b",
            },
        ],
    }

    search_execution.append_bound_tool_search_receipts(
        context,
        binding=binding,
        provider_payload=provider_payload,
        tool_call_id="call-1",
    )

    events = service._read_jsonl(events_path)
    assert len(events) == 1
    event = events[0]
    receipt_ref_sets = event["receiptRefSets"]
    assert len(receipt_ref_sets) == 2
    assert {
        "https://publisher.test/articles/10.1038/paper-a",
        "10.1038/paper-a",
        "identity:doi:10.1038/paper-a",
    }.issubset(receipt_ref_sets[0])
    assert {
        "https://doi.org/10.1038/paper-b",
        "10.1038/paper-b",
        "identity:doi:10.1038/paper-b",
    }.issubset(receipt_ref_sets[1])

    trace = search_execution.project_source_collection_search_trace("team-1", "source-1")
    assert len(trace) == 1
    assert trace[0]["resultRefs"] == event["refs"]
    assert trace[0]["receiptRefSets"] == receipt_ref_sets


def test_source_finding_quality_gate_rejects_mixed_locators_from_real_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = search_execution._service()
    events_path = tmp_path / "search_events.jsonl"
    monkeypatch.setattr(
        service,
        "_source_collection_storage_artifact_paths",
        lambda _team, _run: {
            "runDirectory": tmp_path,
            "artifactsDirectory": tmp_path,
            "searchEventsPath": events_path,
        },
    )
    context = {
        "teamId": "team-1",
        "sourceCollectionRunId": "source-1",
        "taskId": "task-1",
        "sessionId": "session-1",
        "turnId": "turn-1",
    }
    assignment = {"assignmentId": "assignment-1", "agentId": "agent-1", "agentRole": "source_finder"}
    urls = {
        "mechanism": "https://publisher.test/paper-a",
        "independent_baseline": "https://example.test/baseline",
        "limitation_or_null": "https://example.test/limitation",
        "falsification": "https://example.test/falsification",
    }
    for index, perspective in enumerate(PERSPECTIVES, start=1):
        binding = {
            "assignment": assignment,
            "query": {
                "queryId": f"query-{index}",
                "query": f"query {perspective}",
                "perspective": perspective,
            },
        }
        results = [
            {
                "provider": "ddgs",
                "title": perspective,
                "url": urls[perspective],
            }
        ]
        if perspective == "mechanism":
            results.append(
                {
                    "provider": "ddgs",
                    "title": "Paper B",
                    "url": "https://doi.org/10.1038/paper-b",
                    "doi": "10.1038/paper-b",
                }
            )
        search_execution.append_bound_tool_search_receipts(
            context,
            binding=binding,
            provider_payload={
                "providers": [{"provider": "ddgs", "status": "ok", "resultCount": len(results)}],
                "results": results,
            },
            tool_call_id=f"call-{index}",
        )

    trace = search_execution.project_source_collection_search_trace("team-1", "source-1")
    mechanism_trace = next(item for item in trace if item["perspective"] == "mechanism")
    assert {
        urls["mechanism"],
        "https://doi.org/10.1038/paper-b",
    }.issubset(mechanism_trace["resultRefs"])
    assert len(mechanism_trace["receiptRefSets"]) == 2

    candidates = []
    for index, perspective in enumerate(PERSPECTIVES, start=1):
        candidate = {
            "candidateId": f"candidate-{index}",
            "sourceUrl": urls[perspective],
            "perspective": perspective,
        }
        if perspective == "mechanism":
            candidate["metadata"] = {"sourceIdentityKey": "doi:10.1038/paper-b"}
        candidates.append(candidate)
    payload = {
        "perspectives": list(PERSPECTIVES),
        "queries": [item["query"] for item in trace],
        "candidateSources": candidates,
        "counterEvidenceCandidateSources": candidates[2:],
        "searchTrace": trace,
    }

    with pytest.raises(ValueError, match="unboundCandidates=.*candidate-1"):
        search_execution.validate_source_finding_receipt_payload(
            payload,
            require_candidate_receipt_binding=True,
        )


def test_formal_batch_search_persists_structured_provider_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = {"sessionId": "session-1", "turnId": "turn-1"}
    monkeypatch.setattr(
        search_execution,
        "resolve_bound_source_search_context",
        lambda _runtime: context,
    )
    monkeypatch.setattr(
        search_execution,
        "bind_formal_search_query",
        lambda _context, query: {
            "assignment": {"assignmentId": "assignment-1"},
            "query": {"queryId": "query-1", "query": query, "perspective": "mechanism"},
        },
    )
    persisted: list[dict] = []
    monkeypatch.setattr(
        search_execution,
        "append_bound_tool_search_receipts",
        lambda _context, **kwargs: persisted.append(kwargs) or ["evt-1"],
    )
    monkeypatch.setattr(
        research_search_tools.research_search_backends,
        "collect_provider_results",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "query": "assigned query",
            "providers": [{"provider": "ddgs", "status": "ok", "resultCount": 1}],
            "results": [
                {
                    "provider": "ddgs",
                    "title": "Result",
                    "url": "https://example.test/result",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "core.web.services.agent_directory_service.current_agent_runtime",
        lambda: {"sessionId": "session-1", "turnId": "turn-1"},
    )

    rendered = research_search_tools.batch_web_search(
        '["assigned query"]',
        max_workers=1,
    )

    assert "https://example.test/result" in rendered
    assert len(persisted) == 1
    assert persisted[0]["provider_payload"]["providers"][0]["provider"] == "ddgs"
    assert persisted[0]["tool_call_id"].startswith("search-call-")


def test_formal_batch_search_rejects_unassigned_query_before_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = {
        "sessionId": "session-1",
        "turnId": "turn-1",
        "assignments": [
            {
                "assignmentId": "assignment-1",
                "scope": {
                    "assignedQueries": [
                        {
                            "queryId": "query-1",
                            "query": "assigned query",
                            "perspective": "mechanism",
                        }
                    ]
                },
            }
        ],
    }
    monkeypatch.setattr(
        search_execution,
        "resolve_bound_source_search_context",
        lambda _runtime: context,
    )
    monkeypatch.setattr(
        research_search_tools.research_search_backends,
        "collect_provider_results",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("provider must not run for an unassigned query")
        ),
    )
    monkeypatch.setattr(
        "core.web.services.agent_directory_service.current_agent_runtime",
        lambda: {"sessionId": "session-1", "turnId": "turn-1"},
    )

    with pytest.raises(RuntimeError, match="formal source search receipt failed"):
        research_search_tools.batch_web_search('["unassigned query"]', max_workers=1)


def test_formal_batch_search_fails_when_receipt_persistence_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = {"sessionId": "session-1", "turnId": "turn-1"}
    monkeypatch.setattr(
        search_execution,
        "resolve_bound_source_search_context",
        lambda _runtime: context,
    )
    monkeypatch.setattr(
        search_execution,
        "bind_formal_search_query",
        lambda _context, query: {
            "assignment": {"assignmentId": "assignment-1"},
            "query": {"queryId": "query-1", "query": query, "perspective": "mechanism"},
        },
    )
    monkeypatch.setattr(
        search_execution,
        "append_bound_tool_search_receipts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    monkeypatch.setattr(
        research_search_tools.research_search_backends,
        "collect_provider_results",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "query": "assigned query",
            "providers": [{"provider": "ddgs", "status": "ok", "resultCount": 1}],
            "results": [
                {
                    "provider": "ddgs",
                    "title": "Result",
                    "url": "https://example.test/result",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "core.web.services.agent_directory_service.current_agent_runtime",
        lambda: {"sessionId": "session-1", "turnId": "turn-1"},
    )

    with pytest.raises(RuntimeError, match="formal source search receipt failed"):
        research_search_tools.batch_web_search('["assigned query"]', max_workers=1)


class _Ports:
    def required_artifact_kinds(self, _action):
        return ("source_candidate_batch",)

    def read_back_artifact(self, canonical_ref):
        return ArtifactReadBack(
            canonical_ref=canonical_ref,
            version="1.0.0",
            content_hash="a" * 64,
            domain_revision="revision-1",
        )


def test_ledger_adapter_blocks_candidate_hash_without_search_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        artifact_readback_registry,
    )

    monkeypatch.setattr(
        artifact_readback_registry,
        "load_source_finding_receipt_payload",
        lambda **_kwargs: None,
    )
    action = SimpleNamespace(action_id="action-1", node_id="source_finding")
    result = AdapterResult(
        action_id="action-1",
        outcome="succeeded",
        materialized_refs=(
            {
                "kind": "source_candidate_batch",
                "canonicalRef": "source_candidate_batch://team-1/sc-run-1/" + "a" * 64,
                "sha256": "a" * 64,
                "version": "1.0.0",
            },
        ),
        anchor={"actionId": "action-1"},
    )

    verified = AgentActionAdapter(_Ports()).verify(action, result)

    assert verified.outcome == "blocked"
    assert verified.problem["code"] == "source_search_receipt_missing"


def test_receipt_gate_rejects_candidate_batch_changed_after_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        artifact_readback_registry,
    )

    monkeypatch.setattr(
        artifact_readback_registry,
        "load_scoped_artifact_payload",
        lambda *_args, **_kwargs: {
            "teamId": "team-1",
            "sourceCollectionRunId": "sc-run-1",
            "candidates": [{"candidateId": "candidate-changed"}],
            "candidateCount": 1,
        },
    )

    payload = artifact_readback_registry.load_source_finding_receipt_payload(
        team_id="team-1",
        authority_run_id="sc-run-1",
        candidate_content_hash="a" * 64,
    )

    assert payload is None


def test_ledger_adapter_records_verified_search_receipt_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        artifact_readback_registry,
    )

    payload = _receipt_payload()
    monkeypatch.setattr(
        artifact_readback_registry,
        "load_source_finding_receipt_payload",
        lambda **_kwargs: payload,
    )
    action = SimpleNamespace(action_id="action-2", node_id="source_finding")
    result = AdapterResult(
        action_id="action-2",
        outcome="succeeded",
        materialized_refs=(
            {
                "kind": "source_candidate_batch",
                "canonicalRef": "source_candidate_batch://team-1/sc-run-1/" + "a" * 64,
                "sha256": "a" * 64,
                "version": "1.0.0",
            },
        ),
        anchor={"actionId": "action-2"},
    )

    verified = AgentActionAdapter(_Ports()).verify(action, result)

    assert verified.outcome == "succeeded"
    receipt = verified.artifact_receipts[0]
    assert len(receipt["searchReceiptSha256"]) == 64
    assert receipt["searchEventIds"] == ["evt-1", "evt-2", "evt-3", "evt-4"]
