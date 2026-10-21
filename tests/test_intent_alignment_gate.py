#!/usr/bin/env python3
"""worker 意图对齐 gate 测试（设计 §8.2 T5，§8.1 P0 验收 1/4/5 的 gate 侧）。

覆盖：无工件零行为差异（prompt 构造输入不变）、有工件+clarifying 时 packet
注入与章节渲染、gate 异常 fail-open 直通（store 损坏 / PromptManager 不可得）、
分叉信号与清晰信号的 gate 段透传。fixture 隔离复用
tests/test_intent_alignment_artifact.py 的 isolated 模式（monkeypatch 路径
函数 + 单例复位）。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from core.orchestration import intent_alignment
from core.orchestration.intent_alignment import get_intent_alignment_store
from core.prompt_manager import PromptManager, to_string
from core.web.services.session import worker

SESSION_ID = "sess_gate"


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """monkeypatch 路径函数到 tmp_path + 单例复位（复用 artifact 测试 fixture 模式）。"""
    intent_dir = tmp_path / "workspace" / "memory" / "intent_alignment"

    def fake_store_path(session_id: str) -> str:
        return str(intent_dir / f"{session_id}.json")

    monkeypatch.setattr(intent_alignment, "_intent_alignment_store_path", fake_store_path)
    intent_alignment.reset_intent_alignment_store()
    yield intent_alignment
    intent_alignment.reset_intent_alignment_store()


@pytest.fixture
def runtime_agent():
    """带真实 PromptManager 的 runtime agent 替身（worker 取法：getattr 链）。"""
    return SimpleNamespace(prompt_manager=PromptManager())


def _origin() -> dict:
    return {
        "mode": "chat",
        "roomId": "",
        "sourceTextDigest": "sha256:deadbeef",
        "createdAt": "2026-10-21T00:00:00+00:00",
    }


def _turn(turn_id: str = "turn_1") -> dict:
    return {"sessionId": SESSION_ID, "turnId": turn_id, "messageId": "msg_1"}


def _seed_clarifying_artifact(store) -> str:
    """落四要素初稿（v1）+ 登记一个 asked 问题，返回台账 question id。"""
    store.open_or_load(SESSION_ID, origin=_origin())
    store.record_structured(
        SESSION_ID,
        goal="搭建命令行待办工具",
        boundaries=["不做图形界面"],
        constraints=["必须使用 Python 标准库"],
        acceptance=["能添加和列出待办"],
        assumptions=[],
    )
    return store.record_question_asked(
        SESSION_ID,
        question="数据要落盘还是只留内存？",
        why_it_matters="决定是否引入文件存储层",
        applies_to="constraints",
        turn_ref=_turn("turn_2"),
    )


# ── P0 验收 1：无工件 gate 零行为差异 ────────────────────────────────────


def test_gate_without_artifact_keeps_prompt_input_unchanged(runtime_agent):
    """无工件：不注入 packet，章节维持空态，prompt 构造输入零差异。"""
    pm = runtime_agent.prompt_manager
    before = to_string(pm.build(include=["INTENT_ALIGNMENT"]))
    assert pm.get_intent_alignment_packet() is None

    worker._inject_intent_alignment_packet(SESSION_ID, "请帮我创建一个待办清单", runtime_agent)

    assert pm.get_intent_alignment_packet() is None
    assert to_string(pm.build(include=["INTENT_ALIGNMENT"])) == before


# ── P0 验收 4（gate 侧）：clarifying 工件 packet 注入 + 章节渲染 ─────────


def test_gate_injects_clarifying_packet_and_section_renders(isolated_store, runtime_agent):
    """有工件且台账有 asked 问题：注入组装结果，章节渲染 clarifying 内容。"""
    qid = _seed_clarifying_artifact(get_intent_alignment_store())
    pm = runtime_agent.prompt_manager

    worker._inject_intent_alignment_packet(SESSION_ID, "看看现在的项目结构再决定", runtime_agent)

    packet = pm.get_intent_alignment_packet()
    assert isinstance(packet, dict), "worker 层应把组装结果注入 PromptManager"
    assert packet["schemaVersion"] == intent_alignment._PACKET_SCHEMA_VERSION
    assert packet["status"] == "clarifying"
    assert [q["id"] for q in packet["openQuestions"]] == [qid]
    assert packet["openQuestions"][0]["question"] == "数据要落盘还是只留内存？"
    # 章节渲染（包含性断言，模式同 tests/test_prompt_manager.py B1/B2）。
    content = to_string(pm.build(include=["INTENT_ALIGNMENT"]))
    assert "## 意图对齐" in content
    assert "待澄清问题" in content
    assert "数据要落盘还是只留内存？" in content


# ── P0 验收 5：gate 异常 fail-open 直通 ──────────────────────────────────


def test_gate_fail_open_when_store_raises(isolated_store, runtime_agent, caplog):
    """store 损坏：只记一条 warning，直通原链路且不注入 packet。"""
    store = get_intent_alignment_store()

    def broken_get_current(session_id: str):
        raise RuntimeError("corrupt store")

    store.get_current = broken_get_current
    pm = runtime_agent.prompt_manager

    with caplog.at_level(logging.WARNING, logger="core.web.services.session.worker"):
        worker._inject_intent_alignment_packet(SESSION_ID, "请帮我创建一个待办清单", runtime_agent)

    assert pm.get_intent_alignment_packet() is None
    warnings = [r for r in caplog.records if "Intent alignment gate failed open" in r.message]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    assert "RuntimeError" in warnings[0].getMessage()


def test_gate_fail_open_when_prompt_manager_unavailable(isolated_store, caplog):
    """PromptManager 不可得：同样 fail-open，只记 warning，不中断。"""
    _seed_clarifying_artifact(get_intent_alignment_store())
    bare_agent = SimpleNamespace()  # 无 prompt_manager 属性

    with caplog.at_level(logging.WARNING, logger="core.web.services.session.worker"):
        worker._inject_intent_alignment_packet(SESSION_ID, "请帮我创建一个待办清单", bare_agent)

    warnings = [r for r in caplog.records if "Intent alignment gate failed open" in r.message]
    assert len(warnings) == 1


# ── gate 段信号透传：分叉 / 清晰 ─────────────────────────────────────────


def test_gate_passes_fork_signal_through(isolated_store, runtime_agent):
    """分叉信号（多义指代+互斥约束）命中 → gate 段 action=ask，证据透传。"""
    _seed_clarifying_artifact(get_intent_alignment_store())
    pm = runtime_agent.prompt_manager

    worker._inject_intent_alignment_packet(SESSION_ID, "这个要同步还是异步？", runtime_agent)

    packet = pm.get_intent_alignment_packet()
    gate = packet["gate"]
    assert gate["action"] == "ask"
    assert gate["decidedBy"] == "rules"
    assert gate["confidence"] == pytest.approx(0.8)
    assert "多义指代" in gate["reason"]
    assert "互斥约束" in gate["reason"]


def test_gate_passes_clear_signal_through(isolated_store, runtime_agent):
    """清晰祈使句 → gate 段 action=proceed（仅直通倾向提示，判定权在 agent）。"""
    _seed_clarifying_artifact(get_intent_alignment_store())
    pm = runtime_agent.prompt_manager

    worker._inject_intent_alignment_packet(SESSION_ID, "请帮我创建一个待办清单", runtime_agent)

    gate = pm.get_intent_alignment_packet()["gate"]
    assert gate["action"] == "proceed"
    assert gate["decidedBy"] == "rules"
    assert gate["confidence"] == pytest.approx(0.7)
    assert "直通倾向提示" in gate["reason"]
