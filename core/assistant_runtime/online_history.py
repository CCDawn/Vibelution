"""Host-only history archive coordinator; never expose construction to a model.

The owner supplies resolved registrations and updates/revokes them through this
object. There is deliberately no HTTP or model action in this module.
"""
from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Callable

from . import migration_history as history
from .main_control import _opaque, history_request_id
from .migration_io import (FileSnapshot, MigrationIOError, check_path, migration_target_lock,
                           path_identity, pinned_source_files, pinned_target_directory, publish_directory, read_stable_file, strict_json)

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")


class HistoryTargetBusy(MigrationIOError):
    """A nonblocking target-lock acquisition failed before entering its guard."""


class _HistoryConfirmationBusy(Exception):
    """The target guard refused entry before a receipt publication attempt."""


@dataclass(frozen=True)
class AuthorizedHistorySource:
    """A trusted main-owned registration plus explicit source authorization."""
    project_root: Path
    workspace: Path
    instance_id: str
    assistant_agent_id: str
    project_id: str
    authority_guard: Callable
    authority_snapshots: tuple[FileSnapshot, ...] = ()


class OnlineHistoryOwner:
    def __init__(self, *, profile_root: Path, generation: str,
                 sources: dict[str, AuthorizedHistorySource], generation_guard: Callable):
        if (not isinstance(generation, str) or not _ID.fullmatch(generation)
                or not callable(generation_guard)):
            raise ValueError("history_generation_invalid")
        self._profile = check_path(profile_root)
        if not self._profile.is_dir():
            raise ValueError("history_profile_invalid")
        self._profile_identity = self._identity()
        self._generation = generation
        self._generation_guard = generation_guard
        self._lock = RLock()
        self._closed = False
        self._revision = 0
        self._sources = self._validate_sources(sources)

    def _identity(self):
        stamp = path_identity(check_path(self._profile))
        return stamp[0], stamp[1], stamp[5]

    @staticmethod
    def _validate_sources(sources):
        if type(sources) is not dict or len(sources) > 128:
            raise ValueError("history_sources_invalid")
        result = {}
        for key, source in sources.items():
            if (not _opaque(key, 160)
                    or type(source) is not AuthorizedHistorySource
                    or not isinstance(source.project_root, Path) or not source.project_root.is_absolute()
                    or not isinstance(source.workspace, Path) or not source.workspace.is_absolute()
                    or not callable(source.authority_guard)
                    or type(source.authority_snapshots) is not tuple
                    or any(not isinstance(snapshot, FileSnapshot) for snapshot in source.authority_snapshots)
                    or any(not isinstance(value, str) or not _ID.fullmatch(value)
                           for value in (source.instance_id, source.assistant_agent_id, source.project_id))):
                raise ValueError("history_sources_invalid")
            result[key] = source
        return result

    def replace_sources(self, sources: dict[str, AuthorizedHistorySource]):
        """Trusted host-only authorization update; revocation fences writes."""
        validated = self._validate_sources(sources)
        with self._generation_guard(self._generation):
            with self._lock:
                if self._closed:
                    raise MigrationIOError("history_owner_closed")
                self._sources = validated
                self._revision += 1

    def close(self):
        with self._lock:
            self._closed = True
            self._sources = {}

    def suspend(self):
        """Always permit narrowing authority, including on a stale generation."""
        with self._lock:
            self._sources = {}
            self._revision += 1

    def _verify(self, project_id, source, revision):
        if self._closed or self._revision != revision or self._sources.get(project_id) != source:
            raise MigrationIOError("history_authority_revoked")
        if self._identity() != self._profile_identity:
            raise MigrationIOError("history_profile_changed")

    def import_history(self, project_id: str, migration_id: str, *, _expected_source=None, _expected_revision=None):
        """One attempt only: an existing reservation always means unknown.

        Caller retains migration_id after any error; inspecting the immutable
        archive is separate from attempting this operation again.
        """
        if (not _opaque(project_id, 160) or not isinstance(migration_id, str)
                or not _ID.fullmatch(migration_id)):
            raise ValueError("history_request_invalid")
        with self._generation_guard(self._generation):
            with self._lock:
                source = self._sources.get(project_id)
                if source is None:
                    raise MigrationIOError("history_authority_revoked")
                revision = self._revision
                if _expected_source is not None and (source != _expected_source or revision != _expected_revision):
                    raise MigrationIOError("history_authority_revoked")

        @contextmanager
        def guard():
            # The caller-provided generation fence must hold the same authority
            # used to replace generations for the entire guarded operation.
            with self._generation_guard(self._generation):
                with source.authority_guard():
                    with self._lock:
                        self._verify(project_id, source, revision)
                        yield

        with guard():
            pass

        found = history.discover_history(project_root=source.project_root, workspace=source.workspace,
            project_id=source.project_id, instance_id=source.instance_id,
            assistant_agent_id=source.assistant_agent_id)
        if not found.report.get("historyComplete"):
            raise MigrationIOError("history_discovery_incomplete")
        target = history._canonical_target(self._profile)
        for source_root in (*found.source_roots, source.project_root):
            source_root = check_path(source_root).resolve()
            if target.is_relative_to(source_root) or source_root.is_relative_to(target):
                raise MigrationIOError("history_target_overlaps_source")
        # Reserve durably before attempting any archive writes. Never retry a
        # reserved ID, even after process restart or loss of the success ACK.
        with guard():
            with pinned_target_directory(self._profile / "history_online_reservations", create=True) as root:
                with migration_target_lock(root / ".reserve"):
                    marker = root / migration_id
                    if marker.exists() or marker.is_symlink():
                        raise MigrationIOError("history_outcome_unknown")
                    raw = json.dumps({"schemaVersion": 1, "migrationId": migration_id,
                                      "projectId": project_id, "generation": self._generation},
                                     sort_keys=True, separators=(",", ":")).encode("utf-8")
                    history._write_new(marker, raw)
        @contextmanager
        def confirmation_guard():
            with pinned_source_files((*found.snapshots, *source.authority_snapshots)):
                yield

        return history.import_history(found, self._profile, migration_id,
                                      authority_verify=lambda: self._verify_locked(project_id, source, revision),
                                      write_guard=guard, confirmation_guard=confirmation_guard)

    def _verify_locked(self, project_id, source, revision):
        with self._generation_guard(self._generation):
            with source.authority_guard():
                with self._lock:
                    self._verify(project_id, source, revision)

    @staticmethod
    def _request_id(project_id, preview_id):
        if not _opaque(project_id, 160) or type(preview_id) is not str or re.fullmatch(r"[a-f0-9]{64}", preview_id) is None:
            raise ValueError("history_request_invalid")
        return history_request_id(project_id, preview_id)

    @contextmanager
    def _receipt_authority(self, project_id, target_guard):
        """Trusted host supplies a nonblocking target lock with nonfailing release."""
        from .initial_migration_binding import source_identity, target_identity
        with self._generation_guard(self._generation):
            with self._lock:
                source = self._sources.get(project_id)
                if source is None:
                    raise MigrationIOError("history_authority_revoked")
                revision = self._revision
            with source.authority_guard():
                with self._lock:
                    # The host guard must be nonblocking and pin the native
                    # target identity. Pin the source authority through commit.
                    with pinned_source_files(source.authority_snapshots), target_guard() as target:
                        if type(target) is not tuple or len(target) != 2 or any(not isinstance(v, str) or not _ID.fullmatch(v) for v in target):
                            raise MigrationIOError("history_target_invalid")
                        self._verify(project_id, source, revision)
                        scope = {"projectId": source.project_id, "instanceId": source.instance_id, "agentId": source.assistant_agent_id}
                        source_digest, _, _ = source_identity(scope, source.project_root, source.workspace)
                        target_digest, _ = target_identity(self._profile, *target)
                        yield source, scope, source_digest, target, target_digest, revision
                        self._verify(project_id, source, revision)

    def import_bound_history(self, project_id, preview_id, turn_id, *, target_guard):
        """Admit once, then persist only a confirmed native result; never replay."""
        mid = self._request_id(project_id, preview_id)
        if not _opaque(turn_id, 160) or not callable(target_guard):
            raise ValueError("history_request_invalid")
        with ExitStack() as stack:
            deadline = None
            while True:
                try:
                    values = stack.enter_context(self._receipt_authority(project_id, target_guard))
                    break
                except HistoryTargetBusy:
                    if deadline is None:
                        deadline = time.monotonic() + 2.0
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return {"prewriteBusy": True}
                    time.sleep(min(0.05, remaining))
            source, scope, src, target, dst, revision = values
            if deadline is not None and time.monotonic() >= deadline:
                return {"prewriteBusy": True}
            binding = {"schemaVersion": 1, "requestId": mid, "projectId": project_id,
                       "previewId": preview_id, "turnId": turn_id, "sourceScope": scope,
                       "sourceIdentity": src, "targetAgentId": target[0], "targetSessionId": target[1], "targetIdentity": dst}
            with pinned_target_directory(self._profile / "history_request_receipts", create=True) as root:
                with migration_target_lock(root / ".receipts"):
                    path = root / (mid + ".intent")
                    if path.exists() or path.is_symlink():
                        raise MigrationIOError("history_outcome_unknown")
                    history._write_new(path, json.dumps(binding, sort_keys=True, separators=(",", ":")).encode())
        result = self.import_history(project_id, mid, _expected_source=source, _expected_revision=revision)
        # Retry only a target lock that was never entered. All guards and pins
        # unwind before waiting; the native import is never called again.
        @contextmanager
        def confirmation_guard():
            with ExitStack() as stack:
                try:
                    target = stack.enter_context(target_guard())
                except HistoryTargetBusy:
                    raise _HistoryConfirmationBusy() from None
                yield target

        deadline = None
        while True:
            try:
                if deadline is not None:
                    with self._generation_guard(self._generation):
                        with self._lock:
                            self._verify(project_id, source, revision)
                            with confirmation_guard():
                                if time.monotonic() >= deadline:
                                    raise MigrationIOError("history_outcome_unknown")
                return self._confirm_bound_history(project_id, preview_id, binding, source, revision, result, confirmation_guard, deadline)
            except _HistoryConfirmationBusy:
                if deadline is None:
                    deadline = time.monotonic() + 2.0
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MigrationIOError("history_outcome_unknown") from None
                time.sleep(min(0.05, remaining))

    def _confirm_bound_history(self, project_id, preview_id, binding, source, revision, result, target_guard, deadline):
        mid = self._request_id(project_id, preview_id)
        with self._receipt_authority(project_id, target_guard) as (current_source, scope, src, target, dst, current_revision):
            if (scope != binding["sourceScope"] or src != binding["sourceIdentity"]
                    or target != (binding["targetAgentId"], binding["targetSessionId"]) or dst != binding["targetIdentity"]
                    or current_source != source or current_revision != revision):
                raise MigrationIOError("history_outcome_unknown")
        # Source checks (including their exit checks) are complete before a
        # receipt exists. This records a past confirmed result; it does not
        # assert the source remains unchanged after that confirmation.
        from .initial_migration_binding import target_identity
        archive_id = result.get("migrationId")
        count = result.get("historyCount")
        if (result.get("published") is not True or not isinstance(archive_id, str) or not _ID.fullmatch(archive_id)
                or type(count) is not int or not 0 <= count <= 10000):
            raise MigrationIOError("history_outcome_unknown")
        archive = self._profile / "history_archive" / "migrations" / archive_id
        with pinned_target_directory(archive):
            loaded = history._load_archive(archive, visible_only=True)
            if (loaded is None or loaded[0]["schemaVersion"] not in (2, 3) or len(loaded[0]["histories"]) != count
                    or any(row["sourceScope"] != {**scope, "projectRoot": str(source.project_root),
                          "workspace": str(source.workspace)} for row in loaded[0]["histories"])):
                raise MigrationIOError("history_outcome_unknown")
            with history._pin_parent_archives(archive, loaded[0], include_self=True):
                pinned = history._load_archive(archive, visible_only=True)
                if pinned is None or pinned[0] != loaded[0]:
                    raise MigrationIOError("history_outcome_unknown")
                with self._generation_guard(self._generation):
                    with self._lock:
                        if (self._closed or self._sources.get(project_id) != source or self._revision != revision
                                or self._identity() != self._profile_identity):
                            raise MigrationIOError("history_authority_revoked")
                        with target_guard() as current_target:
                            if current_target != target or target_identity(self._profile, *target)[0] != dst:
                                raise MigrationIOError("history_target_invalid")
                            if deadline is not None and time.monotonic() >= deadline:
                                raise MigrationIOError("history_outcome_unknown")
                            receipt = {"schemaVersion": 1, "requestId": mid, "migrationId": archive_id, "historyCount": count}
                            with pinned_target_directory(self._profile / "history_request_receipts") as root:
                                with migration_target_lock(root / ".receipts"):
                                    if strict_json(read_stable_file(root / (mid + ".intent"), 16384).raw) != binding:
                                        raise MigrationIOError("history_outcome_unknown")
                                    pending, final = root / ("." + mid + ".pending"), root / mid
                                    if any(p.exists() or p.is_symlink() for p in (pending, final)):
                                        raise MigrationIOError("history_outcome_unknown")
                                    with pinned_target_directory(pending, create=True) as folder:
                                        history._write_new(folder / "result.json", json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode())
                                        identity = path_identity(folder)
                                    if deadline is not None and time.monotonic() >= deadline:
                                        raise MigrationIOError("history_outcome_unknown")
                                    publish_directory(pending, final, identity)
        return receipt

    def _capture_receipt_authority(self, project_id, target_guard):
        """Revalidate authority without holding the lifecycle or target lock over archive I/O."""
        from .initial_migration_binding import source_identity, target_identity
        with self._generation_guard(self._generation):
            with self._lock:
                source = self._sources.get(project_id)
                revision = self._revision
                if source is None:
                    raise MigrationIOError("history_authority_revoked")
                self._verify(project_id, source, revision)
        with source.authority_guard():
            with pinned_source_files(source.authority_snapshots):
                scope = {"projectId": source.project_id, "instanceId": source.instance_id, "agentId": source.assistant_agent_id}
                src, _, _ = source_identity(scope, source.project_root, source.workspace)
                with target_guard() as target:
                    if type(target) is not tuple or len(target) != 2 or any(not isinstance(v, str) or not _ID.fullmatch(v) for v in target):
                        raise MigrationIOError("history_target_invalid")
                    dst, _ = target_identity(self._profile, *target)
        with self._generation_guard(self._generation):
            with self._lock:
                self._verify(project_id, source, revision)
        return source, scope, src, target, dst, revision

    def read_bound_history(self, project_id, preview_id, *, target_guard):
        """Read only an independently recorded result under fresh host authority."""
        mid = self._request_id(project_id, preview_id)
        try:
            captured = self._capture_receipt_authority(project_id, target_guard)
            source, scope, src, target, dst, _ = captured
            with pinned_target_directory(self._profile / "history_request_receipts") as root:
                with migration_target_lock(root / ".receipts"):
                    intent_snapshot = read_stable_file(root / (mid + ".intent"), 16384)
                    with pinned_target_directory(root / mid) as folder:
                        result_snapshot = read_stable_file(folder / "result.json", 16384)
                    binding = strict_json(intent_snapshot.raw)
                    receipt = strict_json(result_snapshot.raw)
                with pinned_source_files((intent_snapshot, result_snapshot)):
                    if (type(binding) is not dict or set(binding) != {"schemaVersion", "requestId", "projectId", "previewId", "turnId", "sourceScope", "sourceIdentity", "targetAgentId", "targetSessionId", "targetIdentity"}
                            or binding["schemaVersion"] != 1 or binding["requestId"] != mid or binding["projectId"] != project_id
                            or binding["previewId"] != preview_id or not _opaque(binding["turnId"], 160)
                            or binding["sourceScope"] != scope or binding["sourceIdentity"] != src
                            or (binding["targetAgentId"], binding["targetSessionId"]) != target or binding["targetIdentity"] != dst
                            or type(receipt) is not dict or set(receipt) != {"schemaVersion", "requestId", "migrationId", "historyCount"}
                            or receipt["schemaVersion"] != 1 or receipt["requestId"] != mid
                            or type(receipt["migrationId"]) is not str or not _ID.fullmatch(receipt["migrationId"])
                            or type(receipt["historyCount"]) is not int or not 0 <= receipt["historyCount"] <= 10000):
                        raise MigrationIOError("history_outcome_unknown")
                    archive = self._profile / "history_archive" / "migrations" / receipt["migrationId"]
                    with pinned_target_directory(archive):
                        loaded = history._load_archive(archive, visible_only=True)
                        if (loaded is None or loaded[0]["schemaVersion"] not in (2, 3) or len(loaded[0]["histories"]) != receipt["historyCount"]
                                or any(row["sourceScope"] != {**scope, "projectRoot": str(source.project_root),
                                      "workspace": str(source.workspace)} for row in loaded[0]["histories"])):
                            raise MigrationIOError("history_outcome_unknown")
                        with history._pin_parent_archives(archive, loaded[0], include_self=True):
                            pinned = history._load_archive(archive, visible_only=True)
                            if pinned is None or pinned[0] != loaded[0]:
                                raise MigrationIOError("history_outcome_unknown")
                            if self._capture_receipt_authority(project_id, target_guard) != captured:
                                raise MigrationIOError("history_authority_revoked")
                            return receipt
        except Exception:
            return None
