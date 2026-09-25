"""AppShell 全路由只读冒烟：真实分支实例 + headless chromium。

口径（正式文档见 docs/guides/e2e-playwright.md；锚点实测于 2026-09-25，
分支实例 head=23ecd0c3d9d3，headless chromium 1440x900 zh-CN）：
- 每条路由只 ``goto``，**严禁点击任何按钮**（/logs 清理、/launcher 重启、
  /agents 归档、/memory/cleanup 清理、/git commit/discard 都是危险区）；
- 主锚点：页面根 ``[data-vui-domain-recipe="<预期值>"]`` 可见（29 条路由中
  27 条带该属性，见逐路由表）；``/usage``、``/reset`` 无该属性，进豁免表；
- 次锚点：``header[data-vui="route-header"] h1`` 可见——只对实测可见的路由
  断言。chat/evolution 工作台布局没有 route-header h1；agents 家族与 /teams
  的 route-header 存在于 DOM 但 pane 隐藏（空态布局事实），均登记豁免；
- 不出现 ``state-surface[data-tone="error"]``；
- 守卫路由（WorkbenchDomainRoute/WorkbenchModeRoute）先 GET
  ``/api/config/public``，被禁用时按 home 解析规则断言重定向后的 URL；
- URL 断言用前缀匹配：``/chat`` 会自动补 ``?session=<id>``（产品自动选中
  最近会话），精确相等会误报。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import pytest

from tests.e2e.helpers.page_anchors import (
    ROUTE_HEADER_H1,
    STATE_SURFACE_ERROR,
    domain_recipe_selector,
)

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


# ---------------------------------------------------------------------------
# 路由表（与 web/src/app/router.tsx AppShell children 对齐）
# recipe: 预期的 data-vui-domain-recipe 值；None = 实测无该属性（豁免）。
# assert_h1: True = 断言 route-header h1 可见；False = 实测不可见/不存在（豁免）。
# guard: ("domain", name) → WorkbenchDomainRoute；(mode, name) → WorkbenchModeRoute
# ---------------------------------------------------------------------------

_H1_NONE_EVOLUTION = "chat/evolution 工作台布局没有 route-header h1（实测）"
_H1_HIDDEN_PANE = "route-header 存在于 DOM 但 pane 隐藏（空态布局事实，实测）"
_NO_RECIPE = "页面根没有 data-vui-domain-recipe（实测）"


@dataclass(frozen=True)
class RouteSpec:
    path: str
    recipe: str | None
    assert_h1: bool
    guard: tuple[str, str] | None = None
    note: str = ""


ROUTES: tuple[RouteSpec, ...] = (
    RouteSpec("/chat", "chat-session-workbench", False, ("domain", "chat"), _H1_NONE_EVOLUTION),
    RouteSpec("/companions", "virtual-human-companion-lobby", False, ("domain", "chat"), _H1_NONE_EVOLUTION),
    RouteSpec("/supervised-evolution", "evolution-multi-rail", False, ("mode", "supervised_evolution"), _H1_NONE_EVOLUTION),
    RouteSpec("/supervised-evolution/runs", "evolution-multi-rail", False, ("mode", "supervised_evolution"), _H1_NONE_EVOLUTION),
    RouteSpec("/supervised-evolution/library", "evolution-multi-rail", False, ("mode", "supervised_evolution"), _H1_NONE_EVOLUTION),
    RouteSpec("/supervised-evolution/review", "supervised-review-workbench", True, ("mode", "supervised_evolution")),
    RouteSpec("/self-evolution", "evolution-multi-rail", False, ("mode", "self_evolution"), _H1_NONE_EVOLUTION),
    RouteSpec("/agents", "agents-management-workbench", False, None, _H1_HIDDEN_PANE),
    RouteSpec("/agents/prompts", "prompt-templates-workbench", False, None, _H1_HIDDEN_PANE),
    RouteSpec("/agents/tools", "tools-workbench", False, None, _H1_HIDDEN_PANE),
    RouteSpec("/agents/skills", "skills-workbench", False, None, _H1_HIDDEN_PANE),
    RouteSpec("/memory", "memory-knowledge-workbench", True),
    RouteSpec("/memory/team", "memory-knowledge-workbench", True),
    RouteSpec("/memory/library", "memory-knowledge-workbench", True),
    RouteSpec("/memory/agents", "memory-knowledge-workbench", True),
    RouteSpec("/memory/knowledge", "memory-knowledge-workbench", True),
    RouteSpec("/memory/manage", "memory-knowledge-workbench", True),
    RouteSpec("/memory/sources", "memory-knowledge-workbench", True),
    RouteSpec("/memory/effective", "memory-knowledge-workbench", True),
    RouteSpec("/memory/cleanup", "memory-knowledge-workbench", True),
    RouteSpec("/memory/graph", "memory-knowledge-workbench", True),
    RouteSpec("/teams", "teams-organization-workbench", False, None, _H1_HIDDEN_PANE),
    RouteSpec("/kernel", "kernel-task-center-workbench", True),
    RouteSpec("/git", "git-workbench", True),
    RouteSpec("/usage", None, True, None, _NO_RECIPE),
    RouteSpec("/logs", "logs-workbench", True),
    RouteSpec("/pet", "pet-companion", True),
    RouteSpec("/reset", None, True, None, _NO_RECIPE),
    RouteSpec("/config", "config-settings", True),
)


def _flag(mapping: dict[str, Any], key: str) -> bool:
    value = mapping.get(key)
    return value if isinstance(value, bool) else True


def _domain_enabled(config: dict[str, Any], domain: str) -> bool:
    return _flag(config.get("domainAvailability") or {}, domain)


def _mode_enabled(config: dict[str, Any], mode: str) -> bool:
    if not _domain_enabled(config, "evolution"):
        return False
    return _flag(config.get("modeAvailability") or {}, mode)


def _evolution_home(config: dict[str, Any]) -> str:
    availability = config.get("modeAvailability") or {}
    self_ok = _flag(availability, "self_evolution")
    supervised_ok = _flag(availability, "supervised_evolution")
    default_mode = config.get("defaultMode")
    if default_mode == "self_evolution" and self_ok:
        return "/self-evolution"
    if default_mode == "supervised_evolution" and supervised_ok:
        return "/supervised-evolution"
    if supervised_ok:
        return "/supervised-evolution"
    if self_ok:
        return "/self-evolution"
    return "/config"


def home_path(config: dict[str, Any]) -> str:
    route = config.get("defaultRoute") or "/chat"
    return _evolution_home(config) if route == "/evolution" else route


def guard_enabled(config: dict[str, Any], guard: tuple[str, str] | None) -> bool:
    if guard is None:
        return True
    kind, name = guard
    if kind == "domain":
        return _domain_enabled(config, name)
    return _mode_enabled(config, name)


def fetch_public_config(e2e_instance: Any) -> dict[str, Any]:
    """守卫判定输入：GET /api/config/public（冒烟本身不做任何写操作）。"""
    return e2e_instance.api_get("/api/config/public")


def _url_on_path(page: Any, base_url: str, path: str) -> bool:
    """URL 是否已在目标路径（允许 query，如 /chat 自动补 ?session=）。"""
    return str(page.url).startswith(f"{base_url}{path}")


def assert_route_surface(page: Any, spec: RouteSpec) -> str:
    """就绪后的页面断言：domain-recipe（豁免除外）、h1（按路由表）、无 error 状态面。"""
    title = ""
    if spec.recipe is None:
        print(f"[smoke] {spec.path}: {spec.note}")
    else:
        recipe = page.locator(domain_recipe_selector(spec.recipe)).first
        # 注意：Locator.wait_for() 成功时返回 None，不能作为断言值；
        # 超时会直接抛 TimeoutError，走到这里即已可见。
        recipe.wait_for(state="visible", timeout=10_000)
        assert recipe.is_visible(), (
            f"{spec.path}: 预期 [data-vui-domain-recipe=\"{spec.recipe}\"] 可见（url={page.url}）"
        )

    if spec.assert_h1:
        header = page.locator(ROUTE_HEADER_H1)
        header.first.wait_for(state="visible", timeout=15_000)
        title = header.first.inner_text().strip()
        assert title, f"{spec.path}: route-header h1 可见但文本为空（url={page.url}）"
    elif not spec.note:
        raise AssertionError(f"{spec.path}: 路由表不一致——h1 豁免必须带理由（note）")

    errors = page.locator(STATE_SURFACE_ERROR)
    assert errors.count() == 0, (
        f"{spec.path}: 出现 state-surface[data-tone=\"error\"]（url={page.url}, "
        f"count={errors.count()}）"
    )
    return title or (spec.recipe or "")


def test_home_redirect(page: Any, e2e_instance: Any) -> None:
    """/ 由 HomeRedirect 跳 defaultRoute（被禁用时按 mode 可用性回退）。"""
    config = fetch_public_config(e2e_instance)
    expected = home_path(config)
    page.goto(f"{e2e_instance.base_url}/", wait_until="domcontentloaded")
    page.wait_for_url(lambda url: _url_on_path(page, e2e_instance.base_url, expected), timeout=20_000)
    spec = next(
        (item for item in ROUTES if item.path == expected),
        RouteSpec(expected, None, False, None, "home redirect 兜底（非标准 defaultRoute，只断言无 error）"),
    )
    assert_route_surface(page, spec)


@pytest.mark.parametrize("spec", ROUTES, ids=[spec.path for spec in ROUTES])
def test_route_smoke(page: Any, e2e_instance: Any, spec: RouteSpec) -> None:
    config = fetch_public_config(e2e_instance)
    expected_path = spec.path if guard_enabled(config, spec.guard) else home_path(config)

    page.goto(f"{e2e_instance.base_url}{spec.path}", wait_until="domcontentloaded")
    page.wait_for_url(lambda url: _url_on_path(page, e2e_instance.base_url, expected_path), timeout=20_000)
    title = assert_route_surface(page, spec)
    assert _url_on_path(page, e2e_instance.base_url, expected_path), (
        f"{spec.path}: 守卫后 URL 不符（期望 {expected_path}，实际 {page.url}）"
    )
    # 显式产出每条路由的页头，便于报告归档。
    print(f"[smoke] {spec.path} -> {expected_path} :: h1={title!r}")
