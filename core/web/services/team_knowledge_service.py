"""Team-scoped knowledge base storage and governance service."""

from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines

from . import agent_directory_service, chat_room_service, team_service
from .runtime_scene_service import record_runtime_scene_event
from .team_knowledge import constants as _tk_constants
from .team_knowledge import search_ranking as _tk_search_ranking
from .team_knowledge import store as _tk_store
from .team_knowledge import permissions as _tk_permissions
from .team_knowledge import source_inbox as _tk_source_inbox
from .team_knowledge import public_catalog as _tk_public_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = _tk_constants.SCHEMA_VERSION
SOURCE_TYPES = _tk_constants.SOURCE_TYPES
INGESTION_ADAPTERS = _tk_constants.INGESTION_ADAPTERS
REVIEW_ROLES = _tk_constants.REVIEW_ROLES
IMPORTANCE_LEVELS = _tk_constants.IMPORTANCE_LEVELS
STABILITY_VALUES = _tk_constants.STABILITY_VALUES
SCOPES = _tk_constants.SCOPES
REVIEW_PRIORITIES = _tk_constants.REVIEW_PRIORITIES
SUGGESTION_STATUSES = _tk_constants.SUGGESTION_STATUSES
KNOWLEDGE_OWNER_TYPES = _tk_constants.KNOWLEDGE_OWNER_TYPES
SOURCE_INBOX_STATUSES = _tk_constants.SOURCE_INBOX_STATUSES
SOURCE_REVIEW_DECISIONS = _tk_constants.SOURCE_REVIEW_DECISIONS
CENTRAL_SOURCE_STATUSES = _tk_constants.CENTRAL_SOURCE_STATUSES
KNOWLEDGE_SEARCH_MODES = _tk_constants.KNOWLEDGE_SEARCH_MODES
MAX_LOCAL_SOURCE_COPIES = _tk_constants.MAX_LOCAL_SOURCE_COPIES
MAX_LOCAL_SOURCE_COPY_BYTES = _tk_constants.MAX_LOCAL_SOURCE_COPY_BYTES
BM25_K1 = _tk_constants.BM25_K1
BM25_B = _tk_constants.BM25_B
_SAFE_ID_FRAGMENT = _tk_constants._SAFE_ID_FRAGMENT
_SEARCH_TOKEN_PATTERN = _tk_constants._SEARCH_TOKEN_PATTERN
_LOCK = threading.RLock()


class TeamKnowledgeError(ValueError):
    """Raised when a team knowledge request is invalid."""


class TeamKnowledgeNotFoundError(TeamKnowledgeError):
    """Raised when a knowledge resource does not exist."""


class TeamKnowledgePermissionError(TeamKnowledgeError):
    """Raised when an actor cannot perform the requested knowledge action."""


class TeamKnowledgeAmbiguousKnowledgeBaseError(TeamKnowledgeError):
    """Raised when an unscoped knowledge base id matches multiple owners."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_knowledge_overview(
    *,
    agent_id: str = "",
    internal: bool = False,
    sync_roots: bool = True,
) -> dict[str, Any]:
    """Return formal knowledge bases visible to an optional Agent.

    ``sync_roots=False`` 供只读投影（提示词渲染等）使用：跳过 ``_sync_roots``
    对兄弟服务 ``PROJECT_ROOT`` 的全局改写，避免只读查询劫持调用方（群聊轮次、
    会话 journal、Agent 目录）已解析的项目根目录。
    """

    if sync_roots:
        _sync_roots()
    visible_bases: list[dict[str, Any]] = []
    pending_proposals = 0
    item_count = 0
    source_count = 0
    for owner in _iter_knowledge_owners(agent_id=agent_id, include_archived=False, include_all_agents=internal):
        for base in _knowledge_bases_for_owner(owner):
            if not _can_access(owner, base, agent_id, "read", internal=internal):
                continue
            stats = _knowledge_base_stats_for_owner(owner, str(base.get("knowledgeBaseId") or ""))
            pending_proposals += stats["pendingProposalCount"]
            item_count += stats["itemCount"]
            source_count += stats["sourceArtifactCount"]
            visible_bases.append(
                {
                    **_knowledge_base_to_api(base, owner),
                    "stats": stats,
                    "pendingProposals": _pending_proposals_for_base(owner, str(base.get("knowledgeBaseId") or "")),
                    "permissions": _permissions_for_actor(owner, base, agent_id, internal=internal),
                }
            )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": str(agent_id or "").strip(),
        "summary": {
            "knowledgeBaseCount": len(visible_bases),
            "pendingProposalCount": pending_proposals,
            "itemCount": item_count,
            "sourceArtifactCount": source_count,
        },
        "knowledgeBases": visible_bases,
        "updatedAt": utc_now_iso(),
    }


def get_knowledge_steward_overview(*, agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    """Return the default knowledge steward Agent and its read-only governance posture."""

    payload = _build_knowledge_steward_overview(agent_id=agent_id, internal=internal)
    _record_event(
        "knowledge.steward.overview.viewed",
        "",
        "",
        actor_agent_id=str((payload.get("steward") or {}).get("agentId") or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID),
        fields={
            "stewardAgentId": str((payload.get("steward") or {}).get("agentId") or ""),
            "openTaskCount": int((payload["governance"]["summary"] or {}).get("openTaskCount") or 0),
            "permissionBoundary": str((payload.get("steward") or {}).get("permissionBoundary") or ""),
        },
    )
    return payload


def _build_knowledge_steward_overview(
    *,
    agent_id: str = "",
    governance_tasks: dict[str, Any] | None = None,
    internal: bool = False,
) -> dict[str, Any]:
    _sync_roots()
    steward = agent_directory_service.get_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID)
    steward_id = str((steward or {}).get("agentId") or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID).strip()
    normalized_agent_id = str(agent_id or "").strip()
    governance_tasks = governance_tasks or list_knowledge_governance_tasks(
        agent_id=normalized_agent_id,
        status="all",
        internal=internal,
    )
    task_summary = dict(governance_tasks.get("summary") or {})
    open_tasks = [task for task in list(governance_tasks.get("tasks") or []) if str(task.get("status") or "") == "open"]
    open_tasks.sort(
        key=lambda item: (
            _priority_rank(str(item.get("priority") or "")),
            str(item.get("updatedAt") or item.get("createdAt") or ""),
        ),
        reverse=True,
    )
    permission_boundary = "governed_stage_writeback_ingestion"
    metadata = dict((steward or {}).get("metadata") or {}) if isinstance((steward or {}).get("metadata"), dict) else {}
    if metadata.get("permissionBoundary"):
        permission_boundary = str(metadata.get("permissionBoundary") or permission_boundary).strip() or permission_boundary
    tool_policy = dict((steward or {}).get("toolPolicy") or {}) if isinstance((steward or {}).get("toolPolicy"), dict) else {}
    memory_policy = dict((steward or {}).get("memoryPolicy") or {}) if isinstance((steward or {}).get("memoryPolicy"), dict) else {}
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "steward": {
            "agentId": steward_id,
            "agentCode": str((steward or {}).get("agentCode") or "").strip(),
            "displayName": str((steward or {}).get("displayName") or "").strip() or "知识库管理员",
            "functionalDisplayName": str(metadata.get("functionalDisplayName") or "知识库管理员").strip(),
            "status": str((steward or {}).get("status") or "missing").strip(),
            "directSessionId": str((steward or {}).get("directSessionId") or "").strip(),
            "directChatPath": f"/chat?session={str((steward or {}).get('directSessionId') or '').strip()}" if str((steward or {}).get("directSessionId") or "").strip() else "/chat",
            "managedDomain": str(metadata.get("managedDomain") or "team_knowledge").strip(),
            "permissionBoundary": permission_boundary,
            "protected": bool(metadata.get("protected")),
            "taskProfile": (steward or {}).get("taskProfile") if isinstance((steward or {}).get("taskProfile"), dict) else {},
            "toolPolicy": {
                "policyId": str(tool_policy.get("policyId") or (steward or {}).get("toolPolicyId") or "").strip(),
                "allowedTools": list(tool_policy.get("allowedTools") or []),
                "preferredTools": list(tool_policy.get("preferredTools") or []),
                "networkAccess": str(tool_policy.get("networkAccess") or "none").strip(),
                "mutationAccess": str(tool_policy.get("mutationAccess") or "restricted").strip(),
                "maxCallsPerTurn": int(tool_policy.get("maxCallsPerTurn") or 0),
            },
            "memoryPolicy": {
                "policyId": str(memory_policy.get("policyId") or (steward or {}).get("memoryPolicyId") or "").strip(),
                "readSharedGroups": list(memory_policy.get("readSharedGroups") or []),
                "writeSharedGroups": list(memory_policy.get("writeSharedGroups") or []),
                "readKnowledgeBaseIds": list(memory_policy.get("readKnowledgeBaseIds") or []),
                "proposeKnowledgeBaseIds": list(memory_policy.get("proposeKnowledgeBaseIds") or []),
                "reviewKnowledgeBaseIds": list(memory_policy.get("reviewKnowledgeBaseIds") or []),
                "rateKnowledgeBaseIds": list(memory_policy.get("rateKnowledgeBaseIds") or []),
            },
        },
        "governance": {
            "summary": {
                **task_summary,
                "openTaskCount": sum(1 for task in list(governance_tasks.get("tasks") or []) if str(task.get("status") or "") == "open"),
            },
            "openTasks": open_tasks[:8],
        },
        "operatingBoundary": {
            "canDirectlyApplyKnowledge": True,
            "canDirectlyIngestScreenedSources": True,
            "canDeleteKnowledge": False,
            "canChangeAcl": False,
            "canBypassReviewer": False,
            "formalKnowledgeRequiresReviewer": False,
            "screeningAgentIsReviewer": True,
            "knowledgeBodiesInPrompt": False,
        },
        "updatedAt": utc_now_iso(),
    }
    return payload


def list_ingestion_adapters() -> dict[str, Any]:
    """Return the standard adapter contract for semi-automatic knowledge ingestion."""

    adapters = [
        {
            "sourceType": source_type,
            **dict(INGESTION_ADAPTERS[source_type]),
            "outputContract": {
                "creates": ["SourceArtifact", "RefinementProposal"],
                "proposalStatus": "pending",
                "createsKnowledgeItem": False,
                "requiresReview": True,
            },
            "directReviewContract": {
                "entrypoint": "owner_source_inbox_review",
                "creates": ["CentralSource", "SourceArtifact", "KnowledgeItem"],
                "createsKnowledgeItem": True,
                "requiresScreening": True,
                "proposalStatus": "not_required",
            },
        }
        for source_type in sorted(INGESTION_ADAPTERS)
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "adapters": adapters,
        "summary": {"adapterCount": len(adapters)},
        "updatedAt": utc_now_iso(),
    }


def list_team_knowledge_bases(team_id: str, *, agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    team = _require_team_identity(team_id) if internal else _require_team(team_id)
    owner = _owner_context("team", team["teamId"], team=team)
    bases = []
    for base in _knowledge_bases_for_owner(owner):
        if _can_access(owner, base, agent_id, "read", internal=internal):
            bases.append(
                {
                    **_knowledge_base_to_api(base, owner),
                    "stats": _knowledge_base_stats_for_owner(owner, str(base.get("knowledgeBaseId") or "")),
                    "pendingProposals": _pending_proposals_for_base(owner, str(base.get("knowledgeBaseId") or "")),
                    "permissions": _permissions_for_actor(owner, base, agent_id, internal=internal),
                }
            )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team["teamId"],
        "knowledgeBases": bases,
        "summary": {"knowledgeBaseCount": len(bases)},
        "updatedAt": utc_now_iso(),
    }


def list_agent_knowledge_bases(agent_id: str, *, actor_agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    agent = _require_agent(agent_id)
    owner = _owner_context("agent", agent["agentId"], agent=agent)
    bases = []
    for base in _knowledge_bases_for_owner(owner):
        if _can_access(owner, base, actor_agent_id, "read", internal=internal):
            bases.append(
                {
                    **_knowledge_base_to_api(base, owner),
                    "stats": _knowledge_base_stats_for_owner(owner, str(base.get("knowledgeBaseId") or "")),
                    "pendingProposals": _pending_proposals_for_base(owner, str(base.get("knowledgeBaseId") or "")),
                    "permissions": _permissions_for_actor(owner, base, actor_agent_id, internal=internal),
                }
            )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": agent["agentId"],
        "knowledgeBases": bases,
        "summary": {"knowledgeBaseCount": len(bases)},
        "updatedAt": utc_now_iso(),
    }


def create_knowledge_base(
    team_id: str,
    *,
    name: str,
    description: str = "",
    actor_agent_id: str = "",
    acl: dict[str, Any] | None = None,
) -> dict[str, Any]:
    team = _require_team(team_id)
    owner = _owner_context("team", team["teamId"], team=team)
    normalized_actor = str(actor_agent_id or "").strip()
    if not normalized_actor:
        raise TeamKnowledgePermissionError("Agent identity is required to create a team knowledge base.")
    if not _member_role(team, normalized_actor):
        raise TeamKnowledgePermissionError("Only Team members can create a team knowledge base.")
    return _create_knowledge_base_for_owner(owner, name=name, description=description, actor_agent_id=normalized_actor, acl=acl)


def get_or_create_team_knowledge_base(
    team_id: str,
    *,
    name: str,
    description: str = "",
    actor_agent_id: str = "",
    reuse_any_existing: bool = False,
    create_if_missing: bool = True,
) -> dict[str, Any]:
    """Resolve a Team knowledge base by name (or any active base) and create it only if missing.

    查重与建库共享同一个 ``_LOCK`` 临界区，关闭 "list 查重 → create" 两段各自拿锁
    之间的 check-then-act 竞态（历史并行 run 曾同时判无同名库，产生
    ``kb-knowledge-expansion-library-2..8`` 八个重复库）。``reuse_any_existing``
    对应旧调用方 "有任何 active 库就复用" 的语义；``create_if_missing=False``
    提供只查不建模式，未命中返回 ``{"knowledgeBase": None, "created": False}``。
    """

    team = _require_team(team_id)
    owner = _owner_context("team", team["teamId"], team=team)
    normalized_actor = str(actor_agent_id or "").strip()
    if not normalized_actor:
        raise TeamKnowledgePermissionError("Agent identity is required to create a team knowledge base.")
    if not _member_role(team, normalized_actor):
        raise TeamKnowledgePermissionError("Only Team members can create a team knowledge base.")
    normalized_name = trim_lines(name or "", max_lines=1).strip()
    if not normalized_name:
        raise TeamKnowledgeError("Knowledge base name is required.")
    with _LOCK:
        state = _load_bases_state_for_owner(owner)
        bases = [item for item in state.get("knowledgeBases") or [] if isinstance(item, dict)]
        target = None
        for item in bases:
            if str(item.get("status") or "active") != "active":
                continue
            if reuse_any_existing or str(item.get("name") or "").strip() == normalized_name:
                target = item
                break
        if target is not None:
            target_id = str(target.get("knowledgeBaseId") or "")
            repaired = _repair_base_for_owner(owner, target)
            return {
                "knowledgeBase": {
                    **_knowledge_base_to_api(repaired, owner),
                    "stats": _knowledge_base_stats_for_owner(owner, target_id),
                    "permissions": _permissions_for_actor(owner, repaired, normalized_actor),
                },
                "created": False,
            }
        if not create_if_missing:
            return {"knowledgeBase": None, "created": False}
        return {
            "knowledgeBase": _create_knowledge_base_for_owner(
                owner,
                name=normalized_name,
                description=description,
                actor_agent_id=normalized_actor,
            ),
            "created": True,
        }


def ensure_knowledge_base_review_grant(knowledge_base_id: str, agent_id: str) -> dict[str, Any]:
    """Idempotently grant one agent review permission on a knowledge base.

    Used by the trusted team knowledge-ingestion gate to honor separation of
    duties: the steward proposes, a distinct coordinator/lead reviews. This only
    extends the per-base ACL review grant for the named agent; it never widens
    the shared REVIEW_ROLES set or any other knowledge base.
    """
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise TeamKnowledgePermissionError("Agent identity is required to grant knowledge base review.")
    owner, base = _require_base_with_owner(knowledge_base_id)
    with _LOCK:
        state = _load_bases_state_for_owner(owner)
        bases = state.get("knowledgeBases") if isinstance(state.get("knowledgeBases"), list) else []
        target = _find_by_id(bases, "knowledgeBaseId", base["knowledgeBaseId"])
        if not target:
            raise TeamKnowledgeNotFoundError("Knowledge base not found.")
        acl = _normalize_acl(target.get("acl"))
        review_grants = list(acl["grants"].get("review") or [])
        if normalized_agent_id not in review_grants:
            review_grants.append(normalized_agent_id)
            acl["grants"]["review"] = _unique_strings(review_grants)
            target["acl"] = acl
            target["updatedAt"] = utc_now_iso()
            _save_bases_state_for_owner(owner, state)
        return dict(target)


def grant_knowledge_base_access(
    knowledge_base_id: str,
    target_agent_id: str,
    *,
    permissions: list[str] | tuple[str, ...],
    actor_agent_id: str,
) -> dict[str, Any]:
    """Grant explicit per-Agent KB permissions through the governed owner ACL."""

    normalized_actor_id = str(actor_agent_id or "").strip()
    if not normalized_actor_id:
        raise TeamKnowledgePermissionError("Current Agent identity is required to grant knowledge base access.")
    target_agent = _require_agent(target_agent_id)
    normalized_target_id = str(target_agent.get("agentId") or "").strip()
    normalized_permissions = _unique_strings(
        str(permission or "").strip().lower()
        for permission in list(permissions or [])
    )
    allowed_permissions = {"read", "propose", "review"}
    unsupported = sorted(set(normalized_permissions).difference(allowed_permissions))
    if unsupported:
        raise TeamKnowledgeError("Unsupported knowledge base permissions: " + ", ".join(unsupported))
    if not normalized_permissions:
        raise TeamKnowledgeError("At least one knowledge base permission is required.")

    owner, base = _require_base_with_owner(knowledge_base_id)
    _require_permission(owner, base, normalized_actor_id, "review")
    changed_permissions: list[str] = []
    with _LOCK:
        state = _load_bases_state_for_owner(owner)
        bases = state.get("knowledgeBases") if isinstance(state.get("knowledgeBases"), list) else []
        target = _find_by_id(bases, "knowledgeBaseId", base["knowledgeBaseId"])
        if not target:
            raise TeamKnowledgeNotFoundError("Knowledge base not found.")
        acl = _normalize_acl(target.get("acl"))
        for permission in normalized_permissions:
            grants = list(acl["grants"].get(permission) or [])
            if normalized_target_id not in grants:
                grants.append(normalized_target_id)
                acl["grants"][permission] = _unique_strings(grants)
                changed_permissions.append(permission)
        if changed_permissions:
            target["acl"] = acl
            target["updatedAt"] = utc_now_iso()
            state["updatedAt"] = target["updatedAt"]
            _save_bases_state_for_owner(owner, state)
            audit_payload = {
                "knowledgeBaseId": base["knowledgeBaseId"],
                "targetAgentId": normalized_target_id,
                "grantedPermissions": changed_permissions,
            }
            _append_audit(
                owner,
                "knowledge_base.access_granted",
                audit_payload,
                actor_agent_id=normalized_actor_id,
            )
        result = dict(target)

    if changed_permissions:
        _record_event(
            "knowledge.knowledge_base.access_granted",
            owner,
            base["knowledgeBaseId"],
            actor_agent_id=normalized_actor_id,
            fields={
                "targetAgentId": normalized_target_id,
                "grantedPermissions": changed_permissions,
            },
        )
    return {
        "knowledgeBase": _knowledge_base_to_api(result, owner),
        "targetAgentId": normalized_target_id,
        "requestedPermissions": normalized_permissions,
        "changedPermissions": changed_permissions,
        "changed": bool(changed_permissions),
    }


def create_agent_knowledge_base(
    agent_id: str,
    *,
    name: str,
    description: str = "",
    actor_agent_id: str = "",
    acl: dict[str, Any] | None = None,
) -> dict[str, Any]:
    agent = _require_agent(agent_id)
    owner = _owner_context("agent", agent["agentId"], agent=agent)
    normalized_actor = str(actor_agent_id or "").strip()
    if not normalized_actor:
        raise TeamKnowledgePermissionError("Agent identity is required to create a private formal knowledge base.")
    if normalized_actor != agent["agentId"]:
        raise TeamKnowledgePermissionError("Only the owning Agent can create its private formal knowledge base.")
    return _create_knowledge_base_for_owner(owner, name=name, description=description, actor_agent_id=normalized_actor, acl=acl)


def _create_knowledge_base_for_owner(
    owner: dict[str, Any],
    *,
    name: str,
    description: str = "",
    actor_agent_id: str = "",
    acl: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_name = trim_lines(name or "", max_lines=1).strip()
    if not normalized_name:
        raise TeamKnowledgeError("Knowledge base name is required.")
    now = utc_now_iso()
    owner_type = str(owner.get("ownerType") or "team")
    owner_id = str(owner.get("ownerId") or "").strip()
    with _LOCK:
        state = _load_bases_state_for_owner(owner)
        existing_ids = {str(item.get("knowledgeBaseId") or "") for item in state.get("knowledgeBases") or []}
        knowledge_base_id = _new_id("kb", existing_ids, normalized_name)
        base = {
            "knowledgeBaseId": knowledge_base_id,
            "ownerType": owner_type,
            "ownerId": owner_id,
            "teamId": owner_id if owner_type == "team" else "",
            "agentId": owner_id if owner_type == "agent" else "",
            "name": normalized_name,
            "description": trim_lines(description or "", max_lines=6).strip(),
            "status": "active",
            "acl": _normalize_acl(acl),
            "createdAt": now,
            "updatedAt": now,
        }
        state.setdefault("knowledgeBases", []).append(base)
        state["updatedAt"] = now
        _save_bases_state_for_owner(owner, state)
        _append_audit(owner, "knowledge_base.created", base, actor_agent_id=actor_agent_id)
    _record_event("knowledge.knowledge_base.created", owner, knowledge_base_id, actor_agent_id=actor_agent_id)
    return {
        **_knowledge_base_to_api(base, owner),
        "stats": _knowledge_base_stats_for_owner(owner, knowledge_base_id),
        "permissions": _permissions_for_actor(owner, base, actor_agent_id),
    }


def knowledge_base_policy_allows(knowledge_base_id: str, policy_ids: set[str] | list[str] | tuple[str, ...]) -> bool:
    """Return whether a tool memoryPolicy allows a raw or owner-scoped knowledge base id."""

    normalized_policy_ids = {str(item or "").strip() for item in list(policy_ids or []) if str(item or "").strip()}
    if not normalized_policy_ids:
        return True
    requested = str(knowledge_base_id or "").strip()
    if not requested:
        return False
    if requested in normalized_policy_ids:
        return True
    owner_type, owner_id, base_id = _parse_owner_scoped_knowledge_base_id(requested)
    has_scoped_policy = any(_parse_owner_scoped_knowledge_base_id(item)[0] for item in normalized_policy_ids)
    if owner_type and owner_id and base_id and base_id in normalized_policy_ids and not has_scoped_policy:
        return True
    return False


def create_source_artifact(
    knowledge_base_id: str,
    *,
    source_type: str,
    source_ref: dict[str, Any] | None = None,
    source_created_at: str = "",
    captured_by: str = "",
    source_hash: str = "",
    evidence_range: dict[str, Any] | None = None,
    title: str = "",
    summary: str = "",
    actor_agent_id: str = "",
    central_source_id: str = "",
    inbox_source_id: str = "",
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    _require_permission(owner, base, actor_agent_id, "propose")
    central_source: dict[str, Any] | None = None
    owner_ref: dict[str, Any] = {}
    normalized_central_source_id = str(central_source_id or "").strip()
    if not normalized_central_source_id:
        raise TeamKnowledgeError("SourceArtifact requires centralSourceId; collect the source to the owner inbox and promote it first.")
    if normalized_central_source_id:
        central_source, owner_ref = _require_central_source_for_owner(
            owner,
            normalized_central_source_id,
            actor_agent_id=actor_agent_id,
        )
    normalized_type = str(source_type or "").strip()
    if not normalized_type and central_source:
        normalized_type = str(central_source.get("sourceType") or "").strip()
    normalized_ref = source_ref if isinstance(source_ref, dict) else {}
    if normalized_type == "team_chat_refinement":
        if str(owner.get("ownerType") or "") != "team":
            raise TeamKnowledgeError("team_chat_refinement sources require a Team knowledge base.")
        _validate_team_chat_source(owner["team"], normalized_ref)
    if central_source:
        central_source_type = str(central_source.get("sourceType") or "").strip()
        if normalized_type != central_source_type:
            raise TeamKnowledgeError("SourceArtifact sourceType must match the central source.")
        central_ref = _bounded_dict(central_source.get("sourceRef") if isinstance(central_source.get("sourceRef"), dict) else {})
        central_ref.update({
            "centralSourceId": central_source["centralSourceId"],
            "centralPath": central_source.get("centralPath") or "",
            "sourceHash": central_source.get("sourceHash") or "",
            "originalOwnerType": owner_ref.get("ownerType") or central_source.get("originOwnerType") or "",
            "originalOwnerId": owner_ref.get("ownerId") or central_source.get("originOwnerId") or "",
            "originalPath": owner_ref.get("originalPath") or central_source.get("originOriginalPath") or "",
        })
        source_ref = central_ref
        source_created_at = str(central_source.get("sourceCreatedAt") or source_created_at or "")
        source_hash = str(central_source.get("sourceHash") or source_hash or "")
    if normalized_type not in SOURCE_TYPES:
        raise TeamKnowledgeError(f"Unsupported source type: {source_type}")
    now = utc_now_iso()
    bounded_ref = _bounded_dict(normalized_ref)
    local_copies = [
        item
        for item in list(normalized_ref.get("localCopies") or (central_source or {}).get("localCopies") or [])
        if isinstance(item, dict)
    ][:MAX_LOCAL_SOURCE_COPIES]
    if local_copies:
        bounded_ref["localCopies"] = local_copies
    artifact = {
        "sourceArtifactId": _new_event_id("src"),
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBaseId": base["knowledgeBaseId"],
        "sourceType": normalized_type,
        "sourceRef": bounded_ref,
        "capturedAt": now,
        "sourceCreatedAt": trim_lines(source_created_at or "", max_lines=1).strip(),
        "capturedBy": trim_lines(captured_by or actor_agent_id or "user", max_lines=1).strip(),
        "sourceHash": trim_lines(source_hash or str((central_source or {}).get("sourceHash") or "") or _source_hash(normalized_ref, title, summary), max_lines=1).strip(),
        "evidenceRange": _bounded_dict(evidence_range if isinstance(evidence_range, dict) else {}),
        "title": trim_lines(title or normalized_type, max_lines=1).strip(),
        "summary": trim_lines(summary or "", max_lines=8).strip(),
        "centralSourceId": normalized_central_source_id,
        "inboxSourceId": trim_lines(inbox_source_id or str(owner_ref.get("inboxSourceId") or ""), max_lines=1).strip(),
        "curationStatus": "central_curated" if normalized_central_source_id else "source_artifact",
    }
    with _LOCK:
        _append_jsonl(_source_artifacts_path_for_owner(owner), artifact)
        _append_audit(owner, "knowledge.source.registered", artifact, actor_agent_id=actor_agent_id)
    _record_event(
        "knowledge.source.registered",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=actor_agent_id,
        fields={"sourceArtifactId": artifact["sourceArtifactId"], "sourceType": artifact["sourceType"]},
    )
    return artifact


def create_refinement_proposal(
    knowledge_base_id: str,
    *,
    source_artifact_ids: list[str] | None,
    proposed_by_agent_id: str = "",
    title: str,
    summary: str = "",
    content: str,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    actor_agent_id = str(proposed_by_agent_id or "").strip()
    _require_permission(owner, base, actor_agent_id, "propose")
    normalized_title = trim_lines(title or "", max_lines=1).strip()
    normalized_content = trim_lines(content or "", max_lines=80).strip()
    if not normalized_title:
        raise TeamKnowledgeError("Proposal title is required.")
    if not normalized_content:
        raise TeamKnowledgeError("Proposal content is required.")
    artifact_ids = _unique_strings(source_artifact_ids or [])
    if not artifact_ids:
        raise TeamKnowledgeError("Formal knowledge proposals require at least one central source artifact.")
    central_source_ids: list[str] = []
    artifacts_by_id = {
        str(item.get("sourceArtifactId") or ""): item
        for item in _source_artifacts_for_base(owner, base["knowledgeBaseId"])
    }
    known_artifacts = set(artifacts_by_id)
    missing = [item for item in artifact_ids if item not in known_artifacts]
    if missing:
        raise TeamKnowledgeError(f"Unknown source artifact ids: {', '.join(missing[:3])}")
    ungoverned = [
        item_id
        for item_id in artifact_ids
        if not str((artifacts_by_id.get(item_id) or {}).get("centralSourceId") or "").strip()
    ]
    if ungoverned:
        raise TeamKnowledgeError("Formal knowledge proposals require central-curated source artifacts.")
    central_source_ids = _unique_strings(
        str((artifacts_by_id.get(item_id) or {}).get("centralSourceId") or "")
        for item_id in artifact_ids
    )
    now = utc_now_iso()
    proposal = {
        "proposalId": _new_event_id("kprop"),
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "targetKnowledgeBaseId": base["knowledgeBaseId"],
        "sourceArtifactIds": artifact_ids,
        "centralSourceIds": central_source_ids,
        "proposedByAgentId": actor_agent_id,
        "status": "pending",
        "title": normalized_title,
        "summary": trim_lines(summary or "", max_lines=6).strip(),
        "content": normalized_content,
        "tags": _unique_strings(tags or [])[:24],
        "createdAt": now,
        "updatedAt": now,
        "reviewedAt": "",
        "reviewedByAgentId": "",
        "resolutionNote": "",
        "batchId": "",
        "knowledgeItemIds": [],
    }
    with _LOCK:
        _append_jsonl(_proposals_path_for_owner(owner), proposal)
        _append_audit(owner, "knowledge.proposal.created", proposal, actor_agent_id=actor_agent_id)
    _record_event(
        "knowledge.proposal.created",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=actor_agent_id,
        fields={"proposalId": proposal["proposalId"], "sourceArtifactCount": len(artifact_ids)},
    )
    return proposal


def create_ingestion_package(
    knowledge_base_id: str,
    *,
    source_type: str,
    source_ref: dict[str, Any] | None = None,
    source_created_at: str = "",
    captured_by: str = "",
    evidence_range: dict[str, Any] | None = None,
    source_title: str = "",
    source_summary: str = "",
    excerpt: str = "",
    proposed_by_agent_id: str = "",
    central_source_id: str = "",
    proposal_title: str = "",
    proposal_summary: str = "",
    proposal_content: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Create one source artifact and one pending proposal from a semi-automatic adapter."""

    owner, base = _require_base_with_owner(knowledge_base_id)
    actor_agent_id = str(proposed_by_agent_id or captured_by or "").strip()
    _require_permission(owner, base, actor_agent_id, "propose")
    normalized_type = str(source_type or "").strip()
    if normalized_type not in SOURCE_TYPES:
        raise TeamKnowledgeError(f"Unsupported source type: {source_type}")
    normalized_excerpt = trim_lines(excerpt or "", max_lines=24).strip()
    normalized_source_summary = trim_lines(source_summary or normalized_excerpt, max_lines=8).strip()
    normalized_proposal_title = trim_lines(proposal_title or source_title or normalized_type, max_lines=1).strip()
    normalized_proposal_summary = trim_lines(proposal_summary or normalized_source_summary, max_lines=6).strip()
    normalized_content = trim_lines(proposal_content or normalized_excerpt or normalized_source_summary, max_lines=80).strip()
    if not normalized_content:
        raise TeamKnowledgeError("Ingestion requires proposalContent, excerpt, or sourceSummary.")
    source = create_source_artifact(
        knowledge_base_id,
        source_type=normalized_type,
        source_ref=source_ref,
        source_created_at=source_created_at,
        captured_by=captured_by or actor_agent_id,
        evidence_range=evidence_range,
        title=source_title or normalized_proposal_title,
        summary=normalized_source_summary,
        actor_agent_id=actor_agent_id,
        central_source_id=central_source_id,
    )
    proposal = create_refinement_proposal(
        knowledge_base_id,
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=actor_agent_id,
        title=normalized_proposal_title,
        summary=normalized_proposal_summary,
        content=normalized_content,
        tags=tags,
    )
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBaseId": base["knowledgeBaseId"],
        "status": "submitted",
        "sourceArtifact": source,
        "proposal": proposal,
        "updatedAt": utc_now_iso(),
    }
    _append_audit(owner, "knowledge.ingestion.adapter.created", proposal, actor_agent_id=actor_agent_id)
    _record_event(
        "knowledge.ingestion.adapter.created",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=actor_agent_id,
        fields={
            "sourceArtifactId": source["sourceArtifactId"],
            "proposalId": proposal["proposalId"],
            "sourceType": normalized_type,
        },
    )
    return payload


def review_refinement_proposal(
    knowledge_base_id: str,
    proposal_id: str,
    *,
    status: str,
    reviewed_by_agent_id: str = "",
    resolution_note: str = "",
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    reviewer_id = str(reviewed_by_agent_id or "").strip()
    _require_permission(owner, base, reviewer_id, "review")
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"approved", "applied", "rejected"}:
        raise TeamKnowledgeError("Review status must be approved, applied, or rejected.")
    with _LOCK:
        proposals = _read_jsonl(_proposals_path_for_owner(owner))
        proposal = _find_by_id(proposals, "proposalId", proposal_id)
        if not proposal or str(proposal.get("targetKnowledgeBaseId") or "") != base["knowledgeBaseId"]:
            raise TeamKnowledgeNotFoundError("Knowledge proposal not found.")
        if str(proposal.get("status") or "") != "pending":
            raise TeamKnowledgeError("Only pending proposals can be reviewed.")
        now = utc_now_iso()
        proposal["status"] = "rejected" if normalized_status == "rejected" else "applied"
        proposal["updatedAt"] = now
        proposal["reviewedAt"] = now
        proposal["reviewedByAgentId"] = reviewer_id
        proposal["resolutionNote"] = trim_lines(resolution_note or "", max_lines=4).strip()
        batch: dict[str, Any] | None = None
        item: dict[str, Any] | None = None
        if proposal["status"] == "applied":
            batch = _batch_from_proposal(owner, base, proposal, reviewer_id, now)
            item = _item_from_proposal(owner, base, proposal, batch, reviewer_id, now)
            proposal["batchId"] = batch["batchId"]
            proposal["knowledgeItemIds"] = [item["knowledgeItemId"]]
            _append_jsonl(_batches_path_for_owner(owner), batch)
            _append_jsonl(_items_path_for_owner(owner), item)
            _append_audit(owner, "knowledge.batch.applied", batch, actor_agent_id=reviewer_id)
        _write_jsonl(_proposals_path_for_owner(owner), proposals)
        _append_audit(owner, "knowledge.proposal.reviewed", proposal, actor_agent_id=reviewer_id)
    _record_event(
        "knowledge.proposal.reviewed",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=reviewer_id,
        fields={"proposalId": proposal["proposalId"], "status": proposal["status"], "batchId": proposal.get("batchId") or ""},
    )
    if batch:
        _record_event(
            "knowledge.batch.applied",
            owner,
            base["knowledgeBaseId"],
            actor_agent_id=reviewer_id,
            fields={"batchId": batch["batchId"], "knowledgeItemCount": 1},
        )
    return {"proposal": proposal, "batch": batch, "item": item}


def list_knowledge_items(knowledge_base_id: str, *, agent_id: str = "") -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    _require_permission(owner, base, agent_id, "read")
    items = [
        item
        for item in _read_jsonl(_items_path_for_owner(owner))
        if str(item.get("knowledgeBaseId") or "") == base["knowledgeBaseId"]
    ]
    items.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBase": _knowledge_base_to_api(base, owner),
        "items": items,
        "summary": {"itemCount": len(items)},
        "updatedAt": utc_now_iso(),
    }


def update_knowledge_item_metadata(
    knowledge_base_id: str,
    knowledge_item_id: str,
    *,
    metadata_patch: dict[str, Any],
    actor_agent_id: str = "",
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    actor_id = str(actor_agent_id or "").strip()
    _require_permission(owner, base, actor_id, "review")
    normalized_item_id = str(knowledge_item_id or "").strip()
    if not normalized_item_id:
        raise TeamKnowledgeError("Knowledge item id is required.")
    if not isinstance(metadata_patch, dict) or not metadata_patch:
        raise TeamKnowledgeError("Knowledge item metadata patch is required.")
    now = utc_now_iso()
    with _LOCK:
        items = _read_jsonl(_items_path_for_owner(owner))
        item = _find_by_id(items, "knowledgeItemId", normalized_item_id)
        if not item or str(item.get("knowledgeBaseId") or "") != base["knowledgeBaseId"]:
            raise TeamKnowledgeNotFoundError("Knowledge item not found.")
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        metadata.update(_bounded_dict(metadata_patch))
        item["metadata"] = metadata
        item["updatedAt"] = now
        _write_jsonl(_items_path_for_owner(owner), items)
        _append_audit(owner, "knowledge.item.metadata.updated", item, actor_agent_id=actor_id)
    _record_event(
        "knowledge.item.metadata.updated",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=actor_id,
        fields={"knowledgeItemId": item["knowledgeItemId"], "metadataKeys": sorted(_bounded_dict(metadata_patch).keys())},
    )
    return item


def list_knowledge_governance_tasks(*, agent_id: str = "", status: str = "open", internal: bool = False) -> dict[str, Any]:
    """Return a reviewer-facing queue derived from proposals, rating suggestions, and source-only evidence."""

    _sync_roots()
    normalized_status = str(status or "open").strip().lower()
    if normalized_status not in {"open", "closed", "all"}:
        raise TeamKnowledgeError(f"Unsupported governance task status: {status}")
    tasks: list[dict[str, Any]] = []
    actor_id = str(agent_id or "").strip()
    for owner in _iter_knowledge_owners(agent_id=actor_id, include_archived=True, include_all_agents=internal):
        for base in _knowledge_bases_for_owner(owner):
            base_id = str(base.get("knowledgeBaseId") or "")
            permissions = _permissions_for_actor(owner, base, actor_id, internal=internal)
            if not permissions["canRead"]:
                continue
            proposals = [
                proposal
                for proposal in _read_jsonl(_proposals_path_for_owner(owner))
                if str(proposal.get("targetKnowledgeBaseId") or "") == base_id
            ]
            proposal_source_ids = {
                source_id
                for proposal in proposals
                for source_id in [str(value or "") for value in list(proposal.get("sourceArtifactIds") or [])]
                if source_id
            }
            for proposal in proposals:
                proposal_status = str(proposal.get("status") or "")
                task_closed = proposal_status != "pending"
                if not _task_status_matches(task_closed, normalized_status):
                    continue
                tasks.append(
                    _governance_task(
                        owner,
                        base,
                        task_type="proposal_review",
                        status="closed" if task_closed else "open",
                        priority="elevated" if not task_closed else "normal",
                        title=str(proposal.get("title") or "Review proposal"),
                        summary=str(proposal.get("summary") or proposal.get("content") or ""),
                        target_id=str(proposal.get("proposalId") or ""),
                        target_status=proposal_status,
                        created_at=str(proposal.get("createdAt") or ""),
                        updated_at=str(proposal.get("updatedAt") or ""),
                        permissions=permissions,
                        source_artifact_ids=[str(value) for value in list(proposal.get("sourceArtifactIds") or []) if str(value or "").strip()],
                    )
                )
            for suggestion in _read_jsonl(_rating_suggestions_path_for_owner(owner)):
                if str(suggestion.get("knowledgeBaseId") or "") != base_id:
                    continue
                suggestion_status = str(suggestion.get("status") or "")
                task_closed = suggestion_status != "pending"
                if not _task_status_matches(task_closed, normalized_status):
                    continue
                tasks.append(
                    _governance_task(
                        owner,
                        base,
                        task_type="rating_review",
                        status="closed" if task_closed else "open",
                        priority=str(suggestion.get("reviewPriority") or "normal"),
                        title=f"{suggestion.get('importanceLevel') or 'medium'} rating suggestion",
                        summary=str(suggestion.get("markingReason") or ""),
                        target_id=str(suggestion.get("suggestionId") or ""),
                        target_status=suggestion_status,
                        created_at=str(suggestion.get("createdAt") or ""),
                        updated_at=str(suggestion.get("updatedAt") or ""),
                        permissions=permissions,
                        source_artifact_ids=[],
                    )
                )
            if normalized_status in {"open", "all"}:
                for artifact in _source_artifacts_for_base(owner, base_id):
                    source_id = str(artifact.get("sourceArtifactId") or "")
                    if source_id in proposal_source_ids:
                        continue
                    tasks.append(
                        _governance_task(
                            owner,
                            base,
                            task_type="source_needs_proposal",
                            status="open",
                            priority="normal",
                            title=str(artifact.get("title") or "Source needs proposal"),
                            summary=str(artifact.get("summary") or ""),
                            target_id=source_id,
                            target_status="source_only",
                            created_at=str(artifact.get("capturedAt") or ""),
                            updated_at=str(artifact.get("capturedAt") or ""),
                            permissions=permissions,
                            source_artifact_ids=[source_id],
                        )
                    )
    tasks.extend(_catalog_governance_tasks(status=normalized_status))
    tasks.sort(key=lambda item: (_priority_rank(str(item.get("priority") or "")), str(item.get("updatedAt") or item.get("createdAt") or "")), reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": actor_id,
        "tasks": tasks,
        "summary": {
            "taskCount": len(tasks),
            "openTaskCount": sum(1 for task in tasks if task.get("status") == "open"),
            "proposalReviewCount": sum(1 for task in tasks if task.get("taskType") == "proposal_review"),
            "ratingReviewCount": sum(1 for task in tasks if task.get("taskType") == "rating_review"),
            "sourceNeedsProposalCount": sum(1 for task in tasks if task.get("taskType") == "source_needs_proposal"),
            "catalogFreshnessCount": sum(1 for task in tasks if task.get("taskType") == "catalog_freshness"),
            "catalogConflictCount": sum(1 for task in tasks if task.get("taskType") == "catalog_conflict"),
            "catalogProposalCount": sum(1 for task in tasks if task.get("taskType") == "catalog_proposal"),
        },
        "updatedAt": utc_now_iso(),
    }


def list_knowledge_steward_recommendations(*, agent_id: str = "", limit: int = 12, internal: bool = False) -> dict[str, Any]:
    """Return read-only steward recommendations derived from open governance tasks."""

    payload = _build_knowledge_steward_recommendations(agent_id=agent_id, limit=limit, internal=internal)
    _record_event(
        "knowledge.steward.recommendations.viewed",
        "",
        "",
        actor_agent_id=str(payload.get("stewardAgentId") or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID),
        fields={
            "agentId": str(payload.get("agentId") or ""),
            "recommendationCount": payload["summary"]["recommendationCount"],
            "visibleRecommendationCount": payload["summary"]["visibleRecommendationCount"],
        },
    )
    return payload


def _build_knowledge_steward_recommendations(
    *,
    agent_id: str = "",
    limit: int = 12,
    tasks_payload: dict[str, Any] | None = None,
    internal: bool = False,
) -> dict[str, Any]:
    _sync_roots()
    steward = agent_directory_service.get_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID)
    steward_id = str((steward or {}).get("agentId") or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID).strip()
    normalized_agent_id = str(agent_id or "").strip()
    bounded_limit = max(1, min(50, int(limit or 12)))
    tasks_payload = tasks_payload or list_knowledge_governance_tasks(agent_id=normalized_agent_id, status="open", internal=internal)
    recommendations = [_steward_recommendation_from_task(task) for task in list(tasks_payload.get("tasks") or [])]
    recommendations.sort(
        key=lambda item: (
            _priority_rank(str(item.get("priority") or "")),
            str(item.get("updatedAt") or item.get("createdAt") or ""),
        ),
        reverse=True,
    )
    visible_recommendations = recommendations[:bounded_limit]
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "stewardAgentId": steward_id,
        "recommendations": visible_recommendations,
        "summary": {
            "recommendationCount": len(recommendations),
            "visibleRecommendationCount": len(visible_recommendations),
            "proposalReviewCount": sum(1 for item in recommendations if item.get("recommendedAction") == "review_proposal"),
            "ratingReviewCount": sum(1 for item in recommendations if item.get("recommendedAction") == "review_rating_suggestion"),
            "proposalDraftCount": sum(1 for item in recommendations if item.get("recommendedAction") == "draft_refinement_proposal"),
        },
        "operatingBoundary": {
            "canDirectlyApplyKnowledge": False,
            "canDeleteKnowledge": False,
            "canChangeAcl": False,
            "canBypassReviewer": False,
            "recommendationsOnly": True,
            "formalKnowledgeRequiresReviewer": True,
        },
        "updatedAt": utc_now_iso(),
    }
    return payload


def get_knowledge_steward_workbench(*, agent_id: str = "", limit: int = 12, internal: bool = False) -> dict[str, Any]:
    """Return the knowledge base admin's consolidated read-only workbench."""

    payload = _build_knowledge_steward_workbench(agent_id=agent_id, limit=limit, internal=internal)
    _record_event(
        "knowledge.steward.workbench.viewed",
        "",
        "",
        actor_agent_id=str((payload.get("steward") or {}).get("agentId") or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID),
        fields={
            "agentId": str(payload.get("agentId") or ""),
            "openTaskCount": int(payload["summary"].get("openTaskCount") or 0),
            "recommendationCount": int(payload["summary"].get("recommendationCount") or 0),
            "stageCount": len(payload.get("stages") or []),
        },
    )
    return payload


def _build_knowledge_steward_workbench(
    *,
    agent_id: str = "",
    limit: int = 12,
    overview: dict[str, Any] | None = None,
    tasks_payload: dict[str, Any] | None = None,
    recommendations_payload: dict[str, Any] | None = None,
    internal: bool = False,
) -> dict[str, Any]:
    _sync_roots()
    normalized_agent_id = str(agent_id or "").strip()
    bounded_limit = max(1, min(50, int(limit or 12)))
    overview = overview or _build_knowledge_steward_overview(agent_id=normalized_agent_id, internal=internal)
    tasks_payload = tasks_payload or list_knowledge_governance_tasks(agent_id=normalized_agent_id, status="open", internal=internal)
    recommendations_payload = recommendations_payload or _build_knowledge_steward_recommendations(
        agent_id=normalized_agent_id,
        limit=bounded_limit,
        tasks_payload=tasks_payload,
        internal=internal,
    )
    recommendations = list(recommendations_payload.get("recommendations") or [])
    tasks = list(tasks_payload.get("tasks") or [])
    stages = [
        _steward_workbench_stage(
            "source_to_proposal",
            "Source evidence to proposal",
            "Turn registered evidence into pending refinement proposals without creating formal knowledge.",
            "draft_refinement_proposal",
            recommendations,
            tasks,
            expected_task_type="source_needs_proposal",
            next_tool="knowledge_ingestion_tool or knowledge_proposal_tool",
        ),
        _steward_workbench_stage(
            "proposal_review",
            "Proposal review",
            "Inspect source evidence and wait for a reviewer-capable Agent to approve or reject proposals.",
            "review_proposal",
            recommendations,
            tasks,
            expected_task_type="proposal_review",
            next_tool="review_refinement_proposal API / UI reviewer action",
        ),
        _steward_workbench_stage(
            "rating_review",
            "Rating review",
            "Confirm or reject importance, confidence, stability, and priority suggestions.",
            "review_rating_suggestion",
            recommendations,
            tasks,
            expected_task_type="rating_review",
            next_tool="rating suggestion review API / UI reviewer action",
        ),
    ]
    next_actions = [
        {
            "actionId": f"next:{item.get('recommendationId') or index}",
            "recommendedAction": str(item.get("recommendedAction") or ""),
            "priority": str(item.get("priority") or "normal"),
            "title": str(item.get("title") or ""),
            "knowledgeBaseId": str(item.get("knowledgeBaseId") or ""),
            "knowledgeBaseName": str(item.get("knowledgeBaseName") or ""),
            "targetId": str(item.get("targetId") or ""),
            "requiresReviewer": bool(item.get("requiresReviewer")),
            "canExecuteWithCurrentActor": bool(item.get("canExecuteWithCurrentActor")),
            "nextStep": str(item.get("nextStep") or ""),
        }
        for index, item in enumerate(recommendations[: min(6, bounded_limit)])
    ]
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "steward": overview.get("steward") or {},
        "summary": {
            **dict(tasks_payload.get("summary") or {}),
            **{
                "recommendationCount": int((recommendations_payload.get("summary") or {}).get("recommendationCount") or 0),
                "visibleRecommendationCount": int((recommendations_payload.get("summary") or {}).get("visibleRecommendationCount") or 0),
                "stageCount": len(stages),
                "blockedStageCount": sum(1 for stage in stages if int(stage.get("openCount") or 0) and not int(stage.get("executableCount") or 0)),
            },
        },
        "stages": stages,
        "nextActions": next_actions,
        "acceptanceChecklist": [
            {"id": "source_registered", "label": "Every candidate keeps SourceArtifact ids and timestamps.", "required": True},
            {"id": "proposal_reviewed", "label": "Formal knowledge is created only after reviewer approval.", "required": True},
            {"id": "rating_reviewed", "label": "Importance and stability marks stay pending until reviewed.", "required": True},
            {"id": "trace_available", "label": "Trace view can reconstruct source -> proposal -> batch/item -> rating.", "required": True},
        ],
        "operatingBoundary": {
            **dict(overview.get("operatingBoundary") or {}),
            "recommendationsOnly": True,
            "canDirectlyApplyKnowledge": False,
            "canDeleteKnowledge": False,
            "canChangeAcl": False,
            "canBypassReviewer": False,
            "formalKnowledgeRequiresReviewer": True,
        },
        "updatedAt": utc_now_iso(),
    }
    return payload


def get_knowledge_trace(knowledge_base_id: str, target_id: str, *, agent_id: str = "") -> dict[str, Any]:
    """Return the source -> proposal -> batch -> item -> rating trail for one knowledge object."""

    owner, base = _require_base_with_owner(knowledge_base_id)
    _require_permission(owner, base, agent_id, "read")
    normalized_target_id = str(target_id or "").strip()
    if not normalized_target_id:
        raise TeamKnowledgeError("Knowledge trace target id is required.")
    artifacts = _source_artifacts_for_base(owner, base["knowledgeBaseId"])
    proposals = [
        proposal
        for proposal in _read_jsonl(_proposals_path_for_owner(owner))
        if str(proposal.get("targetKnowledgeBaseId") or "") == base["knowledgeBaseId"]
    ]
    batches = [
        batch
        for batch in _read_jsonl(_batches_path_for_owner(owner))
        if str(batch.get("knowledgeBaseId") or "") == base["knowledgeBaseId"]
    ]
    items = [
        item
        for item in _read_jsonl(_items_path_for_owner(owner))
        if str(item.get("knowledgeBaseId") or "") == base["knowledgeBaseId"]
    ]
    suggestions = [
        suggestion
        for suggestion in _read_jsonl(_rating_suggestions_path_for_owner(owner))
        if str(suggestion.get("knowledgeBaseId") or "") == base["knowledgeBaseId"]
    ]
    target_type = "unknown"
    source_ids: set[str] = set()
    proposal_ids: set[str] = set()
    batch_ids: set[str] = set()
    item_ids: set[str] = set()
    suggestion_ids: set[str] = set()
    if _find_by_id(items, "knowledgeItemId", normalized_target_id):
        target_type = "knowledge_item"
        item_ids.add(normalized_target_id)
    elif _find_by_id(proposals, "proposalId", normalized_target_id):
        target_type = "proposal"
        proposal_ids.add(normalized_target_id)
    elif _find_by_id(artifacts, "sourceArtifactId", normalized_target_id):
        target_type = "source_artifact"
        source_ids.add(normalized_target_id)
    elif _find_by_id(suggestions, "suggestionId", normalized_target_id):
        target_type = "rating_suggestion"
        suggestion_ids.add(normalized_target_id)
    else:
        raise TeamKnowledgeNotFoundError("Knowledge trace target not found.")

    changed = True
    while changed:
        changed = False
        for item in items:
            item_id = str(item.get("knowledgeItemId") or "")
            if item_id in item_ids:
                if _add_all(source_ids, [str(value or "") for value in list(item.get("sourceArtifactIds") or [])]):
                    changed = True
                if _add_all(batch_ids, [str(item.get("batchId") or "")]):
                    changed = True
            if str(item.get("batchId") or "") in batch_ids and item_id:
                if _add_all(item_ids, [item_id]):
                    changed = True
        for batch in batches:
            batch_id = str(batch.get("batchId") or "")
            if batch_id in batch_ids:
                if _add_all(proposal_ids, [str(value or "") for value in list(batch.get("proposalIds") or [])]):
                    changed = True
                if _add_all(source_ids, [str(value or "") for value in list(batch.get("sourceArtifactIds") or [])]):
                    changed = True
        for proposal in proposals:
            proposal_id = str(proposal.get("proposalId") or "")
            if proposal_id in proposal_ids or any(str(value or "") in source_ids for value in list(proposal.get("sourceArtifactIds") or [])):
                if proposal_id and _add_all(proposal_ids, [proposal_id]):
                    changed = True
                if _add_all(source_ids, [str(value or "") for value in list(proposal.get("sourceArtifactIds") or [])]):
                    changed = True
                if _add_all(batch_ids, [str(proposal.get("batchId") or "")]):
                    changed = True
                if _add_all(item_ids, [str(value or "") for value in list(proposal.get("knowledgeItemIds") or [])]):
                    changed = True
        for suggestion in suggestions:
            suggestion_id = str(suggestion.get("suggestionId") or "")
            if str(suggestion.get("knowledgeItemId") or "") in item_ids or str(suggestion.get("proposalId") or "") in proposal_ids:
                if suggestion_id and _add_all(suggestion_ids, [suggestion_id]):
                    changed = True
                if _add_all(item_ids, [str(suggestion.get("knowledgeItemId") or "")]):
                    changed = True
                if _add_all(proposal_ids, [str(suggestion.get("proposalId") or "")]):
                    changed = True
    nodes = {
        "sourceArtifacts": [item for item in artifacts if str(item.get("sourceArtifactId") or "") in source_ids],
        "proposals": [item for item in proposals if str(item.get("proposalId") or "") in proposal_ids],
        "batches": [item for item in batches if str(item.get("batchId") or "") in batch_ids],
        "items": [item for item in items if str(item.get("knowledgeItemId") or "") in item_ids],
        "ratingSuggestions": [item for item in suggestions if str(item.get("suggestionId") or "") in suggestion_ids],
    }
    local_copies = _local_copies_from_source_artifacts(nodes["sourceArtifacts"])
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBase": _knowledge_base_to_api(base, owner),
        "targetId": normalized_target_id,
        "targetType": target_type,
        "nodes": nodes,
        "localCopies": local_copies,
        "summary": {
            **{key: len(value) for key, value in nodes.items()},
            "localCopyCount": len(local_copies),
        },
        "updatedAt": utc_now_iso(),
    }


def update_knowledge_item_rating(
    knowledge_base_id: str,
    knowledge_item_id: str,
    *,
    actor_agent_id: str = "",
    importance_level: str = "",
    confidence: float | None = None,
    stability: str = "",
    scope: str = "",
    review_priority: str = "",
    marking_reason: str = "",
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    _require_permission(owner, base, actor_agent_id, "review")
    with _LOCK:
        items = _read_jsonl(_items_path_for_owner(owner))
        item = _find_by_id(items, "knowledgeItemId", knowledge_item_id)
        if not item or str(item.get("knowledgeBaseId") or "") != base["knowledgeBaseId"]:
            raise TeamKnowledgeNotFoundError("Knowledge item not found.")
        if importance_level:
            item["importanceLevel"] = _enum_value(importance_level, IMPORTANCE_LEVELS, "importance level")
        if confidence is not None:
            item["confidence"] = max(0.0, min(1.0, float(confidence)))
        if stability:
            item["stability"] = _enum_value(stability, STABILITY_VALUES, "stability")
        if scope:
            item["scope"] = _enum_value(scope, SCOPES, "scope")
        if review_priority:
            item["reviewPriority"] = _enum_value(review_priority, REVIEW_PRIORITIES, "review priority")
        now = utc_now_iso()
        item["markedBy"] = trim_lines(actor_agent_id or "user", max_lines=1).strip()
        item["markedAt"] = now
        item["markingReason"] = trim_lines(marking_reason or "", max_lines=4).strip()
        item["updatedAt"] = now
        _write_jsonl(_items_path_for_owner(owner), items)
        _append_audit(owner, "knowledge.item.rating.updated", item, actor_agent_id=actor_agent_id)
    _record_event(
        "knowledge.item.rating.updated",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=actor_agent_id,
        fields={"knowledgeItemId": item["knowledgeItemId"], "importanceLevel": item.get("importanceLevel")},
    )
    return item


def create_rating_suggestion(
    knowledge_base_id: str,
    *,
    suggested_by_agent_id: str = "",
    target_type: str = "",
    knowledge_item_id: str = "",
    proposal_id: str = "",
    importance_level: str,
    confidence: float | None = None,
    stability: str,
    review_priority: str,
    marking_reason: str = "",
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    suggester_id = str(suggested_by_agent_id or "").strip()
    _require_rating_suggestion_permission(owner, base, suggester_id)
    normalized_target_type = str(target_type or "").strip().lower()
    if normalized_target_type not in {"proposal", "knowledge_item"}:
        raise TeamKnowledgeError("Rating suggestion targetType must be proposal or knowledge_item.")
    normalized_item_id = str(knowledge_item_id or "").strip()
    normalized_proposal_id = str(proposal_id or "").strip()
    if normalized_target_type == "knowledge_item":
        if not normalized_item_id:
            raise TeamKnowledgeError("knowledge_item rating suggestions require knowledgeItemId.")
        _require_item(owner, base["knowledgeBaseId"], normalized_item_id)
    if normalized_target_type == "proposal":
        if not normalized_proposal_id:
            raise TeamKnowledgeError("proposal rating suggestions require proposalId.")
        _require_proposal(owner, base["knowledgeBaseId"], normalized_proposal_id)
    now = utc_now_iso()
    suggestion = {
        "suggestionId": _new_event_id("krate"),
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBaseId": base["knowledgeBaseId"],
        "targetType": normalized_target_type,
        "knowledgeItemId": normalized_item_id,
        "proposalId": normalized_proposal_id,
        "suggestedByAgentId": suggester_id,
        "importanceLevel": _enum_value(importance_level, IMPORTANCE_LEVELS, "importance level"),
        "confidence": max(0.0, min(1.0, float(confidence if confidence is not None else 0.7))),
        "stability": _enum_value(stability, STABILITY_VALUES, "stability"),
        "reviewPriority": _enum_value(review_priority, REVIEW_PRIORITIES, "review priority"),
        "markingReason": trim_lines(marking_reason or "", max_lines=4).strip(),
        "status": "pending",
        "createdAt": now,
        "updatedAt": now,
        "reviewedByAgentId": "",
        "reviewedAt": "",
        "resolutionNote": "",
    }
    with _LOCK:
        _append_jsonl(_rating_suggestions_path_for_owner(owner), suggestion)
        _append_audit(owner, "knowledge.rating.suggested", suggestion, actor_agent_id=suggester_id)
    _record_event(
        "knowledge.rating.suggested",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=suggester_id,
        fields={
            "suggestionId": suggestion["suggestionId"],
            "targetType": suggestion["targetType"],
            "knowledgeItemId": suggestion["knowledgeItemId"],
            "proposalId": suggestion["proposalId"],
        },
    )
    return suggestion


def list_rating_suggestions(knowledge_base_id: str, *, agent_id: str = "", status: str = "") -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    _require_permission(owner, base, agent_id, "read")
    normalized_status = str(status or "").strip().lower()
    if normalized_status and normalized_status not in SUGGESTION_STATUSES:
        raise TeamKnowledgeError(f"Unsupported rating suggestion status: {status}")
    suggestions = [
        item
        for item in _read_jsonl(_rating_suggestions_path_for_owner(owner))
        if str(item.get("knowledgeBaseId") or "") == base["knowledgeBaseId"]
        and (not normalized_status or str(item.get("status") or "") == normalized_status)
    ]
    suggestions.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBase": _knowledge_base_to_api(base, owner),
        "suggestions": suggestions,
        "summary": {
            "suggestionCount": len(suggestions),
            "pendingSuggestionCount": sum(1 for item in suggestions if str(item.get("status") or "") == "pending"),
        },
        "updatedAt": utc_now_iso(),
    }


def review_rating_suggestions_bulk(
    knowledge_base_id: str,
    *,
    suggestion_ids: list[str] | None,
    status: str,
    reviewed_by_agent_id: str = "",
    resolution_note: str = "",
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    reviewer_id = str(reviewed_by_agent_id or "").strip()
    _require_permission(owner, base, reviewer_id, "rate")
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"applied", "rejected"}:
        raise TeamKnowledgeError("Rating suggestion review status must be applied or rejected.")
    normalized_ids = _unique_strings(suggestion_ids or [])
    if not normalized_ids:
        raise TeamKnowledgeError("At least one rating suggestion id is required.")

    reviewed: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    applied_items: list[dict[str, Any]] = []
    now = utc_now_iso()
    with _LOCK:
        suggestions = _read_jsonl(_rating_suggestions_path_for_owner(owner))
        items: list[dict[str, Any]] | None = None
        items_changed = False
        for suggestion_id in normalized_ids:
            suggestion = _find_by_id(suggestions, "suggestionId", suggestion_id)
            if not suggestion or str(suggestion.get("knowledgeBaseId") or "") != base["knowledgeBaseId"]:
                skipped.append({"suggestionId": suggestion_id, "reason": "not_found"})
                continue
            if str(suggestion.get("status") or "") != "pending":
                skipped.append({"suggestionId": suggestion_id, "reason": "not_pending"})
                continue
            applied_item: dict[str, Any] | None = None
            if normalized_status == "applied" and str(suggestion.get("targetType") or "") == "knowledge_item":
                if items is None:
                    items = _read_jsonl(_items_path_for_owner(owner))
                item = _find_by_id(items, "knowledgeItemId", str(suggestion.get("knowledgeItemId") or ""))
                if not item or str(item.get("knowledgeBaseId") or "") != base["knowledgeBaseId"]:
                    skipped.append({"suggestionId": suggestion_id, "reason": "target_not_found"})
                    continue
                item["importanceLevel"] = suggestion["importanceLevel"]
                item["confidence"] = suggestion["confidence"]
                item["stability"] = suggestion["stability"]
                item["reviewPriority"] = suggestion["reviewPriority"]
                item["markedBy"] = reviewer_id
                item["markedAt"] = now
                item["markingReason"] = str(suggestion.get("markingReason") or "")
                item["updatedAt"] = now
                applied_item = item
                applied_items.append(item)
                items_changed = True
                _append_audit(owner, "knowledge.item.rating.updated", item, actor_agent_id=reviewer_id)
            suggestion["status"] = normalized_status
            suggestion["updatedAt"] = now
            suggestion["reviewedAt"] = now
            suggestion["reviewedByAgentId"] = reviewer_id
            suggestion["resolutionNote"] = trim_lines(resolution_note or "", max_lines=4).strip()
            reviewed.append({"suggestion": suggestion, "item": applied_item})
            _append_audit(owner, "knowledge.rating_suggestion.reviewed", suggestion, actor_agent_id=reviewer_id)
        if items is not None and items_changed:
            _write_jsonl(_items_path_for_owner(owner), items)
        _write_jsonl(_rating_suggestions_path_for_owner(owner), suggestions)
        _append_audit(
            owner,
            "knowledge.rating_suggestion.bulk_reviewed",
            {
                "ownerType": owner["ownerType"],
                "ownerId": owner["ownerId"],
                "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
                "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
                "knowledgeBaseId": base["knowledgeBaseId"],
                "status": normalized_status,
                "reviewedCount": len(reviewed),
                "skippedCount": len(skipped),
            },
            actor_agent_id=reviewer_id,
        )
    _record_event(
        "knowledge.rating_suggestion.bulk_reviewed",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=reviewer_id,
        fields={
            "status": normalized_status,
            "reviewedCount": len(reviewed),
            "skippedCount": len(skipped),
        },
    )
    for applied_item in applied_items:
        _record_event(
            "knowledge.item.rating.updated",
            owner,
            base["knowledgeBaseId"],
            actor_agent_id=reviewer_id,
            fields={"knowledgeItemId": applied_item["knowledgeItemId"], "importanceLevel": applied_item.get("importanceLevel")},
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBaseId": base["knowledgeBaseId"],
        "status": normalized_status,
        "reviewed": reviewed,
        "skipped": skipped,
        "summary": {
            "requestedCount": len(normalized_ids),
            "reviewedCount": len(reviewed),
            "skippedCount": len(skipped),
            "appliedItemCount": len(applied_items),
        },
        "updatedAt": utc_now_iso(),
    }


def review_rating_suggestion(
    knowledge_base_id: str,
    suggestion_id: str,
    *,
    status: str,
    reviewed_by_agent_id: str = "",
    resolution_note: str = "",
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    reviewer_id = str(reviewed_by_agent_id or "").strip()
    _require_permission(owner, base, reviewer_id, "rate")
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"applied", "rejected"}:
        raise TeamKnowledgeError("Rating suggestion review status must be applied or rejected.")
    with _LOCK:
        suggestions = _read_jsonl(_rating_suggestions_path_for_owner(owner))
        suggestion = _find_by_id(suggestions, "suggestionId", suggestion_id)
        if not suggestion or str(suggestion.get("knowledgeBaseId") or "") != base["knowledgeBaseId"]:
            raise TeamKnowledgeNotFoundError("Rating suggestion not found.")
        if str(suggestion.get("status") or "") != "pending":
            raise TeamKnowledgeError("Only pending rating suggestions can be reviewed.")
        now = utc_now_iso()
        suggestion["status"] = normalized_status
        suggestion["updatedAt"] = now
        suggestion["reviewedAt"] = now
        suggestion["reviewedByAgentId"] = reviewer_id
        suggestion["resolutionNote"] = trim_lines(resolution_note or "", max_lines=4).strip()
        applied_item: dict[str, Any] | None = None
        if normalized_status == "applied" and str(suggestion.get("targetType") or "") == "knowledge_item":
            items = _read_jsonl(_items_path_for_owner(owner))
            item = _find_by_id(items, "knowledgeItemId", str(suggestion.get("knowledgeItemId") or ""))
            if not item or str(item.get("knowledgeBaseId") or "") != base["knowledgeBaseId"]:
                raise TeamKnowledgeNotFoundError("Knowledge item not found.")
            item["importanceLevel"] = suggestion["importanceLevel"]
            item["confidence"] = suggestion["confidence"]
            item["stability"] = suggestion["stability"]
            item["reviewPriority"] = suggestion["reviewPriority"]
            item["markedBy"] = reviewer_id
            item["markedAt"] = now
            item["markingReason"] = str(suggestion.get("markingReason") or "")
            item["updatedAt"] = now
            applied_item = item
            _write_jsonl(_items_path_for_owner(owner), items)
            _append_audit(owner, "knowledge.item.rating.updated", item, actor_agent_id=reviewer_id)
        _write_jsonl(_rating_suggestions_path_for_owner(owner), suggestions)
        _append_audit(owner, "knowledge.rating_suggestion.reviewed", suggestion, actor_agent_id=reviewer_id)
    _record_event(
        "knowledge.rating_suggestion.reviewed",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=reviewer_id,
        fields={"suggestionId": suggestion["suggestionId"], "status": suggestion["status"]},
    )
    if applied_item:
        _record_event(
            "knowledge.item.rating.updated",
            owner,
            base["knowledgeBaseId"],
            actor_agent_id=reviewer_id,
            fields={"knowledgeItemId": applied_item["knowledgeItemId"], "importanceLevel": applied_item.get("importanceLevel")},
        )
    return {"suggestion": suggestion, "item": applied_item}


def search_knowledge_items(
    *,
    agent_id: str = "",
    query: str = "",
    team_id: str = "",
    owner_type: str = "",
    owner_id: str = "",
    knowledge_base_id: str = "",
    tags: list[str] | None = None,
    source_type: str = "",
    importance_level: str = "",
    confidence_min: float | None = None,
    stability: str = "",
    created_from: str = "",
    created_to: str = "",
    search_mode: str = "exact",
    limit: int = 25,
) -> dict[str, Any]:
    _sync_roots()
    normalized_query = trim_lines(query or "", max_lines=4).strip().lower()
    normalized_team_id = str(team_id or "").strip()
    normalized_owner_type = _normalize_owner_type(owner_type)
    normalized_owner_id = str(owner_id or "").strip()
    scoped_owner_type, scoped_owner_id, normalized_base_id = _parse_owner_scoped_knowledge_base_id(knowledge_base_id)
    normalized_owner_type = normalized_owner_type or scoped_owner_type
    normalized_owner_id = normalized_owner_id or scoped_owner_id
    normalized_tags = {item.lower() for item in _unique_strings(tags or [])}
    normalized_source_type = str(source_type or "").strip()
    if normalized_source_type and normalized_source_type not in SOURCE_TYPES:
        raise TeamKnowledgeError(f"Unsupported source type: {source_type}")
    normalized_importance = _enum_value(importance_level, IMPORTANCE_LEVELS, "importance level") if importance_level else ""
    normalized_stability = _enum_value(stability, STABILITY_VALUES, "stability") if stability else ""
    normalized_search_mode = str(search_mode or "exact").strip().lower()
    if normalized_search_mode not in KNOWLEDGE_SEARCH_MODES:
        raise TeamKnowledgeError(f"Unsupported knowledge search mode: {search_mode}")
    bounded_limit = max(1, min(100, int(limit or 25)))
    score_after_scan = normalized_search_mode == "bm25"
    results: list[dict[str, Any]] = []
    scanned_bases = 0
    owner_candidates = _iter_knowledge_owners(agent_id=agent_id, include_archived=True)
    if normalized_owner_type and normalized_owner_id and not any(
        str(owner.get("ownerType") or "") == normalized_owner_type and str(owner.get("ownerId") or "") == normalized_owner_id
        for owner in owner_candidates
    ):
        owner_candidates.append(_owner_context(normalized_owner_type, normalized_owner_id))
    if normalized_base_id and not (normalized_owner_type and normalized_owner_id):
        visible_matches = [
            owner
            for owner in owner_candidates
            for base in _knowledge_bases_for_owner(owner)
            if str(base.get("knowledgeBaseId") or "") == normalized_base_id
            and _can_access(owner, base, agent_id, "read")
        ]
        unique_owner_keys = {
            (str(owner.get("ownerType") or ""), str(owner.get("ownerId") or ""))
            for owner in visible_matches
        }
        if len(unique_owner_keys) > 1:
            raise TeamKnowledgeAmbiguousKnowledgeBaseError(
                "Knowledge base id is ambiguous across owners; use scopedKnowledgeBaseId."
            )
    for owner in owner_candidates:
        current_owner_type = str(owner.get("ownerType") or "").strip()
        current_owner_id = str(owner.get("ownerId") or "").strip()
        if normalized_owner_type and current_owner_type != normalized_owner_type:
            continue
        if normalized_owner_id and current_owner_id != normalized_owner_id:
            continue
        if normalized_team_id and not (current_owner_type == "team" and current_owner_id == normalized_team_id):
            continue
        for base in _knowledge_bases_for_owner(owner):
            base_id = str(base.get("knowledgeBaseId") or "")
            if normalized_base_id and base_id != normalized_base_id:
                continue
            if not _can_access(owner, base, agent_id, "read"):
                continue
            scanned_bases += 1
            artifacts_by_id = {
                str(item.get("sourceArtifactId") or ""): item
                for item in _source_artifacts_for_base(owner, base_id)
            }
            for item in _read_jsonl(_items_path_for_owner(owner)):
                if str(item.get("knowledgeBaseId") or "") != base_id:
                    continue
                if not _item_matches_filters(
                    item,
                    query="" if score_after_scan else normalized_query,
                    tags=normalized_tags,
                    source_type=normalized_source_type,
                    importance_level=normalized_importance,
                    confidence_min=confidence_min,
                    stability=normalized_stability,
                    created_from=created_from,
                    created_to=created_to,
                    artifacts_by_id=artifacts_by_id,
                    search_mode=normalized_search_mode,
                ):
                    continue
                view = _search_item_view(item, base, owner, artifacts_by_id)
                if score_after_scan:
                    view["semanticScore"] = 1.0 if not normalized_query else 0.0
                    view["searchMode"] = normalized_search_mode
                    view["matchReason"] = "no_query" if not normalized_query else "metadata_filter"
                else:
                    score = _semantic_match_score(view, normalized_query) if normalized_query else 1.0
                    if normalized_query and normalized_search_mode == "semantic" and score <= 0:
                        continue
                    if normalized_query and normalized_search_mode == "hybrid" and score <= 0:
                        haystack = " ".join(
                            [
                                str(view.get("title") or ""),
                                str(view.get("summary") or ""),
                                str(view.get("content") or ""),
                            ]
                        ).lower()
                        if normalized_query not in haystack:
                            continue
                    view["semanticScore"] = score
                    view["searchMode"] = normalized_search_mode
                    view["matchReason"] = _search_match_reason(view, normalized_query, score)
                results.append(view)
                if len(results) >= bounded_limit and not score_after_scan:
                    break
            if len(results) >= bounded_limit and not score_after_scan:
                break
        if len(results) >= bounded_limit and not score_after_scan:
            break
    if score_after_scan:
        results = _rank_bm25_search_results(results, normalized_query)
        if normalized_query:
            results = [item for item in results if float(item.get("semanticScore") or 0.0) > 0]
        results = results[:bounded_limit]
    else:
        results.sort(key=lambda item: (float(item.get("semanticScore") or 0.0), str(item.get("updatedAt") or item.get("createdAt") or "")), reverse=True)
    _record_event(
        "knowledge.search.executed",
        normalized_team_id,
        normalized_base_id,
        actor_agent_id=agent_id,
        fields={"queryLength": len(normalized_query), "resultCount": len(results), "scannedKnowledgeBaseCount": scanned_bases},
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": str(agent_id or "").strip(),
        "filters": {
            "query": normalized_query,
            "teamId": normalized_team_id,
            "ownerType": normalized_owner_type,
            "ownerId": normalized_owner_id,
            "knowledgeBaseId": normalized_base_id,
            "tags": sorted(normalized_tags),
            "sourceType": normalized_source_type,
            "importanceLevel": normalized_importance,
            "confidenceMin": confidence_min,
            "stability": normalized_stability,
            "createdFrom": str(created_from or "").strip(),
            "createdTo": str(created_to or "").strip(),
            "searchMode": normalized_search_mode,
            "limit": bounded_limit,
        },
        "summary": {"resultCount": len(results), "scannedKnowledgeBaseCount": scanned_bases},
        "results": results,
        "updatedAt": utc_now_iso(),
    }


def get_knowledge_operations_health(*, agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    """Return operational health for accessible team knowledge bases."""

    payload = _build_knowledge_operations_health(agent_id=agent_id, internal=internal)
    _record_event(
        "knowledge.operations.health.viewed",
        "",
        "",
        actor_agent_id=str(payload.get("agentId") or ""),
        fields={"knowledgeBaseCount": payload["summary"]["knowledgeBaseCount"], "findingCount": payload["summary"]["findingCount"]},
    )
    return payload


def _build_knowledge_operations_health(*, agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    _sync_roots()
    normalized_agent_id = str(agent_id or "").strip()
    rows: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for owner in _iter_knowledge_owners(agent_id=normalized_agent_id, include_archived=True, include_all_agents=internal):
        for base in _knowledge_bases_for_owner(owner):
            if not _can_access(owner, base, normalized_agent_id, "read", internal=internal):
                continue
            base_id = str(base.get("knowledgeBaseId") or "")
            artifacts = _source_artifacts_for_base(owner, base_id)
            proposals = [
                proposal
                for proposal in _read_jsonl(_proposals_path_for_owner(owner))
                if str(proposal.get("targetKnowledgeBaseId") or "") == base_id
            ]
            items = [
                item
                for item in _read_jsonl(_items_path_for_owner(owner))
                if str(item.get("knowledgeBaseId") or "") == base_id
            ]
            suggestions = [
                suggestion
                for suggestion in _read_jsonl(_rating_suggestions_path_for_owner(owner))
                if str(suggestion.get("knowledgeBaseId") or "") == base_id
            ]
            proposal_source_ids = {
                str(source_id or "")
                for proposal in proposals
                for source_id in list(proposal.get("sourceArtifactIds") or [])
                if str(source_id or "").strip()
            }
            orphan_sources = [item for item in artifacts if str(item.get("sourceArtifactId") or "") not in proposal_source_ids]
            pending_proposals = [item for item in proposals if str(item.get("status") or "") == "pending"]
            pending_suggestions = [item for item in suggestions if str(item.get("status") or "") == "pending"]
            unrated_items = [
                item
                for item in items
                if not str(item.get("markedAt") or "").strip()
                and str(item.get("importanceLevel") or "medium") == "medium"
                and str(item.get("reviewPriority") or "normal") == "normal"
            ]
            health = "ok"
            if pending_proposals or pending_suggestions:
                health = "warning"
            if orphan_sources and not proposals:
                health = "attention"
            row = {
                "ownerType": owner["ownerType"],
                "ownerId": owner["ownerId"],
                "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
                "teamName": str((owner.get("team") or {}).get("name") or ""),
                "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
                "agentName": str((owner.get("agent") or {}).get("displayName") or ""),
                "knowledgeBaseId": base_id,
                "knowledgeBaseName": str(base.get("name") or ""),
                "health": health,
                "counts": {
                    "sourceArtifactCount": len(artifacts),
                    "orphanSourceCount": len(orphan_sources),
                    "proposalCount": len(proposals),
                    "pendingProposalCount": len(pending_proposals),
                    "formalItemCount": len(items),
                    "unratedItemCount": len(unrated_items),
                    "pendingRatingSuggestionCount": len(pending_suggestions),
                },
                "nextReviewTargetIds": [
                    *[str(item.get("proposalId") or "") for item in pending_proposals[:3]],
                    *[str(item.get("suggestionId") or "") for item in pending_suggestions[:3]],
                    *[str(item.get("sourceArtifactId") or "") for item in orphan_sources[:3]],
                ],
            }
            rows.append(row)
            if orphan_sources:
                findings.append(_knowledge_health_finding("orphan_sources", "warning", row, len(orphan_sources), "Registered sources still need refinement proposals."))
            if pending_proposals:
                findings.append(_knowledge_health_finding("pending_proposals", "warning", row, len(pending_proposals), "Pending proposals need reviewer decisions."))
            if pending_suggestions:
                findings.append(_knowledge_health_finding("pending_rating_suggestions", "info", row, len(pending_suggestions), "Rating suggestions are waiting for reviewer confirmation."))
            if unrated_items:
                findings.append(_knowledge_health_finding("unrated_items", "info", row, len(unrated_items), "Formal knowledge items still use default importance metadata."))
    summary = {
        "knowledgeBaseCount": len(rows),
        "attentionCount": sum(1 for row in rows if row["health"] == "attention"),
        "warningCount": sum(1 for row in rows if row["health"] == "warning"),
        "okCount": sum(1 for row in rows if row["health"] == "ok"),
        "findingCount": len(findings),
        "orphanSourceCount": sum(int(row["counts"]["orphanSourceCount"]) for row in rows),
        "pendingProposalCount": sum(int(row["counts"]["pendingProposalCount"]) for row in rows),
        "pendingRatingSuggestionCount": sum(int(row["counts"]["pendingRatingSuggestionCount"]) for row in rows),
        "unratedItemCount": sum(int(row["counts"]["unratedItemCount"]) for row in rows),
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "knowledgeBases": rows,
        "findings": findings,
        "summary": summary,
        "updatedAt": utc_now_iso(),
    }


def get_knowledge_governance_plan(*, agent_id: str = "", limit: int = 12, internal: bool = False) -> dict[str, Any]:
    """Return a read-only governance plan derived from health and steward workbench state."""

    payload = _build_knowledge_governance_plan(agent_id=agent_id, limit=limit, internal=internal)
    _record_event(
        "knowledge.governance.plan.viewed",
        "",
        "",
        actor_agent_id=str(payload.get("agentId") or ""),
        fields={"actionCount": len(payload.get("actions") or []), "healthFindingCount": payload["summary"]["healthFindingCount"]},
    )
    return payload


def _build_knowledge_governance_plan(
    *,
    agent_id: str = "",
    limit: int = 12,
    workbench: dict[str, Any] | None = None,
    health: dict[str, Any] | None = None,
    internal: bool = False,
) -> dict[str, Any]:
    """Build a read-only governance plan, optionally reusing already computed dashboard state."""

    normalized_agent_id = str(agent_id or "").strip()
    bounded_limit = max(1, min(50, int(limit or 12)))
    workbench = workbench or _build_knowledge_steward_workbench(agent_id=normalized_agent_id, limit=bounded_limit, internal=internal)
    health = health or _build_knowledge_operations_health(agent_id=normalized_agent_id, internal=internal)
    actions: list[dict[str, Any]] = []
    for item in list(workbench.get("nextActions") or []):
        actions.append(
            {
                "planActionId": f"plan:{item.get('actionId')}",
                "kind": str(item.get("recommendedAction") or ""),
                "priority": str(item.get("priority") or "normal"),
                "knowledgeBaseId": str(item.get("knowledgeBaseId") or ""),
                "knowledgeBaseName": str(item.get("knowledgeBaseName") or ""),
                "targetId": str(item.get("targetId") or ""),
                "title": str(item.get("title") or ""),
                "recommendedTool": _recommended_tool_for_action(str(item.get("recommendedAction") or "")),
                "nextStep": str(item.get("nextStep") or ""),
                "requiresReviewer": bool(item.get("requiresReviewer")),
                "mutatesFormalKnowledge": False,
            }
        )
    for finding in list(health.get("findings") or []):
        if str(finding.get("findingType") or "") == "unrated_items":
            actions.append(
                {
                    "planActionId": f"plan:{finding.get('findingId')}",
                    "kind": "suggest_rating_metadata",
                    "priority": "normal",
                    "knowledgeBaseId": str(finding.get("knowledgeBaseId") or ""),
                    "knowledgeBaseName": str(finding.get("knowledgeBaseName") or ""),
                    "targetId": "",
                    "title": "Suggest rating metadata for default-marked formal knowledge.",
                    "recommendedTool": "knowledge_rating_suggestion_tool",
                    "nextStep": "Inspect formal items and submit pending rating suggestions for reviewer confirmation.",
                    "requiresReviewer": True,
                    "mutatesFormalKnowledge": False,
                }
            )
    actions = actions[:bounded_limit]
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "mode": "recommendations_only",
        "actions": actions,
        "summary": {
            "actionCount": len(actions),
            "healthFindingCount": int((health.get("summary") or {}).get("findingCount") or 0),
            "workbenchRecommendationCount": int((workbench.get("summary") or {}).get("recommendationCount") or 0),
        },
        "operatingBoundary": {
            "canDirectlyApplyKnowledge": False,
            "canDeleteKnowledge": False,
            "canChangeAcl": False,
            "canBypassReviewer": False,
            "formalKnowledgeRequiresReviewer": True,
            "planOnly": True,
        },
        "updatedAt": utc_now_iso(),
    }
    return payload


def get_knowledge_dashboard_snapshot(
    *,
    agent_id: str = "",
    recommendation_limit: int = 6,
    workbench_limit: int = 8,
    plan_limit: int = 8,
    internal: bool = False,
) -> dict[str, Any]:
    """Return the Memory route's knowledge dashboard state with shared intermediate scans."""

    _sync_roots()
    normalized_agent_id = str(agent_id or "").strip()
    bounded_recommendation_limit = max(1, min(50, int(recommendation_limit or 6)))
    bounded_workbench_limit = max(1, min(50, int(workbench_limit or 8)))
    bounded_plan_limit = max(1, min(50, int(plan_limit or 8)))
    internal_access = bool(internal)
    overview = list_knowledge_overview(agent_id=normalized_agent_id, internal=internal_access)
    governance_tasks_all = list_knowledge_governance_tasks(agent_id=normalized_agent_id, status="all", internal=internal_access)
    governance_tasks_open = list_knowledge_governance_tasks(agent_id=normalized_agent_id, status="open", internal=internal_access)
    steward = _build_knowledge_steward_overview(
        agent_id=normalized_agent_id,
        governance_tasks=governance_tasks_all,
        internal=internal_access,
    )
    recommendations = _build_knowledge_steward_recommendations(
        agent_id=normalized_agent_id,
        limit=bounded_recommendation_limit,
        tasks_payload=governance_tasks_open,
        internal=internal_access,
    )
    workbench_recommendations = (
        recommendations
        if bounded_workbench_limit == bounded_recommendation_limit
        else _build_knowledge_steward_recommendations(
            agent_id=normalized_agent_id,
            limit=bounded_workbench_limit,
            tasks_payload=governance_tasks_open,
            internal=internal_access,
        )
    )
    workbench = _build_knowledge_steward_workbench(
        agent_id=normalized_agent_id,
        limit=bounded_workbench_limit,
        overview=steward,
        tasks_payload=governance_tasks_open,
        recommendations_payload=workbench_recommendations,
        internal=internal_access,
    )
    health = _build_knowledge_operations_health(agent_id=normalized_agent_id, internal=internal_access)
    governance_plan = _build_knowledge_governance_plan(
        agent_id=normalized_agent_id,
        limit=bounded_plan_limit,
        workbench=workbench,
        health=health,
        internal=internal_access,
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "overview": overview,
        "steward": steward,
        "recommendations": recommendations,
        "workbench": workbench,
        "operationsHealth": health,
        "governancePlan": governance_plan,
        "updatedAt": utc_now_iso(),
    }


def knowledge_permission_audit(*, agent_id: str = "") -> dict[str, Any]:
    _sync_roots()
    normalized_agent_id = str(agent_id or "").strip()
    try:
        from core.web.services import agent_directory_service

        memory_policy = agent_directory_service.resolve_memory_policy_for_agent(normalized_agent_id) if normalized_agent_id else {}
    except Exception:
        memory_policy = {}
    read_policy = set(_unique_strings(memory_policy.get("readKnowledgeBaseIds") or []))
    propose_policy = set(_unique_strings(memory_policy.get("proposeKnowledgeBaseIds") or []))
    review_policy = set(_unique_strings(memory_policy.get("reviewKnowledgeBaseIds") or []))
    rate_policy = set(_unique_strings(memory_policy.get("rateKnowledgeBaseIds") or []))
    rows: list[dict[str, Any]] = []
    for owner in _iter_knowledge_owners(agent_id=normalized_agent_id, include_archived=True):
        team = owner.get("team") if isinstance(owner.get("team"), dict) else {}
        agent = owner.get("agent") if isinstance(owner.get("agent"), dict) else {}
        role = _member_role(team, normalized_agent_id) if normalized_agent_id and owner["ownerType"] == "team" else ""
        for base in _knowledge_bases_for_owner(owner):
            base_id = str(base.get("knowledgeBaseId") or "")
            rows.append(
                {
                    "ownerType": owner["ownerType"],
                    "ownerId": owner["ownerId"],
                    "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
                    "teamName": str(team.get("name") or ""),
                    "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
                    "agentName": str(agent.get("displayName") or agent.get("agentCode") or ""),
                    "knowledgeBaseId": base_id,
                    "knowledgeBaseName": str(base.get("name") or ""),
                    "teamRole": role,
                    "permissions": {
                        "read": _permission_explain(owner, base, normalized_agent_id, "read", read_policy),
                        "propose": _permission_explain(owner, base, normalized_agent_id, "propose", propose_policy),
                        "review": _permission_explain(owner, base, normalized_agent_id, "review", review_policy),
                        "rate": _permission_explain(owner, base, normalized_agent_id, "rate", rate_policy),
                    },
                }
            )
    tools = {
        name: {
            "toolName": name,
            "visible": True,
            "allowedByToolPolicy": True,
            "blockedByToolPolicy": False,
            "reason": "available",
        }
        for name in ("unified_memory_search_tool", "knowledge_proposal_tool", "knowledge_rating_suggestion_tool")
    }
    _record_event(
        "knowledge.permission.audit.viewed",
        "",
        "",
        actor_agent_id=normalized_agent_id,
        fields={"knowledgeBaseCount": len(rows), "visibleToolCount": sum(1 for item in tools.values() if item["visible"])},
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "tools": tools,
        "knowledgeBases": rows,
        "summary": {
            "knowledgeBaseCount": len(rows),
            "readableCount": sum(1 for row in rows if row["permissions"]["read"]["allowed"]),
            "proposableCount": sum(1 for row in rows if row["permissions"]["propose"]["allowed"]),
            "reviewableCount": sum(1 for row in rows if row["permissions"]["review"]["allowed"]),
            "rateableCount": sum(1 for row in rows if row["permissions"]["rate"]["allowed"]),
        },
        "updatedAt": utc_now_iso(),
    }


def get_agent_memory_readiness_report(*, agent_id: str = "") -> dict[str, Any]:
    """Report whether active Agents can practically read governed memory."""

    payload = _build_agent_memory_readiness_report(agent_id=agent_id)
    _record_event(
        "knowledge.agent_memory_readiness.viewed",
        "",
        "",
        actor_agent_id=str(payload.get("agentId") or ""),
        fields={
            "agentCount": int((payload.get("summary") or {}).get("agentCount") or 0),
            "unifiedToolAgentCount": int((payload.get("summary") or {}).get("unifiedMemorySearchToolAgentCount") or 0),
            "visibleKnowledgeBaseCount": int((payload.get("summary") or {}).get("visibleKnowledgeBaseCount") or 0),
        },
    )
    return payload


def _build_agent_memory_readiness_report(*, agent_id: str = "") -> dict[str, Any]:
    _sync_roots()
    normalized_agent_id = str(agent_id or "").strip()
    try:
        agents = agent_directory_service.list_agents(include_archived=False)
    except Exception:
        agents = []
    rows: list[dict[str, Any]] = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        row = _agent_memory_readiness_row(agent)
        if row:
            rows.append(row)
    rows.sort(key=lambda item: (str(item.get("primaryMode") or ""), str(item.get("displayName") or ""), str(item.get("agentId") or "")))
    summary = {
        "agentCount": len(rows),
        "unifiedMemorySearchToolAgentCount": sum(1 for row in rows if row["memorySearch"]["hasUnifiedMemorySearchTool"]),
        "legacyResearchKnowledgeToolAgentCount": sum(1 for row in rows if row["memorySearch"]["hasResearchKnowledgeQueryTool"]),
        "runtimeMemorySearchToolAgentCount": sum(1 for row in rows if row["memorySearch"]["hasSearchMemoryTool"]),
        "skillLibrarySearchToolAgentCount": sum(1 for row in rows if row["memorySearch"]["hasSkillLibrarySearchTool"]),
        "agentsWithVisibleKnowledgeBaseCount": sum(1 for row in rows if int(row["formalKnowledge"]["visibleKnowledgeBaseCount"]) > 0),
        "visibleKnowledgeBaseCount": sum(int(row["formalKnowledge"]["visibleKnowledgeBaseCount"]) for row in rows),
        "visibleKnowledgeItemCount": sum(int(row["formalKnowledge"]["visibleKnowledgeItemCount"]) for row in rows),
        "visibleSourceArtifactCount": sum(int(row["formalKnowledge"]["visibleSourceArtifactCount"]) for row in rows),
        "missingUnifiedMemorySearchToolCount": sum(1 for row in rows if not row["memorySearch"]["hasUnifiedMemorySearchTool"]),
        "formalKnowledgeEmptyAgentCount": sum(1 for row in rows if int(row["formalKnowledge"]["visibleKnowledgeBaseCount"]) == 0),
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "operatingBoundary": {
            "readOnly": True,
            "mutatesFormalKnowledge": False,
            "includesFormalKnowledgeBodies": False,
            "usesTeamKnowledgeAcl": True,
            "honorsMemoryPolicy": True,
            "countsOnly": True,
        },
        "summary": summary,
        "agents": rows,
        "recommendations": _agent_memory_readiness_recommendations(summary),
        "updatedAt": utc_now_iso(),
    }


def _agent_memory_readiness_row(agent: dict[str, Any]) -> dict[str, Any]:
    agent_id_value = str(agent.get("agentId") or "").strip()
    if not agent_id_value:
        return {}
    try:
        tool_policy = agent.get("toolPolicy") if isinstance(agent.get("toolPolicy"), dict) else agent_directory_service.resolve_tool_policy_for_agent(agent_id_value)
    except Exception:
        tool_policy = {}
    try:
        memory_policy = agent.get("memoryPolicy") if isinstance(agent.get("memoryPolicy"), dict) else agent_directory_service.resolve_memory_policy_for_agent(agent_id_value)
    except Exception:
        memory_policy = {}
    allowed_tools = _unique_strings((tool_policy or {}).get("allowedTools") or [])
    preferred_tools = _unique_strings((tool_policy or {}).get("preferredTools") or [])
    allowed_set = set(allowed_tools)
    preferred_set = set(preferred_tools)
    search_tool_priority = (
        "unified_memory_search_tool",
        "skill_library_search_tool",
        "research_knowledge_query_tool",
        "search_memory_tool",
    )
    primary_search_tool = next((tool for tool in preferred_tools if tool in search_tool_priority), "")
    if not primary_search_tool:
        primary_search_tool = next((tool for tool in search_tool_priority if tool in allowed_set), "")
    formal_visibility = _agent_formal_knowledge_visibility(agent_id_value, memory_policy if isinstance(memory_policy, dict) else {})
    has_unified = "unified_memory_search_tool" in allowed_set
    readiness_status = "ready"
    if not has_unified:
        readiness_status = "missing_unified_memory_search_tool"
    elif int(formal_visibility["visibleKnowledgeBaseCount"]) == 0:
        readiness_status = "tool_ready_no_visible_formal_knowledge"
    return {
        "agentId": agent_id_value,
        "agentCode": str(agent.get("agentCode") or ""),
        "displayName": str(agent.get("displayName") or ""),
        "primaryMode": str(agent.get("primaryMode") or ""),
        "roleKey": str(agent.get("roleKey") or ""),
        "status": str(agent.get("status") or ""),
        "toolPolicyId": str((tool_policy or {}).get("policyId") or agent.get("toolPolicyId") or ""),
        "memoryPolicyId": str((memory_policy or {}).get("policyId") or agent.get("memoryPolicyId") or ""),
        "readinessStatus": readiness_status,
        "memorySearch": {
            "hasUnifiedMemorySearchTool": has_unified,
            "hasResearchKnowledgeQueryTool": "research_knowledge_query_tool" in allowed_set,
            "hasSearchMemoryTool": "search_memory_tool" in allowed_set,
            "hasSkillLibrarySearchTool": "skill_library_search_tool" in allowed_set,
            "unifiedMemorySearchPreferred": "unified_memory_search_tool" in preferred_set,
            "primarySearchTool": primary_search_tool,
            "allowedSearchTools": [tool for tool in search_tool_priority if tool in allowed_set],
            "preferredSearchTools": [tool for tool in preferred_tools if tool in search_tool_priority],
        },
        "formalKnowledge": formal_visibility,
    }


def _agent_formal_knowledge_visibility(agent_id: str, memory_policy: dict[str, Any]) -> dict[str, Any]:
    read_policy = set(_unique_strings((memory_policy or {}).get("readKnowledgeBaseIds") or []))
    visible_bases: list[dict[str, Any]] = []
    item_count = 0
    source_artifact_count = 0
    for owner in _iter_knowledge_owners(agent_id=agent_id, include_archived=True):
        for base in _knowledge_bases_for_owner(owner):
            base_id = str(base.get("knowledgeBaseId") or "").strip()
            if not base_id:
                continue
            scoped_base_id = _owner_scoped_knowledge_base_id(owner, base_id)
            if not knowledge_base_policy_allows(scoped_base_id, read_policy):
                continue
            if not _can_access(owner, base, agent_id, "read"):
                continue
            owner_items = [
                item
                for item in _read_jsonl(_items_path_for_owner(owner))
                if str(item.get("knowledgeBaseId") or "").strip() == base_id
            ]
            owner_artifacts = _source_artifacts_for_base(owner, base_id)
            item_count += len(owner_items)
            source_artifact_count += len(owner_artifacts)
            visible_bases.append(
                {
                    "ownerType": owner["ownerType"],
                    "ownerId": owner["ownerId"],
                    "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
                    "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
                    "knowledgeBaseId": base_id,
                    "scopedKnowledgeBaseId": scoped_base_id,
                    "knowledgeBaseName": str(base.get("name") or ""),
                    "itemCount": len(owner_items),
                    "sourceArtifactCount": len(owner_artifacts),
                }
            )
    return {
        "effectiveReadScope": "explicit_memory_policy" if read_policy else "team_membership_and_owner_acl",
        "readKnowledgeBaseIdCount": len(read_policy),
        "visibleKnowledgeBaseCount": len(visible_bases),
        "visibleKnowledgeItemCount": item_count,
        "visibleSourceArtifactCount": source_artifact_count,
        "knowledgeBases": visible_bases[:20],
    }


def _agent_memory_readiness_recommendations(summary: dict[str, Any]) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    if int(summary.get("missingUnifiedMemorySearchToolCount") or 0) > 0:
        recommendations.append(
            {
                "recommendationId": "agent_memory_tool_policy_unified_search",
                "severity": "warning",
                "title": "Some active Agents cannot use unified memory search.",
                "nextStep": "Repair their role tool profiles or explicit ToolPolicy.allowedTools to include unified_memory_search_tool.",
            }
        )
    if int(summary.get("formalKnowledgeEmptyAgentCount") or 0) > 0:
        recommendations.append(
            {
                "recommendationId": "agent_memory_formal_knowledge_empty",
                "severity": "info",
                "title": "Some Agents have no visible formal knowledge bases.",
                "nextStep": "Create owner-scoped Agent/Team knowledge bases or attach the Agent to a Team with governed memory.",
            }
        )
    return recommendations


def team_knowledge_memory_section_summary() -> dict[str, Any]:
    """Return a lightweight summary for /api/memory/overview."""

    overview = _lightweight_knowledge_memory_summary()
    return {
        "knowledgeBaseCount": int((overview.get("summary") or {}).get("knowledgeBaseCount") or 0),
        "pendingProposalCount": int((overview.get("summary") or {}).get("pendingProposalCount") or 0),
        "itemCount": int((overview.get("summary") or {}).get("itemCount") or 0),
        "sourceArtifactCount": int((overview.get("summary") or {}).get("sourceArtifactCount") or 0),
        "updatedAt": str(overview.get("updatedAt") or ""),
    }


def _lightweight_knowledge_memory_summary() -> dict[str, Any]:
    """Count knowledge artifacts without expanding owners, permissions, or proposal payloads."""

    knowledge_base_count = 0
    pending_proposal_count = 0
    item_count = 0
    source_artifact_count = 0
    updated_at = ""
    for root in _iter_existing_knowledge_roots():
        bases_state = _load_knowledge_bases_state_from_path(root / "knowledge_bases.json")
        base_ids = {
            str(item.get("knowledgeBaseId") or "").strip()
            for item in list(bases_state.get("knowledgeBases") or [])
            if isinstance(item, dict) and str(item.get("knowledgeBaseId") or "").strip()
        }
        knowledge_base_count += len(base_ids)
        updated_at = max(updated_at, str(bases_state.get("updatedAt") or ""))
        if not base_ids:
            continue
        for item in _read_jsonl(root / "items.jsonl"):
            if str(item.get("knowledgeBaseId") or "") in base_ids:
                item_count += 1
                updated_at = max(updated_at, str(item.get("updatedAt") or item.get("createdAt") or ""))
        for item in _read_jsonl(root / "source_artifacts.jsonl"):
            if str(item.get("knowledgeBaseId") or "") in base_ids:
                source_artifact_count += 1
                updated_at = max(updated_at, str(item.get("updatedAt") or item.get("createdAt") or ""))
        for item in _read_jsonl(root / "refinement_proposals.jsonl"):
            if str(item.get("targetKnowledgeBaseId") or "") not in base_ids:
                continue
            updated_at = max(updated_at, str(item.get("updatedAt") or item.get("createdAt") or ""))
            if str(item.get("status") or "") == "pending":
                pending_proposal_count += 1

    return {
        "schemaVersion": SCHEMA_VERSION,
        "summary": {
            "knowledgeBaseCount": knowledge_base_count,
            "pendingProposalCount": pending_proposal_count,
            "itemCount": item_count,
            "sourceArtifactCount": source_artifact_count,
        },
        "updatedAt": updated_at or utc_now_iso(),
    }


def _require_base_with_owner(knowledge_base_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    owner_type, owner_id, normalized_id = _parse_owner_scoped_knowledge_base_id(knowledge_base_id)
    if not normalized_id:
        raise TeamKnowledgeError("Knowledge base id is required.")
    _sync_roots()
    if owner_type and owner_id:
        owner = _owner_context(owner_type, owner_id)
        base = _find_knowledge_base_for_owner(owner, normalized_id)
        if base:
            return owner, base
        raise TeamKnowledgeNotFoundError("Knowledge base not found.")
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for owner in _iter_knowledge_owners(agent_id="", include_archived=True, include_all_agents=True):
        base = _find_knowledge_base_for_owner(owner, normalized_id)
        if base:
            matches.append((owner, base))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise TeamKnowledgeAmbiguousKnowledgeBaseError(
            "Knowledge base id is ambiguous across owners; use scopedKnowledgeBaseId."
        )
    raise TeamKnowledgeNotFoundError("Knowledge base not found.")


def _require_base_with_team(knowledge_base_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    if str(owner.get("ownerType") or "") != "team":
        raise TeamKnowledgeNotFoundError("Team knowledge base not found.")
    return dict(owner.get("team") or {}), base


def _require_team(team_id: str) -> dict[str, Any]:
    _sync_roots()
    try:
        return team_service.get_team(team_id)
    except team_service.TeamNotFoundError as exc:
        raise TeamKnowledgeNotFoundError("Team not found.") from exc
    except team_service.TeamServiceError as exc:
        raise TeamKnowledgeError(str(exc)) from exc


def _require_team_identity(team_id: str) -> dict[str, Any]:
    _sync_roots()
    try:
        normalized_team_id = team_service.assert_team_exists(team_id)
    except team_service.TeamNotFoundError as exc:
        raise TeamKnowledgeNotFoundError("Team not found.") from exc
    except team_service.TeamServiceError as exc:
        raise TeamKnowledgeError(str(exc)) from exc
    return {"teamId": normalized_team_id, "name": ""}


def _require_agent(agent_id: str) -> dict[str, Any]:
    _sync_roots()
    normalized_id = str(agent_id or "").strip()
    if not normalized_id:
        raise TeamKnowledgeError("Agent id is required.")
    agent = agent_directory_service.get_agent(normalized_id)
    if not agent:
        raise TeamKnowledgeNotFoundError("Agent not found.")
    return agent


def _require_owner_context(owner_type: str, owner_id: str) -> dict[str, Any]:
    normalized_type = _normalize_owner_type(owner_type)
    normalized_id = str(owner_id or "").strip()
    if not normalized_id:
        raise TeamKnowledgeError("Owner id is required.")
    if normalized_type == "team":
        return _owner_context("team", normalized_id, team=_require_team(normalized_id))
    if normalized_type == "agent":
        return _owner_context("agent", normalized_id, agent=_require_agent(normalized_id))
    raise TeamKnowledgeError("Owner type is required.")


def _knowledge_base_to_api(base: dict[str, Any], owner_value: dict[str, Any]) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    owner_type = str(base.get("ownerType") or owner.get("ownerType") or "team").strip() or "team"
    owner_id = str(base.get("ownerId") or owner.get("ownerId") or base.get("teamId") or "").strip()
    team = owner.get("team") if isinstance(owner.get("team"), dict) else {}
    agent = owner.get("agent") if isinstance(owner.get("agent"), dict) else {}
    scoped_id = _owner_scoped_knowledge_base_id(owner, str(base.get("knowledgeBaseId") or ""))
    return {
        "knowledgeBaseId": str(base.get("knowledgeBaseId") or "").strip(),
        "scopedKnowledgeBaseId": scoped_id,
        "ownerType": owner_type,
        "ownerId": owner_id,
        "teamId": str(base.get("teamId") or (owner_id if owner_type == "team" else "")).strip(),
        "teamName": str(team.get("name") or "").strip(),
        "agentId": str(base.get("agentId") or (owner_id if owner_type == "agent" else "")).strip(),
        "agentName": str(agent.get("displayName") or agent.get("agentCode") or "").strip(),
        "name": str(base.get("name") or "").strip(),
        "description": str(base.get("description") or "").strip(),
        "status": str(base.get("status") or "active").strip(),
        "acl": _normalize_acl(base.get("acl") if isinstance(base.get("acl"), dict) else {}),
        "createdAt": str(base.get("createdAt") or "").strip(),
        "updatedAt": str(base.get("updatedAt") or "").strip(),
    }


def _knowledge_base_stats_for_owner(owner_value: Any, knowledge_base_id: str) -> dict[str, int]:
    owner = _coerce_owner_context(owner_value)
    proposals = [
        item
        for item in _read_jsonl(_proposals_path_for_owner(owner))
        if str(item.get("targetKnowledgeBaseId") or "") == knowledge_base_id
    ]
    return {
        "sourceArtifactCount": len(_source_artifacts_for_base(owner, knowledge_base_id)),
        "pendingProposalCount": sum(1 for item in proposals if str(item.get("status") or "") == "pending"),
        "proposalCount": len(proposals),
        "itemCount": sum(
            1
            for item in _read_jsonl(_items_path_for_owner(owner))
            if str(item.get("knowledgeBaseId") or "") == knowledge_base_id
        ),
        "batchCount": sum(
            1
            for item in _read_jsonl(_batches_path_for_owner(owner))
            if str(item.get("knowledgeBaseId") or "") == knowledge_base_id
        ),
    }


def _knowledge_base_stats(team_id: str, knowledge_base_id: str) -> dict[str, int]:
    return _knowledge_base_stats_for_owner(_owner_context("team", team_id), knowledge_base_id)


def _pending_proposals_for_base(owner_value: Any, knowledge_base_id: str) -> list[dict[str, Any]]:
    owner = _coerce_owner_context(owner_value)
    proposals = [
        item
        for item in _read_jsonl(_proposals_path_for_owner(owner))
        if str(item.get("targetKnowledgeBaseId") or "") == knowledge_base_id and str(item.get("status") or "") == "pending"
    ]
    proposals.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    return proposals[:12]


def _validate_team_chat_source(team: dict[str, Any], source_ref: dict[str, Any]) -> None:
    room_id = str(source_ref.get("roomId") or "").strip()
    if not room_id:
        raise TeamKnowledgeError("team_chat_refinement requires sourceRef.roomId.")
    if not (source_ref.get("messageRange") or source_ref.get("roundId")):
        raise TeamKnowledgeError("team_chat_refinement requires sourceRef.messageRange or sourceRef.roundId.")
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    if room_id == linked_room_id:
        return
    room = chat_room_service.get_chat_room_detail(room_id)
    config = room.get("config") if isinstance(room, dict) and isinstance(room.get("config"), dict) else {}
    if str(config.get("source") or "").strip() == "team" and str(config.get("teamId") or "").strip() == team["teamId"]:
        return
    raise TeamKnowledgeError("team_chat_refinement roomId must belong to the Team linked chat room.")


def _knowledge_bases_for_owner(owner_value: Any) -> list[dict[str, Any]]:
    owner = _coerce_owner_context(owner_value)
    state = _load_bases_state_for_owner(owner)
    bases = [item for item in state.get("knowledgeBases") or [] if isinstance(item, dict)]
    return [_repair_base_for_owner(owner, item) for item in bases]


def _knowledge_bases_for_team(team_id: str) -> list[dict[str, Any]]:
    return _knowledge_bases_for_owner(_owner_context("team", team_id))


def _find_knowledge_base_for_owner(owner_value: Any, knowledge_base_id: str) -> dict[str, Any] | None:
    _, _, normalized_id = _parse_owner_scoped_knowledge_base_id(knowledge_base_id)
    for base in _knowledge_bases_for_owner(owner_value):
        if str(base.get("knowledgeBaseId") or "").strip() == normalized_id:
            return base
    return None


def _find_knowledge_base(team_id: str, knowledge_base_id: str) -> dict[str, Any] | None:
    return _find_knowledge_base_for_owner(_owner_context("team", team_id), knowledge_base_id)


def _source_artifacts_for_base(owner_value: Any, knowledge_base_id: str) -> list[dict[str, Any]]:
    owner = _coerce_owner_context(owner_value)
    return [
        item
        for item in _read_jsonl(_source_artifacts_path_for_owner(owner))
        if str(item.get("knowledgeBaseId") or "") == knowledge_base_id
    ]


def _require_item(owner_value: Any, knowledge_base_id: str, knowledge_item_id: str) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    item = _find_by_id(_read_jsonl(_items_path_for_owner(owner)), "knowledgeItemId", knowledge_item_id)
    if not item or str(item.get("knowledgeBaseId") or "") != knowledge_base_id:
        raise TeamKnowledgeNotFoundError("Knowledge item not found.")
    return item


def _require_proposal(owner_value: Any, knowledge_base_id: str, proposal_id: str) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    proposal = _find_by_id(_read_jsonl(_proposals_path_for_owner(owner)), "proposalId", proposal_id)
    if not proposal or str(proposal.get("targetKnowledgeBaseId") or "") != knowledge_base_id:
        raise TeamKnowledgeNotFoundError("Knowledge proposal not found.")
    return proposal


_search_text_for_payload = _tk_search_ranking._search_text_for_payload
_tokenize_search_text = _tk_search_ranking._tokenize_search_text
_tokenize_bm25_text = _tk_search_ranking._tokenize_bm25_text
_rank_bm25_search_results = _tk_search_ranking._rank_bm25_search_results
_bm25_text_for_result = _tk_search_ranking._bm25_text_for_result
_semantic_match_score = _tk_search_ranking._semantic_match_score
_search_match_reason = _tk_search_ranking._search_match_reason
_item_matches_filters = _tk_search_ranking._item_matches_filters

_iter_existing_knowledge_roots = _tk_store._iter_existing_knowledge_roots
_load_knowledge_bases_state_from_path = _tk_store._load_knowledge_bases_state_from_path
_load_bases_state_for_owner = _tk_store._load_bases_state_for_owner
_load_bases_state = _tk_store._load_bases_state
_source_governance_for_owner = _tk_store._source_governance_for_owner
_save_bases_state_for_owner = _tk_store._save_bases_state_for_owner
_save_bases_state = _tk_store._save_bases_state
_append_audit = _tk_store._append_audit
_find_by_id = _tk_store._find_by_id
_bounded_dict = _tk_store._bounded_dict
_source_hash = _tk_store._source_hash
_source_hash_with_content = _tk_store._source_hash_with_content
_find_central_source_by_hash_locked = _tk_store._find_central_source_by_hash_locked
_find_central_source_by_id_locked = _tk_store._find_central_source_by_id_locked
_rewrite_owner_source_review_queue_locked = _tk_store._rewrite_owner_source_review_queue_locked
_source_inbox_summary = _tk_store._source_inbox_summary
_safe_source_filename = _tk_store._safe_source_filename
_extended_fs_path = _tk_store._extended_fs_path
_project_relative_path = _tk_store._project_relative_path
_project_path_from_relative = _tk_store._project_path_from_relative
_read_jsonl = _tk_store._read_jsonl
_write_jsonl = _tk_store._write_jsonl
_append_jsonl = _tk_store._append_jsonl
_write_json = _tk_store._write_json
_owner_context = _tk_store._owner_context
_coerce_owner_context = _tk_store._coerce_owner_context
_normalize_owner_type = _tk_store._normalize_owner_type
_iter_knowledge_owners = _tk_store._iter_knowledge_owners
_knowledge_root = _tk_store._knowledge_root
_knowledge_root_for_owner = _tk_store._knowledge_root_for_owner
_knowledge_bases_path_for_owner = _tk_store._knowledge_bases_path_for_owner
_knowledge_bases_path = _tk_store._knowledge_bases_path
_source_artifacts_path_for_owner = _tk_store._source_artifacts_path_for_owner
_source_artifacts_path = _tk_store._source_artifacts_path
_owner_source_governance_path = _tk_store._owner_source_governance_path
_owner_inbox_root_for_owner = _tk_store._owner_inbox_root_for_owner
_owner_inbox_source_dir = _tk_store._owner_inbox_source_dir
_owner_source_index_path = _tk_store._owner_source_index_path
_owner_source_review_queue_path = _tk_store._owner_source_review_queue_path
_owner_source_rejected_path = _tk_store._owner_source_rejected_path
_proposals_path_for_owner = _tk_store._proposals_path_for_owner
_proposals_path = _tk_store._proposals_path
_batches_path_for_owner = _tk_store._batches_path_for_owner
_batches_path = _tk_store._batches_path
_items_path_for_owner = _tk_store._items_path_for_owner
_items_path = _tk_store._items_path
_audit_path_for_owner = _tk_store._audit_path_for_owner
_audit_path = _tk_store._audit_path
_rating_suggestions_path_for_owner = _tk_store._rating_suggestions_path_for_owner
_rating_suggestions_path = _tk_store._rating_suggestions_path
_developer_sandbox_module = _tk_store._developer_sandbox_module
_route_team_knowledge_workspace_path = _tk_store._route_team_knowledge_workspace_path
_assert_central_source_write_allowed = _tk_store._assert_central_source_write_allowed
_central_knowledge_root = _tk_store._central_knowledge_root
_central_sources_root = _tk_store._central_sources_root
_central_source_accepted_dir = _tk_store._central_source_accepted_dir
_central_source_registry_root = _tk_store._central_source_registry_root
_central_source_registry_path = _tk_store._central_source_registry_path
_central_owner_refs_path = _tk_store._central_owner_refs_path
_central_promotion_log_path = _tk_store._central_promotion_log_path
_project_root = _tk_store._project_root
_sync_roots = _tk_store._sync_roots
_safe_token = _tk_store._safe_token
_owner_scoped_knowledge_base_id = _tk_store._owner_scoped_knowledge_base_id
_parse_owner_scoped_knowledge_base_id = _tk_store._parse_owner_scoped_knowledge_base_id
_new_id = _tk_store._new_id
_new_event_id = _tk_store._new_event_id
_unique_strings = _tk_store._unique_strings

_permissions_for_actor = _tk_permissions._permissions_for_actor
_require_permission = _tk_permissions._require_permission
_require_rating_suggestion_permission = _tk_permissions._require_rating_suggestion_permission
_can_access = _tk_permissions._can_access
_can_collect_owner_source = _tk_permissions._can_collect_owner_source
_can_read_owner_source_inbox = _tk_permissions._can_read_owner_source_inbox
_can_review_owner_source = _tk_permissions._can_review_owner_source
_can_configure_owner_source_governance = _tk_permissions._can_configure_owner_source_governance
_is_global_knowledge_steward = _tk_permissions._is_global_knowledge_steward
_permission_explain = _tk_permissions._permission_explain
_member_role = _tk_permissions._member_role
_normalize_acl = _tk_permissions._normalize_acl

update_owner_source_governance = _tk_source_inbox.update_owner_source_governance
ensure_owner_source_review_grant = _tk_source_inbox.ensure_owner_source_review_grant
collect_source_to_inbox = _tk_source_inbox.collect_source_to_inbox
list_owner_source_inbox = _tk_source_inbox.list_owner_source_inbox
review_owner_inbox_source = _tk_source_inbox.review_owner_inbox_source
create_source_artifact_from_central_source = _tk_source_inbox.create_source_artifact_from_central_source
list_central_sources = _tk_source_inbox.list_central_sources
_direct_ingest_accepted_source_locked = _tk_source_inbox._direct_ingest_accepted_source_locked
_normalize_source_review_decision = _tk_source_inbox._normalize_source_review_decision
_write_owner_inbox_source_file = _tk_source_inbox._write_owner_inbox_source_file
_promote_owner_source_to_central_locked = _tk_source_inbox._promote_owner_source_to_central_locked
_resolve_duplicate_central_source_locked = _tk_source_inbox._resolve_duplicate_central_source_locked
_append_owner_ref_for_central_source_locked = _tk_source_inbox._append_owner_ref_for_central_source_locked
_copy_or_write_central_source_file = _tk_source_inbox._copy_or_write_central_source_file
_require_central_source_for_owner = _tk_source_inbox._require_central_source_for_owner
_central_owner_ref_visible = _tk_source_inbox._central_owner_ref_visible
_stage_local_source_copies = _tk_source_inbox._stage_local_source_copies
_relocate_local_copies_to_central = _tk_source_inbox._relocate_local_copies_to_central
_resolve_copyable_local_file = _tk_source_inbox._resolve_copyable_local_file
_sha256_local_file = _tk_source_inbox._sha256_local_file

# --- public structure curation catalog (workspace/knowledge/public) ---
PUBLIC_STRUCTURE_SCHEMA_VERSION = _tk_public_catalog.PUBLIC_STRUCTURE_SCHEMA_VERSION
STARTUP_STRUCTURE_MAX_CARDS = _tk_public_catalog.STARTUP_STRUCTURE_MAX_CARDS
STARTUP_STRUCTURE_MAX_CHARS = _tk_public_catalog.STARTUP_STRUCTURE_MAX_CHARS
STARTUP_CARD_WHEN_TO_USE_CHARS = _tk_public_catalog.STARTUP_CARD_WHEN_TO_USE_CHARS
STARTUP_CARD_SUMMARY_CHARS = _tk_public_catalog.STARTUP_CARD_SUMMARY_CHARS
DEFAULT_PARTITION_QUOTAS = _tk_public_catalog.DEFAULT_PARTITION_QUOTAS
PUBLIC_PARTITIONS = _tk_public_catalog.PUBLIC_PARTITIONS
PUBLIC_CARD_KINDS = _tk_public_catalog.PUBLIC_CARD_KINDS
PUBLIC_VISIBILITIES = _tk_public_catalog.PUBLIC_VISIBILITIES
PUBLIC_FRESHNESS_POLICIES = _tk_public_catalog.PUBLIC_FRESHNESS_POLICIES
PUBLIC_FRESHNESS_STATUSES = _tk_public_catalog.PUBLIC_FRESHNESS_STATUSES
PUBLIC_SOURCE_TYPES = _tk_public_catalog.PUBLIC_SOURCE_TYPES
PUBLIC_QUEUE_KINDS = _tk_public_catalog.PUBLIC_QUEUE_KINDS
PUBLIC_QUEUE_STATUSES = _tk_public_catalog.PUBLIC_QUEUE_STATUSES
PUBLIC_QUEUE_REASONS = _tk_public_catalog.PUBLIC_QUEUE_REASONS
PUBLIC_QUEUE_RESOLUTIONS = _tk_public_catalog.PUBLIC_QUEUE_RESOLUTIONS
PUBLIC_MAX_EXPERIENCE_BYTES = _tk_public_catalog.PUBLIC_MAX_EXPERIENCE_BYTES
PublicCatalogError = _tk_public_catalog.PublicCatalogError
PublicCatalogPermissionError = _tk_public_catalog.PublicCatalogPermissionError
PublicCatalogNotFoundError = _tk_public_catalog.PublicCatalogNotFoundError
PublicCatalogSourceUnavailableError = _tk_public_catalog.PublicCatalogSourceUnavailableError
PublicCatalogConflictError = _tk_public_catalog.PublicCatalogConflictError
get_public_catalog = _tk_public_catalog.get_public_catalog
save_public_structure = _tk_public_catalog.save_public_structure
upsert_public_card = _tk_public_catalog.upsert_public_card
archive_public_card = _tk_public_catalog.archive_public_card
refresh_public_catalog_freshness = _tk_public_catalog.refresh_public_catalog_freshness
search_public_catalog = _tk_public_catalog.search_public_catalog
resolve_public_locator = _tk_public_catalog.resolve_public_locator
open_public_card = _tk_public_catalog.open_public_card
build_startup_structure_block = _tk_public_catalog.build_startup_structure_block
submit_public_proposal = _tk_public_catalog.submit_public_proposal
list_public_proposals = _tk_public_catalog.list_public_proposals
resolve_public_proposal = _tk_public_catalog.resolve_public_proposal
list_catalog_queue_events = _tk_public_catalog.list_catalog_queue_events
resolve_catalog_queue_event = _tk_public_catalog.resolve_catalog_queue_event
_catalog_governance_tasks = _tk_public_catalog._catalog_governance_tasks


def _local_copies_from_source_artifacts(source_artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    copies: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in source_artifacts:
        if not isinstance(source, dict):
            continue
        ref = source.get("sourceRef") if isinstance(source.get("sourceRef"), dict) else {}
        pack_path = str(ref.get("centralPath") or "").strip()
        if pack_path and pack_path not in seen:
            seen.add(pack_path)
            copies.append(
                {
                    "candidateId": "",
                    "title": trim_lines(str(source.get("title") or "source"), max_lines=1).strip(),
                    "filename": Path(pack_path).name,
                    "sha256": str(source.get("sourceHash") or ref.get("sourceHash") or ""),
                    "byteSize": 0,
                    "centralPath": pack_path,
                    "originalPath": str(ref.get("originalPath") or ""),
                    "kind": "source_pack",
                }
            )
        for item in list(ref.get("localCopies") or []):
            if not isinstance(item, dict):
                continue
            key = str(item.get("sha256") or item.get("centralPath") or item.get("filename") or "").strip()
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            copies.append(
                {
                    "candidateId": str(item.get("candidateId") or "")[:160],
                    "title": trim_lines(str(item.get("title") or ""), max_lines=1).strip(),
                    "filename": str(item.get("filename") or "")[:180],
                    "sha256": str(item.get("sha256") or "")[:128],
                    "byteSize": int(item.get("byteSize") or 0),
                    "centralPath": str(item.get("centralPath") or "")[:500],
                    "originalPath": str(item.get("originalPath") or "")[:500],
                    "kind": str(item.get("kind") or "local_file"),
                }
            )
            if len(copies) >= MAX_LOCAL_SOURCE_COPIES:
                return copies
    return copies[:MAX_LOCAL_SOURCE_COPIES]


def _search_item_view(
    item: dict[str, Any],
    base: dict[str, Any],
    owner_value: dict[str, Any],
    artifacts_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    team = owner.get("team") if isinstance(owner.get("team"), dict) else {}
    agent = owner.get("agent") if isinstance(owner.get("agent"), dict) else {}
    source_artifacts = [
        artifacts_by_id[source_id]
        for source_id in [str(value or "") for value in list(item.get("sourceArtifactIds") or [])]
        if source_id in artifacts_by_id
    ]
    local_copies = _local_copies_from_source_artifacts(source_artifacts)
    return {
        "knowledgeItemId": str(item.get("knowledgeItemId") or ""),
        "knowledgeBaseId": str(base.get("knowledgeBaseId") or ""),
        "knowledgeBaseName": str(base.get("name") or ""),
        "ownerType": str(item.get("ownerType") or base.get("ownerType") or owner.get("ownerType") or "team"),
        "ownerId": str(item.get("ownerId") or base.get("ownerId") or owner.get("ownerId") or ""),
        "teamId": str(item.get("teamId") or (owner.get("ownerId") if owner.get("ownerType") == "team" else "")),
        "teamName": str(team.get("name") or ""),
        "agentId": str(item.get("agentId") or (owner.get("ownerId") if owner.get("ownerType") == "agent" else "")),
        "agentName": str(agent.get("displayName") or agent.get("agentCode") or ""),
        "batchId": str(item.get("batchId") or ""),
        "sourceArtifactIds": [str(value) for value in list(item.get("sourceArtifactIds") or [])[:12] if str(value or "").strip()],
        "centralSourceIds": [str(value) for value in list(item.get("centralSourceIds") or [])[:12] if str(value or "").strip()],
        "sourceTypes": sorted({str(source.get("sourceType") or "") for source in source_artifacts if str(source.get("sourceType") or "")}),
        "localCopies": local_copies,
        "sourceSummaries": [
            {
                "sourceArtifactId": str(source.get("sourceArtifactId") or ""),
                "centralSourceId": str(source.get("centralSourceId") or ""),
                "sourceType": str(source.get("sourceType") or ""),
                "capturedAt": str(source.get("capturedAt") or ""),
                "title": trim_lines(str(source.get("title") or ""), max_lines=1),
                "summary": trim_lines(str(source.get("summary") or ""), max_lines=2),
                "centralPath": str(
                    (source.get("sourceRef") if isinstance(source.get("sourceRef"), dict) else {}).get("centralPath")
                    or ""
                ),
                "localCopyCount": len(
                    [
                        item
                        for item in list(
                            (source.get("sourceRef") if isinstance(source.get("sourceRef"), dict) else {}).get(
                                "localCopies"
                            )
                            or []
                        )
                        if isinstance(item, dict)
                    ]
                ),
            }
            for source in source_artifacts[:6]
        ],
        "title": trim_lines(str(item.get("title") or ""), max_lines=2),
        "summary": trim_lines(str(item.get("summary") or ""), max_lines=4),
        "content": trim_lines(str(item.get("content") or ""), max_lines=12),
        "tags": [str(value) for value in list(item.get("tags") or [])[:12] if str(value or "").strip()],
        "importanceLevel": str(item.get("importanceLevel") or ""),
        "confidence": item.get("confidence"),
        "stability": str(item.get("stability") or ""),
        "scope": str(item.get("scope") or ""),
        "reviewPriority": str(item.get("reviewPriority") or ""),
        "createdAt": str(item.get("createdAt") or ""),
        "appliedAt": str(item.get("appliedAt") or ""),
        "updatedAt": str(item.get("updatedAt") or ""),
    }


def _task_status_matches(closed: bool, normalized_status: str) -> bool:
    if normalized_status == "all":
        return True
    if normalized_status == "closed":
        return closed
    return not closed


def _governance_task(
    owner_value: dict[str, Any],
    base: dict[str, Any],
    *,
    task_type: str,
    status: str,
    priority: str,
    title: str,
    summary: str,
    target_id: str,
    target_status: str,
    created_at: str,
    updated_at: str,
    permissions: dict[str, bool],
    source_artifact_ids: list[str],
) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    team = owner.get("team") if isinstance(owner.get("team"), dict) else {}
    agent = owner.get("agent") if isinstance(owner.get("agent"), dict) else {}
    return {
        "taskId": f"ktask:{base.get('knowledgeBaseId')}:{task_type}:{target_id}",
        "taskType": task_type,
        "status": status,
        "priority": priority if priority in REVIEW_PRIORITIES else "normal",
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": str(team.get("teamId") or ""),
        "teamName": str(team.get("name") or ""),
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "agentName": str(agent.get("displayName") or agent.get("agentCode") or ""),
        "knowledgeBaseId": str(base.get("knowledgeBaseId") or ""),
        "knowledgeBaseName": str(base.get("name") or ""),
        "targetId": target_id,
        "targetStatus": target_status,
        "title": trim_lines(title or task_type, max_lines=1),
        "summary": trim_lines(summary or "", max_lines=3),
        "sourceArtifactIds": source_artifact_ids[:12],
        "createdAt": created_at,
        "updatedAt": updated_at or created_at,
        "permissions": {
            "canReview": bool(permissions.get("canReview")),
            "canRate": bool(permissions.get("canRate")),
            "canPropose": bool(permissions.get("canPropose")),
        },
    }


def _steward_recommendation_from_task(task: dict[str, Any]) -> dict[str, Any]:
    task_type = str(task.get("taskType") or "").strip()
    priority = str(task.get("priority") or "normal").strip()
    permissions = task.get("permissions") if isinstance(task.get("permissions"), dict) else {}
    if task_type == "proposal_review":
        recommended_action = "review_proposal"
        reason = "Pending refinement proposal needs a reviewer before it can become formal knowledge."
        next_step = "Open the trace, inspect source evidence, then approve or reject as a review-capable Agent."
        requires_reviewer = True
        can_execute = bool(permissions.get("canReview"))
    elif task_type == "rating_review":
        recommended_action = "review_rating_suggestion"
        reason = "Pending importance or stability suggestion needs reviewer confirmation before item metadata changes."
        next_step = "Compare the suggestion with the target evidence, then apply or reject the rating suggestion."
        requires_reviewer = True
        can_execute = bool(permissions.get("canRate"))
    elif task_type == "source_needs_proposal":
        recommended_action = "draft_refinement_proposal"
        reason = "Registered source evidence has not yet been refined into a proposal."
        next_step = "Draft a refinement proposal that summarizes the source without creating formal knowledge directly."
        requires_reviewer = False
        can_execute = bool(permissions.get("canPropose"))
    else:
        recommended_action = "inspect_task"
        reason = "Governance task needs manual inspection."
        next_step = "Inspect the task and choose the smallest review-safe action."
        requires_reviewer = True
        can_execute = False
    return {
        "recommendationId": f"krec:{task.get('taskId')}",
        "taskId": str(task.get("taskId") or ""),
        "taskType": task_type,
        "recommendedAction": recommended_action,
        "priority": priority if priority in REVIEW_PRIORITIES else "normal",
        "teamId": str(task.get("teamId") or ""),
        "teamName": str(task.get("teamName") or ""),
        "knowledgeBaseId": str(task.get("knowledgeBaseId") or ""),
        "knowledgeBaseName": str(task.get("knowledgeBaseName") or ""),
        "targetId": str(task.get("targetId") or ""),
        "targetStatus": str(task.get("targetStatus") or ""),
        "title": trim_lines(str(task.get("title") or recommended_action), max_lines=1),
        "summary": trim_lines(str(task.get("summary") or ""), max_lines=3),
        "reason": reason,
        "nextStep": next_step,
        "requiresReviewer": requires_reviewer,
        "canExecuteWithCurrentActor": can_execute,
        "sourceArtifactIds": [str(value) for value in list(task.get("sourceArtifactIds") or [])[:12] if str(value or "").strip()],
        "createdAt": str(task.get("createdAt") or ""),
        "updatedAt": str(task.get("updatedAt") or task.get("createdAt") or ""),
    }


def _steward_workbench_stage(
    stage_id: str,
    title: str,
    description: str,
    recommended_action: str,
    recommendations: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    *,
    expected_task_type: str,
    next_tool: str,
) -> dict[str, Any]:
    stage_recommendations = [
        item
        for item in recommendations
        if str(item.get("recommendedAction") or "") == recommended_action
    ]
    stage_tasks = [
        item
        for item in tasks
        if str(item.get("taskType") or "") == expected_task_type
    ]
    open_count = len(stage_tasks)
    executable_count = sum(1 for item in stage_recommendations if bool(item.get("canExecuteWithCurrentActor")))
    return {
        "stageId": stage_id,
        "title": title,
        "description": description,
        "recommendedAction": recommended_action,
        "nextTool": next_tool,
        "openCount": open_count,
        "executableCount": executable_count,
        "blockedCount": max(0, open_count - executable_count),
        "items": stage_recommendations[:6],
        "status": "clear" if open_count == 0 else ("actionable" if executable_count else "needs_permission_or_reviewer"),
    }


def _knowledge_health_finding(
    finding_type: str,
    severity: str,
    row: dict[str, Any],
    count: int,
    message: str,
) -> dict[str, Any]:
    return {
        "findingId": f"khealth:{row.get('knowledgeBaseId')}:{finding_type}",
        "findingType": finding_type,
        "severity": severity,
        "teamId": str(row.get("teamId") or ""),
        "teamName": str(row.get("teamName") or ""),
        "knowledgeBaseId": str(row.get("knowledgeBaseId") or ""),
        "knowledgeBaseName": str(row.get("knowledgeBaseName") or ""),
        "count": int(count),
        "message": message,
        "nextReviewTargetIds": [str(value) for value in list(row.get("nextReviewTargetIds") or []) if str(value or "").strip()],
    }


def _recommended_tool_for_action(action: str) -> str:
    return {
        "review_proposal": "knowledge_governance_tasks_tool",
        "review_rating_suggestion": "knowledge_governance_tasks_tool",
        "draft_refinement_proposal": "knowledge_proposal_tool",
        "suggest_rating_metadata": "knowledge_rating_suggestion_tool",
    }.get(str(action or "").strip(), "unified_memory_search_tool")


def _priority_rank(priority: str) -> int:
    return {"normal": 1, "elevated": 2, "urgent": 3}.get(str(priority or ""), 0)


def _add_all(target: set[str], values: list[str]) -> bool:
    changed = False
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in target:
            target.add(normalized)
            changed = True
    return changed


def _batch_from_proposal(
    owner_value: dict[str, Any],
    base: dict[str, Any],
    proposal: dict[str, Any],
    reviewer_id: str,
    now: str,
) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    return {
        "batchId": _new_event_id("kbatch"),
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBaseId": base["knowledgeBaseId"],
        "proposalIds": [proposal["proposalId"]],
        "sourceArtifactIds": list(proposal.get("sourceArtifactIds") or []),
        "centralSourceIds": list(proposal.get("centralSourceIds") or []),
        "reviewedByAgentId": reviewer_id,
        "appliedAt": now,
        "status": "applied",
    }


def _item_from_proposal(
    owner_value: dict[str, Any],
    base: dict[str, Any],
    proposal: dict[str, Any],
    batch: dict[str, Any],
    reviewer_id: str,
    now: str,
) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    return {
        "knowledgeItemId": _new_event_id("kitem"),
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBaseId": base["knowledgeBaseId"],
        "batchId": batch["batchId"],
        "sourceArtifactIds": list(proposal.get("sourceArtifactIds") or []),
        "centralSourceIds": list(proposal.get("centralSourceIds") or []),
        "title": proposal.get("title") or "",
        "summary": proposal.get("summary") or "",
        "content": proposal.get("content") or "",
        "tags": list(proposal.get("tags") or []),
        "importanceLevel": "medium",
        "confidence": 0.7,
        "stability": "evolving",
        "scope": "team" if owner["ownerType"] == "team" else "agent",
        "reviewPriority": "normal",
        "createdAt": now,
        "updatedAt": now,
        "reviewedAt": now,
        "appliedAt": now,
        "reviewedByAgentId": reviewer_id,
        "markedBy": "",
        "markedAt": "",
        "markingReason": "",
    }


def _repair_base_for_owner(owner_value: Any, base: dict[str, Any]) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    now = utc_now_iso()
    owner_type = str(base.get("ownerType") or owner.get("ownerType") or "team").strip()
    owner_id = _safe_token(base.get("ownerId"), default=str(owner.get("ownerId") or ""), max_length=128)
    return {
        "knowledgeBaseId": _safe_token(base.get("knowledgeBaseId"), default=_new_event_id("kb"), max_length=128),
        "ownerType": owner_type,
        "ownerId": owner_id,
        "teamId": _safe_token(base.get("teamId"), default=owner_id if owner_type == "team" else "", max_length=96),
        "agentId": _safe_token(base.get("agentId"), default=owner_id if owner_type == "agent" else "", max_length=128),
        "name": trim_lines(str(base.get("name") or ("Agent Knowledge" if owner_type == "agent" else "Team Knowledge")), max_lines=1).strip(),
        "description": trim_lines(str(base.get("description") or ""), max_lines=6).strip(),
        "status": str(base.get("status") or "active").strip() or "active",
        "acl": _normalize_acl(base.get("acl")),
        "createdAt": str(base.get("createdAt") or now),
        "updatedAt": str(base.get("updatedAt") or base.get("createdAt") or now),
    }


def _repair_base(team_id: str, base: dict[str, Any]) -> dict[str, Any]:
    return _repair_base_for_owner(_owner_context("team", team_id), base)


def _record_event(
    event_code: str,
    owner_value: Any,
    knowledge_base_id: str,
    *,
    actor_agent_id: str = "",
    fields: dict[str, Any] | None = None,
) -> None:
    owner = _coerce_owner_context(owner_value)
    try:
        record_runtime_scene_event(
            "team_knowledge_service",
            "knowledge",
            event_code,
            message=event_code,
            outcome="observed",
            fields={
                "ownerType": owner.get("ownerType"),
                "ownerId": owner.get("ownerId"),
                "teamId": owner.get("ownerId") if owner.get("ownerType") == "team" else "",
                "agentId": owner.get("ownerId") if owner.get("ownerType") == "agent" else "",
                "knowledgeBaseId": knowledge_base_id,
                "actorAgentId": str(actor_agent_id or "").strip(),
                **(fields or {}),
            },
            lifecycle=True,
        )
    except Exception:
        pass


def _enum_value(value: str, allowed: set[str], label: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise TeamKnowledgeError(f"Unsupported {label}: {value}")
    return normalized
