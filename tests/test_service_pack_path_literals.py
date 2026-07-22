"""Guard against pack-extract path literal corruption.

AST extract rewrites have previously dropped the dot in filenames
(e.g. ``agent_turn_results.jsonl`` → ``agent_turn_resultjsonl``,
``stage_session_tasks.json`` → ``stage_session_taskjson``). Those bugs
are silent at import time and break runtime log/store routing.

This test fails the suite if any string literal under the service packs
looks like a filename with a glued extension.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = [
    REPO_ROOT / "core" / "web" / "services",
]

# Extension names that must not appear glued to a path-like leaf without a dot.
_GLUED_EXT = re.compile(
    r"(?P<leaf>[A-Za-z0-9_./\\*-]*[A-Za-z0-9_-])"
    r"(?P<ext>jsonl|json)$"
)

# Kind tokens / identifiers that legitimately end with _json / _jsonl (not paths).
_ALLOW_FULLMATCH = re.compile(
    r"^(?:"
    r"[a-z][a-z0-9_]*_(?:json|jsonl)"  # prompt_jsonl, result_json, …
    r"|claude_code_project_jsonl"
    r"|claude_project_jsonl"
    r"|invalid_json"
    r"|resultJson"
    r"|--json"
    r"|project-memory-json"  # memory matrix item id, not a filesystem path
    r"|project-html"
    r")$"
)


def _is_corrupt_path_literal(value: str) -> bool:
    if not value or len(value) > 240:
        return False
    if ".jsonl" in value or value.endswith(".json"):
        return False
    leaf = value.replace("\\", "/").split("/")[-1]
    if not leaf or _ALLOW_FULLMATCH.match(leaf):
        return False
    # Pure snake kinds: foo_json / foo_jsonl
    if re.fullmatch(r"[a-z][a-z0-9_]*", leaf) and (
        leaf.endswith("_json") or leaf.endswith("_jsonl")
    ):
        return False
    match = _GLUED_EXT.search(leaf)
    if not match:
        return False
    # Glued: alnum/underscore immediately before extension name, no leading dot on leaf.
    if leaf.endswith("." + match.group("ext")):
        return False
    # Require path-ish or hyphen/underscore filename stems (not prose).
    if not re.search(r"[/\\_*\-]", value) and not re.search(r"[a-z0-9](?:jsonl|json)$", leaf):
        return False
    # stage_session_taskjson / agent_turn_resultjsonl style
    if re.search(r"[A-Za-z0-9_-](?:jsonl|json)$", leaf) and not leaf.endswith(
        ("_json", "_jsonl")
    ):
        return True
    return False


def _iter_string_literals(path: Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [(exc.lineno or 0, f"<syntax error: {exc}>")]
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append((getattr(node, "lineno", 0) or 0, node.value))
    return found


def _py_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.is_dir():
            continue
        files.extend(sorted(root.rglob("*.py")))
    return files


@pytest.mark.parametrize("path", _py_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_service_pack_path_literals_not_mangled(path: Path) -> None:
    corrupt: list[str] = []
    for lineno, value in _iter_string_literals(path):
        if value.startswith("<syntax error"):
            pytest.fail(f"{path}:{lineno}: {value}")
        if _is_corrupt_path_literal(value):
            corrupt.append(f"{lineno}: {value!r}")
    assert not corrupt, (
        "Mangled path-like string literal(s) (missing '.' before json/jsonl). "
        "Restore the correct filename (e.g. stage_session_tasks.json, "
        f"agent_turn_results.jsonl).\n{path}:\n  " + "\n  ".join(corrupt)
    )


def test_known_correct_filenames_still_present() -> None:
    """Smoke anchors: previously-broken paths must remain correct after extract."""
    stage_reconcile = (
        REPO_ROOT
        / "core"
        / "web"
        / "services"
        / "team_workflow"
        / "source_collection"
        / "stage_reconcile.py"
    ).read_text(encoding="utf-8")
    assert "stage_session_tasks.json" in stage_reconcile
    assert "agent_turn_results.jsonl" in stage_reconcile
    assert "stage_session_taskjson" not in stage_reconcile
    assert "agent_turn_resultjsonl" not in stage_reconcile

    knowledge_kernel = (
        REPO_ROOT / "core" / "web" / "services" / "team_workflow" / "knowledge_kernel.py"
    ).read_text(encoding="utf-8")
    assert "transfer_records.jsonl" in knowledge_kernel
    assert "transfer_recordjsonl" not in knowledge_kernel
