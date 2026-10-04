"""Bounded memory telemetry with a non-recursive failure signal.

The existing runtime scene is the only event store. Logging failure never
changes a memory operation's result or retries the operation.
"""

from __future__ import annotations

import builtins
import inspect
import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter
from typing import Any, Callable

from core.logging.pipeline_metrics import pipeline_metrics
from core.logging.trace_context import merge_current_trace_fields

_logger = logging.getLogger(__name__)
_MEMORY_TOOL_CALL_ID: ContextVar[str] = ContextVar("memory_tool_call_id", default="")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:/-]{1,180}\Z")
_CODE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,95}\Z")
_ARGUMENT_IDS = {
    "knowledge_base_id": "knowledgeBaseId", "knowledge_item_id": "knowledgeItemId",
    "source_artifact_id": "sourceArtifactId", "inbox_source_id": "inboxSourceId",
    "proposal_id": "proposalId", "episode_id": "episodeId", "owner_id": "ownerId",
}
_RESULT_IDS = ("episodeId", "successorEpisodeId", "knowledgeItemId", "proposalId", "sourceArtifactId")
_RESULT_REASON_CODES = frozenset({
    "agent_runtime_missing", "agent_identity_required", "episode_id_required", "invalid_json",
    "personal_memory_disabled", "private_memory_disabled", "knowledge_access_denied",
    "knowledge_base_not_in_memory_policy", "user_content_space_not_in_memory_policy",
    *[name for name, value in vars(builtins).items()
      if isinstance(value, type) and issubclass(value, Exception)],
})


def _identifier(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    return text if _IDENTIFIER.fullmatch(text) else ""


def _code(value: Any, default: str = "operation_failed") -> str:
    text = value.strip() if isinstance(value, str) else ""
    return text if _CODE.fullmatch(text) else default


def _runtime_fields(runtime: dict[str, Any]) -> dict[str, str]:
    fields = {key: _identifier(runtime.get(key)) for key in (
        "agentId", "sessionId", "turnId", "toolCallId", "requestId",
    )}
    fields["turnId"] = fields["turnId"] or _identifier(runtime.get("runId"))
    return {key: value for key, value in fields.items() if value}


@contextmanager
def memory_tool_call_scope(tool_call_id: str):
    """Pass the native call identity through the executor's copied context."""
    token = _MEMORY_TOOL_CALL_ID.set(_identifier(tool_call_id))
    try:
        yield
    finally:
        _MEMORY_TOOL_CALL_ID.reset(token)


def _result_reason(payload: dict[str, Any], default: str) -> str:
    # Some legacy tools put str(exception) in "error". Never copy that text.
    reason = payload.get("error")
    return reason if isinstance(reason, str) and reason in _RESULT_REASON_CODES else default


def _write_failure(event_code: str, component: str, fields: dict[str, Any], error: Exception) -> None:
    # Metrics do not call a logger, so this signal survives a broken log sink.
    try:
        pipeline_metrics.note_drop(priority="operational", reason="writer_failed")
    except Exception:
        pass
    try:
        memory_id = next((_identifier(fields.get(key)) for key in (
            "episodeId", "eventId", "knowledgeItemId", "proposalId", "sourceArtifactId",
        ) if _identifier(fields.get(key))), "")
        _logger.warning(
            "memory.event.write_failed eventCode=%s component=%s agentId=%s sessionId=%s "
            "turnId=%s toolCallId=%s knowledgeBaseId=%s memoryId=%s errorType=%s",
            _code(event_code), _code(component), _identifier(fields.get("agentId") or fields.get("actorAgentId")),
            _identifier(fields.get("sessionId")), _identifier(fields.get("turnId")),
            _identifier(fields.get("toolCallId")), _identifier(fields.get("knowledgeBaseId")),
            memory_id, type(error).__name__,
        )
    except Exception:
        # A failing warning handler must not change the business result either.
        pass


def record_memory_event(
    component: str, phase: str, event_code: str, *, fields: dict[str, Any],
    level: str = "info", outcome: str = "observed", lifecycle: bool = True,
    writer: Callable[..., Any] | None = None,
    refresh_package_if_due: bool = True,
) -> None:
    event_fields = fields
    try:
        event_fields = merge_current_trace_fields(fields)
        call_id = _MEMORY_TOOL_CALL_ID.get()
        if call_id:
            event_fields["toolCallId"] = call_id
        if writer is None:
            from core.web.services.runtime_scene_service import record_runtime_scene_event

            writer = record_runtime_scene_event
        options = {} if refresh_package_if_due else {"refresh_package_if_due": False}
        writer(component, phase, event_code, message=event_code, level=level,
               outcome=outcome, fields=event_fields, lifecycle=lifecycle, **options)
    except Exception as error:
        _write_failure(event_code, component, event_fields, error)


def audit_memory_tool(component: str, *, record_success: bool = False):
    """Record terminal decisions omitted by early returns, with no argument dump."""
    def decorate(function: Callable[..., str]):
        signature = inspect.signature(function)

        @wraps(function)
        def invoke(*args: Any, **kwargs: Any) -> str:
            started = perf_counter()
            fields: dict[str, Any] = {"toolName": function.__name__}
            try:
                from core.web.services.agent_directory_service import current_agent_runtime

                fields.update(_runtime_fields(current_agent_runtime()))
            except Exception:
                pass
            try:
                bound = signature.bind_partial(*args, **kwargs)
                for argument, field in _ARGUMENT_IDS.items():
                    value = _identifier(bound.arguments.get(argument))
                    if value:
                        fields[field] = value
            except TypeError:
                pass

            def record(outcome: str, reason: str = "", payload: dict[str, Any] | None = None):
                metadata = {**fields, "durationMs": round(max(0.0, perf_counter() - started) * 1000, 3)}
                if reason:
                    metadata["reasonCode"] = _code(reason)
                for key in _RESULT_IDS:
                    value = _identifier((payload or {}).get(key))
                    if value:
                        metadata[key] = value
                record_memory_event(component, "tool", f"memory.tool.execution.{outcome}",
                                    fields=metadata, outcome=outcome,
                                    # Business outcomes are audit facts. Warning would
                                    # synchronously rebuild the full scene diagnosis.
                                    level="info",
                                    refresh_package_if_due=False)

            try:
                result = function(*args, **kwargs)
            except Exception as error:
                record("failed", type(error).__name__)
                raise
            try:
                payload = json.loads(result)
            except (TypeError, ValueError):
                record("failed", "invalid_tool_response")
                return result
            if isinstance(payload, dict):
                status = payload.get("status") if isinstance(payload.get("status"), str) else ""
                if status == "blocked":
                    record("blocked", _result_reason(payload, "policy_blocked"), payload)
                elif status in {"failed", "error"} or payload.get("ok") is False:
                    record("failed", _result_reason(payload, "operation_failed"), payload)
                elif record_success:
                    record("succeeded", payload=payload)
            return result

        return invoke

    return decorate
