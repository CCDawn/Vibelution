"""Export completed financial research answers from native Session Turns.

The stored Turn stays unchanged. Export and catalog apply the conclusion
figure check, then a screening comparison when this Turn called the screen tool.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import zipfile
from io import BytesIO
from typing import Literal

from core.chat.turn_journal import (
    EVENT_TURN_COMPLETED,
    EVENT_TURN_FAILED,
    EVENT_TURN_INTERRUPTED,
    EVENT_USER_MESSAGE,
    session_turn_items_from_events,
)
from core.web.services import agent_directory_service as directory
from core.web.services import financial_assistant_service as assistant_service
from core.web.services import session_service
from core.web.services.financial_report.formats import render_docx, render_print_html
from core.web.services.financial_report.conclusion_figures import ground_completed_report
from core.web.services.financial_report.screen_comparison import (
    is_screening_report_prompt,
    project_screening_comparison,
)
from core.web.services.financial_report.pdf import (
    FinancialPdfTooLarge,
    FinancialPdfUnavailable,
    render_pdf,
)

ExportFormat = Literal["markdown", "json", "docx", "pdf", "pdf-file"]
MAX_REPORT_TEXT_CHARS = 250_000
MAX_EXPORT_CONTENT_CHARS = 2_000_000
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_STOCK_RESEARCH_PROMPT = re.compile(
    r"^\s*请研究\s*.+?，\s*分析日期\s*\d{4}-\d{2}-\d{2}", re.DOTALL
)
_TOPIC_RESEARCH_PROMPT = re.compile(
    r"^\s*请对以下主题开展投资研究\s*[：:]?.{0,12000}?分析截至\s*\d{4}-\d{2}-\d{2}",
    re.DOTALL,
)
_TEAM_SYNTHESIS_PROMPT = re.compile(
    r"^\s*你是主助手的股票研究汇总角色。请综合股票\s+[^；。\n]{1,50}的多分析师研究。"
    r"研究日期：(?:\d{4}-\d{2}-\d{2}|未指定)；观察周期：近\d+天",
    re.DOTALL,
)
_EXPLICIT_REPORT_PROMPT = re.compile(
    r"(?:重新生成|生成|撰写|更新|重写)(?:完整)?(?:一份)?(?:股票|投资|研究)?(?:研究报告|研报)"
    r"|(?:regenerate|create|write|update|rewrite)\s+(?:the\s+)?(?:full\s+)?(?:stock\s+|investment\s+)?research\s+report",
    re.IGNORECASE,
)


def list_report_validations(agent_id: str) -> dict:
    from .financial_report.validation import list_validations
    return list_validations(agent_id)


def create_report_validation(agent_id: str, payload: dict) -> dict:
    from .financial_report.validation import create_validation
    return create_validation(agent_id, payload)


def check_report_validation(agent_id: str, validation_id: str) -> dict:
    from .financial_report.validation import check_validation
    return check_validation(agent_id, validation_id)


def report_feedback_prompt(agent_id: str, validation_id: str) -> dict:
    from .financial_report.validation import feedback_prompt
    return feedback_prompt(agent_id, validation_id)


def save_report_lesson(agent_id: str, validation_id: str, text: str, request_id: str) -> dict:
    from .financial_report.validation import save_lesson
    return save_lesson(agent_id, validation_id, text, request_id)


def report_reflection_context(agent_id: str, symbol: str, analysis_cutoff: str) -> dict:
    from .financial_report.validation import reflection_context
    return {"items": reflection_context(agent_id, symbol, analysis_cutoff=analysis_cutoff)}


def backtest_research_strategy(agent_id: str, payload: dict) -> dict:
    from .financial_report.backtest import run_backtest
    return run_backtest(agent_id, payload)


class FinancialReportExportError(ValueError):
    """Base error for an invalid or unavailable report export."""


class FinancialReportNotFound(FinancialReportExportError):
    """The requested Agent, Session, or Turn is not owned by this assistant."""


class FinancialReportUnavailable(FinancialReportExportError):
    """The exact Turn is unfinished, failed, or is not a research report."""


class FinancialReportTooLarge(FinancialReportExportError):
    """The canonical content is larger than the bounded export contract."""


class FinancialReportInvalid(FinancialReportExportError):
    """The requested identifiers or format are invalid."""


def _normalized_identifier(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(normalized) or ".." in normalized:
        raise FinancialReportInvalid(f"{label} 无效")
    return normalized


def _research_request(text: str) -> bool:
    candidate = str(text or "").strip()
    return bool(
        candidate
        and len(candidate) <= 80_000
        and (
            _STOCK_RESEARCH_PROMPT.search(candidate)
            or _TOPIC_RESEARCH_PROMPT.search(candidate)
            or _TEAM_SYNTHESIS_PROMPT.search(candidate)
            or is_screening_report_prompt(candidate)
            or _EXPLICIT_REPORT_PROMPT.search(candidate)
        )
    )


def _report_file_suffix(request_text: str, turn_id: str) -> str:
    request = str(request_text or "")
    header = ""
    for pattern in (_STOCK_RESEARCH_PROMPT, _TEAM_SYNTHESIS_PROMPT):
        match = pattern.match(request)
        if match:
            header = request[: match.end()]
            break
    tickers = set(
        re.findall(
            r"(?<!\d)(?:sh|sz|bj)?([036489]\d{5})(?!\d)",
            header,
            flags=re.IGNORECASE,
        )
    )
    if len(tickers) == 1:
        return next(iter(tickers))
    international = re.findall(r"[（(]\s*([A-Z][A-Z0-9.-]{0,9}|\d{5})\s*[,，）)]", header)
    if len(international) == 1:
        return international[0]
    canonical = {next(value for value in match if value).upper() for match in re.findall(r"\bhk(\d{5})\b|\bus([A-Z][A-Z0-9.-]{0,9})\b", header, flags=re.IGNORECASE)}
    if len(canonical) == 1:
        return next(iter(canonical))
    return hashlib.sha256(str(turn_id or "").encode("utf-8")).hexdigest()[-8:]


def _owned_session(agent_id: str, session_id: str) -> bool:
    try:
        agent = directory.get_agent(agent_id)
        if not isinstance(agent, dict):
            return False
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if metadata.get("financialAssistantProfile") != assistant_service.PROFILE:
            return False
        session = session_service.load_session_chat_state(
            session_service.PROJECT_ROOT, session_id
        )
    except (directory.AgentDirectoryError, OSError, RuntimeError, TypeError, ValueError):
        return False
    if not isinstance(session, dict):
        return False
    owner = str(session.get("agentId") or session.get("agent_id") or "").strip()
    return owner == agent_id


def _completed_report(agent_id: str, session_id: str, turn_id: str) -> tuple[str, str, str]:
    if not _owned_session(agent_id, session_id):
        raise FinancialReportNotFound("未找到该炒股智能体拥有的研究会话")
    try:
        all_events = session_service.load_session_conversation_events_snapshot(
            session_id
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        raise FinancialReportNotFound("未找到研究会话") from None
    return _completed_report_from_events(all_events, session_id, turn_id, agent_id=agent_id)


def _completed_report_from_events(all_events: list, session_id: str, turn_id: str, *, agent_id: str = "") -> tuple[str, str, str]:
    """Read an already-authorized snapshot, sharing export validation with catalog."""
    turn_events = [
        event
        for event in all_events
        if str(getattr(event, "session_id", "") or "").strip() == session_id
        and str(getattr(event, "turn_id", "") or "").strip() == turn_id
    ]
    if not turn_events:
        raise FinancialReportNotFound("未找到该研究轮次")

    terminal_events = [
        event
        for event in turn_events
        if str(getattr(event, "event_type", "") or "")
        in {EVENT_TURN_COMPLETED, EVENT_TURN_FAILED, EVENT_TURN_INTERRUPTED}
    ]
    if len(terminal_events) != 1 or terminal_events[0].event_type != EVENT_TURN_COMPLETED:
        raise FinancialReportUnavailable("研究尚未成功完成，暂不能导出")
    terminal = terminal_events[0]
    if str(getattr(terminal, "status", "") or "").strip().lower() not in {
        "completed",
        "success",
        "succeeded",
        "done",
    }:
        raise FinancialReportUnavailable("研究尚未成功完成，暂不能导出")
    terminal_payload = terminal.payload if isinstance(terminal.payload, dict) else {}
    successful_statuses = {"completed", "success", "succeeded", "done"}
    for key in ("terminalReason", "terminal_reason", "finalStatus", "final_status", "resultStatus", "result_status"):
        value = str(terminal_payload.get(key) or "").strip().lower()
        if value and value not in successful_statuses:
            raise FinancialReportUnavailable("研究尚未成功完成，暂不能导出")
    if terminal_payload.get("marker") or terminal_payload.get("errorType") or terminal_payload.get("error_type"):
        raise FinancialReportUnavailable("研究尚未成功完成，暂不能导出")

    user_events = [
        event
        for event in turn_events
        if event.event_type == EVENT_USER_MESSAGE
        and bool(getattr(event, "visible_in_model", True))
    ]
    user_events.sort(key=lambda event: (int(getattr(event, "sequence", 0) or 0), str(getattr(event, "event_id", ""))))
    request_text = str((user_events[-1].payload or {}).get("content") or "") if user_events else ""
    if not request_text or not _research_request(request_text):
        raise FinancialReportUnavailable("该轮内容不是研究报告，暂不能导出")

    items = session_turn_items_from_events(turn_events, turn_id=turn_id)
    final_items: dict[str, dict] = {}
    for item in items:
        if (
            item.get("type") != "assistant_message"
            or item.get("channel") != "answer"
            or item.get("phase") != "final_answer"
            or item.get("status") != "completed"
        ):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        item_id = str(item.get("itemId") or item.get("id") or "")
        previous = final_items.get(item_id)
        revision_key = (int(item.get("revision") or 0), int(item.get("sequence") or 0))
        previous_key = (
            int(previous.get("revision") or 0), int(previous.get("sequence") or 0)
        ) if previous else (-1, -1)
        if revision_key >= previous_key:
            final_items[item_id] = item
    ordered = sorted(
        final_items.values(), key=lambda item: int(item.get("sequence") or 0)
    )
    report_text = "\n\n".join(str(item.get("text") or "").strip() for item in ordered).strip()
    if not report_text:
        raise FinancialReportUnavailable("该研究轮次没有已提交的最终答案")
    if re.search(
        r"(?:^|\n\n)(?:本轮已按请求停止[。，]|This turn was stopped (?:as requested|before it started)\.)",
        report_text,
        flags=re.IGNORECASE,
    ):
        raise FinancialReportUnavailable("已停止的研究不能导出")
    if agent_id and _TEAM_SYNTHESIS_PROMPT.search(request_text):
        from core.web.services.financial_report.conclusion_figures import ground_report_records
        from core.web.services.financial_report.team_evidence import original_tool_records, team_report_records

        records = team_report_records(agent_id, session_id, turn_id, request=request_text,
            report=report_text, completed_at=str(terminal.timestamp),
            own=original_tool_records(all_events, session_id=session_id, turn_id=turn_id))
        report_text = ground_report_records(report_text, records)
    else:
        report_text = ground_completed_report(report_text, items, turn_events)
    report_text = project_screening_comparison(report_text, request_text, items, turn_events)
    if len(report_text) > MAX_REPORT_TEXT_CHARS:
        raise FinancialReportTooLarge("研究报告超过导出大小限制")
    completed_at = str(getattr(terminal, "timestamp", "") or "").strip()
    return report_text, completed_at, _report_file_suffix(request_text, turn_id)


def list_financial_reports(assistant_agent_id: str, **filters) -> dict:
    from .financial_report.catalog import list_reports

    return list_reports(assistant_agent_id, **filters)


def export_financial_reports(assistant_agent_id: str, *, targets: list[dict], format: str) -> dict:
    """Bounded ZIP from exact native identities, with no archive/report storage."""
    if format not in {"markdown", "json", "docx"} or not isinstance(targets, list) or not 1 <= len(targets) <= 20:
        raise FinancialReportInvalid("批量导出最多20份，支持Markdown、JSON或Word")
    identities = [(str(item.get("sessionId") or ""), str(item.get("turnId") or "")) for item in targets if isinstance(item, dict)]
    if len(identities) != len(targets) or len(set(identities)) != len(identities):
        raise FinancialReportInvalid("批量导出身份无效或重复")
    output, total = BytesIO(), 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for index, (session_id, turn_id) in enumerate(identities, start=1):
            result = export_financial_report(assistant_agent_id, session_id=session_id, turn_id=turn_id, format=format)
            data = base64.b64decode(result["content"], validate=True) if result["encoding"] == "base64" else result["content"].encode("utf-8")
            total += len(data)
            if total > 8_000_000:
                raise FinancialReportTooLarge("批量导出超过8MB，请减少报告数量")
            # Distinct native Turns can share the same date/ticker filename.
            bundle.writestr(f"{index:02d}-{result['fileName']}", data)
    return {"fileName": "stock-research-bundle.zip", "mediaType": "application/zip", "encoding": "base64", "content": base64.b64encode(output.getvalue()).decode("ascii"), "count": len(identities)}


def _file_name(completed_at: str, suffix: str, extension: str) -> str:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", completed_at)
    date = match.group(1) if match else "report"
    safe_suffix = re.sub(r"[^A-Za-z0-9.-]", "", str(suffix or ""))[:10].strip(".-") or "report"
    return f"stock-research-{date}-{safe_suffix}.{extension}"


def _record_report_export_event(
    event_code: str,
    *,
    outcome: str,
    fields: dict[str, object],
    level: str = "info",
) -> None:
    """Best-effort export audit through the shared runtime-scene recorder."""
    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "finance",
            "report_export",
            event_code,
            outcome=outcome,
            level=level,
            fields=fields,
            refresh_package_if_due=False,
        )
    except Exception:  # noqa: BLE001 - logging must never block a valid export.
        # Export availability must not depend on runtime-scene logging.
        return


def _export_rejection_category(error: FinancialReportExportError) -> str:
    if isinstance(error, FinancialReportInvalid):
        return "invalid_request"
    if isinstance(error, FinancialReportNotFound):
        return "not_found"
    if isinstance(error, FinancialReportUnavailable):
        return "unavailable"
    if isinstance(error, FinancialReportTooLarge):
        return "too_large"
    return "export_rejected"


def export_financial_report(
    assistant_agent_id: str,
    *,
    session_id: str,
    turn_id: str,
    format: ExportFormat,
) -> dict[str, str]:
    """Return the canonical report in one of the bounded export formats."""
    safe_format = format if format in {"markdown", "json", "docx", "pdf", "pdf-file"} else "unknown"
    try:
        agent_id = _normalized_identifier(assistant_agent_id, "assistantAgentId")
        normalized_session_id = _normalized_identifier(session_id, "sessionId")
        normalized_turn_id = _normalized_identifier(turn_id, "turnId")
        if safe_format == "unknown":
            raise FinancialReportInvalid("导出格式无效")
        report, completed_at, file_suffix = _completed_report(
            agent_id, normalized_session_id, normalized_turn_id
        )
        if format == "markdown":
            file_name = _file_name(completed_at, file_suffix, "md")
            media_type = "text/markdown; charset=utf-8"
            encoding = "utf8"
            content = report
        elif format == "json":
            file_name = _file_name(completed_at, file_suffix, "json")
            media_type = "application/json; charset=utf-8"
            encoding = "utf8"
            content = json.dumps(
                {
                    "schemaVersion": 1,
                    "assistantAgentId": agent_id,
                    "sessionId": normalized_session_id,
                    "turnId": normalized_turn_id,
                    "completedAt": completed_at,
                    "content": report,
                },
                ensure_ascii=False,
                indent=2,
            )
        elif format == "docx":
            file_name = _file_name(completed_at, file_suffix, "docx")
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            encoding = "base64"
            content = base64.b64encode(
                render_docx(report, completed_at=completed_at)
            ).decode("ascii")
        elif format == "pdf-file":
            file_name = _file_name(completed_at, file_suffix, "pdf")
            media_type = "application/pdf"
            encoding = "base64"
            try:
                content = base64.b64encode(render_pdf(
                    report,
                    title=file_name.removesuffix(".pdf"),
                    completed_at=completed_at or "—",
                )).decode("ascii")
            except FinancialPdfTooLarge as exc:
                raise FinancialReportTooLarge(str(exc)) from None
            except FinancialPdfUnavailable as exc:
                raise FinancialReportUnavailable(str(exc)) from None
        else:
            file_name = _file_name(completed_at, file_suffix, "html")
            media_type = "text/html; charset=utf-8"
            encoding = "utf8"
            content = render_print_html(
                report,
                title=file_name.removesuffix(".html"),
                completed_at=completed_at or "—",
            )
        if len(content) > MAX_EXPORT_CONTENT_CHARS:
            raise FinancialReportTooLarge("导出文件超过传输大小限制")
    except FinancialReportExportError as exc:
        _record_report_export_event(
            "finance.report_export.rejected",
            outcome="rejected",
            level="warning",
            fields={
                "format": safe_format,
                "reasonCategory": _export_rejection_category(exc),
            },
        )
        raise
    except Exception:
        _record_report_export_event(
            "finance.report_export.failed",
            outcome="failed",
            level="error",
            fields={"format": safe_format, "reasonCategory": "internal_error"},
        )
        raise

    _record_report_export_event(
        "finance.report_export.succeeded",
        outcome="succeeded",
        fields={
            "assistantAgentId": agent_id,
            "sessionId": normalized_session_id,
            "turnId": normalized_turn_id,
            "format": format,
            "reportChars": min(len(report), MAX_REPORT_TEXT_CHARS),
        },
    )
    return {
        "sessionId": normalized_session_id,
        "turnId": normalized_turn_id,
        "format": format,
        "fileName": file_name,
        "mediaType": media_type,
        "encoding": encoding,
        "content": content,
    }
