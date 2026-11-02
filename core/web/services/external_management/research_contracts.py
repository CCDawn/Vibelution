"""Closed metadata and semantic controls for the formal Research Ledger."""
from typing import Literal

from pydantic import Field, model_validator

from .runtime_contracts import RuntimeClosed, RuntimeOperation, RuntimeUntrusted, _ID, _OPTIONAL_ID

ResearchCommandName = Literal["retry_node", "resolve_human_task", "reconcile_run"]


class ResearchReference(RuntimeClosed):
    run_id: str = Field(pattern=_ID)
    team_id: str = Field(pattern=_ID)
    flow_id: str = Field(pattern=_ID)


class ResearchReadQuery(ResearchReference):
    node_offset: int = Field(default=0, ge=0, le=1_000_000)
    human_task_offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=3, ge=1, le=3)
    expected_revision: str = Field(default="", pattern=r"^(?:[1-9][0-9]{0,18})?$")
    expected_snapshot: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def bound_page(self):
        if ((self.node_offset or self.human_task_offset) and not (self.expected_revision and self.expected_snapshot)
                or self.expected_revision and int(self.expected_revision) > 2**63 - 1):
            raise ValueError("Continuation requires the original native revision and metadata snapshot")
        return self


class ResearchCommand(ResearchReference):
    command: ResearchCommandName
    expected_revision: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    node_id: str = Field(default="", pattern=_OPTIONAL_ID)
    task_id: str = Field(default="", pattern=_OPTIONAL_ID)
    decision: Literal["", "accept", "reject", "revise"] = ""
    checkpoint_id: str = Field(default="", pattern=_OPTIONAL_ID)

    @model_validator(mode="after")
    def semantic_target(self):
        if int(self.expected_revision) > 2**63 - 1:
            raise ValueError("Bounded native revision required")
        if self.command == "retry_node":
            valid = bool(self.node_id) and not self.task_id and not self.decision and not self.checkpoint_id
        elif self.command == "resolve_human_task":
            valid = bool(self.node_id and self.task_id and self.decision) and bool(self.checkpoint_id) == (self.decision == "revise")
        else:
            valid = not any((self.node_id, self.task_id, self.decision, self.checkpoint_id))
        if not valid:
            raise ValueError("Exact semantic command target required")
        return self


class ResearchNode(RuntimeClosed):
    nodeId: str = Field(pattern=_ID)
    nodeRunId: str = Field(pattern=_ID)
    status: Literal["starting", "dispatching", "running", "waiting_human", "succeeded",
                    "failed", "blocked", "cancelled", "stale"]
    attempt: int = Field(ge=1, le=2**63 - 1)
    commands: list[Literal["retry_node"]] = Field(max_length=1)


class ResearchHumanTask(RuntimeClosed):
    taskId: str = Field(pattern=_ID)
    nodeId: str = Field(pattern=_ID)
    nodeRunId: str = Field(pattern=_ID)
    status: Literal["pending"]
    commands: list[Literal["resolve_human_task"]] = Field(max_length=1)
    decisions: list[Literal["accept", "reject", "revise"]] = Field(max_length=3)
    checkpointId: str = Field(default="", pattern=_OPTIONAL_ID)

    @model_validator(mode="after")
    def available_decisions(self):
        if (len(set(self.decisions)) != len(self.decisions)
                or bool(self.checkpointId) != ("revise" in self.decisions)
                or bool(self.commands) != bool(self.decisions)):
            raise ValueError("Native human-task decisions must agree with checkpoint availability")
        return self


class ResearchReadResponse(RuntimeUntrusted):
    operation: RuntimeOperation
    snapshot: str = Field(pattern=r"^[a-f0-9]{64}$")
    nodes: list[ResearchNode] = Field(max_length=3)
    humanTasks: list[ResearchHumanTask] = Field(max_length=3)
    commands: list[Literal["reconcile_run"]] = Field(max_length=1)
    nodeOffset: int = Field(ge=0, le=1_000_000)
    humanTaskOffset: int = Field(ge=0, le=1_000_000)
    nodeTotal: int = Field(ge=0, le=1_000_000)
    humanTaskTotal: int = Field(ge=0, le=1_000_000)
    nextNodeOffset: int | None = Field(ge=0, le=1_000_000)
    nextHumanTaskOffset: int | None = Field(ge=0, le=1_000_000)
    complete: Literal[True]

    @model_validator(mode="after")
    def native_page(self):
        if self.operation.kind != "research_run":
            raise ValueError("Research run required")
        for rows, offset, total, next_offset, key in (
            (self.nodes, self.nodeOffset, self.nodeTotal, self.nextNodeOffset, "nodeId"),
            (self.humanTasks, self.humanTaskOffset, self.humanTaskTotal, self.nextHumanTaskOffset, "taskId"),
        ):
            end = offset + len(rows)
            if ((rows and end > total) or (offset < total and not rows)
                    or next_offset != (end if end < total else None)
                    or len({getattr(item, key) for item in rows}) != len(rows)):
                raise ValueError("Consistent native metadata page required")
        return self


class ResearchReceipt(RuntimeClosed):
    commandId: str = Field(pattern=_ID)
    runId: str = Field(pattern=_ID)
    teamId: str = Field(pattern=_ID)
    flowId: str = Field(pattern=_ID)
    command: ResearchCommandName
    requestId: str = Field(pattern=_ID)
    expectedRevision: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    acceptedRevision: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    nodeId: str = Field(default="", pattern=_OPTIONAL_ID)
    taskId: str = Field(default="", pattern=_OPTIONAL_ID)
    decision: Literal["", "accept", "reject", "revise"] = ""
    checkpointId: str = Field(default="", pattern=_OPTIONAL_ID)
    childRunId: str = Field(default="", pattern=_OPTIONAL_ID)


class ResearchCommandResponse(RuntimeUntrusted):
    operation: RuntimeOperation
    command: ResearchCommandName
    accepted: Literal[True]
    revisionCheck: Literal["native_cas"]
    receipt: ResearchReceipt

    @model_validator(mode="after")
    def bound_receipt(self):
        if (self.operation.kind != "research_run" or self.command != self.receipt.command
                or (self.operation.resourceId, self.operation.teamId, self.operation.flowId)
                != (self.receipt.runId, self.receipt.teamId, self.receipt.flowId)):
            raise ValueError("Native command receipt identity mismatch")
        receipt = self.receipt
        ResearchCommand(run_id=receipt.runId, team_id=receipt.teamId, flow_id=receipt.flowId,
            command=receipt.command, expected_revision=receipt.expectedRevision,
            node_id=receipt.nodeId, task_id=receipt.taskId, decision=receipt.decision, checkpoint_id=receipt.checkpointId)
        if (int(receipt.acceptedRevision) != int(receipt.expectedRevision) + 1
                or not self.operation.revision.isdecimal()
                or int(self.operation.revision) < int(receipt.acceptedRevision)
                or bool(receipt.childRunId) != (receipt.decision == "revise")
                or receipt.childRunId == receipt.runId):
            raise ValueError("Native CAS and fork receipt evidence required")
        return self
