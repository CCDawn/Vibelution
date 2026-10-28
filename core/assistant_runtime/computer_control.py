"""Launcher-private operator transport for the existing single-window owner.

Mount only in the Launcher assistant host, with its main-owned bearer token.
The model tools are deliberately absent here: selection and confirmation are
operator operations and must pass through the owned Electron main frame.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request

from core.web.routes.personal_assistant_computer import Confirmation, Control, Grant, State, Windows
from core.web.services import personal_assistant_computer_service as service


def create_router(token: str) -> APIRouter:
    if not isinstance(token, str) or len(token) < 16:
        raise ValueError("Launcher host token is required")

    def require_main(request: Request) -> None:
        if request.url.hostname not in {"127.0.0.1", "localhost"} or request.headers.get("origin"):
            raise HTTPException(403, "Launcher control source required")
        if not secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            raise HTTPException(401, "Launcher authorization required")

    router = APIRouter(prefix="/api/assistant/computer", dependencies=[Depends(require_main)])

    def call(method, *args):
        try:
            return method(*args)
        except (ValueError, OSError, service.CuaDriverError):
            # Never return native exception details, paths or driver payloads.
            raise HTTPException(409, "电脑控制状态已变化或驱动不可用，请刷新后重试。") from None

    @router.get("", response_model=State)
    def state():
        return call(service.get_state)

    # Enumeration replaces the current selection tokens and is therefore a
    # mutation; POST lets the host migration barrier reject it when fenced.
    @router.post("/windows", response_model=Windows)
    def windows():
        return call(service.list_windows)

    @router.post("/grant", response_model=State)
    def grant(payload: Grant):
        return call(service.grant_window, payload.selectionId, payload.allowVision)

    @router.post("/control", response_model=State)
    def control(payload: Control):
        return call(service.control, payload.grantId, payload.action)

    @router.post("/confirm", response_model=State)
    def confirm(payload: Confirmation):
        return call(service.confirm, payload.grantId, payload.pendingId, payload.approved)

    return router
