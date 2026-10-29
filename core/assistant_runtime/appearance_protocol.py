"""Pure closed appearance contracts for the existing private main transport."""
from __future__ import annotations
import re

APPEARANCE_ACTIONS = frozenset({"launcher_theme_get", "launcher_theme_set", "operator_image_upload"})
IMAGE_SELECTION_SECONDS = 120

def validate_request(action, request):
    if type(request) is not dict:
        raise ValueError("Invalid appearance request")
    if action == "launcher_theme_get":
        valid = request == {"operation": "read"}
    elif action == "launcher_theme_set":
        valid = set(request) == {"operation", "theme"} and request["operation"] == "set" and type(request["theme"]) is str and request["theme"] in {"dark", "light"}
    elif action == "operator_image_upload":
        valid = set(request) == {"operation", "kind"} and request["operation"] == "import" and type(request["kind"]) is str and request["kind"] in {"avatar", "background"}
    else:
        valid = False
    if not valid:
        raise ValueError("Invalid appearance request")
    return dict(request)

def unavailable(action, request):
    if action == "operator_image_upload":
        return {"schemaVersion":1, **request, "code":"unavailable", "verified":False}
    return {"schemaVersion":1, "operation":request["operation"], "code":"unavailable"}

def validate_result(action, request, result):
    if type(result) is not dict or type(result.get("schemaVersion")) is not int or result["schemaVersion"] != 1 or result.get("operation") != request["operation"]:
        raise ValueError("Invalid appearance result")
    if action == "operator_image_upload":
        required = {"schemaVersion", "operation", "kind", "code", "verified"}
        if not required <= result.keys() or result.keys() - required - {"selection"} or result.get("kind") != request["kind"] or type(result.get("code")) is not str or result["code"] not in {"applied", "cancelled", "unavailable", "invalid_image", "not_applied", "unknown", "busy"} or type(result.get("verified")) is not bool:
            raise ValueError("Invalid appearance result")
        applied = result["code"] == "applied"
        selection = result.get("selection")
        prefix = "workspace/user_avatars" if request["kind"] == "avatar" else "theme_backgrounds"
        if applied:
            if result["verified"] is not True or type(selection) is not str or not re.fullmatch(prefix + r"/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,239}\.(?i:png|jpg|jpeg|webp)", selection):
                raise ValueError("Invalid appearance result")
        elif result["verified"] is not False or "selection" in result:
            raise ValueError("Invalid appearance result")
    else:
        required = {"schemaVersion", "operation", "code"}
        if not required <= result.keys() or result.keys() - required - {"theme", "workbenchSync", "assistantSync", "authorityStatus"} or type(result.get("code")) is not str or result["code"] not in {"read", "applied", "conflict", "unknown", "unavailable", "persistence_failed"}:
            raise ValueError("Invalid appearance result")
        if result["code"] in {"conflict", "unknown"} and action != "launcher_theme_set":
            raise ValueError("Invalid appearance result")
        if "authorityStatus" in result and (action != "launcher_theme_set" or type(result["authorityStatus"]) is not str or result["authorityStatus"] not in {"committed", "unknown"}):
            raise ValueError("Invalid appearance result")
        if "assistantSync" in result and (action != "launcher_theme_set" or type(result["assistantSync"]) is not str or result["assistantSync"] not in {"applied", "conflict", "unavailable", "unknown"}):
            raise ValueError("Invalid appearance result")
        if "workbenchSync" in result and (action != "launcher_theme_set" or result["code"] not in {"applied", "conflict", "unknown", "unavailable"} or type(result["workbenchSync"]) is not str or result["workbenchSync"] not in {"applied", "conflict", "unavailable", "unknown"}):
            raise ValueError("Invalid appearance result")
        if result["code"] in {"read", "applied"}:
            if result["code"] != ("read" if action == "launcher_theme_get" else "applied") or type(result.get("theme")) is not str or result["theme"] not in {"dark", "light"} or action == "launcher_theme_set" and result["theme"] != request["theme"]:
                raise ValueError("Invalid appearance result")
        elif "theme" in result:
            raise ValueError("Invalid appearance result")
    return dict(result)
