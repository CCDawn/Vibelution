"""页面锚点选择器与「加载完成」判定（折自 tests/e2e/_recon 侦察结论）。

约定：无统一 data-testid，定位靠 ``data-vui`` + 原生 ARIA：
- 页头：``header[data-vui="route-header"]`` 内唯一 ``h1``（冒烟首选断言）；
- 页面根：多数路由带 ``data-vui-domain-recipe``；
- 状态面：``section[data-vui="state-surface"][data-tone=...]``，
  等待加载完成 = 等 tone 离开 loading 或页头出现。
"""

from __future__ import annotations

from typing import Any

ROUTE_HEADER_H1 = 'header[data-vui="route-header"] h1'
STATE_SURFACE = 'section[data-vui="state-surface"]'
STATE_SURFACE_ERROR = f'{STATE_SURFACE}[data-tone="error"]'
STATE_SURFACE_NOT_LOADING = f'{STATE_SURFACE}:not([data-tone="loading"])'
DOMAIN_RECIPE_ROOT = "[data-vui-domain-recipe]"
PRIMARY_NAV = 'nav[data-shell-group="navigation"][aria-label="主导航"]'


def domain_recipe_selector(recipe: str) -> str:
    """按预期值定位页面根 recipe 锚点（逐路由最强锚点）。"""
    return f'[data-vui-domain-recipe="{recipe}"]'


def primary_nav_link(path: str) -> str:
    """主导航项定位器（react-router Link 渲染成真 <a href>）。"""
    return f'a[data-vui="route-link-button"][data-chrome="shell-nav"][href="{path}"]'


def wait_route_ready(page: Any, *, timeout_ms: int = 30_000) -> str:
    """等待当前路由加载完成（recipe 锚点/h1 可见或状态面离开 loading），返回就绪信号文本。

    只等待、不点击；超时抛 AssertionError 并附当时 URL 供证据。
    实测背景：chat/evolution 工作台没有 route-header h1，agents 家族与 /teams
    的 h1 在空态下隐藏，因此就绪信号把 ``[data-vui-domain-recipe]`` 纳入。
    """
    deadline_ready = page.locator(
        f"{DOMAIN_RECIPE_ROOT}, {ROUTE_HEADER_H1}, {STATE_SURFACE_NOT_LOADING}"
    ).first
    try:
        deadline_ready.wait_for(state="visible", timeout=timeout_ms)
    except Exception as exc:  # playwright TimeoutError
        raise AssertionError(
            f"路由加载完成信号未出现（recipe 锚点 / h1 / 非 loading 状态面）："
            f"url={page.url} within {timeout_ms}ms"
        ) from exc
    header = page.locator(ROUTE_HEADER_H1)
    if header.count() == 0:
        return ""
    return header.first.inner_text().strip()


def h1_text(page: Any) -> str:
    header = page.locator(ROUTE_HEADER_H1)
    if header.count() == 0:
        return ""
    return header.first.inner_text().strip()
