"""Managed external-Agent task lifecycle owned by the Vibelution backend."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.external_agent.contracts import (
    GUIDE_URI,
    GUIDE_VERSION,
    TASK_TERMINAL_STATUSES,
)

from .policy import (
    DEFAULT_EXTERNAL_AGENT_PERMISSION_CEILING,
    external_mcp_eligibility,
    list_externally_callable_agents,
)
from .store import (
    ExternalAgentTaskConflictError,
    ExternalAgentTaskNotFoundError,
    ExternalAgentTaskStore,
)


class ExternalAgentTaskError(RuntimeError):
    """Base managed external-Agent error."""

    def __init__(self, message: str, *, code: str = "EXTERNAL_AGENT_ERROR") -> None:
        super().__init__(message)
        self.code = str(code or "EXTERNAL_AGENT_ERROR")


class ExternalAgentAccessError(ExternalAgentTaskError):
    """Fail-closed not-found or capability error."""


class ExternalAgentConflictError(ExternalAgentTaskError):
    """Stale task or approval decision conflict."""


@dataclass(frozen=True)
class ExternalAgentTaskServiceDependencies:
    list_agents: Callable[..., list[dict[str, Any]]]
    get_agent: Callable[..., dict[str, Any] | None]
    active_team_lookup: Callable[[str], dict[str, Any] | None]
    create_session: Callable[..., dict[str, Any]]
    submit_message: Callable[..., dict[str, Any]]
    get_session_detail: Callable[..., dict[str, Any] | None]
    list_approvals: Callable[..., list[dict[str, Any]]]
    resolve_approval: Callable[..., dict[str, Any]]
    stop_turn: Callable[..., dict[str, Any]]
    record_event: Callable[..., Any] | None = None


_PROFILES = ("read_only", "workspace_write", "full_access")
_TERMINAL_PHASES = frozenset(
    {
        "idle",
        "ready",
        "completed",
        "succeeded",
        "failed",
        "error",
        "stopped",
        "cancelled",
        "interrupted",
    }
)
_RUNNING_PHASES = frozenset(
    {"queued", "running", "working", "busy", "stopping", "cancelling"}
)
_RESUMABLE_PHASES = frozenset({"needs_continue", "paused_limit"})
_APPROVAL_DECISIONS = frozenset(
    {"accept", "acceptForSession", "acceptAlways", "decline", "cancel"}
)
_MAX_TASK_CHARS = 64_000
_MAX_RESULT_CHARS = 8_000
_MAX_MANAGED_CONTINUATIONS = 3
_MANAGED_CONTINUATION_PROMPT = (
    "继续完成当前外部 Agent 任务；复用已有上下文，完成剩余工作并给出最终结果。"
)
_POLL_AFTER_MS = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _clip(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def default_dependencies() -> ExternalAgentTaskServiceDependencies:
    from core.web.services import agent_directory_service, session_service
    from core.web.services.runtime_scene_service import record_runtime_scene_event
    from core.web.services.session import tool_approvals
    from core.web.services.team import team_membership

    return ExternalAgentTaskServiceDependencies(
        list_agents=agent_directory_service.list_agents,
        get_agent=agent_directory_service.get_agent,
        active_team_lookup=team_membership._find_active_team_for_agent,
        create_session=session_service.create_chat_session,
        submit_message=session_service.submit_session_message,
        get_session_detail=session_service.get_session_detail,
        list_approvals=tool_approvals.list_tool_approval_requests,
        resolve_approval=tool_approvals.resolve_tool_approval_request,
        stop_turn=session_service.request_stop_session_turn,
        record_event=record_runtime_scene_event,
    )


class ExternalAgentTaskService:
    def __init__(
        self,
        store: ExternalAgentTaskStore,
        *,
        dependencies: ExternalAgentTaskServiceDependencies | None = None,
        operator_permission_ceiling: str = "read_only",
        runtime_permission_ceiling: str = "workspace_write",
        lease_seconds: int = 30,
        max_task_seconds: int = 1800,
        max_concurrent_tasks_per_owner: int = 4,
        max_concurrent_tasks_per_agent: int = 1,
        enabled: bool = True,
        allowed_agent_ids: Iterable[str] = (),
        denied_agent_ids: Iterable[str] = (),
        approval_persist_enabled: bool = False,
    ) -> None:
        self.store = store
        self.dependencies = dependencies or default_dependencies()
        self.operator_permission_ceiling = self._profile(operator_permission_ceiling)
        self.runtime_permission_ceiling = self._profile(runtime_permission_ceiling)
        self.lease_seconds = max(5, min(int(lease_seconds), 300))
        self.max_task_seconds = max(5, min(int(max_task_seconds), 7200))
        self.max_concurrent_tasks_per_owner = max(
            1, min(int(max_concurrent_tasks_per_owner), 32)
        )
        self.max_concurrent_tasks_per_agent = max(
            1, min(int(max_concurrent_tasks_per_agent), 8)
        )
        self.enabled = bool(enabled)
        self.allowed_agent_ids = frozenset(
            str(item or "").strip()
            for item in allowed_agent_ids
            if str(item or "").strip()
        )
        self.denied_agent_ids = frozenset(
            str(item or "").strip()
            for item in denied_agent_ids
            if str(item or "").strip()
        )
        self.approval_persist_enabled = bool(approval_persist_enabled)
        self._refresh_lock = threading.RLock()

    def list_agents(self, *, limit: int = 50) -> dict[str, Any]:
        self._require_gateway_enabled()
        bounded_limit = max(1, min(int(limit), 200))
        agents = self.dependencies.list_agents(include_archived=False, detail="summary")
        items = list_externally_callable_agents(
            agents,
            active_team_lookup=self.dependencies.active_team_lookup,
            operator_enabled=self._operator_agent_enabled,
        )[:bounded_limit]
        self._record_gateway_event(
            "external_agent.discovery.completed",
            fields={
                "observedCount": len(agents),
                "eligibleCount": len(items),
                "deniedCount": max(0, len(agents) - len(items)),
            },
        )
        return {
            "status": "ok",
            "count": len(items),
            "agents": items,
            "guideUri": GUIDE_URI,
            "guideVersion": GUIDE_VERSION,
        }

    def start_task(
        self,
        *,
        owner_id: str,
        adapter_connection_id: str,
        capabilities: set[str],
        agent_id: str,
        task: str,
        permission_profile: str,
        client_request_id: str,
        title: str,
        runtime_revision: str,
        include_private: bool = False,
    ) -> dict[str, Any]:
        del capabilities  # Reserved for future per-start capability checks.
        self._require_gateway_enabled()
        normalized_task = str(task or "").strip()
        if not normalized_task:
            raise ValueError("task is required")
        if len(normalized_task) > _MAX_TASK_CHARS:
            raise ValueError(f"task exceeds {_MAX_TASK_CHARS} characters")
        agent = self.dependencies.get_agent(
            str(agent_id or "").strip(), include_archived=False
        )
        try:
            self._require_eligible(agent)
        except ExternalAgentAccessError as exc:
            self._record_gateway_event(
                "external_agent.execution.denied",
                fields={"reasonCode": exc.code},
                outcome="denied",
            )
            raise
        resolved_agent_id = str(
            (agent or {}).get("agentId") or (agent or {}).get("id") or ""
        ).strip()
        effective = self._effective_profile(permission_profile, agent or {})
        normalized_request_id = _clip(client_request_id, 200)
        existing = self.store.find_idempotent(
            owner_id=owner_id,
            client_request_id=normalized_request_id,
        )
        if existing is None:
            active = self.store.list_nonterminal()
            owner_active = sum(
                1 for item in active if self.store.owner_matches(item, owner_id)
            )
            agent_active = sum(
                1
                for item in active
                if str(item.get("agentId") or "") == resolved_agent_id
            )
            if owner_active >= self.max_concurrent_tasks_per_owner:
                raise ExternalAgentConflictError(
                    "external Agent owner concurrency limit reached",
                    code="TASK_CONFLICT",
                )
            if agent_active >= self.max_concurrent_tasks_per_agent:
                raise ExternalAgentConflictError(
                    "external Agent concurrency limit reached",
                    code="TASK_CONFLICT",
                )
        request_digest = _digest(
            json.dumps(
                {
                    "agentId": resolved_agent_id,
                    "taskDigest": _digest(normalized_task),
                    "permissionProfile": str(permission_profile or "read_only").strip(),
                    "title": _clip(title, 160),
                },
                sort_keys=True,
                ensure_ascii=False,
            )
        )
        try:
            record, created = self.store.create_task(
                owner_id=owner_id,
                agent_id=resolved_agent_id,
                task_digest=_digest(normalized_task),
                client_request_id=normalized_request_id,
                request_digest=request_digest,
                permission_profile=effective,
                lease_seconds=self.lease_seconds,
                adapter_connection_id=adapter_connection_id,
                runtime_revision=runtime_revision,
                max_task_seconds=self.max_task_seconds,
            )
        except ExternalAgentTaskConflictError as exc:
            raise ExternalAgentConflictError(str(exc), code="TASK_CONFLICT") from exc

        if not created:
            return self._public_task(record, include_private=include_private)

        if not str(record.get("sessionId") or "").strip():
            try:
                session = self.dependencies.create_session(
                    agent_id=resolved_agent_id,
                    title=_clip(title, 160) or f"[external] {resolved_agent_id}",
                    created_by="external_agent_task",
                    conversation_index_kind="hidden",
                    session_metadata={
                        "source": "external_agent_task",
                        "externalTaskId": record["taskId"],
                        "effectivePermissionProfile": effective,
                        "runtimeRevision": str(runtime_revision or "").strip(),
                    },
                    lightweight=True,
                    activate=False,
                )
                session_id = str(
                    session.get("sessionId")
                    or session.get("conversationId")
                    or session.get("id")
                    or ""
                ).strip()
                if not session_id:
                    raise RuntimeError(
                        "hidden external task session returned no sessionId"
                    )
                submitted = self.dependencies.submit_message(
                    session_id,
                    normalized_task,
                    message_source="external_agent_task",
                    message_metadata={
                        "source": "external_agent_task",
                        "taskId": record["taskId"],
                        "effectivePermissionProfile": effective,
                        "allowInternalAutoContinue": True,
                        "runtimeRevision": str(runtime_revision or "").strip(),
                    },
                    lightweight_response=True,
                    include_started_turn_id=True,
                )
                turn_id = str(
                    submitted.get("turnId")
                    or submitted.get("startedTurnId")
                    or submitted.get("activeTurnId")
                    or ""
                ).strip()
                record = self._transition(
                    record["taskId"],
                    status="running",
                    expected_revision=int(record["revision"]),
                    reason_code="turn_started",
                    fields={"sessionId": session_id, "turnId": turn_id},
                )
                self._record_event("external_agent.task.started", record)
            except Exception:
                latest = self.store.get_task(record["taskId"])
                if str(latest.get("status") or "") not in TASK_TERMINAL_STATUSES:
                    self._transition(
                        record["taskId"],
                        status="failed",
                        expected_revision=int(latest["revision"]),
                        reason_code="task_start_failed",
                        fields={
                            "error": {
                                "code": "TASK_START_FAILED",
                                "message": "Agent task could not be started.",
                            }
                        },
                    )
                raise
        else:
            record = self.store.get_task(record["taskId"])
        return self._public_task(record, include_private=include_private)

    def get_task(self, *, owner_id: str, task_id: str) -> dict[str, Any]:
        with self._refresh_lock:
            record = self._owned_task(owner_id, task_id)
            record, approvals = self._refresh(record)
        return self._public_task(record, pending_approvals=approvals)

    def resolve_approval(
        self,
        *,
        owner_id: str,
        capabilities: set[str],
        task_id: str,
        approval_id: str,
        decision: str,
        expected_revision: str,
        reason: str,
    ) -> dict[str, Any]:
        del reason  # Never persist potentially sensitive free-form approval text.
        normalized_decision = str(decision or "").strip()
        if normalized_decision not in _APPROVAL_DECISIONS:
            raise ValueError(
                f"unsupported approval decision: {normalized_decision or '<empty>'}"
            )
        self._require_gateway_enabled()
        if normalized_decision == "acceptAlways" and (
            not self.approval_persist_enabled or "approval.persist" not in capabilities
        ):
            raise ExternalAgentAccessError(
                "approval.persist capability is required",
                code="APPROVAL_FORBIDDEN",
            )
        record = self._owned_task(owner_id, task_id)
        if str(record.get("status") or "") in TASK_TERMINAL_STATUSES:
            raise ExternalAgentConflictError(
                "terminal task approvals cannot be changed",
                code="APPROVAL_CONFLICT",
            )
        agent = self.dependencies.get_agent(
            str(record.get("agentId") or ""), include_archived=False
        )
        self._require_eligible(agent)
        if normalized_decision == "acceptAlways":
            metadata = (
                agent.get("metadata")
                if isinstance(agent, dict) and isinstance(agent.get("metadata"), dict)
                else {}
            )
            persist_allowed = bool(
                (agent or {}).get("externalApprovalPersistAllowed")
                or metadata.get("externalApprovalPersistAllowed")
            )
            if not persist_allowed:
                raise ExternalAgentAccessError(
                    "Agent policy does not allow approval.persist",
                    code="APPROVAL_FORBIDDEN",
                )
        decisions = (
            record.get("approvalDecisions")
            if isinstance(record.get("approvalDecisions"), dict)
            else {}
        )
        previous = (
            decisions.get(approval_id)
            if isinstance(decisions.get(approval_id), dict)
            else None
        )
        if previous:
            if str(previous.get("decision") or "") != normalized_decision:
                raise ExternalAgentConflictError(
                    "approval decision conflict",
                    code="APPROVAL_CONFLICT",
                )
            return {
                "status": "ok",
                "taskId": record["taskId"],
                "approvalId": approval_id,
                "decision": normalized_decision,
                "taskStatus": record["status"],
            }
        session_id = str(record.get("sessionId") or "")
        pending = self.dependencies.list_approvals(session_id, status="")
        approval = next(
            (
                item
                for item in pending
                if str(item.get("requestId") or "") == str(approval_id or "").strip()
            ),
            None,
        )
        if (
            not isinstance(approval, dict)
            or str(approval.get("status") or "") != "pending"
        ):
            raise ExternalAgentAccessError(
                "approval was not found for this task",
                code="APPROVAL_FORBIDDEN",
            )
        if str(approval.get("turnId") or "") not in {
            "",
            str(record.get("turnId") or ""),
        }:
            raise ExternalAgentAccessError(
                "approval was not found for this task",
                code="APPROVAL_FORBIDDEN",
            )
        fingerprint = str(
            approval.get("decisionFingerprint") or approval.get("configRevision") or ""
        )
        if expected_revision and str(expected_revision).strip() != fingerprint:
            raise ExternalAgentConflictError(
                "approval revision conflict",
                code="APPROVAL_CONFLICT",
            )
        current_config_revision = (agent or {}).get("configRevision")
        approval_config_revision = approval.get("configRevision")
        if (
            current_config_revision not in (None, "", 0)
            and approval_config_revision not in (None, "", 0)
            and str(current_config_revision) != str(approval_config_revision)
        ):
            raise ExternalAgentConflictError(
                "Agent config revision changed",
                code="APPROVAL_CONFLICT",
            )
        result = self.dependencies.resolve_approval(
            session_id,
            str(approval_id or "").strip(),
            decision=normalized_decision,
        )
        decisions[str(approval_id)] = {
            "decision": normalized_decision,
            "revision": fingerprint,
            "resolvedAt": _now_iso(),
        }
        latest = self.store.get_task(record["taskId"])
        target_status = (
            "running"
            if str(latest.get("status") or "") == "awaiting_approval"
            else str(latest.get("status") or "")
        )
        latest = self._transition(
            latest["taskId"],
            status=target_status,
            expected_revision=int(latest["revision"]),
            reason_code="approval_resolved",
            fields={"approvalDecisions": decisions},
        )
        if normalized_decision == "cancel":
            latest = self._request_cancel(
                latest,
                terminal_status="cancelled",
                reason_code="approval_cancelled",
            )
        self._record_event(
            "external_agent.approval.resolved",
            latest,
            fields={"approvalId": str(approval_id), "decision": normalized_decision},
        )
        return {
            "status": "ok",
            "taskId": latest["taskId"],
            "approvalId": str(approval_id),
            "decision": str(result.get("decision") or normalized_decision),
            "taskStatus": latest["status"],
        }

    def cancel_task(
        self,
        *,
        owner_id: str,
        task_id: str,
        terminal_status: str = "cancelled",
        reason_code: str = "cancel_requested",
    ) -> dict[str, Any]:
        record = self._owned_task(owner_id, task_id)
        if str(record.get("status") or "") in TASK_TERMINAL_STATUSES:
            return self._public_task(record)
        record = self._request_cancel(
            record,
            terminal_status=terminal_status,
            reason_code=reason_code,
        )
        self._record_event("external_agent.task.cancel_requested", record)
        return self._public_task(record)

    def heartbeat(
        self,
        *,
        owner_id: str,
        task_id: str,
        lease_id: str,
        adapter_connection_id: str,
    ) -> dict[str, Any]:
        try:
            record = self.store.renew_lease(
                task_id,
                owner_id=owner_id,
                lease_id=lease_id,
                adapter_connection_id=adapter_connection_id,
                lease_seconds=self.lease_seconds,
            )
        except ExternalAgentTaskNotFoundError as exc:
            raise ExternalAgentAccessError(
                "external Agent task was not found",
                code="TASK_NOT_FOUND",
            ) from exc
        return self._public_task(record, include_private=True)

    def cancel_connection_tasks(
        self, *, owner_id: str, adapter_connection_id: str
    ) -> list[dict[str, Any]]:
        cancelled: list[dict[str, Any]] = []
        for record in self.store.list_nonterminal():
            if not self.store.owner_matches(record, owner_id):
                continue
            if (
                str(record.get("adapterConnectionId") or "")
                != str(adapter_connection_id or "").strip()
            ):
                continue
            cancelled.append(
                self._public_task(
                    self._request_cancel(
                        record,
                        terminal_status="cancelled",
                        reason_code="adapter_shutdown",
                    )
                )
            )
        return cancelled

    def reconcile(self, *, now_iso: str | None = None) -> list[dict[str, Any]]:
        now = _parse_iso(now_iso or _now_iso()) or datetime.now(timezone.utc)
        updated: list[dict[str, Any]] = []
        for record in self.store.list_nonterminal():
            current = self.store.get_task(str(record.get("taskId") or ""))
            try:
                self._require_eligible(
                    self.dependencies.get_agent(
                        str(current.get("agentId") or ""), include_archived=False
                    )
                )
            except ExternalAgentAccessError:
                current = self._request_cancel(
                    current,
                    terminal_status="cancelled",
                    reason_code="agent_eligibility_revoked",
                )
                updated.append(current)
                continue
            lease_expiry = _parse_iso(str(current.get("leaseExpiresAt") or ""))
            deadline = _parse_iso(str(current.get("deadlineAt") or ""))
            if deadline is not None and deadline <= now:
                current = self._request_cancel(
                    current,
                    terminal_status="timed_out",
                    reason_code="task_deadline_exceeded",
                )
                updated.append(current)
                continue
            if lease_expiry is not None and lease_expiry <= now:
                current = self._request_cancel(
                    current,
                    terminal_status="timed_out",
                    reason_code="lease_expired",
                )
                updated.append(current)
                continue
            with self._refresh_lock:
                refreshed, _ = self._refresh(current)
            if refreshed != current:
                updated.append(refreshed)
        return updated

    def _request_cancel(
        self,
        record: dict[str, Any],
        *,
        terminal_status: str,
        reason_code: str,
    ) -> dict[str, Any]:
        status = str(record.get("status") or "")
        if status in TASK_TERMINAL_STATUSES:
            return record
        session_id = str(record.get("sessionId") or "")
        turn_id = str(record.get("turnId") or "")
        if not session_id:
            return self._transition(
                record["taskId"],
                status=terminal_status,
                expected_revision=int(record["revision"]),
                reason_code=reason_code,
            )
        if not str(record.get("stopRequestedAt") or ""):
            if status not in {"cancelling", "stop_unconfirmed"}:
                record = self._transition(
                    record["taskId"],
                    status="cancelling",
                    expected_revision=int(record["revision"]),
                    reason_code=reason_code,
                    fields={
                        "cancellationTerminalStatus": terminal_status,
                        "stopRequestedAt": _now_iso(),
                    },
                )
            self.dependencies.stop_turn(session_id, expected_turn_id=turn_id)
        detail = self.dependencies.get_session_detail(
            session_id,
            message_limit=20,
            include_secondary=False,
        )
        latest = self.store.get_task(record["taskId"])
        if not self._session_running(detail):
            return self._transition(
                latest["taskId"],
                status=str(latest.get("cancellationTerminalStatus") or terminal_status),
                expected_revision=int(latest["revision"]),
                reason_code=f"{reason_code}_confirmed",
            )
        if str(latest.get("status") or "") == "cancelling":
            return self._transition(
                latest["taskId"],
                status="stop_unconfirmed",
                expected_revision=int(latest["revision"]),
                reason_code="stop_not_yet_confirmed",
            )
        return latest

    def _refresh(
        self, record: dict[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        status = str(record.get("status") or "")
        if status in TASK_TERMINAL_STATUSES:
            return record, []
        if status in {"cancelling", "stop_unconfirmed"}:
            refreshed = self._request_cancel(
                record,
                terminal_status=str(
                    record.get("cancellationTerminalStatus") or "cancelled"
                ),
                reason_code=str(record.get("reasonCode") or "cancel_requested"),
            )
            return refreshed, []
        try:
            self._require_eligible(
                self.dependencies.get_agent(
                    str(record.get("agentId") or ""), include_archived=False
                )
            )
        except ExternalAgentAccessError:
            revoked = self._request_cancel(
                record,
                terminal_status="cancelled",
                reason_code="agent_eligibility_revoked",
            )
            return revoked, []
        session_id = str(record.get("sessionId") or "")
        if not session_id:
            return record, []
        approvals = [
            item
            for item in self.dependencies.list_approvals(session_id, status="pending")
            if str(item.get("status") or "pending") == "pending"
            and str(item.get("turnId") or "") in {"", str(record.get("turnId") or "")}
        ]
        latest = self.store.get_task(record["taskId"])
        if approvals:
            if str(latest.get("status") or "") != "awaiting_approval":
                latest = self._transition(
                    latest["taskId"],
                    status="awaiting_approval",
                    expected_revision=int(latest["revision"]),
                    reason_code="approval_required",
                )
            return latest, approvals
        detail = self.dependencies.get_session_detail(
            session_id,
            message_limit=40,
            include_secondary=False,
        )
        if self._session_running(detail):
            if str(latest.get("status") or "") == "awaiting_approval":
                latest = self._transition(
                    latest["taskId"],
                    status="running",
                    expected_revision=int(latest["revision"]),
                    reason_code="approval_wait_cleared",
                )
            return latest, []
        phase = self._session_phase(detail)
        if phase in _RESUMABLE_PHASES:
            return self._continue_resumable_task(latest, detail), []
        if phase in _TERMINAL_PHASES:
            failed = phase in {"failed", "error"}
            result_summary = self._result_summary(detail or {})
            latest = self._transition(
                latest["taskId"],
                status="failed" if failed else "succeeded",
                expected_revision=int(latest["revision"]),
                reason_code="turn_failed" if failed else "turn_succeeded",
                fields={
                    "resultSummary": result_summary,
                    "error": (
                        {
                            "code": "TURN_FAILED",
                            "message": result_summary or "Agent turn failed.",
                        }
                        if failed
                        else None
                    ),
                },
            )
        return latest, []

    def _continue_resumable_task(
        self,
        record: dict[str, Any],
        detail: dict[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            continuation_count = max(0, int(record.get("continuationCount") or 0))
        except (TypeError, ValueError):
            continuation_count = 0
        result_summary = self._result_summary(detail or {})
        if continuation_count >= _MAX_MANAGED_CONTINUATIONS:
            failed = self._transition(
                record["taskId"],
                status="failed",
                expected_revision=int(record["revision"]),
                reason_code="turn_continuation_limit",
                fields={
                    "resultSummary": result_summary,
                    "error": {
                        "code": "TURN_CONTINUATION_LIMIT",
                        "message": "Agent task reached the managed continuation limit.",
                    },
                },
            )
            self._record_event(
                "external_agent.task.continuation_limit_reached",
                failed,
                fields={"continuationCount": continuation_count},
            )
            return failed

        continuation_index = continuation_count + 1
        session_id = str(record.get("sessionId") or "").strip()
        try:
            submitted = self.dependencies.submit_message(
                session_id,
                _MANAGED_CONTINUATION_PROMPT,
                message_source="external_agent_task",
                message_metadata={
                    "source": "external_agent_task",
                    "taskId": record["taskId"],
                    "effectivePermissionProfile": str(
                        record.get("effectivePermissionProfile") or "read_only"
                    ),
                    "allowInternalAutoContinue": True,
                    "runtimeRevision": str(record.get("runtimeRevision") or ""),
                    "continuationIndex": continuation_index,
                },
                lightweight_response=True,
                include_started_turn_id=True,
            )
            turn_id = str(
                submitted.get("turnId")
                or submitted.get("startedTurnId")
                or submitted.get("activeTurnId")
                or ""
            ).strip()
            if not turn_id:
                raise RuntimeError("managed continuation returned no turnId")
        except Exception:  # noqa: BLE001 - project a stable boundary, never raw internals
            latest = self.store.get_task(record["taskId"])
            failed = self._transition(
                latest["taskId"],
                status="failed",
                expected_revision=int(latest["revision"]),
                reason_code="turn_continuation_failed",
                fields={
                    "resultSummary": result_summary,
                    "error": {
                        "code": "TURN_CONTINUATION_FAILED",
                        "message": "Agent task continuation could not be started.",
                    },
                },
            )
            self._record_event("external_agent.task.continuation_failed", failed)
            return failed

        latest = self.store.get_task(record["taskId"])
        continued = self._transition(
            latest["taskId"],
            status="running",
            expected_revision=int(latest["revision"]),
            reason_code="turn_continued",
            fields={
                "turnId": turn_id,
                "continuationCount": continuation_index,
            },
        )
        self._record_event(
            "external_agent.task.continued",
            continued,
            fields={"continuationCount": continuation_index},
        )
        return continued

    def _owned_task(self, owner_id: str, task_id: str) -> dict[str, Any]:
        try:
            record = self.store.get_task(task_id)
        except ExternalAgentTaskNotFoundError as exc:
            raise ExternalAgentAccessError(
                "external Agent task was not found",
                code="TASK_NOT_FOUND",
            ) from exc
        if not self.store.owner_matches(record, owner_id):
            raise ExternalAgentAccessError(
                "external Agent task was not found",
                code="TASK_NOT_FOUND",
            )
        return record

    def _require_eligible(self, agent: dict[str, Any] | None) -> None:
        decision = external_mcp_eligibility(
            agent,
            active_team_lookup=self.dependencies.active_team_lookup,
            operator_enabled=self._operator_agent_enabled,
        )
        if not decision.eligible:
            raise ExternalAgentAccessError(
                "Agent is not available for external calls",
                code="AGENT_NOT_FOUND",
            )

    def _require_gateway_enabled(self) -> None:
        if not self.enabled:
            raise ExternalAgentAccessError(
                "Managed external-Agent gateway is disabled",
                code="GATEWAY_NOT_READY",
            )

    def _operator_agent_enabled(self, agent_id: str) -> bool:
        normalized = str(agent_id or "").strip()
        if not self.enabled or not normalized or normalized in self.denied_agent_ids:
            return False
        return not self.allowed_agent_ids or normalized in self.allowed_agent_ids

    def operator_capabilities(self) -> set[str]:
        return {"approval.persist"} if self.approval_persist_enabled else set()

    def record_adapter_event(
        self, event_code: str, *, adapter_connection_id: str
    ) -> None:
        connection_digest = _digest(str(adapter_connection_id or "").strip())
        self._record_gateway_event(
            event_code,
            fields={"adapterConnectionDigest": connection_digest},
        )

    def _effective_profile(self, requested: str, agent: dict[str, Any]) -> str:
        requested_profile = self._profile(requested or "read_only")
        agent_ceiling = self._profile(
            agent.get("externalMaximumPermissionProfile")
            or DEFAULT_EXTERNAL_AGENT_PERMISSION_CEILING
        )
        index = min(
            _PROFILES.index(requested_profile),
            _PROFILES.index(agent_ceiling),
            _PROFILES.index(self.operator_permission_ceiling),
            _PROFILES.index(self.runtime_permission_ceiling),
        )
        return _PROFILES[index]

    @staticmethod
    def _profile(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in _PROFILES:
            raise ValueError(
                f"unsupported external permission profile: {normalized or '<empty>'}"
            )
        return normalized

    @staticmethod
    def _session_phase(detail: dict[str, Any] | None) -> str:
        if not isinstance(detail, dict):
            return ""
        runtime = (
            detail.get("runtime") if isinstance(detail.get("runtime"), dict) else {}
        )
        return (
            str(
                detail.get("phase")
                or detail.get("status")
                or detail.get("lastTurnStatus")
                or runtime.get("phase")
                or runtime.get("status")
                or ""
            )
            .strip()
            .lower()
        )

    @classmethod
    def _session_running(cls, detail: dict[str, Any] | None) -> bool:
        if not isinstance(detail, dict):
            return True  # Fail closed: absence is not stop confirmation.
        if isinstance(detail.get("running"), bool):
            return bool(detail["running"])
        if isinstance(detail.get("isRunning"), bool):
            return bool(detail["isRunning"])
        return cls._session_phase(detail) in _RUNNING_PHASES

    @staticmethod
    def _result_summary(detail: dict[str, Any]) -> str:
        messages: Iterable[Any] = (
            detail.get("messages") if isinstance(detail.get("messages"), list) else []
        )
        for message in reversed(list(messages)):
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "").strip().lower() != "assistant":
                continue
            return _clip(
                message.get("content") or message.get("text") or "", _MAX_RESULT_CHARS
            )
        return _clip(
            detail.get("summary") or detail.get("resultSummary") or "",
            _MAX_RESULT_CHARS,
        )

    @staticmethod
    def _sanitize_approval(approval: dict[str, Any]) -> dict[str, Any]:
        return {
            "approvalId": str(approval.get("requestId") or ""),
            "toolName": str(approval.get("toolName") or ""),
            "risk": str(approval.get("risk") or ""),
            "targetSummary": (
                dict(approval.get("argumentSummary"))
                if isinstance(approval.get("argumentSummary"), dict)
                else {}
            ),
            "configRevision": approval.get("configRevision"),
            "revision": str(
                approval.get("decisionFingerprint")
                or approval.get("configRevision")
                or ""
            ),
            "availableDecisions": [
                "accept",
                "acceptForSession",
                "acceptAlways",
                "decline",
                "cancel",
            ],
        }

    def _public_task(
        self,
        record: dict[str, Any],
        *,
        pending_approvals: list[dict[str, Any]] | None = None,
        include_private: bool = False,
    ) -> dict[str, Any]:
        status = str(record.get("status") or "")
        payload: dict[str, Any] = {
            "taskId": str(record.get("taskId") or ""),
            "status": status,
            "effectivePermissionProfile": str(
                record.get("effectivePermissionProfile") or "read_only"
            ),
            "createdAt": record.get("createdAt"),
            "updatedAt": record.get("updatedAt"),
            "completedAt": record.get("completedAt"),
            "resultSummary": _clip(
                record.get("resultSummary") or "", _MAX_RESULT_CHARS
            ),
            "error": record.get("error")
            if isinstance(record.get("error"), dict)
            else None,
            "pendingApprovals": [
                self._sanitize_approval(item) for item in (pending_approvals or [])
            ],
            "pollAfterMs": 0 if status in TASK_TERMINAL_STATUSES else _POLL_AFTER_MS,
            "shouldPoll": status not in TASK_TERMINAL_STATUSES,
            "guideUri": GUIDE_URI,
            "guideVersion": GUIDE_VERSION,
        }
        if include_private:
            payload["_leaseId"] = str(record.get("leaseId") or "")
        return payload

    def _record_event(
        self,
        event_code: str,
        record: dict[str, Any],
        *,
        fields: dict[str, Any] | None = None,
    ) -> None:
        recorder = self.dependencies.record_event
        if not callable(recorder):
            return
        safe_fields = {
            "taskId": str(record.get("taskId") or ""),
            "agentId": str(record.get("agentId") or ""),
            "status": str(record.get("status") or ""),
            "reasonCode": str(record.get("reasonCode") or ""),
            "effectivePermissionProfile": str(
                record.get("effectivePermissionProfile") or ""
            ),
        }
        safe_fields.update(dict(fields or {}))
        try:
            recorder(
                "external_agent",
                "managed_task",
                event_code,
                message="Managed external-Agent task lifecycle event.",
                outcome=str(record.get("status") or "recorded"),
                fields=safe_fields,
                lifecycle=True,
            )
        except Exception:  # noqa: BLE001,S110 - diagnostics must never break task state
            pass

    def _record_gateway_event(
        self,
        event_code: str,
        *,
        fields: dict[str, Any] | None = None,
        outcome: str = "recorded",
    ) -> None:
        recorder = self.dependencies.record_event
        if not callable(recorder):
            return
        try:
            recorder(
                "external_agent",
                "managed_gateway",
                event_code,
                message="Managed external-Agent gateway lifecycle event.",
                outcome=str(outcome or "recorded"),
                fields=dict(fields or {}),
                lifecycle=True,
            )
        except Exception:  # noqa: BLE001,S110 - diagnostics must never break gateway lifecycle
            pass

    def _transition(
        self,
        task_id: str,
        *,
        status: str,
        expected_revision: int | None = None,
        reason_code: str = "",
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        previous = self.store.get_task(task_id)
        updated = self.store.transition(
            task_id,
            status=status,
            expected_revision=expected_revision,
            reason_code=reason_code,
            fields=fields,
        )
        self._record_event(
            "external_agent.task.state_transition",
            updated,
            fields={
                "fromStatus": str(previous.get("status") or ""),
                "toStatus": str(updated.get("status") or ""),
                "transitionReasonCode": str(reason_code or ""),
            },
        )
        return updated


def build_default_service(project_root: Path) -> ExternalAgentTaskService:
    from config.settings import get_config

    gateway = get_config().external_agent_gateway
    return ExternalAgentTaskService(
        ExternalAgentTaskStore(
            Path(project_root).resolve() / ".runtime" / "external_agents"
        ),
        operator_permission_ceiling=gateway.permission_ceiling,
        runtime_permission_ceiling=gateway.runtime_permission_ceiling,
        lease_seconds=gateway.lease_seconds,
        max_task_seconds=gateway.max_task_seconds,
        max_concurrent_tasks_per_owner=gateway.max_concurrent_tasks_per_owner,
        max_concurrent_tasks_per_agent=gateway.max_concurrent_tasks_per_agent,
        enabled=gateway.enabled,
        allowed_agent_ids=gateway.allowed_agent_ids,
        denied_agent_ids=gateway.denied_agent_ids,
        approval_persist_enabled=gateway.approval_persist_enabled,
    )


_DEFAULT_SERVICES_LOCK = threading.RLock()
_DEFAULT_SERVICES: dict[str, tuple[str, ExternalAgentTaskService]] = {}


def get_default_service(project_root: Path) -> ExternalAgentTaskService:
    from config.settings import get_config

    root = Path(project_root).expanduser().resolve()
    key = str(root).casefold()
    gateway = get_config().external_agent_gateway
    fingerprint = hashlib.sha256(gateway.model_dump_json().encode("utf-8")).hexdigest()
    with _DEFAULT_SERVICES_LOCK:
        cached = _DEFAULT_SERVICES.get(key)
        if cached is None or cached[0] != fingerprint:
            service = build_default_service(root)
            _DEFAULT_SERVICES[key] = (fingerprint, service)
            return service
        return cached[1]


__all__ = [
    "ExternalAgentAccessError",
    "ExternalAgentConflictError",
    "ExternalAgentTaskError",
    "ExternalAgentTaskService",
    "ExternalAgentTaskServiceDependencies",
    "build_default_service",
    "default_dependencies",
    "get_default_service",
]
