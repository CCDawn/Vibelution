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


@pytest.mark.parametrize("requested_status", ["completed", "running"])
def test_finding_writeback_rejects_unreceipted_completion_before_task_closes(monkeypatch, requested_status):
    from core.web.services.team_workflow.research_runtime import artifact_readback_registry as registry
    from core.web.services.team_workflow.source_collection import stage_writeback, writeback_materialize

    s = stage_writeback._service()
    task = {"taskId": "task", "stageId": "finding", "agentRole": "source_finder",
            "workflowRunId": "workflow", "status": "running"}
    monkeypatch.setattr(s.team_service, "get_team", lambda *_: {})
    monkeypatch.setattr(s, "_find_source_collection_stage_session_task_by_id", lambda *_: (task, "source"))
    monkeypatch.setattr(s, "_merge_source_collection_stage_writeback_result_payload", lambda *_: {})
    monkeypatch.setattr(s, "_source_collection_stage_writeback_candidate_coverage", lambda *_: {})
    monkeypatch.setattr(s, "_materialize_source_collection_stage_writeback_sources", lambda *_a, **_kw: {})
    monkeypatch.setattr(writeback_materialize, "source_collection_finding_writeback_close_status", lambda *_: "completed")
    payload = _receipt_payload()
    payload["candidateSources"][0]["sourceUrl"] = "https://missing.test/source"
    monkeypatch.setattr(registry, "load_scoped_artifact_payload", lambda *_a, **_kw: {"candidates": payload["candidateSources"]})
    monkeypatch.setattr(search_execution, "project_source_collection_search_trace", lambda *_: payload["searchTrace"])
    with pytest.raises(s.TeamWorkflowOrchestrationError, match="source_search_receipt_missing.*candidate-1") as error:
        stage_writeback.writeback_source_collection_stage_session_task("team", "task", {"status": requested_status})
    assert "parent_query_id" in str(error.value)
    assert task["status"] == "running"


def test_source_finding_quality_gate_rejects_candidate_not_linked_to_receipt() -> None:
    payload = _receipt_payload()
    payload["candidateSources"][0]["sourceUrl"] = "https://forged.test/not-returned"

    with pytest.raises(ValueError, match="unboundCandidates=.*candidate-1"):
        search_execution.validate_source_finding_receipt_payload(
            payload,
            require_candidate_receipt_binding=True,
        )


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
