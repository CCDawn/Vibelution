"""Opt-in operator proof for an already configured, relocated data owner.

This authority permits existing-only metadata reads. It never migrates data,
changes native storage resolution, or manufactures a migration completion.
Only the trusted local operator CLI writes this record; it is not a model tool.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tomllib

import vibelution_storage as storage
from config import paths as config_paths
from core.assistant_runtime.migration_io import (
    check_path, pinned_mutable_file, pinned_source_files, pinned_target_directory,
    read_stable_file, strict_json, validate_path,
)
from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock, lock_path_for
from core.web.services.personal_assistant_project.windows_read import _locked_source


RECORD_NAME = "storage-owner-handoff.json"
_LIMIT = 128 * 1024
_REQUEST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_KIND = "configured-data-owner-handoff"
_COVERAGE = ("Configured data owner binding only; no recursive inventory, content, "
             "migration readiness, writer quiescence, data copy or migration cutover is certified.")


class StorageOwnerHandoffError(ValueError):
    """Stable diagnostic without config values, content, or native exceptions."""


def _require(condition, code):
    if not condition:
        raise StorageOwnerHandoffError(code)


def _digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _request(value):
    _require(isinstance(value, str) and _REQUEST.fullmatch(value), "invalid_request_id")
    return value


def _physical(info):
    index = (info.index_high << 32) | info.index_low
    _require(bool(index), "unproven_directory_identity")
    return {"volume": info.volume, "fileId": index}


def _directory(pins, path):
    path = check_path(path)
    _, _, info = pins.enter_context(_locked_source(
        Path(path.anchor), path, directory=True, allow_child_replacement=True))
    return _physical(info)


def _existing_ancestors(path):
    """Check lexical ancestors before any resolver can erase a reparse alias."""
    path = validate_path(path)
    parent = path
    while not os.path.lexists(parent):
        parent = parent.parent
    check_path(parent)
    return path


def _target(project_root):
    root = check_path(validate_path(Path(project_root)))
    target = storage.resolve_project_storage_paths(root)
    _require(root == target.project_root, "project_root_mismatch")
    _existing_ancestors(target.instance_home)
    return root, target, target.instance_home / RECORD_NAME


def _config_path():
    # resolve_config_path intentionally resolves aliases for general callers;
    # this authority rejects the lexical route before resolution can hide one.
    raw = os.environ.get(config_paths.CONFIG_PATH_ENV, "").strip()
    if raw:
        lexical = Path(raw).expanduser()
    else:
        home = os.environ.get(config_paths.CONFIG_HOME_ENV, "").strip()
        lexical = (Path(home).expanduser() if home else config_paths.default_config_home()) / config_paths.CONFIG_FILENAME
    check_path(lexical)
    result = config_paths.resolve_config_path()
    _require(lexical == result, "config_authority_alias")
    return result


def _data_route(pins, raw, base):
    path = Path(os.path.expandvars(raw.strip())).expanduser()
    if not path.is_absolute():
        path = base / path
    # Reject aliases and pin the lexical namespace before normalization. In
    # particular, an equivalent case/slash spelling must not persist as a new
    # owner, while case-sensitive distinct directories retain physical gates.
    _directory(pins, path)
    return path.resolve()


def _record(path):
    snapshot = read_stable_file(path, _LIMIT)
    data = strict_json(snapshot.raw)
    _require(isinstance(data, dict) and set(data) == {
        "schemaVersion", "kind", "status", "binding", "bindingDigest", "apply", "revocation"},
        "invalid_handoff_record")
    _require(type(data["schemaVersion"]) is int and data["schemaVersion"] == 1
             and data["kind"] == _KIND and data["status"] in {"active", "revoked"}
             and isinstance(data["binding"], dict) and data["bindingDigest"] == _digest(data["binding"]),
             "invalid_handoff_record")
    apply = data["apply"]
    _require(isinstance(apply, dict) and set(apply) == {
        "requestId", "planDigest", "confirmedRelocatedData", "committedAt"}
        and isinstance(apply.get("requestId"), str) and _REQUEST.fullmatch(apply["requestId"])
        and isinstance(apply.get("planDigest"), str) and _DIGEST.fullmatch(apply["planDigest"])
        and apply.get("confirmedRelocatedData") is True and isinstance(apply.get("committedAt"), str),
        "invalid_handoff_receipt")
    revoked = data["revocation"]
    _require((data["status"] == "active" and revoked is None)
             or (data["status"] == "revoked" and isinstance(revoked, dict)
                 and set(revoked) == {"requestId", "recordDigest", "revokedAt"}
                 and isinstance(revoked.get("requestId"), str) and _REQUEST.fullmatch(revoked["requestId"])
                 and isinstance(revoked.get("recordDigest"), str) and _DIGEST.fullmatch(revoked["recordDigest"])
                 and isinstance(revoked.get("revokedAt"), str)), "invalid_handoff_revocation")
    _require(apply["planDigest"] == _plan(data["binding"], path)["planDigest"], "invalid_handoff_plan_receipt")
    if revoked is not None:
        _require(revoked["requestId"] != apply["requestId"], "invalid_handoff_revocation")
    return snapshot, data


@contextmanager
def _binding(project_root, *, identity_snapshot=None, config_snapshot=None):
    root, target, record_path = _target(project_root)
    config_path = _config_path()
    identity = identity_snapshot or read_stable_file(root / storage.PROJECT_IDENTITY_RELATIVE_PATH, _LIMIT)
    config = config_snapshot or read_stable_file(config_path, 16 * 1024 * 1024)
    _require(identity.path == root / storage.PROJECT_IDENTITY_RELATIVE_PATH
             and config.path == config_path, "authority_path_mismatch")
    with ExitStack() as pins:
        pins.enter_context(pinned_source_files((identity, config)))
        identity_data = strict_json(identity.raw)
        _require(isinstance(identity_data, dict) and type(identity_data.get("schemaVersion")) is int
                 and identity_data["schemaVersion"] == 1 and identity_data.get("projectId") == target.project_id,
                 "invalid_project_identity")
        config_data = tomllib.loads(config.raw.decode("utf-8"))
        settings = config_data.get("storage", {})
        _require(isinstance(settings, dict), "invalid_storage_config")
        raw = settings.get("data_home", "")
        _require(isinstance(raw, str) and bool(raw.strip()), "configured_data_home_required")
        environment = os.environ.get(config_paths.DATA_HOME_ENV, "")
        configured_route = _data_route(pins, raw, config_path.parent)
        route_raw = environment.strip() or raw.strip()
        route_base = Path.cwd() if environment.strip() else config_path.parent
        source = _data_route(pins, route_raw, route_base)
        # A same-project name or a global config alone is not owner evidence.
        instances = target.project_home / "instances"
        _require(source.name == "data" and source.parent.parent == instances
                 and re.fullmatch(r"[0-9a-f]{8}", source.parent.name)
                 and source.parent.name != target.instance_id, "source_outside_project_instance")
        source_marker = read_stable_file(source.parent / storage.STORAGE_MIGRATION_STATE_NAME, _LIMIT)
        pins.enter_context(pinned_source_files((source_marker,)))
        marker = strict_json(source_marker.raw)
        _require(isinstance(marker, dict) and type(marker.get("schemaVersion")) is int
                 and marker["schemaVersion"] == storage.STORAGE_MIGRATION_SCHEMA_VERSION
                 and marker.get("status") == "completed" and marker.get("projectId") == target.project_id
                 and marker.get("instanceId") == source.parent.name, "invalid_source_marker")
        old_root = marker.get("projectRoot")
        _require(isinstance(old_root, str) and bool(old_root), "missing_source_owner")
        old_root = _existing_ancestors(Path(old_root))
        _require(storage.instance_id_for_project(old_root) == source.parent.name,
                 "source_owner_instance_mismatch")
        _require(marker.get("targetRoot") == str(source.parent), "source_target_root_mismatch")
        canonical_marker = storage.storage_migration_state_path(target)
        _require(not os.path.lexists(canonical_marker), "canonical_migration_marker_present")
        active = storage.resolve_active_project_storage_paths(root)
        _require(not active.migrated and active.data == source
                 and storage.resolve_project_data_home(root) == source
                 and storage.resolve_project_workspace_home(root) == source / "workspace",
                 "native_route_mismatch")
        binding = {"projectId": target.project_id, "instanceId": target.instance_id,
            "projectRoot": str(root), "identitySha256": identity.sha256,
            "projectRootIdentity": _directory(pins, root),
            "sourceInstanceId": source.parent.name, "sourceProjectRoot": str(old_root),
            "sourceDataRoot": str(source), "sourceDataIdentity": _directory(pins, source),
            "workspace": str(source / "workspace"), "workspaceIdentity": _directory(pins, source / "workspace"),
            "sourceMarkerPath": str(source_marker.path), "sourceMarkerSha256": source_marker.sha256,
            "configPath": str(config_path), "configuredDataHome": str(configured_route)}
        def recheck():
            _require(not os.path.lexists(canonical_marker), "canonical_migration_marker_present")
            _require(_config_path() == config_path
                     and os.environ.get(config_paths.DATA_HOME_ENV, "") == environment
                     and str(_data_route(pins, raw, config_path.parent)) == str(configured_route)
                     and str(_data_route(pins, route_raw, route_base)) == str(source)
                     and storage.resolve_project_storage_paths(root) == target
                     and storage.resolve_active_project_storage_paths(root) == active
                     and storage.resolve_project_data_home(root) == source
                     and storage.resolve_project_workspace_home(root) == source / "workspace",
                     "native_route_changed")
        recheck()
        yield binding, active, record_path, recheck
        recheck()


@contextmanager
def pinned_storage_owner_handoff(project_root, *, identity_snapshot=None, config_snapshot=None):
    """Pin valid proof and its authorities across an existing-only metadata read."""
    with _binding(project_root, identity_snapshot=identity_snapshot, config_snapshot=config_snapshot) as context:
        binding, active, path, _ = context
        snapshot, data = _record(path)
        with pinned_source_files((snapshot,)):
            _require(data["status"] == "active" and data["binding"] == binding, "handoff_binding_invalid")
            yield active


def _plan(binding, path):
    operation = {"schemaVersion": 1, "operation": "bind-configured-relocated-owner",
                 "binding": binding, "recordPath": str(path), "expectedRecord": "absent"}
    return {**operation, "planDigest": _digest(operation), "coverage": _COVERAGE,
            "writes": [str(path), str(lock_path_for(path))], "dataWrites": False,
            "rollback": "revoke this proof atomically; retain binding, receipts and all data"}


def plan_storage_owner_handoff(project_root):
    """Read-only plan; no initialization, directory creation, lock file or writes."""
    with _binding(project_root) as (binding, _, path, _):
        result = _plan(binding, path)
        if os.path.lexists(path):
            snapshot, record = _record(path)
            with pinned_source_files((snapshot,)):
                status = record["status"]
                if status == "active" and record["binding"] != binding:
                    status = "binding-invalid"
                result.update(status=status, recordDigest=snapshot.sha256,
                              applyRequestId=record["apply"]["requestId"])
        else:
            result["status"] = "planned"
        return result


def _receipt(record, path, request_id):
    if record["apply"]["requestId"] == request_id:
        return {"action": "apply", **record["apply"], "bindingDigest": record["bindingDigest"],
                "recordPath": str(path), "outcome": "committed", "currentProofStatus": record["status"]}
    revocation = record["revocation"]
    _require(isinstance(revocation, dict) and revocation["requestId"] == request_id, "receipt_not_found")
    return {"action": "revoke", **revocation, "recordPath": str(path), "outcome": "committed",
            "currentProofStatus": record["status"]}


@contextmanager
def _owned_record(project_root):
    """Historical receipts/revocation need current-root proof, not a live source."""
    root, target, path = _target(project_root)
    identity = read_stable_file(root / storage.PROJECT_IDENTITY_RELATIVE_PATH, _LIMIT)
    with ExitStack() as pins:
        pins.enter_context(pinned_source_files((identity,)))
        physical = _directory(pins, root)
        snapshot, data = _record(path)
        binding = data["binding"]
        _require(binding.get("projectRoot") == str(root) and binding.get("instanceId") == target.instance_id
                 and binding.get("projectId") == target.project_id and binding.get("identitySha256") == identity.sha256
                 and binding.get("projectRootIdentity") == physical, "record_owner_mismatch")
        yield snapshot, data, path


def read_storage_owner_handoff_receipt(project_root, *, request_id):
    """Read the original request outcome without acquiring/creating write locks."""
    _request(request_id)
    with _owned_record(project_root) as (snapshot, data, path):
        with pinned_source_files((snapshot,)):
            return {**_receipt(data, path, request_id), "currentRecordDigest": snapshot.sha256}


@contextmanager
def _writer(path):
    with pinned_target_directory(path.parent, create=True):
        with pinned_mutable_file(lock_path_for(path)):
            with cross_process_file_lock(path):
                # Atomic IO uses the same reentrant lock, and must never use
                # its optional in-place-write fallback for authority records.
                yield


def apply_storage_owner_handoff(project_root, *, plan_digest, confirm_relocated_data, request_id):
    _request(request_id)
    _require(confirm_relocated_data is True, "relocated_data_confirmation_required")
    _require(isinstance(plan_digest, str) and _DIGEST.fullmatch(plan_digest), "invalid_plan_digest")
    _, _, path = _target(project_root)
    # ACK recovery is purely a receipt read, even if config/source later drift.
    if os.path.lexists(path):
        result = read_storage_owner_handoff_receipt(project_root, request_id=request_id)
        _require(result["action"] == "apply" and result["planDigest"] == plan_digest, "request_conflict")
        return result
    with _binding(project_root) as (binding, _, path, _):
        _require(_plan(binding, path)["planDigest"] == plan_digest, "plan_changed")
    with _writer(path):
        if os.path.lexists(path):
            result = read_storage_owner_handoff_receipt(project_root, request_id=request_id)
            _require(result["action"] == "apply" and result["planDigest"] == plan_digest, "request_conflict")
            return result
        with _binding(project_root) as (binding, _, current, recheck):
            _require(current == path and _plan(binding, path)["planDigest"] == plan_digest, "plan_changed")
            record = {"schemaVersion": 1, "kind": _KIND, "status": "active", "binding": binding,
                "bindingDigest": _digest(binding), "apply": {"requestId": request_id, "planDigest": plan_digest,
                    "confirmedRelocatedData": True, "committedAt": datetime.now(timezone.utc).isoformat()},
                "revocation": None}
            recheck()
            atomic_write_json(path, record, strict_replace=True, ensure_parent_dir=False)
            return read_storage_owner_handoff_receipt(project_root, request_id=request_id)


def revoke_storage_owner_handoff(project_root, *, record_digest, request_id):
    _request(request_id)
    _require(isinstance(record_digest, str) and _DIGEST.fullmatch(record_digest), "invalid_record_digest")
    _, _, path = _target(project_root)
    # Never create metadata merely to discover that there is no proof.
    _require(os.path.lexists(path), "handoff_record_missing")
    with _writer(path):
        with _owned_record(project_root) as (snapshot, data, path):
            if data["status"] == "revoked":
                result = {**_receipt(data, path, request_id), "currentRecordDigest": snapshot.sha256}
                _require(result["action"] == "revoke" and result["recordDigest"] == record_digest, "request_conflict")
                return result
            _require(request_id != data["apply"]["requestId"], "request_conflict")
            _require(snapshot.sha256 == record_digest, "record_changed")
            data["status"] = "revoked"
            data["revocation"] = {"requestId": request_id, "recordDigest": record_digest,
                                  "revokedAt": datetime.now(timezone.utc).isoformat()}
            atomic_write_json(path, data, strict_replace=True, ensure_parent_dir=False)
            return read_storage_owner_handoff_receipt(project_root, request_id=request_id)
