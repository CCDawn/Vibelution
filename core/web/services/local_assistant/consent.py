"""Apply task-level local consent at the existing final execution gate."""
from pathlib import Path

from .policy import LOCAL_RUNTIME_SOURCE_PREFIX, normal_development_call


def _ordinary_read(tool_name, args, workspace):
    root = Path(workspace).resolve()
    if tool_name == "read_file_tool":
        value = args.get("file_path")
    elif tool_name in {"glob_tool", "grep_search_tool"}:
        value = args.get("search_dir") or "."
        if tool_name == "glob_tool":
            pattern = args.get("pattern", "")
            if not isinstance(pattern, str) or Path(pattern).is_absolute() or Path(pattern).drive or ".." in pattern.replace("\\", "/").split("/"):
                return False
    else:
        return False
    if not isinstance(value, str) or not value:
        return False
    target = Path(value)
    return (target if target.is_absolute() else root / target).resolve().is_relative_to(root)


def _native_launcher(runtime):
    from core.infrastructure.native_runtime import is_launcher_assistant_process
    if not is_launcher_assistant_process():
        return False
    from core.infrastructure.launcher_assistant_authority import current_launcher_authority, verify_launcher_authority
    from core.assistant_runtime import native
    return runtime.get("agentId") == native._AGENT_ID and verify_launcher_authority(current_launcher_authority())


def _task_runtime(runtime):
    from core.web.services import agent_directory_service as directory
    from core.web.services.external_agent.approval_binding import external_session_task
    from .runtime import verified_task_runtime
    from .service import task_store
    from core.web.services.external_agent.store import ExternalAgentTaskStoreError
    session_id, agent_id = runtime.get("sessionId", ""), runtime.get("agentId", "")
    task_id = external_session_task(session_id=session_id, agent_id=agent_id)
    if not task_id:
        return None
    try:
        record = task_store(directory.PROJECT_ROOT).get_task(task_id)
        metadata = {"source": "external_agent_task", "taskId": task_id,
                    "effectivePermissionProfile": record["effectivePermissionProfile"]}
        return verified_task_runtime(project_root=directory.PROJECT_ROOT, session_id=session_id,
            agent_id=agent_id, metadata=metadata)
    except (OSError, ValueError, KeyError, ExternalAgentTaskStoreError):
        return None


def local_terminal_wait_allowed(runtime):
    """An active native task may wait until its command/deadline, not eight polls."""
    return (str(runtime.get("runtimeToolSource", "")).startswith(LOCAL_RUNTIME_SOURCE_PREFIX)
            and _task_runtime(runtime) is not None)


def local_approval_policy(runtime, tool_name, args, requirement, permission_preset):
    if _native_launcher(runtime) and tool_name == "personal_assistant_manage_tool":
        from .management_approval import approval_requirement
        return approval_requirement(runtime, args), "request_approval"
    if not str(runtime.get("runtimeToolSource", "")).startswith(LOCAL_RUNTIME_SOURCE_PREFIX):
        return requirement, permission_preset
    task = _task_runtime(runtime)
    risk = requirement[1] if requirement else "execute"
    from core.web.services.tool_catalog import TOOL_CATALOG
    metadata = TOOL_CATALOG.get(tool_name) or {}
    if task and "read_only" in (metadata.get("capabilityTags") or ()):
        if _ordinary_read(tool_name, args, task["workspace"]):
            return None, permission_preset
        return ("always", "read"), "request_approval"
    if (task and risk not in {"network", "destructive"}
            and normal_development_call(tool_name, args, task["workspace"])):
        return None, permission_preset
    # This includes revoked tasks and shell calls outside normal development.
    # Even collaboration modes or an Agent full_access preset cannot silently
    # authorize a publish, delete, arbitrary shell script or privilege change.
    return ("always", risk), "request_approval"
