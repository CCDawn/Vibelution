"""Inline message-level curation endpoints (include/exclude single messages).

Covers the two session routes (POST /messages/{id}/curation and GET
/curation) plus the project-level model stats route. Dataset paths are
isolated per test by monkeypatching ``PROJECT_ROOT`` to tmp_path, mirroring
the existing chat-review-candidate tests in test_web_app.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.evaluation.chat_case_lifecycle import NEGATIVE_DATASET_NAME, POSITIVE_DATASET_NAME
from core.evaluation.chat_dataset_capture import resolve_chat_dataset_paths
from core.evaluation.chat_review_queue import append_queue_event
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import chat_review_service, session_service
from tests.helpers.web_chat_state import _seed_chat_state

pytestmark = pytest.mark.serial

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


@pytest.fixture(autouse=True)
def _pin_chat_dataset_pipeline(monkeypatch):
    # Keep capture enabled deterministically regardless of the operator config,
    # and keep runtime-scene recording hermetic.
    monkeypatch.setattr(session_service.get_config().evolution.chat_dataset, "enabled", True)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *args, **kwargs: {"accepted": True})


def _seed_two_turn_session(project_root) -> None:
    _seed_chat_state(
        project_root,
        task_status="done",
        conversations=[
            {
                "conversation_id": "session-live",
                "title": "真实会话",
                "updated_at": "2026-05-18T12:00:00",
                "last_turn_status": "ready",
                "messages": [
                    {
                        "role": "user",
                        "content": "先帮我排查 lint 失败原因",
                        "timestamp": "2026-05-18T11:55:00",
                    },
                    {
                        "role": "assistant",
                        "content": "先看失败输出和相关文件，再归因。",
                        "timestamp": "2026-05-18T11:56:00",
                        "tool_calls": [{"name": "read_file_tool"}],
                    },
                    {
                        "role": "user",
                        "content": "继续修",
                        "timestamp": "2026-05-18T11:57:00",
                    },
                    {
                        "role": "assistant",
                        "content": "结论：路径大小写不一致。下一步建议修正导入并复测。",
                        "timestamp": "2026-05-18T11:58:00",
                        "metadata": {"llmUsage": {"llmModelId": "model-alpha"}},
                    },
                ],
            }
        ],
    )
    session_service._invalidate_session_list_cache()


def _assistant_messages(session_id: str = "session-live") -> list[dict]:
    response = client.get(f"/api/sessions/{session_id}")
    assert response.status_code == 200
    return [
        message
        for message in (response.json().get("messages") or [])
        if message.get("role") == "assistant"
    ]


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _turn_payload(
    turn_number: int,
    *,
    assistant_message_id: str,
    user_message_id: str,
    model_id: str = "",
) -> dict:
    metadata = {
        "mode": "chat",
        "source": "web_session",
        "assistant_message_id": assistant_message_id,
        "user_message_id": user_message_id,
    }
    if model_id:
        metadata["llm_model_id"] = model_id
    return {
        "turn_number": turn_number,
        "user_message": f"user-{turn_number}",
        "assistant_message": f"assistant-{turn_number}",
        "tool_calls": [],
        "tool_call_count": 0,
        "had_delegation": False,
        "had_explicit_conclusion": True,
        "had_next_action": True,
        "metadata": metadata,
    }


def _seed_queue_candidate(
    queue_path: Path,
    *,
    candidate_id: str,
    session_id: str,
    candidate_timestamp: str,
    turns: list[dict],
    decision: str | None = None,
    decision_timestamp: str = "",
) -> None:
    append_queue_event(
        queue_path,
        {
            "event": "candidate",
            "timestamp": candidate_timestamp,
            "candidate_id": candidate_id,
            "session_id": session_id,
            "status": "pending",
            "segment": {"conversation_turns": turns},
        },
    )
    if decision is not None:
        append_queue_event(
            queue_path,
            {
                "event": "decision",
                "timestamp": decision_timestamp,
                "candidate_id": candidate_id,
                "status": decision,
                "reviewer_note": "",
            },
        )


def test_include_and_exclude_route_messages_into_datasets(tmp_path, monkeypatch):
    _seed_two_turn_session(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    paths = resolve_chat_dataset_paths(project_root=tmp_path)
    assistants = _assistant_messages()
    first_id = assistants[0]["id"]
    second_id = assistants[1]["id"]

    include_response = client.post(
        f"/api/sessions/session-live/messages/{first_id}/curation",
        json={"action": "include"},
    )
    assert include_response.status_code == 200
    payload = include_response.json()
    assert payload["sessionId"] == "session-live"
    assert payload["messageId"] == first_id
    assert payload["action"] == "include"
    assert payload["status"] == "included"
    assert payload["candidateId"] == "session-live_t0001_0001"
    assert payload["caseId"] == "session-live_t0001_0001"
    assert payload["modelId"] == ""
    assert payload["datasetName"] == POSITIVE_DATASET_NAME

    approved = _read_jsonl(paths.approved_jsonl_path)
    assert len(approved) == 1
    assert approved[0]["case_id"] == "session-live_t0001_0001"
    assert approved[0]["approval"]["status"] == "positive"
    assert approved[0]["conversation_turns"][0]["metadata"]["assistant_message_id"] == first_id
    assert approved[0]["conversation_turns"][0]["metadata"]["user_message_id"]

    # Replaying the same decision is idempotent and must not duplicate rows.
    replay_response = client.post(
        f"/api/sessions/session-live/messages/{first_id}/curation",
        json={"action": "include"},
    )
    assert replay_response.status_code == 200
    assert replay_response.json()["candidateId"] == "session-live_t0001_0001"
    assert len(_read_jsonl(paths.approved_jsonl_path)) == 1

    # The fragment already lives in the positive dataset: exclude conflicts.
    conflict_response = client.post(
        f"/api/sessions/session-live/messages/{first_id}/curation",
        json={"action": "exclude"},
    )
    assert conflict_response.status_code == 409

    # Excluding the second message ends its fragment exactly at that message.
    exclude_response = client.post(
        f"/api/sessions/session-live/messages/{second_id}/curation",
        json={"action": "exclude"},
    )
    assert exclude_response.status_code == 200
    payload = exclude_response.json()
    assert payload["action"] == "exclude"
    assert payload["status"] == "excluded"
    assert payload["candidateId"] == "session-live_t0001_0002"
    assert payload["modelId"] == "model-alpha"
    assert payload["datasetName"] == NEGATIVE_DATASET_NAME
    negative = _read_jsonl(paths.negative_jsonl_path)
    assert len(negative) == 1
    assert negative[0]["case_id"] == "session-live_t0001_0002"
    assert negative[0]["review"]["reason_code"] == "inline_exclude"
    assert negative[0]["review"]["error_type"] == "user_reported"
    assert negative[0]["conversation_turns"][-1]["metadata"]["assistant_message_id"] == second_id
    assert negative[0]["conversation_turns"][-1]["metadata"]["llm_model_id"] == "model-alpha"

    state_response = client.get("/api/sessions/session-live/curation")
    assert state_response.status_code == 200
    state = state_response.json()
    assert state["sessionId"] == "session-live"
    assert state["captureEnabled"] is True
    assert second_id in {item["messageId"] for item in state["items"]}


def test_curation_state_derives_items_and_counts_from_queue(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    queue_path = resolve_chat_dataset_paths(project_root=tmp_path).review_queue_path

    _seed_queue_candidate(
        queue_path,
        candidate_id="cand-a",
        session_id="session-live",
        candidate_timestamp="2026-05-18T12:00:00+00:00",
        turns=[_turn_payload(1, assistant_message_id="msg-shared", user_message_id="msg-u1")],
        decision="positive",
        decision_timestamp="2026-05-18T12:01:00+00:00",
    )
    _seed_queue_candidate(
        queue_path,
        candidate_id="cand-b",
        session_id="session-live",
        candidate_timestamp="2026-05-18T12:05:00+00:00",
        turns=[
            _turn_payload(1, assistant_message_id="msg-shared", user_message_id="msg-u1"),
            _turn_payload(2, assistant_message_id="msg-x", user_message_id="msg-u2", model_id="model-x"),
        ],
        decision="negative",
        decision_timestamp="2026-05-18T12:06:00+00:00",
    )
    _seed_queue_candidate(
        queue_path,
        candidate_id="cand-c",
        session_id="session-live",
        candidate_timestamp="2026-05-18T12:02:00+00:00",
        turns=[_turn_payload(1, assistant_message_id="msg-y", user_message_id="msg-u3", model_id="model-y")],
        decision="positive",
        decision_timestamp="2026-05-18T12:03:00+00:00",
    )
    # Another session: never appears in this session's state.
    _seed_queue_candidate(
        queue_path,
        candidate_id="cand-d",
        session_id="session-other",
        candidate_timestamp="2026-05-18T12:02:00+00:00",
        turns=[_turn_payload(1, assistant_message_id="msg-z", user_message_id="msg-u4")],
        decision="positive",
        decision_timestamp="2026-05-18T12:03:00+00:00",
    )
    # Pending candidates carry no curation decision yet.
    _seed_queue_candidate(
        queue_path,
        candidate_id="cand-e",
        session_id="session-live",
        candidate_timestamp="2026-05-18T12:04:00+00:00",
        turns=[_turn_payload(1, assistant_message_id="msg-pending", user_message_id="msg-u5")],
    )
    # Discarded fragments stay out of the curation state.
    _seed_queue_candidate(
        queue_path,
        candidate_id="cand-f",
        session_id="session-live",
        candidate_timestamp="2026-05-18T11:58:00+00:00",
        turns=[_turn_payload(1, assistant_message_id="msg-discarded", user_message_id="msg-u6")],
        decision="discard",
        decision_timestamp="2026-05-18T11:59:00+00:00",
    )

    response = client.get("/api/sessions/session-live/curation")
    assert response.status_code == 200
    payload = response.json()
    # msg-shared appears in cand-a (positive) and cand-b (negative); the latest
    # reviewed_at decision (cand-b, 12:06) wins.
    assert payload == {
        "sessionId": "session-live",
        "captureEnabled": True,
        "items": [
            {
                "messageId": "msg-y",
                "action": "include",
                "modelId": "model-y",
                "candidateId": "cand-c",
                "decidedAt": "2026-05-18T12:03:00+00:00",
            },
            {
                "messageId": "msg-shared",
                "action": "exclude",
                "modelId": "",
                "candidateId": "cand-b",
                "decidedAt": "2026-05-18T12:06:00+00:00",
            },
            {
                "messageId": "msg-x",
                "action": "exclude",
                "modelId": "model-x",
                "candidateId": "cand-b",
                "decidedAt": "2026-05-18T12:06:00+00:00",
            },
        ],
        "countsByModel": [
            {"modelId": "", "included": 0, "excluded": 1},
            {"modelId": "model-x", "included": 0, "excluded": 1},
            {"modelId": "model-y", "included": 1, "excluded": 0},
        ],
    }

    missing = client.get("/api/sessions/missing-session/curation")
    assert missing.status_code == 404


def test_curation_existence_matches_legacy_set_for_hidden_sessions(tmp_path, monkeypatch):
    """404-semantics equivalence: sessions hidden from the index still resolve.

    The legacy existence oracle was _load_conversations() membership, which has
    no hidden/internal filtering. The fast path must agree for every case:
    found stays found (including index-hidden sessions), missing stays 404.
    """

    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service.agent_directory_service, "PROJECT_ROOT", tmp_path)

    visible = session_service.create_chat_session(
        title="可见策展会话", lightweight=True
    )
    hidden = session_service.create_chat_session(
        title="索引隐藏策展会话",
        conversation_index_kind=session_service.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN,
        lightweight=True,
        activate=False,
    )
    session_service._invalidate_session_list_cache()

    # The hidden session is genuinely excluded from the visible session index.
    visible_ids = {str(item.get("id") or "").strip() for item in session_service.list_sessions()}
    assert visible["id"] in visible_ids
    assert hidden["id"] not in visible_ids

    # The legacy oracle still finds it, and the endpoint must match it exactly.
    legacy_ids = {
        str(item.get("id") or "").strip()
        for item in session_service._load_conversations()[1]
    }
    assert hidden["id"] in legacy_ids
    for session_id, expected_status in (
        (visible["id"], 200),
        (hidden["id"], 200),
        ("session-missing", 404),
    ):
        assert (session_id in legacy_ids) is (expected_status == 200)
        response = client.get(f"/api/sessions/{session_id}/curation")
        assert response.status_code == expected_status

    payload = client.get(f"/api/sessions/{hidden['id']}/curation")
    assert payload.status_code == 200
    assert payload.json() == {
        "sessionId": hidden["id"],
        "captureEnabled": True,
        "items": [],
        "countsByModel": [],
    }


def test_curation_state_returns_empty_for_fresh_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live/curation")
    assert response.status_code == 200
    assert response.json() == {
        "sessionId": "session-live",
        "captureEnabled": True,
        "items": [],
        "countsByModel": [],
    }


def test_model_curation_stats_aggregates_decided_turns(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    queue_path = resolve_chat_dataset_paths(project_root=tmp_path).review_queue_path

    _seed_queue_candidate(
        queue_path,
        candidate_id="stats-a",
        session_id="session-one",
        candidate_timestamp="2026-05-18T12:00:00+00:00",
        turns=[
            _turn_payload(1, assistant_message_id="a-1", user_message_id="u-1", model_id="model-a"),
            _turn_payload(2, assistant_message_id="a-2", user_message_id="u-2", model_id="model-a"),
        ],
        decision="positive",
        decision_timestamp="2026-05-18T12:01:00+00:00",
    )
    _seed_queue_candidate(
        queue_path,
        candidate_id="stats-b",
        session_id="session-two",
        candidate_timestamp="2026-05-18T12:00:00+00:00",
        turns=[_turn_payload(1, assistant_message_id="b-1", user_message_id="u-3", model_id="model-b")],
        decision="negative",
        decision_timestamp="2026-05-18T12:01:00+00:00",
    )
    _seed_queue_candidate(
        queue_path,
        candidate_id="stats-c",
        session_id="session-three",
        candidate_timestamp="2026-05-18T12:00:00+00:00",
        turns=[_turn_payload(1, assistant_message_id="c-1", user_message_id="u-4")],
        decision="negative",
        decision_timestamp="2026-05-18T12:01:00+00:00",
    )
    # Pending items never contribute to the stats.
    _seed_queue_candidate(
        queue_path,
        candidate_id="stats-d",
        session_id="session-four",
        candidate_timestamp="2026-05-18T12:00:00+00:00",
        turns=[_turn_payload(1, assistant_message_id="d-1", user_message_id="u-5", model_id="model-a")],
    )

    response = client.get("/api/chat-review/model-curation-stats")
    assert response.status_code == 200
    assert response.json() == {
        "models": [
            {"modelId": "model-a", "included": 2, "excluded": 0},
            {"modelId": "", "included": 0, "excluded": 1},
            {"modelId": "model-b", "included": 0, "excluded": 1},
        ]
    }


def test_set_message_curation_rejects_unsupported_inputs(tmp_path, monkeypatch):
    _seed_two_turn_session(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    assistants = _assistant_messages()
    first_id = assistants[0]["id"]
    detail = client.get("/api/sessions/session-live").json()
    user_id = next(
        message["id"] for message in detail["messages"] if message.get("role") == "user"
    )

    invalid_action = client.post(
        f"/api/sessions/session-live/messages/{first_id}/curation",
        json={"action": "maybe"},
    )
    assert invalid_action.status_code == 422

    missing_session = client.post(
        "/api/sessions/missing-session/messages/whatever/curation",
        json={"action": "include"},
    )
    assert missing_session.status_code == 404

    missing_message = client.post(
        "/api/sessions/session-live/messages/session-live-message-999/curation",
        json={"action": "include"},
    )
    assert missing_message.status_code == 422

    user_message = client.post(
        f"/api/sessions/session-live/messages/{user_id}/curation",
        json={"action": "include"},
    )
    assert user_message.status_code == 422


def test_set_message_curation_rejects_unsettled_messages(tmp_path, monkeypatch):
    _seed_two_turn_session(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    original_loader = session_service._session_ledger_visible_messages
    assistants = _assistant_messages()
    first_id = assistants[0]["id"]

    def _loader_with_status(status: str):
        def _resolve(session_id: str) -> list[dict]:
            messages = original_loader(session_id)
            for item in messages:
                if str(item.get("id") or "") == first_id:
                    item["status"] = status
            return messages

        return _resolve

    for status in ("running", "failed"):
        monkeypatch.setattr(
            session_service,
            "_session_ledger_visible_messages",
            _loader_with_status(status),
        )
        response = client.post(
            f"/api/sessions/session-live/messages/{first_id}/curation",
            json={"action": "include"},
        )
        assert response.status_code == 422
        assert "收口" in response.json()["detail"] or "streaming" in response.json()["detail"].lower()


def test_set_message_curation_requires_enabled_capture(tmp_path, monkeypatch):
    _seed_two_turn_session(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service.get_config().evolution.chat_dataset, "enabled", False)
    assistants = _assistant_messages()
    first_id = assistants[0]["id"]

    response = client.post(
        f"/api/sessions/session-live/messages/{first_id}/curation",
        json={"action": "include"},
    )
    assert response.status_code == 422
    assert "未启用" in response.json()["detail"] or "disabled" in response.json()["detail"].lower()

    state = client.get("/api/sessions/session-live/curation")
    assert state.status_code == 200
    assert state.json()["captureEnabled"] is False
