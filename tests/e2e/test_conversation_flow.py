"""会话交互链路 e2e：发消息免模型断言、终止、空态、hover 工具条、划词引用。

口径（锚点实测见 docs/guides/e2e-playwright.md「锚点约定速查」）：
- composer 输入框 ``textarea[aria-label="发送消息"]``，Enter 提交；
- 生成中：``[role="status"][data-active-turn-stage]`` + 停止按钮 aria-label「终止」；
- 消息计数：会话根 ``div[data-agent-thread-message-count]``（免模型断言利器）；
- 停止反馈：``[data-testid="composer-stop-pending-feedback"]``（终止请求在途）；
- 空态：``这条会话还没有可展示的消息。`` + ``[data-vui="conversation-starter-cards"]``；
- hover 工具条 ``span[data-conversation-hover-actions="1"]``：opacity 门控
  （``opacity-0 group-hover:opacity-100``），Playwright 的 is_visible 对 opacity:0
  仍判可见，因此用 ``getComputedStyle().opacity`` 断言真实可见性；
- 划词引用 ``[data-conversation-selection-menu="1"]``：对消息文本 triple-click
  产生 selection → 点「引用到输入框」→ composer 值含 ``> 所选文本`` 且保持 focus
  （web/src/components/conversation/conversationTextSelection.ts buildQuotedDraftText）。

arrange 优先 API：POST /api/sessions 建会话、POST /api/sessions/{id}/messages 提交
用户消息（helpers/agent_factory.py）。不依赖真实模型输出：turn 提交后立即终止。
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from tests.e2e.helpers.agent_factory import create_session, stop_session_turn, submit_user_message

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

COMPOSER_TEXTAREA = 'textarea[aria-label="发送消息"]'
STOP_BUTTON = 'button[aria-label="终止"]'
SEND_BUTTON = 'button[aria-label="发送"]'
THREAD_ROOT = "div[data-agent-thread-message-count]"
ACTIVE_TURN_STAGE = '[role="status"][data-active-turn-stage]'
STOP_PENDING_FEEDBACK = '[data-testid="composer-stop-pending-feedback"]'
HOVER_ACTIONS = 'span[data-conversation-hover-actions="1"]'
SELECTION_MENU = '[data-conversation-selection-menu="1"]'
STARTER_CARDS = '[data-vui="conversation-starter-cards"]'
EMPTY_STATE_TITLE = "这条会话还没有可展示的消息。"


def _open_session(page: Any, base_url: str, session_id: str) -> None:
    page.goto(f"{base_url}/chat?session={session_id}", wait_until="domcontentloaded")
    page.locator(THREAD_ROOT).first.wait_for(state="visible", timeout=30_000)


def _thread_message_count(page: Any) -> int:
    root = page.locator(THREAD_ROOT).first
    return int(root.get_attribute("data-agent-thread-message-count") or "0")


def test_send_message_stop_mode_then_terminate(page: Any, e2e_instance: Any) -> None:
    """发消息后进入 stop 模式 + turn stage + 消息数增长；终止后回到可输入态。"""
    session_id = create_session(e2e_instance.port, title="e2e conversation flow")
    _open_session(page, e2e_instance.base_url, session_id)

    composer = page.locator(COMPOSER_TEXTAREA).first
    composer.wait_for(state="visible", timeout=15_000)
    count_before = _thread_message_count(page)

    message_text = "e2e 免模型断言：请忽略这条消息"
    composer.click()
    composer.fill(message_text)
    composer.press("Enter")

    # 提交即进入生成态：终止按钮 + turn stage（免模型：不依赖任何模型输出）。
    page.locator(STOP_BUTTON).first.wait_for(state="visible", timeout=15_000)
    page.locator(ACTIVE_TURN_STAGE).first.wait_for(state="visible", timeout=15_000)
    # 用户消息落时间线：计数增长（轮询提交落库的短窗口）。生成中时间线还会叠加
    # 助手侧占位/流式消息，因此断言「严格增长」而非精确 +1（实测 0→2）。
    deadline = page.evaluate("performance.now()") + 15_000
    while _thread_message_count(page) <= count_before:
        assert page.evaluate("performance.now()") < deadline, (
            f"消息计数未增长（before={count_before}, "
            f"after={_thread_message_count(page)}）"
        )
        page.wait_for_timeout(300)
    assert _thread_message_count(page) > count_before

    # 立即终止：stop 请求在途反馈 → 回到可输入态。
    page.locator(STOP_BUTTON).first.click()
    page.locator(STOP_PENDING_FEEDBACK).first.wait_for(state="visible", timeout=10_000)
    # 回到可输入态：终止按钮消失、发送按钮回归、composer 可输入。
    deadline = page.evaluate("performance.now()") + 30_000
    while page.locator(STOP_BUTTON).count() > 0 and page.locator(STOP_BUTTON).first.is_visible():
        assert page.evaluate("performance.now()") < deadline, "终止后 stop 模式未退出"
        page.wait_for_timeout(300)
    page.locator(SEND_BUTTON).first.wait_for(state="visible", timeout=15_000)
    assert composer.is_enabled(), "终止后 composer 仍不可输入"
    assert page.locator(STOP_PENDING_FEEDBACK).count() == 0 or not page.locator(
        STOP_PENDING_FEEDBACK
    ).first.is_visible(), "终止完成后停止反馈仍在"


def test_empty_session_empty_state_and_starters(page: Any, e2e_instance: Any) -> None:
    """空会话：空态文案 + starter 卡片组可见。"""
    session_id = create_session(e2e_instance.port, title="e2e empty session")
    _open_session(page, e2e_instance.base_url, session_id)

    empty_state = page.get_by_text(EMPTY_STATE_TITLE, exact=True).first
    empty_state.wait_for(state="visible", timeout=15_000)
    starters = page.locator(STARTER_CARDS).first
    starters.wait_for(state="visible", timeout=10_000)
    assert starters.is_visible(), "空会话未显示 starter 卡片组"


def test_message_row_hover_actions_become_visible(page: Any, e2e_instance: Any) -> None:
    """已有消息行 hover 后工具条真实可见（opacity 门控，非存在性）。"""
    session_id = create_session(e2e_instance.port, title="e2e hover actions")
    marker = f"e2e hover 工具条用例消息 {session_id[:8]}"
    submit_user_message(e2e_instance.port, session_id, marker)
    _open_session(page, e2e_instance.base_url, session_id)

    # 等用户消息渲染出来。
    message_text = page.get_by_text(marker).first
    message_text.wait_for(state="visible", timeout=20_000)

    def _hover_opacities() -> list[str]:
        return page.evaluate(
            """() => Array.from(
                document.querySelectorAll('span[data-conversation-hover-actions="1"]'),
            ).map((el) => getComputedStyle(el).opacity)"""
        )

    # hover 前：工具条全部透明（opacity 0）。
    page.wait_for_timeout(500)
    before = _hover_opacities()
    assert before, "消息行没有 hover 工具条（data-conversation-hover-actions）"
    assert all(value == "0" for value in before), f"hover 前工具条已可见: {before}"

    # hover 消息行：工具条 opacity 变为 1（真实可见）。
    message_text.hover()
    deadline = page.evaluate("performance.now()") + 5_000
    while True:
        after = _hover_opacities()
        if any(value != "0" for value in after):
            break
        assert page.evaluate("performance.now()") < deadline, f"hover 后工具条仍不可见: {after}"
        message_text.hover()
        page.wait_for_timeout(300)
    # 工具条内确有可交互按钮（复制/分叉等）。
    actions_span = page.locator(f"{HOVER_ACTIONS}").first
    assert actions_span.locator("button").count() > 0, "hover 工具条内没有按钮"
    # 收尾：终止 arrange 阶段提交的在飞 turn，不挡实例优雅停机。
    stop_session_turn(e2e_instance.port, session_id)


def test_selection_quote_to_composer(page: Any, e2e_instance: Any) -> None:
    """划词 → 引用菜单出现 → 引用到输入框：composer 含所选文本且保持 focus。"""
    session_id = create_session(e2e_instance.port, title="e2e selection quote")
    selected_text = f"e2e 划词引用目标句 {session_id[:8]}"
    submit_user_message(e2e_instance.port, session_id, f"{selected_text}，前后各有补充内容。")
    _open_session(page, e2e_instance.base_url, session_id)

    message_text = page.get_by_text(selected_text).first
    message_text.wait_for(state="visible", timeout=20_000)

    # triple-click 选中段落：真实 mouseup + selectionchange 驱动划词菜单。
    message_text.click(click_count=3)
    menu = page.locator(SELECTION_MENU).first
    menu.wait_for(state="visible", timeout=10_000)

    quote_button = menu.get_by_role("button", name="引用到输入框")
    quote_button.click()

    composer = page.locator(COMPOSER_TEXTAREA).first
    deadline = page.evaluate("performance.now()") + 5_000
    while selected_text not in (composer.input_value() or ""):
        assert page.evaluate("performance.now()") < deadline, (
            f"composer 未包含所选文本: {composer.input_value()!r}"
        )
        page.wait_for_timeout(300)
    value = composer.input_value()
    assert f"> {selected_text}" in value, f"引用格式不符（应为 > 前缀）: {value!r}"
    assert composer.evaluate("el => el === document.activeElement"), "引用后 composer 未获得焦点"
    # 收尾：终止 arrange 阶段提交的在飞 turn，不挡实例优雅停机。
    stop_session_turn(e2e_instance.port, session_id)
