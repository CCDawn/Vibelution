# -*- coding: utf-8 -*-
"""Read-only conversation log inspection helpers for Agent tooling."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_INFO_DIR = PROJECT_ROOT / "log_info"
MAX_CANDIDATE_SCAN_LINES = 120
MAX_RESULT_ITEMS = 40
MAX_TOOL_SEQUENCE = 80


def conversation_log_inspect_tool(
    query: str = "",
    log_path: str = "",
    limit: int = 5,
    max_events: int = 8000,
) -> str:
    """Inspect conversation JSONL logs and return compact diagnostics."""

    try:
        payload = inspect_conversation_logs(
            query=query,
            log_path=log_path,
            limit=limit,
            max_events=max_events,
        )
    except Exception as exc:
        payload = {
            "status": "error",
            "code": exc.__class__.__name__,
            "message": str(exc),
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def inspect_conversation_logs(
    *,
    query: str = "",
    log_path: str = "",
    limit: int = 5,
    max_events: int = 8000,
) -> dict[str, Any]:
    normalized_limit = _bounded_int(limit, default=5, minimum=1, maximum=20)
    normalized_max_events = _bounded_int(max_events, default=8000, minimum=200, maximum=50000)
    candidates = _select_candidate_logs(query=query, log_path=log_path, limit=normalized_limit)
    inspections = [
        _inspect_log(path, max_events=normalized_max_events)
        for path in candidates
    ]
    return {
        "status": "ok",
        "tool": "conversation_log_inspect_tool",
        "inspectedAt": datetime.now(timezone.utc).isoformat(),
        "query": str(query or "").strip(),
        "logPath": str(log_path or "").strip(),
        "candidateCount": len(candidates),
        "candidates": [
            _candidate_summary(path)
            for path in candidates
        ],
        "inspections": inspections,
        "summary": _aggregate_inspections(inspections),
        "usageGuidance": [
            "Use this tool before grep/read_file when the task is to review conversation JSONL logs.",
            "Read raw log lines only after this summary identifies a narrow path and line range.",
        ],
    }


def _select_candidate_logs(*, query: str, log_path: str, limit: int) -> list[Path]:
    if str(log_path or "").strip():
        path = _resolve_allowed_log_path(log_path)
        return [path]

    if not LOG_INFO_DIR.exists():
        return []

    logs = sorted(
        LOG_INFO_DIR.glob("conversation_*.jsonl"),
        key=lambda item: item.stat().st_mtime if item.exists() else 0,
        reverse=True,
    )
    normalized_query = str(query or "").strip().lower()
    if not normalized_query:
        return logs[:limit]

    matched: list[Path] = []
    for path in logs:
        if _log_matches_query(path, normalized_query):
            matched.append(path)
            if len(matched) >= limit:
                break
    return matched or logs[:limit]


def _resolve_allowed_log_path(value: str) -> Path:
    raw = str(value or "").strip().strip("'\"")
    if not raw:
        raise ValueError("log_path is required when provided.")
    path = Path(raw)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()
    root = PROJECT_ROOT.resolve()
    if root not in (path, *path.parents):
        raise ValueError("conversation_log_inspect_tool only reads logs inside the project root.")
    if path.suffix.lower() != ".jsonl":
        raise ValueError("conversation_log_inspect_tool only reads .jsonl logs.")
    rel = path.relative_to(root).as_posix()
    allowed = rel.startswith("log_info/") or rel.startswith("logs/runtime_scenes/")
    if not allowed:
        raise ValueError("conversation_log_inspect_tool only reads log_info/ or logs/runtime_scenes/ JSONL files.")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Log file not found: {rel}")
    return path


def _log_matches_query(path: Path, normalized_query: str) -> bool:
    if normalized_query in path.name.lower():
        return True
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, line in enumerate(handle, start=1):
                if normalized_query in line.lower():
                    return True
                if line_no >= MAX_CANDIDATE_SCAN_LINES:
                    break
    except Exception:
        return False
    return False


def _inspect_log(path: Path, *, max_events: int) -> dict[str, Any]:
    event_counts: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    tool_call_keys: Counter[str] = Counter()
    tool_sequence: list[dict[str, Any]] = []
    large_results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    token_usage: list[dict[str, Any]] = []
    llm_calls = 0
    total_input = 0
    total_output = 0
    total_events = 0
    malformed_lines = 0
    first_event: dict[str, Any] | None = None
    last_event: dict[str, Any] | None = None

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            if total_events >= max_events:
                break
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                malformed_lines += 1
                continue
            if not isinstance(event, dict):
                malformed_lines += 1
                continue
            total_events += 1
            last_event = event
            if first_event is None:
                first_event = event
            event_type = str(event.get("type") or "unknown").strip() or "unknown"
            event_counts[event_type] += 1

            if event_type == "llm_request":
                llm_calls += 1
                usage = _token_usage_from_event(event)
                if usage:
                    total_input += usage["inputTokens"]
                    total_output += usage["outputTokens"]
                    token_usage.append({"line": line_no, **usage})
            elif event_type in {"token_usage", "llm_response"}:
                usage = _token_usage_from_event(event)
                if usage:
                    total_input += usage["inputTokens"]
                    total_output += usage["outputTokens"]
                    token_usage.append({"line": line_no, **usage})

            if event_type == "tool_call":
                tool_name = str(event.get("tool_name") or event.get("toolName") or "").strip() or "unknown"
                tool_counts[tool_name] += 1
                args = event.get("tool_args") if isinstance(event.get("tool_args"), dict) else {}
                key = _tool_call_key(tool_name, args)
                tool_call_keys[key] += 1
                result_length = _bounded_int(event.get("tool_result_length"), default=0, minimum=0, maximum=10_000_000)
                sequence_item = {
                    "line": line_no,
                    "turn": event.get("turn"),
                    "tool": tool_name,
                    "status": str(event.get("status") or "").strip(),
                    "resultLength": result_length,
                    "argsSummary": _args_summary(args),
                }
                if len(tool_sequence) < MAX_TOOL_SEQUENCE:
                    tool_sequence.append(sequence_item)
                if result_length >= 8000 and len(large_results) < MAX_RESULT_ITEMS:
                    large_results.append(sequence_item)

            if event_type in {"llm_error", "error"} or _event_looks_like_error(event):
                if len(errors) < MAX_RESULT_ITEMS:
                    errors.append(_error_summary(event, line_no=line_no))

    repeated_tools = [
        {"call": key, "count": count}
        for key, count in tool_call_keys.most_common(MAX_RESULT_ITEMS)
        if count > 1
    ]
    inefficiencies = _detect_inefficiencies(
        event_counts=event_counts,
        tool_counts=tool_counts,
        repeated_tools=repeated_tools,
        large_results=large_results,
        total_input=total_input,
        total_output=total_output,
        llm_calls=llm_calls,
        errors=errors,
    )
    return {
        "path": _relative(path),
        "sizeBytes": path.stat().st_size,
        "modifiedAt": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "session": _session_summary(first_event),
        "eventCount": total_events,
        "truncatedAtMaxEvents": total_events >= max_events,
        "malformedLineCount": malformed_lines,
        "eventTypes": dict(event_counts.most_common()),
        "llmCalls": llm_calls,
        "tokenUsage": {
            "observations": len(token_usage),
            "inputTokens": total_input,
            "outputTokens": total_output,
            "totalTokens": total_input + total_output,
            "recent": token_usage[-8:],
        },
        "toolCalls": {
            "total": sum(tool_counts.values()),
            "byTool": dict(tool_counts.most_common()),
            "sequence": tool_sequence,
            "repeated": repeated_tools,
            "largeResults": large_results,
        },
        "errors": errors,
        "inefficiencies": inefficiencies,
        "lastEvent": {
            "type": str((last_event or {}).get("type") or ""),
            "line": total_events,
            "timestamp": str((last_event or {}).get("timestamp") or ""),
        },
    }


def _candidate_summary(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": _relative(path),
        "sizeBytes": stat.st_size,
        "modifiedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _aggregate_inspections(inspections: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "logCount": len(inspections),
        "eventCount": sum(int(item.get("eventCount") or 0) for item in inspections),
        "llmCalls": sum(int(item.get("llmCalls") or 0) for item in inspections),
        "toolCalls": sum(int((item.get("toolCalls") or {}).get("total") or 0) for item in inspections),
        "inputTokens": sum(int(((item.get("tokenUsage") or {}).get("inputTokens") or 0)) for item in inspections),
        "outputTokens": sum(int(((item.get("tokenUsage") or {}).get("outputTokens") or 0)) for item in inspections),
        "errorCount": sum(len(item.get("errors") or []) for item in inspections),
        "inefficiencyCount": sum(len(item.get("inefficiencies") or []) for item in inspections),
    }


def _token_usage_from_event(event: dict[str, Any]) -> dict[str, int] | None:
    raw_input = event.get("input_tokens")
    raw_output = event.get("output_tokens")
    provider_usage = event.get("provider_usage") if isinstance(event.get("provider_usage"), dict) else {}
    if raw_input is None:
        raw_input = provider_usage.get("input_tokens") or provider_usage.get("prompt_tokens")
    if raw_output is None:
        raw_output = provider_usage.get("output_tokens") or provider_usage.get("completion_tokens")
    input_tokens = _bounded_int(raw_input, default=0, minimum=0, maximum=100_000_000)
    output_tokens = _bounded_int(raw_output, default=0, minimum=0, maximum=100_000_000)
    if not input_tokens and not output_tokens:
        return None
    return {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": input_tokens + output_tokens,
    }


def _tool_call_key(tool_name: str, args: dict[str, Any]) -> str:
    stable_args = json.dumps(args or {}, ensure_ascii=False, sort_keys=True)[:400]
    return f"{tool_name} {stable_args}".strip()


def _args_summary(args: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("file_path", "search_dir", "regex_pattern", "query", "log_path", "limit", "max_lines", "offset"):
        if key in args:
            value = args[key]
            summary[key] = str(value)[:240] if isinstance(value, str) else value
    return summary


def _event_looks_like_error(event: dict[str, Any]) -> bool:
    status = str(event.get("status") or "").strip().lower()
    level = str(event.get("level") or "").strip().lower()
    return status in {"error", "failed", "failure"} or level in {"error", "critical"}


def _error_summary(event: dict[str, Any], *, line_no: int) -> dict[str, Any]:
    text = str(
        event.get("message")
        or event.get("error")
        or event.get("content_preview")
        or event.get("tool_result_preview")
        or ""
    ).strip()
    return {
        "line": line_no,
        "type": str(event.get("type") or "").strip(),
        "status": str(event.get("status") or "").strip(),
        "level": str(event.get("level") or "").strip(),
        "preview": text[:500],
    }


def _detect_inefficiencies(
    *,
    event_counts: Counter[str],
    tool_counts: Counter[str],
    repeated_tools: list[dict[str, Any]],
    large_results: list[dict[str, Any]],
    total_input: int,
    total_output: int,
    llm_calls: int,
    errors: list[dict[str, Any]],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if repeated_tools:
        findings.append({
            "code": "repeated_tool_call",
            "message": "同一工具参数在单个日志中重复出现，可能存在重复读取或重复搜索。",
        })
    if large_results:
        findings.append({
            "code": "large_tool_result",
            "message": "存在大工具结果，建议先用日志摘要/统计工具收窄后再读取原文。",
        })
    if tool_counts.get("grep_search_tool", 0) >= 3:
        findings.append({
            "code": "broad_search_loop",
            "message": "grep_search_tool 调用较多，日志任务可能缺少先列候选文件和摘要统计的步骤。",
        })
    if total_input >= 50000 and total_output and total_input / max(total_output, 1) >= 25:
        findings.append({
            "code": "token_imbalance",
            "message": "输入 token 明显高于输出，可能把过多日志或工具结果塞进上下文。",
        })
    if llm_calls >= 4 and tool_counts.get("read_file_tool", 0) + tool_counts.get("grep_search_tool", 0) >= 6:
        findings.append({
            "code": "multi_llm_log_probe",
            "message": "多次 LLM 调用夹杂多次日志读/搜，建议先用 conversation_log_inspect_tool 汇总。",
        })
    if errors and event_counts.get("session_end", 0):
        findings.append({
            "code": "error_status_check_needed",
            "message": "日志同时出现错误和 session_end，应核对完成状态是否与错误状态一致。",
        })
    return findings[:MAX_RESULT_ITEMS]


def _session_summary(event: dict[str, Any] | None) -> dict[str, Any]:
    raw = event or {}
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    return {
        "sessionId": str(raw.get("session_id") or metadata.get("session_id") or "").strip(),
        "label": str(raw.get("session_label") or "").strip(),
        "agentMode": str(metadata.get("agent_mode") or "").strip(),
        "model": str(metadata.get("model") or "").strip(),
        "topic": str(metadata.get("conversation_topic") or "").strip(),
        "toolsCount": metadata.get("tools_count"),
    }


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except Exception:
        return str(path)


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
