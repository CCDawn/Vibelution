"""Launcher-owned tasks reuse the native owner with a separate access policy."""
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from core.external_agent.contracts import TASK_TERMINAL_STATUSES
from core.web.services.external_agent.service import ExternalAgentAccessError, ExternalAgentTaskService, _parse_iso
from core.web.services.external_agent.store import ExternalAgentTaskStore
from vibelution_storage import resolve_project_runtime_home


route_service: ContextVar[ExternalAgentTaskService | None] = ContextVar("local_assistant_task_service", default=None)


def task_store(project_root):
    from .task_cleanup import LocalAssistantCleanupTaskStore
    return LocalAssistantCleanupTaskStore(resolve_project_runtime_home(Path(project_root)) / "local_assistant_tasks")


def materialize_workspace(project_root, task_id):
    from core.infrastructure.branch_workspace import allocate_worktree_path
    from core.web.services.team.dev_task_board import _materialize_worktree
    slug = "assistant-" + task_id
    workspace = allocate_worktree_path(project_root, slug)
    _materialize_worktree(Path(project_root), workspace, "codex/" + slug, timeout_seconds=600)
    return workspace


class LocalAssistantTaskService(ExternalAgentTaskService):
    """Only authenticated transport may select this policy; DTOs cannot."""

    cleanup_workspaces = True
    cleanup_absent_sessions = False

    def __init__(self, store, *, project_root, authority_fingerprint=None, workspace_factory=None, **kwargs):
        from core.infrastructure.launcher_assistant_authority import launcher_authority_fingerprint
        self.project_root = Path(project_root).resolve()
        self.authority_fingerprint = authority_fingerprint or launcher_authority_fingerprint
        self.workspace_factory = workspace_factory or (lambda task_id: materialize_workspace(self.project_root, task_id))
        self.request_authority_fingerprint = ""
        # Third-party enabled/allowlist/ceilings never configure this principal.
        kwargs.update(enabled=True, operator_permission_ceiling="workspace_write", runtime_permission_ceiling="workspace_write")
        super().__init__(store, **kwargs)

    def _require_gateway_enabled(self):
        current = self.authority_fingerprint()
        if not current or self.request_authority_fingerprint and current != self.request_authority_fingerprint:
            raise ExternalAgentAccessError("Local assistant authorization is unavailable", code="LOCAL_ASSISTANT_DISABLED")

    def _require_cleanup_ownership(self, record):
        authority = self.authority_fingerprint()
        proofs = [record.get(key) for key in ("localAuthorityFingerprint", "localCleanupAuthorityFingerprint") if record.get(key)]
        if not authority or not proofs or any(proof != authority for proof in proofs):
            raise ExternalAgentAccessError("Task does not belong to current Launcher", code="TASK_NOT_FOUND")

    def _operator_agent_enabled(self, agent_id):
        return bool(agent_id and agent_id not in self.denied_agent_ids)

    def _operator_agent_explicitly_enabled(self, agent_id):
        return False  # Hidden, team and Companion identities do not become ordinary workers.

    def _effective_profile(self, requested, agent):
        profile = self._profile(requested or "workspace_write")
        return "read_only" if profile == "read_only" else "workspace_write"

    def _require_eligible(self, agent):
        if isinstance(agent, dict) and (agent.get("protected") or agent.get("isProtected")):
            raise ExternalAgentAccessError("Agent is protected", code="AGENT_NOT_FOUND")
        super()._require_eligible(agent)

    def _admit_start_task(self, **kwargs):
        record, created, agent_id, task, effective = super()._admit_start_task(**kwargs)
        if created:
            # Cleanup ownership is established at authenticated admission, not
            # by the later workspace-complete marker used by native startup.
            with self._task_lock(record["taskId"]):
                record = self.store.get_task(record["taskId"])
                record = self.store.transition(record["taskId"], status=record["status"],
                    expected_revision=record["revision"], fields={
                        "localCleanupAuthorityFingerprint": self.request_authority_fingerprint or self.authority_fingerprint(),
                        "localCleanupWorkspaceState": "not_started",
                    })
        return record, created, agent_id, task, effective

    def _request_cancel_locked(self, record, *, terminal_status, reason_code, strict_confirmation=False):
        # A checkout can outlive its lease before any native session exists.
        # Follow the store's cancellation path rather than inventing a direct
        # queued -> timed_out edge shared with third-party tasks.
        if (record["status"] == "queued" and not record.get("sessionId")
                and terminal_status == "timed_out"):
            record = self._transition(record["taskId"], status="cancelling",
                expected_revision=record["revision"], reason_code=reason_code,
                fields={"cancellationTerminalStatus": terminal_status})
        return super()._request_cancel_locked(record, terminal_status=terminal_status,
            reason_code=reason_code, strict_confirmation=strict_confirmation)

    def _preparation_stop_reason(self, record, fingerprint):
        if (not fingerprint or self.authority_fingerprint() != fingerprint
                or record.get("localAuthorityFingerprint") not in (None, fingerprint)):
            return "local_authority_revoked"
        if self._native_start_admission is not None:
            from config.settings import get_config
            self.denied_agent_ids = frozenset(get_config().external_agent_gateway.denied_agent_ids)
        try:
            self._require_eligible(self.dependencies.get_agent(record["agentId"], include_archived=False))
        except ExternalAgentAccessError:
            return "agent_eligibility_revoked"
        now = datetime.now(timezone.utc)
        for field, code in (("deadlineAt", "task_deadline_exceeded"), ("leaseExpiresAt", "lease_expired")):
            expires = _parse_iso(record.get(field, ""))
            if expires is None or expires <= now:
                return code
        return ""

    def _stop_preparation(self, record, reason):
        status = "timed_out" if reason in {"task_deadline_exceeded", "lease_expired"} else "cancelled"
        return self._request_cancel(record, terminal_status=status, reason_code=reason)

    def _start_native_task(self, record, **kwargs):
        task_id = record["taskId"]
        # Provisioning is serialized separately: request lookup, renewal and
        # cancellation must remain available while Git creates the checkout.
        with self._task_lock("local-workspace:" + task_id):
            with self._task_lock(task_id):
                current = self.store.get_task(task_id)
                if current["status"] in TASK_TERMINAL_STATUSES:
                    return self._public_task(current, include_private=kwargs["include_private"])
                fingerprint = self.request_authority_fingerprint or self.authority_fingerprint()
                reason = self._preparation_stop_reason(current, fingerprint)
                if reason:
                    current = self._stop_preparation(current, reason)
                    return self._public_task(current, include_private=kwargs["include_private"])
                needs_workspace = not current.get("localAuthorityFingerprint")
                if needs_workspace:
                    current = self.store.transition(task_id, status=current["status"],
                        expected_revision=current["revision"], fields={"localCleanupWorkspaceState": "preparing"})
            if needs_workspace:
                try:
                    workspace = (self.workspace_factory(task_id)
                                 if kwargs["effective"] == "workspace_write" else self.project_root)
                    cleanup_workspace = str(Path(workspace).absolute())
                except Exception:
                    # This preparation precedes the native owner's own startup
                    # try/except. Persist failure on the original idempotent row
                    # so lookup/heartbeat cannot leave it queued indefinitely.
                    with self._task_lock(task_id):
                        latest = self.store.get_task(task_id)
                        if latest["status"] not in TASK_TERMINAL_STATUSES:
                            self._transition(task_id, status="failed",
                                expected_revision=latest["revision"], reason_code="workspace_setup_failed",
                                fields={"error": {"code": "WORKSPACE_SETUP_FAILED",
                                                  "message": "Agent task workspace could not be prepared."},
                                        "localCleanupWorkspaceState": "unknown"})
                        else:
                            self.store.transition(task_id, status=latest["status"],
                                expected_revision=latest["revision"], fields={"localCleanupWorkspaceState": "unknown"})
                    raise
            with self._task_lock(task_id):
                current = self.store.get_task(task_id)
                if needs_workspace:
                    # Cancellation must stay responsive during preparation,
                    # but must not lose a successfully prepared directory.
                    current = self.store.transition(task_id, status=current["status"],
                        expected_revision=current["revision"], fields={
                            "localCleanupWorkspaceState": "ready", "localCleanupWorkspacePath": cleanup_workspace,
                        })
                if current["status"] in TASK_TERMINAL_STATUSES:
                    return self._public_task(current, include_private=kwargs["include_private"])
                reason = self._preparation_stop_reason(current, fingerprint)
                if reason:
                    current = self._stop_preparation(current, reason)
                    return self._public_task(current, include_private=kwargs["include_private"])
                if needs_workspace:
                    current = self.store.transition(task_id, status=current["status"],
                        expected_revision=current["revision"], fields={
                            "localAuthorityFingerprint": fingerprint,
                            "localWorkspacePath": str(Path(workspace).resolve()),
                        })
                return super()._start_native_task(current, **kwargs)


@contextmanager
def _local_start_admission(service):
    from config.settings import get_config
    from core.web.services import agent_directory_service as directory
    if (Path(directory.PROJECT_ROOT).resolve() != service.project_root
            or Path(directory._active_project_root()).resolve() != service.project_root):
        raise ExternalAgentAccessError("Native local Agent owner changed", code="LOCAL_ASSISTANT_DISABLED")
    with directory.agent_session_lifecycle_transaction():
        if Path(directory._active_project_root()).resolve() != service.project_root:
            raise ExternalAgentAccessError("Native local Agent owner changed", code="LOCAL_ASSISTANT_DISABLED")
        service._require_gateway_enabled()  # Fresh Launcher authority, never MCP enabled.
        current = service.authority_fingerprint()
        if not current:
            raise ExternalAgentAccessError("Local assistant authorization is unavailable", code="LOCAL_ASSISTANT_DISABLED")
        if not service.request_authority_fingerprint:
            service.request_authority_fingerprint = current
        # A service selected before waiting for Life must honor a later explicit
        # target deny. MCP enabled/allowlist/ceilings do not configure this lane.
        service.denied_agent_ids = frozenset(get_config().external_agent_gateway.denied_agent_ids)
        yield None


def build_local_service(project_root):
    from config.settings import get_config
    gateway = get_config().external_agent_gateway
    service = LocalAssistantTaskService(task_store(project_root), project_root=project_root,
        denied_agent_ids=gateway.denied_agent_ids, max_task_seconds=7200,
        lease_seconds=gateway.lease_seconds,
        max_concurrent_tasks_per_owner=gateway.max_concurrent_tasks_per_owner,
        max_concurrent_tasks_per_agent=gateway.max_concurrent_tasks_per_agent)
    service._native_start_admission = lambda: _local_start_admission(service)
    return service
