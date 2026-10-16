"""Version-one public contracts and bounded input validation."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator


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


class Step(Contract):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=160)
    kind: Literal["input", "agent", "human", "output"]
    owner: str = Field(default="", max_length=128)
    instruction: str = Field(default="", max_length=8000)


class Flow(Contract):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    fields: list[InputField] = Field(default_factory=list, max_length=40)
    steps: list[Step] = Field(default_factory=list, max_length=60)
    revision: int = Field(default=0, ge=0)
    updatedAt: str = Field(default="", max_length=80)

    @model_validator(mode="after")
    def unique_ids(self):
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
    action: Literal["confirm", "revise", "retry", "stop"]
    expectedRevision: int = Field(ge=1)


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
