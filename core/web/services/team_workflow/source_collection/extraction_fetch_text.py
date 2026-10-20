"""Read original text from successful fetch receipts of the stage task session.

The Session Journal remains the authority. Candidate summaries and Agent
writeback metadata cannot manufacture a fetch receipt or its source text.
Every turn of the task's session is in supply scope: the agent may fetch in
an earlier turn or in a continuation turn (after a remediation parking), and
those receipts must not vanish at the turn boundary.  The session boundary —
not the turn boundary — decides what this task can quote.  A cross-host
redirect parking message additionally registers its original URL as an alias
of an already-fetched redirect target, so a candidate locator parked at the
redirect still quotes the text actually fetched at the landing page.
"""

from __future__ import annotations

from typing import Any

# web_fetch_tool 成功回执的两种前缀（tools/web_search_tool.web_fetch）：
# HTML 走 [网页内容]，PDF 走 [PDF 文本]。PDF 回执同样携带真实抓取原文，
# 必须进入 quotable 供给——只认 HTML 前缀会让纯 PDF 来源（如 arXiv /pdf/）
# 即使抓取成功也必然 no_quotable_text。
_RECEIPT_PREFIXES = ("[网页内容] ", "[PDF 文本] ")

# 跨主机重定向停靠消息（tools/web_search_tool.web_fetch 按安全策略停止跟随）。
# 它不是内容回执，禁止进入 _RECEIPT_PREFIXES——只作为 (原 URL → 重定向目标)
# 别名对的解析来源。
_REDIRECT_PARKING_PREFIX = "[网页抓取] "
_REDIRECT_ORIGINAL_LABEL = "原 URL"
_REDIRECT_TARGET_LABEL = "重定向目标"


def _labeled_url(line: str, label: str) -> str:
    """One labeled URL value from a parking-message line, or ``""``.

    Tolerates stray whitespace around the label and both ASCII/full-width
    colons; a label line without a usable value parses as empty.
    """
    stripped = line.strip()
    if not stripped.startswith(label):
        return ""
    value = stripped[len(label):].strip()
    if value.startswith((':', '：')):
        return value[1:].strip()
    return ""


def _redirect_alias_pair(result: str) -> tuple[str, str]:
    """Parse a redirect parking message into ``(original, target)``.

    Only ``[网页抓取] ``-prefixed tool results count.  Line order and extra
    whitespace are tolerated; when either URL line is missing or
    unparseable the pair comes back empty and the receipt is skipped —
    parsing never raises.
    """
    if not result.startswith(_REDIRECT_PARKING_PREFIX):
        return "", ""
    original = ""
    target = ""
    for line in result.splitlines():
        original = original or _labeled_url(line, _REDIRECT_ORIGINAL_LABEL)
        target = target or _labeled_url(line, _REDIRECT_TARGET_LABEL)
        if original and target:
            break
    return original, target


def task_fetched_text(task: dict[str, Any]) -> dict[str, dict[str, str]]:
    from core.web.services import team_workflow_orchestration_service as s

    turn = task.get("turn") or {}
    session_id = str(task.get("sessionId") or turn.get("sessionId") or "").strip()
    if not session_id:
        return {}
    events = s._source_collection_stage_conversation_events(session_id)
    texts: dict[str, dict[str, str]] = {}
    for event in events:
        if str(getattr(event, "event_type", "")) != "tool_result":
            continue
        # 本 stage task 会话内的全部 turn 都在供给范围内：修正停靠后 agent
        # 在新 turn 继续、或复看早前 turn 的抓取时，回执不因 turn 边界丢失；
        # 同一 locator 的重复抓取按 Journal 顺序后者覆盖前者。
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
    # 第二遍扫描：跨主机重定向停靠消息携带 (原 URL → 重定向目标)。代理按提示
    # 抓到落地页后，原定位键（如 DOI 链接）也要能命中那份真实抓取的原文，
    # 否则候选的 DOI 定位键永远 quoteAvailable=false（结构性死锁）。别名条目
    # 是 target 条目的浅拷贝：出处字段沿用 target 的真实抓取（诚实出处），
    # 只有 locator 换成原 URL 并加 aliasOf 标注；直接抓取优先，别名只填空，
    # target 未成功抓取时不做别名、也不多跳。
    for event in events:
        if str(getattr(event, "event_type", "")) != "tool_result":
            continue
        for call in s._source_collection_stage_tool_calls_from_event(event):
            if s._source_collection_stage_tool_call_name(call) != "web_fetch_tool":
                continue
            if not s._source_collection_stage_tool_call_succeeded(call):
                continue
            result = call.get("result")
            if not isinstance(result, str):
                continue
            original, target = _redirect_alias_pair(result)
            if not original or not target:
                continue
            if texts.get(original):
                continue
            fetched = texts.get(target)
            if not fetched or not str(fetched.get("text") or "").strip():
                continue
            alias = dict(fetched)
            alias["locator"] = original
            alias["aliasOf"] = target
            texts[original] = alias
    return texts
