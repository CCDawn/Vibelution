"""Exhausted-assignment closure: the collection zombie regression (SCI-014).

Root cause: a source-collection assignment whose LAST query only yielded
low-quality-rejected results keeps a ``returned`` output with
``blockingIssues=["no_importable_search_result"]``; the assignment stays in
the open set (``returned``), ``searchOpenAssignmentCount`` pins the run in
``needs_continue`` forever, and every re-dispatched worker skips the
already-attempted queries and writes another no-op batch.

The worker tail must close such exhausted assignments with exactly one
``queries exhausted`` closing output (idempotent), and must never touch
assignments that still have runnable queries or whose latest output carries a
different blocking issue.  All content below is fixture data; no network.
"""

from __future__ import annotations

from core.web.services.team_workflow.source_collection import search_execution
from tests._support.team_workflow.helpers import (  # noqa: F401
    _use_fake_local_research_config,
    _use_tmp_project_root,
)
from core.web.services import (
    data_processing_service,
    team_service,
    team_workflow_orchestration_service,
)


def _empty_search_response(query, *, max_results, provider):
    query_text = str(query.get("query") or "neural source")
    return {
        "provider": provider,
        "searchUrl": f"https://api.example.test/search?q={query_text.replace(' ', '+')}",
        "results": [],
    }


def _seed_search_assignment(run_id, *, query_ids, status="returned"):
    return data_processing_service.create_collection_assignment(
        run_id,
        {
            "agentRole": "source_finder",
            "status": status,
            "scope": {
                "assignedQueries": [
                    {"queryId": query_id, "query": f"predictive coding {query_id}"}
                    for query_id in query_ids
                ]
            },
        },
    )


def _zombie_output(run_id, assignment_id, query_id, *, remaining):
    return data_processing_service.record_collection_output(
        run_id,
        assignment_id,
        {
            "status": "returned",
            "records": [],
            "notes": "Automated metadata search returned no importable records for this query.",
            "blockingIssues": ["no_importable_search_result"],
            "qualitySignals": {"queryId": query_id, "remainingQueryCount": remaining},
        },
    )["output"]


def test_closure_writes_single_closing_output_for_exhausted_assignment(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    run_id = data_processing_service.create_processing_run(title="zombie closure unit")["runId"]
    assignment = _seed_search_assignment(run_id, query_ids=["q1", "q2"])
    _zombie_output(run_id, assignment["assignmentId"], "q1", remaining=1)
    _zombie_output(run_id, assignment["assignmentId"], "q2", remaining=0)
    outputs = data_processing_service.list_collection_outputs(run_id)["outputs"]

    closed = search_execution._close_exhausted_source_collection_assignments(
        run_id,
        [assignment],
        outputs,
        {"q1", "q2"},
    )

    # exactly one closing output, on the no-record output-record schema
    assert len(closed) == 1
    closing = closed[0]
    assert closing["assignmentId"] == assignment["assignmentId"]
    assert closing["status"] == "completed"
    assert closing["notes"] == "queries exhausted"
    assert closing["blockingIssues"] == []
    assert closing["qualitySignals"]["closingOutput"] is True

    # the assignment leaves the open set
    assignments = data_processing_service.list_collection_assignments(run_id)["assignments"]
    assert assignments[0]["status"] == "completed"

    # idempotent replay: the closing output is the latest one, nothing appended
    replayed = search_execution._close_exhausted_source_collection_assignments(
        run_id,
        assignments,
        data_processing_service.list_collection_outputs(run_id)["outputs"],
        {"q1", "q2"},
    )
    assert replayed == []
    outputs_after = data_processing_service.list_collection_outputs(run_id)["outputs"]
    assert len(outputs_after) == len(outputs) + 1
    assert len([item for item in outputs_after if item["notes"] == "queries exhausted"]) == 1


def test_closure_skips_assignment_with_remaining_runnable_queries(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    run_id = data_processing_service.create_processing_run(title="zombie closure runnable")["runId"]
    assignment = _seed_search_assignment(run_id, query_ids=["q1", "q2"])
    _zombie_output(run_id, assignment["assignmentId"], "q1", remaining=1)

    closed = search_execution._close_exhausted_source_collection_assignments(
        run_id,
        [assignment],
        data_processing_service.list_collection_outputs(run_id)["outputs"],
        {"q1"},
    )

    assert closed == []
    assignments = data_processing_service.list_collection_assignments(run_id)["assignments"]
    assert assignments[0]["status"] == "returned"


def test_closure_skips_assignment_with_different_blocking_issue(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    run_id = data_processing_service.create_processing_run(title="zombie closure blocker")["runId"]
    assignment = _seed_search_assignment(run_id, query_ids=["q1"])
    data_processing_service.record_collection_output(
        run_id,
        assignment["assignmentId"],
        {
            "status": "returned",
            "records": [],
            "notes": "Provider outage blocked this query.",
            "blockingIssues": ["provider_outage"],
            "qualitySignals": {"queryId": "q1", "remainingQueryCount": 0},
        },
    )

    closed = search_execution._close_exhausted_source_collection_assignments(
        run_id,
        [assignment],
        data_processing_service.list_collection_outputs(run_id)["outputs"],
        {"q1"},
    )

    assert closed == []
    assignments = data_processing_service.list_collection_assignments(run_id)["assignments"]
    assert assignments[0]["status"] == "returned"


def test_execute_search_closes_zombie_assignment_and_stays_idempotent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_execute_source_collection_query",
        _empty_search_response,
    )
    team = team_service.create_team(name="ai科学研究团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "title": "Zombie collection batch",
            "topic": "predictive coding cortical hierarchy",
            "querySeeds": ["predictive coding cortical hierarchy"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": "Source Finder Agent"},
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    plan_query_count = len(run_response["searchPlan"]["queries"])

    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_id,
        {"maxQueries": plan_query_count, "maxResultsPerQuery": 2},
    )

    # every plan query was attempted and only yielded the stuck no-record
    # outputs; the worker tail closed the assignment in the same batch
    assert execution["attemptedQueryCount"] == plan_query_count
    assert execution["recordCount"] == 0
    assert execution["remainingQueryCount"] == 0
    assert execution["hasMore"] is False
    assert execution["sourceCollectionSummary"]["searchOpenAssignmentCount"] == 0
    assignments = data_processing_service.list_collection_assignments(run_id)["assignments"]
    assert all(item["status"] == "completed" for item in assignments)
    outputs = data_processing_service.list_collection_outputs(run_id)["outputs"]
    closing_outputs = [item for item in outputs if item["notes"] == "queries exhausted"]
    assert len(closing_outputs) == 1
    assert closing_outputs[0]["status"] == "completed"

    # re-dispatch of the would-be zombie run: every query is skipped, the
    # replay appends no output and the assignment stays closed
    replay = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_id,
        {"maxQueries": plan_query_count, "maxResultsPerQuery": 2},
    )
    assert replay["attemptedQueryCount"] == 0
    assert data_processing_service.list_collection_outputs(run_id)["outputs"] == outputs
    assert all(
        item["status"] == "completed"
        for item in data_processing_service.list_collection_assignments(run_id)["assignments"]
    )
    assert replay["sourceCollectionSummary"]["searchOpenAssignmentCount"] == 0
