"""会话 SSE keep-warm 回归：离开 /chat 30s 内切回，/events 不应有第二次请求。

口径（docs/guides/e2e-playwright.md「keep-warm 网络断言口径」；实现
web/src/routes/chat/sessionStreamWarmRegistry.ts，SESSION_STREAM_WARM_MS=30_000）：
- 在 /chat 打开会话，统计 ``GET /api/sessions/*/events`` 请求数（page.on("request")）；
- 经主导航切到 /agents 再切回（远小于 30s 窗口）；
- 断言 /events 仍只有第一次请求（warm 连接复用），且切回后不出现
  「正在加载会话消息…」加载骨架（``[data-testid="conversation-transcript-loading-state"]``）。

控时序：切走→切回全程秒级完成，不会越过 30s warm 窗口。
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import pytest

from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.page_anchors import domain_recipe_selector, primary_nav_link

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

THREAD_ROOT = "div[data-agent-thread-message-count]"
TRANSCRIPT_SKELETON = '[data-testid="conversation-transcript-loading-state"]'
EVENTS_URL_PATTERN = re.compile(r"/api/sessions/[^/?]+/events")


def _open_chat_and_wait_thread_root(page: Any, base_url: str, session_id: str) -> None:
    """打开 /chat?session=<id> 并等会话容器渲染；偶发首屏过慢时重载一次重试。

    高负载开发机上首次 goto 偶发 30s 内不出会话容器（前端 chunk/首屏竞态），
    与被测的 keep-warm 语义无关，允许一次重载重试；仍失败则截图留现场。
    """
    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            page.goto(f"{base_url}/chat?session={session_id}", wait_until="domcontentloaded")
            page.locator(THREAD_ROOT).first.wait_for(state="visible", timeout=30_000)
            return
        except Exception as exc:  # noqa: BLE001 - 记录后重载重试
            last_error = exc
            try:
                page.screenshot(path=f"C:/vtmp/e2e-keep-warm-attempt{attempt}.png")
            except Exception:  # noqa: BLE001 - 截图失败不影响主流程
                pass
    raise AssertionError(f"/chat 会话容器两次未渲染（session={session_id}）: {last_error}")


def test_session_stream_stays_warm_within_window(page: Any, e2e_instance: Any) -> None:
    """30s 内切走再切回：/events 无第二次请求 + 无会话消息加载骨架。"""
    session_id = create_session(e2e_instance.port, title="e2e keep warm")
    events_seen: list[str] = []
    page.on(
        "request",
        lambda request: events_seen.append(request.url)
        if EVENTS_URL_PATTERN.search(request.url)
        else None,
    )

    _open_chat_and_wait_thread_root(page, e2e_instance.base_url, session_id)
    thread_root = page.locator(THREAD_ROOT).first

    # 等第一条 /events 请求出现（SSE 订阅建立）。
    deadline = time.monotonic() + 15
    while not events_seen:
        assert time.monotonic() < deadline, "打开会话后没有出现 /api/sessions/*/events 请求"
        page.wait_for_timeout(200)
    first_event_url = events_seen[0]
    assert f"/{session_id}/" in first_event_url, (
        f"/events 请求不属于测试会话: {first_event_url}"
    )

    # 切走：主导航 → /agents（纯路由跳转的允许点击面）。
    page.locator(primary_nav_link("/agents")).first.click()
    page.locator(domain_recipe_selector("agents-management-workbench")).first.wait_for(
        state="visible", timeout=30_000
    )

    # 切回（远小于 30s warm 窗口）。
    page.locator(primary_nav_link("/chat")).first.click()

    # 主断言先行：/events 没有第二次请求（warm 连接复用）。纯网络口径不受
    # 首屏渲染快慢影响；轮询窗口内若出现第二次请求则立即判负。
    render_deadline = time.monotonic() + 60
    while time.monotonic() < render_deadline:
        if len(events_seen) > 1:
            break
        if page.locator(THREAD_ROOT).first.is_visible():
            # 容器已渲染，稍候确认没有补发请求。
            page.wait_for_timeout(1_500)
            break
        page.wait_for_timeout(1_000)
    assert len(events_seen) == 1, (
        f"切回后 /events 出现了 {len(events_seen) - 1} 次新请求: {events_seen}"
    )

    # DOM 备选口径：切回后不应出现「正在加载会话消息…」骨架。
    thread_root = page.locator(THREAD_ROOT).first
    if not thread_root.is_visible():
        try:
            thread_root.wait_for(state="visible", timeout=60_000)
        except Exception:  # noqa: BLE001 - 留现场再抛
            try:
                page.screenshot(path="C:/vtmp/e2e-keep-warm-render.png")
            except Exception:  # noqa: BLE001 - 截图尽力而为
                pass
            raise AssertionError(
                f"切回 /chat 后会话容器 60s 未渲染（url={page.url}，events={events_seen}）"
            )
    assert page.locator(TRANSCRIPT_SKELETON).count() == 0 or not page.locator(
        TRANSCRIPT_SKELETON
    ).first.is_visible(), "切回后出现了会话消息加载骨架（keep-warm 未生效）"
