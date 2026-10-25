"""Pure schemas shared by the native client and target backend; no runtime identity."""
from __future__ import annotations

from typing import Any, Literal
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Scope = Literal["agents:read", "agents:create", "agents:update", "agents:avatar", "teams:run", "teams:read", "platform:describe", "sessions:read"]
SCOPES = ("agents:read", "agents:create", "agents:update", "agents:avatar", "teams:run", "teams:read", "platform:describe", "sessions:read")
_AVATAR_EXTENSION = r"(?:[pP][nN][gG]|[jJ][pP][gG]|[jJ][pP][eE][gG]|[wW][eE][bB][pP]|svg)"
_AVATAR_PATH_PATTERN = r"^workspace/avatars/[A-Za-z0-9_.-]+\." + _AVATAR_EXTENSION + "$"


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Binding(Closed):
    projectId: str = Field(min_length=1, max_length=160)
    instanceId: str = Field(min_length=1, max_length=160)


class BindSubject(Closed):
    client_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    expected_binding: Binding
    scopes: list[Scope] = Field(min_length=1, max_length=8)


class Envelope(Closed):
    request_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    expected_binding: Binding
    parameters: dict


class AgentCreate(Closed):
    display_name: str = Field(min_length=1, max_length=120)
    model_id: str = Field(min_length=1, max_length=200)
    mission: str = Field(default="执行用户明确交办的任务，报告结果和可核验依据。", max_length=2000)

    @field_validator("display_name", "model_id")
    @classmethod
    def nonblank_single_line(cls, value):
        value = value.strip()
        if not value or len(value.splitlines()) != 1:
            raise ValueError("A nonblank single line is required")
        return value


class ModelBinding(Closed):
    modelId: str = Field(min_length=1, max_length=200)


class DialogueBindings(Closed):
    dialogue: ModelBinding


class Persona(Closed):
    gender: str | None = Field(default=None, max_length=120)
    age: str | None = Field(default=None, max_length=120)
    pronouns: str | None = Field(default=None, max_length=120)
    personality: str | None = Field(default=None, max_length=1000)
    communicationStyle: str | None = Field(default=None, max_length=1000)
    background: str | None = Field(default=None, max_length=2000)
    collaborationPreference: str | None = Field(default=None, max_length=1000)
    identityNotes: str | None = Field(default=None, max_length=2000)
    expertise: list[str] | None = Field(default=None, max_length=12)


class Task(Closed):
    mission: str | None = Field(default=None, max_length=2000)
    responsibilities: str | None = Field(default=None, max_length=2000)
    preferredTasks: str | None = Field(default=None, max_length=2000)
    avoidTasks: str | None = Field(default=None, max_length=2000)
    successCriteria: str | None = Field(default=None, max_length=2000)
    deliverables: str | None = Field(default=None, max_length=2000)
    constraints: str | None = Field(default=None, max_length=2000)
    handoffNotes: str | None = Field(default=None, max_length=2000)
    taskTypes: list[str] | None = Field(default=None, max_length=12)


class AgentUpdates(Closed):
    displayName: str | None = Field(default=None, min_length=1, max_length=120)
    llmBindings: DialogueBindings | None = None
    promptTemplateId: str | None = Field(default=None, min_length=1, max_length=160)
    personaProfile: Persona | None = None
    taskProfile: Task | None = None

    @model_validator(mode="after")
    def no_null_or_empty_update(self):
        def invalid(value):
            return value is None or (isinstance(value, dict) and (not value or any(invalid(item) for item in value.values())))
        if invalid(self.model_dump(exclude_unset=True)):
            raise ValueError("Empty and null updates are not accepted")
        return self


class AgentUpdate(Closed):
    agent_id: str = Field(min_length=1, max_length=128)
    expected_config_revision: int = Field(ge=0)
    updates: AgentUpdates


class AgentAvatar(Closed):
    agent_id: str = Field(min_length=1, max_length=128)
    expected_updated_at: str = Field(min_length=1, max_length=160)
    avatar_image_path: str = Field(default="", max_length=256, pattern="^(?:" + _AVATAR_PATH_PATTERN[1:-1] + ")?$")
    reset_to_default: bool = False

    @model_validator(mode="after")
    def exactly_one_source(self):
        if bool(self.avatar_image_path) == self.reset_to_default:
            raise ValueError("Choose one native avatar source")
        return self


class TeamRun(Closed):
    name: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=12000)
    template_id: Literal["dev-team"] = "dev-team"

    @field_validator("name", "goal")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Nonblank text required")
        return value


ACTION_MODELS = {"agent_create": AgentCreate, "agent_update": AgentUpdate, "agent_avatar": AgentAvatar, "team_run": TeamRun}
ACTION_SCOPES = {"agent_create": "agents:create", "agent_update": "agents:update", "agent_avatar": "agents:avatar", "team_run": "teams:run"}


def contracts() -> dict:
    descriptions = {
        "agent_create": "在目标项目创建普通低权限 Agent；必须选择显式模型，使用稳定 request_id，未知结果查询原回执。",
        "agent_update": "按原生 configRevision 更新普通 Agent 名称、对话模型、提示词或人物/任务档案；拒绝权限、身份与生命周期字段。",
        "agent_avatar": "按原生 updatedAt 使用已有头像候选或恢复默认；不接收 URL、文件上传或任意路径。",
        "team_run": "创建内置 dev-team 并受理原生工作流运行；稳定 request_id，未知结果查询原回执，只有 resumeAllowed 才可用原参数续接。",
    }
    return {name: {"action": name, "description": descriptions[name], "parameters": model.model_json_schema(),
                   "governed": name == "team_run", "scope": ACTION_SCOPES[name]} for name, model in ACTION_MODELS.items()}


class BindingResponse(Closed):
    protocolVersion: Literal[1]
    binding: Binding
    scopes: list[Scope]
    actions: dict


class BoundSubjectResponse(Closed):
    protocolVersion: Literal[1]
    subject_id: str
    subject_capability: str = Field(repr=False)
    binding: Binding
    scopes: list[Scope]


class AgentView(Closed):
    agentId: str
    directSessionId: str
    displayName: str
    configRevision: int
    updatedAt: str
    modelId: str
    avatarImagePath: str


class AgentReadResponse(Closed):
    agent: AgentView


class AvatarOptionsQuery(Closed):
    offset: int = Field(default=0, ge=0, le=50000)
    limit: int = Field(default=20, ge=1, le=30)


class AvatarOption(Closed):
    filename: str = Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9_.-]+\." + _AVATAR_EXTENSION + "$")
    path: str = Field(max_length=256, pattern=_AVATAR_PATH_PATTERN)

    @model_validator(mode="after")
    def matching_filename(self):
        if self.path != "workspace/avatars/" + self.filename:
            raise ValueError("Avatar identity mismatch")
        return self


class AvatarOptionsResponse(Closed):
    options: list[AvatarOption] = Field(max_length=30)
    total: int = Field(ge=0, le=50000)
    offset: int = Field(ge=0, le=50000)
    nextOffset: int | None = Field(ge=0, le=50000)
    untrustedContent: Literal[True]

    @model_validator(mode="after")
    def coherent_page(self):
        end = self.offset + len(self.options)
        if self.offset >= self.total:
            valid = not self.options and self.nextOffset is None
        else:
            valid = bool(self.options) and end <= self.total and self.nextOffset == (end if end < self.total else None)
        if not valid:
            raise ValueError("Invalid avatar page")
        return self

    @field_validator("untrustedContent", mode="before")
    @classmethod
    def explicitly_untrusted(cls, value):
        if value is not True:
            raise ValueError("Explicit untrusted marker required")
        return value


class SessionMetadataQuery(Closed):
    session_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


class SessionListQuery(Closed):
    agent_id: str = Field(default="", max_length=128, pattern=r"^(?:[A-Za-z0-9][A-Za-z0-9_.:-]*)?$")
    query: str = Field(default="", max_length=64)
    offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=6, ge=1, le=6)

    @field_validator("query")
    @classmethod
    def single_line(cls, value):
        if any(unicodedata.category(char) == "Cc" for char in value):
            raise ValueError("Single-line query required")
        return value


class SessionListItem(Closed):
    id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    agentId: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    titlePreview: str = Field(max_length=48)
    titleTruncated: bool

    @field_validator("titlePreview")
    @classmethod
    def visible_text(cls, value):
        if any(unicodedata.category(char) == "Cc" for char in value):
            raise ValueError("Control-free title required")
        return value


class SessionListResponse(Closed):
    source: Literal["native-session-directory"]
    untrustedContent: Literal[True]
    sessions: list[SessionListItem] = Field(max_length=6)
    offset: int = Field(ge=0, le=1_000_000)
    limit: int = Field(ge=0, le=6)
    total: int = Field(ge=0, le=10_000)
    nextOffset: int | None

    @field_validator("untrustedContent", mode="before")
    @classmethod
    def explicitly_untrusted(cls, value):
        if value is not True:
            raise ValueError("Explicit untrusted marker required")
        return value

    @model_validator(mode="after")
    def page_consistency(self):
        ids = [item.id for item in self.sessions]
        end = self.offset + len(ids)
        if (ids != sorted(set(ids)) or self.limit != len(ids)
            or ids and end > self.total or self.offset < self.total and not ids
            or self.nextOffset != (end if end < self.total else None)):
            raise ValueError("Inconsistent Session page")
        return self


class SessionView(Closed):
    id: str
    title: str
    agentId: str
    pinnedAtMs: int | None
    pinned: bool
    status: str
    archived: bool


class SessionReadResponse(Closed):
    session: SessionView
    untrustedContent: Literal[True] = True


class SessionConfigView(Closed):
    sessionId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    agentId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    agentConfigRevisionId: str = Field(min_length=1, max_length=225)
    modelId: str = Field(min_length=1, max_length=300)
    contextWindow: int | None = Field(gt=0, le=2**53 - 1)
    reasoningEffort: str | None = Field(max_length=40, pattern=r"^[a-z0-9_-]*$")

    @field_validator("modelId")
    @classmethod
    def opaque_single_line_model(cls, value):
        if value != value.strip() or len(value.splitlines()) != 1 or any(unicodedata.category(c) == "Cc" for c in value):
            raise ValueError("Invalid stored model identifier")
        return value

    @model_validator(mode="after")
    def bound_revision(self):
        if not re.fullmatch(re.escape(self.agentId) + r":[0-9a-f]{64}", self.agentConfigRevisionId):
            raise ValueError("Revision belongs to another Agent")
        return self


class SessionConfigResponse(Closed):
    source: Literal["session_agent_config_revision"]
    untrustedContent: Literal[True]
    config: SessionConfigView


class SessionCompiledModelConfig(Closed):
    agentConfigRevisionId: str = Field(min_length=1, max_length=225)
    modelId: str = Field(min_length=1, max_length=300)
    contextWindow: int | None = Field(gt=0, le=2**53 - 1)
    reasoningEffort: str | None = Field(max_length=40, pattern=r"^[a-z0-9_-]*$")

    @field_validator("modelId")
    @classmethod
    def opaque_single_line_model(cls, value):
        return SessionConfigView.opaque_single_line_model(value)


class SessionConfigComparisonResponse(Closed):
    """Stored scalar differences in modelId/contextWindow/reasoningEffort order."""
    source: Literal["session_agent_config_comparison"]
    untrustedContent: Literal[True]
    sessionId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    agentId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    pinned: SessionCompiledModelConfig
    current: SessionCompiledModelConfig
    sameRevision: bool
    changedFields: list[Literal["modelId", "contextWindow", "reasoningEffort"]] = Field(max_length=3)

    @model_validator(mode="after")
    def native_comparison_consistent(self):
        for config in (self.pinned, self.current):
            if not re.fullmatch(re.escape(self.agentId) + r":[0-9a-f]{64}", config.agentConfigRevisionId):
                raise ValueError("Compared revision belongs to another Agent")
        same = self.pinned.agentConfigRevisionId == self.current.agentConfigRevisionId
        changed = [field for field in ("modelId", "contextWindow", "reasoningEffort")
                   if getattr(self.pinned, field) != getattr(self.current, field)]
        if self.sameRevision is not same or self.changedFields != changed or (same and changed):
            raise ValueError("Inconsistent compiled configuration comparison")
        return self


class ReceiptResponse(Closed):
    status: Literal["completed", "unknown"]
    action: Literal["agent_create", "agent_update", "agent_avatar", "team_run"]
    requestId: str
    verified: bool
    reused: bool
    agent: AgentView | None = None
    code: Literal["OPERATION_UNCONFIRMED"] | None = None
    phase: Literal["materialization_pending", "materialized", "flow_saved", "started"] | None = None
    resumeAllowed: bool | None = None
    teamRun: TeamRunView | None = None


class TeamAttempt(Closed):
    nodeId: str
    number: int
    agentId: str
    sessionId: str
    turnId: str
    status: str


class ArtifactRef(Closed):
    nodeId: str
    sessionId: str
    turnId: str


class TeamRunView(Closed):
    teamId: str
    flowId: str
    runId: str | None = None
    status: Literal["running", "waiting", "completed", "failed", "stopped"] | None = None
    current: int | None = None
    stepCount: int | None = None
    attemptCount: int | None = None
    attempts: list[TeamAttempt] = Field(default_factory=list, max_length=20)
    attemptsTruncated: bool = False
    artifactRefs: list[ArtifactRef] = Field(default_factory=list, max_length=20)


ReceiptResponse.model_rebuild()


class DocumentationCatalogQuery(Closed):
    query: str = Field(default="", max_length=512)
    tag: str = Field(default="", max_length=128)
    offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=20, ge=1, le=50)


class DocumentationDescribeQuery(Closed):
    operation_id: str = Field(min_length=1, max_length=256)

    @field_validator("operation_id")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Operation ID required")
        return value.strip()


DocumentationAction = Literal["session_list", "agent_create", "agent_update", "agent_avatar", "session_config_get", "session_config_compare"]
# This maps documentation to already-migrated semantic actions. It grants no
# HTTP execution and deliberately advertises no other registered API operation.
DOCUMENTATION_ACTIONS = {
    ("GET", "/api/v1/launcher-assistant-management/sessions"): "session_list",
    ("POST", "/api/agents"): "agent_create",
    ("PATCH", "/api/agents/{agent_id}"): "agent_update",
    ("PATCH", "/api/agents/{agent_id}/avatar"): "agent_avatar",
    ("GET", "/api/v1/launcher-assistant-management/sessions/{session_id}/config"): "session_config_get",
    ("GET", "/api/v1/launcher-assistant-management/sessions/{session_id}/config-comparison"): "session_config_compare",
}


class DocumentationActionParameters(Closed):
    action: DocumentationAction


class DocumentationActionHelp(Closed):
    action: Literal["describe"] = "describe"
    parameters: DocumentationActionParameters


class DocumentationEntry(Closed):
    operationId: str
    method: str
    path: str
    summary: str
    tags: list[str]
    access: Literal["native_action", "operator_only"]
    executable: bool
    action: DocumentationAction | None = None
    capabilitySubset: Literal[True] | None = None
    argumentHelp: DocumentationActionHelp | None = None

    @model_validator(mode="after")
    def semantic_action_only(self):
        action = DOCUMENTATION_ACTIONS.get((self.method, self.path))
        if self.executable:
            if (self.access != "native_action" or not action or self.action != action or self.capabilitySubset is not True
                or self.argumentHelp is None or self.argumentHelp.parameters.action != action):
                raise ValueError("Only an exact migrated semantic action can be executable")
        elif self.access != "operator_only" or any(value is not None for value in (self.action, self.capabilitySubset, self.argumentHelp)):
            raise ValueError("Unmigrated operations are documentation only")
        return self


class DocumentationResponse(Closed):
    ok: bool
    status: Literal["ok", "error"]
    observedAt: str
    source: Literal["registered-openapi"]
    untrustedContent: Literal[True]
    message: str | None = None
    operationId: str | None = None
    operations: list[DocumentationEntry] | None = Field(default=None, max_length=50)
    offset: int | None = None
    limit: int | None = None
    total: int | None = None
    truncated: bool | None = None
    operation: DocumentationEntry | None = None
    description: str | None = None
    parameters: list[Any] | None = None
    requestBody: dict[str, Any] | None = None
    responses: dict[str, Any] | None = None
    components: dict[str, Any] | None = None
    omittedSchemas: list[str] | None = Field(default=None, max_length=128)
    omittedSchemaCount: int | None = None
    omittedSchemasTruncated: bool | None = None
    omittedFields: list[str] | None = None
