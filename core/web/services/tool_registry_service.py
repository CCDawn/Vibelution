"""Tool registry service for the local web workbench."""

from __future__ import annotations

import copy
import json
import os
import queue
import re
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.public_config import (
    CONFIG_PATH,
    build_effective_config,
    list_llm_model_options,
    load_public_config,
    save_public_config,
)
from config.settings import reload_config
from core.infrastructure.image_model_discovery import resolve_image_model, should_discover_image_model
from core.infrastructure.llm_utils import parse_tool_args
from core.orchestration.tool_lifecycle import ToolLifecycleBridge
from core.web.services.tool_catalog import bundle_ids_for_tool, list_tool_bundles, metadata_for_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
GENERATED_TOOLS_PATH = PROJECT_ROOT / "workspace" / "tool_registry" / "generated_tools.json"
TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SCHEMA_BLOCKED_KEYS = {"$ref", "oneOf", "anyOf", "allOf", "not", "patternProperties"}
MAX_DESCRIPTION_CHARS = 600
MAX_RESPONSE_TEMPLATE_CHARS = 2_000
TOOL_TEST_TIMEOUT_SECONDS = 3.0
MAIN_AGENT_SCOPE_ID = "main_agent"
SUBAGENT_SCOPE_IDS = ("subagent_default", "subagent_explorer", "subagent_worker")
AGENT_SCOPE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": MAIN_AGENT_SCOPE_ID,
        "label": "Main agent",
        "kind": "main",
        "isSubagent": False,
        "mode": "runtime",
        "description": "Primary agent runtime and management view.",
    },
    {
        "id": "subagent_default",
        "label": "Subagent default",
        "kind": "subagent",
        "isSubagent": True,
        "mode": "readonly",
        "description": "Default read-only subagent role.",
    },
    {
        "id": "subagent_explorer",
        "label": "Subagent explorer",
        "kind": "subagent",
        "isSubagent": True,
        "mode": "readonly",
        "description": "Explorer subagent role for bounded codebase inspection.",
    },
    {
        "id": "subagent_worker",
        "label": "Subagent worker",
        "kind": "subagent",
        "isSubagent": True,
        "mode": "readonly",
        "description": "Worker subagent role running under the current read-only subagent guard.",
    },
)
SAFE_BUILTIN_TEST_ARGS: dict[str, dict[str, Any]] = {
    "get_current_goal_tool": {},
    "get_core_context_tool": {},
    "get_evolution_fitness_tool": {"recent_limit": 3},
    "get_git_status_summary_tool": {"limit": 3},
    "get_recent_changes_tool": {"limit": 3},
    "conversation_log_inspect_tool": {"limit": 1, "max_events": 200},
    "get_self_model_tool": {},
    "task_list_tool": {},
}
SAFE_BUILTIN_TEST_REASONS: dict[str, str] = {
    "get_current_goal_tool": "Reads the current goal with no caller-supplied arguments.",
    "get_core_context_tool": "Reads the compact core context with no caller-supplied arguments.",
    "get_evolution_fitness_tool": "Reads a short self-evolution fitness summary with a fixed recent_limit.",
    "get_git_status_summary_tool": "Reads a short Git status summary with a fixed limit.",
    "get_recent_changes_tool": "Reads recent Git change summaries with a fixed limit.",
    "conversation_log_inspect_tool": "Reads a compact summary of recent conversation logs with fixed limits.",
    "get_self_model_tool": "Reads the persisted self model with no caller-supplied arguments.",
    "task_list_tool": "Reads the current task list with no caller-supplied arguments.",
}
IMAGE2_TOOL_NAME = "image2_generate_tool"
IMAGE2_FALLBACK_MODEL = "gpt-image-1.5"
IMAGE2_MODEL_DISCOVERY_TIMEOUT_SECONDS = 5
DEFAULT_PERMISSION_POLICY = {
    "requiresExplicitAllow": False,
    "reason": "",
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
    tools = [_with_agent_scope_states(item) for item in tools]
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
        "agentScopes": _agent_scope_summaries(tools),
        "toolBundles": list_tool_bundles(available_tool_names={str(item.get("name") or "") for item in tools}),
        "tools": tools,
    }


def get_image2_model_config() -> dict[str, Any]:
    """Return the image2 tool's model selector state without exposing secrets."""

    public_config = load_public_config()
    return _image2_model_config_payload(public_config)


def set_image2_default_model(model_ref: str) -> dict[str, Any]:
    """Persist the model library entry used by image2_generate_tool."""

    normalized_ref = str(model_ref or "").strip()
    public_config = load_public_config()
    available_model_refs = {
        str(item.get("model_id") or "").strip()
        for item in list_llm_model_options(public_config)
        if str(item.get("source") or "") == "model_library" and str(item.get("model_id") or "").strip()
    }
    if normalized_ref and normalized_ref not in available_model_refs:
        raise ToolRegistryError(f"Unknown image2 model reference: {normalized_ref}")

    updated = copy.deepcopy(public_config)
    tools_config = updated.setdefault("tools", {})
    if not isinstance(tools_config, dict):
        raise ToolRegistryError("tools config must be an object")
    image2_config = tools_config.setdefault("image2", {})
    if not isinstance(image2_config, dict):
        raise ToolRegistryError("tools.image2 config must be an object")
    previous_ref = str(image2_config.get("default_model_ref") or "").strip()
    image2_config["default_model_ref"] = normalized_ref

    build_effective_config(updated)
    save_public_config(updated)
    reload_config(str(CONFIG_PATH))
    _record_registry_event(
        "tool_registry.image2_model.updated",
        "image2 tool default model changed.",
        tool_id=IMAGE2_TOOL_NAME,
        status="configured" if normalized_ref else "fallback",
        outcome="succeeded",
        fields={
            "source": "tool_config",
            "previousModelRef": previous_ref,
            "modelRef": normalized_ref,
            "runtimeConfigReloaded": True,
        },
    )
    return _image2_model_config_payload(load_public_config())


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


def test_tool(
    tool_id: str,
    args: dict[str, Any] | None = None,
    agent_scope: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Run a controlled test call for one tool.

    Generated tools use their manifest response template. Built-ins only run when
    they are explicitly allow-listed with fixed safe arguments.
    """

    normalized = _normalize_tool_id(tool_id)
    scope_id = _normalize_agent_scope_id(agent_scope)
    scope_summary = _agent_scope_summary(scope_id)
    agent_summary = _tool_test_agent_summary(agent_id)
    builtin_names = _builtin_tool_names()
    if normalized in builtin_names:
        item = _with_agent_scope_states(next(tool for tool in _builtin_tool_items() if tool["name"] == normalized))
        scope_block = _agent_scope_test_block(item, scope_id)
        if scope_block:
            compatibility = _agent_compatibility_result(
                status="blocked",
                callable=False,
                message=scope_block,
                tool_name=normalized,
                args={},
            )
            _record_registry_event(
                "tool_registry.test.blocked",
                "Tool test was blocked by agent scope policy.",
                tool_id=normalized,
                status="blocked",
                outcome="blocked",
                level="warning",
                fields={
                    "source": "built_in",
                    "agentScope": scope_id,
                    "agentId": str(agent_summary.get("agentId") or ""),
                },
            )
            return {
                "toolId": normalized,
                "source": "built_in",
                "status": "blocked",
                "called": False,
                "callable": False,
                "message": scope_block,
                "resultPreview": "",
                "argsUsed": {},
                "testPolicy": item["testPolicy"],
                "agentCompatibility": compatibility,
                "agentScope": scope_summary,
                "agent": agent_summary,
                "timeout": _timeout_metadata(False, TOOL_TEST_TIMEOUT_SECONDS, 0),
            }
        test_args = dict(SAFE_BUILTIN_TEST_ARGS.get(normalized) or {})
        agent_policy_block = _agent_policy_test_block(normalized, test_args, agent_summary)
        if agent_policy_block:
            return _blocked_tool_test_response(
                normalized,
                source="built_in",
                message=agent_policy_block,
                args_used=test_args,
                test_policy=item["testPolicy"],
                agent_scope=scope_summary,
                agent=agent_summary,
                event_reason="agent_tool_policy",
            )
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
                "agentScope": scope_summary,
                "agent": agent_summary,
                "timeout": _timeout_metadata(False, TOOL_TEST_TIMEOUT_SECONDS, 0),
            }

        test_policy = _builtin_test_policy(normalized)
        return _run_tool_test_with_timeout(
            normalized,
            source="built_in",
            test_policy=test_policy,
            args_used=test_args,
            agent_scope=scope_summary,
            agent=agent_summary,
            run=lambda: _test_safe_builtin_tool(normalized, test_args, test_policy, agent_summary),
        )

    records = _load_generated_tools()
    _, record = _find_generated_record(records, normalized)
    item = _generated_tool_item(record, builtin_names=builtin_names)
    scoped_item = _with_agent_scope_states(item)
    scope_block = _agent_scope_test_block(scoped_item, scope_id)
    if scope_block:
        compatibility = _agent_compatibility_result(
            status="blocked",
            callable=False,
            message=scope_block,
            tool_name=normalized,
            args={},
        )
        return {
            "toolId": normalized,
            "source": "generated",
            "status": "blocked",
            "called": False,
            "callable": False,
            "message": scope_block,
            "resultPreview": "",
            "argsUsed": {},
            "testPolicy": scoped_item["testPolicy"],
            "agentCompatibility": compatibility,
            "agentScope": scope_summary,
            "agent": agent_summary,
            "timeout": _timeout_metadata(False, TOOL_TEST_TIMEOUT_SECONDS, 0),
        }
    if not item["validated"]:
        raise ToolRegistryError("Generated tool must be validated before testing")
    supplied_args = args if isinstance(args, dict) else {}
    agent_policy_block = _agent_policy_test_block(normalized, supplied_args, agent_summary)
    if agent_policy_block:
        return _blocked_tool_test_response(
            normalized,
            source="generated",
            message=agent_policy_block,
            args_used=supplied_args,
            test_policy=scoped_item["testPolicy"],
            agent_scope=scope_summary,
            agent=agent_summary,
            event_reason="agent_tool_policy",
        )
    response_template = str(item.get("responseTemplate") or "").strip()
    result_text = response_template or f"Generated tool `{normalized}` test completed."
    return _run_tool_test_with_timeout(
        normalized,
        source="generated",
        test_policy=item["testPolicy"],
        args_used=supplied_args,
        agent_scope=scope_summary,
        agent=agent_summary,
        run=lambda: _test_generated_tool_manifest(normalized, item, supplied_args, result_text),
    )


def _test_safe_builtin_tool(
    tool_name: str,
    test_args: dict[str, Any],
    test_policy: dict[str, Any],
    agent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from core.infrastructure.tool_executor import ToolExecutor
    from contextlib import nullcontext

    active_agent = agent if isinstance(agent, dict) else {}
    agent_id = str(active_agent.get("agentId") or "").strip()
    runtime_context: Any
    if agent_id:
        from core.web.services.agent_directory_service import active_agent_runtime

        runtime_context = active_agent_runtime(agent_id)
    else:
        runtime_context = nullcontext()

    executor = ToolExecutor()
    parsed_args = _agent_parse_tool_args(tool_name, test_args)
    with runtime_context:
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


def _tool_test_agent_summary(agent_id: str | None) -> dict[str, Any]:
    normalized = str(agent_id or "").strip()
    if not normalized:
        return {}
    try:
        from core.web.services.agent_directory_service import get_agent, resolve_tool_policy_for_agent

        agent = get_agent(normalized, include_archived=False)
        if not agent:
            raise ToolRegistryError(f"Agent not found: {normalized}")
        policy = resolve_tool_policy_for_agent(normalized)
        return {
            "agentId": str(agent.get("agentId") or normalized).strip(),
            "agentCode": str(agent.get("agentCode") or "").strip(),
            "displayName": str(agent.get("displayName") or "").strip(),
            "primaryMode": str(agent.get("primaryMode") or "").strip(),
            "roleKey": str(agent.get("roleKey") or "").strip(),
            "toolPolicyId": str(policy.get("policyId") or agent.get("toolPolicyId") or "").strip(),
        }
    except ToolRegistryError:
        raise
    except Exception as exc:
        raise ToolRegistryError(f"Unable to resolve Agent for tool test: {type(exc).__name__}") from exc


def _agent_policy_test_block(tool_name: str, args: dict[str, Any], agent: dict[str, Any] | None) -> str:
    active_agent = agent if isinstance(agent, dict) else {}
    agent_id = str(active_agent.get("agentId") or "").strip()
    if not agent_id:
        return ""
    try:
        from core.web.services.agent_directory_service import evaluate_tool_policy, resolve_tool_policy_for_agent

        decision = evaluate_tool_policy(
            tool_name,
            args if isinstance(args, dict) else {},
            policy=resolve_tool_policy_for_agent(agent_id),
            agent_id=agent_id,
        )
    except Exception as exc:
        return f"[工具策略提示] 当前工具测试无法验证该 Agent 的 ToolPolicy: {type(exc).__name__}。"
    if getattr(decision, "allowed", True):
        return ""
    return str(getattr(decision, "message", "") or "[工具策略提示] 当前工具测试被该 Agent 的 ToolPolicy 拦截。")


def _blocked_tool_test_response(
    tool_name: str,
    *,
    source: str,
    message: str,
    args_used: dict[str, Any],
    test_policy: dict[str, Any],
    agent_scope: dict[str, Any],
    agent: dict[str, Any],
    event_reason: str,
) -> dict[str, Any]:
    parsed_args = args_used if isinstance(args_used, dict) else {}
    compatibility = _agent_compatibility_result(
        status="blocked",
        callable=False,
        message=message,
        tool_name=tool_name,
        args=parsed_args,
    )
    _record_registry_event(
        "tool_registry.test.blocked",
        "Tool test was blocked before execution.",
        tool_id=tool_name,
        status="blocked",
        outcome="blocked",
        level="warning",
        fields={
            "source": source,
            "testPolicy": str(test_policy.get("mode") or ""),
            "agentScope": str(agent_scope.get("id") or MAIN_AGENT_SCOPE_ID),
            "agentId": str(agent.get("agentId") or ""),
            "reason": event_reason,
        },
    )
    return {
        "toolId": tool_name,
        "source": source,
        "status": "blocked",
        "called": False,
        "callable": False,
        "message": message,
        "resultPreview": "",
        "argsUsed": parsed_args,
        "testPolicy": test_policy,
        "agentCompatibility": compatibility,
        "agentScope": agent_scope,
        "agent": agent,
        "timeout": _timeout_metadata(False, TOOL_TEST_TIMEOUT_SECONDS, 0),
    }


def _run_tool_test_with_timeout(
    tool_name: str,
    *,
    source: str,
    test_policy: dict[str, Any],
    args_used: dict[str, Any],
    agent_scope: dict[str, Any],
    agent: dict[str, Any] | None = None,
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
                "agentId": str((agent or {}).get("agentId") or "") if isinstance(agent, dict) else "",
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
            "agentScope": agent_scope,
            "agent": agent if isinstance(agent, dict) else {},
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
                "agentId": str((agent or {}).get("agentId") or "") if isinstance(agent, dict) else "",
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
            "agentScope": agent_scope,
            "agent": agent if isinstance(agent, dict) else {},
            "timeout": _timeout_metadata(False, timeout_seconds, duration_ms),
        }

    duration_ms = int((time.monotonic() - started_at) * 1000)
    payload = value if isinstance(value, dict) else {}
    event_fields = payload.pop("_eventFields", {})
    payload["timeout"] = _timeout_metadata(False, timeout_seconds, duration_ms)
    payload["agentScope"] = agent_scope
    payload["agent"] = agent if isinstance(agent, dict) else {}
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
    agent_scope = payload.get("agentScope") if isinstance(payload.get("agentScope"), dict) else {}
    agent = payload.get("agent") if isinstance(payload.get("agent"), dict) else {}
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
            "agentScope": str(agent_scope.get("id") or MAIN_AGENT_SCOPE_ID),
            "agentId": str(agent.get("agentId") or ""),
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

    built_tools = create_key_tools()
    llm_visible_names = {str(tool.name) for tool in create_llm_facing_tools() if getattr(tool, "name", "")}
    available_tool_names = {str(getattr(tool, "name", "") or "").strip() for tool in built_tools if getattr(tool, "name", "")}
    items: list[dict[str, Any]] = []
    for tool in built_tools:
        name = str(getattr(tool, "name", "") or "").strip()
        if not name:
            continue
        items.append(
            {
                "id": name,
                "name": name,
                "description": _description_for_tool(tool),
                "source": "built_in",
                **metadata_for_tool(name, source="built_in"),
                "bundleIds": bundle_ids_for_tool(name, available_tool_names=available_tool_names),
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
                "permissionPolicy": _permission_policy_for_tool(name),
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
        **metadata_for_tool(name, source="generated"),
        "bundleIds": [],
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
        "permissionPolicy": dict(DEFAULT_PERMISSION_POLICY),
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


def _permission_policy_for_tool(tool_name: str) -> dict[str, Any]:
    normalized = str(tool_name or "").strip()
    try:
        from core.web.services.agent_directory_service import EXPLICIT_TOOL_POLICY_REQUIRED_TOOLS

        requires_explicit_allow = normalized in EXPLICIT_TOOL_POLICY_REQUIRED_TOOLS
    except Exception:
        requires_explicit_allow = False
    if not requires_explicit_allow:
        return dict(DEFAULT_PERMISSION_POLICY)
    return {
        "requiresExplicitAllow": True,
        "reason": "This tool is hidden and blocked until the selected Agent explicitly includes it in ToolPolicy.allowedTools.",
    }


def _normalize_agent_scope_id(agent_scope: object) -> str:
    scope_id = str(agent_scope or "").strip()
    if any(scope["id"] == scope_id for scope in AGENT_SCOPE_DEFINITIONS):
        return scope_id
    return MAIN_AGENT_SCOPE_ID


def _agent_scope_summary(scope_id: str, counts: dict[str, int] | None = None) -> dict[str, Any]:
    normalized = _normalize_agent_scope_id(scope_id)
    definition = next(scope for scope in AGENT_SCOPE_DEFINITIONS if scope["id"] == normalized)
    return {
        **definition,
        "counts": counts
        or {
            "total": 0,
            "visible": 0,
            "callable": 0,
            "blocked": 0,
        },
    }


def _agent_scope_summaries(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for definition in AGENT_SCOPE_DEFINITIONS:
        scope_id = str(definition["id"])
        states = [
            item.get("agentScopes", {}).get(scope_id, {})
            for item in tools
            if isinstance(item.get("agentScopes"), dict)
        ]
        visible_count = sum(1 for state in states if state.get("visible"))
        callable_count = sum(1 for state in states if state.get("callable"))
        blocked_count = sum(1 for state in states if state.get("visible") and not state.get("callable"))
        summaries.append(
            _agent_scope_summary(
                scope_id,
                counts={
                    "total": len(tools),
                    "visible": visible_count,
                    "callable": callable_count,
                    "blocked": blocked_count,
                },
            )
        )
    return summaries


def _with_agent_scope_states(item: dict[str, Any]) -> dict[str, Any]:
    scoped = dict(item)
    scoped["agentScopes"] = {
        str(definition["id"]): _agent_scope_state_for_tool(scoped, str(definition["id"]))
        for definition in AGENT_SCOPE_DEFINITIONS
    }
    return scoped


def _agent_scope_state_for_tool(item: dict[str, Any], scope_id: str) -> dict[str, Any]:
    normalized = _normalize_agent_scope_id(scope_id)
    test_policy = item.get("testPolicy") if isinstance(item.get("testPolicy"), dict) else {}
    llm_visible = bool(item.get("llmVisible"))
    runtime_active = bool(item.get("runtimeActive"))
    testable = bool(test_policy.get("callable"))

    if normalized == MAIN_AGENT_SCOPE_ID:
        callable_by_agent = runtime_active or (item.get("source") == "generated" and bool(item.get("validated")))
        block_reason = "" if callable_by_agent else str(item.get("blockReason") or item.get("validationError") or "")
        return {
            "visible": True,
            "callable": callable_by_agent,
            "llmVisible": llm_visible,
            "runtimeActive": runtime_active,
            "testable": testable,
            "blockReason": block_reason,
        }

    visible = llm_visible or (item.get("source") == "generated" and bool(item.get("validated")))
    block_reason = ""
    callable_by_agent = bool(visible)
    readonly_block = _readonly_subagent_block_reason(str(item.get("name") or item.get("id") or ""))
    if readonly_block:
        callable_by_agent = False
        block_reason = readonly_block
    elif not visible:
        callable_by_agent = False
        block_reason = "Tool is not visible to this agent scope."

    return {
        "visible": visible,
        "callable": callable_by_agent,
        "llmVisible": llm_visible,
        "runtimeActive": runtime_active,
        "testable": testable and callable_by_agent,
        "blockReason": block_reason,
    }


def _agent_scope_test_block(item: dict[str, Any], scope_id: str) -> str:
    normalized = _normalize_agent_scope_id(scope_id)
    state = item.get("agentScopes", {}).get(normalized, {}) if isinstance(item.get("agentScopes"), dict) else {}
    if state.get("callable"):
        return ""
    return str(state.get("blockReason") or "Tool is not callable in the selected agent scope.")


def _readonly_subagent_block_reason(tool_name: str) -> str:
    normalized = str(tool_name or "").strip()
    if not normalized:
        return ""
    try:
        from core.infrastructure.tool_executor import ToolExecutor

        blocked_tools = ToolExecutor._READ_ONLY_BLOCKED_TOOLS
    except Exception:
        blocked_tools = set()
    if normalized not in blocked_tools:
        return ""
    if normalized == "spawn_agent_tool":
        return "[只读子代理] 当前子 agent 运行在只读模式，禁止继续派发子 agent。"
    return f"[只读子代理] 当前子 agent 运行在只读模式，禁止调用 `{normalized}`。"


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


def _image2_model_config_payload(public_config: dict[str, Any]) -> dict[str, Any]:
    tools_config = public_config.get("tools", {})
    image2_config = tools_config.get("image2", {}) if isinstance(tools_config, dict) else {}
    default_model_ref = str(image2_config.get("default_model_ref") or "").strip() if isinstance(image2_config, dict) else ""
    models = [
        _image2_model_option_payload(
            option,
            discover=_should_discover_image2_option(option, default_model_ref=default_model_ref),
        )
        for option in list_llm_model_options(public_config)
    ]
    models = [model for model in models if model]
    selected = next((model for model in models if model["modelRef"] == default_model_ref), None)
    fallback = {
        "modelRef": "",
        "label": "Environment / built-in fallback",
        "model": IMAGE2_FALLBACK_MODEL,
        "configuredModel": IMAGE2_FALLBACK_MODEL,
        "resolvedModel": IMAGE2_FALLBACK_MODEL,
        "providerKind": "",
        "source": "fallback",
        "apiKeyEnv": "",
        "apiKeyConfigured": False,
        "discoveredModels": [],
        "modelDiscoveryStatus": "skipped",
        "modelDiscoveryError": "",
        "modelDiscoveryUrl": "",
    }
    return {
        "schemaVersion": 1,
        "toolId": IMAGE2_TOOL_NAME,
        "defaultModelRef": default_model_ref,
        "selectedModel": selected or fallback,
        "models": models,
        "fallbackModel": fallback,
    }


def _image2_model_option_payload(option: dict[str, Any], *, discover: bool = False) -> dict[str, Any]:
    model_ref = str(option.get("model_id") or "").strip()
    if not model_ref or str(option.get("source") or "") != "model_library":
        return {}
    configured_model = str(option.get("model") or "").strip()
    discovery = _discover_image2_option_model(option) if discover else {}
    resolved_model = str(discovery.get("model") or configured_model).strip() or configured_model
    discovery_payload = discovery.get("discovery") if isinstance(discovery.get("discovery"), dict) else {}
    return {
        "modelRef": model_ref,
        "label": str(option.get("label") or configured_model or model_ref).strip() or model_ref,
        "model": resolved_model,
        "configuredModel": configured_model,
        "resolvedModel": resolved_model,
        "providerKind": str(option.get("provider_kind") or "").strip(),
        "source": str(option.get("source") or "model_library").strip(),
        "apiKeyEnv": str(option.get("api_key_env") or "").strip(),
        "apiKeyConfigured": bool(option.get("api_key_configured")),
        "discoveredModels": list(discovery_payload.get("models") or []),
        "modelDiscoveryStatus": str(discovery_payload.get("status") or ("not_requested" if not discover else "")),
        "modelDiscoveryError": str(discovery_payload.get("error") or ""),
        "modelDiscoveryUrl": str(discovery_payload.get("url") or ""),
    }


def _should_discover_image2_option(option: dict[str, Any], *, default_model_ref: str) -> bool:
    model_ref = str(option.get("model_id") or "").strip()
    configured_model = str(option.get("model") or "").strip()
    label = str(option.get("label") or "").strip().lower()
    if model_ref == default_model_ref:
        return True
    if model_ref == "relay_image2":
        return True
    if "image2" in model_ref.lower() or "image2" in label:
        return True
    return should_discover_image_model(configured_model) and ("image" in model_ref.lower() or "image" in label)


def _discover_image2_option_model(option: dict[str, Any]) -> dict[str, Any]:
    provider = option.get("provider") if isinstance(option.get("provider"), dict) else {}
    api_key_env = str(option.get("api_key_env") or "").strip()
    provider_api_key_env = str(provider.get("api_key_env") or "").strip() if isinstance(provider, dict) else ""
    api_key = _read_registry_env_var(api_key_env) if api_key_env else ""
    if not api_key and provider_api_key_env:
        api_key = _read_registry_env_var(provider_api_key_env)
    extra_headers = provider.get("extra_headers") if isinstance(provider, dict) else {}
    headers = {str(key): str(value) for key, value in extra_headers.items()} if isinstance(extra_headers, dict) else {}
    return resolve_image_model(
        configured_model=str(option.get("model") or "").strip(),
        base_url=str(provider.get("base_url") or "").strip() if isinstance(provider, dict) else "",
        api_key=api_key,
        headers=headers,
        timeout=IMAGE2_MODEL_DISCOVERY_TIMEOUT_SECONDS,
    )


def _read_registry_env_var(name: str) -> str:
    token = str(name or "").strip()
    if not token:
        return ""
    try:
        from config.models import _read_env_var

        return str(_read_env_var(token) or "")
    except Exception:
        return str(os.environ.get(token) or "")


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
    return datetime.now(timezone.utc).isoformat()
