"""External memory-backed skill library indexing and search."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines
from core.infrastructure import developer_sandbox


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1
MAX_LIMIT = 25
SUPPORTED_QUERY_MODES = {"auto", "keyword", "metadata", "hybrid", "regex", "rg", "grep", "semantic", "rag"}
SUPPORTED_SOURCES = {"all_visible", "managed", "system_index"}
SUPPORTED_SCOPES = {"all_visible", "shared", "team", "agent", "system"}
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.-]+|[\u4e00-\u9fff]")


class SkillLibraryError(ValueError):
    """Raised when a skill library request is invalid."""


def skill_library_root(root: Path | None = None) -> Path:
    """Return the formal external skills library root."""

    if root is not None:
        return Path(root).resolve()
    return developer_sandbox.formal_workspace_path(PROJECT_ROOT, "skills")


def initialize_skill_library(*, root: Path | None = None) -> dict[str, Any]:
    """Create the external skills library directory skeleton."""

    library_root = skill_library_root(root)
    for path in [
        library_root / "managed" / "shared",
        library_root / "managed" / "teams",
        library_root / "managed" / "agents",
        library_root / "system_index" / "sources",
        library_root / "system_index" / "indexes",
        library_root / "indexes",
    ]:
        path.mkdir(parents=True, exist_ok=True)
    _write_jsonl(library_root / "registry.jsonl", _read_jsonl(library_root / "registry.jsonl"))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "root": str(library_root),
        "managedRoot": str(library_root / "managed"),
        "systemIndexRoot": str(library_root / "system_index"),
        "indexesRoot": str(library_root / "indexes"),
        "updatedAt": _utc_now_iso(),
    }


def import_managed_skill(
    source_dir: str | os.PathLike[str],
    *,
    scope_type: str = "shared",
    owner_id: str = "",
    skill_id: str = "",
    root: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Copy one skill into the externally managed skills library."""

    library_root = skill_library_root(root)
    initialize_skill_library(root=library_root)
    source_path = Path(source_dir).expanduser().resolve()
    if not source_path.is_dir():
        raise SkillLibraryError(f"Skill source directory does not exist: {source_path}")
    skill_file = source_path / "SKILL.md"
    if not skill_file.exists():
        raise SkillLibraryError("Managed skill import requires SKILL.md.")
    metadata = _parse_skill_file(skill_file)
    normalized_scope = _normalize_scope(scope_type)
    if normalized_scope == "system":
        raise SkillLibraryError("Managed skills cannot use system scope.")
    normalized_owner = _safe_id(owner_id, default="default") if normalized_scope in {"team", "agent"} else ""
    normalized_skill_id = _safe_id(skill_id or metadata.get("name") or source_path.name, default="skill")
    target_dir = _managed_skill_dir(library_root, normalized_scope, normalized_owner, normalized_skill_id)
    if target_dir.exists():
        if not overwrite:
            raise SkillLibraryError(f"Managed skill already exists: {normalized_skill_id}")
        shutil.rmtree(target_dir)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_path, target_dir)
    manifest = _manifest_for_managed_skill(
        skill_id=normalized_skill_id,
        scope_type=normalized_scope,
        owner_id=normalized_owner,
        metadata=metadata,
        target_dir=target_dir,
    )
    _write_json(target_dir / "manifest.json", manifest)
    _write_json(
        target_dir / "source_ref.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "sourceKind": "local_import",
            "sourcePath": str(source_path),
            "importedAt": _utc_now_iso(),
        },
    )
    rebuild_skill_indexes(root=library_root, include_system_index=False)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "imported",
        "skill": _record_from_managed_skill(target_dir, scope_type=normalized_scope, owner_id=normalized_owner),
        "updatedAt": _utc_now_iso(),
    }


def rebuild_skill_indexes(
    *,
    root: Path | None = None,
    system_roots: list[str | os.PathLike[str]] | None = None,
    include_managed: bool = True,
    include_system_index: bool = True,
) -> dict[str, Any]:
    """Rebuild JSONL indexes from external managed skills and system-indexed skills."""

    library_root = skill_library_root(root)
    initialize_skill_library(root=library_root)
    indexed_at = _utc_now_iso()
    existing_records = _read_jsonl(library_root / "registry.jsonl")
    existing_chunks = _read_jsonl(library_root / "indexes" / "unified_chunks.jsonl")
    existing_metadata_rows = _read_jsonl(library_root / "indexes" / "unified_metadata.jsonl")
    records: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    metadata_rows: list[dict[str, Any]] = []

    if include_managed:
        for skill_dir, scope_type, owner_id in _iter_managed_skill_dirs(library_root):
            record = _record_from_managed_skill(skill_dir, scope_type=scope_type, owner_id=owner_id)
            if not record:
                continue
            record["indexedAt"] = indexed_at
            records.append(record)
            chunks.extend(_chunks_for_record(record, skill_dir / "SKILL.md", indexed_at=indexed_at))
            metadata_rows.append(_metadata_row(record, indexed_at=indexed_at))

    if include_system_index:
        for system_root in _effective_system_roots(system_roots):
            for skill_dir in _iter_skill_dirs(Path(system_root)):
                record = _record_from_system_skill(skill_dir, indexed_at=indexed_at)
                if not record:
                    continue
                records.append(record)
                chunks.extend(_chunks_for_record(record, skill_dir / "SKILL.md", indexed_at=indexed_at))
                metadata_rows.append(_metadata_row(record, indexed_at=indexed_at))
    else:
        records.extend(item for item in existing_records if item.get("sourceKind") == "system_index")
        chunks.extend(item for item in existing_chunks if item.get("sourceKind") == "system_index")
        metadata_rows.extend(item for item in existing_metadata_rows if item.get("sourceKind") == "system_index")

    if not include_managed:
        records.extend(item for item in existing_records if item.get("sourceKind") == "managed")
        chunks.extend(item for item in existing_chunks if item.get("sourceKind") == "managed")
        metadata_rows.extend(item for item in existing_metadata_rows if item.get("sourceKind") == "managed")

    records.sort(key=lambda item: (str(item.get("sourceKind") or ""), str(item.get("scopeType") or ""), str(item.get("skillId") or "")))
    chunks.sort(key=lambda item: (str(item.get("skillId") or ""), int(item.get("chunkIndex") or 0)))
    metadata_rows.sort(key=lambda item: str(item.get("skillId") or ""))
    _write_jsonl(library_root / "registry.jsonl", records)
    _write_jsonl(library_root / "indexes" / "unified_chunks.jsonl", chunks)
    _write_jsonl(library_root / "indexes" / "unified_metadata.jsonl", metadata_rows)
    _write_jsonl(library_root / "indexes" / "unified_keyword.jsonl", chunks)
    _write_jsonl(library_root / "system_index" / "registry.jsonl", [item for item in records if item.get("sourceKind") == "system_index"])
    _write_jsonl(library_root / "system_index" / "indexes" / "chunks.jsonl", [item for item in chunks if item.get("sourceKind") == "system_index"])
    _write_jsonl(library_root / "system_index" / "indexes" / "metadata.jsonl", [item for item in metadata_rows if item.get("sourceKind") == "system_index"])
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "indexed",
        "root": str(library_root),
        "summary": {
            "skillCount": len(records),
            "managedCount": sum(1 for item in records if item.get("sourceKind") == "managed"),
            "systemIndexCount": sum(1 for item in records if item.get("sourceKind") == "system_index"),
            "chunkCount": len(chunks),
        },
        "updatedAt": indexed_at,
    }


def search_skill_library(
    *,
    query: str = "",
    query_mode: str = "auto",
    source: str = "all_visible",
    scope: str = "all_visible",
    actor_agent_id: str = "",
    team_id: str = "",
    tags: list[str] | None = None,
    limit: int = 8,
    root: Path | None = None,
) -> dict[str, Any]:
    """Search the external skills library indexes without falling back to old skill paths."""

    library_root = skill_library_root(root)
    requested_mode = str(query_mode or "auto").strip().lower() or "auto"
    if requested_mode not in SUPPORTED_QUERY_MODES:
        raise SkillLibraryError(f"Unsupported skill query mode: {query_mode}")
    normalized_source = _normalize_source(source)
    normalized_scope = _normalize_search_scope(scope)
    normalized_query = trim_lines(str(query or ""), max_lines=4).strip()
    effective_mode = _effective_query_mode(requested_mode, normalized_query)
    bounded_limit = _clamp_limit(limit)
    normalized_tags = [str(tag or "").strip().lower() for tag in list(tags or []) if str(tag or "").strip()]
    chunks = _read_jsonl(library_root / "indexes" / "unified_chunks.jsonl")
    matched = []
    pattern = _compile_regex(normalized_query) if effective_mode in {"regex", "rg", "grep"} else None
    for chunk in chunks:
        if not _is_chunk_visible(
            chunk,
            source=normalized_source,
            scope=normalized_scope,
            actor_agent_id=actor_agent_id,
            team_id=team_id,
        ):
            continue
        if normalized_tags and not set(normalized_tags).issubset(set(_chunk_tags(chunk))):
            continue
        score, reason = _match_score(chunk, normalized_query, effective_mode, pattern=pattern)
        if score <= 0:
            continue
        next_chunk = dict(chunk)
        next_chunk["score"] = score
        next_chunk["matchReason"] = reason
        matched.append(next_chunk)
    matched.sort(key=lambda item: (float(item.get("score") or 0.0), str(item.get("updatedAt") or "")), reverse=True)
    selected = matched[:bounded_limit]
    results = [_result_from_chunk(item, rank=index + 1) for index, item in enumerate(selected)]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "request": {
            "query": normalized_query,
            "queryLength": len(normalized_query),
            "queryMode": requested_mode,
            "effectiveQueryMode": effective_mode,
            "source": normalized_source,
            "scope": normalized_scope,
            "actorAgentId": str(actor_agent_id or "").strip(),
            "teamId": str(team_id or "").strip(),
            "tags": sorted(set(normalized_tags)),
            "limit": bounded_limit,
        },
        "summary": {
            "resultCount": len(results),
            "candidateChunkCount": len(matched),
            "indexChunkCount": len(chunks),
        },
        "results": results,
        "retrievalPolicy": {
            "backend": "external_skill_jsonl_index",
            "sourceOfTruth": "external_workspace_skills",
            "fallsBackToCodexSkills": False,
            "systemIndexExecutable": False,
            "managedExecutionRequiresManifestAllowlist": True,
        },
        "updatedAt": _utc_now_iso(),
    }


def validate_skill_script_execution(
    skill_id: str,
    script_path: str,
    *,
    actor_agent_id: str = "",
    team_id: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    """Validate whether a managed skill script can be executed from the external library."""

    library_root = skill_library_root(root)
    normalized_skill_id = _safe_id(skill_id, default="")
    if not normalized_skill_id:
        return _execution_result(False, "missing_skill_id")
    records = _read_jsonl(library_root / "registry.jsonl")
    record = next((item for item in records if str(item.get("skillId") or "") == normalized_skill_id), None)
    if not record:
        return _execution_result(False, "skill_not_found")
    if record.get("sourceKind") != "managed":
        return _execution_result(False, "system_index_is_read_only", skill_id=normalized_skill_id)
    if not _is_record_visible(record, source="managed", scope="all_visible", actor_agent_id=actor_agent_id, team_id=team_id):
        return _execution_result(False, "skill_not_visible")
    skill_dir = Path(str(record.get("managedPath") or "")).resolve()
    manifest = _read_json(skill_dir / "manifest.json")
    execution = manifest.get("execution") if isinstance(manifest.get("execution"), dict) else {}
    allowed_scripts = [str(item or "").replace("\\", "/").strip().lstrip("/") for item in list(execution.get("allowedScripts") or [])]
    requested = str(script_path or "").replace("\\", "/").strip().lstrip("/")
    if not bool(execution.get("enabled")):
        return _execution_result(False, "execution_disabled", skill_id=normalized_skill_id)
    if not requested or requested not in allowed_scripts:
        return _execution_result(False, "script_not_in_manifest_allowlist", skill_id=normalized_skill_id)
    target = (skill_dir / requested).resolve()
    try:
        target.relative_to(skill_dir)
    except ValueError:
        return _execution_result(False, "script_path_outside_skill", skill_id=normalized_skill_id)
    if not target.exists() or not target.is_file():
        return _execution_result(False, "script_not_found", skill_id=normalized_skill_id)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "executionAllowed": True,
        "reason": "allowed_by_manifest",
        "skillId": normalized_skill_id,
        "scriptPath": str(target),
        "sourceKind": "managed",
    }


def _manifest_for_managed_skill(
    *,
    skill_id: str,
    scope_type: str,
    owner_id: str,
    metadata: dict[str, Any],
    target_dir: Path,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "skillId": skill_id,
        "name": str(metadata.get("name") or skill_id).strip(),
        "description": str(metadata.get("description") or "").strip(),
        "sourceKind": "managed",
        "scopeType": scope_type,
        "ownerId": owner_id,
        "managedPath": str(target_dir),
        "tags": list(metadata.get("tags") or []),
        "execution": {
            "enabled": False,
            "allowedScripts": [],
            "requiresManifestAllowlist": True,
        },
        "updatedAt": _utc_now_iso(),
    }


def _record_from_managed_skill(skill_dir: Path, *, scope_type: str, owner_id: str) -> dict[str, Any]:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return {}
    manifest = _read_json(skill_dir / "manifest.json")
    metadata = _parse_skill_file(skill_file)
    skill_id = _safe_id(manifest.get("skillId") or metadata.get("name") or skill_dir.name, default="skill")
    execution = manifest.get("execution") if isinstance(manifest.get("execution"), dict) else {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "skillId": skill_id,
        "name": str(manifest.get("name") or metadata.get("name") or skill_id).strip(),
        "description": str(manifest.get("description") or metadata.get("description") or "").strip(),
        "sourceKind": "managed",
        "scopeType": scope_type,
        "ownerId": owner_id,
        "managedPath": str(skill_dir.resolve()),
        "skillFilePath": str(skill_file.resolve()),
        "readOnly": False,
        "executionAllowed": bool(execution.get("enabled")),
        "executionBoundary": "manifest_allowlist",
        "tags": _unique_strings(list(manifest.get("tags") or []) + list(metadata.get("tags") or [])),
        "updatedAt": _path_mtime_iso(skill_file),
    }


def _record_from_system_skill(skill_dir: Path, *, indexed_at: str) -> dict[str, Any]:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return {}
    metadata = _parse_skill_file(skill_file)
    skill_id = _safe_id(metadata.get("name") or skill_dir.name, default="system-skill")
    source_key = hashlib.sha1(str(skill_dir.resolve()).encode("utf-8")).hexdigest()[:12]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "skillId": f"system-{skill_id}-{source_key}",
        "name": str(metadata.get("name") or skill_dir.name).strip(),
        "description": str(metadata.get("description") or "").strip(),
        "sourceKind": "system_index",
        "scopeType": "system",
        "ownerId": "",
        "sourcePath": str(skill_dir.resolve()),
        "skillFilePath": str(skill_file.resolve()),
        "readOnly": True,
        "executionAllowed": False,
        "executionBoundary": "system_native_only",
        "tags": _unique_strings(list(metadata.get("tags") or []) + ["system_index"]),
        "updatedAt": _path_mtime_iso(skill_file) or indexed_at,
        "indexedAt": indexed_at,
    }


def _chunks_for_record(record: dict[str, Any], skill_file: Path, *, indexed_at: str) -> list[dict[str, Any]]:
    text = _read_text(skill_file)
    if not text:
        return []
    parts = _split_chunks(text)
    chunks = []
    for index, chunk_text in enumerate(parts):
        chunk_id = hashlib.sha1(f"{record.get('skillId')}:{index}:{chunk_text}".encode("utf-8")).hexdigest()[:16]
        searchable = "\n".join(
            part
            for part in [
                str(record.get("name") or ""),
                str(record.get("description") or ""),
                " ".join(list(record.get("tags") or [])),
                chunk_text,
            ]
            if part
        )
        chunks.append(
            {
                "schemaVersion": SCHEMA_VERSION,
                "chunkId": f"skill-chunk-{chunk_id}",
                "skillId": str(record.get("skillId") or ""),
                "name": str(record.get("name") or ""),
                "description": str(record.get("description") or ""),
                "sourceKind": str(record.get("sourceKind") or ""),
                "scopeType": str(record.get("scopeType") or ""),
                "ownerId": str(record.get("ownerId") or ""),
                "readOnly": bool(record.get("readOnly")),
                "executionAllowed": bool(record.get("executionAllowed")),
                "executionBoundary": str(record.get("executionBoundary") or ""),
                "skillFilePath": str(record.get("skillFilePath") or ""),
                "managedPath": str(record.get("managedPath") or ""),
                "sourcePath": str(record.get("sourcePath") or ""),
                "tags": list(record.get("tags") or []),
                "chunkIndex": index,
                "text": chunk_text,
                "searchableText": searchable,
                "tokens": _tokens(searchable),
                "updatedAt": str(record.get("updatedAt") or ""),
                "indexedAt": indexed_at,
            }
        )
    return chunks


def _metadata_row(record: dict[str, Any], *, indexed_at: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "skillId": str(record.get("skillId") or ""),
        "name": str(record.get("name") or ""),
        "description": str(record.get("description") or ""),
        "sourceKind": str(record.get("sourceKind") or ""),
        "scopeType": str(record.get("scopeType") or ""),
        "ownerId": str(record.get("ownerId") or ""),
        "readOnly": bool(record.get("readOnly")),
        "executionAllowed": bool(record.get("executionAllowed")),
        "executionBoundary": str(record.get("executionBoundary") or ""),
        "skillFilePath": str(record.get("skillFilePath") or ""),
        "tags": list(record.get("tags") or []),
        "updatedAt": str(record.get("updatedAt") or ""),
        "indexedAt": indexed_at,
    }


def _result_from_chunk(chunk: dict[str, Any], *, rank: int) -> dict[str, Any]:
    source_kind = str(chunk.get("sourceKind") or "").strip()
    return {
        "resultId": str(chunk.get("chunkId") or _result_id(chunk, rank)),
        "resultType": "skill_chunk",
        "skillId": str(chunk.get("skillId") or ""),
        "title": str(chunk.get("name") or ""),
        "description": str(chunk.get("description") or ""),
        "excerpt": _excerpt(str(chunk.get("text") or ""), max_chars=1200),
        "score": float(chunk.get("score") or 0.0),
        "rank": rank,
        "sourceKind": source_kind,
        "scopeType": str(chunk.get("scopeType") or ""),
        "ownerId": str(chunk.get("ownerId") or ""),
        "readOnly": bool(chunk.get("readOnly")),
        "executionAllowed": bool(chunk.get("executionAllowed")) if source_kind == "managed" else False,
        "executionBoundary": str(chunk.get("executionBoundary") or ""),
        "matchReason": str(chunk.get("matchReason") or ""),
        "skillFilePath": str(chunk.get("skillFilePath") or ""),
        "managedPath": str(chunk.get("managedPath") or ""),
        "sourcePath": str(chunk.get("sourcePath") or ""),
        "metadata": {
            "tags": list(chunk.get("tags") or []),
            "chunkIndex": int(chunk.get("chunkIndex") or 0),
            "updatedAt": str(chunk.get("updatedAt") or ""),
            "indexedAt": str(chunk.get("indexedAt") or ""),
        },
    }


def _iter_managed_skill_dirs(root: Path) -> list[tuple[Path, str, str]]:
    items: list[tuple[Path, str, str]] = []
    shared_root = root / "managed" / "shared"
    for child in sorted(shared_root.iterdir() if shared_root.exists() else []):
        if child.is_dir():
            items.append((child, "shared", ""))
    for owner_root, scope in [(root / "managed" / "teams", "team"), (root / "managed" / "agents", "agent")]:
        for owner_dir in sorted(owner_root.iterdir() if owner_root.exists() else []):
            if not owner_dir.is_dir():
                continue
            for child in sorted(owner_dir.iterdir()):
                if child.is_dir():
                    items.append((child, scope, owner_dir.name))
    return items


def _iter_skill_dirs(root: Path) -> list[Path]:
    base = Path(root).expanduser()
    if not base.exists():
        return []
    if (base / "SKILL.md").exists():
        return [base.resolve()]
    result = []
    for child in sorted(base.iterdir()):
        if child.is_dir() and (child / "SKILL.md").exists():
            result.append(child.resolve())
    return result


def _effective_system_roots(system_roots: list[str | os.PathLike[str]] | None) -> list[Path]:
    if system_roots is not None:
        return [Path(item).expanduser().resolve() for item in system_roots if str(item or "").strip()]
    home = Path(os.environ.get("USERPROFILE") or Path.home()).expanduser()
    return [home / ".codex" / "skills" / ".system"]


def _managed_skill_dir(root: Path, scope_type: str, owner_id: str, skill_id: str) -> Path:
    if scope_type == "shared":
        return root / "managed" / "shared" / skill_id
    if scope_type == "team":
        return root / "managed" / "teams" / owner_id / skill_id
    if scope_type == "agent":
        return root / "managed" / "agents" / owner_id / skill_id
    raise SkillLibraryError(f"Unsupported managed skill scope: {scope_type}")


def _parse_skill_file(path: Path) -> dict[str, Any]:
    text = _read_text(path)
    metadata: dict[str, Any] = {"name": "", "description": "", "tags": []}
    if not text.startswith("---"):
        return metadata
    lines = text.splitlines()
    frontmatter = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        frontmatter.append(line)
    for line in frontmatter:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip()
        normalized_value = value.strip().strip("\"'")
        if normalized_key in {"name", "description"}:
            metadata[normalized_key] = normalized_value
        elif normalized_key == "tags":
            metadata["tags"] = [item.strip() for item in normalized_value.strip("[]").split(",") if item.strip()]
    return metadata


def _is_chunk_visible(
    chunk: dict[str, Any],
    *,
    source: str,
    scope: str,
    actor_agent_id: str,
    team_id: str,
) -> bool:
    return _is_record_visible(chunk, source=source, scope=scope, actor_agent_id=actor_agent_id, team_id=team_id)


def _is_record_visible(
    record: dict[str, Any],
    *,
    source: str,
    scope: str,
    actor_agent_id: str,
    team_id: str,
) -> bool:
    source_kind = str(record.get("sourceKind") or "").strip()
    if source != "all_visible" and source_kind != source:
        return False
    scope_type = str(record.get("scopeType") or "").strip()
    if scope != "all_visible" and scope_type != scope:
        return False
    if source_kind == "system_index":
        return True
    owner_id = str(record.get("ownerId") or "").strip()
    if scope_type == "shared":
        return True
    if scope_type == "team":
        return bool(team_id and owner_id == str(team_id).strip())
    if scope_type == "agent":
        return bool(actor_agent_id and owner_id == str(actor_agent_id).strip())
    return False


def _match_score(chunk: dict[str, Any], query: str, mode: str, *, pattern: re.Pattern[str] | None) -> tuple[float, str]:
    text = str(chunk.get("searchableText") or "")
    if mode == "metadata":
        return 0.4, "metadata_listing"
    if mode in {"regex", "rg", "grep"}:
        if pattern is not None and pattern.search(text):
            return 1.0, "regex_match"
        return 0.0, ""
    if not query:
        return 0.4, "metadata_listing"
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return (1.0, "literal_match") if query.lower() in text.lower() else (0.0, "")
    chunk_tokens = set(str(token or "").lower() for token in list(chunk.get("tokens") or []))
    overlap = query_tokens & chunk_tokens
    literal_bonus = 0.4 if query.lower() in text.lower() else 0.0
    score = (len(overlap) / max(1, len(query_tokens))) + literal_bonus
    return (score, "keyword_overlap" if overlap else "literal_match") if score > 0 else (0.0, "")


def _compile_regex(query: str) -> re.Pattern[str]:
    if not query:
        raise SkillLibraryError("Regex skill search requires query.")
    try:
        return re.compile(query, re.IGNORECASE)
    except re.error as exc:
        raise SkillLibraryError(f"Invalid skill regex query: {exc}") from exc


def _effective_query_mode(requested_mode: str, query: str) -> str:
    if requested_mode == "auto":
        return "hybrid" if query else "metadata"
    if requested_mode in {"semantic", "rag"}:
        return "hybrid"
    return requested_mode


def _chunk_tags(chunk: dict[str, Any]) -> list[str]:
    return [str(tag or "").strip().lower() for tag in list(chunk.get("tags") or []) if str(tag or "").strip()]


def _split_chunks(text: str, *, max_chars: int = 1800) -> list[str]:
    normalized = trim_lines(str(text or ""), max_lines=240).strip()
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]
    chunks = []
    current: list[str] = []
    current_len = 0
    for line in normalized.splitlines():
        line_len = len(line) + 1
        if current and current_len + line_len > max_chars:
            chunks.append("\n".join(current).strip())
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def _tokens(text: str) -> list[str]:
    return sorted({match.group(0).lower() for match in _TOKEN_PATTERN.finditer(str(text or "")) if match.group(0).strip()})


def _normalize_source(source: str) -> str:
    normalized = str(source or "all_visible").strip().lower() or "all_visible"
    if normalized not in SUPPORTED_SOURCES:
        raise SkillLibraryError(f"Unsupported skill source: {source}")
    return normalized


def _normalize_search_scope(scope: str) -> str:
    normalized = str(scope or "all_visible").strip().lower() or "all_visible"
    if normalized not in SUPPORTED_SCOPES:
        raise SkillLibraryError(f"Unsupported skill scope: {scope}")
    return normalized


def _normalize_scope(scope: str) -> str:
    normalized = str(scope or "shared").strip().lower() or "shared"
    if normalized not in {"shared", "team", "agent"}:
        raise SkillLibraryError(f"Unsupported managed skill scope: {scope}")
    return normalized


def _clamp_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 8
    return max(1, min(MAX_LIMIT, parsed))


def _safe_id(value: Any, *, default: str) -> str:
    text = str(value or "").strip()
    cleaned = _SAFE_ID_FRAGMENT.sub("-", text).strip(".-_")
    return cleaned or default


def _unique_strings(values: list[Any]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        result.append(item)
        seen.add(item)
    return result


def _execution_result(allowed: bool, reason: str, *, skill_id: str = "") -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "executionAllowed": allowed,
        "reason": reason,
        "skillId": skill_id,
    }


def _result_id(chunk: dict[str, Any], rank: int) -> str:
    digest = hashlib.sha1(f"{chunk.get('skillId')}:{chunk.get('chunkIndex')}:{rank}".encode("utf-8")).hexdigest()[:12]
    return f"skill-result-{digest}"


def _excerpt(text: str, *, max_chars: int) -> str:
    normalized = trim_lines(str(text or ""), max_lines=18).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def _read_text(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not Path(path).exists():
        return []
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _path_mtime_iso(path: Path) -> str:
    try:
        timestamp = Path(path).stat().st_mtime
    except OSError:
        return ""
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
