"""Private loopback API for the Launcher assistant, without Workbench lifespan."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=64000)
    requestId: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


class StopTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turnId: str = Field(min_length=1, max_length=160, pattern=r"\S", strict=True)


class Continuation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turnId: str = Field(min_length=1, max_length=160, pattern=r"\S", strict=True)
    headId: str = Field(min_length=1, max_length=200, pattern=r"\S", strict=True)
    ledgerSeq: int = Field(ge=1, strict=True)
    agentId: str = Field(min_length=1, max_length=160, pattern=r"\S", strict=True)


class ContinueTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$", strict=True)
    continuation: Continuation


class Curation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messageId: str = Field(min_length=1, max_length=160)
    action: str = Field(min_length=1, max_length=40)


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    decision: Literal["accept", "decline"]


class ProjectSnapshot(BaseModel):
    """Main-only authorization projection; deliberately absent from renderer IPC."""
    model_config = ConfigDict(extra="forbid", strict=True)
    schemaVersion: Literal[1]
    revision: int = Field(ge=0)
    projects: dict[str, str] = Field(max_length=128)


def _operator_profile() -> dict[str, str] | None:
    """Read only the two display fields from the bound operator document."""
    from config.editor_schema_data import USER_AVATAR_PRESET_OPTIONS
    from config.paths import resolve_config_path
    from config.public_config import read_existing_config_snapshot

    try:
        config = read_existing_config_snapshot(resolve_config_path())
    except (OSError, ValueError):
        return None
    profile = config.get("user_profile", {})
    if not isinstance(profile, dict):
        return None
    name = profile.get("display_name", "")
    preset = profile.get("avatar_preset", "default")
    if (not isinstance(name, str) or len(name) > 120
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in name)
            or not isinstance(preset, str) or preset not in USER_AVATAR_PRESET_OPTIONS):
        return None
    return {"displayName": name, "avatarPreset": preset}


class NativeFacade:
    """Bind the narrow host API to one immutable native assistant identity."""

    def __init__(self, root):
        self.root = root
        self.assistant = None

    def bootstrap(self):
        from . import native
        result = native.bootstrap(self.root)
        self.assistant = result["assistant"]
        return result

    def get_detail(self):
        from . import native
        return native.get_detail(self.assistant["directSessionId"])

    def identity(self):
        from tools import pa_assistant_actions

        from . import native
        result = native.identity()
        result["operatorAssetsVersion"] = 1
        result["settings"] = pa_assistant_actions.execute("assistant_settings", {}, {}, governed=False)
        profile = _operator_profile()
        if profile is not None:
            result["operatorProfile"] = profile
        return result

    def approvals(self):
        from core.web.services.session.tool_approvals import list_tool_approval_requests
        return list_tool_approval_requests(self.assistant["directSessionId"], status="pending")

    def resolve_approval(self, request_id, decision):
        from core.web.services.session.tool_approvals import (
            resolve_tool_approval_request,
        )
        return resolve_tool_approval_request(self.assistant["directSessionId"], request_id, decision=decision)

    def submit(self, message, request_id):
        from . import native
        return native.submit(message, request_id)

    def stop(self, turn_id):
        from . import native
        return native.stop(turn_id)

    def continue_turn(self, request_id, continuation):
        from . import native
        return native.continue_turn(request_id, continuation)

    def shutdown(self):
        from . import native
        return native.shutdown()

    def config(self):
        from core.web.services.config_service import get_config_bootstrap
        return get_config_bootstrap()

    def curation(self):
        from core.web.services import session_service
        return session_service.get_session_message_curation(self.assistant["directSessionId"])

    def curate(self, message_id, action):
        from core.web.services import session_service
        return session_service.set_session_message_curation(
            self.assistant["directSessionId"], message_id, action=action)

    async def events(self, last_event_id):
        from core.web.services import session_service
        session_id = self.assistant["directSessionId"]
        cursor = session_service.parse_session_stream_last_event_id(last_event_id)
        async for event in session_service.stream_session_events_async(
            session_id, initial="full", last_event_id=cursor
        ):
            yield event


def create_app(*, native, token: str, dispatch=None, main_control=None, on_ready: Callable | None = None,
               on_shutdown: Callable | None = None) -> FastAPI:
    if len(token) < 16:
        raise ValueError("Assistant host requires a private bearer credential")

    async def maintain_dispatches():
        while True:
            try:
                await dispatch.heartbeat()
            except Exception:  # noqa: BLE001, S110 - private backend errors must not enter host logs.
                # Native IDs and credentials remain durable. A failed poll is
                # not permission to repeat a task or cancel it.
                pass
            await asyncio.sleep(10)

    @asynccontextmanager
    async def lifespan(app):
        task = None
        bound = False
        try:
            if dispatch is not None:
                from .actions import bind_actions, unbind_actions
                bind_actions(dispatch, asyncio.get_running_loop(), main_control=main_control)
                bound = True
            # Native startup recovery can immediately resume a tool-using
            # worker. Its authorized action owner must already be available.
            app.state.assistant = await asyncio.to_thread(native.bootstrap)
            if dispatch is not None:
                task = asyncio.create_task(maintain_dispatches())
            if on_ready is not None:
                on_ready()
            yield
        finally:
            # Release synchronous tool waiters before draining their native
            # worker; shutdown must never wait on its own main-control request.
            if main_control is not None:
                main_control.close()
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            # Native own chat is drained; remote tasks are never cancelled by
            # an HTTP connection, renderer close, or this host's shutdown.
            try:
                await asyncio.to_thread(native.shutdown)
            finally:
                if bound:
                    unbind_actions(dispatch)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    from .native import AssistantSessionError

    @app.exception_handler(AssistantSessionError)
    async def session_command_error(_request: Request, error: AssistantSessionError):
        errors = {
            "ASSISTANT_NOT_READY": (503, "Native assistant is not ready"),
            "ASSISTANT_STOPPING": (503, "Native assistant is stopping"),
            "ASSISTANT_IDENTITY_INVALID": (409, "Native assistant identity changed"),
            "SESSION_NOT_FOUND": (404, "Native assistant session not found"),
            "SESSION_CONFLICT": (409, "Native session changed; refresh before retrying"),
            "SESSION_INVALID": (422, "Native session command is invalid"),
        }
        status, message = errors.get(error.code, (500, "Native session command failed"))
        code = error.code if error.code in errors else "SESSION_OPERATION_FAILED"
        return JSONResponse({"detail": {"code": code, "message": message}}, status_code=status)

    @app.middleware("http")
    async def private_launcher_boundary(request: Request, call_next):
        host = request.url.hostname
        if host not in {"127.0.0.1", "localhost"} or request.headers.get("origin"):
            return JSONResponse({"error": "launcher_origin_required"}, status_code=403)
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied, "Bearer " + token):
            return JSONResponse({"error": "launcher_auth_required"}, status_code=401)
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"status": "ok", "role": "launcher_assistant", "protocolVersion": 1,
                **({"mainControlVersion": 1} if main_control is not None else {})}

    if main_control is not None:
        async def main_control_body(request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid main control protocol")
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 4096:
                    raise HTTPException(413, detail="Main control payload is too large")
                body.extend(chunk)
            return body

        @app.get("/api/assistant/main-control/next")
        async def main_control_next(request: Request):
            if await main_control_body(request):
                raise HTTPException(422, detail="Invalid main control protocol")
            return await main_control.claim()

        @app.post("/api/assistant/main-control/settle")
        async def main_control_settle(request: Request):
            body = await main_control_body(request)

            def unique_object(pairs):
                value = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError("Duplicate protocol field")
                    value[key] = item
                return value

            try:
                payload = json.loads(body, object_pairs_hook=unique_object)
                if (type(payload) is not dict or set(payload) != {"schemaVersion", "deliveryId", "result"}
                        or type(payload["schemaVersion"]) is not int or payload["schemaVersion"] != 1
                        or type(payload["result"]) is not dict):
                    raise ValueError("Invalid main control envelope")
                accepted = main_control.settle(payload["deliveryId"], payload["result"])
            except (ValueError, UnicodeDecodeError, RecursionError):
                raise HTTPException(422, detail="Invalid main control protocol") from None
            return {"schemaVersion": 1, "accepted": accepted}

    if on_shutdown is not None:
        @app.post("/api/assistant/shutdown")
        def shutdown():
            on_shutdown()
            return {"stopping": True}

    if dispatch is not None:
        @app.put("/api/assistant/project-registry")
        async def project_registry(payload: ProjectSnapshot):
            from .dispatch import DispatchError
            try:
                # One event loop owns this immutable view and all native calls.
                # No background thread may race an admission with this update.
                return dispatch.replace_projects(payload.model_dump())
            except DispatchError as exc:
                raise HTTPException(409, detail={"code": exc.code}) from None

    @app.get("/api/assistant")
    def assistant():
        return native.identity() if callable(getattr(native, "identity", None)) else app.state.assistant

    @app.get("/api/assistant/approvals")
    def approvals():
        return native.approvals()

    @app.post("/api/assistant/approvals/decision")
    def resolve_approval(payload: ApprovalDecision):
        from core.web.services.session.tool_approvals import (
            ToolApprovalConflictError,
            ToolApprovalError,
            ToolApprovalNotFoundError,
        )
        try:
            return native.resolve_approval(payload.requestId, payload.decision)
        except ToolApprovalNotFoundError:
            raise HTTPException(404, detail="Native approval not found") from None
        except ToolApprovalConflictError:
            raise HTTPException(409, detail="Native approval already resolved") from None
        except ToolApprovalError:
            raise HTTPException(422, detail="Native approval could not be resolved") from None

    @app.get("/api/assistant/session")
    def detail():
        return native.get_detail()

    @app.get("/api/assistant/config")
    def config():
        return native.config()

    @app.get("/api/assistant/operator-assets/{kind}")
    async def operator_asset(kind: Literal["avatar", "background"], request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid operator asset request")
        from .operator_assets import read_operator_asset
        try:
            return await asyncio.to_thread(read_operator_asset, kind)
        except ValueError:
            raise HTTPException(503, detail={"code": "operator_asset_unavailable"}) from None

    @app.get("/api/assistant/curation")
    def curation():
        return native.curation()

    @app.post("/api/assistant/curation")
    def curate(payload: Curation):
        return native.curate(payload.messageId, payload.action)

    @app.post("/api/assistant/messages")
    def message(payload: Message):
        try:
            return native.submit(payload.message, payload.requestId)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/assistant/stop", status_code=202)
    def stop(payload: StopTurn):
        return native.stop(payload.turnId)

    @app.post("/api/assistant/continue", status_code=202)
    def continue_turn(payload: ContinueTurn):
        return native.continue_turn(payload.requestId, payload.continuation.model_dump())

    @app.get("/api/assistant/events")
    async def events(request: Request):
        try:
            from core.web.services import session_service
            session_service.parse_session_stream_last_event_id(request.headers.get("last-event-id", ""))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid native event cursor") from exc
        return StreamingResponse(native.events(request.headers.get("last-event-id", "")),
                                 media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    if dispatch is not None:
        @app.get("/api/assistant/dispatches")
        def dispatches():
            return {"dispatches": dispatch.list_dispatches()}

    return app
