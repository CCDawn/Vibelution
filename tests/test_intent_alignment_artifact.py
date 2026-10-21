#!/usr/bin/env python3
"""意图对齐工件存储测试（设计文档 §9 表 A，T1 服务核心十用例）。

fixture 隔离模式对照 tests/test_task_planner.py:15-22：monkeypatch 路径函数到
tmp_path + 单例复位。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.orchestration import intent_alignment
from core.orchestration.intent_alignment import (
    IntentAlignmentStore,
    IntentAlignmentInvalidTransitionError,
    IntentAlignmentVersionConflictError,
    get_intent_alignment_store,
)

SESSION_ID = "sess_itest"


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """monkeypatch 路径函数到 tmp_path + 单例复位（对照 test_task_planner fixture）。"""
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


def _open_draft(store, session_id: str = SESSION_ID):
    """开骨架 + 落 v1 结构化初稿，返回 (store, v1_snapshot)。"""
    store.open_or_load(session_id, origin=_origin())
    version = store.record_structured(
        session_id,
        goal="搭建命令行待办工具",
        boundaries=["不做图形界面", "范围限于单机"],
        constraints=["必须使用 Python 标准库"],
        acceptance=["能添加和列出待办"],
        assumptions=[{"id": "a1", "text": "用户只需要单机版", "source": "inferred"}],
    )
    return version


def _persisted(monkeypatched_module, session_id: str = SESSION_ID) -> dict:
    path = monkeypatched_module._intent_alignment_store_path(session_id)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def test_structured_draft_persists_and_reloads(isolated_store):
    """A1 —— v1 draft 落盘，新 store 实例重载可见（对照 tests/test_task_planner.py:25）。"""
    v1 = _open_draft(get_intent_alignment_store())

    assert v1["version"] == 1
    assert v1["status"] == "draft"
    assert v1["contentHash"].startswith("sha256:")
    assert v1["supersedes"] is None

    persisted = _persisted(isolated_store)
    assert persisted["schemaVersion"] == 1
    assert persisted["currentVersion"] == 1
    assert persisted["origin"]["mode"] == "chat"
    assert [v["version"] for v in persisted["versions"]] == [1]
    assert persisted["versions"][0]["status"] == "draft"
    assert persisted["versions"][0]["contentHash"] == v1["contentHash"]

    # 新 store 实例从磁盘重载可见（不依赖单例内存态）。
    intent_alignment.reset_intent_alignment_store()
    fresh = get_intent_alignment_store()
    reloaded = fresh.get_current(SESSION_ID)
    assert reloaded is not None
    assert reloaded["version"] == 1
    assert reloaded["status"] == "draft"
    assert reloaded["goal"] == {"text": "搭建命令行待办工具"}
    assert reloaded["contentHash"] == v1["contentHash"]


def test_answer_creates_new_version_and_freezes_old(isolated_store):
    """A2 —— record_answer(q2) 产生 v2；v1 状态/内容/contentHash 不变，v2.changes 引用 q2。"""
    store = get_intent_alignment_store()
    _open_draft(store)
    q2 = store.record_question_asked(
        SESSION_ID,
        question="数据要落盘还是只留内存？",
        why_it_matters="决定是否引入文件存储层",
        applies_to="constraints",
        turn_ref=_turn("turn_2"),
    )
    assert q2 == "q1"

    v1_before = store.get_version(SESSION_ID, 1)
    v2 = store.record_answer(
        SESSION_ID,
        q2,
        answer_text="需要落盘，重启后保留",
        turn_ref=_turn("turn_3"),
        merge=[{"field": "constraints[+]", "to": "待办数据必须落盘持久化"}],
    )

    assert v2 is not None
    assert v2["version"] == 2
    assert v2["supersedes"] == 1
    assert v2["status"] == "draft"
    # v2.changes 逐条记录 {field, from, to, reason} 且引用 q2。
    assert len(v2["changes"]) == 1
    change = v2["changes"][0]
    assert change["field"] == "constraints[+]"
    assert change["from"] is None
    assert change["to"] == "待办数据必须落盘持久化"
    assert change["questionId"] == q2
    assert change["reason"] == f"answer to {q2}"
    # 答案原文已入台账。
    answered = next(q for q in v2["openQuestions"] if q["id"] == q2)
    assert answered["status"] == "answered"
    assert answered["answer"]["text"] == "需要落盘，重启后保留"

    # v1 冻结：状态/内容/contentHash 均不变（supersededBy 由索引侧表达）。
    v1_after = store.get_version(SESSION_ID, 1)
    assert v1_after["status"] == v1_before["status"] == "draft"
    assert v1_after["contentHash"] == v1_before["contentHash"]
    assert v1_after["constraints"] == v1_before["constraints"]
    assert v1_after["supersededBy"] == 2
    persisted = _persisted(isolated_store)
    assert persisted["currentVersion"] == 2
    assert len(persisted["versions"]) == 2
    assert persisted["versions"][0]["status"] == "draft"


def test_same_answer_replay_is_idempotent(isolated_store):
    """A3 —— 相同 questionId+answer+merge 重放不产生新版本。"""
    store = get_intent_alignment_store()
    _open_draft(store)
    q1 = store.record_question_asked(
        SESSION_ID,
        question="技术栈有限定吗？",
        why_it_matters="影响 constraints",
        applies_to="constraints",
        turn_ref=_turn("turn_2"),
    )
    merge = [{"field": "constraints[+]", "to": "仅用标准库"}]
    first = store.record_answer(
        SESSION_ID, q1, answer_text="仅用标准库", turn_ref=_turn("turn_3"), merge=merge
    )
    assert first is not None and first["version"] == 2

    replay = store.record_answer(
        SESSION_ID, q1, answer_text="仅用标准库", turn_ref=_turn("turn_9"), merge=merge
    )
    assert replay is None
    persisted = _persisted(isolated_store)
    assert persisted["currentVersion"] == 2
    assert [v["version"] for v in persisted["versions"]] == [1, 2]
    # 无 merge 的相同答案重放同样幂等（gate 回执路径）。
    q2 = store.record_question_asked(
        SESSION_ID,
        question="谁负责验收？",
        why_it_matters="影响 acceptance",
        applies_to="acceptance",
        turn_ref=_turn("turn_4"),
    )
    assert store.record_answer(
        SESSION_ID, q2, answer_text="用户本人", turn_ref=_turn("turn_5"), merge=[]
    ) is None
    assert store.record_answer(
        SESSION_ID, q2, answer_text="用户本人", turn_ref=_turn("turn_6"), merge=None
    ) is None
    persisted = _persisted(isolated_store)
    assert persisted["currentVersion"] == 2
    assert [v["version"] for v in persisted["versions"]] == [1, 2]


def test_invalid_transitions_rejected(isolated_store):
    """A4 —— confirmed→draft 直接连边、对 superseded 版本 record_answer 均拒绝。"""
    store = get_intent_alignment_store()
    _open_draft(store)
    card = "card_a4"
    store.request_confirmation(SESSION_ID, card_id=card, turn_ref=_turn("turn_2"))
    store.submit_confirmation_decision(
        SESSION_ID, decision="approved", turn_ref=_turn("turn_3")
    )
    assert store.get_current(SESSION_ID)["status"] == "confirmed"

    # confirmed → draft 直接连边：决策 API 不允许从 confirmed 发起（修订必须走
    # 版本链新版本路径），发卡 API 也不允许在非 draft 上重复发起。
    with pytest.raises(IntentAlignmentInvalidTransitionError):
        store.submit_confirmation_decision(
            SESSION_ID, decision="revision_requested", turn_ref=_turn("turn_4")
        )
    with pytest.raises(IntentAlignmentInvalidTransitionError):
        store.submit_confirmation_decision(
            SESSION_ID, decision="approved", turn_ref=_turn("turn_4")
        )
    with pytest.raises(IntentAlignmentInvalidTransitionError):
        store.request_confirmation(SESSION_ID, card_id="card_again", turn_ref=_turn("turn_4"))
    # 决策词表校验：非法 decision 直接拒绝。
    with pytest.raises(ValueError):
        store.submit_confirmation_decision(
            SESSION_ID, decision="maybe", turn_ref=_turn("turn_4")
        )

    # 对 superseded 版本 record_answer 拒绝：rejected 终止链后任何内容写入都拒绝。
    store2_session = "sess_a4_rejected"
    store.open_or_load(store2_session, origin=_origin())
    store.record_structured(
        store2_session,
        goal="目标 B",
        boundaries=["边界"],
        constraints=["约束"],
        acceptance=["验收"],
        assumptions=[],
    )
    store.request_confirmation(store2_session, card_id="card_r", turn_ref=_turn("turn_5"))
    store.submit_confirmation_decision(
        store2_session, decision="rejected", turn_ref=_turn("turn_6")
    )
    rejected_current = store.get_current(store2_session)
    assert rejected_current["status"] == "superseded"
    assert rejected_current["confirmation"]["decision"] == "rejected"
    with pytest.raises(IntentAlignmentInvalidTransitionError):
        store.record_answer(
            store2_session,
            "q1",
            answer_text="迟到的回答",
            turn_ref=_turn("turn_7"),
            merge=[{"field": "constraints[+]", "to": "无效追加"}],
        )
    with pytest.raises(IntentAlignmentInvalidTransitionError):
        store.record_structured(
            store2_session,
            goal="重写",
            boundaries=[],
            constraints=[],
            acceptance=[],
            assumptions=[],
        )
    # 链终止：没有产生后继版本。
    persisted = _persisted(isolated_store, store2_session)
    assert persisted["currentVersion"] == 1
    assert len(persisted["versions"]) == 1


def test_confirmation_decision_paths(isolated_store):
    """A5 —— approved→confirmed；revision_requested→旧版本 superseded + 新 draft 继承已答内容；rejected→superseded 无后继。"""
    store = get_intent_alignment_store()

    def seeded(session_id: str):
        store.open_or_load(session_id, origin=_origin())
        store.record_structured(
            session_id,
            goal="构建报表导出",
            boundaries=["仅限 CSV"],
            constraints=["输出目录固定"],
            acceptance=["导出文件可打开"],
            assumptions=[],
        )
        return None

    # ── approved → confirmed ──
    seeded("sess_a5_ok")
    store.request_confirmation("sess_a5_ok", card_id="card_ok", turn_ref=_turn("turn_2"))
    approved = store.submit_confirmation_decision(
        "sess_a5_ok", decision="approved", turn_ref=_turn("turn_3"), note="用户口头确认"
    )
    assert approved["status"] == "confirmed"
    assert approved["confirmation"]["decision"] == "approved"
    assert approved["confirmation"]["decidedAtTurn"] == "turn_3"
    assert approved["confirmation"]["confirmedDigest"] == approved["contentHash"]

    # ── revision_requested → 旧版本 superseded + 新 draft 继承已答内容 ──
    seeded("sess_a5_rev")
    q1 = store.record_question_asked(
        "sess_a5_rev",
        question="需要 Excel 格式吗？",
        why_it_matters="决定导出实现",
        applies_to="acceptance",
        turn_ref=_turn("turn_2"),
    )
    store.record_answer(
        "sess_a5_rev",
        q1,
        answer_text="要，Excel 优先",
        turn_ref=_turn("turn_3"),
        merge=[{"field": "acceptance[+]", "to": "导出的 Excel 可被 WPS 打开"}],
    )
    store.request_confirmation("sess_a5_rev", card_id="card_rev", turn_ref=_turn("turn_4"))
    revision = store.submit_confirmation_decision(
        "sess_a5_rev", decision="revision_requested", turn_ref=_turn("turn_5")
    )
    # 新 draft 版本继承已答内容（acceptance 合并项保留、台账 q1 保持 answered）。
    assert revision["version"] == 3
    assert revision["status"] == "draft"
    assert revision["supersedes"] == 2
    assert [item["criterion"] for item in revision["acceptance"]] == [
        "导出文件可打开",
        "导出的 Excel 可被 WPS 打开",
    ]
    inherited_q = next(q for q in revision["openQuestions"] if q["id"] == q1)
    assert inherited_q["status"] == "answered"
    # 旧 pending 版本被标记 superseded，索引侧由 v3.supersedes 表达。
    v2 = store.get_version("sess_a5_rev", 2)
    assert v2["status"] == "superseded"
    assert v2["supersededBy"] == 3
    assert v2["confirmation"]["decision"] == "revision_requested"
    assert store.get_current("sess_a5_rev")["version"] == 3

    # ── rejected → superseded 无后继 ──
    seeded("sess_a5_rej")
    store.request_confirmation("sess_a5_rej", card_id="card_rej", turn_ref=_turn("turn_2"))
    rejected = store.submit_confirmation_decision(
        "sess_a5_rej", decision="rejected", turn_ref=_turn("turn_3")
    )
    assert rejected["version"] == 1
    assert rejected["status"] == "superseded"
    assert rejected["supersededBy"] is None
    persisted = _persisted(isolated_store, "sess_a5_rej")
    assert persisted["currentVersion"] == 1
    assert all(v.get("supersedes") is None for v in persisted["versions"])


def test_take_confirmed_first_consumer_transitions_then_registrations_only(isolated_store):
    """A6 —— 首次 take 使 confirmed→consumed，第二个 consumer 只追加 consumedBy。"""
    store = get_intent_alignment_store()
    _open_draft(store)
    store.request_confirmation(SESSION_ID, card_id="card_a6", turn_ref=_turn("turn_2"))
    store.submit_confirmation_decision(
        SESSION_ID, decision="approved", turn_ref=_turn("turn_3")
    )

    first = store.take_confirmed(
        SESSION_ID, consumer="task_manager", ref="tasks.json#1"
    )
    assert first is not None
    assert first["status"] == "consumed"

    second = store.take_confirmed(SESSION_ID, consumer="runtime_goal", ref="")
    assert second is not None
    assert second["version"] == first["version"]
    assert second["status"] == "consumed"  # 状态不再改变

    persisted = _persisted(isolated_store)
    assert [entry["consumer"] for entry in persisted["consumedBy"]] == [
        "task_manager",
        "runtime_goal",
    ]
    assert persisted["consumedBy"][0]["ref"] == "tasks.json#1"
    assert persisted["currentVersion"] == 1  # 消费不产生新版本
    assert len(persisted["versions"]) == 1

    # 无 confirmed 工件：draft 上 take 返回 None，不抛错、不登记。
    other = "sess_a6_draft"
    store.open_or_load(other, origin=_origin())
    store.record_structured(
        other, goal="G", boundaries=["b"], constraints=["c"], acceptance=["a"], assumptions=[]
    )
    assert store.take_confirmed(other, consumer="task_manager") is None
    assert _persisted(isolated_store, other)["consumedBy"] == []
    # 全新会话无工件：返回 None 不抛错。
    assert store.take_confirmed("sess_a6_missing", consumer="task_manager") is None


def test_concurrent_append_conflict_detected(isolated_store):
    """A7 —— 两个 store 实例持相同 baseVersion 追加，后写者收版本冲突，文件保持先写者完整版本链。"""
    store_a = get_intent_alignment_store()
    _open_draft(store_a)
    q1 = store_a.record_question_asked(
        SESSION_ID,
        question="并发问题：要支持多人吗？",
        why_it_matters="决定架构",
        applies_to="constraints",
        turn_ref=_turn("turn_2"),
    )
    # store_b 在文件仍为 v1 时建立自己的 base 视图（独立实例、独立工作副本）。
    store_b = IntentAlignmentStore()
    assert store_b.open_or_load(SESSION_ID, origin=_origin())["version"] == 1

    # 先写者追加 v2 成功。
    first = store_a.record_answer(
        SESSION_ID,
        q1,
        answer_text="只支持单机",
        turn_ref=_turn("turn_3"),
        merge=[{"field": "constraints[+]", "to": "仅单机运行"}],
    )
    assert first is not None and first["version"] == 2

    # 后写者仍持 baseVersion=1：显式版本冲突，绝不静默覆盖。
    with pytest.raises(IntentAlignmentVersionConflictError):
        store_b.record_answer(
            SESSION_ID,
            q1,
            answer_text="支持多人",
            turn_ref=_turn("turn_4"),
            merge=[{"field": "constraints[+]", "to": "多人协作"}],
        )

    persisted = _persisted(isolated_store)
    assert [v["version"] for v in persisted["versions"]] == [1, 2]
    assert persisted["currentVersion"] == 2
    # 文件保持先写者完整版本链：constraints 只含先写者的追加项。
    assert persisted["versions"][1]["constraints"] == [
        "必须使用 Python 标准库",
        "仅单机运行",
    ]
    assert persisted["versions"][1]["openQuestions"][0]["answer"]["text"] == "只支持单机"


def test_corrupt_file_quarantined_not_rebuilt(isolated_store):
    """A8 —— 损坏文件改名隔离、store 返回空库，原内容不被覆盖。"""
    path = Path(isolated_store._intent_alignment_store_path(SESSION_ID))
    corrupted = path.parent / f"{SESSION_ID}.json"
    corrupted.parent.mkdir(parents=True, exist_ok=True)
    corrupted.write_text("{not valid json!!", encoding="utf-8")

    store = get_intent_alignment_store()
    # 读路径：损坏文件按空库处理。
    assert store.get_current(SESSION_ID) is None
    assert store.open_questions(SESSION_ID) == []

    # 原文件已被改名隔离（.corrupt-<ts>），原字节内容保留。
    quarantined = list(corrupted.parent.glob(f"{SESSION_ID}.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{not valid json!!"
    assert not corrupted.exists()

    # 空库可继续工作：写入产生全新工件，不触碰隔离副本。
    _open_draft(store)
    persisted = _persisted(isolated_store)
    assert persisted["currentVersion"] == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{not valid json!!"

    # 结构非法（合法 JSON 但形状错误）同样隔离。
    bad_shape = corrupted.parent / f"{SESSION_ID}.json"
    bad_shape.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    intent_alignment.reset_intent_alignment_store()
    store2 = get_intent_alignment_store()
    assert store2.get_current(SESSION_ID) is None
    quarantined_all = list(corrupted.parent.glob(f"{SESSION_ID}.json.corrupt-*"))
    assert len(quarantined_all) == 2


def test_snapshot_is_projection_not_second_storage(isolated_store):
    """A9 —— get_current 返回深拷贝，改投影不影响落盘数据（对照 tests/test_task_planner.py:74）。"""
    store = get_intent_alignment_store()
    _open_draft(store)

    snapshot = store.get_current(SESSION_ID)
    assert snapshot is not None
    snapshot["goal"]["text"] = "被篡改的目标"
    snapshot["boundaries"].append("投影污染")
    snapshot["openQuestions"].append({"id": "q_fake", "status": "asked"})
    snapshot["status"] = "confirmed"

    fresh = store.get_current(SESSION_ID)
    assert fresh["goal"] == {"text": "搭建命令行待办工具"}
    assert fresh["boundaries"] == ["不做图形界面", "范围限于单机"]
    assert fresh["openQuestions"] == []
    assert fresh["status"] == "draft"

    persisted = _persisted(isolated_store)
    assert persisted["versions"][0]["goal"] == {"text": "搭建命令行待办工具"}
    assert persisted["versions"][0]["boundaries"] == ["不做图形界面", "范围限于单机"]
    assert persisted["versions"][0]["status"] == "draft"

    # get_version 与 open_questions 同样是只读投影。
    version_view = store.get_version(SESSION_ID, 1)
    version_view["constraints"].clear()
    assert store.get_version(SESSION_ID, 1)["constraints"] == ["必须使用 Python 标准库"]
    question_views = store.open_questions(SESSION_ID)
    assert question_views == []
    question_views.append({"id": "q_fake"})
    assert store.open_questions(SESSION_ID) == []


def test_open_questions_accumulate_across_rounds(isolated_store):
    """A10 —— 问 q1、答 q1、问 q2 后 open_questions 只含 q2；q1 答案已体现在当前版本四要素。"""
    store = get_intent_alignment_store()
    _open_draft(store)

    q1 = store.record_question_asked(
        SESSION_ID,
        question="导出格式要哪种？",
        why_it_matters="决定导出模块选型",
        applies_to="constraints",
        turn_ref=_turn("turn_2"),
    )
    pending = store.open_questions(SESSION_ID)
    assert [q["id"] for q in pending] == [q1]

    store.record_answer(
        SESSION_ID,
        q1,
        answer_text="CSV 就够了",
        turn_ref=_turn("turn_3"),
        merge=[{"field": "constraints[+]", "to": "导出仅支持 CSV 格式"}],
    )
    # 答案已折算进当前版本四要素（累积，而非每轮从对话重算）。
    current = store.get_current(SESSION_ID)
    assert "导出仅支持 CSV 格式" in current["constraints"]
    assert store.open_questions(SESSION_ID) == []

    q2 = store.record_question_asked(
        SESSION_ID,
        question="需要定时导出吗？",
        why_it_matters="决定是否引入调度器",
        applies_to="constraints",
        turn_ref=_turn("turn_4"),
    )
    open_now = store.open_questions(SESSION_ID)
    assert [q["id"] for q in open_now] == [q2]
    assert q2 != q1
    # 已答问题不再出现，但其答案与台账留痕仍在当前版本上。
    assert open_now[0]["question"] == "需要定时导出吗？"
    ledger = {
        q["id"]: q["status"] for q in store.get_current(SESSION_ID)["openQuestions"]
    }
    assert ledger == {q1: "answered", q2: "asked"}
