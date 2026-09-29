"""主导航性能基线：测量 + 预算断言（``VIBELUTION_E2E_PERF_MEASURE_ONLY=1`` 时只测量）。

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

预算门：默认对每路由 goto/clickNav 与遥测事件总量断言上限（见
``GOTO_BUDGET_MS`` / ``CLICK_NAV_BUDGET_MS`` / 遥测预算常量的推导注释）。
设 ``VIBELUTION_E2E_PERF_MEASURE_ONLY=1`` 则只采集不断言——重新定基线时
用该模式采 5 轮、回填预算表即可，无需改断言逻辑。
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

# 只测量不断言的逃生口：重新定基线时设 1，采样新数据回填下方预算表。
MEASURE_ONLY_ENV_VAR = "VIBELUTION_E2E_PERF_MEASURE_ONLY"

# ---------------------------------------------------------------------------
# 预算门推导（2026-09-29，worktree codex/e2e-perf-budget，main tip 0786c609e）。
# 样本：同日 13 轮全部 8/8 measured 的并集——02:35–02:40 定基 4 轮、
# 02:41–02:58 验证 8 轮（perf_baseline_20260929-024135…025859）、10:30 日间
# 复验 1 轮（perf_baseline_20260929-103048，日间负载下 clickNav 整体抬升，
# 暴露 /companions 与 /supervised-evolution 两处预算不足后并入样本）。测量
# 期机器有并行会话负载，预算按防抖公式放大而非收紧。
#
# 防抖公式：预算下限 = max(13 轮并集最大值 × 1.3, 13 轮中位数 × 3)，向上
# 取整到十位。交接复核发现首版预算多处低于该下限（定基 5 轮中位数低估了
# 后续轮，验证轮与日间复验轮抬高中位与尾部），已分批上调至不窄于下限；
# 个别项保留历史上更宽的取值（注释中标注）。目标：只抓数量级回归（切页
# 卡死、异常重渲染、遥测轰炸），不管 10% 量级噪声。取两式更宽者保证采样
# 期内观测到的最大抖动（含冷启动离群点 /companions goto 7056ms、/agents
# clickNav 14160ms——高负载下首次懒加载 chunk 编译所致）不会 flake。
#
# 13 轮采样（ms，min/median/max）：
#   /chat                  goto 177/271/481     clickNav 379/1052/1868
#   /companions            goto 446/641/7056    clickNav 123/231/1168
#   /supervised-evolution  goto 519/572/933     clickNav 221/335/1420
#   /self-evolution        goto 584/759/1453    clickNav 227/340/923
#   /teams                 goto 510/605/1492    clickNav 230/857/1379
#   /kernel                goto 498/577/1035    clickNav 116/225/251
#   /memory                goto 439/584/1383    clickNav 221/849/885
#   /agents                goto 947/1184/2150   clickNav 813/860/14160
GOTO_BUDGET_MS: dict[str, int] = {
    "/chat": 970,  # 下限 max(481*1.3≈625, 271*3=813)=820；保留 8 轮复核值 970
    "/companions": 9180,  # max(7056*1.3≈9173, 641*3=1923)=9180（冷启动离群点定值）
    "/supervised-evolution": 1730,  # 下限 max(933*1.3≈1213, 572*3=1716)=1720；保留 8 轮复核值 1730
    "/self-evolution": 2830,  # 下限 max(1453*1.3≈1889, 759*3=2277)=2280；保留定基轮更宽取值
    "/teams": 1940,  # max(1492*1.3≈1940, 605*3=1815)=1940；日间复验 1492ms 后由 1820 上调
    "/kernel": 1760,  # 下限 max(1035*1.3≈1346, 577*3=1731)=1740；保留 8 轮复核值 1760
    "/memory": 1800,  # max(1383*1.3≈1798, 584*3=1752)=1800；日间复验 1383ms 后由 1780 上调
    "/agents": 3660,  # 下限 max(2150*1.3≈2795, 1184*3=3552)=3560；保留 8 轮复核值 3660
}
CLICK_NAV_BUDGET_MS: dict[str, int] = {
    "/chat": 3270,  # 下限 max(1868*1.3≈2428, 1052*3=3156)=3160；保留定基轮更宽取值
    "/companions": 1520,  # max(1168*1.3≈1518, 231*3=693)=1520；日间复验 1168ms 后由 750 上调
    "/supervised-evolution": 1850,  # max(1420*1.3=1846, 335*3=1005)=1850；定基 max 曾定 830，914ms 翻车上调 1190，日间复验 1420ms 再上调
    "/self-evolution": 1200,  # max(923*1.3≈1200, 340*3=1020)=1200；由 1130 上调
    "/teams": 2580,  # max(1379*1.3≈1793, 857*3=2571)=2580
    "/kernel": 710,  # 下限 max(251*1.3≈326, 225*3=675)=680；保留 710
    "/memory": 2550,  # max(885*1.3≈1151, 849*3=2547)=2550
    "/agents": 18410,  # max(14160*1.3≈18408, 860*3=2580)=18410（离群点定值）
}

# 遥测预算（13 轮采样）：主导航一次巡检不应产生遥测轰炸。
# - 全量事件总数 13 轮 88–103，max=103 → ×1.5 余量 = 155；
# - 导航相关三码（route.changed + chat_route.chunk_load_started/loaded）
#   合计 13 轮 28–29，max=29 → ×2 余量 = 58，取 60。
TELEMETRY_TOTAL_EVENT_BUDGET = 155
NAV_TRACKED_EVENT_BUDGET = 60


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

    if os.environ.get(MEASURE_ONLY_ENV_VAR) == "1":
        print(
            f"[perf] {MEASURE_ONLY_ENV_VAR}=1：跳过预算断言（只测量）。"
            "回填 GOTO_BUDGET_MS / CLICK_NAV_BUDGET_MS / 遥测预算前请先采 5 轮。"
        )
        return

    # 预算断言：失败信息必须带实测值 vs 预算值。未在预算表中的路由（如未来
    # 新增主导航项）不断言，避免结构性改动误伤；遥测预算对全量与导航相关
    # 三码分别封顶。
    budget_violations = [
        f"{item['path']} goto 实测 {item['gotoMs']}ms > 预算 {GOTO_BUDGET_MS[item['path']]}ms"
        for item in measured
        if item["path"] in GOTO_BUDGET_MS and item["gotoMs"] > GOTO_BUDGET_MS[item["path"]]
    ] + [
        f"{item['path']} clickNav 实测 {item['clickNavMs']}ms > 预算 {CLICK_NAV_BUDGET_MS[item['path']]}ms"
        for item in measured
        if item["path"] in CLICK_NAV_BUDGET_MS and item["clickNavMs"] > CLICK_NAV_BUDGET_MS[item["path"]]
    ]
    assert not budget_violations, "主导航性能预算超标（数量级回归）: " + "; ".join(budget_violations)

    telemetry_total = sum(telemetry.counts.values())
    nav_tracked_total = sum(telemetry.counts.get(code, 0) for code in TRACKED_EVENT_CODES)
    assert telemetry_total <= TELEMETRY_TOTAL_EVENT_BUDGET, (
        f"遥测事件总量实测 {telemetry_total} > 预算 {TELEMETRY_TOTAL_EVENT_BUDGET}"
        f"（主导航巡检不应产生遥测轰炸）: {dict(telemetry.counts)}"
    )
    assert nav_tracked_total <= NAV_TRACKED_EVENT_BUDGET, (
        f"导航遥测三码总量实测 {nav_tracked_total} > 预算 {NAV_TRACKED_EVENT_BUDGET}"
        f"（route.changed/chunk_load_started/chunk_loaded 轰炸）: "
        f"{ {code: telemetry.counts.get(code, 0) for code in TRACKED_EVENT_CODES} }"
    )
