"""Assistant-governed branch instance cleanup plan and execute actions.

``branch_cleanup_plan`` is a read-only cleanup view over the launcher branch
instance registry; ``branch_cleanup_execute`` is a destructive action that
re-checks every hard gate in this process before delegating to the existing
launcher cleanup executor. Active coordination claims are absolute: no flag
bypasses them, and an unavailable coordination backend can never prove a
worktree unowned, so it blocks deletion too (fail-closed).

Both actions resolve the managed integration checkout explicitly (host
dispatch registry, then machine instances registry); the redirected assistant
profile ``PROJECT_ROOT`` is never treated as a Git workspace.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BranchCleanupPlan(Arguments):
    pass


class BranchCleanupExecute(Arguments):
    instance_ids: list[str] = Field(min_length=1, max_length=50)
    allow_unmerged: bool = False
    allow_dirty: bool = False


_MAX_INSTANCE_ID = 300
_ACTIVE_AGENT_STATES = frozenset({"active", "paused"})
_ACTIVE_CLAIM_STATUSES = frozenset({"active", "ready"})
_IN_FLIGHT_PHASES = frozenset({"opening", "starting", "restarting"})

_REASON_ORDER = (
    "PROTECTED_BRANCH", "CURRENT_WORKSPACE", "INSTANCE_IN_FLIGHT",
    "CLAIM_ACTIVE", "CLAIM_UNPROVABLE", "UNMERGED", "DIRTY",
)

_APPROVAL_GUIDANCE = {
    "ok": False, "status": "approval_required", "tool": "personal_assistant_manage_tool",
    "message": "使用 manage，action 保持不变，arguments_json 为这些参数的JSON；等待原生审批后执行。",
}


def contracts() -> dict[str, dict[str, Any]]:
    """Closed descriptors for the launcher-local allowlist."""
    return {
        "branch_cleanup_plan": {
            "action": "branch_cleanup_plan", "governed": False,
            "description": (
                "只读列出全部已注册分支实例的清理视图：完整 instance_id、slug 与分支名、worktree 目录、"
                "注册与后端状态、merged_to_main、dirty、活跃 claim（agent+stage）、eligible 与不可清理原因 reasons；"
                "不删除任何数据。执行删除前必须先调用本动作，把结果给用户看，等用户明确确认要删哪些实例后，"
                "再用 branch_cleanup_execute 携带完整 instance_ids 执行。"),
            "parameters": BranchCleanupPlan.model_json_schema(),
        },
        "branch_cleanup_execute": {
            "action": "branch_cleanup_execute", "governed": True,
            "description": (
                "经原生审批删除选中的分支实例：停止实例、删除 worktree 目录与本地分支，并把注册表条目转为 inactive；"
                "远端 ref 永不触碰。执行前必须先运行 branch_cleanup_plan，把 plan 结果给用户看并等用户确认要删哪些，"
                "instance_ids 必须原样使用 plan 返回的完整 id。硬门：main 与受保护分支、当前工作区一律拒绝；"
                "未合入 main 默认拒，仅 allow_unmerged=true 放行；脏 worktree 默认拒，仅 allow_dirty=true 放行；"
                "存在活跃 claim 一律拒绝，任何标志都不能越过；协调后端不可用时同样按不可证明拒绝。"
                "被拒实例连同原因返回，不影响其余实例。"),
            "parameters": BranchCleanupExecute.model_json_schema(),
        },
    }


def execute(action: str, parameters: dict, runtime: dict, *, governed: bool = False) -> dict:
    """Dispatch the two closed actions; identity/approval come from the wrapper."""
    if action == "branch_cleanup_plan":
        return plan(runtime)
    if action == "branch_cleanup_execute":
        if governed is not True:
            return {**_APPROVAL_GUIDANCE, "action": action}
        return execute_cleanup(parameters, runtime)
    return {"ok": False, "status": "blocked", "error": "unknown_action"}


def _root_failure(error: str, message: str) -> dict:
    return {"ok": False, "status": "unavailable", "action": "branch_cleanup_plan",
            "error": error, "message": message}


def _resolve_integration_root(runtime: dict | None) -> tuple[Path | None, dict | None]:
    """Resolve the managed integration checkout without trusting model input.

    The tool ``runtime`` carries only agent/session/turn identity (no project
    root), so the root comes from the host-authorized dispatch project registry
    first, then from the machine instances registry as a last fallback. Zero or
    ambiguous roots stay fail-closed with a readable error; the redirected
    assistant profile ``PROJECT_ROOT`` is never guessed as a workspace.
    """
    roots = _dispatch_registered_roots()
    if len(roots) == 1:
        return roots[0], None
    if len(roots) > 1:
        return None, _root_failure("project_root_ambiguous",
            "宿主登记了多个项目根，无法确定要查看哪个工作台的分支实例；请先在 Launcher 聚焦目标项目后重试，不自动猜测。")
    roots = _registry_project_roots()
    if len(roots) == 1:
        return roots[0], None
    if len(roots) > 1:
        return None, _root_failure("project_root_ambiguous",
            "本机实例注册表存在多个候选项目根，无法确定目标工作台；请先在 Launcher 打开目标项目后重试，不自动猜测。")
    return None, _root_failure("project_root_unavailable",
        "无法确定当前工作台项目根：宿主进程没有已登记的项目根可用；请先在 Launcher 打开项目后重试，不把助理目录当作 Git 工作区。")


def _dispatch_registered_roots() -> tuple[Path, ...]:
    from core.assistant_runtime import actions

    binding = actions._binding
    service = binding[0] if isinstance(binding, tuple) and binding else None
    getter = getattr(service, "registered_project_roots", None)
    if getter is None:
        return ()
    try:
        return tuple(getter())
    except Exception:
        return ()


def _registry_project_roots() -> tuple[Path, ...]:
    """Last-resort roots from machine instances registry rows, git-proven."""
    from core.infrastructure.branch_workspace import resolve_branch_workspace
    from core.runtime_manager import instances_registry as registry

    try:
        payload = registry.load_registry()
    except (OSError, ValueError):
        return ()
    roots: list[Path] = []
    for entry in (payload.get("instances") or {}).values():
        if not isinstance(entry, dict):
            continue
        raw = str(entry.get("projectRoot") or "").strip()
        if not raw:
            continue
        try:
            resolved = Path(raw).expanduser().resolve()
            resolve_branch_workspace(resolved)
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def plan(runtime: dict | None = None) -> dict:
    """Read-only cleanup view; never mutates instances, branches or registry."""
    from core.launcher import service as launcher_service

    checkout, failure = _resolve_integration_root(runtime)
    if failure is not None:
        return failure
    payload = launcher_service.list_launcher_branch_instances(include_cleanup_metadata=True, checkout=checkout)
    return {"ok": True, "action": "branch_cleanup_plan", "status": "observed",
            **_plan_view(payload)}


def execute_cleanup(parameters: dict, runtime: dict | None = None) -> dict:
    """Hard-gate every instance, then delegate accepted ids to the executor."""
    try:
        args = BranchCleanupExecute.model_validate(parameters)
    except Exception:
        return {"ok": False, "status": "blocked", "action": "branch_cleanup_execute",
                "error": "invalid_input",
                "message": "参数不符合 branch_cleanup_execute 的 schema；请重新 describe 并按 plan 结果提供完整 instance_ids。"}
    from core.launcher import service as launcher_service

    wanted: list[str] = []
    for raw in args.instance_ids:
        instance_id = str(raw).strip()
        if instance_id and len(instance_id) <= _MAX_INSTANCE_ID and instance_id not in wanted:
            wanted.append(instance_id)
    if not wanted:
        return {"ok": False, "status": "blocked", "action": "branch_cleanup_execute",
                "error": "invalid_input",
                "message": "instance_ids 必须包含 plan 返回的完整非空实例 id。"}
    checkout, failure = _resolve_integration_root(runtime)
    if failure is not None:
        return {**failure, "action": "branch_cleanup_execute"}
    payload = launcher_service.list_launcher_branch_instances(include_cleanup_metadata=True, checkout=checkout)
    by_id = {
        str(item.get("id") or ""): dict(item)
        for item in payload.get("items") or []
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    claims = _resolve_claims(list(by_id.values()), _integration_root(payload))
    accepted: list[str] = []
    rejected: list[dict[str, Any]] = []
    for instance_id in wanted:
        item = by_id.get(instance_id)
        if item is None:
            rejected.append({"instanceId": instance_id, "reason": "INSTANCE_NOT_FOUND"})
            continue
        reasons = _reject_reasons(item, claims.get(instance_id) or {},
                                 allow_unmerged=args.allow_unmerged, allow_dirty=args.allow_dirty)
        if reasons:
            rejected.append({"instanceId": instance_id,
                             "branch": _branch(item), "shortName": _short_name(item),
                             "reasons": reasons})
            continue
        accepted.append(instance_id)
    cleaned: list[Any] = []
    failed: list[Any] = []
    skipped: list[Any] = []
    result: dict[str, Any] | None = None
    if accepted:
        from core.launcher.branch_instance_cleanup import cleanup_branch_instances

        result = cleanup_branch_instances(accepted, confirm=True, list_payload=payload, checkout=checkout)
        cleaned, failed, skipped = result.get("cleaned") or [], result.get("failed") or [], result.get("skipped") or []
    ok = not rejected and not failed and (result is None or result.get("ok") is True)
    if ok:
        status = "applied"
    elif cleaned:
        status = "partial"
    else:
        status = "rejected"
    return {"ok": ok, "action": "branch_cleanup_execute", "status": status,
            "requested": len(wanted), "rejected": rejected, "cleaned": cleaned,
            "failed": failed, "skipped": skipped}


def _plan_view(payload: dict[str, Any]) -> dict[str, Any]:
    items = [dict(item) for item in payload.get("items") or [] if isinstance(item, dict)]
    claims = _resolve_claims(items, _integration_root(payload))
    rows = [_plan_row(item, claims.get(str(item.get("id") or "")) or {}) for item in items]
    return {"instances": rows, "total": len(rows)}


def _plan_row(item: dict[str, Any], claim: dict[str, Any]) -> dict[str, Any]:
    runtime = item.get("runtime") if isinstance(item.get("runtime"), dict) else {}
    backend = runtime.get("backend") if isinstance(runtime.get("backend"), dict) else {}
    active_claim = claim.get("claim")
    return {
        "instanceId": str(item.get("id") or ""),
        "slug": _short_name(item),
        "branch": _branch(item),
        "kind": str(item.get("kind") or ""),
        "worktreeRoot": str(item.get("path") or ""),
        "registeredStatus": str(item.get("status") or runtime.get("registryStatus") or "").strip().lower(),
        "backendAlive": bool(backend.get("alive") or item.get("alive")),
        "mergedToMain": bool(item.get("mergedToMain")),
        "dirty": bool(item.get("dirty")),
        "activeClaim": dict(active_claim) if isinstance(active_claim, dict) else None,
        "eligible": not _reject_reasons(item, claim, allow_unmerged=False, allow_dirty=False),
        "reasons": _reject_reasons(item, claim, allow_unmerged=False, allow_dirty=False),
    }


def _reject_reasons(
    item: dict[str, Any],
    claim: dict[str, Any],
    *,
    allow_unmerged: bool,
    allow_dirty: bool,
) -> list[str]:
    """Reasons this instance cannot be deleted under the requested flags.

    Claim gates ignore flags: an active coordination claim always blocks, and
    an unprovable coordination state can never become a deletion permission.
    """
    from core.runtime_manager.instances_registry import IN_FLIGHT_STATUSES

    branch = _branch(item)
    reasons: set[str] = set()
    if str(item.get("id") or "") == "main" or str(item.get("kind") or "") == "main" or branch in _protected_branches():
        reasons.add("PROTECTED_BRANCH")
    elif item.get("current"):
        reasons.add("CURRENT_WORKSPACE")
    runtime = item.get("runtime") if isinstance(item.get("runtime"), dict) else {}
    status = str(item.get("status") or runtime.get("registryStatus") or "").strip().lower()
    phase = str(item.get("phase") or runtime.get("phase") or "").strip().lower()
    if status in IN_FLIGHT_STATUSES or phase in _IN_FLIGHT_PHASES:
        reasons.add("INSTANCE_IN_FLIGHT")
    if claim.get("claim") is not None:
        reasons.add("CLAIM_ACTIVE")
    elif claim.get("provable") is False:
        reasons.add("CLAIM_UNPROVABLE")
    if not bool(item.get("mergedToMain")) and str(item.get("kind") or "") != "retired":
        has_local_commits = bool(branch or str(item.get("head") or "").strip())
        if has_local_commits and not allow_unmerged:
            reasons.add("UNMERGED")
    if bool(item.get("dirty")) and not allow_dirty:
        reasons.add("DIRTY")
    return [reason for reason in _REASON_ORDER if reason in reasons]


def _resolve_claims(items: list[dict[str, Any]], integration_root: Path) -> dict[str, dict[str, Any]]:
    """Map instance id -> claim evidence for its worktree root and branch.

    Mirrors the managed closeout ownership check: the coordination registry's
    active/paused agents matched by worktree path or branch, plus the worktree
    claim binding resolved against active registry claims. Registry failure
    keeps ``provable`` false so deletion stays blocked (fail-closed).
    """
    status = _coordination_status(integration_root)
    agents = status.get("agents") if isinstance(status, dict) else None
    claims = status.get("claims") if isinstance(status, dict) else None
    provable = isinstance(agents, list)
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        instance_id = str(item.get("id") or "")
        branch = _branch(item)
        found: dict[str, str] | None = None
        if provable:
            found = _registry_agent_claim(item, branch, agents)
        if found is None:
            found = _binding_claim(item, claims)
        result[instance_id] = {"claim": found, "provable": provable}
    return result


def _registry_agent_claim(item: dict[str, Any], branch: str, agents: Any) -> dict[str, str] | None:
    task_root = _norm_path(item.get("path"))
    if not task_root and not branch:
        return None
    for agent in agents if isinstance(agents, list) else []:
        if not isinstance(agent, dict) or agent.get("state") not in _ACTIVE_AGENT_STATES:
            continue
        worktree_match = bool(agent.get("worktree")) and _norm_path(agent.get("worktree")) == task_root and bool(task_root)
        branch_match = bool(branch) and str(agent.get("branch") or "") == branch
        if worktree_match or branch_match:
            return {"agentId": str(agent.get("id") or ""), "stage": str(agent.get("stage") or "")}
    return None


def _binding_claim(item: dict[str, Any], claims: Any) -> dict[str, str] | None:
    binding = _read_claim_binding(item.get("path"))
    if binding is None or not isinstance(claims, list):
        return None
    claim_id = str(binding.get("claim_id") or "")
    if not claim_id:
        return None
    for claim in claims:
        if not isinstance(claim, dict) or str(claim.get("id") or "") != claim_id:
            continue
        if claim.get("status") not in _ACTIVE_CLAIM_STATUSES:
            return None
        return {"agentId": str(binding.get("agent_id") or claim.get("agentId") or ""), "stage": ""}
    return None


def _read_claim_binding(worktree: Any) -> dict[str, Any] | None:
    """Read the worktree-level vibelution-claim.json binding, if any."""
    root = Path(str(worktree or "").strip())
    if not root.is_dir():
        return None
    from core.infrastructure import git_process

    completed = git_process.run_git(
        ["rev-parse", "--absolute-git-dir"], cwd=str(root),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False, timeout=10.0,
    )
    if completed.returncode != 0:
        return None
    git_dir = Path(str(completed.stdout or "").strip())
    if not git_dir.is_absolute():
        git_dir = root / git_dir
    path = git_dir / "vibelution-claim.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or not str(payload.get("claim_id") or ""):
        return None
    return payload


def _coordination_status(project_root: Path) -> dict[str, Any] | None:
    """Query the external coordination registry; None means unprovable."""
    script = _coordination_script()
    if script is None:
        return None
    try:
        completed = subprocess.run(
            [sys.executable, str(script), str(project_root), "status", "--json"],
            cwd=str(project_root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False, timeout=20.0,
            **_no_window_kwargs(),
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _coordination_script() -> Path | None:
    """Same coordination registry script the managed closeout path uses."""
    candidates = (
        Path.home() / ".codex" / "skills" / "briefbound-project-memory" / "scripts" / "agent_coordination.py",
        Path.home() / ".codex" / "skills" / "ccdawn-dawn-agent-html-memory" / "scripts" / "agent_work_guard.py",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _no_window_kwargs() -> dict[str, Any]:
    """Never allocate a visible console (development-standard 8.0)."""
    if os.name != "nt":
        return {}
    kwargs: dict[str, Any] = {"creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0))}
    return kwargs


def _integration_root(payload: dict[str, Any]) -> Path:
    from core.runtime_manager.constants import PROJECT_ROOT

    return Path(str(payload.get("integrationRoot") or PROJECT_ROOT))


def _protected_branches() -> frozenset[str]:
    from core.launcher.branch_instance_cleanup import PROTECTED_BRANCHES

    return PROTECTED_BRANCHES


def _norm_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return os.path.normcase(str(Path(text).resolve()))
    except OSError:
        return os.path.normcase(text)


def _branch(item: dict[str, Any]) -> str:
    branch = str(item.get("branch") or "").strip()
    if branch.startswith("refs/heads/"):
        branch = branch.removeprefix("refs/heads/")
    return branch


def _short_name(item: dict[str, Any]) -> str:
    return str(item.get("shortName") or item.get("branch") or item.get("id") or "").strip()
