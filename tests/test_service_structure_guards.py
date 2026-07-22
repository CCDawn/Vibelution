"""Soft structure guards for pack-split web services.

Complements ``test_service_pack_path_literals`` and per-domain structure pack
re-export tests. These checks are intentionally cheap and high-signal:

1. Critical helpers must have exactly one ``def`` across a pack tree
   (prevents silent duplicate implementations after extract).
2. Public facades must stay re-export / glue thin (budget on top-level
   function bodies), so new business logic lands in packs.
3. Anchored path filenames that were previously mangled stay correct.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICES = REPO_ROOT / "core" / "web" / "services"


@dataclass(frozen=True)
class SingleImplSymbol:
    name: str
    search_roots: tuple[Path, ...]
    expected_module: str


# High-churn / previously-split symbols: exactly one FunctionDef in the tree.
SINGLE_IMPL_SYMBOLS: tuple[SingleImplSymbol, ...] = (
    SingleImplSymbol(
        name="_sync_source_collection_stage_round_after_search",
        search_roots=(
            SERVICES / "team_workflow_orchestration_service.py",
            SERVICES / "team_workflow",
        ),
        expected_module="core.web.services.team_workflow.source_collection.search_execution",
    ),
    SingleImplSymbol(
        name="_source_collection_stage_session_task_store_path",
        search_roots=(
            SERVICES / "team_workflow_orchestration_service.py",
            SERVICES / "team_workflow",
        ),
        expected_module="core.web.services.team_workflow.source_collection.stage_reconcile",
    ),
    SingleImplSymbol(
        name="_transfer_records_path",
        search_roots=(
            SERVICES / "team_workflow_orchestration_service.py",
            SERVICES / "team_workflow",
        ),
        expected_module="core.web.services.team_workflow.knowledge_kernel",
    ),
    SingleImplSymbol(
        name="submit_session_message",
        search_roots=(
            SERVICES / "session_service.py",
            SERVICES / "session",
        ),
        expected_module="core.web.services.session.submit",
    ),
    SingleImplSymbol(
        name="get_session_detail",
        search_roots=(
            SERVICES / "session_service.py",
            SERVICES / "session",
        ),
        expected_module="core.web.services.session.projection",
    ),
    SingleImplSymbol(
        name="stream_session_events",
        search_roots=(
            SERVICES / "session_service.py",
            SERVICES / "session",
        ),
        expected_module="core.web.services.session.publish",
    ),
    SingleImplSymbol(
        name="record_runtime_scene_event",
        search_roots=(
            SERVICES / "runtime_scene_service.py",
            SERVICES / "runtime_scene",
        ),
        expected_module="core.web.services.runtime_scene.record",
    ),
)


# Top-level FunctionDef budget on facades (wrappers / transactions only).
# Soft awareness: raise only if a facade grows real business bodies again.
FACADE_FUNCTION_BUDGETS: dict[str, int] = {
    "session_service.py": 12,
    "team_workflow_orchestration_service.py": 8,
    "agent_directory_service.py": 12,
    "runtime_scene_service.py": 8,
}


def _iter_py_files(root: Path) -> list[Path]:
    if root.is_file() and root.suffix == ".py":
        return [root]
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.py") if p.name != "__init__.py" or True)


def _function_defs(path: Path) -> list[tuple[str, int]]:
    text = path.read_text(encoding="utf-8")
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    tree = ast.parse(text, filename=str(path))
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append((node.name, getattr(node, "lineno", 0) or 0))
    return found


def _top_level_function_defs(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    tree = ast.parse(text, filename=str(path))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(node.name)
    return names


def _module_for_path(path: Path) -> str:
    rel = path.resolve().relative_to(REPO_ROOT.resolve())
    parts = list(rel.with_suffix("").parts)
    return ".".join(parts)


@pytest.mark.parametrize(
    "symbol",
    SINGLE_IMPL_SYMBOLS,
    ids=lambda s: s.name,
)
def test_critical_symbol_has_single_implementation(symbol: SingleImplSymbol) -> None:
    hits: list[tuple[Path, int]] = []
    for root in symbol.search_roots:
        for path in _iter_py_files(root):
            if path.name == "__init__.py":
                continue
            for name, lineno in _function_defs(path):
                if name == symbol.name:
                    hits.append((path, lineno))

    assert len(hits) == 1, (
        f"Expected exactly one def {symbol.name!r} under "
        f"{[str(r.relative_to(REPO_ROOT)) for r in symbol.search_roots]}, "
        f"found {len(hits)}:\n"
        + "\n".join(f"  {p.relative_to(REPO_ROOT)}:{ln}" for p, ln in hits)
    )
    only_path, _ = hits[0]
    actual_module = _module_for_path(only_path)
    assert actual_module == symbol.expected_module, (
        f"{symbol.name} lives in {actual_module}, expected {symbol.expected_module}"
    )


@pytest.mark.parametrize("facade_name,budget", sorted(FACADE_FUNCTION_BUDGETS.items()))
def test_public_facade_stays_thin(facade_name: str, budget: int) -> None:
    path = SERVICES / facade_name
    assert path.is_file(), f"missing facade {facade_name}"
    names = _top_level_function_defs(path)
    assert len(names) <= budget, (
        f"{facade_name} has {len(names)} top-level function bodies "
        f"(budget {budget}). Prefer pack modules + re-export. Bodies: {names}"
    )


def test_extract_path_anchors_still_correct() -> None:
    """Previously mangled filenames must remain dotted and plural where expected."""
    checks = [
        (
            SERVICES
            / "team_workflow"
            / "source_collection"
            / "stage_reconcile.py",
            (
                "stage_session_tasks.json",
                "agent_turn_results.jsonl",
            ),
            (
                "stage_session_taskjson",
                "agent_turn_resultjsonl",
            ),
        ),
        (
            SERVICES / "team_workflow" / "knowledge_kernel.py",
            ("transfer_records.jsonl",),
            ("transfer_recordjsonl",),
        ),
        (
            SERVICES / "session" / "agent_runtime.py",
            (
                "prompt-snapshots.jsonl",
                "agent-bindings.jsonl",
                "turns.jsonl",
            ),
            (
                "prompt-snapshotjsonl",
                "agent-bindingjsonl",
                "turnjsonl",
            ),
        ),
        (
            SERVICES / "session" / "projection.py",
            ("agent_inbox_messages.jsonl",),
            ("agent_inbox_messagejsonl",),
        ),
        (
            SERVICES / "session" / "timeline.py",
            ("tool_calls.jsonl", "turns.jsonl"),
            ("tool_calljsonl", "turnjsonl"),
        ),
        (
            SERVICES / "session" / "turn_diagnostics.py",
            ("errors.jsonl",),
            ("errorjsonl",),
        ),
    ]
    for path, required, forbidden in checks:
        text = path.read_text(encoding="utf-8")
        for token in required:
            assert token in text, f"{path.relative_to(REPO_ROOT)} missing {token!r}"
        for token in forbidden:
            assert token not in text, f"{path.relative_to(REPO_ROOT)} still has mangled {token!r}"


def test_pack_readmes_exist_for_split_domains() -> None:
    required = [
        SERVICES / "session" / "README.md",
        SERVICES / "team_workflow" / "README.md",
        SERVICES / "agent_directory" / "README.md",
        SERVICES / "runtime_scene" / "README.md",
    ]
    missing = [str(p.relative_to(REPO_ROOT)) for p in required if not p.is_file()]
    assert not missing, f"missing pack ownership READMEs: {missing}"
