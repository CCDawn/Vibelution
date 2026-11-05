"""Irreversible cleanup confined to Launcher-owned tasks and exclusive resources.

The native Session lifecycle remains authoritative. This adapter only removes
the proven task's files after native deletion, leaving its recovery/admission
guards and a content-free request tombstone. Released bytes are the net decrease
of the same logical-file surfaces, including newly retained guards. Shared
SQLite/Git object storage is never attributed to one task.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path

from core.external_agent.contracts import TASK_TERMINAL_STATUSES
from core.chat.session_activity import session_activity_policy
from core.infrastructure import git_process
from core.infrastructure.branch_workspace import _is_reparse_point, resolve_branch_workspace
from core.infrastructure.file_lock import cross_process_file_lock
from core.web.services.external_agent.service import ExternalAgentAccessError, ExternalAgentConflictError
from core.web.services.external_agent.store import ExternalAgentTaskStore
from core.web.services.session.agent_sessions import _delete_session_control_phase

_SESSION_GUARDS = frozenset({".session_deleted", "session_admission.lock"})


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class LocalAssistantCleanupTaskStore(ExternalAgentTaskStore):
    """Local-only request fencing; third-party store semantics are unchanged."""

    def cleanup_lock(self):
        return cross_process_file_lock(self.root / "cleanup", timeout=30)

    def tombstone_path(self, task_id):
        return self.root / "cleanup_tombstones" / self.task_path(task_id).name

    def cleanup_completion(self, task_id):
        path = self.tombstone_path(task_id)
        if self.task_path(task_id).exists() or not path.is_file():
            return None
        _safe_tree(path)
        return self._read_path(path)

    def finish_cleanup(self, record, tombstone):
        path = self.tombstone_path(record["taskId"])
        _atomic_json(path, tombstone)
        record_path = self.task_path(record["taskId"])
        _safe_tree(record_path)
        record_bytes = record_path.stat().st_size
        record_path.unlink()
        return record_bytes

    def _check_request(self, owner_id, client_request_id):
        if not str(client_request_id or "").strip():
            return
        key = _digest([hashlib.sha256(owner_id.strip().encode()).hexdigest(), client_request_id.strip()])
        for path in (self.root / "cleanup_tombstones").glob("eat-*.json"):
            if self._read_path(path).get("requestKeyHash") == key:
                raise ExternalAgentConflictError("Request belongs to a permanently cleaned task", code="TASK_ALREADY_CLEANED")

    def find_idempotent(self, *, owner_id, client_request_id):
        with self.cleanup_lock():
            self._check_request(owner_id, client_request_id)
            return super().find_idempotent(owner_id=owner_id, client_request_id=client_request_id)

    def create_task(self, **kwargs):
        with self.cleanup_lock():
            self._check_request(kwargs["owner_id"], kwargs["client_request_id"])
            return super().create_task(**kwargs)

    def transition(self, task_id, **kwargs):
        with self.cleanup_lock():
            return super().transition(task_id, **kwargs)


def _safe_tree(root):
    """Freeze only regular files; reject links, junctions and special files."""
    root = Path(root).absolute()
    for ancestor in (root, *root.parents):
        if _is_reparse_point(ancestor):
            raise ValueError("unsafe_resource_link")
    if root.resolve() != root:
        raise ValueError("unsafe_resource_path")
    if not root.exists():
        return []
    result = []
    if root.is_file():
        info = root.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            raise ValueError("unsafe_resource_type")
        return [(root, info.st_size, info.st_mtime_ns, info.st_ino)]
    for entry in sorted(root.iterdir()):
        if _is_reparse_point(entry):
            raise ValueError("unsafe_resource_link")
        if entry.is_dir():
            result.extend(_safe_tree(entry))
        elif entry.is_file():
            info = entry.lstat()
            if info.st_nlink > 1:
                raise ValueError("shared_resource_hardlink")
            result.append((entry, info.st_size, info.st_mtime_ns, info.st_ino))
        else:
            raise ValueError("unsafe_resource_type")
    return result


def _native_session_service(service):
    from core.web.services import session_service as native
    from core.web.services.session import directory_runtime
    directory_root = directory_runtime.directory_store_project_root()
    if (Path(native.PROJECT_ROOT).resolve() != service.project_root
            or Path(native.agent_directory_service._active_project_root()).resolve() != service.project_root
            or directory_root is not None and Path(directory_root).resolve() != service.project_root):
        raise ExternalAgentConflictError("Native Session owner changed", code="CLEANUP_OWNER_CHANGED")
    return native


def _owned_record(service, owner_id, task_id):
    service._require_gateway_enabled()
    record = service._owned_task(owner_id, task_id)
    service._require_cleanup_ownership(record)
    if record.get("status") not in TASK_TERMINAL_STATUSES:
        raise ExternalAgentConflictError("Only stopped terminal tasks can be cleaned", code="TASK_NOT_TERMINAL")
    if record.get("localCleanupComplete") is True:
        raise ExternalAgentAccessError("Task was cleaned", code="TASK_NOT_FOUND")
    return record


@contextmanager
def _cleanup_scope(service, owner_id, task_id):
    # Session admission -> chat state -> Agent lifecycle matches native mutation
    # ordering. Store writes are fenced only after lifecycle admission, avoiding
    # a cycle with a concurrently admitted start.
    record = _owned_record(service, owner_id, task_id)
    with ExitStack() as stack:
        session_id = record.get("sessionId")
        native = _native_session_service(service) if session_id else None
        if native is not None:
            for root in native._agent_session_workspace_roots():
                _safe_tree(Path(root).absolute() / native._safe_session_workspace_token(session_id))
            stack.enter_context(native._session_submit_admit_lock(session_id))
            stack.enter_context(native._CHAT_STATE_LOCK)
            stack.enter_context(native.agent_directory_service.agent_session_lifecycle_transaction())
        stack.enter_context(service._task_lock(task_id))
        stack.enter_context(service.store.cleanup_lock())
        current = _owned_record(service, owner_id, task_id)
        if current.get("sessionId") != session_id:
            raise ExternalAgentConflictError("Task Session changed", code="CLEANUP_STALE")
        if native is not None and _native_session_service(service) is not native:
            raise ExternalAgentConflictError("Native Session owner changed", code="CLEANUP_OWNER_CHANGED")
        authority = service.request_authority_fingerprint or service.authority_fingerprint()
        yield current, native, authority


def _session_plan(service, record, native):
    session_id = record.get("sessionId")
    if not session_id:
        return [], [], False, None
    raw = native.load_session_chat_state(native.PROJECT_ROOT, session_id)
    retry = record.get("localCleanupSessionDeleted") is True
    absent = raw is None and not retry
    if raw is not None:
        metadata = raw.get("metadata") or {}
        if (not isinstance(metadata, dict) or metadata.get("source") != "external_agent_task"
                or metadata.get("externalTaskId") != record["taskId"]
                or (raw.get("conversation_id") or raw.get("conversationId") or raw.get("id")) != session_id
                or (raw.get("agent_id") or raw.get("agentId")) != record["agentId"]
                or (raw.get("conversation_index_kind") or raw.get("conversationIndexKind")) != "hidden"):
            raise ValueError("session_ownership_unproven")
        if session_activity_policy({"status": _delete_session_control_phase(session_id, raw)})["blocksMutation"]:
            raise ValueError("session_active")
    elif absent and not service.cleanup_absent_sessions:
        raise ValueError("session_ownership_unproven")
    if absent and session_activity_policy({"status": _delete_session_control_phase(session_id, {})})["blocksMutation"]:
        raise ValueError("session_active")
    from core.web.services.session.admission_lock import session_has_active_work_run
    if session_has_active_work_run(native, session_id, record.get("turnId") or ""):
        raise ValueError("session_active")
    conversations = native.load_chat_state(native.PROJECT_ROOT).get("conversations") or []
    related_keys = ("parent_session_id", "parentSessionId", "root_session_id", "rootSessionId")
    if raw is not None and any(raw.get(key) for key in related_keys):
        raise ValueError("session_family_shared")
    if any(isinstance(item, dict) and any(item.get(key) == session_id for key in related_keys)
           for item in conversations):
        raise ValueError("session_family_shared")
    from core.web.services.session import directory_runtime
    directory_pin = directory_runtime.pin_open_directory_store(service.project_root) if absent else None
    directory_store = (directory_pin.store if directory_pin else None) if absent else directory_runtime.get_open_directory_store()
    if absent and directory_store is None:
        raise ValueError("session_ownership_unproven")
    if directory_store is not None:
        if absent and directory_store.repository.get_session_runtime_state(session_id) is not None:
            raise ValueError("session_ownership_unproven")
        row = directory_store.repository.get_session(session_id, include_archived=True)
        if absent and row is not None:
            raise ValueError("session_ownership_unproven")
        if (row and (row.get("agentId") != record["agentId"] or row.get("parentSessionId"))
                or directory_store.repository.list_child_sessions(session_id)):
            raise ValueError("session_directory_shared")
    if any(agent.get("directSessionId") == session_id for agent in
           native.agent_directory_service.list_agents(include_archived=True, detail="full")):
        raise ValueError("session_direct_binding")
    from vibelution_storage import resolve_project_runtime_home
    runtime = resolve_project_runtime_home(service.project_root)
    stores = {store.root: store for store in (service.store,
        ExternalAgentTaskStore(runtime / "external_agents"), ExternalAgentTaskStore(runtime / "local_assistant_tasks"))}
    for store in stores.values():
        for path in store.tasks_dir.glob("eat-*.json"):
            other = store._read_path(path)
            if other.get("sessionId") == session_id and (store.root != service.store.root or other.get("taskId") != record["taskId"]):
                raise ValueError("session_shared_by_task")
    token = native._safe_session_workspace_token(session_id)
    directories = []
    files = []
    for root in native._agent_session_workspace_roots():
        path = Path(root).absolute() / token
        if path.parent != Path(root).resolve() or path == service.project_root or path == Path(root):
            raise ValueError("unsafe_session_root")
        tree = _safe_tree(path)
        directories.append(path)
        if path.exists():
            files.extend(item for item in tree if item[0].relative_to(path).as_posix() not in _SESSION_GUARDS)
    # Missing legacy runtime and directory rows prove there is no native
    # Session to mutate, but cannot authorize deleting orphan content.
    if absent and files:
        raise ValueError("session_ownership_unproven")
    if directory_pin and not directory_runtime.directory_store_pin_is_current(directory_pin):
        raise ValueError("session_ownership_unproven")
    return directories, files, absent, directory_pin


def _git(root, *args):
    return git_process.run_git(list(args), cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _workspace_plan(service, record):
    if not service.cleanup_workspaces:
        return None, [], "legacy_workspace_not_owned"
    if record.get("localCleanupWorkspaceState") == "preparing":
        return None, [], "workspace_preparation_active"
    if record.get("localCleanupWorkspaceState") == "unknown":
        return None, [], "workspace_preparation_unconfirmed"
    raw = record.get("localWorkspacePath") or record.get("localCleanupWorkspacePath")
    if not raw:
        if record.get("localCleanupWorkspaceState") == "ready":
            return None, [], "workspace_ownership_unproven"
        return None, [], ""
    path = Path(raw).absolute()
    if path == service.project_root:
        return None, [], "shared_project_source"
    if not path.exists():
        return None, [], ""
    layout = resolve_branch_workspace(service.project_root)
    expected = layout.branch_pool / ("assistant-" + record["taskId"])
    branch = "codex/assistant-" + record["taskId"]
    if path != expected or path.resolve() != expected or path == layout.integration_root:
        return None, [], "workspace_ownership_unproven"
    for task_path in service.store.tasks_dir.glob("eat-*.json"):
        other = service.store._read_path(task_path)
        other_paths = [other.get(key) for key in ("localWorkspacePath", "localCleanupWorkspacePath") if other.get(key)]
        if (other.get("taskId") != record["taskId"]
                and any(Path(other_path).resolve() == path for other_path in other_paths)):
            return None, [], "workspace_shared_by_task"
    files = _safe_tree(path)
    main = layout.integration_root
    listing = _git(main, "worktree", "list", "--porcelain")
    if listing.returncode:
        raise ValueError("workspace_inspection_failed")
    registered = False
    for block in listing.stdout.split("\n\n"):
        lines = block.splitlines()
        if lines and lines[0] == "worktree " + path.as_posix():
            registered = "branch refs/heads/" + branch in lines and not any(line.startswith("locked") for line in lines)
    if not registered or _git(path, "rev-parse", "--show-toplevel").stdout.strip().replace("\\", "/").casefold() != path.as_posix().casefold():
        return None, [], "workspace_registration_changed"
    status = _git(path, "status", "--porcelain=v1", "--untracked-files=all", "--ignored")
    if status.returncode or status.stdout.strip():
        return None, [], "workspace_has_uncommitted_or_ignored_files"
    head = _git(path, "rev-parse", "HEAD")
    if head.returncode or _git(main, "merge-base", "--is-ancestor", head.stdout.strip(), "refs/heads/main").returncode:
        return None, [], "workspace_has_unmerged_commits"
    return {"path": path, "main": main, "branch": branch, "head": head.stdout.strip()}, files, ""


def _plan(service, record, native):
    retained, failures = [], []
    directories, session_files, workspace, workspace_files = [], [], None, []
    session_absent = False
    directory_pin = None
    if record.get("sessionId"):
        try:
            directories, session_files, session_absent, directory_pin = _session_plan(service, record, native)
            if session_absent:
                retained.append({"kind": "session_guards", "reason": "native_recovery_and_admission_guards"})
        except (ValueError, OSError) as exc:
            failures.append({"kind": "session", "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__})
    try:
        workspace, workspace_files, reason = _workspace_plan(service, record)
        if reason:
            # Shared resources intentionally outlive this task. An exclusive
            # workspace we cannot safely finish cleaning must keep its task
            # record reachable, rather than leave an orphan after deletion.
            destination = retained if reason in {"shared_project_source", "workspace_shared_by_task", "legacy_workspace_not_owned"} else failures
            destination.append({"kind": "workspace", "reason": reason})
    except (ValueError, OSError, RuntimeError) as exc:
        failures.append({"kind": "workspace", "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__})
    task_files = _safe_tree(service.store.task_path(record["taskId"]))
    resources = [{"kind": kind, "count": len(files), "bytes": sum(item[1] for item in files)}
                 for kind, files in (("task_record", task_files), ("session_files", session_files), ("workspace", workspace_files)) if files]
    retained.append({"kind": "shared_runtime_storage", "reason": "shared_database_and_git_objects"})
    retained.append({"kind": "cleanup_guard", "reason": "cross_process_cleanup_lock",
                     "bytes": (service.store.root / "cleanup.lock").stat().st_size})
    internal = {"directories": directories, "sessionFiles": session_files, "workspace": workspace,
                "workspaceFiles": workspace_files, "taskFiles": task_files, "failures": failures,
                "sessionAbsent": session_absent, "sessionDirectoryPin": directory_pin}
    fingerprint = _digest({"record": record, "files": [[str(path), size, modified, inode] for files in
        (task_files, session_files, workspace_files) for path, size, modified, inode in files], "retained": retained,
        "failures": failures, "sessionAbsent": session_absent,
        "sessionDirectoryGeneration": directory_pin.generation if directory_pin else None})
    return {"schemaVersion": 1, "taskId": record["taskId"], "revision": record["revision"],
            "status": "blocked" if failures else "ready",
            "fingerprint": fingerprint, "estimatedBytes": 0 if failures else sum(item["bytes"] for item in resources),
            "resources": [] if failures else resources, "retained": retained + failures}, internal


def _completed_cleanup(service, owner_id, task_id):
    """An authenticated retry may finish unlinking its host association."""
    service._require_gateway_enabled()
    with service.store.cleanup_lock():
        path = service.store.tombstone_path(task_id)
        record = service.store.cleanup_completion(task_id)
        if record is None:
            return None
        if (record.get("taskId") != task_id or not service.store.owner_matches(record, owner_id)
                or record.get("localAuthorityFingerprint") != service.authority_fingerprint()):
            return None
        return {"schemaVersion": 1, "taskId": task_id, "revision": record["cleanupRevision"],
            "status": "ready", "alreadyDeleted": True, "fingerprint": record["cleanupFingerprint"],
            "estimatedBytes": 0, "resources": [], "retained": [
                {"kind": "request_tombstone", "reason": "prevent_request_replay", "bytes": path.stat().st_size},
                {"kind": "cleanup_guard", "reason": "cross_process_cleanup_lock",
                 "bytes": (service.store.root / "cleanup.lock").stat().st_size}]}


def preview_task_cleanup(service, *, owner_id, task_id):
    try:
        with _cleanup_scope(service, owner_id, task_id) as (record, native, _authority):
            return _plan(service, record, native)[0]
    except ExternalAgentAccessError:
        completed = _completed_cleanup(service, owner_id, task_id)
        if completed is None:
            raise
        return completed


def _delete_session_files(native, record, directories, progress):
    session_id = record["sessionId"]
    if native.load_session_chat_state(native.PROJECT_ROOT, session_id) is not None:
        native.delete_chat_session_lightweight(session_id, activate_replacement=False)
    if (native.load_session_chat_state(native.PROJECT_ROOT, session_id) is not None
            or not native._is_session_workspace_intentionally_deleted(session_id)
            or not any((directory / ".session_deleted").is_file() for directory in directories)):
        raise ValueError("native_session_delete_unconfirmed")
    for directory in directories:
        for path, size, _modified, _inode in _safe_tree(directory):
            if path.relative_to(directory).as_posix() in _SESSION_GUARDS:
                progress["guardBytes"] += size
            else:
                # Revalidate all ancestors immediately before unlinking. Never
                # descend through a link introduced since the preview.
                _safe_tree(path)
                path.unlink()
                progress["released"] += size
        _prune_empty_directories(directory)


def _prune_empty_directories(directory, *, preserve_root=True):
    if not directory.exists():
        return
    _safe_tree(directory)
    for child in directory.iterdir():
        if _is_reparse_point(child):
            raise ValueError("unsafe_resource_link")
        if child.is_dir():
            _prune_empty_directories(child, preserve_root=False)
    if not preserve_root and not any(directory.iterdir()):
        directory.rmdir()


def cleanup_task(service, *, owner_id, task_id, revision, fingerprint):
    try:
        return _cleanup_task(service, owner_id=owner_id, task_id=task_id, revision=revision, fingerprint=fingerprint)
    except ExternalAgentAccessError:
        completed = _completed_cleanup(service, owner_id, task_id)
        if completed is None:
            raise
        if type(revision) is not int or revision != completed["revision"] or fingerprint != completed["fingerprint"]:
            raise ExternalAgentConflictError("Cleanup preview changed", code="CLEANUP_STALE")
        return {"schemaVersion": 1, "taskId": task_id, "status": "deleted", "alreadyDeleted": True,
                "releasedBytes": 0, "retained": completed["retained"], "failures": []}


def _accounting_snapshot(service, record, plan):
    """Freeze the exact logical-byte surfaces before any cleanup writes."""
    paths = [(service.store.task_path(record["taskId"]), "file"),
             (service.store.tombstone_path(record["taskId"]), "file")]
    paths.extend((directory, "directory") for directory in plan["directories"])
    if plan["workspace"]:
        paths.append((plan["workspace"]["path"], "directory"))
    surfaces = []
    for path, kind in paths:
        _safe_tree(path)
        try:
            info = path.lstat()
        except FileNotFoundError:
            identity = None
        else:
            identity = (info.st_dev, info.st_ino) if kind == "directory" else None
        surfaces.append((path, kind, identity))
    return surfaces, _accounting_bytes(surfaces)


def _accounting_bytes(surfaces):
    files = {}
    for path, kind, identity in surfaces:
        # lstat raises on unreadable paths rather than treating them as absent.
        # The same directory identity must survive until removal; replacing a
        # root cannot turn unrelated files into this task's accounting surface.
        try:
            info = path.lstat()
        except FileNotFoundError:
            _safe_tree(path)
            continue
        directory = stat.S_ISDIR(info.st_mode)
        if (directory != (kind == "directory")
                or directory and identity is not None and (info.st_dev, info.st_ino) != identity):
            raise ValueError("cleanup_accounting_path_changed")
        for entry, size, _modified, _inode in _safe_tree(path):
            files[entry] = size
    return sum(files.values())


def _cleanup_task(service, *, owner_id, task_id, revision, fingerprint):
    with _cleanup_scope(service, owner_id, task_id) as (record, native, authority):
        preview, plan = _plan(service, record, native)
        if type(revision) is not int or revision != record["revision"] or fingerprint != preview["fingerprint"]:
            raise ExternalAgentConflictError("Cleanup preview changed", code="CLEANUP_STALE")
        retained, failures, released = list(preview["retained"]), list(plan["failures"]), 0
        try:
            surfaces, bytes_before = _accounting_snapshot(service, record, plan)
        except (OSError, ValueError):
            return {"schemaVersion": 1, "taskId": task_id, "status": "blocked", "releasedBytes": 0,
                "retained": retained, "failures": failures + [
                    {"kind": "accounting", "reason": "cleanup_accounting_unavailable"}]}
        if plan["sessionDirectoryPin"] is not None:
            from core.web.services.session import directory_runtime
            if not directory_runtime.directory_store_pin_is_current(plan["sessionDirectoryPin"]):
                raise ExternalAgentConflictError("Native Session owner changed", code="CLEANUP_OWNER_CHANGED")
        if not failures and record.get("sessionId") and not plan["sessionAbsent"]:
            progress = {"released": 0, "guardBytes": 0}
            try:
                # Persist recovery proof before native deletion: a failed file
                # unlink must be retryable after its runtime row has gone.
                record = service.store.transition(task_id, status=record["status"], expected_revision=record["revision"],
                    fields={"localCleanupSessionDeleted": True})
                _delete_session_files(native, record, plan["directories"], progress)
            except Exception as exc:
                failures.append({"kind": "session", "reason": type(exc).__name__})
            released += progress["released"]
            retained.append({"kind": "session_guards", "reason": "native_recovery_and_admission_guards", "bytes": progress["guardBytes"]})
        workspace = plan["workspace"]
        if not failures and workspace:
            try:
                # Recheck after Session cleanup; git remove is never forced.
                current, files, reason = _workspace_plan(service, record)
                if reason or current != workspace:
                    raise ValueError("workspace_changed")
                result = _git(workspace["main"], "worktree", "remove", str(workspace["path"]))
                if result.returncode or workspace["path"].exists():
                    raise ValueError("workspace_remove_failed")
                released += sum(item[1] for item in files)
                branch_head = _git(workspace["main"], "rev-parse", "refs/heads/" + workspace["branch"])
                if branch_head.returncode or branch_head.stdout.strip() != workspace["head"]:
                    retained.append({"kind": "local_branch", "reason": "branch_changed"})
                elif _git(workspace["main"], "branch", "-d", workspace["branch"]).returncode:
                    retained.append({"kind": "local_branch", "reason": "branch_delete_failed"})
            except Exception as exc:
                failures.append({"kind": "workspace", "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__})
        if not failures:
            tombstone = {"schemaVersion": 1, "taskId": task_id, "ownerSubjectHash": record["ownerSubjectHash"],
                "requestKeyHash": _digest([record["ownerSubjectHash"], record.get("clientRequestId") or ""]),
                "localAuthorityFingerprint": authority,
                "cleanupRevision": revision, "cleanupFingerprint": fingerprint}
            path = service.store.tombstone_path(task_id)
            try:
                released += service.store.finish_cleanup(record, tombstone)
                retained.append({"kind": "request_tombstone", "reason": "prevent_request_replay", "bytes": path.stat().st_size})
            except OSError as exc:
                failures.append({"kind": "task_record", "reason": type(exc).__name__})
        if failures:
            # Keep the original task visible and retryable; never hide a partial
            # purge or save its full projection as a backup elsewhere.
            service.store.transition(task_id, status=record["status"], expected_revision=record["revision"],
                fields={"localCleanupStatus": "partial", "localCleanupFailureKinds": [item["kind"] for item in failures]})
        try:
            storage_delta = bytes_before - _accounting_bytes(surfaces)
        except (OSError, ValueError):
            storage_delta = 0
            failures.append({"kind": "accounting", "reason": "cleanup_accounting_unavailable"})
        return {"schemaVersion": 1, "taskId": task_id, "status": "partial" if failures and released else "blocked" if failures else "deleted",
                "releasedBytes": max(0, storage_delta), "storageDeltaBytes": storage_delta, "retained": retained, "failures": failures}
