"""Read original text from successful fetch receipts of the current stage task.

The Session Journal remains the authority. Candidate summaries and Agent
writeback metadata cannot manufacture a fetch receipt or its source text.
"""

from __future__ import annotations

from typing import Any


def task_fetched_text(task: dict[str, Any]) -> dict[str, dict[str, str]]:
    from core.web.services import team_workflow_orchestration_service as s

    turn = task.get("turn") or {}
    session_id = str(task.get("sessionId") or turn.get("sessionId") or "").strip()
    turn_id = str(turn.get("turnId") or "").strip()
    if not session_id or not turn_id:
        return {}
    events = s._source_collection_stage_conversation_events(session_id)
    texts: dict[str, dict[str, str]] = {}
    for event in events:
        if str(getattr(event, "event_type", "")) != "tool_result":
            continue
        if str(getattr(event, "turn_id", "")) != turn_id:
            continue
        for call in s._source_collection_stage_tool_calls_from_event(event):
            if s._source_collection_stage_tool_call_name(call) != "web_fetch_tool":
                continue
            if not s._source_collection_stage_tool_call_succeeded(call):
                continue
            args = s._source_collection_stage_tool_call_args(call)
            locator = str(args.get("url") or "").strip()
            result = call.get("result")
            if not locator or not isinstance(result, str) or not result.startswith("[网页内容] "):
                continue
            header, separator, body = result.partition("\n\n")
            if not separator or not body.strip():
                continue
            # Keep fetched text only, excluding the tool's truncation notice.
            body = body.rsplit("\n\n... [截断，原内容 ", 1)[0].strip()
            texts[locator] = {
                "text": body,
                "locator": locator,
                "resolvedUrl": header.splitlines()[0].removeprefix("[网页内容] "),
                "eventId": str(getattr(event, "event_id", "")),
                "sessionId": session_id,
                "turnId": str(getattr(event, "turn_id", "")),
            }
    return texts
