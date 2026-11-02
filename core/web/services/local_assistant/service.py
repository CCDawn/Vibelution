"""Launcher-owned tasks reuse the native owner with a separate access policy."""
from contextvars import ContextVar
from contextlib import contextmanager
from pathlib import Path

from core.web.services.external_agent.service import ExternalAgentAccessError, ExternalAgentTaskService
from core.web.services.external_agent.store import ExternalAgentTaskStore
from vibelution_storage import resolve_project_runtime_home


route_service: ContextVar[ExternalAgentTaskService | None] = ContextVar("local_assistant_task_service", default=None)


def task_store(project_root):
    return ExternalAgentTaskStore(resolve_project_runtime_home(Path(project_root)) / "local_assistant_tasks")


def materialize_workspace(project_root, task_id):
    from core.infrastructure.branch_workspace import allocate_worktree_path
    from core.web.services.team.dev_task_board import _materialize_worktree
    slug = "assistant-" + task_id
    workspace = allocate_worktree_path(project_root, slug)
    _materialize_worktree(Path(project_root), workspace, "codex/" + slug)
    return workspace


class LocalAssistantTaskService(ExternalAgentTaskService):
    """Only authenticated transport may select this policy; DTOs cannot."""

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

    def _start_native_task(self, record, **kwargs):
        with self._task_lock(record["taskId"]):
            current = self.store.get_task(record["taskId"])
            fingerprint = self.request_authority_fingerprint or self.authority_fingerprint()
            if self.authority_fingerprint() != fingerprint:
                raise ExternalAgentAccessError("Local assistant authorization changed", code="LOCAL_ASSISTANT_DISABLED")
            if current.get("localAuthorityFingerprint") not in (None, fingerprint) or not fingerprint:
                raise ExternalAgentAccessError("Local assistant authorization changed", code="LOCAL_ASSISTANT_DISABLED")
            if not current.get("localAuthorityFingerprint"):
                workspace = (self.workspace_factory(record["taskId"])
                             if kwargs["effective"] == "workspace_write" else self.project_root)
                current = self.store.transition(current["taskId"], status=current["status"],
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
