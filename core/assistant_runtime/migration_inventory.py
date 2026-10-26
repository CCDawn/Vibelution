"""Read-only PA source evidence. No bootstrap, data copy, repair or cutover.

The caller resolves active storage through vibelution_storage before calling.
This inventory is not a prepared migration: live files may change immediately
after observation. Native quiescence/watermarks and handoff remain mandatory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_PROFILE = "personal_assistant_v1"
_PENDING = ("source_selection", "source_quiescence", "native_session_ownership", "legacy_session_discovery",
            "native_journal_watermark", "target_history_import",
            "private_memory_migration", "private_knowledge_custom_paths", "personal_affairs_migration", "legacy_dispatch_handoff",
            "workflow_recovery_authority", "pending_approval_disposition", "target_verification", "platform_retirement")


class InventoryError(ValueError):
    """A bounded failure; never include source content in diagnostics."""


def _hash_file(path: Path, expected_size: int) -> str:
    digest = hashlib.sha256()
    remaining = expected_size
    with path.open("rb") as stream:
        while remaining:
            block = stream.read(min(128 * 1024, remaining))
            if not block:
                raise InventoryError("source_changed")
            digest.update(block)
            remaining -= len(block)
        if stream.read(1):
            raise InventoryError("source_changed")
    return digest.hexdigest()


def _linked(path: Path) -> bool:
    value = path.lstat()
    return stat.S_ISLNK(value.st_mode) or bool(getattr(value, "st_file_attributes", 0) & 0x400)


def _checked(root: Path, *parts: str) -> Path:
    path = root
    for part in parts:
        path = path / part
        if path.exists() or path.is_symlink():
            if _linked(path):
                raise InventoryError("linked_source")
    if not path.resolve().is_relative_to(root):
        raise InventoryError("source_outside_scope")
    return path


def _identity(path: Path) -> tuple:
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _tree(path: Path, *, max_file_bytes: int, max_files: int, expected_file: bool = False) -> dict:
    result = {"available": False, "entries": [], "issues": []}
    try:
        if _linked(path):
            result["issues"].append({"path": "", "code": "linked_source"})
            return result
    except FileNotFoundError:
        return result
    except OSError:
        result["issues"].append({"path": "", "code": "source_unreadable"})
        return result
    result["available"] = True
    mode = path.lstat().st_mode
    if (expected_file and not stat.S_ISREG(mode)) or (not expected_file and not stat.S_ISDIR(mode)):
        result["issues"].append({"path": "", "code": "source_type_mismatch"})
        return result
    base = path if path.is_dir() else path.parent

    def files():
        if path.is_file():
            yield path
            return
        pending = [path]
        visited = 0
        while pending:
            current = pending.pop()
            try:
                # scandir is incremental: os.walk first allocates the entire
                # directory even when the caller only needs a bounded prefix.
                with os.scandir(current) as children:
                    for child in children:
                        if visited >= max_files:
                            result["issues"].append({"path": "", "code": "file_limit"})
                            return
                        visited += 1
                        entry = Path(child.path)
                        if child.name.endswith(".lock"):
                            continue
                        if _linked(entry):
                            result["issues"].append({"path": entry.relative_to(base).as_posix(), "code": "linked_source"})
                        elif child.is_dir(follow_symlinks=False):
                            pending.append(entry)
                        elif child.is_file(follow_symlinks=False):
                            yield entry
                        else:
                            result["issues"].append({"path": entry.relative_to(base).as_posix(), "code": "source_type_mismatch"})
            except OSError:
                result["issues"].append({"path": "", "code": "source_unreadable"})

    for entry in files():
        relative = entry.relative_to(base).as_posix()
        try:
            if _linked(entry) or not entry.resolve().is_relative_to(base.resolve()):
                result["issues"].append({"path": relative, "code": "linked_source"})
                continue
            before = _identity(entry)
            if before[2] > max_file_bytes:
                result["issues"].append({"path": relative, "code": "file_too_large"})
                continue
            digest = _hash_file(entry, before[2])
            if _identity(entry) != before:
                result["issues"].append({"path": relative, "code": "source_changed"})
                continue
            result["entries"].append({"path": relative, "size": before[2], "sha256": digest})
        except InventoryError:
            result["issues"].append({"path": relative, "code": "source_changed"})
        except OSError:
            result["issues"].append({"path": relative, "code": "source_unreadable"})
    result["entries"].sort(key=lambda row: row["path"])
    return result


def inventory_sources(*, project_root: Path, workspace: Path, project_id: str, instance_id: str,
                      max_file_bytes: int = 64 * 1024 * 1024, max_files: int = 10000) -> dict:
    """Fingerprint only PA-owned scopes. Never select, pause or import one."""
    if not all(isinstance(p, Path) and p.is_absolute() for p in (project_root, workspace)):
        raise InventoryError("absolute_source_roots_required")
    if max_file_bytes < 1 or max_files < 1:
        raise InventoryError("positive_inventory_limits_required")
    for root in (project_root, workspace):
        try:
            if _linked(root):
                raise InventoryError("linked_source_root")
        except OSError:
            raise InventoryError("source_root_unavailable") from None
    project_root, workspace = project_root.resolve(), workspace.resolve()
    registry = _checked(workspace, "agents", "agents.json")
    try:
        before = _identity(registry)
        if before[2] > 16 * 1024 * 1024:
            raise InventoryError("registry_too_large")
        with registry.open("rb") as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise InventoryError("registry_too_large")
        payload = json.loads(raw.decode("utf-8-sig"))
        rows = payload["agents"]
        if (not isinstance(rows, list) or len(rows) > 100000 or any(not isinstance(row, dict) for row in rows)
                or _identity(registry) != before):
            raise InventoryError("registry_unavailable_or_changed")
    except (OSError, ValueError, KeyError, TypeError):
        raise InventoryError("registry_unavailable_or_changed") from None
    candidates = []
    for row in rows:
        metadata = row.get("metadata", {})
        if row.get("roleKey") != "personal_assistant" and not (isinstance(metadata, dict) and metadata.get("personalAssistantProfile")):
            continue
        aid, sid = row.get("agentId"), row.get("directSessionId")
        if (not isinstance(metadata, dict) or metadata.get("personalAssistantProfile") != _PROFILE
                or row.get("roleKey") != "personal_assistant" or not isinstance(row.get("toolPolicy", {}), dict)
                or not isinstance(row.get("status"), str) or row["status"] not in {"active", "archived"}
                or not all(isinstance(v, str) and _TOKEN.fullmatch(v) for v in (aid, sid))
                or any(candidate["agentId"] == aid or candidate["sessionId"] == sid for candidate in candidates)
                or any(other is not row and (other.get("agentId") == aid or other.get("directSessionId") == sid) for other in rows)):
            raise InventoryError("assistant_identity_unavailable")
        if len(candidates) >= 32:
            raise InventoryError("too_many_source_candidates")
        locations = {
            "journal": (workspace, ("sessions", sid, "turn_journal.jsonl")),
            "session_assets": (workspace, ("sessions", sid, "artifacts")),
            "agent_assets": (workspace, ("agents", aid, "artifacts")),
            "memory": (workspace, ("agents", aid, "memory")),
            "episodic_memory": (workspace, ("agents", aid, "events", "episodic_events.jsonl")),
            "dispatch_events": (workspace, ("agents", aid, "events", "agent_inbox_messages.jsonl")),
            "private_knowledge": (workspace, ("agents", aid, "knowledge")),
            "mental_model": (workspace, ("agents", aid, "mental_model")),
            "inbox": (workspace, ("agents", aid, "inbox")),
            "outbox": (workspace, ("agents", aid, "outbox")),
            "plugins": (workspace, ("agents", aid, "plugins")),
            # Existing PersonalAffairsService's default owner; do not infer
            # an empty ledger from the differently routed plugin location.
            "legacy_personal_affairs": (project_root, ("agents", aid, "plugins", "personal-affairs")),
        }
        files = {}
        for category, (base, parts) in locations.items():
            try:
                path = _checked(base, *parts)
                files[category] = _tree(path, max_file_bytes=max_file_bytes, max_files=max_files,
                    expected_file=category in {"journal", "episodic_memory", "dispatch_events"})
            except (InventoryError, OSError):
                files[category] = {"available": False, "entries": [], "issues": [{"path": "", "code": "source_unavailable"}]}
        encoded = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        candidates.append({"agentId": aid, "sessionId": sid, "status": row.get("status"),
            "agentConfigSha256": hashlib.sha256(encoded).hexdigest(), "files": files,
            "inventoryComplete": files["journal"]["available"] and not any(item["issues"] for item in files.values())})
    return {"schemaVersion": 1, "stage": "inventory", "inventoryScope": "declared_current_identity_only",
            "observedAt": datetime.now(timezone.utc).isoformat(),
            "sourceScope": {"projectId": project_id, "instanceId": instance_id, "projectRoot": str(project_root), "workspace": str(workspace)},
            "registrySha256": hashlib.sha256(raw).hexdigest(), "candidates": candidates,
            "selectionRequired": sum(row["status"] == "active" for row in candidates) != 1,
            "sourceQuiesced": False, "readyForCutover": False, "pendingChecks": list(_PENDING)}
