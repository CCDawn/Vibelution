"""Durable associations for closed target operations; target owns execution."""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

import anyio

from core.infrastructure.atomic_io import atomic_write_json

from .dispatch import DispatchError


def _legacy_page(rows, project_id, *, offset, limit, field, observer_id=None):
    result = {"projectId": project_id, field: [], "total": len(rows), "offset": offset,
              "nextOffset": None, "untrustedContent": True, "readOnly": True,
              "readyForCutover": False}
    if observer_id is not None:
        result["observerId"] = observer_id
    for row in rows[offset:offset + limit]:
        candidate = {**result, field: result[field] + [row]}
        if len(json.dumps(candidate, ensure_ascii=False)) > 3200:
            if not result[field]:
                return {"ok": False, "status": "unavailable", "error": "legacy_navigation_budget",
                        "projectId": project_id, "untrustedContent": True}
            break
        result[field].append(row)
    end = offset + len(result[field])
    result["nextOffset"] = end if end < len(rows) else None
    return result


# Keep catalog navigation comfortably inside the native tool-result cap after
# the action tool adds its source/untrusted wrapper and the model-result header.
_DOCUMENTATION_NAVIGATION_TARGET_CHARS = 3400
_DOCUMENTATION_SUMMARY_CHARS = 120
_DOCUMENTATION_NAVIGATION = (
    "本页用于 API 目录导航；summary 是不超过 120 字符的摘要，完整说明请用 api_describe 并传入原样 operationId。"
    "limit 是本次实际返回条数；若 nextOffset 非空，保持原 query/tag，"
    "用 nextOffset 作为下一次 api_catalog 的 offset 继续读取。"
)
_DOCUMENTATION_READ_ERROR = "API 目录读取失败；原始错误详情未透传，请检查文档服务状态。"
_DOCUMENTATION_ENTRY_ERROR = (
    "目录项完整元数据超过单页预算，未返回部分条目；请使用完整 operationId 调用 api_describe。"
)


def _documentation_wrapper_size(project_id: str, result: dict) -> int:
    """Measure the exact JSON shape emitted by personal_assistant_action_tool."""
    wrapped = {
        "source": "launcher-assistant",
        "untrustedContent": True,
        **result,
        "projectId": project_id,
    }
    return len(json.dumps(wrapped, ensure_ascii=False))


def _documentation_navigation_entry(entry: dict) -> dict:
    projected = deepcopy(entry)
    summary = entry.get("summary")
    if isinstance(summary, str) and len(summary) > _DOCUMENTATION_SUMMARY_CHARS:
        projected["summary"] = summary[: _DOCUMENTATION_SUMMARY_CHARS - 3] + "..."
    return projected


def _documentation_catalog_response(result: dict, project_id: str, *, offset: int,
                                    total: int, operations: list[dict], truncated: bool,
                                    code: str | None = None, message: str | None = None,
                                    operation_id_hint: str | None = None) -> dict:
    # Catalog responses carry only these top-level protocol facts. In particular,
    # free-form target errors are never copied into the native model result.
    response = {
        key: deepcopy(result[key])
        for key in ("observedAt", "source", "untrustedContent")
        if key in result
    }
    response.update(
        ok=code is None,
        status="ok" if code is None else "error",
        operations=operations,
        offset=offset,
        limit=len(operations),
        total=total,
        truncated=truncated,
        nextOffset=(offset + len(operations)) if truncated and code is None else None,
        navigation=_DOCUMENTATION_NAVIGATION,
        projectId=project_id,
    )
    if code is not None:
        response.update(code=code, message=message or _DOCUMENTATION_READ_ERROR)
        if operation_id_hint is not None:
            response["operationIdHint"] = operation_id_hint
    return response


def _documentation_catalog_navigation(result: dict, project_id: str, parameters: dict) -> dict:
    """Return a complete, budget-safe navigation page from the closed SDK DTO."""
    requested_offset = parameters.get("offset", 0)
    offset = result.get("offset", requested_offset)
    if type(offset) is not int or offset < 0:
        offset = requested_offset if type(requested_offset) is int and requested_offset >= 0 else 0
    source_operations = result.get("operations")
    source_operations = source_operations if isinstance(source_operations, list) else []
    raw_total = result.get("total", offset + len(source_operations))
    total = raw_total if type(raw_total) is int and raw_total >= 0 else offset + len(source_operations)

    if result.get("ok") is False or result.get("status") == "error":
        return _documentation_catalog_response(
            result, project_id, offset=offset, total=total, operations=[], truncated=False,
            code="DOCUMENTATION_READ_FAILED", message=_DOCUMENTATION_READ_ERROR,
        )

    if (any(not isinstance(row, dict) for row in source_operations)
            or offset < total and not source_operations
            or source_operations and (offset >= total or offset + len(source_operations) > total)):
        return _documentation_catalog_response(
            result, project_id, offset=offset, total=total, operations=[], truncated=False,
            code="DOCUMENTATION_PAGE_INVALID",
            message="API 目录分页响应不完整，未返回条目；请重新从当前 offset 查询。",
        )

    selected: list[dict] = []
    for source_entry in source_operations:
        entry = _documentation_navigation_entry(source_entry)
        candidate_rows = [*selected, entry]
        more = offset + len(candidate_rows) < total
        candidate = _documentation_catalog_response(
            result, project_id, offset=offset, total=total,
            operations=candidate_rows, truncated=more,
        )
        if _documentation_wrapper_size(project_id, candidate) > _DOCUMENTATION_NAVIGATION_TARGET_CHARS:
            if selected:
                break
            operation_id = source_entry.get("operationId")
            hint = operation_id if isinstance(operation_id, str) and 0 < len(operation_id) <= 128 else None
            failed = _documentation_catalog_response(
                result, project_id, offset=offset, total=total, operations=[], truncated=True,
                code="DOCUMENTATION_ENTRY_TOO_LARGE", message=_DOCUMENTATION_ENTRY_ERROR,
                operation_id_hint=hint,
            )
            return failed
        selected = candidate_rows

    more = offset + len(selected) < total
    return _documentation_catalog_response(
        result, project_id, offset=offset, total=total,
        operations=selected, truncated=more,
    )


class ManagementAdapter:
    def __init__(self, profile_root: Path, projects, call):
        self._root = Path(profile_root) / "assistant_management"
        self._project_provider = projects if callable(projects) else lambda: projects
        self._call = call
        self._locks: dict[str, anyio.Lock] = {}

    @property
    def _projects(self):
        return self._project_provider()

    def _key(self, project_id, action, request_id):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        from core.web.services.external_management.contracts import ACTION_MODELS
        if action not in ACTION_MODELS or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", request_id):
            raise DispatchError("Invalid management request.", code="INVALID_MANAGEMENT_REQUEST")
        return hashlib.sha256(json.dumps([project_id, str(self._projects[project_id]).casefold(), action, request_id]).encode()).hexdigest()

    def _read(self, path):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("schemaVersion") == 1 and re.fullmatch(r"[a-f0-9]{64}", value.get("fingerprint", "")):
                return value
        except (OSError, ValueError, TypeError):
            pass
        raise DispatchError("Existing management association is unreadable; preserved without replay.", code="MANAGEMENT_STATE_INVALID")

    async def invoke(self, project_id: str, *, action: str, request_id: str, parameters: dict):
        key = self._key(project_id, action, request_id)
        fingerprint = hashlib.sha256(json.dumps(parameters, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        path = self._root / (key + ".json")
        async with self._locks.setdefault(key, anyio.Lock()):
            # A request may have waited while main suspended project admission.
            # Reuse the provider gate before reading/replaying or writing intent.
            self._key(project_id, action, request_id)
            retrying = path.exists()
            if retrying:
                record = self._read(path)
                if record["fingerprint"] != fingerprint:
                    raise DispatchError("Request ID belongs to different parameters.", code="MANAGEMENT_CONFLICT")
                try:
                    result = await self._call(project_id, lambda client: client.management_receipt(action=action, request_id=request_id))
                    team = result.get("teamRun")
                    resumable = (action == "team_run" and result.get("status") == "unknown"
                        and result.get("resumeAllowed") is True
                        and result.get("phase") in {"materialized", "flow_saved"}
                        and isinstance(team, dict) and bool(team.get("teamId")) and bool(team.get("flowId"))
                        and not team.get("runId"))
                    if not resumable:
                        return {**result, "projectId": project_id}
                    # Only the target can prove a frozen, fully materialized
                    # team is safe to continue. Replay the identical envelope
                    # through that same durable gate, never create a new key.
                except DispatchError as exc:
                    if exc.code != "REQUEST_UNAVAILABLE":
                        raise
                    # Only an authenticated not-admitted result permits the
                    # original envelope to reach the target's durable gate.
            else:
                atomic_write_json(path, {"schemaVersion": 1, "fingerprint": fingerprint})
            result = await self._call(project_id, lambda client: client.management_action(action=action,
                request_id=request_id, parameters=parameters, require_existing_subject=retrying))
            return {**result, "projectId": project_id}

    async def receipt(self, project_id: str, *, action: str, request_id: str):
        key = self._key(project_id, action, request_id)
        self._read(self._root / (key + ".json"))
        result = await self._call(project_id, lambda client: client.management_receipt(action=action, request_id=request_id))
        return {**result, "projectId": project_id}

    async def agent(self, project_id: str, *, agent_id: str):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        result = await self._call(project_id, lambda client: client.management_agent(agent_id=agent_id))
        return {**result, "projectId": project_id}

    async def avatar_options(self, project_id: str, **query):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        result = await self._call(project_id, lambda client: client.management_avatar_options(**query))
        return {**result, "projectId": project_id}

    async def session_list(self, project_id: str, **parameters):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        result = await self._call(project_id, lambda client: client.management_session_list(**parameters))
        return {**result, "projectId": project_id}

    async def team_list(self, project_id: str, **parameters):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        result = await self._call(project_id, lambda client: client.management_team_list(**parameters))
        return {**result, "projectId": project_id}

    async def authorization_status(self, project_id: str):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        result = await self._call(project_id, lambda client: client.management_authorization_status())
        return {**result, "projectId": project_id}

    async def legacy_observers(self, project_id: str, *, offset=0, limit=3):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        result = await self._call(project_id, lambda client: client.management_legacy_observers())
        rows = [{key: row[key] for key in ("observerId", "status", "sourceAgentId", "sourceSessionId")}
                | {"whitelistedMessageCount": len(row["legacyMessageIds"]), "actions": ["read_receipt"]}
                for row in result["observers"]]
        return _legacy_page(rows, project_id, offset=offset, limit=limit, field="observers")

    async def legacy_receipts(self, project_id: str, *, observer_id: str, offset=0, limit=3):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        result = await self._call(project_id, lambda client: client.management_legacy_receipts(observer_id))
        rows = [{key: value for key, value in row.items() if key != "receipts"} for row in result["dispatches"]]
        return _legacy_page(rows, project_id, offset=offset, limit=limit,
                            field="dispatches", observer_id=observer_id)

    async def team(self, project_id: str, **parameters):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        result = await self._call(project_id, lambda client: client.management_team(**parameters))
        return {**result, "projectId": project_id}

    async def room_list(self, project_id: str, **parameters):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        result = await self._call(project_id, lambda client: client.management_room_list(**parameters))
        return {**result, "projectId": project_id}

    async def room(self, project_id: str, **parameters):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        result = await self._call(project_id, lambda client: client.management_room(**parameters))
        return {**result, "projectId": project_id}

    async def session_parameters(self, project_id: str, **parameters):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        result = await self._call(project_id, lambda client: client.management_session_parameters(**parameters))
        return {**result, "projectId": project_id}

    async def session(self, project_id: str, *, session_id: str):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        result = await self._call(project_id, lambda client: client.management_session(session_id=session_id))
        return {**result, "projectId": project_id}

    async def session_config(self, project_id: str, *, session_id: str):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        result = await self._call(project_id, lambda client: client.management_session_config(session_id=session_id))
        return {**result, "projectId": project_id}

    async def session_config_compare(self, project_id: str, *, session_id: str):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        result = await self._call(project_id, lambda client: client.management_session_config_compare(session_id=session_id))
        return {**result, "projectId": project_id}

    async def documentation(self, project_id: str, **parameters):
        if project_id not in self._projects:
            raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
        if parameters.get("operation_id") is not None:
            from .documentation_projection import DocumentationNodeQuery, project_documentation_node

            # Local view fields never become HTTP/SDK parameters or permissions.
            query = DocumentationNodeQuery.model_validate(parameters)
            result = await self._call(project_id, lambda client: client.management_documentation(operation_id=query.operation_id))
            return project_documentation_node(result, project_id, query)
        result = await self._call(project_id, lambda client: client.management_documentation(**parameters))
        return _documentation_catalog_navigation(result, project_id, parameters)
