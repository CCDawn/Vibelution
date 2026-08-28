from __future__ import annotations

from typing import Any

from core.runtime_manager import command_queue


RUNTIME_ACTION_COMMANDS = {
    "restart_after_apply": "hot_restart_workbench",
    "resume_self_evolution": "resume_self_evolution",
    "recover_after_crash": "recover_workbench",
    "request_app_exit": "close_workbench",
}

# Hot restart is session-scoped: the runtime-manager daemon fails a
# hot_restart_workbench command without a sessionId (HotRestartSessionRequired)
# and that sticky failure poisons the workbench lifecycle.  When the intent
# carries no trusted source session, fall back to a plain restart instead.
RUNTIME_ACTION_SESSION_FALLBACK_COMMANDS = {
    "restart_after_apply": "restart_workbench",
}


def _runtime_command_for_action(action: str, source_session_id: str) -> str | None:
    if source_session_id:
        return RUNTIME_ACTION_COMMANDS.get(action)
    return RUNTIME_ACTION_SESSION_FALLBACK_COMMANDS.get(action) or RUNTIME_ACTION_COMMANDS.get(
        action
    )


def dispatch_runtime_effect_intent(intent: dict[str, Any]) -> dict[str, Any]:
    action = str(intent.get("action") or "").strip()
    source_session_id = str(intent.get("sourceSessionId") or "").strip()
    command_type = _runtime_command_for_action(action, source_session_id)
    if not command_type:
        return {"dispatched": False, "reason": "not_runtime_effect"}
    result = command_queue.submit_command(
        command_type,
        requested_by=str(intent.get("actorType") or "launcher_lifecycle"),
        args={
            "reason": str(intent.get("reason") or action),
            "allowActiveSessionId": str(intent.get("sourceSessionId") or ""),
            "allowActiveRunId": str(intent.get("sourceRunId") or ""),
            "sourceRunId": str(intent.get("sourceRunId") or ""),
            "sourceTaskId": str(intent.get("sourceTaskId") or ""),
            "sourceWorktree": str(intent.get("sourceWorktree") or ""),
            "lifecycleIntentId": str(intent.get("intentId") or ""),
        },
    )
    return {
        "dispatched": True,
        "commandId": str(result.get("commandId") or ""),
        "accepted": bool(result.get("accepted", True)),
    }


def dispatch_workbench_close_transaction(
    transaction: dict[str, Any],
    *,
    request_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit the backend half of a persisted Electron close transaction.

    Electron remains the exclusive window owner.  A successful command only
    authorizes its later ``window-closed`` acknowledgement.
    """

    mode = str(transaction.get("mode") or "normal").strip().lower()
    command_type = "force_close_workbench" if mode == "force" else "close_workbench"
    args = {
        "reason": str(transaction.get("reason") or "electron_workbench_close"),
        "source": "electron_workbench_close",
        "desktopSessionId": str(transaction.get("desktopSessionId") or ""),
        "expectedDesktopSessionRevision": int(transaction.get("expectedDesktopSessionRevision") or 0),
        "workbenchCloseId": str(transaction.get("closeId") or ""),
        "confirmationCloseId": str(transaction.get("confirmationCloseId") or ""),
        "externalWindowOwner": "electron",
    }
    if request_audit:
        args["requestAudit"] = request_audit
    result = command_queue.submit_command(
        command_type,
        requested_by="electron_workbench_close",
        args=args,
    )
    return {
        "dispatched": True,
        "commandId": str(result.get("commandId") or ""),
        "accepted": bool(result.get("accepted", True)),
    }
