"""Unified Team / Role format contract validators.

This module is the machine-checkable companion of
``docs/standards/unified-team-format.md``. It freezes the canonical shapes
that all four team systems (通用 / 科研 / 进化 / 金融) converge on:

- Team = manifest (``teamId``/``name``/``purpose``/``status``/
  ``linkedChatRoomId`` + member rows). Member rows are written by
  ``canvas_normalize._normalize_members`` and that shape is authoritative.
- Role = declarative definition (``ROLE_DEFINITION_FIELDS``) carried by the
  workspace role file layer (``role_definition_service``: one markdown file
  per role under ``workspace/roles/``).
- Model / prompt configuration is NEVER stored in team or role records:
  ``workspace/agents/agents.json`` (``llmBindings``, ``promptTemplateId``)
  is the sole authority. Team projections may surface a read-only
  ``model`` summary (``team_projection._member_model_summary``) at API
  response time only.

Pure functions only: nothing here writes any store. Reference checks take
explicit ``known_agent_ids``; when omitted, the Agent directory is read
(read-only) at call time.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any

__all__ = [
    "MEMBER_ROW_FIELDS",
    "ROLE_DEFINITION_FIELDS",
    "PERSONA_PROFILE_FIELDS",
    "TASK_PROFILE_FIELDS",
    "TOOL_POLICY_FIELDS",
    "MODEL_LITERAL_KEYS",
    "MAX_MEMBER_ROWS",
    "MAX_MEMBER_ID_LENGTH",
    "MAX_RESPONSIBILITIES_PER_MEMBER",
    "validate_team_record",
    "validate_member_row",
    "validate_role_definition",
    "load_known_agent_ids",
]

# --- canonical member row (canvas_normalize._normalize_members) -----------

MEMBER_ROW_FIELDS = frozenset(
    {
        "memberId",
        "agentId",
        "agentCode",
        "agentName",
        "role",
        "purpose",
        "responsibilities",
        "agentStatus",
    }
)

# The canonical writer emits "active"; "archived" is tolerated for rows that
# survived an Agent archive without team repair.
MEMBER_STATUS_VALUES = frozenset({"active", "archived"})

MAX_MEMBER_ROWS = 120  # matches canvas_normalize._normalize_members cap
MAX_MEMBER_ID_LENGTH = 96  # matches s._safe_token(max_length=96)
MAX_RESPONSIBILITIES_PER_MEMBER = 8  # matches _normalize_members slice

# --- canonical role definition (role file layer golden shape) --------------

ROLE_DEFINITION_FIELDS = frozenset(
    {
        "roleKey",
        "role",
        "purpose",
        "responsibilities",
        "agentName",
        "personaProfile",
        "taskProfile",
        "toolPolicy",
    }
)

PERSONA_PROFILE_FIELDS = frozenset(
    {
        "personality",
        "communicationStyle",
        "background",
        "identityNotes",
        "expertise",
    }
)

TASK_PROFILE_FIELDS = frozenset(
    {
        "mission",
        "responsibilities",
        "preferredTasks",
        "avoidTasks",
        "successCriteria",
        "constraints",
        "deliverables",
    }
)

TOOL_POLICY_FIELDS = frozenset(
    {
        "allowedTools",
        "preferredTools",
        "writeScopes",
    }
)

# Keys that embed a resolved model / prompt value instead of a reference to
# agents.json. Their presence in a team or role record is always a contract
# violation: agents.json is the sole model/prompt authority.
MODEL_LITERAL_KEYS = frozenset(
    {
        "model",
        "modelId",
        "model_id",
        "dialogueModelId",
        "llm",
        "llmBindings",
        "provider",
        "prompt",
        "promptText",
        "systemPrompt",
    }
)

# Optional reference key: a role may point at an agents.json llmBindings slot
# (e.g. "dialogue"); the resolved model id still lives only in agents.json.
MODEL_REFERENCE_KEY = "modelRef"


def _issue(severity: str, code: str, message: str, *, path: str = "") -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message, "path": path}


def _has_errors(issues: Iterable[dict[str, str]]) -> bool:
    return any(item.get("severity") == "error" for item in issues)


def _summary(issues: list[dict[str, str]]) -> dict[str, int]:
    return {
        "errorCount": sum(1 for item in issues if item.get("severity") == "error"),
        "warningCount": sum(1 for item in issues if item.get("severity") == "warning"),
        "issueCount": len(issues),
    }


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _agent_llm_slot_values() -> frozenset[str]:
    """Slot names accepted as model references (agents.json llmBindings keys)."""

    from core.llm.agent_runtime import AGENT_LLM_SLOTS

    return frozenset(str(slot) for slot in AGENT_LLM_SLOTS)


def load_known_agent_ids() -> set[str]:
    """Read-only snapshot of every Agent id in the workspace agents.json."""

    from core.web.services import agent_directory_service

    return {
        str(agent.get("agentId") or "").strip()
        for agent in agent_directory_service.list_agents(include_archived=True)
        if isinstance(agent, dict) and str(agent.get("agentId") or "").strip()
    }


def _check_no_model_literals(payload: dict[str, Any], issues: list[dict[str, str]], *, path: str) -> None:
    for key in sorted(MODEL_LITERAL_KEYS & set(payload)):
        issues.append(
            _issue(
                "error",
                "model_literal_forbidden",
                f"字段 {key} 内嵌了模型/提示词字面值；模型与提示词权威在 agents.json，记录内只允许引用。",
                path=f"{path}.{key}" if path else key,
            )
        )


def validate_member_row(
    member: Any,
    *,
    known_agent_ids: Collection[str] | None = None,
    path: str = "",
) -> list[dict[str, str]]:
    """Validate one member row against the canonical shape.

    ``known_agent_ids`` restricts ``agentId`` to ids present in the Agent
    directory (agents.json). ``None`` skips the existence check (shape-only).
    """

    where = path or "members[]"
    if not isinstance(member, dict):
        return [_issue("error", "member_not_object", "成员行必须是对象。", path=where)]

    issues: list[dict[str, str]] = []
    agent_id = str(member.get("agentId") or "").strip()
    if not agent_id:
        issues.append(_issue("error", "member_missing_agent_id", "成员行缺少 agentId。", path=f"{where}.agentId"))
    elif known_agent_ids is not None and agent_id not in set(known_agent_ids):
        issues.append(
            _issue(
                "error",
                "member_unknown_agent_id",
                f"成员行引用的 Agent 不存在于 agents.json：{agent_id}",
                path=f"{where}.agentId",
            )
        )

    member_id = member.get("memberId")
    if not _nonempty_str(member_id):
        issues.append(_issue("error", "member_missing_id", "成员行缺少非空 memberId。", path=f"{where}.memberId"))
    elif len(str(member_id)) > MAX_MEMBER_ID_LENGTH:
        issues.append(
            _issue("error", "member_id_too_long", f"memberId 超过 {MAX_MEMBER_ID_LENGTH} 字符上限。", path=f"{where}.memberId")
        )

    for key in ("agentCode", "agentName", "role", "purpose"):
        if not isinstance(member.get(key), str):
            issues.append(_issue("error", "member_field_not_string", f"成员行字段 {key} 必须是字符串。", path=f"{where}.{key}"))
    if isinstance(member.get("role"), str) and "\n" in str(member.get("role")):
        issues.append(_issue("error", "member_role_multiline", "成员行 role 限单行。", path=f"{where}.role"))

    responsibilities = member.get("responsibilities")
    if not _str_list(responsibilities):
        issues.append(
            _issue("error", "member_responsibilities_not_string_list", "responsibilities 必须是字符串数组。", path=f"{where}.responsibilities")
        )
    elif len(responsibilities) > MAX_RESPONSIBILITIES_PER_MEMBER:
        issues.append(
            _issue(
                "error",
                "member_responsibilities_too_many",
                f"responsibilities 超过 {MAX_RESPONSIBILITIES_PER_MEMBER} 条上限。",
                path=f"{where}.responsibilities",
            )
        )

    status = member.get("agentStatus")
    if str(status or "").strip() not in MEMBER_STATUS_VALUES:
        issues.append(
            _issue("error", "member_invalid_status", f"agentStatus 必须是 {sorted(MEMBER_STATUS_VALUES)} 之一。", path=f"{where}.agentStatus")
        )

    unknown = set(member) - MEMBER_ROW_FIELDS
    if MODEL_LITERAL_KEYS & unknown:
        _check_no_model_literals(member, issues, path=where)
        unknown -= MODEL_LITERAL_KEYS
    if unknown:
        issues.append(
            _issue("warning", "member_unknown_field", f"成员行含未登记字段（前向兼容，不阻断）：{sorted(unknown)}", path=where)
        )
    return issues


def validate_team_record(
    team: Any,
    *,
    known_agent_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Validate a stored/normalized Team manifest record.

    This checks the storage layer (``canvas_normalize._normalize_members``
    output), not API responses; the API projection may add a read-only
    ``model`` summary per member at response time.

    When ``known_agent_ids`` is omitted, the Agent directory is read
    (read-only) to resolve the current agents.json id set.
    """

    if not isinstance(team, dict):
        return {
            "valid": False,
            "summary": _summary([_issue("error", "team_not_object", "团队记录必须是对象。")]),
            "issues": [_issue("error", "team_not_object", "团队记录必须是对象。")],
        }

    issues: list[dict[str, str]] = []
    if not _nonempty_str(team.get("teamId")):
        issues.append(_issue("error", "team_missing_id", "团队清单缺少非空 teamId。", path="teamId"))
    if not _nonempty_str(team.get("name")):
        issues.append(_issue("error", "team_missing_name", "团队清单缺少非空 name。", path="name"))
    if not isinstance(team.get("purpose"), str):
        issues.append(_issue("error", "team_purpose_not_string", "purpose 必须是字符串（可为空）。", path="purpose"))
    if not isinstance(team.get("linkedChatRoomId"), str):
        issues.append(_issue("error", "team_room_ref_not_string", "linkedChatRoomId 必须是字符串（可为空，待链接）。", path="linkedChatRoomId"))

    from core.web.services.team.team_constants import TEAM_STATUSES

    status = str(team.get("status") or "").strip()
    if status not in TEAM_STATUSES:
        issues.append(_issue("error", "team_invalid_status", f"status 必须是 {sorted(TEAM_STATUSES)} 之一。", path="status"))

    members = team.get("members")
    if not isinstance(members, list):
        issues.append(_issue("error", "team_members_not_list", "members 必须是成员行数组。", path="members"))
    else:
        if len(members) > MAX_MEMBER_ROWS:
            issues.append(_issue("error", "team_members_too_many", f"成员数超过 {MAX_MEMBER_ROWS} 上限。", path="members"))
        resolved_ids = set(known_agent_ids) if known_agent_ids is not None else None
        seen_agent_ids: set[str] = set()
        for index, member in enumerate(members):
            row_issues = validate_member_row(member, known_agent_ids=resolved_ids, path=f"members[{index}]")
            issues.extend(row_issues)
            if isinstance(member, dict):
                agent_id = str(member.get("agentId") or "").strip()
                if agent_id:
                    if agent_id in seen_agent_ids:
                        issues.append(
                            _issue("error", "team_duplicate_agent_id", f"同一 Agent 重复加入成员行：{agent_id}", path=f"members[{index}].agentId")
                        )
                    seen_agent_ids.add(agent_id)

    _check_no_model_literals(team, issues, path="")

    return {"valid": not _has_errors(issues), "summary": _summary(issues), "issues": issues}


def validate_role_definition(role: Any) -> dict[str, Any]:
    """Validate a role definition against the role file layer field set.

    Model semantics: a role may optionally carry ``modelRef`` pointing at an
    agents.json ``llmBindings`` slot (reference). Any resolved model or
    prompt literal (``model``/``modelId``/``prompt``/...) is rejected.
    """

    if not isinstance(role, dict):
        return {
            "valid": False,
            "summary": _summary([_issue("error", "role_not_object", "角色定义必须是对象。")]),
            "issues": [_issue("error", "role_not_object", "角色定义必须是对象。")],
        }

    issues: list[dict[str, str]] = []
    for key in ("roleKey", "role", "purpose", "agentName"):
        if not _nonempty_str(role.get(key)):
            issues.append(_issue("error", "role_missing_field", f"角色定义缺少非空 {key}。", path=key))

    responsibilities = role.get("responsibilities")
    if not _str_list(responsibilities) or not responsibilities:
        issues.append(_issue("error", "role_responsibilities_invalid", "responsibilities 必须是非空字符串数组。", path="responsibilities"))

    sections = (
        ("personaProfile", PERSONA_PROFILE_FIELDS),
        ("taskProfile", TASK_PROFILE_FIELDS),
        ("toolPolicy", TOOL_POLICY_FIELDS),
    )
    for section_name, required_fields in sections:
        section = role.get(section_name)
        if not isinstance(section, dict):
            issues.append(_issue("error", "role_section_missing", f"角色定义缺少 {section_name} 小节。", path=section_name))
            continue
        missing = required_fields - set(section)
        if missing:
            issues.append(
                _issue("error", "role_section_field_missing", f"{section_name} 缺少字段：{sorted(missing)}", path=section_name)
            )
        if section_name == "personaProfile" and not _str_list(section.get("expertise")):
            issues.append(_issue("error", "role_expertise_invalid", "personaProfile.expertise 必须是字符串数组。", path="personaProfile.expertise"))
        for field_name in ("allowedTools", "preferredTools", "writeScopes"):
            if section_name == "toolPolicy" and field_name in section and not _str_list(section.get(field_name)):
                issues.append(_issue("error", "role_tool_list_invalid", f"toolPolicy.{field_name} 必须是字符串数组。", path=f"toolPolicy.{field_name}"))

    _check_no_model_literals(role, issues, path="")

    model_ref = role.get(MODEL_REFERENCE_KEY)
    if MODEL_REFERENCE_KEY in role:
        slot_values = _agent_llm_slot_values()
        if not isinstance(model_ref, str) or model_ref.strip() not in slot_values:
            issues.append(
                _issue(
                    "error",
                    "role_model_ref_not_slot",
                    f"{MODEL_REFERENCE_KEY} 必须是 agents.json llmBindings 槽位引用（{sorted(slot_values)}），不能是具体模型字面值。",
                    path=MODEL_REFERENCE_KEY,
                )
            )

    return {"valid": not _has_errors(issues), "summary": _summary(issues), "issues": issues}
