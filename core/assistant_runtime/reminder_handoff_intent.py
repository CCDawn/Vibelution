"""Immutable, native-authorized reminder handoff request; never a sender proof."""
import hashlib
import json
import re
import secrets
from pathlib import Path

from .migration_io import MigrationIOError, migration_target_lock, path_identity, pinned_target_directory, publish_directory, read_stable_file, strict_json
from .migration_history import _write_new


def _remove_owned_pending(pending, directory_identity, file_identity, raw):
    """Remove only this invocation's unchanged staging object by Windows handles."""
    import ctypes
    from ctypes import wintypes
    from core.web.services.personal_assistant_project.windows_read import _api, _verify

    api = _api()
    api.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    api.SetFileInformationByHandle.restype = wintypes.BOOL
    invalid = ctypes.c_void_p(-1).value
    directory_handle = file_handle = None
    try:
        # Omitting FILE_SHARE_DELETE pins both exact objects against replacement.
        directory_handle = api.CreateFileW(str(pending), 0x80000000 | 0x10000, 3, None, 3, 0x02200000, None)
        if directory_handle == invalid:
            return False
        _verify(api, directory_handle, pending, directory=True)
        if path_identity(pending) != directory_identity or {item.name for item in pending.iterdir()} != {"intent.json"}:
            return False
        path = pending / "intent.json"
        # Deny both write and delete sharing while authenticating and removing
        # the captured file, so changed user content is never unlinked.
        file_handle = api.CreateFileW(str(path), 0x80000000 | 0x10000, 1, None, 3, 0x02200000, None)
        if file_handle == invalid:
            return False
        _verify(api, file_handle, path, directory=False)
        if path_identity(path) != file_identity:
            return False
        buffer = ctypes.create_string_buffer(len(raw) + 1)
        read = wintypes.DWORD()
        if not api.ReadFile(file_handle, buffer, len(buffer), ctypes.byref(read), None) or buffer.raw[:read.value] != raw:
            return False
        disposition = wintypes.BOOL(True)
        if not api.SetFileInformationByHandle(file_handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
            return False
        api.CloseHandle(file_handle)
        file_handle = None
        _verify(api, directory_handle, pending, directory=True)
        if any(pending.iterdir()):
            return False
        if not api.SetFileInformationByHandle(directory_handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
            return False
        return True
    except Exception:
        return False
    finally:
        if file_handle and file_handle != invalid:
            api.CloseHandle(file_handle)
        if directory_handle and directory_handle != invalid:
            api.CloseHandle(directory_handle)


def handoff_id(project_id):
    return "initial-" + hashlib.sha256((project_id + ":reminder_handoff").encode()).hexdigest()[:40]


def sync_id(project_id):
    return "affairs-" + hashlib.sha256((project_id + ":reminder_handoff").encode()).hexdigest()[:40]


def _validate(value):
    keys = {"schemaVersion", "registeredProjectId", "sourceScope", "category", "turnId", "operationId", "syncId", "revision",
            "sourceIdentityDigest", "registryDigest", "targetIdentityDigest", "projectDirectory", "workspaceDirectory", "targetDirectory",
            "targetAgentId", "targetSessionId", "authority", "baselineId", "baselineState", "readyForCutover"}
    opaque = lambda x: isinstance(x, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", x) is not None
    if (type(value) is not dict or set(value) != keys or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1
            or not opaque(value["registeredProjectId"]) or not opaque(value["turnId"]) or not opaque(value["targetAgentId"])
            or not opaque(value["targetSessionId"]) or value["category"] != "reminder_handoff"
            or value["operationId"] != handoff_id(value["registeredProjectId"]) or value["syncId"] != sync_id(value["registeredProjectId"])
            or type(value["revision"]) is not int or not 0 <= value["revision"] <= 2**53 - 1
            or value["authority"] != "native_policy_admitted" or value["baselineId"] is not None
            or value["baselineState"] != "unknown" or value["readyForCutover"] is not False):
        raise MigrationIOError("reminder_handoff_invalid")
    scope = value["sourceScope"]
    if type(scope) is not dict or set(scope) != {"projectId", "instanceId", "agentId"} or not all(opaque(x) for x in scope.values()):
        raise MigrationIOError("reminder_handoff_invalid")
    for key in ("sourceIdentityDigest", "registryDigest", "targetIdentityDigest"):
        if type(value[key]) is not str or re.fullmatch(r"[a-f0-9]{64}", value[key]) is None:
            raise MigrationIOError("reminder_handoff_invalid")
    for key in ("projectDirectory", "workspaceDirectory", "targetDirectory"):
        item = value[key]
        if (type(item) is not dict or set(item) != {"device", "inode", "birthtimeNs"}
                or any(type(x) is not str or re.fullmatch(r"[1-9][0-9]{0,24}", x) is None for x in item.values())):
            raise MigrationIOError("reminder_handoff_invalid")
    return value


def read_handoff_intent(root, project_id):
    directory = Path(root) / "reminder_handoff_intents"
    if not directory.exists() and not directory.is_symlink():
        return None
    name = hashlib.sha256(handoff_id(project_id).encode()).hexdigest()
    with pinned_target_directory(directory), migration_target_lock(directory):
        entry = directory / name
        if not entry.exists() and not entry.is_symlink():
            return None
        with pinned_target_directory(entry):
            if {p.name for p in entry.iterdir()} != {"intent.json"}:
                raise MigrationIOError("reminder_handoff_invalid")
            row = _validate(strict_json(read_stable_file(entry / "intent.json", 16384).raw))
            if row["registeredProjectId"] != project_id:
                raise MigrationIOError("reminder_handoff_invalid")
            return row


def publish_handoff_intent(root, binding, token, verify):
    binding = _validate(binding)
    if not callable(getattr(token, "publish", None)) or not callable(verify):
        raise MigrationIOError("reminder_handoff_invalid")
    directory = Path(root) / "reminder_handoff_intents"
    name = hashlib.sha256(binding["operationId"].encode()).hexdigest()
    raw = json.dumps(binding, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    with pinned_target_directory(directory, create=True), migration_target_lock(directory):
        # An interrupted staging directory is not proof that the original
        # publication failed. Its random name cannot establish which request
        # owns it, so no new publication may pass until it is reconciled.
        for index, entry in enumerate(directory.iterdir()):
            if index >= 512 or entry.name.startswith(".pending-"):
                raise MigrationIOError("reminder_handoff_publication_unknown")
        final = directory / name
        if final.exists() or final.is_symlink():
            raise MigrationIOError("reminder_handoff_already_registered")
        pending = directory / (".pending-" + secrets.token_hex(16))
        with pinned_target_directory(pending, create=True):
            _write_new(pending / "intent.json", raw)
            identity = path_identity(pending)
            file_identity = path_identity(pending / "intent.json")
        publication_started = False
        def commit():
            nonlocal publication_started
            verify()
            token.check()
            publication_started = True
            publish_directory(pending, final, identity)
        try:
            token.publish(commit)
        except BaseException:
            if not publication_started:
                _remove_owned_pending(pending, identity, file_identity, raw)
            raise
    return binding
