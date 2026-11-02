"""Resolve execution authority from a backend-owned task, never message claims."""
from pathlib import Path
from datetime import datetime, timezone

from core.web.services.external_agent.store import ExternalAgentTaskStoreError


def verified_task_runtime(*, project_root, session_id, agent_id, metadata,
                          store=None, authority_fingerprint=None):
    from core.infrastructure.launcher_assistant_authority import launcher_authority_fingerprint
    from .service import task_store
    if not isinstance(metadata, dict) or metadata.get("source") != "external_agent_task":
        return None
    task_id = metadata.get("taskId")
    if not isinstance(task_id, str) or not task_id:
        return None
    try:
        record = (store or task_store(project_root)).get_task(task_id)
        fingerprint = (authority_fingerprint or launcher_authority_fingerprint)()
        if (not fingerprint or record.get("localAuthorityFingerprint") != fingerprint
                or record.get("agentId") != agent_id or record.get("sessionId") != session_id
                or record.get("effectivePermissionProfile") != metadata.get("effectivePermissionProfile")
                or record.get("status") not in {"queued", "running", "awaiting_approval"}):
            return None
        if record.get("stopRequestedAt") or any(
                datetime.fromisoformat(record[key].replace("Z", "+00:00")) <= datetime.now(timezone.utc)
                for key in ("leaseExpiresAt", "deadlineAt")):
            return None
        workspace = Path(record["localWorkspacePath"])
        if not workspace.is_absolute() or not workspace.is_dir() or workspace.is_symlink():
            return None
        return {"taskId": task_id, "workspace": workspace.resolve(),
                "profile": record["effectivePermissionProfile"]}
    except (OSError, ValueError, TypeError, KeyError, ExternalAgentTaskStoreError):
        return None
