"""Codex-style per-call tool approval coordination for live session turns."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import Event, RLock
import time
from typing import Any, Callable, Literal, Mapping
from uuid import uuid4


ToolApprovalPolicy = Literal["untrusted", "on_request", "never"]
ToolApprovalDecision = Literal["accept", "acceptForSession", "decline", "cancel"]

DEFAULT_APPROVAL_POLICY: ToolApprovalPolicy = "on_request"
DEFAULT_APPROVAL_TIMEOUT_SECONDS = 300.0
MAX_RETAINED_REQUESTS = 256
_VALID_POLICIES = {"untrusted", "on_request", "never"}
_VALID_DECISIONS = {"accept", "acceptForSession", "decline", "cancel"}
_PATCH_TARGET_PATTERN = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File: (?P<path>.+?)\s*$",
    re.MULTILINE,
)
_SANDBOX_CONTAINED_TOOLS = {"cli_tool", "exec_command", "write_stdin"}
_WORKSPACE_PATH_TOOLS = {"apply_diff_edit_tool", "apply_patch_tool", "write_file_tool"}


class ToolApprovalError(ValueError):
    """Base error for invalid or stale approval operations."""


class ToolApprovalNotFoundError(ToolApprovalError):
    """Raised when an approval request does not exist in the named session."""


class ToolApprovalConflictError(ToolApprovalError):
    """Raised when a request has already resolved or its identity is stale."""


@dataclass(slots=True)
class _ApprovalRequest:
    request_id: str
    session_id: str
    turn_id: str
    agent_id: str
    call_id: str
    tool_name: str
    approval: str
    risk: str
    arguments_hash: str
    argument_summary: dict[str, Any]
    decision_fingerprint: str
    created_at: str
    expires_at: float
    status: str = "pending"
    decision: str = ""
    resolved_at: str = ""
    event: Event = field(default_factory=Event, repr=False)

    def public_projection(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "sessionId": self.session_id,
            "turnId": self.turn_id,
            "agentId": self.agent_id,
            "callId": self.call_id,
            "toolName": self.tool_name,
            "approval": self.approval,
            "risk": self.risk,
            "argumentsHash": self.arguments_hash,
            "argumentSummary": dict(self.argument_summary),
            "decisionFingerprint": self.decision_fingerprint,
            "availableDecisions": ["accept", "acceptForSession", "decline", "cancel"],
            "createdAt": self.created_at,
            "status": self.status,
            "decision": self.decision or None,
            "resolvedAt": self.resolved_at or None,
        }


@dataclass(frozen=True, slots=True)
class ToolApprovalOutcome:
    allowed: bool
    code: str
    message: str = ""
    request_id: str = ""


_LOCK = RLock()
_REQUESTS: dict[str, _ApprovalRequest] = {}
_REQUEST_IDS_BY_CALL: dict[tuple[str, str, str], str] = {}
_SESSION_POLICIES: dict[str, ToolApprovalPolicy] = {}
_SESSION_GRANTS: set[tuple[str, str, str, str]] = set()


def get_session_tool_approval_policy(session_id: str) -> dict[str, str]:
    normalized_session = _required_identity(session_id, "sessionId")
    with _LOCK:
        policy = _SESSION_POLICIES.get(normalized_session, DEFAULT_APPROVAL_POLICY)
    return {"sessionId": normalized_session, "policy": policy}


def set_session_tool_approval_policy(session_id: str, policy: str) -> dict[str, str]:
    normalized_session = _required_identity(session_id, "sessionId")
    normalized_policy = str(policy or "").strip()
    if normalized_policy not in _VALID_POLICIES:
        raise ToolApprovalError(f"unsupported tool approval policy: {normalized_policy or '<empty>'}")
    with _LOCK:
        _SESSION_POLICIES[normalized_session] = normalized_policy  # type: ignore[assignment]
        _SESSION_GRANTS.difference_update(
            grant for grant in _SESSION_GRANTS if grant[0] == normalized_session
        )
    return {"sessionId": normalized_session, "policy": normalized_policy}


def list_tool_approval_requests(session_id: str, *, status: str = "") -> list[dict[str, Any]]:
    normalized_session = _required_identity(session_id, "sessionId")
    normalized_status = str(status or "").strip()
    with _LOCK:
        requests = [
            request
            for request in _REQUESTS.values()
            if request.session_id == normalized_session
            and (not normalized_status or request.status == normalized_status)
        ]
    requests.sort(key=lambda item: (item.created_at, item.request_id))
    return [item.public_projection() for item in requests]


def get_tool_approval_request(session_id: str, request_id: str) -> dict[str, Any]:
    request = _get_request(session_id, request_id)
    return request.public_projection()


def resolve_tool_approval_request(
    session_id: str,
    request_id: str,
    *,
    decision: str,
) -> dict[str, Any]:
    normalized_decision = str(decision or "").strip()
    if normalized_decision not in _VALID_DECISIONS:
        raise ToolApprovalError(f"unsupported tool approval decision: {normalized_decision or '<empty>'}")
    request = _get_request(session_id, request_id)
    with _LOCK:
        if request.status != "pending":
            raise ToolApprovalConflictError(
                f"tool approval request is already {request.status}: {request.request_id}"
            )
        if normalized_decision == "acceptForSession" and request.approval == "always":
            raise ToolApprovalConflictError("always-approval tools cannot be approved for the session")
        _resolve_request_locked(request, normalized_decision)
    return request.public_projection()


def authorize_or_wait(
    *,
    session_id: str,
    turn_id: str,
    agent_id: str,
    call_id: str,
    tool_name: str,
    tool_args: Mapping[str, Any],
    approval: str,
    risk: str,
    decision_fingerprint: str,
    cancel_checker: Callable[[], str] | None = None,
    timeout_seconds: float = DEFAULT_APPROVAL_TIMEOUT_SECONDS,
) -> ToolApprovalOutcome:
    normalized_session = _required_identity(session_id, "sessionId")
    normalized_turn = _required_identity(turn_id, "turnId")
    normalized_agent = _required_identity(agent_id, "agentId")
    normalized_call = _required_identity(call_id, "callId")
    normalized_tool = _required_identity(tool_name, "toolName")
    normalized_approval = str(approval or "never").strip()
    normalized_risk = str(risk or "read").strip()
    if normalized_approval == "never":
        return ToolApprovalOutcome(True, "approval_not_required")

    args_hash = _arguments_hash(tool_args)
    grant_key = (normalized_session, normalized_agent, normalized_tool, args_hash)
    with _LOCK:
        policy = _SESSION_POLICIES.get(normalized_session, DEFAULT_APPROVAL_POLICY)
        if grant_key in _SESSION_GRANTS and normalized_approval != "always":
            return ToolApprovalOutcome(True, "approved_for_session")

    if _can_auto_approve(
        policy=policy,
        tool_name=normalized_tool,
        tool_args=tool_args,
        approval=normalized_approval,
        risk=normalized_risk,
    ):
        return ToolApprovalOutcome(True, "auto_approved")
    if policy == "never":
        return ToolApprovalOutcome(
            False,
            "approval_policy_never",
            "[工具审批] 当前审批策略禁止请求用户授权，且该调用无法在现有沙盒边界内自动执行。",
        )

    request = _get_or_create_request(
        session_id=normalized_session,
        turn_id=normalized_turn,
        agent_id=normalized_agent,
        call_id=normalized_call,
        tool_name=normalized_tool,
        approval=normalized_approval,
        risk=normalized_risk,
        arguments_hash=args_hash,
        argument_summary=_argument_summary(normalized_tool, tool_args),
        decision_fingerprint=str(decision_fingerprint or "").strip(),
        timeout_seconds=timeout_seconds,
    )
    while not request.event.wait(0.05):
        if callable(cancel_checker):
            try:
                cancel_reason = str(cancel_checker() or "").strip()
            except Exception:
                cancel_reason = ""
            if cancel_reason:
                with _LOCK:
                    if request.status == "pending":
                        _resolve_request_locked(request, "cancel")
                return ToolApprovalOutcome(
                    False,
                    "approval_cancelled",
                    f"[工具审批] 等待用户授权时已取消：{cancel_reason}",
                    request.request_id,
                )
        if time.monotonic() >= request.expires_at:
            with _LOCK:
                if request.status == "pending":
                    request.status = "expired"
                    request.decision = "cancel"
                    request.resolved_at = _utc_now()
                    request.event.set()
            return ToolApprovalOutcome(
                False,
                "approval_timeout",
                "[工具审批] 等待用户授权超时，已按 fail-closed 拒绝执行。",
                request.request_id,
            )

    if request.status == "accepted":
        return ToolApprovalOutcome(True, "approved", request_id=request.request_id)
    if request.status == "accepted_for_session":
        return ToolApprovalOutcome(True, "approved_for_session", request_id=request.request_id)
    if request.status == "declined":
        return ToolApprovalOutcome(
            False,
            "approval_declined",
            "[工具审批] 用户拒绝了本次工具调用。",
            request.request_id,
        )
    return ToolApprovalOutcome(
        False,
        "approval_cancelled",
        "[工具审批] 本次工具调用已取消。",
        request.request_id,
    )


def reset_tool_approval_state() -> None:
    """Cancel live waiters and clear ephemeral session approvals."""

    with _LOCK:
        for request in _REQUESTS.values():
            if request.status == "pending":
                _resolve_request_locked(request, "cancel")
        _REQUESTS.clear()
        _REQUEST_IDS_BY_CALL.clear()
        _SESSION_POLICIES.clear()
        _SESSION_GRANTS.clear()


def _get_or_create_request(
    *,
    session_id: str,
    turn_id: str,
    agent_id: str,
    call_id: str,
    tool_name: str,
    approval: str,
    risk: str,
    arguments_hash: str,
    argument_summary: dict[str, Any],
    decision_fingerprint: str,
    timeout_seconds: float,
) -> _ApprovalRequest:
    key = (session_id, turn_id, call_id)
    with _LOCK:
        existing_id = _REQUEST_IDS_BY_CALL.get(key)
        if existing_id:
            existing = _REQUESTS.get(existing_id)
            if existing is None:
                raise ToolApprovalConflictError("tool approval request index is stale")
            if (
                existing.agent_id != agent_id
                or existing.tool_name != tool_name
                or existing.arguments_hash != arguments_hash
                or existing.decision_fingerprint != decision_fingerprint
            ):
                raise ToolApprovalConflictError("callId was reused with different approval facts")
            return existing
        request = _ApprovalRequest(
            request_id=f"approval-{uuid4().hex}",
            session_id=session_id,
            turn_id=turn_id,
            agent_id=agent_id,
            call_id=call_id,
            tool_name=tool_name,
            approval=approval,
            risk=risk,
            arguments_hash=arguments_hash,
            argument_summary=argument_summary,
            decision_fingerprint=decision_fingerprint,
            created_at=_utc_now(),
            expires_at=time.monotonic() + max(0.1, float(timeout_seconds)),
        )
        _REQUESTS[request.request_id] = request
        _REQUEST_IDS_BY_CALL[key] = request.request_id
        _prune_requests_locked()
        _record_approval_event("tool.approval.requested", request, outcome="pending")
        return request


def _get_request(session_id: str, request_id: str) -> _ApprovalRequest:
    normalized_session = _required_identity(session_id, "sessionId")
    normalized_request = _required_identity(request_id, "requestId")
    with _LOCK:
        request = _REQUESTS.get(normalized_request)
        if request is None or request.session_id != normalized_session:
            raise ToolApprovalNotFoundError(f"tool approval request not found: {normalized_request}")
        return request


def _resolve_request_locked(request: _ApprovalRequest, decision: str) -> None:
    request.decision = decision
    request.resolved_at = _utc_now()
    if decision == "accept":
        request.status = "accepted"
    elif decision == "acceptForSession":
        request.status = "accepted_for_session"
        _SESSION_GRANTS.add(
            (request.session_id, request.agent_id, request.tool_name, request.arguments_hash)
        )
    elif decision == "decline":
        request.status = "declined"
    else:
        request.status = "cancelled"
    request.event.set()
    _record_approval_event("tool.approval.resolved", request, outcome=request.status)


def _can_auto_approve(
    *,
    policy: str,
    tool_name: str,
    tool_args: Mapping[str, Any],
    approval: str,
    risk: str,
) -> bool:
    if approval == "always" or risk in {"network", "destructive"}:
        return False
    if policy == "untrusted":
        return risk == "read" and approval == "never"
    if tool_name in _SANDBOX_CONTAINED_TOOLS:
        return True
    if tool_name in _WORKSPACE_PATH_TOOLS:
        return _workspace_path_call_is_contained(tool_name, tool_args)
    return False


def _workspace_path_call_is_contained(tool_name: str, tool_args: Mapping[str, Any]) -> bool:
    try:
        from tools.shell_tools import _get_workspace_root

        workspace_root = _get_workspace_root().resolve()
        if tool_name == "apply_patch_tool":
            cwd = Path(str(tool_args.get("cwd") or ".").strip() or ".")
            base = cwd.resolve() if cwd.is_absolute() else (workspace_root / cwd).resolve()
            targets = [
                (base / str(match.group("path") or "").strip()).resolve()
                for match in _PATCH_TARGET_PATTERN.finditer(str(tool_args.get("patch_text") or ""))
                if str(match.group("path") or "").strip()
            ]
            return bool(targets) and base.is_relative_to(workspace_root) and all(
                target.is_relative_to(workspace_root) for target in targets
            )
        raw_path = str(tool_args.get("file_path") or "").strip()
        if not raw_path:
            return False
        candidate = Path(raw_path)
        if candidate.is_absolute():
            return False
        parts = candidate.parts
        if parts and parts[0].lower() == "workspace":
            candidate = Path(*parts[1:])
        return (workspace_root / candidate).resolve().is_relative_to(workspace_root)
    except Exception:
        return False


def _arguments_hash(tool_args: Mapping[str, Any]) -> str:
    payload = {
        str(key): value
        for key, value in dict(tool_args or {}).items()
        if str(key) != "_cancel_checker"
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _argument_summary(tool_name: str, tool_args: Mapping[str, Any]) -> dict[str, Any]:
    args = dict(tool_args or {})
    summary: dict[str, Any] = {
        "argumentKeys": sorted(str(key) for key in args if str(key) != "_cancel_checker")[:24],
    }
    if tool_name in {"cli_tool", "exec_command"}:
        command = str(args.get("cmd") or args.get("command") or "").strip()
        if command:
            summary["commandPreview"] = command[:500]
            summary["commandTruncated"] = len(command) > 500
    path = str(args.get("file_path") or "").strip()
    if path:
        summary["pathPreview"] = path[:300]
        summary["pathTruncated"] = len(path) > 300
    return summary


def _prune_requests_locked() -> None:
    if len(_REQUESTS) <= MAX_RETAINED_REQUESTS:
        return
    resolved = sorted(
        (item for item in _REQUESTS.values() if item.status != "pending"),
        key=lambda item: (item.resolved_at or item.created_at, item.request_id),
    )
    for request in resolved[: max(0, len(_REQUESTS) - MAX_RETAINED_REQUESTS)]:
        _REQUESTS.pop(request.request_id, None)
        _REQUEST_IDS_BY_CALL.pop((request.session_id, request.turn_id, request.call_id), None)


def _record_approval_event(
    event_code: str,
    request: _ApprovalRequest,
    *,
    outcome: str,
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "tool_authorization",
            "approval",
            event_code,
            message=event_code,
            level="warning" if request.status in {"pending", "declined", "cancelled", "expired"} else "info",
            outcome=str(outcome or "").strip() or "observed",
            fields={
                "requestId": request.request_id,
                "sessionId": request.session_id,
                "turnId": request.turn_id,
                "agentId": request.agent_id,
                "callId": request.call_id,
                "toolName": request.tool_name,
                "approval": request.approval,
                "risk": request.risk,
                "status": request.status,
                "decision": request.decision,
                "argumentsHash": request.arguments_hash,
                "decisionFingerprintPresent": bool(request.decision_fingerprint),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _required_identity(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ToolApprovalError(f"{field_name} is required")
    return normalized


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
