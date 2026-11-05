"""Cleanup compatibility for pre-local-transport Launcher dispatches only.

The original external record stays at its original path as a content-free
terminal receipt. Ordinary SDK idempotency still finds it, so deleting a
Launcher dispatch can never turn a retried request into a second execution.
"""
from .service import LocalAssistantTaskService
from .task_cleanup import LocalAssistantCleanupTaskStore, _atomic_json, _safe_tree
from core.web.services.external_agent.service import ExternalAgentAccessError
from vibelution_storage import resolve_project_runtime_home


class LegacyAssistantCleanupTaskStore(LocalAssistantCleanupTaskStore):
    def tombstone_path(self, task_id):
        return self.task_path(task_id)

    def cleanup_completion(self, task_id):
        path = self.task_path(task_id)
        if not path.is_file():
            return None
        _safe_tree(path)
        record = self._read_path(path)
        return record if record.get("localCleanupComplete") is True else None

    def finish_cleanup(self, record, tombstone):
        path = self.task_path(record["taskId"])
        _safe_tree(path)
        before = path.stat().st_size
        fields = ("schemaVersion", "taskId", "revision", "status", "ownerSubjectHash",
            "clientRequestId", "requestDigest", "agentId", "effectivePermissionProfile",
            "createdAt", "updatedAt", "completedAt", "leaseId")
        stub = {key: record[key] for key in fields if key in record}
        stub.update(tombstone)
        stub.update(localCleanupComplete=True, reasonCode="task_cleaned")
        _atomic_json(path, stub)
        return max(0, before - path.stat().st_size)


class LegacyAssistantCleanupService(LocalAssistantTaskService):
    # External tasks never established ownership of an isolated worktree.
    # Session workingDirectory or arbitrary old projection fields are not proof.
    cleanup_workspaces = False
    cleanup_absent_sessions = True

    def _require_cleanup_ownership(self, record):
        request_id = record.get("clientRequestId")
        if (not isinstance(request_id, str) or not request_id.startswith("launcher-assistant:")
                or not request_id[len("launcher-assistant:"):].strip()):
            raise ExternalAgentAccessError("Task is not a Launcher dispatch", code="TASK_NOT_FOUND")


def build_legacy_cleanup_service(local_service):
    service = LegacyAssistantCleanupService(
        LegacyAssistantCleanupTaskStore(resolve_project_runtime_home(local_service.project_root) / "external_agents"),
        project_root=local_service.project_root, authority_fingerprint=local_service.authority_fingerprint)
    service.request_authority_fingerprint = local_service.request_authority_fingerprint
    return service
