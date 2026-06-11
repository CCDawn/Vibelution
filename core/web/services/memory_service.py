"""Agent memory overview and user management service."""

from __future__ import annotations

import copy
import json
import re
import sqlite3
import subprocess
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONTENT_LIMIT = 8000
LIST_LIMIT = 20
MEMORY_CHANNELS = {"conversation", "research", "self_evolution", "supervised_evolution", "explicit_read"}
MEMORY_CHANNEL_ORDER = ["conversation", "research", "self_evolution", "supervised_evolution", "explicit_read"]
VISIBILITY_CLASSES = {"prompt", "agent_visible", "manual", "diagnostic", "missing"}
USER_MANAGED_SECTION_ID = "user-managed-memory"
USER_MANAGED_SOURCE_KIND = "user_managed_memory"
USER_MANAGED_MEMORY_FILENAME = "user_memory_overrides.json"
MANAGED_AUDIT_LIMIT = 200
MANAGED_MEMORY_WRITE_LOCK = Lock()
MEMORY_OVERVIEW_PERF_STATE_LOCK = Lock()
MEMORY_OVERVIEW_WAS_SLOW = False
MEMORY_OVERVIEW_SLOW_MS = 500.0
MEMORY_OVERVIEW_SUBTIMING_LIMIT = 12
MEMORY_OVERVIEW_SECTION_CACHE_TTL_SECONDS = 3.0
MEMORY_OVERVIEW_SECTION_CACHE_LOCK = Lock()
MEMORY_OVERVIEW_SECTION_CACHE: dict[str, Any] = {
    "root": "",
    "sections": {},
}
MEMORY_OVERVIEW_PREWARM_LOCK = Lock()
MEMORY_OVERVIEW_PREWARM_INFLIGHT = False
MEMORY_USAGE_CONTRACT_CACHE_TTL_SECONDS = 8.0
MEMORY_USAGE_CONTRACT_CACHE_LOCK = Lock()
MEMORY_USAGE_CONTRACT_CACHE: dict[str, Any] = {"root": "", "expiresAt": 0.0, "payload": None}
MEMORY_USAGE_CONTRACT_SLOW_MS = 250.0
GIT_SNAPSHOT_CACHE_TTL_SECONDS = 3.0
GIT_SNAPSHOT_CACHE_LOCK = Lock()
GIT_SNAPSHOT_CACHE: dict[str, Any] = {"root": "", "expiresAt": 0.0, "payload": None}
SQLITE_APPEND_ONLY_TABLES = {"GitFileChange", "GitEntityChange"}


def _path_signature(path: Path) -> str:
    try:
        stat = Path(path).stat()
    except OSError:
        return "missing"
    return f"{int(stat.st_mtime_ns)}:{int(stat.st_size)}"


def _dir_signature(path: Path) -> str:
    root = Path(path)
    if not root.exists():
        return "missing"
    try:
        entries = []
        for item in root.iterdir():
            try:
                stat = item.stat()
            except OSError:
                continue
            entries.append(f"{item.name}:{int(stat.st_mtime_ns)}:{int(stat.st_size)}")
        return "|".join(sorted(entries))
    except OSError:
        return "unavailable"


def _memory_overview_section_signature(root: Path, section_id: str) -> str | None:
    normalized = str(section_id or "").strip()
    if normalized == "project-memory":
        memory_dir = root / ".docs" / "project-memory"
        lanes_dir = memory_dir / "lanes"
        return "|".join(
            [
                _path_signature(memory_dir / "memory.json"),
                _path_signature(memory_dir / "INDEX.md"),
                _dir_signature(lanes_dir),
            ]
        )
    if normalized == "runtime-memory":
        return _path_signature(root / "workspace" / "runtime_state.json")
    if normalized == "prompt-memory":
        return _dir_signature(root / "workspace" / "prompts")
    if normalized in {"workspace-database", "git-memory", "self-evolution-memory"}:
        return _path_signature(root / "workspace" / "agent_brain.db")
    if normalized == "research-memory":
        return _dir_signature(root / "workspace" / "research")
    if normalized == "team-knowledge":
        return _dir_signature(root / "workspace" / "teams")
    if normalized == "chat-session-memory":
        return "|".join(
            [
                _path_signature(root / "workspace" / "chat" / "chat_state.json"),
                _dir_signature(root / "workspace" / "sessions"),
            ]
        )
    if normalized == "supervised-evolution-memory":
        return _dir_signature(root / "workspace" / "supervised_evolution")
    if normalized == "runtime-scene-evidence":
        return _dir_signature(root / "logs" / "runtime_scenes")
    return None


def get_memory_overview(*, include_content: bool = True) -> dict[str, Any]:
    """Return a snapshot of every known agent-memory source plus user management state."""

    started_at = time.perf_counter()
    root = PROJECT_ROOT.resolve()
    warnings: list[str] = []
    phase_timings: list[dict[str, Any]] = []
    phase_started_at = time.perf_counter()
    managed_memory = _load_managed_memory(root, warnings=warnings)
    _append_memory_overview_phase_timing(phase_timings, "managed_memory.load", phase_started_at)
    phase_started_at = time.perf_counter()
    base_sections, section_timings = _timed_base_memory_sections(root, warnings)
    _append_memory_overview_phase_timing(phase_timings, "base_sections.load_or_cache", phase_started_at, count=len(base_sections))
    phase_started_at = time.perf_counter()
    sections = _apply_managed_memory(root, base_sections, managed_memory)
    _append_memory_overview_phase_timing(phase_timings, "managed_memory.apply", phase_started_at, count=len(sections))
    item_count = sum(len(section["items"]) for section in sections)
    agent_visible_count = sum(
        1 for section in sections for item in section["items"] if bool(item.get("agentVisible"))
    )
    runtime_injected_count = sum(
        1 for section in sections for item in section["items"] if bool(item.get("inPrompt"))
    )
    overview = {
        "schemaVersion": 3,
        "generatedAt": _now_iso(),
        "projectRoot": str(root),
        "summary": {
            "sectionCount": len(sections),
            "itemCount": item_count,
            "agentVisibleCount": agent_visible_count,
            "runtimeInjectedCount": runtime_injected_count,
            "warnings": warnings,
        },
        "sections": sections,
    }
    if not include_content:
        phase_started_at = time.perf_counter()
        overview["sections"] = _defer_memory_overview_content(sections)
        _append_memory_overview_phase_timing(phase_timings, "content.defer", phase_started_at, count=len(sections))
    _record_memory_overview_perf_event(
        root,
        overview,
        duration_ms=(time.perf_counter() - started_at) * 1000,
        section_timings=section_timings,
        phase_timings=phase_timings,
    )
    return overview


def prewarm_memory_overview_cache(*, reason: str = "startup") -> dict[str, Any]:
    """Build the memory overview caches before the first Memory page request."""

    global MEMORY_OVERVIEW_PREWARM_INFLIGHT
    normalized_reason = _clip(str(reason or "startup"), 120) or "startup"
    started_at = time.perf_counter()
    with MEMORY_OVERVIEW_PREWARM_LOCK:
        if MEMORY_OVERVIEW_PREWARM_INFLIGHT:
            return {
                "status": "skipped",
                "reason": normalized_reason,
                "skipReason": "inflight",
                "durationMs": round((time.perf_counter() - started_at) * 1000, 1),
            }
        MEMORY_OVERVIEW_PREWARM_INFLIGHT = True

    try:
        overview = get_memory_overview(include_content=False)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
        summary = overview.get("summary") if isinstance(overview.get("summary"), dict) else {}
        section_count = len(overview.get("sections") or [])
        item_count = int((summary or {}).get("itemCount") or 0)
        result = {
            "status": "completed",
            "reason": normalized_reason,
            "durationMs": duration_ms,
            "sectionCount": section_count,
            "itemCount": item_count,
        }
        _record_memory_overview_prewarm_event(
            status="completed",
            reason=normalized_reason,
            elapsed_ms=duration_ms,
            section_count=section_count,
            item_count=item_count,
        )
        return result
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
        _record_memory_overview_prewarm_event(
            status="failed",
            reason=normalized_reason,
            elapsed_ms=duration_ms,
            error_type=type(exc).__name__,
            error_message=_clip(str(exc), 240),
        )
        return {
            "status": "failed",
            "reason": normalized_reason,
            "durationMs": duration_ms,
            "errorType": type(exc).__name__,
        }
    finally:
        with MEMORY_OVERVIEW_PREWARM_LOCK:
            MEMORY_OVERVIEW_PREWARM_INFLIGHT = False


def get_memory_item_detail(section_id: str, item_id: str) -> dict[str, Any] | None:
    """Return one memory item with full content and current user-management overlay."""

    root = PROJECT_ROOT.resolve()
    section_id = str(section_id or "").strip()
    item_id = str(item_id or "").strip()
    warnings: list[str] = []
    managed_memory = _load_managed_memory(root, warnings=warnings)
    if section_id == USER_MANAGED_SECTION_ID:
        sections = [_user_managed_memory_section(root, managed_memory)]
    else:
        base_section = _load_base_memory_section(root, section_id, warnings)
        if base_section is None:
            return None
        sections = _apply_managed_memory(root, [base_section], managed_memory)
    for section in sections:
        if str(section.get("id") or "") != section_id:
            continue
        for item in section.get("items") or []:
            if isinstance(item, dict) and str(item.get("id") or "") == item_id:
                return {
                    "schemaVersion": 1,
                    "generatedAt": _now_iso(),
                    "projectRoot": str(root),
                    "section": {key: value for key, value in section.items() if key != "items"},
                    "item": dict(item),
                    "warnings": warnings,
                }
    return None


def get_memory_usage_contract() -> dict[str, Any]:
    """Return the cross-system contract for using Agent and Team memory."""

    started_at = time.perf_counter()
    root = PROJECT_ROOT.resolve()
    cache_root = str(root)
    now = time.monotonic()
    with MEMORY_USAGE_CONTRACT_CACHE_LOCK:
        cached_payload = MEMORY_USAGE_CONTRACT_CACHE.get("payload")
        if (
            MEMORY_USAGE_CONTRACT_CACHE.get("root") == cache_root
            and cached_payload is not None
            and float(MEMORY_USAGE_CONTRACT_CACHE.get("expiresAt") or 0.0) > now
        ):
            contract = copy.deepcopy(cached_payload)
            _record_memory_contract_viewed_event(contract, cache_hit=True, duration_ms=(time.perf_counter() - started_at) * 1000)
            return contract

    try:
        from core.web.services.team_knowledge_service import (
            get_knowledge_governance_plan,
            get_knowledge_operations_health,
            list_knowledge_overview,
        )

        knowledge_overview = list_knowledge_overview(internal=True)
        operations_health = get_knowledge_operations_health(internal=True)
        governance_plan = get_knowledge_governance_plan(limit=8, internal=True)
    except Exception:
        knowledge_overview = {"summary": {}}
        operations_health = {"summary": {}}
        governance_plan = {"summary": {}, "operatingBoundary": {}}
    contract = {
        "schemaVersion": 1,
        "generatedAt": _now_iso(),
        "projectRoot": str(root),
        "principles": [
            "Agent private memory stays agent-scoped and is not mixed into Team knowledge files.",
            "Agent formal knowledge is Agent-owned, permissioned, source-backed, and RAG-readable by explicit owner scope.",
            "Team knowledge is Team-scoped, permissioned, source-backed, and tool-readable by default.",
            "Evidence is not knowledge; proposals are not formal knowledge; formal knowledge requires reviewer confirmation.",
            "Evolution systems may register runtime evidence and proposals, but must not directly apply formal knowledge.",
            "Formal knowledge bodies are not injected into prompts by default; Agents use explicit query tools.",
        ],
        "domains": [
            {
                "domainId": "agent_private_memory",
                "label": "Agent private memory",
                "owner": "Agent",
                "storage": "workspace/agents/{agentId}/memory",
                "readsThrough": ["MemoryPolicy", "Agent runtime context", "/api/memory/overview"],
                "writesThrough": ["Agent-private memory tools", "manual memory management"],
                "canRegisterSource": False,
                "canCreateFormalKnowledge": False,
                "promptDefault": "agent_runtime_dependent",
                "boundary": "Private identity, working notes, and agent-local continuity do not become Team knowledge automatically.",
            },
            {
                "domainId": "agent_formal_knowledge",
                "label": "Agent formal knowledge base",
                "owner": "Agent",
                "storage": "workspace/agents/{agentId}/knowledge",
                "readsThrough": ["knowledge_rag_retrieve_tool", "/api/knowledge/search", "/api/knowledge/rag/retrieve"],
                "writesThrough": ["SourceArtifact", "RefinementProposal", "owner review/apply", "rating suggestion review"],
                "canRegisterSource": True,
                "canCreateFormalKnowledge": True,
                "promptDefault": "not_in_prompt",
                "boundary": "Agent-owned formal knowledge is private to the owning Agent by default; other Agents require explicit grants or future owner-aware policy.",
            },
            {
                "domainId": "team_knowledge",
                "label": "Team knowledge base",
                "owner": "Team",
                "storage": "workspace/teams/{teamId}/knowledge",
                "readsThrough": ["knowledge_query_tool", "/api/knowledge/search", "/api/knowledge/overview"],
                "writesThrough": ["SourceArtifact", "RefinementProposal", "review/apply", "rating suggestion review"],
                "canRegisterSource": True,
                "canCreateFormalKnowledge": True,
                "promptDefault": "not_in_prompt",
                "boundary": "Team member may read/propose; review roles apply or rate. Cross-Team access requires explicit ACL or policy.",
            },
            {
                "domainId": "team_chat",
                "label": "Team chat refinement",
                "owner": "Team chat room",
                "storage": "chat room history + SourceArtifact",
                "readsThrough": ["team_chat_refinement sourceRef", "traceability view"],
                "writesThrough": ["source registration", "refinement proposal"],
                "canRegisterSource": True,
                "canCreateFormalKnowledge": False,
                "promptDefault": "conversation_context_only",
                "boundary": "Group chat can become evidence and proposal material, but cannot become formal knowledge without review.",
            },
            {
                "domainId": "self_evolution",
                "label": "Self evolution evidence",
                "owner": "Self evolution runtime",
                "storage": "workspace/evolution + logs/runtime_scenes",
                "readsThrough": ["memory overview", "runtime scene logs", "knowledge proposal tools"],
                "writesThrough": ["runtime_evidence_refinement SourceArtifact", "RefinementProposal"],
                "canRegisterSource": True,
                "canCreateFormalKnowledge": False,
                "promptDefault": "bounded_runtime_context",
                "boundary": "Self evolution may record validated lessons as evidence/proposals; reviewer confirmation gates formal knowledge.",
            },
            {
                "domainId": "supervised_evolution",
                "label": "Supervised evolution evidence",
                "owner": "Supervised evolution workbench",
                "storage": "workspace/supervised_evolution + logs/runtime_scenes",
                "readsThrough": ["evaluation bundles", "decision records", "runtime scene logs"],
                "writesThrough": ["runtime_evidence_refinement SourceArtifact", "RefinementProposal"],
                "canRegisterSource": True,
                "canCreateFormalKnowledge": False,
                "promptDefault": "bounded_evaluation_context",
                "boundary": "Case traces and decisions are evidence; they do not mutate Team KB without a proposal review.",
            },
            {
                "domainId": "external_artifacts",
                "label": "External search and PDF",
                "owner": "Research/parser pipeline",
                "storage": "SourceArtifact + RefinementProposal",
                "readsThrough": ["pdf_refinement", "external_search_refinement"],
                "writesThrough": ["ingestion package", "proposal tool"],
                "canRegisterSource": True,
                "canCreateFormalKnowledge": False,
                "promptDefault": "not_in_prompt",
                "boundary": "Parsers and searchers produce source-backed proposals only; they do not write formal knowledge directly.",
            },
        ],
        "flow": [
            {"stepId": "source", "label": "Register source", "creates": ["SourceArtifact"], "requiresReviewer": False},
            {"stepId": "proposal", "label": "Refine proposal", "creates": ["RefinementProposal"], "requiresReviewer": False},
            {"stepId": "review", "label": "Review/apply", "creates": ["KnowledgeBatch", "KnowledgeItem"], "requiresReviewer": True},
            {"stepId": "rating", "label": "Suggest/review rating", "creates": ["RatingSuggestion", "KnowledgeItem metadata"], "requiresReviewer": True},
            {"stepId": "query", "label": "Explicit query", "creates": [], "requiresReviewer": False},
        ],
        "forbiddenActions": [
            "Evolution runtime directly creates KnowledgeItem.",
            "Parser/search pipeline directly creates KnowledgeItem.",
            "Team chat transcript directly becomes formal knowledge.",
            "Team knowledge body is injected into prompts by default.",
            "Agent private memory is silently promoted into Team knowledge.",
            "Cross-Team read/write occurs without ACL, Team role, or MemoryPolicy permission.",
        ],
        "runtimeAccess": {
            "summaryInPromptAllowed": True,
            "knowledgeBodiesInPromptByDefault": False,
            "explicitReadChannels": ["research", "explicit_read"],
            "agentToolBoundary": {
                "query": "knowledge_query_tool",
                "proposal": "knowledge_proposal_tool or knowledge_ingestion_tool",
                "health": "knowledge_operations_health_tool",
                "plan": "knowledge_governance_plan_tool",
                "ratingSuggestion": "knowledge_rating_suggestion_tool",
            },
        },
        "currentState": {
            "knowledge": knowledge_overview.get("summary") or {},
            "operationsHealth": operations_health.get("summary") or {},
            "governancePlan": governance_plan.get("summary") or {},
            "operatingBoundary": governance_plan.get("operatingBoundary") or {},
        },
    }
    with MEMORY_USAGE_CONTRACT_CACHE_LOCK:
        MEMORY_USAGE_CONTRACT_CACHE.update(
            {
                "root": cache_root,
                "expiresAt": time.monotonic() + MEMORY_USAGE_CONTRACT_CACHE_TTL_SECONDS,
                "payload": copy.deepcopy(contract),
            }
        )
    _record_memory_contract_viewed_event(contract, cache_hit=False, duration_ms=(time.perf_counter() - started_at) * 1000)
    return contract


def create_user_memory_item(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a user-authored memory item in the management layer."""

    root = PROJECT_ROOT.resolve()
    now = _now_iso()
    title = _normalize_managed_text(payload.get("title"), max_length=160)
    summary = _normalize_managed_text(payload.get("summary"), max_length=1000)
    content = _normalize_managed_text(payload.get("content"), max_length=20000)
    if not title:
        raise ValueError("title is required")
    item = {
        "id": f"user-{uuid.uuid4().hex[:12]}",
        "title": title,
        "summary": summary or _clip(content, 360) or title,
        "content": content,
        "channels": ["explicit_read"],
        "agentVisible": True,
        "inPrompt": False,
        "createdAt": now,
        "updatedAt": now,
    }
    with MANAGED_MEMORY_WRITE_LOCK:
        managed_memory = _load_managed_memory(root)
        managed_memory["items"].insert(0, item)
        _append_managed_audit(managed_memory, "create", USER_MANAGED_SECTION_ID, item["id"], item)
        _save_managed_memory(root, managed_memory)
    _clear_memory_usage_contract_cache()
    response_item = _user_managed_item(root, item)
    _record_memory_management_event("create", USER_MANAGED_SECTION_ID, item["id"], response_item)
    return {
        "ok": True,
        "action": "create",
        "sectionId": USER_MANAGED_SECTION_ID,
        "itemId": item["id"],
        "item": response_item,
    }


def update_memory_item(section_id: str, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Update a user memory item, or add an override for a system-source item."""

    root = PROJECT_ROOT.resolve()
    section_id = str(section_id or "").strip()
    item_id = str(item_id or "").strip()
    patch = _managed_patch_from_payload(payload, require_any=True)
    now = _now_iso()
    with MANAGED_MEMORY_WRITE_LOCK:
        managed_memory = _load_managed_memory(root)
        if section_id == USER_MANAGED_SECTION_ID:
            item = _find_user_managed_item(managed_memory, item_id)
            if item is None:
                raise FileNotFoundError("User memory item not found")
            item.update(patch)
            item["updatedAt"] = now
            _append_managed_audit(managed_memory, "update", section_id, item_id, item)
            _save_managed_memory(root, managed_memory)
            updated_item = _user_managed_item(root, item)
        else:
            base_item = _find_base_memory_item(root, section_id, item_id)
            if base_item is None:
                raise FileNotFoundError("Memory item not found")
            key = _managed_override_key(section_id, item_id)
            overrides = managed_memory.setdefault("overrides", {})
            current = dict(overrides.get(key) or {})
            current.update(patch)
            current["updatedAt"] = now
            current["sectionId"] = section_id
            current["itemId"] = item_id
            overrides[key] = current
            _append_managed_audit(managed_memory, "override", section_id, item_id, {**base_item, **patch})
            _save_managed_memory(root, managed_memory)
            updated_item = _apply_item_override(dict(base_item), current)
    _clear_memory_usage_contract_cache()
    _record_memory_management_event("update", section_id, item_id, updated_item)
    return {
        "ok": True,
        "action": "update",
        "sectionId": section_id,
        "itemId": item_id,
        "item": updated_item,
    }


def delete_memory_item(section_id: str, item_id: str) -> dict[str, Any]:
    """Delete a user item, or disable a system item through a reversible override."""

    root = PROJECT_ROOT.resolve()
    section_id = str(section_id or "").strip()
    item_id = str(item_id or "").strip()
    now = _now_iso()
    with MANAGED_MEMORY_WRITE_LOCK:
        managed_memory = _load_managed_memory(root)
        if section_id == USER_MANAGED_SECTION_ID:
            items = managed_memory.setdefault("items", [])
            index = next((idx for idx, item in enumerate(items) if str(item.get("id") or "") == item_id), -1)
            if index < 0:
                raise FileNotFoundError("User memory item not found")
            removed = items.pop(index)
            _append_managed_audit(managed_memory, "delete", section_id, item_id, removed)
            _save_managed_memory(root, managed_memory)
            action = "delete"
            item_payload = _user_managed_item(root, removed)
        else:
            base_item = _find_base_memory_item(root, section_id, item_id)
            if base_item is None:
                raise FileNotFoundError("Memory item not found")
            key = _managed_override_key(section_id, item_id)
            overrides = managed_memory.setdefault("overrides", {})
            current = dict(overrides.get(key) or {})
            current.update({"disabled": True, "updatedAt": now, "sectionId": section_id, "itemId": item_id})
            overrides[key] = current
            _append_managed_audit(managed_memory, "disable", section_id, item_id, base_item)
            _save_managed_memory(root, managed_memory)
            action = "disable"
            item_payload = _apply_item_override(dict(base_item), current)
    _clear_memory_usage_contract_cache()
    _record_memory_management_event(action, section_id, item_id, item_payload)
    return {
        "ok": True,
        "action": action,
        "sectionId": section_id,
        "itemId": item_id,
        "item": item_payload,
    }


def restore_memory_item(section_id: str, item_id: str) -> dict[str, Any]:
    """Restore a system item by removing its user override."""

    root = PROJECT_ROOT.resolve()
    section_id = str(section_id or "").strip()
    item_id = str(item_id or "").strip()
    if section_id == USER_MANAGED_SECTION_ID:
        raise ValueError("User-created memory items cannot be restored after deletion")
    with MANAGED_MEMORY_WRITE_LOCK:
        managed_memory = _load_managed_memory(root)
        key = _managed_override_key(section_id, item_id)
        overrides = managed_memory.setdefault("overrides", {})
        if key not in overrides:
            raise FileNotFoundError("Memory override not found")
        base_item = _find_base_memory_item(root, section_id, item_id)
        if base_item is None:
            raise FileNotFoundError("Memory item not found")
        removed = overrides.pop(key)
        _append_managed_audit(managed_memory, "restore", section_id, item_id, {**base_item, **removed})
        _save_managed_memory(root, managed_memory)
    _clear_memory_usage_contract_cache()
    _record_memory_management_event("restore", section_id, item_id, base_item)
    return {
        "ok": True,
        "action": "restore",
        "sectionId": section_id,
        "itemId": item_id,
        "item": _with_default_managed_state(base_item),
    }


def _base_memory_sections(root: Path, warnings: list[str]) -> list[dict[str, Any]]:
    sections, _timings = _timed_base_memory_sections(root, warnings)
    return sections


def _timed_base_memory_sections(root: Path, warnings: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cache_root = str(root.resolve())
    now = time.monotonic()
    sections: list[dict[str, Any]] = []
    timings: list[dict[str, Any]] = []
    for fallback_section_id, load_section in _base_memory_section_specs(root, warnings):
        cached = None
        signature = _memory_overview_section_signature(root, fallback_section_id)
        with MEMORY_OVERVIEW_SECTION_CACHE_LOCK:
            if MEMORY_OVERVIEW_SECTION_CACHE.get("root") == cache_root:
                cache_sections = MEMORY_OVERVIEW_SECTION_CACHE.get("sections")
                cached = (cache_sections or {}).get(fallback_section_id) if isinstance(cache_sections, dict) else None
            elif MEMORY_OVERVIEW_SECTION_CACHE.get("root"):
                MEMORY_OVERVIEW_SECTION_CACHE.update({"root": cache_root, "sections": {}})
        cache_expired = not (isinstance(cached, dict) and float(cached.get("expiresAt") or 0.0) > now)
        cached_signature = cached.get("signature") if isinstance(cached, dict) else None
        signature_matches = bool(signature is not None and cached_signature == signature)
        if isinstance(cached, dict) and (not cache_expired or signature_matches):
            warnings.extend(copy.deepcopy(cached.get("warnings") or []))
            section = copy.deepcopy(cached.get("section") or {})
            timing = copy.deepcopy(cached.get("timing") or {})
            cached_duration_ms = timing.get("durationMs") if isinstance(timing, dict) else None
            if isinstance(cached_duration_ms, (int, float)):
                timing["cachedLoadDurationMs"] = round(float(cached_duration_ms), 1)
            timing["durationMs"] = 0.0
            if isinstance(timing.get("subTimingsMs"), list):
                timing["cachedSubTimingsMs"] = timing.pop("subTimingsMs")
            timing["cacheHit"] = True
            timing["cacheExpired"] = bool(cache_expired)
            sections.append(section)
            timings.append(timing)
            continue

        section_warnings: list[str] = []
        started_at = time.perf_counter()
        sub_timings: list[dict[str, Any]] = []
        section = load_section(section_warnings, sub_timings)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
        section_id = str(section.get("id") or fallback_section_id).strip() if isinstance(section, dict) else fallback_section_id
        timing = {
            "sectionId": section_id,
            "durationMs": duration_ms,
            "itemCount": len(section.get("items") or []) if isinstance(section, dict) else 0,
            "cacheHit": False,
            "cacheExpired": bool(isinstance(cached, dict) and cache_expired),
            "cacheSignatureChanged": bool(
                isinstance(cached, dict)
                and cache_expired
                and signature is not None
                and cached_signature is not None
                and cached_signature != signature
            ),
        }
        if sub_timings:
            timing["subTimingsMs"] = _normalize_memory_overview_subtimings(sub_timings)
        warnings.extend(section_warnings)
        sections.append(section)
        timings.append(timing)
        with MEMORY_OVERVIEW_SECTION_CACHE_LOCK:
            if MEMORY_OVERVIEW_SECTION_CACHE.get("root") != cache_root:
                MEMORY_OVERVIEW_SECTION_CACHE.update({"root": cache_root, "sections": {}})
            cache_sections = MEMORY_OVERVIEW_SECTION_CACHE.setdefault("sections", {})
            cache_sections[fallback_section_id] = {
                "expiresAt": time.monotonic() + MEMORY_OVERVIEW_SECTION_CACHE_TTL_SECONDS,
                "signature": signature,
                "section": copy.deepcopy(section),
                "timing": copy.deepcopy(timing),
                "warnings": copy.deepcopy(section_warnings),
            }
    return sections, timings


def _clear_memory_overview_section_cache() -> None:
    with MEMORY_OVERVIEW_SECTION_CACHE_LOCK:
        MEMORY_OVERVIEW_SECTION_CACHE.update({"root": "", "sections": {}})


def _clear_memory_usage_contract_cache() -> None:
    with MEMORY_USAGE_CONTRACT_CACHE_LOCK:
        MEMORY_USAGE_CONTRACT_CACHE.update({"root": "", "expiresAt": 0.0, "payload": None})


def _load_timed_base_memory_sections(root: Path, warnings: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sections: list[dict[str, Any]] = []
    timings: list[dict[str, Any]] = []
    for fallback_section_id, load_section in _base_memory_section_specs(root, warnings):
        started_at = time.perf_counter()
        sub_timings: list[dict[str, Any]] = []
        section_warnings: list[str] = []
        section = load_section(section_warnings, sub_timings)
        warnings.extend(section_warnings)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
        section_id = str(section.get("id") or fallback_section_id).strip() if isinstance(section, dict) else fallback_section_id
        sections.append(section)
        timing = {
            "sectionId": section_id,
            "durationMs": duration_ms,
            "itemCount": len(section.get("items") or []) if isinstance(section, dict) else 0,
            "cacheHit": False,
        }
        if sub_timings:
            timing["subTimingsMs"] = _normalize_memory_overview_subtimings(sub_timings)
        timings.append(timing)
    return sections, timings


def _base_memory_section_specs(root: Path, warnings: list[str]):
    return [
        ("project-memory", lambda section_warnings, sub_timings: _project_memory_section(root, section_warnings)),
        ("runtime-memory", lambda section_warnings, sub_timings: _runtime_memory_section(root)),
        ("prompt-memory", lambda section_warnings, sub_timings: _prompt_memory_section(root)),
        ("workspace-database", lambda section_warnings, sub_timings: _workspace_database_section(root, sub_timings=sub_timings)),
        ("research-memory", lambda section_warnings, sub_timings: _research_memory_section(root)),
        ("team-knowledge", lambda section_warnings, sub_timings: _team_knowledge_memory_section(root, sub_timings=sub_timings)),
        ("git-memory", lambda section_warnings, sub_timings: _git_memory_section(root, sub_timings=sub_timings)),
        ("chat-session-memory", lambda section_warnings, sub_timings: _chat_session_memory_section(root, sub_timings=sub_timings)),
        ("self-evolution-memory", lambda section_warnings, sub_timings: _self_evolution_memory_section(root, sub_timings=sub_timings)),
        ("supervised-evolution-memory", lambda section_warnings, sub_timings: _supervised_evolution_memory_section(root, sub_timings=sub_timings)),
        ("runtime-scene-evidence", lambda section_warnings, sub_timings: _runtime_scene_memory_section(root, sub_timings=sub_timings)),
    ]


def _load_base_memory_section(root: Path, section_id: str, warnings: list[str]) -> dict[str, Any] | None:
    target = str(section_id or "").strip()
    if not target:
        return None
    for fallback_section_id, load_section in _base_memory_section_specs(root, warnings):
        if fallback_section_id != target:
            continue
        section_warnings: list[str] = []
        section = load_section(section_warnings, [])
        warnings.extend(section_warnings)
        return section if isinstance(section, dict) else None
    return None


def _project_memory_section(root: Path, warnings: list[str]) -> dict[str, Any]:
    project_memory_dir = root / ".docs" / "project-memory"
    memory_json_path = project_memory_dir / "memory.json"
    memory_payload = _load_json(memory_json_path, fallback={})
    lane_payloads = []
    if project_memory_dir.exists():
        for lane_path in sorted((project_memory_dir / "lanes").glob("*.json")):
            payload = _load_json(lane_path, fallback={})
            if isinstance(payload, dict):
                lane_payloads.append((lane_path, payload))

    index_path = project_memory_dir / "INDEX.md"
    index_text = _read_text(index_path)["content"] if index_path.exists() else ""
    actual_recent_count = _project_memory_recent_update_count(memory_payload, lane_payloads)
    declared_recent_count = _extract_index_count(index_text, "最近更新")
    if declared_recent_count is not None and declared_recent_count != actual_recent_count:
        warnings.append(
            f"项目记忆最近更新计数不一致：INDEX.md={declared_recent_count}, memory.json={actual_recent_count}"
        )

    raw_summary_payload = memory_payload.get("summary") if isinstance(memory_payload, dict) else {}
    summary_payload = raw_summary_payload if isinstance(raw_summary_payload, dict) else {}
    summary = (
        f"仓库级项目记忆，当前焦点：{summary_payload.get('focus') or '未记录'}。"
        "它服务于开发交接和页面展示，显式读取后 agent 可使用，但不会默认进入运行 prompt。"
    )
    items: list[dict[str, Any]] = []
    items.append(
        _file_item(
            root,
            memory_json_path,
            item_id="project-memory-json",
            title="memory.json",
            kind="project_memory_index",
            source="项目记忆",
            agent_visible=True,
            in_prompt=False,
            used_by=["项目记忆同步", "开发交接", "显式读取"],
            channels=["explicit_read"],
            summary=_summarize_project_memory(memory_payload),
        )
    )
    for path, title, kind in [
        (index_path, "INDEX.md", "project_memory_index"),
        (project_memory_dir / "profile.json", "profile.json", "project_memory_profile"),
        (project_memory_dir / "inbox.json", "inbox.json", "project_memory_inbox"),
        (root / "PROJECT_MEMORY.html", "PROJECT_MEMORY.html", "project_memory_html"),
    ]:
        items.append(
            _file_item(
                root,
                path,
                item_id=_item_id("project", path),
                title=title,
                kind=kind,
                source="项目记忆",
                agent_visible=True,
                in_prompt=False,
                used_by=["项目记忆页面", "显式读取"],
                channels=["explicit_read"],
            )
        )

    for lane_path, payload in lane_payloads:
        lane_title = str(payload.get("title") or lane_path.stem)
        lane_focus = str(payload.get("focus") or payload.get("summary") or "")
        items.append(
            _file_item(
                root,
                lane_path,
                item_id=_item_id("lane", lane_path),
                title=f"分线：{lane_title}",
                kind="project_memory_lane",
                source="项目记忆分线",
                agent_visible=True,
                in_prompt=False,
                used_by=["项目记忆同步", "显式读取"],
                channels=["explicit_read"],
                summary=f"{lane_focus or '未记录焦点'}",
            )
        )

    if project_memory_dir.exists():
        for html_path in sorted(project_memory_dir.glob("*.html")):
            items.append(
                _file_item(
                    root,
                    html_path,
                    item_id=_item_id("project-html", html_path),
                    title=html_path.name,
                    kind="project_memory_html",
                    source="项目记忆页面",
                    agent_visible=True,
                    in_prompt=False,
                    used_by=["项目记忆页面", "显式读取"],
                    channels=["explicit_read"],
                )
            )
    return _section(
        "project-memory",
        "项目记忆",
        "repository_project_memory",
        "manual_read",
        "显式读取后 agent 可使用；不默认注入普通对话、自进化或监督进化 prompt。",
        _rel(root, project_memory_dir),
        "",
        summary,
        items,
    )


def _runtime_memory_section(root: Path) -> dict[str, Any]:
    memory_dir = root / "workspace" / "memory"
    items = [
        _file_item(
            root,
            memory_dir / "memory.json",
            item_id="runtime-memory-index",
            title="workspace memory.json",
            kind="runtime_memory_index",
            source="运行时轻量记忆",
            agent_visible=True,
            in_prompt=False,
            used_by=["tools.memory_tools", "get_core_context_tool", "get_current_goal_tool"],
            channels=["explicit_read"],
            summary="轻量 core_wisdom/current_goal 索引；工具可读，当前默认 PromptManager.build() 不直接读取该文件。",
        ),
        _file_item(
            root,
            memory_dir / "tasks.json",
            item_id="runtime-task-memory",
            title="tasks.json",
            kind="task_memory",
            source="任务记忆",
            agent_visible=True,
            in_prompt=False,
            used_by=["TaskManager", "task_list_tool", "TASK_CHECKLIST 条件章节"],
            channels=["explicit_read"],
            summary="任务清单和完成摘要；用于防止长任务漂移。",
        ),
        _file_item(
            root,
            memory_dir / "pet_info.json",
            item_id="companion-state-memory",
            title="pet_info.json",
            kind="companion_state",
            source="陪伴体状态",
            agent_visible=True,
            in_prompt=False,
            used_by=["pet_service", "Chat/SelfEvolution 左栏状态"],
            channels=["explicit_read"],
            summary="长期陪伴体状态，不等同于当前 agent 推理记忆。",
        ),
    ]
    archives = sorted((memory_dir / "archives").glob("*.json")) if (memory_dir / "archives").exists() else []
    for path in archives[-LIST_LIMIT:]:
        items.append(
            _file_item(
                root,
                path,
                item_id=_item_id("runtime-archive", path),
                title=f"archive/{path.name}",
                kind="runtime_memory_archive",
                source="运行时记忆归档",
                agent_visible=True,
                in_prompt=False,
                used_by=["tools.memory_tools", "显式读取"],
                channels=["explicit_read"],
            )
        )
    return _section(
        "runtime-memory",
        "运行时记忆",
        "workspace_memory",
        "tool_accessible",
        "agent 可通过 memory tools 读取/写入；只有同步进 PromptManager.state_memory 后才进入 MEMORY 章节。",
        _rel(root, memory_dir),
        "",
        "workspace/memory 下的轻量索引、任务和归档。",
        items,
    )


def _prompt_memory_section(root: Path) -> dict[str, Any]:
    prompt_dir = root / "workspace" / "prompts"
    specs = [
        (
            "STATE_MEMORY.md",
            "state_memory",
            True,
            ["PromptManager.MEMORY", "agent._sync_runtime_state_memory"],
            ["conversation"],
        ),
        (
            "DYNAMIC.md",
            "dynamic_prompt_memory",
            False,
            ["tools.memory_tools", "workspace PromptManager 条件章节"],
            ["explicit_read"],
        ),
        (
            "COMPRESS_SUMMARY.md",
            "compressed_summary",
            False,
            ["legacy compatibility", "显式读取"],
            ["explicit_read"],
        ),
        (
            "IDENTITY.md",
            "dynamic_identity",
            False,
            ["workspace PromptManager 条件章节"],
            ["explicit_read"],
        ),
        (
            "USER.md",
            "dynamic_user",
            False,
            ["workspace PromptManager 条件章节"],
            ["explicit_read"],
        ),
        (
            "GIT_WORKFLOW.md",
            "git_workflow_prompt_memory",
            False,
            ["GIT_RULES 条件章节"],
            ["explicit_read"],
        ),
        (
            "CODEBASE_MAP.md",
            "codebase_map_cache",
            False,
            ["CODEBASE_MAP 条件章节"],
            ["explicit_read"],
        ),
    ]
    items = [
        _file_item(
            root,
            prompt_dir / filename,
            item_id=_item_id("prompt", prompt_dir / filename),
            title=filename,
            kind=kind,
            source="PromptManager 动态提示",
            agent_visible=True,
            in_prompt=in_prompt,
            used_by=used_by,
            channels=channels,
            summary=_prompt_file_summary(filename, in_prompt),
        )
        for filename, kind, in_prompt, used_by, channels in specs
    ]
    return _section(
        "prompt-memory",
        "PromptManager 动态提示",
        "prompt_workspace",
        "runtime_prompt",
        "STATE_MEMORY 可进入 MEMORY 章节；其他动态提示多为条件章节或工具显式读取。",
        _rel(root, prompt_dir),
        "",
        "workspace/prompts 下保存短期状态记忆、动态提示和提示词缓存。",
        items,
    )


def _workspace_database_section(root: Path, sub_timings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    db_path = root / "workspace" / "agent_brain.db"
    table_specs = [
        ("LongTermMemory", "long_term_memory", "长期记忆", ["record_learning_tool", "search_memory_tool"]),
        ("ErrorArchive", "error_archive", "错误归档", ["record_error", "search_error_archive_tool"]),
        ("CodebaseKnowledge", "codebase_knowledge", "代码库认知", ["CODEBASE_MAP 条件章节", "search_codebase_knowledge"]),
        ("TaskLog", "task_log", "任务日志", ["WorkspaceManager", "显式查询"]),
        ("Identity", "identity_memory", "身份/规则快照", ["WorkspaceManager", "显式查询"]),
    ]
    items = []
    for table, kind, title, used_by in table_specs:
        payload = _time_memory_overview_step(
            sub_timings,
            f"sqlite.{table}",
            lambda table=table: _sqlite_table_snapshot(db_path, table),
        )
        items.append(
            _data_item(
                root,
                item_id=f"sqlite-{table.lower()}",
                title=title,
                kind=kind,
                source="workspace/agent_brain.db",
                path=_rel(root, db_path),
                updated_at=payload.get("updatedAt", _mtime(db_path)),
                agent_visible=True,
                in_prompt=False,
                used_by=used_by,
                channels=["explicit_read"],
                summary=f"{table}: {payload.get('count', 0)} 条；通过工具或条件章节使用，不默认全量注入 prompt。",
                content=payload,
                content_type="json",
            )
        )
    return _section(
        "workspace-database",
        "SQLite 长期记忆",
        "workspace_database",
        "tool_accessible",
        "agent 可通过搜索/状态工具读取部分表；不会默认把数据库全量注入 prompt。",
        _rel(root, db_path),
        "",
        "agent_brain.db 中的长期记忆、错误归档、代码库认知和任务日志。",
        items,
    )


def _research_memory_section(root: Path) -> dict[str, Any]:
    knowledge_path = root / "workspace" / "research" / "knowledge_base.json"
    knowledge_exists = knowledge_path.exists()
    payload = _load_json(knowledge_path, fallback={})
    summary = _research_knowledge_summary(payload)
    item_summary = (
        f"{summary['entryCount']} 个来源，{summary['claimCount']} 条论断，"
        f"{summary['evidenceCount']} 条证据，{summary['gapCount']} 个缺口；"
        "用于科研 agent 联网前复用资料、检查重复搜索，并为后续自进化记忆提供来源。"
    )
    item_content = {
        "schemaVersion": summary["schemaVersion"],
        "entryCount": summary["entryCount"],
        "claimCount": summary["claimCount"],
        "evidenceCount": summary["evidenceCount"],
        "gapCount": summary["gapCount"],
        "hypothesisCount": summary["hypothesisCount"],
        "experimentCount": summary["experimentCount"],
        "recentSources": summary["recentSources"],
        "agentEvolutionMemory": summary["agentEvolutionMemory"],
    }
    if not knowledge_exists:
        item_summary = "科研知识库尚未生成；运行科研广撒网或深搜后会创建 workspace/research/knowledge_base.json。"
        item_content = {
            **item_content,
            "status": "missing",
            "nextStep": "Run a research broad or deep search to create the knowledge base.",
        }
    items = [
        _virtual_data_item(
            item_id="research-knowledge-base",
            title="research knowledge_base.json",
            kind="research_knowledge_base",
            source="科研知识库",
            path=_rel(root, knowledge_path),
            updated_at=str(payload.get("updatedAt") or _mtime(knowledge_path)) if isinstance(payload, dict) else _mtime(knowledge_path),
            agent_visible=knowledge_exists,
            in_prompt=False,
            used_by=["ResearchKnowledgeBase", "research theme discovery agents", "/api/research/knowledge-base"],
            channels=["research", "self_evolution", "explicit_read"],
            visibility_class="agent_visible" if knowledge_exists else "missing",
            summary=item_summary,
            content=item_content,
            content_type="json",
            exists=knowledge_exists,
        )
    ]
    return _section(
        "research-memory",
        "科研记忆",
        "research_knowledge_memory",
        "tool_accessible",
        "科研 agent 可通过 ResearchKnowledgeBase 与 /api/research/knowledge-base 使用；当前不默认注入普通对话 prompt。",
        _rel(root, knowledge_path),
        "/api/research/knowledge-base",
        "科研调研来源、可追溯认知层和后续自进化记忆桥接。它复用现有 Memory 总览，不另建孤立入口。",
        items,
    )


def _team_knowledge_memory_section(root: Path, sub_timings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    try:
        from core.web.services.team_knowledge_service import team_knowledge_memory_section_summary

        summary_payload = _time_memory_overview_step(
            sub_timings,
            "team_knowledge.summary",
            lambda: team_knowledge_memory_section_summary(),
        )
    except Exception:
        summary_payload = {
            "knowledgeBaseCount": 0,
            "pendingProposalCount": 0,
            "itemCount": 0,
            "sourceArtifactCount": 0,
            "updatedAt": "",
            "status": "unavailable",
        }
    knowledge_base_count = int(summary_payload.get("knowledgeBaseCount") or 0)
    pending_count = int(summary_payload.get("pendingProposalCount") or 0)
    item_count = int(summary_payload.get("itemCount") or 0)
    source_count = int(summary_payload.get("sourceArtifactCount") or 0)
    item = _virtual_data_item(
        item_id="team-knowledge-platform",
        title="团队知识库平台",
        kind="team_knowledge_platform",
        source="团队知识库",
        path="workspace/teams/*/knowledge",
        updated_at=str(summary_payload.get("updatedAt") or ""),
        agent_visible=True,
        in_prompt=False,
        used_by=["/api/knowledge/overview", "/agents/memory/knowledge", "knowledge_query_tool"],
        channels=["research", "explicit_read"],
        visibility_class="agent_visible",
        summary=(
            f"{knowledge_base_count} 个团队知识库，{item_count} 条正式知识，"
            f"{pending_count} 条待审提案，{source_count} 个来源登记。"
        ),
        content={
            "sourceApi": "/api/knowledge/overview",
            "knowledgeBaseCount": knowledge_base_count,
            "pendingProposalCount": pending_count,
            "itemCount": item_count,
            "sourceArtifactCount": source_count,
            "promptInjection": False,
            "defaultEffect": "tool_readable",
        },
        content_type="json",
        exists=knowledge_base_count > 0 or item_count > 0 or pending_count > 0 or source_count > 0,
    )
    return _section(
        "team-knowledge",
        "团队知识库",
        "team_knowledge_platform",
        "tool_readable",
        "团队共享知识按权限显式检索；P1 不默认注入 prompt。",
        "workspace/teams/*/knowledge",
        "/api/knowledge/overview",
        "团队共享知识库、来源登记、精炼提案、批次落盘和重要程度标记的统一入口。",
        [item],
    )


def _git_memory_section(root: Path, sub_timings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    db_path = root / "workspace" / "agent_brain.db"
    git_snapshot = _time_memory_overview_step(sub_timings, "git.snapshot", lambda: _git_snapshot(root))
    git_db = {
        "attentionCache": _time_memory_overview_step(
            sub_timings,
            "sqlite.GitAttentionCache",
            lambda: _sqlite_table_snapshot(db_path, "GitAttentionCache", limit=5),
        ),
        "fileChanges": _time_memory_overview_step(
            sub_timings,
            "sqlite.GitFileChange",
            lambda: _sqlite_table_snapshot(db_path, "GitFileChange", limit=10),
        ),
        "entityChanges": _time_memory_overview_step(
            sub_timings,
            "sqlite.GitEntityChange",
            lambda: _sqlite_table_snapshot(db_path, "GitEntityChange", limit=10),
        ),
        "worktreeSnapshots": _time_memory_overview_step(
            sub_timings,
            "sqlite.GitWorkingTreeSnapshot",
            lambda: _sqlite_table_snapshot(db_path, "GitWorkingTreeSnapshot", limit=5),
        ),
    }
    items = [
        _data_item(
            root,
            item_id="git-working-tree",
            title="当前 Git 工作区",
            kind="git_worktree_snapshot",
            source="git status --porcelain",
            path=".git",
            updated_at=_now_iso(),
            agent_visible=True,
            in_prompt=True,
            used_by=["GIT_MEMORY prompt section", "GitMemoryService.format_prompt_context"],
            channels=["conversation", "self_evolution"],
            summary=git_snapshot.get("summary") or "当前 Git 状态不可用。",
            content=git_snapshot,
            content_type="json",
        ),
        _data_item(
            root,
            item_id="git-memory-db",
            title="Git attention/index cache",
            kind="git_memory_database",
            source="workspace/agent_brain.db",
            path=_rel(root, db_path),
            updated_at=_mtime(db_path),
            agent_visible=True,
            in_prompt=True,
            used_by=["GIT_MEMORY prompt section", "GitMemoryService"],
            channels=["conversation", "self_evolution"],
            summary="最近提交变化、当前脏区、关注实体与验证摘要会进入 GIT_MEMORY 章节。",
            content=git_db,
            content_type="json",
        ),
    ]
    return _section(
        "git-memory",
        "Git 记忆",
        "git_memory",
        "runtime_prompt",
        "普通对话和自进化底层 agent 默认可通过 GIT_MEMORY 感知当前脏区、最近变化和关注实体。",
        "workspace/agent_brain.db",
        "",
        "GitMemoryService 生成 prompt 上下文，并维护 Git 索引表。",
        items,
    )


def _chat_session_memory_section(root: Path, sub_timings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    chat_state = root / "workspace" / "chat" / "chat_state.json"
    session_root = root / "workspace" / "sessions"
    sessions_payload = _time_memory_overview_step(
        sub_timings,
        "session_workspace.summary",
        lambda: _session_memory_summary(root, session_root),
    )
    items = [
        _file_item(
            root,
            chat_state,
            item_id="chat-state",
            title="chat_state.json",
            kind="chat_conversation_memory",
            source="Web Chat 会话状态",
            agent_visible=True,
            in_prompt=True,
            used_by=["session_service", "Web chat turn history"],
            channels=["conversation"],
            summary="Web 对话历史和 active_task；当前会话历史会作为 chat agent 的上下文来源。",
        ),
        _data_item(
            root,
            item_id="session-workspaces",
            title="workspace/sessions/*/memory",
            kind="session_isolated_memory",
            source="Web Chat session workspace",
            path=_rel(root, session_root),
            updated_at=sessions_payload.get("updatedAt", ""),
            agent_visible=True,
            in_prompt=False,
            used_by=["session_service._session_tool_workspace_override", "tools.memory_tools"],
            channels=["conversation", "explicit_read"],
            summary=(
                f"{sessions_payload.get('sessionCount', 0)} 个 session workspace；"
                "运行中的 Web chat 工具会被隔离到对应 session/memory。"
            ),
            content=sessions_payload,
            content_type="json",
        ),
    ]
    return _section(
        "chat-session-memory",
        "会话记忆",
        "chat_session_memory",
        "runtime_context",
        "Web chat agent 能感知当前会话历史；每个 session 的工具记忆目录彼此隔离。",
        _rel(root, session_root),
        "",
        "Web Chat 对话历史、active_task 和 session-scoped memory。",
        items,
    )


def _self_evolution_memory_section(root: Path, sub_timings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    db_path = root / "workspace" / "agent_brain.db"
    active_promotions = root / "workspace" / "gym" / "active_promotions.json"
    audit_path = root / "workspace" / "evolution" / "audit.jsonl"
    transaction_payload = _time_memory_overview_step(
        sub_timings,
        "sqlite.EvolutionTransaction",
        lambda: _sqlite_table_snapshot(db_path, "EvolutionTransaction", limit=10),
    )
    items = [
        _file_item(
            root,
            active_promotions,
            item_id="self-active-advisory",
            title="active_promotions.json",
            kind="active_advisory_baseline",
            source="Gym active advisory baseline",
            agent_visible=True,
            in_prompt=True,
            used_by=["build_self_evolution_run_prompt", "build_active_advisory_snapshot"],
            channels=["self_evolution"],
            summary="自进化 run prompt 会显式带入 active advisory baseline 作为观察参照。",
        ),
        _data_item(
            root,
            item_id="self-evolution-transactions",
            title="EvolutionTransaction",
            kind="self_evolution_transaction_memory",
            source="workspace/agent_brain.db",
            path=_rel(root, db_path),
            updated_at=transaction_payload.get("updatedAt", _mtime(db_path)),
            agent_visible=True,
            in_prompt=True,
            used_by=["build_self_evolution_run_prompt", "self_evolution_service"],
            channels=["self_evolution"],
            summary="最近自进化事务会进入自进化 run prompt，用于判断共享现场和上轮结果。",
            content=transaction_payload,
            content_type="json",
        ),
        _file_item(
            root,
            audit_path,
            item_id="self-evolution-audit",
            title="workspace/evolution/audit.jsonl",
            kind="self_evolution_audit",
            source="自进化审计日志",
            agent_visible=True,
            in_prompt=False,
            used_by=["self_evolution_service", "显式日志读取"],
            channels=["self_evolution", "explicit_read"],
            summary="审计证据默认展示在状态面；不默认全量进入 run prompt。",
        ),
    ]
    return _section(
        "self-evolution-memory",
        "自进化记忆",
        "self_evolution_memory",
        "runtime_prompt",
        "自进化 run prompt 显式感知 advisory baseline、worktree snapshot、recent transactions 和 fitness。",
        "workspace/evolution",
        "/api/evolution/self/overview",
        "自进化使用的建议基线、事务历史和审计证据。",
        items,
    )


def _supervised_evolution_memory_section(root: Path, sub_timings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    supervised_root = root / "workspace" / "supervised_evolution"
    decisions = _time_memory_overview_step(
        sub_timings,
        "latest_files.supervised_decisions",
        lambda: _latest_files(supervised_root / "decisions", "*.json", limit=10),
    )
    policies = _time_memory_overview_step(
        sub_timings,
        "latest_files.supervised_policy",
        lambda: _latest_files(supervised_root / "policy", "*.json", limit=10),
    )
    bundles = _time_memory_overview_step(
        sub_timings,
        "latest_files.evaluation_bundles",
        lambda: _latest_files(root / "workspace" / "evaluation" / "bundles", "*.json", limit=10),
    )
    decision_payload = _time_memory_overview_step(
        sub_timings,
        "file_payload.supervised_decisions",
        lambda: _file_list_payload(root, decisions),
        count=lambda payload: int(payload.get("count") or 0) if isinstance(payload, dict) else 0,
    )
    policy_payload = _time_memory_overview_step(
        sub_timings,
        "file_payload.supervised_policy",
        lambda: _file_list_payload(root, policies),
        count=lambda payload: int(payload.get("count") or 0) if isinstance(payload, dict) else 0,
    )
    bundle_payload = _time_memory_overview_step(
        sub_timings,
        "file_payload.evaluation_bundles",
        lambda: _file_list_payload(root, bundles),
        count=lambda payload: int(payload.get("count") or 0) if isinstance(payload, dict) else 0,
    )
    items = [
        _file_item(
            root,
            supervised_root / "workbench_state.json",
            item_id="supervised-workbench-state",
            title="workbench_state.json",
            kind="supervised_workbench_state",
            source="监督进化工作台状态",
            agent_visible=True,
            in_prompt=False,
            used_by=["evolution_service", "supervised_control_service"],
            channels=["supervised_evolution", "explicit_read"],
            summary="监督工作台上次选择的数据集、bundle 和运行设置。",
        ),
        _file_item(
            root,
            supervised_root / "history.jsonl",
            item_id="supervised-history",
            title="history.jsonl",
            kind="supervised_history",
            source="监督进化历史",
            agent_visible=True,
            in_prompt=False,
            used_by=["evolution_service", "显式读取"],
            channels=["supervised_evolution", "explicit_read"],
            summary="监督运行历史索引；用于页面和后续诊断，不默认进入 agent prompt。",
        ),
        _data_item(
            root,
            item_id="supervised-decisions",
            title="decisions/*.json",
            kind="supervised_decision_records",
            source="监督结论",
            path=_rel(root, supervised_root / "decisions"),
            updated_at=_latest_mtime(decisions),
            agent_visible=True,
            in_prompt=False,
            used_by=["evolution_service", "proposal library", "显式读取"],
            channels=["supervised_evolution", "explicit_read"],
            summary=f"最近 {len(decisions)} 条监督决策记录。",
            content=decision_payload,
            content_type="json",
        ),
        _data_item(
            root,
            item_id="supervised-policy",
            title="policy/*.json",
            kind="supervised_policy_records",
            source="监督策略记录",
            path=_rel(root, supervised_root / "policy"),
            updated_at=_latest_mtime(policies),
            agent_visible=True,
            in_prompt=False,
            used_by=["evolution_service", "policy/action review"],
            channels=["supervised_evolution", "explicit_read"],
            summary=f"最近 {len(policies)} 条监督策略记录。",
            content=policy_payload,
            content_type="json",
        ),
        _data_item(
            root,
            item_id="supervised-bundles",
            title="workspace/evaluation/bundles/*.json",
            kind="supervised_prompt_bundles",
            source="监督评测 bundle",
            path="workspace/evaluation/bundles",
            updated_at=_latest_mtime(bundles),
            agent_visible=True,
            in_prompt=True,
            used_by=["run_supervised_evolution_session", "scripts.evolution_harness"],
            channels=["supervised_evolution"],
            summary=f"监督 harness 会把 bundle case prompt 交给 baseline/candidate agent；当前列出最近 {len(bundles)} 个文件。",
            content=bundle_payload,
            content_type="json",
        ),
    ]
    return _section(
        "supervised-evolution-memory",
        "监督进化记忆",
        "supervised_evolution_memory",
        "runtime_context",
        "监督 harness 感知 bundle/dataset prompt 与 active advisory baseline；不会读取项目记忆全量。",
        _rel(root, supervised_root),
        "/api/evolution/overview",
        "监督进化的工作台状态、决策、策略和评测 bundle。",
        items,
    )


def _runtime_scene_memory_section(root: Path, sub_timings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    scene_root = root / "logs" / "runtime_scenes"
    scene_dirs = []
    if scene_root.exists():
        scene_dirs = _time_memory_overview_step(
            sub_timings,
            "runtime_scene.list_dirs",
            lambda: sorted(
                [path for path in scene_root.iterdir() if path.is_dir()],
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )[:LIST_LIMIT],
            count=lambda paths: len(paths),
        )
    scene_summaries = _time_memory_overview_step(
        sub_timings,
        "runtime_scene.summaries",
        lambda: [_runtime_scene_summary(root, path) for path in scene_dirs],
        count=lambda summaries: len(summaries),
    )
    items = [
        _data_item(
            root,
            item_id="runtime-scenes-index",
            title="runtime_scenes/*",
            kind="runtime_scene_evidence_index",
            source="运行现场日志包",
            path=_rel(root, scene_root),
            updated_at=_latest_mtime(scene_dirs),
            agent_visible=True,
            in_prompt=True,
            used_by=["RUNTIME_LOG_INDEX prompt section", "LogsRoute", "runtime_scene_service", "显式日志读取"],
            channels=["conversation", "self_evolution", "supervised_evolution", "explicit_read"],
            visibility_class="prompt",
            summary=(
                f"最近 {len(scene_dirs)} 个运行现场包；RUNTIME_LOG_INDEX 只把最近包索引、状态、"
                "问题簇和下一步摘要注入 prompt，不注入 raw 日志全文。"
            ),
            content={
                "scenes": scene_summaries,
            },
            content_type="json",
        )
    ]
    return _section(
        "runtime-scene-evidence",
        "运行现场证据",
        "runtime_scene_evidence",
        "runtime_prompt",
        "agent 默认可通过 RUNTIME_LOG_INDEX 感知最近运行现场索引；raw 日志仍需显式读取。",
        _rel(root, scene_root),
        "/api/logs/runtime-scenes",
        "用于重构失败轮次、工具序列和收束原因的证据包。",
        items,
    )


def _research_knowledge_summary(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    entries = data.get("entries") if isinstance(data.get("entries"), list) else []
    claims = data.get("claims") if isinstance(data.get("claims"), list) else []
    evidence = data.get("evidence") if isinstance(data.get("evidence"), list) else []
    gaps = data.get("gaps") if isinstance(data.get("gaps"), list) else []
    hypotheses = data.get("hypotheses") if isinstance(data.get("hypotheses"), list) else []
    experiments = data.get("experiments") if isinstance(data.get("experiments"), list) else []
    recent_sources = []
    for item in sorted(
        [entry for entry in entries if isinstance(entry, dict)],
        key=lambda entry: str(entry.get("lastSeenAt") or entry.get("firstSeenAt") or ""),
        reverse=True,
    )[:8]:
        recent_sources.append(
            {
                "knowledgeId": str(item.get("knowledgeId") or ""),
                "kind": str(item.get("kind") or ""),
                "title": _clip(str(item.get("title") or ""), 160),
                "lastSeenAt": str(item.get("lastSeenAt") or ""),
                "hitCount": item.get("hitCount") or 0,
            }
        )
    evolution_memory = data.get("agentEvolutionMemory") if isinstance(data.get("agentEvolutionMemory"), dict) else {}
    return {
        "schemaVersion": int(data.get("schemaVersion") or 0) if isinstance(data.get("schemaVersion"), int) else data.get("schemaVersion") or 0,
        "entryCount": len(entries),
        "claimCount": len(claims),
        "evidenceCount": len(evidence),
        "gapCount": len(gaps),
        "hypothesisCount": len(hypotheses),
        "experimentCount": len(experiments),
        "recentSources": recent_sources,
        "agentEvolutionMemory": {
            "experienceRefs": len(evolution_memory.get("experienceRefs") or []),
            "reflectionRefs": len(evolution_memory.get("reflectionRefs") or []),
            "candidateRefs": len(evolution_memory.get("candidateRefs") or []),
            "strategyNotes": len(evolution_memory.get("strategyNotes") or []),
        },
    }


def _section(
    section_id: str,
    title: str,
    source_kind: str,
    visibility: str,
    agent_visibility: str,
    source_path: str,
    source_api: str,
    summary: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": section_id,
        "title": title,
        "sourceKind": source_kind,
        "visibility": visibility,
        "agentVisibility": agent_visibility,
        "sourcePath": source_path,
        "sourceApi": source_api,
        "updatedAt": _latest_item_timestamp(items),
        "summary": summary,
        "items": items,
    }


def _apply_managed_memory(root: Path, sections: list[dict[str, Any]], managed_memory: dict[str, Any]) -> list[dict[str, Any]]:
    user_section = _user_managed_memory_section(root, managed_memory)
    overrides = managed_memory.get("overrides") if isinstance(managed_memory.get("overrides"), dict) else {}
    merged_sections = [user_section]
    for section in sections:
        section_id = str(section.get("id") or "")
        items = []
        for item in section.get("items") or []:
            if not isinstance(item, dict):
                continue
            key = _managed_override_key(section_id, str(item.get("id") or ""))
            items.append(_apply_item_override(dict(item), overrides.get(key)))
        merged = {
            **section,
            "items": items,
            "updatedAt": _latest_item_timestamp(items),
        }
        merged_sections.append(merged)
    return merged_sections


def _defer_memory_overview_content(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    light_sections = copy.deepcopy(sections)
    for section in light_sections:
        for item in section.get("items") or []:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "")
            item["contentLength"] = len(content)
            item["contentDeferred"] = bool(content)
            item["content"] = ""
    return light_sections


def _user_managed_memory_section(root: Path, managed_memory: dict[str, Any]) -> dict[str, Any]:
    items = [
        _user_managed_item(root, item)
        for item in managed_memory.get("items") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    return _section(
        USER_MANAGED_SECTION_ID,
        "用户手动记忆",
        USER_MANAGED_SOURCE_KIND,
        "user_managed",
        "用户手动维护；默认可被显式读取，但不会直接改写系统来源文件或自动注入 prompt。",
        _rel(root, _managed_memory_path(root)),
        "/api/memory/items",
        "用户新增、编辑、禁用和恢复记忆的管理层；系统来源只保存覆盖状态。",
        items,
    )


def _user_managed_item(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    updated_at = str(item.get("updatedAt") or item.get("createdAt") or "")
    content = str(item.get("content") or "")
    limited = _limit_text(content)
    return {
        **_memory_item_payload(
            item_id=str(item.get("id") or ""),
            title=_clip(str(item.get("title") or "用户记忆"), 160),
            kind="user_managed_memory",
            source="用户手动记忆",
            path=_rel(root, _managed_memory_path(root)),
            updated_at=updated_at,
            agent_visible=bool(item.get("agentVisible", True)),
            in_prompt=bool(item.get("inPrompt", False)),
            used_by=["/memory 用户管理", "显式读取"],
            channels=_normalize_channels(item.get("channels") if isinstance(item.get("channels"), list) else ["explicit_read"], agent_visible=True, in_prompt=False),
            visibility_class="agent_visible",
            summary=_clip(str(item.get("summary") or _summarize_text(content) or item.get("title") or "用户记忆"), 360),
            content=limited["content"],
            content_type="markdown",
            content_truncated=limited["truncated"],
            exists=True,
        ),
        "managedState": {
            "editable": True,
            "deletable": True,
            "restorable": False,
            "disabled": False,
            "userManaged": True,
            "overridden": False,
            "actionHint": "用户创建的记忆会持久化在管理层，可直接编辑或删除。",
        },
    }


def _apply_item_override(item: dict[str, Any], override: Any) -> dict[str, Any]:
    if not isinstance(override, dict):
        return _with_default_managed_state(item)
    overridden = False
    for field in ("title", "summary"):
        if field in override and override.get(field) is not None:
            item[field] = str(override.get(field) or "")
            overridden = True
    if "content" in override and override.get("content") is not None:
        limited = _limit_text(str(override.get("content") or ""))
        item["content"] = limited["content"]
        item["contentTruncated"] = limited["truncated"]
        item["contentType"] = "markdown"
        overridden = True
    if override.get("updatedAt"):
        item["updatedAt"] = str(override.get("updatedAt") or "")
    disabled = bool(override.get("disabled"))
    if disabled:
        item["agentVisible"] = False
        item["inPrompt"] = False
        item["visibilityClass"] = "manual"
        item["channels"] = []
        item["summary"] = _clip(f"[已禁用] {item.get('summary') or ''}", 360)
    item["managedState"] = {
        "editable": True,
        "deletable": True,
        "restorable": True,
        "disabled": disabled,
        "userManaged": False,
        "overridden": overridden or disabled,
        "actionHint": "系统来源不会被直接改写；这里保存的是用户覆盖、禁用或恢复状态。",
    }
    return item


def _with_default_managed_state(item: dict[str, Any]) -> dict[str, Any]:
    item.setdefault(
        "managedState",
        {
            "editable": True,
            "deletable": True,
            "restorable": False,
            "disabled": False,
            "userManaged": False,
            "overridden": False,
            "actionHint": "系统来源可被覆盖或禁用，原始证据文件保持不变。",
        },
    )
    return item


def _file_item(
    root: Path,
    path: Path,
    *,
    item_id: str,
    title: str,
    kind: str,
    source: str,
    agent_visible: bool,
    in_prompt: bool,
    used_by: list[str],
    channels: list[str] | None = None,
    visibility_class: str | None = None,
    summary: str = "",
) -> dict[str, Any]:
    file_payload = _read_text(path)
    exists = path.exists()
    content_type = _content_type(path)
    final_summary = (
        summary
        or _file_content_summary(path, file_payload["content"], content_type=content_type, exists=exists)
        or ("存在" if exists else "文件不存在")
    )
    return _memory_item_payload(
        item_id=item_id,
        title=title,
        kind=kind,
        source=source,
        path=_rel(root, path),
        updated_at=_mtime(path),
        agent_visible=agent_visible,
        in_prompt=in_prompt,
        used_by=used_by,
        channels=channels,
        visibility_class=visibility_class,
        summary=_clip(final_summary, 360),
        content=file_payload["content"],
        content_type=content_type,
        content_truncated=file_payload["truncated"],
        exists=exists,
    )


def _data_item(
    root: Path,
    *,
    item_id: str,
    title: str,
    kind: str,
    source: str,
    path: str,
    updated_at: str,
    agent_visible: bool,
    in_prompt: bool,
    used_by: list[str],
    summary: str,
    content: Any,
    content_type: str,
    channels: list[str] | None = None,
    visibility_class: str | None = None,
) -> dict[str, Any]:
    text = _json_text(content) if content_type == "json" else str(content or "")
    limited = _limit_text(text)
    return _memory_item_payload(
        item_id=item_id,
        title=title,
        kind=kind,
        source=source,
        path=path,
        updated_at=updated_at,
        agent_visible=agent_visible,
        in_prompt=in_prompt,
        used_by=used_by,
        channels=channels,
        visibility_class=visibility_class,
        summary=_clip(summary, 360),
        content=limited["content"],
        content_type=content_type,
        content_truncated=limited["truncated"],
        exists=True,
    )


def _virtual_data_item(
    *,
    item_id: str,
    title: str,
    kind: str,
    source: str,
    path: str,
    updated_at: str,
    agent_visible: bool,
    in_prompt: bool,
    used_by: list[str],
    summary: str,
    content: Any,
    content_type: str,
    exists: bool,
    channels: list[str] | None = None,
    visibility_class: str | None = None,
) -> dict[str, Any]:
    text = _json_text(content) if content_type == "json" else str(content or "")
    limited = _limit_text(text)
    return _memory_item_payload(
        item_id=item_id,
        title=title,
        kind=kind,
        source=source,
        path=path,
        updated_at=updated_at,
        agent_visible=agent_visible,
        in_prompt=in_prompt,
        used_by=used_by,
        channels=channels,
        visibility_class=visibility_class,
        summary=_clip(summary, 360),
        content=limited["content"],
        content_type=content_type,
        content_truncated=limited["truncated"],
        exists=exists,
    )


def _memory_item_payload(
    *,
    item_id: str,
    title: str,
    kind: str,
    source: str,
    path: str,
    updated_at: str,
    agent_visible: bool,
    in_prompt: bool,
    used_by: list[str],
    channels: list[str] | None,
    visibility_class: str | None,
    summary: str,
    content: str,
    content_type: str,
    content_truncated: bool,
    exists: bool,
) -> dict[str, Any]:
    normalized_channels = _normalize_channels(channels, agent_visible=agent_visible, in_prompt=in_prompt)
    normalized_visibility = _normalize_visibility_class(
        visibility_class,
        agent_visible=agent_visible,
        in_prompt=in_prompt,
        exists=exists,
        content_truncated=content_truncated,
    )
    return {
        "id": item_id,
        "title": title,
        "kind": kind,
        "source": source,
        "path": path,
        "agentVisible": agent_visible,
        "inPrompt": in_prompt,
        "visibilityClass": normalized_visibility,
        "channels": normalized_channels,
        "updatedAt": updated_at,
        "usedBy": used_by,
        "summary": summary,
        "content": content,
        "contentType": content_type,
        "contentTruncated": content_truncated,
        "exists": exists,
    }


def _normalize_channels(channels: list[str] | None, *, agent_visible: bool, in_prompt: bool) -> list[str]:
    values = [channel for channel in channels or [] if channel in MEMORY_CHANNELS]
    if not values and agent_visible and not in_prompt:
        values = ["explicit_read"]
    unique_values = dict.fromkeys(values)
    return [channel for channel in MEMORY_CHANNEL_ORDER if channel in unique_values]


def _normalize_visibility_class(
    visibility_class: str | None,
    *,
    agent_visible: bool,
    in_prompt: bool,
    exists: bool,
    content_truncated: bool,
) -> str:
    if visibility_class in VISIBILITY_CLASSES:
        return visibility_class
    if not exists:
        return "missing"
    if in_prompt:
        return "prompt"
    if agent_visible:
        return "agent_visible"
    return "manual"


def _read_text(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"content": "", "truncated": False}
    try:
        return _limit_text(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        return {"content": f"[read_error] {type(exc).__name__}: {exc}", "truncated": False}


def _limit_text(text: str, limit: int = CONTENT_LIMIT) -> dict[str, Any]:
    value = str(text or "")
    if len(value) <= limit:
        return {"content": value, "truncated": False}
    return {
        "content": value[:limit].rstrip() + "\n\n...[truncated]",
        "truncated": True,
    }


def _load_json(path: Path, *, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _managed_memory_path(root: Path) -> Path:
    return root / "workspace" / "memory" / USER_MANAGED_MEMORY_FILENAME


def _load_managed_memory(root: Path, *, warnings: list[str] | None = None) -> dict[str, Any]:
    path = _managed_memory_path(root)
    if not path.exists():
        return _empty_managed_memory()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if warnings is not None:
            warnings.append(f"用户记忆管理层不可读：{type(exc).__name__}: {exc}")
        return _empty_managed_memory()
    if not isinstance(payload, dict):
        if warnings is not None:
            warnings.append("用户记忆管理层格式错误：根节点不是对象")
        return _empty_managed_memory()
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    overrides = payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {}
    audit = payload.get("audit") if isinstance(payload.get("audit"), list) else []
    return {
        "schemaVersion": 1,
        "items": [item for item in items if isinstance(item, dict)],
        "overrides": {str(key): value for key, value in overrides.items() if isinstance(value, dict)},
        "audit": [item for item in audit if isinstance(item, dict)][-MANAGED_AUDIT_LIMIT:],
    }


def _empty_managed_memory() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "items": [],
        "overrides": {},
        "audit": [],
    }


def _save_managed_memory(root: Path, payload: dict[str, Any]) -> None:
    path = _managed_memory_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = {
        "schemaVersion": 1,
        "items": payload.get("items") if isinstance(payload.get("items"), list) else [],
        "overrides": payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {},
        "audit": (payload.get("audit") if isinstance(payload.get("audit"), list) else [])[-MANAGED_AUDIT_LIMIT:],
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(_json_text(normalized) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _append_managed_audit(
    managed_memory: dict[str, Any],
    action: str,
    section_id: str,
    item_id: str,
    item: dict[str, Any],
) -> None:
    audit = managed_memory.setdefault("audit", [])
    if not isinstance(audit, list):
        audit = []
        managed_memory["audit"] = audit
    audit.append(
        {
            "timestamp": _now_iso(),
            "action": action,
            "sectionId": section_id,
            "itemId": item_id,
            "title": str(item.get("title") or ""),
            "summary": _clip(str(item.get("summary") or ""), 240),
        }
    )
    del audit[:-MANAGED_AUDIT_LIMIT]


def _managed_override_key(section_id: str, item_id: str) -> str:
    return f"{section_id}:{item_id}"


def _find_user_managed_item(managed_memory: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for item in managed_memory.get("items") or []:
        if isinstance(item, dict) and str(item.get("id") or "") == item_id:
            return item
    return None


def _find_base_memory_item(root: Path, section_id: str, item_id: str) -> dict[str, Any] | None:
    warnings: list[str] = []
    section = _load_base_memory_section(root, section_id, warnings)
    if section is None:
        return None
    for item in section.get("items") or []:
        if isinstance(item, dict) and str(item.get("id") or "") == item_id:
            return dict(item)
    return None


def _managed_patch_from_payload(payload: dict[str, Any], *, require_any: bool) -> dict[str, str]:
    patch: dict[str, str] = {}
    for field, limit in (("title", 160), ("summary", 1000), ("content", 20000)):
        if field not in payload:
            continue
        value = _normalize_managed_text(payload.get(field), max_length=limit)
        if field == "title" and not value:
            raise ValueError("title is required")
        patch[field] = value
    if require_any and not patch:
        raise ValueError("At least one editable field is required")
    return patch


def _normalize_managed_text(value: Any, *, max_length: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip()


def _record_memory_management_event(action: str, section_id: str, item_id: str, item: dict[str, Any]) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "memory_service",
            "memory_management",
            f"memory.{action}",
            message=f"Memory management action: {action}",
            outcome="succeeded",
            fields={
                "action": action,
                "sectionId": section_id,
                "itemId": item_id,
                "title": str(item.get("title") or ""),
                "userManaged": bool((item.get("managedState") or {}).get("userManaged")),
                "overridden": bool((item.get("managedState") or {}).get("overridden")),
                "disabled": bool((item.get("managedState") or {}).get("disabled")),
            },
            lifecycle=True,
        )
    except Exception:
        pass


def _append_memory_overview_phase_timing(
    timings: list[dict[str, Any]],
    phase: str,
    started_at: float,
    *,
    count: int | None = None,
) -> None:
    timing = {
        "phase": _clip(str(phase or "unknown"), 120),
        "durationMs": round((time.perf_counter() - started_at) * 1000, 1),
    }
    if count is not None:
        timing["count"] = int(count)
    timings.append(timing)


def _time_memory_overview_step(
    timings: list[dict[str, Any]] | None,
    step: str,
    callback: Callable[[], Any],
    *,
    count: Callable[[Any], int] | None = None,
) -> Any:
    started_at = time.perf_counter()
    result = callback()
    if timings is not None:
        timing = {
            "step": _clip(str(step or "unknown"), 120),
            "durationMs": round((time.perf_counter() - started_at) * 1000, 1),
        }
        try:
            value_count = count(result) if count is not None else _memory_overview_result_count(result)
            if value_count is not None:
                timing["count"] = int(value_count)
        except Exception:
            pass
        timings.append(timing)
    return result


def _memory_overview_result_count(result: Any) -> int | None:
    if isinstance(result, dict):
        for key in ("count", "sessionCount", "fileCount", "knowledgeBaseCount", "itemCount"):
            value = result.get(key)
            if isinstance(value, int):
                return value
        rows = result.get("rows")
        if isinstance(rows, list):
            return len(rows)
    if isinstance(result, (list, tuple, set)):
        return len(result)
    return None


def _normalize_memory_overview_subtimings(timings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [
        {
            key: value
            for key, value in {
                "step": _clip(str(timing.get("step") or "unknown"), 120),
                "durationMs": round(float(timing.get("durationMs") or 0.0), 1),
                "count": timing.get("count") if isinstance(timing.get("count"), int) else None,
            }.items()
            if value is not None
        }
        for timing in timings
        if isinstance(timing, dict)
    ]
    return sorted(normalized, key=lambda timing: float(timing.get("durationMs") or 0.0), reverse=True)[
        :MEMORY_OVERVIEW_SUBTIMING_LIMIT
    ]


def _record_memory_overview_perf_event(
    root: Path,
    overview: dict[str, Any],
    *,
    duration_ms: float,
    section_timings: list[dict[str, Any]] | None = None,
    phase_timings: list[dict[str, Any]] | None = None,
) -> None:
    global MEMORY_OVERVIEW_WAS_SLOW
    slow = duration_ms >= MEMORY_OVERVIEW_SLOW_MS
    recovered = False
    with MEMORY_OVERVIEW_PERF_STATE_LOCK:
        recovered = bool(MEMORY_OVERVIEW_WAS_SLOW and not slow)
        MEMORY_OVERVIEW_WAS_SLOW = slow
    if not slow and not recovered:
        return
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        sections = overview.get("sections") if isinstance(overview.get("sections"), list) else []
        section_metrics = [
            {
                "sectionId": str(section.get("id") or ""),
                "itemCount": len(section.get("items") or []),
            }
            for section in sections
            if isinstance(section, dict)
        ]
        event_code = "memory.overview.slow" if slow else "memory.overview.recovered"
        record_runtime_scene_event(
            "memory_service",
            "performance",
            event_code,
            message=(
                "Memory overview generation exceeded slow threshold"
                if slow
                else "Memory overview generation recovered below slow threshold"
            ),
            level="warning" if slow else "info",
            outcome="observed" if slow else "recovered",
            fields={
                "durationMs": round(float(duration_ms), 1),
                "thresholdMs": MEMORY_OVERVIEW_SLOW_MS,
                "projectRoot": str(root),
                "sectionCount": len(section_metrics),
                "itemCount": int((overview.get("summary") or {}).get("itemCount") or 0),
                "sections": section_metrics,
                "phaseTimingsMs": list(phase_timings or []),
                "sectionTimingsMs": list(section_timings or []),
            },
            lifecycle=True,
        )
    except Exception:
        pass


def _record_memory_overview_prewarm_event(
    *,
    status: str,
    reason: str,
    elapsed_ms: float,
    section_count: int = 0,
    item_count: int = 0,
    error_type: str = "",
    error_message: str = "",
) -> None:
    normalized_status = str(status or "").strip().lower() or "observed"
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "memory_service",
            "performance",
            "memory.overview.prewarm",
            message=(
                "Memory overview cache prewarm failed before the first Memory page request."
                if normalized_status == "failed"
                else "Memory overview cache prewarm completed outside the Memory page request path."
            ),
            level="warning" if normalized_status == "failed" else "info",
            outcome=normalized_status,
            fields={
                "status": normalized_status,
                "reason": _clip(str(reason or "startup"), 120) or "startup",
                "elapsedMs": round(float(elapsed_ms), 1),
                "sectionCount": max(0, int(section_count)),
                "itemCount": max(0, int(item_count)),
                "includeContent": False,
                "cacheWarmup": True,
                "errorType": str(error_type or "").strip(),
                "errorMessage": _clip(str(error_message or ""), 240),
            },
            lifecycle=False,
        )
    except Exception:
        pass


def _record_memory_contract_viewed_event(contract: dict[str, Any], *, cache_hit: bool, duration_ms: float) -> None:
    level = "warning" if duration_ms >= MEMORY_USAGE_CONTRACT_SLOW_MS and not cache_hit else "info"
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "memory_service",
            "memory_contract",
            "memory.usage_contract.viewed",
            message="Memory usage contract viewed",
            level=level,
            outcome="observed",
            fields={
                "cacheHit": cache_hit,
                "durationMs": round(float(duration_ms), 1),
                "cacheTtlSeconds": MEMORY_USAGE_CONTRACT_CACHE_TTL_SECONDS,
                "slowThresholdMs": MEMORY_USAGE_CONTRACT_SLOW_MS,
                "domainCount": len(contract.get("domains") or []),
                "forbiddenActionCount": len(contract.get("forbiddenActions") or []),
                "knowledgeBaseCount": int(((contract.get("currentState") or {}).get("knowledge") or {}).get("knowledgeBaseCount") or 0),
                "formalKnowledgeRequiresReviewer": bool(((contract.get("currentState") or {}).get("operatingBoundary") or {}).get("formalKnowledgeRequiresReviewer")),
            },
            lifecycle=True,
        )
    except Exception:
        pass


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


def _sqlite_table_snapshot(db_path: Path, table: str, *, limit: int = LIST_LIMIT) -> dict[str, Any]:
    if not db_path.exists():
        return {"table": table, "count": 0, "rows": [], "updatedAt": ""}
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            if not _sqlite_table_exists(conn, table):
                return {"table": table, "count": 0, "rows": [], "updatedAt": _mtime(db_path)}
            count_payload = _sqlite_table_count(conn, table)
            order_column = _sqlite_order_column(conn, table)
            order_sql = f' ORDER BY "{order_column}" DESC' if order_column else ""
            rows = conn.execute(f'SELECT * FROM "{table}"{order_sql} LIMIT ?', (max(1, int(limit)),)).fetchall()
            return {
                "table": table,
                "count": count_payload["count"],
                "countExact": count_payload["exact"],
                "rows": [_normalize_sqlite_row(dict(row)) for row in rows],
                "updatedAt": _mtime(db_path),
            }
    except sqlite3.Error as exc:
        return {"table": table, "count": 0, "rows": [], "updatedAt": _mtime(db_path), "error": str(exc)}


def _sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _sqlite_table_count(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    if table in SQLITE_APPEND_ONLY_TABLES:
        approximate_count = _sqlite_autoincrement_sequence(conn, table)
        if approximate_count is None:
            approximate_count = conn.execute(f'SELECT MAX("id") AS count FROM "{table}"').fetchone()["count"]
        return {"count": int(approximate_count or 0), "exact": False}
    count = conn.execute(f'SELECT COUNT(*) AS count FROM "{table}"').fetchone()["count"]
    return {"count": int(count or 0), "exact": True}


def _sqlite_autoincrement_sequence(conn: sqlite3.Connection, table: str) -> int | None:
    if not _sqlite_table_exists(conn, "sqlite_sequence"):
        return None
    row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (table,)).fetchone()
    if row is None:
        return None
    return int(row["seq"] or 0)


def _sqlite_order_column(conn: sqlite3.Connection, table: str) -> str:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    columns = {str(row[1]) for row in rows}
    if table in SQLITE_APPEND_ONLY_TABLES and "id" in columns:
        return "id"
    for candidate in ("updated_at", "last_seen", "created_at", "opened_at", "id"):
        if candidate in columns:
            return candidate
    return ""


def _normalize_sqlite_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, bytes):
            normalized[key] = f"<bytes:{len(value)}>"
        elif isinstance(value, str) and len(value) > 1200:
            normalized[key] = value[:1197].rstrip() + "..."
        else:
            normalized[key] = value
    return normalized


def _git_snapshot(root: Path) -> dict[str, Any]:
    cache_root = str(root.resolve())
    now = time.monotonic()
    with GIT_SNAPSHOT_CACHE_LOCK:
        cached_payload = GIT_SNAPSHOT_CACHE.get("payload")
        if (
            GIT_SNAPSHOT_CACHE.get("root") == cache_root
            and cached_payload is not None
            and float(GIT_SNAPSHOT_CACHE.get("expiresAt") or 0.0) > now
        ):
            return copy.deepcopy(cached_payload)

    payload = _load_git_snapshot(root)
    with GIT_SNAPSHOT_CACHE_LOCK:
        GIT_SNAPSHOT_CACHE.update(
            {
                "root": cache_root,
                "expiresAt": time.monotonic() + GIT_SNAPSHOT_CACHE_TTL_SECONDS,
                "payload": copy.deepcopy(payload),
            }
        )
    return payload


def _clear_git_snapshot_cache() -> None:
    with GIT_SNAPSHOT_CACHE_LOCK:
        GIT_SNAPSHOT_CACHE.update({"root": "", "expiresAt": 0.0, "payload": None})


def _load_git_snapshot(root: Path) -> dict[str, Any]:
    no_window_kwargs = _subprocess_no_window_kwargs()
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain=1"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            **no_window_kwargs,
        )
        head = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            **no_window_kwargs,
        )
    except Exception as exc:
        return {"available": False, "summary": f"Git unavailable: {type(exc).__name__}: {exc}", "files": []}
    if status.returncode != 0:
        return {
            "available": False,
            "summary": (status.stderr or status.stdout or "Git status failed").strip(),
            "files": [],
        }
    files = [
        {"status": line[:2], "path": line[3:]}
        for line in status.stdout.splitlines()
        if len(line) >= 3
    ]
    return {
        "available": True,
        "head": head.stdout.strip() if head.returncode == 0 else "",
        "dirty": bool(files),
        "fileCount": len(files),
        "files": files[:50],
        "truncated": len(files) > 50,
        "summary": "工作区干净" if not files else f"当前工作区有 {len(files)} 个变化文件",
    }


def _subprocess_no_window_kwargs() -> dict[str, int]:
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"creationflags": flags} if flags else {}


def _session_memory_summary(root: Path, session_root: Path) -> dict[str, Any]:
    sessions: list[dict[str, Any]] = []
    if session_root.exists():
        for session_dir in sorted([path for path in session_root.iterdir() if path.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True):
            memory_dir = session_dir / "memory"
            files = sorted(memory_dir.glob("*")) if memory_dir.exists() else []
            sessions.append(
                {
                    "sessionId": session_dir.name,
                    "path": _rel(root, memory_dir),
                    "fileCount": len([path for path in files if path.is_file()]),
                    "updatedAt": _mtime(memory_dir),
                    "files": [
                        {
                            "path": _rel(root, path),
                            "updatedAt": _mtime(path),
                            "sizeBytes": path.stat().st_size if path.exists() and path.is_file() else 0,
                        }
                        for path in files[:8]
                        if path.is_file()
                    ],
                }
            )
    return {
        "sessionCount": len(sessions),
        "updatedAt": _latest_mtime([session_root, *[session_root / item["sessionId"] for item in sessions[:1]]]),
        "sessions": sessions[:LIST_LIMIT],
    }


def _runtime_scene_summary(root: Path, scene_dir: Path) -> dict[str, Any]:
    manifest = _load_json(scene_dir / "manifest.json", fallback={})
    return {
        "id": scene_dir.name,
        "path": _rel(root, scene_dir),
        "title": manifest.get("title") if isinstance(manifest, dict) else "",
        "status": manifest.get("status") if isinstance(manifest, dict) else "",
        "result": manifest.get("result") if isinstance(manifest, dict) else "",
        "startedAt": manifest.get("started_at") if isinstance(manifest, dict) else "",
        "endedAt": manifest.get("ended_at") if isinstance(manifest, dict) else "",
        "updatedAt": _mtime(scene_dir),
    }


def _file_list_payload(root: Path, paths: list[Path]) -> dict[str, Any]:
    return {
        "count": len(paths),
        "files": [
            {
                "path": _rel(root, path),
                "updatedAt": _mtime(path),
                "sizeBytes": path.stat().st_size if path.exists() else 0,
                "summary": _summarize_text(_read_text(path)["content"]),
            }
            for path in paths
        ],
    }


def _latest_files(directory: Path, pattern: str, *, limit: int) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        [path for path in directory.glob(pattern) if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:limit]


def _extract_index_count(text: str, label: str) -> int | None:
    match = re.search(rf"\|\s*{re.escape(label)}\s*\|\s*(\d+)\s*\|", text)
    if not match:
        return None
    return int(match.group(1))


def _summarize_project_memory(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "项目记忆索引不可读。"
    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lanes = payload.get("lanes") if isinstance(payload.get("lanes"), list) else []
    updates = payload.get("recentUpdates") if isinstance(payload.get("recentUpdates"), list) else []
    return (
        f"{project.get('name') or 'Vibelution'}: {summary.get('currentPhase') or '未记录阶段'}；"
        f"{len(lanes)} 条分线，{len(updates)} 条最近更新。"
    )


def _project_memory_recent_update_count(memory_payload: Any, lane_payloads: list[tuple[Path, dict[str, Any]]]) -> int:
    items: list[dict[str, Any]] = []
    if isinstance(memory_payload, dict) and isinstance(memory_payload.get("recentUpdates"), list):
        items.extend(item for item in memory_payload.get("recentUpdates", []) if isinstance(item, dict))
    for _, payload in lane_payloads:
        lane_id = str(payload.get("id") or "")
        lane_title = str(payload.get("title") or "")
        for item in payload.get("recentUpdates") or []:
            if not isinstance(item, dict):
                continue
            lane_item = dict(item)
            lane_item.setdefault("laneId", lane_id)
            lane_item.setdefault("laneTitle", lane_title)
            items.append(lane_item)

    seen: set[tuple[str, str, str, str]] = set()
    for item in items:
        seen.add(
            (
                str(item.get("timestamp", "")),
                str(item.get("title", "")),
                str(item.get("laneId", "")),
                str(item.get("details", "")),
            )
        )
    return len(seen)


def _prompt_file_summary(filename: str, in_prompt: bool) -> str:
    if filename == "STATE_MEMORY.md":
        return "短期状态记忆；当 PromptManager.state_memory 非空时会进入 MEMORY 章节。"
    if filename == "CODEBASE_MAP.md":
        return "代码库地图缓存；只在 CODEBASE_MAP 被判定相关或显式选择时进入 prompt。"
    if filename == "GIT_WORKFLOW.md":
        return "Git 纪律摘要来源；只在 GIT_RULES 条件章节启用时进入 prompt。"
    if in_prompt:
        return "默认运行 prompt 来源。"
    return "动态提示或兼容文件；当前不是默认 prompt 注入项。"


def _summarize_text(text: str) -> str:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return ""
    return _clip(normalized, 240)


def _file_content_summary(path: Path, content: str, *, content_type: str, exists: bool) -> str:
    if not exists:
        return "文件不存在"
    if content_type == "html":
        title = _extract_html_title(content) or path.name
        return f"HTML 页面：{title}。列表只展示页面身份；完整源码可在详情中显式检查。"
    return _summarize_text(content)


def _extract_html_title(content: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", str(content or ""), flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _clip(" ".join(match.group(1).split()), 120)


def _clip(text: str, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix == ".jsonl":
        return "jsonl"
    return "text"


def _item_id(prefix: str, path: Path) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", path.as_posix()).strip("-").lower()
    return f"{prefix}-{slug[-80:] or 'item'}"


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def _mtime(path: Path) -> str:
    try:
        if not path.exists():
            return ""
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
    except OSError:
        return ""


def _latest_mtime(paths: list[Path]) -> str:
    values = [_mtime(path) for path in paths if path]
    values = [value for value in values if value]
    return max(values) if values else ""


def _latest_item_timestamp(items: list[dict[str, Any]]) -> str:
    values = [str(item.get("updatedAt") or "") for item in items if item.get("updatedAt")]
    return max(values) if values else ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
