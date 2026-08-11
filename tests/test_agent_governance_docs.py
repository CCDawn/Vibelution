from __future__ import annotations

import re
from pathlib import Path

from core.prompt_manager.core_prompt_sources import CORE_PROMPT_NAMES, CORE_PROMPT_SPECS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
FIXED_WINDOWS_USER_RE = re.compile(r"C:\\Users\\(?:\d+|Administrator)\\", re.IGNORECASE)


def _assert_local_links_resolve(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    for raw_target in MARKDOWN_LINK_RE.findall(content):
        target = raw_target.strip().split("#", 1)[0].strip()
        if not target or "://" in target or target.startswith("#"):
            continue
        if ".docs/project-memory/" in target.replace("\\", "/"):
            continue
        resolved = (path.parent / target).resolve()
        assert resolved.exists(), f"{path.relative_to(PROJECT_ROOT)} -> {raw_target}"


def test_three_core_prompt_sources_are_the_only_required_base():
    assert CORE_PROMPT_NAMES == ("COMMON", "SOUL", "AGENTS")
    assert [spec.relative_path for spec in CORE_PROMPT_SPECS] == [
        "core/core_prompt/COMMON.md",
        "core/core_prompt/SOUL.md",
        "AGENTS.md",
    ]


def test_global_governance_uses_root_agents_and_docs_standards():
    assert (PROJECT_ROOT / "AGENTS.md").is_file()
    assert (PROJECT_ROOT / "docs" / "standards" / "README.md").is_file()
    assert (PROJECT_ROOT / "docs" / "standards" / "development-standard.md").is_file()
    assert not (PROJECT_ROOT / "DEVELOPMENT_STANDARD.md").exists()
    assert not (PROJECT_ROOT / "CONTEXT.md").exists()
    assert not (PROJECT_ROOT / "core" / "core_prompt" / "SPEC.md").exists()


def test_main_is_reserved_for_fast_forward_integration() -> None:
    agents = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    standard = (PROJECT_ROOT / "docs" / "standards" / "development-standard.md").read_text(
        encoding="utf-8"
    )
    collaboration = (PROJECT_ROOT / "docs" / "agents" / "worktree-collaboration.md").read_text(
        encoding="utf-8"
    )
    loop = (PROJECT_ROOT / "docs" / "guides" / "loop.md").read_text(encoding="utf-8")

    assert "禁止在根 `main` 直接写入任何变更" in agents
    assert "Direct writes and commits on `main` are forbidden" in standard
    assert "Direct development writes and commits on `main` are forbidden" in collaboration
    assert "必须使用任务 worktree 与 `codex/<task-slug>` 分支" in loop
    assert "FAST_PATCH may stay in the current workspace" not in standard


def test_windows_no_console_red_line_is_normative():
    """Visible console popups are permanently forbidden for product runtime."""

    agents = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    standard = (PROJECT_ROOT / "docs" / "standards" / "development-standard.md").read_text(
        encoding="utf-8"
    )
    standards_index = (PROJECT_ROOT / "docs" / "standards" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "禁止任何可见控制台弹窗" in agents
    assert "CREATE_NO_WINDOW" in agents
    assert "无控制台弹窗" in agents
    assert "### 8.0 Windows No-Console Absolute Red Line" in standard
    assert "merge blocker" in standard
    assert "taskkill.exe" in standard
    assert "禁止 cmd/控制台弹窗" in standards_index
    rebirth = (PROJECT_ROOT / "tools" / "rebirth_tools.py").read_text(encoding="utf-8")
    assert "CREATE_NO_WINDOW" in rebirth
    restarter = (
        PROJECT_ROOT / "core" / "restarter_manager" / "restarter.py"
    ).read_text(encoding="utf-8")
    assert "no_window_subprocess_kwargs" in restarter
    assert "CREATE_NEW_PROCESS_GROUP" in restarter


def test_governance_entry_links_resolve():
    _assert_local_links_resolve(PROJECT_ROOT / "AGENTS.md")
    _assert_local_links_resolve(PROJECT_ROOT / "docs" / "README.md")
    _assert_local_links_resolve(PROJECT_ROOT / "docs" / "standards" / "README.md")


def test_current_normative_docs_do_not_pin_a_windows_username():
    normative_paths = [
        PROJECT_ROOT / "AGENTS.md",
        PROJECT_ROOT / "docs" / "README.md",
        PROJECT_ROOT / "docs" / "standards" / "README.md",
        PROJECT_ROOT / "docs" / "standards" / "development-standard.md",
        PROJECT_ROOT / "docs" / "agents" / "domain.md",
        PROJECT_ROOT / "docs" / "agents" / "worktree-collaboration.md",
        PROJECT_ROOT / "tests" / "README.md",
    ]
    for path in normative_paths:
        content = path.read_text(encoding="utf-8")
        assert FIXED_WINDOWS_USER_RE.search(content) is None, path.relative_to(PROJECT_ROOT)
