"""Bounded read-only review of one unresolved episodic synchronization."""
from __future__ import annotations

import hashlib
import json
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from core.infrastructure.native_runtime import assistant_native_root
from core.infrastructure.file_lock import cross_process_file_lock

from .migration_io import (MigrationIOError, migration_target_lock, pinned_mutable_file,
    pinned_source_files, pinned_target_directory, read_stable_file, strict_json, verify_snapshot)


class _Review(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sync_id: str = Field(pattern=r"^episodic-[a-f0-9]{40}$")
    offset: int = Field(default=0, ge=0, le=12288)
    limit: int = Field(default=3, ge=1, le=6)
    character_offset: int = Field(default=0, ge=0, le=4194304)
    max_characters: int = Field(default=240, ge=1, le=400)
    review_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def contracts():
    return {"episodic_conflict_review": {"action": "episodic_conflict_review", "governed": False,
        "description": "查看情景同步冲突的旧来源快照与当前目标差异；逐项比较 changedFields、text 和 metadataJson，按各自 nextCharacterOffset 续读，续页必须传 review_token=首屏 reviewToken。来源未冻结，保留目标对账前会重新核验。",
        "parameters": _Review.model_json_schema()}}


def execute(action, parameters, runtime):
    if action != "episodic_conflict_review":
        raise ValueError("未知情景记忆查询")
    try:
        args = _Review.model_validate(parameters)
        root = assistant_native_root()
    except (ValidationError, RuntimeError):
        raise ValueError("情景记忆查询参数或助理身份无效") from None
    from . import native
    if (not isinstance(runtime, dict) or not native._STARTED or native._OFFLINE_MIGRATION
            or native._STOP_REQUESTED.is_set() or runtime.get("agentId") != native._AGENT_ID
            or runtime.get("sessionId") != native._SESSION_ID):
        raise ValueError("情景差异只供当前 Launcher 助理查询")
    try:
        if (args.offset or args.character_offset) and args.review_token is None:
            raise MigrationIOError("episodic_review_token_required")
        return _review(root, native._AGENT_ID, native._SESSION_ID, args.sync_id, args.offset, args.limit,
                       args.character_offset, args.max_characters, args.review_token)
    except (MigrationIOError, OSError, TimeoutError):
        raise ValueError("情景差异暂不可用或来源校验未通过") from None


def _review(root, agent_id, session_id, sync_id, offset, limit, character_offset, max_characters, expected_token):
    from . import native
    from .initial_migration_binding import read_initial_intent, target_identity
    from .migration_episodic import _BYTE_CAP, _parse_rows, _target
    from .online_episodic_sync import _archive, _digest, _receipts, _review_token, _CHAIN_LIMIT, _CHAIN_BYTE_LIMIT
    from core.web.services import agent_directory_service as directory
    from core.web.services.external_management.state_snapshot import ExistingStateSnapshot
    from scripts.assistant_migration_activate import verify_initial_personal_receipts
    if not native._LOCK.acquire(blocking=False):
        raise MigrationIOError("episodic_sync_busy")
    try:
        root = Path(root)
        receipt_dir = root / "episodic_sync_receipts"
        receipt_path = receipt_dir / (hashlib.sha256(sync_id.encode()).hexdigest() + ".json")
        with pinned_target_directory(receipt_dir), migration_target_lock(receipt_dir):
            probe = strict_json(read_stable_file(receipt_path, 16384).raw)
            if type(probe) is not dict:
                raise MigrationIOError("episodic_sync_receipt_invalid")
            initial_id, scope = probe.get("initialId"), probe.get("sourceScope")
            intent = read_initial_intent(root, initial_id)
            if (intent is None or intent["category"] != "personal" or intent["sourceScope"] != scope
                    or intent["targetAgentId"] != agent_id or intent["targetSessionId"] != session_id
                    or target_identity(root, agent_id, session_id) != (intent["targetIdentityDigest"], intent["targetDirectory"])):
                raise MigrationIOError("episodic_sync_identity_changed")
            verify_initial_personal_receipts(root, initial_id)
            receipts = _receipts(receipt_dir, initial_id, scope, agent_id)
            if len(receipts) > _CHAIN_LIMIT:
                raise MigrationIOError("episodic_sync_receipt_limit")
            baseline, _, proofs = _archive(root, initial_id, scope)
            evidence_bytes = sum(len(proof.raw) for proof in proofs)
            digest = hashlib.sha256(initial_id.encode()).hexdigest() + ".json"
            proofs += tuple(read_stable_file(path, 16384) for path in (
                root / "initial_migration_claims" / initial_id / "claim.json",
                root / "episodic_migrations" / digest, root / "affairs_migrations" / digest))
            previous, visited, blocked, conflict_base = initial_id, set(), None, None
            for _ in range(len(receipts)):
                links = [(key, value) for key, value in receipts.items() if value[0]["parentId"] == previous]
                if len(links) != 1:
                    raise MigrationIOError("episodic_sync_baseline_ambiguous")
                key, (receipt, receipt_snapshot) = links[0]
                if key in visited:
                    raise MigrationIOError("episodic_sync_baseline_ambiguous")
                if blocked is not None:
                    prior = receipts[blocked][0]
                    resolved = (prior["published"] and prior["conflictCount"] > 0
                                and receipt.get("resolutionOf") == blocked and receipt["sourceSha256"] == prior["sourceSha256"]
                                and receipt.get("reviewToken") == _review_token(prior, receipt["targetSha256"]))
                    refreshed = (receipt.get("refreshOf") == blocked and prior["published"]
                                 and prior["conflictCount"] > 0)
                    if not (resolved or refreshed):
                        raise MigrationIOError("episodic_sync_baseline_unresolved")
                    blocked = None
                    if resolved:
                        conflict_base = None
                elif "resolutionOf" in receipt or "refreshOf" in receipt:
                    raise MigrationIOError("episodic_sync_receipt_invalid")
                rows, sha, archive_proofs = _archive(root, key, scope)
                evidence_bytes += sum(len(proof.raw) for proof in archive_proofs) + len(receipt_snapshot.raw)
                if evidence_bytes > _CHAIN_BYTE_LIMIT:
                    raise MigrationIOError("episodic_sync_receipt_limit")
                if sha != receipt["sourceSha256"] or not receipt["published"]:
                    raise MigrationIOError("episodic_sync_baseline_unresolved")
                visited.add(key); proofs += (*archive_proofs, receipt_snapshot)
                if receipt["conflictCount"]:
                    blocked = key
                    if conflict_base is None:
                        conflict_base = baseline
                    before, after = conflict_base, rows
                baseline, previous = rows, key
            if visited != set(receipts) or blocked != sync_id:
                raise MigrationIOError("episodic_sync_baseline_unresolved")
            receipt = receipts[sync_id][0]
            state = ExistingStateSnapshot(root, directory, pin_workspace=True)
            ledger = _target(SimpleNamespace(root=root, agent_id=agent_id), state)
            with ExitStack() as stack:
                for archive_id in {initial_id, *visited}:
                    stack.enter_context(pinned_target_directory(root / "history_sources" / "migrations" / archive_id / ".confirmed"))
                stack.enter_context(pinned_target_directory(ledger.parent))
                stack.enter_context(pinned_mutable_file(ledger.with_name(ledger.name + ".lock"), create=False))
                stack.enter_context(cross_process_file_lock(ledger, timeout=0))
                snapshot = read_stable_file(ledger, _BYTE_CAP) if ledger.exists() or ledger.is_symlink() else None
                current = _parse_rows(snapshot.raw, agent_id) if snapshot else []
                all_proofs = (*proofs, *((snapshot,) if snapshot else ()))
                stack.enter_context(pinned_source_files(all_proofs))
                if _target(SimpleNamespace(root=root, agent_id=agent_id), state) != ledger:
                    raise MigrationIOError("episodic_sync_target_changed")
                for proof in all_proofs:
                    verify_snapshot(proof)
                verify_initial_personal_receipts(root, initial_id)
                if _receipts(receipt_dir, initial_id, scope, agent_id) != receipts:
                    raise MigrationIOError("episodic_sync_target_changed")
                token = _review_token(receipt, _digest(current))
                if expected_token is not None and expected_token != token:
                    raise MigrationIOError("episodic_review_changed")
                old = {row["episodeId"]: row for row in before}
                new = {row["episodeId"]: row for row in after}
                actual = {row["episodeId"]: row for row in current}
                # A structural conflict can involve a target-only row (for
                # example an eventId collision), which has no source ID to
                # enumerate. Include those rows for review without treating
                # them as deletion candidates or changing the target.
                target_only = actual.keys() - (old.keys() | new.keys())
                changed = [key for key in sorted(old.keys() | new.keys() | target_only)
                           if key in target_only or old.get(key) != new.get(key)
                           or actual.get(key) != ({**new[key], "agentId": agent_id} if key in new else None)]
                def content(row):
                    if row is None:
                        return None
                    text = row["text"]
                    end = min(len(text), character_offset + max_characters)
                    # Text alone hides changes to validity, references and the
                    # succession chain. Return every remaining native field in
                    # bounded pages; agentId differs by design after migration.
                    metadata = json.dumps({k: v for k, v in row.items() if k not in {"text", "agentId"}},
                                          ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    metadata_end = min(len(metadata), character_offset + max_characters)
                    return {"text": text[character_offset:end], "characterOffset": character_offset,
                            "nextCharacterOffset": end if end < len(text) else None,
                            "metadataJson": metadata[character_offset:metadata_end],
                            "metadataNextCharacterOffset": metadata_end if metadata_end < len(metadata) else None}
                def changed_fields(source, target):
                    source = source or {}
                    target = target or {}
                    return sorted(key for key in (source.keys() | target.keys()) - {"agentId"}
                                  if source.get(key) != target.get(key))
                result = [{"episodeId": key, "kind": "target_only" if key in target_only else "added" if key not in old else "removed" if key not in new else "changed",
                           "changedFields": changed_fields(new.get(key), actual.get(key)),
                           "source": content(new.get(key)), "target": content(actual.get(key))}
                          for key in changed[offset:offset + limit]]
                return {"syncId": sync_id, "reviewToken": token,
                        "differences": result, "total": len(changed),
                        "nextOffset": offset + len(result) if offset + len(result) < len(changed) else None,
                        "readOnly": True, "untrustedContent": True, "sourceSnapshotOnly": True,
                        "notice": "目标独有记录供检查跨记录冲突；保留目标将接受本批全部差异，来源或目标变化后必须重新查看。"}
    finally:
        native._LOCK.release()
