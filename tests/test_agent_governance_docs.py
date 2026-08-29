from __future__ import annotations

import re
from pathlib import Path

from core.prompt_manager.assembly_contract import estimate_prompt_tokens
from core.prompt_manager.core_prompt_sources import (
    CORE_PROMPT_NAMES,
    CORE_PROMPT_SPECS,
    strip_prompt_front_matter,
)


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


def test_stable_core_keeps_prompt_budget_headroom() -> None:
    content = "\n\n".join(
        strip_prompt_front_matter((PROJECT_ROOT / spec.relative_path).read_text(encoding="utf-8"))
        for spec in CORE_PROMPT_SPECS
    )

    assert estimate_prompt_tokens(content) <= 5400


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


def test_proactive_self_review_and_local_main_merge_is_required() -> None:
    agents = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    standard = (PROJECT_ROOT / "docs" / "standards" / "development-standard.md").read_text(
        encoding="utf-8"
    )
    collaboration = (PROJECT_ROOT / "docs" / "agents" / "worktree-collaboration.md").read_text(
        encoding="utf-8"
    )
    loop = (PROJECT_ROOT / "docs" / "guides" / "loop.md").read_text(encoding="utf-8")
    playbook = (PROJECT_ROOT / "docs" / "guides" / "playbook.md").read_text(encoding="utf-8")

    assert "主动自审当前任务 diff" in agents
    assert "不得把「等用户再说审查/合入」当作完成态" in agents
    assert "未主动自审并合入本地 `main`" in agents
    assert "waiting for the user to request review or merge is not done" in standard
    assert "without waiting for the user to request review" in collaboration
    assert "不得等用户再下令审查/合入" in loop
    assert "合入门已通过却未主动合入" in loop
    assert "不得等用户再下令" in playbook


def test_validation_and_managed_closeout_are_single_pass_by_default() -> None:
    agents = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    loop = (PROJECT_ROOT / "docs" / "guides" / "loop.md").read_text(encoding="utf-8")
    testing = (PROJECT_ROOT / "tests" / "README.md").read_text(encoding="utf-8")

    assert "同一 HEAD" in agents
    assert "不得重复执行" in agents
    assert "scripts/task_closeout.py" in loop
    assert "--manifest" in loop
    assert "next_action=retry_with_manifest" in testing
    assert "不得重测" in testing


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


def test_product_runtime_sources_never_invoke_taskkill():
    """AGENTS.md §2 red line: product runtime source must not shell out to taskkill.exe."""

    taskkill_command = re.compile(r"[\"']taskkill(?:\.exe)?[\"']")
    scan_roots = (
        PROJECT_ROOT / "tools",
        PROJECT_ROOT / "core",
        PROJECT_ROOT / "scripts",
    )
    violations: list[str] = []
    for root in scan_roots:
        for py_file in sorted(root.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            text = py_file.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if taskkill_command.search(line):
                    violations.append(
                        f"{py_file.relative_to(PROJECT_ROOT)}:{lineno}: {stripped}"
                    )
    assert not violations, (
        "product runtime sources must terminate/probe processes without "
        f"taskkill:\n" + "\n".join(violations)
    )


def test_research_before_write_scales_external_work_by_risk():
    """Local reuse stays mandatory while located small fixes can skip external scanning."""

    agents = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    standard = (PROJECT_ROOT / "docs" / "standards" / "development-standard.md").read_text(
        encoding="utf-8"
    )
    standards_index = (PROJECT_ROOT / "docs" / "standards" / "README.md").read_text(
        encoding="utf-8"
    )
    loop = (PROJECT_ROOT / "docs" / "guides" / "loop.md").read_text(encoding="utf-8")
    playbook = (PROJECT_ROOT / "docs" / "guides" / "playbook.md").read_text(encoding="utf-8")
    route = (PROJECT_ROOT / "docs" / "guides" / "route.md").read_text(encoding="utf-8")

    assert "本地能复用 ≠ 本地就是好方案" in agents
    assert "改造后再复用" in agents
    assert "评估排序" in agents
    assert "最符合本项目、最值得借鉴的部分" in agents
    assert "record --mode LOCAL_ONLY" in agents
    assert "已定位小修/机械修改不得被强制仓外扫描拖慢" in agents
    assert "### 2.2 Local Reuse And Risk-Scaled Mature-Scheme Research" in standard
    assert "adapt then reuse" in standard
    assert "Rank and extract" in standard
    assert "§2.2" in standards_index
    assert "已定位小修不付固定扫描成本" in loop
    assert "仓外对照与排序" in loop
    assert "R10" in playbook
    assert "最值得借鉴的部分" in playbook
    assert "不评估本地复用" in route


def test_companion_chat_isolation_is_a_normative_red_line() -> None:
    agents = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    standard = (PROJECT_ROOT / "docs" / "standards" / "development-standard.md").read_text(
        encoding="utf-8"
    )

    assert "Companion / 虚拟人会话隔离红线" in agents
    assert "不得因虚拟人需求修改普通 Agent" in agents
    assert "Companion mailbox 只负责到达顺序，不得成为第二套 transcript" in agents
    assert "#### Companion / Virtual-Human Chat Isolation" in standard
    assert "not a variant of the ordinary chat runtime" in standard
    assert "The task diff is empty for ordinary chat runtime cores" in standard
    assert "tests/test_session_submit.py" in standard
    assert "CompanionChatReuse.contract.test.ts" in standard


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
