"""Task-scoped contact card and async messages; no Launcher credentials."""
import json
import sqlite3


def public_contact_card():
    """Service identity shared by native and MCP discovery."""
    return {"contact": "launcher_assistant", "displayName": "Launcher 个人助理", "kind": "external_contact",
            "authorized": False, "availability": "not_authorized", "onlineStatus": "unknown",
            "tool": "launcher_assistant_contact_tool", "scope": "original_launcher_task",
            "requestPath": "请操作者通过 Launcher 向当前 Agent 派遣原生任务；通用项目联系人授权尚未提供。",
            "asynchronous": True}


def contact_card():
    """Resolve messaging authority only for the current native task."""
    card = public_contact_card()
    try:
        from core.web.services import agent_directory_service as directory
        from core.web.services.local_assistant.consent import _task_runtime
        from core.web.services.local_assistant.contact import contacts_for_project
        task = _task_runtime(directory.current_agent_runtime(bound_only=True))
        if task:
            card.update(contacts_for_project(directory.PROJECT_ROOT).describe(task["taskId"]))
            card["onlineStatus"] = "recently_observed" if card["availability"] == "observed_online" else "unknown"
    except Exception:
        card.update(availability="unavailable", onlineStatus="unknown")
    return card


def launcher_assistant_contact_tool(operation="describe", request_id="", content=""):
    from core.web.services import agent_directory_service as directory
    from core.web.services.local_assistant.consent import _task_runtime
    from core.web.services.local_assistant.contact import contacts_for_project
    from core.web.services.local_assistant.service import task_store

    runtime = directory.current_agent_runtime(bound_only=True)
    task_runtime = _task_runtime(runtime)
    if not task_runtime:
        return json.dumps(contact_card(), ensure_ascii=False)
    try:
        task = task_store(directory.PROJECT_ROOT).get_task(task_runtime["taskId"])
        owner = contacts_for_project(directory.PROJECT_ROOT)
        if operation == "describe" and not request_id and not content:
            result = owner.describe(task["taskId"])
        elif operation == "send":
            result = owner.send(task, request_id, content)
        elif operation == "receipt" and not content:
            result = owner.receipt(task, request_id)
        else:
            raise ValueError("contact_operation_invalid")
        return json.dumps(result, ensure_ascii=False)
    except (OSError, ValueError, KeyError, sqlite3.Error):
        return json.dumps({"ok": False, "availability": "unavailable", "message": "Contact state is unavailable or parameters conflict; do not infer delivery."})
