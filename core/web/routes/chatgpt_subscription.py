"""Authenticated configuration surface for the local ChatGPT account."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.llm.chatgpt_subscription import ChatGPTSubscriptionError
from core.web.services import chatgpt_subscription_service as service

router = APIRouter(prefix="/config/chatgpt-subscription", tags=["config"])


class SafeModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Account(SafeModel):
    subject: str = Field(max_length=256)
    email: str = Field(default="", max_length=320)


class SafeError(SafeModel):
    code: str = Field(max_length=128)
    message: str = Field(max_length=512)


class LoginState(SafeModel):
    attemptId: str = Field(max_length=128)
    state: str = Field(max_length=64)
    expiresAt: str


class Status(SafeModel):
    state: Literal["connected", "signed_out", "reauth_required", "unavailable"]
    connected: bool
    account: Account | None = None
    expiresAt: str | None = None
    lastError: SafeError | None = None
    login: LoginState | None = None


class LoginStarted(SafeModel):
    attemptId: str
    authorizationUrl: str
    expiresAt: str


class CancelLogin(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    attemptId: str = Field(min_length=16, max_length=128)


class Cancelled(SafeModel):
    cancelled: bool


class Disconnected(SafeModel):
    revocationConfirmed: bool


class ReasoningLevel(SafeModel):
    effort: str = Field(max_length=64)


class SubscriptionModel(SafeModel):
    slug: str = Field(max_length=512)
    display_name: str = Field(default="", max_length=256)
    visibility: Literal["list"] = "list"
    supported_in_api: bool = True
    context_window: int | None = Field(default=None, gt=0)
    input_modalities: list[str] = Field(default_factory=list)
    supported_reasoning_levels: list[ReasoningLevel] = Field(default_factory=list)


class Models(SafeModel):
    models: list[SubscriptionModel]
    provider: dict


def _call(operation, *args):
    try:
        return operation(*args)
    except ChatGPTSubscriptionError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from None


@router.get("/status", response_model=Status)
def get_status():
    return _call(service.subscription_status)


@router.post("/login", response_model=LoginStarted)
def start_login():
    return _call(service.start_subscription_login)


@router.post("/cancel", response_model=Cancelled)
def cancel_login(request: CancelLogin):
    return _call(service.cancel_subscription_login, request.attemptId)


@router.post("/logout", response_model=Disconnected)
def logout():
    return _call(service.disconnect_subscription)


@router.get("/models", response_model=Models)
def get_models():
    return _call(service.subscription_models)
