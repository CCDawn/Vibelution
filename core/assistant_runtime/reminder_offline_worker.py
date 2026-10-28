"""Trusted offline worker for one source's final affairs snapshot.

The caller must construct the observation through the main-owned registration
lease, never from model or renderer paths. A result is preparation evidence,
not evidence that all old senders stopped or that ownership transferred.
"""
from __future__ import annotations

import hashlib
import os
import re
from contextlib import contextmanager
from itertools import islice
from pathlib import Path

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.reminder_source_mutex import try_acquire_reminder_source_mutex
from .initial_migration_binding import (_directory, list_initial_intents, read_initial_intent,
                                        source_identity, target_identity)
from .migration_active import _selected, _verify_captured
from .migration_affairs import _parse_rows
from .migration_affairs_conflicts import (_CHAIN_LIMIT, _load, _record_path, _scope, _sync_candidates,
                                           discover_affairs_baseline_locked, locked_affairs_target,
                                           verified_affairs_baseline_locked)
from .migration_affairs_conflicts import prepare_affairs_conflicts
from .migration_affairs_sync import reconcile_affairs
from .migration_io import MigrationIOError, pinned_source_files, pinned_target_directory, read_stable_file, strict_json
from .migration_profile import offline_migration_profile
from .migration_source_archive import import_source_snapshots
from .reminder_source_identity import ReminderSourceObservation
from .reminder_uncertain_preparation import inspect_uncertainty_preparation, prepare_current_day_uncertainty

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z")
_RECOVERY = re.compile(r"rprep-[a-f0-9]{40}\Z")


def _matches_origin(intent, target, scope, project: Path, workspace: Path) -> bool:
    try:
        source_digest, project_id, workspace_id = source_identity(scope, project, workspace)
        source_digests = {source_digest}
        if os.name == "nt":
            # Main's registry stores a case-folded physical project path;
            # older approved intents can retain the canonical Windows case.
            # Recompute only spellings of these same checked filesystem
            # objects, keeping all ancestor identities in the digest.
            project_variants = (project, project.resolve(), Path(str(project).lower()))
            workspace_variants = (workspace, workspace.resolve(), Path(str(workspace).lower()))
            for project_variant in project_variants:
                for workspace_variant in workspace_variants:
                    digest, project_variant_id, workspace_variant_id = source_identity(scope, project_variant, workspace_variant)
                    if project_variant_id != project_id or workspace_variant_id != workspace_id:
                        raise MigrationIOError("reminder_worker_baseline_authority_unavailable")
                    source_digests.add(digest)
        target_digest, target_id = target_identity(target.root, target.agent_id, target.session_id)
    except Exception:
        raise MigrationIOError("reminder_worker_baseline_authority_unavailable") from None
    return (intent is not None and intent["category"] == "personal" and intent["sourceScope"] == scope
            and intent["sourceIdentityDigest"] in source_digests
            and intent["projectDirectory"] == project_id and intent["workspaceDirectory"] == workspace_id
            and intent["targetDirectory"] == target_id and intent["targetAgentId"] == target.agent_id
            and intent["targetSessionId"] == target.session_id and intent["targetIdentityDigest"] == target_digest)


def _verify_baseline_origin(target, scope, project: Path, workspace: Path, baseline_id: str) -> None:
    """Bind the verified chain's original import to this physical source."""
    candidates = _sync_candidates(target.root, scope, target.agent_id)
    current, seen = baseline_id, set()
    for _ in range(_CHAIN_LIMIT):
        if current in seen:
            raise MigrationIOError("reminder_worker_baseline_authority_unavailable")
        seen.add(current)
        receipt = target.root / "affairs_migrations" / (hashlib.sha256(current.encode()).hexdigest() + ".json")
        if receipt.exists() or receipt.is_symlink():
            break
        links = candidates.get(current, [])
        if len(links) != 1:
            raise MigrationIOError("reminder_worker_baseline_authority_unavailable")
        current = links[0][0]["baselineMigrationId"]
    else:
        raise MigrationIOError("reminder_worker_baseline_authority_unavailable")
    try:
        intent = read_initial_intent(target.root, current)
    except Exception:
        raise MigrationIOError("reminder_worker_baseline_authority_unavailable") from None
    if not _matches_origin(intent, target, scope, project, workspace):
        raise MigrationIOError("reminder_worker_baseline_authority_unavailable")


def run_reminder_offline_worker(*, source: ReminderSourceObservation,
                                sync_id: str, mode: str = "start", recovery_id: str | None = None) -> dict:
    """Run on the source-mutex-owning thread with no caller-supplied paths.

    The source observation and IDs must originate from a trusted main-owned,
    continuously held registration/admission permit. The target comes solely
    from offline_migration_profile's actual native host-owner lock. Recovery
    confirms the original sync without creating a new sync, archive or
    conflict record; an existing original preparation ID is rediscovered
    from strictly validated records. Main must durably retain the sync ID
    before dispatch. A fresh invocation rejects existing sync artifacts.
    """
    if (type(source) is not ReminderSourceObservation or type(sync_id) is not str
            or _ID.fullmatch(sync_id) is None
            or mode not in ("start", "resume") or mode == "start" and recovery_id is not None
            or recovery_id is not None and (type(recovery_id) is not str or _RECOVERY.fullmatch(recovery_id) is None)):
        raise MigrationIOError("reminder_worker_request_invalid")
    mutex = try_acquire_reminder_source_mutex(source)
    if mutex is None:
        raise MigrationIOError("reminder_worker_source_busy")
    try:
        if mutex.abandoned:
            raise MigrationIOError("reminder_uncertainty_source_recovery_required")
        with offline_migration_profile() as target:
            with source._preview._lock:
                source._check()
                row = source._preview._previews[source._token]
                project, workspace, paths, authority = Path(row[3]), Path(row[4]), row[5], tuple(row[7])
                scope = _scope({"projectId": paths.project_id, "instanceId": paths.instance_id,
                                "agentId": source.agent_id})
            from scripts.assistant_migration_activate import _capture
            captured, selected_authorities = _capture(project, workspace, scope, None,
                                                       categories=frozenset({"personal_affairs"}))
            snapshot = _selected(captured, "personal_affairs")
            _parse_rows(snapshot.raw)
            authority = (*authority, *selected_authorities)

            def verify():
                mutex.check()
                target.check()
                _verify_captured(captured, authority, source._check)
                mutex.check()
                target.check()

            @contextmanager
            def guard():
                verify()
                yield
                verify()

            verify()
            with pinned_source_files((*authority, snapshot)):
                verify()
                archive = target.root / "history_sources/migrations"
                digest = hashlib.sha256(sync_id.encode()).hexdigest()
                receipt = target.root / "affairs_sync_receipts" / (digest + ".json")
                operations = target.root / "reminder_offline_operations"
                claim_path = operations / (digest + ".intent.json")
                sync_path = operations / (digest + ".sync-intent.json")
                if mode == "start":
                    artifacts = (archive / sync_id, archive / (".pending-" + sync_id),
                                 _record_path(target.root, sync_id), receipt, claim_path, sync_path)
                    if any(path.exists() or path.is_symlink() for path in artifacts):
                        raise MigrationIOError("reminder_worker_original_outcome_unknown")
                    # Reject unproven historical imports before creating any
                    # transaction lock sidecars, operation claim or archive.
                    try:
                        refs = list_initial_intents(target.root)
                        matched = any(_matches_origin(read_initial_intent(target.root, ref["operationId"]),
                                                       target, scope, project, workspace)
                                      for ref in refs if ref["category"] == "personal")
                    except Exception:
                        raise MigrationIOError("reminder_worker_baseline_authority_unavailable") from None
                    if not matched:
                        raise MigrationIOError("reminder_worker_baseline_authority_unavailable")
                    from . import native
                    with native._LOCK, locked_affairs_target(target.root, target_agent_id=target.agent_id) as locked:
                        verify()
                        baseline = discover_affairs_baseline_locked(target.root, source_scope=scope,
                            target_agent_id=target.agent_id, target=locked)
                        baseline_id = baseline["baselineMigrationId"]
                        if type(baseline_id) is not str or _ID.fullmatch(baseline_id) is None or baseline_id == sync_id:
                            raise MigrationIOError("reminder_worker_binding_changed")
                        _verify_baseline_origin(target, scope, project, workspace, baseline_id)
                        with pinned_target_directory(operations, create=True):
                            if any(path.exists() or path.is_symlink() for path in artifacts):
                                raise MigrationIOError("reminder_worker_original_outcome_unknown")
                            claim = {"schemaVersion": 1, "syncId": sync_id, "baselineId": baseline_id,
                                     "sourceScope": scope, "ledgerKey": source._ledger,
                                     "sourceAuthorityKey": source._authority, "sourceSha256": snapshot.sha256,
                                     "targetDirectory": _directory(target.root), "targetAgentId": target.agent_id}
                            verify()
                            atomic_write_json(claim_path, claim, strict_replace=True, sort_keys=True)
                with pinned_target_directory(operations):
                    claim_snapshot = read_stable_file(claim_path, 16384)
                    stored_claim = strict_json(claim_snapshot.raw)
                    if (type(stored_claim) is not dict or type(stored_claim.get("schemaVersion")) is not int
                            or type(stored_claim.get("baselineId")) is not str
                            or _ID.fullmatch(stored_claim["baselineId"]) is None
                            or stored_claim["baselineId"] == sync_id):
                        raise MigrationIOError("reminder_worker_binding_changed")
                    baseline_id = stored_claim["baselineId"]
                    claim = {"schemaVersion": 1, "syncId": sync_id, "baselineId": baseline_id,
                             "sourceScope": scope, "ledgerKey": source._ledger,
                             "sourceAuthorityKey": source._authority, "sourceSha256": snapshot.sha256,
                             "targetDirectory": _directory(target.root), "targetAgentId": target.agent_id}
                    if stored_claim != claim:
                        raise MigrationIOError("reminder_worker_binding_changed")
                    from . import native
                    with native._LOCK, locked_affairs_target(target.root, target_agent_id=target.agent_id) as locked:
                        verify()
                        verified_affairs_baseline_locked(target.root, baseline_id, scope, target.agent_id, target=locked)
                        _verify_baseline_origin(target, scope, project, workspace, baseline_id)
                        verify()
                    sync_intent = {"schemaVersion": 1, "syncId": sync_id, "claimSha256": claim_snapshot.sha256}
                    # Archive copies and difference plans are idempotent only
                    # for the exact same source/target/operation binding.
                    import_source_snapshots(captured, target.root, sync_id,
                        source_roots=(project, workspace), authority_snapshots=authority,
                        authority_verify=verify, categories=frozenset({"personal_affairs"}), write_guard=guard)
                    verify()
                    prepare_affairs_conflicts(target, baseline_migration_id=baseline_id,
                        snapshot_migration_id=sync_id, sync_id=sync_id, source_scope=scope)
                    verify()
                record = _load(target.root, sync_id, scope, target.agent_id)
                if (record["baselineMigrationId"] != baseline_id or record["snapshotMigrationId"] != sync_id
                        or record["snapshotSha256"] != snapshot.sha256):
                    raise MigrationIOError("reminder_worker_binding_changed")
                verify()
                if mode == "resume":
                    folder = target.root / "reminder_handoff_preparations"
                    matches = []
                    if folder.exists() or folder.is_symlink():
                        with pinned_target_directory(folder):
                            entries = list(islice(folder.glob("*.intent.json"), 513))
                            if len(entries) > 512:
                                raise MigrationIOError("reminder_worker_preparation_inventory_unknown")
                            for path in entries:
                                original = path.name[:-len(".intent.json")]
                                inspect_uncertainty_preparation(target=target, operation_id=original)
                                item = strict_json(read_stable_file(path, 1024 * 1024).raw)
                                if item["syncId"] == sync_id:
                                    matches.append(original)
                    if len(matches) > 1 or recovery_id is not None and matches != [recovery_id]:
                        raise MigrationIOError("reminder_worker_preparation_inventory_unknown")
                    recovery_id = matches[0] if matches else None
                # Once the sync intent exists, loss of its receipt is unknown;
                # recovery can confirm it but must never rerun the write.
                with pinned_target_directory(operations):
                    started = sync_path.exists() or sync_path.is_symlink()
                    if started:
                        stored_sync = strict_json(read_stable_file(sync_path, 4096).raw)
                        if (type(stored_sync) is not dict or type(stored_sync.get("schemaVersion")) is not int
                                or stored_sync != sync_intent):
                            raise MigrationIOError("reminder_worker_binding_changed")
                    else:
                        if receipt.exists() or receipt.is_symlink():
                            raise MigrationIOError("reminder_worker_original_outcome_unknown")
                        verify()
                        atomic_write_json(sync_path, sync_intent, strict_replace=True, sort_keys=True)
                    sync = reconcile_affairs(target, sync_id=sync_id, source_scope=scope,
                                             confirmation_only=started)
                verify()
                if sync["conflictCount"]:
                    return {"schemaVersion": 1, "state": "pending", "code": "affairs_conflicts",
                            "syncId": sync_id, "conflictCount": sync["conflictCount"],
                            "readyForCutover": False}
                prepared = prepare_current_day_uncertainty(source=source, source_mutex=mutex,
                    target=target, sync_id=sync_id, recovery_id=recovery_id)
                verify()
                return {"schemaVersion": 1, "state": "pending", "code": "sender_proof_unavailable",
                        "syncId": sync_id, "preparationId": prepared["operationId"],
                        "uncertainCount": prepared["uncertainCount"], "readyForCutover": False}
    finally:
        mutex.release()
