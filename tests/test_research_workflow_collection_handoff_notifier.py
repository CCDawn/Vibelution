"""Source-collection completed → hypothesis-first handoff notifier."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope,
)
from core.web.services.team_workflow.source_collection import residual
from core.web.services.team_workflow.source_collection import runs as collection_runs
from core.web.services.team_workflow.source_collection import search_execution

from tests.test_research_workflow_hypothesis_first_chain import (
    _ROLES,
    _build_runtime,
    _close_first_meeting_with_envelope,
    _fake_collection_runs,
    _hf_env,
    _open_first_meeting,
    _patch_approved_question,
    _seed_parent_run,
)


def _closed_collection_request(tmp_path, monkeypatch):
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    _seed_parent_run(runtime, team_id, agents["experiment_planner"])
    agent_ids = [agents[role] for role in _ROLES]
    recorded = _open_first_meeting(team_id, agent_ids)
    meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
    closed = _close_first_meeting_with_envelope(
        team_id, agent_ids, meeting_id, runtime
    )
    request = closed["collection"]["requests"][0]
    return team_id, agents, runtime, request


def test_completed_collection_handoffs_and_opens_next_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with server_operator_scope("u-1", roles=("operator",)):
        team_id, _agents, runtime, request = _closed_collection_request(
            tmp_path, monkeypatch
        )
        try:
            first = chain.notify_collection_run_terminal(
                team_id, request["collectionRunId"], "completed"
            )
            assert first["status"] == "handed_off"
            assert first["request"]["status"] == "handed_off"
            assert first["request"]["handoffRef"].startswith("source_collection_run:")
            next_meeting = first["nextMeeting"]
            assert next_meeting["status"] in {"opened", "reused", "budget_exhausted"}
            if next_meeting["status"] != "budget_exhausted":
                assert next_meeting["meetingRound"]["meetingRoundId"]

            repeated = chain.notify_collection_run_terminal(
                team_id, request["collectionRunId"], "completed"
            )
            assert repeated["status"] == "reused"
            if next_meeting["status"] != "budget_exhausted":
                assert (
                    repeated["nextMeeting"]["meetingRound"]["meetingRoundId"]
                    == next_meeting["meetingRound"]["meetingRoundId"]
                )
        finally:
            runtime.close()


def test_failed_and_needs_continue_do_not_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with server_operator_scope("u-1", roles=("operator",)):
        team_id, _agents, runtime, request = _closed_collection_request(
            tmp_path, monkeypatch
        )
        try:
            failed = chain.notify_collection_run_terminal(
                team_id, request["collectionRunId"], "failed"
            )
            assert failed["status"] == "collection_recovery"
            latest = chain.list_collection_requests(team_id)["requests"][0]
            assert latest["status"] != "handed_off"
            assert latest["collectionRunStatus"] == "failed"

            continued = chain.notify_collection_run_terminal(
                team_id, request["collectionRunId"], "needs_continue"
            )
            assert continued["status"] == "collection_recovery"
            latest = chain.list_collection_requests(team_id)["requests"][0]
            assert latest["status"] != "handed_off"
            assert latest["collectionRunStatus"] == "needs_continue"
            assert latest["handoffRef"] == ""
        finally:
            runtime.close()


def test_handoff_failure_is_pending_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with server_operator_scope("u-1", roles=("operator",)):
        team_id, _agents, runtime, request = _closed_collection_request(
            tmp_path, monkeypatch
        )
        try:
            def boom(*_args, **_kwargs):
                raise RuntimeError("handoff writer exploded")

            original_handoff = chain.record_collection_handoff
            monkeypatch.setattr(chain, "record_collection_handoff", boom)
            pending = chain.notify_collection_run_terminal(
                team_id, request["collectionRunId"], "completed"
            )
            assert pending["status"] == "handoff_pending"
            latest = chain.list_collection_requests(team_id)["requests"][0]
            assert latest["status"] == "handoff_pending"
            assert latest["handoffError"]

            monkeypatch.setattr(chain, "record_collection_handoff", original_handoff)
            retried = chain.notify_collection_run_terminal(
                team_id, request["collectionRunId"], "completed"
            )
            assert retried["status"] == "handed_off"
            latest = chain.list_collection_requests(team_id)["requests"][0]
            assert latest["status"] == "handed_off"
        finally:
            runtime.close()


def test_completion_paths_share_sync_notifier() -> None:
    sync_src = inspect.getsource(
        search_execution._sync_source_collection_stage_round_after_search
    )
    assert "notify_collection_run_terminal" in sync_src
    foreground = inspect.getsource(collection_runs.execute_source_collection_search)
    background = inspect.getsource(
        search_execution._run_source_collection_search_background
    )
    recovery = inspect.getsource(
        residual._sync_source_collection_stage_round_from_latest_work_run
    )
    assert "_sync_source_collection_stage_round_after_search" in foreground
    assert "execute_source_collection_search" in background
    assert "_sync_source_collection_stage_round_after_search" in recovery
