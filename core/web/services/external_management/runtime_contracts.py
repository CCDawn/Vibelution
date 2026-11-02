"""Closed operator projections over existing runtime owners; no transcript data."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RuntimeKind = Literal["session_turn", "runtime_task", "external_task", "team_run",
                      "supervised_run", "self_evolution_run", "research_run"]
RuntimeCommandName = Literal["stop", "pause", "resume", "retry", "confirm"]
_ID = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$"
_OPTIONAL_ID = r"^(?:[A-Za-z0-9][A-Za-z0-9_.:-]{0,159})?$"


class RuntimeClosed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RuntimeOperationsQuery(RuntimeClosed):
    kind: RuntimeKind | None = None
    state: Literal["active", "terminal", "all"] = "active"
    offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=3, ge=1, le=3)
    expected_snapshot: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class RuntimeOperationQuery(RuntimeClosed):
    kind: RuntimeKind
    resource_id: str = Field(pattern=_ID)
    session_id: str = Field(default="", pattern=_OPTIONAL_ID)
    team_id: str = Field(default="", pattern=_OPTIONAL_ID)
    flow_id: str = Field(default="", pattern=_OPTIONAL_ID)

    @model_validator(mode="after")
    def owner_references(self):
        if self.kind == "session_turn":
            valid = bool(self.session_id) and not self.team_id and not self.flow_id
        elif self.kind == "team_run":
            valid = bool(self.team_id) and not self.session_id
        elif self.kind == "research_run":
            valid = bool(self.team_id and self.flow_id) and not self.session_id
        else:
            valid = not any((self.session_id, self.team_id, self.flow_id))
        if not valid:
            raise ValueError("Exact native owner references required")
        return self


class RuntimeCommand(RuntimeOperationQuery):
    command: RuntimeCommandName
    expected_revision: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")


class RuntimeOperation(RuntimeClosed):
    kind: RuntimeKind
    resourceId: str = Field(pattern=_ID)
    status: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    revision: str = Field(max_length=160, pattern=r"^[A-Za-z0-9_.:-]*$")
    agentId: str = Field(default="", pattern=_OPTIONAL_ID)
    sessionId: str = Field(default="", pattern=_OPTIONAL_ID)
    teamId: str = Field(default="", pattern=_OPTIONAL_ID)
    flowId: str = Field(default="", pattern=_OPTIONAL_ID)
    commands: list[RuntimeCommandName] = Field(max_length=5)
    progressFingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @field_validator("commands")
    @classmethod
    def unique_commands(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Unique native commands required")
        return value


class RuntimeCoverage(RuntimeClosed):
    source: RuntimeKind
    state: Literal["available", "unavailable", "partial"]
    complete: bool

    @model_validator(mode="after")
    def availability(self):
        if self.complete and self.state != "available":
            raise ValueError("Unavailable or partial source cannot prove completeness")
        return self


class RuntimeUntrusted(RuntimeClosed):
    untrustedContent: Literal[True]

    @field_validator("untrustedContent", mode="before")
    @classmethod
    def explicit_untrusted(cls, value):
        if value is not True:
            raise ValueError("Explicit untrusted marker required")
        return value


class RuntimeOperationsResponse(RuntimeUntrusted):
    snapshot: str = Field(pattern=r"^[a-f0-9]{64}$")
    operations: list[RuntimeOperation] = Field(max_length=3)
    offset: int = Field(ge=0, le=1_000_000)
    total: int = Field(ge=0, le=1_000_000)
    nextOffset: int | None = Field(ge=0, le=1_000_000)
    coverage: list[RuntimeCoverage] = Field(min_length=1, max_length=7)
    complete: bool

    @model_validator(mode="after")
    def coherent_projection(self):
        sources = [item.source for item in self.coverage]
        if len(sources) != len(set(sources)):
            raise ValueError("Unique source coverage required")
        if self.complete != all(item.complete and item.state == "available" for item in self.coverage):
            raise ValueError("Completeness must agree with native source coverage")
        end = self.offset + len(self.operations)
        if (self.operations and end > self.total or self.offset < self.total and not self.operations
            or self.nextOffset != (end if end < self.total else None)):
            raise ValueError("Consistent runtime pagination required")
        refs = [(item.kind, item.resourceId, item.sessionId, item.teamId, item.flowId) for item in self.operations]
        if len(refs) != len(set(refs)):
            raise ValueError("Duplicate native operation")
        return self


class RuntimeOperationResponse(RuntimeUntrusted):
    operation: RuntimeOperation


class RuntimeCommandResponse(RuntimeOperationResponse):
    command: RuntimeCommandName
    accepted: bool
    stopRequested: bool
    revisionCheck: Literal["native_cas", "preflight_only"]

    @model_validator(mode="after")
    def asynchronous_stop(self):
        if self.stopRequested and (self.command != "stop" or not self.accepted):
            raise ValueError("Stop intent requires an accepted native stop command")
        return self
