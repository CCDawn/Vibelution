from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORDINARY_CORE_SURFACES = (
    "core/orchestration/context_engine.py",
    "core/web/services/session/proactive.py",
    "core/web/services/session/worker.py",
    "core/web/services/session_service.py",
    "core/web/services/agent_directory/lifecycle.py",
    "core/web/services/agent_directory/ops_residual.py",
    "core/web/services/agent_directory/projections.py",
)
CONCRETE_PLUGIN_MODULE_PREFIXES = (
    "core.agent_plugins.virtual_human_life",
    "core.web.services.virtual_human_life_service",
)
CONCRETE_PLUGIN_MARKERS = (
    "virtual-human-life",
    "virtual_human_life_service",
    "virtualHumanLife",
    "cancel_virtual_human_proactive_turns",
)


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_ordinary_core_depends_only_on_plugin_agnostic_runtime_extensions() -> None:
    violations: list[str] = []
    for relative_path in ORDINARY_CORE_SURFACES:
        path = PROJECT_ROOT / relative_path
        source = path.read_text(encoding="utf-8")
        for module in _imported_modules(path):
            if module.startswith(CONCRETE_PLUGIN_MODULE_PREFIXES):
                violations.append(f"{relative_path}: import {module}")
        for marker in CONCRETE_PLUGIN_MARKERS:
            if marker in source:
                violations.append(f"{relative_path}: marker {marker}")

    assert violations == []
