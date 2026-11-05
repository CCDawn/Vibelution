"""Bounded, read-only observation of authorized native runtime metadata.

This checkpoint is not a runtime index: absence never settles an operation.
Only identities, status/progress fingerprints and observation times survive a
restart. All wakes still belong to LauncherPatrol and native Session admission.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time

import anyio

from core.infrastructure.atomic_io import atomic_write_json
from .migration_io import check_path

KINDS = ("session_turn", "session_queue", "runtime_task", "external_task", "team_run", "supervised_run",
         "self_evolution_run", "research_run")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_FAILURES = {"failed", "error", "timed_out", "timeout", "incomplete", "budget_exhausted"}
_TERMINAL = _FAILURES | {"done", "completed", "succeeded", "success", "stopped", "cancelled", "canceled",
                       "closed", "dropped", "exited", "stale", "superseded", "archived", "settled"}
_ACTIVE = {"created", "queued", "sent", "running", "waiting_external", "stopping", "cancelling",
           "pausing", "pause_requested", "stop_unconfirmed"}
_ATTENTION = {"blocked", "reconciliation_required", "waiting", "waiting_human", "awaiting_approval"}
_ISSUES = {"terminal", "blocked", "attention_required", "no_progress", "read_failed", "coverage_unavailable", "control_settled"}
_FIELDS = ("runtimeKind", "resourceId", "sessionId", "teamId", "flowId")
_PAGE_SIZE = 3
_CALLS = 7  # A management lane may use four reads, inside the shared time budget.
_BUDGET = 4.0
_MAX_ROWS = 8192
_FRESH_FOR = 60.0
_STALL_AFTER = 2 * 3600
_BLOCK_AFTER = 5 * 60
_FAIL_AFTER = 2 * 60


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _reference(project, row):
    kind, rid = row.get("kind"), row.get("resourceId")
    if kind not in KINDS or not isinstance(rid, str) or not _ID.fullmatch(rid):
        raise ValueError("runtime_watch_reference_invalid")
    ref = {"projectId": project, "runtimeKind": kind, "resourceId": rid}
    for key in ("sessionId", "teamId", "flowId"):
        value = row.get(key) or ""
        if not isinstance(value, str) or value and not _ID.fullmatch(value):
            raise ValueError("runtime_watch_reference_invalid")
        ref[key] = value
    if ((kind in {"session_turn", "session_queue"} and not ref["sessionId"])
            or (kind in {"team_run", "research_run"} and not ref["teamId"])):
        raise ValueError("runtime_watch_reference_invalid")
    if kind == "research_run" and not ref["flowId"]:
        raise ValueError("runtime_watch_reference_invalid")
    return ref


def runtime_event(row):
    """Closed, canonical event representation shared with the delivery ledger."""
    if row.get("kind") != "platform_runtime" or row.get("issue") not in _ISSUES:
        return None
    if any(not isinstance(row.get(key), str) or not _ID.fullmatch(row[key])
           for key in ("projectId", "status")) or not isinstance(row.get("episode"), str) or not _HASH.fullmatch(row["episode"]):
        return None
    try:
        ref = _reference(row["projectId"], {**row, "kind": row.get("runtimeKind")})
    except ValueError:
        return None
    event = {"kind": "platform_runtime", **ref,
             **{key: row[key] for key in ("issue", "status", "episode")}}
    return {**event, "eventId": _digest(event)}


def _management_reference(project, row):
    from core.web.services.external_management.contracts import ACTION_MODELS
    action, request = row.get("action"), row.get("requestId")
    if (action not in ACTION_MODELS or action == "team_run" or action.startswith("authorization_")
            or not isinstance(request, str) or not _REQUEST_ID.fullmatch(request)):
        raise ValueError("management_watch_reference_invalid")
    return {"projectId": project, "action": action, "requestId": request}


def management_event(row):
    """An unresolved original request, without inventing a native object."""
    if (row.get("kind") != "management_request" or type(row.get("schemaVersion")) is not int or row["schemaVersion"] != 2
            or row.get("issue") != "requires_review" or row.get("status") != "unknown"
            or not isinstance(row.get("projectId"), str) or not _ID.fullmatch(row["projectId"])
            or not isinstance(row.get("episode"), str) or not _HASH.fullmatch(row["episode"])):
        return None
    try:
        ref = _management_reference(row["projectId"], row)
    except (ValueError, TypeError):
        return None
    event = {"schemaVersion": 2, "kind": "management_request", **ref,
             **{key: row[key] for key in ("issue", "status", "episode")}}
    return {**event, "eventId": _digest(event)}


class RuntimeWatchObserver:
    def __init__(self, dispatch, directory):
        self.dispatch = dispatch
        self._path = directory / "runtime-watch.json"
        self._lock = threading.RLock()
        self._fresh = {}
        self._pass_guards = {}
        self._pending_management = None
        self.status = {"state": "unknown"}
        if self._path.exists() or self._path.is_symlink():
            check_path(self._path)
            if self._path.stat().st_size > 8 * 1024 * 1024:
                raise RuntimeError("runtime_watch_state_invalid")
            self._state = json.loads(self._path.read_text(encoding="utf-8"))
            self._validate()
        else:
            self._state = {"schemaVersion": 1, "cursor": 0, "sources": {}, "rows": {}}
        self._persisted = None

    def _validate(self):
        state = self._state
        if (not isinstance(state, dict) or set(state) != {"schemaVersion", "cursor", "sources", "rows"}
                or state["schemaVersion"] != 1 or type(state["cursor"]) is not int or state["cursor"] < 0
                or any(not isinstance(state[key], dict) or len(state[key]) > _MAX_ROWS for key in ("sources", "rows"))):
            raise RuntimeError("runtime_watch_state_invalid")
        for category in ("sources", "rows"):
            for key, item in state[category].items():
                if not isinstance(item, dict) or not _HASH.fullmatch(key) or not isinstance(item.get("projectId"), str) or not _ID.fullmatch(item["projectId"]):
                    raise RuntimeError("runtime_watch_state_invalid")
                allowed = {"projectId", "runtimeKind", "binding", "offset", "snapshot", "failures", "failedAt", "coverage",
                           "ref", "status", "fingerprint", "changedAt", "lastSeen", "samples", "wasActive",
                           "scanSnapshot", "scanComplete", "scanFromZero"}
                if set(item) - allowed or not _HASH.fullmatch(item.get("binding", "")):
                    raise RuntimeError("runtime_watch_state_invalid")
                for field in ("failedAt", "changedAt", "lastSeen"):
                    if field in item and (type(item[field]) not in (int, float) or not math.isfinite(item[field])):
                        raise RuntimeError("runtime_watch_state_invalid")
                for field in ("offset", "failures", "samples"):
                    if field in item and (type(item[field]) is not int or item[field] < 0):
                        raise RuntimeError("runtime_watch_state_invalid")
                if item.get("runtimeKind") not in (*KINDS, "commands", "management_request"):
                    raise RuntimeError("runtime_watch_state_invalid")
                for field in ("snapshot", "fingerprint", "scanSnapshot"):
                    if field in item and not _HASH.fullmatch(item[field]):
                        raise RuntimeError("runtime_watch_state_invalid")
                if "ref" in item:
                    try:
                        ref = (_management_reference(item["projectId"], item["ref"])
                               if item["runtimeKind"] == "management_request" else
                               _reference(item["projectId"], {**item["ref"], "kind": item["runtimeKind"]}))
                    except (ValueError, TypeError):
                        raise RuntimeError("runtime_watch_state_invalid") from None
                    if ref != item["ref"]:
                        raise RuntimeError("runtime_watch_state_invalid")
                if "status" in item and (not isinstance(item["status"], str) or not _ID.fullmatch(item["status"])):
                    raise RuntimeError("runtime_watch_state_invalid")
                if "coverage" in item and item["coverage"] not in {"available", "partial", "unavailable", "unknown"}:
                    raise RuntimeError("runtime_watch_state_invalid")
                if "wasActive" in item and type(item["wasActive"]) is not bool:
                    raise RuntimeError("runtime_watch_state_invalid")
                if any(field in item and type(item[field]) is not bool for field in ("scanComplete", "scanFromZero")):
                    raise RuntimeError("runtime_watch_state_invalid")

    def _save(self):
        encoded = json.dumps(self._state, sort_keys=True)
        if encoded != self._persisted:
            atomic_write_json(self._path, self._state, strict_replace=True)
            self._persisted = encoded

    def _binding(self, project):
        binding = self.dispatch._project_read_binding(project)
        # Registry generation is process-local. Persist only the admitted root
        # identity so an ordinary host restart cannot create a new episode.
        return _digest(str(binding[1]))

    def _guard(self, project):
        binding = self.dispatch._project_read_binding(project)
        return _digest([binding[0], str(binding[1])])

    def _authorized(self):
        projects = {}
        for project in self.dispatch.project_ids():
            if not isinstance(project, str) or not _ID.fullmatch(project):
                continue
            try:
                projects[project] = self._binding(project)
            except Exception:
                continue
        return projects

    def _prune(self, projects):
        for category in ("sources", "rows"):
            self._state[category] = {key: item for key, item in self._state[category].items()
                if projects.get(item["projectId"]) == item["binding"]}
        self._fresh = {key: value for key, value in self._fresh.items()
                       if value[0]["projectId"] in projects and self.current(value[0])}

    def current(self, event):
        with self._lock:
            observed = self._fresh.get(event["eventId"])
            try:
                return bool(observed and observed[0] == event and time.monotonic() - observed[2] <= _FRESH_FOR
                            and self._guard(event["projectId"]) == observed[1])
            except Exception:
                return False

    def _event(self, ref, issue, status, episode, binding):
        event = runtime_event({"kind": "platform_runtime", **ref, "issue": issue,
                               "status": status, "episode": _digest(episode)})
        if event is None:
            raise ValueError("runtime_watch_event_invalid")
        self._fresh[event["eventId"]] = event, self._pass_guards[ref["projectId"]], time.monotonic()
        return event

    def _observe(self, project, row, binding, now):
        ref = _reference(project, row)
        status, revision = row.get("status"), row.get("revision")
        if not isinstance(status, str) or not _ID.fullmatch(status) or not isinstance(revision, str) or not 1 <= len(revision) <= 160:
            raise ValueError("runtime_watch_metadata_invalid")
        key = _digest(ref)
        progress = row.get("progressFingerprint")
        if progress is not None and (not isinstance(progress, str) or not _HASH.fullmatch(progress)):
            raise ValueError("runtime_watch_progress_invalid")
        # Control CAS versions and updatedAt can change on every heartbeat.
        # Without owner progress evidence only a status transition is progress.
        fingerprint = _digest([status, progress])
        previous = self._state["rows"].get(key)
        if previous is None and len(self._state["rows"]) >= _MAX_ROWS:
            raise ValueError("runtime_watch_capacity")
        changed = previous is None or previous["fingerprint"] != fingerprint
        for event_id, observation in list(self._fresh.items()):
            if all(observation[0].get(field) == ref.get(field) for field in ("projectId", *_FIELDS)):
                self._fresh.pop(event_id, None)
        terminal_unchanged = bool(previous and not changed and status in _TERMINAL)
        item = {"projectId": project, "runtimeKind": ref["runtimeKind"], "binding": binding,
                "ref": ref, "status": status, "fingerprint": fingerprint,
                "changedAt": now if changed and not terminal_unchanged else previous["changedAt"], "lastSeen": now,
                "samples": 1 if changed else previous["samples"] + 1,
                "wasActive": status in _ACTIVE or bool(previous and previous["wasActive"])}
        self._state["rows"][key] = item
        issue = None
        if status in _FAILURES or status in _TERMINAL and item["wasActive"]:
            issue = "terminal"
        elif status in _ATTENTION and item["samples"] >= 2 and now - item["changedAt"] >= _BLOCK_AFTER:
            issue = "attention_required"
        elif status in _ACTIVE and item["samples"] >= 3 and now - item["changedAt"] >= _STALL_AFTER:
            issue = "no_progress"
        return [] if issue is None else [self._event(ref, issue, status, [key, issue, item["changedAt"]], binding)]

    def _failure(self, source, now, *, coverage=False):
        source["failures"] = source.get("failures", 0) + 1
        source.setdefault("failedAt", now)
        if source["failures"] < 3 or now - source["failedAt"] < _FAIL_AFTER:
            return []
        kind = source["runtimeKind"]
        if kind == "commands":
            # A directory failure has no original request or runtime identity.
            # Keep coverage partial rather than manufacture a runtime task.
            return []
        ref = source.get("ref") or {"projectId": source["projectId"], "runtimeKind": kind, "resourceId": "source-coverage",
               "sessionId": "source-coverage" if kind in {"session_turn", "session_queue"} else "",
               "teamId": "source-coverage" if kind in {"team_run", "research_run"} else "",
               "flowId": "source-coverage" if kind == "research_run" else ""}
        issue = "coverage_unavailable" if coverage else "read_failed"
        return [self._event(ref, issue, "unavailable", [source["projectId"], source["runtimeKind"], issue,
                                                     ref["resourceId"], source["failedAt"]], source["binding"])]

    def _dispatch_errors(self, rows, projects, now):
        """A stale receipt with lastError cannot masquerade as a fresh terminal."""
        events = []
        for row in rows[:_MAX_ROWS]:
            if not isinstance(row, dict) or row.get("projectId") not in projects or row.get("stateInvalid"):
                continue
            project, task = row["projectId"], row.get("nativeTaskId")
            if not isinstance(task, str) or not _ID.fullmatch(task):
                continue
            key = _digest([project, "dispatch_read", task])
            if row.get("lastError") is None:
                self._state["sources"].pop(key, None)
                for event_id, observation in list(self._fresh.items()):
                    if (observation[0]["projectId"] == project and observation[0].get("resourceId") == task
                            and observation[0]["issue"] == "read_failed"):
                        self._fresh.pop(event_id, None)
                continue
            if not isinstance(row["lastError"], dict):
                continue
            if key not in self._state["sources"] and len(self._state["sources"]) >= _MAX_ROWS:
                continue
            source = self._state["sources"].setdefault(key, {"projectId": project, "runtimeKind": "external_task",
                "binding": projects[project], "ref": _reference(project, {"kind": "external_task", "resourceId": task}),
                "offset": 0, "coverage": "unknown", "failures": 0})
            events.extend(self._failure(source, now))
        return events

    async def _page(self, project, kind, source, now):
        query = {"kind": kind, "state": "all", "offset": source.get("offset", 0), "limit": _PAGE_SIZE}
        if query["offset"] and source.get("snapshot"):
            query["expected_snapshot"] = source["snapshot"]
        page = await self.dispatch.management.runtime(project, "list", **query)
        if self._guard(project) != self._pass_guards[project]:
            raise ValueError("runtime_watch_binding_changed")
        if (not isinstance(page, dict) or page.get("projectId") != project or page.get("offset") != query["offset"]
                or type(page.get("total")) is not int or page["total"] < query["offset"]
                or not isinstance(page.get("operations"), list) or len(page["operations"]) > _PAGE_SIZE
                or not isinstance(page.get("snapshot"), str) or not _HASH.fullmatch(page["snapshot"])):
            raise ValueError("runtime_watch_page_invalid")
        coverage = page.get("coverage")
        if (not isinstance(coverage, list) or len(coverage) != 1 or not isinstance(coverage[0], dict)
                or coverage[0].get("source") != kind or coverage[0].get("state") not in {"available", "partial", "unavailable"}
                or type(coverage[0].get("complete")) is not bool
                or coverage[0]["complete"] != (coverage[0]["state"] == "available")
                or page.get("complete") is not coverage[0]["complete"]):
            raise ValueError("runtime_watch_coverage_invalid")
        end, following = query["offset"] + len(page["operations"]), page.get("nextOffset")
        if (following is not None and (type(following) is not int or following != end or not query["offset"] < following < page["total"])
                or following is None and end != page["total"] or end > page["total"]):
            raise ValueError("runtime_watch_page_invalid")
        if query["offset"] and source.get("snapshot") and page["snapshot"] != source["snapshot"]:
            raise ValueError("runtime_watch_snapshot_changed")
        events, seen = [], set()
        for row in page["operations"]:
            if not isinstance(row, dict) or row.get("kind") != kind or row.get("resourceId") in seen:
                raise ValueError("runtime_watch_page_invalid")
            seen.add(row["resourceId"])
            events.extend(self._observe(project, row, source["binding"], now))
        source["offset"], source["snapshot"] = following or 0, page["snapshot"]
        if query["offset"] == 0:
            source["scanFromZero"], source["scanSnapshot"] = True, page["snapshot"]
        elif not query.get("expected_snapshot"):
            source["scanFromZero"] = False
        source["scanComplete"] = (following is None and source.get("scanFromZero") is True
                                   and source.get("scanSnapshot") == page["snapshot"])
        source["coverage"] = coverage[0]["state"]
        source["lastSeen"] = now
        if coverage[0]["complete"] is True and coverage[0]["state"] == "available" and page.get("complete") is True:
            source.pop("failedAt", None)
            source["failures"] = 0
            for event_id, observation in list(self._fresh.items()):
                if (observation[0]["projectId"] == project and observation[0].get("runtimeKind") == kind
                        and observation[0].get("resourceId") == "source-coverage"
                        and observation[0]["issue"] in {"read_failed", "coverage_unavailable"}):
                    self._fresh.pop(event_id, None)
        else:
            events.extend(self._failure(source, now, coverage=True))
        return events

    def _clear_management_event(self, ref):
        for event_id, observation in list(self._fresh.items()):
            if observation[0].get("kind") == "management_request" and all(
                    observation[0].get(field) == value for field, value in ref.items()):
                self._fresh.pop(event_id, None)

    def _management_issue(self, item):
        # One unresolved episode covers both missing proof and sustained read
        # failure. Changing read availability must not generate repeated wakes.
        event = management_event({"schemaVersion": 2, "kind": "management_request", **item["ref"],
            "issue": "requires_review", "status": "unknown", "episode": _digest([item["ref"], item["changedAt"]])})
        self._fresh[event["eventId"]] = event, self._pass_guards[item["projectId"]], time.monotonic()
        return [event]

    def _management_failure(self, item, now):
        item["failures"] = item.get("failures", 0) + 1
        item.setdefault("failedAt", now)
        item["lastSeen"] = now
        if item.get("status") != "requires_review" and (item["failures"] < 3 or now - item["failedAt"] < _FAIL_AFTER):
            return []
        item["status"] = "requires_review"
        return self._management_issue(item)

    async def _request_receipt(self, project, ref):
        receipt = await self.dispatch.management.receipt(project, action=ref["action"], request_id=ref["requestId"])
        if (self._guard(project) != self._pass_guards[project] or not isinstance(receipt, dict)
                or any(receipt.get(key) != value for key, value in ref.items())
                or receipt.get("status") not in {"completed", "unknown"}
                or receipt.get("verified") is not (receipt["status"] == "completed")):
            raise ValueError("management_watch_receipt_invalid")
        return receipt

    async def _request(self, project, ref, item, now):
        receipt = await self._request_receipt(project, ref)
        if receipt["status"] == "unknown":
            from core.web.services.external_management.reconciliation_contracts import ReconciliationResponse
            result = await self.dispatch.management.reconciliation(project, action=ref["action"], request_id=ref["requestId"])
            if (self._guard(project) != self._pass_guards[project] or not isinstance(result, dict)
                    or any(result.get(key) != value for key, value in ref.items())):
                raise ValueError("management_watch_reconciliation_invalid")
            proof = ReconciliationResponse.model_validate({key: value for key, value in result.items() if key != "projectId"})
            if proof.state == "requires_review":
                item["status"], item["lastSeen"], item["failures"] = "requires_review", now, 0
                item.pop("failedAt", None)
                return self._management_issue(item)
            if proof.state == "unavailable":
                return self._management_failure(item, now)
            # Reconciliation metadata is no business result. Read the original
            # authoritative receipt again, including any runtime control target.
            receipt = await self._request_receipt(project, ref)
            if receipt["status"] != "completed":
                return self._management_failure(item, now)
        events = (await self._control_target(project, ref["requestId"], receipt, item, now)
                  if ref["action"] == "runtime_command" else [])
        self._clear_management_event(ref)
        item["status"], item["lastSeen"], item["failures"] = "confirmed", now, 0
        item.pop("failedAt", None)
        return events

    async def _control_target(self, project, request_id, receipt, item, now):
        """A native command ACK is never the actual target's settlement."""
        result = receipt.get("operation")
        if not isinstance(result, dict) or not isinstance(result.get("operation"), dict):
            raise ValueError("runtime_watch_command_unconfirmed")
        ref = _reference(project, result["operation"])
        command = result.get("command")
        if command not in {"stop", "pause", "resume", "confirm", "retry"}:
            raise ValueError("runtime_watch_command_unconfirmed")
        # Queue withdrawal is an atomic deletion with an exact native ACK.
        # Its disappearance on a later read is not additional completion proof.
        if ref["runtimeKind"] == "session_queue":
            if (command != "stop" or result.get("accepted") is not True
                    or result.get("revisionCheck") != "native_cas" or result.get("stopRequested") is not False
                    or result["operation"].get("status") != "cancelled"):
                raise ValueError("runtime_watch_command_unconfirmed")
            return [self._event(ref, "control_settled", "cancelled", [request_id, command], item["binding"])]
        refs = {key: ref[field] for key, field in (("session_id", "sessionId"), ("team_id", "teamId"), ("flow_id", "flowId"))
                if ref[field] and (ref["runtimeKind"] in {"team_run", "research_run"} and field in {"teamId", "flowId"}
                                  or ref["runtimeKind"] in {"session_turn", "session_queue"} and field == "sessionId")}
        detail = await self.dispatch.management.runtime(project, "get", kind=ref["runtimeKind"], resource_id=ref["resourceId"], **refs)
        if (not isinstance(detail, dict) or detail.get("projectId") != project or not isinstance(detail.get("operation"), dict)
                or _reference(project, detail["operation"]) != ref or self._guard(project) != self._pass_guards[project]):
            raise ValueError("runtime_watch_command_target_changed")
        events = self._observe(project, detail["operation"], item["binding"], now)
        status = detail["operation"].get("status")
        settled = (status in _TERMINAL if command == "stop" else status == "paused" if command == "pause"
                   else status in {"running", "queued"} if command == "resume" else False)
        if settled:
            events.append(self._event(ref, "control_settled", status, [request_id, command], item["binding"]))
        return events

    async def _commands(self, project, source, now):
        """Fairly inspect recorded refs; never invoke or replay a mutation."""
        from core.web.services.external_management.contracts import ACTION_MODELS
        offset = source.get("offset", 0)
        page = self.dispatch.management.list_requests(project_id=project, action="", offset=offset, limit=1)
        if (self._guard(project) != self._pass_guards[project] or not isinstance(page, dict)
                or page.get("offset") != offset or not isinstance(page.get("requests"), list)
                or len(page["requests"]) > 1 or type(page.get("total")) is not int or page["total"] < offset):
            source["offset"] = 0
            raise ValueError("runtime_watch_commands_invalid")
        end, following = offset + len(page["requests"]), page.get("nextOffset")
        if following is not None and (type(following) is not int or following != end or not offset < following < page["total"]):
            raise ValueError("runtime_watch_commands_invalid")
        if following is None and end != page["total"]:
            raise ValueError("runtime_watch_commands_invalid")
        # Advance before any target read: one unreadable request cannot keep
        # later references out of the lane, including across host restarts.
        source["offset"] = following or 0
        events = []
        for row in page["requests"]:
            if (not isinstance(row, dict) or set(row) != {"projectId", "action", "requestId"}
                    or row.get("projectId") != project or row.get("action") not in ACTION_MODELS
                    or not isinstance(row.get("requestId"), str) or not _REQUEST_ID.fullmatch(row["requestId"])):
                raise ValueError("runtime_watch_commands_invalid")
            if row["action"] == "team_run" or row["action"].startswith("authorization_"):
                continue
            ref = _management_reference(project, row)
            key = _digest(["management_request", ref])
            if key not in self._state["rows"] and len(self._state["rows"]) >= _MAX_ROWS:
                raise ValueError("runtime_watch_capacity")
            item = self._state["rows"].setdefault(key, {"projectId": project, "runtimeKind": "management_request",
                "binding": source["binding"], "ref": ref, "status": "observing", "changedAt": now, "failures": 0})
            if item["status"] == "confirmed" and ref["action"] != "runtime_command":
                continue
            self._pending_management = item
            try:
                events.extend(await self._request(project, ref, item, now))
            except Exception:
                events.extend(self._management_failure(item, now))
            self._pending_management = None
        source.pop("failedAt", None)
        source["failures"] = 0
        source["coverage"] = "available" if page.get("status", "ok") == "ok" else "partial"
        source["lastSeen"] = now
        return events

    async def refresh(self, *, now=None, dispatch_rows=()):
        observed = time.time() if now is None else float(now)
        if not callable(getattr(getattr(self.dispatch, "management", None), "runtime", None)) or not callable(getattr(self.dispatch, "project_ids", None)):
            self.status = {"state": "unavailable"}
            return []
        projects = self._authorized()
        self._pass_guards = {}
        for project in list(projects):
            try:
                self._pass_guards[project] = self._guard(project)
            except Exception:
                projects.pop(project)
        with self._lock:
            self._prune(projects)
        lanes = [(project, kind) for project in sorted(projects) for kind in (*KINDS, "commands")]
        if not lanes:
            self._save()
            self.status = {"state": "ready", "authorizedProjects": 0}
            return []
        start = self._state["cursor"] % len(lanes)
        lanes = (lanes[start:] + lanes[:start])[:_CALLS]
        events, attempted = self._dispatch_errors(list(dispatch_rows), projects, observed), 0
        source = None
        with anyio.move_on_after(_BUDGET) as budget:
            for project, kind in lanes:
                attempted += 1
                self._pending_management = None
                source_key = _digest([project, kind])
                source = self._state["sources"].setdefault(source_key, {"projectId": project, "runtimeKind": kind,
                    "binding": projects[project], "offset": 0, "failures": 0, "coverage": "unknown"})
                try:
                    events.extend(await (self._commands(project, source, observed) if kind == "commands"
                                         else self._page(project, kind, source, observed)))
                except Exception as error:
                    source.pop("snapshot", None)
                    source["coverage"] = "unknown"
                    source["scanFromZero"], source["scanComplete"] = False, False
                    # A moving snapshot is ordinary progress, not a failing source.
                    if getattr(error, "code", None) != "RUNTIME_SNAPSHOT_CHANGED":
                        if kind != "commands":
                            source["offset"] = 0
                        events.extend(self._failure(source, observed))
        if budget.cancel_called and source is not None:
            source["coverage"] = "unknown"
            source["scanFromZero"], source["scanComplete"] = False, False
            events.extend(self._failure(source, observed))
            if self._pending_management is not None:
                events.extend(self._management_failure(self._pending_management, observed))
        self._pending_management = None
        self._state["cursor"] += attempted
        with self._lock:
            current = self._authorized()
            self._prune(current)
            events = [event for event in events if current.get(event["projectId"]) == projects[event["projectId"]]
                      and self.current(event)]
            self._save()
            sources = [item for item in self._state["sources"].values() if item["runtimeKind"] != "commands" and "ref" not in item]
            complete = len(sources) == len(current) * len(KINDS) and all(
                item["coverage"] == "available" and item.get("scanComplete") is True
                and observed - item.get("lastSeen", 0) <= _FRESH_FOR for item in sources)
            management_sources = [item for item in self._state["sources"].values() if item["runtimeKind"] == "commands"]
            complete = complete and len(management_sources) == len(current) and all(
                item["coverage"] == "available" and observed - item.get("lastSeen", 0) <= _FRESH_FOR
                for item in management_sources)
            self.status = {"state": "ready" if complete else "partial", "authorizedProjects": len(current),
                           "sourcesObserved": len(sources), "sourcesExpected": len(current) * len(KINDS)}
        return events
