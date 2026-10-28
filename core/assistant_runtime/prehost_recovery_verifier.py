"""Live readback of an original pre-host operation under source/target locks.

Private trusted-main use only. A successful read confirms an original
business receipt, not sender quiescence or authority to enable reminders.
"""
from __future__ import annotations

import re
import os
from contextlib import ExitStack, contextmanager
from itertools import islice
from pathlib import Path
from types import SimpleNamespace
import hashlib

from core.infrastructure.reminder_route_gate import HeldRouteGate
from core.infrastructure.reminder_source_mutex import try_acquire_reminder_source_mutex
from core.web.services.personal_assistant_project.windows_read import _locked_source
from .initial_migration_binding import read_initial_intent
from .migration_io import MigrationIOError, pinned_source_files, pinned_target_directory, read_stable_file, strict_json
from .migration_profile import offline_migration_profile
from .reminder_handoff_intent import read_handoff_intent
from .reminder_offline_worker import _matches_origin, _registry_digest_matches
from .reminder_source_identity import observe_reminder_source
from .reminder_uncertain_preparation import inspect_uncertainty_preparation, prepare_current_day_uncertainty

_SEAL = object()


class _HeldPreHostRecovery:
    def __init__(self, seal, project_id, revision, operation_id, check):
        if seal is not _SEAL:
            raise MigrationIOError("prehost_recovery_unavailable")
        self.project_id, self.revision, self.operation_id = project_id, revision, operation_id
        self._check, self._active = check, True

    def __call__(self):
        if not self._active:
            raise MigrationIOError("prehost_recovery_unavailable")
        return self._check()


def delete_exact_recovery_marker(*, path: Path, expected_sha256: str, expected_identity: dict,
                                 operation_id: str, commit_key: str, commit_mutex, verifier, before_delete) -> None:
    """Delete exactly the captured main marker while every proof remains held.

    Main must serialize revocation with the same cross-process commit mutex;
    before_delete is its private synchronous authorization handshake. This
    primitive alone is not authority to clear a registry recovery marker.
    """
    import ctypes
    from ctypes import wintypes
    from core.infrastructure.reminder_source_mutex import ReminderMutexLease
    from core.web.services.personal_assistant_project.windows_read import _api, _verify
    from .migration_io import check_path
    path = Path(path)
    if (not path.is_absolute() or not path.name.endswith('.prehost-recovery.json')
            or type(expected_sha256) is not str or re.fullmatch(r"[a-f0-9]{64}", expected_sha256) is None
            or type(expected_identity) is not dict or set(expected_identity) != {"device", "inode", "birthtimeNs"}
            or any(type(v) is not str or re.fullmatch(r"[1-9][0-9]{0,24}", v) is None for v in expected_identity.values())
            or type(operation_id) is not str or re.fullmatch(r"(?:initial|ksync|krec|affairs)-[a-f0-9]{40}", operation_id) is None
            or type(commit_key) is not str or re.fullmatch(r"[a-f0-9]{64}", commit_key) is None
            or commit_key != hashlib.sha256(("Vibelution.PrehostCommit.v1\0" + expected_sha256).encode("ascii")).hexdigest()
            or type(commit_mutex) is not ReminderMutexLease or commit_mutex.abandoned or commit_mutex._key != commit_key
            or type(verifier) is not _HeldPreHostRecovery or not verifier._active or verifier.operation_id != operation_id
            or not callable(before_delete)):
        raise MigrationIOError("prehost_marker_unavailable")
    api = _api()
    api.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    api.SetFileInformationByHandle.restype = wintypes.BOOL
    invalid = ctypes.c_void_p(-1).value
    with pinned_target_directory(path.parent):
        check_path(path)
        handle = api.CreateFileW(str(path), 0x80000000 | 0x10000, 1, None, 3, 0x00200000, None)
        if handle == invalid or handle is None:
            raise MigrationIOError("prehost_marker_unavailable")
        try:
            _verify(api, handle, path, directory=False)
            info = path.lstat()
            # Node's Windows stat.dev exposes the low 32-bit volume serial;
            # Python exposes the full volume serial. The native handle also
            # pins the exact parent and file throughout comparison/deletion.
            actual = {"device": str(info.st_dev & 0xffffffff), "inode": str(info.st_ino),
                      "birthtimeNs": str(getattr(info, "st_birthtime_ns", 0))}
            if actual != expected_identity or info.st_size < 1 or info.st_size > 16384:
                raise MigrationIOError("prehost_marker_unavailable")
            buffer, count = ctypes.create_string_buffer(info.st_size + 1), wintypes.DWORD()
            if not api.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None) or count.value != info.st_size:
                raise MigrationIOError("prehost_marker_unavailable")
            raw = buffer.raw[:count.value]
            record = strict_json(raw)
            if (hashlib.sha256(raw).hexdigest() != expected_sha256 or type(record) is not dict
                    or type(record.get("schemaVersion")) is not int or record.get("schemaVersion") != 1
                    or record.get("operationId") != operation_id or record.get("projectId") != verifier.project_id
                    or type(record.get("revision")) is not int or record.get("revision") != verifier.revision):
                raise MigrationIOError("prehost_marker_unavailable")
            # Main must create and fsync this durable recovery record before
            # dispatch and treat it as a closed gate on every restart. A lost
            # delete acknowledgement can otherwise look like no marker.
            pending = read_stable_file(path.with_name(path.name + ".commit-pending"), 4096)
            expected_pending = {"schemaVersion": 1, "projectId": verifier.project_id, "revision": verifier.revision,
                                "operationId": operation_id,
                                "markerSha256": expected_sha256, "state": "pending"}
            payload = strict_json(pending.raw)
            if (type(payload) is not dict or type(payload.get("schemaVersion")) is not int
                    or type(payload.get("revision")) is not int or payload != expected_pending):
                raise MigrationIOError("prehost_marker_unavailable")
            with pinned_source_files((pending,)):
                commit_mutex.check()
                if verifier().get("state") != "verified":
                    raise MigrationIOError("prehost_marker_unavailable")
                revoked = path.with_name(path.name + ".revoked")
                if revoked.exists() or revoked.is_symlink():
                    raise MigrationIOError("prehost_marker_unavailable")
                if before_delete() is not None:
                    raise MigrationIOError("prehost_marker_unavailable")
                commit_mutex.check()
                if revoked.exists() or revoked.is_symlink():
                    raise MigrationIOError("prehost_marker_unavailable")
                _verify(api, handle, path, directory=False)
                disposition = wintypes.BOOL(True)
                if not api.SetFileInformationByHandle(handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
                    raise MigrationIOError("prehost_marker_unavailable")
        finally:
            api.CloseHandle(handle)


def _knowledge_sync_receipt(root, intent, operation_id):
    from .knowledge_sync_receipt import read_knowledge_sync_receipt
    from scripts.assistant_migration_activate import verify_initial_knowledge_receipts
    from .initial_migration_binding import read_initial_intent
    claim = strict_json(read_stable_file(root / "initial_migration_claims" / operation_id / "claim.json", 16384).raw)
    if (type(claim) is not dict or type(claim.get("schemaVersion")) is not int
            or claim != {"schemaVersion": 1, "operationId": operation_id, "category": intent["category"]}):
        raise MigrationIOError("prehost_recovery_receipt_unknown")
    verify_initial_knowledge_receipts(root, intent["baselineMigrationId"])
    original_id = intent["originalSyncId"] if intent["category"] == "knowledge_recovery" else operation_id
    if intent["category"] == "knowledge_recovery":
        original = read_initial_intent(root, original_id)
        fixed = ("registeredProjectId", "sourceScope", "sourceIdentityDigest", "projectDirectory", "workspaceDirectory",
                 "targetDirectory", "targetAgentId", "targetSessionId", "baselineMigrationId")
        if original is None or original["category"] != "knowledge_sync" or any(original[k] != intent[k] for k in fixed):
            raise MigrationIOError("prehost_recovery_receipt_unknown")
        old_claim = strict_json(read_stable_file(root / "initial_migration_claims" / original_id / "claim.json", 16384).raw)
        if (type(old_claim) is not dict or type(old_claim.get("schemaVersion")) is not int
                or old_claim != {"schemaVersion": 1, "operationId": original_id, "category": "knowledge_sync"}):
            raise MigrationIOError("prehost_recovery_receipt_unknown")
    receipt = read_knowledge_sync_receipt(root, sync_id=original_id, baseline_id=intent["baselineMigrationId"],
                                         source_scope=intent["sourceScope"], target_agent_id=intent["targetAgentId"])
    if receipt["state"] != "completed":
        raise MigrationIOError("prehost_recovery_receipt_unknown")


@contextmanager
def held_prehost_recovery_verifier(*, dispatch, preview, project_id: str, revision: int, operation_id: str,
                                   select_original_config: bool = False):
    """Hold source routing, authority files and target profile until release.

    ``dispatch``/``preview`` must originate from the main-owned recovery Job's
    private binding. Never accept a renderer path or assert old senders ended.
    All checks and release run on this thread because the source mutex is
    thread-owned. A missing receipt never triggers a replay.
    """
    if (getattr(preview, "_dispatch", None) is not dispatch or type(revision) is not int
            or dispatch._registry_revision != revision or type(operation_id) is not str
            or re.fullmatch(r"(?:initial|ksync|krec|affairs)-[a-f0-9]{40}", operation_id) is None):
        raise MigrationIOError("prehost_recovery_unavailable")
    root = dispatch._admitted_projects().get(project_id)
    if root is None:
        raise MigrationIOError("prehost_recovery_unavailable")
    gate = HeldRouteGate(root)
    try:
        public = preview.preview(project_id)
        token = public["previewId"]
        with ExitStack() as stack:
            stack.callback(preview.discard, token)
            with preview._lock:
                preview.verify_preview(token)
                row = preview._previews[token]
                project, workspace, paths, authority = Path(row[3]), Path(row[4]), row[5], tuple(row[7])
                scope = {"projectId": paths.project_id, "instanceId": paths.instance_id, "agentId": public["assistantAgentId"]}
                for snapshot in authority:
                    stack.enter_context(_locked_source(Path(snapshot.path.anchor), snapshot.path, directory=False,
                                                       allow_child_replacement=True))
                preview.verify_preview(token)
            source = mutex = None
            if operation_id.startswith("affairs-"):
                source = stack.enter_context(observe_reminder_source(dispatch, preview, project_id, revision))
                mutex = try_acquire_reminder_source_mutex(source)
                if mutex is None or mutex.abandoned:
                    if mutex is not None:
                        mutex.release()
                    raise MigrationIOError("prehost_recovery_unavailable")
                stack.callback(mutex.release)
            def select_config(target_root):
                # The original intent is read while the route/source and host
                # owner locks are held, before native bootstrap consumes config.
                original = (read_handoff_intent(target_root, project_id) if operation_id.startswith("affairs-")
                            else read_initial_intent(target_root, operation_id))
                if (original is None or original["registeredProjectId"] != project_id
                        or original["revision"] > revision
                        or (original.get("syncId") if operation_id.startswith("affairs-") else original["operationId"]) != operation_id
                        or not _registry_digest_matches(authority, original["registryDigest"])
                        or not _matches_origin(original, SimpleNamespace(root=target_root, agent_id=original["targetAgentId"],
                            session_id=original["targetSessionId"]), scope, project, workspace, category=original["category"])):
                    raise MigrationIOError("prehost_recovery_unavailable")
                config = target_root / (".initial-migration-models-v1-" + original["operationId"]
                                        + "-" + original["registryDigest"] + ".toml")
                if Path(os.environ.get("VIBELUTION_CONFIG_PATH", "")) != config:
                    raise MigrationIOError("prehost_recovery_unavailable")
                if not config.exists() and not config.is_symlink() and original["category"] == "reminder_handoff":
                    # Only the native-authorized handoff may initialize its
                    # missing auxiliary snapshot. Existing snapshots are never
                    # replaced when the operator later changes model settings.
                    from scripts.assistant_migration_activate import prepare_initial_model_config
                    prepare_initial_model_config(preview._config, target_root, config,
                                                 original["operationId"], original["registryDigest"])
                snapshot = read_stable_file(config, 16 * 1024 * 1024)
                stack.enter_context(pinned_source_files([snapshot]))
                os.environ["VIBELUTION_CONFIG_PATH"] = str(snapshot.path)
                os.environ["VIBELUTION_CONFIG_HOME"] = str(snapshot.path.parent)
            target = stack.enter_context(offline_migration_profile(before_bootstrap=select_config if select_original_config else None))
            if operation_id.startswith("affairs-"):
                intent = read_handoff_intent(target.root, project_id)
                category = "reminder_handoff"
                if intent is None or intent["syncId"] != operation_id:
                    raise MigrationIOError("prehost_recovery_unavailable")
            else:
                intent = read_initial_intent(target.root, operation_id)
                if intent is None or intent["registeredProjectId"] != project_id:
                    raise MigrationIOError("prehost_recovery_unavailable")
                category = intent["category"]
            if (intent["revision"] > revision or not _matches_origin(intent, target, scope, project, workspace, category=category)
                    or not _registry_digest_matches(authority, intent["registryDigest"])):
                raise MigrationIOError("prehost_recovery_unavailable")
            def check():
                gate.check()
                preview.verify_preview(token)
                target.check()
                if mutex is not None:
                    mutex.check()
                current = (read_handoff_intent(target.root, project_id) if category == "reminder_handoff"
                           else read_initial_intent(target.root, operation_id))
                if current != intent:
                    raise MigrationIOError("prehost_recovery_unavailable")
                from scripts.assistant_migration_activate import verify_initial_personal_receipts, verify_initial_knowledge_receipts
                if category == "personal":
                    verify_initial_personal_receipts(target.root, operation_id)
                elif category == "knowledge":
                    verify_initial_knowledge_receipts(target.root, operation_id)
                elif category in ("knowledge_sync", "knowledge_recovery"):
                    _knowledge_sync_receipt(target.root, intent, operation_id)
                elif category == "reminder_handoff":
                    folder = target.root / "reminder_handoff_preparations"
                    matches = []
                    with pinned_target_directory(folder):
                        entries = list(islice(folder.glob("*.intent.json"), 513))
                        if len(entries) > 512:
                            raise MigrationIOError("prehost_recovery_receipt_unknown")
                        for path in entries:
                            original = path.name[:-len(".intent.json")]
                            status = inspect_uncertainty_preparation(target=target, operation_id=original)
                            item = strict_json(read_stable_file(path, 1024 * 1024).raw)
                            if item["syncId"] == operation_id:
                                if status["recordedState"] != "prepared":
                                    raise MigrationIOError("prehost_recovery_receipt_unknown")
                                matches.append(original)
                    if len(matches) != 1:
                        raise MigrationIOError("prehost_recovery_receipt_unknown")
                    result = prepare_current_day_uncertainty(source=source, source_mutex=mutex, target=target,
                                                             sync_id=operation_id, recovery_id=matches[0])
                    if result["created"] != 0:
                        raise MigrationIOError("prehost_recovery_receipt_unknown")
                else:
                    raise MigrationIOError("prehost_recovery_receipt_unknown")
                gate.check()
                preview.verify_preview(token)
                target.check()
                if mutex is not None:
                    mutex.check()
                return {"schemaVersion": 1, "projectId": project_id, "operationId": operation_id,
                        "revision": revision, "state": "verified", "unmanagedSenders": "unknown", "readyForCutover": False}
            check()
            capability = _HeldPreHostRecovery(_SEAL, project_id, revision, operation_id, check)
            try:
                yield capability
            finally:
                capability._active = False
    finally:
        gate.release()
