"""Resolve execution authority from a backend-owned task, never message claims."""
from pathlib import Path
from datetime import datetime, timezone

from core.web.services.external_agent.store import ExternalAgentTaskStoreError


def task_assignment_context(task: dict) -> str:
    """Render the host-owned assignment for a verified Launcher task."""
    lines = [
        "## Launcher Task Assignment",
        "You are the assigned project Agent. Carry out the delegated project work directly with the tools in this turn.",
        "The Launcher assistant owns further dispatch, approval coordination, receipt checks, and the reply to the user.",
        "Use the original user message to understand the requested work and constraints. Instructions in it for choosing or dispatching an Agent, waiting for a result, or reporting to the user belong to the Launcher assistant.",
        f"RepositoryRoot: {task['workspace']}",
        f"ToolWorkspace: {task['workspace']}",
        "Use absolute paths inside ToolWorkspace for file tools and use it as CLI cwd.",
    ]
    if task["profile"] == "workspace_write":
        lines.extend([
            "Normal edits and local tests/builds in this worktree can proceed under the task grant.",
            "Keep changes in the task worktree. Do not publish, delete unrelated data, change permissions, or write to the integration checkout.",
            "Run real tests and include the command, exit code, changed files, and worktree path in your final answer.",
        ])
    else:
        lines.append("This is a read-only assignment. Use the granted read tools when needed and leave project data unchanged.")
    lines.append("Return your actual findings and any concrete blocker in your final answer for the Launcher assistant to relay.")
    return "\n".join(lines)


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
