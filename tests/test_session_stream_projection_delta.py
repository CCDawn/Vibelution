"""Incremental turnItems projection + witness-backed write edge compression.

覆盖三组契约：
1. 黄金对拍：同一流式序列，增量投影每帧的 turnItems 与权威全量重建逐字节一致；
2. 成本：纯文本追加帧走增量路径，第 K 帧的 witness 哈希量与 K（总长）无关；
3. wire 等价：witness 帧与旧全量重算帧在 SSE 写边的压缩输出完全一致（含滞后
   游标、重写回退、剪枝历史回退），且 witness 字段不出现在任何输出帧上。
"""

from __future__ import annotations

import json
import queue
import threading
from types import SimpleNamespace

import pytest

from core.web.services import session_service
from core.web.services.session import publish
from core.web.services.session import stream_projection_delta as spd
from core.web.services.session.stream_projection_delta import (
    WITNESS_FIELD,
    TurnDeltaProjector,
    drop_turn_delta_projector,
    reset_turn_delta_projectors_for_tests,
)
from core.web.services.session.stream_transport_delta import SessionStreamItemDelta


@pytest.fixture(autouse=True)
def _reset_projectors():
    reset_turn_delta_projectors_for_tests()
    yield
    reset_turn_delta_projectors_for_tests()


def _frame_inputs(content: str, thought: str, *, stage: str = "assistant_response", done: bool = False, ledger_sequence: int = 7):
    return dict(
        message_id="session-delta-message-turn-1",
        content=content,
        thought=thought,
        feedback_events=[],
        tool_calls=[],
        mental_snapshot=None,
        stage=stage,
        done=done,
        ledger_sequence=ledger_sequence,
    )


def _authority_items(session_id: str, turn_id: str, inputs: dict) -> list[dict]:
    codex_transcript = session_service._build_codex_transcript_projection(
        message_id=inputs["message_id"],
        content=inputs["content"],
        feedback_events=inputs["feedback_events"],
        tool_calls=inputs["tool_calls"],
        streaming=not inputs["done"],
    )
    return session_service._build_session_turn_items_projection(
        session_id=session_id,
        turn_id=turn_id,
        message_id=inputs["message_id"],
        content=inputs["content"],
        thought=inputs["thought"],
        mental_snapshot=inputs["mental_snapshot"],
        codex_transcript=codex_transcript,
        done=inputs["done"],
        source="assistant_delta",
        stage=inputs["stage"],
    )


def _canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


STREAM_SCRIPT = [
    # (stage, thought, content, done) — thinking → answer → tool → terminal
    ("model_thinking", "先看日志结构。", "", False),
    ("model_thinking", "先看日志结构。再查投影顺序。", "", False),
    ("assistant_response", "先看日志结构。再查投影顺序。", "第一段回答。", False),
    ("assistant_response", "先看日志结构。再查投影顺序。", "第一段回答。第二段继续。", False),
    ("assistant_response", "先看日志结构。再查投影顺序。补充推理。", "第一段回答。第二段继续。", False),
    ("assistant_response", "先看日志结构。再查投影顺序。补充推理。", "第一段回答。第二段继续。", True),
]


def test_incremental_frames_match_authority_rebuild_byte_for_byte():
    session_id = "proj-golden"
    turn_id = "turn-golden"
    projector = TurnDeltaProjector(session_id, turn_id)
    modes = []
    for stage, thought, content, done in STREAM_SCRIPT:
        inputs = _frame_inputs(content, thought, stage=stage, done=done)
        items, witness = projector.frame_items(**inputs)
        modes.append(projector.mode)
        authority = _authority_items(session_id, turn_id, inputs)
        assert _canonical_json(items) == _canonical_json(authority)
        # 每帧 witness 的指纹集合必须覆盖全部 item 身份，供写边判等。
        identities = {spd.item_identity(item) for item in items}
        identities.discard(None)
        assert set(witness.fingerprints) == identities
    # 纯文本追加帧必须真的走增量路径，而不是恒定回退全量重建。
    assert modes == ["rebuild", "incremental", "rebuild", "incremental", "incremental", "rebuild"]


def test_frame_k_witness_cost_is_independent_of_k():
    session_id = "proj-cost"
    turn_id = "turn-cost"
    projector = TurnDeltaProjector(session_id, turn_id)
    chunk = "x" * 64
    witness_bytes_by_frame = []
    modes = []
    for index in range(120):
        inputs = _frame_inputs(content=chunk * (index + 1), thought="")
        items, _witness = projector.frame_items(**inputs)
        witness_bytes_by_frame.append(projector.last_frame_witness_bytes)
        modes.append(projector.mode)
        assert items
    # 第一帧全量重建要哈希整个 body；此后每帧只碰增量。
    assert witness_bytes_by_frame[0] >= len(chunk)
    assert all(mode == "incremental" for mode in modes[1:])
    assert witness_bytes_by_frame[-1] <= len(chunk) + 64  # ~appended bytes + digest slack
    # 若成本随帧数增长，第 100 帧之后的均值会显著高于前 10 帧——此处必须持平。
    early = max(witness_bytes_by_frame[1:11])
    late = max(witness_bytes_by_frame[100:])
    assert late <= early + 64


def test_witness_frames_and_legacy_recompute_produce_identical_wire_output():
    items_history: list[list[dict]] = []
    projector = TurnDeltaProjector("proj-wire", "turn-wire")
    for stage, thought, content, done in STREAM_SCRIPT:
        inputs = _frame_inputs(content, thought, stage=stage, done=done)
        items, witness = projector.frame_items(**inputs)
        items_history.append((items, witness, inputs))

    for items, witness, inputs in items_history:
        event = {
            "type": "assistant_delta",
            "sessionId": "proj-wire",
            "turnId": "turn-wire",
            "deltaSeq": 1,
            "deltaSeqFrom": 1,
            "stage": inputs["stage"],
            "done": inputs["done"],
            "turnItems": items,
            WITNESS_FIELD: witness,
        }
        legacy_event = {key: value for key, value in event.items() if key != WITNESS_FIELD}
        witness_compact = SessionStreamItemDelta().compact(event)
        legacy_compact = SessionStreamItemDelta().compact(legacy_event)
        assert WITNESS_FIELD not in witness_compact
        assert _canonical_json(witness_compact) == _canonical_json(legacy_compact)
        # 共享快照不被原地修改。
        assert event.get("turnItems") == items


def test_lagged_connection_append_matches_legacy_prefix_verification():
    projector = TurnDeltaProjector("proj-lag", "turn-lag")
    frames = []
    for index in range(4):
        inputs = _frame_inputs(content="答案" * (index + 1), thought="")
        items, witness = projector.frame_items(**inputs)
        frames.append((items, witness))

    def compact_sequence(witnessed: bool) -> list[dict]:
        delta = SessionStreamItemDelta()
        output = []
        for index, (items, witness) in enumerate(frames):
            if index == 2:
                # 连接在第三帧被跳过（coalesce/丢弃），游标停留在第一帧。
                continue
            event = {
                "type": "assistant_delta",
                "sessionId": "proj-lag",
                "turnId": "turn-lag",
                "turnItems": items,
                "done": False,
            }
            if witnessed:
                event[WITNESS_FIELD] = witness
            output.append(delta.compact(event))
        return output

    witnessed = compact_sequence(True)
    legacy = compact_sequence(False)
    assert _canonical_json(witnessed) == _canonical_json(legacy)
    # 跳帧后恢复帧必须覆盖整段跳过的增量（append 或全行，两条路径一致）。
    recovered = witnessed[-1]
    covers = (
        any(entry["baseLength"] == 4 for entry in recovered.get("turnItemAppends") or [])
        or bool(recovered.get("turnItems"))
    )
    assert covers


def test_pruned_prefix_history_falls_back_to_full_row():
    projector = TurnDeltaProjector("proj-prune", "turn-prune")
    items, witness = projector.frame_items(**_frame_inputs(content="hello", thought=""))
    event = {
        "type": "assistant_delta",
        "sessionId": "proj-prune",
        "turnId": "turn-prune",
        "turnItems": items,
        "done": False,
        WITNESS_FIELD: witness,
    }
    delta = SessionStreamItemDelta()
    delta.compact(event)

    grown_items, grown_witness = projector.frame_items(**_frame_inputs(content="hello world", thought=""))
    pruned_witness = spd.AssistantDeltaFrameWitness(
        fingerprints=grown_witness.fingerprints,
        text_cursors=grown_witness.text_cursors,
        prefix_history={},  # 历史被剪掉：无法验证游标前缀
    )
    compact = delta.compact(
        {
            "type": "assistant_delta",
            "sessionId": "proj-prune",
            "turnId": "turn-prune",
            "turnItems": grown_items,
            "done": False,
            WITNESS_FIELD: pruned_witness,
        }
    )
    # 无法验证前缀时回退全行，绝不猜测拼接。
    assert compact["turnItems"] == grown_items
    assert "turnItemAppends" not in compact


def test_completed_row_with_journal_items_is_never_a_carrier():
    """journal 已提交的 completed 行不可作为增量载体：authority 不延伸 committed 行。"""

    projector = TurnDeltaProjector("proj-journal", "turn-journal")
    committed_reasoning = {
        "version": 3,
        "id": "reasoning:0",
        "itemId": "reasoning",
        "sessionId": "proj-journal",
        "turnId": "turn-journal",
        "type": "reasoning",
        "status": "completed",
        "revision": 0,
        "sequence": 1,
        "text": "已提交的推理段。",
    }
    projector._content = "已提交的推理段。"
    projector._thought = "已提交的推理段。"
    projector._items = [committed_reasoning]
    projector._refresh_witnesses(projector._items)
    projector._record_carriers(projector._items, journal_has_turn_items=True)
    assert projector._thought_carrier is None
    assert projector._content_carrier is None
    # 同一行在 journal 为空时（live 建行）才是可延伸载体。
    projector._record_carriers(projector._items, journal_has_turn_items=False)
    assert projector._thought_carrier == (0, ("item", "reasoning"))


def test_terminal_frame_drops_projector_and_next_turn_rebuilds():
    session_id = "proj-cleanup"
    turn_id = "turn-cleanup"
    projector = spd.turn_delta_projector(session_id, turn_id)
    assert projector is not None
    projector.frame_items(**_frame_inputs(content="第一帧", thought=""))
    drop_turn_delta_projector(session_id, turn_id)
    assert spd.turn_delta_projector(session_id, turn_id) is not projector
    fresh = spd.turn_delta_projector(session_id, turn_id)
    items, _witness = fresh.frame_items(**_frame_inputs(content="第一帧", thought=""))
    assert fresh.mode == "rebuild"
    assert items


def test_projector_registry_is_bounded():
    for index in range(spd._MAX_PROJECTORS + 8):
        spd.turn_delta_projector(f"proj-cap-{index}", "turn-cap")
    assert len(spd._PROJECTORS) <= spd._MAX_PROJECTORS


# ---------------------------------------------------------------------------
# publish 集成：事件带 witness、wire 无 witness、遥测带 projectionMode
# ---------------------------------------------------------------------------

class _PublishDeltaService:
    """Minimal service facade binding the real publish-layer delta helpers."""

    _SESSION_STREAM_SUBSCRIBERS_LOCK = threading.Lock()
    _SESSION_STREAM_SUBSCRIBERS: dict = {}
    _SESSION_STREAM_DELTA_SEQ: dict = {}
    _SESSION_STREAM_LAST_SNAPSHOT_LOCK = threading.Lock()
    _SESSION_STREAM_LAST_SNAPSHOT_AT: dict = {}
    _SESSION_STREAM_THROTTLED_COUNTS: dict = {}

    _next_session_delta_seq = staticmethod(publish._next_session_delta_seq)
    _merge_session_assistant_delta_events = staticmethod(publish._merge_session_assistant_delta_events)
    _assistant_delta_recovery_stream_event = staticmethod(publish._assistant_delta_recovery_stream_event)
    _coalesce_session_assistant_delta_queue = staticmethod(publish._coalesce_session_assistant_delta_queue)
    _put_session_stream_event = staticmethod(publish._put_session_stream_event)

    def __init__(self) -> None:
        self.ledger_seq = 5
        self.telemetry: list[dict] = []

    def _perf_counter(self) -> float:
        return 0.0

    def _elapsed_ms(self, _started_at: float) -> int:
        return 0

    def _now_timestamp(self) -> str:
        return "2026-10-06T00:00:00Z"

    def _session_ledger_sequence(self, _session_id: str) -> int:
        return self.ledger_seq

    def _live_assistant_message_id(self, session_id: str, turn_id: str) -> str:
        return f"{session_id}-message-{turn_id}"

    def _build_codex_transcript_projection(self, **_kwargs):
        return None

    def _build_session_turn_items_projection(self, **kwargs):
        content = str(kwargs.get("content") or "")
        items = []
        if content:
            items.append(
                {
                    "version": 3,
                    "id": "answer:0",
                    "itemId": "answer",
                    "sessionId": kwargs.get("session_id"),
                    "turnId": kwargs.get("turn_id"),
                    "type": "agent_message",
                    "phase": "final_answer",
                    "status": "completed" if kwargs.get("done") else "running",
                    "revision": 0,
                    "sequence": 1,
                    "text": content,
                }
            )
        return items

    def _record_session_assistant_delta_published_event(self, **kwargs):
        self.telemetry.append(kwargs)


@pytest.fixture()
def delta_publish_env(monkeypatch):
    service = _PublishDeltaService()
    monkeypatch.setattr(publish, "_service", lambda: service)
    reset_turn_delta_projectors_for_tests()
    yield service
    reset_turn_delta_projectors_for_tests()


def test_publish_attaches_witness_and_wire_strips_it(delta_publish_env):
    service = delta_publish_env
    subscriber = queue.Queue()
    publish._register_session_stream_subscriber("session-live", subscriber)
    first = None
    second = None
    try:
        publish._publish_session_assistant_delta("session-live", _state("第一帧"))
        first = subscriber.get_nowait()
        publish._publish_session_assistant_delta("session-live", _state("第一帧第二帧"))
        second = subscriber.get_nowait()
    finally:
        publish._unregister_session_stream_subscriber("session-live", subscriber)

    assert first is not None and second is not None
    assert WITNESS_FIELD in first and WITNESS_FIELD in second
    assert first["turnItems"][0]["text"] == "第一帧"
    assert second["turnItems"][0]["text"] == "第一帧第二帧"

    delta = SessionStreamItemDelta()
    first_wire = delta.compact(dict(first))
    second_wire = delta.compact(dict(second))
    assert WITNESS_FIELD not in first_wire and WITNESS_FIELD not in second_wire
    assert first_wire["turnItems"] and second_wire["turnItems"] == []
    assert second_wire["turnItemAppends"][0]["appendedText"] == "第二帧"

    assert service.telemetry[-1]["projection_mode"] == "incremental"
    assert service.telemetry[0]["projection_mode"] == "rebuild"


def _state(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        turn_id="turn-1",
        stage="assistant_response",
        updated_at="",
        content=content,
        thought="",
        mental_snapshot=None,
        feedback_events=[],
        tool_calls=[],
    )


def test_publish_terminal_frame_drops_projector(delta_publish_env):
    service = delta_publish_env
    subscriber = queue.Queue()
    publish._register_session_stream_subscriber("session-live", subscriber)
    try:
        publish._publish_session_assistant_delta("session-live", _state("增长"), done=True)
    finally:
        publish._unregister_session_stream_subscriber("session-live", subscriber)

    assert service.telemetry[-1]["projection_mode"] == "rebuild"
    assert spd._PROJECTORS.get(("session-live", "turn-1")) is None
