# -*- coding: utf-8 -*-
"""Read-only conversation log inspection helpers for Agent tooling."""

from __future__ import annotations

import json
import hashlib
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
MAX_SCENE_CONVERSATION_FILES = 20
MAX_SCENE_EVENT_FILES = 24
MAX_CORRELATION_SUMMARIES = 12
MAX_AGENT_TRACE_EVIDENCE_REFS = 16
AGENT_TRACE_STALL_THRESHOLD_MS = 20_000

IDENTITY_ALIASES = {
    "sessionId": ("sessionId", "runtimeSessionId", "runtime_session_id", "session_id"),
    "turnId": ("turn_id", "turnId"),
    "invocationId": ("invocation_id", "invocationId"),
    "submissionId": (
        "submission_id",
        "submissionId",
        "client_submission_id",
        "clientSubmissionId",
    ),
}
BOUNDARY_IDENTITY_KEYS = ("turnId", "invocationId", "submissionId")
TERMINAL_SUCCESS = {"success", "succeeded", "completed", "complete", "ok"}
TERMINAL_ERROR = {"error", "failed", "failure"}
TERMINAL_STOP = {"cancelled", "canceled", "stopped", "aborted", "terminated"}


def conversation_log_inspect_tool(
    query: str = "",
    log_path: str = "",
    limit: int = 5,
    max_events: int = 8000,
    session_id: str = "",
    turn_id: str = "",
    invocation_id: str = "",
    submission_id: str = "",
) -> str:
    """Inspect conversation JSONL logs and return compact diagnostics."""

    try:
        payload = inspect_conversation_logs(
            query=query,
            log_path=log_path,
            limit=limit,
            max_events=max_events,
            session_id=session_id,
            turn_id=turn_id,
            invocation_id=invocation_id,
            submission_id=submission_id,
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
    session_id: str = "",
    turn_id: str = "",
    invocation_id: str = "",
    submission_id: str = "",
) -> dict[str, Any]:
    normalized_limit = _bounded_int(limit, default=5, minimum=1, maximum=20)
    normalized_max_events = _bounded_int(max_events, default=8000, minimum=200, maximum=50000)
    identity_filters = {
        "sessionId": str(session_id or "").strip(),
        "turnId": str(turn_id or "").strip(),
        "invocationId": str(invocation_id or "").strip(),
        "submissionId": str(submission_id or "").strip(),
    }
    normalized_query = str(query or "").strip()
    candidates = _select_candidate_logs(
        query=normalized_query,
        log_path=log_path,
        limit=normalized_limit,
        identity_filters=identity_filters,
    )
    has_locator = bool(normalized_query or any(identity_filters.values()))
    if str(log_path or "").strip():
        selection_status = "explicit"
    elif has_locator:
        selection_status = "matched" if candidates else "not_found"
    else:
        selection_status = "latest" if candidates else "not_found"
    inspections = [
        _inspect_target(
            path,
            max_events=normalized_max_events,
            identity_filters=identity_filters,
        )
        for path in candidates
    ]
    return {
        "status": "ok",
        "tool": "conversation_log_inspect_tool",
        "inspectedAt": datetime.now(timezone.utc).isoformat(),
        "query": _safe_text(normalized_query, limit=120),
        "logPath": str(log_path or "").strip(),
        "identityFilters": identity_filters,
        "selectionStatus": selection_status,
        "fallbackUsed": False,
        "candidateCount": len(candidates),
        "candidates": [
            _candidate_summary(path)
            for path in candidates
        ],
        "inspections": inspections,
        "summary": _aggregate_inspections(inspections),
        "usageGuidance": [
            "Use this tool before grep/read_file when reviewing conversation JSONL or a runtime scene package.",
            "Read raw log lines only after this summary identifies a narrow path and line range.",
        ],
    }


def _select_candidate_logs(
    *,
    query: str,
    log_path: str,
    limit: int,
    identity_filters: dict[str, str],
) -> list[Path]:
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
    active_filters = {key: value for key, value in identity_filters.items() if value}
    if not normalized_query and not active_filters:
        return logs[:limit]

    matched: list[Path] = []
    for path in logs:
        if normalized_query and not _log_matches_query(path, normalized_query):
            continue
        if active_filters and not _log_matches_identity_filters(path, active_filters):
            continue
        matched.append(path)
        if len(matched) >= limit:
            break
    return matched


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
    rel = path.relative_to(root).as_posix()
    if path.is_dir():
        if not rel.startswith("logs/runtime_scenes/"):
            raise ValueError(
                "conversation_log_inspect_tool only reads log_info/ JSONL files or logs/runtime_scenes/ packages."
            )
        if not (path / "manifest.json").is_file() and not (path / "timeline.jsonl").is_file():
            raise ValueError("Runtime scene package must contain manifest.json or timeline.jsonl.")
        return path
    if path.suffix.lower() != ".jsonl":
        raise ValueError("conversation_log_inspect_tool only reads .jsonl logs or runtime scene packages.")
    if not (rel.startswith("log_info/") or rel.startswith("logs/runtime_scenes/")):
        raise ValueError("conversation_log_inspect_tool only reads log_info/ or logs/runtime_scenes/ JSONL files.")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Log file not found: {rel}")
    return path


def _inspect_target(
    path: Path,
    *,
    max_events: int,
    identity_filters: dict[str, str],
) -> dict[str, Any]:
    if path.is_dir():
        return _inspect_scene_package(
            path,
            max_events=max_events,
            identity_filters=identity_filters,
        )
    return _inspect_log(
        path,
        max_events=max_events,
        identity_filters=identity_filters,
    )


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


def _log_matches_identity_filters(path: Path, identity_filters: dict[str, str]) -> bool:
    matched = {key: False for key in identity_filters}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, line in enumerate(handle, start=1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = None
                if isinstance(event, dict):
                    identities = _event_identities(event)
                    for key, expected in identity_filters.items():
                        if identities.get(key) == expected:
                            matched[key] = True
                    if all(matched.values()):
                        return True
                if line_no >= MAX_CANDIDATE_SCAN_LINES:
                    break
    except Exception:
        return False
    return False


def _inspect_log(
    path: Path,
    *,
    max_events: int,
    identity_filters: dict[str, str] | None = None,
) -> dict[str, Any]:
    records, malformed_lines, truncated = _read_jsonl_records(path, max_events=max_events)
    return _inspect_records(
        path=path,
        records=records,
        malformed_lines=malformed_lines,
        truncated=truncated,
        identity_filters=identity_filters or {},
        kind="jsonl",
        source_files=[path],
    )


def _inspect_scene_package(
    path: Path,
    *,
    max_events: int,
    identity_filters: dict[str, str],
) -> dict[str, Any]:
    source_files: list[Path] = []
    timeline = path / "timeline.jsonl"
    if timeline.is_file():
        source_files.append(timeline)
    conversations = path / "conversations"
    if conversations.is_dir():
        conversation_files = sorted(
            conversations.glob("*.jsonl"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )[:MAX_SCENE_CONVERSATION_FILES]
        source_files.extend(conversation_files)
    events = path / "events"
    if events.is_dir():
        source_files.extend(
            sorted(
                events.glob("*.jsonl"),
                key=lambda item: item.stat().st_mtime,
            )[:MAX_SCENE_EVENT_FILES]
        )

    records: list[dict[str, Any]] = []
    malformed_lines = 0
    truncated = False
    for source in source_files:
        remaining = max_events - len(records)
        if remaining <= 0:
            truncated = True
            break
        source_records, malformed, source_truncated = _read_jsonl_records(
            source,
            max_events=remaining,
        )
        records.extend(source_records)
        malformed_lines += malformed
        truncated = truncated or source_truncated

    inspection = _inspect_records(
        path=path,
        records=records,
        malformed_lines=malformed_lines,
        truncated=truncated,
        identity_filters=identity_filters,
        kind="runtime_scene",
        source_files=source_files,
    )
    inspection["scene"] = _scene_manifest_summary(path / "manifest.json")
    return inspection


def _read_jsonl_records(path: Path, *, max_events: int) -> tuple[list[dict[str, Any]], int, bool]:
    records: list[dict[str, Any]] = []
    malformed_lines = 0
    truncated = False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            if len(records) >= max_events:
                truncated = True
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
            records.append({
                "event": event,
                "line": line_no,
                "source": _relative(path),
            })
    return records, malformed_lines, truncated


def _inspect_records(
    *,
    path: Path,
    records: list[dict[str, Any]],
    malformed_lines: int,
    truncated: bool,
    identity_filters: dict[str, str],
    kind: str,
    source_files: list[Path],
) -> dict[str, Any]:
    event_counts: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    tool_call_keys: Counter[str] = Counter()
    tool_sequence: list[dict[str, Any]] = []
    large_results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    token_usage: list[dict[str, Any]] = []
    authorization_events: list[dict[str, Any]] = []
    llm_calls = 0
    total_input = 0
    total_output = 0
    total_events = len(records)
    first_event: dict[str, Any] | None = None
    last_event: dict[str, Any] | None = None

    for record in records:
        event = record["event"]
        line_no = int(record["line"])
        source = str(record["source"])
        last_event = event
        if first_event is None:
            first_event = event
        event_type = str(event.get("type") or event.get("event_code") or "unknown").strip() or "unknown"
        event_counts[event_type] += 1

        if event_type == "llm_request":
            llm_calls += 1
            usage = _token_usage_from_event(event)
            if usage:
                total_input += usage["inputTokens"]
                total_output += usage["outputTokens"]
                token_usage.append({"source": source, "line": line_no, **usage})
        elif event_type in {"token_usage", "llm_response"}:
            usage = _token_usage_from_event(event)
            if usage:
                total_input += usage["inputTokens"]
                total_output += usage["outputTokens"]
                token_usage.append({"source": source, "line": line_no, **usage})

        if event_type == "tool_call":
            tool_name = str(event.get("tool_name") or event.get("toolName") or "").strip() or "unknown"
            tool_counts[tool_name] += 1
            args = event.get("tool_args") if isinstance(event.get("tool_args"), dict) else {}
            key = _tool_call_key(tool_name, args)
            tool_call_keys[key] += 1
            result_length = _bounded_int(event.get("tool_result_length"), default=0, minimum=0, maximum=10_000_000)
            sequence_item = {
                "source": source,
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
                errors.append(_error_summary(event, line_no=line_no, source=source))

        if event_type.startswith("tool.authorization.") and len(authorization_events) < MAX_RESULT_ITEMS:
            fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
            authorization_events.append(
                {
                    "source": source,
                    "line": line_no,
                    "eventCode": event_type,
                    "outcome": str(event.get("outcome") or "").strip(),
                    "agentId": _safe_text(str(fields.get("agentId") or ""), limit=120),
                    "turnId": _safe_text(str(fields.get("turnId") or ""), limit=120),
                    "policyId": _safe_text(str(fields.get("policyId") or ""), limit=120),
                    "policyVersion": _bounded_int(fields.get("policyVersion"), default=0, minimum=0, maximum=1_000_000),
                    "registryVersion": _bounded_int(fields.get("registryVersion"), default=0, minimum=0, maximum=1_000_000),
                    "decisionFingerprint": _safe_text(str(fields.get("decisionFingerprint") or ""), limit=64),
                    "visibleCount": _bounded_int(fields.get("visibleCount"), default=0, minimum=0, maximum=10_000),
                    "executableCount": _bounded_int(fields.get("executableCount"), default=0, minimum=0, maximum=10_000),
                    "parity": bool(fields.get("parity")),
                    "legacyVisibleCount": _bounded_int(fields.get("legacyVisibleCount"), default=0, minimum=0, maximum=10_000),
                    "shadowVisibleCount": _bounded_int(fields.get("shadowVisibleCount"), default=0, minimum=0, maximum=10_000),
                    "shadowOnlyCount": _bounded_int(fields.get("shadowOnlyCount"), default=0, minimum=0, maximum=10_000),
                    "legacyOnlyCount": _bounded_int(fields.get("legacyOnlyCount"), default=0, minimum=0, maximum=10_000),
                    "denyCodeCounts": dict(fields.get("denyCodeCounts") or {}) if isinstance(fields.get("denyCodeCounts"), dict) else {},
                    "errorType": _safe_text(str(fields.get("errorType") or ""), limit=120),
                    "durationMs": _bounded_int(fields.get("durationMs"), default=0, minimum=0, maximum=600_000),
                }
            )

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
    stat = path.stat()
    size_bytes = (
        sum(item.stat().st_size for item in source_files if item.is_file())
        if path.is_dir()
        else stat.st_size
    )
    correlation = _correlate_boundaries(records, identity_filters=identity_filters)
    return {
        "path": _relative(path),
        "kind": kind,
        "sizeBytes": size_bytes,
        "modifiedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "sourceFiles": [_candidate_summary(item) for item in source_files],
        "session": _session_summary(first_event),
        "eventCount": total_events,
        "truncatedAtMaxEvents": truncated,
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
        "toolAuthorization": {
            "eventCount": len(authorization_events),
            "parityMismatchCount": sum(1 for item in authorization_events if item["eventCode"].endswith("shadow_decision") and not item["parity"]),
            "failureCount": sum(1 for item in authorization_events if item["eventCode"].endswith("shadow_failed") or item["eventCode"].endswith(".failed")),
            "latest": authorization_events[-1] if authorization_events else None,
            "recent": authorization_events[-8:],
        },
        "inefficiencies": inefficiencies,
        "correlation": correlation,
        "agentTrace": _agent_turn_trace(records, correlation=correlation),
        "lastEvent": {
            "type": str((last_event or {}).get("type") or ""),
            "line": int(records[-1]["line"]) if records else 0,
            "timestamp": str((last_event or {}).get("timestamp") or (last_event or {}).get("ts") or ""),
        },
    }


def _candidate_summary(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": _relative(path),
        "kind": "runtime_scene" if path.is_dir() else "jsonl",
        "sizeBytes": stat.st_size if path.is_file() else 0,
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
        "toolAuthorizationEventCount": sum(
            int((item.get("toolAuthorization") or {}).get("eventCount") or 0) for item in inspections
        ),
        "toolAuthorizationMismatchCount": sum(
            int((item.get("toolAuthorization") or {}).get("parityMismatchCount") or 0) for item in inspections
        ),
        "toolAuthorizationFailureCount": sum(
            int((item.get("toolAuthorization") or {}).get("failureCount") or 0) for item in inspections
        ),
    }


def _scene_manifest_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"manifestPresent": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {"manifestPresent": True, "manifestReadable": False}
    if not isinstance(payload, dict):
        return {"manifestPresent": True, "manifestReadable": False}
    package = payload.get("package") if isinstance(payload.get("package"), dict) else {}
    return {
        "manifestPresent": True,
        "manifestReadable": True,
        "runtimeSceneId": str(payload.get("runtime_scene_id") or package.get("package_id") or "").strip(),
        "status": str(payload.get("status") or "").strip(),
        "result": str(payload.get("result") or "").strip(),
        "startedAt": str(payload.get("started_at") or package.get("started_at") or "").strip(),
        "endedAt": str(payload.get("ended_at") or package.get("ended_at") or "").strip(),
        "stopReasonSummary": _text_fingerprint(str(payload.get("stop_reason") or "")),
    }


def _correlate_boundaries(
    records: list[dict[str, Any]],
    *,
    identity_filters: dict[str, str],
) -> dict[str, Any]:
    active_filters = {key: value for key, value in identity_filters.items() if value}
    boundary_records: list[dict[str, Any]] = []
    matched_record_count = 0
    for order, record in enumerate(records):
        identities = _event_identities(record["event"])
        if active_filters and all(identities.get(key) == value for key, value in active_filters.items()):
            matched_record_count += 1
        if not any(identities.get(key) for key in BOUNDARY_IDENTITY_KEYS):
            continue
        boundary_records.append({**record, "order": order, "identities": identities})

    parents = list(range(len(boundary_records)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    owners: dict[tuple[str, str], int] = {}
    for index, record in enumerate(boundary_records):
        for key in BOUNDARY_IDENTITY_KEYS:
            value = record["identities"].get(key)
            if not value:
                continue
            token = (key, value)
            if token in owners:
                union(index, owners[token])
            else:
                owners[token] = index

    grouped: dict[int, list[dict[str, Any]]] = {}
    for index, record in enumerate(boundary_records):
        grouped.setdefault(find(index), []).append(record)

    boundaries = [_boundary_summary(items) for items in grouped.values()]
    if active_filters:
        boundaries = [
            boundary
            for boundary in boundaries
            if all(boundary["identity"].get(key) == value for key, value in active_filters.items())
        ]
    boundaries.sort(key=lambda item: int(item["lastOrder"]), reverse=True)

    terminal = [item for item in boundaries if item["terminal"]]
    errors = [item for item in boundaries if item["state"] == "error"]
    successful = [item for item in boundaries if item["state"] == "success"]
    unterminated = [item for item in boundaries if not item["terminal"]]
    current_unterminated = unterminated[0] if unterminated else None
    diagnostics: list[dict[str, str]] = []
    if not active_filters:
        match_status = "not_filtered"
    elif boundaries:
        match_status = "matched"
    elif matched_record_count:
        match_status = "identity_match_without_boundary"
        diagnostics.append({
            "code": "identity_match_without_boundary",
            "message": "Identity matched log records, but no turn, invocation, or submission boundary was found.",
        })
    else:
        match_status = "not_found"
    return {
        "filters": active_filters,
        "matchStatus": match_status,
        "matchedRecordCount": matched_record_count,
        "diagnostics": diagnostics,
        "boundaryCount": len(boundaries),
        "recentSuccessfulBoundary": _public_boundary(successful[0]) if successful else None,
        "currentUnterminatedBoundary": _public_boundary(current_unterminated) if current_unterminated else None,
        "terminalSummary": [_public_boundary(item) for item in terminal[:MAX_CORRELATION_SUMMARIES]],
        "errorSummary": [_public_boundary(item) for item in errors[:MAX_CORRELATION_SUMMARIES]],
        "missingIdentity": list((current_unterminated or {}).get("missingIdentity") or []),
        "truncated": len(boundaries) > MAX_CORRELATION_SUMMARIES,
    }


def _event_identities(event: dict[str, Any]) -> dict[str, str]:
    containers = [event]
    for key in ("fields", "metadata", "identity"):
        value = event.get(key)
        if isinstance(value, dict):
            containers.append(value)
    identities: dict[str, str] = {}
    for canonical, aliases in IDENTITY_ALIASES.items():
        lookups = (
            ((container, alias) for alias in aliases for container in containers)
            if canonical == "sessionId"
            else ((container, alias) for container in containers for alias in aliases)
        )
        for container, alias in lookups:
                value = container.get(alias)
                if value is not None and str(value).strip():
                    identities[canonical] = str(value).strip()[:240]
                    break
    return identities


def _boundary_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    records.sort(key=lambda item: int(item["order"]))
    identity: dict[str, str] = {}
    terminal_records: list[tuple[str, dict[str, Any]]] = []
    error_records: list[dict[str, Any]] = []
    for record in records:
        identity.update(record["identities"])
        terminal_state = _terminal_state(record["event"])
        if terminal_state:
            terminal_records.append((terminal_state, record))
        if terminal_state == "error" or _event_looks_like_error(record["event"]):
            error_records.append(record)
    state = terminal_records[-1][0] if terminal_records else "open"
    terminal_record = terminal_records[-1][1] if terminal_records else None
    error_record = error_records[-1] if error_records else None
    return {
        "identity": identity,
        "missingIdentity": [key for key in IDENTITY_ALIASES if not identity.get(key)],
        "state": state,
        "terminal": bool(terminal_records),
        "eventCount": len(records),
        "firstEvent": _safe_event_summary(records[0]),
        "lastEvent": _safe_event_summary(records[-1]),
        "terminalEvent": _safe_event_summary(terminal_record) if terminal_record else None,
        "errorType": _error_type((error_record or {}).get("event") or {}),
        "errorEvent": _safe_event_summary(error_record) if error_record else None,
        "lastOrder": int(records[-1]["order"]),
    }


def _public_boundary(boundary: dict[str, Any] | None) -> dict[str, Any] | None:
    if boundary is None:
        return None
    return {key: value for key, value in boundary.items() if key != "lastOrder"}


def _agent_turn_trace(records: list[dict[str, Any]], *, correlation: dict[str, Any]) -> dict[str, Any]:
    boundary = (
        (correlation.get("terminalSummary") or [None])[0]
        or correlation.get("currentUnterminatedBoundary")
        or correlation.get("recentSuccessfulBoundary")
    )
    identity = dict((boundary or {}).get("identity") or {})
    turn_id = str(identity.get("turnId") or "").strip()
    session_id = str(identity.get("sessionId") or "").strip()
    invocation_id = str(identity.get("invocationId") or "").strip()
    trace_id = str(identity.get("traceId") or turn_id or invocation_id or "").strip()
    if not trace_id:
        return {
            "status": "not_found",
            "traceId": "",
            "currentStage": "unknown",
            "durationMs": 0,
            "llm": {"attemptCount": 0, "eventCount": 0, "retryCount": 0},
            "tools": {
                "callCount": 0,
                "names": [],
                "resultBinding": {
                    "observed": False,
                    "boundCount": 0,
                    "unboundCallCount": 0,
                    "unknownCallIdCount": 0,
                },
            },
            "delivery": {"publishedDeltaCount": 0, "appliedDeltaCount": 0, "snapshotApplied": False},
            "stall": {"detected": False, "idleMs": 0, "lastEventCode": ""},
            "anomalies": ["identity_not_found"],
            "evidenceRefs": [],
        }

    matched = [
        record
        for record in records
        if _agent_trace_record_matches(
            _event_identities(record["event"]),
            turn_id=turn_id,
            session_id=session_id,
            invocation_id=invocation_id,
        )
    ]
    matched = _agent_trace_deduplicate(matched)
    event_codes = [_agent_trace_event_code(record["event"]) for record in matched]
    state = str((boundary or {}).get("state") or "open").strip().lower()
    status = {
        "success": "completed",
        "error": "failed",
        "stopped": "stopped",
        "open": "running",
    }.get(state, "running")
    llm_codes = [code for code in event_codes if code.startswith("llm.") or code.startswith("llm_")]
    invocation_ids = {
        str(_event_identities(record["event"]).get("invocationId") or "").strip()
        for record, code in zip(matched, event_codes)
        if code in llm_codes and str(_event_identities(record["event"]).get("invocationId") or "").strip()
    }
    attempt_starts = sum(1 for code in llm_codes if code.endswith(("attempt_started", ".stream.started", ".invoke.started")))
    tool_records = [
        record
        for record, code in zip(matched, event_codes)
        if code.endswith(".tool_call") or code == "tool_call"
    ]
    tool_names = sorted({
        _agent_trace_tool_name(record["event"])
        for record in tool_records
        if _agent_trace_tool_name(record["event"])
    })
    binding_records = [
        record
        for record, code in zip(matched, event_codes)
        if code == "tool.result.bound"
    ]
    tool_call_ids = {
        str(
            ((record["event"].get("fields") or {}) if isinstance(record["event"].get("fields"), dict) else {}).get("toolCallId")
            or ""
        ).strip()
        for record in tool_records
    }
    tool_call_ids.discard("")
    bound_call_ids = {
        str(
            ((record["event"].get("fields") or {}) if isinstance(record["event"].get("fields"), dict) else {}).get("toolCallId")
            or ""
        ).strip()
        for record in binding_records
        if bool(
            ((record["event"].get("fields") or {}) if isinstance(record["event"].get("fields"), dict) else {}).get("resultBound")
        )
    }
    bound_call_ids.discard("")
    binding_observed = bool(binding_records)
    unbound_call_ids = tool_call_ids - bound_call_ids if binding_observed else set()
    result_binding = {
        "observed": binding_observed,
        "boundCount": len(bound_call_ids),
        "unboundCallCount": len(unbound_call_ids),
        "unknownCallIdCount": max(0, len(tool_records) - len(tool_call_ids)),
    }
    published_delta_count = sum(code == "session.assistant_delta.published" for code in event_codes)
    applied_delta_count = sum(code == "browser.session_stream.assistant_delta_applied" for code in event_codes)
    snapshot_applied = any(code == "browser.session_stream.snapshot_applied" for code in event_codes)
    anomalies: list[str] = []
    if status == "running":
        anomalies.append("open_turn")
    if any(_event_looks_like_error(record["event"]) for record in matched):
        anomalies.append("runtime_error")
    if status == "completed" and published_delta_count and not applied_delta_count:
        anomalies.append("delivery_evidence_missing")
    if binding_observed and unbound_call_ids:
        anomalies.append("tool_result_binding_missing")
    missing_identity = [
        key
        for key in ((boundary or {}).get("missingIdentity") or [])
        if key in {"sessionId", "turnId"}
    ]
    if missing_identity:
        anomalies.append("identity_gap")
    stall = _agent_trace_stall(matched, status=status)
    if stall["detected"]:
        anomalies.append("stall")

    return {
        "status": status,
        "traceId": trace_id,
        "sessionId": session_id,
        "turnId": turn_id,
        "currentStage": _agent_trace_stage(status, event_codes),
        "durationMs": _agent_trace_duration_ms(matched),
        "llm": {
            "attemptCount": max(len(invocation_ids), attempt_starts),
            "eventCount": len(llm_codes),
            "retryCount": sum("retry" in code for code in llm_codes),
        },
        "tools": {
            "callCount": len(tool_records),
            "names": tool_names,
            "resultBinding": result_binding,
        },
        "delivery": {
            "publishedDeltaCount": published_delta_count,
            "appliedDeltaCount": applied_delta_count,
            "snapshotApplied": snapshot_applied,
        },
        "stall": stall,
        "anomalies": anomalies,
        "evidenceRefs": [
            {
                "source": str(record["source"]),
                "line": int(record["line"]),
                "eventCode": _agent_trace_event_code(record["event"]),
            }
            for record in matched[:MAX_AGENT_TRACE_EVIDENCE_REFS]
        ],
    }


def _agent_trace_record_matches(
    identities: dict[str, str],
    *,
    turn_id: str,
    session_id: str,
    invocation_id: str,
) -> bool:
    if turn_id:
        return identities.get("turnId") == turn_id
    if invocation_id:
        return identities.get("invocationId") == invocation_id
    return bool(session_id and identities.get("sessionId") == session_id)


def _agent_trace_deduplicate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    for record in sorted(records, key=_agent_trace_dedup_order):
        key = _agent_trace_dedup_key(record)
        if key not in unique:
            unique[key] = record
    return sorted(unique.values(), key=_agent_trace_record_order)


def _agent_trace_dedup_order(record: dict[str, Any]) -> tuple[datetime, int, int]:
    source = str(record["source"]).replace("\\", "/")
    source_priority = 0 if "/events/" in source else 1 if "/conversations/" in source else 2
    timestamp, line = _agent_trace_record_order(record)
    return timestamp, source_priority, line


def _agent_trace_dedup_key(record: dict[str, Any]) -> tuple[str, ...]:
    event = record["event"]
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    code = _agent_trace_event_code(event)
    identities = _event_identities(event)
    stable_sequence = next(
        (
            str(value).strip()
            for value in (
                fields.get("ledgerSeq"),
                fields.get("deltaSeq"),
                fields.get("toolCallId"),
                fields.get("messageId"),
                event.get("seq"),
                event.get("event_id"),
            )
            if value is not None and str(value).strip()
        ),
        "",
    )
    if "delta" in code and not stable_sequence:
        return (code, str(record["source"]), str(record["line"]))
    timestamp = str(event.get("ts") or event.get("timestamp") or "").strip()
    return (
        code,
        timestamp,
        identities.get("sessionId", ""),
        identities.get("turnId", ""),
        identities.get("invocationId", ""),
        identities.get("submissionId", ""),
        stable_sequence,
        str(event.get("outcome") or event.get("status") or "").strip(),
    )


def _agent_trace_event_code(event: dict[str, Any]) -> str:
    return str(event.get("event_code") or event.get("type") or "unknown").strip().lower()


def _agent_trace_record_order(record: dict[str, Any]) -> tuple[datetime, int]:
    event = record["event"]
    timestamp = str(event.get("ts") or event.get("timestamp") or "").strip()
    if timestamp.endswith("Z"):
        timestamp = f"{timestamp[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        parsed = datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), int(record["line"])


def _agent_trace_duration_ms(records: list[dict[str, Any]]) -> int:
    if len(records) < 2:
        return 0
    first, last = _agent_trace_record_order(records[0])[0], _agent_trace_record_order(records[-1])[0]
    return max(0, int((last - first).total_seconds() * 1000))


def _agent_trace_stall(records: list[dict[str, Any]], *, status: str) -> dict[str, Any]:
    if status != "running" or not records:
        return {"detected": False, "idleMs": 0, "lastEventCode": ""}
    last_record = records[-1]
    last_at = _agent_trace_record_order(last_record)[0]
    idle_ms = max(0, int((datetime.now(timezone.utc) - last_at).total_seconds() * 1000))
    return {
        "detected": idle_ms >= AGENT_TRACE_STALL_THRESHOLD_MS,
        "idleMs": idle_ms,
        "lastEventCode": _agent_trace_event_code(last_record["event"]),
    }


def _agent_trace_stage(status: str, event_codes: list[str]) -> str:
    if status in {"completed", "failed", "stopped"}:
        return status
    last_code = event_codes[-1] if event_codes else ""
    if "tool" in last_code:
        return "executing_tools"
    if "stream" in last_code or "delta" in last_code:
        return "streaming"
    if "llm" in last_code or "model" in last_code:
        return "waiting_for_model"
    if "context" in last_code:
        return "preparing_context"
    return "accepted"


def _agent_trace_tool_name(event: dict[str, Any]) -> str:
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    return str(event.get("tool_name") or event.get("toolName") or fields.get("toolName") or "").strip()[:160]


def _terminal_state(event: dict[str, Any]) -> str:
    status = str(event.get("status") or "").strip().lower()
    outcome = str(event.get("outcome") or "").strip().lower()
    event_code = str(event.get("event_code") or event.get("type") or "").strip().lower()
    values = {status, outcome}
    if values & TERMINAL_ERROR or event_code.endswith((".failed", ".failure", ".error")):
        return "error"
    if values & TERMINAL_STOP or event_code.endswith((".cancelled", ".canceled", ".stopped", ".aborted", ".terminated")):
        return "stopped"
    if values & TERMINAL_SUCCESS or event_code.endswith((".succeeded", ".completed")):
        return "success"
    return ""


def _safe_event_summary(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None
    event = record["event"]
    return {
        "source": str(record["source"]),
        "line": int(record["line"]),
        "timestamp": str(event.get("ts") or event.get("timestamp") or "")[:80],
        "eventCode": str(event.get("event_code") or event.get("type") or "")[:160],
        "status": str(event.get("status") or "")[:80],
        "outcome": str(event.get("outcome") or "")[:80],
        "level": str(event.get("level") or "")[:40],
    }


def _error_type(event: dict[str, Any]) -> str:
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    return str(
        event.get("error_type")
        or event.get("errorType")
        or fields.get("error_type")
        or fields.get("errorType")
        or ""
    ).strip()[:160]


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
    stable_args = json.dumps(args or {}, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(stable_args.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{tool_name} args_sha256:{digest}".strip()


def _args_summary(args: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"keys": sorted(str(key) for key in args)[:20]}
    for key in ("limit", "max_lines", "offset"):
        if key in args and isinstance(args[key], (int, float, bool)):
            summary[key] = args[key]
    for key in ("file_path", "search_dir", "log_path"):
        if key in args and isinstance(args[key], str):
            summary[f"{key}Length"] = len(args[key])
    return summary


def _event_looks_like_error(event: dict[str, Any]) -> bool:
    status = str(event.get("status") or "").strip().lower()
    level = str(event.get("level") or "").strip().lower()
    return status in {"error", "failed", "failure"} or level in {"error", "critical"}


def _error_summary(event: dict[str, Any], *, line_no: int, source: str = "") -> dict[str, Any]:
    text = str(
        event.get("message")
        or event.get("error")
        or event.get("content_preview")
        or event.get("tool_result_preview")
        or ""
    ).strip()
    detail = _text_fingerprint(text)
    return {
        "source": source,
        "line": line_no,
        "type": str(event.get("type") or "").strip(),
        "eventCode": str(event.get("event_code") or event.get("type") or "").strip()[:160],
        "status": str(event.get("status") or "").strip(),
        "level": str(event.get("level") or "").strip(),
        "errorType": _error_type(event),
        "detailLength": detail["length"],
        "detailSha256": detail["sha256"],
    }


def _text_fingerprint(value: str) -> dict[str, Any]:
    text = str(value or "")
    return {
        "length": len(text),
        "sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
    }


def _safe_text(value: str, *, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.search(r"(?i)(api[_-]?key|authorization|bearer|password|secret|access[_-]?token|refresh[_-]?token)\s*[:=]", text):
        return "[REDACTED]"
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", text)
    return text[:limit]


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
        "sessionId": _event_identities(raw).get("sessionId", ""),
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
