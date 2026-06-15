"""Hard-delete cleanup helpers for Memory Library targets."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import agent_directory_service, memory_service, rag_vector_index_service, team_knowledge_service
from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1
CONFIRMATION_PHRASE = "硬删除记忆"
MEMORY_DB_TABLES = ("LongTermMemory", "TaskLog", "ErrorArchive", "CodebaseKnowledge")
TARGET_TYPES = {
    "global_runtime_memory",
    "agent_private_memory",
    "agent_formal_knowledge",
    "team_knowledge",
    "knowledge_base",
    "agent_memory_policy",
    "sqlite_database_compact",
    "evaluation_artifacts",
    "session_artifacts",
    "legacy_log_info",
    "runtime_scene_logs",
    "team_archive_artifacts",
}
MAINTENANCE_TARGET_LABELS = {
    "sqlite_database_compact": "SQLite database compact",
    "evaluation_artifacts": "Evaluation artifacts",
    "session_artifacts": "Session artifacts",
    "legacy_log_info": "Legacy log_info logs",
    "runtime_scene_logs": "Runtime scene logs",
    "team_archive_artifacts": "Team archive artifacts",
}
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")


class MemoryCleanupError(ValueError):
    """Raised when a memory cleanup request is invalid or unsafe."""


@dataclass(frozen=True)
class CleanupTarget:
    target_type: str
    owner_type: str = ""
    owner_id: str = ""
    agent_id: str = ""
    team_id: str = ""
    knowledge_base_id: str = ""
    scoped_knowledge_base_id: str = ""
    label: str = ""

    @property
    def key(self) -> str:
        parts = [
            self.target_type,
            self.owner_type,
            self.owner_id,
            self.agent_id,
            self.team_id,
            self.knowledge_base_id,
            self.scoped_knowledge_base_id,
        ]
        return ":".join(part for part in parts if part)


@dataclass(frozen=True)
class CleanupPath:
    path: Path
    kind: str
    action: str
    note: str = ""


def preview_memory_cleanup(targets: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Return a hard-delete preview for selected memory cleanup targets."""

    started_at = time.perf_counter()
    normalized_targets = _normalize_targets(targets)
    target_previews = [_preview_target(target) for target in normalized_targets]
    totals = _sum_target_totals(target_previews)
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "hard_delete_memory_cleanup_preview",
        "hardDelete": True,
        "confirmationPhrase": CONFIRMATION_PHRASE,
        "targets": target_previews,
        "totals": totals,
        "operatingBoundary": _operating_boundary(),
        "generatedAt": team_knowledge_service.utc_now_iso(),
        "elapsedMs": round((time.perf_counter() - started_at) * 1000, 1),
    }
    _record_cleanup_event("memory.cleanup.preview.generated", payload, outcome="succeeded")
    return payload


def execute_memory_cleanup(
    targets: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    confirmation_phrase: str = "",
) -> dict[str, Any]:
    """Hard-delete selected memory cleanup targets after exact confirmation."""

    if str(confirmation_phrase or "").strip() != CONFIRMATION_PHRASE:
        raise MemoryCleanupError(f'Confirmation phrase must be "{CONFIRMATION_PHRASE}".')
    started_at = time.perf_counter()
    normalized_targets = _normalize_targets(targets)
    results = [_execute_target(target) for target in normalized_targets]
    totals = _sum_target_totals(results)
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "hard_delete_memory_cleanup_execute",
        "hardDelete": True,
        "confirmationPhrase": CONFIRMATION_PHRASE,
        "targets": results,
        "totals": totals,
        "operatingBoundary": _operating_boundary(),
        "generatedAt": team_knowledge_service.utc_now_iso(),
        "elapsedMs": round((time.perf_counter() - started_at) * 1000, 1),
    }
    _append_cleanup_audit(payload)
    _clear_memory_caches()
    _record_cleanup_event("memory.cleanup.executed", payload, outcome="succeeded")
    return payload


def _normalize_targets(targets: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[CleanupTarget]:
    _sync_roots()
    if not isinstance(targets, (list, tuple)) or not targets:
        raise MemoryCleanupError("At least one memory cleanup target is required.")
    if len(targets) > 200:
        raise MemoryCleanupError("Too many memory cleanup targets.")
    normalized: list[CleanupTarget] = []
    seen: set[str] = set()
    for raw in targets:
        if not isinstance(raw, dict):
            raise MemoryCleanupError("Memory cleanup targets must be objects.")
        target = _normalize_target(raw)
        if target.key in seen:
            continue
        seen.add(target.key)
        normalized.append(target)
    if not normalized:
        raise MemoryCleanupError("No valid memory cleanup targets were selected.")
    return normalized


def _normalize_target(raw: dict[str, Any]) -> CleanupTarget:
    target_type = str(raw.get("targetType") or raw.get("type") or "").strip()
    if target_type not in TARGET_TYPES:
        raise MemoryCleanupError(f"Unsupported memory cleanup target type: {target_type}")

    if target_type == "global_runtime_memory":
        return CleanupTarget(target_type=target_type, label="Global runtime memory")

    if target_type in MAINTENANCE_TARGET_LABELS:
        return CleanupTarget(target_type=target_type, label=MAINTENANCE_TARGET_LABELS[target_type])

    if target_type in {"agent_private_memory", "agent_formal_knowledge", "agent_memory_policy"}:
        agent_id = _safe_token(raw.get("agentId") or raw.get("ownerId"), default="", max_length=128)
        if not agent_id:
            raise MemoryCleanupError(f"{target_type} requires agentId.")
        if target_type == "agent_memory_policy" and not agent_directory_service.get_agent(agent_id, include_archived=True):
            raise MemoryCleanupError(f"Agent not found: {agent_id}")
        label = {
            "agent_private_memory": f"Agent private memory: {agent_id}",
            "agent_formal_knowledge": f"Agent formal knowledge: {agent_id}",
            "agent_memory_policy": f"Agent MemoryPolicy reset: {agent_id}",
        }[target_type]
        return CleanupTarget(target_type=target_type, owner_type="agent", owner_id=agent_id, agent_id=agent_id, label=label)

    if target_type == "team_knowledge":
        team_id = _safe_token(raw.get("teamId") or raw.get("ownerId"), default="", max_length=96)
        if not team_id:
            raise MemoryCleanupError("team_knowledge requires teamId.")
        return CleanupTarget(target_type=target_type, owner_type="team", owner_id=team_id, team_id=team_id, label=f"Team knowledge: {team_id}")

    scoped_id = str(raw.get("scopedKnowledgeBaseId") or raw.get("knowledgeBaseId") or "").strip()
    owner_type = str(raw.get("ownerType") or "").strip().lower()
    owner_id = str(raw.get("ownerId") or raw.get("teamId") or raw.get("agentId") or "").strip()
    knowledge_base_id = str(raw.get("knowledgeBaseId") or "").strip()
    parsed_owner_type, parsed_owner_id, parsed_base_id = team_knowledge_service._parse_owner_scoped_knowledge_base_id(scoped_id)
    owner_type = parsed_owner_type or owner_type
    owner_id = parsed_owner_id or owner_id
    knowledge_base_id = parsed_base_id or knowledge_base_id
    if owner_type and owner_id and knowledge_base_id:
        owner = team_knowledge_service._owner_context(owner_type, owner_id)
        state = team_knowledge_service._load_bases_state_for_owner(owner)
        base = next(
            (item for item in list(state.get("knowledgeBases") or []) if str(item.get("knowledgeBaseId") or "") == knowledge_base_id),
            None,
        )
        if not base:
            raise MemoryCleanupError(f"Knowledge base not found: {owner_type}:{owner_id}:{knowledge_base_id}")
    else:
        owner, base = team_knowledge_service._require_base_with_owner(scoped_id or knowledge_base_id)
        owner_type = str(owner.get("ownerType") or "").strip()
        owner_id = str(owner.get("ownerId") or "").strip()
        knowledge_base_id = str(base.get("knowledgeBaseId") or "").strip()
    if owner_type not in {"agent", "team"} or not owner_id or not knowledge_base_id:
        raise MemoryCleanupError("knowledge_base requires ownerType, ownerId, and knowledgeBaseId.")
    scoped = team_knowledge_service._owner_scoped_knowledge_base_id({"ownerType": owner_type, "ownerId": owner_id}, knowledge_base_id)
    return CleanupTarget(
        target_type="knowledge_base",
        owner_type=owner_type,
        owner_id=owner_id,
        agent_id=owner_id if owner_type == "agent" else "",
        team_id=owner_id if owner_type == "team" else "",
        knowledge_base_id=knowledge_base_id,
        scoped_knowledge_base_id=scoped,
        label=f"Knowledge base: {scoped}",
    )


def _preview_target(target: CleanupTarget) -> dict[str, Any]:
    path_previews = [_path_preview(path) for path in _paths_for_target(target)]
    counts = _counts_for_target(target, path_previews)
    return {
        "targetKey": target.key,
        "targetType": target.target_type,
        "label": target.label,
        "ownerType": target.owner_type,
        "ownerId": target.owner_id,
        "agentId": target.agent_id,
        "teamId": target.team_id,
        "knowledgeBaseId": target.knowledge_base_id,
        "scopedKnowledgeBaseId": target.scoped_knowledge_base_id,
        "status": "preview",
        "paths": path_previews,
        "counts": counts,
        "warnings": _warnings_for_target(target),
    }


def _execute_target(target: CleanupTarget) -> dict[str, Any]:
    before = _preview_target(target)
    results: list[dict[str, Any]] = []
    if target.target_type == "global_runtime_memory":
        for cleanup_path in _paths_for_target(target):
            results.append(_execute_global_path(cleanup_path))
    elif target.target_type == "sqlite_database_compact":
        for cleanup_path in _paths_for_target(target):
            results.append(_execute_compact_path(cleanup_path))
    elif target.target_type == "knowledge_base":
        results.extend(_remove_knowledge_base_records(target))
        results.extend(_delete_vector_records_for_target(target))
    elif target.target_type == "agent_memory_policy":
        results.append(_reset_agent_memory_policy(target.agent_id))
    else:
        for cleanup_path in _paths_for_target(target):
            results.append(_execute_delete_path(cleanup_path))
        if target.target_type in {"agent_formal_knowledge", "team_knowledge"}:
            results.extend(_delete_vector_records_for_target(target))
    counts = _counts_from_execution(before, results)
    return {
        **before,
        "status": "executed",
        "paths": results,
        "counts": counts,
    }


def _paths_for_target(target: CleanupTarget) -> list[CleanupPath]:
    root = _project_root()
    if target.target_type == "global_runtime_memory":
        return [
            CleanupPath(root / "workspace" / "agent_brain.db", "database", "reset", "Clear memory tables only."),
            CleanupPath(root / "workspace" / "memory", "directory", "delete", "Delete runtime memory files."),
            CleanupPath(root / "workspace" / "prompts" / "STATE_MEMORY.md", "file", "reset", "Reset prompt state memory to an empty file."),
        ]
    if target.target_type == "sqlite_database_compact":
        return [
            CleanupPath(root / "workspace" / "agent_brain.db", "database_compact", "compact", "Reclaim SQLite free pages without deleting rows."),
        ]
    if target.target_type == "evaluation_artifacts":
        return [
            CleanupPath(root / "workspace" / "evaluation", "directory", "delete", "Delete evaluation bundles, chat candidates, and review queues."),
        ]
    if target.target_type == "session_artifacts":
        return [
            CleanupPath(root / "workspace" / "sessions", "directory", "delete", "Delete historical session transcripts and artifacts."),
        ]
    if target.target_type == "legacy_log_info":
        return [
            CleanupPath(root / "log_info", "directory", "delete", "Delete legacy conversation/debug payload logs."),
        ]
    if target.target_type == "runtime_scene_logs":
        return [
            CleanupPath(root / "logs" / "runtime_scenes", "directory", "delete", "Delete runtime scene diagnostic bundles."),
        ]
    if target.target_type == "team_archive_artifacts":
        teams_root = root / "workspace" / "teams"
        if not teams_root.exists():
            return []
        return [
            CleanupPath(team_dir / "archives", "directory", "delete", f"Delete archived workflow evidence for team {team_dir.name}.")
            for team_dir in sorted(teams_root.iterdir())
            if team_dir.is_dir() and (team_dir / "archives").exists()
        ]
    if target.target_type == "agent_private_memory":
        return [
            CleanupPath(root / "workspace" / "agents" / target.agent_id / "memory", "directory", "delete", "Delete Agent private memory files.")
        ]
    if target.target_type == "agent_formal_knowledge":
        return [
            CleanupPath(root / "workspace" / "agents" / target.agent_id / "knowledge", "directory", "delete", "Delete Agent-owned formal knowledge.")
        ]
    if target.target_type == "team_knowledge":
        return [
            CleanupPath(root / "workspace" / "teams" / target.team_id / "knowledge", "directory", "delete", "Delete Team-owned formal knowledge.")
        ]
    if target.target_type == "knowledge_base":
        owner = _owner_for_target(target)
        return [
            CleanupPath(team_knowledge_service._knowledge_bases_path_for_owner(owner), "json", "filter", "Remove the selected knowledge base row."),
            CleanupPath(team_knowledge_service._source_artifacts_path_for_owner(owner), "jsonl", "filter", "Remove source artifacts attached to the selected knowledge base."),
            CleanupPath(team_knowledge_service._proposals_path_for_owner(owner), "jsonl", "filter", "Remove refinement proposals for the selected knowledge base."),
            CleanupPath(team_knowledge_service._batches_path_for_owner(owner), "jsonl", "filter", "Remove review batches for the selected knowledge base."),
            CleanupPath(team_knowledge_service._items_path_for_owner(owner), "jsonl", "filter", "Remove formal knowledge items for the selected knowledge base."),
            CleanupPath(team_knowledge_service._rating_suggestions_path_for_owner(owner), "jsonl", "filter", "Remove rating suggestions for the selected knowledge base."),
            CleanupPath(team_knowledge_service._audit_path_for_owner(owner), "jsonl", "filter", "Remove owner audit rows for the selected knowledge base."),
        ]
    return []


def _path_preview(cleanup_path: CleanupPath) -> dict[str, Any]:
    resolved = _assert_allowed_cleanup_path(cleanup_path.path, action=cleanup_path.action)
    stats = _database_compact_stats(resolved) if cleanup_path.kind == "database_compact" else _path_stats(resolved)
    row_count = _database_memory_row_count(resolved) if cleanup_path.kind == "database" else _json_row_count(resolved)
    return {
        "path": _relative_path(resolved),
        "kind": cleanup_path.kind,
        "action": cleanup_path.action,
        "note": cleanup_path.note,
        "exists": resolved.exists(),
        "fileCount": stats["fileCount"],
        "byteCount": stats["byteCount"],
        "rowCount": row_count,
    }


def _counts_for_target(target: CleanupTarget, path_previews: list[dict[str, Any]]) -> dict[str, int]:
    knowledge_counts = _knowledge_counts_for_target(target)
    vector_count = _vector_count_for_target(target)
    return {
        "pathCount": len(path_previews),
        "fileCount": sum(int(item.get("fileCount") or 0) for item in path_previews),
        "byteCount": sum(int(item.get("byteCount") or 0) for item in path_previews),
        "rowCount": sum(int(item.get("rowCount") or 0) for item in path_previews),
        "databaseRowCount": _database_row_count_for_target(target),
        "knowledgeBaseCount": knowledge_counts["knowledgeBaseCount"],
        "knowledgeItemCount": knowledge_counts["knowledgeItemCount"],
        "sourceArtifactCount": knowledge_counts["sourceArtifactCount"],
        "proposalCount": knowledge_counts["proposalCount"],
        "batchCount": knowledge_counts["batchCount"],
        "ratingSuggestionCount": knowledge_counts["ratingSuggestionCount"],
        "vectorRecordCount": vector_count,
        "memoryPolicyResetCount": 1 if target.target_type == "agent_memory_policy" else 0,
    }


def _knowledge_counts_for_target(target: CleanupTarget) -> dict[str, int]:
    empty = {
        "knowledgeBaseCount": 0,
        "knowledgeItemCount": 0,
        "sourceArtifactCount": 0,
        "proposalCount": 0,
        "batchCount": 0,
        "ratingSuggestionCount": 0,
    }
    if target.target_type not in {"knowledge_base", "team_knowledge", "agent_formal_knowledge"}:
        return empty
    owner = _owner_for_target(target)
    base_id = target.knowledge_base_id
    return {
        "knowledgeBaseCount": _count_bases(owner, base_id),
        "knowledgeItemCount": _count_jsonl(owner, team_knowledge_service._items_path_for_owner, _matches_base(base_id)),
        "sourceArtifactCount": _count_jsonl(owner, team_knowledge_service._source_artifacts_path_for_owner, _matches_base(base_id)),
        "proposalCount": _count_jsonl(owner, team_knowledge_service._proposals_path_for_owner, _matches_base(base_id)),
        "batchCount": _count_jsonl(owner, team_knowledge_service._batches_path_for_owner, _matches_base(base_id)),
        "ratingSuggestionCount": _count_jsonl(owner, team_knowledge_service._rating_suggestions_path_for_owner, _matches_base(base_id)),
    }


def _database_row_count_for_target(target: CleanupTarget) -> int:
    if target.target_type != "global_runtime_memory":
        return 0
    return _database_memory_row_count(_project_root() / "workspace" / "agent_brain.db")


def _database_memory_row_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    try:
        with sqlite3.connect(str(path)) as conn:
            existing = {
                str(row[0])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            total = 0
            for table in MEMORY_DB_TABLES:
                if table in existing:
                    total += int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            return total
    except sqlite3.Error:
        return 0


def _remove_knowledge_base_records(target: CleanupTarget) -> list[dict[str, Any]]:
    owner = _owner_for_target(target)
    base_id = target.knowledge_base_id
    removed_item_ids = _knowledge_item_ids_for_base(owner, base_id)
    results = [_remove_knowledge_base_row(owner, base_id)]
    filters: list[tuple[Path, Callable[[dict[str, Any]], bool]]] = [
        (team_knowledge_service._source_artifacts_path_for_owner(owner), _matches_base(base_id)),
        (team_knowledge_service._proposals_path_for_owner(owner), _matches_base(base_id)),
        (team_knowledge_service._batches_path_for_owner(owner), _matches_base(base_id)),
        (team_knowledge_service._items_path_for_owner(owner), _matches_base(base_id)),
        (
            team_knowledge_service._rating_suggestions_path_for_owner(owner),
            lambda row: _row_matches_base(row, base_id) or str(row.get("knowledgeItemId") or "") in removed_item_ids,
        ),
        (
            team_knowledge_service._audit_path_for_owner(owner),
            lambda row: _row_matches_base(row, base_id) or _row_matches_base(row.get("payload") if isinstance(row.get("payload"), dict) else {}, base_id),
        ),
    ]
    for path, predicate in filters:
        results.append(_filter_jsonl_path(path, predicate))
    return results


def _remove_knowledge_base_row(owner: dict[str, Any], knowledge_base_id: str) -> dict[str, Any]:
    path = _assert_allowed_cleanup_path(team_knowledge_service._knowledge_bases_path_for_owner(owner), action="filter")
    payload = _read_json(path)
    bases = [item for item in list(payload.get("knowledgeBases") or []) if isinstance(item, dict)]
    kept = [item for item in bases if str(item.get("knowledgeBaseId") or "") != knowledge_base_id]
    removed = len(bases) - len(kept)
    if removed:
        payload["knowledgeBases"] = kept
        payload["updatedAt"] = team_knowledge_service.utc_now_iso()
        _write_json(path, payload)
    return _execution_result(path, "json", "filter", "deleted" if removed else "skipped", row_count=removed)


def _filter_jsonl_path(path: Path, predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    resolved = _assert_allowed_cleanup_path(path, action="filter")
    rows = team_knowledge_service._read_jsonl(resolved)
    kept = [row for row in rows if not predicate(row)]
    removed = len(rows) - len(kept)
    if removed:
        team_knowledge_service._write_jsonl(resolved, kept)
    return _execution_result(resolved, "jsonl", "filter", "deleted" if removed else "skipped", row_count=removed)


def _execute_global_path(cleanup_path: CleanupPath) -> dict[str, Any]:
    path = _assert_allowed_cleanup_path(cleanup_path.path, action=cleanup_path.action)
    if cleanup_path.kind == "database":
        return _reset_memory_database(path)
    if _relative_path(path) == "workspace/prompts/STATE_MEMORY.md":
        return _reset_state_memory_file(path)
    return _execute_delete_path(cleanup_path)


def _execute_delete_path(cleanup_path: CleanupPath) -> dict[str, Any]:
    path = _assert_allowed_cleanup_path(cleanup_path.path, action=cleanup_path.action)
    if not path.exists():
        return _execution_result(path, cleanup_path.kind, cleanup_path.action, "skipped", message="missing")
    try:
        if path.is_dir():
            stats = _path_stats(path)
            shutil.rmtree(path)
            return _execution_result(path, cleanup_path.kind, cleanup_path.action, "deleted", file_count=stats["fileCount"], byte_count=stats["byteCount"])
        size = path.stat().st_size
        path.unlink()
        return _execution_result(path, cleanup_path.kind, cleanup_path.action, "deleted", file_count=1, byte_count=size)
    except OSError as exc:
        return _execution_result(path, cleanup_path.kind, cleanup_path.action, "failed", message=str(exc))


def _execute_compact_path(cleanup_path: CleanupPath) -> dict[str, Any]:
    path = _assert_allowed_cleanup_path(cleanup_path.path, action=cleanup_path.action)
    if not path.exists():
        return _execution_result(path, cleanup_path.kind, cleanup_path.action, "skipped", message="missing")
    try:
        before_size = path.stat().st_size
        reclaimable = _database_compact_stats(path)["byteCount"]
        if reclaimable <= 0:
            return _execution_result(path, cleanup_path.kind, cleanup_path.action, "skipped", file_count=1, message="no free pages")
        with sqlite3.connect(str(path), timeout=120) as conn:
            conn.execute("PRAGMA busy_timeout=120000")
            conn.execute("VACUUM")
        after_size = path.stat().st_size
    except (OSError, sqlite3.Error) as exc:
        return _execution_result(path, cleanup_path.kind, cleanup_path.action, "failed", message=str(exc))
    freed = max(0, before_size - after_size)
    return _execution_result(
        path,
        cleanup_path.kind,
        cleanup_path.action,
        "deleted" if freed else "skipped",
        file_count=1,
        byte_count=freed,
        message=f"compacted database; estimated reclaimable bytes before compact: {reclaimable}",
    )


def _reset_memory_database(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _execution_result(path, "database", "reset", "skipped", message="missing")
    try:
        with sqlite3.connect(str(path)) as conn:
            existing = {
                str(row[0])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            cleared_rows = 0
            for table in MEMORY_DB_TABLES:
                if table not in existing:
                    continue
                cleared_rows += int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                conn.execute(f"DELETE FROM {table}")
            conn.commit()
    except sqlite3.Error as exc:
        return _execution_result(path, "database", "reset", "failed", message=str(exc))
    return _execution_result(path, "database", "reset", "deleted", row_count=cleared_rows, message="memory tables cleared")


def _reset_state_memory_file(path: Path) -> dict[str, Any]:
    try:
        from core.prompt_manager import get_prompt_manager

        prompt_manager = get_prompt_manager()
        dynamic_root = str(prompt_manager.get_status().get("dynamic_root") or "").strip()
        if dynamic_root and _same_or_child(Path(dynamic_root), path.parent):
            prompt_manager.clear_state_memory(persist=False)
    except Exception:
        pass
    try:
        old_size = path.stat().st_size if path.exists() else 0
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    except OSError as exc:
        return _execution_result(path, "file", "reset", "failed", message=str(exc))
    return _execution_result(path, "file", "reset", "deleted", file_count=1 if old_size else 0, byte_count=old_size)


def _reset_agent_memory_policy(agent_id: str) -> dict[str, Any]:
    try:
        payload = agent_directory_service.reset_agent_instance(
            agent_id,
            clear_runtime_state=False,
            reset_direct_session=False,
            reset_memory_policy=True,
        )
    except agent_directory_service.AgentDirectoryError as exc:
        return {
            "path": f"workspace/agents/{agent_id}/memory-policy",
            "kind": "policy",
            "action": "reset",
            "status": "failed",
            "message": str(exc),
            "fileCount": 0,
            "byteCount": 0,
            "rowCount": 0,
        }
    reset_summary = payload.get("resetSummary") if isinstance(payload.get("resetSummary"), dict) else {}
    reset_memory_policy = bool(reset_summary.get("resetMemoryPolicy") or payload.get("resetMemoryPolicy"))
    agent_payload = payload.get("agent") if isinstance(payload.get("agent"), dict) else {}
    return {
        "path": str(agent_payload.get("workspacePath") or payload.get("workspacePath") or f"workspace/agents/{agent_id}"),
        "kind": "policy",
        "action": "reset",
        "status": "deleted" if reset_memory_policy else "skipped",
        "message": "MemoryPolicy reset to default workspace path.",
        "fileCount": 0,
        "byteCount": 0,
        "rowCount": 1 if reset_memory_policy else 0,
    }


def _delete_vector_records_for_target(target: CleanupTarget) -> list[dict[str, Any]]:
    records_dir = rag_vector_index_service._items_dir()
    if not records_dir.exists():
        return [_execution_result(records_dir, "directory", "filter", "skipped", message="missing")]
    deleted = 0
    failed = 0
    for path in sorted(records_dir.glob("*.json")):
        record = rag_vector_index_service._read_json(path)
        if not isinstance(record, dict) or not _vector_record_matches(record, target):
            continue
        try:
            path.unlink()
            deleted += 1
        except OSError:
            failed += 1
    try:
        rag_vector_index_service._write_index_summary(rag_vector_index_service._load_all_index_records())
    except Exception:
        failed += 1
    status = "failed" if failed else ("deleted" if deleted else "skipped")
    return [
        _execution_result(
            records_dir,
            "vector_index",
            "filter",
            status,
            row_count=deleted,
            message=f"deleted vector records: {deleted}",
        )
    ]


def _vector_count_for_target(target: CleanupTarget) -> int:
    if target.target_type not in {"knowledge_base", "agent_formal_knowledge", "team_knowledge"}:
        return 0
    return sum(1 for record in rag_vector_index_service._load_all_index_records() if _vector_record_matches(record, target))


def _vector_record_matches(record: dict[str, Any], target: CleanupTarget) -> bool:
    if target.owner_type and str(record.get("ownerType") or "").strip() != target.owner_type:
        return False
    if target.owner_id and str(record.get("ownerId") or record.get("teamId") or record.get("agentId") or "").strip() != target.owner_id:
        return False
    if target.knowledge_base_id and str(record.get("knowledgeBaseId") or "").strip() != target.knowledge_base_id:
        return False
    return bool(target.owner_type and target.owner_id)


def _counts_from_execution(before: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, int]:
    counts = dict(before.get("counts") or {})
    counts["pathCount"] = len(results)
    counts["fileCount"] = sum(int(item.get("fileCount") or 0) for item in results)
    counts["byteCount"] = sum(int(item.get("byteCount") or 0) for item in results)
    counts["rowCount"] = sum(int(item.get("rowCount") or 0) for item in results)
    if before.get("targetType") == "agent_memory_policy":
        counts["memoryPolicyResetCount"] = sum(1 for item in results if item.get("status") == "deleted")
    if before.get("targetType") in {"knowledge_base", "agent_formal_knowledge", "team_knowledge"}:
        counts["vectorRecordCount"] = sum(int(item.get("rowCount") or 0) for item in results if item.get("kind") == "vector_index")
    return {key: int(value or 0) for key, value in counts.items()}


def _execution_result(
    path: Path,
    kind: str,
    action: str,
    status: str,
    *,
    file_count: int = 0,
    byte_count: int = 0,
    row_count: int = 0,
    message: str = "",
) -> dict[str, Any]:
    return {
        "path": _relative_path(path),
        "kind": kind,
        "action": action,
        "status": status,
        "exists": path.exists(),
        "fileCount": int(file_count),
        "byteCount": int(byte_count),
        "rowCount": int(row_count),
        "message": message,
    }


def _sum_target_totals(targets: list[dict[str, Any]]) -> dict[str, int]:
    totals = {
        "targetCount": len(targets),
        "pathCount": 0,
        "fileCount": 0,
        "byteCount": 0,
        "rowCount": 0,
        "databaseRowCount": 0,
        "knowledgeBaseCount": 0,
        "knowledgeItemCount": 0,
        "sourceArtifactCount": 0,
        "proposalCount": 0,
        "batchCount": 0,
        "ratingSuggestionCount": 0,
        "vectorRecordCount": 0,
        "memoryPolicyResetCount": 0,
    }
    for target in targets:
        counts = target.get("counts") if isinstance(target.get("counts"), dict) else {}
        for key in totals:
            if key != "targetCount":
                totals[key] += int(counts.get(key) or 0)
    return totals


def _warnings_for_target(target: CleanupTarget) -> list[str]:
    if target.target_type == "knowledge_base":
        return ["Central source files are not deleted by a single knowledge-base cleanup target."]
    if target.target_type == "global_runtime_memory":
        return ["Project governance memory under .docs/project-memory is protected and not included."]
    if target.target_type == "sqlite_database_compact":
        return ["SQLite compact reclaims free pages only; it does not delete memory rows or Git/evolution tables."]
    if target.target_type == "team_archive_artifacts":
        return ["Team archives can include workflow evidence; preview carefully and do not run while a matching team workflow is active."]
    if target.target_type in {"evaluation_artifacts", "session_artifacts", "legacy_log_info", "runtime_scene_logs"}:
        return ["This deletes diagnostic/source-audit evidence, not formal team or Agent knowledge."]
    return []


def _operating_boundary() -> dict[str, bool | str]:
    return {
        "hardDelete": True,
        "noBackup": True,
        "projectMemoryProtected": True,
        "centralSourcesDeletedByKnowledgeBaseTarget": False,
        "agentManagementMemoryPolicyResetMigrated": True,
        "maintenanceArtifactsSupported": True,
        "sqliteCompactSupported": True,
    }


def _owner_for_target(target: CleanupTarget) -> dict[str, Any]:
    owner_type = target.owner_type or ("agent" if target.agent_id else "team")
    owner_id = target.owner_id or target.agent_id or target.team_id
    return team_knowledge_service._owner_context(owner_type, owner_id)


def _count_bases(owner: dict[str, Any], knowledge_base_id: str = "") -> int:
    state = team_knowledge_service._load_bases_state_for_owner(owner)
    bases = [item for item in list(state.get("knowledgeBases") or []) if isinstance(item, dict)]
    if knowledge_base_id:
        return sum(1 for item in bases if str(item.get("knowledgeBaseId") or "") == knowledge_base_id)
    return len(bases)


def _count_jsonl(owner: dict[str, Any], path_factory: Callable[[Any], Path], predicate: Callable[[dict[str, Any]], bool]) -> int:
    return sum(1 for row in team_knowledge_service._read_jsonl(path_factory(owner)) if predicate(row))


def _knowledge_item_ids_for_base(owner: dict[str, Any], knowledge_base_id: str) -> set[str]:
    return {
        str(row.get("knowledgeItemId") or "")
        for row in team_knowledge_service._read_jsonl(team_knowledge_service._items_path_for_owner(owner))
        if str(row.get("knowledgeBaseId") or "") == knowledge_base_id
    }


def _matches_base(knowledge_base_id: str) -> Callable[[dict[str, Any]], bool]:
    if not knowledge_base_id:
        return lambda _row: True
    return lambda row: _row_matches_base(row, knowledge_base_id)


def _row_matches_base(row: Any, knowledge_base_id: str) -> bool:
    if not isinstance(row, dict):
        return False
    return any(
        str(row.get(key) or "") == knowledge_base_id
        for key in ("knowledgeBaseId", "targetKnowledgeBaseId")
    )


def _json_row_count(path: Path) -> int:
    if path.suffix.lower() == ".jsonl":
        return len(team_knowledge_service._read_jsonl(path))
    if path.suffix.lower() != ".json" or not path.exists():
        return 0
    payload = _read_json(path)
    if isinstance(payload.get("knowledgeBases"), list):
        return len(payload["knowledgeBases"])
    return 1 if payload else 0


def _path_stats(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"fileCount": 0, "byteCount": 0}
    if path.is_file():
        try:
            return {"fileCount": 1, "byteCount": int(path.stat().st_size)}
        except OSError:
            return {"fileCount": 1, "byteCount": 0}
    file_count = 0
    byte_count = 0
    for child in path.rglob("*"):
        if not child.is_file():
            continue
        file_count += 1
        try:
            byte_count += int(child.stat().st_size)
        except OSError:
            continue
    return {"fileCount": file_count, "byteCount": byte_count}


def _database_compact_stats(path: Path) -> dict[str, int]:
    if not path.exists() or not path.is_file():
        return {"fileCount": 0, "byteCount": 0}
    try:
        with sqlite3.connect(str(path)) as conn:
            page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
            freelist_count = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
    except sqlite3.Error:
        return {"fileCount": 1, "byteCount": 0}
    return {"fileCount": 1, "byteCount": max(0, page_size * freelist_count)}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _append_cleanup_audit(payload: dict[str, Any]) -> None:
    audit_path = _project_root() / "logs" / "memory_cleanup" / "memory_cleanup_audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "schemaVersion": SCHEMA_VERSION,
        "event": "memory.cleanup.executed",
        "createdAt": team_knowledge_service.utc_now_iso(),
        "hardDelete": True,
        "totals": payload.get("totals") or {},
        "targets": [
            {
                "targetType": target.get("targetType"),
                "ownerType": target.get("ownerType"),
                "ownerId": target.get("ownerId"),
                "agentId": target.get("agentId"),
                "teamId": target.get("teamId"),
                "knowledgeBaseId": target.get("knowledgeBaseId"),
                "scopedKnowledgeBaseId": target.get("scopedKnowledgeBaseId"),
                "status": target.get("status"),
            }
            for target in list(payload.get("targets") or [])
            if isinstance(target, dict)
        ],
    }
    with audit_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def _record_cleanup_event(event_code: str, payload: dict[str, Any], *, outcome: str) -> None:
    try:
        record_runtime_scene_event(
            "memory_cleanup",
            "cleanup",
            event_code,
            message=event_code,
            outcome=outcome,
            fields={
                "targetCount": int((payload.get("totals") or {}).get("targetCount") or 0),
                "fileCount": int((payload.get("totals") or {}).get("fileCount") or 0),
                "rowCount": int((payload.get("totals") or {}).get("rowCount") or 0),
                "hardDelete": True,
            },
            lifecycle=True,
        )
    except Exception:
        return


def _clear_memory_caches() -> None:
    try:
        memory_service._clear_memory_overview_section_cache()
        memory_service._clear_memory_usage_contract_cache()
    except Exception:
        return


def _assert_allowed_cleanup_path(path: Path, *, action: str) -> Path:
    root = _project_root().resolve()
    candidate = path if path.is_absolute() else root / path
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise MemoryCleanupError(f"Cleanup path could not be resolved: {path}") from exc
    allowed_roots = [
        root / "workspace" / "memory",
        root / "workspace" / "prompts" / "STATE_MEMORY.md",
        root / "workspace" / "agent_brain.db",
        root / "workspace" / "agents",
        root / "workspace" / "teams",
        root / "workspace" / "knowledge" / "rag",
        root / "workspace" / "evaluation",
        root / "workspace" / "sessions",
        root / "log_info",
        root / "logs" / "runtime_scenes",
    ]
    if not any(_same_or_child(base.resolve(), resolved) for base in allowed_roots):
        raise MemoryCleanupError(f"Cleanup path is outside the memory cleanup allow-list: {_relative_path(resolved)}")
    if ".docs" in resolved.parts:
        raise MemoryCleanupError("Project governance memory is protected from this cleanup tool.")
    if action == "delete" and resolved in {root / "workspace", root / "workspace" / "agents", root / "workspace" / "teams", root / "workspace" / "knowledge", root / "logs"}:
        raise MemoryCleanupError(f"Refusing broad cleanup path: {_relative_path(resolved)}")
    return resolved


def _same_or_child(base: Path, candidate: Path) -> bool:
    try:
        return candidate == base or candidate.relative_to(base) is not None
    except ValueError:
        return False


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(_project_root().resolve()).as_posix()
    except ValueError:
        return str(path)


def _safe_token(value: Any, *, default: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    text = _SAFE_ID_FRAGMENT.sub("-", text).strip(".-_")
    return (text or default)[:max_length]


def _project_root() -> Path:
    root = Path(PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _sync_roots() -> None:
    root = _project_root()
    for service in (memory_service, team_knowledge_service, agent_directory_service):
        if getattr(service, "PROJECT_ROOT", root) != root:
            setattr(service, "PROJECT_ROOT", root)
