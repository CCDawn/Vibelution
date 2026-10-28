"""Private loopback API for the Launcher assistant, without Workbench lifespan."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from contextlib import nullcontext
from functools import partial
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator


_INITIAL_PREPARE_CODES = frozenset({
    "initial_migration_request_invalid", "initial_migration_busy", "initial_migration_unavailable",
    "initial_migration_turn_invalid", "initial_migration_binding_invalid", "initial_migration_binding_changed",
    "initial_migration_directory_identity_unavailable", "initial_intent_invalid", "initial_intent_limit",
    "initial_intent_exists", "initial_intent_claimed_unknown", "initial_profile_owner_unavailable",
    "initial_delivery_unavailable", "history_preview_expired", "history_preview_changed",
    "history_source_unavailable", "source_unavailable", "source_changed",
})


def _initial_prepare_failure_code(error):
    """Use only a closed list of internal codes; exceptions may contain paths or secrets."""
    from .migration_io import MigrationIOError
    if isinstance(error, MigrationIOError):
        code = str(error)
        return code if code in _INITIAL_PREPARE_CODES else "migration_error"
    if isinstance(error, PermissionError):
        return "permission_error"
    if isinstance(error, FileNotFoundError):
        return "filesystem_missing"
    if isinstance(error, OSError):
        return "filesystem_error"
    if isinstance(error, ValueError):
        return "value_error"
    return "unexpected_error"


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


class ReminderSettlement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    eventId: str = Field(pattern=r"^reminder:[0-9]{8}:[a-f0-9]{64}$")
    attemptToken: str = Field(pattern=r"^[a-f0-9]{64}$")
    channel: Literal["assistant_window", "system_notification", "attention_fallback"]


class ReminderFallback(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    eventId: str = Field(pattern=r"^reminder:[0-9]{8}:[a-f0-9]{64}$")
    attemptToken: str = Field(pattern=r"^[a-f0-9]{64}$")


class LegacyReminderReservation(BaseModel):
    """Private main-only request; sourceKey is bound by Electron main."""
    model_config = ConfigDict(extra="forbid", strict=True)
    sourceKey: str = Field(pattern=r"^[a-f0-9]{64}$")
    eventId: str = Field(max_length=128, pattern=r"^affair-reminder:[A-Za-z0-9._:-]{1,103}:[0-9]{8}$")


class LegacyReminderAttempt(LegacyReminderReservation):
    attemptToken: str = Field(pattern=r"^[a-f0-9]{64}$")


class LegacyReminderSettlement(LegacyReminderAttempt):
    channel: Literal["assistant_window", "system_notification", "attention_fallback"]


class LegacyReminderSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    projectId: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
    revision: int = Field(ge=0, le=2**53 - 1)


class ProjectSnapshot(BaseModel):
    """Main-only authorization projection; deliberately absent from renderer IPC."""
    model_config = ConfigDict(extra="forbid", strict=True)
    schemaVersion: Literal[1]
    revision: int = Field(ge=0)
    projects: dict[str, str] = Field(max_length=128)


class SuspendProjects(BaseModel):
    """Main may only close the gate; restoring requires a full snapshot PUT."""
    model_config = ConfigDict(extra="forbid", strict=True)


class HistoryImport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    projectId: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
    previewId: str = Field(pattern=r"^[a-f0-9]{64}$")
    turnId: str = Field(min_length=1, max_length=160, pattern=r"^\S+$")
    revision: int = Field(ge=0)
    operationId: str = Field(pattern=r"^[a-f0-9]{32}$")


class AffairsSync(HistoryImport):
    recoverSyncId: str | None = Field(default=None, pattern=r"^affairs-[a-f0-9]{40}$")


class EpisodicSync(HistoryImport):
    recoverSyncId: str | None = Field(default=None, pattern=r"^episodic-[a-f0-9]{40}$")
    resolveSyncId: str | None = Field(default=None, pattern=r"^episodic-[a-f0-9]{40}$")
    reviewToken: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def resolution_binding(self):
        if ((self.resolveSyncId is None) != (self.reviewToken is None)
                or self.resolveSyncId is not None and self.recoverSyncId is not None):
            raise ValueError("Invalid episodic resolution")
        return self


class InitialMigrationPrepare(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    deliveryId: str = Field(pattern=r"^[a-f0-9]{32}$")
    projectId: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
    previewId: str = Field(pattern=r"^[a-f0-9]{64}$")
    turnId: str = Field(min_length=1, max_length=160, pattern=r"^\S+$")
    revision: int = Field(ge=0)
    operationId: str = Field(pattern=r"^initial-[a-f0-9]{40}$")
    category: Literal["personal", "knowledge"]


class InitialMigrationDrain(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    deliveryId: str = Field(pattern=r"^[a-f0-9]{32}$")
    operationId: str = Field(pattern=r"^initial-[a-f0-9]{40}$")


class CancelHistoryImport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operationId: str = Field(pattern=r"^[a-f0-9]{32}$")
    previewId: str = Field(pattern=r"^[a-f0-9]{64}$")


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


def create_app(*, native, token: str, dispatch=None, main_control=None, history_control=None, on_ready: Callable | None = None,
               on_shutdown: Callable | None = None) -> FastAPI:
    if len(token) < 16:
        raise ValueError("Assistant host requires a private bearer credential")
    if main_control is not None and history_control is not None:
        bind_retirement = getattr(main_control, "bind_preview_retirement", None)
        if callable(bind_retirement):
            bind_retirement(history_control.retire_preview)

    @asynccontextmanager
    async def initial_fence(turn_id=None, *, registry=False):
        if main_control is None or not getattr(main_control, "initial_migration_enabled", False):
            yield
            return
        tokens = main_control.begin_initial_fence(turn_id)
        try:
            if not await asyncio.to_thread(main_control.drain_initial_fence, tokens):
                raise HTTPException(503, detail="Initial migration publication outcome unknown")
            if registry and tokens and history_control is not None:
                if not await asyncio.to_thread(history_control.wait_guard_idle):
                    raise HTTPException(503, detail="Initial migration publication outcome unknown")
            yield
        finally:
            main_control.end_initial_fence(turn_id)

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
        reminder_executor = None
        legacy_reminder_executor = None
        try:
            if dispatch is not None:
                from .actions import bind_actions, unbind_actions
                bind_actions(dispatch, asyncio.get_running_loop(), main_control=main_control)
                bound = True
            # Native startup recovery can immediately resume a tool-using
            # worker. Its authorized action owner must already be available.
            app.state.assistant = await asyncio.to_thread(native.bootstrap)
            if isinstance(native, NativeFacade):
                from .reminders import LauncherReminders
                reminder_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="assistant-reminders")
                app.state.reminder_executor = reminder_executor
                app.state.reminders = await asyncio.get_running_loop().run_in_executor(
                    reminder_executor, LauncherReminders, native.root, native.assistant["agentId"])
                from .legacy_reminder_receipts import LegacyReminderReceipts
                legacy_reminder_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="legacy-reminder-receipts")
                app.state.legacy_reminder_executor = legacy_reminder_executor
                app.state.legacy_reminder_receipts = await asyncio.get_running_loop().run_in_executor(
                    legacy_reminder_executor, LegacyReminderReceipts, native.root / "legacy_reminder_receipts")
            if dispatch is not None:
                task = asyncio.create_task(maintain_dispatches())
            if on_ready is not None:
                on_ready()
            yield
        finally:
            if history_control is not None:
                await asyncio.to_thread(history_control.close)
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
                try:
                    try:
                        if legacy_reminder_executor is not None and hasattr(app.state, "legacy_reminder_receipts"):
                            await asyncio.get_running_loop().run_in_executor(legacy_reminder_executor, app.state.legacy_reminder_receipts.close)
                    finally:
                        if reminder_executor is not None and hasattr(app.state, "reminders"):
                            await asyncio.get_running_loop().run_in_executor(reminder_executor, app.state.reminders.close)
                finally:
                    try:
                        if legacy_reminder_executor is not None:
                            await asyncio.to_thread(legacy_reminder_executor.shutdown, wait=True)
                    finally:
                        try:
                            if reminder_executor is not None:
                                await asyncio.to_thread(reminder_executor.shutdown, wait=True)
                        finally:
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
                **({"mainControlVersion": 1} if main_control is not None else {}),
                **({"initialMigrationControlVersion": 1} if main_control is not None and getattr(main_control, "initial_migration_enabled", False) else {}),
                **({"appearanceControlVersion": 1} if main_control is not None and getattr(main_control, "appearance_enabled", False) else {})}

    async def reminder_call(method, *args, **kwargs):
        from .reminder_receipts import ReminderReceiptError
        if not hasattr(app.state, "reminders"):
            raise HTTPException(503, detail={"code": "reminder_unavailable"})
        try:
            return await asyncio.get_running_loop().run_in_executor(
                app.state.reminder_executor, partial(getattr(app.state.reminders, method), *args, **kwargs))
        except ReminderReceiptError as error:
            code = str(error)
            permanent = {
                "reminder_imported_profile_blocked", "receipt_capacity_exceeded",
                "receipt_admission_closed", "receipt_schema_invalid",
                "receipt_integrity_failed", "receipt_owner_or_capacity_mismatch",
                "receipt_header_invalid", "receipt_namespace_invalid",
                "receipt_file_budget_exceeded",
            }
            raise HTTPException(409 if code in permanent else 503, detail={"code": code}) from None
        except Exception:
            raise HTTPException(503, detail={"code": "reminder_unavailable"}) from None

    @app.post("/api/assistant/reminders/next")
    async def reminder_next(request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid reminder request")
        return JSONResponse(await reminder_call("next"), headers={"Cache-Control": "no-store"})

    @app.post("/api/assistant/reminders/submitted")
    async def reminder_submitted(payload: ReminderSettlement, request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid reminder request")
        result = await reminder_call("settle", payload.eventId, payload.attemptToken, payload.channel, opened=False)
        return {"schemaVersion": 1, "receipt": result}

    @app.post("/api/assistant/reminders/opened")
    async def reminder_opened(payload: ReminderSettlement, request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid reminder request")
        result = await reminder_call("settle", payload.eventId, payload.attemptToken, payload.channel, opened=True)
        return {"schemaVersion": 1, "receipt": result}

    @app.post("/api/assistant/reminders/fallback")
    async def reminder_fallback(payload: ReminderFallback, request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid reminder request")
        result = await reminder_call("fallback", payload.eventId, payload.attemptToken)
        return {"schemaVersion": 1, "receipt": result}

    async def legacy_reminder_call(method, payload, request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid legacy reminder request")
        if not hasattr(app.state, "legacy_reminder_receipts"):
            raise HTTPException(503, detail={"code": "legacy_reminder_unavailable"})
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                app.state.legacy_reminder_executor,
                partial(getattr(app.state.legacy_reminder_receipts, method), payload.model_dump()))
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except Exception:
            # The RPC result may be unknown after a committed write. Do not retry.
            raise HTTPException(503, detail={"code": "legacy_reminder_unavailable"}) from None

    @app.post("/api/assistant/legacy-reminders/reserve")
    async def legacy_reminder_reserve(payload: LegacyReminderReservation, request: Request):
        return await legacy_reminder_call("reserve", payload, request)

    @app.post("/api/assistant/legacy-reminders/settle")
    async def legacy_reminder_settle(payload: LegacyReminderSettlement, request: Request):
        return await legacy_reminder_call("settle", payload, request)

    @app.post("/api/assistant/legacy-reminders/abandon")
    async def legacy_reminder_abandon(payload: LegacyReminderAttempt, request: Request):
        return await legacy_reminder_call("abandon", payload, request)

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
        async def shutdown():
            # Wake main-control long polls on their owning event loop before
            # Uvicorn starts waiting for HTTP requests to drain.
            if main_control is not None:
                main_control.close()
            if history_control is not None:
                await asyncio.to_thread(history_control.close)
            on_shutdown()
            return {"stopping": True}

    if dispatch is not None:
        @app.post("/api/assistant/project-registry/suspend")
        async def suspend_project_registry(payload: SuspendProjects, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid private project suspension")
            if history_control is not None:
                history_control.signal_registry_change()
            async with initial_fence(registry=True):
                with history_control.guard() if history_control is not None else nullcontext():
                    if history_control is not None:
                        history_control.registry_changed()
                    return dispatch.suspend_projects()

        @app.put("/api/assistant/project-registry")
        async def project_registry(payload: ProjectSnapshot):
            from .dispatch import DispatchError
            try:
                # One event loop owns this immutable view and all native calls.
                # No background thread may race an admission with this update.
                if history_control is not None:
                    history_control.signal_registry_change()
                async with initial_fence(registry=True):
                    with history_control.guard() if history_control is not None else nullcontext():
                        if history_control is not None:
                            history_control.registry_changed()
                        return dispatch.replace_projects(payload.model_dump())
            except DispatchError as exc:
                raise HTTPException(409, detail={"code": exc.code}) from None

    if history_control is not None:
        @app.post("/api/assistant/legacy-reminders/source")
        async def legacy_reminder_source(payload: LegacyReminderSource, request: Request):
            from .migration_io import MigrationIOError
            if request.query_params:
                raise HTTPException(422, detail="Invalid legacy reminder source request")
            try:
                result = await asyncio.to_thread(history_control.legacy_reminder_source,
                                                 payload.projectId, payload.revision)
            except MigrationIOError:
                raise HTTPException(409, detail="Legacy reminder source unavailable") from None
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        if main_control is not None and getattr(main_control, "initial_migration_enabled", False):
            @app.post("/api/assistant/initial-migration/prepare")
            async def prepare_initial_migration(payload: InitialMigrationPrepare, request: Request):
                if request.query_params:
                    raise HTTPException(422, detail="Invalid initial migration request")
                bound = {key: getattr(payload, key) for key in ("projectId", "previewId", "turnId", "category", "operationId")}
                publication = main_control.initial_delivery(payload.deliveryId, bound, admit=True)
                if not publication:
                    logging.getLogger(__name__).warning("assistant_initial_prepare category=%s phase=admission code=delivery_unavailable", payload.category)
                    raise HTTPException(409, detail="Initial migration delivery unavailable")
                def prepare():
                    try:
                        return history_control.prepare_initial_source(payload.projectId, payload.previewId,
                            payload.revision, payload.turnId, payload.operationId, payload.category, publication)
                    finally:
                        publication.finished()
                phase = "prepare"
                try:
                    result = await asyncio.to_thread(prepare)
                    phase = "confirmation"
                    if not main_control.initial_delivery(payload.deliveryId, bound, confirm=True):
                        raise ValueError("delivery changed")
                except Exception as error:
                    logging.getLogger(__name__).warning("assistant_initial_prepare category=%s phase=%s code=%s",
                        payload.category, phase, _initial_prepare_failure_code(error))
                    history_control.retire_preview(payload.previewId)
                    raise HTTPException(409, detail="Initial migration source unavailable") from None
                return JSONResponse(result, headers={"Cache-Control": "no-store"})

            @app.post("/api/assistant/initial-migration/drain")
            async def drain_initial_migration(payload: InitialMigrationDrain, request: Request):
                if request.query_params:
                    raise HTTPException(422, detail="Invalid initial migration request")
                found, publication = main_control.begin_initial_drain(payload.deliveryId, payload.operationId)
                drained = found and (publication is None or await asyncio.to_thread(publication.wait_finished, 2.0))
                return JSONResponse({"schemaVersion": 1, "operationId": payload.operationId,
                                     "state": "unknown", "drained": bool(drained)},
                                    status_code=200 if drained else 503,
                                    headers={"Cache-Control": "no-store"})

        @app.post("/api/assistant/affairs-sync")
        async def affairs_sync(payload: AffairsSync, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid affairs sync request")
            args = (payload.projectId, payload.previewId, payload.revision, payload.turnId, payload.operationId)
            if payload.recoverSyncId is None:
                result = await asyncio.to_thread(history_control.sync_affairs, *args)
            else:
                result = await asyncio.to_thread(history_control.sync_affairs, *args, payload.recoverSyncId)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        @app.post("/api/assistant/affairs-sync/cancel")
        async def affairs_sync_cancel(payload: CancelHistoryImport, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid affairs sync cancellation")
            try:
                return await asyncio.to_thread(history_control.cancel_affairs, payload.operationId, payload.previewId)
            except Exception:
                raise HTTPException(503, detail="Affairs sync cancellation unavailable") from None

        @app.post("/api/assistant/episodic-sync")
        async def episodic_sync(payload: EpisodicSync, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid episodic sync request")
            args = (payload.projectId, payload.previewId, payload.revision, payload.turnId, payload.operationId)
            result = await asyncio.to_thread(history_control.sync_episodic, *args, payload.recoverSyncId,
                                             payload.resolveSyncId, payload.reviewToken)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        @app.post("/api/assistant/episodic-sync/cancel")
        async def episodic_sync_cancel(payload: CancelHistoryImport, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid episodic sync cancellation")
            try:
                return await asyncio.to_thread(history_control.cancel_affairs, payload.operationId, payload.previewId)
            except Exception:
                raise HTTPException(503, detail="Episodic sync cancellation unavailable") from None

        @app.post("/api/assistant/history-import")
        async def history_import(payload: HistoryImport, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid history import request")
            result = await asyncio.to_thread(history_control.import_history, payload.projectId,
                payload.previewId, payload.revision, payload.turnId, payload.operationId)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        @app.post("/api/assistant/history-import/cancel")
        async def history_cancel(payload: CancelHistoryImport, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid history import request")
            try:
                return await asyncio.to_thread(history_control.cancel, payload.operationId, payload.previewId)
            except Exception:
                raise HTTPException(503, detail="History cancellation unavailable") from None

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

    if main_control is not None and getattr(main_control, "appearance_enabled", False):
        @app.post("/api/assistant/operator-assets/{kind}")
        async def import_operator_asset(kind: Literal["avatar", "background"], request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid operator asset request")
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 14 * 1024 * 1024:
                    raise HTTPException(413, detail="Operator image payload is too large")
                body.extend(chunk)
            def unique(pairs):
                value = {}
                for key, item in pairs:
                    if key in value: raise ValueError("Duplicate field")
                    value[key] = item
                return value
            try:
                payload = json.loads(body, object_pairs_hook=unique)
                if type(payload) is not dict or set(payload) != {"deliveryId", "filename", "contentType", "dataBase64"} or any(type(v) is not str for v in payload.values()):
                    raise ValueError("Invalid payload")
            except (ValueError, UnicodeDecodeError, RecursionError):
                raise HTTPException(422, detail="Invalid operator image payload") from None
            if not main_control.admit_image_import(payload["deliveryId"], kind):
                raise HTTPException(409, detail="Operator image request is no longer active")
            from .operator_image_actions import import_operator_image
            return await asyncio.to_thread(import_operator_image, kind, payload["filename"], payload["contentType"], payload["dataBase64"])

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
    async def stop(payload: StopTurn):
        async with initial_fence(payload.turnId.strip()):
            if history_control is not None:
                result = await asyncio.to_thread(history_control.stop_native_turn, native.stop, payload.turnId.strip())
            else:
                result = await asyncio.to_thread(native.stop, payload.turnId)
            if main_control is not None and getattr(main_control, "appearance_enabled", False):
                main_control.cancel_image_imports(payload.turnId.strip())
            cancel_history = getattr(main_control, "cancel_history_imports", None)
            if callable(cancel_history):
                cancel_history(payload.turnId.strip())
            return result

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
