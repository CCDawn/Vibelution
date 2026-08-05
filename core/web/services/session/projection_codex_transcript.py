"""Codex transcript projection helpers extracted from session.projection (Wave 5)."""
from __future__ import annotations

from typing import Any, Mapping

from core.web.services.session import projection as parent


def _service():
    return parent._service()


def _build_codex_transcript_from_turn_items(
    *,
    message_id: str,
    turn_items: list[dict[str, Any]] | None,
    streaming: bool = False,
    window_slimmed: bool = False,
) -> dict[str, Any] | None:
    """One-way codexTranscript projection from SessionTurnItem v2 (renderer adapter)."""
    s = _service()
    normalized_message_id = str(message_id or "").strip()
    items = [item for item in list(turn_items or []) if isinstance(item, dict)]
    if not normalized_message_id or not items:
        return None
    cells: list[dict[str, Any]] = []
    for item in items:
        text = str(item.get("text") or item.get("summary") or item.get("title") or "").strip()
        kind = str(item.get("kind") or item.get("type") or "").strip().lower()
        phase = str(item.get("phase") or "").strip().lower()
        status = str(item.get("status") or ("running" if streaming else "completed")).strip() or "completed"
        tone = "error" if status == "failed" else ("running" if status in {"running", "in_progress", "pending"} else "neutral")
        render_id = str(
            item.get("callId")
            or item.get("itemId")
            or item.get("id")
            or f"{normalized_message_id}-{len(cells) + 1}"
        ).strip()
        cell_base = {
            "id": render_id,
            "messageId": str(item.get("messageId") or normalized_message_id).strip(),
            "status": status,
            "tone": tone,
            "channel": item.get("channel"),
            "phase": item.get("phase"),
            "terminal": item.get("terminal"),
            "provisional": item.get("provisional"),
            "sourceItemId": str(item.get("itemId") or item.get("id") or "").strip() or None,
            "diagnosticSummary": item.get("diagnosticSummary"),
        }
        if kind in {"assistant_message", "agent_message", "commentary"} or phase in {
            "final_answer",
            "commentary",
            "interim",
        }:
            if not text:
                continue
            cells.append(
                s._compact_codex_record(
                    {
                        **cell_base,
                        "kind": "assistant_markdown",
                        "text": text,
                        "channel": item.get("channel")
                        or ("commentary" if phase in {"commentary", "interim"} or kind == "commentary" else "answer"),
                        "phase": item.get("phase")
                        or ("commentary" if kind == "commentary" else "final_answer"),
                    }
                )
            )
            continue
        if kind in {"reasoning", "analysis"} or phase == "reasoning":
            if not text:
                continue
            cells.append(
                s._compact_codex_record(
                    {
                        **cell_base,
                        "kind": "reasoning_summary",
                        "text": text,
                        "summary": text,
                    }
                )
            )
            continue
        if kind in {"tool_call", "tool", "command"} or phase == "tool_call":
            cells.append(
                s._compact_codex_record(
                    {
                        **cell_base,
                        "kind": "tool_call",
                        "title": str(item.get("toolName") or item.get("title") or "Tool").strip() or "Tool",
                        "text": text or None,
                        "summary": str(item.get("summary") or "").strip() or None,
                    }
                )
            )
            continue
        if kind in {"error", "turn_error"} or phase == "turn_failed":
            if not text:
                continue
            cells.append(
                s._compact_codex_record(
                    {
                        **cell_base,
                        "kind": "error_notice",
                        "tone": "error",
                        "text": text,
                        "terminal": True,
                    }
                )
            )
            continue
        if kind == "status" or phase == "status":
            if not text:
                continue
            cells.append(
                s._compact_codex_record(
                    {
                        **cell_base,
                        "kind": "status",
                        "text": text,
                    }
                )
            )
    cells = [cell for cell in cells if cell]
    if not cells:
        return None
    return s._compact_codex_record(
        {
            "version": 1,
            "source": "native",
            "messageId": normalized_message_id,
            "streaming": bool(streaming),
            "windowSlimmed": bool(window_slimmed),
            "cells": cells,
            "toolCalls": [],
            "terminalOperations": [],
            "terminalSessions": [],
            "modelObservations": [],
            "rolloutEvents": [],
        }
    )


def _build_window_final_answer_transcript(
    *,
    message_id: str,
    content: Any,
) -> dict[str, Any] | None:
    """Minimal native transcript for completed window payloads.

    Carries only the committed final answer cell so frontend ownership is explicit
    without shipping tool rollout diagnostics.
    """
    s = _service()
    normalized_message_id = str(message_id or "").strip()
    content_text = s._sanitize_message_content("assistant", content)
    if not normalized_message_id or not content_text:
        return None
    return s._compact_codex_record(
        {
            "version": 1,
            "source": "native",
            "messageId": normalized_message_id,
            "streaming": False,
            "windowSlimmed": True,
            "cells": [
                s._compact_codex_record(
                    {
                        "id": f"{normalized_message_id}-assistant-markdown",
                        "kind": "assistant_markdown",
                        "messageId": normalized_message_id,
                        "status": "completed",
                        "tone": "neutral",
                        "channel": "answer",
                        "phase": "final_answer",
                        "terminal": True,
                        "text": content_text,
                    }
                )
            ],
            "toolCalls": [],
            "terminalOperations": [],
            "terminalSessions": [],
            "modelObservations": [],
            "rolloutEvents": [],
        }
    )


def _slim_codex_transcript_for_window_payload(
    transcript: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Drop heavy native-transcript fields for windowed session detail.

    Chat switch loads use transcript_scope=window. Full cells/rolloutEvents can
    dominate the response (often >80% of JSON). Keep a compact surface so the
    UI can still render error/tool summaries without shipping full diagnostics.

    Never truncate non-commentary assistant_markdown: that text is the final
    answer owner and must match message.content for display ownership.
    """
    s = _service()
    if not isinstance(transcript, dict):
        return None
    if bool(transcript.get("streaming")):
        return transcript

    slim_cells: list[dict[str, Any]] = []
    raw_cells = transcript.get("cells")
    if isinstance(raw_cells, list):
        for cell in raw_cells[:48]:
            if not isinstance(cell, dict):
                continue
            text = cell.get("text")
            if not isinstance(text, str) or not text.strip():
                text = cell.get("markdown") if isinstance(cell.get("markdown"), str) else ""
            text = str(text or "").strip()
            cell_kind = str(cell.get("kind") or "").strip()
            cell_phase = str(cell.get("phase") or "").strip().lower()
            keep_full_answer_text = cell_kind == "assistant_markdown" and cell_phase != "commentary"
            if len(text) > 400 and not keep_full_answer_text:
                text = f"{text[:400]}…"
            slim_cell = s._compact_codex_record(
                {
                    "id": cell.get("id"),
                    "kind": cell.get("kind"),
                    "messageId": cell.get("messageId") or transcript.get("messageId"),
                    "title": cell.get("title"),
                    "status": cell.get("status"),
                    "tone": cell.get("tone"),
                    "phase": cell.get("phase"),
                    "channel": cell.get("channel"),
                    "terminal": cell.get("terminal"),
                    "text": text or None,
                    "failureCount": cell.get("failureCount"),
                }
            )
            if slim_cell:
                slim_cells.append(slim_cell)

    slim_tool_calls: list[dict[str, Any]] = []
    raw_tool_calls = transcript.get("toolCalls")
    if isinstance(raw_tool_calls, list):
        for tool_call in raw_tool_calls[:40]:
            if not isinstance(tool_call, dict):
                continue
            summary = str(tool_call.get("summary") or tool_call.get("detail") or "").strip()
            if len(summary) > 240:
                summary = f"{summary[:240]}…"
            slim_tool_calls.append(
                s._compact_codex_record(
                    {
                        "id": tool_call.get("id") or tool_call.get("callId"),
                        "callId": tool_call.get("callId") or tool_call.get("id"),
                        "name": tool_call.get("name"),
                        "status": tool_call.get("status"),
                        "summary": summary or None,
                    }
                )
            )

    slim = s._compact_codex_record(
        {
            "version": transcript.get("version") or 1,
            "source": transcript.get("source") or "native",
            "messageId": transcript.get("messageId") or "",
            "streaming": False,
            "windowSlimmed": True,
            "cells": slim_cells,
            "toolCalls": slim_tool_calls,
            "terminalOperations": [],
            "terminalSessions": [],
            "modelObservations": [],
            "rolloutEvents": [],
        }
    )
    if not slim_cells and not slim_tool_calls:
        return None
    return slim


def _build_codex_transcript_projection(
    *,
    message_id: str,
    role: str = "assistant",
    content: Any = "",
    feedback_events: Any = None,
    tool_calls: Any = None,
    streaming: bool = False,
) -> dict[str, Any] | None:
    s = _service()
    normalized_message_id = str(message_id or "").strip()
    if not normalized_message_id:
        return None
    normalized_role = str(role or "assistant").strip().lower()
    if normalized_role != "assistant":
        return None
    normalized_feedback_events = s._normalize_message_feedback_events(feedback_events or [])
    normalized_tool_calls = s._normalize_message_tool_calls(tool_calls or [])
    content_text = s._sanitize_message_content("assistant", content)
    operation_sources = s._codex_transcript_operation_sources(
        normalized_message_id,
        normalized_feedback_events,
        normalized_tool_calls,
    )
    cells: list[dict[str, Any]] = []
    lifecycle = s._empty_codex_tool_lifecycle_projection()
    rollout_events: list[dict[str, Any]] = []

    for ordinal, source in enumerate(operation_sources):
        cell, source_lifecycle, source_events = s._codex_transcript_cell_from_operation_source(
            normalized_message_id,
            source,
            ordinal,
        )
        if cell:
            cells.append(cell)
        s._extend_codex_tool_lifecycle_projection(lifecycle, source_lifecycle)
        rollout_events.extend(source_events)

    if content_text:
        cells.append(
            s._compact_codex_record(
                {
                    "id": f"{normalized_message_id}-assistant-markdown",
                    "kind": "assistant_markdown",
                    "messageId": normalized_message_id,
                    "status": "running" if streaming else "completed",
                    "tone": "running" if streaming else "neutral",
                    "text": content_text,
                }
            )
        )
    if streaming and not content_text and any(
        cell.get("status") in {"pending", "running"} for cell in cells
    ):
        cells.append(
            {
                "id": f"{normalized_message_id}-stream-tail",
                "kind": "stream_tail",
                "messageId": normalized_message_id,
                "status": "running",
                "tone": "running",
            }
        )

    if not cells and not rollout_events and not any(lifecycle.values()):
        return None
    return s._compact_codex_record(
        {
            "version": 1,
            "source": "native",
            "messageId": normalized_message_id,
            "streaming": bool(streaming),
            "cells": cells,
            "toolCalls": lifecycle["toolCalls"],
            "terminalOperations": lifecycle["terminalOperations"],
            "terminalSessions": lifecycle["terminalSessions"],
            "modelObservations": lifecycle["modelObservations"],
            "rolloutEvents": rollout_events,
        }
    )


def _build_terminal_error_codex_transcript_projection(
    *,
    message_id: str,
    error_item: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_message_id = str(message_id or error_item.get("messageId") or "").strip()
    item_id = str(error_item.get("itemId") or error_item.get("id") or "terminal-error").strip()
    diagnostic_summary = error_item.get("diagnosticSummary")
    return {
        "version": 1,
        "source": "native",
        "messageId": normalized_message_id,
        "streaming": False,
        "cells": [
            {
                "id": item_id,
                "kind": "error_notice",
                "messageId": normalized_message_id,
                "status": "failed",
                "tone": "error",
                "text": str(error_item.get("text") or "").strip(),
                "phase": "turn_failed",
                "terminal": True,
                "diagnosticSummary": dict(diagnostic_summary) if isinstance(diagnostic_summary, Mapping) else {},
                "sourceItemId": item_id,
            }
        ],
        "toolCalls": [],
        "terminalOperations": [],
        "terminalSessions": [],
        "modelObservations": [],
        "rolloutEvents": [],
    }


def _codex_tool_lifecycle_projection_from_source(
    source: dict[str, Any],
    operation_id: str,
    ordinal: int,
    status: str,
    title: str,
    summary: str,
) -> dict[str, list[dict[str, Any]]]:
    s = _service()
    lifecycle = s._empty_codex_tool_lifecycle_projection()
    if not operation_id:
        return lifecycle
    tool_call_id = f"tool_call:{operation_id}"
    runtime_kind = s._codex_runtime_kind(source)
    terminal_session_key = s._codex_terminal_session_key(source)
    terminal_request = s._codex_terminal_request(source, summary, title) if runtime_kind == "terminal" else {}
    if runtime_kind == "terminal" and not terminal_session_key and terminal_request.get("displayCommand"):
        # Direct cli_tool/exec_command events do not always carry a terminal session
        # identifier. A projection-local key preserves their real command/output
        # hierarchy without inventing one for legacy summaries or write_stdin.
        terminal_session_key = f"tool-call:{operation_id}"
    terminal_operation_id = f"terminal_operation:{ordinal}" if runtime_kind == "terminal" and terminal_session_key else ""
    tool_call = s._compact_codex_record(
        {
            "toolCallId": tool_call_id,
            "rawOperationId": operation_id,
            "status": status,
            "title": title or str(source.get("name") or "Tool call").strip() or "Tool call",
            "summary": summary,
            "rawToolName": str(source.get("name") or "").strip(),
            "runtimeKind": runtime_kind,
            "sequence": s._coerce_nonnegative_int(source.get("sequence") or source.get("_sequence")) or None,
            "timestamp": str(source.get("timestamp") or "").strip(),
            "terminalOperationId": terminal_operation_id,
            "tracePath": str(source.get("tracePath") or "").strip(),
            "error": s._trim_tool_detail_text(source.get("error") or "", max_chars=1200, max_lines=10),
            "resultPreview": s._trim_tool_detail_text(source.get("resultPreview") or "", max_chars=4000, max_lines=80),
            "resultType": str(source.get("resultType") or source.get("result_type") or "").strip(),
            "resultLength": s._coerce_tool_number(s._first_present_mapping_value(source, ("resultLength", "result_length"))),
            "resultKind": str(source.get("resultKind") or source.get("result_kind") or "").strip(),
            "truncated": bool(source.get("truncated")) if "truncated" in source else None,
            "originalLength": s._coerce_tool_number(s._first_present_mapping_value(source, ("originalLength", "original_length"))),
        }
    )
    lifecycle["toolCalls"].append(tool_call)
    if runtime_kind != "terminal" or not terminal_session_key:
        return lifecycle
    terminal_id = f"terminal:{terminal_session_key}"
    terminal_operation = s._compact_codex_record(
        {
            "operationId": terminal_operation_id,
            "toolCallId": tool_call_id,
            "terminalId": terminal_id,
            "kind": s._codex_terminal_operation_kind(source),
            "status": status,
            "request": terminal_request,
            "result": None if status in {"pending", "running"} else s._codex_terminal_result(source, summary, status),
            "durationSeconds": s._coerce_tool_number(
                s._first_present_mapping_value(source, ("durationSeconds", "duration_seconds"))
            ),
            "rawOperationId": operation_id,
            "tracePath": str(source.get("tracePath") or "").strip(),
        }
    )
    lifecycle["terminalOperations"].append(terminal_operation)
    lifecycle["terminalSessions"].append(
        {
            "terminalId": terminal_id,
            "createdByOperationId": terminal_operation_id,
            "operationIds": [terminal_operation_id],
            "status": status,
        }
    )
    lifecycle["modelObservations"].append(
        {
            "operationId": terminal_operation_id,
            "toolCallId": tool_call_id,
            "source": "DirectToolCall",
            "callItemIds": [tool_call_id],
            "outputItemIds": [] if status in {"pending", "running"} else [f"{tool_call_id}:output"],
        }
    )
    return lifecycle
