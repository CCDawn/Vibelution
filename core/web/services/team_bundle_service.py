"""Team bundle export / import.

A team bundle is a portable JSON description of one team: its member Agents
(llm bindings, persona/task profiles, tool policies, prompt template ids),
the custom prompt template bodies those Agents reference, the chat room
shape, and the research canvas. Credentials never travel inside a bundle:
providers are declared under ``dependencies`` so the import preview can list
missing providers and the credential env vars they still need.

Export projects Agent registry records down to a stable whitelist (instance
ids, config hashes and timestamps are stripped). Import is two-phase: a
``dry_run`` preview reports version gates, upsert conflicts, dependency gaps
and pending credentials; execution upserts Agents by
``metadata.teamBundleAgentKey`` (falling back to display name) and then the
team, chat room and canvas, mirroring ``team_template_service``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.web.services import (
    agent_directory_service,
    chat_room_service,
    prompt_template_service,
    session_service,
    team_service,
)
from core.web.services.team_service import TeamNotFoundError as _TeamNotFoundError

PROJECT_ROOT = Path(__file__).resolve().parents[3]

BUNDLE_KIND = "vibelution-team-bundle"
BUNDLE_SCHEMA_VERSION = 1
SUPPORTED_BUNDLE_SCHEMA_MAJOR = 1

_BUNDLE_AGENT_METADATA_KEY = "teamBundleAgentKey"
_BUNDLE_SOURCE = "team_bundle"

# Registry fields that survive export; everything else (ids, sessions,
# workspace paths, config hashes, timestamps) is instance-local.
_AGENT_EXPORT_FIELDS = (
    "agentCode",
    "displayName",
    "kind",
    "primaryMode",
    "roleKey",
    "llmBindings",
    "promptTemplateId",
    "toolPolicy",
    "memoryPolicy",
    "contextCompressionPolicy",
    "permissionPreset",
)

_METADATA_EXPORT_EXCLUDED_KEYS = frozenset(
    {
        "teamTemplateId",
        "teamTemplateRole",
        _BUNDLE_AGENT_METADATA_KEY,
        "teamBundleSource",
        "teamBundleImportedAt",
    }
)


class TeamBundleError(ValueError):
    """Raised for malformed bundles or bundle/target mismatches."""

    def __init__(self, message: str, *, code: str = "invalid_bundle") -> None:
        super().__init__(message)
        self.code = code


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _app_version() -> str:
    try:
        raw = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        raw = ""
    return raw or "unknown"


def _agent_bundle_key(agent: dict[str, Any]) -> str:
    metadata = agent.get("metadata") or {}
    key = str(metadata.get(_BUNDLE_AGENT_METADATA_KEY) or "").strip()
    return key or str(agent.get("displayName") or "").strip()


def _project_agent_for_bundle(agent: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for field in _AGENT_EXPORT_FIELDS:
        value = agent.get(field)
        if value not in (None, "", [], {}):
            projected[field] = value
    metadata = dict(agent.get("metadata") or {})
    persona = metadata.pop("personaProfile", None)
    task = metadata.pop("taskProfile", None)
    for key in _METADATA_EXPORT_EXCLUDED_KEYS:
        metadata.pop(key, None)
    if metadata:
        projected["metadata"] = metadata
    if isinstance(persona, dict) and persona:
        projected["personaProfile"] = persona
    if isinstance(task, dict) and task:
        projected["taskProfile"] = task
    projected["bundleAgentKey"] = _agent_bundle_key(agent)
    return projected


def _collect_dependencies(agents: list[dict[str, Any]]) -> dict[str, Any]:
    providers: dict[str, dict[str, Any]] = {}
    for agent in agents:
        bindings = agent.get("llmBindings") or {}
        for slot_binding in bindings.values():
            if not isinstance(slot_binding, dict):
                continue
            model_id = str(slot_binding.get("modelId") or "").strip()
            if not model_id:
                continue
            provider_id, _, model_name = model_id.partition("/")
            if not provider_id:
                continue
            entry = providers.setdefault(provider_id, {"models": []})
            if model_name and model_name not in entry["models"]:
                entry["models"].append(model_name)
    return {"providers": providers}


def _custom_prompt_templates_for(agent_ids_prompt_ids: list[str]) -> list[dict[str, Any]]:
    if not agent_ids_prompt_ids:
        return []
    listing = prompt_template_service.list_prompt_templates()
    templates = listing.get("templates") if isinstance(listing, dict) else None
    if not isinstance(templates, list):
        return []
    wanted = set(agent_ids_prompt_ids)
    bundled: list[dict[str, Any]] = []
    for template in templates:
        if not isinstance(template, dict):
            continue
        template_id = str(template.get("templateId") or template.get("id") or "")
        if template_id not in wanted:
            continue
        record: dict[str, Any] = {"templateId": template_id}
        for field in ("label", "content", "description", "sourcePath"):
            value = template.get(field)
            if value not in (None, ""):
                record[field] = value
        bundled.append(record)
    return bundled


def export_team_bundle(team_id: str) -> dict[str, Any]:
    try:
        team = team_service.get_team(team_id)
    except _TeamNotFoundError:
        raise TeamBundleError(f"Team not found: {team_id}", code="team_not_found") from None
    if not team:
        raise TeamBundleError(f"Team not found: {team_id}", code="team_not_found")
    members = [member for member in team.get("members") or [] if isinstance(member, dict)]
    agents: list[dict[str, Any]] = []
    member_bindings: list[dict[str, Any]] = []
    prompt_ids: list[str] = []
    for member in members:
        agent = agent_directory_service.get_agent(str(member.get("agentId") or ""))
        if not agent:
            continue
        projected = _project_agent_for_bundle(agent)
        agents.append(projected)
        member_bindings.append(
            {
                "bundleAgentKey": projected["bundleAgentKey"],
                "role": member.get("role") or "",
                "purpose": member.get("purpose") or "",
                "responsibilities": list(member.get("responsibilities") or []),
            }
        )
        prompt_id = str(projected.get("promptTemplateId") or "")
        if prompt_id:
            prompt_ids.append(prompt_id)
    linked_room = team.get("linkedChatRoom") or {}
    canvas = team_service.get_team_canvas(team_id)
    return {
        "kind": BUNDLE_KIND,
        "schemaVersion": BUNDLE_SCHEMA_VERSION,
        "exportedAt": _utc_now_iso(),
        "appVersion": _app_version(),
        "team": {
            "name": team.get("name") or "",
            "description": team.get("description") or "",
            "purpose": team.get("purpose") or "",
            "members": member_bindings,
            "chatRoom": {
                "mode": linked_room.get("mode") or "",
                "purpose": linked_room.get("purpose") or "",
            },
        },
        "agents": agents,
        "promptTemplates": _custom_prompt_templates_for(prompt_ids),
        "canvas": canvas if isinstance(canvas, dict) and canvas.get("nodes") else {},
        "dependencies": _collect_dependencies(agents),
    }


def _normalize_incoming_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise TeamBundleError("Bundle must be a JSON object.", code="invalid_bundle")
    kind = str(bundle.get("kind") or "").strip()
    if kind and kind != BUNDLE_KIND:
        raise TeamBundleError(
            f"Unsupported bundle kind: {kind} (expected {BUNDLE_KIND})",
            code="unsupported_kind",
        )
    schema_version = bundle.get("schemaVersion")
    try:
        schema_major = int(schema_version)
    except (TypeError, ValueError):
        raise TeamBundleError("Bundle is missing a valid schemaVersion.", code="invalid_schema_version") from None
    team = bundle.get("team")
    if not isinstance(team, dict) or not str(team.get("name") or "").strip():
        raise TeamBundleError("Bundle is missing team.name.", code="invalid_team")
    agents = bundle.get("agents")
    if not isinstance(agents, list) or not agents:
        raise TeamBundleError("Bundle has no agents.", code="invalid_agents")
    for agent in agents:
        if not isinstance(agent, dict) or not str(agent.get("bundleAgentKey") or agent.get("displayName") or "").strip():
            raise TeamBundleError("Bundle agent is missing bundleAgentKey/displayName.", code="invalid_agent")
    return bundle


def _bundle_schema_major(bundle: dict[str, Any]) -> int:
    try:
        return int(bundle.get("schemaVersion"))
    except (TypeError, ValueError):
        return 0


def _load_local_provider_index() -> dict[str, dict[str, Any]]:
    from config.public_config import load_public_config

    try:
        config = load_public_config()
    except Exception:
        return {}
    providers = config.get("llm", {}).get("providers", {}) if isinstance(config, dict) else {}
    return providers if isinstance(providers, dict) else {}


def _dependency_report(dependencies: dict[str, Any]) -> dict[str, Any]:
    wanted = dependencies.get("providers") or {}
    local_providers = _load_local_provider_index()
    missing_providers: list[str] = []
    missing_models: list[dict[str, str]] = []
    pending_credentials: list[dict[str, str]] = []
    for provider_id, spec in wanted.items():
        local = local_providers.get(str(provider_id))
        if not isinstance(local, dict):
            missing_providers.append(str(provider_id))
            continue
        credential_ref = str(local.get("credential_ref") or "")
        if credential_ref.startswith("env:"):
            pending_credentials.append(
                {"providerId": str(provider_id), "credentialEnv": credential_ref.removeprefix("env:")}
            )
        local_models = {
            str(model.get("upstream_id") or model_id)
            for model_id, model in (local.get("models") or {}).items()
            if isinstance(model, dict)
        }
        for model_name in (spec or {}).get("models") or []:
            if str(model_name) not in local_models:
                missing_models.append({"providerId": str(provider_id), "model": str(model_name)})
    return {
        "missingProviders": missing_providers,
        "missingModels": missing_models,
        "pendingCredentials": pending_credentials,
    }


def _match_local_agent(bundle_agent: dict[str, Any]) -> dict[str, Any] | None:
    bundle_key = str(bundle_agent.get("bundleAgentKey") or bundle_agent.get("displayName") or "").strip()
    display_name = str(bundle_agent.get("displayName") or "").strip()
    for agent in agent_directory_service.list_agents():
        metadata = agent.get("metadata") or {}
        if str(metadata.get(_BUNDLE_AGENT_METADATA_KEY) or "").strip() == bundle_key:
            return agent
    if display_name:
        for agent in agent_directory_service.list_agents():
            if str(agent.get("displayName") or "").strip() == display_name:
                return agent
    return None


def _find_team_by_name(name: str) -> dict[str, Any] | None:
    listing = team_service.list_teams()
    teams = listing.get("teams") if isinstance(listing, dict) else listing
    if not isinstance(teams, list):
        return None
    for team in teams:
        if isinstance(team, dict) and str(team.get("name") or "").strip() == name.strip():
            return team_service.get_team(str(team.get("teamId") or ""))
    return None


def _apply_prompt_templates(templates: list[dict[str, Any]]) -> None:
    for template in templates:
        template_id = str(template.get("templateId") or "").strip()
        content = str(template.get("content") or "").strip()
        if not template_id or not content:
            continue
        prompt_template_service.update_prompt_template(
            template_id,
            name=str(template.get("label") or template_id),
            content=content,
            metadata={"source": _BUNDLE_SOURCE},
        )


def _upsert_agent(bundle_agent: dict[str, Any]) -> tuple[dict[str, Any], str]:
    existing = _match_local_agent(bundle_agent)
    bundle_key = str(bundle_agent.get("bundleAgentKey") or bundle_agent.get("displayName") or "").strip()
    metadata = dict(bundle_agent.get("metadata") or {})
    metadata.update(
        {
            _BUNDLE_AGENT_METADATA_KEY: bundle_key,
            "teamBundleSource": _BUNDLE_SOURCE,
            "teamBundleImportedAt": _utc_now_iso(),
        }
    )
    common_kwargs: dict[str, Any] = {
        "display_name": str(bundle_agent.get("displayName") or bundle_key),
        "llm_bindings": bundle_agent.get("llmBindings") or {},
        "primary_mode": str(bundle_agent.get("primaryMode") or "chat"),
        "role_key": str(bundle_agent.get("roleKey") or ""),
        "prompt_template_id": str(bundle_agent.get("promptTemplateId") or ""),
        "tool_policy": bundle_agent.get("toolPolicy") or None,
        "memory_policy": bundle_agent.get("memoryPolicy") or None,
        "context_compression_policy": bundle_agent.get("contextCompressionPolicy") or None,
        "persona_profile": bundle_agent.get("personaProfile") or None,
        "task_profile": bundle_agent.get("taskProfile") or None,
        "metadata": metadata,
    }
    if existing:
        agent = agent_directory_service.update_agent_instance(
            str(existing["agentId"]), **common_kwargs
        )
        return agent, "updated"
    session = session_service.create_chat_session(
        title=str(common_kwargs["display_name"]),
        llm_bindings=session_service.default_session_llm_bindings(),
        created_by=_BUNDLE_SOURCE,
    )
    agent_id = str(session.get("agentId") or "").strip()
    if not agent_id:
        raise TeamBundleError(
            f"Bundle agent did not create an Agent: {common_kwargs['display_name']}",
            code="agent_create_failed",
        )
    agent = agent_directory_service.update_agent_instance(agent_id, **common_kwargs)
    return agent, "created"


def import_team_bundle(bundle: dict[str, Any], *, dry_run: bool, confirm: bool = False) -> dict[str, Any]:
    normalized = _normalize_incoming_bundle(bundle)
    team_spec = normalized["team"]
    agents_spec = [agent for agent in normalized["agents"] if isinstance(agent, dict)]
    schema_major = _bundle_schema_major(normalized)
    version_pending = schema_major > SUPPORTED_BUNDLE_SCHEMA_MAJOR and not confirm

    create_agents: list[str] = []
    overwrite_agents: list[str] = []
    agent_id_by_key: dict[str, str] = {}
    if not version_pending:
        for bundle_agent in agents_spec:
            bundle_key = str(bundle_agent.get("bundleAgentKey") or bundle_agent.get("displayName") or "").strip()
            existing = _match_local_agent(bundle_agent)
            if existing:
                overwrite_agents.append(str(existing.get("displayName") or bundle_key))
                agent_id_by_key[bundle_key] = str(existing["agentId"])
            else:
                create_agents.append(str(bundle_agent.get("displayName") or bundle_key))
        existing_team = _find_team_by_name(str(team_spec.get("name") or ""))
        team_action = "update" if existing_team else "create"
    else:
        existing_team = _find_team_by_name(str(team_spec.get("name") or ""))
        team_action = "update" if existing_team else "create"

    dependency = _dependency_report(normalized.get("dependencies") or {})
    warnings: list[str] = []
    if schema_major < SUPPORTED_BUNDLE_SCHEMA_MAJOR:
        warnings.append(
            f"Bundle schema v{schema_major} is older than v{SUPPORTED_BUNDLE_SCHEMA_MAJOR}; "
            "importing with current-field mapping."
        )
    if dependency["missingProviders"]:
        warnings.append(
            "Missing providers: " + ", ".join(dependency["missingProviders"])
        )

    report: dict[str, Any] = {
        "schemaVersion": BUNDLE_SCHEMA_VERSION,
        "bundleSchemaVersion": schema_major,
        "status": "pending" if version_pending else ("ready" if dry_run else "completed"),
        "dryRun": dry_run,
        "team": {
            "name": team_spec.get("name") or "",
            "action": team_action,
        },
        "agents": {
            "create": create_agents,
            "overwrite": overwrite_agents,
        },
        "dependencies": dependency,
        "warnings": warnings,
    }
    if dry_run or version_pending:
        return report

    _apply_prompt_templates([t for t in normalized.get("promptTemplates") or [] if isinstance(t, dict)])
    members: list[dict[str, Any]] = []
    created_or_updated: list[dict[str, Any]] = []
    for bundle_agent in agents_spec:
        agent, action = _upsert_agent(bundle_agent)
        created_or_updated.append({"agentId": agent["agentId"], "action": action})
    agent_by_key: dict[str, dict[str, Any]] = {
        str(
            (agent.get("metadata") or {}).get(_BUNDLE_AGENT_METADATA_KEY)
            or agent.get("displayName")
            or ""
        ): agent
        for agent in [agent_directory_service.get_agent(item["agentId"]) for item in created_or_updated]
    }
    for index, member_spec in enumerate(team_spec.get("members") or [], start=1):
        if not isinstance(member_spec, dict):
            continue
        bundle_key = str(member_spec.get("bundleAgentKey") or "").strip()
        agent = agent_by_key.get(bundle_key)
        if not agent:
            continue
        members.append(
            {
                "memberId": f"bundle-member-{index}",
                "agentId": agent["agentId"],
                "role": member_spec.get("role") or "",
                "purpose": member_spec.get("purpose") or "",
                "responsibilities": list(member_spec.get("responsibilities") or []),
            }
        )
    team_kwargs: dict[str, Any] = {
        "name": str(team_spec.get("name") or ""),
        "description": str(team_spec.get("description") or ""),
        "purpose": str(team_spec.get("purpose") or ""),
        "members": members,
    }
    if existing_team:
        team = team_service.update_team(str(existing_team["teamId"]), **team_kwargs)
    else:
        team = team_service.create_team(
            **team_kwargs,
            team_kind="bundle_import",
            team_category="导入团队",
            team_source=_BUNDLE_SOURCE,
        )
    chat_spec = team_spec.get("chatRoom") or {}
    room_id = str(team.get("linkedChatRoomId") or "").strip()
    if room_id and chat_spec:
        chat_room_service.update_chat_room(
            room_id,
            mode=str(chat_spec.get("mode") or ""),
            purpose=str(chat_spec.get("purpose") or ""),
            config={"source": _BUNDLE_SOURCE, "teamId": team["teamId"]},
        )
    canvas = normalized.get("canvas")
    if isinstance(canvas, dict) and canvas.get("nodes"):
        node_agent_by_key = {agent["agentId"]: agent for agent in agent_by_key.values()}
        remapped_nodes: list[dict[str, Any]] = []
        for node in canvas.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            node_agent_id = str(node.get("agentId") or "")
            if node_agent_id and node_agent_id in agent_id_by_key:
                node["agentId"] = agent_id_by_key[node_agent_id]
            remapped_nodes.append(node)
        canvas["nodes"] = remapped_nodes
        team_service.save_team_canvas(str(team["teamId"]), canvas)
    report["result"] = {
        "teamId": team["teamId"],
        "agents": created_or_updated,
    }
    report["status"] = "completed"
    return report
