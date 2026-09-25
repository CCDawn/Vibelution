"""快捷键改键 e2e：默认 chip、录新键覆盖、localStorage 持久、新键唤起面板、冲突抢占。

口径（web/src/routes/ConfigShortcutsPanel.tsx + web/src/shortcuts/*，实测于
2026-09-25 head=5eeb54a40）：
- URL 契约：``?section=`` 是设置分组 id、``?page=`` 是页面 id（ConfigRoute.tsx
  requestedSectionId/requestedPageId）；快捷键页 =
  ``/config?section=workbench-interface&page=workbench-shortcuts``；
- 命令行 ``[data-testid="shortcuts-row-<id>"]``，状态 chip「默认」/「已覆盖」；
  「修改」按钮 ``shortcuts-modify-<id>``；
- 录制：点「修改」→ ``shortcuts-recording-strip`` 出现 → 按新组合键 →
  chip 变「已覆盖」，localStorage ``vibelution.shortcuts.overrides`` 写入 canonical
  绑定串（Windows 上 Ctrl 归一为 ``CmdOrCtrl``，如 ``CmdOrCtrl+Shift+l``）；
- 新键全局生效：任意页按新键 → 命令面板打开（GlobalCommandSurfaces）；
- 冲突：给「会话搜索」录 Ctrl+K（被「打开命令面板」默认 CmdOrCtrl+K 物理占用）→
  danger banner + 「抢占并绑定」按钮。

VDialog 锚点已透传（2026-09-25 修复 668cfa8c1）：面板打开后
``[data-vui="global-command-palette"]`` / ``"global-session-search"`` 锚点在 DOM；
用例沿用 ``[data-testid="vui-command-palette"]``（VCommandPalette 自身 testid，
与锚点二选一皆可）。

保留键黑名单含 CmdOrCtrl+Shift+j（DevTools），录新键选 Control+Shift+L。
每个测试用例独立 browser context（conftest page fixture），localStorage 互不污染。
"""

from __future__ import annotations

import os
from typing import Any

import pytest

pytestmark = [
    pytest.mark.serial,
    pytest.mark.timeout(0),
    # skipif 而非模块级 skip：模块级 skip 会「零收集」，closeout 选择器直跑
    # 本文件时 pytest 退出码 5（NO_TESTS_COLLECTED）判失败；skipif 逐条跳过退出码 0。
    pytest.mark.skipif(
        os.environ.get("VIBELUTION_E2E") != "1",
        reason="e2e 手动车道：设 VIBELUTION_E2E=1 后运行（见 docs/guides/e2e-playwright.md）",
    ),
]

SHORTCUTS_URL_PATH = "/config"
SHORTCUTS_URL_QUERY = "section=workbench-interface&page=workbench-shortcuts"
PANEL = '[data-testid="shortcuts-panel"]'
STORAGE_KEY = "vibelution.shortcuts.overrides"
PALETTE_BODY = '[data-testid="vui-command-palette"]'


def _row(page: Any, command_id: str) -> Any:
    return page.locator(f'[data-testid="shortcuts-row-{command_id}"]').first


def _status_chip_text(page: Any, command_id: str) -> str:
    keys = page.locator(f'[data-testid="shortcuts-keys-{command_id}"]').first
    return (keys.inner_text() or "").strip()


def _open_shortcuts_panel(page: Any, base_url: str) -> None:
    page.goto(f"{base_url}{SHORTCUTS_URL_PATH}?{SHORTCUTS_URL_QUERY}", wait_until="domcontentloaded")
    page.locator(PANEL).first.wait_for(state="visible", timeout=20_000)


def test_default_rows_show_default_chip(page: Any, e2e_instance: Any) -> None:
    """两行默认命令（命令面板/会话搜索）状态 chip 均为「默认」。"""
    _open_shortcuts_panel(page, e2e_instance.base_url)
    for command_id in ("openCommandPalette", "openSessionSearch"):
        row = _row(page, command_id)
        row.wait_for(state="visible", timeout=15_000)
        assert "默认" in _status_chip_text(page, command_id), (
            f"{command_id} 状态 chip 不是「默认」: {_status_chip_text(page, command_id)!r}"
        )
        # 默认绑定 kbd 标签在场（Ctrl+K / Ctrl+P 的 Windows 标签）。
        assert row.locator('[data-testid="shortcuts-binding-kbd"]').count() >= 1, (
            f"{command_id} 没有默认绑定 kbd 标签"
        )


def test_record_new_binding_persists_and_opens_palette(page: Any, e2e_instance: Any) -> None:
    """录 Control+Shift+L → chip「已覆盖」→ localStorage 写入 → 新键任意页唤起命令面板。"""
    _open_shortcuts_panel(page, e2e_instance.base_url)
    row = _row(page, "openCommandPalette")

    page.locator('[data-testid="shortcuts-modify-openCommandPalette"]').first.click()
    page.locator('[data-testid="shortcuts-recording-strip"]').first.wait_for(
        state="visible", timeout=10_000
    )
    page.keyboard.press("Control+Shift+l")
    # 录制条收起且 chip 变「已覆盖」。
    page.locator('[data-testid="shortcuts-recording-strip"]').first.wait_for(
        state="hidden", timeout=10_000
    )
    deadline = page.evaluate("performance.now()") + 5_000
    while "已覆盖" not in _status_chip_text(page, "openCommandPalette"):
        assert page.evaluate("performance.now()") < deadline, (
            f"chip 未变「已覆盖」: {_status_chip_text(page, 'openCommandPalette')!r}"
        )
        page.wait_for_timeout(300)
    assert "已覆盖" in _status_chip_text(page, "openCommandPalette")

    stored = page.evaluate(f"() => localStorage.getItem({STORAGE_KEY!r})") or ""
    assert "CmdOrCtrl+Shift+l" in stored, f"localStorage 未写入新绑定: {stored!r}"

    # 任意页（静态中转页 /reset）按新键 → 命令面板打开。
    # 注：VDialog/ShadcnDialog 不透传 data-vui（已登记产品缺陷），断言用面板自身 testid。
    page.goto(f"{e2e_instance.base_url}/reset", wait_until="domcontentloaded")
    page.wait_for_timeout(800)
    page.keyboard.press("Control+Shift+l")
    palette = page.locator(PALETTE_BODY).first
    palette.wait_for(state="visible", timeout=10_000)
    assert palette.is_visible(), "新键未唤起命令面板"


def test_conflicting_binding_shows_steal_banner(page: Any, e2e_instance: Any) -> None:
    """给「会话搜索」录 Ctrl+K（被「打开命令面板」占用）→ danger banner + 抢占并绑定。"""
    _open_shortcuts_panel(page, e2e_instance.base_url)
    row = _row(page, "openSessionSearch")
    row.wait_for(state="visible", timeout=15_000)

    page.locator('[data-testid="shortcuts-modify-openSessionSearch"]').first.click()
    page.locator('[data-testid="shortcuts-recording-strip"]').first.wait_for(
        state="visible", timeout=10_000
    )
    page.keyboard.press("Control+k")

    banner = page.locator('[data-testid="shortcuts-banner"][data-banner-tone="danger"]').first
    banner.wait_for(state="visible", timeout=10_000)
    banner_text = (banner.inner_text() or "").strip()
    assert "已被「打开命令面板」占用" in banner_text, f"banner 文案不符: {banner_text!r}"
    steal_button = banner.locator('[data-testid="shortcuts-banner-steal"]').first
    assert steal_button.is_visible(), "抢占并绑定按钮不可见"
    assert "抢占并绑定" in (steal_button.inner_text() or ""), (
        f"抢占按钮文案不符: {steal_button.inner_text()!r}"
    )
    # 冲突未落地：目标命令 chip 仍是「默认」，localStorage 无写入。
    assert "默认" in _status_chip_text(page, "openSessionSearch"), "被拒绝的绑定不应生效"
    stored = page.evaluate(f"() => localStorage.getItem({STORAGE_KEY!r})") or ""
    assert "openSessionSearch" not in stored, f"被拒绝的绑定不应写入 localStorage: {stored!r}"
