"""Launcher-only receipt wakeups, using the native proactive Session owner.

The ledger is an idempotency/attempt record, not a transcript. An uncertain
submission is never retried, even after restart. The host owns one instance
and calls ``inspect`` after its ordinary dispatch heartbeat.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from core.external_agent.contracts import TASK_ACTIVE_STATUSES, TASK_TERMINAL_STATUSES
from core.infrastructure.atomic_io import atomic_write_json
from .migration_io import check_path, pinned_target_directory

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_DISPATCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}\Z")
_TOKEN = re.compile(r"[a-f0-9]{64}\Z")
_INTERVAL = 15 * 60
_HOUR = 3600
_MAX_PER_HOUR = 2
_MAX_ENTRIES = 4096
_RECHECK_INTERVAL = 60.0
_RECHECK_BATCH = 16
_OWNER = None
_OWNER_LOCK = threading.RLock()


def _event(row: dict[str, Any]) -> dict[str, str] | None:
    receipt = row.get("receipt")
    if row.get("stateInvalid") or row.get("lastError") is not None or not isinstance(receipt, dict):
        return None
    project, dispatch, task, status = (row.get("projectId"), row.get("dispatchId"),
                                      row.get("nativeTaskId"), receipt.get("status"))
    if (not isinstance(project, str) or not _ID.fullmatch(project)
            or not isinstance(dispatch, str) or not _DISPATCH.fullmatch(dispatch)
            or not isinstance(task, str) or not _ID.fullmatch(task)
            or task != receipt.get("taskId") or status not in TASK_TERMINAL_STATUSES):
        return None
    event = {"projectId": project, "dispatchId": dispatch, "nativeTaskId": task, "status": status}
    encoded = json.dumps(event, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    event["eventId"] = hashlib.sha256(encoded.encode()).hexdigest()
    return event


class LauncherPatrol:
    """One per native host. All writes are private to the Launcher profile."""

    def __init__(self, root: Path, agent_id: str, session_id: str, dispatch):
        from core.infrastructure.native_runtime import assistant_native_root, is_launcher_assistant_process
        from . import native

        if (not is_launcher_assistant_process() or Path(root).resolve() != assistant_native_root()
                or not native._STARTED or native._OFFLINE_MIGRATION
                or (agent_id, session_id) != (native._AGENT_ID, native._SESSION_ID)):
            raise RuntimeError("patrol_identity_invalid")
        self.root, self.agent_id, self.session_id, self.dispatch = Path(root), agent_id, session_id, dispatch
        self._lock, self._stack = threading.RLock(), ExitStack()
        self._active: set[str] = set()
        self._submitting: set[str] = set()
        self._persisted: dict[int, str] = {}
        self._recheck_after: dict[str, float] = {}
        directory = self.root / "assistant_patrol"
        fresh = not directory.exists() and not directory.is_symlink()
        try:
            self._stack.enter_context(pinned_target_directory(directory, create=fresh))
            self._path = directory / "deliveries.json"
            if fresh:
                self._state = {"schemaVersion": 1, "agentId": agent_id, "sessionId": session_id, "entries": []}
                self._save()
            else:
                paths = [self._path, *sorted(directory.glob("deliveries.[0-9]*.json"))]
                all_entries = []
                for index, path in enumerate(paths):
                    if path != self._segment_path(index):
                        raise RuntimeError("patrol_state_invalid")
                    check_path(path)
                    if path.stat().st_size > 4 * 1024 * 1024:
                        raise RuntimeError("patrol_state_invalid")
                    segment = json.loads(path.read_text(encoding="utf-8"))
                    if (not isinstance(segment, dict) or segment.get("schemaVersion") != 1
                            or segment.get("agentId") != agent_id or segment.get("sessionId") != session_id
                            or set(segment) != {"schemaVersion", "agentId", "sessionId", "entries"}
                            or not isinstance(segment.get("entries"), list)
                            or len(segment["entries"]) > _MAX_ENTRIES
                            or index < len(paths) - 1 and len(segment["entries"]) != _MAX_ENTRIES):
                        raise RuntimeError("patrol_state_invalid")
                    all_entries.extend(segment["entries"])
                    self._persisted[index] = self._encoded(segment)
                self._state = {"schemaVersion": 1, "agentId": agent_id, "sessionId": session_id, "entries": all_entries}
                self._validate()
            global _OWNER
            with _OWNER_LOCK:
                if _OWNER is not None:
                    raise RuntimeError("patrol_owner_exists")
                _OWNER = self
        except BaseException:
            self._stack.close()
            raise

    def _validate(self):
        state = self._state
        if (not isinstance(state, dict) or set(state) != {"schemaVersion", "agentId", "sessionId", "entries"}
                or state["schemaVersion"] != 1 or state["agentId"] != self.agent_id
                or state["sessionId"] != self.session_id or not isinstance(state["entries"], list)):
            raise RuntimeError("patrol_state_invalid")
        seen_events, seen_tokens = set(), set()
        for item in state["entries"]:
            if (not isinstance(item, dict) or not {"event", "token", "state", "createdAt"}.issubset(item)
                    or set(item) - {"event", "token", "state", "createdAt", "attempts", "cancelProof", "priorTurnId"}
                    or not isinstance(item["event"], dict) or not isinstance(item["token"], str)
                    or not _TOKEN.fullmatch(item["token"])
                    or item["state"] not in {"reserved", "accepted", "completed", "cancelled", "unknown", "observed",
                                             "cancelled_pre_admission", "failed", "interrupted"}
                    or type(item["createdAt"]) not in (float, int) or not math.isfinite(item["createdAt"])):
                raise RuntimeError("patrol_state_invalid")
            attempts = item.get("attempts", [item["createdAt"]])
            if (not isinstance(attempts, list) or not attempts or len(attempts) > 1000
                    or any(type(stamp) not in (int, float) or not math.isfinite(stamp) for stamp in attempts)):
                raise RuntimeError("patrol_state_invalid")
            if item["state"] == "cancelled_pre_admission" and (
                    item.get("cancelProof") not in {"not_submitted", "context_cancelled"}
                    or not isinstance(item.get("priorTurnId"), str)
                    or item["cancelProof"] == "context_cancelled" and not item["priorTurnId"]):
                raise RuntimeError("patrol_state_invalid")
            event = item["event"]
            rebuilt = _event({**event, "receipt": {"taskId": event.get("nativeTaskId"), "status": event.get("status")}})
            if rebuilt != event or event["eventId"] in seen_events or item["token"] in seen_tokens:
                raise RuntimeError("patrol_state_invalid")
            seen_events.add(event["eventId"]); seen_tokens.add(item["token"])

    def _segment_path(self, index):
        return self._path if index == 0 else self._path.parent / f"deliveries.{index:08d}.json"

    @staticmethod
    def _encoded(value):
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)

    def _save(self):
        # A failed atomic write has an uncertain outcome; this owner must not
        # attempt another delivery until restarted and the ledger re-read.
        try:
            entries = self._state["entries"]
            for index, start in enumerate(range(0, max(1, len(entries)), _MAX_ENTRIES)):
                segment = {**self._state, "entries": entries[start:start + _MAX_ENTRIES]}
                encoded = self._encoded(segment)
                if self._persisted.get(index) != encoded:
                    atomic_write_json(self._segment_path(index), segment, sort_keys=True, indent=2, strict_replace=True)
                    self._persisted[index] = encoded
        except Exception:
            self._broken = True
            raise

    def _entry(self, token):
        return next((item for item in self._state["entries"] if item["token"] == token), None)

    def _eligible(self, event):
        from . import native
        from core.infrastructure.native_runtime import is_launcher_assistant_process
        from core.web.services.session.queued_turns import session_queue_hold_active
        if (not is_launcher_assistant_process() or not native._STARTED or native._OFFLINE_MIGRATION
                or native._STOP_REQUESTED.is_set() or native._QUIESCING
                or (native._AGENT_ID, native._SESSION_ID) != (self.agent_id, self.session_id)
                or session_queue_hold_active(self.session_id)):
            return False
        try:
            assistant = native._projection().get("assistant") or {}
            if (assistant.get("agentId"), assistant.get("directSessionId")) != (self.agent_id, self.session_id):
                return False
            with self.dispatch._dispatch_state:
                self.dispatch._check_dispatch_unfenced()
                if event["projectId"] not in self.dispatch._admitted_projects():
                    return False
                return any(_event(row) == event for row in self.dispatch.list_dispatches(event["projectId"]))
        except Exception:
            return False

    def current(self, agent_id, revision, token):
        from core.web.services.personal_assistant_patrol_service import is_pa_patrol_enabled, is_pa_patrol_wake_enabled
        with self._lock:
            item = self._entry(token)
            return bool(is_pa_patrol_enabled() and is_pa_patrol_wake_enabled()
                        and not getattr(self, "_broken", False) and agent_id == self.agent_id
                        and revision == 1 and token in self._active and item
                        and item["state"] in {"reserved", "accepted"} and self._eligible(item["event"]))

    async def refresh_stale_terminals(self, rows, *, now=None):
        """Re-read error-marked terminal tasks through their authorized native owner.

        This does not turn a stale snapshot into evidence: the SDK read must
        succeed and persist a matching task receipt, after which the host must
        pass a fresh ``list_dispatches()`` to ``inspect``. The original task is
        never recreated. Failed reads remain marked and are retried later.
        """
        from core.web.services.personal_assistant_patrol_service import is_pa_patrol_enabled, is_pa_patrol_wake_enabled

        if not is_pa_patrol_enabled() or not is_pa_patrol_wake_enabled():
            return {"attempted": 0}
        observed = time.monotonic() if now is None else float(now)
        with self._lock:
            if getattr(self, "_broken", False):
                raise RuntimeError("patrol_state_unknown")
            self._recheck_after = {key: deadline for key, deadline in self._recheck_after.items()
                                   if deadline > observed}
            known = {item["event"]["eventId"]: item for item in self._state["entries"]}
            ids = []
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("lastError"), dict):
                    continue
                event = _event({**row, "lastError": None})
                if event is None:
                    continue
                item = known.get(event["eventId"])
                if item is not None and item["state"] != "cancelled_pre_admission":
                    continue
                dispatch_id = event["dispatchId"]
                if dispatch_id in ids or observed < self._recheck_after.get(dispatch_id, 0.0):
                    continue
                ids.append(dispatch_id)
                if len(ids) >= _RECHECK_BATCH:
                    break
            if not ids:
                return {"attempted": 0}
            # Throttle failed, unauthorized and uncertain reads alike. A
            # later pass can retry; no stale receipt is treated as fresh.
            for dispatch_id in ids:
                self._recheck_after[dispatch_id] = observed + _RECHECK_INTERVAL
        async with self.dispatch._dispatch_admission:
            self.dispatch._check_dispatch_unfenced()
            with self.dispatch._dispatch_state:
                self.dispatch._admitted_projects()
                generation = self.dispatch._registry_gate_generation
            await self.dispatch._refresh_batch(ids, include_terminal=True,
                                               terminal_registry_generation=generation)
        return {"attempted": len(ids)}

    def inspect(self, rows, *, now=None):
        """Inspect current native snapshots, attempting at most one receipt wake."""
        from . import native
        from core.web.services.personal_assistant_patrol_service import is_pa_patrol_enabled, is_pa_patrol_wake_enabled
        from core.web.services.session.proactive import submit_session_proactive_turn

        observed = time.time() if now is None else float(now)
        events = [event for row in rows if isinstance(row, dict) and (event := _event(row))]
        summary = {"active": sum(1 for row in rows if isinstance(row, dict)
                         and isinstance(row.get("receipt"), dict)
                         and row["receipt"].get("status") in TASK_ACTIVE_STATUSES),
                   "terminal": len(events), "wake": "none"}
        summary["deliveryStates"] = self.reconcile()
        if not is_pa_patrol_enabled() or not is_pa_patrol_wake_enabled():
            return summary
        with self._lock:
            if getattr(self, "_broken", False):
                raise RuntimeError("patrol_state_unknown")
            known = {item["event"]["eventId"]: item for item in self._state["entries"]}
            eligible = [event for event in events if (event["eventId"] not in known
                        or known[event["eventId"]]["state"] == "cancelled_pre_admission")
                        and self._eligible(event)]
            recent = [stamp for item in self._state["entries"]
                      for stamp in item.get("attempts", [item["createdAt"]])
                      if stamp > observed - _HOUR]
            if not eligible or (recent and observed - max(recent) < _INTERVAL) or len(recent) >= _MAX_PER_HOUR:
                return summary
            event = eligible[0]
            item = known.get(event["eventId"])
            if item is not None:
                # Reconcile has proved the old context released and no turn
                # entered the Journal; preserve its original delivery token.
                if item["token"] in self._active or not self._pre_admission_released(item):
                    return summary
                item["attempts"] = [stamp for stamp in item.get("attempts", [item["createdAt"]])
                                    if stamp > observed - _HOUR] + [observed]
                item["state"] = "reserved"
                item.pop("cancelProof", None)
                item.pop("priorTurnId", None)
                token = item["token"]
            else:
                token = secrets.token_hex(32)
                item = {"event": event, "token": token, "state": "reserved", "createdAt": observed,
                        "attempts": [observed]}
                self._state["entries"].append(item)
            self._save()  # Commit before any native scheduling.
            self._active.add(token)
            self._submitting.add(token)
        attempted = False
        precheck_refused = False
        try:
            with native._session_command() as (_, sid):
                if sid != self.session_id or not self.current(self.agent_id, 1, token):
                    raise RuntimeError("patrol_binding_changed")
                attempted = True
                try:
                    result = submit_session_proactive_turn(session_id=sid, agent_id=self.agent_id,
                        origin="proactive_plugin", source_kind="personal-assistant-dialogue",
                        plugin_id="personal-assistant-dialogue", trigger_id=event["eventId"],
                        delivery_token=token, binding_revision=1,
                        trigger={"deliveryKind": "launcher_dispatch_receipt"})
                except Exception as error:
                    # The native facade wraps SessionValidationError on exit,
                    # so capture this proof before leaving its context.
                    precheck_refused = self._native_precheck_refused(error, token)
                    raise
            with self._lock:
                if result.get("accepted") is not True:
                    raise RuntimeError("patrol_submission_unknown")
                if item["state"] == "reserved":
                    item["state"] = "accepted"
                    self._save()
            summary["wake"] = "accepted"
        except Exception:
            with self._lock:
                self._active.discard(token)
                if getattr(self, "_broken", False):
                    raise RuntimeError("patrol_state_unknown") from None
                if item["state"] in {"reserved", "accepted"}:
                    item["state"] = "cancelled_pre_admission" if not attempted or precheck_refused else "unknown"
                    if item["state"] == "cancelled_pre_admission":
                        item.update(cancelProof="not_submitted", priorTurnId="")
                    self._save()
            summary["wake"] = "deferred" if item["state"] == "cancelled_pre_admission" else "unknown"
        finally:
            with self._lock:
                self._submitting.discard(token)
        return summary

    def _native_precheck_refused(self, error, token):
        """Recognize only the native guard that runs before context creation."""
        from core.web.services import session_service as sessions
        from core.web.services.session import proactive
        from core.web.services.session.journal_bridge import load_session_conversation_events_cached
        if (not isinstance(error, sessions.SessionValidationError)
                or error.args != ("The proactive trigger is stale or no longer authorized.",)):
            return False
        tb = error.__traceback__
        while tb is not None and tb.tb_next is not None:
            tb = tb.tb_next
        if tb is None or tb.tb_frame.f_code is not proactive.submit_session_proactive_turn.__code__:
            return False
        with proactive._PROACTIVE_CONTEXTS_LOCK:
            if token in proactive._PROACTIVE_CONTEXTS:
                return False
        try:
            events = load_session_conversation_events_cached(self.session_id, project_root=self.root)
        except Exception:
            return False
        return not any(getattr(event, "correlation_id", "") == token for event in events)

    def finish(self, context, *, cancelled=False):
        metadata = context.get("proactive_plugin") or {}
        token = metadata.get("deliveryToken")
        with self._lock:
            item = self._entry(token)
            if (not item or token not in self._active or context.get("origin") != "proactive_plugin"
                    or context.get("agent_id") != self.agent_id or context.get("session_id") != self.session_id
                    or metadata.get("pluginId") != "personal-assistant-dialogue"
                    or metadata.get("sourceKind") != "personal-assistant-dialogue"
                    or metadata.get("triggerId") != item["event"]["eventId"]):
                return None
            item["state"] = self._journal_state(item)
            self._active.discard(token)
            self._save()
            return {"state": item["state"]}

    def cancel(self, agent_id, token):
        from core.web.services.session import proactive
        with self._lock:
            if agent_id == self.agent_id and token in self._active:
                item = self._entry(token)
                if item is not None:
                    with proactive._PROACTIVE_CONTEXTS_LOCK:
                        context = proactive._PROACTIVE_CONTEXTS.get(token)
                        # This callback runs before native releases the context.
                        # A missing or admitted context is not proof of no turn.
                        prior_turn = str(context.get("turn_id") or "") if isinstance(context, dict) else ""
                        pre_admission = bool(prior_turn and context.get("_proactive_admitted") is False)
                    item["state"] = "cancelled_pre_admission" if pre_admission else "unknown"
                    if pre_admission:
                        item.update(cancelProof="context_cancelled", priorTurnId=prior_turn)
                    self._active.discard(token)
                    self._save()

    def _journal_state(self, item, events=None):
        from core.web.services.session.journal_bridge import load_session_conversation_events_cached
        if events is None:
            events = load_session_conversation_events_cached(self.session_id, project_root=self.root)
        token, expected = item["token"], item["event"]["eventId"]
        starts = [e for e in events if getattr(e, "event_type", "") == "turn_started"
                  and getattr(e, "correlation_id", "") == token]
        triggers = [e for e in events if getattr(e, "event_type", "") == "internal_turn_trigger"
                    and getattr(e, "correlation_id", "") == token]
        if not starts and not triggers:
            return "cancelled_pre_admission" if item["state"] == "cancelled_pre_admission" else "unknown"
        if len(starts) != 1 or len(triggers) != 1:
            return "unknown"
        turn = getattr(starts[0], "turn_id", "")
        trigger = triggers[0]
        payload = getattr(trigger, "payload", {})
        start_payload = getattr(starts[0], "payload", {})
        if (not turn or getattr(trigger, "turn_id", "") != turn or not isinstance(payload, dict)
                or not isinstance(start_payload, dict) or start_payload.get("agentId") != self.agent_id
                or start_payload.get("pluginId") != "personal-assistant-dialogue"
                or getattr(starts[0], "source_kind", "") != "personal-assistant-dialogue"
                or getattr(trigger, "source_kind", "") != "personal-assistant-dialogue"
                or payload.get("agentId") != self.agent_id or payload.get("bindingRevision") != 1
                or payload.get("deliveryKind") != "launcher_dispatch_receipt"
                or payload.get("pluginId") != "personal-assistant-dialogue"
                or payload.get("triggerId") != expected or payload.get("deliveryToken") != token):
            return "unknown"
        turn_events = [e for e in events if getattr(e, "turn_id", "") == turn]
        terminal = [e for e in turn_events if getattr(e, "event_type", "")
                    in {"turn_completed", "turn_failed", "turn_interrupted"}]
        if not terminal:
            return "observed"
        if len(terminal) != 1:
            return "unknown"
        kind = terminal[0].event_type
        if kind == "turn_failed":
            return "failed"
        if kind == "turn_interrupted":
            return "interrupted"
        visible = any(getattr(e, "visible_in_model", False) and (
            e.event_type == "assistant_message" and str(e.payload.get("content") or "").strip()
            or e.event_type == "assistant_item_committed" and e.payload.get("kind") == "assistant_message"
            and e.payload.get("channel") == "answer" and e.payload.get("phase") == "final_answer"
            and str(e.payload.get("text") or "").strip()) for e in turn_events)
        return "completed" if visible else "unknown"

    @staticmethod
    def _pre_admission_released(item):
        from core.web.services.session import proactive
        with proactive._PROACTIVE_CONTEXTS_LOCK:
            if item["token"] in proactive._PROACTIVE_CONTEXTS:
                return False
        if item["state"] != "cancelled_pre_admission":
            return True
        if item.get("cancelProof") == "not_submitted":
            return True
        turn = item.get("priorTurnId")
        if item.get("cancelProof") != "context_cancelled" or not turn:
            return False
        # Native releases the proactive registry just before releasing its
        # scheduler slot. Check both, under the scheduler's own condition.
        from core.web.services import session_service as sessions
        scheduler = sessions._SESSION_TURN_SCHEDULER
        with scheduler._condition:
            if turn in scheduler._active_turn_ids_by_session.values():
                return False
            return not any(context.get("turn_id") == turn for queue in scheduler._queues.values() for context in queue)

    def reconcile(self):
        """Classify the original turn from Journal; never replay uncertain work."""
        from core.web.services.session.journal_bridge import load_session_conversation_events_cached
        with self._lock:
            journal = None
            changed = False
            for item in self._state["entries"]:
                if item["state"] not in {"reserved", "accepted", "unknown", "observed", "cancelled_pre_admission"}:
                    continue
                token = item["token"]
                if token in self._submitting or not self._pre_admission_released(item):
                    continue
                self._active.discard(token)
                if journal is None:
                    journal = load_session_conversation_events_cached(self.session_id, project_root=self.root)
                state = self._journal_state(item, journal)
                if state != item["state"]:
                    item["state"] = state
                    changed = True
            if changed:
                self._save()
            return {state: sum(item["state"] == state for item in self._state["entries"])
                    for state in ("unknown", "observed", "failed", "interrupted", "completed", "cancelled_pre_admission")}

    def prompt(self, agent_id, session_id, run_id):
        from core.web.services.session import proactive
        with proactive._PROACTIVE_CONTEXTS_LOCK:
            contexts = list(proactive._PROACTIVE_CONTEXTS.values())
        for context in contexts:
            metadata = context.get("proactive_plugin") or {}
            token = metadata.get("deliveryToken")
            if (context.get("turn_id") == run_id and context.get("session_id") == session_id
                    and context.get("origin") == "proactive_plugin"
                    and metadata.get("pluginId") == "personal-assistant-dialogue"
                    and metadata.get("sourceKind") == "personal-assistant-dialogue"
                    and self.current(agent_id, metadata.get("bindingRevision"), token)
                    and metadata.get("triggerId") == self._entry(token)["event"]["eventId"]):
                event = self._entry(token)["event"]
                return ("收到 Launcher 派遣的原生终态回执。请查询原 dispatch_id 的回执并向用户简要汇总；"
                        "原生状态不等于业务目标完成，不要重派或擅自执行控制操作。\n"
                        f"project_id={event['projectId']} dispatch_id={event['dispatchId']} status={event['status']}")
        return ""

    def close(self):
        global _OWNER
        with _OWNER_LOCK:
            if _OWNER is self:
                _OWNER = None
        self._stack.close()


def owner():
    with _OWNER_LOCK:
        return _OWNER
