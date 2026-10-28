"""Pure schemas shared by the native client and target backend; no runtime identity."""
from __future__ import annotations

from typing import Any, ClassVar, Literal
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Scope = Literal["agents:read", "agents:create", "agents:update", "agents:avatar", "agents:archive", "teams:run", "teams:read", "teams:directory:read", "rooms:read", "platform:describe", "sessions:read", "sessions:pin", "sessions:parameters:read", "legacy:receipts:read", "tasks:read"]
SCOPES = ("agents:read", "agents:create", "agents:update", "agents:avatar", "agents:archive", "teams:run", "teams:read", "teams:directory:read", "rooms:read", "platform:describe", "sessions:read", "sessions:pin", "sessions:parameters:read", "legacy:receipts:read", "tasks:read")
_AVATAR_EXTENSION = r"(?:[pP][nN][gG]|[jJ][pP][gG]|[jJ][pP][eE][gG]|[wW][eE][bB][pP]|svg)"
_AVATAR_PATH_PATTERN = r"^workspace/avatars/[A-Za-z0-9_.-]+\." + _AVATAR_EXTENSION + "$"


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class UntrustedResponse(Closed):
    untrustedContent: Literal[True]

    @field_validator("untrustedContent", mode="before")
    @classmethod
    def explicitly_untrusted(cls, value):
        if value is not True:
            raise ValueError("Explicit untrusted marker required")
        return value


class Binding(Closed):
    projectId: str = Field(min_length=1, max_length=160)
    instanceId: str = Field(min_length=1, max_length=160)


class BindSubject(Closed):
    client_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    expected_binding: Binding
    scopes: list[Scope] = Field(min_length=1, max_length=len(SCOPES))


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


class AgentArchive(Closed):
    agent_id: str = Field(min_length=1, max_length=128)
    expected_config_revision: int = Field(ge=0)


class AuthorizationUpgrade(Closed):
    expected_scopes: list[Scope] = Field(min_length=1, max_length=len(SCOPES))
    add_scopes: list[Scope] = Field(min_length=1, max_length=len(SCOPES))

    @model_validator(mode="after")
    def explicit_missing_additions(self):
        if (self.expected_scopes != sorted(set(self.expected_scopes)) or self.add_scopes != sorted(set(self.add_scopes))
            or set(self.expected_scopes) & set(self.add_scopes)):
            raise ValueError("Choose exact sorted missing additions")
        return self


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


class SessionPin(Closed):
    session_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    pinned: bool


ACTION_MODELS = {"agent_create": AgentCreate, "agent_update": AgentUpdate, "agent_avatar": AgentAvatar, "agent_archive": AgentArchive, "team_run": TeamRun, "session_pin": SessionPin, "authorization_upgrade": AuthorizationUpgrade}
ACTION_SCOPES = {"agent_create": "agents:create", "agent_update": "agents:update", "agent_avatar": "agents:avatar", "agent_archive": "agents:archive", "team_run": "teams:run", "session_pin": "sessions:pin", "authorization_upgrade": None}


def contracts() -> dict:
    descriptions = {
        "agent_create": "在目标项目创建普通低权限 Agent；必须选择显式模型，使用稳定 request_id，未知结果查询原回执。",
        "agent_update": "按原生 configRevision 更新普通 Agent 名称、对话模型、提示词或人物/任务档案；拒绝权限、身份与生命周期字段。",
        "agent_avatar": "按原生 updatedAt 使用已有头像候选或恢复默认；不接收 URL、文件上传或任意路径。",
        "agent_archive": "每次经原生审批，按 configRevision 归档普通 Agent 并封存关联 Session；protected 或关联 Session 忙时拒绝。稳定 request_id，未知结果只查询原回执，不提供 purge、reset、restore 或 force。verified 表示首次原生回读已归档，完成回执保留历史状态。",
        "team_run": "创建内置 dev-team 并受理原生工作流运行；稳定 request_id，未知结果查询原回执，只有 resumeAllowed 才可用原参数续接。",
        "session_pin": "经原生审批置顶或取消置顶普通可见 Session；不改变当前选择。verified 表示首次确认时原生元数据符合目标状态，不证明某次调用的因果；完成回执保留历史状态，当前状态用 session_get 查询。未知结果查询原 action/request_id，不能换 ID 重放。",
        "authorization_upgrade": "经原生审批显式增加当前Launcher原主体的指定缺失权限；先authorization_status读取当前scopes，expected_scopes和add_scopes必须分别排序、唯一、不重叠。不能默认升级到全部权限，查询只选所需读取权；写权另行明确选择。保留client/subject/capability和任务关联，不支持撤销或换主体。unknown或异常保持同一request_id查询management_receipt(action=authorization_upgrade)，不更换ID重试。需要operator control，旧读取scope本身不授予升级权。完成回执为历史证明，当前状态另查。",
    }
    return {name: {"action": name, "description": descriptions[name], "parameters": model.model_json_schema(),
                   "governed": name in {"team_run", "session_pin", "agent_archive", "authorization_upgrade"}, "scope": ACTION_SCOPES[name] or "operator:control"} for name, model in ACTION_MODELS.items()}


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


class LegacyObserverCreate(Closed):
    request_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    expected_binding: Binding
    source_agent_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    legacy_message_ids: list[str] = Field(min_length=1, max_length=32)
    expected_registry_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_source_authority: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("legacy_message_ids")
    @classmethod
    def exact_sorted_refs(cls, value):
        if (any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", item) for item in value)
                or value != sorted(set(value))):
            raise ValueError("Sorted unique legacy message references required")
        return value


class LegacyObserverView(UntrustedResponse):
    requestId: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    observerId: str = Field(pattern=r"^lob-[a-f0-9]{64}$")
    status: Literal["created", "unknown"]
    reused: bool
    sourceAgentId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    sourceSessionId: str | None = Field(default=None, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    legacyMessageIds: list[str] = Field(min_length=1, max_length=32)
    actions: list[Literal["read_receipt"]] = Field(min_length=1, max_length=1)
    ownerEpoch: Literal[1]
    sourceQuiesced: Literal[False]
    readyForCutover: Literal[False]

    @field_validator("ownerEpoch", mode="before")
    @classmethod
    def exact_epoch(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Exact observation epoch required")
        return value

    @field_validator("sourceQuiesced", "readyForCutover", mode="before")
    @classmethod
    def no_cutover_claim(cls, value):
        if value is not False:
            raise ValueError("Observation does not establish cutover")
        return value

    @model_validator(mode="after")
    def coherent_observer(self):
        LegacyObserverCreate.exact_sorted_refs(self.legacyMessageIds)
        if self.status == "created" and self.sourceSessionId is None:
            raise ValueError("Created observation requires its original source Session")
        return self


class LegacyObserversResponse(UntrustedResponse):
    observers: list[LegacyObserverView] = Field(max_length=32)

    @model_validator(mode="after")
    def unique_sorted_observers(self):
        ids = [observer.observerId for observer in self.observers]
        if ids != sorted(set(ids)):
            raise ValueError("Unique sorted observation directory required")
        return self


class LegacyReceiptView(Closed):
    legacyMessageId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    taskStatus: Literal["running", "blocked", "completed", "failed"]
    evidenceCount: int = Field(ge=0, le=5)


class LegacyDispatchView(Closed):
    legacyMessageId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    targetAgentId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    targetSessionId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    businessTaskStatus: Literal["running", "blocked", "completed", "failed", "cancelled", "awaiting_result", "awaiting_confirmation", "unresolved"]
    nativeCorrelation: Literal["correlated", "unresolved"]
    nativeTurnId: str | None = Field(default=None, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    nativeRunId: str | None = Field(default=None, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    nativeTaskId: None = None
    nativeTurnStatus: Literal["running", "completed", "failed", "interrupted"] | None = None
    nativeRunReason: str = Field(min_length=1, max_length=96, pattern=r"^[a-z0-9_]+$")
    reason: str = Field(min_length=1, max_length=96, pattern=r"^[a-z0-9_]+$")
    receipts: list[LegacyReceiptView] = Field(max_length=32)
    receiptCount: int = Field(ge=0, le=10000)
    receiptsTruncated: bool

    @model_validator(mode="after")
    def coherent_receipts(self):
        ids = [receipt.legacyMessageId for receipt in self.receipts]
        if (len(set(ids)) != len(ids) or self.receiptCount < len(ids)
                or self.receiptsTruncated != (self.receiptCount > len(ids))
                or self.nativeRunId is not None and self.nativeRunId != self.nativeTurnId
                or self.nativeCorrelation == "correlated" and self.nativeTurnId is None):
            raise ValueError("Inconsistent observation receipt proof")
        return self


class LegacyReceiptsResponse(UntrustedResponse):
    observer: LegacyObserverView
    dispatches: list[LegacyDispatchView] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def only_granted_refs(self):
        if self.observer.status != "created" or [row.legacyMessageId for row in self.dispatches] != self.observer.legacyMessageIds:
            raise ValueError("Receipt response must exactly match the observation grant")
        return self


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


class DirectoryQuery(Closed):
    query: str = Field(default="", max_length=64)
    offset: int = Field(default=0, ge=0, le=100_000)
    limit: int = Field(default=6, ge=1, le=6)
    archived: bool = False

    @field_validator("query")
    @classmethod
    def single_line(cls, value):
        if any(unicodedata.category(char) in {"Cc", "Cf"} for char in value):
            raise ValueError("Single-line query required")
        return value


class ActiveTasksQuery(Closed):
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=6, ge=1, le=6)


class ActiveTask(Closed):
    taskId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    kind: Literal["cli_agent", "child_session", "research_task"]
    status: Literal["queued", "sent", "running", "idle"]
    summary: Literal["CLI agent task", "Child session task", "Research task"]
    startedAt: str = Field(max_length=40, pattern=r"^(?:|[0-9TZ+:.\-]+)$")
    updatedAt: str = Field(min_length=1, max_length=40, pattern=r"^[0-9TZ+:.\-]+$")

    @model_validator(mode="after")
    def fixed_summary(self):
        if self.summary != {"cli_agent": "CLI agent task", "child_session": "Child session task", "research_task": "Research task"}[self.kind]:
            raise ValueError("Invalid task summary")
        return self


class ActiveTasksResponse(UntrustedResponse):
    source: Literal["native-active-task-index"]
    coverage: Literal["active index only; may omit active tasks; total counts indexed tasks only, not all active tasks or project health"]
    indexCompleteness: Literal["unknown"]
    tasks: list[ActiveTask] = Field(max_length=6)
    offset: int = Field(ge=0, le=10000)
    total: int = Field(ge=0, le=10000)
    nextOffset: int | None = Field(ge=0, le=10000)

    @model_validator(mode="after")
    def coherent_page(self):
        ids = [item.taskId for item in self.tasks]
        end = self.offset + len(ids)
        if (ids != sorted(set(ids)) or ids and end > self.total or self.offset < self.total and not ids
                or self.nextOffset != (end if end < self.total else None)):
            raise ValueError("Inconsistent active task page")
        return self

class TeamReadQuery(Closed):
    team_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    member_offset: int = Field(default=0, ge=0, le=120)
    limit: int = Field(default=6, ge=1, le=6)


class RoomReadQuery(Closed):
    room_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


class DirectoryItem(Closed):
    id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    status: str = Field(min_length=1, max_length=32)


class TeamSummary(DirectoryItem):
    status: Literal["active", "archived"]
    name: str = Field(max_length=32)
    purpose: str = Field(max_length=64)
    memberCount: int = Field(ge=0, le=120)


class RoomSummary(DirectoryItem):
    status: Literal["ready", "running", "stopping", "failed", "archived"]
    title: str = Field(max_length=120)


class DirectoryPage(UntrustedResponse):
    _items_field: ClassVar[str]
    offset: int = Field(ge=0, le=100_000)
    total: int = Field(ge=0, le=100_000)
    nextOffset: int | None = Field(ge=0, le=100_000)
    @model_validator(mode="after")
    def coherent_page(self):
        items = getattr(self, self._items_field)
        ids = [item.id for item in items]
        end = self.offset + len(ids)
        if (ids != sorted(set(ids)) or ids and end > self.total or self.offset < self.total and not ids
            or self.nextOffset != (end if end < self.total else None)):
            raise ValueError("Inconsistent directory page")
        return self


class TeamListResponse(DirectoryPage):
    _items_field = "teams"
    teams: list[TeamSummary] = Field(max_length=6)


class RoomListResponse(DirectoryPage):
    _items_field = "rooms"
    rooms: list[RoomSummary] = Field(max_length=6)


class TeamMember(Closed):
    agentId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


class TeamView(DirectoryItem):
    status: Literal["active", "archived"]
    name: str = Field(max_length=120)
    purpose: str = Field(max_length=240)
    members: list[TeamMember] = Field(max_length=6)
    memberOffset: int = Field(ge=0, le=120)
    memberTotal: int = Field(ge=0, le=120)
    nextMemberOffset: int | None = Field(ge=0, le=120)

    @model_validator(mode="after")
    def coherent_members(self):
        end = self.memberOffset + len(self.members)
        if (len({member.agentId for member in self.members}) != len(self.members)
            or self.members and end > self.memberTotal or self.memberOffset < self.memberTotal and not self.members
            or self.nextMemberOffset != (end if end < self.memberTotal else None)):
            raise ValueError("Inconsistent Team member page")
        return self


class TeamReadResponse(UntrustedResponse):
    team: TeamView


class RoomReadResponse(UntrustedResponse):
    room: RoomSummary


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


class SessionBudgetView(Closed):
    revision: int = Field(ge=0)
    maxCallsPerTurn: int | None = Field(ge=0, le=2**53 - 1)


class SessionParametersView(Closed):
    sessionId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    agentId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    configRevision: int = Field(ge=0)
    currentModelId: str = Field(min_length=1, max_length=300)
    currentReasoningEffort: Literal["", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"]
    reasoningEffortValues: list[Literal["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"]] = Field(max_length=8)
    contextWindow: int = Field(ge=0, le=2**53 - 1)
    maxContextWindow: int = Field(ge=0, le=2**53 - 1)
    budget: SessionBudgetView

    @model_validator(mode="after")
    def consistent_values(self):
        if (self.configRevision != self.budget.revision or self.contextWindow > self.maxContextWindow
            or len(set(self.reasoningEffortValues)) != len(self.reasoningEffortValues)
            or self.currentReasoningEffort and self.currentReasoningEffort not in self.reasoningEffortValues):
            raise ValueError("Inconsistent parameter snapshot")
        return self


class SessionParametersResponse(UntrustedResponse):
    source: Literal["native-current-agent-runtime-parameters"]
    catalogState: Literal["existing", "absent"]
    parameters: SessionParametersView


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


class AuthorizationView(Closed):
    subjectId: str = Field(pattern=r"^ops-[0-9a-f]{32}$")
    previousScopes: list[Scope] = Field(min_length=1, max_length=len(SCOPES))
    addedScopes: list[Scope] = Field(min_length=1, max_length=len(SCOPES))
    scopes: list[Scope] = Field(min_length=1, max_length=len(SCOPES))
    grantRevision: int = Field(ge=1)

    @model_validator(mode="after")
    def exact_additions(self):
        if (any(values != sorted(set(values)) for values in (self.previousScopes, self.addedScopes, self.scopes))
            or set(self.previousScopes) & set(self.addedScopes)
            or self.scopes != sorted(set(self.previousScopes) | set(self.addedScopes))):
            raise ValueError("Invalid authorization proof")
        return self


class AuthorizationStateResponse(Closed):
    subjectId: str = Field(pattern=r"^ops-[0-9a-f]{32}$")
    binding: Binding
    scopes: list[Scope] = Field(min_length=1, max_length=len(SCOPES))
    grantRevision: int = Field(ge=0)

    @field_validator("scopes")
    @classmethod
    def exact_scopes(cls, value):
        if value != sorted(set(value)):
            raise ValueError("Invalid authorization state")
        return value


class ReceiptResponse(Closed):
    status: Literal["completed", "unknown"]
    action: Literal["agent_create", "agent_update", "agent_avatar", "agent_archive", "team_run", "session_pin", "authorization_upgrade"]
    requestId: str
    verified: bool
    reused: bool
    agent: AgentView | None = None
    session: SessionView | None = None
    authorization: AuthorizationView | None = None
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


DocumentationAction = Literal["session_list", "agent_create", "agent_update", "agent_avatar", "agent_archive", "session_config_get", "session_config_compare", "session_parameters_get", "session_pin", "team_list", "team_get", "room_list", "room_get", "authorization_status", "legacy_observers", "legacy_receipts"]
# This maps documentation to already-migrated semantic actions. It grants no
# HTTP execution and deliberately advertises no other registered API operation.
DOCUMENTATION_ACTIONS = {
    ("GET", "/api/v1/launcher-assistant-management/sessions"): "session_list",
    ("POST", "/api/agents"): "agent_create",
    ("PATCH", "/api/agents/{agent_id}"): "agent_update",
    ("PATCH", "/api/agents/{agent_id}/avatar"): "agent_avatar",
    ("DELETE", "/api/agents/{agent_id}"): "agent_archive",
    ("GET", "/api/v1/launcher-assistant-management/sessions/{session_id}/config"): "session_config_get",
    ("GET", "/api/v1/launcher-assistant-management/sessions/{session_id}/config-comparison"): "session_config_compare",
    ("POST", "/api/sessions/{session_id}/pin"): "session_pin",
    ("POST", "/api/sessions/{session_id}/unpin"): "session_pin",
    ("GET", "/api/teams"): "team_list",
    ("GET", "/api/teams/{team_id}"): "team_get",
    ("GET", "/api/chat-rooms"): "room_list",
    ("GET", "/api/chat-rooms/{room_id}"): "room_get",
    ("GET", "/api/v1/launcher-assistant-management/directory/teams"): "team_list",
    ("GET", "/api/v1/launcher-assistant-management/directory/teams/{team_id}"): "team_get",
    ("GET", "/api/v1/launcher-assistant-management/directory/rooms"): "room_list",
    ("GET", "/api/v1/launcher-assistant-management/directory/rooms/{room_id}"): "room_get",
    ("GET", "/api/v1/launcher-assistant-management/sessions/{session_id}/parameters"): "session_parameters_get",
    ("GET", "/api/v1/launcher-assistant-management/authorization"): "authorization_status",
    ("GET", "/api/v1/launcher-assistant-management/legacy-observers"): "legacy_observers",
    ("GET", "/api/v1/launcher-assistant-management/legacy-observers/{observer_id}/receipts"): "legacy_receipts",
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
