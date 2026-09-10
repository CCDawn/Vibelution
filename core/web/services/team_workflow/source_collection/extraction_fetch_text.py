"""Read original text from successful fetch receipts of the current stage task.

The Session Journal remains the authority. Candidate summaries and Agent
writeback metadata cannot manufacture a fetch receipt or its source text.
"""

from __future__ import annotations

from typing import Any

# web_fetch_tool 成功回执的两种前缀（tools/web_search_tool.web_fetch）：
# HTML 走 [网页内容]，PDF 走 [PDF 文本]。PDF 回执同样携带真实抓取原文，
# 必须进入 quotable 供给——只认 HTML 前缀会让纯 PDF 来源（如 arXiv /pdf/）
# 即使抓取成功也必然 no_quotable_text。
_RECEIPT_PREFIXES = ("[网页内容] ", "[PDF 文本] ")


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
            if not locator or not isinstance(result, str):
                continue
            receipt_prefix = next(
                (prefix for prefix in _RECEIPT_PREFIXES if result.startswith(prefix)),
                None,
            )
            if not receipt_prefix:
                continue
            header, separator, body = result.partition("\n\n")
            if not separator or not body.strip():
                continue
            # Keep fetched text only, excluding the tool's truncation notice.
            body = body.rsplit("\n\n... [截断，原内容 ", 1)[0].strip()
            texts[locator] = {
                "text": body,
                "locator": locator,
                "resolvedUrl": header.splitlines()[0].removeprefix(receipt_prefix),
                "eventId": str(getattr(event, "event_id", "")),
                "sessionId": session_id,
                "turnId": str(getattr(event, "turn_id", "")),
            }
    return texts
