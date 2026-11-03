"""Read existing native Session metadata without hydration, repair or admission.

Each owner certifies only its own observation. These facts are not a global
atomic snapshot. Journal-only open Turns cannot certify worker liveness.
In particular, an empty result never certifies that ordinary Sessions are idle.
"""
from __future__ import annotations

import re
from itertools import islice
from pathlib import Path
from typing import Any

from . import directory_runtime

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")


def _service():
    from core.web.services import session_service

    return session_service


def _identity(value: Any, *, optional: bool = False) -> bool:
    return isinstance(value, str) and (optional and value == "" or _ID.fullmatch(value) is not None)


def _coverage(source: str, *, invalid: int = 0, truncated: bool = False,
              unavailable: bool = False, reason: str = "none", pending: int = 0,
              external: int = 0, revision: int | None = None) -> dict[str, Any]:
    complete = not (invalid or truncated or unavailable or pending or reason != "none")
    return {"source": source, "state": "unavailable" if unavailable else "available" if complete else "partial",
            "complete": complete, "truncated": truncated, "invalidCount": invalid,
            "reason": reason, "pendingAdmissionCount": pending, "externalReservationCount": external,
            "revision": revision}


def _running_turns(owner, *, max_rows: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # Do not hold these locks while calling controller code or SQLite, and do
    # not acquire the scheduler lock under running: its callbacks use running.
    with owner._RUNNING_SESSIONS_LOCK:
        running = set(islice(owner._RUNNING_SESSION_IDS, max_rows))
        active = dict(islice(owner._SESSION_ACTIVE_TURN_IDS.items(), max_rows))
        truncated = max(len(owner._RUNNING_SESSION_IDS), len(owner._SESSION_ACTIVE_TURN_IDS)) > max_rows
    with owner._SESSION_TURN_CONTROLS_LOCK:
        controls = dict(islice(owner._SESSION_TURN_CONTROLS.items(), max_rows))
        truncated = truncated or len(owner._SESSION_TURN_CONTROLS) > max_rows
    invalid = len(set(active) - running) + len(set(controls) - running)
    items = []
    changed = False
    for sid in running:
        tid, controller = active.get(sid), controls.get(sid)
        if (not _identity(sid) or not _identity(tid) or controller is None
                or getattr(controller, "turn_id", None) != tid):
            invalid += 1
            continue
        try:
            state = controller.snapshot()
            if (not isinstance(state, dict) or state.get("turnId") != tid
                    or type(state.get("stopRequested")) is not bool
                    or type(state.get("releasedToUser")) is not bool or state["releasedToUser"]):
                invalid += 1
                continue
        except Exception:
            invalid += 1
            continue
        with owner._RUNNING_SESSIONS_LOCK:
            still_current = sid in owner._RUNNING_SESSION_IDS and owner._SESSION_ACTIVE_TURN_IDS.get(sid) == tid
        with owner._SESSION_TURN_CONTROLS_LOCK:
            still_current = still_current and owner._SESSION_TURN_CONTROLS.get(sid) is controller
        if not still_current or getattr(controller, "turn_id", None) != tid:
            changed = True
            invalid += 1
            continue
        items.append({"sessionId": sid, "turnId": tid, "agentId": "",
                      "status": "stopping" if state["stopRequested"] else "running",
                      "stopRequested": state["stopRequested"], "releasedToUser": False,
                      "liveControl": True, "sources": ["running_controller"]})
    with owner._RUNNING_SESSIONS_LOCK:
        after_running = set(islice(owner._RUNNING_SESSION_IDS, max_rows))
        after_active = dict(islice(owner._SESSION_ACTIVE_TURN_IDS.items(), max_rows))
        changed = changed or running != after_running or active != after_active
    with owner._SESSION_TURN_CONTROLS_LOCK:
        after_controls = dict(islice(owner._SESSION_TURN_CONTROLS.items(), max_rows))
        changed = changed or controls.keys() != after_controls.keys() or any(
            after_controls.get(sid) is not control for sid, control in controls.items())
    items = [item for item in items if item["sessionId"] in after_running
             and after_active.get(item["sessionId"]) == item["turnId"]
             and after_controls.get(item["sessionId"]) is controls.get(item["sessionId"])]
    return items, _coverage("running_controller", invalid=invalid, truncated=truncated,
                           reason="source_changed" if changed else "invalid_metadata" if invalid else "none")


def _scheduled_turns(owner, *, max_rows: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    snapshot = owner._SESSION_TURN_SCHEDULER.snapshot_queued_turn_metadata(max_rows=max_rows)
    items: dict[tuple[str, str], dict[str, Any]] = {}
    seen: set[tuple[str, str]] = set()
    invalid = snapshot["invalidCount"]
    for entry in snapshot["entries"]:
        if entry["admissionPending"]:
            continue
        identity = (entry["sessionId"], entry["turnId"])
        if identity in seen:
            invalid += 1 + int(identity in items)
            items.pop(identity, None)
            continue
        seen.add(identity)
        items[identity] = {"sessionId": entry["sessionId"], "turnId": entry["turnId"],
                           "agentId": entry["agentId"], "status": "queued", "stopRequested": False,
                           "releasedToUser": False, "liveControl": False, "sources": ["scheduler"]}
    pending = snapshot["pendingAdmissionCount"]
    return list(items.values()), _coverage("scheduler", invalid=invalid, truncated=snapshot["truncated"],
        pending=pending, external=snapshot["externalReservationCount"],
        reason="invalid_metadata" if invalid else "pending_admission" if pending else "none")


def _queued_rows(project_root: Path, *, max_rows: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        pin = directory_runtime.pin_open_directory_store(project_root)
    except ValueError:
        return [], _coverage("persisted_queue", unavailable=True, reason="project_binding_mismatch")
    if pin is None:
        return [], _coverage("persisted_queue", unavailable=True, reason="store_not_open")
    try:
        snapshot = pin.store.repository.read_session_queue_metadata_snapshot(max_rows=max_rows)
        if not directory_runtime.directory_store_pin_is_current(pin):
            return [], _coverage("persisted_queue", unavailable=True, reason="source_changed")
        return snapshot["rows"], _coverage("persisted_queue", invalid=snapshot["invalidCount"],
            truncated=snapshot["truncated"], revision=snapshot["stateRevision"],
            reason="invalid_metadata" if snapshot["invalidCount"] else "budget_exceeded" if snapshot["truncated"] else "none")
    except Exception:
        return [], _coverage("persisted_queue", unavailable=True, reason="read_failed")


def read_session_runtime_inventory(project_root: Path, *, max_rows: int = 10000) -> dict[str, Any]:
    """Closed observation over running/controller, scheduler and existing queues.

    Queues retain queueId: they are pre-Turn rows, and several notices may
    become one Turn while a control_notice opens no model Turn at all.
    No commands, Session hydration, index repair or admission occurs. Journal
    bytes stay inside the native metadata inventory owner.
    """
    if type(max_rows) is not int or not 1 <= max_rows <= 10000:
        raise ValueError("Invalid metadata inventory limit")
    root = Path(project_root).resolve()
    owner = _service()
    turns, coverage = [], []
    for source, read in (("running_controller", _running_turns), ("scheduler", _scheduled_turns)):
        try:
            if Path(owner.PROJECT_ROOT).resolve() != root:
                facts, state = [], _coverage(source, unavailable=True, reason="project_binding_mismatch")
            else:
                facts, state = read(owner, max_rows=max_rows)
        except Exception:
            facts, state = [], _coverage(source, unavailable=True, reason="read_failed")
        turns.extend(facts)
        coverage.append(state)
    try:
        from core.chat.turn_journal_inventory import read_turn_journal_inventory
        journal = read_turn_journal_inventory(root, max_directories=max_rows)
        turns.extend(journal["turns"])
        coverage.append(_coverage("journal", invalid=journal["invalidCount"], truncated=journal["truncated"],
                                  unavailable=journal["unavailable"], reason=journal["reason"]))
    except Exception:
        coverage.append(_coverage("journal", unavailable=True, reason="read_failed"))
    by_id: dict[tuple[str, str], dict[str, Any]] = {}
    for fact in turns:
        identity = (fact["sessionId"], fact["turnId"])
        previous = by_id.get(identity)
        if previous is None:
            by_id[identity] = fact
        else:
            previous["sources"].extend(fact["sources"])
            previous["agentId"] = previous["agentId"] or fact["agentId"]
            if previous["status"] != "stopping" and fact["status"] != "unknown":
                previous["status"] = fact["status"]
    queues, state = _queued_rows(root, max_rows=max_rows)
    coverage.append(state)
    return {"turns": sorted(by_id.values(), key=lambda item: (item["sessionId"], item["turnId"])),
            "queues": queues, "sourceCoverage": coverage, "consistency": "non_atomic", "complete": False}
