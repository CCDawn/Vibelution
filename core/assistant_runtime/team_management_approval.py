"""Launcher-only, body-free Team consent scope over the executable contracts."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata


TEAM_MANAGEMENT_ACTIONS = frozenset({"team_create", "team_member_add", "team_member_remove", "team_archive"})


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _displayable(value):
    if isinstance(value, str):
        return not any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in value)
    if isinstance(value, list):
        return all(_displayable(item) for item in value)
    if isinstance(value, dict):
        return all(_displayable(key) and _displayable(item) for key, item in value.items())
    return True


def _member_scope(members):
    from core.web.services import team_knowledge_service as knowledge
    roles = []
    for member in members:
        effective = knowledge._member_role({"members": [member]}, member["agentId"])
        roles.append({"memberId": member["memberId"], "agentId": member["agentId"], "role": member["role"],
            "effectiveRole": effective, "knowledgeReviewEligible": effective in knowledge.REVIEW_ROLES})
    return {"memberAgentIds": [item["agentId"] for item in members],
        "memberIds": [item["memberId"] for item in members], "memberRoles": roles,
        "membersDigest": _digest(members), "memberCount": str(len(members))}


def team_management_approval_summary(action, parameters):
    """A displayed scope never grants consent; native tool arguments bind it."""
    from core.web.services.external_management.team_lifecycle_contracts import TEAM_LIFECYCLE_ACTION_MODELS
    if action not in TEAM_MANAGEMENT_ACTIONS or not isinstance(parameters, dict):
        raise ValueError("Unknown Team management action")
    project_id, request_id = parameters.get("project_id"), parameters.get("request_id")
    if (not isinstance(project_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", project_id)
            or not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", request_id)):
        raise ValueError("Invalid Team management identity")
    args = TEAM_LIFECYCLE_ACTION_MODELS[action].model_validate(
        {key: value for key, value in parameters.items() if key not in {"project_id", "request_id"}}).model_dump()
    values = {**args, "project_id": project_id, "request_id": request_id}
    targets = {"project_id": project_id, "request_id": request_id}
    for key in ("team_id", "expected_team_fingerprint", "agent_id", "expected_linked_chat_room_id"):
        if args.get(key):
            targets[key] = args[key]
    content_omitted = False
    if action == "team_create":
        changed = ["team"]
        delta = {"operation": "create", "name": args["name"], "teamKind": "custom",
            **{key + "Chars": str(len(args[key])) for key in ("description", "purpose")},
            **{key + "Digest": _digest(args[key]) for key in ("description", "purpose")},
            **_member_scope(args["members"])}
        content_omitted = any(args[key] for key in ("description", "purpose")) or any(
            member["purpose"] or member["responsibilities"] for member in args["members"])
    elif action == "team_member_add":
        changed, delta = ["members"], {"operation": "add", **_member_scope([args["member"]])}
        content_omitted = bool(args["member"]["purpose"] or args["member"]["responsibilities"])
    elif action == "team_member_remove":
        changed, delta = ["members"], {"operation": "remove", "removedAgentId": args["agent_id"],
            "preservesAgent": True, "preservesHistory": True, "explicitKnowledgeGrantsUnchanged": True}
    else:
        changed = ["status", "members", "sessions", "linkedChatRooms"]
        delta = {"operation": "archive", "memberAgentIds": args["expected_member_agent_ids"],
            "memberCount": str(len(args["expected_member_agent_ids"])),
            "linkedChatRoomId": args["expected_linked_chat_room_id"],
            "archivesMemberAgents": True, "freezesMemberSessions": True,
            "deletesLinkedChatRooms": True, "clearsOtherMemberRoomAssociations": True,
            "dissolvesEmptyMemberRooms": True, "keepsTeamKnowledgeAndFlows": True}
    summary = {"assistantPlatformPreviewVersion": 1, "assistantAction": action, "assistantTargets": targets,
        "assistantParametersDigest": _digest(values), "assistantChangedFields": changed,
        "assistantDelta": delta, "assistantContentOmitted": bool(content_omitted), "assistantDetailsOmitted": False}
    if not _displayable(targets) or not _displayable(delta):
        raise ValueError("Team consent scope cannot be displayed safely")
    if len(json.dumps(summary, ensure_ascii=False)) > 16000:
        summary.update(assistantDetailsOmitted=True, assistantDelta={"omittedFields": changed, "digest": _digest(delta)})
    return summary
