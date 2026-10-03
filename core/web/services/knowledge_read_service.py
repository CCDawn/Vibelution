"""Bounded Agent-facing reads of governed formal knowledge items."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from core.chat.chat_task_types import trim_lines
from core.web.services import team_knowledge_service


DEFAULT_PAGE_CHARS = 2400
MAX_PAGE_CHARS = 4000
MAX_SOURCE_CITATIONS = 12


class KnowledgeReadError(ValueError):
    """Base error for a bounded formal knowledge read."""


class KnowledgeReadNotFoundError(KnowledgeReadError):
    """The requested formal item is not readable in this scope."""


class KnowledgeReadPermissionError(KnowledgeReadError):
    """The current Agent cannot read the requested formal item."""


class KnowledgeReadSourceRelationError(KnowledgeReadError):
    """The requested source artifact is not directly linked to the item."""


def read_knowledge_item(
    *,
    knowledge_base_id: str,
    knowledge_item_id: str,
    agent_id: str,
    offset: int = 0,
    max_chars: int = DEFAULT_PAGE_CHARS,
    source_artifact_id: str = "",
    read_mode: str = "item",
    private_memory_enabled: bool = True,
) -> dict[str, Any]:
    """Return a bounded page of one readable item and citations to its linked sources.

    The knowledge service remains the authority for ACL, active status, and
    financial-evidence eligibility. This adapter never reads a source path.
    """

    base_id = _required_id(knowledge_base_id, "knowledge_base_id")
    item_id = _required_id(knowledge_item_id, "knowledge_item_id")
    actor_id = _required_id(agent_id, "agent_id")
    requested_source_id = _optional_id(source_artifact_id, "source_artifact_id")
    normalized_offset = _integer(offset, field="offset", default=0, minimum=0)
    page_limit = min(
        MAX_PAGE_CHARS,
        max(1, _integer(max_chars, field="max_chars", default=DEFAULT_PAGE_CHARS, minimum=1)),
    )
    mode = str(read_mode or "item").strip().lower()
    if mode not in {"item", "source", "history"}:
        raise KnowledgeReadError("read_mode must be item, source, or history.")
    if mode == "source" and not requested_source_id:
        raise KnowledgeReadSourceRelationError("A linked source_artifact_id is required to read a source body.")
    from core.web.services.team_knowledge import lifecycle

    try:
        if not private_memory_enabled:
            owner, _ = team_knowledge_service._require_base_with_owner(base_id)
            if owner["ownerType"] == "agent":
                raise KnowledgeReadPermissionError("Agent private memory is disabled by MemoryPolicy.")
        if mode == "history":
            history = team_knowledge_service.list_knowledge_item_versions(
                base_id, item_id, agent_id=actor_id, offset=normalized_offset, limit=min(page_limit, 25),
            )
            return {
                **history, "offsetUnit": "versions",
                "readMode": mode, "untrusted": True, "embeddedInstructionsAreData": True,
            }
        item = team_knowledge_service.get_readable_knowledge_item(
            base_id,
            item_id,
            agent_id=actor_id,
        )
        item_base_id = str(item.get("knowledgeBaseId") or "").strip() if isinstance(item, dict) else ""
        if (
            not isinstance(item, dict)
            or str(item.get("knowledgeItemId") or "").strip() != item_id
            or not item_base_id
            or (item_base_id != base_id and base_id.rsplit(":", 1)[-1] != item_base_id)
        ):
            raise KnowledgeReadNotFoundError("Knowledge item not found.")
    except team_knowledge_service.TeamKnowledgePermissionError as exc:
        raise KnowledgeReadPermissionError("Knowledge item is outside the current Agent ACL.") from exc
    except team_knowledge_service.TeamKnowledgeNotFoundError as exc:
        raise KnowledgeReadNotFoundError("Knowledge item not found.") from exc

    linked_source_ids = _unique_ids(item.get("sourceArtifactIds"))
    if requested_source_id and requested_source_id not in linked_source_ids:
        raise KnowledgeReadSourceRelationError("Source artifact is not linked to this knowledge item.")
    try:
        trace = team_knowledge_service.get_knowledge_trace(
            base_id,
            item_id,
            agent_id=actor_id,
        )
    except team_knowledge_service.TeamKnowledgePermissionError as exc:
        raise KnowledgeReadPermissionError("Knowledge item is outside the current Agent ACL.") from exc
    except team_knowledge_service.TeamKnowledgeNotFoundError as exc:
        raise KnowledgeReadNotFoundError("Knowledge item not found.") from exc
    selected_source_ids = (
        [requested_source_id]
        if requested_source_id
        else linked_source_ids[:MAX_SOURCE_CITATIONS]
    )
    owner_type = str(item.get("ownerType") or "").strip()
    owner_id = str(item.get("ownerId") or "").strip()
    scoped_base_id = team_knowledge_service._owner_scoped_knowledge_base_id(
        {"ownerType": owner_type, "ownerId": owner_id},
        item_base_id,
    )
    linked_central_source_ids = set(_unique_ids(item.get("centralSourceIds")))
    trace_nodes = trace.get("nodes") if isinstance(trace, dict) else {}
    source_rows = trace_nodes.get("sourceArtifacts") if isinstance(trace_nodes, dict) else []
    sources_by_id = {
        str(source.get("sourceArtifactId") or "").strip(): source
        for source in list(source_rows or [])
        if isinstance(source, dict) and str(source.get("sourceArtifactId") or "").strip()
    }
    citations = [
        _source_citation(
            source_artifact_id=source_id,
            knowledge_base_id=base_id,
            scoped_knowledge_base_id=scoped_base_id,
            knowledge_item_id=item_id,
            source=sources_by_id.get(source_id, {}),
            allowed_central_source_ids=linked_central_source_ids,
        )
        for source_id in selected_source_ids
    ]

    content = item.get("content") if isinstance(item.get("content"), str) else ""
    source_snapshot = None
    if mode == "source":
        try:
            source_snapshot = team_knowledge_service.read_knowledge_source_snapshot(
                base_id, item_id, requested_source_id, agent_id=actor_id,
            )
        except team_knowledge_service.TeamKnowledgePermissionError as exc:
            raise KnowledgeReadPermissionError("Source is outside the current Agent ACL.") from exc
        except team_knowledge_service.TeamKnowledgeNotFoundError as exc:
            raise KnowledgeReadNotFoundError("Source snapshot not found.") from exc
        except team_knowledge_service.TeamKnowledgeError as exc:
            raise KnowledgeReadError(str(exc)) from exc
        content = source_snapshot["content"]
    start = min(normalized_offset, len(content))
    end = min(len(content), start + page_limit)
    has_more = end < len(content)
    return {
        "knowledgeBaseId": base_id,
        "scopedKnowledgeBaseId": scoped_base_id,
        "knowledgeItemId": item_id,
        "title": trim_lines(str(item.get("title") or ""), max_lines=1).strip()[:240],
        "ownerType": owner_type,
        "ownerId": owner_id,
        "content": content[start:end],
        "contentLength": len(content),
        "offset": start,
        "returnedChars": end - start,
        "hasMore": has_more,
        "nextOffset": end if has_more else None,
        "sourceArtifactIds": selected_source_ids,
        "centralSourceIds": [
            str(citation["centralSourceId"])
            for citation in citations
            if citation.get("centralSourceId")
        ][:MAX_SOURCE_CITATIONS],
        "citations": citations,
        "sourceBodyStatus": "source_body_available" if source_snapshot else "source_body_not_requested",
        **({"readMode": mode, "contentSha256": source_snapshot["contentSha256"]} if source_snapshot else {}),
        **({"contentSha256": lifecycle.content_sha256(item), "revision": int(item.get("revision") or 1),
            "rootKnowledgeItemId": item.get("rootKnowledgeItemId") or item_id} if not source_snapshot else {}),
        "untrusted": True,
        "contentTrust": "untrusted_reference_material",
        "embeddedInstructionsAreData": True,
    }


def _source_citation(
    *,
    source_artifact_id: str,
    knowledge_base_id: str,
    scoped_knowledge_base_id: str,
    knowledge_item_id: str,
    source: dict[str, Any],
    allowed_central_source_ids: set[str],
) -> dict[str, str]:
    source_ref = source.get("sourceRef") if isinstance(source.get("sourceRef"), dict) else {}
    financial = source_ref.get("financialEvidence") if isinstance(source_ref.get("financialEvidence"), dict) else {}
    central_source_id = str(source.get("centralSourceId") or "").strip()
    citation = {
        "knowledgeBaseId": knowledge_base_id,
        "scopedKnowledgeBaseId": scoped_knowledge_base_id,
        "knowledgeItemId": knowledge_item_id,
        "sourceArtifactId": source_artifact_id,
        "sourceType": trim_lines(str(source.get("sourceType") or ""), max_lines=1).strip()[:80],
        "title": trim_lines(str(source.get("title") or ""), max_lines=1).strip()[:180],
        "capturedAt": trim_lines(str(source.get("capturedAt") or ""), max_lines=1).strip()[:64],
        "sourceHash": trim_lines(str(source.get("sourceHash") or ""), max_lines=1).strip()[:128],
        "contentTrust": "untrusted_source_material",
    }
    if central_source_id in allowed_central_source_ids:
        citation["centralSourceId"] = central_source_id
    source_url = _safe_source_url(source_ref.get("url") or financial.get("sourceUrl"))
    if source_url:
        citation["sourceUrl"] = source_url
    page = str(source_ref.get("pageRange") or financial.get("page") or "").strip()
    if page:
        citation["page"] = trim_lines(page, max_lines=1).strip()[:80]
    return citation


def _safe_source_url(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 2048 or any(char.isspace() for char in candidate):
        return ""
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return ""
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return ""
    except ValueError:
        return ""
    return candidate


def _required_id(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result or len(result) > 240:
        raise KnowledgeReadError(f"{field} must be a bounded non-empty identifier.")
    return result


def _optional_id(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if len(result) > 240:
        raise KnowledgeReadError(f"{field} must be bounded.")
    return result


def _integer(value: Any, *, field: str, default: int, minimum: int) -> int:
    if isinstance(value, bool):
        raise KnowledgeReadError(f"{field} must be an integer.")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise KnowledgeReadError(f"{field} must be an integer.") from exc
    if result < minimum:
        raise KnowledgeReadError(f"{field} must be at least {minimum}.")
    return result


def _unique_ids(values: Any) -> list[str]:
    result = []
    seen = set()
    for value in list(values or []):
        normalized = str(value or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
