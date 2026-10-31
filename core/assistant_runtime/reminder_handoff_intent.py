"""Immutable, native-authorized reminder handoff request; never a sender proof."""
import hashlib
import json
import re
import secrets
from itertools import islice
from pathlib import Path

from .migration_io import MigrationIOError, check_path, migration_target_lock, path_identity, pinned_target_directory, publish_directory, read_stable_file, strict_json
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


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def _head(root, name, original, *, owned_pending=None):
    """Read one complete, unambiguous immutable authorization chain under the intent lock."""
    refreshes = Path(root) / "reminder_handoff_intent_refreshes"
    chain = refreshes / name
    head = _digest(original)
    if refreshes.exists() or refreshes.is_symlink():
        check_path(refreshes)
        if not refreshes.is_dir():
            raise MigrationIOError("reminder_handoff_invalid")
    if not chain.exists() and not chain.is_symlink():
        return original, head
    links = {}
    with pinned_target_directory(chain):
        for index, entry in enumerate(chain.iterdir()):
            if owned_pending is not None and entry == owned_pending[0]:
                _, directory_identity, file_identity, raw = owned_pending
                with pinned_target_directory(entry):
                    if (path_identity(entry) != directory_identity
                            or {p.name for p in islice(entry.iterdir(), 2)} != {"intent.json"}
                            or path_identity(entry / "intent.json") != file_identity
                            or read_stable_file(entry / "intent.json", 32768).raw != raw):
                        raise MigrationIOError("reminder_handoff_invalid")
                continue
            if index >= 128 or re.fullmatch(r"[a-f0-9]{64}", entry.name) is None:
                raise MigrationIOError("reminder_handoff_invalid")
            with pinned_target_directory(entry):
                if {p.name for p in islice(entry.iterdir(), 2)} != {"intent.json"}:
                    raise MigrationIOError("reminder_handoff_invalid")
                record = strict_json(read_stable_file(entry / "intent.json", 32768).raw)
            if (type(record) is not dict or set(record) != {"schemaVersion", "parentSha256", "binding"}
                    or type(record["schemaVersion"]) is not int or record["schemaVersion"] != 1
                    or type(record["parentSha256"]) is not str
                    or re.fullmatch(r"[a-f0-9]{64}", record["parentSha256"]) is None
                    or _digest(record) != entry.name):
                raise MigrationIOError("reminder_handoff_invalid")
            binding = _validate(record["binding"])
            fixed = set(original) - {"turnId", "revision", "registryDigest"}
            if (any(binding[key] != original[key] for key in fixed)
                    or record["parentSha256"] in links):
                raise MigrationIOError("reminder_handoff_invalid")
            links[record["parentSha256"]] = (entry.name, binding)
    seen = set()
    current = original
    while head in links:
        if head in seen:
            raise MigrationIOError("reminder_handoff_invalid")
        seen.add(head)
        next_head, successor = links[head]
        if successor["registryDigest"] == current["registryDigest"]:
            raise MigrationIOError("reminder_handoff_invalid")
        head, current = next_head, successor
    if len(seen) != len(links):
        raise MigrationIOError("reminder_handoff_invalid")
    return current, head


def _read_authorization(root, directory, project_id, *, owned_pending=None):
    name = hashlib.sha256(handoff_id(project_id).encode()).hexdigest()
    entry = directory / name
    if not entry.exists() and not entry.is_symlink():
        refreshes = Path(root) / "reminder_handoff_intent_refreshes"
        if refreshes.exists() or refreshes.is_symlink():
            check_path(refreshes)
            if not refreshes.is_dir():
                raise MigrationIOError("reminder_handoff_invalid")
        chain = refreshes / name
        if chain.exists() or chain.is_symlink():
            raise MigrationIOError("reminder_handoff_invalid")
        return None, None
    with pinned_target_directory(entry):
        if {p.name for p in islice(entry.iterdir(), 2)} != {"intent.json"}:
            raise MigrationIOError("reminder_handoff_invalid")
        row = _validate(strict_json(read_stable_file(entry / "intent.json", 16384).raw))
        if row["registeredProjectId"] != project_id:
            raise MigrationIOError("reminder_handoff_invalid")
    return _head(root, name, row, owned_pending=owned_pending)


def read_handoff_authorization(root, project_id):
    """Return the effective authorization and its chain digest, or (None, None)."""
    directory = Path(root) / "reminder_handoff_intents"
    if not directory.exists() and not directory.is_symlink():
        refreshes = Path(root) / "reminder_handoff_intent_refreshes"
        if refreshes.exists() or refreshes.is_symlink():
            raise MigrationIOError("reminder_handoff_invalid")
        return None, None
    with pinned_target_directory(directory), migration_target_lock(directory):
        for index, entry in enumerate(directory.iterdir()):
            if index >= 512 or entry.name.startswith(".pending-"):
                raise MigrationIOError("reminder_handoff_publication_unknown")
        return _read_authorization(root, directory, project_id)


def read_handoff_intent(root, project_id):
    return read_handoff_authorization(root, project_id)[0]


def _unstarted(root, binding, owner_check):
    """Fail closed on any known old execution artifact while profile ownership is held."""
    if not callable(owner_check) or owner_check() is not True:
        raise MigrationIOError("reminder_handoff_owner_unavailable")
    root = Path(root)
    digest = hashlib.sha256(binding["syncId"].encode()).hexdigest()
    artifacts = (root / "reminder_offline_operations" / (digest + ".intent.json"),
                 root / "reminder_offline_operations" / (digest + ".sync-intent.json"),
                 root / "initial_migration_claims" / binding["operationId"],
                 root / "history_sources" / "migrations" / binding["syncId"],
                 root / "history_sources" / "migrations" / (".pending-" + binding["syncId"]),
                 root / "affairs_conflicts" / (digest + ".json"),
                 root / "affairs_migrations" / (digest + ".json"),
                 root / "affairs_sync_receipts" / (digest + ".json"))
    for path in artifacts:
        parent = path.parent
        # Even a broken/replaced intermediate directory must not look absent.
        while parent != root and not parent.exists() and not parent.is_symlink():
            parent = parent.parent
        check_path(parent)
        if not parent.is_dir():
            raise MigrationIOError("reminder_handoff_started_unknown")
        if path.exists() or path.is_symlink():
            raise MigrationIOError("reminder_handoff_started_unknown")
    preparations = root / "reminder_handoff_preparations"
    if preparations.exists() or preparations.is_symlink():
        with pinned_target_directory(preparations):
            if next(preparations.iterdir(), None) is not None:
                raise MigrationIOError("reminder_handoff_started_unknown")
    # The everyday reminder receipt database is shared and cannot be attributed
    # to this sync by itself. It never proves sender quiescence or cutover.
    prefix = ".initial-migration-models-v1-" + binding["operationId"] + "-"
    with pinned_target_directory(root):
        for index, entry in enumerate(root.iterdir()):
            if index >= 4096 or entry.name.casefold().startswith(prefix.casefold()):
                raise MigrationIOError("reminder_handoff_started_unknown")
    if owner_check() is not True:
        raise MigrationIOError("reminder_handoff_owner_unavailable")


def publish_handoff_intent(root, binding, token, verify, *, expected_head=None, owner_check=None):
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
            previous, head = _read_authorization(root, directory, binding["registeredProjectId"])
            fixed = set(previous) - {"turnId", "revision", "registryDigest"}
            if (type(expected_head) is not str or expected_head != head
                    or any(binding[key] != previous[key] for key in fixed)
                    or binding["registryDigest"] == previous["registryDigest"]):
                raise MigrationIOError("reminder_handoff_already_registered")
            _unstarted(root, binding, owner_check)
            record = {"schemaVersion": 1, "parentSha256": head, "binding": binding}
            raw = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
            chain = Path(root) / "reminder_handoff_intent_refreshes" / name
            with pinned_target_directory(chain, create=True):
                if len(list(islice(chain.iterdir(), 128))) >= 128:
                    raise MigrationIOError("reminder_handoff_invalid")
                pending = chain / (".pending-" + secrets.token_hex(16))
                def recheck(owned_pending):
                    _unstarted(root, binding, owner_check)
                    if _read_authorization(root, directory, binding["registeredProjectId"],
                                           owned_pending=owned_pending) != (previous, head):
                        raise MigrationIOError("reminder_handoff_invalid")
                return _publish(pending, chain / _digest(record), raw, token, verify,
                                recheck, binding)
        if expected_head is not None:
            raise MigrationIOError("reminder_handoff_invalid")
        # An orphaned chain must never become authority for a newly created base.
        _read_authorization(root, directory, binding["registeredProjectId"])
        pending = directory / (".pending-" + secrets.token_hex(16))
        return _publish(pending, final, raw, token, verify, lambda _: None, binding)


def _publish(pending, final, raw, token, verify, recheck, binding):
    with pinned_target_directory(pending, create=True):
        _write_new(pending / "intent.json", raw)
        identity = path_identity(pending)
        file_identity = path_identity(pending / "intent.json")
    publication_started = False
    def commit():
        nonlocal publication_started
        verify()
        recheck((pending, identity, file_identity, raw))
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
