"""Operator-control authenticated transport for closed, neutral target management."""
from __future__ import annotations

import json
import re
from pathlib import Path

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
    TeamKnowledgeResponse,
)
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


def _directory_query(request, *, detail=False):
    values = request.query_params
    allowed = {"member_offset", "limit"} if detail else DirectoryQuery.model_fields.keys()
    if (set(values) - allowed or len(values.multi_items()) != len(values)
        or any(not re.fullmatch(r"[0-9]{1,6}", values[key]) for key in ("offset", "member_offset", "limit") if key in values)
        or "archived" in values and values["archived"].casefold() not in {"true", "false"}):
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})


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
    payload = await _body(request, unique_keys=action == "authorization_upgrade")
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
    if action == "authorization_upgrade" and request.query_params:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT"})
    return await _call(lambda: _service().receipt(*_credentials(request), action, request_id))


@router.get("/team-runs/requests/{original_request_id}", response_model=ReceiptResponse, response_model_exclude_none=True)
async def team_receipt(original_request_id: str, request: Request):
    _require_control(request)
    return await _call(lambda: _service().team_receipt(*_credentials(request), original_request_id))


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
