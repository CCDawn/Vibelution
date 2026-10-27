"""Main-only binding of one approved native-turn preview to archive import."""
from __future__ import annotations

import secrets
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock, RLock

from .migration_io import MigrationIOError
from .online_history import AuthorizedHistorySource, OnlineHistoryOwner


class HistoryHost:
    def __init__(self, profile_root: Path, generation: str, dispatch, preview):
        self._lock = RLock()
        self._import_lock = Lock()
        self._active = True
        self._generation = generation
        self._dispatch = dispatch
        self._preview = preview
        self._cancelled = set()
        self._operation = None
        self._operation_turn = None
        self._operation_stopped = False
        self._sync_signal_lock = Lock()
        self._sync_active = None
        self._sync_cancelled = {}
        self._sync_seen = {}
        self._owner = OnlineHistoryOwner(profile_root=profile_root, generation=generation,
                                         sources={}, generation_guard=self.guard)

    @contextmanager
    def guard(self, generation=None):
        with self._lock:
            if not self._active or generation is not None and generation != self._generation:
                raise MigrationIOError("history_generation_changed")
            if generation is not None and (self._operation_stopped or self._operation in self._cancelled):
                raise MigrationIOError("history_cancelled")
            yield

    def registry_changed(self):
        """Called under guard before any project snapshot or suspension."""
        self._owner.suspend()

    def signal_registry_change(self):
        """Revoke an admitted sync before waiting for the generation guard."""
        self._signal_sync()

    def _signal_sync(self, *, turn_id=None, operation_id=None, preview_id=None):
        with self._sync_signal_lock:
            current = self._sync_active
            if (current is not None and (turn_id is None or current["turnId"] == turn_id)
                    and (operation_id is None or current["operationId"] == operation_id)
                    and (preview_id is None or current["previewId"] == preview_id)):
                current["owner"].revoke()

    def close(self):
        self._signal_sync()
        with self._lock:
            self._active = False
            self._owner.close()

    def stop_native_turn(self, native_stop, turn_id):
        """Order a successful native stop against the final archive commit."""
        self._signal_sync(turn_id=turn_id)
        with self._lock:
            result = native_stop(turn_id)
            self._preview.stop_turn(turn_id)
            if self._operation_turn == turn_id:
                self._operation_stopped = True
                self._owner.suspend()
            return result

    @contextmanager
    def _sync_guard(self, generation, turn_id, operation_id):
        """Pin the admitted native Turn, generation and registry without waiting."""
        from . import native
        from core.web.services import session_service as sessions

        if not self._lock.acquire(blocking=False):
            raise MigrationIOError("affairs_sync_busy")
        running = False
        try:
            with self._sync_signal_lock:
                current = self._sync_active
                valid = (self._active and generation == self._generation and current is not None
                         and current["operationId"] == operation_id and current["turnId"] == turn_id
                         and operation_id not in self._sync_cancelled)
            if not valid or native._STOP_REQUESTED.is_set() or not native._STARTED or native._OFFLINE_MIGRATION:
                raise MigrationIOError("affairs_sync_cancelled")
            if not sessions._RUNNING_SESSIONS_LOCK.acquire(blocking=False):
                raise MigrationIOError("affairs_sync_busy")
            running = True
            if (native._SESSION_ID not in sessions._RUNNING_SESSION_IDS
                    or sessions._SESSION_ACTIVE_TURN_IDS.get(native._SESSION_ID) != turn_id):
                raise MigrationIOError("affairs_sync_turn_invalid")
            yield
        finally:
            if running:
                sessions._RUNNING_SESSIONS_LOCK.release()
            self._lock.release()

    def cancel_affairs(self, operation_id, preview_id):
        """Revoke before waiting; cancellation acknowledges only a drained owner."""
        with self._sync_signal_lock:
            seen = self._sync_seen.get(operation_id)
            current = self._sync_active
            if (seen is not None and seen["previewId"] != preview_id
                    or current is not None and current["operationId"] == operation_id
                    and current["previewId"] != preview_id):
                raise ValueError("affairs_sync_operation_mismatch")
            if operation_id not in self._sync_cancelled and len(self._sync_cancelled) >= 256:
                raise MigrationIOError("affairs_sync_cancel_capacity")
            self._sync_cancelled[operation_id] = preview_id
            if current is not None and current["operationId"] == operation_id:
                current["owner"].revoke()
                done = current["done"]
            else:
                done = None
        if done is not None and not done.wait(timeout=10):
            raise MigrationIOError("affairs_sync_drain_unconfirmed")
        # The sync guard holds this lock until the write capability drains.
        with self._lock:
            self._preview.discard(preview_id)
            return {"schemaVersion": 1, "operationId": operation_id, "cancelled": True}

    def sync_affairs(self, project_id, preview_id, revision, turn_id, operation_id):
        """Consume exactly one main-approved preview and synchronize its affairs."""
        from .main_control import affairs_migration_id
        from .migration_affairs_conflicts import (discover_affairs_baseline_locked, locked_affairs_target,
            _BaselineVerifier, _sync_candidates, _verify_record_sources)
        from .migration_affairs_convergence import converge_affairs
        from .migration_io import pinned_source_files
        from .online_affairs_sync import synchronize_affairs
        from .online_affairs_sync_lease import OnlineAffairsSyncOwner

        mid = affairs_migration_id(project_id, preview_id)
        base = {"schemaVersion": 1, "projectId": project_id, "previewId": preview_id,
                "migrationId": mid, "readyForCutover": False}
        binding_key = (project_id, preview_id, revision, turn_id)
        if not self._import_lock.acquire(blocking=False):
            with self._sync_signal_lock:
                active = self._sync_active
                same_preview = active is not None and active["previewId"] == preview_id
            if not same_preview:
                self._preview.discard(preview_id)
            return {**base, "state": "rejected", "code": "busy"}
        owner = OnlineAffairsSyncOwner(self._generation,
            lambda generation, turn: self._sync_guard(generation, turn, operation_id))
        current = {"operationId": operation_id, "previewId": preview_id, "turnId": turn_id,
                   "owner": owner, "done": Event()}
        try:
            with self._sync_signal_lock:
                previous = self._sync_seen.get(operation_id)
                if previous is not None:
                    if previous["binding"] != binding_key:
                        return {**base, "state": "unknown", "code": "unknown"}
                    return previous.get("result") or {**base, "state": "unknown", "code": "unknown"}
                if operation_id in self._sync_cancelled:
                    if self._sync_cancelled[operation_id] != preview_id:
                        return {**base, "state": "unknown", "code": "unknown"}
                    self._preview.discard(preview_id)
                    # A cancel may arrive after an evicted successful result.
                    # Its tombstone fences future work, not prior effects.
                    return {**base, "state": "unknown", "code": "unknown"}
                if len(self._sync_seen) >= 256:
                    # A cached terminal result is evictable only after its
                    # preview was consumed or explicitly discarded. A late
                    # duplicate then cannot acquire a fresh write capability.
                    terminal = next((key for key, entry in self._sync_seen.items()
                                     if entry["result"] is not None), None)
                    if terminal is None:
                        return {**base, "state": "rejected", "code": "busy"}
                    del self._sync_seen[terminal]
                self._sync_seen[operation_id] = {"binding": binding_key, "previewId": preview_id, "result": None}
                self._sync_active = current
            validation_phase = "preview"
            convergence_attempted = False
            try:
                with self._sync_guard(self._generation, turn_id, operation_id):
                    binding = self._preview.consume_for_import(preview_id, project_id, revision, turn_id)
                    validation_phase = "baseline"
                    paths, source_agent = binding[2], binding[3]
                    scope = {"projectId": paths.project_id, "instanceId": paths.instance_id, "agentId": source_agent}
                    from . import native
                    if not native._LOCK.acquire(blocking=False):
                        raise MigrationIOError("affairs_sync_busy")
                    try:
                        with locked_affairs_target(self._owner._profile, target_agent_id=native._AGENT_ID) as target:
                            try:
                                baseline = discover_affairs_baseline_locked(self._owner._profile, source_scope=scope,
                                    target_agent_id=native._AGENT_ID, target=target)["baselineMigrationId"]
                                unresolved = None
                            except MigrationIOError as error:
                                if str(error) != "affairs_baseline_unresolved":
                                    raise
                                verifier = _BaselineVerifier(self._owner._profile, scope, native._AGENT_ID, target=target)
                                verifier.candidates = _sync_candidates(self._owner._profile, scope, native._AGENT_ID)
                                pending = []
                                for links in verifier.candidates.values():
                                    for record, receipt, record_snapshot, receipt_snapshot in links:
                                        if receipt["published"] is not True or receipt["conflictCount"] == 0:
                                            continue
                                        _verify_record_sources(self._owner._profile, record, verifier)
                                        verifier.snapshots.extend((record_snapshot, receipt_snapshot))
                                        if not verifier.converged(record, receipt):
                                            pending.append((record["syncId"], record["baselineMigrationId"]))
                                verifier.finish()
                                if len(pending) != 1:
                                    raise MigrationIOError("affairs_baseline_unresolved")
                                unresolved = pending[0]
                    finally:
                        native._LOCK.release()
                if unresolved is not None:
                    sync_id, old_baseline = unresolved
                    # Leave the non-reentrant session guard before owner.admit;
                    # admit reacquires the same Turn/registry guard once.
                    with owner.admit(generation=self._generation, turn_id=turn_id,
                                     baseline_migration_id=old_baseline, source_scope=scope) as lease:
                        binding[4]()
                        with pinned_source_files(binding[5]):
                            binding[4]()
                            convergence_attempted = True
                            converge_affairs(lease, sync_id=sync_id, source_scope=scope)
                            binding[4]()
                    with self._sync_guard(self._generation, turn_id, operation_id):
                        binding[4]()
                        if not native._LOCK.acquire(blocking=False):
                            raise MigrationIOError("affairs_sync_busy")
                        try:
                            with locked_affairs_target(self._owner._profile, target_agent_id=native._AGENT_ID) as target:
                                baseline = discover_affairs_baseline_locked(self._owner._profile, source_scope=scope,
                                    target_agent_id=native._AGENT_ID, target=target)["baselineMigrationId"]
                        finally:
                            native._LOCK.release()
            except Exception as error:
                with self._sync_signal_lock:
                    cancelled = operation_id in self._sync_cancelled or owner._revoked.is_set()
                if convergence_attempted and str(error) not in {"affairs_convergence_not_reached", "affairs_convergence_not_required"}:
                    result = {**base, "state": "unknown", "code": "unknown"}
                elif not cancelled and validation_phase == "preview" and str(error) == "history_preview_expired":
                    # The preview may already have been consumed by an evicted
                    # completed request; absence cannot prove it did not write.
                    result = {**base, "state": "unknown", "code": "unknown"}
                else:
                    baseline_codes = {"affairs_baseline_unresolved": "unresolved",
                                      "affairs_convergence_not_reached": "unresolved",
                                      "affairs_convergence_not_required": "unresolved",
                                      "affairs_baseline_pending": "pending",
                                      "affairs_baseline_not_found": "baseline_unavailable"}
                    code = ("cancelled" if cancelled else "busy" if str(error) == "affairs_sync_busy"
                            else baseline_codes.get(str(error), "project_unavailable") if validation_phase == "baseline"
                            else "preview_invalid")
                    result = {**base, "state": "rejected", "code": code}
            else:
                try:
                    outcome = synchronize_affairs(preview_binding=binding, owner=owner, generation=self._generation,
                        turn_id=turn_id, migration_id=mid, baseline_migration_id=baseline)
                except Exception:
                    outcome = {}
                if not isinstance(outcome, dict):
                    outcome = {}
                state, code = outcome.get("state"), outcome.get("code")
                valid_counts = (type(outcome.get("appliedCount")) is int
                    and 0 <= outcome["appliedCount"] <= 4096
                    and type(outcome.get("conflictCount")) is int
                    and 0 <= outcome["conflictCount"] <= 4096)
                if valid_counts and state == "complete" and code == "synchronized" and outcome["conflictCount"] == 0:
                    result = {**base, "state": state, "code": code, "appliedCount": outcome["appliedCount"], "conflictCount": 0}
                elif valid_counts and state == "partial" and code == "unresolved" and outcome["conflictCount"] > 0:
                    result = {**base, "state": state, "code": code, "appliedCount": outcome["appliedCount"], "conflictCount": outcome["conflictCount"]}
                else:
                    result = {**base, "state": "unknown", "code": "unknown"}
            # Includes guard failures before consume: such previews must not
            # become executable after their result leaves the bounded cache.
            self._preview.discard(preview_id)
            with self._sync_signal_lock:
                self._sync_seen[operation_id]["result"] = result
            return result
        finally:
            with self._sync_signal_lock:
                if self._sync_active is current:
                    self._sync_active = None
                current["done"].set()
            self._import_lock.release()

    def cancel(self, operation_id, preview_id):
        """Fence publication before acknowledging cancellation, even if early."""
        with self._lock:
            if operation_id not in self._cancelled and len(self._cancelled) >= 256:
                raise MigrationIOError("history_cancel_capacity")
            self._cancelled.add(operation_id)
            self._preview.discard(preview_id)
            if self._operation == operation_id:
                self._owner.suspend()
            return {"schemaVersion": 1, "operationId": operation_id, "cancelled": True}

    def import_history(self, project_id, preview_id, revision, turn_id, operation_id):
        base = {"schemaVersion": 1, "projectId": project_id, "previewId": preview_id,
                "readyForCutover": False}
        if not self._import_lock.acquire(blocking=False):
            self._preview.discard(preview_id)
            return {**base, "state": "rejected", "code": "busy"}
        try:
            try:
                with self._lock:
                    if operation_id in self._cancelled:
                        self._preview.discard(preview_id)
                        return {**base, "state": "rejected", "code": "cancelled"}
                    self._operation = operation_id
                    self._operation_turn = turn_id
                    self._operation_stopped = False
                with self.guard():
                    root, workspace, paths, agent_id, verify, snapshots = self._preview.consume_for_import(
                        preview_id, project_id, revision, turn_id)

                    @contextmanager
                    def authority():
                        verify()
                        yield
                        verify()

                    source = AuthorizedHistorySource(root, workspace, paths.instance_id, agent_id,
                                                     paths.project_id, authority, snapshots)
                    self._owner.replace_sources({project_id: source})
            except (MigrationIOError, ValueError):
                code = "cancelled" if operation_id in self._cancelled else "preview_invalid"
                return {**base, "state": "rejected", "code": code}
            try:
                result = self._owner.import_history(project_id, "history-" + secrets.token_hex(16))
                return {**base, "state": "published", "code": "imported",
                        "historyCount": result["historyCount"]}
            except Exception:
                # The writer may have reserved or published before losing its
                # final confirmation. Never replay or guess from an exception.
                return {**base, "state": "unknown", "code": "unknown"}
            finally:
                self._owner.suspend()
        finally:
            with self._lock:
                self._operation = None
                self._operation_turn = None
                self._operation_stopped = False
            self._import_lock.release()
