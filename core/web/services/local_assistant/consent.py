"""Apply task-level local consent at the existing final execution gate."""
import re

from .policy import (LOCAL_REUSE_EVIDENCE_TOOL, LOCAL_RUNTIME_SOURCE_PREFIX, normal_development_call,
                     workspace_paths_allowed)


class LocalTaskScopeError(PermissionError):
    """An invocation is outside its task grant and cannot receive an approval."""


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
    try:
        task_id = external_session_task(session_id=session_id, agent_id=agent_id)
        record = task_store(directory.PROJECT_ROOT).get_task(task_id)
        metadata = {"source": "external_agent_task", "taskId": task_id,
                    "effectivePermissionProfile": record["effectivePermissionProfile"]}
        return verified_task_runtime(project_root=directory.PROJECT_ROOT, session_id=session_id,
            agent_id=agent_id, metadata=metadata)
    except (OSError, ValueError, KeyError, ExternalAgentTaskStoreError):
        return None


def local_terminal_wait_allowed(runtime):
    """An active native task may wait until its command/deadline, not eight polls."""
    if not str(runtime.get("runtimeToolSource", "")).startswith(LOCAL_RUNTIME_SOURCE_PREFIX):
        return False
    _active_task(runtime)
    return True


def _active_task(runtime):
    task = _task_runtime(runtime)
    if task is None:
        raise LocalTaskScopeError("本次派遣的工作区授权已失效，请结束任务并将结果交回个人助理。")
    return task


def require_local_workspace_write(runtime):
    """Require a current server-bound worktree write grant, even after tool selection."""
    if runtime.get("runtimeToolSource") == LOCAL_RUNTIME_SOURCE_PREFIX + "workspace_write":
        task = _active_task(runtime)
        if task["profile"] == "workspace_write":
            return task
    raise LocalTaskScopeError("本地复用记录工具仅供持有工作区写权限的当前 Launcher 派遣任务使用。")


def local_approval_policy(runtime, tool_name, args, requirement, permission_preset):
    if tool_name == LOCAL_REUSE_EVIDENCE_TOOL:
        require_local_workspace_write(runtime)
        return None, permission_preset
    if _native_launcher(runtime) and tool_name == "personal_assistant_manage_tool":
        from .management_approval import approval_requirement
        return approval_requirement(runtime, args), "request_approval"
    if not str(runtime.get("runtimeToolSource", "")).startswith(LOCAL_RUNTIME_SOURCE_PREFIX):
        return requirement, permission_preset
    task = _active_task(runtime)
    workspace = task["workspace"]
    if not workspace_paths_allowed(tool_name, args, workspace):
        raise LocalTaskScopeError("工具路径超出本次派遣的工作区，请使用任务工作区内的路径。")
    if tool_name in {"cli_tool", "exec_command"}:
        command = args.get("command" if tool_name == "cli_tool" else "cmd")
        if isinstance(command, str):
            if re.match(r"(?i)^\s*rg(?:\.exe)?(?:\s|$)", command):
                raise LocalTaskScopeError("本次派遣可直接用 grep_search_tool 搜源码，或用 glob_tool 查文件名。请用对应工具继续，路径限定在任务工作区。")
            if re.fullmatch(r"(?i)\s*python(?:\.exe)?\s+scripts[\\/]reuse_research_evidence\.py\s+record\s+--help\s*", command):
                raise LocalTaskScopeError("LOCAL_ONLY 复用记录请使用 record_local_reuse_evidence_tool，其参数由工具直接提供。")
    risk = requirement[1] if requirement else "execute"
    if risk not in {"network", "destructive"} and normal_development_call(tool_name, args, workspace):
        return None, permission_preset
    # The target Agent's standing preset cannot grant consent for a dispatched task.
    return ("always", risk), "request_approval"
