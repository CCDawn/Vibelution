"""Prepare current-day unknown reminder evidence against a real offline target.

This protects the target from automatically replaying today's source affairs
when the old sender's history is incomplete. It is not a sender shutdown,
source-quiescence proof or authority to enable the Launcher reminder pump.
No source path, agent ID, item ID or day is accepted from a renderer/model.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.reminder_source_mutex import ReminderMutexLease, trusted_reminder_source_mutex_key
from . import native
from .migration_affairs import _BYTE_CAP, _parse_rows, _token
from .initial_migration_binding import _directory
from .migration_affairs_conflicts import (_digest, _load, _scope, _sync_receipt,
                                           _verify_record_sources, locked_affairs_target)
from .migration_io import (MigrationIOError, path_identity, pinned_source_files, pinned_target_directory,
                           publish_directory, read_stable_file, strict_json, verify_snapshot)
from .migration_profile import OfflineMigrationProfileLease
from .reminder_receipts import ReminderReceiptStore
from .reminder_source_identity import ReminderSourceObservation


def _preparation_id(ledger_key: str, authority: str, sync_id: str, target_agent_id: str, day: str, target_identity: dict) -> str:
    packed = json.dumps([ledger_key, authority, sync_id, target_agent_id, day, target_identity], ensure_ascii=True,
                        sort_keys=True, separators=(",", ":"))
    return "rprep-" + hashlib.sha256(packed.encode("ascii")).hexdigest()[:40]


def _receipt_directory(base: Path, preparations: Path, operation_id: str, intent_sha: str,
                       day: str, *, completed: bool, check) -> tuple[Path, bool]:
    """Publish a proven new day directory; never adopt an unproven one."""
    directory = base / day
    staging = base / ("." + operation_id + ".pending")
    proof_path = preparations / (operation_id + ".directory.json")
    has_proof = proof_path.exists() or proof_path.is_symlink()
    if not has_proof and (directory.exists() or directory.is_symlink()):
        if staging.exists() or staging.is_symlink():
            raise MigrationIOError("reminder_uncertainty_directory_unknown")
        return directory, False
    if not has_proof:
        if completed:
            raise MigrationIOError("reminder_uncertainty_directory_unknown")
        check()
        if not staging.exists() and not staging.is_symlink():
            staging.mkdir()
        with pinned_target_directory(staging):
            if any(staging.iterdir()):
                raise MigrationIOError("reminder_uncertainty_directory_unknown")
            identity = _directory(staging)
            proof = {"schemaVersion": 1, "operationId": operation_id, "intentSha256": intent_sha,
                     "day": day, "directory": identity}
            check()
            atomic_write_json(proof_path, proof, strict_replace=True, sort_keys=True)
    proof = strict_json(read_stable_file(proof_path, 4096).raw)
    if (type(proof) is not dict or set(proof) != {"schemaVersion", "operationId", "intentSha256", "day", "directory"}
            or type(proof["schemaVersion"]) is not int or proof["schemaVersion"] != 1
            or proof["operationId"] != operation_id or proof["intentSha256"] != intent_sha or proof["day"] != day):
        raise MigrationIOError("reminder_uncertainty_directory_unknown")
    if staging.exists() or staging.is_symlink():
        if directory.exists() or directory.is_symlink() or _directory(staging) != proof["directory"]:
            raise MigrationIOError("reminder_uncertainty_directory_unknown")
        with pinned_target_directory(staging):
            if any(staging.iterdir()):
                raise MigrationIOError("reminder_uncertainty_directory_unknown")
            before = path_identity(staging)
        check()
        publish_directory(staging, directory, before)
    if _directory(directory) != proof["directory"]:
        raise MigrationIOError("reminder_uncertainty_directory_unknown")
    if completed:
        return directory, False
    # The offline profile lock excludes all cooperating Launcher senders. A
    # missing journal beside a nonempty DB, or a journal beside an empty DB,
    # cannot prove initialization was interrupted before any send.
    db, journal = directory / "reminders.sqlite3", directory / "reminders.sqlite3-journal"
    db_size = db.stat().st_size if db.exists() and not db.is_symlink() else 0
    journal_size = journal.stat().st_size if journal.exists() and not journal.is_symlink() else 0
    if db.is_symlink() or journal.is_symlink() or (db_size and not journal.exists()) or (not db_size and journal_size):
        raise MigrationIOError("reminder_uncertainty_directory_unknown")
    return directory, True


def inspect_uncertainty_preparation(*, target: OfflineMigrationProfileLease, operation_id: str) -> dict:
    """Read an original receipt without claiming current source ownership.

    Main may display this recorded status while recovery is pending. To verify
    a current preparation it must invoke prepare_current_day_uncertainty with
    the same ID and live source/target locks; this read cannot enable a sender.
    """
    if (type(target) is not OfflineMigrationProfileLease or type(operation_id) is not str
            or not re.fullmatch(r"rprep-[a-f0-9]{40}", operation_id)):
        raise MigrationIOError("reminder_uncertainty_recovery_invalid")
    target.check()
    directory = target.root / "reminder_handoff_preparations"
    with pinned_target_directory(directory):
        snapshot = read_stable_file(directory / (operation_id + ".intent.json"), 1024 * 1024)
        value = strict_json(snapshot.raw)
        expected = {"schemaVersion", "operationId", "day", "syncId", "ledgerKey", "sourceAuthorityKey", "sourceScope", "targetAgentId", "targetDirectory",
                    "sourceSha256", "targetSha256", "eventIds", "state", "coverage", "readyForCutover"}
        if (not isinstance(value, dict) or set(value) != expected or value["schemaVersion"] != 1
                or type(value["schemaVersion"]) is not int or value["operationId"] != operation_id
                or value["targetAgentId"] != target.agent_id or not _token(value["syncId"])
                or value["targetDirectory"] != _directory(target.root)
                or any(type(value[name]) is not str or not re.fullmatch(r"[a-f0-9]{64}", value[name])
                       for name in ("ledgerKey", "sourceAuthorityKey"))
                or any(type(value[name]) is not str or not re.fullmatch(r"[a-f0-9]{64}", value[name])
                       for name in ("sourceSha256", "targetSha256"))
                or value["state"] != "pending" or value["coverage"] != "unknown" or value["readyForCutover"] is not False
                or type(value["day"]) is not str or not re.fullmatch(r"[0-9]{8}", value["day"])
                or type(value["eventIds"]) is not list or len(value["eventIds"]) > 2048):
            raise MigrationIOError("reminder_uncertainty_receipt_invalid")
        try:
            if datetime.strptime(value["day"], "%Y%m%d").strftime("%Y%m%d") != value["day"]:
                raise ValueError
            _scope(value["sourceScope"])
        except (ValueError, MigrationIOError):
            raise MigrationIOError("reminder_uncertainty_receipt_invalid") from None
        pattern = re.compile("reminder:" + value["day"] + r":[a-f0-9]{64}\Z")
        ids = value["eventIds"]
        if (any(type(item) is not str or pattern.fullmatch(item) is None for item in ids)
                or ids != sorted(set(ids))
                or _preparation_id(value["ledgerKey"], value["sourceAuthorityKey"], value["syncId"], target.agent_id, value["day"], value["targetDirectory"]) != operation_id):
            raise MigrationIOError("reminder_uncertainty_receipt_invalid")
        done_path = directory / (operation_id + ".done.json")
        recorded = "pending"
        if done_path.exists() or done_path.is_symlink():
            done = strict_json(read_stable_file(done_path, 4096).raw)
            if (not isinstance(done, dict) or type(done.get("schemaVersion")) is not int
                    or done.get("readyForCutover") is not False
                    or done != {"schemaVersion": 1, "operationId": operation_id, "intentSha256": snapshot.sha256,
                                "state": "prepared", "coverage": "unknown", "readyForCutover": False}):
                raise MigrationIOError("reminder_uncertainty_receipt_invalid")
            recorded = "prepared"
        verify_snapshot(snapshot)
        target.check()
        return {"schemaVersion": 1, "operationId": operation_id, "recordedState": recorded,
                "day": value["day"], "uncertainCount": len(ids), "sourceState": "unknown", "readyForCutover": False}


def prepare_current_day_uncertainty(*, source: ReminderSourceObservation,
                                    source_mutex: ReminderMutexLease,
                                    target: OfflineMigrationProfileLease,
                                    sync_id: str, recovery_id: str | None = None) -> dict:
    """Protect source-derived items for today after a verified, conflict-free sync.

    The caller must already have retired/fenced the managed source and obtain
    this *same-thread* source mutex; do not hold the same mutex in Electron.
    Offline target ownership is the existing OS host-owner lock, not a path or
    boolean. A live, possibly uncooperative old sender is outside this proof.
    recovery_id addresses the original durable intent; it never accepts a path.
    """
    if (type(source) is not ReminderSourceObservation or type(source_mutex) is not ReminderMutexLease
            or type(target) is not OfflineMigrationProfileLease or not isinstance(sync_id, str)):
        raise MigrationIOError("reminder_uncertainty_authority_unavailable")
    ledger_key = trusted_reminder_source_mutex_key(source)
    if source_mutex._key != ledger_key or source_mutex._verify != source._check:
        raise MigrationIOError("reminder_uncertainty_authority_unavailable")
    if source_mutex.abandoned:
        raise MigrationIOError("reminder_uncertainty_source_recovery_required")
    source_mutex.check()
    target.check()
    target_identity = _directory(target.root)
    with source._preview._lock:
        source._check()
        preview_row = source._preview._previews[source._token]
        project, workspace, paths = Path(preview_row[3]), Path(preview_row[4]), preview_row[5]
        for origin in (project, workspace):
            if target.root == origin or target.root.is_relative_to(origin) or origin.is_relative_to(target.root):
                raise MigrationIOError("reminder_uncertainty_source_target_overlap")
        scope = _scope({"projectId": paths.project_id, "instanceId": paths.instance_id, "agentId": source.agent_id})
        source_path = project / "agents" / source.agent_id / "plugins/personal-affairs/affairs/items.jsonl"
        snapshot = read_stable_file(source_path, _BYTE_CAP)
        source_rows = _parse_rows(snapshot.raw)
        source._check()
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    preparations = target.root / "reminder_handoff_preparations"
    previous = None
    if recovery_id is not None:
        if type(recovery_id) is not str or not re.fullmatch(r"rprep-[a-f0-9]{40}", recovery_id):
            raise MigrationIOError("reminder_uncertainty_recovery_invalid")
        with pinned_target_directory(preparations):
            previous = strict_json(read_stable_file(preparations / (recovery_id + ".intent.json"), 1024 * 1024).raw)
        if not isinstance(previous, dict) or not isinstance(previous.get("day"), str):
            raise MigrationIOError("reminder_uncertainty_recovery_invalid")
        day = previous["day"]
        try:
            if datetime.strptime(day, "%Y%m%d").strftime("%Y%m%d") != day or day > today:
                raise ValueError
        except ValueError:
            raise MigrationIOError("reminder_uncertainty_recovery_invalid") from None
    else:
        day = today
    with pinned_source_files((snapshot,)), native._LOCK, locked_affairs_target(target.root, target_agent_id=target.agent_id) as locked:
        def check():
            source_mutex.check()
            target.check()
            if _directory(target.root) != target_identity:
                raise MigrationIOError("reminder_uncertainty_target_changed")
            verify_snapshot(snapshot)
            locked.check(target.root, target.agent_id)
            if recovery_id is None and datetime.now(timezone.utc).strftime("%Y%m%d") != day:
                raise MigrationIOError("reminder_uncertainty_day_changed")

        check()
        record = _load(target.root, sync_id, scope, target.agent_id)
        _verify_record_sources(target.root, record, target=locked)
        receipt, _ = _sync_receipt(target.root, record)
        rows = locked.rows(target.root, target.agent_id)
        if (record["snapshotSha256"] != snapshot.sha256 or receipt is None
                or receipt["published"] is not True or receipt["conflictCount"] != 0
                or receipt["targetSha256"] != _digest(rows)):
            raise MigrationIOError("reminder_uncertainty_sync_unconfirmed")
        source_ids = {row["itemId"] for row in source_rows}
        # A currently completed or future item may have been reminded earlier
        # today and can later be reopened or made due. With incomplete legacy
        # history every source-derived target ID is conservatively unknown for
        # this UTC day; target-only and later-created items stay unaffected.
        ids = sorted({"reminder:" + day + ":" + hashlib.sha256(item["itemId"].encode("utf-8")).hexdigest()
                      for item in rows if item["itemId"] in source_ids})
        check()
        operation_id = _preparation_id(ledger_key, source._authority, sync_id, target.agent_id, day, target_identity)
        if recovery_id is not None and recovery_id != operation_id:
            raise MigrationIOError("reminder_uncertainty_recovery_invalid")
        intent = {"schemaVersion": 1, "operationId": operation_id, "day": day, "syncId": sync_id,
                  "ledgerKey": ledger_key, "sourceAuthorityKey": source._authority, "sourceScope": scope,
                  "targetAgentId": target.agent_id, "targetDirectory": target_identity,
                  "sourceSha256": snapshot.sha256, "targetSha256": receipt["targetSha256"],
                  "eventIds": ids, "state": "pending", "coverage": "unknown", "readyForCutover": False}
        with pinned_target_directory(preparations, create=recovery_id is None):
            intent_path = preparations / (operation_id + ".intent.json")
            done_path = preparations / (operation_id + ".done.json")
            if not intent_path.exists() and not intent_path.is_symlink():
                if recovery_id is not None or done_path.exists() or done_path.is_symlink():
                    raise MigrationIOError("reminder_uncertainty_recovery_invalid")
                check()
                atomic_write_json(intent_path, intent, strict_replace=True, sort_keys=True)
            intent_snapshot = read_stable_file(intent_path, 1024 * 1024)
            if strict_json(intent_snapshot.raw) != intent or (previous is not None and previous != intent):
                raise MigrationIOError("reminder_uncertainty_intent_conflict")
            inspect_uncertainty_preparation(target=target, operation_id=operation_id)
            done = {"schemaVersion": 1, "operationId": operation_id, "intentSha256": intent_snapshot.sha256,
                    "state": "prepared", "coverage": "unknown", "readyForCutover": False}
            completed = done_path.exists() or done_path.is_symlink()
            if completed and strict_json(read_stable_file(done_path, 4096).raw) != done:
                raise MigrationIOError("reminder_uncertainty_receipt_invalid")
            with pinned_source_files((intent_snapshot,)):
                base = target.root / "reminder_receipts"
                with pinned_target_directory(base, create=not completed):
                    directory, fresh = _receipt_directory(base, preparations, operation_id,
                        intent_snapshot.sha256, day, completed=completed, check=check)
                    owner = "assistant-" + hashlib.sha256(target.agent_id.encode()).hexdigest()
                    with ReminderReceiptStore(directory, owner_id=owner, maximum=4096, create=fresh) as store:
                        if completed and any(store.get(event_id) is None for event_id in ids):
                            raise MigrationIOError("reminder_uncertainty_receipt_invalid")
                        outcome = store.suppress_legacy_events(ids, source_observation=source,
                                                               ledger_key=ledger_key, check_source=check)
                check()
                verify_snapshot(intent_snapshot)
                if not completed:
                    atomic_write_json(done_path, done, strict_replace=True, sort_keys=True)
                if strict_json(read_stable_file(done_path, 4096).raw) != done:
                    raise MigrationIOError("reminder_uncertainty_receipt_invalid")
                check()
        return {"schemaVersion": 1, "state": "prepared", "operationId": operation_id, "day": day,
                "uncertainCount": len(ids), "created": outcome["created"],
                "sourceQuiesced": False, "readyForCutover": False}
