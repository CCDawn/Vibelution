"""Read-only campaign delegation from the existing Team flow binding authority."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from core.runtime_manager.work_run_store import WorkRunStore

from .self_evolution_local_integration import LocalIntegrationError
from .team_workflow.generic import binding, code_repair, store


_SOURCE = "campaign_role_binding_v1"
_REFERENCE_KEYS = ("teamId", "flowId", "bindingId", "expiresAt")


def _marked(grant: dict) -> bool:
    return ("campaignRoleBinding" in grant
            or grant.get("roleBindingSource") == _SOURCE)


def _grant(context: dict) -> dict:
    grant = context.get("localIntegrationAuthorization")
    if grant is not None and not isinstance(grant, dict):
        raise LocalIntegrationError("Campaign binding authorization is invalid.")
    return grant or {}


def _origin(context: dict) -> tuple[dict, tuple[str, str] | None]:
    """Locate canonical campaign request; caller role/Agent fields are irrelevant."""
    owner = context
    child = "_campaignSource" in context
    if child:
        from . import self_evolution_campaign_service as campaigns

        source = context["_campaignSource"]
        if (not isinstance(source, dict) or not isinstance(source.get("storeRoot"), str)
                or not source["storeRoot"] or not isinstance(source.get("campaignId"), str)):
            raise LocalIntegrationError("Campaign binding private source is missing or invalid.")
        try:
            owner = campaigns._load(WorkRunStore(root=Path(source["storeRoot"])), source["campaignId"])
        except (ValueError, TypeError, KeyError, OSError) as exc:
            raise LocalIntegrationError("Campaign binding canonical source is unavailable.") from exc
    request = owner.get("request") or {}
    if not isinstance(request, dict):
        raise LocalIntegrationError("Campaign binding request is invalid.")
    if "roleBindingFlowId" not in request:
        if _marked(_grant(owner)) or _marked(_grant(context)):
            raise LocalIntegrationError("Campaign role binding source was removed.")
        return owner, None
    local = request.get("localIntegration") or {}
    try:
        team_id = store.token(local["teamId"])
        flow_id = store.token(request["roleBindingFlowId"])
        if child and (context.get("request") or {}).get("localIntegration", {}).get("teamId") != team_id:
            raise ValueError("team")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise LocalIntegrationError("Campaign role binding requires an exact Team and flow source.") from exc
    return owner, (team_id, flow_id)


def _check_reference(grant: dict, reference: dict, *, required: bool = False) -> None:
    if required or _marked(grant):
        if grant.get("roleBindingSource") != _SOURCE or grant.get("campaignRoleBinding") != reference:
            raise LocalIntegrationError("Campaign role binding authorization changed.")
    if grant and grant.get("teamId") != reference["teamId"]:
        raise LocalIntegrationError("Campaign role binding Team changed.")


def _checked(context: dict, *, expected: tuple[str, str] | None = None) -> tuple[dict, dict] | None:
    owner, origin = _origin(context)
    if expected is not None and origin != expected:
        raise LocalIntegrationError("Campaign role binding source changed while locking.")
    if origin is None:
        return None
    team_id, flow_id = origin
    try:
        flow = store.read(store.path(team_id, "flows", flow_id))
        status = binding.get_recovery_binding(team_id, flow_id)
        policy = flow.get("failureRecovery") or {}
        reference = {"teamId": team_id, "flowId": flow_id,
                     "bindingId": policy["bindingId"], "expiresAt": policy["expiresAt"]}
        expiry = datetime.fromisoformat(reference["expiresAt"])
        if (flow.get("id") != flow_id or status.get("status") != "ready"
                or not reference["bindingId"] or expiry.tzinfo is None
                or expiry <= datetime.now(timezone.utc)
                or {key: status.get(key) for key in _REFERENCE_KEYS} != reference
                or any(status.get(key) != policy.get(key) for key in (
                    "assistantAgentId", "directorAgentId", "developerAgentId", "reviewerAgentId"))):
            raise LocalIntegrationError("Campaign role binding is unavailable, changed or expired.")
        _check_reference(_grant(owner), reference, required=owner is not context)
        _check_reference(_grant(context), reference)
        roles = code_repair.bound_role_bindings({"flow": flow})
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise LocalIntegrationError("Campaign role binding is unavailable, changed or expired.") from exc
    return reference, roles


def campaign_bindings(context: dict) -> dict | None:
    """Resolve campaign roles only when its live canonical binding remains valid."""
    checked = _checked(context)
    return checked[1] if checked is not None else None


def bind_campaign_authority(context: dict, grant: dict) -> dict:
    """Freeze the live source reference and cap authority at the binding expiry."""
    checked = _checked(context)
    if checked is None:
        if _marked(grant):
            raise LocalIntegrationError("Campaign role binding source was removed.")
        return deepcopy(grant)
    reference, roles = checked
    _check_reference(grant, reference)
    if "principals" in grant and {role: value.get("agentId") for role, value in grant["principals"].items()} != {
            role: value["agentId"] for role, value in roles.items()}:
        raise LocalIntegrationError("Campaign principals differ from the authorized flow roles.")
    try:
        expiry = datetime.fromisoformat(grant["expiresAt"])
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError("expired")
        result = deepcopy(grant)
        result.update(roleBindingSource=_SOURCE, campaignRoleBinding=reference,
                      expiresAt=min(expiry, datetime.fromisoformat(reference["expiresAt"])).isoformat())
        return result
    except (KeyError, TypeError, ValueError) as exc:
        raise LocalIntegrationError("Campaign binding grant expiry is invalid.") from exc


@contextmanager
def binding_guard(context: dict):
    """Hold flow authority through final merge; acquire before campaign/run locks."""
    _, origin = _origin(context)
    if origin is None:
        yield
        return
    try:
        target = store.path(origin[0], "flows", origin[1])
    except (ValueError, TypeError, OSError) as exc:
        raise LocalIntegrationError("Campaign role binding source is unavailable.") from exc
    with store.locked(target):
        _checked(context, expected=origin)
        yield
