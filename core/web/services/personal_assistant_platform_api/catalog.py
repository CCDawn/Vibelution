"""Bounded OpenAPI discovery for the personal assistant platform API.

Discovery describes registered routes and the separately governed ways an
assistant may use them. It never executes an HTTP operation or treats route
discovery as authorization.
"""

from __future__ import annotations

import copy
import json
import time
from collections import deque
from collections.abc import Callable, Iterator
from typing import Any

STANDARD_METHODS = ("get", "post", "put", "patch", "delete")
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50
MAX_SCHEMA_COMPONENTS = 32
MAX_DESCRIPTION_CHARS = 48_000

_SAFE_AGENT_FIELDS = (
    "displayName",
    "llmBindings",
    "personaProfile",
    "taskProfile",
    "reasoningEffortBySlot",
    "contextCompressionPolicy",
    "promptTemplateId",
)

_NATIVE_ACTIONS: dict[tuple[str, str], dict[str, Any]] = {
    ("post", "/api/agents"): {
        "action": "agent_create",
        "constraints": [
            "Creates a normal Agent with the fixed message-collaboration permission.",
            "Does not grant file, command, or authorization-management permissions.",
        ],
    },
    ("patch", "/api/agents/{agent_id}"): {
        "action": "agent_update",
        "constraints": [
            "Updates are limited to SAFE_AGENT_FIELDS.",
            "Identity, permissions, and lifecycle changes require native management approval.",
        ],
    },
    ("patch", "/api/agents/{agent_id}/avatar"): {
        "action": "agent_avatar",
        "constraints": ["Uses an existing avatar option or restores the model default."],
    },
    ("put", "/api/config/language"): {
        "action": "settings_update",
        "constraints": ["Uses the bounded settings update action."],
    },
    ("post", "/api/config/draft/providers/{provider_id}/models"): {
        "action": "model_add",
        "constraints": [
            "Adds a model to an existing provider through the persistence adapter.",
            "This is not arbitrary HTTP writing and does not accept a new provider, secret, or network address.",
        ],
    },
}

# The HTTP specification remains the documentation authority. These entries
# identify bounded semantic adapters, never an operator-token HTTP dispatcher.
_EXTENDED_ACTIONS = {
    ("get", "/api/sessions"): "workspace_list",
    ("get", "/api/session-archive"): "workspace_list",
    ("get", "/api/teams"): "workspace_list",
    ("get", "/api/chat-rooms"): "workspace_list",
    ("get", "/api/personal-assistant/settings"): "assistant_settings",
    ("patch", "/api/personal-assistant/settings"): "assistant_settings_update",
    ("patch", "/api/personal-assistant/settings/model"): "assistant_model_set",
    ("get", "/api/agents/{agent_id}/plugins/virtual-human-life/companions/dialogue-settings"): "dialogue_settings",
    ("put", "/api/agents/{agent_id}/plugins/virtual-human-life/companions/dialogue-settings"): "dialogue_settings_update",
    ("post", "/api/config/draft/providers"): "provider_add",
    ("put", "/api/config/draft/providers/{provider_id}"): "provider_update",
    ("delete", "/api/config/draft/providers/{provider_id}"): "provider_remove",
    ("post", "/api/config/draft/providers/{provider_id}/discover"): "provider_discover",
    ("post", "/api/config/test-llm"): "provider_test",
    ("post", "/api/config/draft/update-model"): "model_update",
    ("post", "/api/config/draft/delete-model"): "model_remove",
    ("delete", "/api/config/draft/providers/{provider_id}/models/{model_key}"): "model_remove",
    ("put", "/api/tools/image2/default-model"): "model_default",
    ("post", "/api/sessions/{session_id}/pin"): "session_pin",
    ("post", "/api/sessions/{session_id}/unpin"): "session_unpin",
    ("patch", "/api/sessions/{session_id}/reasoning-effort"): "session_reasoning_update",
    ("patch", "/api/sessions/{session_id}/model-parameters"): "session_model_parameters_update",
    ("patch", "/api/sessions/{session_id}/budget-parameters"): "session_budget_update",
    ("post", "/api/sessions/{session_id}/archive"): "session_archive",
    ("post", "/api/sessions/{session_id}/unarchive"): "session_unarchive",
    ("patch", "/api/teams/{team_id}"): "team_update",
    ("delete", "/api/teams/{team_id}"): "team_archive",
    ("patch", "/api/chat-rooms/{room_id}"): "room_update",
    ("get", "/api/teams/{team_id}"): "team_get",
    ("get", "/api/chat-rooms/{room_id}"): "room_get",
    ("get", "/api/sessions/{session_id}"): "session_get",
}


def _extended_action(method: str, path: str) -> dict | None:
    from tools.pa_platform_actions import extension_contracts, legacy_manage_contracts
    legacy = {("delete", "/api/agents/{agent_id}"): "agent_archive",
              ("post", "/api/sessions"): "session_create", ("patch", "/api/sessions/{session_id}"): "session_update",
              ("delete", "/api/sessions/{session_id}"): "session_delete", ("post", "/api/sessions/{session_id}/stop"): "session_stop",
              ("post", "/api/teams"): "team_create"}
    if (method, path) in legacy:
        name = legacy[(method, path)]
        contract = legacy_manage_contracts()[name]
        return {"action": name, "governed": True, "constraints": [contract["description"], "Use the canonical action schema and native approval."]}
    name = _EXTENDED_ACTIONS.get((method, path))
    contract = extension_contracts().get(name)
    if not contract:
        return None
    result = {"action": name, "governed": contract.get("governed", False),
            "constraints": [contract["description"], "Use the action schema; HTTP payloads are not accepted by the adapter."]}
    if name == "workspace_list":
        kind = {"/api/teams": "teams", "/api/chat-rooms": "rooms"}.get(path, "sessions")
        result["parameters"] = {"kind": kind, **({"archived": True} if path == "/api/session-archive" else {})}
    return result


def get_spec() -> dict[str, Any]:
    """Register web routes and return the current OpenAPI document."""

    from core.web.app import app, ensure_web_routes_registered

    ensure_web_routes_registered(app)
    spec = app.openapi()
    return spec if isinstance(spec, dict) else {}


def api_catalog(query: str = "", tag: str = "", offset: int = 0, limit: int = DEFAULT_PAGE_SIZE, *,
                spec: dict[str, Any] | None = None,
                entry_projector: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None) -> dict[str, Any]:
    """List registered ``/api`` operations with bounded pagination.

    ``spec`` and ``entry_projector`` are internal owner seams, never HTTP/tool
    parameters. The neutral documentation owner can avoid lifecycle bootstrap
    and legacy PA advertising while sharing all discovery/pagination rules.
    """

    if type(offset) is not int or offset < 0:
        return _receipt({"message": "offset must be an integer greater than or equal to zero"}, ok=False)
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
        return _receipt({"message": f"limit must be an integer from 1 to {MAX_PAGE_SIZE}"}, ok=False)

    wanted_query = str(query or "").strip().casefold()
    wanted_tag = str(tag or "").strip().casefold()
    spec = get_spec() if spec is None else spec
    paths = spec.get("paths") if isinstance(spec.get("paths"), dict) else {}
    read_paths = _allowlisted_read_paths(paths) if entry_projector is None else set()

    matches: list[dict[str, Any]] = []
    for method, path, operation in _iter_operations(paths):
        entry = (_catalog_entry(method, path, operation, read_paths) if entry_projector is None
                 else entry_projector(method, path, operation))
        operation_tags = entry["tags"]
        if wanted_tag and not any(item.casefold() == wanted_tag for item in operation_tags):
            continue
        searchable = " ".join(
            [entry["operationId"], entry["method"], entry["path"], entry["summary"], *operation_tags]
        ).casefold()
        if wanted_query and wanted_query not in searchable:
            continue
        matches.append(entry)

    page = matches[offset : offset + limit]
    return _receipt(
        {
            "operations": page,
            "offset": offset,
            "limit": limit,
            "total": len(matches),
            "truncated": offset + len(page) < len(matches),
        }
    )


def api_describe(operation_id: str, *, spec: dict[str, Any] | None = None,
                 entry_projector: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Describe one unique operation and only its reachable schema components.

    Internal spec/projection seams preserve the legacy default owner path.
    """

    wanted_id = str(operation_id or "").strip()
    if not wanted_id:
        return _receipt(
            {"message": "operationId is required", "operationId": wanted_id},
            ok=False,
        )
    spec = get_spec() if spec is None else spec
    paths = spec.get("paths") if isinstance(spec.get("paths"), dict) else {}
    operations = [
        (method, path, operation)
        for method, path, operation in _iter_operations(paths)
        if operation.get("operationId") is not None
        and str(operation.get("operationId"))
        and str(operation.get("operationId")) == wanted_id
    ]
    if len(operations) != 1:
        if operations:
            return _receipt(
                {
                    "message": "operationId is duplicated; describe is refused",
                    "operationId": wanted_id,
                },
                ok=False,
            )
        return _receipt(
            {"message": "operationId is not present in the registered OpenAPI document", "operationId": wanted_id},
            ok=False,
        )

    method, path, operation = operations[0]
    paths_for_read = _allowlisted_read_paths(paths) if entry_projector is None else set()
    path_item = paths.get(path) if isinstance(paths.get(path), dict) else {}
    parameters = _effective_parameters(path_item.get("parameters"), operation.get("parameters"))
    request_body = copy.deepcopy(operation.get("requestBody"))
    responses = copy.deepcopy(operation.get("responses") or {})
    operation_parts = {"parameters": parameters, "requestBody": request_body, "responses": responses}

    schema_map = _schema_map(spec)
    reachable, missing = _reachable_schemas(operation_parts, schema_map)
    omitted: list[str] = list(missing)
    omitted_fields: list[str] = []
    schemas: dict[str, Any] = {}
    entry = (_catalog_entry(method, path, operation, paths_for_read) if entry_projector is None
             else entry_projector(method, path, operation))
    payload: dict[str, Any] = {
        "operation": entry,
        "description": str(operation.get("description") or "")[:8000],
        "parameters": parameters,
        "requestBody": request_body,
        "responses": responses,
        "components": {"schemas": schemas},
        "truncated": False,
        "omittedSchemas": [],
    }
    if missing:
        payload["truncated"] = True

    ordered_names = list(reachable)
    candidates = ordered_names[:MAX_SCHEMA_COMPONENTS]
    omitted.extend(ordered_names[MAX_SCHEMA_COMPONENTS:])
    for name in candidates:
        schemas[name] = reachable[name]
        if not _within_description_limit(payload):
            schemas.pop(name, None)
            omitted.append(name)
            payload["truncated"] = True

    if omitted:
        payload["truncated"] = True
    _set_omitted_schema_names(payload, omitted)

    # OpenAPI operation bodies are usually small because large structures live
    # in schemas. If an unusual hand-written spec exceeds the response budget,
    # omit the largest detail sections explicitly and keep the result bounded.
    for field in ("responses", "requestBody", "parameters"):
        if _within_description_limit(payload):
            break
        current = payload.get(field)
        if current not in (None, [], {}):
            payload[field] = {} if field == "responses" else ([] if field == "parameters" else None)
            omitted_fields.append(field)
            payload["truncated"] = True
            _set_omitted_schema_names(payload, omitted)
    if omitted_fields:
        payload["omittedFields"] = omitted_fields

    if not _within_description_limit(payload):
        # Keep a complete, clearly marked envelope even for pathological
        # operation metadata or an unusually long omitted-schema list.
        payload["operation"] = _compact_operation(entry)
        payload["components"] = {"schemas": {}}
        payload["parameters"] = []
        payload["requestBody"] = None
        payload["responses"] = {}
        payload["truncated"] = True
        payload["omittedFields"] = ["operationDetails", "components.schemas"]
        _set_omitted_schema_names(payload, [*omitted, *schemas.keys()])
        while not _within_description_limit(payload) and payload["omittedSchemas"]:
            payload["omittedSchemas"].pop()
            payload["omittedSchemasTruncated"] = True

    return _receipt(payload)


def _iter_operations(paths: dict[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    for raw_path, path_item in paths.items():
        path = str(raw_path)
        if not _is_api_path(path) or not isinstance(path_item, dict):
            continue
        for method in STANDARD_METHODS:
            operation = path_item.get(method)
            if isinstance(operation, dict):
                yield method, path, operation


def _is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _catalog_identity_entry(method: str, path: str, operation: dict[str, Any]) -> dict[str, Any]:
    tags = [str(item) for item in operation.get("tags") or [] if item is not None]
    summary = str(operation.get("summary") or "")
    operation_id = str(operation.get("operationId") or "")
    return {
        "operationId": operation_id,
        "method": method.upper(),
        "path": path,
        "summary": summary,
        "tags": tags,
    }


def _catalog_entry(
    method: str, path: str, operation: dict[str, Any], read_paths: set[str]
) -> dict[str, Any]:
    entry = _catalog_identity_entry(method, path, operation)

    if method == "get" and path in read_paths:
        entry.update(
            {
                "access": "read_gateway",
                "executable": True,
                "tool": "personal_assistant_platform_api_tool",
                "execution": {"path": path},
            }
        )
        if "{" in path:
            entry["execution"]["note"] = "Replace each path template parameter with its actual ID."
        return entry

    action = _NATIVE_ACTIONS.get((method, path)) or _extended_action(method, path)
    if action:
        entry.update(
            {
                "access": "native_action",
                "executable": True,
                "tool": "personal_assistant_manage_tool" if action.get("governed") else "personal_assistant_action_tool",
                "action": action["action"],
                "capabilitySubset": True,
                "constraints": list(action["constraints"]),
                "argumentHelp": {"tool": "personal_assistant_action_tool", "action": "describe", "parameters": {"action": action["action"]}},
            }
        )
        if action["action"] == "agent_update":
            entry["allowedFields"] = list(_SAFE_AGENT_FIELDS)
        if action.get("parameters"):
            entry["execution"] = {"action": action["action"], "parameters": action["parameters"]}
        if action.get("governed"):
            entry["approval"] = {"tool": "personal_assistant_manage_tool", "required": "native management approval"}
            entry["execution"] = {"action": action["action"], "arguments_json": "JSON encoding of the action's parameters object"}
        return entry

    entry.update(
        {
            "access": "operator_only",
            "executable": False,
            "tool": None,
            "reason": "Discovery does not grant authorization; no bounded assistant action is registered for this operation.",
        }
    )
    if method == "delete" or _has_restart_segment(path):
        entry["approval"] = {
            "tool": "personal_assistant_manage_tool",
            "required": "native management approval",
            "note": "This catalog only describes the operation; it cannot execute it.",
        }
    return entry


def _allowlisted_read_paths(paths: dict[str, Any]) -> set[str]:
    from core.web.services.personal_assistant_platform_api import api as existing_api

    allowed = existing_api._filter_get_endpoints(paths)
    return set(allowed) if isinstance(allowed, dict) else set()


def _has_restart_segment(path: str) -> bool:
    return any(segment.casefold() == "restart" for segment in path.split("/"))


def _effective_parameters(path_parameters: Any, operation_parameters: Any) -> list[Any]:
    """Combine path-level and operation-level parameters, with operation overrides."""

    merged: list[Any] = []
    positions: dict[tuple[Any, Any], int] = {}
    for item in [*(path_parameters if isinstance(path_parameters, list) else []), *(operation_parameters if isinstance(operation_parameters, list) else [])]:
        cloned = copy.deepcopy(item)
        identity: tuple[Any, Any] | None = None
        if isinstance(cloned, dict) and cloned.get("name") is not None and cloned.get("in") is not None:
            identity = (cloned.get("name"), cloned.get("in"))
        if identity is not None and identity in positions:
            merged[positions[identity]] = cloned
        else:
            if identity is not None:
                positions[identity] = len(merged)
            merged.append(cloned)
    return merged


def _schema_map(spec: dict[str, Any]) -> dict[str, Any]:
    components = spec.get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    return schemas if isinstance(schemas, dict) else {}


def _reachable_schemas(
    operation_parts: dict[str, Any], schema_map: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    pending = deque(_schema_refs(operation_parts))
    seen: set[str] = set()
    reachable: dict[str, Any] = {}
    missing: list[str] = []
    while pending:
        name = pending.popleft()
        if name in seen:
            continue
        seen.add(name)
        if name not in schema_map:
            missing.append(name)
            continue
        schema = copy.deepcopy(schema_map[name])
        reachable[name] = schema
        pending.extend(_schema_refs(schema))
    return reachable, missing


def _schema_refs(value: Any) -> Iterator[str]:
    pending = [value]
    prefix = "#/components/schemas/"
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            reference = current.get("$ref")
            if isinstance(reference, str) and reference.startswith(prefix):
                encoded_name = reference[len(prefix) :].split("/", 1)[0]
                if encoded_name:
                    yield encoded_name.replace("~1", "/").replace("~0", "~")
            pending.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            pending.extend(reversed(current))


def _set_omitted_schema_names(payload: dict[str, Any], names: list[str]) -> None:
    unique_names = list(dict.fromkeys(str(name) for name in names))
    bounded_names = [name[:160] for name in unique_names[:128]]
    payload["omittedSchemas"] = bounded_names
    payload["omittedSchemaCount"] = len(unique_names)
    if len(unique_names) > len(bounded_names):
        payload["omittedSchemasTruncated"] = True


def _compact_operation(entry: dict[str, Any]) -> dict[str, Any]:
    compact = dict(entry)
    compact["operationId"] = str(entry.get("operationId") or "")[:256]
    compact["path"] = str(entry.get("path") or "")[:2048]
    compact["summary"] = str(entry.get("summary") or "")[:512]
    compact["tags"] = [str(tag)[:128] for tag in entry.get("tags") or []][:32]
    compact["constraints"] = [str(text)[:256] for text in entry.get("constraints") or []][:8]
    compact["reason"] = str(entry.get("reason") or "")[:512]
    compact["allowedFields"] = [str(field)[:128] for field in entry.get("allowedFields") or []][:32]
    compact["execution"] = {"path": str((entry.get("execution") or {}).get("path") or "")[:2048]}
    return compact


def _within_description_limit(payload: dict[str, Any]) -> bool:
    return len(_json(_receipt(payload))) <= MAX_DESCRIPTION_CHARS


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _receipt(payload: dict[str, Any], *, ok: bool = True) -> dict[str, Any]:
    return {
        "ok": ok,
        "status": "ok" if ok else "error",
        "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "registered-openapi",
        "untrustedContent": True,
        **payload,
    }


__all__ = ["api_catalog", "api_describe", "get_spec"]
