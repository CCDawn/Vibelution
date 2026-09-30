"""Public contracts for the runtime task query routes (/aux backend).

Cards intentionally mirror the registry snapshot's user-facing subset; fields
that only exist for some kinds (``childSessionId``, ``outputPath``) are set
only when present, so routes use ``response_model_exclude_unset=True``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

RuntimeTaskKind = Literal["cli_agent", "child_session", "research_task"]
StopInitiator = Literal["user", "model"]


class RuntimeTaskCard(BaseModel):
    model_config = ConfigDict(extra="allow")

    taskId: str = ""
    kind: RuntimeTaskKind = "cli_agent"
    status: str = ""
    title: str = ""
    parentSessionId: str = ""
    startedAt: str = ""
    endedAt: str = ""
    summary: str = ""
    childSessionId: str = ""
    outputPath: str = ""


class RuntimeTaskEndedPage(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[RuntimeTaskCard] = []
    total: int = 0
    nextCursor: str = ""


class RuntimeTaskListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    revision: str = ""
    running: list[RuntimeTaskCard] = []
    ended: RuntimeTaskEndedPage = RuntimeTaskEndedPage()


class RuntimeTaskDetailResponse(RuntimeTaskCard):
    model_config = ConfigDict(extra="allow")

    stopInitiator: str | None = None
    pendingMessageCount: int = 0
    timeline: list[dict[str, Any]] = []


class RuntimeTaskStopRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    initiator: StopInitiator = "user"


class RuntimeTaskStopResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    accepted: bool = False
    taskId: str = ""
    status: str = ""
    stopInitiator: str | None = None
