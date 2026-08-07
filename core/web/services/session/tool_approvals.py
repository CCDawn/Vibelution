"""Codex-style per-call tool approval coordination for live session turns.

Session grants (`acceptForSession`) stay process-local and scoped by sessionId.
Durable grants (`acceptAlways`) live inside the owning Agent's ToolPolicy so the
Agent configuration remains the sole authority across processes and sessions.
"""

from __future__ import annotations

from copy import deepcopy
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


ToolApprovalDecision = Literal[
    "accept",
    "acceptForSession",
    "acceptAlways",
    "decline",
    "cancel",
]

DEFAULT_APPROVAL_TIMEOUT_SECONDS = 300.0
MAX_RETAINED_REQUESTS = 256
MAX_DURABLE_GRANTS_PER_TOOL = 64
_VALID_PERMISSION_PRESETS = {"request_approval", "auto_review", "full_access"}
_VALID_DECISIONS = {
    "accept",
    "acceptForSession",
    "acceptAlways",
    "decline",
    "cancel",
}
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
    session_grant_scope: dict[str, Any]
    session_grant_key: str
    decision_fingerprint: str
    config_revision: int
    config_hash: str
    permission_preset: str
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
            "sessionGrantScope": dict(self.session_grant_scope),
            "decisionFingerprint": self.decision_fingerprint,
            "configRevision": self.config_revision,
            "configHash": self.config_hash,
            "permissionPreset": self.permission_preset,
            "availableDecisions": [
                "accept",
                "acceptForSession",
                "acceptAlways",
                "decline",
                "cancel",
            ],
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
# (session_id, agent_id, config_revision, config_hash, tool_name, grant_key)
_SESSION_GRANTS: set[tuple[str, str, int, str, str, str]] = set()


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
        if (
            normalized_decision in {"acceptForSession", "acceptAlways"}
            and request.approval == "always"
        ):
            raise ToolApprovalConflictError(
                "always-approval tools cannot receive session or durable grants"
            )
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
    config_revision: int,
    config_hash: str,
    permission_preset: str,
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
    normalized_permission_preset = str(permission_preset or "").strip()
    if normalized_permission_preset not in _VALID_PERMISSION_PRESETS:
        raise ToolApprovalError(
            f"unsupported Agent permission preset: {normalized_permission_preset or '<empty>'}"
        )
    try:
        normalized_config_revision = int(config_revision)
    except (TypeError, ValueError) as exc:
        raise ToolApprovalError("Agent configRevision is required") from exc
    normalized_config_hash = _required_identity(config_hash, "configHash")
    if normalized_config_revision < 1:
        raise ToolApprovalError("Agent configRevision is required")
    if normalized_permission_preset == "full_access":
        return ToolApprovalOutcome(True, "full_access_auto_approved")

    args_hash = _arguments_hash(tool_args)
    session_grant_scope = _session_grant_scope(normalized_tool, tool_args, args_hash)
    grant_key = (
        normalized_session,
        normalized_agent,
        normalized_config_revision,
        normalized_config_hash,
        normalized_tool,
        _session_grant_key(session_grant_scope),
    )
    with _LOCK:
        if grant_key in _SESSION_GRANTS and normalized_approval != "always":
            return ToolApprovalOutcome(True, "approved_for_session")
        if normalized_approval != "always" and _has_durable_grant(
            agent_id=normalized_agent,
            tool_name=normalized_tool,
            grant_key=_session_grant_key(session_grant_scope),
        ):
            return ToolApprovalOutcome(True, "approved_for_agent")

    if _can_auto_approve(
        permission_preset=normalized_permission_preset,
        tool_name=normalized_tool,
        tool_args=tool_args,
        approval=normalized_approval,
        risk=normalized_risk,
    ):
        return ToolApprovalOutcome(True, "auto_approved")
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
        session_grant_scope=session_grant_scope,
        session_grant_key=_session_grant_key(session_grant_scope),
        decision_fingerprint=str(decision_fingerprint or "").strip(),
        config_revision=normalized_config_revision,
        config_hash=normalized_config_hash,
        permission_preset=normalized_permission_preset,
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
    if request.status == "accepted_always":
        return ToolApprovalOutcome(True, "approved_for_agent", request_id=request.request_id)
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


def reset_tool_approval_state(*, clear_durable: bool = False) -> None:
    """Cancel live waiters and clear ephemeral session approvals.

    Durable agent grants are kept by default so process restarts and tests that
    only reset in-memory session state do not wipe permanent approvals.
    """

    with _LOCK:
        for request in _REQUESTS.values():
            if request.status == "pending":
                _resolve_request_locked(request, "cancel")
        _REQUESTS.clear()
        _REQUEST_IDS_BY_CALL.clear()
        _SESSION_GRANTS.clear()
    if clear_durable:
        clear_durable_tool_approval_grants()


def clear_durable_tool_approval_grants(*, agent_id: str = "") -> int:
    """Remove durable grants for one agent or all agents. Returns removed count."""

    normalized_agent = str(agent_id or "").strip()
    agents = _agent_directory_agents(normalized_agent)
    removed = 0
    for agent in agents:
        policy = _agent_tool_policy(agent)
        grants = _approval_grant_records(policy, agent_id=str(agent.get("agentId") or ""))
        if not grants:
            continue
        updated_policy = _policy_without_approval_grants(policy)
        _update_agent_tool_policy(agent, updated_policy)
        removed += len(grants)
    return removed


def list_durable_tool_approval_grants(*, agent_id: str = "") -> list[dict[str, Any]]:
    """Return durable grant projections (for diagnostics / future settings UI)."""

    normalized_agent = str(agent_id or "").strip()
    records: list[dict[str, Any]] = []
    for agent in _agent_directory_agents(normalized_agent):
        records.extend(
            _approval_grant_records(
                _agent_tool_policy(agent),
                agent_id=str(agent.get("agentId") or ""),
            )
        )
    records.sort(
        key=lambda item: (
            str(item.get("createdAt") or ""),
            str(item.get("agentId") or ""),
            str(item.get("toolName") or ""),
        )
    )
    return [dict(item) for item in records]


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
    session_grant_scope: dict[str, Any],
    session_grant_key: str,
    decision_fingerprint: str,
    config_revision: int,
    config_hash: str,
    permission_preset: str,
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
                or existing.config_revision != config_revision
                or existing.config_hash != config_hash
                or existing.permission_preset != permission_preset
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
            session_grant_scope=session_grant_scope,
            session_grant_key=session_grant_key,
            decision_fingerprint=decision_fingerprint,
            config_revision=config_revision,
            config_hash=config_hash,
            permission_preset=permission_preset,
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
    if decision == "acceptAlways":
        _add_durable_grant(
            agent_id=request.agent_id,
            tool_name=request.tool_name,
            grant_key=request.session_grant_key,
            scope=dict(request.session_grant_scope),
            source_session_id=request.session_id,
            source_request_id=request.request_id,
            expected_config_revision=request.config_revision,
        )
    request.decision = decision
    request.resolved_at = _utc_now()
    if decision == "accept":
        request.status = "accepted"
    elif decision == "acceptForSession":
        request.status = "accepted_for_session"
        _SESSION_GRANTS.add(
            (
                request.session_id,
                request.agent_id,
                request.config_revision,
                request.config_hash,
                request.tool_name,
                request.session_grant_key,
            )
        )
    elif decision == "acceptAlways":
        request.status = "accepted_always"
        # Also warm the current-process session cache for immediate reuse.
        _SESSION_GRANTS.add(
            (
                request.session_id,
                request.agent_id,
                request.config_revision,
                request.config_hash,
                request.tool_name,
                request.session_grant_key,
            )
        )
    elif decision == "decline":
        request.status = "declined"
    else:
        request.status = "cancelled"
    request.event.set()
    _record_approval_event("tool.approval.resolved", request, outcome=request.status)


def _has_durable_grant(*, agent_id: str, tool_name: str, grant_key: str) -> bool:
    try:
        agents = _canonical_agent_configs(agent_id)
        if not agents:
            return False
        return any(
            record["toolName"] == tool_name and record["grantKey"] == grant_key
            for record in _approval_grant_records(
                _agent_tool_policy(agents[0]),
                agent_id=agent_id,
            )
        )
    except Exception:
        # A storage/read failure never upgrades a call; it falls back to asking.
        return False


def _add_durable_grant(
    *,
    agent_id: str,
    tool_name: str,
    grant_key: str,
    scope: Mapping[str, Any],
    source_session_id: str,
    source_request_id: str,
    expected_config_revision: int,
) -> None:
    """Persist a durable tool grant on the Agent ToolPolicy.

    Approval requests freeze the turn's configRevision. The first ``acceptAlways``
    in a turn already bumps the Agent revision, so later always-grants must merge
    onto the live Agent and retry once on optimistic-lock conflicts instead of
    failing closed with a stale request revision.
    """

    from core.web.services import agent_directory_service

    last_conflict: Exception | None = None
    # Attempt 1 uses live Agent state (not the frozen request revision).
    # Attempt 2 re-reads after a concurrent config bump (common mid-turn always chain).
    for attempt in range(2):
        agents = _canonical_agent_configs(agent_id)
        if not agents:
            raise ToolApprovalConflictError(f"Agent configuration not found: {agent_id}")
        agent = agents[0]
        try:
            live_revision = max(0, int(agent.get("configRevision") or 0))
        except (TypeError, ValueError):
            live_revision = 0
        # Prefer live revision; fall back to the request hint only when live is missing.
        write_revision = live_revision if live_revision > 0 else int(expected_config_revision)
        policy = _agent_tool_policy(agent)
        records = _approval_grant_records(
            policy,
            agent_id=agent_id,
            tool_name=tool_name,
        )
        existing = next(
            (
                item
                for item in records
                if item["grantKey"] == grant_key
            ),
            None,
        )
        record = {
            "agentId": agent_id,
            "toolName": tool_name,
            "grantKey": grant_key,
            "scope": dict(scope or {}),
            "createdAt": str((existing or {}).get("createdAt") or "").strip() or _utc_now(),
            "updatedAt": _utc_now(),
            "sourceSessionId": source_session_id,
            "sourceRequestId": source_request_id,
        }
        records = [
            item
            for item in records
            if item["grantKey"] != grant_key
        ]
        records.append(record)
        records.sort(
            key=lambda item: (
                str(item.get("updatedAt") or item.get("createdAt") or ""),
                str(item.get("grantKey") or ""),
            )
        )
        records = records[-MAX_DURABLE_GRANTS_PER_TOOL:]
        updated_policy = _policy_with_tool_approval_grants(
            policy,
            tool_name=tool_name,
            records=records,
        )
        try:
            _update_agent_tool_policy(
                agent,
                updated_policy,
                expected_config_revision=write_revision,
            )
            return
        except ToolApprovalError:
            raise
        except Exception as exc:
            if isinstance(exc, agent_directory_service.AgentNotFoundError):
                raise ToolApprovalConflictError(str(exc)) from exc
            if isinstance(exc, agent_directory_service.AgentStateConflictError):
                last_conflict = exc
                if attempt == 0:
                    continue
                raise ToolApprovalConflictError(str(exc)) from exc
            raise ToolApprovalError(
                "Unable to persist durable approval in Agent ToolPolicy."
            ) from exc
    if last_conflict is not None:
        raise ToolApprovalConflictError(str(last_conflict)) from last_conflict
    raise ToolApprovalConflictError(
        f"Unable to persist durable approval for agent: {agent_id}"
    )


def _agent_directory_agents(agent_id: str = "") -> list[dict[str, Any]]:
    return _canonical_agent_configs(agent_id)


def _canonical_agent_configs(agent_id: str = "") -> list[dict[str, Any]]:
    """Read canonical Agent config without runtime/effective-policy projection."""

    from core.web.services import agent_directory_service

    normalized_agent = str(agent_id or "").strip()
    with agent_directory_service._STATE_LOCK:
        state = agent_directory_service.load_state()
        raw_agents = [
            item
            for item in list(state.get("agents") or [])
            if isinstance(item, dict)
            and (
                not normalized_agent
                or str(item.get("agentId") or "").strip() == normalized_agent
            )
        ]
        policies = agent_directory_service._tool_policies(state)
        snapshots: list[dict[str, Any]] = []
        for raw_agent in raw_agents:
            policy_id = (
                str(
                    raw_agent.get("toolPolicyId")
                    or agent_directory_service.DEFAULT_TOOL_POLICY_ID
                ).strip()
                or agent_directory_service.DEFAULT_TOOL_POLICY_ID
            )
            raw_policy = raw_agent.get("toolPolicy")
            if not isinstance(raw_policy, dict):
                raw_policy = policies.get(policy_id)
            snapshots.append(
                {
                    "agentId": str(raw_agent.get("agentId") or "").strip(),
                    "configRevision": int(raw_agent.get("configRevision") or 0),
                    "configHash": str(raw_agent.get("configHash") or "").strip(),
                    "toolPolicyId": policy_id,
                    "toolPolicy": deepcopy(
                        agent_directory_service.normalize_tool_policy(
                            raw_policy if isinstance(raw_policy, dict) else {},
                            policy_id,
                        )
                    ),
                }
            )
    return snapshots


def _agent_tool_policy(agent: Mapping[str, Any]) -> dict[str, Any]:
    policy = agent.get("toolPolicy")
    return dict(policy) if isinstance(policy, dict) else {}


def _approval_grant_records(
    policy: Mapping[str, Any],
    *,
    agent_id: str,
    tool_name: str = "",
) -> list[dict[str, Any]]:
    rules = policy.get("perToolRules")
    if not isinstance(rules, dict):
        return []
    records: list[dict[str, Any]] = []
    normalized_filter = str(tool_name or "").strip()
    for rule_tool_name, raw_rule in rules.items():
        normalized_tool = str(rule_tool_name or "").strip()
        if normalized_filter and normalized_tool != normalized_filter:
            continue
        if not normalized_tool or not isinstance(raw_rule, dict):
            continue
        raw_grants = raw_rule.get("approvalGrants")
        if not isinstance(raw_grants, list):
            continue
        for item in raw_grants:
            if not isinstance(item, dict):
                continue
            grant_key = str(item.get("grantKey") or "").strip()
            if not grant_key:
                continue
            records.append(
                {
                    "agentId": agent_id,
                    "toolName": normalized_tool,
                    "grantKey": grant_key,
                    "scope": (
                        dict(item.get("scope"))
                        if isinstance(item.get("scope"), dict)
                        else {}
                    ),
                    "createdAt": str(item.get("createdAt") or "").strip(),
                    "updatedAt": str(item.get("updatedAt") or "").strip(),
                    "sourceSessionId": str(item.get("sourceSessionId") or "").strip(),
                    "sourceRequestId": str(item.get("sourceRequestId") or "").strip(),
                }
            )
    return records


def _policy_with_tool_approval_grants(
    policy: Mapping[str, Any],
    *,
    tool_name: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    updated_policy = dict(policy)
    updated_rules = {
        str(tool_name): dict(rule) if isinstance(rule, dict) else {}
        for tool_name, rule in dict(policy.get("perToolRules") or {}).items()
    }
    rule = updated_rules.setdefault(tool_name, {})
    rule["approvalGrants"] = [
        {
            key: item[key]
            for key in (
                "grantKey",
                "scope",
                "createdAt",
                "updatedAt",
                "sourceSessionId",
                "sourceRequestId",
            )
        }
        for item in records
    ]
    updated_policy["perToolRules"] = updated_rules
    return updated_policy


def _policy_without_approval_grants(policy: Mapping[str, Any]) -> dict[str, Any]:
    updated_policy = dict(policy)
    updated_rules = {
        str(tool_name): dict(rule) if isinstance(rule, dict) else {}
        for tool_name, rule in dict(policy.get("perToolRules") or {}).items()
    }
    for rule in updated_rules.values():
        rule.pop("approvalGrants", None)
    updated_policy["perToolRules"] = updated_rules
    return updated_policy


def _update_agent_tool_policy(
    agent: Mapping[str, Any],
    policy: dict[str, Any],
    *,
    expected_config_revision: int | None = None,
) -> dict[str, Any]:
    from core.web.services import agent_directory_service

    current_policy = _agent_tool_policy(agent)
    policy_id = (
        str(
            agent.get("toolPolicyId")
            or current_policy.get("policyId")
            or agent_directory_service.DEFAULT_TOOL_POLICY_ID
        ).strip()
        or agent_directory_service.DEFAULT_TOOL_POLICY_ID
    )
    if policy_id == agent_directory_service.DEFAULT_TOOL_POLICY_ID:
        policy_id = f"tool-{str(agent.get('agentId') or '').strip()}"
        current_policy = agent_directory_service.normalize_tool_policy(
            {**current_policy, "policyId": policy_id},
            policy_id,
        )
        policy = agent_directory_service.normalize_tool_policy(
            {**policy, "policyId": policy_id},
            policy_id,
        )
    revision = (
        int(expected_config_revision)
        if expected_config_revision is not None
        else int(agent.get("configRevision") or 0)
    )
    return agent_directory_service.update_agent_instance(
        str(agent.get("agentId") or ""),
        tool_policy=policy,
        expected_config_revision=revision,
        expected_tool_policy_fingerprint=agent_directory_service.tool_policy_fingerprint(
            current_policy
        ),
    )


# Read-only git subcommands that observe the workspace without mutating it.
# Used under request_approval so shell-backed `git status|branch|log|…` does not
# force a user prompt when dedicated git tools would not.
_SAFE_READONLY_GIT_SUBCOMMANDS = frozenset(
    {
        "status",
        "branch",
        "log",
        "show",
        "diff",
        "rev-parse",
        "rev-list",
        "ls-files",
        "ls-tree",
        "describe",
        "tag",
        "remote",
        "stash",
        "blame",
        "shortlog",
        "whatchanged",
        "name-rev",
        "cat-file",
        "config",
        "version",
        "help",
    }
)
_SAFE_READONLY_GIT_STASH_ACTIONS = frozenset({"list", "show"})
_SAFE_READONLY_GIT_REMOTE_ACTIONS = frozenset({"", "-v", "--verbose", "show", "get-url"})
_SAFE_READONLY_GIT_CONFIG_ACTIONS = frozenset({"--get", "--get-all", "--list", "-l", "--get-regexp"})
_UNSAFE_GIT_FLAG_TOKENS = frozenset(
    {
        "--exec",
        "--upload-pack",
        "--receive-pack",
        "-c",
    }
)


def _cli_command_text(tool_args: Mapping[str, Any]) -> str:
    return str(tool_args.get("cmd") or tool_args.get("command") or "").strip()


def _is_safe_readonly_git_cli(tool_args: Mapping[str, Any]) -> bool:
    """True for single-shot read-only git observation commands (no shell chaining)."""

    command = _cli_command_text(tool_args)
    if not command:
        return False
    # Reject shell metacharacters that can chain/write beyond a pure git read.
    if re.search(r"[|;&><`$]|&&|\|\|", command):
        return False
    try:
        parts = [part for part in re.split(r"\s+", command) if part]
    except Exception:
        return False
    if len(parts) < 2:
        return False
    head = parts[0].strip().lower().replace("\\", "/")
    executable = head.rsplit("/", 1)[-1]
    if executable not in {"git", "git.exe"}:
        return False
    # Drop global git options before the subcommand: git -C . status
    index = 1
    while index < len(parts):
        token = parts[index]
        lowered = token.lower()
        if lowered in _UNSAFE_GIT_FLAG_TOKENS:
            return False
        if lowered in {"-c", "-C"}:
            index += 2
            continue
        if lowered.startswith("-"):
            # Other global flags (e.g. --no-pager) are observational.
            index += 1
            continue
        break
    if index >= len(parts):
        return False
    subcommand = parts[index].strip().lower()
    if subcommand not in _SAFE_READONLY_GIT_SUBCOMMANDS:
        return False
    rest = [part.lower() for part in parts[index + 1 :]]
    if subcommand == "stash":
        action = rest[0] if rest else "list"
        return action in _SAFE_READONLY_GIT_STASH_ACTIONS
    if subcommand == "remote":
        action = rest[0] if rest else ""
        return action in _SAFE_READONLY_GIT_REMOTE_ACTIONS
    if subcommand == "config":
        if not rest:
            return False
        return rest[0] in _SAFE_READONLY_GIT_CONFIG_ACTIONS
    if subcommand == "tag" and any(token in {"-d", "--delete", "-a", "-m", "-f", "--force"} for token in rest):
        return False
    return True


def _can_auto_approve(
    *,
    permission_preset: str,
    tool_name: str,
    tool_args: Mapping[str, Any],
    approval: str,
    risk: str,
) -> bool:
    if permission_preset == "full_access":
        return True
    if approval == "always" or risk in {"network", "destructive"}:
        return False
    # request_approval still prompts for general shell/execute work, but pure
    # read-only git observation matches the preset copy ("ask for high-risk")
    # and avoids regressing dedicated git-tool workflows when models use cli_tool.
    if permission_preset == "request_approval":
        return tool_name in {"cli_tool", "exec_command"} and _is_safe_readonly_git_cli(tool_args)
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
        cwd = str(args.get("cwd") or "").strip()
        if cwd:
            summary["cwdPreview"] = cwd[:300]
            summary["cwdTruncated"] = len(cwd) > 300
    if tool_name == "write_stdin":
        terminal_session_id = str(
            args.get("session_id") or args.get("terminal_session_id") or ""
        ).strip()
        chars = str(args.get("chars") or "")
        if terminal_session_id:
            summary["terminalSessionId"] = terminal_session_id[:160]
        summary["stdinPreview"] = chars[:500]
        summary["stdinTruncated"] = len(chars) > 500
        summary["stdinChars"] = len(chars)
    path = str(args.get("file_path") or "").strip()
    if path:
        summary["pathPreview"] = path[:300]
        summary["pathTruncated"] = len(path) > 300
    return summary


def _session_grant_scope(
    tool_name: str,
    tool_args: Mapping[str, Any],
    arguments_hash: str,
) -> dict[str, Any]:
    if tool_name == "write_stdin":
        terminal_session_id = str(
            tool_args.get("session_id")
            or tool_args.get("terminal_session_id")
            or ""
        ).strip()
        if terminal_session_id:
            return {
                "kind": "terminal_session",
                "terminalSessionId": terminal_session_id,
            }
    return {
        "kind": "exact_arguments",
        "argumentsHash": arguments_hash,
    }


def _session_grant_key(scope: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(scope or {}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


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
                "configRevision": request.config_revision,
                "configHash": request.config_hash,
                "permissionPreset": request.permission_preset,
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
