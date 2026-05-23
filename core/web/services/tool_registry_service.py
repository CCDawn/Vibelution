"""Tool registry service for the local web workbench."""

from __future__ import annotations

import json
import queue
import re
import time
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.infrastructure.llm_utils import parse_tool_args
from core.orchestration.tool_lifecycle import ToolLifecycleBridge


PROJECT_ROOT = Path(__file__).resolve().parents[3]
GENERATED_TOOLS_PATH = PROJECT_ROOT / "workspace" / "tool_registry" / "generated_tools.json"
TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SCHEMA_BLOCKED_KEYS = {"$ref", "oneOf", "anyOf", "allOf", "not", "patternProperties"}
MAX_DESCRIPTION_CHARS = 600
MAX_RESPONSE_TEMPLATE_CHARS = 2_000
TOOL_TEST_TIMEOUT_SECONDS = 3.0
SAFE_BUILTIN_TEST_ARGS: dict[str, dict[str, Any]] = {
    "get_current_goal_tool": {},
    "get_core_context_tool": {},
    "get_evolution_fitness_tool": {"recent_limit": 3},
    "get_git_status_summary_tool": {"limit": 3},
    "get_recent_changes_tool": {"limit": 3},
    "get_self_model_tool": {},
    "task_list_tool": {},
}
SAFE_BUILTIN_TEST_REASONS: dict[str, str] = {
    "get_current_goal_tool": "Reads the current goal with no caller-supplied arguments.",
    "get_core_context_tool": "Reads the compact core context with no caller-supplied arguments.",
    "get_evolution_fitness_tool": "Reads a short self-evolution fitness summary with a fixed recent_limit.",
    "get_git_status_summary_tool": "Reads a short Git status summary with a fixed limit.",
    "get_recent_changes_tool": "Reads recent Git change summaries with a fixed limit.",
    "get_self_model_tool": "Reads the persisted self model with no caller-supplied arguments.",
    "task_list_tool": "Reads the current task list with no caller-supplied arguments.",
}


class ToolRegistryError(ValueError):
    """Base error for tool registry operations."""


class ToolRegistryConflictError(ToolRegistryError):
    """Raised when a generated tool conflicts with an existing tool."""


class ToolRegistryPermissionError(ToolRegistryError):
    """Raised when an operation is blocked by registry policy."""


def get_tool_registry() -> dict[str, Any]:
    """Return built-in and generated tool registry state."""

    builtins = _builtin_tool_items()
    generated = _generated_tool_items(_load_generated_tools(), builtin_names={item["name"] for item in builtins})
    tools = [*builtins, *generated]
    counts = {
        "total": len(tools),
        "builtIn": len(builtins),
        "generated": len(generated),
        "llmVisible": sum(1 for item in tools if item.get("llmVisible")),
        "runtimeActive": sum(1 for item in tools if item.get("runtimeActive")),
        "enabledGenerated": sum(1 for item in generated if item.get("enabled")),
        "invalidGenerated": sum(1 for item in generated if item.get("status") == "invalid"),
    }
    return {
        "schemaVersion": 1,
        "mode": "safe_manifest_registry",
        "storagePath": _relative_project_path(GENERATED_TOOLS_PATH),
        "counts": counts,
        "tools": tools,
    }


def create_generated_tool(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a generated tool manifest after validation."""

    records = _load_generated_tools()
    builtin_names = _builtin_tool_names()
    candidate = _normalize_generated_payload(payload)
    _validate_generated_tool(candidate, records, builtin_names=builtin_names)

    now = _now()
    candidate.update(
        {
            "id": candidate["name"],
            "source": "generated",
            "status": "validated",
            "enabled": False,
            "validated": True,
            "validationError": "",
            "createdAt": now,
            "updatedAt": now,
        }
    )
    records.append(candidate)
    _save_generated_tools(records)
    _record_registry_event(
        "tool_registry.generated.created",
        "Generated tool manifest created.",
        tool_id=candidate["id"],
        status=candidate["status"],
        outcome="succeeded",
    )
    return _generated_tool_item(candidate, builtin_names=builtin_names)


def validate_generated_tool(tool_id: str) -> dict[str, Any]:
    """Revalidate one generated tool manifest."""

    records = _load_generated_tools()
    index, record = _find_generated_record(records, tool_id)
    builtin_names = _builtin_tool_names()
    try:
        _validate_generated_tool(record, records, builtin_names=builtin_names, current_index=index)
    except ToolRegistryError as exc:
        record["status"] = "invalid"
        record["validated"] = False
        record["enabled"] = False
        record["validationError"] = str(exc)
        record["updatedAt"] = _now()
        _save_generated_tools(records)
        _record_registry_event(
            "tool_registry.generated.validation_failed",
            "Generated tool validation failed.",
            tool_id=record["id"],
            status=record["status"],
            outcome="failed",
            level="warning",
            fields={"error": str(exc)},
        )
        return _generated_tool_item(record, builtin_names=builtin_names)

    record["status"] = "validated"
    record["validated"] = True
    record["validationError"] = ""
    record["updatedAt"] = _now()
    _save_generated_tools(records)
    _record_registry_event(
        "tool_registry.generated.validated",
        "Generated tool manifest validated.",
        tool_id=record["id"],
        status=record["status"],
        outcome="succeeded",
    )
    return _generated_tool_item(record, builtin_names=builtin_names)


def set_generated_tool_enabled(tool_id: str, enabled: bool) -> dict[str, Any]:
    """Enable or disable a generated tool manifest."""

    records = _load_generated_tools()
    _, record = _find_generated_record(records, tool_id)
    if not bool(record.get("validated")) or str(record.get("status") or "") != "validated":
        raise ToolRegistryError("Generated tool must pass validation before it can be enabled")
    record["enabled"] = bool(enabled)
    record["updatedAt"] = _now()
    _save_generated_tools(records)
    _record_registry_event(
        "tool_registry.generated.enabled_changed",
        "Generated tool enabled state changed.",
        tool_id=record["id"],
        status=record["status"],
        outcome="succeeded",
        fields={"enabled": bool(enabled)},
    )
    return _generated_tool_item(record, builtin_names=_builtin_tool_names())


def delete_generated_tool(tool_id: str) -> dict[str, Any]:
    """Delete one generated tool manifest."""

    records = _load_generated_tools()
    index, record = _find_generated_record(records, tool_id)
    deleted = records.pop(index)
    _save_generated_tools(records)
    _record_registry_event(
        "tool_registry.generated.deleted",
        "Generated tool manifest deleted.",
        tool_id=deleted["id"],
        status=str(deleted.get("status") or ""),
        outcome="succeeded",
    )
    return {
        "deleted": True,
        "toolId": deleted["id"],
        "summary": f"Deleted generated tool {deleted['id']}",
    }


def delete_tool(tool_id: str) -> dict[str, Any]:
    """Delete a tool by id, refusing protected built-ins."""

    normalized = _normalize_tool_id(tool_id)
    if normalized in _builtin_tool_names():
        raise ToolRegistryPermissionError("Built-in tools are protected and cannot be deleted")
    return delete_generated_tool(normalized)


def test_tool(tool_id: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a controlled test call for one tool.

    Generated tools use their manifest response template. Built-ins only run when
    they are explicitly allow-listed with fixed safe arguments.
    """

    normalized = _normalize_tool_id(tool_id)
    builtin_names = _builtin_tool_names()
    if normalized in builtin_names:
        if normalized not in SAFE_BUILTIN_TEST_ARGS:
            test_policy = _builtin_test_policy(normalized)
            compatibility = _agent_compatibility_result(
                status="blocked",
                callable=False,
                message="Built-in tool is not in the safe browser test allow-list.",
                tool_name=normalized,
                args={},
            )
            _record_registry_event(
                "tool_registry.test.blocked",
                "Built-in tool test was blocked by safe test policy.",
                tool_id=normalized,
                status="blocked",
                outcome="blocked",
                level="warning",
                fields={"source": "built_in", "testPolicy": test_policy["mode"]},
            )
            return {
                "toolId": normalized,
                "source": "built_in",
                "status": "blocked",
                "called": False,
                "callable": False,
                "message": "This built-in tool is not in the safe browser test allow-list.",
                "resultPreview": "",
                "argsUsed": {},
                "testPolicy": test_policy,
                "agentCompatibility": compatibility,
                "timeout": _timeout_metadata(False, TOOL_TEST_TIMEOUT_SECONDS, 0),
            }

        test_args = dict(SAFE_BUILTIN_TEST_ARGS[normalized])
        test_policy = _builtin_test_policy(normalized)
        return _run_tool_test_with_timeout(
            normalized,
            source="built_in",
            test_policy=test_policy,
            args_used=test_args,
            run=lambda: _test_safe_builtin_tool(normalized, test_args, test_policy),
        )

    records = _load_generated_tools()
    _, record = _find_generated_record(records, normalized)
    item = _generated_tool_item(record, builtin_names=builtin_names)
    if not item["validated"]:
        raise ToolRegistryError("Generated tool must be validated before testing")
    supplied_args = args if isinstance(args, dict) else {}
    response_template = str(item.get("responseTemplate") or "").strip()
    result_text = response_template or f"Generated tool `{normalized}` test completed."
    return _run_tool_test_with_timeout(
        normalized,
        source="generated",
        test_policy=item["testPolicy"],
        args_used=supplied_args,
        run=lambda: _test_generated_tool_manifest(normalized, item, supplied_args, result_text),
    )


def _test_safe_builtin_tool(tool_name: str, test_args: dict[str, Any], test_policy: dict[str, Any]) -> dict[str, Any]:
    from core.infrastructure.tool_executor import ToolExecutor

    executor = ToolExecutor()
    parsed_args = _agent_parse_tool_args(tool_name, test_args)
    result, action = executor.execute(tool_name, parsed_args)
    result_text = str(result or "")
    status = "failed" if _is_tool_failure_result(result_text) else "succeeded"
    compatibility = _build_tool_message_compatibility(
        tool_name,
        parsed_args,
        result_text,
        status=status,
        message="Agent-style tool call parsed and returned a tool message.",
    )
    return {
        "toolId": tool_name,
        "source": "built_in",
        "status": status,
        "called": True,
        "callable": True,
        "message": "Safe built-in tool test executed.",
        "resultPreview": result_text[:800],
        "argsUsed": parsed_args,
        "testPolicy": test_policy,
        "agentCompatibility": compatibility,
        "_eventFields": {
            "action": str(action or ""),
            "resultLength": len(result_text),
        },
    }


def _test_generated_tool_manifest(
    tool_name: str,
    item: dict[str, Any],
    supplied_args: dict[str, Any],
    result_text: str,
) -> dict[str, Any]:
    parsed_args = _agent_parse_tool_args(tool_name, supplied_args)
    args_error = _validate_args_for_schema(parsed_args, item.get("argsSchema") or {})
    if args_error:
        compatibility = _agent_compatibility_result(
            status="failed",
            callable=False,
            message=args_error,
            tool_name=tool_name,
            args=parsed_args,
        )
        return {
            "toolId": tool_name,
            "source": "generated",
            "status": "failed",
            "called": False,
            "callable": False,
            "message": args_error,
            "resultPreview": "",
            "argsUsed": parsed_args,
            "testPolicy": item["testPolicy"],
            "agentCompatibility": compatibility,
            "_eventFields": {
                "argCount": len(parsed_args),
                "error": args_error,
            },
        }

    compatibility = _build_tool_message_compatibility(
        tool_name,
        parsed_args,
        result_text,
        status="succeeded",
        message="Generated manifest is compatible with an agent-style tool call.",
    )
    return {
        "toolId": tool_name,
        "source": "generated",
        "status": "succeeded",
        "called": True,
        "callable": True,
        "message": "Generated tool manifest test executed without runtime code execution.",
        "resultPreview": result_text[:800],
        "argsUsed": parsed_args,
        "testPolicy": item["testPolicy"],
        "agentCompatibility": compatibility,
        "_eventFields": {
            "argCount": len(parsed_args),
        },
    }


def _run_tool_test_with_timeout(
    tool_name: str,
    *,
    source: str,
    test_policy: dict[str, Any],
    args_used: dict[str, Any],
    run: Any,
) -> dict[str, Any]:
    timeout_seconds = _effective_tool_test_timeout()
    started_at = time.monotonic()
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def _run() -> None:
        try:
            result_queue.put_nowait(("payload", run()))
        except Exception as exc:
            result_queue.put_nowait(("error", exc))

    worker = threading.Thread(target=_run, name=f"tool-registry-test-{tool_name}", daemon=True)
    worker.start()
    worker.join(timeout=timeout_seconds)

    if worker.is_alive():
        duration_ms = int((time.monotonic() - started_at) * 1000)
        compatibility = _agent_compatibility_result(
            status="timeout",
            callable=False,
            message=f"Tool test exceeded the {timeout_seconds:g}s hard timeout.",
            tool_name=tool_name,
            args=args_used,
        )
        _record_registry_event(
            "tool_registry.test.timeout",
            "Tool registry test hit the hard timeout.",
            tool_id=tool_name,
            status="timeout",
            outcome="timeout",
            level="error",
            fields={
                "source": source,
                "testPolicy": str(test_policy.get("mode") or ""),
                "durationMs": duration_ms,
                "timeoutSeconds": timeout_seconds,
            },
        )
        return {
            "toolId": tool_name,
            "source": source,
            "status": "timeout",
            "called": False,
            "callable": False,
            "message": compatibility["message"],
            "resultPreview": "",
            "argsUsed": args_used,
            "testPolicy": test_policy,
            "agentCompatibility": compatibility,
            "timeout": _timeout_metadata(True, timeout_seconds, duration_ms),
        }

    kind, value = result_queue.get_nowait()
    if kind == "error":
        exc = value
        duration_ms = int((time.monotonic() - started_at) * 1000)
        message = f"Tool test failed before completion: {type(exc).__name__}: {exc}"
        compatibility = _agent_compatibility_result(
            status="failed",
            callable=False,
            message=message,
            tool_name=tool_name,
            args=args_used,
        )
        _record_registry_event(
            "tool_registry.test.executed",
            "Tool registry test failed before completion.",
            tool_id=tool_name,
            status="failed",
            outcome="failed",
            level="error",
            fields={
                "source": source,
                "testPolicy": str(test_policy.get("mode") or ""),
                "durationMs": duration_ms,
                "errorType": type(exc).__name__,
            },
        )
        return {
            "toolId": tool_name,
            "source": source,
            "status": "failed",
            "called": False,
            "callable": False,
            "message": message,
            "resultPreview": "",
            "argsUsed": args_used,
            "testPolicy": test_policy,
            "agentCompatibility": compatibility,
            "timeout": _timeout_metadata(False, timeout_seconds, duration_ms),
        }

    duration_ms = int((time.monotonic() - started_at) * 1000)
    payload = value if isinstance(value, dict) else {}
    event_fields = payload.pop("_eventFields", {})
    payload["timeout"] = _timeout_metadata(False, timeout_seconds, duration_ms)
    _record_completed_tool_test(
        tool_name,
        source=source,
        test_policy=test_policy,
        payload=payload,
        duration_ms=duration_ms,
        event_fields=event_fields if isinstance(event_fields, dict) else {},
    )
    return payload


def _record_completed_tool_test(
    tool_name: str,
    *,
    source: str,
    test_policy: dict[str, Any],
    payload: dict[str, Any],
    duration_ms: int,
    event_fields: dict[str, Any],
) -> None:
    status = str(payload.get("status") or "failed")
    level = "warning" if status == "failed" else "info"
    message = "Tool registry test executed."
    if source == "built_in":
        message = "Safe built-in tool test executed."
    elif source == "generated" and status == "failed":
        message = "Generated tool manifest agent compatibility failed."
    elif source == "generated":
        message = "Generated tool manifest test executed."
    compatibility = payload.get("agentCompatibility") if isinstance(payload.get("agentCompatibility"), dict) else {}
    _record_registry_event(
        "tool_registry.test.executed",
        message,
        tool_id=tool_name,
        status=status,
        outcome=status,
        level=level,
        fields={
            "source": source,
            "testPolicy": str(test_policy.get("mode") or ""),
            "agentCompatibility": str(compatibility.get("status") or ""),
            "durationMs": duration_ms,
            **event_fields,
        },
    )


def _effective_tool_test_timeout() -> float:
    try:
        timeout = float(TOOL_TEST_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        timeout = 3.0
    return max(0.01, min(timeout, 10.0))


def _timeout_metadata(timed_out: bool, timeout_seconds: float, duration_ms: int) -> dict[str, Any]:
    return {
        "timedOut": bool(timed_out),
        "timeoutSeconds": timeout_seconds,
        "durationMs": max(0, int(duration_ms or 0)),
    }


def _agent_parse_tool_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    return parse_tool_args(json.dumps(args if isinstance(args, dict) else {}, ensure_ascii=False))


def _build_tool_message_compatibility(
    tool_name: str,
    args: dict[str, Any],
    result_text: str,
    *,
    status: str,
    message: str,
) -> dict[str, Any]:
    tool_call = _agent_tool_call(tool_name, args)
    messages: list[Any] = []
    try:
        ToolLifecycleBridge.handle_tool_result(tool_call, result_text, None, messages)
    except Exception as exc:
        return _agent_compatibility_result(
            status="failed",
            callable=False,
            message=f"Agent tool message conversion failed: {type(exc).__name__}: {exc}",
            tool_name=tool_name,
            args=args,
        )
    message_type = str(getattr(messages[-1], "type", "") or "") if messages else ""
    if message_type != "tool":
        return _agent_compatibility_result(
            status="failed",
            callable=False,
            message="Agent tool result did not produce a tool message.",
            tool_name=tool_name,
            args=args,
            message_type=message_type,
        )
    return _agent_compatibility_result(
        status=status,
        callable=status == "succeeded",
        message=message,
        tool_name=tool_name,
        args=args,
        message_type=message_type,
        result_preview=result_text[:320],
    )


def _agent_compatibility_result(
    *,
    status: str,
    callable: bool,
    message: str,
    tool_name: str,
    args: dict[str, Any],
    message_type: str = "",
    result_preview: str = "",
) -> dict[str, Any]:
    parsed_args = args if isinstance(args, dict) else {}
    return {
        "status": status,
        "callable": bool(callable),
        "message": message,
        "toolCall": _agent_tool_call(tool_name, parsed_args),
        "argsParsed": parsed_args,
        "messageType": message_type,
        "resultPreview": result_preview,
    }


def _agent_tool_call(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"tool_registry_test_{tool_name}",
        "name": tool_name,
        "args": args if isinstance(args, dict) else {},
    }


def _validate_args_for_schema(args: dict[str, Any], schema: dict[str, Any]) -> str:
    payload = args if isinstance(args, dict) else {}
    normalized = _normalize_schema(schema)
    required = normalized.get("required") if isinstance(normalized.get("required"), list) else []
    for key in required:
        key_text = str(key)
        if key_text not in payload:
            return f"Missing required tool argument: {key_text}"

    properties = normalized.get("properties") if isinstance(normalized.get("properties"), dict) else {}
    for key, property_schema in properties.items():
        if key not in payload or not isinstance(property_schema, dict):
            continue
        expected = str(property_schema.get("type") or "").strip()
        if expected and not _value_matches_schema_type(payload[key], expected):
            return f"Tool argument `{key}` must be {expected}"
    return ""


def _value_matches_schema_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "null":
        return value is None
    return True


def _is_tool_failure_result(result_text: str) -> bool:
    return result_text.startswith("[错误]") or result_text.startswith("[超时]") or result_text.startswith("[短路]")


def _builtin_tool_items() -> list[dict[str, Any]]:
    from tools.Key_Tools import create_key_tools, create_llm_facing_tools

    llm_visible_names = {str(tool.name) for tool in create_llm_facing_tools() if getattr(tool, "name", "")}
    items: list[dict[str, Any]] = []
    for tool in create_key_tools():
        name = str(getattr(tool, "name", "") or "").strip()
        if not name:
            continue
        items.append(
            {
                "id": name,
                "name": name,
                "description": _description_for_tool(tool),
                "source": "built_in",
                "status": "active",
                "enabled": True,
                "validated": True,
                "llmVisible": name in llm_visible_names,
                "runtimeActive": True,
                "deleteAllowed": False,
                "blockReason": "Built-in tools are protected by the agent runtime.",
                "validationError": "",
                "argsSchema": _args_schema_for_tool(tool),
                "testPolicy": _builtin_test_policy(name),
                "createdAt": "",
                "updatedAt": "",
            }
        )
    return sorted(items, key=lambda item: item["name"])


def _builtin_tool_names() -> set[str]:
    return {item["name"] for item in _builtin_tool_items()}


def _generated_tool_items(records: list[dict[str, Any]], *, builtin_names: set[str]) -> list[dict[str, Any]]:
    return sorted((_generated_tool_item(record, builtin_names=builtin_names) for record in records), key=lambda item: item["name"])


def _generated_tool_item(record: dict[str, Any], *, builtin_names: set[str]) -> dict[str, Any]:
    item = dict(record)
    name = str(item.get("name") or item.get("id") or "").strip()
    status = str(item.get("status") or ("validated" if item.get("validated") else "draft")).strip()
    validation_error = str(item.get("validationError") or "").strip()
    conflict = name in builtin_names
    if conflict:
        status = "invalid"
        validation_error = validation_error or "Generated tool conflicts with a built-in tool"
    return {
        "id": name,
        "name": name,
        "description": str(item.get("description") or "").strip(),
        "source": "generated",
        "status": status,
        "enabled": bool(item.get("enabled")) and status == "validated",
        "validated": bool(item.get("validated")) and status == "validated",
        "llmVisible": False,
        "runtimeActive": False,
        "deleteAllowed": True,
        "blockReason": "" if status == "validated" else validation_error,
        "validationError": validation_error,
        "argsSchema": _normalize_schema(item.get("argsSchema")),
        "responseTemplate": str(item.get("responseTemplate") or "").strip(),
        "testPolicy": _generated_test_policy(status == "validated"),
        "createdAt": str(item.get("createdAt") or ""),
        "updatedAt": str(item.get("updatedAt") or ""),
    }


def _builtin_test_policy(tool_name: str) -> dict[str, Any]:
    if tool_name in SAFE_BUILTIN_TEST_ARGS:
        return {
            "mode": "safe_builtin_fixture",
            "callable": True,
            "runtimeCall": True,
            "simulated": False,
            "reason": SAFE_BUILTIN_TEST_REASONS.get(tool_name, "Safe fixed-argument built-in test."),
            "argsPreview": dict(SAFE_BUILTIN_TEST_ARGS[tool_name]),
        }
    return {
        "mode": "blocked",
        "callable": False,
        "runtimeCall": False,
        "simulated": False,
        "reason": "Built-in tool is not in the safe browser test allow-list.",
        "argsPreview": {},
    }


def _generated_test_policy(validated: bool) -> dict[str, Any]:
    return {
        "mode": "generated_manifest_simulation",
        "callable": bool(validated),
        "runtimeCall": False,
        "simulated": True,
        "reason": "Generated tool tests validate the manifest response template without executing browser-submitted code.",
        "argsPreview": {},
    }


def _normalize_generated_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    name = _normalize_tool_id(raw.get("name") or raw.get("id") or "")
    description = str(raw.get("description") or "").strip()
    response_template = str(raw.get("responseTemplate") or raw.get("response_template") or "").strip()
    if not response_template:
        response_template = f"Generated tool `{name}` is registered for controlled future runtime integration."
    return {
        "id": name,
        "name": name,
        "description": description,
        "argsSchema": _normalize_schema(raw.get("argsSchema") or raw.get("args_schema")),
        "responseTemplate": response_template,
    }


def _validate_generated_tool(
    candidate: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    builtin_names: set[str],
    current_index: int | None = None,
) -> None:
    name = _normalize_tool_id(candidate.get("name") or candidate.get("id") or "")
    if not TOOL_NAME_PATTERN.fullmatch(name):
        raise ToolRegistryError("Tool name must start with a lowercase letter and use only lowercase letters, numbers, and underscores")
    if name in builtin_names:
        raise ToolRegistryConflictError("Generated tool cannot override a built-in tool")
    for index, record in enumerate(records):
        if current_index is not None and index == current_index:
            continue
        if _normalize_tool_id(record.get("name") or record.get("id") or "") == name:
            raise ToolRegistryConflictError("Generated tool name already exists")

    description = str(candidate.get("description") or "").strip()
    if not description:
        raise ToolRegistryError("Generated tool description is required")
    if len(description) > MAX_DESCRIPTION_CHARS:
        raise ToolRegistryError(f"Generated tool description must be {MAX_DESCRIPTION_CHARS} characters or fewer")

    response_template = str(candidate.get("responseTemplate") or "").strip()
    if len(response_template) > MAX_RESPONSE_TEMPLATE_CHARS:
        raise ToolRegistryError(f"Generated tool response template must be {MAX_RESPONSE_TEMPLATE_CHARS} characters or fewer")

    schema = _normalize_schema(candidate.get("argsSchema"))
    if schema.get("type") != "object":
        raise ToolRegistryError("Generated tool argsSchema.type must be object")
    if not isinstance(schema.get("properties"), dict):
        raise ToolRegistryError("Generated tool argsSchema.properties must be an object")
    blocked = _find_blocked_schema_keys(schema)
    if blocked:
        raise ToolRegistryError(f"Generated tool argsSchema contains unsupported keyword: {blocked[0]}")


def _find_generated_record(records: list[dict[str, Any]], tool_id: str) -> tuple[int, dict[str, Any]]:
    normalized = _normalize_tool_id(tool_id)
    for index, record in enumerate(records):
        if _normalize_tool_id(record.get("id") or record.get("name") or "") == normalized:
            return index, record
    raise FileNotFoundError(f"Generated tool not found: {normalized}")


def _load_generated_tools() -> list[dict[str, Any]]:
    try:
        payload = json.loads(GENERATED_TOOLS_PATH.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []
    rows = payload.get("tools") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    return [dict(item) for item in rows if isinstance(item, dict)]


def _save_generated_tools(records: list[dict[str, Any]]) -> None:
    GENERATED_TOOLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "updatedAt": _now(),
        "tools": records,
    }
    GENERATED_TOOLS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_tool_id(value: object) -> str:
    return str(value or "").strip().replace("-", "_").lower()


def _normalize_schema(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"type": "object", "properties": {}}
    schema = dict(value)
    schema["type"] = str(schema.get("type") or "object").strip() or "object"
    properties = schema.get("properties")
    schema["properties"] = properties if isinstance(properties, dict) else {}
    required = schema.get("required")
    if required is not None and not isinstance(required, list):
        schema["required"] = []
    return schema


def _find_blocked_schema_keys(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if key_text in SCHEMA_BLOCKED_KEYS:
                found.append(key_text)
            found.extend(_find_blocked_schema_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_find_blocked_schema_keys(item))
    return found


def _description_for_tool(tool: object) -> str:
    description = str(getattr(tool, "description", "") or "").strip()
    return description[:MAX_DESCRIPTION_CHARS]


def _args_schema_for_tool(tool: object) -> dict[str, Any]:
    args = getattr(tool, "args", None)
    if isinstance(args, dict):
        return {"type": "object", "properties": args}
    return {"type": "object", "properties": {}}


def _record_registry_event(
    event_code: str,
    message: str,
    *,
    tool_id: str,
    status: str,
    outcome: str,
    level: str = "info",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "tool_registry",
            "registry",
            event_code,
            message=message,
            level=level,
            outcome=outcome,
            fields={
                "toolId": tool_id,
                "source": "generated",
                "status": status,
                **(fields or {}),
            },
        )
    except Exception:
        return


def _relative_project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _now() -> str:
    return datetime.now(UTC).isoformat()
