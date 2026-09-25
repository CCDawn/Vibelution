"""主导航性能基线：只测量、不断言阈值（阈值另行评定后回填）。

对主导航 8 项（顶栏 ``nav[data-shell-group="navigation"]`` 的 8 个路由）各采集：
- ``goto`` 计时：``page.goto`` → 目标页 ``[data-vui-domain-recipe]`` 可见；
- 顶栏点击切换计时：从静态中转页 ``/reset`` 点击 ``a[data-vui="route-link-button"]``
  （唯一的允许点击面，只导航不触发业务副作用）→ 目标页 recipe 锚点可见；
- ``window.performance``：导航耗时（DOMContentLoaded/load）、资源数、JS 堆；
- 遥测事件计数（拦截 POST /api/runtime/browser-telemetry 放行并统计）：
  ``browser.route.changed``、``browser.chat_route.chunk_load_started/loaded``。

完成信号用 domain-recipe 而非 route-header h1：实测（2026-09-25）chat/evolution
工作台没有 h1，agents 家族与 /teams 的 h1 空态下隐藏；8 个主导航路由全部带
稳定且按页唯一的 domain-recipe。

结果 JSON 落 ``C:\\vtmp\\vibelution-e2e\\``（不可写时回退系统 temp），
stdout 打印简表。只读测量 + 顶栏导航，不触碰危险按钮禁区。
"""

from __future__ import annotations

import json
import os
import platform
import re
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.helpers.page_anchors import (
    ROUTE_HEADER_H1,
    domain_recipe_selector,
    primary_nav_link,
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

# 主导航 8 项 → 预期 domain-recipe（AppShell.tsx 顶栏顺序；chat/evolution 项受
# 可用性守卫，禁用时记 skip 不测量）。
MAIN_NAV_ROUTES: tuple[tuple[str, str], ...] = (
    ("/chat", "chat-session-workbench"),
    ("/companions", "virtual-human-companion-lobby"),
    ("/supervised-evolution", "evolution-multi-rail"),
    ("/self-evolution", "evolution-multi-rail"),
    ("/teams", "teams-organization-workbench"),
    ("/kernel", "kernel-task-center-workbench"),
    ("/memory", "memory-knowledge-workbench"),
    ("/agents", "agents-management-workbench"),
)
STAGING_PATH = "/reset"  # 纯静态页：两次点击测量之间的中转，无轮询无危险按钮。

TELEMETRY_PATH_PATTERN = "**/api/runtime/browser-telemetry"
TRACKED_EVENT_CODES = (
    "browser.route.changed",
    "browser.chat_route.chunk_load_started",
    "browser.chat_route.chunk_loaded",
)
_OUTPUT_DIR_CANDIDATES = (Path(r"C:\vtmp\vibelution-e2e"), Path(tempfile.gettempdir()) / "vibelution-e2e")


def _output_dir() -> Path:
    for candidate in _OUTPUT_DIR_CANDIDATES:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    raise RuntimeError("perf baseline 输出目录不可创建（C:\\vtmp 与系统 temp 均失败）")


class TelemetryCounter:
    """拦截浏览器遥测 POST 并累计 eventCode 计数（请求原样放行）。"""

    def __init__(self, page: Any) -> None:
        self.counts: Counter[str] = Counter()
        page.route(TELEMETRY_PATH_PATTERN, self._handle)

    def _handle(self, route: Any) -> None:
        try:
            body = route.request.post_data or ""
            self.counts.update(re.findall(r'"eventCode"\s*:\s*"([^"]+)"', body))
        except Exception:  # noqa: BLE001 - 计数失败不影响请求放行
            pass
        route.continue_()

    def snapshot(self) -> Counter[str]:
        return self.counts.copy()


def _on_path(page: Any, base_url: str, path: str) -> bool:
    return str(page.url).startswith(f"{base_url}{path}")


def _measure_performance(page: Any) -> dict[str, Any]:
    data = page.evaluate(
        """() => {
            const nav = performance.getEntriesByType('navigation')[0];
            const memory = performance.memory || null;
            return {
                domContentLoadedMs: nav ? Math.round(nav.domContentLoadedEventEnd) : null,
                loadMs: nav ? Math.round(nav.loadEventEnd) : null,
                transferResourceCount: performance.getEntriesByType('resource').length,
                usedJsHeapMb: memory ? Math.round((memory.usedJSHeapSize / 1048576) * 10) / 10 : null,
            };
        }"""
    )
    return dict(data)


def _goto_timed(page: Any, base_url: str, path: str, recipe: str) -> tuple[float, str]:
    """goto 完成口径：目标页 recipe 锚点可见。"""
    started = time.perf_counter()
    page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
    page.locator(domain_recipe_selector(recipe)).first.wait_for(state="visible", timeout=30_000)
    return round((time.perf_counter() - started) * 1000), recipe


def _click_nav_timed(page: Any, base_url: str, path: str, recipe: str) -> tuple[float, str]:
    """点击切换完成口径：URL 到达目标 + recipe 锚点可见。"""
    started = time.perf_counter()
    page.locator(primary_nav_link(path)).first.click()
    page.wait_for_url(lambda url: _on_path(page, base_url, path), timeout=20_000)
    page.locator(domain_recipe_selector(recipe)).first.wait_for(state="visible", timeout=30_000)
    return round((time.perf_counter() - started) * 1000), recipe


def test_main_nav_perf_baseline(e2e_instance: Any) -> None:
    from playwright.sync_api import sync_playwright

    base_url = e2e_instance.base_url
    telemetry: TelemetryCounter | None = None
    results: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            context.set_default_timeout(30_000)
            page = context.new_page()
            telemetry = TelemetryCounter(page)

            # 预热：先落一个静态页，保证后续 goto 测量不包含首次 TCP/资产冷启动差异口径混乱。
            page.goto(f"{base_url}{STAGING_PATH}", wait_until="domcontentloaded")
            page.locator(ROUTE_HEADER_H1).first.wait_for(state="visible", timeout=30_000)

            for path, recipe in MAIN_NAV_ROUTES:
                nav_link = page.locator(primary_nav_link(path))
                if nav_link.count() == 0:
                    results.append({"path": path, "status": "nav-link-missing"})
                    continue
                if nav_link.first.get_attribute("aria-disabled") is not None:
                    results.append({"path": path, "status": "disabled-by-availability"})
                    continue

                before = telemetry.snapshot()
                goto_ms, anchor = _goto_timed(page, base_url, path, recipe)
                perf_after_goto = _measure_performance(page)
                goto_events = {
                    code: telemetry.snapshot().get(code, 0) - before.get(code, 0)
                    for code in TRACKED_EVENT_CODES
                }

                # 点击口径：回到静态中转页，再从顶栏点击目标项。
                page.goto(f"{base_url}{STAGING_PATH}", wait_until="domcontentloaded")
                page.locator(ROUTE_HEADER_H1).first.wait_for(state="visible", timeout=30_000)
                click_before = telemetry.snapshot()
                click_ms, _ = _click_nav_timed(page, base_url, path, recipe)
                click_events = {
                    code: telemetry.snapshot().get(code, 0) - click_before.get(code, 0)
                    for code in TRACKED_EVENT_CODES
                }

                results.append({
                    "path": path,
                    "status": "measured",
                    "gotoMs": goto_ms,
                    "clickNavMs": click_ms,
                    "anchor": anchor,
                    "perfAfterGoto": perf_after_goto,
                    "eventsOnGoto": goto_events,
                    "eventsOnClickNav": click_events,
                })
                print(
                    f"[perf] {path:<24} goto={goto_ms:>6}ms  clickNav={click_ms:>6}ms"
                    f"  resources={perf_after_goto.get('transferResourceCount')}"
                    f"  heap={perf_after_goto.get('usedJsHeapMb')}MB"
                )
        finally:
            browser.close()

    assert telemetry is not None
    payload = {
        "measuredAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "baseUrl": base_url,
        "instanceId": e2e_instance.instance_id,
        "head": e2e_instance.health.get("serving", {}).get("frontend", {}).get("builtFromCommit", ""),
        "viewport": "1440x900",
        "userAgent": platform.platform(),
        "telemetryTotals": dict(telemetry.counts),
        "routes": results,
    }
    output_path = _output_dir() / f"perf_baseline_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    measured = [item for item in results if item.get("status") == "measured"]
    print(
        f"[perf] 主导航 {len(measured)}/{len(MAIN_NAV_ROUTES)} 项完成测量，"
        f"遥测总量={dict(telemetry.counts)}，结果 JSON: {output_path}"
    )
    assert measured, "主导航 8 项没有一项完成测量（检查 e2e_instance 是否就绪、导航是否被可用性守卫禁用）"
