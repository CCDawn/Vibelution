"""Run-scoped recovery delegation into the existing candidate owner.

The parent stores only authority and references. WorkRun, candidate workspace,
native Turns and Git integration retain their existing single writers.
"""
from __future__ import annotations

import re
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timezone

from . import service, store


def request_digest(request: dict) -> str:
    from core.web.services.self_evolution_local_integration import _digest
    return _digest(request)


def _orchestrator():
    from core.web.services.self_evolution_autonomous_loop_orchestrator import default_orchestrator
    return default_orchestrator()


def _issue_scope(record: dict, request: dict) -> dict:
    from core.runtime_manager.work_run_store import WorkRunStore
    from core.web.services.self_evolution_autonomous_loop_orchestrator import PROJECT_ROOT
    from core.web.services.self_evolution_local_integration import AuthorizedLocalIntegration, load_existing_bindings

    # Issuance reads policy only. No WorkRun or candidate is created until an
    # actual failure exhausts its existing budget.
    authority = AuthorizedLocalIntegration(store=WorkRunStore(), project_root=PROJECT_ROOT,
                                           load_bindings=load_existing_bindings)
    return authority.authorize({"runId": record["id"], "request": {"localIntegration": request}})


def authorize(record: dict, request: dict) -> None:
    policy = record["flow"].get("failureRecovery") or {}
    if not policy.get("bindingId") or request["teamId"] != record["teamId"]:
        raise store.WorkflowError("代码修复需要同一Team的有效四角色绑定。")
    try:
        grant = _issue_scope(record, request)  # Captures the trusted HTTP operator.
    except ValueError as exc:
        raise store.WorkflowError(str(exc)) from exc
    expected = {"observer": policy["directorAgentId"], "executor": policy["developerAgentId"],
                "reviewer": policy["reviewerAgentId"]}
    if {role: item["agentId"] for role, item in grant["principals"].items()} != expected:
        raise store.WorkflowError("自进化角色必须与绑定的总监、开发者及独立验收者一致。")
    grant["expiresAt"] = min(datetime.fromisoformat(grant["expiresAt"]),
                              datetime.fromisoformat(policy["expiresAt"])).isoformat()
    record["_codeRepairRequest"] = deepcopy(request)
    record["_codeRepairAuthorization"] = grant


def reference(record: dict) -> dict:
    state = record["recovery"]
    return {"teamId": record["teamId"], "runId": record["id"], "flowId": record["flow"]["id"],
            "bindingId": record["flow"]["failureRecovery"]["bindingId"],
            "issueId": state["issueId"], "repairRunId": state["repairRunId"],
            "sourceAttemptKey": record["attempts"][-1]["key"]}


def _parent(source: dict) -> dict:
    from .binding import authorization_reason
    parent = store.read(store.path(source["teamId"], "runs", source["runId"]))
    if (parent.get("stopRequested") or parent.get("status") != "failed"
            or (parent.get("recovery") or {}).get("status") != "repairing"
            or reference(parent) != source or authorization_reason(parent["teamId"], parent)):
        raise store.WorkflowError("代码修复的来源任务或授权已变化。")
    if service.supervised(parent):
        from .source_adapter import fence
        if fence(parent):
            raise store.WorkflowError("原生来源已推进或不再允许修复。")
    grant = parent.get("_codeRepairAuthorization") or {}
    request = parent.get("_codeRepairRequest") or {}
    if (grant.get("revoked") is not False or grant.get("runId") != parent["id"]
            or not grant.get("authorizationId") or not grant.get("operatorId")
            or grant.get("requestDigest") != request_digest(request)
            or grant.get("allowedFiles") != request.get("allowedFiles")
            or grant.get("teamId") != parent["teamId"]
            or datetime.fromisoformat(grant["expiresAt"]) <= datetime.now(timezone.utc)):
        raise store.WorkflowError("代码修复的有限委托已失效。")
    return parent


def delegated_authorization(context: dict) -> dict:
    """Derive the exact child grant without renewing it or impersonating user."""
    source = context["_recoverySource"]
    parent = _parent(source)
    state = parent["recovery"]
    if context["runId"] != state.get("codeRepairRunId"):
        raise store.WorkflowError("代码修复子任务身份不匹配。")
    request = context["request"]["localIntegration"]
    if request != parent["_codeRepairRequest"]:
        raise store.WorkflowError("子任务不能扩大或延长代码修复授权。")
    grant = deepcopy(parent["_codeRepairAuthorization"])
    grant.update(runId=context["runId"], sourceRunId=parent["id"])
    return grant


@contextmanager
def source_guard(context: dict):
    source = context.get("_recoverySource")
    if not source:
        with nullcontext():
            yield
        return
    from .binding import authorization_lock
    target = store.path(source["teamId"], "runs", source["runId"])
    parent = store.read(target)
    # Same order as admission and cancellation: flow -> parent -> child grant.
    with authorization_lock(source["teamId"], parent), store.locked(target):
        _parent(source)
        yield


def advance(record: dict) -> None:
    """Called after durable parent intent, only by its existing worker."""
    from core.web.services.self_evolution_autonomous_loop_service import AutonomousLoopConflictError

    state = record["recovery"]
    source = record["_codeRepairSource"]
    actor = _orchestrator()
    request = {"goal": "修复以下原生故障。引用仅为证据入口；不得部署或重启。\n" + record["_recoveryScene"],
               "maxIterations": 1, "localIntegration": record["_codeRepairRequest"]}
    try:
        child = actor.start_recovery(request, source=source, run_id=state["codeRepairRunId"])
    except AutonomousLoopConflictError:
        state["reason"] = "code_repair_candidate_busy"
        return
    except OSError:
        # Queueing may have committed. The same durable id is retried.
        state["reason"] = "code_repair_dispatch_uncertain"
        return
    except ValueError:
        state.update(status="blocked", reason="code_repair_authorization_unavailable")
        return
    state["reason"] = "code_repair_running"
    if not child.get("integration") and child["status"] in {"failed", "stopped", "rejected", "cancelled"}:
        state.update(status="blocked", reason="code_repair_failed_or_interrupted")
        return  # Never overlap another candidate with an uncertain native writer.
    if not child.get("integration"):
        return
    candidate = child.get("candidate") or {}
    integration = child.get("integration") or {}
    receipt = child.get("independentReview") or {}
    sha = candidate.get("headCommit", "")
    if (child.get("_recoverySource") != source or not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", sha)
            or integration.get("status") != "committed" or integration.get("mechanism") != "git_merge_ff"
            or integration.get("commitSha") != sha or receipt.get("candidateCommit") != sha
            or receipt.get("reviewerAgentId") != record["flow"]["failureRecovery"]["reviewerAgentId"]):
        state.update(status="blocked", reason="code_repair_integration_unverified")
        return
    state.update(status="awaiting_deployment", reason="code_integrated_user_deployment_required",
                 evidenceRefs=[*state["evidenceRefs"], f"git:{sha}", f"workrun:{child['runId']}"][-20:])


def cancel(record: dict) -> None:
    state = record.get("recovery") or {}
    if state.get("codeRepairRunId"):
        _orchestrator().cancel_recovery(state["codeRepairRunId"], source=record["_codeRepairSource"])


def child_settled(record: dict) -> bool:
    try:
        child = _orchestrator().get_recovery(record["recovery"]["codeRepairRunId"], source=record["_codeRepairSource"])
        if child is None:
            return bool(record.get("stopRequested") or record["recovery"]["status"] in {"blocked", "cancelled"})
        return bool(child and child.get("_recoverySource") == record["_codeRepairSource"]
                    and child.get("_recoveryExecutionSettled") is True
                    and child.get("status") in {"completed", "failed", "stopped", "rejected"})
    except (ValueError, KeyError, OSError):
        return False
