#!/usr/bin/env python3
"""意图对齐判定段测试（设计文档 §9 表 B B9，T2 规则预筛 / 回执解析 / packet 组装）。

覆盖三类输入判定解析（clear 信号识别 / 分叉信号命中交自判 / 回执按三元组映射
与落账无结构化变更）、packet 组装映射、保守不误标（规则不确定时 openQuestions
保留）与 dismiss 不动 store。
fixture 隔离复用 tests/test_intent_alignment_artifact.py 的 isolated 模式
（monkeypatch 路径函数 + 单例复位）。
"""

from __future__ import annotations

import json

import pytest

from core.orchestration import intent_alignment
from core.orchestration.intent_alignment import (
    apply_reply,
    assemble_packet,
    detect_clear_imperative_signal,
    detect_fork_signals,
    get_intent_alignment_store,
    parse_intent_alignment_reply,
    run_rule_prefilter,
)

SESSION_ID = "sess_judge"
CARD_ID = "card_judge_1"


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


def _origin() -> dict:
    return {
        "mode": "chat",
        "roomId": "",
        "sourceTextDigest": "sha256:deadbeef",
        "createdAt": "2026-10-21T00:00:00+00:00",
    }


def _turn(turn_id: str = "turn_1") -> dict:
    return {"sessionId": SESSION_ID, "turnId": turn_id, "messageId": "msg_1"}


def _seed_draft(store) -> None:
    store.open_or_load(SESSION_ID, origin=_origin())
    store.record_structured(
        SESSION_ID,
        goal="搭建命令行待办工具",
        boundaries=["不做图形界面"],
        constraints=["必须使用 Python 标准库"],
        acceptance=["能添加和列出待办"],
        assumptions=[],
    )


def _seed_asked(store) -> str:
    """登记 q1（askedInCard=CARD_ID）并返回台账 id。"""
    return store.record_question_asked(
        SESSION_ID,
        question="数据要落盘还是只留内存？",
        why_it_matters="决定是否引入文件存储层",
        applies_to="constraints",
        turn_ref=_turn("turn_2"),
        asked_in_card=CARD_ID,
    )


def _card_payload() -> dict:
    return {
        "schemaVersion": 1,
        "kind": "intent_alignment_card",
        "cardId": CARD_ID,
        "revision": 1,
        "intentSummary": "为待办工具澄清持久化方案",
        "questions": [
            {
                "questionId": "q1",
                "prompt": "数据要落盘还是只留内存？",
                "inputMode": "single_choice",
                "options": [
                    {"optionId": "o_disk", "label": "落盘"},
                    {"optionId": "o_mem", "label": "只留内存"},
                ],
                "required": True,
            },
            {
                "questionId": "q2",
                "prompt": "还有其他约束吗？",
                "inputMode": "free_text",
                "required": False,
            },
        ],
    }


def _reply(
    action: str = "confirm",
    answers: list | None = None,
    card_id: str = CARD_ID,
    revision: int = 1,
    **overrides,
) -> dict:
    reply = {
        "schemaVersion": 1,
        "kind": "intent_alignment_reply",
        "cardId": card_id,
        "revision": revision,
        "answers": list(answers or []),
        "action": action,
    }
    reply.update(overrides)
    return reply


def _persisted(module, session_id: str = SESSION_ID) -> dict:
    path = module._intent_alignment_store_path(session_id)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


# ── B9-1：clear 快路径信号识别 ────────────────────────────────────────────


def test_clear_imperative_signal_gate_proceed(isolated_store):
    """clear 信号：明确祈使句 + 明确对象 → gate 给 proceed 倾向（仅提示，decidedBy=rules）。"""
    gate = run_rule_prefilter("帮我创建一个命令行待办清单工具，数据存本地文件")
    assert gate["action"] == "proceed"
    assert gate["decidedBy"] == "rules"
    assert 0.0 <= gate["confidence"] <= 1.0
    assert "明确祈使句" in gate["reason"]
    # gate 段结构固定为 §4.2 四字段，不携带任何已答/已对齐结论。
    assert set(gate) == {"action", "confidence", "decidedBy", "reason"}

    clear = detect_clear_imperative_signal("请生成月度报表导出脚本")
    assert clear["hit"] is True
    assert clear["verb"] == "生成"
    assert "报表" in clear["object"]

    # 无祈使动词的叙述句不触发 proceed（保守 ask 倾向）。
    assert run_rule_prefilter("我今天想聊聊报表的事")["action"] == "ask"


# ── B9-2：分叉信号命中交自判 ─────────────────────────────────────────────


def test_fork_signals_hit_ask_and_metric_present_not_flagged(isolated_store):
    """分叉信号：多义指代/缺失量纲/互斥约束命中 → ask；带量纲的说法不误报缺失量纲。"""
    pronoun_gate = run_rule_prefilter("把它改成深色主题")
    assert pronoun_gate["action"] == "ask"
    assert pronoun_gate["decidedBy"] == "rules"
    assert "多义指代" in pronoun_gate["reason"]

    vague_gate = run_rule_prefilter("优化一下首页的展示")
    assert vague_gate["action"] == "ask"
    assert "缺失量纲" in vague_gate["reason"]

    exclusive_hits = detect_fork_signals("既要全量导出又要增量同步")
    assert [hit["signal"] for hit in exclusive_hits] == ["互斥约束"]

    # 带量纲（200ms）不命中缺失量纲，整体无其他分叉信号。
    assert detect_fork_signals("把响应时间优化到 200ms 以内") == []


# ── B9-3：保守不误标（规则不确定时 openQuestions 保留） ──────────────────


def test_prefilter_conservative_keeps_open_questions(isolated_store):
    """规则不确定时保守给出 ask 倾向，且绝不误标已答/已对齐（openQuestions 保留）。"""
    store = get_intent_alignment_store()
    _seed_draft(store)
    qid = _seed_asked(store)

    gate = run_rule_prefilter("看看现在的项目结构再决定")
    assert gate["action"] == "ask"
    assert gate["decidedBy"] == "rules"
    assert gate["confidence"] <= 0.5

    packet = assemble_packet(store.get_current(SESSION_ID), gate)
    assert packet is not None
    assert packet["status"] == "clarifying"
    assert [q["id"] for q in packet["openQuestions"]] == [qid]
    # 台账原状未动：问题仍是 asked。
    assert [q["id"] for q in store.open_questions(SESSION_ID)] == [qid]


# ── B9-4：回执按三元组映射 + 落账无结构化变更 ────────────────────────────


def test_reply_maps_by_triple_and_applies_without_structured_change(isolated_store):
    """回执按 cardId+revision+questionId 三元组映射；落账只标 answered 存原文。"""
    store = get_intent_alignment_store()
    _seed_draft(store)
    qid = _seed_asked(store)
    card = _card_payload()
    answers = [{"questionId": "q1", "selectedOptionIds": ["o_disk"]}]

    parsed = parse_intent_alignment_reply(_reply(answers=answers), card)
    assert parsed["ok"] is True
    assert parsed["cardMatched"] is True
    assert parsed["answers"][0]["questionId"] == qid
    assert parsed["answers"][0]["answerText"] == "落盘"  # 选中项 label 规范化

    before = _persisted(isolated_store)
    outcome = apply_reply(
        store, SESSION_ID, _reply(answers=answers), _turn("turn_reply"), card
    )
    assert outcome["storeTouched"] is True
    assert [a["questionId"] for a in outcome["applied"]] == [qid]
    assert outcome["failed"] == []
    assert outcome["unmapped"] == []
    assert outcome["skipped"] == []

    after = _persisted(isolated_store)
    assert after["currentVersion"] == before["currentVersion"] == 1  # merge=None 无新版本
    v1_before, v1_after = before["versions"][0], after["versions"][0]
    assert v1_after["contentHash"] == v1_before["contentHash"]
    assert v1_after["constraints"] == v1_before["constraints"]
    assert v1_after["goal"] == v1_before["goal"]
    ledger = {q["id"]: q for q in v1_after["openQuestions"]}
    assert ledger[qid]["status"] == "answered"
    assert ledger[qid]["answer"]["text"] == "落盘"
    assert store.open_questions(SESSION_ID) == []


# ── B9-5：freeText 与 skipped 处理 ───────────────────────────────────────


def test_reply_free_text_applied_and_skipped_kept_open(isolated_store):
    """freeText 规范化为答案原文；skipped 题不落账、台账保持 asked（保守留待自判）。"""
    store = get_intent_alignment_store()
    _seed_draft(store)
    _seed_asked(store)  # q1
    q2 = store.record_question_asked(
        SESSION_ID,
        question="还有其他约束吗？",
        why_it_matters="补充 constraints",
        applies_to="constraints",
        turn_ref=_turn("turn_2b"),
        asked_in_card=CARD_ID,
    )
    assert q2 == "q2"

    reply = _reply(
        answers=[
            {"questionId": "q2", "freeText": "仅保留未完成的待办"},
            {"questionId": "q1", "skipped": True},
        ]
    )
    parsed = parse_intent_alignment_reply(reply, _card_payload())
    by_id = {a["questionId"]: a for a in parsed["answers"]}
    assert by_id["q2"]["answerText"] == "仅保留未完成的待办"
    assert by_id["q2"]["skipped"] is False
    assert by_id["q1"]["skipped"] is True
    assert by_id["q1"]["answerText"] == ""

    outcome = apply_reply(store, SESSION_ID, reply, _turn("turn_reply"), _card_payload())
    assert [a["questionId"] for a in outcome["applied"]] == ["q2"]
    assert [s["questionId"] for s in outcome["skipped"]] == ["q1"]

    ledger = {q["id"]: q["status"] for q in store.get_current(SESSION_ID)["openQuestions"]}
    assert ledger == {"q1": "asked", "q2": "answered"}
    assert [q["id"] for q in store.open_questions(SESSION_ID)] == ["q1"]


# ── B9-6：映射失败 / schema 非法条目原样留档，store 不动 ─────────────────


def test_reply_unmapped_and_invalid_leave_store_untouched(isolated_store):
    """revision 不匹配 / questionId 未问过 / schema 非法：条目原样留档，store 不动。"""
    store = get_intent_alignment_store()
    _seed_draft(store)
    _seed_asked(store)
    card = _card_payload()

    # revision 不匹配 → 三元组不成立，全部条目 unmapped。
    mismatch = _reply(revision=2, answers=[{"questionId": "q1", "selectedOptionIds": ["o_disk"]}])
    parsed = parse_intent_alignment_reply(mismatch, card)
    assert parsed["ok"] is True
    assert parsed["cardMatched"] is False
    assert parsed["answers"] == []
    outcome = apply_reply(store, SESSION_ID, mismatch, _turn("turn_x"), card)
    assert outcome["storeTouched"] is False
    assert [u["questionId"] for u in outcome["unmapped"]] == ["q1"]

    # 卡匹配但 questionId 不在卡内 → unmapped 留档。
    outcome = apply_reply(
        store,
        SESSION_ID,
        _reply(answers=[{"questionId": "q_none", "freeText": "随便"}]),
        _turn("turn_x"),
        card,
    )
    assert outcome["applied"] == []
    assert outcome["storeTouched"] is False
    assert [u["questionId"] for u in outcome["unmapped"]] == ["q_none"]

    # 无卡上下文、questionId 不在台账：store 侧映射失败 → unmapped 留档。
    outcome = apply_reply(
        store,
        SESSION_ID,
        _reply(answers=[{"questionId": "q_none", "freeText": "随便"}]),
        _turn("turn_x"),
    )
    assert [u["questionId"] for u in outcome["unmapped"]] == ["q_none"]
    assert outcome["applied"] == []

    # schema 非法（kind 错误）→ ok=False，不写 store。
    invalid = _reply(kind="something_else", answers=[{"questionId": "q1", "freeText": "x"}])
    parsed = parse_intent_alignment_reply(invalid, card)
    assert parsed["ok"] is False
    assert any("kind" in error for error in parsed["errors"])
    outcome = apply_reply(store, SESSION_ID, invalid, _turn("turn_x"), card)
    assert outcome["ok"] is False
    assert outcome["storeTouched"] is False

    persisted = _persisted(isolated_store)
    assert persisted["currentVersion"] == 1
    assert persisted["versions"][0]["openQuestions"][0]["status"] == "asked"


# ── B9-7：dismiss 不动 store ─────────────────────────────────────────────


def test_dismiss_reply_does_not_touch_store(isolated_store):
    """action=dismiss 的 store 处置为开放点：保守不动 store，解析结果原样返回。"""
    store = get_intent_alignment_store()
    _seed_draft(store)
    _seed_asked(store)
    before = _persisted(isolated_store)

    reply = _reply(action="dismiss", answers=[{"questionId": "q1", "freeText": "算了"}])
    outcome = apply_reply(store, SESSION_ID, reply, _turn("turn_dismiss"), _card_payload())
    assert outcome["dismissed"] is True
    assert outcome["storeTouched"] is False
    assert outcome["applied"] == []
    assert outcome["parsed"]["answers"][0]["answerText"] == "算了"

    assert _persisted(isolated_store) == before  # store 完全未动
    assert store.open_questions(SESSION_ID)[0]["id"] == "q1"


# ── B9-8：packet 组装映射与空态 ──────────────────────────────────────────


def test_assemble_packet_mapping_and_empty_state(isolated_store):
    """packet 组装映射（§4.2）：openQuestions/clarifyHistory/confirmedRequirements/budget/gate。"""
    store = get_intent_alignment_store()
    _seed_draft(store)
    q1 = _seed_asked(store)
    store.record_answer(
        SESSION_ID,
        q1,
        answer_text="落盘",
        turn_ref=_turn("turn_3"),
        merge=[{"field": "constraints[+]", "to": "待办数据必须落盘持久化"}],
    )
    q2 = store.record_question_asked(
        SESSION_ID,
        question="要支持多用户吗？",
        why_it_matters="决定是否引入账号体系",
        applies_to="boundaries",
        turn_ref=_turn("turn_4"),
        asked_in_card="card_2",
    )
    gate = run_rule_prefilter("继续推进")
    packet = assemble_packet(store.get_current(SESSION_ID), gate)

    assert packet is not None
    assert packet["schemaVersion"] == 1
    assert packet["status"] == "clarifying"
    # openQuestions ← asked ∧ 未 answered ∧ 未 withdrawn；q1 已答不再出现。
    assert [q["id"] for q in packet["openQuestions"]] == [q2]
    open_view = packet["openQuestions"][0]
    assert open_view["question"] == "要支持多用户吗？"
    assert open_view["impactFork"] == "决定是否引入账号体系"
    assert open_view["askedAt"] == "turn_4"
    assert open_view["options"] == []
    # clarifyHistory ← 已答条目；settledAs 取 changes 折算结果。
    assert [h["questionId"] for h in packet["clarifyHistory"]] == [q1]
    assert packet["clarifyHistory"][0]["answer"] == "落盘"
    assert "待办数据必须落盘持久化" in packet["clarifyHistory"][0]["settledAs"]
    # confirmedRequirements ← 四要素要点（≤5 条、一句话化，goal 在首位）。
    points = [r["point"] for r in packet["confirmedRequirements"]]
    assert len(points) <= 5
    assert points[0] == "搭建命令行待办工具"
    assert "待办数据必须落盘持久化" in points
    assert all("\n" not in point for point in points)
    assert packet["confirmedRequirements"][0]["settledAt"] == "v2"
    # budget / gate。
    assert packet["budget"] == {"questionsAskedThisSession": 2, "maxQuestionsPerTurn": 3}
    assert packet["gate"] == gate

    # 撤销后无 asked → aligned；无工件/空快照 → None（章节空态）。
    store.withdraw_question(SESSION_ID, q2, reason="用户说明单机即可")
    aligned = assemble_packet(store.get_current(SESSION_ID), gate)
    assert aligned is not None
    assert aligned["status"] == "aligned"
    assert aligned["openQuestions"] == []
    assert assemble_packet(None, gate) is None
    assert assemble_packet({}, gate) is None

    # packet 是派生投影：篡改 packet 不影响 store。
    packet["openQuestions"].append({"id": "q_fake"})
    packet["budget"]["questionsAskedThisSession"] = 99
    assert [q["id"] for q in store.open_questions(SESSION_ID)] == []
