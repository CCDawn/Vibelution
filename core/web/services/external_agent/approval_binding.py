"""Pure binding primitives for a managed task's native approval preview.

These helpers neither authorize a caller nor perform a resolution. The owner
must verify task ownership and live execution arguments, and perform the final
comparison and decision atomically under the native approval lock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from hmac import compare_digest
import json
import inspect
import math
import re
import threading
from typing import Any


class ApprovalBindingError(ValueError):
    """An approval cannot be represented or no longer matches its preview."""


_TASKS_LOCK = threading.RLock()
_TASKS: dict[str, tuple[str, str]] = {}


def is_external_session(conversation: Any) -> bool:
    metadata = conversation.get("metadata") if isinstance(conversation, dict) else None
    return isinstance(metadata, dict) and (
        metadata.get("source") == "external_agent_task" or "externalTaskId" in metadata
    )


def validate_external_session_submit(*, conversation: Any, session_id: str,
                                     message_source: str, message_metadata: Any) -> None:
    """Permit only the registered native task to submit its own bound turn."""
    marked = is_external_session(conversation)
    if not marked and message_source != "external_agent_task":
        return
    metadata = conversation.get("metadata") if isinstance(conversation, dict) else None
    message = message_metadata if isinstance(message_metadata, dict) else {}
    if not marked or not isinstance(metadata, dict) or metadata.get("source") != "external_agent_task":
        raise ApprovalBindingError("external session identity unavailable")
    task_id = metadata.get("externalTaskId")
    agent_id = conversation.get("agent_id") or conversation.get("agentId")
    profile = metadata.get("effectivePermissionProfile")
    if (message_source != "external_agent_task" or message.get("source") != "external_agent_task"
            or not isinstance(profile, str) or profile not in {"read_only", "workspace_write", "full_access"}
            or message.get("effectivePermissionProfile") != profile or message.get("taskId") != task_id
            or external_session_task(session_id=session_id, agent_id=agent_id) != task_id):
        raise ApprovalBindingError("external session identity unavailable")


def register_external_session(*, task_id: str, session_id: str, agent_id: str) -> None:
    """Register before submit starts; never overwrite a different task identity."""
    task_id, session_id, agent_id = map(_identity, (task_id, session_id, agent_id))
    with _TASKS_LOCK:
        previous = _TASKS.get(session_id)
        if previous is not None and previous != (task_id, agent_id):
            raise ApprovalBindingError("external session identity conflict")
        _TASKS[session_id] = (task_id, agent_id)


def external_session_task(*, session_id: str, agent_id: str) -> str:
    with _TASKS_LOCK:
        entry = _TASKS.get(session_id)
        if entry is None or entry[1] != agent_id:
            raise ApprovalBindingError("external session identity unavailable")
        return entry[0]


def registered_external_task(*, session_id: str, agent_id: str) -> str:
    """Recognize a registered session even when its current turn lacks a source tag."""
    with _TASKS_LOCK:
        entry = _TASKS.get(session_id)
        if entry is None:
            return ""
        if entry[1] != agent_id:
            raise ApprovalBindingError("external session agent changed")
        return entry[0]


def unregister_external_session(*, task_id: str, session_id: str, agent_id: str) -> None:
    with _TASKS_LOCK:
        if _TASKS.get(session_id) == (task_id, agent_id):
            del _TASKS[session_id]


def freeze_arguments(arguments: dict[str, Any]) -> str:
    if type(arguments) is not dict or "_cancel_checker" in arguments:
        raise ApprovalBindingError("external tool arguments are invalid")
    return _encode(arguments)


def freeze_execution_arguments(func: Any, arguments: dict[str, Any]) -> str:
    """Freeze actual tool keyword arguments, including representable defaults."""
    payload = json.loads(freeze_arguments(arguments))
    payload.pop("_internal_delegate", None)
    payload.pop("force", None)
    try:
        signature = inspect.signature(func)
        signature.bind(**payload)
        for name, parameter in signature.parameters.items():
            if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
                raise ApprovalBindingError("positional-only tool defaults cannot be frozen")
            if (name != "_cancel_checker" and name not in payload
                    and parameter.default is not inspect.Parameter.empty):
                payload[name] = parameter.default
        return _encode(payload)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ApprovalBindingError):
            raise
        raise ApprovalBindingError("tool call cannot be frozen") from exc


def _json_value(value: Any, ancestors: set[int]) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if math.isfinite(value):
            return
        raise ApprovalBindingError("non-finite approval argument")
    if type(value) not in (dict, list):
        raise ApprovalBindingError("approval arguments must be plain JSON values")
    marker = id(value)
    if marker in ancestors:
        raise ApprovalBindingError("cyclic approval arguments")
    ancestors.add(marker)
    try:
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise ApprovalBindingError("approval argument keys must be strings")
            for item in value.values():
                _json_value(item, ancestors)
        else:
            for item in value:
                _json_value(item, ancestors)
    finally:
        ancestors.remove(marker)


def _encode(value: Any) -> str:
    try:
        _json_value(value, set())
        # Preserve mapping order: Python tools receiving nested dicts or **kwargs
        # may observe iteration order, so sorting here can change execution.
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    except (OverflowError, RecursionError, TypeError, ValueError) as exc:
        if isinstance(exc, ApprovalBindingError):
            raise
        raise ApprovalBindingError("approval arguments cannot be frozen") from exc


def _identity(value: Any) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ApprovalBindingError("approval identity is missing or invalid")
    return value


@dataclass(frozen=True, slots=True)
class ApprovalBinding:
    task_id: str
    session_id: str
    agent_id: str
    request_id: str
    turn_id: str
    call_id: str
    tool_name: str
    decision_fingerprint: str
    config_revision: int
    config_hash: str
    approval: str
    risk: str
    permission_preset: str
    arguments_json: str = field(repr=False)
    execution_arguments_json: str = field(repr=False)

    @property
    def revision(self) -> str:
        # Includes all facts, not merely the Agent's configuration version.
        payload = {name: getattr(self, name) for name in self.__dataclass_fields__}
        return sha256(_encode(payload).encode("ascii")).hexdigest()

    def preview(self) -> dict[str, Any]:
        # Keep arguments as JSON text: JavaScript must not round large integers.
        return {
            "taskId": self.task_id, "sessionId": self.session_id, "agentId": self.agent_id,
            "requestId": self.request_id, "turnId": self.turn_id, "callId": self.call_id,
            "toolName": self.tool_name, "revision": self.revision,
            "approval": self.approval, "risk": self.risk, "permissionPreset": self.permission_preset,
            "decisionFingerprint": self.decision_fingerprint,
            "configRevision": self.config_revision, "configHash": self.config_hash,
            "argumentsJson": self.arguments_json,
            "executionArgumentsJson": self.execution_arguments_json,
        }


def freeze_approval(*, task_id: str, session_id: str, agent_id: str, request_id: str,
                    turn_id: str, call_id: str, tool_name: str, decision_fingerprint: str,
                    config_revision: int, config_hash: str, approval: str, risk: str,
                    permission_preset: str, arguments: dict[str, Any],
                    execution_arguments: dict[str, Any] | None = None) -> ApprovalBinding:
    if type(arguments) is not dict:
        raise ApprovalBindingError("approval arguments must be an object")
    if type(config_revision) is not int or config_revision < 1:
        raise ApprovalBindingError("approval config revision is invalid")
    values = [task_id, session_id, agent_id, request_id, turn_id, call_id, tool_name,
              decision_fingerprint, config_hash, approval, risk, permission_preset]
    values = [_identity(value) for value in values]
    if execution_arguments is None:
        execution_arguments = dict(arguments)
        execution_arguments.pop("_internal_delegate", None)
        execution_arguments.pop("force", None)
    if type(execution_arguments) is not dict:
        raise ApprovalBindingError("execution arguments must be an object")
    return ApprovalBinding(*values[:8], config_revision, *values[8:], _encode(arguments), _encode(execution_arguments))


def validate_approval(*, presented: ApprovalBinding, current: ApprovalBinding,
                      expected_revision: str, status: str, expired: bool) -> None:
    """Compare trusted snapshots; caller must also hold the lock through resolve.

    The revision is an integrity comparison, not a credential. Both snapshots
    must come from trusted server state, never from a client-provided preview.
    """
    if (type(presented) is not ApprovalBinding or type(current) is not ApprovalBinding
            or type(expected_revision) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected_revision)
            or type(expired) is not bool
            or status != "pending" or expired):
        raise ApprovalBindingError("approval changed or is unavailable")
    revision = presented.revision
    if not compare_digest(revision, expected_revision) or not compare_digest(revision, current.revision):
        raise ApprovalBindingError("approval changed or is unavailable")
