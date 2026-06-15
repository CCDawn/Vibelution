"""File-backed metadata for optional RAG vector indexing."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from core.chatroom.store import utc_now_iso

from . import team_knowledge_service


SCHEMA_VERSION = 1
INDEX_SCHEMA_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LOCK = threading.RLock()


def list_indexable_knowledge_items(*, agent_id: str = "", internal: bool = False) -> list[dict[str, Any]]:
    """Return reviewed formal knowledge items eligible for vector indexing."""

    _sync_roots()
    items: list[dict[str, Any]] = []
    overview = team_knowledge_service.list_knowledge_overview(agent_id=agent_id, internal=internal)
    for base in list(overview.get("knowledgeBases") or []):
        if not isinstance(base, dict):
            continue
        base_id = str(base.get("scopedKnowledgeBaseId") or base.get("knowledgeBaseId") or "").strip()
        if not base_id:
            continue
        try:
            if internal:
                owner, knowledge_base = team_knowledge_service._require_base_with_owner(base_id)
                raw_items = [
                    item
                    for item in team_knowledge_service._read_jsonl(team_knowledge_service._items_path_for_owner(owner))
                    if str(item.get("knowledgeBaseId") or "") == str(knowledge_base.get("knowledgeBaseId") or "")
                ]
                payload = {
                    "ownerType": owner["ownerType"],
                    "ownerId": owner["ownerId"],
                    "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
                    "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
                    "knowledgeBase": team_knowledge_service._knowledge_base_to_api(knowledge_base, owner),
                    "items": raw_items,
                }
            else:
                payload = team_knowledge_service.list_knowledge_items(base_id, agent_id=agent_id)
        except team_knowledge_service.TeamKnowledgeError:
            continue
        team_id = str(payload.get("teamId") or base.get("teamId") or "").strip()
        knowledge_base = payload.get("knowledgeBase") if isinstance(payload.get("knowledgeBase"), dict) else {}
        for item in list(payload.get("items") or []):
            if not isinstance(item, dict):
                continue
            knowledge_item_id = str(item.get("knowledgeItemId") or "").strip()
            if not knowledge_item_id:
                continue
            source_artifact_ids = [str(value or "").strip() for value in list(item.get("sourceArtifactIds") or []) if str(value or "").strip()]
            central_source_ids = [str(value or "").strip() for value in list(item.get("centralSourceIds") or []) if str(value or "").strip()]
            items.append(
                {
                    "recordId": _owner_scoped_item_record_id(
                        owner_type=str(item.get("ownerType") or base.get("ownerType") or "team").strip(),
                        owner_id=str(item.get("ownerId") or base.get("ownerId") or item.get("teamId") or base.get("teamId") or "").strip(),
                        knowledge_item_id=knowledge_item_id,
                    ),
                    "knowledgeItemId": knowledge_item_id,
                    "knowledgeBaseId": str(item.get("knowledgeBaseId") or base_id).strip(),
                    "knowledgeBaseName": str(knowledge_base.get("name") or base.get("name") or "").strip(),
                    "ownerType": str(item.get("ownerType") or base.get("ownerType") or "team").strip(),
                    "ownerId": str(item.get("ownerId") or base.get("ownerId") or item.get("teamId") or base.get("teamId") or "").strip(),
                    "teamId": str(item.get("teamId") or team_id).strip(),
                    "teamName": str(base.get("teamName") or "").strip(),
                    "agentId": str(item.get("agentId") or base.get("agentId") or "").strip(),
                    "agentName": str(base.get("agentName") or "").strip(),
                    "sourceArtifactIds": source_artifact_ids,
                    "centralSourceIds": central_source_ids,
                    "title": str(item.get("title") or "").strip(),
                    "summary": str(item.get("summary") or "").strip(),
                    "tags": [str(value or "").strip() for value in list(item.get("tags") or []) if str(value or "").strip()],
                    "updatedAt": str(item.get("updatedAt") or item.get("createdAt") or "").strip(),
                    "contentHash": _content_hash(item),
                }
            )
    items.sort(key=lambda item: (str(item.get("teamId") or ""), str(item.get("knowledgeBaseId") or ""), str(item.get("knowledgeItemId") or "")))
    return items


def write_index_record(
    item: dict[str, Any],
    *,
    embedding_provider: str = "",
    embedding_model: str = "",
    status: str = "indexed",
    error_type: str = "",
) -> dict[str, Any]:
    """Persist vector index metadata for one formal knowledge item."""

    normalized_item_id = str(item.get("knowledgeItemId") or "").strip()
    if not normalized_item_id:
        raise ValueError("Vector index records require knowledgeItemId.")
    owner_type = str(item.get("ownerType") or "team").strip()
    owner_id = str(item.get("ownerId") or item.get("teamId") or item.get("agentId") or "").strip()
    record_id = _owner_scoped_item_record_id(
        owner_type=owner_type,
        owner_id=owner_id,
        knowledge_item_id=normalized_item_id,
    )
    now = utc_now_iso()
    record = {
        "schemaVersion": INDEX_SCHEMA_VERSION,
        "recordId": record_id,
        "knowledgeItemId": normalized_item_id,
        "knowledgeBaseId": str(item.get("knowledgeBaseId") or "").strip(),
        "ownerType": owner_type,
        "ownerId": owner_id,
        "teamId": str(item.get("teamId") or "").strip(),
        "agentId": str(item.get("agentId") or "").strip(),
        "sourceArtifactIds": [str(value or "").strip() for value in list(item.get("sourceArtifactIds") or []) if str(value or "").strip()],
        "centralSourceIds": [str(value or "").strip() for value in list(item.get("centralSourceIds") or []) if str(value or "").strip()],
        "contentHash": str(item.get("contentHash") or "").strip(),
        "embeddingProvider": str(embedding_provider or "").strip(),
        "embeddingModel": str(embedding_model or "").strip(),
        "indexedAt": now,
        "status": _normalize_record_status(status),
        "errorType": str(error_type or "").strip(),
        "updatedAt": now,
    }
    with _LOCK:
        _write_json(_item_record_path(record_id), record)
        _write_index_summary(_load_all_index_records())
    return record


def get_vector_index_health(*, agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    """Return vector index readiness without exposing knowledge bodies."""

    indexable_items = list_indexable_knowledge_items(agent_id=agent_id, internal=internal)
    records = {_record_id_for_record(record): record for record in _load_all_index_records()}
    item_rows: list[dict[str, Any]] = []
    indexed_count = 0
    stale_count = 0
    missing_count = 0
    failed_count = 0
    provider = ""
    model = ""
    last_indexed_at = ""

    for item in indexable_items:
        item_id = str(item.get("knowledgeItemId") or "").strip()
        record_id = _record_id_for_item(item)
        record = records.get(record_id)
        status = "missing"
        record_hash = ""
        error_type = ""
        indexed_at = ""
        if record:
            record_hash = str(record.get("contentHash") or "").strip()
            indexed_at = str(record.get("indexedAt") or "").strip()
            error_type = str(record.get("errorType") or "").strip()
            raw_status = _normalize_record_status(record.get("status"))
            if raw_status == "failed":
                status = "failed"
            elif record_hash != str(item.get("contentHash") or "").strip():
                status = "stale"
            else:
                status = "indexed"
            provider = provider or str(record.get("embeddingProvider") or "").strip()
            model = model or str(record.get("embeddingModel") or "").strip()
            last_indexed_at = max(last_indexed_at, indexed_at)
        if status == "indexed":
            indexed_count += 1
        elif status == "stale":
            stale_count += 1
        elif status == "failed":
            failed_count += 1
        else:
            missing_count += 1
        item_rows.append(
            {
                "knowledgeItemId": item_id,
                "recordId": record_id,
                "knowledgeBaseId": str(item.get("knowledgeBaseId") or "").strip(),
                "ownerType": str(item.get("ownerType") or "team").strip(),
                "ownerId": str(item.get("ownerId") or item.get("teamId") or item.get("agentId") or "").strip(),
                "teamId": str(item.get("teamId") or "").strip(),
                "agentId": str(item.get("agentId") or "").strip(),
                "centralSourceIds": [str(value or "").strip() for value in list(item.get("centralSourceIds") or []) if str(value or "").strip()],
                "status": status,
                "contentHash": str(item.get("contentHash") or "").strip(),
                "indexedContentHash": record_hash,
                "indexedAt": indexed_at,
                "errorType": error_type,
            }
        )

    status = "ready"
    if indexed_count <= 0:
        status = "unavailable"
    if stale_count or failed_count:
        status = "degraded"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "provider": "vector",
        "status": status,
        "vectorEnabled": indexed_count > 0 or stale_count > 0 or failed_count > 0,
        "indexedItemCount": indexed_count,
        "staleItemCount": stale_count,
        "missingItemCount": missing_count,
        "failedItemCount": failed_count,
        "indexableItemCount": len(indexable_items),
        "embeddingProvider": provider,
        "embeddingModel": model,
        "lastIndexedAt": last_indexed_at,
        "items": item_rows,
        "updatedAt": utc_now_iso(),
    }


def _content_hash(item: dict[str, Any]) -> str:
    payload = {
        "title": str(item.get("title") or "").strip(),
        "summary": str(item.get("summary") or "").strip(),
        "content": str(item.get("content") or "").strip(),
        "sourceArtifactIds": [str(value or "").strip() for value in list(item.get("sourceArtifactIds") or []) if str(value or "").strip()],
        "centralSourceIds": [str(value or "").strip() for value in list(item.get("centralSourceIds") or []) if str(value or "").strip()],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_record_status(status: Any) -> str:
    normalized = str(status or "indexed").strip().lower()
    return normalized if normalized in {"indexed", "failed"} else "indexed"


def _load_all_index_records() -> list[dict[str, Any]]:
    records = []
    items_dir = _items_dir()
    if not items_dir.exists():
        return []
    for path in sorted(items_dir.glob("*.json")):
        payload = _read_json(path)
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _write_index_summary(records: list[dict[str, Any]]) -> None:
    payload = {
        "schemaVersion": INDEX_SCHEMA_VERSION,
        "updatedAt": utc_now_iso(),
        "recordCount": len(records),
        "records": [
            {
                "knowledgeItemId": str(record.get("knowledgeItemId") or "").strip(),
                "recordId": _record_id_for_record(record),
                "knowledgeBaseId": str(record.get("knowledgeBaseId") or "").strip(),
                "ownerType": str(record.get("ownerType") or "team").strip(),
                "ownerId": str(record.get("ownerId") or record.get("teamId") or record.get("agentId") or "").strip(),
                "teamId": str(record.get("teamId") or "").strip(),
                "agentId": str(record.get("agentId") or "").strip(),
                "centralSourceIds": [str(value or "").strip() for value in list(record.get("centralSourceIds") or []) if str(value or "").strip()],
                "contentHash": str(record.get("contentHash") or "").strip(),
                "status": str(record.get("status") or "").strip(),
                "indexedAt": str(record.get("indexedAt") or "").strip(),
            }
            for record in records
        ],
    }
    _write_json(_index_path(), payload)


def _item_record_path(knowledge_item_id: str) -> Path:
    safe_id = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in knowledge_item_id).strip(".-_") or "item"
    return _items_dir() / f"{safe_id}.json"


def _record_id_for_item(item: dict[str, Any]) -> str:
    return _owner_scoped_item_record_id(
        owner_type=str(item.get("ownerType") or "team").strip(),
        owner_id=str(item.get("ownerId") or item.get("teamId") or item.get("agentId") or "").strip(),
        knowledge_item_id=str(item.get("knowledgeItemId") or "").strip(),
    )


def _record_id_for_record(record: dict[str, Any]) -> str:
    existing = str(record.get("recordId") or "").strip()
    if existing:
        return existing
    return _owner_scoped_item_record_id(
        owner_type=str(record.get("ownerType") or "team").strip(),
        owner_id=str(record.get("ownerId") or record.get("teamId") or record.get("agentId") or "").strip(),
        knowledge_item_id=str(record.get("knowledgeItemId") or "").strip(),
    )


def _owner_scoped_item_record_id(*, owner_type: str, owner_id: str, knowledge_item_id: str) -> str:
    safe_owner_type = _safe_record_fragment(owner_type or "team")
    safe_owner_id = _safe_record_fragment(owner_id)
    safe_item_id = _safe_record_fragment(knowledge_item_id)
    if safe_owner_type and safe_owner_id and safe_item_id:
        return f"{safe_owner_type}:{safe_owner_id}:{safe_item_id}"
    return safe_item_id


def _safe_record_fragment(value: Any) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in str(value or "").strip()).strip(".-_")


def _index_path() -> Path:
    return _index_root() / "index.json"


def _items_dir() -> Path:
    return _index_root() / "items"


def _index_root() -> Path:
    from core.infrastructure import developer_sandbox

    return developer_sandbox.route_workspace_path(
        _project_root(),
        "rag",
        "knowledge",
        "rag",
        intent="state",
        seed=True,
    )


def _project_root() -> Path:
    root = Path(team_knowledge_service.PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _sync_roots() -> None:
    return None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)
