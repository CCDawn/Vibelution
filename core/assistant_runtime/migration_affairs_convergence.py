"""Record a verified convergence of previously unresolved affairs differences.

This capability never changes the affairs ledger. A proof is meaningful only
while its source, receipt and the current target still satisfy the checks.
"""
from __future__ import annotations

import hashlib
import os
from contextlib import ExitStack, nullcontext
from pathlib import Path

from core.infrastructure.atomic_io import _write_temp_file
from core.infrastructure.file_lock import cross_process_file_lock
from core.agent_plugins.personal_affairs.service import AFFAIR_LEDGER_LIMIT

from .migration_affairs import _BYTE_CAP, _parse_rows, _token
from .migration_affairs_conflicts import (
    _BaselineVerifier, _CHAIN_BYTE_LIMIT, _LockedAffairsTarget, _digest, _load, _record_path, _scope, _sync_receipt,
    _verify_record_sources, locked_affairs_target,
)
from .migration_history import _confirmation_exists, _confirm_archive, _encoded
from .migration_io import (
    MigrationIOError, migration_target_lock, path_identity, pinned_mutable_file,
    pinned_source_files, pinned_target_directory, publish_directory, read_stable_file, strict_json,
)
from .online_affairs_sync_lease import OnlineAffairsSyncLease, check_affairs_sync_lease

_PROOF_CAP = 1024 * 1024


def _proof_directory(root, sync_id):
    return Path(root) / "affairs_convergences" / hashlib.sha256(sync_id.encode()).hexdigest()


def _resolution_ids(record, receipt):
    if receipt is None or receipt["published"] is not True:
        raise MigrationIOError("affairs_convergence_receipt_unconfirmed")
    unresolved = {decision["conflictId"] for decision in receipt["decisions"]
                  if decision["status"] == "unresolved"}
    if not unresolved:
        raise MigrationIOError("affairs_convergence_not_required")
    matched = []
    for row in record["conflicts"]:
        if row["conflictId"] in unresolved:
            if row["source"] is None:
                raise MigrationIOError("affairs_convergence_not_reached")
            matched.append(row["conflictId"])
    if len(matched) != len(unresolved):
        raise MigrationIOError("affairs_convergence_invalid")
    return matched


def _unresolved(record, receipt, target_rows):
    matched = _resolution_ids(record, receipt)
    if not isinstance(target_rows, list) or len(target_rows) > AFFAIR_LEDGER_LIMIT:
        raise MigrationIOError("affairs_convergence_target_invalid")
    encoded = bytearray()
    for row in target_rows:
        if not isinstance(row, dict):
            raise MigrationIOError("affairs_convergence_target_invalid")
        encoded.extend(_encoded(row) + b"\n")
        if len(encoded) > _BYTE_CAP:
            raise MigrationIOError("affairs_convergence_target_invalid")
    if _parse_rows(bytes(encoded)) != target_rows:
        raise MigrationIOError("affairs_convergence_target_invalid")
    current = {row["itemId"]: row for row in target_rows}
    for row in record["conflicts"]:
        if row["conflictId"] in matched:
            if current.get(row["itemId"]) != row["source"]:
                raise MigrationIOError("affairs_convergence_not_reached")
    return matched


def _proof_binding(record, receipt, matched):
    return {"schemaVersion": 1, "syncId": record["syncId"], "sourceScope": record["sourceScope"],
            "targetAgentId": record["targetAgentId"], "recordSha256": _digest(record),
            "receiptSha256": _digest(receipt), "resolvedConflictIds": matched,
            "readOnly": True, "sourceQuiesced": False, "readyForCutover": False}


def _checked_proof(directory, record, receipt, matched):
    # observedTargetSha256 is an audit summary, not authentication. The
    # confirmed local archive and its writer remain the trust boundary.
    proof = strict_json(read_stable_file(directory / "proof.json", _PROOF_CAP).raw)
    binding = _proof_binding(record, receipt, matched)
    if (not isinstance(proof, dict) or set(proof) != set(binding) | {"observedTargetSha256"}
            or any(proof.get(key) != value for key, value in binding.items())
            or type(proof.get("schemaVersion")) is not int
            or proof.get("readOnly") is not True or proof.get("sourceQuiesced") is not False
            or proof.get("readyForCutover") is not False
            or not isinstance(proof.get("observedTargetSha256"), str)
            or len(proof["observedTargetSha256"]) != 64
            or any(c not in "0123456789abcdef" for c in proof["observedTargetSha256"])):
        raise MigrationIOError("affairs_convergence_invalid")
    return proof


def _verified_convergence_snapshot(root, record, receipt, target_rows):
    """Verify a bound proof; caller verifies source chain and holds ledger lock."""
    directory = _proof_directory(root, record["syncId"])
    if not directory.exists() and not directory.is_symlink():
        return None
    if not _confirmation_exists(directory):
        return None
    try:
        matched = _unresolved(record, receipt, target_rows)
    except MigrationIOError as error:
        if str(error) in {"affairs_convergence_not_reached", "affairs_convergence_not_required"}:
            return None
        raise
    snapshot = read_stable_file(directory / "proof.json", _PROOF_CAP)
    _checked_proof(directory, record, receipt, matched)
    return snapshot


def _verified_historical_convergence_snapshot(root, record, receipt):
    """Validate an already-confirmed historical resolution, not today's value."""
    directory = _proof_directory(root, record["syncId"])
    if not directory.exists() and not directory.is_symlink():
        return None
    if not _confirmation_exists(directory):
        return None
    try:
        matched = _resolution_ids(record, receipt)
    except MigrationIOError as error:
        if str(error) in {"affairs_convergence_not_reached", "affairs_convergence_not_required"}:
            return None
        raise
    snapshot = read_stable_file(directory / "proof.json", _PROOF_CAP)
    _checked_proof(directory, record, receipt, matched)
    return snapshot


def _write_proof_new(path, proof):
    # A crash during the write leaves only a private temp file, never a
    # truncated proof.json that would prevent a safe same-ID retry.
    temporary = _write_temp_file(path, _encoded(proof).decode("utf-8"), ensure_fsync=True)
    if temporary is None:
        raise MigrationIOError("affairs_convergence_write_failed")
    try:
        # On Windows os.rename is no-replace; an unexpected existing proof is
        # never overwritten, including one created by a non-cooperating writer.
        os.rename(temporary, path)
    except OSError:
        raise MigrationIOError("affairs_convergence_write_failed") from None
    finally:
        if temporary.exists():
            temporary.unlink()


def verify_affairs_convergence(root, *, sync_id, source_scope, target_agent_id, target_rows, target=None):
    """Return whether a confirmed proof applies to the supplied current rows.

    Caller must hold the native ledger lock while reading and using target_rows;
    it must also revalidate before acting on a discovery result.
    """
    root, scope = Path(root), _scope(source_scope)
    if target is not None:
        if not isinstance(target, _LockedAffairsTarget):
            raise MigrationIOError("affairs_target_lock_required")
        if target.rows(root, target_agent_id) != target_rows:
            raise MigrationIOError("source_changed")
    record = _load(root, sync_id, scope, target_agent_id)
    _verify_record_sources(root, record, target=target)
    receipt, _ = _sync_receipt(root, record)
    directory = _proof_directory(root, sync_id)
    if not directory.exists() and not directory.is_symlink():
        return False
    if not _confirmation_exists(directory):
        return False
    try:
        matched = _unresolved(record, receipt, target_rows)
    except MigrationIOError as error:
        if str(error) in {"affairs_convergence_not_reached", "affairs_convergence_not_required"}:
            return False
        raise
    from core.web.services.personal_assistant_project.windows_read import lock_source_directory
    snapshot = read_stable_file(directory / "proof.json", _PROOF_CAP)
    marker = directory / ".confirmed"
    with pinned_source_files((snapshot,)), lock_source_directory(Path(marker.anchor), marker, allow_child_replacement=True):
        _checked_proof(directory, record, receipt, matched)
        # Recheck after reading the proof; the caller owns target serialization.
        _verify_record_sources(root, record, target=target)
        current_receipt, _ = _sync_receipt(root, record)
        if current_receipt != receipt or not _confirmation_exists(directory):
            raise MigrationIOError("source_changed")
    return True


def _evidence(root, record, receipt_snapshot, *, target=None):
    """Capture every file used by the verified baseline and source archive."""
    verifier = _BaselineVerifier(root, record["sourceScope"], record["targetAgentId"], target=target)
    _verify_record_sources(root, record, verifier)
    verifier.finish()
    snapshots = [receipt_snapshot, *verifier.snapshots]
    observed = sum(len(snapshot.raw) for snapshot in snapshots)
    if observed > _CHAIN_BYTE_LIMIT:
        raise MigrationIOError("affairs_convergence_evidence_limit")
    def capture(path, maximum):
        nonlocal observed
        try:
            snapshot = read_stable_file(path, min(maximum, _CHAIN_BYTE_LIMIT - observed))
        except MigrationIOError as error:
            if str(error) == "file_byte_limit":
                raise MigrationIOError("affairs_convergence_evidence_limit") from None
            raise
        observed += len(snapshot.raw)
        return snapshot
    snapshots.append(capture(_record_path(root, record["syncId"]), _PROOF_CAP * 16))
    markers = []
    for mid in verifier.archives:
        directory = root / "history_sources/migrations" / mid
        manifest = capture(directory / "manifest.json", 16 * 1024 * 1024)
        data = strict_json(manifest.raw)
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            raise MigrationIOError("affairs_conflict_archive_invalid")
        entries = [entry for entry in data["entries"] if isinstance(entry, dict)
                   and entry.get("category") == "personal_affairs"
                   and _token(entry.get("sourceRef"))
                   and entry.get("path") == f"sources/{entry.get('sourceRef')}/affairs/items.jsonl"]
        if len(entries) != 1:
            raise MigrationIOError("affairs_conflict_archive_invalid")
        snapshots.append(manifest)
        snapshots.append(capture(directory / entries[0]["path"], _BYTE_CAP))
        markers.append(directory / ".confirmed")
    return snapshots, markers


def converge_affairs(lease, *, sync_id, source_scope):
    """Publish one immutable proof, without writing any target affair row."""
    scope = _scope(source_scope)
    check_affairs_sync_lease(lease, source_scope=scope,
                            baseline_migration_id=getattr(lease, "baseline_migration_id", None))
    root = Path(lease.root)
    record = _load(root, sync_id, scope, lease.agent_id)
    def check():
        check_affairs_sync_lease(lease, source_scope=scope, baseline_migration_id=record["baselineMigrationId"])
    check()
    from . import native
    from core.web.services import personal_affairs_service
    from core.web.services.personal_assistant_project.windows_read import lock_source_directory

    service = personal_affairs_service.get_personal_affairs_service()
    plugin = root / "agents" / lease.agent_id / "plugins" / "personal-affairs"
    if personal_affairs_service.PROJECT_ROOT != root or service.store.plugin_root(lease.agent_id) != plugin:
        raise MigrationIOError("affairs_target_binding_invalid")
    ledger = plugin / "affairs/items.jsonl"
    receipts = root / "affairs_sync_receipts"
    proofs = root / "affairs_convergences"
    final = _proof_directory(root, sync_id)
    pending = proofs / ("." + final.name + ".pending")
    ledger_lock = (cross_process_file_lock(ledger, timeout=0) if isinstance(lease, OnlineAffairsSyncLease)
                   else cross_process_file_lock(ledger))
    # Same order as reconcile: native -> receipts -> ledger; the proof lock
    # is acquired before the ledger and is never acquired by reconcile.
    with native._LOCK, pinned_target_directory(receipts), migration_target_lock(receipts), \
            pinned_target_directory(proofs, create=True), migration_target_lock(proofs), \
            pinned_target_directory(ledger.parent, create=True), \
            pinned_mutable_file(ledger.with_name(ledger.name + ".lock")), ledger_lock, \
            locked_affairs_target(root, target_agent_id=lease.agent_id) as target:
        check()
        record = _load(root, sync_id, scope, lease.agent_id)
        check()
        _verify_record_sources(root, record, target=target)
        receipt, receipt_snapshot = _sync_receipt(root, record)
        ledger_snapshot = read_stable_file(ledger, _BYTE_CAP) if ledger.exists() or ledger.is_symlink() else None
        current = _parse_rows(ledger_snapshot.raw) if ledger_snapshot is not None else []
        matched = _unresolved(record, receipt, current)
        proof = {**_proof_binding(record, receipt, matched), "observedTargetSha256": _digest(current)}
        snapshots, markers = _evidence(root, record, receipt_snapshot, target=target)
        if ledger_snapshot is not None:
            snapshots.append(ledger_snapshot)
        with ExitStack() as stack:
            stack.enter_context(pinned_source_files(snapshots))
            for marker in sorted(set(markers), key=str):
                stack.enter_context(lock_source_directory(Path(marker.anchor), marker, allow_child_replacement=True))

            def recheck():
                check()
                latest_record = _load(root, sync_id, scope, lease.agent_id)
                if latest_record != record:
                    raise MigrationIOError("source_changed")
                _verify_record_sources(root, record, target=target)
                latest_receipt, _ = _sync_receipt(root, record)
                if latest_receipt != receipt:
                    raise MigrationIOError("source_changed")
                rows = _parse_rows(read_stable_file(ledger, _BYTE_CAP).raw) if ledger.exists() or ledger.is_symlink() else []
                if _unresolved(record, receipt, rows) != matched:
                    raise MigrationIOError("affairs_convergence_not_reached")
                check()

            if final.exists() or final.is_symlink():
                _checked_proof(final, record, receipt, matched)
                reused = True
            else:
                with pinned_target_directory(pending, create=True):
                    file = pending / "proof.json"
                    if file.exists() or file.is_symlink():
                        _checked_proof(pending, record, receipt, matched)
                    else:
                        _write_proof_new(file, proof)
                    identity = path_identity(pending)
                recheck()
                publish_directory(pending, final, identity)
                reused = False
            proof_snapshot = read_stable_file(final / "proof.json", _PROOF_CAP)
            with pinned_source_files((proof_snapshot,)):
                _checked_proof(final, record, receipt, matched)
                if not _confirmation_exists(final):
                    _confirm_archive(final, nullcontext, authority_verify=recheck)
                else:
                    recheck()
            return {"syncId": sync_id, "convergedCount": len(matched), "reused": reused,
                    "sourceQuiesced": False, "readyForCutover": False}
