"""Delivery-failure reports land in the personal-assistant inbox, bounded and
never breaking the caller's path (endpoint, in-process rate limit, shell-side
supervisor-event proxy)."""


import pytest

from fastapi.testclient import TestClient


from core.web.app import create_app

from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

from core.web.services import agent_directory_service as directory

from core.web.services import (
    personal_attention_service as attention,
    runtime_scene_service,
)

from tests.test_personal_assistant_service import (
    finance_env as _finance_env,
)

from tests.test_personal_assistant_service import personal_env as _personal_env


finance_env = _finance_env

personal_env = _personal_env


@pytest.fixture(autouse=True)
def _fresh_reporter():
    attention.reset_attention_delivery_failure_reporter_for_tests()
    yield
    attention.reset_attention_delivery_failure_reporter_for_tests()


@pytest.fixture
def client(personal_env):
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


@pytest.fixture
def assistant_agent_id(client) -> str:
    created = client.post("/api/personal-assistant", json={})
    assert created.status_code == 200, created.text
    return created.json()["assistant"]["agentId"]


def _delivery_failures(agent_id: str) -> list[dict]:
    return [
        row
        for row in directory.list_agent_inbox_messages_for_agent(
            agent_id, limit=50, status="pending"
        )
        if row.get("kind") == attention.ATTENTION_DELIVERY_FAILURE_INBOX_KIND
    ]


def test_endpoint_files_renderer_failure_into_assistant_inbox(client, assistant_agent_id):
    response = client.post(
        "/api/personal-assistant/attention/report-delivery-failure",
        json={
            "id": "kr-1",
            "kind": "knowledge_review",
            "severity": "high",
            "stage": "renderer",
            "reason": "notify rejected: shell gone",
            "title": "知识待复核",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"accepted": True, "reason": ""}
    rows = _delivery_failures(assistant_agent_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["promptEligible"] is True
    assert row["createdBy"] == "attention_monitor"
    assert row["status"] == "pending"
    metadata = row["metadata"]
    assert metadata["stage"] == "renderer"
    assert metadata["attentionId"] == "kr-1"
    assert metadata["kind"] == "knowledge_review"
    assert metadata["severity"] == "high"
    assert "notify rejected: shell gone" in metadata["reason"]
    assert row["targetAgentId"] == assistant_agent_id
    assert "kr-1" in row["content"] and "前端渲染通道" in row["content"]
    # prompt_eligible 行可进入下一轮上下文（汇报语义，不唤醒）。
    prompt_rows = directory.list_agent_inbox_messages_for_agent(
        assistant_agent_id, limit=50, status="pending", prompt_eligible_only=True
    )
    assert any(item["messageId"] == row["messageId"] for item in prompt_rows)


def test_endpoint_rejects_extra_fields_and_invalid_stage(client, assistant_agent_id):
    extra = client.post(
        "/api/personal-assistant/attention/report-delivery-failure",
        json={"id": "kr-x", "kind": "anomaly", "stage": "renderer", "reason": "r", "surprise": 1},
    )
    assert extra.status_code == 422
    bad_stage = client.post(
        "/api/personal-assistant/attention/report-delivery-failure",
        json={"id": "kr-x", "kind": "anomaly", "stage": "kernel", "reason": "r"},
    )
    assert bad_stage.status_code == 422
    assert _delivery_failures(assistant_agent_id) == []


def test_service_degrades_without_assistant_and_on_invalid_stage(personal_env):
    assert attention.report_attention_delivery_failure(
        id="kr-2", kind="anomaly", stage="renderer", reason="boom"
    ) == {"accepted": False, "reason": "no_assistant"}
    assert attention.report_attention_delivery_failure(
        id="kr-2", kind="anomaly", stage="nowhere", reason="boom"
    ) == {"accepted": False, "reason": "invalid_stage"}


def test_hourly_bucket_limit_and_same_id_dedup_window(client, assistant_agent_id):
    limit = attention.MAX_DELIVERY_FAILURES_PER_BUCKET_PER_HOUR
    for index in range(limit):
        result = attention.report_attention_delivery_failure(
            id=f"kr-{index}", kind="knowledge_review", stage="renderer", reason="r"
        )
        assert result == {"accepted": True, "reason": ""}
    # 同 (kind, stage) 桶小时上限：第 7 条被限流，不再写收件箱。
    assert attention.report_attention_delivery_failure(
        id="kr-extra", kind="knowledge_review", stage="renderer", reason="r"
    ) == {"accepted": False, "reason": "rate_limited"}
    # 同 id 在去重窗口内重复失败只报一次。
    assert attention.report_attention_delivery_failure(
        id="kr-0", kind="knowledge_review", stage="renderer", reason="r"
    ) == {"accepted": False, "reason": "duplicate"}
    # 不同 stage 是独立桶：壳通道不受渲染通道限流影响。
    assert attention.report_attention_delivery_failure(
        id="kr-0", kind="knowledge_review", stage="shell", reason="r"
    ) == {"accepted": True, "reason": ""}
    assert len(_delivery_failures(assistant_agent_id)) == limit + 1


def _accept_supervisor_scene(monkeypatch):
    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event",
        lambda *args, **_kwargs: {"accepted": True, "runtimeSceneId": "scene-1"},
    )


def test_supervisor_invalid_event_proxies_shell_report_into_inbox(
    personal_env, monkeypatch, assistant_agent_id
):
    _accept_supervisor_scene(monkeypatch)
    result = runtime_scene_service.record_electron_supervisor_event(
        "electron.human_attention_notification.invalid",
        message="Human attention notification payload was rejected.",
        fields={
            "id": "kr-9",
            "kind": "anomaly",
            "severity": "critical",
            "delivered": "invalid_payload",
        },
    )
    assert result["accepted"] is True
    rows = _delivery_failures(assistant_agent_id)
    assert len(rows) == 1
    metadata = rows[0]["metadata"]
    assert metadata["stage"] == "shell"
    assert metadata["attentionId"] == "kr-9"
    assert metadata["kind"] == "anomaly"
    assert "桌面壳通道" in rows[0]["content"]


def test_supervisor_invalid_event_without_id_falls_back_to_unknown(
    personal_env, monkeypatch, assistant_agent_id
):
    _accept_supervisor_scene(monkeypatch)
    runtime_scene_service.record_electron_supervisor_event(
        "electron.human_attention_notification.invalid",
        message="payload must be an object",
        fields={"reason": "payload must be an object"},
    )
    rows = _delivery_failures(assistant_agent_id)
    assert len(rows) == 1
    assert rows[0]["metadata"]["attentionId"] == "unknown"
    assert rows[0]["metadata"]["kind"] == "unknown"
    assert "payload must be an object" in rows[0]["metadata"]["reason"]


def test_supervisor_delivered_event_does_not_proxy(
    personal_env, monkeypatch, assistant_agent_id
):
    _accept_supervisor_scene(monkeypatch)
    result = runtime_scene_service.record_electron_supervisor_event(
        "electron.human_attention_notification.delivered",
        message="delivered via system_notification",
        fields={"id": "kr-2", "kind": "anomaly", "delivered": "system_notification"},
    )
    assert result["accepted"] is True
    assert _delivery_failures(assistant_agent_id) == []


def test_supervisor_proxy_swallows_reporter_failures(personal_env, monkeypatch):
    _accept_supervisor_scene(monkeypatch)

    def broken(*_args, **_kwargs):
        raise RuntimeError("reporter exploded")

    monkeypatch.setattr(attention, "report_attention_delivery_failure", broken)
    result = runtime_scene_service.record_electron_supervisor_event(
        "electron.human_attention_notification.invalid",
        message="rejected",
        fields={"id": "kr-3", "kind": "anomaly", "delivered": "invalid_payload"},
    )
    # 事件记录本身不受上报失败影响。
    assert result["accepted"] is True
