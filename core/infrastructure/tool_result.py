#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具结果处理工具

从 agent.py 中提取的工具结果处理函数：
- truncate_result: 截断超长工具结果
- format_tool_message: 格式化工具消息

使用方式：
    from core.infrastructure.tool_result import truncate_result, format_tool_message
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, Any, Optional, List

from core.logging import debug as _debug_logger


# 默认截断阈值
DEFAULT_MAX_CHARS = 4000

BUSINESS_FAILURE_STATUSES = {
    "blocked",
    "fail",
    "failed",
    "failure",
    "error",
    "errored",
    "cancelled",
    "policy_blocked",
    "timeout",
    "no_result",
    "submitted",
    "in_progress",
    "timed_out",
}

# 这些字段描述的是某个工作流下一步应如何编排，而不是工具已经观察到的事实。
# 它们可以留在原始结果或运行时遥测中，但绝不能作为 ToolMessage 回灌给对话模型。
MODEL_HIDDEN_RESULT_KEYS = frozenset(
    {
        "continuationhint",
        "recordcontinuationhint",
        "retryinstruction",
        "evidenceinstruction",
        "nextaction",
        "recommendednext",
        "recommendednextaction",
        "recommendedtools",
        "avoidtools",
        "suggestedaction",
        "nextstep",
        "instructions",
        "guidance",
    }
)

MODEL_HIDDEN_TEXT_PREFIXES = (
    "[阅读导航]",
    "[续读]",
    "[截断信息] 阅读导航=",
    "continuationhint:",
    "recordcontinuationhint:",
    "retryinstruction:",
    "evidenceinstruction:",
    "nextaction:",
    "recommendednext:",
    "recommendednextaction:",
)


def _normalize_text_payload(text: str) -> str:
    """去除常见包装噪音：前后空白与 UTF-8 BOM。"""
    return text.lstrip("\ufeff").strip()


@dataclass
class ToolResultEnvelope:
    """工具结果的统一封装。"""

    content: str
    truncated: bool
    original_length: int
    result_kind: str = "text"
    strategy: str = "passthrough"
    range_info: str = ""
    continuation_hint: str = ""
    transport_status: str = "returned"
    semantic_status: str = "succeeded"
    exit_code: int | None = None
    timed_out: bool = False
    failure_class: str = ""


@dataclass
class ModelVisibleToolResult:
    """模型可见的工具结果事实，不承载二次摘要。"""

    tool_name: str
    content: str
    truncated: bool
    original_length: int
    result_kind: str = "text"
    strategy: str = "passthrough"
    range_info: str = ""
    continuation_hint: str = ""
    transport_status: str = "returned"
    semantic_status: str = "succeeded"
    exit_code: int | None = None
    timed_out: bool = False
    failure_class: str = ""
    action: str = ""


# 保留旧导入名，避免外部调用方在投影切换期失效。
ToolResultFacts = ModelVisibleToolResult


@dataclass(frozen=True)
class RuntimeToolMetadata:
    """只供运行时/UI/审计使用的工具元数据，不得回灌到 ToolMessage。"""

    result_kind: str
    strategy: str
    range_info: str
    continuation_hint: str
    truncated: bool
    original_length: int
    transport_status: str
    semantic_status: str
    exit_code: int | None
    timed_out: bool
    failure_class: str


def extract_tool_result_semantics(result: Any) -> dict[str, Any]:
    """Extract transport/business semantics from common tool result shapes."""
    semantics: dict[str, Any] = {
        "transportStatus": "returned",
        "semanticStatus": "succeeded",
        "exitCode": None,
        "timedOut": False,
        "failureClass": "",
    }

    payload: dict[str, Any] = result if isinstance(result, dict) else {}
    if isinstance(result, (bytes, bytearray)):
        try:
            result = result.decode("utf-8", errors="replace")
        except Exception as exc:
            _debug_logger.warning(
                f"[工具结果] bytes 结果转文本失败: {type(result).__name__}: {exc}",
                tag="TOOL_RESULT",
            )
            result = str(result)

    text = _normalize_text_payload(str(result or ""))
    lowered = text.lower()
    if not payload and text.startswith("{"):
        try:
            parsed_payload = json.loads(text)
            if isinstance(parsed_payload, dict):
                payload = parsed_payload
        except Exception:
            pass
    if payload:
        status = _normalize_text_payload(str(payload.get("status") or "")).lower()
        if status:
            semantics["semanticStatus"] = status
        failure_class = _normalize_text_payload(
            str(payload.get("failureClass") or payload.get("failure_class") or "")
        )
        if failure_class:
            semantics["failureClass"] = failure_class
        for key in ("exitCode", "exit_code", "returncode", "return_code"):
            if key in payload:
                try:
                    semantics["exitCode"] = int(payload.get(key))
                except (TypeError, ValueError) as exc:
                    _debug_logger.warning(
                        f"[工具结果] exitCode 解析失败(key={key}, value={payload.get(key)!r}): {type(exc).__name__}: {exc}",
                        tag="TOOL_RESULT",
                    )
                    pass
                break
        if semantics["exitCode"] not in (None, 0):
            semantics["semanticStatus"] = "failed"
            semantics["failureClass"] = semantics["failureClass"] or "process_exit"
        if bool(payload.get("timedOut") or payload.get("timed_out")) or status in {"timeout", "timed_out"}:
            semantics["timedOut"] = True
            semantics["failureClass"] = semantics["failureClass"] or "timeout"
        if _looks_like_business_failure(payload):
            if semantics["semanticStatus"] == "succeeded":
                semantics["semanticStatus"] = "failed"
            semantics["failureClass"] = semantics["failureClass"] or status or "business_failure"

    nonzero_exit_match = re.search(
        r"\[(?:EXEC FAILURE|WARNING)\s*\|\s*Exit Code:\s*(-?\d+)\]",
        text,
        flags=re.IGNORECASE,
    )
    if nonzero_exit_match:
        semantics["semanticStatus"] = "failed"
        semantics["failureClass"] = "process_exit"
        try:
            semantics["exitCode"] = int(nonzero_exit_match.group(1))
        except (TypeError, ValueError) as exc:
            _debug_logger.warning(
                f"[工具结果] exitCode 解析失败({nonzero_exit_match.group(0)}): {type(exc).__name__}: {exc}",
                tag="TOOL_RESULT",
            )
            pass
    elif text.startswith(("[执行失败", "[EXEC FAILURE")):
        semantics["semanticStatus"] = "failed"
        semantics["failureClass"] = "process_exit"

    if text.startswith(("[超时]", "[TIMEOUT]")) or "timed out" in lowered:
        semantics["semanticStatus"] = "timeout"
        semantics["timedOut"] = True
        semantics["failureClass"] = "timeout"
    elif text.startswith("[工具参数错误]"):
        semantics["semanticStatus"] = "failed"
        semantics["failureClass"] = semantics["failureClass"] or "tool_argument_error"
    elif text.startswith("[跨平台警告]"):
        semantics["semanticStatus"] = "degraded"
        semantics["failureClass"] = semantics["failureClass"] or "cross_platform_command"
    elif text.startswith("[安全拦截]"):
        semantics["semanticStatus"] = "blocked"
        semantics["failureClass"] = semantics["failureClass"] or "security_block"
    elif text.startswith("[运行测试] 未找到对应测试文件"):
        semantics["semanticStatus"] = "failed"
        semantics["failureClass"] = semantics["failureClass"] or "missing_mapped_test"
    elif text.startswith(("[错误]", "[短路]")):
        semantics["semanticStatus"] = "failed"
        semantics["failureClass"] = semantics["failureClass"] or "tool_error"
    elif text.startswith("[搜索质量不足]"):
        semantics["semanticStatus"] = "degraded"
        semantics["failureClass"] = semantics["failureClass"] or "low_quality_search_results"

    if semantics["semanticStatus"] in BUSINESS_FAILURE_STATUSES and not semantics["failureClass"]:
        semantics["failureClass"] = str(semantics["semanticStatus"])
    if semantics["semanticStatus"] in {"ok", "success", "succeeded"}:
        semantics["semanticStatus"] = "succeeded"
    elif semantics["semanticStatus"] in {"fail", "failure", "error", "errored"}:
        semantics["semanticStatus"] = "failed"
    elif semantics["semanticStatus"] == "timed_out":
        semantics["semanticStatus"] = "timeout"
        semantics["timedOut"] = True
        semantics["failureClass"] = "timeout"
    return semantics


def _looks_like_business_failure(payload: Any) -> bool:
    """判断结构化工具返回值是否表达了业务失败。"""
    if not isinstance(payload, dict):
        return False

    ok_value = payload.get("ok")
    if ok_value is False:
        return True
    success_value = payload.get("success")
    if success_value is False:
        return True

    for key in ("exitCode", "exit_code", "returncode", "return_code"):
        if key not in payload:
            continue
        try:
            if int(payload.get(key)) != 0:
                return True
        except (TypeError, ValueError):
            return True
        break

    status_value = payload.get("status")
    if isinstance(status_value, str):
        normalized_status = _normalize_text_payload(status_value)
        if normalized_status.lower() in BUSINESS_FAILURE_STATUSES:
            return True

    error_value = payload.get("error")
    if error_value and ok_value is not True and success_value is not True:
        return True

    return False


def infer_tool_business_success(result: Any) -> bool:
    """从工具返回值推断业务层是否成功。

    工具调用本身可能完成，但返回 JSON 中的 ``ok=false`` / ``status=failed``
    表示业务动作失败。日志层必须区分这两种状态，避免出现
    ``RESULT xxx OK`` 掩盖业务失败的误导性记录。
    """
    if result is None:
        return False
    if isinstance(result, (bytes, bytearray)):
        try:
            decoded = result.decode("utf-8", errors="replace")
        except Exception as exc:
            _debug_logger.warning(
                f"[工具结果] 业务成功性检查 decode 失败: {type(result).__name__}: {exc}",
                tag="TOOL_RESULT",
            )
            return False
        return infer_tool_business_success(decoded)
    if isinstance(result, dict):
        return not _looks_like_business_failure(result)
    if isinstance(result, str):
        stripped = _normalize_text_payload(result)
        if stripped.lower() in BUSINESS_FAILURE_STATUSES:
            return False
        if stripped.startswith((
            "[错误]",
            "[超时]",
            "[短路]",
            "[工具参数错误]",
            "[EXEC FAILURE",
            "[WARNING | Exit Code",
            "[执行失败",
            "[跨平台警告]",
            "[安全拦截]",
            "[运行测试] 未找到对应测试文件",
        )):
            return False
        if stripped.startswith("{"):
            try:
                return not _looks_like_business_failure(json.loads(stripped))
            except Exception as exc:
                _debug_logger.warning(
                    f"[工具结果] 工具结果 JSON 解析失败: {type(exc).__name__}: {exc}",
                    tag="TOOL_RESULT",
                )
                return True
    return True


def _infer_result_kind(tool_name: str = "", result_str: str = "") -> str:
    name = (tool_name or "").lower()
    text = _normalize_text_payload(result_str or "")
    if name == "source_collection_context_tool":
        return "source_collection_context"
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("contextKind") == "source_collection_stage_task_context":
                return "source_collection_context"
        except Exception:
            pass
    if name == "read_file_tool" or text.startswith("[文件]"):
        return "file_read"
    if name == "code_symbol_tool" or text.startswith("[AST]"):
        return "code_context_graph"
    if name == "grep_search_tool" or text.startswith("[搜索]"):
        return "search"
    if text.startswith("{") or text.startswith("["):
        return "structured_text"
    return "text"


def _extract_range_info(result_kind: str, result_str: str) -> str:
    if result_kind != "file_read":
        return ""
    for line in result_str.splitlines():
        if line.startswith("[区间] "):
            return line[len("[区间] ") :].strip()
    return ""


def _extract_continuation_hint(result_kind: str, result_str: str) -> str:
    if result_kind == "file_read":
        for line in result_str.splitlines():
            if line.startswith("[阅读导航] "):
                return line[len("[阅读导航] ") :].strip()
            if line.startswith("[续读] "):
                return line[len("[续读] ") :].strip()
    if result_kind == "code_context_graph":
        return "优先继续使用 code_symbol_tool 的 explore/inspect/references/impact/affected_tests 模式做结构化补读。"
    if result_kind == "search":
        return "优先缩小搜索范围，或按命中文件继续读取局部上下文。"
    if result_kind == "source_collection_context":
        payload = _try_parse_json_object(result_str)
        if payload:
            context_mode = str(payload.get("contextMode") or "compact").strip().lower() or "compact"
            record_page = payload.get("recordPage") if isinstance(payload.get("recordPage"), dict) else {}
            if record_page.get("hasMore"):
                next_offset = record_page.get("nextOffset")
                limit = record_page.get("limit") or 5
                return (
                    "继续调用 source_collection_context_tool，"
                    f"record_offset={next_offset}, record_limit={limit}, context_mode={context_mode}。"
                )
            page = payload.get("candidatePage") if isinstance(payload.get("candidatePage"), dict) else {}
            if page.get("hasMore"):
                next_offset = page.get("nextOffset")
                limit = page.get("limit") or 5
                return (
                    "继续调用 source_collection_context_tool，"
                    f"candidate_offset={next_offset}, candidate_limit={limit}, context_mode={context_mode}。"
                )
    return ""


def _split_header_and_body(result_str: str) -> tuple[list[str], str]:
    marker = "--- Content ---"
    if marker not in result_str:
        return result_str.splitlines(), ""
    head, body = result_str.split(marker, 1)
    header_lines = [line for line in head.splitlines() if line.strip()]
    return header_lines, body.strip("\n")


def _compact_file_read(result_str: str, max_chars: int, continuation_hint: str) -> Optional[str]:
    header_lines, body = _split_header_and_body(result_str)
    if not header_lines:
        return None

    content_lines = [line for line in body.splitlines() if line.strip()]
    head_excerpt = content_lines[:12]
    tail_excerpt = content_lines[-6:] if len(content_lines) > 18 else []

    compact_lines = list(header_lines)
    compact_lines.extend(["", "--- Content Preview ---"])
    compact_lines.extend(head_excerpt)
    if tail_excerpt:
        compact_lines.append("... [中间内容省略，请按目标选择命中行/实体/相邻窗口补局部上下文] ...")
        compact_lines.extend(tail_excerpt)
    compact_lines.append("--- End Preview ---")
    compact_lines.append(f"[...结果已截断，原长度 {len(result_str)} 字符...]")
    if continuation_hint:
        compact_lines.append(f"[截断信息] 阅读导航={continuation_hint}")

    compact = "\n".join(compact_lines)
    if len(compact) <= max_chars + 180:
        return compact
    return None


def _compact_search_result(result_str: str, max_chars: int, continuation_hint: str) -> Optional[str]:
    lines = result_str.splitlines()
    if not lines:
        return None

    summary_lines: list[str] = []
    preview_lines: list[str] = []
    in_preview = False
    file_preview_count = 0

    for line in lines:
        stripped = line.strip()
        if stripped == "[搜索预览]":
            in_preview = True
            summary_lines.append(line)
            continue
        if not in_preview:
            summary_lines.append(line)
            continue
        if line.startswith("📁 "):
            file_preview_count += 1
            if file_preview_count > 2:
                continue
        if file_preview_count <= 2:
            preview_lines.append(line)

    compact_lines = summary_lines + preview_lines
    compact_lines.append(f"[...结果已截断，原长度 {len(result_str)} 字符...]")
    if continuation_hint:
        compact_lines.append(f"[截断信息] 阅读导航={continuation_hint}")
    compact = "\n".join(line for line in compact_lines if line is not None)
    if len(compact) <= max_chars + 200:
        return compact
    return None


def _try_parse_json_object(result_str: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(_normalize_text_payload(result_str))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _normalize_result_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key or "").lower())


def _project_structured_result_for_model(value: Any) -> Any:
    """删除结构化结果里指挥下一步工具调用的工作流字段。"""
    if isinstance(value, dict):
        return {
            str(key): _project_structured_result_for_model(item)
            for key, item in value.items()
            if _normalize_result_key(key) not in MODEL_HIDDEN_RESULT_KEYS
        }
    if isinstance(value, list):
        return [_project_structured_result_for_model(item) for item in value]
    return value


def project_tool_result_for_model(content: str) -> str:
    """将工具原始结果投影为只含观察事实的模型可见内容。

    运行时可保留 continuation/retry 等元数据用于 UI、审计或 Team 工作流；
    对话 Agent 的 ToolMessage 只收到本次调用已经发生的结果。
    """
    normalized = str(content or "")
    parsed = _try_parse_json_object(normalized)
    if parsed is not None:
        return json.dumps(
            _project_structured_result_for_model(parsed),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    visible_lines = []
    for line in normalized.splitlines():
        if line.lstrip().lower().startswith(MODEL_HIDDEN_TEXT_PREFIXES):
            continue
        visible_lines.append(line)
    return "\n".join(visible_lines)


def _compact_source_collection_context_result(result_str: str, max_chars: int, continuation_hint: str) -> Optional[str]:
    payload = _try_parse_json_object(result_str)
    if not payload:
        return None
    raw_context_mode = str(payload.get("contextMode") or "compact").strip().lower() or "compact"
    if raw_context_mode not in {"compact", "minimal", "evidence", "retry_missing", "retry_evidence", "full"}:
        raw_context_mode = "compact"
    steward_packet = payload.get("stewardActionPacket") if isinstance(payload.get("stewardActionPacket"), dict) else {}
    steward_mode = str(steward_packet.get("packetKind") or "") == "knowledge_steward_approved_candidate_action"
    evidence_mode = raw_context_mode in {"evidence", "retry_missing", "retry_evidence"} or steward_mode
    record_page = payload.get("recordPage") if isinstance(payload.get("recordPage"), dict) else {}
    page = payload.get("candidatePage") if isinstance(payload.get("candidatePage"), dict) else {}
    records = [
        item
        for item in list(payload.get("records") or [])
        if isinstance(item, dict)
    ]
    compact_records = []
    for item in records[:12]:
        compact_record = {
            "recordId": str(item.get("recordId") or item.get("id") or "")[:160],
            "title": str(item.get("title") or "")[:120 if evidence_mode else 80],
            "sourceType": str(item.get("sourceType") or "")[:80],
            "locator": str(item.get("doi") or item.get("sourceUrl") or item.get("sourceRef") or "")[:120],
        }
        if evidence_mode:
            compact_record["summary"] = str(item.get("summary") or "")[:420]
            evidence_refs = [ref for ref in list(item.get("evidenceRefs") or []) if isinstance(ref, dict)][:3]
            if evidence_refs:
                compact_record["evidenceRefs"] = evidence_refs
            if item.get("evidenceScope"):
                compact_record["evidenceScope"] = str(item.get("evidenceScope"))[:80]
        else:
            compact_record["summaryPreview"] = str(item.get("summary") or "")[:48]
        compact_records.append(compact_record)
    candidates = [
        item
        for item in list(payload.get("candidates") or [])
        if isinstance(item, dict)
    ]
    compact_candidates = []
    for item in candidates[:12]:
        doi = str(item.get("doi") or "")[:120]
        source_url = str(item.get("sourceUrl") or "")[:120]
        source_path = str(item.get("sourcePath") or "")[:120]
        compact_candidate = {
            "candidateId": str(item.get("candidateId") or item.get("id") or "")[:160],
            "title": str(item.get("title") or "")[:120 if evidence_mode else 80],
            "sourceKind": str(item.get("sourceKind") or "")[:80],
            "locator": doi or source_url or source_path or str(item.get("locator") or "")[:120],
            "qualityBucket": str(item.get("qualityBucket") or "")[:80],
        }
        if evidence_mode:
            compact_candidate["summary"] = str(item.get("summary") or "")[:420]
            evidence_refs = [ref for ref in list(item.get("evidenceRefs") or []) if isinstance(ref, dict)][:3]
            source_record_id = str(item.get("sourceRecordId") or "")[:160]
            if not evidence_refs and source_record_id:
                evidence_refs = [
                    {
                        "type": "data_record",
                        "id": source_record_id,
                        "label": str(item.get("title") or source_record_id)[:120],
                    }
                ]
            if evidence_refs:
                compact_candidate["evidenceRefs"] = evidence_refs
            if item.get("evidenceScope"):
                compact_candidate["evidenceScope"] = str(item.get("evidenceScope"))[:80]
        else:
            compact_candidate["summaryPreview"] = str(item.get("summary") or item.get("summaryPreview") or "")[:48]
        compact_candidates.append(compact_candidate)
    if evidence_mode and compact_candidates:
        compact_records = []
    compact_usage = {
        "readTool": "source_collection_context_tool",
        "writebackTool": "source_collection_stage_writeback_tool",
        "continuationHint": "",
    }
    if record_page.get("hasMore"):
        compact_usage["recordContinuationHint"] = (
            "source_collection_context_tool("
            f"record_offset={record_page.get('nextOffset')},record_limit={record_page.get('limit') or 5},context_mode={raw_context_mode})"
        )
    if page.get("hasMore"):
        compact_usage["continuationHint"] = (
            "source_collection_context_tool("
            f"candidate_offset={page.get('nextOffset')},candidate_limit={page.get('limit') or 5},context_mode={raw_context_mode})"
        )
    elif continuation_hint:
        compact_usage["continuationHint"] = continuation_hint[:180]
    raw_usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    for key in ("retryInstruction", "evidenceInstruction"):
        if raw_usage.get(key):
            compact_usage[key] = str(raw_usage.get(key))[:1000]
    compact = {
        "status": payload.get("status"),
        "contextKind": payload.get("contextKind"),
        "contextMode": f"{raw_context_mode}_from_tool_result",
        "fieldMode": "evidence_source" if evidence_mode else "preview_only",
        "candidateFieldsTruncated": True,
        "doNotUsePreviewAsEvidence": not evidence_mode,
        "visibleCandidateCount": len(compact_candidates),
        "omittedReturnedCandidateCount": max(0, int(page.get("returned") or len(compact_candidates)) - len(compact_candidates)),
        "counts": payload.get("counts") if isinstance(payload.get("counts"), dict) else {},
        "excludedSourceSummary": _compact_source_collection_tool_excluded_summary(
            payload.get("excludedSourceSummary") if isinstance(payload.get("excludedSourceSummary"), dict) else {}
        ),
        "candidatePage": page,
        "candidateIds": [item.get("candidateId") for item in compact_candidates if item.get("candidateId")],
        "candidates": compact_candidates,
        "usage": compact_usage,
        "truncationGuard": {
            "originalLength": len(result_str),
            "message": "structured_compact; governed_evidence_summary" if evidence_mode else "structured_compact; previews_not_evidence",
        },
    }
    if compact_records or record_page.get("hasMore") or record_page.get("total"):
        compact["visibleRecordCount"] = len(compact_records)
        compact["omittedReturnedRecordCount"] = max(0, int(record_page.get("returned") or len(compact_records)) - len(compact_records))
        compact["recordPage"] = record_page
    unassessed_candidate_ids = payload.get("unassessedCandidateIds") if isinstance(payload.get("unassessedCandidateIds"), list) else []
    if unassessed_candidate_ids:
        compact["unassessedCandidateIds"] = unassessed_candidate_ids[:40]
    if steward_mode:
        compact["stewardActionPacket"] = _compact_source_collection_steward_action_packet(steward_packet)
    if compact_records:
        compact["recordIds"] = [item.get("recordId") for item in compact_records if item.get("recordId")]
        compact["records"] = compact_records
    content = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(content) <= max_chars + 500:
        return content
    if evidence_mode:
        compact["candidates"] = [
            {
                key: value
                for key, value in {
                    "candidateId": str(item.get("candidateId") or "")[:160],
                    "title": str(item.get("title") or "")[:80],
                    "locator": str(item.get("locator") or "")[:120],
                    "summary": str(item.get("summary") or "")[:220],
                    "evidenceRefs": list(item.get("evidenceRefs") or [])[:1],
                    "evidenceScope": item.get("evidenceScope"),
                }.items()
                if value not in ("", [], None)
            }
            for item in compact_candidates[:12]
        ]
        compact["candidateIds"] = [item.get("candidateId") for item in compact["candidates"] if item.get("candidateId")]
        if compact_records:
            compact["records"] = [
                {
                    key: value
                    for key, value in {
                        "recordId": str(item.get("recordId") or "")[:160],
                        "title": str(item.get("title") or "")[:80],
                        "locator": str(item.get("locator") or "")[:120],
                        "summary": str(item.get("summary") or "")[:220],
                        "evidenceRefs": list(item.get("evidenceRefs") or [])[:1],
                        "evidenceScope": item.get("evidenceScope"),
                    }.items()
                    if value not in ("", [], None)
                }
                for item in compact_records[:12]
            ]
            compact["recordIds"] = [item.get("recordId") for item in compact["records"] if item.get("recordId")]
        compact["usage"] = {
            key: value
            for key, value in compact_usage.items()
            if key in {"readTool", "writebackTool", "continuationHint", "recordContinuationHint", "retryInstruction", "evidenceInstruction"}
            and value
        }
        content = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(content) <= max_chars + 700:
            return content
        # An evidence-mode result must never fall through to the generic
        # preview-only fallback below.  In particular, relation mapping needs
        # the anchor for every model-visible candidate to create reviewable
        # edges.  Reduce the visible page before removing that anchor.
        for candidate_count in range(len(compact_candidates), 0, -1):
            evidence_candidates = [
                {
                    key: value
                    for key, value in {
                        "candidateId": str(item.get("candidateId") or "")[:160],
                        "title": str(item.get("title") or "")[:80],
                        "locator": str(item.get("locator") or "")[:120],
                        "evidenceRefs": list(item.get("evidenceRefs") or [])[:1],
                        "evidenceScope": item.get("evidenceScope"),
                    }.items()
                    if value not in ("", [], None)
                }
                for item in compact_candidates[:candidate_count]
            ]
            visible_page = dict(page)
            page_offset = int(page.get("offset") or 0)
            page_total = int(page.get("total") or len(compact_candidates))
            next_offset = page_offset + len(evidence_candidates)
            visible_page["returned"] = len(evidence_candidates)
            visible_page["hasMore"] = next_offset < page_total
            visible_page["nextOffset"] = next_offset if visible_page["hasMore"] else None
            evidence_usage = {
                "readTool": "source_collection_context_tool",
                "writebackTool": "source_collection_stage_writeback_tool",
                "evidenceInstruction": str(raw_usage.get("evidenceInstruction") or "")[:320],
            }
            if visible_page["hasMore"]:
                evidence_usage["continuationHint"] = (
                    "source_collection_context_tool("
                    f"candidate_offset={next_offset},candidate_limit={candidate_count},context_mode={raw_context_mode})"
                )
            evidence_only = {
                "status": payload.get("status"),
                "contextKind": payload.get("contextKind"),
                "contextMode": f"{raw_context_mode}_evidence_anchor_only",
                "fieldMode": "evidence_source",
                "candidateFieldsTruncated": True,
                "doNotUsePreviewAsEvidence": False,
                "visibleCandidateCount": len(evidence_candidates),
                "omittedReturnedCandidateCount": max(0, int(page.get("returned") or 0) - len(evidence_candidates)),
                "candidatePage": visible_page,
                "candidateIds": [item.get("candidateId") for item in evidence_candidates if item.get("candidateId")],
                "candidates": evidence_candidates,
                "usage": {key: value for key, value in evidence_usage.items() if value},
                "truncationGuard": {
                    "originalLength": len(result_str),
                    "message": "structured_compact; evidence anchors retained while the visible candidate page was reduced",
                },
            }
            content = json.dumps(evidence_only, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if len(content) <= max_chars + 700:
                return content
    compact["candidates"] = [
        {
            "candidateId": str(item.get("candidateId") or "")[:160],
            "title": str(item.get("title") or "")[:32],
            "locator": str(item.get("locator") or "")[:80],
            "summaryPreview": str(item.get("summaryPreview") or "")[:24],
        }
        for item in compact_candidates[:12]
    ]
    compact["candidateIds"] = [item.get("candidateId") for item in compact["candidates"] if item.get("candidateId")]
    compact["usage"] = {
        key: value
        for key, value in {
            "readTool": "source_collection_context_tool",
            "continuationHint": compact_usage.get("continuationHint"),
            "recordContinuationHint": compact_usage.get("recordContinuationHint"),
        }.items()
        if value
    }
    compact.pop("status", None)
    compact.pop("contextKind", None)
    compact.pop("truncationGuard", None)
    if not compact_records and not (record_page.get("hasMore") or record_page.get("total")):
        compact.pop("visibleRecordCount", None)
        compact.pop("omittedReturnedRecordCount", None)
        compact.pop("recordPage", None)
        compact.pop("recordIds", None)
        compact.pop("records", None)
    content = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(content) <= max_chars + 700:
        return content
    for item in compact_candidates:
        item["summaryPreview"] = str(item.get("summaryPreview") or "")[:24]
        item["title"] = str(item.get("title") or "")[:64]
        item["locator"] = str(item.get("locator") or "")[:96]
    for item in compact_records:
        item["summaryPreview"] = str(item.get("summaryPreview") or "")[:24]
        item["title"] = str(item.get("title") or "")[:64]
        item["locator"] = str(item.get("locator") or "")[:96]
    content = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(content) <= max_chars + 500:
        return content
    if compact_records or record_page.get("hasMore") or record_page.get("total"):
        compact["records"] = compact_records[:5]
        compact["recordIds"] = [item.get("recordId") for item in compact["records"] if item.get("recordId")]
        compact["visibleRecordCount"] = len(compact["records"])
        compact["omittedReturnedRecordCount"] = max(0, int(record_page.get("returned") or len(compact_records)) - len(compact["records"]))
    compact["candidates"] = compact_candidates[:5]
    compact["candidateIds"] = [item.get("candidateId") for item in compact["candidates"] if item.get("candidateId")]
    compact["visibleCandidateCount"] = len(compact["candidates"])
    compact["omittedReturnedCandidateCount"] = max(0, int(page.get("returned") or len(compact_candidates)) - len(compact["candidates"]))
    return json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _compact_source_collection_steward_action_packet(packet: dict[str, Any]) -> dict[str, Any]:
    approved_ids = [
        str(item)[:160]
        for item in list(packet.get("approvedCandidateIds") or [])[:80]
        if str(item).strip()
    ]
    skeleton = packet.get("writebackResultSkeleton") if isinstance(packet.get("writebackResultSkeleton"), dict) else {}
    candidate_summary = skeleton.get("candidate_summary") if isinstance(skeleton.get("candidate_summary"), dict) else {}
    approved = candidate_summary.get("approved") if isinstance(candidate_summary.get("approved"), dict) else {}
    deferred_counts = candidate_summary.get("deferredCounts") if isinstance(candidate_summary.get("deferredCounts"), dict) else {}
    steward_assessment = skeleton.get("steward_assessment") if isinstance(skeleton.get("steward_assessment"), dict) else {}
    skeleton_approved_ids = [
        str(item)[:160]
        for item in list(skeleton.get("approvedCandidateIds") or approved.get("candidateIds") or approved_ids)[:80]
        if str(item).strip()
    ]
    compact_skeleton = {
        "approvedCandidateIds": skeleton_approved_ids,
        "candidate_summary": {
            "approved": {
                "count": int(approved.get("count") or len(skeleton_approved_ids)),
                "candidateIds": skeleton_approved_ids,
            },
            "deferredCounts": deferred_counts,
        },
        "steward_assessment": {
            key: value
            for key, value in steward_assessment.items()
            if key in {"decision", "reason", "targetDomain", "confidence"}
        },
    }
    return {
        key: value
        for key, value in {
            "schemaVersion": packet.get("schemaVersion"),
            "packetKind": str(packet.get("packetKind") or "")[:120],
            "action": str(packet.get("action") or "")[:120],
            "recommendedStatus": str(packet.get("recommendedStatus") or "")[:80],
            "approvedCandidateIds": approved_ids,
            "approvedCandidateCount": int(packet.get("approvedCandidateCount") or len(approved_ids)),
            "deferredCandidateCounts": packet.get("deferredCandidateCounts")
            if isinstance(packet.get("deferredCandidateCounts"), dict)
            else {},
            "writebackTool": str(packet.get("writebackTool") or "")[:120],
            "writebackContractTaskId": str(packet.get("writebackContractTaskId") or "")[:160],
            "writebackResultSkeleton": compact_skeleton,
            "instructions": [str(item)[:240] for item in list(packet.get("instructions") or [])[:4]],
        }.items()
        if value not in ("", [], {}, None)
    }


def _compact_source_collection_tool_excluded_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        key: summary.get(key)
        for key in ("excludedCount", "activeRecordCount", "rawRecordCount")
        if key in summary
    }


def _compact_code_context_graph_result(result_str: str, max_chars: int, continuation_hint: str) -> Optional[str]:
    payload = _try_parse_json_object(result_str)
    if not payload:
        return None

    compact = {
        key: payload.get(key)
        for key in (
            "status",
            "mode",
            "query",
            "target",
            "summary",
            "count",
            "totalCount",
            "hasMore",
            "resultLimit",
            "index",
            "error",
            "message",
        )
        if key in payload
    }
    omitted: dict[str, int] = {}

    def compact_items(key: str, limit: int) -> list[dict[str, Any]]:
        items = [item for item in list(payload.get(key) or []) if isinstance(item, dict)]
        selected = []
        for item in items[:limit]:
            selected.append(
                {
                    field: (str(value)[:180] if field in {"preview", "summary", "text", "snippet"} else value)
                    for field, value in item.items()
                    if field in {
                        "kind", "name", "qualifiedName", "path", "language", "line", "endLine",
                        "lineCount", "score", "summary", "preview", "text", "snippet",
                    }
                }
            )
        if len(items) > len(selected):
            omitted[key] = len(items) - len(selected)
        return selected

    for key, limit in (("results", 8), ("files", 8), ("symbols", 8), ("snippets", 3), ("tests", 8)):
        selected = compact_items(key, limit)
        if selected:
            compact[key] = selected

    contexts = [item for item in list(payload.get("contexts") or []) if isinstance(item, dict)]
    if contexts:
        compact["contexts"] = [
            {
                "path": item.get("path"),
                "language": item.get("language"),
                "summary": str(item.get("summary") or "")[:180],
                "snippet": str(item.get("snippet") or "")[:300],
                "symbols": [
                    {
                        field: symbol.get(field)
                        for field in ("name", "qualifiedName", "kind", "path", "line")
                        if field in symbol
                    }
                    for symbol in list(item.get("symbols") or [])[:4]
                    if isinstance(symbol, dict)
                ],
            }
            for item in contexts[:3]
        ]
        if len(contexts) > 3:
            omitted["contexts"] = len(contexts) - 3

    relationship_map = payload.get("relationshipMap") if isinstance(payload.get("relationshipMap"), dict) else {}
    if relationship_map:
        compact["relationshipMap"] = {
            "nodes": list(relationship_map.get("nodes") or [])[:6],
            "edges": list(relationship_map.get("edges") or [])[:8],
        }
    if omitted:
        compact["omitted"] = omitted
    if continuation_hint:
        compact["continuationHint"] = continuation_hint
    compact["truncationGuard"] = {
        "originalLength": len(result_str),
        "strategy": "structured_compact",
    }

    content = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(content) <= max_chars + 700:
        return content

    compact.pop("relationshipMap", None)
    compact.pop("contexts", None)
    for key in ("results", "files", "symbols", "snippets", "tests"):
        if isinstance(compact.get(key), list):
            compact[key] = compact[key][:4]
    content = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(content) <= max_chars + 700:
        return content

    minimal = {
        key: compact.get(key)
        for key in (
            "status",
            "mode",
            "query",
            "target",
            "summary",
            "count",
            "totalCount",
            "hasMore",
            "resultLimit",
            "error",
            "message",
            "omitted",
            "continuationHint",
            "truncationGuard",
        )
        if key in compact
    }
    for key in ("results", "files", "symbols", "snippets", "tests"):
        items = compact.get(key)
        if not isinstance(items, list) or not items:
            continue
        minimal[key] = [
            {
                field: item.get(field)
                for field in ("kind", "name", "qualifiedName", "path", "line", "score")
                if field in item
            }
            for item in items[:2]
            if isinstance(item, dict)
        ]
    return json.dumps(minimal, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def package_tool_result(
    result: Any,
    *,
    tool_name: str = "",
    max_chars: int = DEFAULT_MAX_CHARS,
) -> ToolResultEnvelope:
    """将工具结果封装为带元信息的统一结构。"""
    if isinstance(result, (bytes, bytearray)):
        try:
            result_str = result.decode("utf-8", errors="replace")
        except Exception as exc:
            _debug_logger.warning(
                f"[工具结果] 打包结果 decode 失败: {type(result).__name__}: {exc}",
                tag="TOOL_RESULT",
            )
            result_str = str(result)
    elif isinstance(result, (dict, list)):
        try:
            result_str = json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            result_str = str(result)
    else:
        result_str = str(result)
    result_kind = _infer_result_kind(tool_name, result_str)
    range_info = _extract_range_info(result_kind, result_str)
    continuation_hint = _extract_continuation_hint(result_kind, result_str)
    semantics = extract_tool_result_semantics(result)

    if len(result_str) <= max_chars:
        return ToolResultEnvelope(
            content=result_str,
            truncated=False,
            original_length=len(result_str),
            result_kind=result_kind,
            strategy="passthrough",
            range_info=range_info,
            continuation_hint=continuation_hint,
            transport_status=str(semantics["transportStatus"]),
            semantic_status=str(semantics["semanticStatus"]),
            exit_code=semantics["exitCode"],
            timed_out=bool(semantics["timedOut"]),
            failure_class=str(semantics["failureClass"] or ""),
        )

    compact_content: Optional[str] = None
    if result_kind == "file_read":
        compact_content = _compact_file_read(result_str, max_chars, continuation_hint)
    elif result_kind == "search":
        compact_content = _compact_search_result(result_str, max_chars, continuation_hint)
    elif result_kind == "source_collection_context":
        compact_content = _compact_source_collection_context_result(result_str, max_chars, continuation_hint)
    elif result_kind == "code_context_graph":
        compact_content = _compact_code_context_graph_result(result_str, max_chars, continuation_hint)
    if compact_content:
        return ToolResultEnvelope(
            content=compact_content,
            truncated=True,
            original_length=len(result_str),
            result_kind=result_kind,
            strategy="structured_compact",
            range_info=range_info,
            continuation_hint=continuation_hint,
            transport_status=str(semantics["transportStatus"]),
            semantic_status=str(semantics["semanticStatus"]),
            exit_code=semantics["exitCode"],
            timed_out=bool(semantics["timedOut"]),
            failure_class=str(semantics["failureClass"] or ""),
        )

    suffix_lines = [
        f"[...结果已截断，原长度 {len(result_str)} 字符...]",
        f"[截断信息] 类型={result_kind} | 原长度={len(result_str)} 字符",
    ]
    if range_info:
        suffix_lines.append(f"[截断信息] 当前范围={range_info}")
    if continuation_hint:
        suffix_lines.append(f"[截断信息] 阅读导航={continuation_hint}")
    suffix = "\n" + "\n".join(suffix_lines)
    budget = max(0, max_chars - len(suffix) - 1)
    if budget < max(8, max_chars // 3):
        legacy_content = result_str[:max_chars] + f"\n[...结果已截断，原长度 {len(result_str)} 字符...]"
        return ToolResultEnvelope(
            content=legacy_content,
            truncated=True,
            original_length=len(result_str),
            result_kind=result_kind,
            strategy="legacy_prefix_truncate",
            range_info=range_info,
            continuation_hint=continuation_hint,
            transport_status=str(semantics["transportStatus"]),
            semantic_status=str(semantics["semanticStatus"]),
            exit_code=semantics["exitCode"],
            timed_out=bool(semantics["timedOut"]),
            failure_class=str(semantics["failureClass"] or ""),
        )
    content = result_str[:budget] + suffix if budget > 0 else suffix.lstrip()

    return ToolResultEnvelope(
        content=content,
        truncated=True,
        original_length=len(result_str),
        result_kind=result_kind,
        strategy="annotated_truncate",
        range_info=range_info,
        continuation_hint=continuation_hint,
        transport_status=str(semantics["transportStatus"]),
        semantic_status=str(semantics["semanticStatus"]),
        exit_code=semantics["exitCode"],
        timed_out=bool(semantics["timedOut"]),
        failure_class=str(semantics["failureClass"] or ""),
    )


def truncate_result(result: Any, max_chars: int = DEFAULT_MAX_CHARS) -> tuple:
    """
    截断超长工具结果

    Args:
        result: 工具结果
        max_chars: 最大字符数

    Returns:
        (截断后的结果字符串, 是否被截断)
    """
    packaged = package_tool_result(result, max_chars=max_chars)
    return packaged.content, packaged.truncated


def project_runtime_tool_metadata(
    result: Any,
    *,
    tool_name: str = "",
    max_chars: int = DEFAULT_MAX_CHARS,
) -> RuntimeToolMetadata:
    """投影运行时元数据；调用方不得将其序列化进模型消息。"""
    packaged = package_tool_result(result, tool_name=tool_name, max_chars=max_chars)
    return RuntimeToolMetadata(
        result_kind=packaged.result_kind,
        strategy=packaged.strategy,
        range_info=packaged.range_info,
        continuation_hint=packaged.continuation_hint,
        truncated=packaged.truncated,
        original_length=packaged.original_length,
        transport_status=packaged.transport_status,
        semantic_status=packaged.semantic_status,
        exit_code=packaged.exit_code,
        timed_out=packaged.timed_out,
        failure_class=packaged.failure_class,
    )


def package_tool_result_facts(
    result: Any,
    *,
    tool_name: str = "",
    action: Optional[str] = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> ToolResultFacts:
    """将工具原始返回值封装为模型可见的事实载荷。"""
    packaged = package_tool_result(result, tool_name=tool_name, max_chars=max_chars)
    return ToolResultFacts(
        tool_name=str(tool_name or "").strip(),
        content=project_tool_result_for_model(packaged.content),
        truncated=packaged.truncated,
        original_length=packaged.original_length,
        result_kind=packaged.result_kind,
        strategy=packaged.strategy,
        range_info=packaged.range_info,
        continuation_hint="",
        transport_status=packaged.transport_status,
        semantic_status=packaged.semantic_status,
        exit_code=packaged.exit_code,
        timed_out=packaged.timed_out,
        failure_class=packaged.failure_class,
        action=str(action or "").strip(),
    )


def tool_result_facts_payload(facts: ToolResultFacts) -> dict[str, Any]:
    """转为 API/事件可安全传输的事实字段。"""
    payload: dict[str, Any] = {
        "transportStatus": facts.transport_status,
        "semanticStatus": facts.semantic_status,
        "timedOut": bool(facts.timed_out),
        "truncated": bool(facts.truncated),
        "originalLength": int(facts.original_length),
        "resultKind": facts.result_kind,
        "strategy": facts.strategy,
    }
    if facts.tool_name:
        payload["toolName"] = facts.tool_name
    if facts.exit_code is not None:
        payload["exitCode"] = facts.exit_code
    if facts.failure_class:
        payload["failureClass"] = facts.failure_class
    if facts.range_info:
        payload["rangeInfo"] = facts.range_info
    if facts.action:
        payload["action"] = facts.action
    return payload


def render_tool_result_for_model(facts: ToolResultFacts) -> str:
    """把工具结果渲染成 Agent 可自然读取的事实块。"""
    lines = ["[Tool Result Facts]"]
    if facts.tool_name:
        lines.append(f"toolName: {facts.tool_name}")
    lines.append(f"transportStatus: {facts.transport_status}")
    lines.append(f"semanticStatus: {facts.semantic_status}")
    if facts.exit_code is not None:
        lines.append(f"exitCode: {facts.exit_code}")
    lines.append(f"timedOut: {str(bool(facts.timed_out)).lower()}")
    if facts.failure_class:
        lines.append(f"failureClass: {facts.failure_class}")
    lines.append(f"resultKind: {facts.result_kind}")
    lines.append(f"truncated: {str(bool(facts.truncated)).lower()}")
    lines.append(f"originalLength: {facts.original_length}")
    if facts.action:
        lines.append(f"action: {facts.action}")
    if facts.range_info:
        lines.append(f"rangeInfo: {facts.range_info}")
    lines.extend(["", "Result:", facts.content])
    return "\n".join(lines)


def infer_result_from_tool_outputs(tool_outputs: List[str]) -> Dict[str, Any]:
    """从最近工具输出中提炼结构化诊断结果。"""
    haystack = "\n".join(str(item or "") for item in tool_outputs if str(item or "").strip())
    if not haystack:
        return {}

    error_patterns = [
        r"(OSError:\s*\[Errno\s*\d+\][^\n]*)",
        r"(ValueError:[^\n]*)",
        r"(RuntimeError:[^\n]*)",
        r"(TimeoutError:[^\n]*)",
        r"(主循环异常:[^\n]*)",
        r"(\[超时\][^\n]*)",
    ]
    evidence: List[str] = []
    findings: List[str] = []
    for pattern in error_patterns:
        match = re.search(pattern, haystack, flags=re.IGNORECASE)
        if match:
            line = match.group(1).strip()
            evidence.append(line)
            findings.append(f"最近工具输出已包含异常线索: {line}")
            break

    if "Traceback" in haystack:
        findings.append("最近工具输出包含 traceback，可直接作为诊断证据。")

    if not evidence and not findings:
        return {}

    return {
        "status": "partial",
        "summary": evidence[0] if evidence else "最近工具输出已包含可用异常线索。",
        "findings": findings[:3],
        "evidence": evidence[:3],
        "recommended_next_action": "根据现有异常证据直接收束，不再继续扩散读取。",
        "confidence": "medium",
    }


def compact_tool_output_for_diagnosis(text: str, max_chars: int = 6000) -> str:
    """压缩超长工具输出，保留头尾证据。"""
    raw = str(text or "")
    evidence_lines: List[str] = []
    for pattern in (
        r"OSError:\s*\[Errno\s*\d+\][^\n]*",
        r"ValueError:[^\n]*",
        r"RuntimeError:[^\n]*",
        r"TimeoutError:[^\n]*",
        r"主循环异常:[^\n]*",
        r"\[超时\][^\n]*",
    ):
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            evidence_lines.append(match.group(0).strip())

    if len(raw) <= max_chars:
        compacted = raw
    else:
        head = max_chars // 2
        tail = max_chars - head
        compacted = raw[:head] + "\n...\n" + raw[-tail:]

    if evidence_lines:
        suffix = "\n".join(dict.fromkeys(evidence_lines))
        if suffix not in compacted:
            compacted = f"{compacted}\n\n[提取证据]\n{suffix}"
    return compacted


def format_tool_message(
    tool_call: Dict,
    result: Any,
    action: Optional[str] = None,
) -> tuple:
    """
    格式化工具消息

    Args:
        tool_call: 工具调用信息
        result: 工具执行结果
        action: 特殊动作

    Returns:
        (ToolMessage 内容字符串, tool_call_id)
    """
    tool_name = str(tool_call.get("name") or "").strip()
    facts = package_tool_result_facts(result, tool_name=tool_name, action=action)
    result_str = render_tool_result_for_model(facts)

    # 安全获取 tool_call_id
    tool_call_id = str(tool_call.get('id', '')) if tool_call.get('id') is not None else ''

    return result_str, tool_call_id


__all__ = [
    "truncate_result",
    "package_tool_result",
    "package_tool_result_facts",
    "tool_result_facts_payload",
    "render_tool_result_for_model",
    "project_tool_result_for_model",
    "extract_tool_result_semantics",
    "ToolResultEnvelope",
    "ModelVisibleToolResult",
    "ToolResultFacts",
    "RuntimeToolMetadata",
    "project_runtime_tool_metadata",
    "format_tool_message",
    "compact_tool_output_for_diagnosis",
    "infer_result_from_tool_outputs",
    "DEFAULT_MAX_CHARS",
]
