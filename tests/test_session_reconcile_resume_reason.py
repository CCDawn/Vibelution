"""Contract: a hydrated abandoned turn must stay resumable.

``projection`` reconciliation closes ledger turns that no live worker owns. That
is a process restart from the resume decision's point of view, so the reason it
stamps has to stay inside ``startup_recovery._RESTART_INTERRUPT_REASONS``.

Historically this call site passed ``detail_loaded_after_restart`` — the trigger
that noticed the entry, not the cause — which silently fell outside the
whitelist and made every restart resume zero turns.
"""

from __future__ import annotations

import ast
from pathlib import Path

from core.web.services.session.startup_recovery import _RESTART_INTERRUPT_REASONS

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PROJECTION = _PROJECT_ROOT / "core/web/services/session/projection.py"
_TURN_DIAGNOSTICS = _PROJECT_ROOT / "core/web/services/session/turn_diagnostics.py"

_RECONCILE_CALL = "_reconcile_stale_session_ledger"


def _reconcile_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "attr", None) or getattr(func, "id", None)
        if name == _RECONCILE_CALL:
            calls.append(node)
    return calls


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def test_hydration_reconcile_reason_is_resumable() -> None:
    calls = _reconcile_calls(_PROJECTION)
    assert calls, "projection no longer reconciles stale ledger turns"

    for call in calls:
        reason_node = _keyword(call, "reason")
        # Omitted reason falls back to the resumable default in the callee.
        if reason_node is None:
            continue
        assert isinstance(reason_node, ast.Constant), (
            "reconcile reason must stay a literal so the resume whitelist stays auditable"
        )
        assert reason_node.value in _RESTART_INTERRUPT_REASONS, (
            f"hydration reconcile stamps {reason_node.value!r}, which is outside "
            f"_RESTART_INTERRUPT_REASONS={sorted(_RESTART_INTERRUPT_REASONS)}; "
            "startup recovery would skip the turn"
        )


def test_hydration_records_its_trigger_separately() -> None:
    calls = _reconcile_calls(_PROJECTION)
    assert calls, "projection no longer reconciles stale ledger turns"

    triggers = [
        node.value
        for call in calls
        if isinstance(node := _keyword(call, "trigger"), ast.Constant)
    ]
    assert "detail_loaded_after_restart" in triggers, (
        "the hydration trigger must be preserved as diagnostics even though it is "
        "no longer the interruption cause"
    )


def test_reconcile_accepts_a_trigger_keyword() -> None:
    tree = ast.parse(_TURN_DIAGNOSTICS.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == _RECONCILE_CALL:
            keyword_args = {arg.arg for arg in node.args.kwonlyargs}
            assert "reason" in keyword_args
            assert "trigger" in keyword_args
            return
    raise AssertionError(f"{_RECONCILE_CALL} not found in turn_diagnostics.py")
