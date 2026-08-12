"""Server-side operator authorization context (T5.1-6).

Operator identity is never taken from the client command body alone, and never
from client-declared Operator-Id / Operator-Roles headers. HTTP entrypoints must
bind a ServerOperatorContext from the control-plane principal after a valid
control token; missing/invalid control auth yields command_forbidden (403).
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from fastapi import Request

# Legacy header names retained only so callers can detect/reject client claims.
# They MUST NOT grant authority.
OPERATOR_ID_HEADER = "X-Vibelution-Operator-Id"
OPERATOR_ROLES_HEADER = "X-Vibelution-Operator-Roles"

CONTROL_OPERATOR_ID_ENV = "VIBELUTION_RESEARCH_OPERATOR_ID"
CONTROL_OPERATOR_ROLES_ENV = "VIBELUTION_RESEARCH_OPERATOR_ROLES"
_DEFAULT_CONTROL_OPERATOR_ID = "local-control-operator"
_DEFAULT_CONTROL_OPERATOR_ROLES = ("operator", "admin")


@dataclass(frozen=True, slots=True)
class ServerOperatorContext:
    operator_id: str
    display_name: str = ""
    roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "operator_id", str(self.operator_id or "").strip())


_SERVER_OPERATOR: ContextVar[ServerOperatorContext | None] = ContextVar(
    "research_workflow_server_operator",
    default=None,
)


def parse_operator_roles_header(raw: str | None) -> tuple[str, ...]:
    """Parse comma-separated roles (server config / env only)."""
    return tuple(
        part.strip()
        for part in str(raw or "").split(",")
        if part.strip()
    )


def local_control_operator() -> ServerOperatorContext:
    """Server-configured workbench principal (not client-declared)."""
    operator_id = (
        str(os.environ.get(CONTROL_OPERATOR_ID_ENV) or "").strip()
        or _DEFAULT_CONTROL_OPERATOR_ID
    )
    roles_env = str(os.environ.get(CONTROL_OPERATOR_ROLES_ENV) or "").strip()
    roles = (
        parse_operator_roles_header(roles_env)
        if roles_env
        else _DEFAULT_CONTROL_OPERATOR_ROLES
    )
    return ServerOperatorContext(
        operator_id=operator_id,
        display_name="Local control operator",
        roles=roles,
    )


@contextmanager
def server_operator_scope_from_http(
    request: Request,
) -> Iterator[ServerOperatorContext]:
    """Bind the control-plane operator after validating the control token.

    Client ``X-Vibelution-Operator-*`` headers are ignored for authorization.
    """
    from core.web.control import validate_control_request

    error = validate_control_request(request)
    if error is not None:
        raise PermissionError("command_forbidden")
    context = local_control_operator()
    token = bind_server_operator(context)
    try:
        yield context
    finally:
        reset_server_operator(token)


def current_server_operator() -> ServerOperatorContext | None:
    return _SERVER_OPERATOR.get()


def bind_server_operator(context: ServerOperatorContext | None) -> Token:
    return _SERVER_OPERATOR.set(context)


def reset_server_operator(token: Token) -> None:
    _SERVER_OPERATOR.reset(token)


@contextmanager
def server_operator_scope(
    operator_id: str,
    *,
    display_name: str = "",
    roles: tuple[str, ...] = (),
) -> Iterator[ServerOperatorContext]:
    context = ServerOperatorContext(
        operator_id=operator_id,
        display_name=display_name,
        roles=roles,
    )
    token = bind_server_operator(context)
    try:
        yield context
    finally:
        reset_server_operator(token)


def require_server_operator() -> ServerOperatorContext:
    context = current_server_operator()
    if context is None or not context.operator_id:
        raise PermissionError("command_forbidden")
    return context


def require_privileged_server_operator(*, command: str) -> ServerOperatorContext:
    """Identity + role gate for high-impact commands."""
    from .operator_permissions import require_operator_permission

    context = require_server_operator()
    require_operator_permission(
        operator_id=context.operator_id,
        roles=context.roles,
        command=command,
    )
    return context
