"""Host-only history archive coordinator; never expose construction to a model.

The owner supplies resolved registrations and updates/revokes them through this
object. There is deliberately no HTTP or model action in this module.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Callable

from . import migration_history as history
from .main_control import _opaque
from .migration_io import (MigrationIOError, check_path, migration_target_lock,
                           path_identity, pinned_target_directory)

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")


@dataclass(frozen=True)
class AuthorizedHistorySource:
    """A trusted main-owned registration plus explicit source authorization."""
    project_root: Path
    workspace: Path
    instance_id: str
    assistant_agent_id: str
    project_id: str
    authority_guard: Callable


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

    def import_history(self, project_id: str, migration_id: str):
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
        return history.import_history(found, self._profile, migration_id,
                                      authority_verify=lambda: self._verify_locked(project_id, source, revision),
                                      write_guard=guard)

    def _verify_locked(self, project_id, source, revision):
        with self._generation_guard(self._generation):
            with source.authority_guard():
                with self._lock:
                    self._verify(project_id, source, revision)
