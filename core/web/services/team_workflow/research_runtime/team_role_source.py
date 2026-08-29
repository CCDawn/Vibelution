"""Team-role binding source for research workflow runs.

Resolves a team's member roles into the workflow's roleKey -> agentId default
map. This is the CURRENT-CONFIGURATION source
only: run creation freezes the resolved result into an immutable
RunAgentBindingSnapshot, so history never re-reads live team config.

Rules enforced here:
- no random fallback to arbitrary agents (a missing role is simply unbound);
- Team ``members`` is the only role-binding source; canvas is a projection;
- only product-Agent owners may enter binding layers or healing;
- canonical product roles project onto legacy lookup aliases, while a
  legacy-only Team keeps exact aliases independent;
- ambiguous bindings fail closed instead of selecting the first Agent;
- team lookup failure yields an empty map (all roles unbound), never an error.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from core.research.workflow.contracts.research_team_role_contract import (
    CURRENT_RESEARCH_TEAM_ROLE_CONTRACT,
)
from core.research.workflow.models import AgentBindingLayers

RoleOwner = tuple[str, str]
TeamMemberSourceStatus = Literal["unscoped", "found", "missing", "error"]


def normalize_role_key(value: str | None) -> str:
    return str(value or "").strip().lower()


def _role_contract_indexes() -> tuple[
    dict[str, RoleOwner],
    dict[str, tuple[str, ...]],
]:
    owners: dict[str, RoleOwner] = {}
    product_keys: dict[str, tuple[str, ...]] = {}
    contract = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT
    for role in contract.product_agents:
        keys = tuple(
            normalize_role_key(value)
            for value in (role.product_role_id, *role.legacy_role_aliases)
        )
        product_keys[role.product_role_id] = keys
        for key in keys:
            owners[key] = ("product_agent", role.product_role_id)
    for capability in contract.system_capabilities:
        for value in (
            capability.capability_id,
            *capability.legacy_role_aliases,
        ):
            owners[normalize_role_key(value)] = (
                "system_capability",
                capability.capability_id,
            )
    return owners, product_keys


_ROLE_OWNER_BY_KEY, _PRODUCT_ROLE_KEYS_BY_OWNER = _role_contract_indexes()


def _product_owner_id(value: str | None) -> str:
    owner = _ROLE_OWNER_BY_KEY.get(normalize_role_key(value))
    if owner is None or owner[0] != "product_agent":
        return ""
    return owner[1]


def _agent_id_of(item: dict[str, Any]) -> str:
    return str(item.get("agentId") or "").strip()


def _role_of(item: dict[str, Any]) -> str:
    return normalize_role_key(item.get("role"))


def _layer_role_agents(items: Any) -> dict[str, set[str]]:
    candidates: dict[str, set[str]] = {}
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        role = _role_of(item)
        agent_id = _agent_id_of(item)
        if not role or not agent_id or not _product_owner_id(role):
            continue
        candidates.setdefault(role, set()).add(agent_id)
    return candidates


def _select_exact_role_agent(
    layers: tuple[dict[str, set[str]], ...],
    role_key: str,
) -> tuple[str, bool]:
    """Return (agentId, ambiguous) from the highest layer containing roleKey."""
    for layer in layers:
        candidates = layer.get(role_key)
        if not candidates:
            continue
        if len(candidates) != 1:
            return "", True
        return next(iter(candidates)), False
    return "", False


def _filtered_product_role_bindings(values: Mapping[Any, Any]) -> dict[str, str]:
    filtered: dict[str, str] = {}
    for raw_role, raw_agent_id in values.items():
        role = normalize_role_key(str(raw_role or ""))
        agent_id = str(raw_agent_id or "").strip()
        if role and agent_id and _product_owner_id(role):
            filtered[role] = agent_id
    return filtered


def _agent_id_for_product_role(
    bindings: Mapping[str, str],
    role_key: str,
) -> str:
    normalized_role = normalize_role_key(role_key)
    direct = str(bindings.get(normalized_role) or "").strip()
    if direct:
        return direct
    owner_id = _product_owner_id(normalized_role)
    if not owner_id:
        return ""
    candidates = {
        str(bindings.get(lookup_key) or "").strip()
        for lookup_key in _PRODUCT_ROLE_KEYS_BY_OWNER[owner_id]
        if str(bindings.get(lookup_key) or "").strip()
    }
    return next(iter(candidates)) if len(candidates) == 1 else ""


def _team_member_source(team_id: str) -> tuple[TeamMemberSourceStatus, Any]:
    if not str(team_id or "").strip():
        return "unscoped", []
    try:
        from core.web.services.team_service import list_team_role_binding_sources

        sources = list_team_role_binding_sources(team_id)
    except Exception:  # noqa: BLE001 - source failure must fail closed
        return "error", []

    if not isinstance(sources, Mapping):
        return "error", []
    team_exists = bool(sources.get("team_exists", "members" in sources))
    return ("found" if team_exists else "missing"), sources.get("members")


def resolve_team_role_bindings(team_id: str) -> dict[str, str]:
    """Return roleKey -> agentId from the Team's canonical members.

    Empty result means no usable role mapping — callers treat every role as
    unbound (never fall back to a random agent).
    """
    _source_status, members = _team_member_source(team_id)
    return _resolve_member_role_bindings(members)


def _resolve_member_role_bindings(members: Any) -> dict[str, str]:
    layers = (_layer_role_agents(members),)
    bindings: dict[str, str] = {}
    for product_role in CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.product_agents:
        owner_id = product_role.product_role_id
        lookup_keys = _PRODUCT_ROLE_KEYS_BY_OWNER[owner_id]
        canonical_key = lookup_keys[0]
        canonical_agent, canonical_ambiguous = _select_exact_role_agent(
            layers,
            canonical_key,
        )
        if canonical_ambiguous:
            continue
        if canonical_agent:
            for lookup_key in lookup_keys:
                bindings[lookup_key] = canonical_agent
            continue
        for legacy_key in lookup_keys[1:]:
            legacy_agent, legacy_ambiguous = _select_exact_role_agent(
                layers,
                legacy_key,
            )
            if legacy_agent and not legacy_ambiguous:
                bindings[legacy_key] = legacy_agent
    return bindings


def heal_agent_binding_for_node(
    team_id: str,
    node_id: str,
) -> dict[str, str] | None:
    """Fill an empty frozen snapshot slot from the team's current role map.

    Team membership may become available after an incomplete snapshot was
    created. History stays authoritative when the freeze already named an
    agentId.
    """
    from core.research.workflow.definition import node_by_id
    from core.research.workflow.models import ActorKind

    node = node_by_id().get(str(node_id or "").strip())
    if (
        node is None
        or node.actorKind != ActorKind.AGENT
        or not _product_owner_id(node.primaryRoleKey)
    ):
        return None
    roles = resolve_team_role_bindings(team_id)
    if not roles:
        return None
    primary = normalize_role_key(node.primaryRoleKey)
    agent_id = _agent_id_for_product_role(roles, primary)
    if not agent_id:
        return None
    return {
        "nodeId": node.nodeId,
        "agentId": agent_id,
        "roleKey": node.primaryRoleKey,
        "resolvedFrom": "team_role_heal",
        "snapshotId": f"heal:{team_id}:{node.nodeId}",
    }


def heal_agent_binding_from_sibling_freeze(
    snapshot: Mapping[str, Any] | None,
    node_id: str,
) -> dict[str, str] | None:
    """Reuse another frozen node binding on the same run when this slot is empty.

    Compact restores often freeze earlier Agent nodes only. This stays inside
    the run snapshot; it is not a live-directory random pick.
    """
    from core.research.workflow.definition import node_by_id
    from core.research.workflow.models import ActorKind

    nodes = node_by_id()
    node = nodes.get(str(node_id or "").strip())
    if node is None or node.actorKind != ActorKind.AGENT:
        return None
    preferred = normalize_role_key(node.primaryRoleKey)
    preferred_owner = _product_owner_id(preferred)
    if not preferred_owner or not isinstance(snapshot, Mapping):
        return None
    exact_candidates: list[dict[str, str]] = []
    owner_candidates: list[dict[str, str]] = []
    for binding in snapshot.get("agentBindingSnapshot") or []:
        if not isinstance(binding, Mapping):
            continue
        agent_id = str(binding.get("agentId") or "").strip()
        sibling_node_id = str(binding.get("nodeId") or "").strip()
        if not agent_id or not sibling_node_id or sibling_node_id == node.nodeId:
            continue
        sibling_node = nodes.get(sibling_node_id)
        if sibling_node is None or sibling_node.actorKind != ActorKind.AGENT:
            continue
        sibling_owner = _product_owner_id(sibling_node.primaryRoleKey)
        observed_role = normalize_role_key(str(binding.get("roleKey") or ""))
        observed_owner = _product_owner_id(observed_role)
        if (
            not sibling_owner
            or sibling_owner != preferred_owner
            or observed_owner != sibling_owner
        ):
            continue
        item = {
            "nodeId": node.nodeId,
            "agentId": agent_id,
            "roleKey": node.primaryRoleKey,
            "resolvedFrom": "sibling_freeze",
            "snapshotId": f"heal-sibling:{node.nodeId}",
        }
        if observed_role == preferred:
            exact_candidates.append(item)
        else:
            owner_candidates.append(item)
    selected = exact_candidates if exact_candidates else owner_candidates
    return selected[0] if len(selected) == 1 else None


def effective_binding_layers(
    team_id: str,
    config: AgentBindingLayers,
) -> AgentBindingLayers:
    """Build effective layers with Team members as the default authority.

    Priority order (kept by resolve_effective_agent_id in core/research):
      node override > stage override > workflow default > unbound.
    For a Team-scoped workflow, persisted ``workflowDefaults`` are ignored:
    they are a retired second membership source. Stage and node overrides are
    still allowed because they select an Agent for one execution scope and do
    not redefine Team membership. A workflow without a Team keeps its
    persisted defaults for backwards-compatible non-Team use.
    """
    from core.research.workflow.definition import (
        build_challenge_cup_workflow_definition,
        node_by_id,
    )
    from core.research.workflow.models import ActorKind

    definition = build_challenge_cup_workflow_definition()
    valid_stage_ids = {stage.stageId.value for stage in definition.stages}
    source_status, members = _team_member_source(team_id)
    team_defaults = (
        _resolve_member_role_bindings(members)
        if source_status == "found"
        else {}
    )
    persisted_defaults = _filtered_product_role_bindings(config.workflowDefaults)
    if source_status == "unscoped":
        merged_defaults = persisted_defaults
    else:
        # A Team-scoped workflow is fail-closed when the canonical Team source
        # is missing or unavailable. Never revive retired workflowDefaults on
        # a lookup failure; doing so would make a stale layer a second SSOT.
        merged_defaults = team_defaults
    stage_overrides: dict[str, dict[str, str]] = {}
    for raw_stage_id, values in config.stageOverrides.items():
        if not isinstance(values, Mapping):
            continue
        stage_id = str(raw_stage_id or "").strip()
        if stage_id not in valid_stage_ids:
            continue
        filtered = _filtered_product_role_bindings(values)
        if filtered:
            stage_overrides[stage_id] = filtered
    nodes = node_by_id(definition)
    node_overrides: dict[str, str] = {}
    for raw_node_id, raw_agent_id in config.nodeOverrides.items():
        node_id = str(raw_node_id or "").strip()
        agent_id = str(raw_agent_id or "").strip()
        node = nodes.get(node_id)
        if (
            node is None
            or node.actorKind != ActorKind.AGENT
            or not _product_owner_id(node.primaryRoleKey)
            or not agent_id
        ):
            continue
        node_overrides[node_id] = agent_id
    return AgentBindingLayers(
        workflowDefaults=merged_defaults,
        stageOverrides=stage_overrides,
        nodeOverrides=node_overrides,
    )
