from __future__ import annotations

from typing import Any

from core.runtime_manager import command_queue


RUNTIME_ACTION_COMMANDS = {
    "restart_after_apply": "hot_restart_workbench",
    "resume_self_evolution": "resume_self_evolution",
    "recover_after_crash": "recover_workbench",
    "request_app_exit": "close_workbench",
}


def dispatch_runtime_effect_intent(intent: dict[str, Any]) -> dict[str, Any]:
    action = str(intent.get("action") or "").strip()
    command_type = RUNTIME_ACTION_COMMANDS.get(action)
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


def dispatch_workbench_close_transaction(transaction: dict[str, Any]) -> dict[str, Any]:
    """Submit the backend half of a persisted Electron close transaction.

    Electron remains the exclusive window owner.  A successful command only
    authorizes its later ``window-closed`` acknowledgement.
    """

    mode = str(transaction.get("mode") or "normal").strip().lower()
    command_type = "force_close_workbench" if mode == "force" else "close_workbench"
    result = command_queue.submit_command(
        command_type,
        requested_by="electron_workbench_close",
        args={
            "reason": str(transaction.get("reason") or "electron_workbench_close"),
            "source": "electron_workbench_close",
            "desktopSessionId": str(transaction.get("desktopSessionId") or ""),
            "expectedDesktopSessionRevision": int(transaction.get("expectedDesktopSessionRevision") or 0),
            "workbenchCloseId": str(transaction.get("closeId") or ""),
            "confirmationCloseId": str(transaction.get("confirmationCloseId") or ""),
        },
    )
    return {
        "dispatched": True,
        "commandId": str(result.get("commandId") or ""),
        "accepted": bool(result.get("accepted", True)),
    }
