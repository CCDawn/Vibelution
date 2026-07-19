from __future__ import annotations

import ast
from pathlib import Path


TESTS_ROOT = Path(__file__).resolve().parent


def _is_tool_executor_constructor(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ToolExecutor"
    )


def _tool_executor_instance_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for candidate in ast.walk(node):
        if isinstance(candidate, (ast.Assign, ast.AnnAssign)):
            value = candidate.value
            targets = candidate.targets if isinstance(candidate, ast.Assign) else [candidate.target]
        else:
            continue
        if not _is_tool_executor_constructor(value):
            continue
        names.update(target.id for target in targets if isinstance(target, ast.Name))
    return names


def _is_tool_executor_execute(call: ast.Call, instance_names: set[str]) -> bool:
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "execute":
        return False
    receiver = call.func.value
    return _is_tool_executor_constructor(receiver) or (
        isinstance(receiver, ast.Name)
        and receiver.id in instance_names
    )


def _missing_call_id_calls(
    node: ast.AST,
    *,
    known_instance_names: set[str] | None = None,
) -> list[ast.Call]:
    instance_names = _tool_executor_instance_names(node) | set(known_instance_names or ())
    return [
        candidate
        for candidate in ast.walk(node)
        if isinstance(candidate, ast.Call)
        and _is_tool_executor_execute(candidate, instance_names)
        and not any(keyword.arg == "tool_call_id" for keyword in candidate.keywords)
    ]


def _is_active_agent_runtime_context(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == "active_agent_runtime")
            or (isinstance(node.func, ast.Name) and node.func.id == "active_agent_runtime")
        )
    )


def _contract_violations(path: Path, source: str) -> list[str]:
    tree = ast.parse(source, filename=str(path))
    known_instance_names = _tool_executor_instance_names(tree)
    unsafe_helpers = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _missing_call_id_calls(node)
    }
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        if not any(_is_active_agent_runtime_context(item.context_expr) for item in node.items):
            continue
        for statement in node.body:
            for call in _missing_call_id_calls(
                statement,
                known_instance_names=known_instance_names,
            ):
                violations.append(f"{path}:{call.lineno}: ToolExecutor.execute is missing tool_call_id")
            for call in (
                candidate
                for candidate in ast.walk(statement)
                if isinstance(candidate, ast.Call) and isinstance(candidate.func, ast.Name)
            ):
                if call.func.id in unsafe_helpers:
                    violations.append(
                        f"{path}:{call.lineno}: {call.func.id} bypasses the shared authorization helper"
                    )
    return violations


def test_contract_detector_rejects_direct_missing_call_id():
    source = """
from core.infrastructure.tool_executor import ToolExecutor

with agent_directory_service.active_agent_runtime("agent-a"):
    ToolExecutor().execute("agent_message_tool", {})
"""

    violations = _contract_violations(Path("direct.py"), source)

    assert violations == ["direct.py:5: ToolExecutor.execute is missing tool_call_id"]


def test_contract_detector_rejects_local_executor_wrapper():
    source = """
from core.infrastructure.tool_executor import ToolExecutor

def execute_tool(name, args):
    return ToolExecutor().execute(name, args)

with agent_directory_service.active_agent_runtime("agent-a"):
    execute_tool("agent_message_tool", {})
"""

    violations = _contract_violations(Path("wrapper.py"), source)

    assert violations == ["wrapper.py:8: execute_tool bypasses the shared authorization helper"]


def test_contract_detector_rejects_executor_bound_before_runtime_context():
    source = """
from core.infrastructure.tool_executor import ToolExecutor

executor = ToolExecutor()
with active_agent_runtime("agent-a"):
    executor.execute("agent_message_tool", {})
"""

    violations = _contract_violations(Path("bound.py"), source)

    assert violations == ["bound.py:6: ToolExecutor.execute is missing tool_call_id"]


def test_contract_detector_allows_explicit_call_id_and_shared_helper():
    source = """
from core.infrastructure.tool_executor import ToolExecutor

with agent_directory_service.active_agent_runtime("agent-a"):
    ToolExecutor().execute("agent_message_tool", {}, tool_call_id="call-a")

execute_authorized_agent_tool("agent-a", "session-a", "agent_message_tool", {})
"""

    assert _contract_violations(Path("authorized.py"), source) == []


def test_agent_runtime_tests_do_not_bypass_canonical_tool_authorization():
    violations: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        violations.extend(_contract_violations(path, path.read_text(encoding="utf-8-sig")))

    assert violations == [], "\n".join(violations)
