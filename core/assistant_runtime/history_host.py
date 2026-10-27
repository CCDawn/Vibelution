"""Main-only binding of one approved native-turn preview to archive import."""
from __future__ import annotations

import secrets
from contextlib import contextmanager
from pathlib import Path
from threading import Lock, RLock

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

    def close(self):
        with self._lock:
            self._active = False
            self._owner.close()

    def stop_native_turn(self, native_stop, turn_id):
        """Order a successful native stop against the final archive commit."""
        with self._lock:
            result = native_stop(turn_id)
            self._preview.stop_turn(turn_id)
            if self._operation_turn == turn_id:
                self._operation_stopped = True
                self._owner.suspend()
            return result

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
