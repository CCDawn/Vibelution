from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Callable, Iterator

from core.authorization import tool_authorization_service
from core.infrastructure.tool_executor import ToolExecutor
from core.web.services import agent_directory_service


AuthorizedToolExecute = Callable[[str, dict[str, Any]], tuple[Any, Any]]


@contextmanager
def authorized_agent_tool_executor(
    agent_id: str,
    *,
    session_id: str = "",
    executable_tools: tuple[str, ...],
    turn_id: str = "",
) -> Iterator[AuthorizedToolExecute]:
    normalized_turn_id = str(turn_id or f"turn-test-{agent_id}").strip()
    executor = ToolExecutor()
    call_index = 0
    with agent_directory_service.active_agent_runtime(
        agent_id,
        session_id=session_id,
        turn_id=normalized_turn_id,
    ):
        tool_authorization_service.install_execution_authorization(
            SimpleNamespace(
                decision=SimpleNamespace(
                    agent_id=agent_id,
                    turn_id=normalized_turn_id,
                    decision_fingerprint=f"decision-test-{agent_id}-{normalized_turn_id}",
                    executable_tools=tuple(executable_tools),
                )
            )
        )

        def execute(tool_name: str, tool_args: dict[str, Any]) -> tuple[Any, Any]:
            nonlocal call_index
            call_index += 1
            return executor.execute(
                tool_name,
                tool_args,
                tool_call_id=f"call-test-{call_index}-{tool_name}",
            )

        try:
            yield execute
        finally:
            tool_authorization_service.clear_execution_authorization()


def execute_authorized_agent_tool(
    agent_id: str,
    session_id: str,
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    executable_tools: tuple[str, ...] | None = None,
    turn_id: str = "",
) -> tuple[Any, Any]:
    allowed_tools = tuple(executable_tools) if executable_tools is not None else (tool_name,)
    with authorized_agent_tool_executor(
        agent_id,
        session_id=session_id,
        executable_tools=allowed_tools,
        turn_id=turn_id,
    ) as execute:
        return execute(tool_name, tool_args)
