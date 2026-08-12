"""Server-side operator authorization context (T5.1-6).

Operator identity is never taken from the client command body alone. HTTP /
service entrypoints must bind a ServerOperatorContext before submitting
high-impact commands; missing context yields command_forbidden (403).
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator


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
