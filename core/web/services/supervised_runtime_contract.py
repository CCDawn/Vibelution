"""Runtime-only tool contract for supervised evolution roles."""

from __future__ import annotations

from typing import Any


SUPERVISED_ROLE_CONTRACT_VERSION = 2

SUPERVISED_ROLE_RUNTIME_TOOLS: dict[str, tuple[str, ...]] = {
    "baseline": (
        "open_evolution_transaction_tool",
        "close_evolution_transaction_tool",
        "grep_search_tool",
        "code_symbol_tool",
        "cli_tool",
        "python_lint_tool",
    ),
    "candidate": (
        "open_evolution_transaction_tool",
        "close_evolution_transaction_tool",
        "grep_search_tool",
        "code_symbol_tool",
        "cli_tool",
        "python_lint_tool",
    ),
    "reviewer": (),
    "auditor": (),
    "judge": (),
}


def supervised_role_runtime_tools(role: str) -> list[str]:
    return list(SUPERVISED_ROLE_RUNTIME_TOOLS.get(str(role or "").strip(), ()))


def supervised_role_contract(role: str) -> dict[str, Any]:
    normalized_role = str(role or "").strip()
    runtime_tools = supervised_role_runtime_tools(normalized_role)
    return {
        "version": SUPERVISED_ROLE_CONTRACT_VERSION,
        "role": normalized_role,
        "runtimeToolSource": "supervised_conversation_harness",
        "persistentToolPolicy": "system_no_tools",
        "effectiveRuntimeTools": runtime_tools,
        "notes": (
            "Agent Center ToolPolicy remains no-tools for fixed system roles; "
            "supervised runs inject this role-specific tool package through the hidden conversation harness."
            if runtime_tools
            else "This role is evidence-only in the current supervised pipeline and should not invoke tools."
        ),
    }
