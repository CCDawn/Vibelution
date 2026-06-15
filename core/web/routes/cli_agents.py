"""CLI Agent terminal session routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.web.services.cli_agent_terminal_service import (
    CliAgentTerminalError,
    ensure_cli_agent_terminal_session,
    get_cli_agent_terminal_session,
    resize_cli_agent_terminal_session,
    stop_cli_agent_terminal_session,
    stream_cli_agent_terminal_events,
    write_cli_agent_terminal_input,
)
from core.web.services.session_service import append_cli_agent_lifecycle_event


router = APIRouter(tags=["cli-agents"])


class CliAgentTerminalEnsurePayload(BaseModel):
    agentType: str = ""
    task: str = ""
    cwd: str = ""
    mode: str = "readonly"
    model: str = ""
    agent: str = ""
    sourceSessionId: str = ""
    sourceMessageId: str = ""
    sourceRunId: str = ""
    cliSessionId: str = ""
    rows: int = Field(default=28, ge=4, le=120)
    cols: int = Field(default=100, ge=20, le=240)
    sendInitialTask: bool = False


class CliAgentTerminalInputPayload(BaseModel):
    data: str = ""


class CliAgentTerminalResizePayload(BaseModel):
    rows: int = Field(default=28, ge=4, le=120)
    cols: int = Field(default=100, ge=20, le=240)


def _raise_terminal_error(exc: CliAgentTerminalError) -> None:
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    if exc.code in {"TERMINAL_SESSION_NOT_FOUND", "UNSUPPORTED_CLI_AGENT"}:
        status_code = status.HTTP_404_NOT_FOUND
    if exc.code in {"TERMINAL_SESSION_NOT_RUNNING", "WORKTREE_REQUIRED", "CWD_OUTSIDE_ALLOWED_ROOTS"}:
        status_code = status.HTTP_409_CONFLICT
    raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/cli-agents/terminal-sessions/ensure")
def cli_agent_terminal_ensure(payload: CliAgentTerminalEnsurePayload) -> dict[str, Any]:
    try:
        return ensure_cli_agent_terminal_session(
            agent_type=payload.agentType,
            task=payload.task,
            cwd=payload.cwd,
            mode=payload.mode,
            model=payload.model,
            agent=payload.agent,
            source_session_id=payload.sourceSessionId,
            source_message_id=payload.sourceMessageId,
            source_run_id=payload.sourceRunId,
            cli_session_id=payload.cliSessionId,
            rows=payload.rows,
            cols=payload.cols,
            send_initial_task=payload.sendInitialTask,
        )
    except CliAgentTerminalError as exc:
        _raise_terminal_error(exc)


@router.get("/cli-agents/terminal-sessions/{terminal_session_id}")
def cli_agent_terminal_detail(terminal_session_id: str, includeTranscriptTail: bool = False) -> dict[str, Any]:
    try:
        return get_cli_agent_terminal_session(terminal_session_id, include_transcript_tail=includeTranscriptTail)
    except CliAgentTerminalError as exc:
        _raise_terminal_error(exc)


@router.get("/cli-agents/terminal-sessions/{terminal_session_id}/events")
def cli_agent_terminal_events(terminal_session_id: str) -> StreamingResponse:
    try:
        get_cli_agent_terminal_session(terminal_session_id)
    except CliAgentTerminalError as exc:
        _raise_terminal_error(exc)
    return StreamingResponse(
        stream_cli_agent_terminal_events(terminal_session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/cli-agents/terminal-sessions/{terminal_session_id}/input")
def cli_agent_terminal_input(terminal_session_id: str, payload: CliAgentTerminalInputPayload) -> dict[str, Any]:
    try:
        return write_cli_agent_terminal_input(terminal_session_id, payload.data)
    except CliAgentTerminalError as exc:
        _raise_terminal_error(exc)


@router.post("/cli-agents/terminal-sessions/{terminal_session_id}/resize")
def cli_agent_terminal_resize(terminal_session_id: str, payload: CliAgentTerminalResizePayload) -> dict[str, Any]:
    try:
        return resize_cli_agent_terminal_session(terminal_session_id, payload.rows, payload.cols)
    except CliAgentTerminalError as exc:
        _raise_terminal_error(exc)


@router.post("/cli-agents/terminal-sessions/{terminal_session_id}/stop")
def cli_agent_terminal_stop(terminal_session_id: str) -> dict[str, Any]:
    try:
        session = stop_cli_agent_terminal_session(terminal_session_id)
        source_session_id = str(session.get("sourceSessionId") or "").strip()
        if source_session_id:
            lifecycle_event = append_cli_agent_lifecycle_event(
                source_session_id,
                event="closed",
                terminal_session=session,
            )
            if lifecycle_event is not None:
                session["lifecycleEvent"] = lifecycle_event
        return session
    except CliAgentTerminalError as exc:
        _raise_terminal_error(exc)
