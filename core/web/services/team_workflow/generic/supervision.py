"""Project canonical native facts into an explicitly bound repair supervisor.

This owns no native task state, transcript, retry budget or execution queue.
"""
from __future__ import annotations

from copy import deepcopy

from . import source_adapter, service, store


def observe(target, record: dict) -> None:
    if record["stopRequested"] or record["status"] == "stopped":
        return
    before = deepcopy(record)
    snapshot = source_adapter.observe(record)
    state = record.get("recovery")
    old_key = (record.get("attempts") or [{}])[-1].get("key")
    record["attempts"] = snapshot["attempts"]
    record["status"] = snapshot["status"]
    record["_sourceRetryExhausted"] = snapshot["retryExhausted"]
    record["_sourceEligible"] = snapshot["eligible"]
    record["_sourceReason"] = snapshot["reason"]
    record["error"] = snapshot["reason"] if snapshot["status"] == "failed" else ""
    new_key = (record.get("attempts") or [{}])[-1].get("key")
    if state and state["status"] not in {"resolved", "cancelled"}:
        from .recovery import _stop_child
        if snapshot["status"] == "stopped":
            state.update(status="cancelled", reason="source_stopped")
            _stop_child(record["teamId"], record)
        elif snapshot["status"] == "completed":
            state.update(status="resolved", reason="source_step_succeeded", replayedAttemptKey=new_key or "")
            _stop_child(record["teamId"], record)
        elif state["status"] == "repairing" and (new_key != old_key or not snapshot["eligible"]
                                                  or snapshot["status"] != "failed"):
            state.update(status="blocked", reason="source_advanced_or_unavailable")
            _stop_child(record["teamId"], record)
        elif (state["status"] == "awaiting_replay_decision" and new_key != old_key
              and record["flow"]["steps"][0]["kind"] == "session"
              and snapshot["reason"] not in {"source_lineage_invalid", "source_advanced"}):
            state.update(status="replaying", reason="source_manual_retry")
    if record != before:
        service._changed(target, record)
        if state:
            from .recovery import log_transition
            log_transition(record)


def request_replay(record: dict) -> None:
    state = record["recovery"]
    last = record["attempts"][-1]
    # Persist this intent before crossing the Ledger transaction boundary. A
    # lost response must be recovered using the adapter's exact command key.
    record["_recoveryReplayAfter"] = last["key"]
    record["_sourceReplayPending"] = True
    state.update(status="replaying", reason="source_replay_pending")


def submit_replay(target, record: dict) -> None:
    if not record.get("_sourceReplayPending") or record["stopRequested"]:
        return
    reason = source_adapter.replay(record)
    record.pop("_sourceReplayPending", None)
    if reason:
        record["recovery"].update(status="awaiting_replay_decision", reason=reason)
    else:
        record["status"] = "running"
        record["recovery"].update(status="replaying", reason="safe_replay")
    service._changed(target, record)
