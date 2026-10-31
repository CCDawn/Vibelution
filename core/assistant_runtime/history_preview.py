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
from threading import Event, Lock, RLock

from .migration_inventory import declared_assistant_identities
from .migration_io import MigrationIOError, read_stable_file, strict_json, verify_snapshot
from .migration_paths import _identity_chain


def _project_source_paths(root, config, *, projects_home=None, legacy_home=None):
    """Resolve the project route without the assistant's DATA_HOME override."""
    from config.paths import default_data_home, resolve_configured_data_home
    from vibelution_storage import (legacy_project_storage_paths, resolve_project_storage_paths,
        storage_migration_complete, storage_migration_state_path)
    from .migration_io import check_path

    target = resolve_project_storage_paths(root, projects_home=projects_home)
    marker = storage_migration_state_path(target)
    if marker.exists() or marker.is_symlink():
        check_path(marker)
        if not storage_migration_complete(target):
            raise MigrationIOError("history_source_unavailable")
        return target

    legacy_home = (Path(legacy_home) if legacy_home is not None else
                   resolve_configured_data_home(config_path=config) or default_data_home().resolve())
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
        self._retirement_lock = Lock()
        self._retirements = {}
        self._previews = {}
        self._reminder_approvals = {}
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
                self._reminder_approvals = {key: value for key, value in self._reminder_approvals.items() if key in self._previews}
                with self._retirement_lock:
                    for key, (expiry, flag) in list(self._retirements.items()):
                        if expiry <= now:
                            flag.set()
                            del self._retirements[key]
                    if len(self._retirements) >= 4096:
                        raise MigrationIOError("history_preview_capacity")
                if len(self._previews) >= 16:
                    raise MigrationIOError("history_preview_capacity")
                retired = Event()
                def guarded_verify():
                    if retired.is_set():
                        raise ValueError("preview retired")
                    verify()
                    if retired.is_set():
                        raise ValueError("preview retired")
                self._previews[token] = (now + self._ttl, guarded_verify, public,
                                         root, workspace, paths, turn_id, authority_snapshots, set(), retired)
                with self._retirement_lock:
                    self._retirements[token] = (now + self._ttl, retired)
            return dict(public)
        except MigrationIOError:
            raise
        except Exception:
            raise MigrationIOError("history_source_unavailable") from None

    def verify_preview(self, preview_id):
        """Revalidate metadata only; this never grants an import capability."""
        with self._lock:
            row = self._previews.get(preview_id)
            if row is None or row[0] <= self._clock() or row[9].is_set():
                self._previews.pop(preview_id, None)
                raise MigrationIOError("history_preview_expired")
            try:
                row[1]()
                if row[9].is_set():
                    raise ValueError("preview retired")
            except Exception:
                self._previews.pop(preview_id, None)
                raise MigrationIOError("history_preview_changed") from None
            return dict(row[2])

    def consume_for_import(self, preview_id, project_id, revision, turn_id, *, purpose=None):
        """Consume one migration purpose, or exclusively consume for legacy callers.

        The caller must independently establish native authorization for each use.
        An exclusive use (such as affairs sync) cannot share a migration preview.
        """
        with self._lock:
            row = self._previews.get(preview_id)
            if row is None or row[0] <= self._clock() or row[9].is_set():
                self._previews.pop(preview_id, None)
                raise MigrationIOError("history_preview_expired")
            if (not turn_id or self._stop_capacity_exhausted or turn_id in self._stopped_turns
                    or row[6] != turn_id or row[2]["projectId"] != project_id
                    or self._dispatch._registry_revision != revision
                    or purpose not in (None, "history", "personal", "knowledge")):
                self._previews.pop(preview_id, None)
                raise MigrationIOError("history_preview_changed")
            if purpose is None:
                self._previews.pop(preview_id, None)
                if row[8]:
                    raise MigrationIOError("history_preview_changed")
            elif purpose in row[8]:
                raise MigrationIOError("history_preview_expired")
            else:
                # Reserve before any source verification or downstream work.
                row[8].add(purpose)
            try:
                row[1]()
                if row[9].is_set():
                    raise ValueError("preview retired")
            except Exception:
                self._previews.pop(preview_id, None)
                raise MigrationIOError("history_preview_changed") from None
            return row[3], row[4], row[5], row[2]["assistantAgentId"], row[1], row[7]

    def reminder_recovery_approval(self, project_id, preview_id):
        """Freeze the original head and current source shown by native approval.

        This metadata does not itself authorize publication. Only prepare's
        live native delivery may consume it, once, under the profile owner.
        """
        from types import SimpleNamespace
        from . import native
        from .initial_migration_binding import authority_identity
        from .reminder_handoff_intent import read_handoff_authorization
        from .reminder_offline_worker import _matches_origin, _registry_digest_matches
        from core.infrastructure.native_runtime import assistant_native_root

        with self._lock:
            public = self.verify_preview(preview_id)
            row = self._previews[preview_id]
            if public["projectId"] != project_id or not row[6] or not native._STARTED or native._OFFLINE_MIGRATION:
                raise MigrationIOError("reminder_handoff_approval_unavailable")
            root = assistant_native_root()
            prior, head = read_handoff_authorization(root, project_id)
            if prior is None:
                raise MigrationIOError("reminder_handoff_approval_unavailable")
            scope = {"projectId": row[5].project_id, "instanceId": row[5].instance_id, "agentId": public["assistantAgentId"]}
            current_authority = authority_identity(row[7])
            target = SimpleNamespace(root=root, agent_id=native._AGENT_ID, session_id=native._SESSION_ID)
            if (not _matches_origin(prior, target, scope, row[3], row[4], category="reminder_handoff")
                    or _registry_digest_matches(row[7], prior["registryDigest"])):
                raise MigrationIOError("reminder_handoff_approval_unavailable")
            shown = {key: public[key] for key in ("sourceProjectId", "instanceId", "assistantAgentId")}
            shown.update(operationId=prior["operationId"], syncId=prior["syncId"],
                         sourceSnapshotDigest=current_authority, previousAuthorizationHead=head)
            captured = {"projectId": project_id, "turnId": row[6], "revision": self._dispatch._registry_revision,
                        "head": head, "authorityDigest": current_authority,
                        "sourceIdentityDigest": prior["sourceIdentityDigest"], "shown": shown}
            previous = self._reminder_approvals.setdefault(preview_id, captured)
            if {key: previous[key] for key in captured} != captured:
                raise MigrationIOError("reminder_handoff_approval_changed")
            return dict(shown)

    def consume_reminder_recovery_approval(self, project_id, preview_id, revision, turn_id):
        with self._lock:
            self.verify_preview(preview_id)
            captured = self._reminder_approvals.pop(preview_id, None)
            if (captured is None or captured["projectId"] != project_id or captured["turnId"] != turn_id
                    or captured["revision"] != revision or not captured.get("acceptedRequestId")
                    or captured.get("executingRequestId") != captured["acceptedRequestId"]
                    or captured["acceptedRequestId"] != captured.get("request", {}).get("requestId")):
                raise MigrationIOError("reminder_handoff_approval_unavailable")
            return captured

    def bind_reminder_recovery_request(self, preview_id, request):
        """Called only by native authorization, after it creates the real card."""
        from . import native
        with self._lock:
            self.verify_preview(preview_id)
            captured = self._reminder_approvals.get(preview_id)
            if (captured is None or request["sessionId"] != native._SESSION_ID
                    or request["agentId"] != native._AGENT_ID or request["turnId"] != captured["turnId"]
                    or request["toolName"] != "personal_assistant_manage_tool"
                    or request["argumentSummary"].get("assistantAction") != "reminder_handoff_recover"
                    or request["argumentSummary"].get("assistantTargets") != captured["shown"]):
                raise MigrationIOError("reminder_handoff_approval_unavailable")
            identity = {key: request[key] for key in ("requestId", "callId", "argumentsHash", "sessionId", "agentId", "turnId")}
            if captured.setdefault("request", identity) != identity:
                raise MigrationIOError("reminder_handoff_approval_changed")

    def accept_reminder_recovery_request(self, preview_id, request):
        """A native accepted decision, never just an approval summary."""
        with self._lock:
            self.bind_reminder_recovery_request(preview_id, request)
            if request["status"] != "accepted" or request.get("decision") != "accept":
                raise MigrationIOError("reminder_handoff_approval_unavailable")
            self._reminder_approvals[preview_id]["acceptedRequestId"] = request["requestId"]

    def arm_reminder_recovery_call(self, preview_id, proof):
        """Match the executor's copied per-call authorization context, once."""
        with self._lock:
            self.verify_preview(preview_id)
            captured = self._reminder_approvals.get(preview_id)
            if (captured is None or captured.get("request") != proof
                    or captured.get("acceptedRequestId") != proof.get("requestId")
                    or captured.get("executingRequestId")):
                raise MigrationIOError("reminder_handoff_approval_unavailable")
            captured["executingRequestId"] = proof["requestId"]

    def discard(self, preview_id):
        self.retire(preview_id)
        with self._lock:
            self._previews.pop(preview_id, None)
            self._reminder_approvals.pop(preview_id, None)

    def retire(self, preview_id):
        """Fence later uses without waiting for source verification to finish."""
        with self._retirement_lock:
            entry = self._retirements.get(preview_id)
            if entry is not None:
                entry[1].set()

    def stop_turn(self, turn_id):
        """Retire existing and still-being-created previews for this Turn."""
        with self._lock:
            if turn_id not in self._stopped_turns:
                if len(self._stopped_turns) >= 4096:
                    # Never evict a tombstone while delayed requests can exist.
                    self._stop_capacity_exhausted = True
                    for row in self._previews.values():
                        row[9].set()
                    self._previews.clear()
                    self._reminder_approvals.clear()
                    return
                self._stopped_turns.add(turn_id)
            for row in self._previews.values():
                if row[6] == turn_id:
                    row[9].set()
            self._previews = {key: row for key, row in self._previews.items() if row[6] != turn_id}
            self._reminder_approvals = {key: value for key, value in self._reminder_approvals.items() if key in self._previews}
