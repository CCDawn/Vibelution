# -*- coding: utf-8 -*-
"""shared result-contract helpers for chat coding mode."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from .chat_task_types import dedupe_strings, trim_lines


READ_TOOL_NAMES = {
    "read_file_tool",
    "grep_search_tool",
    "glob_tool",
    "code_symbol_tool",
}

WRITE_TOOL_NAMES = {
    "apply_diff_edit_tool",
    "write_file_tool",
}

VERIFY_TOOL_NAMES = {
    "run_test_for_tool",
    "python_lint_tool",
}

PYTEST_CROSS_PLATFORM_BLOCKED_REASON = "pytest 命令被跨平台检查拦截，验证尚未执行。"
MISSING_MAPPED_TEST_BLOCKED_REASON = "run_test_for_tool 未找到映射测试，验证尚未执行。"
LINT_ISSUES_BLOCKED_REASON = "python_lint_tool 发现 lint 问题，验证未通过。"
PY_COMPILE_FAILED_BLOCKED_REASON = "python -m py_compile 执行失败，验证未通过。"

PATH_ARG_KEYS = (
    "file_path",
    "path",
    "source_path",
    "target",
    "search_dir",
)


def _tool_args_dict(record: Dict[str, Any]) -> Dict[str, Any]:
    value = record.get("args") or record.get("tool_args") or {}
    return value if isinstance(value, dict) else {}


def _tool_name(record: Dict[str, Any]) -> str:
    return str(record.get("name") or record.get("tool_name") or "").strip()


def _tool_command(record: Dict[str, Any]) -> str:
    return str(_tool_args_dict(record).get("command") or "").strip()


def _tool_result_preview(record: Dict[str, Any]) -> str:
    return trim_lines(
        record.get("result_preview")
        or record.get("resultPreview")
        or record.get("tool_result")
        or record.get("summary")
        or record.get("raw_output")
        or record.get("result")
        or "",
        max_lines=3,
    )


def _parse_json_payload(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    if not value.startswith("{"):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _has_failure_marker(text: str) -> bool:
    lowered = str(text or "").lower()
    return bool(
        "[错误]" in text
        or "[超时]" in text
        or "[短路]" in text
        or "[安全拦截]" in text
        or "[跨平台警告]" in text
        or "[exec failure" in lowered
        or "[warning | exit code" in lowered
        or " failed" in lowered
        or "失败" in text
        or "syntaxerror" in lowered
        or "traceback" in lowered
    )


def _pytest_passed(text: str) -> bool:
    if _has_failure_marker(text) or "[运行测试] 未找到对应测试文件" in text:
        return False
    lowered = str(text or "").lower()
    return bool(re.search(r"(?:^|[=\s])\d+\s+passed\b", lowered) or re.search(r"\bpassed\b", lowered))


def _lint_issue_count(payload: dict[str, Any]) -> int | None:
    if "issue_count" not in payload and "issueCount" not in payload:
        return None
    try:
        return int(payload.get("issue_count", payload.get("issueCount")))
    except (TypeError, ValueError):
        return None


def verification_from_tool_record(record: Dict[str, Any]) -> Tuple[str, str, str]:
    name = _tool_name(record)
    command = _tool_command(record)
    preview = _tool_result_preview(record)
    if not preview and name not in VERIFY_TOOL_NAMES and "pytest" not in command and "py_compile" not in command:
        return ("", "", "")

    if "[跨平台警告]" in preview and "pytest" in command.lower():
        return ("failed", preview or PYTEST_CROSS_PLATFORM_BLOCKED_REASON, PYTEST_CROSS_PLATFORM_BLOCKED_REASON)

    if name == "run_test_for_tool":
        if "[运行测试] 未找到对应测试文件" in preview:
            return ("failed", preview, MISSING_MAPPED_TEST_BLOCKED_REASON)
        if _pytest_passed(preview):
            return ("passed", preview or "pytest 通过", "")
        return ("failed", preview or f"{name} 验证未通过", "")

    if "pytest" in command.lower():
        if _pytest_passed(preview):
            return ("passed", preview or "pytest 通过", "")
        return ("failed", preview or "pytest 验证未通过", "")

    if "py_compile" in command:
        if "[命令执行完成，无输出]" in preview and not _has_failure_marker(preview):
            return ("passed", "python -m py_compile 通过", "")
        return ("failed", preview or PY_COMPILE_FAILED_BLOCKED_REASON, PY_COMPILE_FAILED_BLOCKED_REASON)

    if name == "python_lint_tool":
        payload = _parse_json_payload(preview)
        status = str(payload.get("status") or "").strip().lower()
        issue_count = _lint_issue_count(payload)
        if status in {"ok", "success", "passed"} and issue_count == 0:
            return ("passed", preview or "ruff lint 通过", "")
        if status in {"ok", "success", "passed"} and issue_count and issue_count > 0:
            return ("failed", preview or LINT_ISSUES_BLOCKED_REASON, LINT_ISSUES_BLOCKED_REASON)
        return ("failed", preview or f"{name} 验证未通过", "")

    return ("", "", "")


def blocked_reason_from_tool_trace(tool_trace: List[Dict[str, Any]]) -> str:
    for record in reversed(list(tool_trace or [])):
        _, _, blocked_reason = verification_from_tool_record(record)
        if blocked_reason:
            return blocked_reason
    return ""


def extract_paths(record: Dict[str, Any]) -> List[str]:
    args = _tool_args_dict(record)
    paths: List[str] = []
    for key in PATH_ARG_KEYS:
        value = args.get(key)
        if isinstance(value, (str, int, float)):
            text = str(value).strip()
            if text:
                paths.append(text)
    return dedupe_strings(paths, limit=8)


def verification_from_tool_trace(tool_trace: List[Dict[str, Any]]) -> Tuple[str, str]:
    for record in reversed(list(tool_trace or [])):
        name = _tool_name(record)
        command = _tool_command(record)
        if name not in VERIFY_TOOL_NAMES and "pytest" not in command and "py_compile" not in command:
            continue
        status, summary, _ = verification_from_tool_record(record)
        if status or summary:
            return (status, summary)
    return ("", "")


def activity_from_tool_trace(tool_trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    read_files: List[str] = []
    changed_files: List[str] = []
    saw_read = False
    saw_write = False
    saw_verify = False
    for record in list(tool_trace or []):
        name = _tool_name(record)
        command = _tool_command(record)
        paths = extract_paths(record)
        if name in READ_TOOL_NAMES:
            read_files.extend(paths)
            saw_read = True
        if name in WRITE_TOOL_NAMES:
            changed_files.extend(paths)
            saw_write = True
        if name in VERIFY_TOOL_NAMES:
            saw_verify = True
        if "pytest" in command or "py_compile" in command:
            saw_verify = True
    return {
        "read_files": dedupe_strings(read_files, limit=12),
        "changed_files": dedupe_strings(changed_files, limit=12),
        "saw_read": saw_read,
        "saw_write": saw_write,
        "saw_verify": saw_verify,
    }


def _string_list(value: Any, *, limit: int = 12) -> List[str]:
    if isinstance(value, list):
        return dedupe_strings(value, limit=limit)
    if isinstance(value, tuple):
        return dedupe_strings(list(value), limit=limit)
    if isinstance(value, str) and value.strip():
        return dedupe_strings([value], limit=limit)
    return []


def _preferred_next_action(result: Dict[str, Any]) -> str:
    return trim_lines(
        result.get("next_action")
        or result.get("recommended_next_action")
        or result.get("required_user_input")
        or "",
        max_lines=2,
    )


def _preferred_blocked_reason(result: Dict[str, Any]) -> str:
    return trim_lines(result.get("blocked_reason") or "", max_lines=3)


def _preferred_required_user_input(result: Dict[str, Any]) -> str:
    return trim_lines(result.get("required_user_input") or "", max_lines=2)


def _has_visible_completion_signal(result: Dict[str, Any]) -> bool:
    text = trim_lines(result.get("summary") or result.get("raw_output") or "", max_lines=8).lower()
    if not text:
        return False
    incomplete_markers = (
        "未完成",
        "没有完成",
        "尚未完成",
        "继续完成",
        "not completed",
        "incomplete",
    )
    if any(marker in text for marker in incomplete_markers):
        return False
    completion_markers = (
        "任务完成",
        "已完成",
        "已经完成",
        "执行成功",
        "已生成",
        "生成完成",
        "生成完毕",
        "成功生成",
        "已成功生成",
        "文件已成功创建",
        "成功创建",
        "已为您生成",
        "created successfully",
        "successfully created",
        "generated successfully",
        "task complete",
        "task completed",
    )
    return any(marker in text for marker in completion_markers)


def _preferred_verification(result: Dict[str, Any], tool_trace: List[Dict[str, Any]]) -> Tuple[str, str]:
    status = str(result.get("verification_status") or "").strip().lower()
    summary = trim_lines(result.get("verification_summary") or "", max_lines=3)
    if status or summary:
        return (status, summary)
    return verification_from_tool_trace(tool_trace)


def _preferred_outcome(
    result: Dict[str, Any],
    *,
    read_files: List[str],
    changed_files: List[str],
    verification_status: str,
    blocked_reason: str,
) -> str:
    explicit = str(result.get("outcome") or result.get("task_outcome") or "").strip().lower()
    if explicit:
        return explicit
    if bool(result.get("needs_user_input")) or bool(result.get("requires_user_input")):
        return "needs_input"
    if result.get("required_user_input"):
        return "needs_input"
    if blocked_reason:
        return "blocked"
    status = str(result.get("status") or "").strip().lower()
    if status in {"failed", "timeout"} or verification_status == "failed":
        return "blocked"
    if status == "completed" and changed_files and _has_visible_completion_signal(result):
        return "done"
    if verification_status == "passed" and changed_files:
        return "done"
    if changed_files or read_files or int(result.get("tool_call_count") or 0) > 0:
        return "progress"
    if trim_lines(result.get("summary") or result.get("raw_output") or "", max_lines=3):
        return "no_change"
    return ""


def build_chat_coding_result_contract(result: Dict[str, Any] | Any) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}

    tool_trace = list(result.get("tool_trace") or [])
    activity = activity_from_tool_trace(tool_trace)
    read_files = dedupe_strings(
        _string_list(result.get("read_files")) + list(activity.get("read_files") or []),
        limit=12,
    )
    changed_files = dedupe_strings(
        _string_list(result.get("changed_files")) + list(activity.get("changed_files") or []),
        limit=12,
    )
    verification_status, verification_summary = _preferred_verification(result, tool_trace)
    blocked_reason = _preferred_blocked_reason(result) or blocked_reason_from_tool_trace(tool_trace)
    required_user_input = _preferred_required_user_input(result)
    next_action = _preferred_next_action(result)
    outcome = _preferred_outcome(
        result,
        read_files=read_files,
        changed_files=changed_files,
        verification_status=verification_status,
        blocked_reason=blocked_reason,
    )
    return {
        "read_files": read_files,
        "changed_files": changed_files,
        "verification_status": verification_status,
        "verification_summary": verification_summary,
        "blocked_reason": blocked_reason,
        "required_user_input": required_user_input,
        "needs_user_input": outcome == "needs_input",
        "next_action": next_action,
        "outcome": outcome,
        "no_change": not bool(changed_files),
    }


__all__ = [
    "PATH_ARG_KEYS",
    "READ_TOOL_NAMES",
    "VERIFY_TOOL_NAMES",
    "WRITE_TOOL_NAMES",
    "activity_from_tool_trace",
    "blocked_reason_from_tool_trace",
    "build_chat_coding_result_contract",
    "extract_paths",
    "verification_from_tool_record",
    "verification_from_tool_trace",
]
