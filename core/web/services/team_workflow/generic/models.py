"""Version-one public contracts and bounded input validation."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputField(Contract):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=160)
    kind: Literal["text", "paragraph", "select"]
    required: bool = False
    options: list[StrictStr] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def valid_options(self):
        if any(not value.strip() or len(value) > 240 for value in self.options):
            raise ValueError("选项不能为空或超过240字。")
        if len(set(self.options)) != len(self.options):
            raise ValueError("选项不能重复。")
        if self.kind == "select" and not self.options:
            raise ValueError("选择字段至少需要一个选项。")
        if self.kind != "select" and self.options:
            raise ValueError("只有选择字段可以设置选项。")
        return self


class ResearchSource(Contract):
    runId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    nodeId: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_:-]*$")


class SessionSource(Contract):
    sessionId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    turnId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    agentId: str = Field(min_length=1, max_length=128)


class Step(Contract):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=160)
    kind: Literal["input", "agent", "human", "output", "research", "session"]
    owner: str = Field(default="", max_length=128)
    instruction: str = Field(default="", max_length=8000)
    resultContract: Literal["text", "outcome_v1"] = "text"
    researchSource: ResearchSource | None = None
    sessionSource: SessionSource | None = None

    @model_validator(mode="after")
    def explicit_research_source(self):
        if self.kind == "research":
            if self.researchSource is None or self.sessionSource is not None or self.owner or self.instruction or self.resultContract != "text":
                raise ValueError("研究监督步骤只声明原生节点引用，不声明执行者、指令或结果契约。")
        elif self.kind == "session":
            if self.sessionSource is None or self.researchSource is not None or self.owner or self.instruction or self.resultContract != "text":
                raise ValueError("会话监督步骤只声明原生任务引用，不声明执行者、指令或结果契约。")
        elif self.researchSource is not None or self.sessionSource is not None:
            raise ValueError("只有原生监督步骤可以引用原生来源。")
        return self


class FailureRecoveryPolicy(Contract):
    """Explicit opt-in; grants no tools, membership or deployment permission."""

    repairFlowId: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    directorAgentId: str = Field(min_length=1, max_length=128)
    reviewerAgentId: str = Field(min_length=1, max_length=128)
    replaySafety: Literal["read_only", "idempotent", "unknown"] = "unknown"
    maxAttempts: int = Field(default=3, ge=1, le=3, strict=True)
    maxRepairAttempts: int = Field(default=2, ge=1, le=3, strict=True)
    repairTimeoutSeconds: int = Field(default=1800, ge=60, le=86400, strict=True)
    assistantAgentId: str = Field(default="", max_length=128)
    developerAgentId: str = Field(default="", max_length=128)
    bindingId: str = Field(default="", max_length=80)
    expiresAt: str = Field(default="", max_length=80)
    repairFlowRevision: int = Field(default=0, ge=0, strict=True)
    agentPolicyFingerprints: dict[str, str] = Field(default_factory=dict, max_length=64)

    @model_validator(mode="after")
    def bound_authorization(self):
        if self.bindingId:
            import re
            roles = {self.assistantAgentId, self.directorAgentId, self.developerAgentId, self.reviewerAgentId}
            if "" in roles or len(roles) != 4 or self.repairFlowRevision < 1:
                raise ValueError("绑定需要四个不同的有效角色及固定修复流程版本。")
            if not roles.issubset(self.agentPolicyFingerprints):
                raise ValueError("角色授权指纹不完整。")
            if any(not key.strip() or len(key) > 128 or not re.fullmatch(r"[0-9a-f]{64}", value)
                   for key, value in self.agentPolicyFingerprints.items()):
                raise ValueError("角色授权指纹无效。")
            try:
                expiry = datetime.fromisoformat(self.expiresAt)
            except ValueError as exc:
                raise ValueError("绑定需要有效的授权期限。") from exc
            if expiry.tzinfo is None:
                raise ValueError("授权期限需要时区。")
        return self


class RecoveryBindingRequest(Contract):
    expectedRevision: int = Field(ge=1, strict=True)
    repairFlowId: str = Field(min_length=1, max_length=80)
    assistantAgentId: str = Field(min_length=1, max_length=128)
    directorAgentId: str = Field(min_length=1, max_length=128)
    developerAgentId: str = Field(min_length=1, max_length=128)
    reviewerAgentId: str = Field(min_length=1, max_length=128)
    acknowledgeAutomaticRecovery: StrictBool
    replaySafety: Literal["read_only", "idempotent", "unknown"] = "unknown"
    maxAttempts: int = Field(default=3, ge=1, le=3, strict=True)
    maxRepairAttempts: int = Field(default=2, ge=1, le=3, strict=True)
    repairTimeoutSeconds: int = Field(default=1800, ge=60, le=86400, strict=True)
    validForSeconds: int = Field(default=86400, ge=60, le=604800, strict=True)

    @model_validator(mode="after")
    def intentional_binding(self):
        if not self.acknowledgeAutomaticRecovery:
            raise ValueError("绑定需要明确启用自动恢复。")
        roles = (self.assistantAgentId, self.directorAgentId, self.developerAgentId, self.reviewerAgentId)
        if any(not role.strip() for role in roles) or len(set(roles)) != 4:
            raise ValueError("个人助理、总监、开发者和验收者必须是四个不同的 Agent。")
        return self


class RecoveryBindingRevoke(Contract):
    expectedRevision: int = Field(ge=1, strict=True)


class RecoveryBindingStatus(Contract):
    schemaVersion: Literal[1] = 1
    teamId: str
    flowId: str
    sourceRevision: int
    status: Literal["unbound", "legacy", "ready", "unavailable", "expired"]
    reason: str = ""
    bindingId: str = ""
    expiresAt: str = ""
    assistantAgentId: str = ""
    directorAgentId: str = ""
    developerAgentId: str = ""
    reviewerAgentId: str = ""
    repairFlowId: str = ""
    automaticLocalIntegration: Literal[False] = False
    automaticDeployment: Literal[False] = False


class RecoveryState(Contract):
    issueId: str
    nodeId: str
    status: Literal["tracking", "retrying", "repairing", "awaiting_deployment",
                    "awaiting_replay_decision", "replaying", "resolved", "blocked", "cancelled"]
    failureCount: int = 0
    repairAttempts: int = 0
    repairRunId: str = ""
    reason: str = ""
    evidenceRefs: list[str] = Field(default_factory=list, max_length=20)
    reviewerSessionId: str = ""
    reviewerTurnId: str = ""
    sourceAttemptKey: str = ""
    replayedAttemptKey: str = ""


class RepairVerdict(Contract):
    verdict: Literal["passed", "failed"]
    deploymentRequired: StrictBool
    effectVerified: StrictBool = False
    evidenceRefs: list[StrictStr] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def bounded_evidence(self):
        if any(not ref.strip() or len(ref) > 500 for ref in self.evidenceRefs):
            raise ValueError("验收证据引用不能为空或超过500字。")
        return self


class Flow(Contract):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    fields: list[InputField] = Field(default_factory=list, max_length=40)
    steps: list[Step] = Field(default_factory=list, max_length=60)
    revision: int = Field(default=0, ge=0)
    updatedAt: str = Field(default="", max_length=80)
    failureRecovery: FailureRecoveryPolicy | None = None

    @model_validator(mode="after")
    def unique_ids(self):
        if any(step.kind in {"research", "session"} for step in self.steps) and (len(self.steps) != 1 or self.fields):
            raise ValueError("原生监督流程只允许一个原生任务引用，不能混入执行步骤或输入。")
        if not self.name.strip() or any(not item.label.strip() for item in [*self.fields, *self.steps]):
            raise ValueError("流程名称和字段、步骤名称不能为空。")
        for items in (self.fields, self.steps):
            if len({item.id for item in items}) != len(items):
                raise ValueError("字段或步骤ID不能重复。")
        return self


class SaveFlow(Contract):
    flow: Flow
    expectedRevision: int = Field(ge=0)


class StartRun(Contract):
    values: dict[str, StrictStr] = Field(default_factory=dict, max_length=40)
    expectedRevision: int = Field(ge=1)
    idempotencyKey: str = Field(min_length=1, max_length=160)


class Command(Contract):
    action: Literal["confirm", "revise", "retry", "stop", "confirm_deployment"]
    expectedRevision: int = Field(ge=1)
    evidenceRef: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def deployment_evidence(self):
        if self.action == "confirm_deployment" and not self.evidenceRef.strip():
            raise ValueError("部署确认需要证据引用，确认后仍需重新验收。")
        if self.action != "confirm_deployment" and self.evidenceRef:
            raise ValueError("只有部署确认可以携带部署证据。")
        return self


class Attempt(Contract):
    nodeId: str
    number: int
    agentId: str
    sessionId: str = ""
    turnId: str = ""
    originTurnId: str = ""
    recoveryTurnIds: list[str] = Field(default_factory=list, max_length=32)
    status: Literal["dispatching", "running", "completed", "failed", "stopped"]
    key: str
    promptHash: str = ""
    failureCode: str = ""
    failureOrigin: Literal["native", "result_contract"] = "native"


class Run(Contract):
    id: str
    teamId: str
    flow: Flow
    values: dict[str, str]
    status: Literal["running", "waiting", "completed", "failed", "stopped"]
    current: int
    revision: int
    messages: list[str] = Field(default_factory=list)
    error: str = ""
    attempts: list[Attempt] = Field(default_factory=list)
    stopRequested: bool = False
    createdAt: str = ""
    updatedAt: str = ""
    recovery: RecoveryState | None = None


class FlowList(Contract):
    schemaVersion: Literal[1] = 1
    teamId: str
    flows: list[Flow]


class RunList(Contract):
    teamId: str
    runs: list[Run]


class Artifact(Contract):
    nodeId: str
    label: str
    sessionId: str
    turnId: str
    content: str
    chatUrl: str = ""


class ArtifactList(Contract):
    artifacts: list[Artifact]
