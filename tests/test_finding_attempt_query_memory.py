"""Regression coverage: finding formal-retry attempts inherit prior query memory.

Link audit A2: each finding attempt re-ran the same searches because the new
attempt's session had no memory of the previous attempt's ``searchTrace``
queries and ``invalidSources`` judgments (observed as a 17-step DOI guess
spiral). The formal-retry path must inject a deduped, bounded
"already tried / already judged invalid" hint into the retry task message and
the reseeded session context of the new attempt.
"""

from __future__ import annotations

import pytest

from core.web.services import (
    agent_directory_service,
    session_service,
    team_service,
    team_workflow_orchestration_service as s,
)
from tests._support.team_workflow.helpers import (
    _start_source_collection_run_with_problem_understanding,
    _use_tmp_project_root,
)

_MEMORY_HEADER = "## 上一轮检索记忆"
_MAX_MEMORY_ITEMS = 30
_MEMORY_ITEM_MAX_LENGTH = 200


def _finding_task_setup(tmp_path, monkeypatch):
    """Isolated team/run/agent wired for finding stage-session tasks."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="资料寻找",
        role_key="source_finder",
    )
    team = team_service.create_team(
        name="科研团队",
        members=[
            {
                "agentId": agent["agentId"],
                "agentName": "资料寻找",
                "role": "source_finder",
            }
        ],
    )
    run = _start_source_collection_run_with_problem_understanding(
        team["teamId"],
        {
            "topic": "query memory",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": agent["agentId"]},
            "querySeeds": ["query memory"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )["run"]
    start_payload = {
        "stageId": "finding",
        "agentId": agent["agentId"],
        "agentRole": "source_finder",
    }
    return team, run, agent, start_payload


def _mark_task_failed(
    team: dict,
    run: dict,
    task_id: str,
    *,
    result: dict,
    status: str = "failed",
) -> dict:
    tasks = s._source_collection_stage_session_tasks(team["teamId"], run["runId"])
    record = next(item for item in tasks if item.get("taskId") == task_id)
    failed = dict(record)
    failed["status"] = status
    failed["result"] = result
    failed["updatedAt"] = s.utc_now_iso()
    s._upsert_source_collection_stage_session_task(team["teamId"], run["runId"], failed)
    return failed


def _seed_context_message_text(session_id: str) -> str:
    detail = session_service.get_session_detail(session_id)
    return "\n".join(
        str(item.get("text") or "")
        for message in detail["messages"]
        if message.get("metadata", {}).get("kind") == "source_collection_agent_context"
        for item in message.get("turnItems", [])
        if isinstance(item, dict)
    )


def test_finding_retry_injects_prior_query_memory(tmp_path, monkeypatch):
    """Auto formal retry carries deduped prior queries into message and seed."""
    team, run, agent, start_payload = _finding_task_setup(tmp_path, monkeypatch)
    submitted: list[str] = []

    def fake_submit_session_message(session_id, content, **kwargs):
        submitted.append(content)
        return {
            "accepted": True,
            "sessionId": session_id,
            "turnId": f"turn-query-memory-{len(submitted)}",
            "status": "running",
        }

    monkeypatch.setattr(session_service, "submit_session_message", fake_submit_session_message)

    # Fresh seed and fresh attempt carry no memory block.
    first_seed = s.seed_source_collection_agent_session_context(
        team["teamId"],
        run["runId"],
        {"stageId": "finding", "agentId": agent["agentId"], "agentRole": "source_finder"},
    )
    assert first_seed["created"] is True
    assert _MEMORY_HEADER not in _seed_context_message_text(first_seed["sessionId"])

    first = s.start_source_collection_stage_session_task(
        team["teamId"], run["runId"], dict(start_payload)
    )
    assert first["alreadyPresent"] is False
    assert _MEMORY_HEADER not in submitted[0]

    _mark_task_failed(
        team,
        run,
        first["taskId"],
        result={
            "searchTrace": [
                {"perspective": "mechanism", "query": "predictive coding", "status": "no_credible_source"},
                {"perspective": "mechanism", "query": "Predictive  Coding", "status": "no_credible_source"},
                {"perspective": "benchmark", "query": "brain-inspired routing benchmark", "status": "found"},
            ],
            "invalidSources": [
                {"url": "https://doi.org/10.1234/guessed-doi", "reason": "404"},
                {"doi": "10.9999/nope", "failureReason": "not found"},
            ],
        },
    )

    retry = s.start_source_collection_stage_session_task(
        team["teamId"], run["runId"], dict(start_payload)
    )
    assert retry["alreadyPresent"] is False
    assert retry["taskId"] != first["taskId"]
    retry_message = submitted[1]
    assert _MEMORY_HEADER in retry_message
    # Case/whitespace variants of the same query collapse into one entry.
    assert retry_message.count("predictive coding") == 1
    assert "Predictive  Coding" not in retry_message
    assert "brain-inspired routing benchmark" in retry_message
    assert "https://doi.org/10.1234/guessed-doi" in retry_message
    assert "10.9999/nope" in retry_message

    # The reseeded context of the retry session carries the same memory.
    retry_seed = s.seed_source_collection_agent_session_context(
        team["teamId"],
        run["runId"],
        {"stageId": "finding", "agentId": agent["agentId"], "agentRole": "source_finder"},
    )
    assert retry_seed["sessionAttempt"] == 2
    assert retry_seed["sessionId"] != first_seed["sessionId"]
    assert retry_seed["created"] is True
    seed_text = _seed_context_message_text(retry_seed["sessionId"])
    assert _MEMORY_HEADER in seed_text
    assert seed_text.count("predictive coding") == 1
    assert "https://doi.org/10.1234/guessed-doi" in seed_text


def test_finding_query_memory_dedupes_bounds_and_ignores_non_failed(tmp_path, monkeypatch):
    """Memory is deduped, capped at 30 items of 200 chars, failed attempts only."""
    long_query = "x" * 500
    prior_tasks = [
        {
            "taskId": "stagetask-running",
            "stageId": "finding",
            "status": "running",
            "result": {"searchTrace": [{"query": "running-attempt-query"}]},
        },
        {
            "taskId": "stagetask-extraction",
            "stageId": "extraction",
            "status": "failed",
            "result": {"searchTrace": [{"query": "extraction-stage-query"}]},
        },
        {
            "taskId": "stagetask-failed",
            "stageId": "finding",
            "status": "failed",
            "updatedAt": "2026-08-28T00:00:00Z",
            "result": {
                "searchTrace": (
                    [
                        {"query": "dup-query"},
                        {"query": "DUP-QUERY"},
                        {"query": long_query},
                    ]
                    + [{"query": f"bulk-query-{i:02d}"} for i in range(40)]
                ),
                "invalidSources": (
                    [{"url": "https://example.org/dup", "reason": "404"}, {"url": "https://example.org/DUP"}]
                    + [{"url": f"https://example.org/{i}"} for i in range(35)]
                ),
            },
        },
    ]

    message = s._source_collection_finding_prior_query_memory_message(prior_tasks)
    assert _MEMORY_HEADER in message
    lines = message.splitlines()
    query_start = next(i for i, line in enumerate(lines) if "已检索过以下 query" in line)
    invalid_start = next(i for i, line in enumerate(lines) if "判为无效" in line)
    query_entries = [line for line in lines[query_start + 1 : invalid_start] if line.startswith("  - ")]
    invalid_entries = [line for line in lines[invalid_start + 1 :] if line.startswith("  - ")]

    # Running and non-finding attempts never contribute memory.
    assert "running-attempt-query" not in message
    assert "extraction-stage-query" not in message
    # Dedupe (case-insensitive) plus the 30-item cap: 3 unique head entries
    # (one truncated) leave room for 27 of the 40 bulk queries.
    assert len(query_entries) == _MAX_MEMORY_ITEMS
    assert query_entries.count("  - dup-query") == 1
    assert "  - " + "x" * _MEMORY_ITEM_MAX_LENGTH in query_entries
    assert all(len(entry) <= len("  - ") + _MEMORY_ITEM_MAX_LENGTH for entry in query_entries)
    assert len(invalid_entries) == _MAX_MEMORY_ITEMS
    assert invalid_entries.count("  - https://example.org/dup（原因：404）") == 1
    assert all(len(entry) <= len("  - ") + _MEMORY_ITEM_MAX_LENGTH + len("（原因：404）") for entry in invalid_entries)

    # Tasks without retrieval traces render no memory block at all.
    assert s._source_collection_finding_prior_query_memory_message([]) == ""
    assert (
        s._source_collection_finding_prior_query_memory_message(
        [
            {
                "taskId": "stagetask-clean",
                "stageId": "finding",
                "status": "failed",
                "result": {"candidateLeads": [{"title": "no trace"}]},
            }
        ]
        )
        == ""
    )
