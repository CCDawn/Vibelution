import time
from concurrent.futures import Future
from threading import Event, Thread

from core.infrastructure.tool_executor import ToolExecutor
from core.infrastructure.tool_execution_scope import (
    ToolExecutionScope,
    current_tool_execution_scope,
    register_current_tool_future,
    tool_execution_scope,
)


def test_tool_execution_scope_waits_for_registered_future():
    scope = ToolExecutionScope(session_id="session-a", turn_id="turn-a")
    future: Future[str] = Future()

    with tool_execution_scope(scope):
        assert current_tool_execution_scope() is scope
        assert register_current_tool_future(future, tool_name="slow_tool") is True
    assert current_tool_execution_scope() is None

    scope.seal()
    assert scope.pending_count == 1
    assert scope.wait_for_quiescence(timeout=0.01) is False
    assert scope.snapshot()["pendingTools"] == ["slow_tool"]

    future.set_result("done")

    assert scope.wait_for_quiescence(timeout=0.1) is True
    assert scope.is_quiescent() is True


def test_tool_execution_scope_unblocks_waiter_after_future_finishes():
    scope = ToolExecutionScope(session_id="session-a", turn_id="turn-a")
    future: Future[str] = Future()
    scope.register(future, tool_name="slow_tool")
    scope.seal()
    settled = Event()

    waiter = Thread(
        target=lambda: settled.set() if scope.wait_for_quiescence(timeout=1) else None,
    )
    waiter.start()
    assert settled.wait(0.02) is False

    future.set_result("done")

    assert settled.wait(0.2) is True
    waiter.join(timeout=1)


def test_register_current_tool_future_is_noop_without_scope():
    future: Future[str] = Future()

    assert register_current_tool_future(future, tool_name="tool") is False


def test_tool_executor_registers_running_tool_until_physical_completion():
    executor = ToolExecutor()
    scope = ToolExecutionScope(session_id="session-a", turn_id="turn-a")
    started = Event()
    release = Event()
    result: list[tuple[object, object]] = []

    def blocking_tool() -> str:
        started.set()
        assert release.wait(1)
        return "done"

    executor.register_tool("blocking_test_tool", blocking_tool, timeout=2)

    def execute_tool() -> None:
        with tool_execution_scope(scope):
            result.append(executor.execute("blocking_test_tool", {}))
        scope.seal()

    worker = Thread(target=execute_tool)
    worker.start()
    assert started.wait(0.5)

    deadline = time.monotonic() + 0.5
    while scope.pending_count == 0 and time.monotonic() < deadline:
        time.sleep(0.005)

    assert scope.pending_count == 1
    assert scope.snapshot()["pendingTools"] == ["blocking_test_tool"]
    assert scope.wait_for_quiescence(timeout=0.01) is False

    release.set()
    worker.join(timeout=1)

    assert worker.is_alive() is False
    assert result == [("done", None)]
    assert scope.wait_for_quiescence(timeout=0.1) is True
