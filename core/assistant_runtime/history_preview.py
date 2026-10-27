"""Metadata-only, short-lived preview of a registered legacy PA source.

The token is evidence for a later approval protocol, not an authorization to
read history or to publish an archive. No import operation is exposed here.
"""
from __future__ import annotations

import secrets
import time
import os
from dataclasses import replace
from pathlib import Path
from threading import RLock

from .migration_inventory import declared_assistant_identities
from .migration_io import MigrationIOError, read_stable_file, strict_json, verify_snapshot
from .migration_paths import _identity_chain


def _project_source_paths(root, config):
    """Resolve the project route without the assistant's DATA_HOME override."""
    from config.paths import default_data_home, resolve_configured_data_home
    from vibelution_storage import (legacy_project_storage_paths, resolve_project_storage_paths,
        storage_migration_complete, storage_migration_state_path)
    from .migration_io import check_path

    target = resolve_project_storage_paths(root)
    marker = storage_migration_state_path(target)
    if marker.exists() or marker.is_symlink():
        check_path(marker)
        if not storage_migration_complete(target):
            raise MigrationIOError("history_source_unavailable")
        return target

    legacy_home = resolve_configured_data_home(config_path=config) or default_data_home().resolve()
    legacy = replace(legacy_project_storage_paths(root, target=target, config_path=config), data=legacy_home)

    def nonempty(path):
        if not path.exists() and not path.is_symlink():
            return False
        check_path(path)
        if not path.is_dir():
            raise MigrationIOError("history_source_unavailable")
        return next(path.iterdir(), None) is not None

    if (root / ".git").is_dir() and any(nonempty(path) for path in (
            legacy.runtime, legacy.logs, legacy.memory, root / "workspace",
            root / "log_info", root / "backups", legacy.data)):
        return legacy
    return target


class HistoryPreview:
    def __init__(self, dispatch, config_path: Path, *, clock=time.monotonic, ttl=300):
        self._dispatch = dispatch
        self._config = Path(config_path)
        self._clock = clock
        self._ttl = ttl
        self._lock = RLock()
        self._previews = {}
        self._stopped_turns = set()
        self._stop_capacity_exhausted = False

    def _registration(self, project_id):
        projects = self._dispatch._admitted_projects()
        root = projects.get(project_id)
        if root is None:
            raise MigrationIOError("history_project_unavailable")
        return self._dispatch._registry_revision, root

    def preview(self, project_id, *, turn_id=None):
        from scripts.assistant_migration_inventory import _existing_route
        from config.paths import resolve_configured_data_home
        from core.infrastructure import developer_sandbox
        from vibelution_storage import (resolve_active_project_storage_paths, resolve_project_storage_paths,
                                       storage_migration_state_path)
        try:
            revision, root = self._registration(project_id)
            if root.resolve(strict=True) != root or not root.is_dir():
                raise ValueError("project changed")
            paths = _project_source_paths(root, self._config)
            # Existing sandbox routing still uses the process-wide resolver.
            # When it disagrees, its pointer cannot prove this source route.
            if resolve_active_project_storage_paths(root, config_path=self._config).runtime != paths.runtime:
                raise ValueError("sandbox runtime ambiguous")
            if developer_sandbox._project_root(root) != root:
                raise ValueError("project root ambiguous")
            # The assistant process has its own VIBELUTION_DATA_HOME. It must
            # never override the selected project's formal source workspace.
            formal = (resolve_configured_data_home(config_path=self._config) or paths.data) / "workspace"
            host_data = os.environ.get("VIBELUTION_DATA_HOME", "").strip()
            if host_data:
                own = Path(host_data).resolve()
                source_home = formal.parent.resolve()
                if source_home == own or source_home.is_relative_to(own) or own.is_relative_to(source_home):
                    raise ValueError("assistant and source data overlap")
            def route_context():
                context = developer_sandbox.snapshot_formal_workspace_paths()
                return context
            with route_context():
                developer_sandbox._FORMAL_WORKSPACE_SNAPSHOT.get()[root] = formal
                workspace, _, route_snapshots, verify_route = _existing_route(paths, self._config)
            root_chain, workspace_chain = _identity_chain(root), _identity_chain(workspace)
            registry = read_stable_file(workspace / "agents/agents.json", 16 * 1024 * 1024)
            project_identity = read_stable_file(root / ".vibelution/project.json", 64 * 1024)
            marker = storage_migration_state_path(resolve_project_storage_paths(root))
            marker_present = marker.exists() or marker.is_symlink()
            marker_snapshots = (read_stable_file(marker, 64 * 1024),) if marker_present else ()
            authority_snapshots = (*route_snapshots, registry, project_identity, *marker_snapshots)
            value = strict_json(registry.raw)
            candidates = declared_assistant_identities(value.get("agents") if isinstance(value, dict) else None)
            if len(candidates) != 1:
                raise MigrationIOError("history_source_ambiguous")
            registry_proof = (registry.path, registry.sha256, registry.identity, len(registry.raw))

            def verify():
                if self._registration(project_id) != (revision, root):
                    raise ValueError("registration changed")
                if (_project_source_paths(root, self._config) != paths
                        or resolve_active_project_storage_paths(root, config_path=self._config).runtime != paths.runtime):
                    raise ValueError("storage changed")
                with route_context():
                    developer_sandbox._FORMAL_WORKSPACE_SNAPSHOT.get()[root] = formal
                    verify_route()
                if not marker_present and (marker.exists() or marker.is_symlink()):
                    raise ValueError("storage marker changed")
                for snapshot in authority_snapshots:
                    verify_snapshot(snapshot)
                if _identity_chain(root) != root_chain or _identity_chain(workspace) != workspace_chain:
                    raise ValueError("physical source changed")
                registry_path, digest, identity, size = registry_proof
                if read_stable_file(registry_path, size, expected=identity).sha256 != digest:
                    raise ValueError("registry changed")

            verify()
            token = secrets.token_hex(32)
            public = {"projectId": project_id, "sourceProjectId": paths.project_id,
                      "instanceId": paths.instance_id, "assistantAgentId": candidates[0]["agentId"],
                      "previewId": token, "expiresInSeconds": self._ttl,
                      "authorized": False, "readyForCutover": False}
            with self._lock:
                if turn_id and (self._stop_capacity_exhausted or turn_id in self._stopped_turns):
                    raise MigrationIOError("history_turn_stopped")
                now = self._clock()
                self._previews = {key: row for key, row in self._previews.items() if row[0] > now}
                if len(self._previews) >= 16:
                    raise MigrationIOError("history_preview_capacity")
                self._previews[token] = (now + self._ttl, verify, public,
                                         root, workspace, paths, turn_id, authority_snapshots)
            return dict(public)
        except MigrationIOError:
            raise
        except Exception:
            raise MigrationIOError("history_source_unavailable") from None

    def verify_preview(self, preview_id):
        """Revalidate metadata only; this never grants an import capability."""
        with self._lock:
            row = self._previews.get(preview_id)
            if row is None or row[0] <= self._clock():
                self._previews.pop(preview_id, None)
                raise MigrationIOError("history_preview_expired")
            try:
                row[1]()
            except Exception:
                self._previews.pop(preview_id, None)
                raise MigrationIOError("history_preview_changed") from None
            return dict(row[2])

    def consume_for_import(self, preview_id, project_id, revision, turn_id):
        """Consume a matching native-turn preview; no approval is inferred."""
        with self._lock:
            row = self._previews.pop(preview_id, None)
            if row is None or row[0] <= self._clock():
                raise MigrationIOError("history_preview_expired")
            if (not turn_id or self._stop_capacity_exhausted or turn_id in self._stopped_turns
                    or row[6] != turn_id or row[2]["projectId"] != project_id
                    or self._dispatch._registry_revision != revision):
                raise MigrationIOError("history_preview_changed")
            try:
                row[1]()
            except Exception:
                raise MigrationIOError("history_preview_changed") from None
            return row[3], row[4], row[5], row[2]["assistantAgentId"], row[1], row[7]

    def discard(self, preview_id):
        with self._lock:
            self._previews.pop(preview_id, None)

    def stop_turn(self, turn_id):
        """Retire existing and still-being-created previews for this Turn."""
        with self._lock:
            if turn_id not in self._stopped_turns:
                if len(self._stopped_turns) >= 4096:
                    # Never evict a tombstone while delayed requests can exist.
                    self._stop_capacity_exhausted = True
                    self._previews.clear()
                    return
                self._stopped_turns.add(turn_id)
            self._previews = {key: row for key, row in self._previews.items() if row[6] != turn_id}
