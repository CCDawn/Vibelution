"""Read-only team references for the existing Launcher patrol admission chain.

Only the local request association and a current, verified native receipt can
produce an event. No result body, team discovery, run admission or replay lives
here; the patrol ledger remains the sole delivery/attempt record.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time

import anyio

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z")
_TERMINAL = {"completed", "failed", "stopped"}
_BATCH = 16
_BUDGET = 4.0
_FRESH_FOR = 60.0
_ACTIONS = ("team_run", "flow_start")


def team_event(row):
    """Canonical, body-free event; authorization is checked by the observer."""
    fields = ("projectId", "requestId", "teamId", "flowId", "runId", "status")
    if (row.get("kind") != "team_run" or row.get("status") not in _TERMINAL
            or row.get("originAction", "team_run") not in _ACTIONS):
        return None
    if any(not isinstance(row.get(key), str) or not _ID.fullmatch(row[key])
           for key in fields[:-1]) or not _REQUEST.fullmatch(row["requestId"]):
        return None
    event = {"kind": "team_run", **{key: row[key] for key in fields}}
    if "originAction" in row:
        # Old team events retain their exact bytes/hash across ledger recovery.
        event["originAction"] = row["originAction"]
    encoded = json.dumps(event, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return {**event, "eventId": hashlib.sha256(encoded.encode()).hexdigest()}


def _key(row):
    return row["projectId"], row.get("originAction", row.get("action", "team_run")), row["requestId"]


class TeamPatrolObserver:
    def __init__(self, dispatch):
        self.dispatch = dispatch
        self._lock = threading.RLock()
        self._observations = {}
        self._cursor = 0
        self.status = {"state": "unknown"}

    def _requests(self, project_id=None, action=None):
        rows, coverage = [], None
        for origin in (action,) if action is not None else _ACTIONS:
            found, observed = self._request_pages(project_id, origin)
            if coverage is not None and coverage != observed:
                raise ValueError("team_patrol_references_unknown")
            rows.extend(found)
            coverage = observed
        return rows, coverage

    def _request_pages(self, project_id, action):
        """Read every local reference page; a broken scan is never an empty set."""
        management = self.dispatch.management
        rows, seen, offset, total, coverage = [], set(), 0, None, None
        while True:
            page = management.list_requests(project_id=project_id, action=action, offset=offset, limit=20)
            if (not isinstance(page, dict) or type(page.get("total")) is not int or page["total"] < 0
                    or page.get("offset") != offset or not isinstance(page.get("requests"), list)
                    or len(page["requests"]) > 20 or total is not None and page["total"] != total):
                raise ValueError("team_patrol_references_unknown")
            observed_coverage = page.get("coverage")
            if (not isinstance(observed_coverage, dict) or observed_coverage.get("kind") != "local_associations"
                    or any(type(observed_coverage.get(key)) is not int or observed_coverage[key] < 0
                           for key in ("legacyUnrecoverable", "invalidRecords"))
                    or coverage is not None and observed_coverage != coverage):
                raise ValueError("team_patrol_references_unknown")
            total, coverage = page["total"], observed_coverage
            for row in page["requests"]:
                if (not isinstance(row, dict) or row.get("action") != action
                        or not isinstance(row.get("projectId"), str) or not _ID.fullmatch(row["projectId"])
                        or not isinstance(row.get("requestId"), str) or not _REQUEST.fullmatch(row["requestId"])
                        or project_id is not None and row["projectId"] != project_id
                        or _key(row) in seen):
                    raise ValueError("team_patrol_references_unknown")
                seen.add(_key(row))
                rows.append({key: row[key] for key in ("projectId", "action", "requestId")})
            end = offset + len(page["requests"])
            following = page.get("nextOffset")
            if following is None:
                if end != total:
                    raise ValueError("team_patrol_references_unknown")
                return rows, coverage
            if type(following) is not int or following != end or not offset < following < total:
                raise ValueError("team_patrol_references_unknown")
            offset = following

    def _binding(self, project_id):
        # Includes both the registry generation and the exact admitted root.
        return self.dispatch._project_read_binding(project_id)

    def current(self, event):
        try:
            with self._lock:
                observation = self._observations.get(_key(event))
            if (observation is None or observation[0] != event
                    or time.monotonic() - observation[2] > _FRESH_FOR
                    or self._binding(event["projectId"]) != observation[1]):
                return False
            rows, _ = self._requests(event["projectId"], event.get("originAction", "team_run"))
            with self._lock:
                return (self._observations.get(_key(event)) == observation
                        and any(_key(row) == _key(event) for row in rows))
        except Exception:
            return False

    async def refresh(self, *, settled=(), priority=()):
        """Bound native reads, retaining fair progress through all reference pages."""
        if not callable(getattr(getattr(self.dispatch, "management", None), "list_requests", None)):
            self.status = {"state": "unavailable"}
            return []
        try:
            rows, coverage = await anyio.to_thread.run_sync(self._requests)
        except Exception:
            with self._lock:
                self._observations.clear()
                self.status = {"state": "unknown"}
            return []
        keys = {_key(row) for row in rows}
        with self._lock:
            self._observations = {key: value for key, value in self._observations.items() if key in keys}
        candidates = [row for row in rows if _key(row) not in settled or _key(row) in priority]
        urgent = [row for row in candidates if _key(row) in priority]
        remaining = [row for row in candidates if _key(row) not in priority]
        if remaining:
            start = self._cursor % len(remaining)
            remaining = remaining[start:] + remaining[:start]
        fresh, attempted, ordinary, failed = [], 0, 0, False
        with anyio.move_on_after(_BUDGET) as budget:
            for row in [*urgent, *remaining][:_BATCH]:
                attempted += 1
                ordinary += _key(row) not in priority
                key = _key(row)
                try:
                    binding = self._binding(row["projectId"])
                    result = await self.dispatch.management.receipt(row["projectId"], action=row["action"],
                                                                    request_id=row["requestId"])
                    if (not isinstance(result, dict) or result.get("projectId") != row["projectId"]
                            or result.get("requestId") != row["requestId"] or result.get("action") != row["action"]):
                        raise ValueError("team_patrol_receipt_invalid")
                    run = result.get("teamRun")
                    if result.get("status") == "unknown" or result.get("verified") is not True:
                        failed = True
                    if row["action"] == "flow_start":
                        run = await self._flow_run(row, result)
                    if self._binding(row["projectId"]) != binding:
                        raise ValueError("team_patrol_binding_changed")
                    event = (team_event({"kind": "team_run", "projectId": row["projectId"],
                             **({"originAction": "flow_start"} if row["action"] == "flow_start" else {}),
                             "requestId": row["requestId"], **{name: run.get(name)
                             for name in ("teamId", "flowId", "runId", "status")}})
                             if isinstance(run, dict) and result.get("verified") is True
                             and result.get("status") == "completed" else None)
                    if isinstance(run, dict) and run.get("status") in _TERMINAL and event is None:
                        failed = True
                    with self._lock:
                        self._observations.pop(key, None)
                        if event is not None:
                            self._observations[key] = event, binding, time.monotonic()
                            fresh.append(event)
                except Exception:
                    failed = True
                    with self._lock:
                        self._observations.pop(key, None)
        if budget.cancel_called:
            # The read in progress did not confirm anything. Earlier native
            # receipts may still be used; the timed-out reference may not.
            failed = True
            with self._lock:
                self._observations.pop(key, None)
        self._cursor += ordinary
        self.status = {"state": "partial" if failed or attempted < len(candidates)
                       or coverage["legacyUnrecoverable"] or coverage["invalidRecords"] else "ready",
                       "coverage": coverage}
        return fresh

    async def _flow_run(self, row, receipt):
        """A stored start acknowledgement is never current terminal evidence."""
        ack = receipt.get("flow")
        if (receipt.get("status") != "completed" or receipt.get("verified") is not True
                or not isinstance(ack, dict) or ack.get("action") != "flow_start" or ack.get("verified") is not True
                or any(not isinstance(ack.get(key), str) or not _ID.fullmatch(ack[key])
                       for key in ("teamId", "flowId", "runId"))):
            raise ValueError("team_patrol_flow_ack_invalid")
        result = await self.dispatch.management.runtime(row["projectId"], "get", kind="team_run",
            resource_id=ack["runId"], team_id=ack["teamId"], flow_id=ack["flowId"])
        operation = result.get("operation") if isinstance(result, dict) else None
        if (not isinstance(result, dict) or result.get("projectId") != row["projectId"]
                or not isinstance(operation, dict) or operation.get("kind") != "team_run"
                or operation.get("resourceId") != ack["runId"]
                or operation.get("teamId") != ack["teamId"] or operation.get("flowId") != ack["flowId"]):
            raise ValueError("team_patrol_flow_status_invalid")
        return {**{key: ack[key] for key in ("teamId", "flowId", "runId")}, "status": operation.get("status")}
