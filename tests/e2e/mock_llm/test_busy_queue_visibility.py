# -*- coding: utf-8 -*-
"""e2e 忙时排队可见性：钉 2026-09-25 缺陷①修复 c0d8bf016 的前端投影。

缺陷①口径（见 defect-audit-e2e-findings-0925.md）：会话忙时提交的第二条消息
此前走「假装已发送」的乐观路径——乐观 user 行冻结在时间线上、turn 静默入队、
零错误面。修复 c0d8bf016 后：入队响应携带排队事实（queued/queuedTurnId/
queuedAt/queuedBehindTurnId，core/web/services/session/submit.py
``_enqueue_busy_session_turn``），前端 ``useChatComposerSubmit.ts`` 把排队行
乐观投进 followup 队列条（``ConversationFollowupQueueBar``，aria-label
「待发送队列」），排队提交跳过 ``appendOptimisticUserMessage``，不再往时间线
塞「已发送」乐观 user 行。

本用例闸门（90s 上浮提示由单测层覆盖，e2e 不等 90s——成本过高）：
1. 第一轮低速流式进行中提交第二条消息 → 队列条出现排队行（头「排队中 · 1 条」
   + 行内可见第二条消息文本）；
2. 排队行不得假装「已发送」：排队被接受后 thread 消息数不变（时间线只有第一轮
   的 user + 助手行；后端入队只写 queued-turns 队列结构、不提交时间线 user 行，
   见 ``core/web/services/session/queued_turns.py``）；
3. 收口：第一轮流完 → 队列自动 drain 启动第二轮 → 两轮均收口、队列条清空、
   无错误面，两轮主调用真实完成（journal 主调用 200 条目 ≥2）。

场景复用（不新建 fixture 文件、不改共享 runner.mjs）：两轮共用共享剧本
``E2E-MOCK-SLOW-V1``（scenarios/runner.mjs 场景 12，ttft 500ms + tps 8 +
240 字符正文 ≈ 30s 流式窗口，本车道此前无用例占用）。注意 runner 剧本按
「请求的任意 user 消息含标记」路由：第二轮（drain 后重提交）的请求历史必然
携带第一轮标记，因此同样命中 SLOW-V1——两轮回复同为数字正文（车道多轮语义，
见 test_multi_turn_context），catch-all 对本会话不可达；drain 本体由
journal 主调用条目增长 + 队列条清空 + 消息数收口钉死，不靠回复内容区分轮次。

写法照抄 ``tests/e2e/mock_llm/test_mock_llm_flow.py`` 的车道纪律（serial +
skipif 环境门；辅助步骤自包含——另一任务正在改该文件，本文件不 import 它）。
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest

pytestmark = [
    pytest.mark.serial,
    pytest.mark.timeout(0),
    # skipif 而非模块级 skip：模块级 skip 会「零收集」，closeout 选择器直跑
    # 本文件时 pytest 退出码 5（NO_TESTS_COLLECTED）判失败；skipif 逐条跳过退出码 0。
    pytest.mark.skipif(
        os.environ.get("VIBELUTION_E2E") != "1",
        reason="e2e 手动车道：设 VIBELUTION_E2E=1 后运行（见 docs/guides/e2e-mock-llm.md）",
    ),
]

TURN_STATUS_NOTE = '[role="status"][data-active-turn-stage]'
THREAD_ROOT = "div[data-agent-thread-message-count]"

# 队列条锚（web/src/components/conversation/ConversationFollowupQueueBar.tsx）：
# 根容器 aria-label「待发送队列」，头部文案「排队中 · N 条」，行内渲染排队消息
# 原文（followupQueueRowText）。均为源码字面量，非构建期 hash。
QUEUE_BAR = 'div[aria-label="待发送队列"]'
QUEUE_BAR_HEADER_HAS_ONE = "排队中 · 1 条"

# ② 同款内联错误卡锚（ConversationView.styles.ts 字面量 class token）。
TURN_ERROR_BANNER = 'div.turnError[role="status"]'
TURN_ERROR_NOTICE = 'div.turnErrorNotice[role="status"]'

TURN_COMPLETE_TIMEOUT_MS = 120_000

SLOW_MARKER = "E2E-MOCK-SLOW-V1"
QUEUED_MARKER = "E2E-MOCK-QUEUE-V2"


# ---------------------------------------------------------------------------
# 共享步骤（自包含；与 test_mock_llm_flow.py 同口径，不 import 它）
# ---------------------------------------------------------------------------


def open_agent_chat(page: Any, e2e_instance: Any, session_id: str) -> None:
    from tests.e2e.helpers.page_anchors import wait_route_ready

    page.goto(
        f"{e2e_instance.base_url}/chat?session={session_id}",
        wait_until="domcontentloaded",
    )
    wait_route_ready(page)
    thread = page.locator(THREAD_ROOT).first
    thread.wait_for(state="visible", timeout=20_000)


def send_message(page: Any, text: str) -> None:
    composer = page.locator('textarea[aria-label="发送消息"]').first
    composer.wait_for(state="visible", timeout=15_000)
    composer.click()
    composer.fill(text)
    composer.press("Enter")


def _attr(holder: Any, name: str, *, timeout_ms: int = 800) -> str:
    """读元素属性；元素瞬时分离（turn 收口竞态）时返回空串而不是挂死。"""
    try:
        return holder.get_attribute(name, timeout=timeout_ms) or ""
    except Exception:  # noqa: BLE001 - playwright 定位失败即视为元素已消失
        return ""


def thread_message_count(page: Any) -> int:
    raw = _attr(page.locator(THREAD_ROOT).first, "data-agent-thread-message-count")
    try:
        return int(raw)
    except ValueError:
        return 0


def wait_turn_started(
    page: Any,
    mock_llm: Any,
    *,
    submit_text: str,
    timeout_ms: int = 8_000,
) -> bool:
    """等 turn 真正启动：stage 推进到 user_submit 之后，或 journal 出现请求。

    乐观态 stage 条本身不是启动证据（车道已知「提交停在乐观态」故障签名），
    必须看到阶段推进或 mock 收到请求；超时重发一次再等一轮。
    """
    def _started() -> bool:
        if mock_llm.server.journal(path="/v1/chat/completions"):
            return True
        notes = page.locator(TURN_STATUS_NOTE)
        for i in range(min(notes.count(), 3)):
            stage = _attr(notes.nth(i), "data-active-turn-stage")
            if stage and stage != "user_submit":
                return True
        return False

    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if _started():
            return True
        page.wait_for_timeout(250)
    print(f"[busy_queue] 提交未真正启动 turn（乐观态冻结），重发一次: {submit_text[:40]!r}")
    send_message(page, submit_text)
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if _started():
            return True
        page.wait_for_timeout(250)
    return False


def _is_title_entry(entry: dict[str, Any]) -> bool:
    """journal 条目是否为标题生成等辅助调用（口径同 test_mock_llm_flow.py）。"""
    body = entry.get("body") or {}
    msgs = body.get("messages") or []
    for m in reversed(msgs):
        if m.get("role") == "user":
            return str(m.get("content") or "").lstrip().startswith("用户消息：")
    return False


def journal_main_200_counts(mock_llm: Any) -> int:
    """主调用 200 条目数（排除标题辅助调用；body 超 64KB 的条目 model 为空）。"""
    entries = mock_llm.server.journal(path="/v1/chat/completions")
    return sum(
        1
        for e in entries
        if not _is_title_entry(e)
        and int(e.get("response", {}).get("status") or 0) == 200
    )


def assert_no_error_surface(page: Any) -> None:
    errors = page.locator('section[data-vui="state-surface"][data-tone="error"]')
    assert errors.count() == 0, f"出现 error 状态面（count={errors.count()}）"


def assert_no_turn_error_card(page: Any) -> None:
    banner = page.locator(TURN_ERROR_BANNER)
    notice = page.locator(TURN_ERROR_NOTICE)
    assert banner.count() == 0, f"出现「请求错误」实时错误横幅（count={banner.count()}）"
    assert notice.count() == 0, f"出现时间线内联错误卡（count={notice.count()}）"


@pytest.fixture
def chat_agent(mock_llm: Any):
    """建一个绑 e2e-mock-chat 的 Agent；用例结束归档。"""
    created = mock_llm.create_agent("e2e-mock-chat", "E2E Busy Queue Agent")
    yield created
    mock_llm.delete_agent(created["agentId"])


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------


def test_busy_submit_projects_queue_row_and_drains(
    page: Any,
    e2e_instance: Any,
    mock_llm: Any,
    chat_agent: dict,
) -> None:
    """忙时提交 → 队列条出现排队行且不假装已发送 → 首轮流完自动 drain 收口。

    排序约束：占位轮复用共享剧本 SLOW-V1（≈30s 流式窗口），本用例必须在该窗口
    内完成排队观察；全用例不依赖执行次序（journal 每用例重置，Agent 独立）。
    """
    open_agent_chat(page, e2e_instance, chat_agent["sessionId"])

    # --- 第一轮：低速流式占住会话 -------------------------------------------
    slow_text = f"{SLOW_MARKER} 请慢慢回复，占住会话"
    send_message(page, slow_text)
    assert wait_turn_started(page, mock_llm, submit_text=slow_text), "占位轮未启动"

    # 乐观层已投影后消息数才稳定（user 行 + 在飞助手行）；等两次采样一致再取基线。
    c0 = thread_message_count(page)
    deadline = time.monotonic() + 5_000 / 1000
    while time.monotonic() < deadline:
        page.wait_for_timeout(500)
        c0b = thread_message_count(page)
        if c0b == c0 and c0 > 0:
            break
        c0 = c0b
    assert c0 > 0, "占位轮启动后 thread 消息数仍为 0（乐观层未投影）"
    print(f"[busy_queue] 占位轮进行中，thread 消息数基线 c0={c0}")

    # --- 忙时提交第二条消息 --------------------------------------------------
    mains_before_queue = journal_main_200_counts(mock_llm)
    queued_text = f"{QUEUED_MARKER} 这条消息应当排队"
    send_message(page, queued_text)

    # 闸门一：队列条出现排队行（乐观排队投影来自响应排队事实）。
    bar = page.locator(QUEUE_BAR)
    deadline = time.monotonic() + 15_000 / 1000
    while time.monotonic() < deadline:
        if bar.count() and bar.first.is_visible():
            break
        page.wait_for_timeout(250)
    else:
        composer_error = page.locator('p[role="alert"]')
        raise AssertionError(
            "忙时提交 15s 内队列条未出现（排队投影未生效）。现场："
            f"composer 告警文本={[composer_error.nth(i).inner_text() for i in range(composer_error.count())]} "
            f"thread_status={_attr(page.locator(THREAD_ROOT).first, 'data-agent-thread-status')} "
            f"message_count={thread_message_count(page)}（基线 c0={c0}）"
        )
    bar_text = bar.first.inner_text()
    assert QUEUE_BAR_HEADER_HAS_ONE in bar_text, (
        f"队列条头部未显示 1 条排队（期望含 {QUEUE_BAR_HEADER_HAS_ONE!r}）: {bar_text[:200]!r}"
    )
    assert QUEUED_MARKER in bar_text, f"排队行未渲染消息原文: {bar_text[:200]!r}"

    # 闸门二：排队行不得假装「已发送」——排队被接受后时间线消息数不变
    # （正确的投影只进队列条；缺陷①旧行为会追加冻结的乐观 user 行使计数 +1）。
    # 在占位轮仍处于流式窗口内采样；两采样点间若已 idle（drain 间隙）则跳过。
    busy_samples = 0
    for _attempt in range(4):
        status = _attr(page.locator(THREAD_ROOT).first, "data-agent-thread-status")
        if status and status != "idle":
            count = thread_message_count(page)
            assert count == c0, (
                f"排队消息以「已发送」乐观行进了时间线（缺陷①回归）：count={count} 基线 c0={c0}"
            )
            busy_samples += 1
        page.wait_for_timeout(700)
    assert busy_samples >= 1, "占位轮在观察窗口内提前收口，未完成忙时断言（流式窗口不足）"
    print(f"[busy_queue] 排队行可见且时间线计数保持 c0={c0}（忙时采样 {busy_samples} 次）")

    # --- 收口：占位轮流完 → drain 第二轮 → 两轮都收口 -----------------------
    deadline = time.monotonic() + TURN_COMPLETE_TIMEOUT_MS / 1000
    while time.monotonic() < deadline:
        status = _attr(page.locator(THREAD_ROOT).first, "data-agent-thread-status")
        count = thread_message_count(page)
        bar_gone = page.locator(QUEUE_BAR).count() == 0
        if status == "idle" and count >= 2 * c0 and bar_gone:
            break
        page.wait_for_timeout(300)
    else:
        raise AssertionError(
            f"队列未在 {TURN_COMPLETE_TIMEOUT_MS}ms 内 drain 收口："
            f"thread_status={_attr(page.locator(THREAD_ROOT).first, 'data-agent-thread-status')} "
            f"message_count={thread_message_count(page)}（基线 c0={c0}） "
            f"queue_bar_count={page.locator(QUEUE_BAR).count()}"
        )

    # 两轮正文都上时间线（idle 投影可能晚一拍，轮询等文本）。两轮回复同为
    # SLOW-V1 的数字正文（剧本按请求历史里的标记路由，见文件头注释）：
    # 断言两轮 user 行（两标记）+ 数字正文出现 ≥40 次（单轮完整正文 240 字符
    # 含 24 次 "0123456789"，两轮完整收口为 48 次）。
    deadline = time.monotonic() + 15_000 / 1000
    texts = page.locator(THREAD_ROOT).first.inner_text()
    while not (
        SLOW_MARKER in texts
        and QUEUED_MARKER in texts
        and texts.count("0123456789") >= 40
    ):
        if time.monotonic() >= deadline:
            raise AssertionError(
                "两轮正文未齐上时间线（期望两轮 user 行 + 两段数字正文）: "
                f"slow_user={SLOW_MARKER in texts} queued_user={QUEUED_MARKER in texts} "
                f"digits_count={texts.count('0123456789')} tail={texts[-300:]!r}"
            )
        page.wait_for_timeout(300)
        texts = page.locator(THREAD_ROOT).first.inner_text()

    assert_no_error_surface(page)
    assert_no_turn_error_card(page)

    # drain 证据：排队消息被 dequeue 后以真实 turn 重发，两轮主调用都到达并
    # 完成（主调用 200 条目 ≥2；不用 V2 标记反查——主调用 body 可超 journal
    # 64KB 上限落 None，见车道既有口径。流式期间主调用 200 不落账，故排队前
    # 采样恒为 0，改用绝对下限而非增量）。
    mains_after_drain = journal_main_200_counts(mock_llm)
    assert mains_after_drain >= 2, (
        "队列 drain 后主调用 200 条目不足 2（两轮未都真实完成）："
        f"before={mains_before_queue} after={mains_after_drain}"
    )
    # 占位轮 200 命中（标记允许出现在任意 user 消息里，含标题辅助调用引文）。
    entries = mock_llm.server.journal(path="/v1/chat/completions")
    slow_hits = [
        e
        for e in entries
        if int(e.get("response", {}).get("status") or 0) == 200
        and any(
            SLOW_MARKER in str((m or {}).get("content") or "")
            for m in ((e.get("body") or {}).get("messages") or [])
        )
    ]
    assert slow_hits, f"journal 无 {SLOW_MARKER} 的 200 命中（占位轮未真实打到 mock）"
    models = {str((e.get("body") or {}).get("model") or "") for e in entries}
    unexpected = models - {"e2e-mock-chat", ""}
    assert not unexpected, f"journal 出现意外 model: {unexpected}"
    print(
        f"[busy_queue] 收口完成：主调用 200 条目 before={mains_before_queue} "
        f"after={mains_after_drain}，journal 总条目={len(entries)}"
    )
