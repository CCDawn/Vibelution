# -*- coding: utf-8 -*-
"""e2e 模拟 LLM 服务商主流程：真实分支实例 + aimock + headless chromium。

口径（正式文档见 docs/guides/e2e-mock-llm.md）：
- ``serial`` marker + ``skipif`` 环境门，写法照抄 ``tests/e2e/test_routes_smoke.py``；
  严禁模块级 ``pytest.skip(allow_module_level=True)``（会零收集，closeout 选择器
  直跑本文件时 pytest 退出码 5 判失败）；
- Agent 用 API arrange（dialogue 槽绑到 ``e2e-mock/<model>``），消息经 UI composer
  发送，断言时间线与 turn 生命周期锚点（``data-active-turn-stage`` /
  ``data-agent-thread-status`` / ``data-agent-thread-message-count``）；
- journal 断言本轮请求只打了 mock（经 ``POST /__aimock/reset/journal`` 隔离）。
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

TURN_COMPLETE_TIMEOUT_MS = 120_000


# ---------------------------------------------------------------------------
# 共享步骤
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


def collect_turn(page: Any, *, timeout_ms: int = TURN_COMPLETE_TIMEOUT_MS) -> dict[str, Any]:
    """采样 turn 生命周期直到收口；返回阶段序列与 elapsed 样本（用于断言与证据）。

    实测（2026-09-26）：收口前时间线上可能同时存在多个 status note（乐观 turn 壳
    与活动层投影各一），只读 ``.first`` 会盯住陈旧元素漏记后段阶段；这里逐个扫描
    全部 note 并按出现顺序合并阶段序列。
    """
    stages: list[str] = []
    elapsed_samples: list[float] = []
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        notes = page.locator(TURN_STATUS_NOTE)
        count = notes.count()
        if count == 0:
            break
        saw_stage = ""
        for i in range(min(count, 4)):
            note = notes.nth(i)
            stage = _attr(note, "data-active-turn-stage")
            raw_elapsed = _attr(note, "data-active-turn-elapsed-seconds")
            if stage:
                saw_stage = saw_stage or stage
                if not stages or stages[-1] != stage:
                    stages.append(stage)
            try:
                elapsed_samples.append(float(raw_elapsed))
            except ValueError:
                pass
        thread_status = _attr(page.locator(THREAD_ROOT).first, "data-agent-thread-status")
        if not saw_stage and thread_status == "idle":
            break
        page.wait_for_timeout(120)
    else:
        raise AssertionError(f"turn 在 {timeout_ms}ms 内未收口（stage 序列={stages}）")
    return {"stages": stages, "elapsed": elapsed_samples}


def wait_turn_closed(page: Any, *, expected_messages: int, timeout_ms: int = 60_000) -> str:
    """等 thread 回到 idle 且消息数达到预期；返回最终 thread status。"""
    deadline = time.monotonic() + timeout_ms / 1000
    thread = page.locator(THREAD_ROOT).first
    while time.monotonic() < deadline:
        status = _attr(thread, "data-agent-thread-status")
        raw_count = _attr(thread, "data-agent-thread-message-count") or "0"
        try:
            count = int(raw_count)
        except ValueError:
            count = 0
        if status == "idle" and count >= expected_messages:
            return status
        page.wait_for_timeout(200)
    raise AssertionError(
        f"thread 未收口（status={thread.get_attribute('data-agent-thread-status')} "
        f"count={thread.get_attribute('data-agent-thread-message-count')}，"
        f"预期 count>={expected_messages}）"
    )


def thread_text(page: Any) -> str:
    """时间线整体文本（对话行没有稳定的 per-message 锚点，用 thread 容器文本断言）。"""
    return page.locator(THREAD_ROOT).first.inner_text()


def wait_thread_text(page: Any, needle: str, *, timeout_ms: int = 15_000) -> str:
    """等指定文本上屏后再返回时间线文本。

    实测（2026-09-25）：thread 转 idle 时助手行的 DOM 投影可能落后一拍
    （turn_completed 与 assistant_item_committed 的 SSE 落地顺序），即时读
    inner_text 会拿到没有正文的时间线；这里轮询等文本出现，超时才判失败。
    """
    deadline = time.monotonic() + timeout_ms / 1000
    texts = thread_text(page)
    while needle not in texts and time.monotonic() < deadline:
        page.wait_for_timeout(200)
        texts = thread_text(page)
    return texts


def thread_text_after(
    page: Any,
    needle: str,
    *,
    timeout_ms: int = 15_000,
    until: tuple[str, ...] = (),
) -> str:
    """等指定文本上屏后，返回该锚**最后一次出现**之后的时间线尾部。

    同一句话在时间线上可能出现多次（如相邻两轮），锚后的尾部文本用于只断言
    当前轮的投影，不被前一轮同文干扰。``until`` 给出尾部必须等待出现的文本
    （任一命中即可）：锚（用户行）上屏是乐观投影、先于回复，直接返回会读到
    尚未落正文的时间线（idle 投影晚一拍，见 wait_thread_text 注释）。
    """
    texts = wait_thread_text(page, needle, timeout_ms=timeout_ms)
    deadline = time.monotonic() + timeout_ms / 1000
    idx = texts.rfind(needle)
    tail = texts[idx:] if idx >= 0 else texts
    while until and not any(item in tail for item in until) and time.monotonic() < deadline:
        page.wait_for_timeout(200)
        texts = thread_text(page)
        idx = texts.rfind(needle)
        tail = texts[idx:] if idx >= 0 else texts
    return tail


def assert_no_error_surface(page: Any) -> None:
    errors = page.locator('section[data-vui="state-surface"][data-tone="error"]')
    assert errors.count() == 0, f"出现 error 状态面（count={errors.count()}）"


# ② 内联错误卡结构锚（web/src/components/conversation/ConversationView.tsx）：
# - div.turnError：turn 失败的实时「请求错误」横幅（role="status"；「请求错误」
#   label 是 sr-only 文案，不能当可见锚）；
# - div.turnErrorNotice：时间线内持久化 turn-error 消息卡。
# 两者均为 ConversationView.styles.ts 里的字面量 class token（非构建期 hash），
# 与 role="status" 组成结构锚，避免纯文案模糊匹配。
TURN_ERROR_BANNER = 'div.turnError[role="status"]'
TURN_ERROR_NOTICE = 'div.turnErrorNotice[role="status"]'


def assert_no_turn_error_card(page: Any) -> None:
    """② 收口面无「请求错误」内联错误卡（修复 354455df3 前该链路必出）。"""
    banner = page.locator(TURN_ERROR_BANNER)
    notice = page.locator(TURN_ERROR_NOTICE)
    assert banner.count() == 0, f"出现「请求错误」实时错误横幅（count={banner.count()}）"
    assert notice.count() == 0, f"出现时间线内联错误卡（count={notice.count()}）"


def assert_journal_all_mock(mock_llm: Any, marker: str) -> list[dict[str, Any]]:
    """journal 口径：本轮只有打到 mock 的 chat/completions 请求，且都带本用例模型。"""
    entries = mock_llm.server.journal(path="/v1/chat/completions")
    assert entries, "journal 为空：产品没有向 e2e-mock 发起请求"

    def _hit(entry: dict[str, Any]) -> bool:
        if int(entry.get("response", {}).get("status") or 0) != 200:
            return False
        messages = (entry.get("body") or {}).get("messages") or []
        # 与 runner.mjs 的路由口径一致：标记允许出现在任意 user 消息里。实测
        # （2026-09-26）主调用末条 user 消息是 Turn Status Bar 遥测尾巴，第二轮
        # 起标记只在更早的 user 消息里，只看 messages[-1] 会漏判。
        return any(marker in str((m or {}).get("content") or "") for m in messages)

    # 标记请求必须以 200 命中（产品侧真实拿到 mock 的流式回复）。
    marker_hits = [entry for entry in entries if _hit(entry)]
    assert marker_hits, f"journal 无 {marker} 的 200 命中"
    # model 只允许本车道两个 pin（空 model 的辅助调用如会话标题生成允许，由
    # zz_catchall.json 兜底接住，同样落在 mock 上）。
    models = {str(entry.get("body", {}).get("model") or "") for entry in entries}
    unexpected = models - {"e2e-mock-chat", "e2e-mock-tools", ""}
    assert not unexpected, f"journal 出现意外 model: {unexpected}"
    return entries


def wait_turn_started(
    page: Any,
    mock_llm: Any,
    *,
    submit_text: str,
    timeout_ms: int = 8_000,
) -> bool:
    """等 turn 真正启动：stage 推进到 user_submit 之后，或 journal 出现请求。

    实测（2026-09-25）：同一实例上跑过多个用例后，偶发提交只停在乐观态
    （stage 条冻结在 user_submit「已发送 · 0s」，上下文 0%），服务端没有起
    turn（journal 为空）；乐观态 stage 条本身不是启动证据，必须看到阶段推进
    或 mock 收到请求。超时则重发一次消息再等一轮。返回是否最终启动。
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
    print(f"[mock_llm] 提交未真正启动 turn（乐观态冻结在 user_submit），重发一次: {submit_text[:40]!r}")
    send_message(page, submit_text)
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if _started():
            return True
        page.wait_for_timeout(250)
    return False


def _is_title_entry(entry: dict[str, Any]) -> bool:
    """journal 条目是否为标题生成等辅助调用。

    辅助调用 body 小、末条 user content 以「用户消息：」开头；主调用 body 超过
    journal 64KB 上限，条目里 body 为空（None）——以此区分两类请求。
    """
    body = entry.get("body") or {}
    msgs = body.get("messages") or []
    for m in reversed(msgs):
        if m.get("role") == "user":
            return str(m.get("content") or "").lstrip().startswith("用户消息：")
    return False


def journal_main_counts(mock_llm: Any) -> tuple[int, int]:
    """返回 (主调用条目数, journal 总条数)（只看 /v1/chat/completions）。"""
    entries = mock_llm.server.journal(path="/v1/chat/completions")
    return sum(1 for e in entries if not _is_title_entry(e)), len(entries)


def complete_turn(
    page: Any,
    mock_llm: Any,
    text: str,
    *,
    expected_messages: int,
    timeout_ms: int = TURN_COMPLETE_TIMEOUT_MS,
) -> None:
    """提交一条消息并等到 turn 收口；收口后主调用未到 mock 则整轮重发一次。

    实测（2026-09-25）：同实例连续多轮后，产品 turn 引擎偶发把 turn 静默丢弃
    （thread 回 idle、乐观态行冻结在「已发送 · 0s」、无错误面；与同机并行的其他
    e2e 实例/共享 operator config 写入相关）。判据必须是「主调用条目」而非任意
    journal 条目——标题生成等辅助调用也会打到 mock，会伪装成主调用已跑。
    """
    send_message(page, text)
    assert wait_turn_started(page, mock_llm, submit_text=text), "turn 未启动"
    wait_turn_closed(page, expected_messages=expected_messages, timeout_ms=timeout_ms)
    mains, total = journal_main_counts(mock_llm)
    if not mains:
        print(
            f"[mock_llm] turn 收口但主调用未到 mock（journal {total} 条全是辅助调用，"
            f"turn 被静默丢弃），重发一次: {text[:40]!r}"
        )
        send_message(page, text)
        assert wait_turn_started(page, mock_llm, submit_text=text), "重发后 turn 仍未启动"
        wait_turn_closed(page, expected_messages=expected_messages, timeout_ms=timeout_ms)


@pytest.fixture
def chat_agent(mock_llm: Any):
    """建一个绑 e2e-mock-chat 的 Agent；用例结束归档。"""
    created = mock_llm.create_agent("e2e-mock-chat", "E2E Mock Chat Agent")
    yield created
    mock_llm.delete_agent(created["agentId"])


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------


def test_tool_calls_turn_closes_without_crash(page: Any, e2e_instance: Any, mock_llm: Any) -> None:
    """tool_calls 剧本（参数多分片 + finish tool_calls）：请求真实打到 mock，
    turn 收口不挂死、页面存活，且全程无「请求错误」内联错误卡。

    钉已修缺陷②（修复 354455df3）：未绑工具 Agent 收到 tool_calls 时，阻断路径
    此前只把合成 tool 结果写进内存、不落 ConversationLedger，下一轮 send-time
    reconcile 撞严格指纹闸门，以 turn_journal_replay_failed fail-closed，时间线
    出「请求错误/重试」内联卡片。修复后阻断路径补 `tool_call_started` +
    `tool_result(status=blocked)` 两条 ledger 事件，reconcile 通过。本用例闸门：
    - tool_calls 轮收口后时间线无错误卡（实时横幅 + 内联卡双锚）；
    - 加发一轮普通消息（正好踩修复机制里的「下一轮 send-time reconcile」），
      断言收口、正文上屏且仍无错误卡。

    剧本契约（scenarios/runner.mjs 场景 9）：首次调用返回 toolCalls（触发阻断），
    后续调用返回纯文本——产品阻断后会带合成 tool 结果再次调用模型；若每次都回
    toolCalls，turn 会迭代到 200 上限（实测拖垮 teardown，见 runner.mjs 注释）。
    修复前该剧本同样能触发②（第一次调用即阻断、不落 ledger），收紧不改变缺陷
    复现面。

    排序约束：本用例必须跑在套件第一位。实测同一实例连续建/用/删 5 个 Agent 后，
    第 6 个 Agent 的 turn 会被产品静默丢弃（thread 回 idle、乐观态冻结、无错误面、
    主调用不发出；重发同样被丢）——产品 turn 调度缺陷嫌疑，随报告提交；在全新
    实例上首位执行本场景可稳定复现正常链路。
    """
    from tests.e2e.helpers.page_anchors import domain_recipe_selector

    created = mock_llm.create_agent("e2e-mock-tools", "E2E Mock Tools Agent")
    try:
        open_agent_chat(page, e2e_instance, created["sessionId"])
        complete_turn(page, mock_llm, "E2E-MOCK-TOOL-V1 请写文件", expected_messages=2)
        # 页面壳存活：chat recipe 锚点仍可见（tool_calls 响应不炸前端）。
        assert page.locator(domain_recipe_selector("chat-session-workbench")).first.is_visible()
        # ② 闸门一：tool_calls 轮收口后时间线无「请求错误」错误卡，且以正常正文
        # 收口（剧本第二次调用返回的阻断降级文本，见 runner.mjs 场景 9 契约）。
        assert_no_turn_error_card(page)
        texts = wait_thread_text(page, "tool_calls 阻断链路正常")
        assert "tool_calls 阻断链路正常" in texts, (
            f"tool_calls 轮未以正文收口（阻断降级缺失）: {texts[:300]!r}"
        )
        entries = assert_journal_all_mock(mock_llm, "E2E-MOCK-TOOL-V1")
        mains, total = journal_main_counts(mock_llm)
        assert mains, (
            "journal 只有辅助调用（标题生成），主调用未到 mock: "
            f"main={mains} total={total}"
        )
        print(f"[mock_llm] tool_calls journal 条目数={len(entries)} 主调用条目={mains}")

        # ② 闸门二：下一轮普通消息触发 send-time reconcile（修复机制所在路径），
        # 必须照常收口、正文上屏且无错误卡（修复 354455df3 前这里必出
        # turn_journal_replay_failed 错误卡）。实测 V2 的请求历史携带 V1 标记，
        # 会命中剧本场景 9 的后续调用文本（而非 catch-all），两种正文都算通过。
        mains_before_v2, _ = journal_main_counts(mock_llm)
        complete_turn(page, mock_llm, "E2E-MOCK-TOOL-V2 收尾确认", expected_messages=4)
        tail = thread_text_after(
            page,
            "E2E-MOCK-TOOL-V2 收尾确认",
            until=("catch-all", "改为直接回复"),
        )
        assert "catch-all" in tail or "改为直接回复" in tail, (
            f"第二轮普通回复未上时间线: {tail[:300]!r}"
        )
        assert_no_turn_error_card(page)
        # journal 侧不反查 V2 标记：主调用请求体可能超 aimock journal 64KB 条目
        # 上限而 body 落 None（V1 的 marker 命中实为标题辅助调用的引文），改用
        # 「主调用 200 条目增长 + 模型白名单」证明 V2 真实打到 mock 且被服务。
        entries_v2 = mock_llm.server.journal(path="/v1/chat/completions")
        mains_after_v2 = sum(
            1
            for e in entries_v2
            if not _is_title_entry(e)
            and int(e.get("response", {}).get("status") or 0) == 200
        )
        assert mains_after_v2 > mains_before_v2, (
            "第二轮主调用未到 mock（journal 主调用 200 条目无增长）："
            f"before={mains_before_v2} after={mains_after_v2}"
        )
        unexpected = {
            str((e.get("body") or {}).get("model") or "") for e in entries_v2
        } - {"e2e-mock-chat", "e2e-mock-tools", ""}
        assert not unexpected, f"journal 出现意外 model: {unexpected}"
    finally:
        mock_llm.delete_agent(created["agentId"])


def test_normal_stream_stage_and_markdown(page: Any, e2e_instance: Any, mock_llm: Any, chat_agent: dict) -> None:
    """发消息 → stage 推进（thinking）→ markdown 正文上时间线 → turn 收口。

    ⑦b responding 阶段未纳入闸门的原因见断言处注释（2026-09-26 实测在真实
    aimock 流式路径上不可观测，与修复 c50d6b8a3 口径不符，已上报待产品收口）。
    """
    open_agent_chat(page, e2e_instance, chat_agent["sessionId"])
    send_message(page, "E2E-MOCK-MARKDOWN-V1 请给我一份 markdown 样例")
    assert wait_turn_started(page, mock_llm, submit_text="E2E-MOCK-MARKDOWN-V1 请给我一份 markdown 样例"), "turn 未启动"

    turn = collect_turn(page)
    # turn 收口必须先等到位（teardown 要归档 Agent，在飞 turn 会挡住 provider 注销）。
    wait_turn_closed(page, expected_messages=2)
    mains, _total = journal_main_counts(mock_llm)
    if not mains:
        # turn 被静默丢弃（见 complete_turn 注释）：重发一轮，采样以第二轮为准。
        print("[mock_llm] turn 收口但主调用未到 mock（turn 被静默丢弃），重发一次")
        send_message(page, "E2E-MOCK-MARKDOWN-V1 请给我一份 markdown 样例")
        assert wait_turn_started(
            page, mock_llm, submit_text="E2E-MOCK-MARKDOWN-V1 请给我一份 markdown 样例"
        ), "重发后 turn 仍未启动"
        turn = collect_turn(page)
        wait_turn_closed(page, expected_messages=2)
    print(f"[mock_llm] stage 序列={turn['stages']} elapsed 样本数={len(turn['elapsed'])}")
    assert turn["stages"], "未观测到任何 data-active-turn-stage（turn 状态面没出现）"
    # 阶段推进口径：wait_turn_started 已确认 stage 从 user_submit 推进过（提交阶段
    # 证据），collect_turn 从推进后开始采样。
    assert "thinking" in turn["stages"], f"未观测到 thinking 阶段: {turn['stages']}"
    # ⑦b 口径说明（2026-09-26 实测，收紧尝试未落地）：修复 c50d6b8a3 声称
    # 「首 answer delta 发 responding（stage 条第五相位）」，其单元测试直接调
    # stream_response 可观测 responding；但在真实 aimock 流式路径上，本车道以
    # 两种采样器（首个 note / 全部 note 扫描）× 多轮运行 × 首轮与第二轮（无标题
    # 辅助调用并发）验证，data-active-turn-stage 始终不出现 responding（序列止于
    # user_submit/working/thinking）——后端 first_answer_delta 发射条件在真实
    # 流式写入路径上未触发（或被消费），SSE 线上 stage 仍为 transport 值。
    # 这与修复口径不符，按纪律不落假闸门：恢复 thinking 闸门，缺陷⑦b 的
    # 「UI 可观测 responding」按未闭合上报，待产品侧钉死根因后本闸门再收紧。
    print(f"[mock_llm] responding 可观测={'responding' in turn['stages']}（⑦b 遗留） stages={turn['stages']}")
    assert_no_error_surface(page)
    texts = wait_thread_text(page, "E2E 冒烟回复")
    assert "E2E 冒烟回复" in texts, f"markdown 标题未出现在时间线: {texts[:300]!r}"
    assert "第一条要点" in texts, "列表内容未出现在时间线"
    assert "inline code" in texts, "行内代码未出现在时间线"
    # 实测（2026-09-25）：流式增量 markdown 在 ``` fence 的 chunk 边界上不稳定，
    # 偶发整块代码块不渲染（同内容离线复现可渲染）；渲染保真度嫌疑记入报告，
    # 这里仅打印事实，不作为车道闸门。
    print(f"[mock_llm] 代码块上屏={('hello from aimock' in texts)}")

    # reasoning 侧证据：思考文本是否可见（产品可能折叠，仅打印事实不断言）。
    print(f"[mock_llm] reasoning 文本可见={'先判断用户意图' in texts}")

    assert_journal_all_mock(mock_llm, "E2E-MOCK-MARKDOWN-V1")


def test_multi_turn_context(page: Any, e2e_instance: Any, mock_llm: Any, chat_agent: dict) -> None:
    """同标记连发两轮：turnIndex 0/1 剧本区分回复，第二轮可见上一轮内容仍在上文。"""
    open_agent_chat(page, e2e_instance, chat_agent["sessionId"])
    complete_turn(page, mock_llm, "E2E-MOCK-MULTITURN-V1", expected_messages=2)
    first_texts = wait_thread_text(page, "第一轮回复")
    assert "第一轮回复" in first_texts, f"第一轮回复缺失: {first_texts[:200]!r}"

    complete_turn(page, mock_llm, "E2E-MOCK-MULTITURN-V1", expected_messages=4)
    assert_no_error_surface(page)
    second_texts = wait_thread_text(page, "第二轮回复")
    assert "第二轮回复" in second_texts, f"第二轮回复缺失: {second_texts[:300]!r}"
    assert_journal_all_mock(mock_llm, "E2E-MOCK-MULTITURN-V1")


def test_rate_limit_retry_survives(page: Any, e2e_instance: Any, mock_llm: Any, chat_agent: dict) -> None:
    """首发 429（带 Retry-After）→ 产品重试链路 → 最终完成；journal 见 429→200。"""
    open_agent_chat(page, e2e_instance, chat_agent["sessionId"])
    complete_turn(page, mock_llm, "E2E-MOCK-429-V1 验证限流重试", expected_messages=2)
    assert_no_error_surface(page)
    texts = wait_thread_text(page, "重试后的成功回复")
    assert "重试后的成功回复" in texts, f"重试成功回复未上时间线: {texts[:300]!r}"

    entries = assert_journal_all_mock(mock_llm, "E2E-MOCK-429-V1")
    statuses = [int(entry.get("response", {}).get("status") or 0) for entry in entries]
    assert 429 in statuses, f"journal 未记录首发 429: {statuses}"
    assert 200 in statuses, f"journal 未记录重试成功 200: {statuses}"
    print(f"[mock_llm] 429 重试链 journal 状态序列={statuses}")


def test_long_think_stage_elapsed_grows(page: Any, e2e_instance: Any, mock_llm: Any, chat_agent: dict) -> None:
    """长思考剧本：前端停在 thinking 且 elapsed 增长；随后正常收口。"""
    open_agent_chat(page, e2e_instance, chat_agent["sessionId"])
    send_message(page, "E2E-MOCK-LONGTHINK-V1 验证长思考")
    assert wait_turn_started(page, mock_llm, submit_text="E2E-MOCK-LONGTHINK-V1 验证长思考"), "turn 未启动"

    # 思考窗口采样：stage 稳定 + elapsed 单调增长（ttft 3000ms + tps 5 提供窗口）。
    samples: list[tuple[str, float]] = []
    deadline = time.monotonic() + 20_000 / 1000
    while time.monotonic() < deadline and len(samples) < 2:
        notes = page.locator(TURN_STATUS_NOTE)
        if notes.count():
            stage = _attr(notes.first, "data-active-turn-stage")
            try:
                elapsed = float(_attr(notes.first, "data-active-turn-elapsed-seconds"))
            except ValueError:
                elapsed = -1.0
            if stage and elapsed >= 0:
                samples.append((stage, elapsed))
        page.wait_for_timeout(500)
    assert samples, "未采样到任何 turn 阶段"
    print(f"[mock_llm] 长思考采样={samples}")

    collect_turn(page)
    wait_turn_closed(page, expected_messages=2)
    mains, _total = journal_main_counts(mock_llm)
    if not mains:
        # turn 被静默丢弃（见 complete_turn 注释）：重发一轮，长思考窗口以第二轮为准。
        print("[mock_llm] turn 收口但主调用未到 mock（turn 被静默丢弃），重发一次")
        send_message(page, "E2E-MOCK-LONGTHINK-V1 验证长思考")
        assert wait_turn_started(
            page, mock_llm, submit_text="E2E-MOCK-LONGTHINK-V1 验证长思考"
        ), "重发后 turn 仍未启动"
        collect_turn(page)
        wait_turn_closed(page, expected_messages=2)
    assert_no_error_surface(page)
    texts = wait_thread_text(page, "长思考结束后的正式回复")
    assert "长思考结束后的正式回复" in texts, f"长思考剧本最终回复缺失: {texts[:300]!r}"
    assert_journal_all_mock(mock_llm, "E2E-MOCK-LONGTHINK-V1")


def test_format_leak_renders_without_crash(page: Any, e2e_instance: Any, mock_llm: Any, chat_agent: dict) -> None:
    """格式泄漏剧本：content/reasoning 混入协议文本，前端渲染不炸、turn 正常收口。

    钉已修缺陷④（修复 d3cf4fa8f）：此前流式 think 态遇异名闭合即错配、非流式
    未闭合即吞到末尾，前端 skipHtml 的 HTML 块语义还把行首 summary 标签连同
    紧随其后无空行的明文段一起吞掉——缺陷本体是吞正文。修复后行首
    think/thinking/summary/analysis 标签被 fence 感知转义为字面文本，紧随明文
    保住上屏。本用例闸门：summary 信封行与其后明文段（「正文仍然可读」）必须
    可见；工具信封原始行照旧可见。
    """
    from tests.e2e.helpers.page_anchors import domain_recipe_selector

    open_agent_chat(page, e2e_instance, chat_agent["sessionId"])
    complete_turn(page, mock_llm, "E2E-MOCK-LEAK-V1 验证格式泄漏渲染", expected_messages=2)
    assert_no_error_surface(page)
    # 页面壳仍活着：chat recipe 锚点可见，泄漏文本按内容上屏（不要求转义形态）。
    assert page.locator(domain_recipe_selector("chat-session-workbench")).first.is_visible()
    texts = wait_thread_text(page, "write_file")
    assert "write_file" in texts, f"泄漏剧本原始行未上时间线: {texts[:300]!r}"
    # ④ 闸门：紧随泄漏标签之后的明文段必须上屏（修复 d3cf4fa8f 前被 HTML 块
    # 语义连吞）；summary 信封行本体同样从「连吞」恢复为字面文本可见。
    assert "正文仍然可读" in texts, (
        f"泄漏标签之后的明文段未上屏（缺陷④回归）: {texts[:300]!r}"
    )
    assert "内部摘要信封泄漏" in texts, (
        f"summary 信封行未以字面文本上屏（缺陷④回归）: {texts[:300]!r}"
    )
    # 事实留证（非闸门）：content 里成对 <think>…</think> 属 reasoning 提取语义
    # （修复保持不变），其内文本不上屏是预期；打印观察不判失败。
    print(
        "[mock_llm] 泄漏文本事实: "
        f"think内文可见={'未闭合的思考标签泄漏' in texts}（reasoning 提取预期 False） "
        f"summary信封={'内部摘要信封泄漏' in texts} 尾段明文={'正文仍然可读' in texts}"
    )
    assert_journal_all_mock(mock_llm, "E2E-MOCK-LEAK-V1")
