"""Canonical assistant tool adapter, bound only inside its owning host process."""

from __future__ import annotations

import asyncio
import re
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


class AffairsSync(HistoryImport):
    recover_sync_id: str | None = Field(default=None, pattern=r"^affairs-[0-9a-f]{40}$")


class EpisodicSync(HistoryImport):
    recover_sync_id: str | None = Field(default=None, pattern=r"^episodic-[0-9a-f]{40}$")
    resolve_sync_id: str | None = Field(default=None, pattern=r"^episodic-[0-9a-f]{40}$")
    review_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def resolution_binding(self):
        if ((self.resolve_sync_id is None) != (self.review_token is None)
                or self.resolve_sync_id is not None and self.recover_sync_id is not None):
            raise ValueError("Choose receipt recovery or a reviewed resolution")
        return self


class InitialMigrationQueue(HistoryImport):
    category: Literal["personal", "knowledge"]


class InitialMigrationReceipt(MainControlProject):
    category: Literal["personal", "knowledge"]


class KnowledgeSyncReceipt(MainControlProject):
    operation_id: str = Field(pattern=r"^ksync-[a-f0-9]{40}$")


class KnowledgeSyncRecover(HistoryImport):
    operation_id: str = Field(pattern=r"^ksync-[a-f0-9]{40}$")


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


_MAIN_SCHEMAS = {"project_status": MainControlProject, "project_lifecycle": ProjectLifecycle, "history_import": HistoryImport, "affairs_sync": AffairsSync, "episodic_sync": EpisodicSync,
                 "project_lifecycle_receipt": ProjectLifecycle}
_MAIN_HELP = {
    "project_status": "只读查询 Launcher 当前已登记主项目的状态与活跃任务数；分支 instance 暂返回 prerequisite_required，不控制分支。",
    "project_lifecycle": "经原生审批控制当前已登记主项目的 start/stop/restart；分支 instance 暂返回 prerequisite_required。不支持 force/interrupt。unknown 时保留同一 request_id 查询 project_lifecycle_receipt，不能换 ID 重放；queued 表示等待执行，不等于完成。",
    "project_lifecycle_receipt": "只读查询同一 project_id、operation、request_id 的主项目原生回执；unknown 时继续查询原 ID，不换 ID 重放，queued 不等于完成；不支持分支 instance 或 force/interrupt。",
    "history_import": "按本轮 history_source_preview 结果，经当前工具审批策略导入所选旧助理的只读历史；不得提供路径或批准标志。成功不表示旧源已冻结、任务已交接或旧助理可退役；unknown 时先查询已有历史，不要自动重复导入。",
    "affairs_sync": "按本轮 history_source_preview 同步已首次导入的旧个人事务；来源、基线由 Launcher 核验，不得传路径或批准标志。unknown 用 affairs_sync_receipt 查本次 migrationId；rejected/pending 用 affairs_conflict_sets 找先前待确认的 syncId（不是本次 ID）。待确认时用新预览和 recover_sync_id=原 ID 核对，不重写；confirmed/matched 只表示当前结果匹配，不证明原写入归因。unresolved 查询差异；baseline_unavailable 表示尚无初次导入基线。成功不表示旧源已冻结或可退役。",
    "episodic_sync": "按本轮 history_source_preview 同步旧情景记忆，保留目标编辑和删除。unresolved 先用 episodic_conflict_review 查看，用户同意保留目标后，以新预览及 resolve_sync_id、review_token 对账，不覆盖目标；目标变化时重新查看，来源变化时先用新预览普通同步刷新差异，再查看新 migrationId。unknown 用新预览和 recover_sync_id=原 migrationId 核对，不重写。不得传路径或批准标志；成功不表示旧源已冻结或退役。",
    "initial_migration_queue": "按本轮 history_source_preview，经原生策略准入申请排队首次导入 personal（事务和情景记忆）或 knowledge（可验证的私有知识）。不得提供路径、旧助理ID或批准标志。queued 仅表示已排队；Launcher 会在当前工作安全结束后自动执行，必要时在下次启动继续，不表示已导入；rejected/busy 表示本次未发布，可重新预览并经审批重试；unknown 保留原 operationId 对账，不得换 ID 重派；旧源未冻结。",
    "initial_migration_receipt": "只读查询已登记项目和类别对应的首次导入原回执，无需重复审批。queued 表示等待，partial 表示部分完成，unknown 表示无法确认；不得换 ID 重派，查询不表示旧源已冻结。",
    "reminder_handoff_queue": "经原生审批登记旧提醒交接请求，使用本轮来源预览；只返回原 operationId，不关闭工作台或停止旧来源。等待来源、窗口和发送者安全证明，不代表交接完成。",
    "reminder_handoff_receipt": "查询已登记项目的旧提醒交接原回执；queued 表示仍等待，waitingFor 为 window（等待窗口自行关闭）、close_transaction（等待关闭事务）、drain（等待后台排空）或 unknown（来源证明不全）。保留原 operationId 和 syncId，不换 ID 重派。",
    "knowledge_sync_queue": "经原生审批，按本轮 history_source_preview 排队同步已完成首次导入的旧私有知识。返回独立 operationId；queued 表示已排队；Launcher 会在当前工作安全结束后自动执行，必要时在下次启动继续，不表示已经同步；rejected/busy 表示本次未发布，可重新预览并经审批重试；排队后停止当前对话不会撤销已保存的任务。unknown 保留原 ID 查询，不换 ID 重派；不冻结旧来源。",
    "knowledge_sync_receipt": "只读查询原 project_id 和 operation_id 的知识同步任务，不会续写未开始项。queued 表示等待安全执行；not_started 表示已确认本次没有取得写入许可，可在用户同意后使用新预览发起新的同步；unknown 不代表未执行，不得换 ID 重派。partial 中 skippedCount 是未处理项，pendingCount 包含它们；excludedCount 是未纳入的项。不表示旧来源已冻结。",
    "knowledge_sync_recover": "经原生审批，使用新 history_source_preview 为原 operation_id 排队离线恢复。只确认已完成项，并只续做可证明从未开始的项；已开始但无法确认的项保持 unknown，绝不重放。queued 表示已排队，Launcher 会在当前工作安全结束后自动执行，必要时在下次启动继续，不代表已完成；rejected/busy 表示本次恢复未发布，可重新预览并经审批重试；查询继续使用原 operation_id。",
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


def authorization_upgrade_approval_summary(parameters: dict) -> dict:
    """Validate the exact executable request before projecting its approval."""
    try:
        values = _management_contracts()["authorization_upgrade"][0].model_validate(parameters).model_dump()
    except (ValidationError, TypeError) as exc:
        raise ValueError("Invalid authorization upgrade") from exc
    project_id = values["project_id"]
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", project_id) is None:
        raise ValueError("Project identity cannot be displayed safely")
    return {"assistantAction": "authorization_upgrade",
            "assistantTargets": {"project_id": project_id},
            "assistantAddedScopes": values["add_scopes"]}


def _documentation_contracts():
    from core.web.services.external_management.contracts import DocumentationCatalogQuery
    from .documentation_projection import DocumentationNodeQuery

    return {name: create_model(f"Launcher_{model.__name__}", __base__=model,
        project_id=(str, Field(min_length=1, max_length=160))) for name, model in (
            ("api_catalog", DocumentationCatalogQuery), ("api_describe", DocumentationNodeQuery))}


def _project_read_contracts():
    from core.web.services.external_management.contracts import (AvatarOptionsQuery, SessionMetadataQuery, SessionListQuery,
        DirectoryQuery, TeamReadQuery, TeamKnowledgeQuery, RoomReadQuery, ActiveTasksQuery, SourceReadQuery, SourceSearchQuery)

    return {name: create_model(f"Launcher_{model.__name__}", __base__=model,
        project_id=(str, Field(min_length=1, max_length=160))) for name, model in (
            ("task_list", ActiveTasksQuery), ("source_read", SourceReadQuery), ("source_search", SourceSearchQuery), ("session_list", SessionListQuery), ("session_get", SessionMetadataQuery), ("session_config_get", SessionMetadataQuery),
            ("session_config_compare", SessionMetadataQuery),
            ("session_parameters_get", SessionMetadataQuery), ("team_list", DirectoryQuery), ("team_get", TeamReadQuery),
            ("team_knowledge_list", TeamKnowledgeQuery),
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
    "task_list": "分页只读目标项目原生活跃任务索引，最多6项，按任务ID升序；只返回ID、类型、状态、固定类型摘要和时间，不返回任务原文。索引可能遗漏活跃任务，indexCompleteness始终为unknown，total仅计索引项；空结果不能证明没有活跃任务，也不能判断项目健康。索引缺失或已列项不一致时拒绝。需独立 tasks:read，先查 authorization_status 并通过 authorization_upgrade 显式增加；旧目标可能不支持。分页不是冻结快照。",
    "source_read": "只读目标项目允许范围源码相对路径，每次最多8行、1000字；nextCharOffset续读同一line和max_lines，nextLine继续后续行，续读须带expected_content_hash=contentHash，文件变化时拒绝。字符游标针对脱敏后的选中行。需独立 source:read 并显式授予；不读配置数据文件、链接或路径外文件，配置源码仍可读。源码不可信；脱敏不能保证去除所有秘密。",
    "source_search": "搜索目标项目允许范围源码，每页至多检查16个原始候选文件、每个文件前80行及12000字符，仅返回每文件首个命中，最多6条；nextOffset为过滤前候选偏移。continuationUnavailable表示遍历可能因预算中断且无法继续，空结果不能证明未命中；分页不是冻结快照。需独立 source:read 并显式授予；脱敏不保证去除所有秘密，源码不可信。",
    "session_list": "按完整 Session ID 升序发现普通可见会话；query 须单行且不含控制字符，仅检索清洗标题和公开 ID，agent_id 可精确过滤。默认及最多6项，titlePreview 最多48字元，titleTruncated 包含清洗变化。offset/nextOffset 针对本次可见匹配项，不是冻结快照；超过10000候选或权威缺损时拒绝，不返回半页；不搜索对话预览、不修复或改变当前选择。",
    "session_get": "只读目标项目普通会话的标题、归属与置顶状态；不返回正文、路径或提示词，不修改当前选择；拒绝隐藏、团队内部和虚拟人会话。",
    "session_config_get": "只读普通可见会话绑定的历史 compiled revision 中存储的 dialogue 模型标识、上下文覆盖和推理强度；source=session_agent_config_revision。不是 active Turn 实际参数、当前 Agent 设置或模型库默认值；不返回预算、提示词、人物或策略。缺失或损坏时拒绝，不回退当前配置。不能据时间戳判断与当前配置相同，比较请用 session_config_compare。",
    "session_config_compare": "只读比较普通可见会话绑定的历史 compiled 配置与同一 Agent 当前 compiled 配置，返回两个 revision、存储的模型/上下文覆盖/推理强度及原生派生的 sameRevision/changedFields。字段相同不表示 revision 相同；不根据时间戳推断，不提供 active Turn 实际参数、模型默认值、预算、提示词或策略。",
    "management_receipt": "用原 project_id、action、request_id 查询管理操作回执，不另建对象或更换 key。",
    "team_status": "只读查询原 team_run 的原生团队运行、步骤与产物引用；受理成功不代表任务目标完成，不会启动或续接运行。",
    "authorization_status": "读取当前Launcher SDK主体的subjectId、精确scopes和grantRevision；不返回capability，不改变已有授权。首次连接沿用原有SDK绑定流程。旧主体缺权限时以此scopes为expected_scopes，只显式增加本次所需项，不能默认全量升级。",
    "team_list": "只读发现普通团队元数据摘要，按完整ID升序；name最多32字元、purpose最多64字元，query仅匹配返回的公开摘要，最多6项，archived=true包含已归档。详情用team_get。独立teams:directory:read，不扩大旧teams:read。缺失/损坏权威拒绝，不初始化或修复；不读取canvas或成员配置。",
    "team_get": "只读普通团队名称、状态、目的和成员Agent ID；成员默认及最多6项，用nextMemberOffset继续member_offset。独立teams:directory:read，不hydrate成员、不读取canvas或任务正文。",
    "team_knowledge_list": "分页查询已授权普通团队的知识库目录，仅返回ID、名称与状态，不读取知识内容或判断Agent访问权。需同时具有knowledge:catalog:read和teams:directory:read；缺失时先查authorization_status，再经原生审批只申请缺失权限。未迁移或数据归属无法确认时返回不可用，不代表目录为空。",
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


def _reminder_handoff_receipt(service, project_id):
    from core.infrastructure.native_runtime import assistant_native_root
    from . import native
    from .initial_migration_binding import _directory, target_identity
    from .reminder_handoff_intent import handoff_id, read_handoff_intent, sync_id
    result = {"schemaVersion": 1, "projectId": project_id, "operationId": handoff_id(project_id),
              "syncId": sync_id(project_id), "state": "unknown", "code": "unknown", "readyForCutover": False}
    try:
        root = assistant_native_root()
        with native._LOCK:
            if not native._STARTED or native._OFFLINE_MIGRATION:
                return result
            revision = service._registry_revision
            project_root = service._admitted_projects().get(project_id)
            if project_root is None:
                return result
            intent = read_handoff_intent(root, project_id)
            if (intent is None or (native._AGENT_ID, native._SESSION_ID) != (intent["targetAgentId"], intent["targetSessionId"])
                    or _directory(project_root) != intent["projectDirectory"]
                    or target_identity(root, native._AGENT_ID, native._SESSION_ID) != (intent["targetIdentityDigest"], intent["targetDirectory"])
                    or service._registry_revision != revision or service._admitted_projects().get(project_id) != project_root):
                return result
            return {**result, "state": "pending", "code": "source_proof_unavailable", "baselineState": "unknown"}
    except Exception:
        return result


def _knowledge_sync_receipt(service, project_id, operation_id):
    """Read an exact authorized intent and receipt; never invoke the sync writer."""
    from core.infrastructure.native_runtime import assistant_native_root
    from . import native
    from .initial_migration_binding import _directory, list_initial_intents, read_initial_intent, target_identity
    from .knowledge_recovery_result import read_verified_recovery_job_result
    from .knowledge_not_started import read_verified_not_started
    from .knowledge_sync_receipt import read_drained_job_result, read_knowledge_sync_receipt
    from .migration_io import read_stable_file, strict_json
    from scripts.assistant_migration_activate import _initial_receipts_or_claim
    unknown = {"schemaVersion": 1, "projectId": project_id, "operationId": operation_id,
               "state": "unknown", "readyForCutover": False}
    try:
        root = assistant_native_root()
        with native._LOCK:
            if not native._STARTED or native._OFFLINE_MIGRATION:
                return unknown
            revision = service._registry_revision
            project_root = service._admitted_projects().get(project_id)
            if project_root is None:
                return unknown
            def still_authorized():
                return (service._registry_revision == revision
                        and service._admitted_projects().get(project_id) == project_root)
            intent = read_initial_intent(root, operation_id)
            if (intent is None or intent["category"] != "knowledge_sync" or intent["registeredProjectId"] != project_id
                    or (native._AGENT_ID, native._SESSION_ID) != (intent["targetAgentId"], intent["targetSessionId"])
                    or _directory(project_root) != intent["projectDirectory"]
                    or target_identity(root, native._AGENT_ID, native._SESSION_ID) != (intent["targetIdentityDigest"], intent["targetDirectory"])):
                return unknown
            if read_verified_not_started(root, operation_id):
                return {**unknown, "state": "not_started", "code": "not_started"} if still_authorized() else unknown
            result = read_drained_job_result(root, operation_id)
            if result not in {"completed", "partial"}:
                for ref in list_initial_intents(root):
                    if ref["category"] != "knowledge_recovery":
                        continue
                    recovery = read_initial_intent(root, ref["operationId"])
                    if (recovery is not None and recovery.get("originalSyncId") == operation_id
                            and all(recovery.get(key) == intent.get(key) for key in ("registeredProjectId", "sourceScope",
                                "sourceIdentityDigest", "projectDirectory", "workspaceDirectory", "targetDirectory",
                                "targetAgentId", "targetSessionId", "baselineMigrationId"))):
                        outcome = read_verified_recovery_job_result(root, ref["operationId"])
                        if outcome in {"completed", "partial"}:
                            result = outcome
                            break
            if result is None:
                if not _initial_receipts_or_claim(root, operation_id, "knowledge_sync") and still_authorized():
                    return {**unknown, "state": "queued"}
                return unknown
            if result not in {"completed", "partial"}:
                return unknown
            claim = strict_json(read_stable_file(root / "initial_migration_claims" / operation_id / "claim.json", 16384).raw)
            if (type(claim) is not dict or type(claim.get("schemaVersion")) is not int
                    or claim != {"schemaVersion": 1, "operationId": operation_id, "category": "knowledge_sync"}):
                return unknown
            receipt = read_knowledge_sync_receipt(root, sync_id=operation_id, baseline_id=intent["baselineMigrationId"],
                source_scope=intent["sourceScope"], target_agent_id=intent["targetAgentId"])
            if receipt["state"] == "unknown" or not still_authorized():
                return unknown
            return {**unknown, **{key: value for key, value in receipt.items() if key != "syncId"},
                    "state": "partial" if result == "partial" else receipt["state"]}
    except Exception:
        return unknown


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
        "parameters": model.model_json_schema(), "governed": key in {"project_lifecycle", "history_import", "affairs_sync", "episodic_sync"}}
        for key, model in _MAIN_SCHEMAS.items()} if main_control is not None else {}
    if main_control is not None and getattr(main_control, "initial_migration_enabled", False):
        main_contracts["initial_migration_queue"] = {"action": "initial_migration_queue",
            "description": _MAIN_HELP["initial_migration_queue"], "parameters": InitialMigrationQueue.model_json_schema(), "governed": True}
        main_contracts["initial_migration_receipt"] = {"action": "initial_migration_receipt",
            "description": _MAIN_HELP["initial_migration_receipt"], "parameters": InitialMigrationReceipt.model_json_schema(), "governed": False}
        main_contracts["knowledge_sync_queue"] = {"action": "knowledge_sync_queue",
            "description": _MAIN_HELP["knowledge_sync_queue"], "parameters": HistoryImport.model_json_schema(), "governed": True}
        main_contracts["knowledge_sync_receipt"] = {"action": "knowledge_sync_receipt",
            "description": _MAIN_HELP["knowledge_sync_receipt"], "parameters": KnowledgeSyncReceipt.model_json_schema(), "governed": False}
        main_contracts["knowledge_sync_recover"] = {"action": "knowledge_sync_recover",
            "description": _MAIN_HELP["knowledge_sync_recover"], "parameters": KnowledgeSyncRecover.model_json_schema(), "governed": True}
        main_contracts["reminder_handoff_queue"] = {"action": "reminder_handoff_queue",
            "description": _MAIN_HELP["reminder_handoff_queue"], "parameters": HistoryImport.model_json_schema(), "governed": True}
        main_contracts["reminder_handoff_receipt"] = {"action": "reminder_handoff_receipt",
            "description": _MAIN_HELP["reminder_handoff_receipt"], "parameters": MainControlProject.model_json_schema(), "governed": False}
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
        schema = {**_MAIN_SCHEMAS, **_APPEARANCE_SCHEMAS, "initial_migration_queue": InitialMigrationQueue,
                  "initial_migration_receipt": InitialMigrationReceipt, "knowledge_sync_queue": HistoryImport,
                  "knowledge_sync_receipt": KnowledgeSyncReceipt, "knowledge_sync_recover": KnowledgeSyncRecover,
                  "reminder_handoff_queue": HistoryImport, "reminder_handoff_receipt": MainControlProject}[action] if action in main_contracts else managed[action][0] if action in managed else schemas[action]
        args = schema.model_validate(parameters).model_dump(exclude_unset=action == "agent_update")
    except ValidationError as exc:
        raise ValueError("Action parameters do not match describe schema") from exc
    if action == "authorization_upgrade":
        authorization_upgrade_approval_summary(args)
    projects = service.project_ids()
    if "project_id" in args and args["project_id"] not in projects:
        raise ValueError("Project is not authorized by Launcher")
    if action in main_contracts:
        if action in {"project_lifecycle", "operator_image_upload", "history_import", "affairs_sync", "episodic_sync", "initial_migration_queue", "knowledge_sync_queue", "knowledge_sync_recover", "reminder_handoff_queue"} and governed is not True:
            return {"ok": False, "status": "approval_required", "action": action, "tool": "personal_assistant_manage_tool"}
        if action in {"initial_migration_queue", "knowledge_sync_queue", "knowledge_sync_recover"}:
            from .main_control import initial_model_env_unavailable
            if initial_model_env_unavailable():
                raise ValueError("Initial migration source model configuration unavailable")
        if action in _APPEARANCE_SCHEMAS:
            if not runtime:
                raise ValueError("Launcher native tool identity is required")
            request = {"operation": "read"} if action == "launcher_theme_get" else {"operation": "set", "theme": args["theme"]} if action == "launcher_theme_set" else {"operation": "import", "kind": args["kind"]}
        elif action in {"history_import", "affairs_sync", "episodic_sync", "initial_migration_queue", "knowledge_sync_queue", "knowledge_sync_recover", "reminder_handoff_queue"}:
            turn_id = runtime.get("turnId") if isinstance(runtime, dict) else None
            if not isinstance(turn_id, str) or not turn_id.strip():
                raise ValueError("Launcher native Turn identity is required")
            request = {"projectId": args["project_id"], "previewId": args["preview_id"], "turnId": turn_id}
            if action == "initial_migration_queue":
                from .main_control import initial_migration_id
                request.update(category=args["category"], operationId=initial_migration_id(args["project_id"], args["preview_id"], args["category"]))
            if action == "knowledge_sync_queue":
                from .main_control import knowledge_sync_id
                request.update(category="knowledge_sync", operationId=knowledge_sync_id(args["project_id"], args["preview_id"]))
            if action == "knowledge_sync_recover":
                from .main_control import knowledge_recovery_id
                request.update(category="knowledge_recovery", originalSyncId=args["operation_id"],
                    operationId=knowledge_recovery_id(args["project_id"], args["preview_id"], args["operation_id"]))
            if action == "reminder_handoff_queue":
                from .reminder_handoff_intent import handoff_id
                request.update(category="reminder_handoff", operationId=handoff_id(args["project_id"]))
            if action in {"affairs_sync", "episodic_sync"} and args.get("recover_sync_id") is not None:
                request["recoverSyncId"] = args["recover_sync_id"]
            if action == "episodic_sync" and args.get("resolve_sync_id") is not None:
                request.update(resolveSyncId=args["resolve_sync_id"], reviewToken=args["review_token"])
        elif action == "reminder_handoff_receipt":
            from .reminder_handoff_intent import handoff_id
            request = {"projectId": args["project_id"], "category": "reminder_handoff", "operationId": handoff_id(args["project_id"])}
        elif action == "knowledge_sync_receipt":
            return _knowledge_sync_receipt(service, args["project_id"], args["operation_id"])
        elif action == "initial_migration_receipt":
            from .main_control import initial_migration_id
            request = {"projectId": args["project_id"], "category": args["category"],
                       "operationId": initial_migration_id(args["project_id"], "", args["category"])}
        else:
            request = {"projectId": args["project_id"], "operation": args.get("operation", "status")}
            if "request_id" in args:
                request["requestId"] = args["request_id"]
        if action in {"operator_image_upload", "history_import", "affairs_sync", "episodic_sync", "initial_migration_queue", "knowledge_sync_queue", "knowledge_sync_recover", "reminder_handoff_queue"}:
            turn_id = runtime.get("turnId")
            if not isinstance(turn_id, str) or not turn_id.strip():
                raise ValueError("Launcher native Turn identity is required")
            coroutine = main_control.invoke("initial_migration_queue" if action in {"knowledge_sync_queue", "knowledge_sync_recover", "reminder_handoff_queue"} else action, request, turn_id=turn_id)
        else:
            coroutine = main_control.invoke("initial_migration_receipt" if action == "reminder_handoff_receipt" else action, request)
    elif action in managed:
        if managed[action][1]["governed"] and governed is not True:
            return {"ok": False, "status": "approval_required", "action": action, "tool": "personal_assistant_manage_tool"}
        project_id, request_id = args.pop("project_id"), args.pop("request_id")
        coroutine = service.management.invoke(project_id, action=action, request_id=request_id, parameters=args)
    elif action == "agent_get":
        coroutine = service.management.agent(args.pop("project_id"), **args)
    elif action == "session_list":
        coroutine = service.management.session_list(args.pop("project_id"), **args)
    elif action == "task_list":
        coroutine = service.management.active_tasks(args.pop("project_id"), **args)
    elif action in {"source_read", "source_search"}:
        coroutine = service.management.source(args.pop("project_id"), action.removeprefix("source_"), **args)
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
    elif action == "team_knowledge_list":
        coroutine = service.management.team_knowledge(args.pop("project_id"), **args)
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
        value = asyncio.run_coroutine_threadsafe(coroutine, loop).result(timeout=125 if action in {"operator_image_upload", "history_import", "affairs_sync", "episodic_sync", "initial_migration_queue", "knowledge_sync_queue", "knowledge_sync_recover", "reminder_handoff_queue"} else 25)
        if action == "knowledge_sync_recover":
            return {"schemaVersion": 1, "projectId": args["project_id"], "operationId": args["operation_id"],
                    "recoveryId": value["operationId"], "state": value["state"], "code": value["code"], "readyForCutover": False}
        return value
    except TimeoutError as exc:
        if action in _APPEARANCE_SCHEMAS:
            raise ValueError("Launcher外观操作尚未确认，请读取当前外观；不要自动重复上传或重新打开选择框。") from exc
        raise ValueError("原生请求尚未确认，请用原 dispatch_id 或 action/request_id 查询回执；不要更换 ID 重建对象。") from exc
    except DispatchError as exc:
        return {"ok": False, "code": exc.code, "message": str(exc)}
