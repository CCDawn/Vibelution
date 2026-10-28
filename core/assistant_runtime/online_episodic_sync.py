"""Guarded online reconciliation of confirmed episodic source archives.

Only a trusted native host may create an owner and hold its Turn/registration
guard while publishing a source archive and calling ``reconcile_episodic``.
The lease is not a model-facing capability or first-import authority.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, get_ident

from core.infrastructure.file_lock import cross_process_file_lock
from core.web.services.agent_directory import episodic_memory as episodes

from .episodic_sync_plan import plan_episodic_sync
from .migration_episodic import _BYTE_CAP, _parse_rows, _target, _token, _write_receipt
from .migration_io import (MigrationIOError, check_path, migration_target_lock, pinned_mutable_file,
                           pinned_source_files, pinned_target_directory, read_stable_file, strict_json,
                           verify_snapshot)

_CHAIN_LIMIT = 256
_CHAIN_BYTE_LIMIT = 64 * 1024 * 1024
_HISTORY_ID_LIMIT = 65536


class EpisodicSyncPrewrite(MigrationIOError):
    """A classified failure known to precede any ledger or sync receipt write."""


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _review_token(receipt, target_sha):
    return _digest({"schemaVersion": 1, "receipt": receipt, "targetSha256": target_sha})


@dataclass(frozen=True)
class _Lease:
    root: Path
    agent_id: str
    session_id: str
    initial_id: str
    scope: dict
    project: Path
    workspace: Path
    intent: dict
    owner: object
    thread: int
    verify: object

    def check(self):
        from . import native
        from .initial_migration_binding import read_initial_intent, source_identity, target_identity
        from core.infrastructure.native_runtime import assistant_native_root
        from core.web.services.session import directory_runtime
        if (self.owner._active is not self or self.thread != get_ident() or self.owner._revoked.is_set()
                or not native._STARTED or native._STOP_REQUESTED.is_set() or native._OFFLINE_MIGRATION
                or native._AGENT_ID != self.agent_id or native._SESSION_ID != self.session_id
                or assistant_native_root() != self.root or directory_runtime.directory_store_project_root() != self.root):
            raise MigrationIOError("episodic_sync_lease_unavailable")
        self.verify()
        if (read_initial_intent(self.root, self.initial_id) != self.intent
                or source_identity(self.scope, self.project, self.workspace) != (
                    self.intent["sourceIdentityDigest"], self.intent["projectDirectory"], self.intent["workspaceDirectory"])
                or target_identity(self.root, self.agent_id, self.session_id) != (
                    self.intent["targetIdentityDigest"], self.intent["targetDirectory"])):
            raise MigrationIOError("episodic_sync_identity_changed")


class OnlineEpisodicSyncOwner:
    """Owned by a host generation; the guard must authenticate its live Turn."""
    def __init__(self, generation, try_guard):
        if not _token(generation) or not callable(try_guard):
            raise ValueError("episodic_sync_owner_invalid")
        self.generation, self._try_guard = generation, try_guard
        self._gate, self._revoked, self._active = Lock(), Event(), None

    def revoke(self):
        self._revoked.set()
        return self.drained()

    def drained(self):
        if not self._gate.acquire(blocking=False):
            return False
        self._gate.release()
        return True

    @contextmanager
    def admit(self, *, generation, turn_id, initial_operation_id, source_scope, project, workspace, verify):
        from . import native
        from .initial_migration_binding import read_initial_intent
        from core.infrastructure.native_runtime import assistant_native_root
        from scripts.assistant_migration_activate import verify_initial_personal_receipts
        if (generation != self.generation or not _token(turn_id) or not _token(initial_operation_id)
                or type(source_scope) is not dict or set(source_scope) != {"projectId", "instanceId", "agentId"}
                or not all(_token(v) for v in source_scope.values()) or not callable(verify)
                or not isinstance(project, Path) or not project.is_absolute()
                or not isinstance(workspace, Path) or not workspace.is_absolute() or self._revoked.is_set()):
            raise MigrationIOError("episodic_sync_request_invalid")
        with self._try_guard(generation, turn_id):
            if not self._gate.acquire(blocking=False):
                raise MigrationIOError("episodic_sync_busy")
            acquired = False
            try:
                if self._revoked.is_set() or not native._LOCK.acquire(blocking=False):
                    raise MigrationIOError("episodic_sync_busy")
                acquired = True
                root = assistant_native_root()
                intent = read_initial_intent(root, initial_operation_id)
                if (intent is None or intent["category"] != "personal" or intent["sourceScope"] != source_scope
                        or intent["targetAgentId"] != native._AGENT_ID or intent["targetSessionId"] != native._SESSION_ID):
                    raise MigrationIOError("episodic_sync_baseline_unavailable")
                lease = _Lease(root, native._AGENT_ID, native._SESSION_ID, initial_operation_id,
                               dict(source_scope), project, workspace, intent, self, get_ident(), verify)
                self._active = lease
                lease.check()
                try:
                    verify_initial_personal_receipts(root, initial_operation_id)
                except (MigrationIOError, OSError, KeyError, TypeError, ValueError):
                    raise EpisodicSyncPrewrite("baseline_unavailable") from None
                lease.check()
                yield lease
            finally:
                self._active = None
                if acquired:
                    native._LOCK.release()
                self._gate.release()


def _archive(root, operation_id, scope):
    from .migration_history import _confirmation_exists
    directory = root / "history_sources" / "migrations" / operation_id
    if not _confirmation_exists(directory):
        raise MigrationIOError("episodic_sync_archive_unconfirmed")
    manifest = read_stable_file(directory / "manifest.json", 16 * 1024 * 1024)
    data = strict_json(manifest.raw)
    if (type(data) is not dict or type(data.get("schemaVersion")) is not int or data.get("schemaVersion") not in (1, 2)
            or data.get("migrationId") != operation_id or data.get("sourceScope") != scope
            or data.get("readOnly") is not True or data.get("untrustedContent") is not True
            or type(data.get("entries")) is not list):
        raise MigrationIOError("episodic_sync_archive_invalid")
    entries = [entry for entry in data["entries"] if type(entry) is dict and entry.get("category") == "episodic_memory"]
    if len(entries) != 1:
        raise MigrationIOError("episodic_sync_archive_invalid")
    entry = entries[0]
    ref = entry.get("sourceRef")
    if not _token(ref) or entry.get("path") != f"sources/{ref}/episodic_events.jsonl":
        raise MigrationIOError("episodic_sync_archive_invalid")
    snapshot = read_stable_file(directory / "sources" / ref / "episodic_events.jsonl", _BYTE_CAP)
    if entry.get("sha256") != snapshot.sha256 or type(entry.get("size")) is not int or entry["size"] != len(snapshot.raw):
        raise MigrationIOError("episodic_sync_archive_invalid")
    rows = _parse_rows(snapshot.raw, scope["agentId"])
    return rows, snapshot.sha256, (manifest, snapshot)


def _receipts(directory, initial_id, scope, agent_id):
    result = {}
    for index, path in enumerate(directory.iterdir()):
        if index >= 2048:
            raise MigrationIOError("episodic_sync_receipt_limit")
        if path.name.endswith(".json.lock"):
            check_path(path)
            continue
        snapshot = read_stable_file(path, 16384)
        row = strict_json(snapshot.raw)
        keys = {"schemaVersion", "syncId", "initialId", "parentId", "sourceScope", "targetAgentId",
                "sourceSha256", "targetSha256", "appliedCount", "conflictCount", "published"}
        resolution = type(row) is dict and set(row) == keys | {"resolutionOf", "reviewToken"}
        refresh = type(row) is dict and set(row) == keys | {"refreshOf"}
        if (type(row) is not dict or set(row) not in (keys, keys | {"resolutionOf", "reviewToken"}, keys | {"refreshOf"}) or type(row["schemaVersion"]) is not int
                or row["schemaVersion"] != 1 or not _token(row["syncId"]) or not _token(row["initialId"])
                or not _token(row["parentId"]) or not _token(row["targetAgentId"])
                or path.name != hashlib.sha256(row["syncId"].encode()).hexdigest() + ".json"
                or type(row["sourceScope"]) is not dict
                or set(row["sourceScope"]) != {"projectId", "instanceId", "agentId"}
                or not all(_token(v) for v in row["sourceScope"].values())
                or type(row["published"]) is not bool
                or any(type(row[k]) is not int or not 0 <= row[k] <= 4096 for k in ("appliedCount", "conflictCount"))
                or any(type(row[k]) is not str or len(row[k]) != 64 or any(c not in "0123456789abcdef" for c in row[k])
                       for k in ("sourceSha256", "targetSha256"))):
            raise MigrationIOError("episodic_sync_receipt_invalid")
        if resolution and (not _token(row["resolutionOf"]) or type(row["reviewToken"]) is not str
                           or len(row["reviewToken"]) != 64
                           or any(c not in "0123456789abcdef" for c in row["reviewToken"])
                           or row["appliedCount"] != 0 or row["conflictCount"] != 0):
            raise MigrationIOError("episodic_sync_receipt_invalid")
        if refresh and (not _token(row["refreshOf"]) or row["appliedCount"] != 0 or row["conflictCount"] == 0):
            raise MigrationIOError("episodic_sync_receipt_invalid")
        if row["initialId"] == initial_id:
            if row["sourceScope"] != scope or row["targetAgentId"] != agent_id:
                raise MigrationIOError("episodic_sync_receipt_invalid")
            result[row["syncId"]] = (row, snapshot)
    return result


def _reconcile_episodic(lease, *, sync_id, confirmation_only=False, resolve_sync_id=None, review_token=None,
                        mark_publication):
    """Synchronize an already-published archive, or confirm an interrupted write.

    ``sync_id`` is both the original operation ID and archive ID. A pending
    receipt never triggers another ledger write. Conflicts never advance the
    source baseline, and block later synchronization pending resolution.
    """
    if (type(lease) is not _Lease or not _token(sync_id) or sync_id == lease.initial_id or type(confirmation_only) is not bool
            or (resolve_sync_id is None) != (review_token is None)
            or resolve_sync_id is not None and (confirmation_only or not _token(resolve_sync_id)
                or type(review_token) is not str or len(review_token) != 64
                or any(c not in "0123456789abcdef" for c in review_token))):
        raise MigrationIOError("episodic_sync_request_invalid")
    lease.check()
    from . import native
    from core.web.services import agent_directory_service as directory
    from core.web.services.external_management.state_snapshot import ExistingStateSnapshot
    from scripts.assistant_migration_activate import verify_initial_personal_receipts
    state = ExistingStateSnapshot(lease.root, directory, pin_workspace=True)
    ledger = _target(lease, state)
    receipts_dir = lease.root / "episodic_sync_receipts"
    receipt_path = receipts_dir / (hashlib.sha256(sync_id.encode()).hexdigest() + ".json")
    with pinned_target_directory(receipts_dir, create=True), migration_target_lock(receipts_dir), \
            pinned_target_directory(ledger.parent, create=True), \
            pinned_mutable_file(ledger.with_name(ledger.name + ".lock")), \
            pinned_mutable_file(receipt_path.with_name(receipt_path.name + ".lock")), \
            cross_process_file_lock(ledger, timeout=0):
        lease.check()
        verify_initial_personal_receipts(lease.root, lease.initial_id)
        receipts = _receipts(receipts_dir, lease.initial_id, lease.scope, lease.agent_id)
        if len(receipts) > _CHAIN_LIMIT:
            raise EpisodicSyncPrewrite("row_limit")
        if (receipt_path.exists() or receipt_path.is_symlink()) and sync_id not in receipts:
            raise MigrationIOError("episodic_sync_receipt_conflict")
        old, _, proofs = _archive(lease.root, lease.initial_id, lease.scope)
        evidence_bytes = sum(len(proof.raw) for proof in proofs)
        # Pin the original activation claim and its two receipts through the
        # native commit. A later replacement cannot lend old bytes authority.
        initial_digest = hashlib.sha256(lease.initial_id.encode()).hexdigest() + ".json"
        proofs += tuple(read_stable_file(path, 16384) for path in (
            lease.root / "initial_migration_claims" / lease.initial_id / "claim.json",
            lease.root / "episodic_migrations" / initial_digest,
            lease.root / "affairs_migrations" / initial_digest))
        previous = lease.initial_id
        known_ids = {row["episodeId"] for row in old}
        seen = set()
        blocked = None
        blocked_before = None
        while True:
            links = [(key, value) for key, value in receipts.items() if value[0]["parentId"] == previous]
            if len(links) > 1:
                raise MigrationIOError("episodic_sync_baseline_ambiguous")
            if not links:
                break
            key, (receipt, receipt_snapshot) = links[0]
            if blocked is not None:
                prior_receipt = receipts[blocked][0]
                resolved = (prior_receipt["published"] and prior_receipt["conflictCount"] > 0
                    and receipt.get("resolutionOf") == blocked
                    and receipt.get("sourceSha256") == prior_receipt["sourceSha256"]
                    and receipt.get("reviewToken") == _review_token(prior_receipt, receipt.get("targetSha256")))
                refreshed = (receipt.get("refreshOf") == blocked and prior_receipt["published"]
                             and prior_receipt["conflictCount"] > 0)
                if not (resolved or refreshed):
                    raise MigrationIOError("episodic_sync_baseline_unresolved")
                blocked = None
                if resolved:
                    blocked_before = None
            elif "resolutionOf" in receipt or "refreshOf" in receipt:
                raise MigrationIOError("episodic_sync_receipt_invalid")
            if key in seen:
                raise MigrationIOError("episodic_sync_baseline_ambiguous")
            seen.add(key)
            rows, sha, archive_proofs = _archive(lease.root, key, lease.scope)
            evidence_bytes += sum(len(proof.raw) for proof in archive_proofs) + len(receipt_snapshot.raw)
            if evidence_bytes > _CHAIN_BYTE_LIMIT:
                raise EpisodicSyncPrewrite("row_limit")
            if sha != receipt["sourceSha256"]:
                raise MigrationIOError("episodic_sync_receipt_invalid")
            proofs += archive_proofs
            known_ids.update(row["episodeId"] for row in rows)
            if len(known_ids) > _HISTORY_ID_LIMIT:
                raise EpisodicSyncPrewrite("row_limit")
            if key != sync_id or receipt["published"]:
                proofs += (receipt_snapshot,)
            if not receipt["published"] or receipt["conflictCount"]:
                if blocked_before is None:
                    blocked_before = old
                blocked = key
            old, previous = rows, key
        if seen != set(receipts):
            raise MigrationIOError("episodic_sync_baseline_ambiguous")
        if resolve_sync_id is not None and (blocked != resolve_sync_id or resolve_sync_id == sync_id or sync_id in receipts):
            raise EpisodicSyncPrewrite("unresolved")
        source, source_sha, archive_proofs = _archive(lease.root, sync_id, lease.scope)
        if evidence_bytes + sum(len(proof.raw) for proof in archive_proofs) > _CHAIN_BYTE_LIMIT:
            raise EpisodicSyncPrewrite("row_limit")
        proofs += archive_proofs
        with ExitStack() as stack:
            for archive_id in {lease.initial_id, sync_id, *seen}:
                stack.enter_context(pinned_target_directory(
                    lease.root / "history_sources" / "migrations" / archive_id / ".confirmed"))
            stack.enter_context(pinned_source_files(proofs))
            for proof in proofs:
                verify_snapshot(proof)
            lease.check()
            if _receipts(receipts_dir, lease.initial_id, lease.scope, lease.agent_id) != receipts:
                raise MigrationIOError("episodic_sync_target_changed")
            with episodes.episodic_transaction(lease.agent_id) as transaction:
                if transaction.path != ledger or _target(lease, state) != ledger:
                    raise MigrationIOError("episodic_sync_target_changed")
                existing = (_parse_rows(read_stable_file(ledger, _BYTE_CAP).raw, lease.agent_id)
                            if ledger.exists() or ledger.is_symlink() else [])
                if transaction.events != existing:
                    raise MigrationIOError("episodic_sync_target_changed")
                prior = receipts.get(sync_id)
                if prior is not None:
                    receipt = prior[0]
                    if confirmation_only and _digest(existing) != receipt["targetSha256"]:
                        raise MigrationIOError("episodic_sync_outcome_unknown")
                    if not receipt["published"]:
                        if _digest(existing) != receipt["targetSha256"]:
                            raise MigrationIOError("episodic_sync_outcome_unknown")
                        lease.check()
                        mark_publication()
                        _write_receipt(receipt_path, {**receipt, "published": True})
                    return {"syncId": sync_id, "appliedCount": receipt["appliedCount"],
                            "conflictCount": receipt["conflictCount"], "reused": True}
                if confirmation_only:
                    raise MigrationIOError("episodic_sync_outcome_unknown")
                if resolve_sync_id is not None:
                    blocked_receipt = receipts[resolve_sync_id][0]
                    if (not blocked_receipt["published"] or not blocked_receipt["conflictCount"]
                            or source_sha != blocked_receipt["sourceSha256"]
                            or review_token != _review_token(blocked_receipt, _digest(existing))):
                        raise EpisodicSyncPrewrite("review_changed")
                    plan = {"rows": existing, "appliedCount": 0, "conflictCount": 0}
                elif blocked is not None:
                    blocked_receipt = receipts[blocked][0]
                    if not blocked_receipt["published"]:
                        raise EpisodicSyncPrewrite("pending")
                    proposal = plan_episodic_sync(blocked_before, source, existing,
                        source_agent_id=lease.scope["agentId"], target_agent_id=lease.agent_id,
                        known_source_ids=known_ids)
                    plan = {"rows": existing, "appliedCount": 0, "conflictCount": max(1, proposal["conflictCount"])}
                else:
                    plan = plan_episodic_sync(old, source, existing, source_agent_id=lease.scope["agentId"],
                                              target_agent_id=lease.agent_id, known_source_ids=known_ids)
                if plan["conflictCount"] > 4096:
                    raise EpisodicSyncPrewrite("row_limit")
                receipt = {"schemaVersion": 1, "syncId": sync_id, "initialId": lease.initial_id,
                           "parentId": previous, "sourceScope": lease.scope, "targetAgentId": lease.agent_id,
                           "sourceSha256": source_sha, "targetSha256": _digest(plan["rows"]),
                           "appliedCount": plan["appliedCount"], "conflictCount": plan["conflictCount"],
                           "published": False}
                if resolve_sync_id is not None:
                    receipt.update(resolutionOf=resolve_sync_id, reviewToken=review_token)
                elif blocked is not None:
                    receipt["refreshOf"] = blocked
                lease.check()
                mark_publication()
                _write_receipt(receipt_path, receipt)
                lease.check()
                if _target(lease, state) != ledger:
                    raise MigrationIOError("episodic_sync_target_changed")
                verify_initial_personal_receipts(lease.root, lease.initial_id)
                lease.check()
                if plan["appliedCount"]:
                    transaction.events[:] = plan["rows"]
                    transaction._dirty = True
            actual = (_parse_rows(read_stable_file(ledger, _BYTE_CAP).raw, lease.agent_id)
                      if ledger.exists() or ledger.is_symlink() else [])
            if actual != plan["rows"]:
                raise MigrationIOError("episodic_sync_outcome_unknown")
            lease.check()
            _write_receipt(receipt_path, {**receipt, "published": True})
            return {"syncId": sync_id, "appliedCount": plan["appliedCount"],
                    "conflictCount": plan["conflictCount"], "reused": False}


def reconcile_episodic(lease, *, sync_id, confirmation_only=False, resolve_sync_id=None, review_token=None):
    published = False
    def mark_publication():
        nonlocal published
        published = True
    try:
        return _reconcile_episodic(lease, sync_id=sync_id, confirmation_only=confirmation_only,
            resolve_sync_id=resolve_sync_id, review_token=review_token, mark_publication=mark_publication)
    except (TimeoutError, MigrationIOError) as error:
        if (not published and not confirmation_only and (isinstance(error, TimeoutError)
                or str(error) == "migration_lock_unavailable")):
            raise EpisodicSyncPrewrite("busy") from None
        raise


def _synchronize_episodic(*, preview_binding, owner, generation, turn_id, initial_operation_id,
                          sync_id, confirmation_only, resolve_sync_id, review_token, mark_started):
    """Capture the approved source under the live host lease and synchronize."""
    if type(owner) is not OnlineEpisodicSyncOwner or type(preview_binding) is not tuple or len(preview_binding) != 6:
        raise MigrationIOError("episodic_sync_request_invalid")
    project, workspace, paths, agent_id, verify, snapshots = preview_binding
    if not isinstance(snapshots, tuple) or Path(paths.project_root) != project:
        raise MigrationIOError("episodic_sync_request_invalid")
    scope = {"projectId": paths.project_id, "instanceId": paths.instance_id, "agentId": agent_id}
    from .migration_active import _selected, _verify_captured
    from .migration_source_archive import import_source_snapshots
    from scripts.assistant_migration_activate import _capture
    with owner.admit(generation=generation, turn_id=turn_id, initial_operation_id=initial_operation_id,
                     source_scope=scope, project=project, workspace=workspace, verify=verify) as lease:
        if confirmation_only:
            with pinned_source_files(snapshots):
                lease.check()
                mark_started()
                return reconcile_episodic(lease, sync_id=sync_id, confirmation_only=True)
        captured, authority = _capture(project, workspace, scope, None, categories=frozenset({"episodic_memory"}))
        source = _selected(captured, "episodic_memory")
        _parse_rows(source.raw, agent_id)
        authority = (*snapshots, *authority)
        for path in (project, workspace, *captured.paths.values(), *(item.path for item in authority)):
            resolved = check_path(path).resolve()
            if lease.root.is_relative_to(resolved) or resolved.is_relative_to(lease.root):
                raise MigrationIOError("history_source_target_overlap")
        def verify_all():
            lease.check()
            _verify_captured(captured, authority, verify)
            lease.check()
        @contextmanager
        def write_guard():
            verify_all()
            yield
            verify_all()
        with pinned_source_files((*authority, source)):
            verify_all()
            import_source_snapshots(captured, lease.root, sync_id, source_roots=(project, workspace),
                authority_snapshots=authority, authority_verify=verify_all,
                categories=frozenset({"episodic_memory"}), write_guard=write_guard)
            verify_all()
            mark_started()
            result = reconcile_episodic(lease, sync_id=sync_id, resolve_sync_id=resolve_sync_id,
                                        review_token=review_token)
            verify_all()
            return result


def synchronize_episodic(*, preview_binding, owner, generation, turn_id, initial_operation_id,
                         sync_id, confirmation_only=False, resolve_sync_id=None, review_token=None):
    started = False
    def mark_started():
        nonlocal started
        started = True
    try:
        return _synchronize_episodic(preview_binding=preview_binding, owner=owner, generation=generation,
            turn_id=turn_id, initial_operation_id=initial_operation_id, sync_id=sync_id,
            confirmation_only=confirmation_only, resolve_sync_id=resolve_sync_id,
            review_token=review_token, mark_started=mark_started)
    except EpisodicSyncPrewrite:
        raise
    except Exception as error:
        if started or confirmation_only:
            raise
        message = str(error)
        if message in {"episodic_sync_busy", "affairs_sync_busy", "migration_lock_unavailable"}:
            code = "busy"
        elif message in {"episodic_sync_baseline_unavailable", "initial_receipts_unknown"} or isinstance(error, FileNotFoundError):
            code = "baseline_unavailable"
        elif message in {"affairs_sync_cancelled", "episodic_sync_lease_unavailable"}:
            code = "cancelled"
        else:
            code = "project_unavailable"
        raise EpisodicSyncPrewrite(code) from None


__all__ = ["OnlineEpisodicSyncOwner", "EpisodicSyncPrewrite", "reconcile_episodic", "synchronize_episodic"]
