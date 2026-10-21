#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""意图对齐 agent 工具族测试（T4，设计文档 §3.5.2 / §3.9 / §4.4-2 / §8 T4 行）。

覆盖：intent_alignment_card 四要素前置校验拒发卡、发卡全链（payload 形状 /
台账登记 / request_confirmation / cardId 唯一 / revision=发卡版本 / question_id
沿用）、intent_alignment_merge 三段转调与首写建 v1、写后 packet 刷新
（options / evidence 回填与 fail-open）、错误路径结构化返回、todo_write 同族
注册面（Key_Tools / llm_facing / executor 映射 / tool_catalog / 白名单 /
registry descriptor）与 journal tool_call turnItem 回放形状。

fixture 隔离复用 tests/test_intent_alignment_artifact.py 的 isolated 模式
（monkeypatch 路径函数 + 单例复位）。
"""

from __future__ import annotations

import json

import pytest

from core.orchestration import intent_alignment
from core.orchestration.intent_alignment import (
    CARD_TOOL_NAME,
    MERGE_TOOL_NAME,
    get_intent_alignment_store,
    intent_alignment_card_handler,
    intent_alignment_merge_handler,
)

SESSION_ID = "sess_tools"


# ---------------------------------------------------------------------------
# fixture 与种子助手
# ---------------------------------------------------------------------------


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


class _PacketCapture:
    """PromptManager 测试替身：只记录 set_intent_alignment_packet 注入。"""

    def __init__(self):
        self.packets: list = []

    def set_intent_alignment_packet(self, packet):
        self.packets.append(packet)


class _BrokenPromptManager:
    """packet 刷新抛错的替身：验证 fail-open 不阻断权威写入。"""

    def set_intent_alignment_packet(self, packet):
        raise RuntimeError("packet projection exploded")


def _turn(turn_id: str = "turn_1") -> dict:
    return {"sessionId": SESSION_ID, "turnId": turn_id, "messageId": ""}


def _question(text: str, **overrides) -> dict:
    entry = {
        "question": text,
        "why_it_matters": "决定存储层实现",
        "applies_to": "constraints",
        "input_mode": "free_text",
    }
    entry.update(overrides)
    return entry


def _choice_question(text: str = "数据要落盘还是只留内存？", question_id: str = "") -> dict:
    entry = _question(
        text,
        input_mode="single_choice",
        options=[
            {"option_id": "o_disk", "label": "落盘", "hint": "需文件存储层"},
            {"option_id": "o_mem", "label": "只留内存"},
        ],
    )
    if question_id:
        entry["question_id"] = question_id
    return entry


def _seed_draft(store) -> dict:
    """落齐四要素初稿（v1 draft），返回工件快照。"""
    store.open_or_load(
        SESSION_ID,
        origin={"mode": "chat", "roomId": "", "sourceTextDigest": "sha256:beef"},
    )
    return store.record_structured(
        SESSION_ID,
        goal="搭建命令行待办工具",
        boundaries=["不做图形界面"],
        constraints=["必须使用 Python 标准库"],
        acceptance=["能添加和列出待办"],
        assumptions=[{"text": "用户要命令行形态", "source": "inferred"}],
    )


def _persisted(module, session_id: str = SESSION_ID) -> dict:
    path = module._intent_alignment_store_path(session_id)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# intent_alignment_card：四要素前置校验拒发卡（§3.5.2 约束）
# ---------------------------------------------------------------------------


def test_card_rejects_without_artifact_or_four_elements(isolated_store):
    """无工件 / 无四要素初稿时结构化拒发卡，不落卡、不动台账、不写盘。"""
    pm = _PacketCapture()

    no_artifact = intent_alignment_card_handler(
        SESSION_ID,
        intent_summary="澄清持久化",
        questions=[_choice_question()],
        turn_ref=_turn(),
        prompt_manager=pm,
    )
    assert no_artifact["status"] == "error"
    assert no_artifact["code"] == "NO_ARTIFACT"
    assert "intent_alignment_merge" in no_artifact["message"]
    # 不落任何骨架文件。
    assert not isolated_store._intent_alignment_store_path(SESSION_ID) or not __import__(
        "pathlib"
    ).Path(intent_alignment._intent_alignment_store_path(SESSION_ID)).exists()
    assert pm.packets == []

    store = get_intent_alignment_store()
    # 只有骨架、没有四要素：同样拒发。
    store.open_or_load(
        SESSION_ID,
        origin={"mode": "chat", "roomId": "", "sourceTextDigest": "sha256:beef"},
    )
    store.record_structured(
        SESSION_ID, goal="", boundaries=[], constraints=[], acceptance=[], assumptions=[]
    )
    empty_draft = intent_alignment_card_handler(
        SESSION_ID,
        intent_summary="澄清持久化",
        questions=[_choice_question()],
        turn_ref=_turn(),
        prompt_manager=pm,
    )
    assert empty_draft["status"] == "error"
    assert empty_draft["code"] == "NO_FOUR_ELEMENTS"
    # 拒发卡不产生 pending_confirmation，也不登记台账。
    snapshot = store.get_current(SESSION_ID)
    assert snapshot["status"] == "draft"
    assert snapshot["openQuestions"] == []
    assert snapshot["confirmation"] == {}


def test_card_rejects_when_version_not_draft(isolated_store):
    """当前版本不是 draft（已发过卡）时结构化拒绝；改问需先 merge 出新 draft。"""
    store = get_intent_alignment_store()
    _seed_draft(store)
    pm = _PacketCapture()
    first = intent_alignment_card_handler(
        SESSION_ID,
        intent_summary="澄清持久化",
        questions=[_choice_question()],
        turn_ref=_turn(),
        prompt_manager=pm,
    )
    assert first["status"] == "ok"

    again = intent_alignment_card_handler(
        SESSION_ID,
        intent_summary="澄清持久化",
        questions=[_choice_question()],
        turn_ref=_turn(),
        prompt_manager=pm,
    )
    assert again["status"] == "error"
    assert again["code"] == "INVALID_TRANSITION"
    assert "intent_alignment_merge" in again["message"]
    # 台账不被重复登记（重试未产生新条目）。
    assert [q["id"] for q in store.open_questions(SESSION_ID)] == ["q1"]


def test_card_rejects_invalid_questions_without_store_write(isolated_store):
    """入参问题非法（空列表 / 超量 / 选择题缺 options / 未知 input_mode）→ 结构化错误且不写台账。"""
    store = get_intent_alignment_store()
    _seed_draft(store)
    pm = _PacketCapture()
    base = {"intent_summary": "澄清", "turn_ref": _turn(), "prompt_manager": pm}

    empty = intent_alignment_card_handler(SESSION_ID, questions=[], **base)
    assert empty == {"status": "error", "code": "INVALID_QUESTIONS", **{
        k: v for k, v in empty.items() if k not in {"status", "code"}
    }}
    assert empty["message"]

    too_many = intent_alignment_card_handler(
        SESSION_ID,
        questions=[_question(f"问题 {index}") for index in range(1, 8)],
        **base,
    )
    assert too_many["code"] == "INVALID_QUESTIONS"
    assert "5" in too_many["message"]

    no_options = intent_alignment_card_handler(
        SESSION_ID, questions=[_question("选一个", input_mode="single_choice")], **base
    )
    assert no_options["code"] == "INVALID_QUESTIONS"
    assert "options" in no_options["message"]

    bad_mode = intent_alignment_card_handler(
        SESSION_ID, questions=[_question("随便问", input_mode="voice")], **base
    )
    assert bad_mode["code"] == "INVALID_QUESTIONS"
    assert "input_mode" in bad_mode["message"]

    no_summary = intent_alignment_card_handler(
        SESSION_ID, intent_summary="  ", questions=[_choice_question()], **{
            k: v for k, v in base.items() if k != "intent_summary"
        }
    )
    assert no_summary["code"] == "INVALID_QUESTIONS"

    # 全部拒发：台账仍为空、版本状态不变。
    assert store.open_questions(SESSION_ID) == []
    assert store.get_current(SESSION_ID)["status"] == "draft"
    assert pm.packets == []


# ---------------------------------------------------------------------------
# intent_alignment_card：发卡全链（payload / 台账 / request_confirmation / packet）
# ---------------------------------------------------------------------------


def test_card_full_chain_payload_ledger_confirmation_and_packet(isolated_store):
    """发卡全链：§5.2 payload 形状、台账登记（id 沿用+分配、askedInCard）、
    request_confirmation 绑定 cardId、revision=发卡版本、packet 刷新回填 options。"""
    store = get_intent_alignment_store()
    _seed_draft(store)
    pm = _PacketCapture()

    result = intent_alignment_card_handler(
        SESSION_ID,
        intent_summary="为待办工具澄清持久化方案",
        questions=[
            _choice_question(question_id="q1"),
            _question("还有其他要补充的约束吗？", required=False, placeholder="例如：仅提醒未使用券"),
        ],
        artifacts=[{"artifact_id": SESSION_ID, "version": 1, "title": "待办工具需求"}],
        turn_ref=_turn("turn_card"),
        prompt_manager=pm,
    )
    assert result["status"] == "ok"
    assert result["cardId"].startswith("ia_")
    assert result["revision"] == 1
    assert result["artifactStatus"] == "pending_confirmation"
    assert len(result["questionIds"]) == 2
    # 沿用 id 在前、台账分配 id 按序号补位。
    assert result["questionIds"][0] == "q1"

    payload = result["payload"]
    assert payload["schemaVersion"] == 1
    assert payload["kind"] == "intent_alignment_card"
    assert payload["cardId"] == result["cardId"]
    assert payload["revision"] == 1
    assert payload["intentSummary"] == "为待办工具澄清持久化方案"
    assert payload["status"] == "open"
    assert payload["artifacts"] == [
        {"artifactId": SESSION_ID, "version": 1, "title": "待办工具需求"}
    ]
    choice, free = payload["questions"]
    assert choice["questionId"] == "q1"
    assert choice["prompt"] == "数据要落盘还是只留内存？"
    assert choice["inputMode"] == "single_choice"
    assert choice["options"] == [
        {"optionId": "o_disk", "label": "落盘", "hint": "需文件存储层"},
        {"optionId": "o_mem", "label": "只留内存"},
    ]
    assert "required" not in choice  # 默认必答，不写冗余字段
    assert free["questionId"] == result["questionIds"][1]
    assert free["inputMode"] == "free_text"
    assert free["required"] is False
    assert free["placeholder"] == "例如：仅提醒未使用券"
    # payload 落在 8KB 建议上限内（产出端约束）。
    assert len(json.dumps(payload, ensure_ascii=False)) <= 8 * 1024

    # 台账：q1 沿用、新题分配、askedInCard 绑定本卡、askedAtTurn 记发卡 turn。
    snapshot = store.get_current(SESSION_ID)
    assert snapshot["status"] == "pending_confirmation"
    assert snapshot["confirmation"]["cardId"] == result["cardId"]
    assert snapshot["confirmation"]["issuedAtTurn"] == "turn_card"
    assert snapshot["confirmation"]["decision"] == "pending"
    ledger = {q["id"]: q for q in snapshot["openQuestions"]}
    assert set(ledger) == {"q1", result["questionIds"][1]}
    assert ledger["q1"]["askedInCard"] == result["cardId"]
    assert ledger["q1"]["askedAtTurn"] == "turn_card"
    assert ledger["q1"]["status"] == "asked"
    assert store.open_questions(SESSION_ID) == snapshot["openQuestions"]

    # 写后 packet 刷新：clarifying + options 从发卡入参回填。
    assert len(pm.packets) == 1
    packet = pm.packets[0]
    assert packet["status"] == "clarifying"
    options_by_id = {q["id"]: q["options"] for q in packet["openQuestions"]}
    assert options_by_id["q1"] == ["落盘", "只留内存"]
    assert options_by_id[result["questionIds"][1]] == []


def test_card_allocates_unique_card_ids_and_reuses_question_ids(isolated_store):
    """cardId 同会话唯一（§3.9）；重问沿用台账 id 且 askedInCard 刷新到新卡。"""
    store = get_intent_alignment_store()
    _seed_draft(store)
    pm = _PacketCapture()

    first = intent_alignment_card_handler(
        SESSION_ID,
        intent_summary="澄清",
        questions=[_choice_question()],
        turn_ref=_turn("turn_a"),
        prompt_manager=pm,
    )
    assert first["status"] == "ok"

    # merge 出新 draft（同内容重写），再对新 draft 重问同一问题（沿用 q1）。
    merged = intent_alignment_merge_handler(
        SESSION_ID,
        structured={"goal": "搭建命令行待办工具"},
        turn_ref=_turn("turn_b"),
        prompt_manager=pm,
    )
    assert merged["status"] == "ok"
    assert merged["version"] == 2

    second = intent_alignment_card_handler(
        SESSION_ID,
        intent_summary="澄清",
        questions=[_choice_question(question_id="q1")],
        turn_ref=_turn("turn_c"),
        prompt_manager=pm,
    )
    assert second["status"] == "ok"
    assert second["cardId"] != first["cardId"]
    assert second["revision"] == 2
    assert second["questionIds"] == ["q1"]

    snapshot = store.get_current(SESSION_ID)
    ledger = {q["id"]: q for q in snapshot["openQuestions"]}
    # 同 id 重问不产生第二条台账；askedInCard 指向最新卡。
    assert len(ledger) == 1
    assert ledger["q1"]["askedInCard"] == second["cardId"]
    assert ledger["q1"]["askedAtTurn"] == "turn_c"

    # 旧版本的卡片记录不受影响（版本快照化，append-only 审计）。
    v1 = store.get_version(SESSION_ID, 1)
    assert v1["confirmation"]["cardId"] == first["cardId"]


def test_card_packet_refresh_fails_open(isolated_store):
    """packet 刷新异常静默直通（fail-open）：发卡与台账落账不受投影故障阻断。"""
    store = get_intent_alignment_store()
    _seed_draft(store)

    result = intent_alignment_card_handler(
        SESSION_ID,
        intent_summary="澄清",
        questions=[_choice_question()],
        turn_ref=_turn(),
        prompt_manager=_BrokenPromptManager(),
    )
    assert result["status"] == "ok"
    snapshot = store.get_current(SESSION_ID)
    assert snapshot["status"] == "pending_confirmation"
    assert snapshot["confirmation"]["cardId"] == result["cardId"]


# ---------------------------------------------------------------------------
# intent_alignment_merge：三段转调、首写建 v1、overlay、packet evidence
# ---------------------------------------------------------------------------


def test_merge_structured_first_write_creates_v1_draft(isolated_store):
    """首次写入经 open_or_load 创建骨架并产生 v1(draft)，origin.mode=chat。"""
    pm = _PacketCapture()
    result = intent_alignment_merge_handler(
        SESSION_ID,
        structured={
            "goal": "做优惠券到期提醒",
            "boundaries": ["先做后端任务"],
            "constraints": ["复用现有消息通道"],
            "acceptance": ["到期前 1 天提醒"],
            "assumptions": [{"text": "用户要 App 推送", "source": "inferred"}],
        },
        turn_ref=_turn(),
        prompt_manager=pm,
    )
    assert result["status"] == "ok"
    assert result["artifactId"] == SESSION_ID
    assert result["version"] == 1
    assert result["artifactStatus"] == "draft"

    data = _persisted(isolated_store)
    assert data["origin"]["mode"] == "chat"
    assert data["currentVersion"] == 1
    snapshot = get_intent_alignment_store().get_current(SESSION_ID)
    assert snapshot["goal"]["text"] == "做优惠券到期提醒"
    assert snapshot["assumptions"][0]["id"] == "a1"

    # 写后 packet 刷新：confirmedRequirements 覆盖四要素要点，evidence 待归并回填。
    packet = pm.packets[-1]
    assert packet["status"] == "aligned"
    points = [item["point"] for item in packet["confirmedRequirements"]]
    assert "做优惠券到期提醒" in points
    assert all(item["evidence"] == "" for item in packet["confirmedRequirements"])


def test_merge_partial_structured_overlays_current_content(isolated_store):
    """partial structured 只覆盖提供的字段，未提供字段保持原值（assumptions 保留）。"""
    store = get_intent_alignment_store()
    _seed_draft(store)
    pm = _PacketCapture()

    result = intent_alignment_merge_handler(
        SESSION_ID,
        structured={"goal": "搭建带持久化的命令行待办工具"},
        turn_ref=_turn("turn_2"),
        prompt_manager=pm,
    )
    assert result["status"] == "ok"
    assert result["version"] == 2
    assert result["artifactStatus"] == "draft"

    snapshot = store.get_current(SESSION_ID)
    assert snapshot["goal"]["text"] == "搭建带持久化的命令行待办工具"
    assert snapshot["boundaries"] == ["不做图形界面"]
    assert snapshot["constraints"] == ["必须使用 Python 标准库"]
    assert snapshot["acceptance"] == [{"criterion": "能添加和列出待办", "verifiable": False}]
    assert snapshot["assumptions"][0]["id"] == "a1"
    # 新版本 supersedes v1，v1 冻结。
    assert snapshot["supersedes"] == 1
    assert store.get_version(SESSION_ID, 1)["goal"]["text"] == "搭建命令行待办工具"


def test_merge_answers_fold_into_new_version_and_backfill_evidence(isolated_store):
    """answers 逐题转调 record_answer：merge 指令折算产生新版本；packet evidence
    回填答案原文短引用、clarifyHistory.settledAs 取折算结果。"""
    store = get_intent_alignment_store()
    _seed_draft(store)
    pm = _PacketCapture()
    issued = intent_alignment_card_handler(
        SESSION_ID,
        intent_summary="澄清",
        questions=[_choice_question(question_id="q1")],
        turn_ref=_turn(),
        prompt_manager=pm,
    )
    assert issued["status"] == "ok"

    answer_text = "数据要落盘到本地文件，不能只留内存"
    result = intent_alignment_merge_handler(
        SESSION_ID,
        answers=[
            {
                "question_id": "q1",
                "answer_text": answer_text,
                "merge": [{"field": "constraints[+]", "to": "数据必须落盘到本地文件"}],
            }
        ],
        turn_ref=_turn("turn_2"),
        prompt_manager=pm,
    )
    assert result["status"] == "ok"
    assert result["answeredQuestionIds"] == ["q1"]
    assert result["version"] == 2
    assert result["artifactStatus"] == "draft"

    snapshot = store.get_current(SESSION_ID)
    ledger = {q["id"]: q for q in snapshot["openQuestions"]}
    assert ledger["q1"]["status"] == "answered"
    assert ledger["q1"]["answer"]["text"] == answer_text
    fold = [c for c in snapshot["changes"] if c.get("questionId") == "q1"]
    assert fold and fold[0]["field"] == "constraints[+]"
    assert fold[0]["to"] == "数据必须落盘到本地文件"
    assert "数据必须落盘到本地文件" in snapshot["constraints"]

    packet = pm.packets[-1]
    assert packet["status"] == "aligned"  # 唯一问题已答，无未决分叉
    history = {item["questionId"]: item for item in packet["clarifyHistory"]}
    assert history["q1"]["answer"] == answer_text
    assert history["q1"]["settledAs"] == "数据必须落盘到本地文件"
    evidence = {
        item["point"]: item["evidence"] for item in packet["confirmedRequirements"]
    }
    assert evidence["数据必须落盘到本地文件"] == answer_text
    # 未被折算的点 evidence 保持空串。
    assert evidence["搭建命令行待办工具"] == ""


def test_merge_confirmation_requires_pending_and_records_decision(isolated_store):
    """confirmation 裁决：draft 上 approve 拒绝；pending_confirmation 上 approve → confirmed。"""
    store = get_intent_alignment_store()
    _seed_draft(store)
    pm = _PacketCapture()

    premature = intent_alignment_merge_handler(
        SESSION_ID,
        confirmation={"decision": "approved"},
        turn_ref=_turn(),
        prompt_manager=pm,
    )
    assert premature["status"] == "error"
    assert premature["code"] == "INVALID_TRANSITION"

    issued = intent_alignment_card_handler(
        SESSION_ID,
        intent_summary="澄清",
        questions=[_choice_question()],
        turn_ref=_turn(),
        prompt_manager=pm,
    )
    assert issued["status"] == "ok"

    approved = intent_alignment_merge_handler(
        SESSION_ID,
        confirmation={"decision": "approved", "note": "用户口头确认"},
        turn_ref=_turn("turn_ok"),
        prompt_manager=pm,
    )
    assert approved["status"] == "ok"
    assert approved["artifactStatus"] == "confirmed"
    snapshot = store.get_current(SESSION_ID)
    assert snapshot["confirmation"]["decision"] == "approved"
    assert snapshot["confirmation"]["decidedAtTurn"] == "turn_ok"
    assert snapshot["confirmation"]["confirmedDigest"] == snapshot["contentHash"]


def test_merge_structured_error_paths(isolated_store):
    """空归并 / 非法 decision / 只带 answers 且无工件：全部结构化错误。"""
    store = get_intent_alignment_store()
    pm = _PacketCapture()

    empty = intent_alignment_merge_handler(SESSION_ID, turn_ref=_turn(), prompt_manager=pm)
    assert empty["status"] == "error"
    assert empty["code"] == "EMPTY_MERGE"

    answers_only = intent_alignment_merge_handler(
        SESSION_ID,
        answers=[{"question_id": "q1", "answer_text": "落盘"}],
        turn_ref=_turn(),
        prompt_manager=pm,
    )
    assert answers_only["status"] == "error"
    assert answers_only["code"] == "NO_ARTIFACT"
    # answers-only 不创建骨架文件（骨架只在真正写入时创建）。
    import pathlib

    assert not pathlib.Path(intent_alignment._intent_alignment_store_path(SESSION_ID)).exists()

    store.open_or_load(
        SESSION_ID,
        origin={"mode": "chat", "roomId": "", "sourceTextDigest": "sha256:beef"},
    )
    store.record_structured(
        SESSION_ID, goal="g", boundaries=["b"], constraints=["c"], acceptance=["a"], assumptions=[]
    )
    bad_decision = intent_alignment_merge_handler(
        SESSION_ID,
        confirmation={"decision": "maybe"},
        turn_ref=_turn(),
        prompt_manager=pm,
    )
    assert bad_decision["status"] == "error"
    assert bad_decision["code"] in {"INVALID_TRANSITION", "MERGE_FAILED"}

    unknown_question = intent_alignment_merge_handler(
        SESSION_ID,
        answers=[{"question_id": "q9", "answer_text": "随便答"}],
        turn_ref=_turn(),
        prompt_manager=pm,
    )
    assert unknown_question["status"] == "error"
    assert unknown_question["code"] == "NO_ARTIFACT"


def test_merge_packet_refresh_fails_open(isolated_store):
    """merge 的 packet 刷新异常同样 fail-open：store 写入不受影响。"""
    store = get_intent_alignment_store()
    _seed_draft(store)

    result = intent_alignment_merge_handler(
        SESSION_ID,
        structured={"goal": "新目标"},
        turn_ref=_turn(),
        prompt_manager=_BrokenPromptManager(),
    )
    assert result["status"] == "ok"
    assert store.get_current(SESSION_ID)["goal"]["text"] == "新目标"


# ---------------------------------------------------------------------------
# 注册面：todo_write 同族 journaled tool-call（Key_Tools / executor / catalog /
# 白名单 / registry descriptor）
# ---------------------------------------------------------------------------


def _llm_tool(name: str):
    from tools.Key_Tools import create_llm_facing_tools

    return next(tool for tool in create_llm_facing_tools() if tool.name == name)


def test_intent_alignment_tools_registered_on_every_surface():
    """缺任一注册面都会导致工具不可见：定义、执行映射、目录、授权四处齐备。"""
    from core.infrastructure.tool_executor import ToolExecutor
    from core.web.services import agent_directory_service, tool_catalog
    from core.web.services.tool_registry_service import get_tool_registry
    from tools.Key_Tools import create_key_tools, create_llm_facing_tools

    key_names = {tool.name for tool in create_key_tools()}
    llm_names = {tool.name for tool in create_llm_facing_tools()}
    executor_map = ToolExecutor()._tool_map
    for name in (CARD_TOOL_NAME, MERGE_TOOL_NAME):
        assert name in key_names
        assert name in llm_names
        assert name in executor_map

        metadata = tool_catalog.metadata_for_tool(name)
        assert metadata["category"] == "task_runtime"
        assert metadata["permissionTier"] == tool_catalog.LOW_PERMISSION_TIER
        assert metadata["riskTags"] == []
        assert metadata["capabilityTags"]

        assert name in agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS
        policy = agent_directory_service.default_session_agent_tool_policy("tool-test")
        assert name in policy["allowedTools"]

        registry = get_tool_registry()
        tool_entry = next(item for item in registry["tools"] if item["name"] == name)
        descriptor = next(item for item in registry["descriptors"] if item["name"] == name)
        assert tool_entry["llmVisible"] is True
        assert tool_entry["runtimeActive"] is True
        assert descriptor["risk"] == "read"
        assert descriptor["approval"] == "never"


def test_intent_alignment_card_schema_declares_merge_first_discipline():
    """发卡工具 schema 三段入参；描述写明先 merge 后发卡与正文同问纪律。"""
    tool = _llm_tool(CARD_TOOL_NAME)
    schema = tool.args_schema.model_json_schema()
    assert set(schema["properties"]) == {"intent_summary", "questions", "artifacts"}
    description = str(getattr(tool, "description", ""))
    assert "intent_alignment_merge" in description
    assert "正文" in description
    assert "why_it_matters" in description


def test_intent_alignment_merge_schema_declares_three_sections():
    """归并工具 schema 三段入参；描述写明答案语义判断归 agent、工具只落账。"""
    tool = _llm_tool(MERGE_TOOL_NAME)
    schema = tool.args_schema.model_json_schema()
    assert set(schema["properties"]) == {"answers", "structured", "confirmation"}
    description = str(getattr(tool, "description", ""))
    for field in ("question_id", "answer_text", "merge", "approved", "revision_requested", "rejected"):
        assert field in description


def test_wrappers_resolve_runtime_context_and_return_json(isolated_store, monkeypatch):
    """Key_Tools wrapper 从 agent runtime 上下文解析会话并透传 handler（无上下文
    返回结构化错误）；packet 刷新按同链路落到 PromptManager。"""
    from core.web.services.agent_directory_service import _CURRENT_AGENT_RUNTIME
    from tools.Key_Tools import create_key_tools

    captured: list = []

    class _StubPromptManager:
        def set_intent_alignment_packet(self, packet):
            captured.append(packet)

    monkeypatch.setattr(
        "core.prompt_manager.prompt_manager.get_prompt_manager", lambda: _StubPromptManager()
    )

    card_tool = next(tool for tool in create_key_tools() if tool.name == CARD_TOOL_NAME)
    merge_tool = next(tool for tool in create_key_tools() if tool.name == MERGE_TOOL_NAME)

    # 无运行时上下文：结构化错误，不打断调用方。
    orphan = json.loads(card_tool.func(intent_summary="澄清", questions=[_choice_question()]))
    assert orphan["status"] == "error"
    assert orphan["code"] == "NO_SESSION_CONTEXT"

    token = _CURRENT_AGENT_RUNTIME.set({"sessionId": SESSION_ID, "turnId": "turn_w"})
    try:
        draft = json.loads(
            merge_tool.func(
                structured={
                    "goal": "搭建命令行待办工具",
                    "boundaries": ["不做图形界面"],
                    "constraints": ["仅标准库"],
                    "acceptance": ["能增删查"],
                }
            )
        )
        assert draft["status"] == "ok"
        assert draft["version"] == 1

        issued = json.loads(
            card_tool.func(
                intent_summary="澄清持久化",
                questions=[_choice_question()],
                artifacts=[{"artifact_id": SESSION_ID, "version": 1, "title": "需求"}],
            )
        )
        assert issued["status"] == "ok"
        assert issued["payload"]["cardId"] == issued["cardId"]
        # 同一 turn 上下文透传：台账 askedAtTurn 记录 wrapper 解析出的 turnId。
        snapshot = get_intent_alignment_store().get_current(SESSION_ID)
        assert snapshot["confirmation"]["cardId"] == issued["cardId"]
        assert snapshot["openQuestions"][0]["askedAtTurn"] == "turn_w"
        # 默认 PromptManager 解析链路被调用（packet 注入走 get_prompt_manager()）。
        assert captured and captured[-1]["status"] == "clarifying"
    finally:
        _CURRENT_AGENT_RUNTIME.reset(token)


# ---------------------------------------------------------------------------
# journal 回放：tool_call turnItem 形状（todo_write 同构，前端派生源）
# ---------------------------------------------------------------------------


def test_card_arguments_survive_journal_turn_item_replay(tmp_path, monkeypatch):
    """journal 回放的 tool_call turnItem 保留结构化入参（卡片内容由前端从
    turnItem.input 派生）；handler 结果随 result 侧携带完整 §5.2 payload。"""
    from core.chat.turn_journal import (
        EVENT_ASSISTANT_ITEM_COMMITTED,
        EVENT_TOOL_RESULT,
        EVENT_TURN_STARTED,
        append_turn_event,
        load_turn_events,
        session_turn_items_from_events,
    )

    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    arguments = {
        "intent_summary": "为待办工具澄清持久化方案",
        "questions": [
            {
                "question_id": "q1",
                "question": "数据要落盘还是只留内存？",
                "why_it_matters": "决定是否引入文件存储层",
                "applies_to": "constraints",
                "input_mode": "single_choice",
                "options": [
                    {"option_id": "o_disk", "label": "落盘"},
                    {"option_id": "o_mem", "label": "只留内存"},
                ],
            }
        ],
    }
    handler_result = {
        "status": "ok",
        "cardId": "ia_8f3c2a",
        "revision": 1,
        "questionIds": ["q1"],
        "artifactStatus": "pending_confirmation",
        "payload": {
            "schemaVersion": 1,
            "kind": "intent_alignment_card",
            "cardId": "ia_8f3c2a",
            "revision": 1,
            "intentSummary": "为待办工具澄清持久化方案",
            "questions": [{"questionId": "q1", "prompt": "数据要落盘还是只留内存？"}],
            "status": "open",
        },
    }

    append_turn_event(tmp_path, "session-card", "turn-card", EVENT_TURN_STARTED, status="running")
    append_turn_event(
        tmp_path,
        "session-card",
        "turn-card",
        EVENT_ASSISTANT_ITEM_COMMITTED,
        status="ready",
        payload={
            "kind": "tool_call",
            "status": "ready",
            "itemId": "tool-item-card-1",
            "callId": "call-card-1",
            "toolName": CARD_TOOL_NAME,
            "sessionId": "session-card",
            "turnId": "turn-card",
            "revision": 0,
        },
    )
    append_turn_event(
        tmp_path,
        "session-card",
        "turn-card",
        EVENT_TOOL_RESULT,
        status="done",
        tool_call_id="call-card-1",
        payload={
            "toolCall": {
                "id": "call-card-1",
                "toolCallId": "call-card-1",
                "name": CARD_TOOL_NAME,
                "status": "done",
                "summary": "已发卡并登记台账",
                "arguments": arguments,
                "result": json.dumps(handler_result, ensure_ascii=False),
            }
        },
    )

    items = session_turn_items_from_events(
        load_turn_events(tmp_path, "session-card"),
        turn_id="turn-card",
    )
    card_item = next(item for item in items if item["type"] == "tool_call")
    assert card_item["toolName"] == CARD_TOOL_NAME
    assert card_item["status"] == "completed"
    # 入参（卡片问题内容）以结构化 JSON 完整回放——前端派生不依赖第二存储。
    replayed_input = json.loads(card_item["input"])
    assert replayed_input["intent_summary"] == arguments["intent_summary"]
    assert replayed_input["questions"][0]["question_id"] == "q1"
    assert replayed_input["questions"][0]["options"][0]["label"] == "落盘"
    # handler 结果（含 cardId/revision/完整 payload）随 result 侧回放。
    assert "已发卡" in card_item["summary"]
