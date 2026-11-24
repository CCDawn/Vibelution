#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""错误组保留区治理测试：去误标判定、保留上限、失败记录索引、整组搬移。

背景：旧实现按 error/failed/错误/失败 等关键词对工具输出做子串匹配，命中
错误字样的正常结果整组回灌保留区且无上限，长会话逐代压缩后保留区越垫越高
（实测一次压缩保留 117 组 ≈7 万 tokens，75 组为误标）。本文件锁定新契约：

1. 判定只认结构性证据（canonical_tool_result 元数据、产品失败信封、堆栈
   开头），正文出现错误字样的成功结果不再判错；
2. 错误组只保留最近 MAX_PRESERVED_ERROR_GROUPS 组原文，真失败/超时优先，
   其次降级；其余整组并入摘要输入；
3. 摘要末尾追加有界的失败记录索引（行数/字符双上限，超限有概括句）；
4. call+result 整组搬移，七项保留重点契约不受影响。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from core.orchestration import turn_compression
from core.orchestration.agent_modes import AgentMode
from core.orchestration.turn_compression import compress_turn_messages
from core.infrastructure.runtime_input import build_runtime_notice_message
from tools.compression_summary_retention import (
    compose_failure_record_index,
    FAILURE_INDEX_HEADER,
    FAILURE_INDEX_OVERFLOW_NOTICE,
    MAX_FAILURE_INDEX_CHARS,
    MAX_FAILURE_INDEX_LINES,
)
from tools.token_manager import (
    EnhancedTokenCompressor,
    MAX_PRESERVED_ERROR_GROUPS,
    _ERROR_GROUP_DEGRADED,
    _ERROR_GROUP_FAILED,
    _ERROR_GROUP_NONE,
    _ERROR_GROUP_TIMEOUT,
    _failure_record_entries,
    _metadata_error_status,
    _select_preserved_error_groups,
    _tool_group_error_class,
)


# ---------------------------------------------------------------------------
# 构造辅助
# ---------------------------------------------------------------------------


def _call(name: str, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": call_id}])


def _result(call_id: str, content: str, **kwargs) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call_id, **kwargs)


def _canonical_failed() -> dict:
    return {
        "canonical_tool_result": SimpleNamespace(status="failed", is_error=True),
    }


def _failure_pair(index: int) -> list:
    """结构化失败组：canonical_tool_result 标记失败，正文带独特标记。"""
    call_id = f"call-fail-{index}"
    return [
        _call("run_tests", call_id),
        _result(
            call_id,
            f"[错误] assertion failed marker-{index}",
            additional_kwargs=_canonical_failed(),
        ),
    ]


def _misclassified_pair(index: int) -> list:
    """旧规则误标组：成功结果正文提到 error/错误 字样。"""
    call_id = f"call-ok-{index}"
    content = (
        f'{{"ok": true, "status": "done", "marker": "hit-{index}", '
        f'"summary": "checked error handling docs, 0 errors found"}}'
    )
    return [_call("web_search_tool", call_id), _result(call_id, content)]


def _flat(groups: list) -> list:
    return [message for group in groups for message in group]


def _tool_messages(messages: list) -> list:
    return [
        message for message in messages
        if getattr(message, "tool_call_id", None)
    ]


# ---------------------------------------------------------------------------
# (a) 去误标：正文错误字样不再判错
# ---------------------------------------------------------------------------


def test_successful_result_mentioning_error_is_not_an_error_group():
    group = _misclassified_pair(0)
    assert _tool_group_error_class(group) == _ERROR_GROUP_NONE

    plain_text_group = [
        _call("read_doc", "call-ok-plain"),
        _result("call-ok-plain", "README mentions error retry policies in section 3。"),
    ]
    assert _tool_group_error_class(plain_text_group) == _ERROR_GROUP_NONE

    chinese_group = [
        _call("web_search_tool", "call-ok-cn"),
        _result("call-ok-cn", '检索完成：找到 12 条关于「错误处理最佳实践」的结果。'),
    ]
    assert _tool_group_error_class(chinese_group) == _ERROR_GROUP_NONE


def test_keyword_error_result_is_summarized_not_retained():
    messages = [
        SystemMessage(content="stable system"),
        *_flat(_misclassified_pair(index) for index in range(6)),
    ]
    messages.extend(AIMessage(content=f"step {i} " + ("x" * 400)) for i in range(6))

    compressor = EnhancedTokenCompressor(token_budget=4_000)
    compressed, _result_meta = compressor.compress(
        messages,
        max_chars=600,
        keep_count=0,
        preserve_errors=True,
        use_llm_summary=False,
    )

    assert _tool_messages(compressed) == []
    call_ids = {getattr(m, "tool_call_id", "") for m in compressed}
    assert all(f"call-ok-{i}" not in call_ids for i in range(6))


# ---------------------------------------------------------------------------
# (b) 结构性证据判错：状态元数据与产品失败信封
# ---------------------------------------------------------------------------


def test_canonical_metadata_failure_classifies_error_group():
    group = _failure_pair(0)
    assert _tool_group_error_class(group) == _ERROR_GROUP_FAILED


def test_metadata_status_mapping_message_classifies_error_group():
    message = {
        "role": "tool",
        "content": "aborted",
        "tool_call_id": "call-meta",
        "metadata": {"kind": "interrupted_tool_result", "status": "aborted"},
    }
    # 中止合成结果不是失败记录
    assert _metadata_error_status(message) == _ERROR_GROUP_NONE
    failed = dict(message)
    failed["metadata"] = {"status": "failed"}
    assert _metadata_error_status(failed) == _ERROR_GROUP_FAILED
    timeout = dict(message)
    timeout["metadata"] = {"status": "timed_out"}
    assert _metadata_error_status(timeout) == _ERROR_GROUP_TIMEOUT


def test_content_failure_envelopes_classify_error_groups():
    cases = [
        ("[超时] 命令执行超过 120 秒被终止", _ERROR_GROUP_TIMEOUT),
        ("[EXEC FAILURE | Exit Code: 2] compile errors", _ERROR_GROUP_FAILED),
        ("[执行失败] process exited with code 1", _ERROR_GROUP_FAILED),
        ("Traceback (most recent call last):\n  File ...", _ERROR_GROUP_FAILED),
        ('{"ok": false, "error": "upstream 502"}', _ERROR_GROUP_FAILED),
    ]
    for content, expected in cases:
        group = [_call("run_command", "call-env"), _result("call-env", content)]
        assert _tool_group_error_class(group) == expected, content


def test_degraded_envelope_classifies_degraded_group():
    group = [
        _call("run_command", "call-deg"),
        _result("call-deg", "[跨平台警告] 使用了 POSIX 专用参数，结果可能不完整"),
    ]
    assert _tool_group_error_class(group) == _ERROR_GROUP_DEGRADED


# ---------------------------------------------------------------------------
# (c) 保留上限：最近 8 组真失败，其余进摘要输入
# ---------------------------------------------------------------------------


def test_error_retention_capped_to_latest_eight_true_failures(monkeypatch):
    groups = (
        [_failure_pair(i) for i in range(30)]
        + [_misclassified_pair(i) for i in range(60)]
    )
    messages = [SystemMessage(content="stable system"), *_flat(groups)]
    messages.extend(AIMessage(content=f"step {i} " + ("x" * 400)) for i in range(3))

    compressor = EnhancedTokenCompressor(token_budget=100_000)
    captured: dict = {}

    def _fake_generate_summary(summarize_msgs, max_chars, **kwargs):
        captured["messages"] = list(summarize_msgs)
        return compressor._rule_based_summary(summarize_msgs, max_chars)

    monkeypatch.setattr(compressor, "_generate_summary", _fake_generate_summary)
    output = compressor.compress(
        messages,
        max_chars=3_000,
        keep_count=0,
        preserve_errors=True,
        use_llm_summary=False,
    )
    compressed = output.messages
    meta = output.result

    retained_ids = {
        getattr(m, "tool_call_id", "") for m in _tool_messages(compressed)
    }
    # 只保留最近 8 组真失败，误标组一组都不进保留区
    assert len(retained_ids) == MAX_PRESERVED_ERROR_GROUPS
    expected_latest = {f"call-fail-{i}" for i in range(22, 30)}
    assert retained_ids == expected_latest
    # 其余真失败与全部误标组进入摘要输入（_generate_summary 收到的消息集）
    summarized_ids = {
        getattr(m, "tool_call_id", "") for m in _tool_messages(captured["messages"])
    }
    for i in range(22):
        assert f"call-fail-{i}" in summarized_ids
    for i in range(60):
        assert f"call-ok-{i}" in summarized_ids
    # 边界对齐：CompressionOutput.summarized_messages 覆盖全部被折叠消息
    output_ids = {
        getattr(m, "tool_call_id", "") for m in _tool_messages(output.summarized_messages)
    }
    for i in range(22):
        assert f"call-fail-{i}" in output_ids
    for i in range(60):
        assert f"call-ok-{i}" in output_ids


def test_true_failures_rank_before_newer_degraded():
    degraded_group = [
        _call("run_command", "call-deg-0"),
        _result("call-deg-0", "[跨平台警告] platform specific flags"),
    ]
    groups = [_failure_pair(0), degraded_group, _failure_pair(1)]
    retained, dropped = _select_preserved_error_groups(
        [(group, _tool_group_error_class(group)) for group in groups],
        2,
    )
    # 两个真失败组都入选（优先于更新的降级组），保留组按消息原序放回
    assert [
        getattr(_tool_messages(group)[0], "tool_call_id") for group in retained
    ] == ["call-fail-0", "call-fail-1"]
    assert [
        getattr(_tool_messages(group)[0], "tool_call_id") for group in dropped
    ] == ["call-deg-0"]


def test_select_preserved_error_groups_recency_within_class():
    groups = [_failure_pair(i) for i in range(12)]
    classified = [(group, _ERROR_GROUP_FAILED) for group in groups]
    retained, dropped = _select_preserved_error_groups(classified, 8)
    retained_ids = [
        getattr(m, "tool_call_id", "") for group in retained for m in _tool_messages(group)
    ]
    assert retained_ids == [f"call-fail-{i}" for i in range(4, 12)]
    dropped_ids = [
        getattr(m, "tool_call_id", "") for group in dropped for m in _tool_messages(group)
    ]
    assert dropped_ids == [f"call-fail-{i}" for i in range(3, -1, -1)]


def test_select_preserved_error_groups_zero_and_huge_limits():
    groups = [_failure_pair(i) for i in range(4)]
    classified = [(group, _ERROR_GROUP_FAILED) for group in groups]
    retained, dropped = _select_preserved_error_groups(classified, 0)
    assert retained == []
    assert len(dropped) == 4
    retained, dropped = _select_preserved_error_groups(classified, 10_000)
    assert len(retained) == 4
    assert dropped == []


# ---------------------------------------------------------------------------
# (d) 失败记录索引：进摘要、有界、超限概括
# ---------------------------------------------------------------------------


def test_failure_record_index_unit_caps_and_overflow():
    assert compose_failure_record_index([]) == ""

    entries = [("web_search_tool", "failed", f"upstream 502 attempt-{i}") for i in range(60)]
    index = compose_failure_record_index(entries)
    lines = index.splitlines()
    assert lines[0] == FAILURE_INDEX_HEADER
    assert len(lines) <= MAX_FAILURE_INDEX_LINES
    assert len(index) <= MAX_FAILURE_INDEX_CHARS
    assert FAILURE_INDEX_OVERFLOW_NOTICE in index

    small = compose_failure_record_index(
        [("run_tests", "failed", "boom") for _ in range(3)], max_lines=10, max_chars=4000,
    )
    small_lines = small.splitlines()
    assert len(small_lines) == 4  # 标题 + 3 条，无溢出提示
    assert FAILURE_INDEX_OVERFLOW_NOTICE not in small

    char_bounded = compose_failure_record_index(
        [("run_tests", "failed", "x" * 200) for _ in range(100)],
        max_lines=1000,
        max_chars=600,
    )
    assert len(char_bounded) <= 600
    assert FAILURE_INDEX_OVERFLOW_NOTICE in char_bounded


def test_failure_index_entries_format():
    group = _failure_pair(7)
    entries = _failure_record_entries([group])
    assert entries == [
        ("run_tests", "failed", "[错误] assertion failed marker-7"),
    ]


def test_dropped_error_groups_produce_bounded_index_in_summary(monkeypatch):
    groups = [_failure_pair(i) for i in range(56)]
    messages = [SystemMessage(content="stable system"), *_flat(groups)]
    messages.extend(AIMessage(content=f"step {i} " + ("x" * 400)) for i in range(3))

    compressor = EnhancedTokenCompressor(token_budget=100_000)
    compressed, meta = compressor.compress(
        messages,
        max_chars=6_000,
        keep_count=0,
        preserve_errors=True,
        use_llm_summary=False,
    )

    assert FAILURE_INDEX_HEADER in meta.summary
    summary_lines = meta.summary.splitlines()
    header_index = summary_lines.index(FAILURE_INDEX_HEADER)
    # 56 组只留 8 组 → 48 条落选 > 40 行上限，必有溢出概括句
    assert FAILURE_INDEX_OVERFLOW_NOTICE in meta.summary
    index_lines = []
    for line in summary_lines[header_index + 1:]:
        if not line.startswith("- "):
            break
        index_lines.append(line)
    assert len(index_lines) + 2 <= MAX_FAILURE_INDEX_LINES
    assert len(meta.summary) <= 6_000
    # 索引行带工具名与状态
    assert any("run_tests" in line and "failed" in line for line in index_lines)


# ---------------------------------------------------------------------------
# (e) 整组搬移：不产生孤儿调用/结果
# ---------------------------------------------------------------------------


def test_groups_move_whole_no_orphan_call_or_result():
    groups = [_failure_pair(i) for i in range(12)]
    groups.append([
        _call("web_search_tool", "call-tail"),
        _result("call-tail", '正常结果 {"ok": true, "status": "done"}'),
    ])
    messages = [SystemMessage(content="stable system"), *_flat(groups)]
    messages.extend(AIMessage(content=f"step {i} " + ("x" * 400)) for i in range(3))

    compressor = EnhancedTokenCompressor(token_budget=100_000)
    compressed, _meta = compressor.compress(
        messages,
        max_chars=3_000,
        keep_count=0,
        preserve_errors=True,
        use_llm_summary=False,
    )

    snapshot = turn_compression._tool_call_pairing_snapshot(compressed)
    assert snapshot["orphanResultCount"] == 0
    assert snapshot["unresolvedCallIds"] == []
    compressed_ids = {
        getattr(m, "tool_call_id", "") for m in _tool_messages(compressed)
    }
    compressed_call_ids = set()
    for message in compressed:
        for call in getattr(message, "tool_calls", None) or []:
            compressed_call_ids.add(str(call.get("id") or ""))
    # 落单检查：出现的 call 与 result 一一成对
    assert compressed_call_ids == compressed_ids
    # 保留的是最新 8 组真失败；落选组整组消失（call 与 result 同时不在）
    assert compressed_call_ids == {f"call-fail-{i}" for i in range(4, 12)}
    for message in compressed:
        call_id = getattr(message, "tool_call_id", None)
        if call_id:
            previous = compressed[compressed.index(message) - 1]
            assert any(
                str(call.get("id") or "") == call_id
                for call in getattr(previous, "tool_calls", None) or []
            ), call_id


# ---------------------------------------------------------------------------
# (f) 七项保留重点契约在压缩后仍然在
# ---------------------------------------------------------------------------


class _FakeUi:
    def __init__(self) -> None:
        self.logs: list = []
        self.events: list = []

    def add_log(self, message: str, level: str = "INFO") -> None:
        self.logs.append((level, message))

    def note_context_compression_event(self, **kwargs) -> None:
        self.events.append(kwargs)


class _FakePromptManager:
    def __init__(self) -> None:
        self.updates: list = []

    def update_state_memory(self, text: str) -> None:
        self.updates.append(text)


class _FakeStrategy:
    def determine_level_with_iteration(self, *args):
        from tools.compression_strategy import CompressionLevel

        return CompressionLevel.STANDARD

    def get_config(self, level, current_tokens, budget):
        from tools.compression_strategy import CompressionConfig

        return CompressionConfig(level=level, summary_max_chars=3_000, keep_ai_messages=2)


def _feature_config():
    return SimpleNamespace(
        mental_model=SimpleNamespace(enabled=False),
        context_compression=SimpleNamespace(
            enabled=True,
            max_compressions_per_session=3,
            effectiveness_threshold=0.0,
        ),
        pet=SimpleNamespace(enabled=False),
        memory=SimpleNamespace(
            semantic_memory_enabled=False,
            llm_extraction_enabled=False,
            llm_summary_enabled=False,
        ),
        supervised_evolution=SimpleNamespace(enabled=False, mental_model_enabled=False),
        agent=SimpleNamespace(
            modes=SimpleNamespace(
                supervised_evolution_enabled=False,
                self_evolution_enabled=False,
            )
        ),
    )


def _estimate(messages) -> int:
    return sum(len(str(getattr(item, "content", "") or "")) for item in messages)


def test_seven_retention_focus_survive_capped_error_compression():
    groups = [_failure_pair(i) for i in range(12)]
    groups.extend(_misclassified_pair(i) for i in range(4))
    messages: list = [
        SystemMessage(content="stable system"),
        HumanMessage(content="记住 scope=challenge-sci-001，写回合同 writeback=team-7"),
        build_runtime_notice_message("历史摘要:\n上一代摘要 compressionGeneration=0 锚点"),
        *_flat(groups),
        AIMessage(
            content="",
            tool_calls=[{"name": "web_search_tool", "args": {}, "id": "call-open"}],
        ),
        # 尾部当前请求：让前面的记忆消息成为可压缩历史（进保留事实块）
        HumanMessage(content="继续推进当前阶段"),
    ]

    events: list = []
    ui = _FakeUi()
    prompt_manager = _FakePromptManager()

    def recorder(scene, action, *, message="", outcome="observed", fields=None, **kwargs):
        events.append({"scene": scene, "action": action, "outcome": outcome, "fields": fields or {}})

    result = compress_turn_messages(
        messages=messages,
        iteration=4,
        reason="test",
        token_compressor=EnhancedTokenCompressor(token_budget=100_000),
        config=_feature_config(),
        effective_max_token_limit=241_664,
        threshold_tokens=228_664,
        runtime_agent_binding={"agentId": "agent-x", "directSessionId": "s1"},
        project_root="",
        mode=AgentMode.CHAT,
        compression_strategy=_FakeStrategy(),
        prompt_manager=prompt_manager,
        estimate_tokens_fn=_estimate,
        get_ui_fn=lambda: ui,
        get_state_manager_fn=lambda: SimpleNamespace(set_state=lambda *a, **k: None),
        scene_recorder_fn=recorder,
        context_input_hard_limit=241_664,
        post_compression_target_tokens=161_109,
        retention_contract={
            "agentId": "agent-x",
            "sessionId": "session-x",
            "researchProjectId": "challenge-sci-001",
            "roleKey": "challenge_cup_search",
        },
    )
    compressed, should_break, _applied, _count, _last_iter, _stop_reason = result

    # 保留契约闸门不被触发：未解决调用/孤儿结果没有新增
    assert should_break is False
    assert not any(
        event["action"] == "agent.context_budget_exhausted" for event in events
    )
    after = turn_compression._tool_call_pairing_snapshot(compressed)
    assert after["orphanResultCount"] == 0
    # 合同摘要字段持久化（compression_generation / unresolved_tool_call 等七项
    # 保留重点的机器载体）
    assert prompt_manager.updates, "summary must be persisted via the prompt manager"
    persisted = prompt_manager.updates[-1]
    for marker in (
        "challenge-sci-001",
        "sessionId=s1",
        "compressionGeneration=",
        "unresolvedToolCallIds=call-open",
        "iteration=4",
    ):
        assert marker in persisted, marker
    # 用户明示记忆（task_contract / writeback_contract 的事实来源）仍在摘要里
    summary_notices = [
        message for message in compressed
        if "历史摘要" in str(getattr(message, "content", ""))
    ]
    assert summary_notices
    assert "scope=challenge-sci-001" in str(summary_notices[-1].content)
    assert "writeback=team-7" in str(summary_notices[-1].content)
    # 上一代摘要被折叠（compression_generation 链不断）
    assert "compressionGeneration=0" in str(summary_notices[-1].content)
    # 超上限的错误组给出失败记录索引
    assert FAILURE_INDEX_HEADER in str(summary_notices[-1].content)


# ---------------------------------------------------------------------------
# (g) 上限边界：0 与很大
# ---------------------------------------------------------------------------


def test_zero_limit_retains_no_error_groups(monkeypatch):
    monkeypatch.setattr("tools.token_manager.MAX_PRESERVED_ERROR_GROUPS", 0)
    groups = [_failure_pair(i) for i in range(5)]
    messages = [SystemMessage(content="stable system"), *_flat(groups)]
    messages.extend(AIMessage(content=f"step {i} " + ("x" * 400)) for i in range(3))

    compressor = EnhancedTokenCompressor(token_budget=100_000)
    compressed, meta = compressor.compress(
        messages,
        max_chars=3_000,
        keep_count=0,
        preserve_errors=True,
        use_llm_summary=False,
    )

    assert _tool_messages(compressed) == []
    assert FAILURE_INDEX_HEADER in meta.summary


def test_huge_limit_retains_all_error_groups_without_index(monkeypatch):
    monkeypatch.setattr("tools.token_manager.MAX_PRESERVED_ERROR_GROUPS", 500)
    groups = [_failure_pair(i) for i in range(5)]
    messages = [SystemMessage(content="stable system"), *_flat(groups)]
    messages.extend(AIMessage(content=f"step {i} " + ("x" * 400)) for i in range(3))

    compressor = EnhancedTokenCompressor(token_budget=200_000)
    compressed, meta = compressor.compress(
        messages,
        max_chars=3_000,
        keep_count=0,
        preserve_errors=True,
        use_llm_summary=False,
    )

    retained_ids = {
        getattr(m, "tool_call_id", "") for m in _tool_messages(compressed)
    }
    assert retained_ids == {f"call-fail-{i}" for i in range(5)}
    assert FAILURE_INDEX_HEADER not in meta.summary


def test_preserve_errors_false_keeps_old_behavior_without_index():
    groups = [_failure_pair(i) for i in range(3)]
    messages = [SystemMessage(content="stable system"), *_flat(groups)]
    messages.extend(AIMessage(content=f"step {i} " + ("x" * 400)) for i in range(3))

    compressor = EnhancedTokenCompressor(token_budget=100_000)
    compressed, meta = compressor.compress(
        messages,
        max_chars=3_000,
        keep_count=0,
        preserve_errors=False,
        use_llm_summary=False,
    )
    assert _tool_messages(compressed) == []
    assert FAILURE_INDEX_HEADER not in meta.summary
