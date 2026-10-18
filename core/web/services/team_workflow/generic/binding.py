"""Recovery-role opt-in over existing Team, Agent policy and flow authorities.

No Agent, Session, permission preset, tool grant or second registry is created.
The one CAS write is the existing source flow's recovery policy. Active runs
reference that live opt-in while retaining their own frozen execution recipe.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import nullcontext
import uuid

from . import native, service, store
from .models import Flow, RecoveryBindingRequest, RecoveryBindingRevoke, RecoveryBindingStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def authorization_lock(team_id: str, source: dict):
    """Serialize revocation with admission; always acquire before run locks."""
    flow = source.get("flow") or {}
    if (flow.get("failureRecovery") or {}).get("bindingId"):
        return store.locked(store.path(team_id, "flows", flow["id"]))
    return nullcontext()


def _agent_fingerprint(team_id: str, agent_id: str) -> str:
    from core.web.services import agent_directory_service as directory

    native.validate_owner(team_id, agent_id)
    agent = directory.get_agent(agent_id, include_archived=False)
    policy = (agent or {}).get("toolPolicy")
    if not agent or not isinstance(policy, dict) or "allowedTools" not in policy:
        raise store.WorkflowError("角色的工具授权尚未解析，不能启用自动恢复。")
    return service.digest({"toolPolicy": directory.tool_policy_fingerprint(policy),
                           "permissionPreset": agent.get("permissionPreset", ""),
                           "primaryMode": agent.get("primaryMode", ""), "roleKey": agent.get("roleKey", "")})


def _assistant_ready(agent_id: str) -> None:
    from core.web.services.personal_assistant_service import get_personal_assistant

    assistant = get_personal_assistant().get("assistant") or {}
    if assistant.get("agentId") != agent_id or assistant.get("setupStatus") != "ready":
        raise store.WorkflowError("绑定必须使用已就绪的个人助理唯一身份。")


def bind_recovery(team_id: str, flow_id: str, payload: dict) -> dict:
    request = RecoveryBindingRequest.model_validate(payload)
    source = Flow.model_validate(store.read(store.path(team_id, "flows", flow_id))).model_dump()
    store.check_revision(source, request.expectedRevision)
    _assistant_ready(request.assistantAgentId)
    roles = {request.assistantAgentId, request.directorAgentId, request.developerAgentId, request.reviewerAgentId}
    source_owners = {step["owner"] for step in source["steps"] if service.executable(step)}
    fingerprints = {agent_id: _agent_fingerprint(team_id, agent_id) for agent_id in sorted(roles | source_owners)}
    template = Flow.model_validate(store.read(store.path(team_id, "flows", request.repairFlowId))).model_dump()
    policy = {key: value for key, value in request.model_dump().items()
              if key not in {"expectedRevision", "acknowledgeAutomaticRecovery", "validForSeconds"}}
    policy.update(bindingId="binding-" + uuid.uuid4().hex, agentPolicyFingerprints=fingerprints,
                  repairFlowRevision=template["revision"],
                  expiresAt=(utc_now() + timedelta(seconds=request.validForSeconds)).isoformat())
    source["failureRecovery"] = policy
    from .recovery import freeze_repair_template

    freeze_repair_template(team_id, source)
    service.save_flow(team_id, flow_id, {"flow": source, "expectedRevision": request.expectedRevision})
    _log(team_id, flow_id, "bound", policy["bindingId"])
    return get_recovery_binding(team_id, flow_id)


def revoke_recovery(team_id: str, flow_id: str, payload: dict) -> dict:
    request = RecoveryBindingRevoke.model_validate(payload)
    source = Flow.model_validate(store.read(store.path(team_id, "flows", flow_id))).model_dump()
    store.check_revision(source, request.expectedRevision)
    binding_id = (source.get("failureRecovery") or {}).get("bindingId", "")
    if not binding_id:
        raise store.Conflict("流程没有可撤销的角色绑定。")
    source["failureRecovery"] = None
    service.save_flow(team_id, flow_id, {"flow": source, "expectedRevision": request.expectedRevision})
    _log(team_id, flow_id, "revoked", binding_id)
    service._wake()
    return get_recovery_binding(team_id, flow_id)


def authorization_reason(team_id: str, source: dict) -> str:
    """Empty means the frozen run may still use its original recovery opt-in."""
    if not isinstance(source.get("flow"), dict):
        return "recovery_authorization_unavailable"
    policy = source["flow"].get("failureRecovery") or {}
    if not policy.get("bindingId"):
        return ""  # Compatibility: pre-binding flows retain their frozen semantics.
    try:
        if utc_now() >= datetime.fromisoformat(policy["expiresAt"]):
            return "recovery_authorization_expired"
        current = store.read(store.path(team_id, "flows", source["flow"]["id"]))
        if current.get("failureRecovery") != policy:
            return "recovery_authorization_revoked_or_changed"
        refs = lambda flow: [(step["kind"], step.get("researchSource"), step.get("sessionSource"))
                             for step in flow.get("steps", []) if step["kind"] in {"research", "session"}]
        if refs(current) != refs(source["flow"]):
            return "recovery_source_changed"
        _assistant_ready(policy["assistantAgentId"])
        for agent_id, fingerprint in policy["agentPolicyFingerprints"].items():
            if _agent_fingerprint(team_id, agent_id) != fingerprint:
                return "recovery_role_policy_changed"
    except (ValueError, KeyError, OSError):
        return "recovery_authorization_unavailable"
    return ""


def dispatch_authorization_reason(team_id: str, source: dict, attempt: dict) -> str:
    reason = authorization_reason(team_id, source)
    policy = source["flow"].get("failureRecovery") or {}
    if reason or not policy.get("bindingId"):
        return reason
    try:
        from core.web.services import agent_directory_service as directory
        from core.web.services.agent_tool_governance_service import temporary_granted_tools_for_agent

        agent = directory.get_agent(attempt["agentId"], include_archived=False)
        allowed = set((agent or {}).get("toolPolicy", {}).get("allowedTools", []))
        grants = temporary_granted_tools_for_agent(attempt["agentId"],
            session_id=attempt["sessionId"], turn_id=attempt.get("turnId", ""))
        if set(grants) - allowed:
            return "recovery_session_policy_changed"
    except (ValueError, KeyError, OSError):
        return "recovery_authorization_unavailable"
    if service.supervised(source):
        from .source_adapter import fence
        return fence(source)
    return ""


def get_recovery_binding(team_id: str, flow_id: str) -> dict:
    source = Flow.model_validate(store.read(store.path(team_id, "flows", flow_id))).model_dump()
    policy = source.get("failureRecovery") or {}
    reason = authorization_reason(team_id, {"flow": source}) if policy.get("bindingId") else ""
    status = ("unbound" if not policy else "legacy" if not policy.get("bindingId") else
              "expired" if reason == "recovery_authorization_expired" else "unavailable" if reason else "ready")
    if status == "ready":
        try:
            template = store.read(store.path(team_id, "flows", policy["repairFlowId"]))
            if template["revision"] != policy["repairFlowRevision"]:
                status, reason = "unavailable", "recovery_recipe_changed"
        except (ValueError, KeyError, OSError):
            status, reason = "unavailable", "recovery_recipe_unavailable"
    return RecoveryBindingStatus(teamId=team_id, flowId=flow_id, sourceRevision=source["revision"],
        status=status, reason=reason, **{key: policy.get(key, "") for key in (
            "bindingId", "expiresAt", "assistantAgentId", "directorAgentId", "developerAgentId",
            "reviewerAgentId", "repairFlowId")}).model_dump()


def _log(team_id: str, flow_id: str, outcome: str, binding_id: str) -> None:
    from core.web.services.runtime_scene_service import record_runtime_scene_event

    record_runtime_scene_event("team_workflow", "recovery_binding", "generic_workflow.recovery_binding.changed",
        outcome=outcome, lifecycle=True, fields={"teamId": team_id, "flowId": flow_id, "bindingId": binding_id})
