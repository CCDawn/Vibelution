"""Canonical assistant tool adapter, bound only inside its owning host process."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from concurrent.futures import TimeoutError
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, model_validator

from .dispatch import DispatchError
from .task_source import TaskSelector


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionIndex(Parameters):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(default="", max_length=64, description="按动作名称或完整说明搜索，支持中文。")
    offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=12, ge=1, le=12)


class Project(Parameters):
    project_id: str = Field(min_length=1, max_length=160)


class MainControlProject(Parameters):
    model_config = ConfigDict(extra="forbid", strict=True)
    project_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


class ProjectLifecycle(MainControlProject):
    operation: Literal["start", "stop", "restart"]
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


class HistoryImport(MainControlProject):
    preview_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class LauncherTheme(Parameters):
    model_config = ConfigDict(extra="forbid", strict=True)
    theme: Literal["dark", "light"]


class OperatorImageImport(Parameters):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["avatar", "background"]


_APPEARANCE_SCHEMAS = {"launcher_theme_get": Parameters, "launcher_theme_set": LauncherTheme,
                       "operator_image_upload": OperatorImageImport}
_APPEARANCE_HELP = {
    "launcher_theme_get": "读取Launcher当前持久化的明暗主题；仅Launcher同来源窗口，不代表各项目HTTP页面的独立主题。",
    "launcher_theme_set": "设置Launcher为light或dark并等待页面核验持久化与自动生效，同来源窗口同步；沿用现有主题存储，不修改各项目HTTP页面的独立偏好。",
    "operator_image_upload": "经原生审批打开单张图片选择框，用户选择PNG/JPEG/WebP后自动上传并应用为头像avatar或壁纸background，无须进入设置页；取消不修改。模型不得传文件路径、URL或图片内容。等待最多120秒，unknown/unavailable时先读operator_image_options/当前外观，不自动重复打开选择框。重复人工导入可能新增资源。",
}


_MAIN_SCHEMAS = {"project_status": MainControlProject, "project_lifecycle": ProjectLifecycle, "history_import": HistoryImport, "affairs_sync": HistoryImport,
                 "project_lifecycle_receipt": ProjectLifecycle}
_MAIN_HELP = {
    "project_status": "只读查询 Launcher 当前已登记主项目的状态与活跃任务数；分支 instance 暂返回 prerequisite_required，不控制分支。",
    "project_lifecycle": "经原生审批控制当前已登记主项目的 start/stop/restart；分支 instance 暂返回 prerequisite_required。不支持 force/interrupt。unknown 时保留同一 request_id 查询 project_lifecycle_receipt，不能换 ID 重放；queued 表示等待执行，不等于完成。",
    "project_lifecycle_receipt": "只读查询同一 project_id、operation、request_id 的主项目原生回执；unknown 时继续查询原 ID，不换 ID 重放，queued 不等于完成；不支持分支 instance 或 force/interrupt。",
    "history_import": "按本轮 history_source_preview 结果，经当前工具审批策略导入所选旧助理的只读历史；不得提供路径或批准标志。成功不表示旧源已冻结、任务已交接或旧助理可退役；unknown 时先查询已有历史，不要自动重复导入。",
    "affairs_sync": "按本轮 history_source_preview 同步已首次导入的旧个人事务；按现有工具治理策略执行，来源、基线由 Launcher 核验，不得传路径或批准标志。unresolved/pending 表示原差异需处理或回执待确认，查询 affairs_conflict_sets 与原回执；baseline_unavailable 表示尚无可验证的初次导入基线。unknown 使用返回的 migrationId 查询原回执，不得换 ID 自动重放。成功不表示旧源已冻结或可退役。",
}


class Dispatch(Project):
    model_config = ConfigDict(extra="forbid", strict=True, json_schema_extra={"oneOf": [
        {"required": ["task"], "not": {"required": ["task_source"]}},
        {"required": ["task_source"], "not": {"required": ["task"]}},
    ]})
    agent_id: str = Field(min_length=1, max_length=160)
    task: str | None = Field(default=None, min_length=1, max_length=64000)
    task_source: TaskSelector | None = None
    dispatch_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")
    title: str = Field(default="", max_length=120)

    @model_validator(mode="after")
    def one_source(self):
        if (self.task is None) == (self.task_source is None) or any(
            getattr(self, key) is None for key in self.model_fields_set & {"task", "task_source"}
        ):
            raise ValueError("Choose exactly one task or task_source")
        return self


class Receipt(Parameters):
    dispatch_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")


class AgentRead(Project):
    agent_id: str = Field(min_length=1, max_length=128)


class ManagementReceipt(Project):
    action: str = Field(pattern=r"^(?:agent_(create|update|avatar|archive)|team_run|session_pin|authorization_upgrade)$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")


class TeamStatus(Project):
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")


class LegacyObservers(Project):
    model_config = ConfigDict(extra="forbid", strict=True)
    offset: int = Field(default=0, ge=0, le=32)
    limit: int = Field(default=3, ge=1, le=4)


class LegacyReceipts(LegacyObservers):
    observer_id: str = Field(pattern=r"^lob-[a-f0-9]{64}$")


def _management_contracts():
    from core.web.services.external_management.contracts import ACTION_MODELS, contracts
    result = {}
    for name, model in ACTION_MODELS.items():
        schema = create_model(f"Launcher_{model.__name__}", __base__=model,
            project_id=(str, Field(min_length=1, max_length=160)),
            request_id=(str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")))
        result[name] = (schema, {**contracts()[name], "parameters": schema.model_json_schema()})
    return result


def _documentation_contracts():
    from core.web.services.external_management.contracts import DocumentationCatalogQuery
    from .documentation_projection import DocumentationNodeQuery

    return {name: create_model(f"Launcher_{model.__name__}", __base__=model,
        project_id=(str, Field(min_length=1, max_length=160))) for name, model in (
            ("api_catalog", DocumentationCatalogQuery), ("api_describe", DocumentationNodeQuery))}


def _project_read_contracts():
    from core.web.services.external_management.contracts import (AvatarOptionsQuery, SessionMetadataQuery, SessionListQuery,
        DirectoryQuery, TeamReadQuery, RoomReadQuery)

    return {name: create_model(f"Launcher_{model.__name__}", __base__=model,
        project_id=(str, Field(min_length=1, max_length=160))) for name, model in (
            ("session_list", SessionListQuery), ("session_get", SessionMetadataQuery), ("session_config_get", SessionMetadataQuery),
            ("session_config_compare", SessionMetadataQuery),
            ("session_parameters_get", SessionMetadataQuery), ("team_list", DirectoryQuery), ("team_get", TeamReadQuery),
            ("room_list", DirectoryQuery), ("room_get", RoomReadQuery),
            ("avatar_options", AvatarOptionsQuery))}


_SCHEMAS = {"projects": Parameters, "agents": Project, "dispatch": Dispatch, "receipt": Receipt,
            "agent_get": AgentRead, "management_receipt": ManagementReceipt, "team_status": TeamStatus,
            "authorization_status": Project, "legacy_observers": LegacyObservers, "legacy_receipts": LegacyReceipts,
            "history_source_preview": MainControlProject}
_HELP = {
    "history_source_preview": "用户要求迁移历史或同步旧事务时，预览已登记项目的唯一旧个人助理身份和短期预览编号；不读取会话内容、不授予导入权限，也不表示切换完成。多个候选或来源变化时拒绝。",
    "legacy_observers": "分页只读本主体已明确交接的旧任务观察授权；不创建授权，不继承旧临时控制权限。新legacy:receipts:read须明确授予，旧授权不会自动扩大。",
    "legacy_receipts": "按observer_id分页查询白名单旧任务及迟到回执。businessTaskStatus是显式业务报告，nativeTurnStatus只是执行轮状态；unknown/unresolved不是完成。不得重派或将旧消息ID当external task ID；取消、继续、审批必须重新走原生授权。",
    "projects": "列出 Launcher 已授权项目的 projectId。",
    "agents": "查询项目当前允许派遣的普通 Agent；不会创建项目内个人助理。",
    "dispatch": "以稳定 dispatch_id 派遣只读任务。优先用 task_source 的 start_after/end_before 唯一短锚点提取当前用户原文（都为空表示整条消息）；不得改写任务、ID或引号文字。task 仅允许用户消息的精确原文子串。未知时保留原参数与 ID，查询回执或由原生引用恢复，不能换 ID 重派。",
    "receipt": "查询原生任务回执；离线/超时/等待审批都不代表目标完成。",
    "agent_get": "读取目标项目普通 Agent 当前 configRevision、updatedAt、模型与头像，用于配置 CAS。",
    "avatar_options": "分页只读目标项目现有 Agent 头像 filename/path 候选；offset最多50000，limit最多30。仅使用返回的路径，不接收模型、URL、目录或图片内容；来源不可用时不得猜测路径。",
    "session_list": "按完整 Session ID 升序发现普通可见会话；query 须单行且不含控制字符，仅检索清洗标题和公开 ID，agent_id 可精确过滤。默认及最多6项，titlePreview 最多48字元，titleTruncated 包含清洗变化。offset/nextOffset 针对本次可见匹配项，不是冻结快照；超过10000候选或权威缺损时拒绝，不返回半页；不搜索对话预览、不修复或改变当前选择。",
    "session_get": "只读目标项目普通会话的标题、归属与置顶状态；不返回正文、路径或提示词，不修改当前选择；拒绝隐藏、团队内部和虚拟人会话。",
    "session_config_get": "只读普通可见会话绑定的历史 compiled revision 中存储的 dialogue 模型标识、上下文覆盖和推理强度；source=session_agent_config_revision。不是 active Turn 实际参数、当前 Agent 设置或模型库默认值；不返回预算、提示词、人物或策略。缺失或损坏时拒绝，不回退当前配置。不能据时间戳判断与当前配置相同，比较请用 session_config_compare。",
    "session_config_compare": "只读比较普通可见会话绑定的历史 compiled 配置与同一 Agent 当前 compiled 配置，返回两个 revision、存储的模型/上下文覆盖/推理强度及原生派生的 sameRevision/changedFields。字段相同不表示 revision 相同；不根据时间戳推断，不提供 active Turn 实际参数、模型默认值、预算、提示词或策略。",
    "management_receipt": "用原 project_id、action、request_id 查询管理操作回执，不另建对象或更换 key。",
    "team_status": "只读查询原 team_run 的原生团队运行、步骤与产物引用；受理成功不代表任务目标完成，不会启动或续接运行。",
    "authorization_status": "读取当前Launcher SDK主体的subjectId、精确scopes和grantRevision；不返回capability，不改变已有授权。首次连接沿用原有SDK绑定流程。旧主体缺权限时以此scopes为expected_scopes，只显式增加本次所需项，不能默认全量升级。",
    "team_list": "只读发现普通团队元数据摘要，按完整ID升序；name最多32字元、purpose最多64字元，query仅匹配返回的公开摘要，最多6项，archived=true包含已归档。详情用team_get。独立teams:directory:read，不扩大旧teams:read。缺失/损坏权威拒绝，不初始化或修复；不读取canvas或成员配置。",
    "team_get": "只读普通团队名称、状态、目的和成员Agent ID；成员默认及最多6项，用nextMemberOffset继续member_offset。独立teams:directory:read，不hydrate成员、不读取canvas或任务正文。",
    "room_list": "只读发现普通房间ID、清洗标题和状态，按ID升序；query仅匹配公开元数据，最多6项，archived=true包含已归档。要求rooms:read，系统/私有房间过滤；损坏或未知来源拒绝。物理读取canonical JSON时会解码同文件rounds，但不遍历、搜索或返回消息，不对账或修复。",
    "room_get": "只读普通房间ID、清洗标题和状态，要求rooms:read；不返回消息、参与者Session或路径，不对账、修复或切换房间。",
    "session_parameters_get": "只读普通可见会话当前Agent的模型、推理选项、上下文上限和预算覆盖及同一configRevision；要求sessions:read和sessions:parameters:read。来源是已保存候选+已加载runtime配置+冻结catalog，不是active Turn实际参数或历史compiled revision。catalogState=absent表示尚无已保存verified观察；配置尚未加载、来源损坏或变化时拒绝，不ensure/repair。预算0为无限制，null为未设置覆盖。",
    "api_catalog": "按目标项目当前 OpenAPI 分页导航 API 文档；executable=false 仅可查说明，不能执行；执行动作参数以 describe 为准。",
    "api_describe": "只读目录中真实 operation_id 的有限文档节点，返回 viewVersion=1；仅 operation_id 发给 SDK。document_pointer 为空表示根，按返回的完整 pointer 深入；offset/limit 分页，默认512。续读绑定 expected_document_digest=documentDigest。upstreamTruncated/textFiltered 明示上游省略和文本清洗；小文本页边界不能稳定呈现时明确拒绝，不补造内容。文档不授予执行权限。",
}
_binding = None


def _schema_without_titles(schema):
    """Remove display annotations only at JSON Schema nodes, never data maps."""
    if not isinstance(schema, dict):
        return deepcopy(schema)
    result = {}
    for key, value in schema.items():
        if key == "title":
            continue
        if key in {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"} and isinstance(value, dict):
            result[key] = {name: _schema_without_titles(child) for name, child in value.items()}
        elif key in {"anyOf", "allOf", "oneOf", "prefixItems"} and isinstance(value, list):
            result[key] = [_schema_without_titles(child) for child in value]
        elif key in {"items", "additionalItems", "additionalProperties", "unevaluatedProperties", "unevaluatedItems",
                     "contains", "not", "if", "then", "else", "propertyNames", "contentSchema"}:
            result[key] = ([_schema_without_titles(child) for child in value] if isinstance(value, list)
                           else _schema_without_titles(value))
        else:
            result[key] = deepcopy(value)
    return result


def _describe_contract(contract: dict) -> dict:
    return {**contract, "parameters": _schema_without_titles(contract["parameters"])}


def _index_page(parameters: dict, schemas: dict, local: dict, managed: dict) -> dict:
    try:
        query = ActionIndex.model_validate(parameters)
    except ValidationError as exc:
        raise ValueError("Index parameters do not match describe(index) schema") from exc
    contracts = {key: {"action": key, "description": _HELP[key], "governed": False} for key in schemas}
    contracts.update(local)
    contracts.update({key: value[1] for key, value in managed.items()})
    needle = query.query.strip().casefold()
    matches = [contracts[key] for key in sorted(contracts)
               if not needle or needle in (key + " " + contracts[key]["description"]).casefold()]
    rows = []
    for contract in matches[query.offset:query.offset + query.limit]:
        description = contract["description"]
        # Navigation is a short excerpt; describe retains every execution rule.
        short = description.split("。", 1)[0] + ("。" if "。" in description else "")
        row = {"action": contract["action"], "description": short if len(short) <= 64 else short[:63] + "…",
               "governed": contract.get("governed", False), "available": contract.get("available", True),
               "unavailableReason": contract.get("unavailableReason", "")}
        if "scope" in contract:
            row["scope"] = contract["scope"]
        rows.append(row)
    end = query.offset + len(rows)
    return {"actions": rows, "total": len(matches), "offset": query.offset,
            "nextOffset": end if end < len(matches) else None,
            "description": "本页是动作导航摘要，完整参数合同由 describe(action) 返回；query 过滤完整动作说明，offset/limit 为分页参数，nextOffset=null 表示没有下一页。",
            "indexParameters": _schema_without_titles(ActionIndex.model_json_schema())}


def bind_actions(service, loop, main_control=None):
    global _binding
    if _binding is not None:
        raise RuntimeError("Launcher assistant actions already have an owner")
    _binding = (service, loop, main_control)


def unbind_actions(service):
    global _binding
    if _binding is not None and _binding[0] is service:
        _binding = None


def history_import_approval_summary(project_id: str, preview_id: str) -> dict:
    """Resolve a preview for display only; this never grants import authority."""
    if _binding is None:
        raise ValueError("History preview unavailable")
    preview = getattr(_binding[0], "history_preview", None)
    if preview is None:
        raise ValueError("History preview unavailable")
    value = preview.verify_preview(preview_id)
    if value.get("projectId") != project_id:
        raise ValueError("History preview changed")
    return {key: value[key] for key in ("sourceProjectId", "instanceId", "assistantAgentId")}


def execute_action(action: str, parameters: dict, *, runtime: dict | None = None, governed: bool = False) -> dict:
    """Called only after the canonical tool's native Agent/Session identity gate.

    One event loop owns every managed client, lock and heartbeat. The native
    worker is synchronous, so it submits to that loop without creating a second
    client lifecycle or cancelling a write when its response takes too long.
    """
    if _binding is None:
        raise ValueError("Launcher assistant host is not running")
    service, loop, main_control = _binding
    from . import local_actions
    local = local_actions.contracts()
    managed = _management_contracts()
    schemas = {**_SCHEMAS, **_documentation_contracts(), **_project_read_contracts()}
    main_contracts = {key: {"action": key, "description": _MAIN_HELP[key],
        "parameters": model.model_json_schema(), "governed": key in {"project_lifecycle", "history_import", "affairs_sync"}}
        for key, model in _MAIN_SCHEMAS.items()} if main_control is not None else {}
    if main_control is not None and getattr(main_control, "appearance_enabled", False):
        main_contracts.update({key: {"action": key, "description": _APPEARANCE_HELP[key],
            "parameters": model.model_json_schema(), "governed": key == "operator_image_upload"}
            for key, model in _APPEARANCE_SCHEMAS.items()})
    if action == "index":
        return _index_page(parameters, schemas, {**local, **main_contracts}, managed)
    if action == "describe":
        if parameters == {"action": "index"}:
            return {"action": "index", "description": "分页搜索 Launcher 动作导航；执行动作前 describe 读取完整 schema。",
                    "parameters": _schema_without_titles(ActionIndex.model_json_schema())}
        if set(parameters) != {"action"} or parameters["action"] not in {*schemas, *local, *managed, *main_contracts}:
            raise ValueError("Unknown Launcher action")
        key = parameters["action"]
        if key in main_contracts:
            return _describe_contract(main_contracts[key])
        if key in local:
            return _describe_contract(local[key])
        if key in managed:
            return _describe_contract(managed[key][1])
        return _describe_contract({"action": key, "description": _HELP[key], "parameters": schemas[key].model_json_schema()})
    if action in local:
        if not runtime:
            raise ValueError("Launcher native tool identity is required")
        return local_actions.execute(action, parameters, runtime, governed=governed)
    if action not in {*schemas, *managed, *main_contracts}:
        raise ValueError("Unknown Launcher action; use index for supported operations")
    try:
        schema = {**_MAIN_SCHEMAS, **_APPEARANCE_SCHEMAS}[action] if action in main_contracts else managed[action][0] if action in managed else schemas[action]
        args = schema.model_validate(parameters).model_dump(exclude_unset=action == "agent_update")
    except ValidationError as exc:
        raise ValueError("Action parameters do not match describe schema") from exc
    projects = service.project_ids()
    if "project_id" in args and args["project_id"] not in projects:
        raise ValueError("Project is not authorized by Launcher")
    if action in main_contracts:
        if action in {"project_lifecycle", "operator_image_upload", "history_import", "affairs_sync"} and governed is not True:
            return {"ok": False, "status": "approval_required", "action": action, "tool": "personal_assistant_manage_tool"}
        if action in _APPEARANCE_SCHEMAS:
            if not runtime:
                raise ValueError("Launcher native tool identity is required")
            request = {"operation": "read"} if action == "launcher_theme_get" else {"operation": "set", "theme": args["theme"]} if action == "launcher_theme_set" else {"operation": "import", "kind": args["kind"]}
        elif action in {"history_import", "affairs_sync"}:
            turn_id = runtime.get("turnId") if isinstance(runtime, dict) else None
            if not isinstance(turn_id, str) or not turn_id.strip():
                raise ValueError("Launcher native Turn identity is required")
            request = {"projectId": args["project_id"], "previewId": args["preview_id"], "turnId": turn_id}
        else:
            request = {"projectId": args["project_id"], "operation": args.get("operation", "status")}
            if "request_id" in args:
                request["requestId"] = args["request_id"]
        if action in {"operator_image_upload", "history_import", "affairs_sync"}:
            turn_id = runtime.get("turnId")
            if not isinstance(turn_id, str) or not turn_id.strip():
                raise ValueError("Launcher native Turn identity is required")
            coroutine = main_control.invoke(action, request, turn_id=turn_id)
        else:
            coroutine = main_control.invoke(action, request)
    elif action in managed:
        if managed[action][1]["governed"] and governed is not True:
            return {"ok": False, "status": "approval_required", "action": action, "tool": "personal_assistant_manage_tool"}
        project_id, request_id = args.pop("project_id"), args.pop("request_id")
        coroutine = service.management.invoke(project_id, action=action, request_id=request_id, parameters=args)
    elif action == "agent_get":
        coroutine = service.management.agent(args.pop("project_id"), **args)
    elif action == "session_list":
        coroutine = service.management.session_list(args.pop("project_id"), **args)
    elif action == "session_get":
        coroutine = service.management.session(args.pop("project_id"), **args)
    elif action == "session_config_get":
        coroutine = service.management.session_config(args.pop("project_id"), **args)
    elif action == "session_config_compare":
        coroutine = service.management.session_config_compare(args.pop("project_id"), **args)
    elif action == "session_parameters_get":
        coroutine = service.management.session_parameters(args.pop("project_id"), **args)
    elif action == "team_list":
        coroutine = service.management.team_list(args.pop("project_id"), **args)
    elif action == "team_get":
        coroutine = service.management.team(args.pop("project_id"), **args)
    elif action == "room_list":
        coroutine = service.management.room_list(args.pop("project_id"), **args)
    elif action == "room_get":
        coroutine = service.management.room(args.pop("project_id"), **args)
    elif action == "avatar_options":
        coroutine = service.management.avatar_options(args.pop("project_id"), **args)
    elif action == "management_receipt":
        coroutine = service.management.receipt(args.pop("project_id"), **args)
    elif action == "team_status":
        coroutine = service.management.receipt(args.pop("project_id"), action="team_run", **args)
    elif action == "authorization_status":
        coroutine = service.management.authorization_status(args.pop("project_id"))
    elif action == "legacy_observers":
        coroutine = service.management.legacy_observers(args.pop("project_id"), **args)
    elif action == "legacy_receipts":
        coroutine = service.management.legacy_receipts(args.pop("project_id"), **args)
    elif action in {"api_catalog", "api_describe"}:
        coroutine = service.management.documentation(args.pop("project_id"), **args)
    elif action == "projects":
        return {"projects": [{"projectId": key} for key in projects]}
    elif action == "history_source_preview":
        from .migration_io import MigrationIOError
        preview = getattr(service, "history_preview", None)
        if preview is None:
            return {"ok": False, "code": "history_preview_unavailable"}
        try:
            return preview.preview(args["project_id"], turn_id=runtime.get("turnId") if isinstance(runtime, dict) else None)
        except MigrationIOError as exc:
            allowed = {"history_project_unavailable", "history_source_ambiguous", "history_preview_capacity"}
            return {"ok": False, "code": str(exc) if str(exc) in allowed else "history_source_unavailable"}
    elif action == "agents":
        coroutine = service.discover(args["project_id"])
    elif action == "dispatch":
        if not runtime:
            raise ValueError("Launcher native tool identity is required")
        project_id = args.pop("project_id")
        coroutine = service.dispatch_from_source(project_id, **args, runtime=runtime)
    elif action == "receipt":
        coroutine = service.reconcile(args["dispatch_id"])
    try:
        return asyncio.run_coroutine_threadsafe(coroutine, loop).result(timeout=125 if action in {"operator_image_upload", "history_import", "affairs_sync"} else 25)
    except TimeoutError as exc:
        if action in _APPEARANCE_SCHEMAS:
            raise ValueError("Launcher外观操作尚未确认，请读取当前外观；不要自动重复上传或重新打开选择框。") from exc
        raise ValueError("原生请求尚未确认，请用原 dispatch_id 或 action/request_id 查询回执；不要更换 ID 重建对象。") from exc
    except DispatchError as exc:
        return {"ok": False, "code": exc.code, "message": str(exc)}
