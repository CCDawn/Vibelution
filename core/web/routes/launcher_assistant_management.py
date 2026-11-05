"""Operator-control authenticated transport for closed, neutral target management."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from core.web.control import validate_control_request
from core.web.services.external_management.contracts import (
    AgentReadResponse,
    AvatarOptionsQuery,
    AvatarOptionsResponse,
    BindingResponse,
    BoundSubjectResponse,
    DocumentationCatalogQuery,
    DocumentationResponse,
    ReceiptResponse,
    SessionReadResponse,
    SessionListQuery,
    SessionListResponse,
    SessionConfigResponse,
    SessionConfigComparisonResponse,
    DirectoryQuery, TeamListResponse, TeamReadResponse, RoomListResponse, RoomReadResponse, SessionParametersResponse, AuthorizationStateResponse,
    LegacyObserverView, LegacyObserversResponse, LegacyReceiptsResponse, ActiveTasksResponse, SourceReadResponse, SourceSearchResponse,
    TeamKnowledgeResponse, TeamResultResponse, AgentDirectoryQuery, AgentDirectoryResponse, AgentPurgePreviewResponse,
)
from core.web.services.external_management.runtime_contracts import (
    RuntimeOperationsQuery, RuntimeOperationsResponse, RuntimeOperationQuery, RuntimeOperationResponse, RuntimeKind,
)
from core.web.services.external_management.asset_contracts import (
    TeamAssetQuery, TeamAssetResponse, ToolPolicyQuery, ToolPolicyResponse, KnowledgeACLQuery, KnowledgeACLResponse,
    DispatchAccessQuery, DispatchAccessResponse,
)
from core.web.services.external_management.team_lifecycle_contracts import TeamArchivePreviewResponse
from core.web.services.external_management.agent_configuration_contracts import AgentConfigurationQuery, AgentConfigurationResponse
from core.web.services.external_management.configuration_discovery_contracts import (AgentPromptQuery, AgentPromptResponse,
    ToolPolicyInspectQuery, ToolPolicyInspectResponse)
from core.web.services.external_management.flow_contracts import FlowListQuery, FlowListResponse, FlowReadQuery, FlowReadResponse
from core.web.services.external_management.platform_actions import PLATFORM_ACTIONS
from core.web.services.external_management.service import (
    ManagementError,
    ManagementService,
    build_default_service,
)

router = APIRouter(prefix="/v1/launcher-assistant-management", tags=["launcher-assistant-management"])
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SUBJECT_HEADER = "X-Vibelution-Management-Subject"
CAPABILITY_HEADER = "X-Vibelution-Management-Capability"
_SERVICE: ManagementService | None = None


def _service():
    return _SERVICE if _SERVICE is not None else build_default_service(PROJECT_ROOT)


def _require_control(request: Request):
    error = validate_control_request(request)
    if error is not None:
        raise HTTPException(status_code=error.status_code, detail={"code": "OPERATOR_CONTROL_REQUIRED"})


def _credentials(request: Request):
    return request.headers.get(SUBJECT_HEADER, ""), request.headers.get(CAPABILITY_HEADER, "")


async def _body(request: Request, *, unique_keys=False):
    try:
        chunks = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 24 * 1024:
                raise ValueError("request too large")
            chunks.append(chunk)
        content = b"".join(chunks)
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("Duplicate field")
                value[key] = item
            return value
        value = json.loads(content, object_pairs_hook=unique) if unique_keys else json.loads(content)
        if not isinstance(value, dict):
            raise TypeError("object required")
        return value
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"}) from None


async def _call(operation, *args):
    try:
        return await run_in_threadpool(operation, *args)
    except ManagementError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from None
    except TimeoutError:
        raise HTTPException(status_code=409, detail={"code": "MANAGEMENT_BUSY"}) from None
    except Exception:  # noqa: BLE001 -- the transport exposes bounded errors, never filesystem or credential detail
        raise HTTPException(status_code=503, detail={"code": "MANAGEMENT_UNAVAILABLE"}) from None


async def _operator_call(request, operation):
    from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope_from_http
    try:
        with server_operator_scope_from_http(request):
            return await _call(operation)
    except PermissionError:
        raise HTTPException(status_code=403, detail={"code": "OPERATOR_CONTROL_REQUIRED"}) from None


def _closed_query(request, model):
    values = request.query_params
    if set(values) - model.model_fields.keys() or len(values.multi_items()) != len(values):
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    result = dict(values)
    for key in ("offset", "limit", "node_offset", "human_task_offset"):
        if key in result:
            if not re.fullmatch(r"[0-9]{1,7}", result[key]):
                raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
            result[key] = int(result[key])
    return result


from core.web.services.external_management.runtime_legacy_contracts import (
    LegacyRuntimeKind, LegacyRuntimeOperationsQuery, LegacyRuntimeOperationQuery,
    LegacyRuntimeOperationsResponse, LegacyRuntimeOperationResponse)


@router.get("/runtime/operations", response_model=LegacyRuntimeOperationsResponse)
async def runtime_operations(request: Request, kind: LegacyRuntimeKind | None = None,
                             state: Literal["active", "terminal", "all"] = "active", offset: int = 0, limit: int = 3):
    _require_control(request)
    query = _closed_query(request, LegacyRuntimeOperationsQuery)
    return await _operator_call(request, lambda: _service().read_runtime(*_credentials(request), "list", query, legacy=True))


@router.get("/runtime/operation", response_model=LegacyRuntimeOperationResponse)
async def runtime_operation(request: Request, kind: LegacyRuntimeKind, resource_id: str,
                            session_id: str = "", team_id: str = "", flow_id: str = ""):
    _require_control(request)
    query = _closed_query(request, LegacyRuntimeOperationQuery)
    return await _operator_call(request, lambda: _service().read_runtime(*_credentials(request), "get", query, legacy=True))


@router.get("/runtime/inventory", response_model=RuntimeOperationsResponse)
async def runtime_inventory(request: Request):
    _require_control(request)
    query = _closed_query(request, RuntimeOperationsQuery)
    return await _operator_call(request, lambda: _service().read_runtime(*_credentials(request), "list", query))


@router.get("/runtime/item", response_model=RuntimeOperationResponse)
async def runtime_item(request: Request):
    _require_control(request)
    query = _closed_query(request, RuntimeOperationQuery)
    return await _operator_call(request, lambda: _service().read_runtime(*_credentials(request), "get", query))


from core.web.services.external_management.knowledge_catalog_contracts import KnowledgeCatalogQuery, KnowledgeCatalogResponse
from core.web.services.external_management.research_contracts import ResearchReadQuery, ResearchReadResponse


@router.get("/knowledge-bases", response_model=KnowledgeCatalogResponse)
async def knowledge_catalog(request: Request):
    _require_control(request)
    query = _closed_query(request, KnowledgeCatalogQuery)
    return await _operator_call(request, lambda: _service().read_knowledge_catalog(*_credentials(request), query))


@router.get("/research/operation", response_model=ResearchReadResponse)
async def research_operation(request: Request):
    _require_control(request)
    query = _closed_query(request, ResearchReadQuery)
    return await _operator_call(request, lambda: _service().read_research(*_credentials(request), query))


@router.get("/assets/team-archive", response_model=TeamArchivePreviewResponse)
async def team_archive_preview(request: Request, team_id: str = ""):
    _require_control(request)
    query = _closed_query(request, TeamAssetQuery)
    return await _operator_call(request, lambda: _service().read_asset(*_credentials(request), "team-archive", query))


@router.get("/assets/team", response_model=TeamAssetResponse)
async def read_team_asset(request: Request, team_id: str = ""):
    _require_control(request)
    query = _closed_query(request, TeamAssetQuery)
    return await _operator_call(request, lambda: _service().read_asset(*_credentials(request), "team", query))


@router.get("/assets/tool-policy", response_model=ToolPolicyResponse)
async def read_tool_policy(request: Request, agent_id: str = ""):
    _require_control(request)
    query = _closed_query(request, ToolPolicyQuery)
    return await _operator_call(request, lambda: _service().read_asset(*_credentials(request), "tool-policy", query))


@router.get("/assets/agent-config", response_model=AgentConfigurationResponse)
async def read_agent_configuration(request: Request, agent_id: str = ""):
    _require_control(request)
    query = _closed_query(request, AgentConfigurationQuery)
    return await _operator_call(request, lambda: _service().read_asset(*_credentials(request), "agent-config", query))


@router.get("/assets/agent-prompt", response_model=AgentPromptResponse)
async def read_agent_prompt(request: Request, agent_id: str = ""):
    _require_control(request)
    query = _closed_query(request, AgentPromptQuery)
    return await _operator_call(request, lambda: _service().read_asset(*_credentials(request), "agent-prompt", query))


@router.get("/assets/tool-policy-inspect", response_model=ToolPolicyInspectResponse)
async def inspect_agent_tool_policy(request: Request, agent_id: str = "", updates_json: str = "{}"):
    _require_control(request)
    query = _closed_query(request, ToolPolicyInspectQuery)
    return await _operator_call(request, lambda: _service().read_asset(*_credentials(request), "tool-policy-inspect", query))


@router.get("/assets/dispatch-access", response_model=DispatchAccessResponse)
async def read_dispatch_access(request: Request, agent_id: str = ""):
    _require_control(request)
    query = _closed_query(request, DispatchAccessQuery)
    return await _operator_call(request, lambda: _service().read_asset(*_credentials(request), "dispatch-access", query))


@router.get("/assets/knowledge-acl", response_model=KnowledgeACLResponse)
async def read_knowledge_acl(request: Request, knowledge_base_id: str = ""):
    _require_control(request)
    query = _closed_query(request, KnowledgeACLQuery)
    return await _operator_call(request, lambda: _service().read_asset(*_credentials(request), "knowledge-acl", query))


@router.get("/team-flows", response_model=FlowListResponse)
async def list_team_flows(request: Request, team_id: str = "", offset: int = 0, limit: int = 5,
                          expected_digest: str | None = None):
    _require_control(request)
    query = _closed_query(request, FlowListQuery)
    return await _operator_call(request, lambda: _service().read_flow(*_credentials(request), "list", query))


@router.get("/team-flow", response_model=FlowReadResponse)
async def read_team_flow(request: Request, team_id: str = "", flow_id: str = "", pointer: str = "",
                         offset: int = 0, limit: int = 512, expected_digest: str | None = None):
    _require_control(request)
    query = _closed_query(request, FlowReadQuery)
    return await _operator_call(request, lambda: _service().read_flow(*_credentials(request), "get", query))


@router.get("/binding", response_model=BindingResponse)
async def binding(request: Request):
    _require_control(request)
    return await _call(lambda: _service().binding())


@router.post("/subjects/bind", response_model=BoundSubjectResponse)
async def bind_subject(request: Request):
    _require_control(request)
    payload = await _body(request)
    return await _call(lambda: _service().bind(payload))


@router.get("/authorization", response_model=AuthorizationStateResponse)
async def authorization_status(request: Request):
    _require_control(request)
    if request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().authorization_status(*_credentials(request)))


@router.post("/legacy-observers", response_model=LegacyObserverView)
async def create_legacy_observer(request: Request):
    _require_control(request)
    if request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    payload = await _body(request, unique_keys=True)
    return await _call(lambda: _service().create_legacy_observer(*_credentials(request), payload))


@router.get("/legacy-observers", response_model=LegacyObserversResponse)
async def list_legacy_observers(request: Request):
    _require_control(request)
    if request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().list_legacy_observers(*_credentials(request)))


@router.get("/legacy-observers/{observer_id}/receipts", response_model=LegacyReceiptsResponse)
async def read_legacy_receipts(observer_id: str, request: Request):
    _require_control(request)
    if request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().read_legacy_receipts(*_credentials(request), observer_id))


@router.get("/avatar-options", response_model=AvatarOptionsResponse)
async def avatar_options(request: Request, offset: int = 0, limit: int = 20):
    _require_control(request)
    query = request.query_params
    if (set(query) - AvatarOptionsQuery.model_fields.keys() or len(query.multi_items()) != len(query)
        or any(not re.fullmatch(r"[0-9]{1,5}", value) for value in query.values())):
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().read_avatar_options(*_credentials(request), offset=offset, limit=limit))


@router.get("/agents/{agent_id}", response_model=AgentReadResponse)
async def read_agent(agent_id: str, request: Request):
    _require_control(request)
    return await _call(lambda: _service().read_agent(*_credentials(request), agent_id))


@router.get("/agents/{agent_id}/purge-preview", response_model=AgentPurgePreviewResponse)
async def agent_purge_preview(agent_id: str, request: Request):
    _require_control(request)
    if request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().read_purge_preview(*_credentials(request), agent_id))


def _directory_query(request, *, detail=False):
    values = request.query_params
    allowed = {"member_offset", "limit"} if detail else DirectoryQuery.model_fields.keys()
    if (set(values) - allowed or len(values.multi_items()) != len(values)
        or any(not re.fullmatch(r"[0-9]{1,6}", values[key]) for key in ("offset", "member_offset", "limit") if key in values)
        or "archived" in values and values["archived"].casefold() not in {"true", "false"}):
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})


@router.get("/directory/agents", response_model=AgentDirectoryResponse)
async def list_agents(request: Request, query: str = "", offset: int = 0, limit: int = 6,
                      expected_revision: str | None = None):
    _require_control(request)
    values = request.query_params
    if (set(values) - AgentDirectoryQuery.model_fields.keys() or len(values.multi_items()) != len(values)
            or any(not re.fullmatch(r"[0-9]{1,6}", values[key]) for key in ("offset", "limit") if key in values)):
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().read_agents(*_credentials(request), query=query, offset=offset,
        limit=limit, expected_revision=expected_revision))


@router.get("/directory/teams", response_model=TeamListResponse)
async def list_teams(request: Request, query: str = "", offset: int = 0, limit: int = 6, archived: bool = False):
    _require_control(request)
    _directory_query(request)
    return await _call(lambda: _service().read_teams(*_credentials(request), query=query, offset=offset, limit=limit, archived=archived))


@router.get("/active-tasks", response_model=ActiveTasksResponse)
async def list_active_tasks(request: Request, offset: int = 0, limit: int = 6):
    _require_control(request)
    values = request.query_params
    if (set(values) - {"offset", "limit"} or len(values.multi_items()) != len(values)
            or any(not re.fullmatch(r"[0-9]{1,5}", values[key]) for key in values)):
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().read_active_tasks(*_credentials(request), offset=offset, limit=limit))


def _source_query(request, allowed, integers):
    values = request.query_params
    if (set(values) - allowed or len(values.multi_items()) != len(values)
            or any(not re.fullmatch(r"[0-9]{1,7}", values[key]) for key in integers if key in values)):
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})


@router.get("/source/read", response_model=SourceReadResponse)
async def source_read(request: Request, path: str, line: int = 1, max_lines: int = 8, char_offset: int = 0,
                      expected_content_hash: str | None = None):
    _require_control(request)
    _source_query(request, {"path", "line", "max_lines", "char_offset", "expected_content_hash"}, {"line", "max_lines", "char_offset"})
    return await _call(lambda: _service().source_query(*_credentials(request), "read", {"path": path, "line": line, "max_lines": max_lines,
                      "char_offset": char_offset, "expected_content_hash": expected_content_hash}))


@router.get("/source/search", response_model=SourceSearchResponse)
async def source_search(request: Request, query: str, path: str = ".", offset: int = 0):
    _require_control(request)
    _source_query(request, {"path", "query", "offset"}, {"offset"})
    return await _call(lambda: _service().source_query(*_credentials(request), "search", {"path": path, "query": query, "offset": offset}))


@router.get("/directory/teams/{team_id}", response_model=TeamReadResponse)
async def read_team(team_id: str, request: Request, member_offset: int = 0, limit: int = 6):
    _require_control(request)
    _directory_query(request, detail=True)
    return await _call(lambda: _service().read_team(*_credentials(request), team_id, member_offset=member_offset, limit=limit))


@router.get("/directory/teams/{team_id}/knowledge-bases", response_model=TeamKnowledgeResponse)
async def read_team_knowledge(team_id: str, request: Request, offset: int = 0, limit: int = 6):
    _require_control(request)
    values = request.query_params
    if (set(values) - {"offset", "limit"} or len(values.multi_items()) != len(values)
            or any(not re.fullmatch(r"[0-9]{1,5}", value) for value in values.values())):
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().read_team_knowledge(*_credentials(request), team_id, offset=offset, limit=limit))


@router.get("/directory/rooms", response_model=RoomListResponse)
async def list_rooms(request: Request, query: str = "", offset: int = 0, limit: int = 6, archived: bool = False):
    _require_control(request)
    _directory_query(request)
    return await _call(lambda: _service().read_rooms(*_credentials(request), query=query, offset=offset, limit=limit, archived=archived))


@router.get("/directory/rooms/{room_id}", response_model=RoomReadResponse)
async def read_room(room_id: str, request: Request):
    _require_control(request)
    if request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().read_room(*_credentials(request), room_id))


@router.post("/actions/{action}", response_model=ReceiptResponse, response_model_exclude_none=True)
async def invoke(action: str, request: Request):
    _require_control(request)
    operator_actions = {"authorization_reduce", "authorization_revoke", *PLATFORM_ACTIONS}
    if action in operator_actions and request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    payload = await _body(request, unique_keys=action in {"authorization_upgrade", *operator_actions})
    if action in operator_actions:
        return await _operator_call(request, lambda: _service().invoke(*_credentials(request), action, payload))
    return await _call(lambda: _service().invoke(*_credentials(request), action, payload))


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(request: Request, agent_id: str = "", query: str = "", offset: int = 0, limit: int = 6):
    _require_control(request)
    values = request.query_params
    if (set(values) - SessionListQuery.model_fields.keys() or len(values.multi_items()) != len(values)
        or any(not re.fullmatch(r"[0-9]{1,7}", values[key]) for key in ("offset", "limit") if key in values)):
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().read_sessions(*_credentials(request), agent_id=agent_id,
        query=query, offset=offset, limit=limit))


@router.get("/sessions/{session_id}", response_model=SessionReadResponse)
async def read_session(session_id: str, request: Request):
    _require_control(request)
    if request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().read_session(*_credentials(request), session_id))


@router.get("/sessions/{session_id}/config", response_model=SessionConfigResponse)
async def read_session_config(session_id: str, request: Request):
    _require_control(request)
    if request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().read_session_config(*_credentials(request), session_id))


@router.get("/sessions/{session_id}/config-comparison", response_model=SessionConfigComparisonResponse)
async def read_session_config_comparison(session_id: str, request: Request):
    _require_control(request)
    if request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().read_session_config_comparison(*_credentials(request), session_id))


@router.get("/sessions/{session_id}/parameters", response_model=SessionParametersResponse)
async def read_session_parameters(session_id: str, request: Request):
    _require_control(request)
    if request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().read_session_parameters(*_credentials(request), session_id))


@router.get("/actions/{action}/requests/{request_id}", response_model=ReceiptResponse, response_model_exclude_none=True)
async def receipt(action: str, request_id: str, request: Request):
    _require_control(request)
    if action in {"authorization_upgrade", "authorization_reduce", "authorization_revoke", *PLATFORM_ACTIONS} and request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    if action in {"authorization_reduce", "authorization_revoke", *PLATFORM_ACTIONS}:
        return await _operator_call(request, lambda: _service().receipt(*_credentials(request), action, request_id))
    return await _call(lambda: _service().receipt(*_credentials(request), action, request_id))


from core.web.services.external_management.reconciliation_contracts import ReconciliationResponse


@router.get("/actions/{action}/requests/{request_id}/reconciliation", response_model=ReconciliationResponse)
async def reconcile_request(action: str, request_id: str, request: Request):
    _require_control(request)
    if request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _operator_call(request, lambda: _service().reconcile_request(*_credentials(request), action, request_id))


@router.get("/team-runs/requests/{original_request_id}", response_model=ReceiptResponse, response_model_exclude_none=True)
async def team_receipt(original_request_id: str, request: Request):
    _require_control(request)
    return await _call(lambda: _service().team_receipt(*_credentials(request), original_request_id))


@router.get("/team-runs/requests/{original_request_id}/result", response_model=TeamResultResponse)
async def team_result(original_request_id: str, request: Request):
    _require_control(request)
    if request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().team_result(*_credentials(request), original_request_id))


@router.get("/api-documentation/catalog", response_model=DocumentationResponse, response_model_exclude_none=True)
async def documentation_catalog(request: Request, query: str = "", tag: str = "", offset: int = 0, limit: int = 20):
    _require_control(request)
    if set(request.query_params) - DocumentationCatalogQuery.model_fields.keys():
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().documentation_catalog(*_credentials(request), query=query, tag=tag, offset=offset, limit=limit))


@router.get("/api-documentation/operations/{operation_id}", response_model=DocumentationResponse, response_model_exclude_none=True)
async def documentation_describe(operation_id: str, request: Request):
    _require_control(request)
    if request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().documentation_describe(*_credentials(request), operation_id))
