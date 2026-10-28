"""Main-only identity proofs for a later, separately authorized offline import."""
from __future__ import annotations

import hashlib
from itertools import islice
import json
import re
import secrets
import stat
from pathlib import Path

from .migration_io import MigrationIOError, check_path, verify_snapshot
from .migration_paths import _identity_chain


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def _directory(path):
    path = check_path(Path(path))
    info = path.lstat()
    birth = getattr(info, "st_birthtime_ns", None)
    if (not stat.S_ISDIR(info.st_mode) or info.st_dev <= 0 or info.st_ino <= 0
            or type(birth) is not int or birth <= 0):
        raise MigrationIOError("initial_migration_directory_identity_unavailable")
    return {"device": str(info.st_dev), "inode": str(info.st_ino), "birthtimeNs": str(birth)}


def _chain(path):
    path = Path(path)
    chain = _identity_chain(path)
    if not chain or chain[-1][0] != path:
        raise MigrationIOError("initial_migration_directory_identity_unavailable")
    # Directory contents may legitimately change while the same directory
    # remains authoritative; the endpoint has its own stable identity above.
    return [[str(node), list(identity)] for node, identity in chain[:-1]]


def source_identity(scope, project, workspace):
    project_identity, workspace_identity = _directory(project), _directory(workspace)
    digest = _digest({"schemaVersion": 1, "sourceScope": scope, "project": project_identity,
                      "workspace": workspace_identity, "projectChain": _chain(project), "workspaceChain": _chain(workspace)})
    return digest, project_identity, workspace_identity


def target_identity(root, agent_id, session_id):
    identity = _directory(root)
    return _digest({"schemaVersion": 1, "agentId": agent_id, "sessionId": session_id,
                    "root": identity, "rootChain": _chain(root)}), identity


def authority_identity(snapshots):
    if not snapshots:
        raise MigrationIOError("source_authority_required")
    rows = []
    for snapshot in snapshots:
        verify_snapshot(snapshot)
        rows.append([str(snapshot.path), snapshot.sha256, len(snapshot.raw), list(snapshot.identity)])
    return _digest(sorted(rows, key=lambda row: row[0].casefold()))


def _intent_anchor(binding):
    # Session repair and re-registration must not create a new execution
    # authority for the same physical source, target profile and category.
    keys = ("sourceScope", "projectDirectory", "workspaceDirectory", "targetDirectory", "targetAgentId", "category")
    if binding["category"] in ("knowledge_sync", "knowledge_recovery"):
        keys += ("operationId",)
    return _digest({key: binding[key] for key in keys})


def _validate_intent(binding):
    from .main_control import _opaque, initial_migration_id, knowledge_sync_id, knowledge_recovery_id
    keys = {"schemaVersion", "registeredProjectId", "sourceScope", "category", "turnId", "operationId",
            "revision", "sourceIdentityDigest", "registryDigest", "targetIdentityDigest", "projectDirectory",
            "workspaceDirectory", "targetDirectory", "targetAgentId", "targetSessionId", "authority", "readyForCutover"}
    if type(binding) is dict and binding.get("category") in ("knowledge_sync", "knowledge_recovery"):
        keys |= {"previewId", "baselineMigrationId"}
        if binding["category"] == "knowledge_recovery":
            keys.add("originalSyncId")
    if (type(binding) is not dict or set(binding) != keys or type(binding["schemaVersion"]) is not int
            or binding["schemaVersion"] != 1):
        raise MigrationIOError("initial_intent_invalid")
    scope = binding["sourceScope"]
    if (type(scope) is not dict or set(scope) != {"projectId", "instanceId", "agentId"}
            or not all(_opaque(v, 160) for v in scope.values())
            or not all(_opaque(binding[k], 160) for k in ("registeredProjectId", "turnId", "targetAgentId", "targetSessionId"))
            or binding["category"] not in ("personal", "knowledge", "knowledge_sync", "knowledge_recovery")
            or (binding["category"] in ("personal", "knowledge") and binding["operationId"] != initial_migration_id(binding["registeredProjectId"], "", binding["category"]))
            or (binding["category"] in ("knowledge_sync", "knowledge_recovery") and (type(binding["previewId"]) is not str
                or re.fullmatch(r"[a-f0-9]{64}", binding["previewId"]) is None
                or (binding["category"] == "knowledge_sync" and binding["operationId"] != knowledge_sync_id(binding["registeredProjectId"], binding["previewId"]))
                or (binding["category"] == "knowledge_recovery" and (type(binding["originalSyncId"]) is not str
                    or re.fullmatch(r"ksync-[a-f0-9]{40}", binding["originalSyncId"]) is None
                    or binding["operationId"] != knowledge_recovery_id(binding["registeredProjectId"], binding["previewId"], binding["originalSyncId"])))
                or binding["baselineMigrationId"] != initial_migration_id(binding["registeredProjectId"], "", "knowledge")))
            or type(binding["revision"]) is not int or not 0 <= binding["revision"] <= 2**53 - 1
            or binding["authority"] != "native_policy_admitted" or binding["readyForCutover"] is not False):
        raise MigrationIOError("initial_intent_invalid")
    for key in ("sourceIdentityDigest", "registryDigest", "targetIdentityDigest"):
        if type(binding[key]) is not str or re.fullmatch(r"[a-f0-9]{64}", binding[key]) is None:
            raise MigrationIOError("initial_intent_invalid")
    for key in ("projectDirectory", "workspaceDirectory", "targetDirectory"):
        identity = binding[key]
        if (type(identity) is not dict or set(identity) != {"device", "inode", "birthtimeNs"}
                or any(type(v) is not str or re.fullmatch(r"[1-9][0-9]{0,24}", v) is None for v in identity.values())):
            raise MigrationIOError("initial_intent_invalid")
    return binding


def _read_intents(directory):
    from .migration_io import check_path, read_stable_file, strict_json
    result, ids = {}, set()
    for index, path in enumerate(directory.iterdir()):
        if index >= 512:
            raise MigrationIOError("initial_intent_limit")
        if path.name.startswith(".pending-"):
            # A pending directory is never execution authority.
            check_path(path)
            continue
        if re.fullmatch(r"[a-f0-9]{64}", path.name) is None:
            raise MigrationIOError("initial_intent_invalid")
        check_path(path)
        if not path.is_dir() or {p.name for p in islice(path.iterdir(), 2)} != {"intent.json"}:
            raise MigrationIOError("initial_intent_invalid")
        binding = _validate_intent(strict_json(read_stable_file(path / "intent.json", 16384).raw))
        if _intent_anchor(binding) != path.name or binding["operationId"] in ids:
            raise MigrationIOError("initial_intent_invalid")
        ids.add(binding["operationId"])
        result[path.name] = binding
    return result


def _intent_heads(directory, bases, *, with_ids=False):
    """Validate every immutable authorization successor; never guess a head."""
    from .migration_io import check_path, pinned_target_directory, read_stable_file, strict_json
    root = directory.parent / "initial_migration_intent_refreshes"
    heads = {key: _digest(value) for key, value in bases.items()}
    if not root.exists() and not root.is_symlink():
        return (bases, heads) if with_ids else bases
    result = dict(bases)
    total_entries = total_bytes = 0
    with pinned_target_directory(root):
        for index, chain in enumerate(root.iterdir()):
            if index >= 512 or chain.name not in bases:
                raise MigrationIOError("initial_intent_invalid")
            check_path(chain)
            if not chain.is_dir():
                raise MigrationIOError("initial_intent_invalid")
            links = {}
            with pinned_target_directory(chain):
                for n, item in enumerate(chain.iterdir()):
                    total_entries += 1
                    if n >= 128 or total_entries > 4096:
                        raise MigrationIOError("initial_intent_limit")
                    if item.name.startswith(".pending-"):
                        check_path(item)
                        continue
                    if re.fullmatch(r"[a-f0-9]{64}", item.name) is None:
                        raise MigrationIOError("initial_intent_invalid")
                    check_path(item)
                    if not item.is_dir() or {p.name for p in islice(item.iterdir(), 2)} != {"intent.json"}:
                        raise MigrationIOError("initial_intent_invalid")
                    snapshot = read_stable_file(item / "intent.json", 32768)
                    total_bytes += len(snapshot.raw)
                    if total_bytes > 32 * 1024 * 1024:
                        raise MigrationIOError("initial_intent_limit")
                    record = strict_json(snapshot.raw)
                    if (type(record) is not dict or set(record) != {"schemaVersion", "parentSha256", "binding"}
                            or type(record["schemaVersion"]) is not int or record["schemaVersion"] != 1
                            or type(record["parentSha256"]) is not str
                            or re.fullmatch(r"[a-f0-9]{64}", record["parentSha256"]) is None
                            or _digest(record) != item.name):
                        raise MigrationIOError("initial_intent_invalid")
                    binding = _validate_intent(record["binding"])
                    original = bases[chain.name]
                    fixed = ("registeredProjectId", "sourceScope", "category", "operationId", "projectDirectory",
                             "workspaceDirectory", "targetDirectory", "targetAgentId")
                    if (any(binding[key] != original[key] for key in fixed)
                            or _intent_anchor(binding) != chain.name or record["parentSha256"] in links):
                        raise MigrationIOError("initial_intent_invalid")
                    links[record["parentSha256"]] = (item.name, binding)
            parent = _digest(bases[chain.name])
            seen = set()
            while parent in links:
                if parent in seen:
                    raise MigrationIOError("initial_intent_invalid")
                seen.add(parent)
                parent, result[chain.name] = links[parent]
            if len(seen) != len(links):
                raise MigrationIOError("initial_intent_invalid")
            heads[chain.name] = parent
    return (result, heads) if with_ids else result


def read_initial_intent(profile_root, operation_id):
    """Trusted main-only recovery. Absence does not prove no business write."""
    from .migration_io import migration_target_lock, pinned_target_directory
    if type(operation_id) is not str or re.fullmatch(r"(?:initial|ksync|krec)-[a-f0-9]{40}", operation_id) is None:
        raise MigrationIOError("initial_intent_invalid")
    directory = Path(profile_root) / "initial_migration_intents"
    if not directory.exists() and not directory.is_symlink():
        refreshes = directory.parent / "initial_migration_intent_refreshes"
        if refreshes.exists() or refreshes.is_symlink():
            raise MigrationIOError("initial_intent_invalid")
        return None
    with pinned_target_directory(directory), migration_target_lock(directory):
        return next((value for value in _intent_heads(directory, _read_intents(directory)).values()
                     if value["operationId"] == operation_id), None)


def list_initial_intents(profile_root):
    """List only published references; callers must hold the host-owner lock.

    An absent entry says nothing about in-flight publishers unless ownership
    has first been acquired. Pending objects are never execution authority.
    """
    from .migration_io import migration_target_lock, pinned_target_directory
    directory = Path(profile_root) / "initial_migration_intents"
    if not directory.exists() and not directory.is_symlink():
        refreshes = directory.parent / "initial_migration_intent_refreshes"
        if refreshes.exists() or refreshes.is_symlink():
            raise MigrationIOError("initial_intent_invalid")
        return []
    with pinned_target_directory(directory), migration_target_lock(directory):
        rows = _intent_heads(directory, _read_intents(directory)).values()
        return sorted(({key: row[key] for key in ("operationId", "registeredProjectId", "category", "registryDigest")}
                       for row in rows), key=lambda row: row["operationId"])


def publish_initial_intent(profile_root, binding, token, verify, *, owner_check=None):
    """Persist immutable authority while the caller holds native/source guards.

    The token orders publication with timeout, cancellation and broker close.
    A lost response is unknown; recover only with the original operation ID.
    """
    from .migration_history import _write_new
    from .migration_io import (migration_target_lock, path_identity, pinned_target_directory, publish_directory,
                               read_stable_file, strict_json)
    binding = _validate_intent(binding)
    if not callable(getattr(token, "publish", None)) or not callable(verify):
        raise MigrationIOError("initial_delivery_unavailable")
    directory = Path(profile_root) / "initial_migration_intents"
    raw = json.dumps(binding, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    if len(raw) > 16384:
        raise MigrationIOError("initial_intent_invalid")
    with pinned_target_directory(directory, create=True), migration_target_lock(directory):
        existing, heads = _intent_heads(directory, _read_intents(directory), with_ids=True)
        anchor = _intent_anchor(binding)
        if binding["category"] in ("knowledge_sync", "knowledge_recovery"):
            from .knowledge_sync_receipt import read_drained_job_result, read_knowledge_sync_receipt
            from .knowledge_recovery_result import read_verified_recovery_job_result
            from .knowledge_not_started import read_verified_not_started
            from scripts.assistant_migration_activate import verify_initial_knowledge_receipts
            if not callable(owner_check) or owner_check() is not True:
                raise MigrationIOError("initial_profile_owner_unavailable")
            baseline = next((row for row in existing.values()
                             if row["operationId"] == binding["baselineMigrationId"]), None)
            fixed = ("registeredProjectId", "sourceScope", "sourceIdentityDigest", "projectDirectory",
                     "workspaceDirectory", "targetDirectory", "targetAgentId", "targetSessionId")
            if (baseline is None or baseline["category"] != "knowledge"
                    or any(baseline[key] != binding[key] for key in fixed)
                    or read_drained_job_result(profile_root, baseline["operationId"]) != "completed"):
                raise MigrationIOError("knowledge_sync_baseline_unavailable")
            verify_initial_knowledge_receipts(Path(profile_root), baseline["operationId"])
            if binding["category"] == "knowledge_recovery":
                from . import migration_knowledge as k
                original = next((row for row in existing.values() if row["operationId"] == binding["originalSyncId"]), None)
                if (original is None or original["category"] != "knowledge_sync"
                        or any(original[key] != binding[key] for key in fixed)
                        or original["baselineMigrationId"] != binding["baselineMigrationId"]):
                    raise MigrationIOError("knowledge_sync_recovery_invalid")
                claim = strict_json(read_stable_file(Path(profile_root) / "initial_migration_claims" / original["operationId"] / "claim.json", 16384).raw)
                if (type(claim) is not dict or type(claim.get("schemaVersion")) is not int
                        or claim != {"schemaVersion": 1, "operationId": original["operationId"], "category": "knowledge_sync"}):
                    raise MigrationIOError("knowledge_sync_recovery_invalid")
                plan_path = Path(profile_root) / "knowledge_migrations" / "sync_operations" / (k._digest(original["operationId"]) + ".plan.json")
                if not plan_path.exists() or plan_path.is_symlink():
                    raise MigrationIOError("knowledge_sync_recovery_invalid")
                if read_drained_job_result(profile_root, original["operationId"]) in ("completed", "partial"):
                    raise MigrationIOError("knowledge_sync_recovery_finished")
                for earlier in existing.values():
                    if (earlier["category"] == "knowledge_recovery" and earlier["originalSyncId"] == original["operationId"]
                            and earlier["operationId"] != binding["operationId"]):
                        status = read_verified_recovery_job_result(profile_root, earlier["operationId"])
                        if status is None:
                            raise MigrationIOError("knowledge_sync_recovery_pending")
                        if status in ("completed", "partial"):
                            raise MigrationIOError("knowledge_sync_recovery_finished")
            for prior in existing.values():
                if binding["category"] == "knowledge_recovery":
                    break
                if (prior["category"] != "knowledge_sync" or prior["operationId"] == binding["operationId"]
                        or any(prior[key] != binding[key] for key in ("sourceScope", "projectDirectory", "workspaceDirectory", "targetDirectory", "targetAgentId"))):
                    continue
                if read_verified_not_started(profile_root, prior["operationId"]):
                    continue
                outcome = read_drained_job_result(profile_root, prior["operationId"])
                receipt = read_knowledge_sync_receipt(profile_root, sync_id=prior["operationId"],
                    baseline_id=prior["baselineMigrationId"], source_scope=prior["sourceScope"], target_agent_id=prior["targetAgentId"])
                if outcome not in ("completed", "partial"):
                    for recovery in existing.values():
                        if (recovery["category"] == "knowledge_recovery" and recovery["originalSyncId"] == prior["operationId"]
                                and recovery["baselineMigrationId"] == prior["baselineMigrationId"]
                                and all(recovery[key] == prior[key] for key in fixed)
                                and read_verified_recovery_job_result(profile_root, recovery["operationId"]) in ("completed", "partial")):
                            outcome = "partial"
                            break
                if outcome not in ("completed", "partial") or receipt["state"] not in ("completed", "partial"):
                    raise MigrationIOError("knowledge_sync_prior_unknown")
                claim = strict_json(read_stable_file(Path(profile_root) / "initial_migration_claims" / prior["operationId"] / "claim.json", 16384).raw)
                if (type(claim) is not dict or type(claim.get("schemaVersion")) is not int
                        or claim != {"schemaVersion": 1, "operationId": prior["operationId"], "category": "knowledge_sync"}):
                    raise MigrationIOError("knowledge_sync_prior_unknown")
        if anchor not in existing:
            if any(v["operationId"] == binding["operationId"] for v in existing.values()):
                raise MigrationIOError("initial_intent_exists")
            pending = directory / (".pending-" + secrets.token_hex(16))
            with pinned_target_directory(pending, create=True):
                _write_new(pending / "intent.json", raw)
                identity = path_identity(pending)
            def commit():
                verify()
                token.check()
                publish_directory(pending, directory / anchor, identity)
            token.publish(commit)
        else:
            if binding["category"] in ("knowledge_sync", "knowledge_recovery"):
                # A published sync ID is one-shot, even if its response was lost.
                raise MigrationIOError("knowledge_sync_intent_exists")
            previous = existing[anchor]
            fixed = ("registeredProjectId", "sourceScope", "category", "operationId", "projectDirectory",
                     "workspaceDirectory", "targetDirectory", "targetAgentId")
            if any(binding[key] != previous[key] for key in fixed):
                raise MigrationIOError("initial_intent_exists")
            # Host holds the native profile owner for its entire lifetime. An
            # offline activation cannot claim concurrently with this refresh.
            from scripts.assistant_migration_activate import _initial_receipts_or_claim
            def unclaimed():
                if not callable(owner_check) or owner_check() is not True:
                    raise MigrationIOError("initial_profile_owner_unavailable")
                if _initial_receipts_or_claim(Path(profile_root), binding["operationId"], binding["category"]):
                    raise MigrationIOError("initial_intent_claimed_unknown")
            unclaimed()
            chain = directory.parent / "initial_migration_intent_refreshes" / anchor
            record = {"schemaVersion": 1, "parentSha256": heads[anchor], "binding": binding}
            encoded = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
            with pinned_target_directory(chain, create=True):
                if len(list(islice(chain.iterdir(), 128))) >= 128:
                    raise MigrationIOError("initial_intent_limit")
                pending = chain / (".pending-" + secrets.token_hex(16))
                with pinned_target_directory(pending, create=True):
                    _write_new(pending / "intent.json", encoded)
                    identity = path_identity(pending)
                def commit_refresh():
                    verify()
                    unclaimed()
                    token.check()
                    publish_directory(pending, chain / _digest(record), identity)
                token.publish(commit_refresh)
    return binding
