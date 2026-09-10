"""Awaiting-approval reaper: escalation at 48 h, auto-reject at 7 d.

A digest that FAILED the auto-approve quality gate waits for a human
forever; the reaper escalates the wait once (anomaly-inbox item) and
auto-rejects past 7 d through the existing manual reject domain path with
``decidedBy="system:reaper"``, idempotent on the meeting's closure digest.
Meetings whose digest PASSES the gate are never touched, non-awaiting
states are never touched, and the kill switch restores the manual-only
contract.  Timestamps are injected (no wall-clock dependence).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core.web.services import team_service
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import reaper
from tests._support.team_workflow.helpers import _use_tmp_project_root

_TEAM_ID = "team-reaper"
_BASE_MS = 1_783_000_000_000  # fixed epoch; every timestamp derives from it


def _offset_iso(*, hours: float) -> str:
    moment = datetime.fromtimestamp(_BASE_MS / 1000, tz=timezone.utc) - timedelta(
        hours=hours
    )
    return moment.isoformat().replace("+00:00", "Z")


def _reaper_env(tmp_path, monkeypatch) -> str:
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.delenv(reaper.REAPER_KILL_SWITCH_ENV, raising=False)
    reaper.reset_reaper_throttle_for_tests()
    team_id = _TEAM_ID
    # Seed the chain ledger so _team_ids_with_chain_storage sees the team.
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": chain.SCHEMA_VERSION,
            "recordKind": "reaper_seed",
            "createdAt": _offset_iso(hours=0),
        },
    )
    return team_id


def _seed_awaiting_meeting(
    team_id: str,
    meeting_id: str,
    *,
    updated_at: str,
    meeting_type: str = "hypothesis_review",
    with_digest: bool = True,
    summary_draft_error: str = "",
) -> dict:
    record = meetings.create_meeting_round(
        team_id,
        {
            "program": "XH-202619",
            "theme": "cc-reaper",
            "campaign": "cc-reaper",
            "question": "SCI-007",
            "branch": "main",
            "workflow": "hypothesis_first",
            "agentId": "agent-coordinator",
            "mode": "dev",
            "meetingRoundId": meeting_id,
            "meetingType": meeting_type,
            "participants": ["agent-reviewer"],
            "discussionItemRefs": ["hypothesis_candidate:candidate-a"],
        },
    )["meetingRound"]
    updated = {**record, "status": "awaiting_approval", "updatedAt": updated_at}
    if with_digest:
        updated["digestDraft"] = {"contentHash": f"hash-{meeting_id}"}
    if summary_draft_error:
        updated["summaryDraftError"] = summary_draft_error
    meetings._append_round_record(team_id, updated)
    return updated


def _reaper_decisions(team_id: str) -> list[dict]:
    return [
        dict(record)
        for record in chain._read_jsonl(chain._storage_path(team_id))
        if record.get("recordKind") == reaper.REAPER_DECISION_KIND
    ]


def test_escalates_once_after_48h_and_stays_awaiting(tmp_path, monkeypatch) -> None:
    team_id = _reaper_env(tmp_path, monkeypatch)
    _seed_awaiting_meeting(
        team_id,
        "meeting-stalled-49h",
        updated_at=_offset_iso(hours=49),
        summary_draft_error="digest provider exploded",
    )

    summary = reaper.reap_awaiting_approval_meetings(
        now_ms=_BASE_MS, respect_throttle=False
    )

    assert summary["escalated"] == 1
    assert summary["rejected"] == 0
    # Escalation only: the meeting keeps waiting for its human gate.
    meeting = meetings.get_meeting_round(team_id, "meeting-stalled-49h")[
        "meetingRound"
    ]
    assert meeting["status"] == "awaiting_approval"
    decisions = _reaper_decisions(team_id)
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision["action"] == "escalate"
    assert decision["decidedBy"] == "system:reaper"
    assert decision["idempotencyKey"].startswith(
        f"hf2:reaper:escalate:{team_id}:meeting-stalled-49h:"
    )
    items = decision["escalation"]["items"]
    assert decision["escalation"]["status"] == "emitted"
    assert items[0]["kind"] == "needs_human_gate"
    assert items[0]["scope"]["meetingRoundId"] == "meeting-stalled-49h"

    # Replay: the same digest escalates exactly once (idempotent marker).
    replay = reaper.reap_awaiting_approval_meetings(
        now_ms=_BASE_MS, respect_throttle=False
    )
    assert replay["escalated"] == 0
    assert replay["skipped"] == 1
    assert len(_reaper_decisions(team_id)) == 1


def test_auto_rejects_once_after_7d_via_manual_domain_path(
    tmp_path, monkeypatch
) -> None:
    team_id = _reaper_env(tmp_path, monkeypatch)
    _seed_awaiting_meeting(
        team_id,
        "meeting-stalled-8d",
        updated_at=_offset_iso(hours=8 * 24),
        summary_draft_error="digest provider exploded",
    )

    summary = reaper.reap_awaiting_approval_meetings(
        now_ms=_BASE_MS, respect_throttle=False
    )

    assert summary["rejected"] == 1
    assert summary["escalated"] == 0
    # The EXISTING manual reject domain path ran: awaiting -> summarizing,
    # draft popped, system:reaper recorded as the rejecting actor.
    meeting = meetings.get_meeting_round(team_id, "meeting-stalled-8d")[
        "meetingRound"
    ]
    assert meeting["status"] == "summarizing"
    assert "digestDraft" not in meeting
    assert meeting["draftRejectedBy"] == "system:reaper"
    decisions = _reaper_decisions(team_id)
    assert len(decisions) == 1
    assert decisions[0]["action"] == "reject"
    assert decisions[0]["decidedBy"] == "system:reaper"
    assert decisions[0]["idempotencyKey"].startswith(
        f"hf2:reaper:reject:{team_id}:meeting-stalled-8d:"
    )

    # Replay on the same closure digest is a no-op: re-seed the awaiting
    # state (same meeting id + digest hash) and the recorded marker wins.
    updated = {
        **meeting,
        "status": "awaiting_approval",
        "updatedAt": _offset_iso(hours=8 * 24),
        "digestDraft": {"contentHash": "hash-meeting-stalled-8d"},
        "summaryDraftError": "digest provider exploded",
    }
    meetings._append_round_record(team_id, updated)
    replay = reaper.reap_awaiting_approval_meetings(
        now_ms=_BASE_MS, respect_throttle=False
    )
    assert replay["rejected"] == 0
    assert replay["skipped"] == 1
    assert len(_reaper_decisions(team_id)) == 1
    still = meetings.get_meeting_round(team_id, "meeting-stalled-8d")[
        "meetingRound"
    ]
    assert still["status"] == "awaiting_approval"


def test_passed_digest_meeting_is_never_reaped(tmp_path, monkeypatch) -> None:
    """A digest that PASSES the gate stays on the auto-approve path."""
    team_id = _reaper_env(tmp_path, monkeypatch)
    _seed_awaiting_meeting(
        team_id,
        "meeting-healthy-8d",
        updated_at=_offset_iso(hours=8 * 24),
        with_digest=True,
    )

    summary = reaper.reap_awaiting_approval_meetings(
        now_ms=_BASE_MS, respect_throttle=False
    )

    assert summary["rejected"] == 0
    assert summary["escalated"] == 0
    assert summary["skipped"] == 1
    meeting = meetings.get_meeting_round(team_id, "meeting-healthy-8d")[
        "meetingRound"
    ]
    assert meeting["status"] == "awaiting_approval"
    assert _reaper_decisions(team_id) == []


def test_kill_switch_disables_the_reaper(tmp_path, monkeypatch) -> None:
    team_id = _reaper_env(tmp_path, monkeypatch)
    _seed_awaiting_meeting(
        team_id,
        "meeting-stalled-8d-off",
        updated_at=_offset_iso(hours=8 * 24),
        summary_draft_error="digest provider exploded",
    )
    monkeypatch.setenv(reaper.REAPER_KILL_SWITCH_ENV, "0")

    summary = reaper.reap_awaiting_approval_meetings(
        now_ms=_BASE_MS, respect_throttle=False
    )

    assert summary["status"] == "skipped"
    assert summary["reason"] == "kill_switch_off"
    assert summary["rejected"] == 0
    meeting = meetings.get_meeting_round(team_id, "meeting-stalled-8d-off")[
        "meetingRound"
    ]
    assert meeting["status"] == "awaiting_approval"
    assert _reaper_decisions(team_id) == []


def test_fresh_and_passing_gate_meetings_are_untouched(
    tmp_path, monkeypatch
) -> None:
    team_id = _reaper_env(tmp_path, monkeypatch)
    _seed_awaiting_meeting(
        team_id,
        "meeting-fresh-gate-failed",
        updated_at=_offset_iso(hours=1),
        summary_draft_error="digest provider exploded",
    )
    _seed_awaiting_meeting(
        team_id,
        "meeting-candgen-passing",
        updated_at=_offset_iso(hours=8 * 24),
        meeting_type="hypothesis_candidate_generation",
        with_digest=False,
    )
    # A generation digest with proposals and zero validation errors PASSES
    # the quality gate: the auto-approve sweep owns it, never the reaper.
    record = meetings.get_meeting_round(team_id, "meeting-candgen-passing")[
        "meetingRound"
    ]
    meetings._append_round_record(
        team_id,
        {
            **record,
            "digestDraft": {
                "contentHash": "hash-candgen-passing",
                "proposedCandidates": [
                    {"candidateId": "hyp-new", "proposedBy": "agent-a"}
                ],
            },
        },
    )

    summary = reaper.reap_awaiting_approval_meetings(
        now_ms=_BASE_MS, respect_throttle=False
    )

    assert summary["rejected"] == 0
    assert summary["escalated"] == 0
    assert summary["skipped"] == 2
    assert _reaper_decisions(team_id) == []
    for meeting_id in ("meeting-fresh-gate-failed", "meeting-candgen-passing"):
        meeting = meetings.get_meeting_round(team_id, meeting_id)["meetingRound"]
        assert meeting["status"] == "awaiting_approval"


def test_recovery_loop_hook_drives_the_reaper(monkeypatch) -> None:
    """run_hypothesis_recovery_once is the production reaper host."""
    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        WorkflowRuntime,
    )

    calls: list[str] = []

    class _Stub:
        def _sweep_auto_advance_closure_best_effort(self) -> None:
            calls.append("auto_advance")

        _reap_awaiting_approval_best_effort = (
            WorkflowRuntime._reap_awaiting_approval_best_effort
        )

    def fake_reap(**_kwargs) -> dict:
        calls.append("reaper")
        return {"status": "ok"}

    monkeypatch.setattr(reaper, "reap_awaiting_approval_meetings", fake_reap)
    stub = _Stub()
    assert WorkflowRuntime.run_hypothesis_recovery_once(stub, limit=4) == 0
    assert calls == ["auto_advance", "reaper"]


def test_reaper_hook_isolates_failures(monkeypatch) -> None:
    """A raising reaper never breaks the recovery tick (never raises)."""
    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        WorkflowRuntime,
    )

    class _Stub:
        def _sweep_auto_advance_closure_best_effort(self) -> None:
            pass

        _reap_awaiting_approval_best_effort = (
            WorkflowRuntime._reap_awaiting_approval_best_effort
        )

    def boom(**_kwargs) -> dict:
        raise RuntimeError("reaper exploded")

    monkeypatch.setattr(reaper, "reap_awaiting_approval_meetings", boom)
    assert (
        WorkflowRuntime.run_hypothesis_recovery_once(_Stub(), limit=4) == 0
    )
