"""Exact Launcher platform approval metadata; native argument hashes own consent."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata

from pydantic import ValidationError
from .team_management_approval import TEAM_MANAGEMENT_ACTIONS, team_management_approval_summary

PLATFORM_MANAGEMENT_ACTIONS = frozenset({"dispatch_cancel", "runtime_command", "team_update", "team_recovery_confirm_deployment",
    "agent_parameters_update", "agent_prompt_update",
    "agent_tool_policy_update", "knowledge_acl_grant", "knowledge_acl_revoke", "flow_save", "flow_start", "agent_dispatch_access_set", *TEAM_MANAGEMENT_ACTIONS})


def _digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _decimal_values(value):
    if type(value) is int:
        return str(value)
    if isinstance(value, list):
        return [_decimal_values(item) for item in value]
    if isinstance(value, dict):
        return {key: _decimal_values(item) for key, item in value.items()}
    return value


def _displayable(value):
    if isinstance(value, str):
        return not any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value)
    if isinstance(value, list):
        return all(_displayable(item) for item in value)
    if isinstance(value, dict):
        return all(_displayable(key) and _displayable(item) for key, item in value.items())
    return True


def platform_management_approval_summary(action, parameters):
    """Validate the executable DTO, then expose only identity and scope metadata.

    Fixed user-content isolation is distinct from missing authorization details.
    The former remains reviewable; the latter disables manual acceptance. This
    function does not add an approval requirement or alter full_access policy.
    """
    if action in TEAM_MANAGEMENT_ACTIONS:
        return team_management_approval_summary(action, parameters)
    if action not in PLATFORM_MANAGEMENT_ACTIONS:
        raise ValueError("Unknown platform management action")
    from .actions import _management_contracts
    try:
        validated = _management_contracts()[action][0].model_validate(parameters)
        values = validated.model_dump()
        explicit = validated.model_dump(exclude_unset=True)
        fingerprint = _digest(values)
    except (ValidationError, TypeError, KeyError, UnicodeError, RecursionError) as error:
        raise ValueError("Invalid platform management arguments") from error
    target_keys = {"project_id", "request_id", "dispatch_id", "native_task_id", "agent_id", "team_id", "flow_id",
        "kind", "resource_id", "session_id", "knowledge_base_id", "target_agent_id", "expected_revision",
        "expected_config_revision", "expected_agent_updated_at", "expected_policy_fingerprint",
        "expected_registry_version", "expected_registry_fingerprint", "expected_team_fingerprint",
        "expected_acl_fingerprint", "expectedRevision", "expected_public_config_hash", "expected_eligibility_fingerprint",
        "expected_template_id", "expected_content_hash", "run_id"}
    targets = {key: str(value) for key, value in values.items() if key in target_keys and value not in (None, "")}
    for key, value in targets.items():
        if not _displayable(value):
            raise ValueError("Platform target cannot be displayed safely")
        if (key in {"project_id", "agent_id", "team_id", "flow_id", "resource_id", "session_id", "native_task_id", "target_agent_id"}
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", value) is None):
            raise ValueError("Platform target identity is invalid")
    delta, content_omitted, details_omitted = {}, False, False
    if action == "dispatch_cancel":
        changed, delta = ["stopRequested"], {"operation": "request_stop"}
    elif action == "runtime_command":
        changed, delta = ["command"], {"command": values["command"]}
    elif action == "team_recovery_confirm_deployment":
        changed, delta = ["deploymentEvidence"], {"evidenceRef": values["evidence_ref"],
            "evidenceDigest": _digest(values["evidence_ref"]), "verificationRequired": True,
            "resumesOriginalRunOnly": True}
    elif action == "agent_dispatch_access_set":
        changed, delta = ["enabled"], {"enabled": values["enabled"]}
    elif action == "agent_parameters_update":
        changed = [values["kind"]]
        delta = _decimal_values(values["parameters"])
    elif action == "agent_prompt_update":
        changed = sorted(["promptTemplateId", "promptContent"])
        delta = {"scope": "single_agent_copy_on_write", "contentChars": str(len(values["content"])),
                 "contentDigest": _digest(values["content"]), "activation": "next_submission"}
        content_omitted = True
    elif action.startswith("knowledge_acl_"):
        changed, delta = ["permissions"], {"permissions": values["permissions"]}
    elif action == "agent_tool_policy_update":
        updates = explicit["updates"]
        changed = sorted(updates)
        delta = _decimal_values(updates)
        if "blockedCommandPatterns" in delta:
            patterns = delta.pop("blockedCommandPatterns")
            delta.update(blockedCommandPatternsCount=str(len(patterns)), blockedCommandPatternsDigest=_digest(patterns))
            details_omitted = True
    elif action == "team_update":
        updates = explicit["updates"]
        changed = sorted(updates)
        if "name" in updates:
            delta["name"] = updates["name"]
        for field in ("description", "purpose"):
            if field in updates:
                delta[field + "Chars"] = str(len(updates[field]))
                delta[field + "Digest"] = _digest(updates[field])
                content_omitted |= bool(updates[field])
        if "members" in updates:
            members = values["updates"]["members"]
            from core.web.services import team_knowledge_service as knowledge
            roles = []
            for member in members:
                effective = knowledge._member_role({"members": [member]}, member["agentId"])
                roles.append({"memberId": member["memberId"], "agentId": member["agentId"], "role": member["role"],
                    "effectiveRole": effective, "knowledgeReviewEligible": effective in knowledge.REVIEW_ROLES})
            delta.update(memberAgentIds=[item["agentId"] for item in members],
                memberIds=[item["memberId"] for item in members], membersMode="replace",
                memberRoles=roles, membersDigest=_digest(members), memberCount=str(len(members)))
            content_omitted |= any(item["purpose"] or item["responsibilities"] for item in members)
    elif action == "flow_save":
        flow = values["flow"]
        changed = ["flow"]
        delta = {"fieldIds": [item["id"] for item in flow["fields"]],
            "fieldKinds": [item["kind"] for item in flow["fields"]],
            "requiredFieldIds": [item["id"] for item in flow["fields"] if item["required"]],
            "optionCounts": [str(len(item["options"])) for item in flow["fields"]],
            "nodeIds": [item["id"] for item in flow["steps"]], "nodeKinds": [item["kind"] for item in flow["steps"]],
            "nodeOwners": [item["owner"] for item in flow["steps"]],
            "nodeSourceRefs": [item["researchSource"] or item["sessionSource"] or {} for item in flow["steps"]],
            "instructionNodeIds": [item["id"] for item in flow["steps"] if item["instruction"]],
            "definitionDigest": _digest(flow), "recoveryPolicyDigest": _digest(flow["failureRecovery"])}
        content_omitted = True
    else:  # flow_start: input names and sizes are scope; values remain private.
        changed = ["values"]
        names = sorted(values["values"])
        if any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name) is None for name in names):
            raise ValueError("Invalid Flow input identity")
        delta = {"inputIds": names, "inputValueLengths": {name: str(len(values["values"][name])) for name in names},
                 "inputsDigest": _digest(values["values"]), "localIntegration": False}
        content_omitted = bool(names)
    summary = {"assistantPlatformPreviewVersion": 1, "assistantAction": action, "assistantTargets": targets,
        "assistantParametersDigest": fingerprint, "assistantChangedFields": changed, "assistantDelta": delta,
        "assistantContentOmitted": bool(content_omitted), "assistantDetailsOmitted": bool(details_omitted)}
    if not _displayable(delta) or len(json.dumps(summary, ensure_ascii=False)) > 16000:
        summary.update(assistantDetailsOmitted=True, assistantDelta={"omittedFields": changed, "digest": _digest(delta)})
    if action.startswith("knowledge_acl_"):
        summary["assistantPermissions"] = values["permissions"]
    return summary
