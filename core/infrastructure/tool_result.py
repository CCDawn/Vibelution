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
class ToolResultFacts:
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
        if stripped.startswith(("[错误]", "[超时]", "[短路]", "[EXEC FAILURE", "[WARNING | Exit Code", "[执行失败")):
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
    text = result_str or ""
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


def package_tool_result_facts(
    result: Any,
    *,
    tool_name: str = "",
    action: Optional[str] = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> ToolResultFacts:
    """将工具原始返回值封装为模型与 UI 共享的事实载荷。"""
    packaged = package_tool_result(result, tool_name=tool_name, max_chars=max_chars)
    return ToolResultFacts(
        tool_name=str(tool_name or "").strip(),
        content=packaged.content,
        truncated=packaged.truncated,
        original_length=packaged.original_length,
        result_kind=packaged.result_kind,
        strategy=packaged.strategy,
        range_info=packaged.range_info,
        continuation_hint=packaged.continuation_hint,
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
    if facts.continuation_hint:
        payload["continuationHint"] = facts.continuation_hint
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
    if facts.continuation_hint:
        lines.append(f"continuationHint: {facts.continuation_hint}")
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
    "extract_tool_result_semantics",
    "ToolResultEnvelope",
    "ToolResultFacts",
    "format_tool_message",
    "compact_tool_output_for_diagnosis",
    "infer_result_from_tool_outputs",
    "DEFAULT_MAX_CHARS",
]
