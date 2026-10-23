"""Object-shaped, bounded everyday platform actions for the canonical assistant.

Identity and ToolPolicy are enforced by the public tool wrapper. These adapters
never accept a URL, command, provider secret, or permission-policy update.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.web.services import agent_directory_service as directory


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AgentCreate(Arguments):
    display_name: str = Field(min_length=1, max_length=120)
    request_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    model_id: str = Field(default="", max_length=200)
    mission: str = Field(default="", max_length=2000)


class AgentUpdate(Arguments):
    agent_id: str = Field(min_length=1, max_length=128)
    updates: dict[str, Any]
    expected_config_revision: int | None = Field(default=None, ge=0)


class AgentAvatar(Arguments):
    agent_id: str = Field(min_length=1, max_length=128)
    avatar_image_path: str = Field(default="", max_length=256)
    reset_to_default: bool = False


class SettingsUpdate(Arguments):
    updates: list[dict[str, Any]] = Field(min_length=1, max_length=20)


class ModelAdd(Arguments):
    provider_id: str = Field(min_length=1, max_length=80)
    upstream_id: str = Field(min_length=1, max_length=200)
    model_key: str = Field(default="", max_length=120)
    label: str = Field(default="", max_length=120)


class TeamStatus(Arguments):
    team_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    wait_seconds: int = Field(default=0, ge=0, le=30)


SAFE_AGENT_FIELDS = frozenset({
    "displayName", "llmBindings", "personaProfile", "taskProfile",
    "reasoningEffortBySlot", "contextCompressionPolicy", "promptTemplateId",
})

_CONTRACTS = {
    "agent_create": (AgentCreate, "创建可接收派遣的普通 Agent；默认沿用助理对话模型，权限固定为消息协作，不授予文件/命令/授权管理。"),
    "agent_update": (AgentUpdate, "修改名称、模型、提示词、人物/任务档案或压缩设置；updates 使用 API camelCase 字段。权限、身份和生命周期变更走 manage。"),
    "agent_avatar": (AgentAvatar, "使用 avatar_options 中的现有图片或恢复模型默认头像。"),
    "settings_update": (SettingsUpdate, "更新应用用户名、头像预设、壁纸与普通设置；先 settings_catalog 取得 section/key/选项。"),
    "model_add": (ModelAdd, "为已配置 Provider 添加模型；不接收密钥或新网络地址。"),
    "team_status": (TeamStatus, "读取自己所建团队的原生状态、当前步骤与完成产物，可 wait_seconds 最多30秒；started/running 不代表完成。"),
}


def action_catalog(action: str = "") -> dict:
    if action:
        if action not in _CONTRACTS:
            raise ValueError("未知操作。先 action=index 查看可用操作。")
        model, description = _CONTRACTS[action]
        result = {"action": action, "description": description, "parameters": model.model_json_schema()}
        if action == "agent_update":
            from core.web.routes.agents import AgentUpdatePayload
            schema = AgentUpdatePayload.model_json_schema()
            result["updatesSchema"] = {
                **schema,
                "properties": {key: value for key, value in schema["properties"].items() if key in SAFE_AGENT_FIELDS},
                "additionalProperties": False,
            }
            result["example"] = {"agent_id": "<从概览取得>", "updates": {"displayName": "新名字"}}
        return result
    return {
        "actions": [{"action": key, "description": item[1]} for key, item in _CONTRACTS.items()],
        "readActions": ["index", "describe", "settings_catalog", "model_options", "avatar_options"],
        "governedActions": {"tool": "personal_assistant_manage_tool", "actions": ["team_run", "agent_archive", "session_stop", "session_delete", "knowledge_acl_grant", "restart"]},
        "hint": "describe 的 parameters 是对象；直接传 parameters，不要嵌套 JSON 字符串。创建时使用稳定 request_id，结果未知先核验，不换 key 重建。",
    }


def _agent_receipt(agent: dict, *, reused: bool = False) -> dict:
    return {"ok": True, "verified": True, "status": "completed", "agentId": agent["agentId"],
            "directSessionId": agent.get("directSessionId", ""),
            "displayName": agent.get("displayName", ""),
            "avatarImagePath": agent.get("avatarImagePath", ""),
            "modelId": directory.agent_dialogue_model_id(agent), "reused": reused}


def _create(args: AgentCreate, runtime: dict) -> dict:
    from core.infrastructure.atomic_io import atomic_write_json
    from core.infrastructure.file_lock import cross_process_file_lock
    from core.web.services.agent_operation_service import create_agent_from_catalog_request

    if not args.display_name.strip():
        raise ValueError("Agent 名称不能为空。")
    identity = [runtime["agentId"], runtime["sessionId"], args.request_id]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    fingerprint = hashlib.sha256(args.model_dump_json().encode()).hexdigest()
    path = directory._workspace_path("personal-assistant-actions", "agents", key + ".json")
    with cross_process_file_lock(path.with_suffix(".admission"), timeout=5):
        if path.exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
            if previous.get("fingerprint") != fingerprint:
                raise ValueError("request_id 已用于不同创建参数。")
            if previous.get("agentId"):
                agent = directory.get_agent(previous["agentId"])
                if agent and previous.get("status") == "completed":
                    return _agent_receipt(agent, reused=True)
                return {"ok": False, "status": "partial", "agentId": previous["agentId"],
                        "message": "Agent 已创建但配置未确认；请核验对象，不要重复创建。"}
            return {"ok": False, "status": "unknown", "message": "上次创建未确认；请核验现有 Agent，不要自动更换 request_id 重建。"}
        model_id = args.model_id.strip()
        if not model_id:
            actor = directory.get_agent(runtime["agentId"])
            model_id = directory.agent_dialogue_model_id(actor or {})
        if not model_id:
            raise ValueError("没有可用对话模型，请先配置模型。")
        atomic_write_json(path, {"fingerprint": fingerprint, "status": "pending"})
        try:
            agent = create_agent_from_catalog_request(
                display_name=args.display_name.strip(), primary_mode="chat", role_key="assistant_worker",
                prompt_template_id="prompt-chat-default", llm_bindings={"dialogue": {"modelId": model_id}},
                task_profile={"mission": args.mission or "执行用户或个人助理明确交办的任务，报告结果和依据。"},
                tool_policy={"allowedTools": ["agent_message_tool"], "preferredTools": ["agent_message_tool"],
                             "networkAccess": "none", "mutationAccess": "controlled", "writeScopes": ["private"],
                             "approvalOverrides": {"agent_message_tool": "never"}, "maxCallsPerTurn": 8},
                metadata={"personalAssistantCreatedBy": runtime["agentId"], "personalAssistantRequestKey": key},
                source="personal_assistant_action",
            )
            atomic_write_json(path, {"fingerprint": fingerprint, "status": "pending", "agentId": agent["agentId"]})
            # Native target admission and approval remain authoritative.
            agent = directory.update_agent_instance(agent["agentId"],
                permission_preset="request_approval",
                delegation_policy={"allowSubagents": False, "allowWakeMessages": True})
            observed = directory.get_agent(agent["agentId"])
            if not observed:
                return {"ok": False, "status": "unknown", "agentId": agent["agentId"], "message": "创建后未能核验对象，请先读取状态。"}
            atomic_write_json(path, {"fingerprint": fingerprint, "status": "completed", "agentId": agent["agentId"]})
            return _agent_receipt(observed)
        except Exception:
            return {"ok": False, "status": "unknown", "message": "创建未确认，已保留幂等记录；请核验平台对象后处理，不要自动重复创建。"}


def execute_action(action: str, parameters: dict, runtime: dict) -> dict:
    serialized = json.dumps(parameters, ensure_ascii=False, allow_nan=False)
    if len(serialized) > 16000:
        raise ValueError("操作参数过长。")
    # Provider tool arguments are canonical immutable JSON: arrays arrive as
    # tuples and mappings can be frozen dict subclasses. Restore JSON container
    # shapes at this adapter boundary before strict DTO validation; do not relax
    # scalar types or change the native Session/LLM representation.
    parameters = json.loads(serialized)
    if action == "index":
        Arguments.model_validate(parameters)
        return {"ok": True, **action_catalog()}
    if action == "describe":
        if set(parameters) != {"action"} or not isinstance(parameters["action"], str):
            raise ValueError("describe 只接受 {action: 操作名}。")
        return {"ok": True, **action_catalog(parameters["action"])}
    if action in {"settings_catalog", "avatar_options", "model_options"}:
        Arguments.model_validate(parameters)
        if action == "settings_catalog":
            from tools.pa_settings_actions import settings_catalog
            return {"ok": True, **settings_catalog()}
        if action == "avatar_options":
            return {"ok": True, **directory.list_agent_avatar_options()}
        from core.web.services.config_service import get_agent_model_options_workspace
        return {"ok": True, **get_agent_model_options_workspace()}
    contract = _CONTRACTS.get(action)
    if not contract:
        raise ValueError("此操作不可通过日常工具执行；请查询目录，高风险操作使用 personal_assistant_manage_tool 的原生审批。")
    args = contract[0].model_validate(parameters)
    if action == "agent_create":
        return _create(args, runtime)
    if action in {"agent_update", "agent_avatar"}:
        current = directory.get_agent(args.agent_id)
        if not current or current.get("status") != "active":
            raise ValueError("目标 Agent 不存在或已归档。")
        if (current.get("metadata") or {}).get("personalAssistantProfile") or current.get("roleKey") == "personal_assistant":
            raise ValueError("个人助理自身配置请使用对应设置；身份和授权不可通过日常更新变更。")
        if action == "agent_avatar":
            if bool(args.avatar_image_path) == args.reset_to_default:
                raise ValueError("请选择现有头像路径或 reset_to_default=true。")
            agent = directory.update_agent_avatar(args.agent_id, avatar_image_path=args.avatar_image_path, reset_to_default=args.reset_to_default)
        else:
            if not args.updates or set(args.updates) - SAFE_AGENT_FIELDS:
                raise ValueError("更新仅接受普通配置字段；权限、角色身份及生命周期变更需要原生审批。")
            from core.web.routes.agents import AgentUpdatePayload
            from core.web.services.agent_operation_service import update_agent_from_catalog_request
            validated = AgentUpdatePayload.model_validate(args.updates).model_dump(exclude_unset=True)
            if any(value is None for value in validated.values()):
                raise ValueError("普通更新不能使用 null 清除配置。")
            from core.web.services.agent_directory.profiles import AGENT_PERSONA_PROFILE_FIELDS, AGENT_TASK_PROFILE_FIELDS
            for field, allowed in (("personaProfile", AGENT_PERSONA_PROFILE_FIELDS), ("taskProfile", AGENT_TASK_PROFILE_FIELDS)):
                if field in validated:
                    if directory._is_profileless_session_agent(current):
                        raise ValueError("无角色的普通会话不使用人物或任务档案，请选择有角色的 Agent。")
                    if set(validated[field]) - set(allowed):
                        raise ValueError("档案中包含未知字段，请 describe 查询 API schema 或平台字段定义。")
                    validated[field] = {**current.get(field, {}), **validated[field]}
            agent = update_agent_from_catalog_request(args.agent_id, updates=validated,
                expected_config_revision=(args.expected_config_revision if args.expected_config_revision is not None
                                          else int(current.get("configRevision") or 0)), source="personal_assistant_action")
        observed = directory.get_agent(agent["agentId"])
        if not observed:
            return {"ok": False, "status": "unknown", "agentId": agent["agentId"], "message": "写入后未能读取对象，请先核验。"}
        return _agent_receipt(observed)
    if action == "settings_update":
        from tools.pa_settings_actions import settings_update
        return settings_update(args.updates)
    if action == "model_add":
        from tools.pa_settings_actions import model_add
        return model_add(**args.model_dump())
    from tools.pa_team_actions import team_run_status
    return team_run_status(**args.model_dump())
