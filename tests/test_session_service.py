from types import SimpleNamespace
import queue

from core.ui.chat_state import load_chat_state, save_chat_state
from core.web.services import session_service
from core.web.services import agent_directory_service


def test_session_stream_coalescing_preserves_assistant_delta_events():
    subscriber = queue.Queue()
    subscriber.put_nowait({"type": "assistant_delta", "contentDelta": "你"})
    subscriber.put_nowait({"type": "assistant_delta", "contentDelta": "好"})

    dropped = session_service._coalesce_session_stream_queue(subscriber, event_type="assistant_delta")

    assert dropped == 0
    assert subscriber.get_nowait()["contentDelta"] == "你"
    assert subscriber.get_nowait()["contentDelta"] == "好"
    assert session_service._SESSION_STREAM_COALESCED_EVENT_TYPES == {"session_detail"}


def test_session_stream_full_queue_prefers_dropping_snapshots_before_assistant_delta():
    subscriber = queue.Queue(maxsize=2)
    subscriber.put_nowait({"type": "assistant_delta", "contentDelta": "你"})
    subscriber.put_nowait({"type": "session_detail", "ledgerSeq": 1})

    delivered, dropped = session_service._put_session_stream_event(
        subscriber,
        {"type": "assistant_delta", "content": "你好", "contentDelta": "好", "replaceContent": False},
        recover_assistant_delta_on_drop=True,
    )

    assert delivered is True
    assert dropped == 1
    first = subscriber.get_nowait()
    second = subscriber.get_nowait()
    assert first["type"] == "assistant_delta"
    assert first["contentDelta"] == "你"
    assert second["type"] == "assistant_delta"
    assert second["contentDelta"] == "好"
    assert second["replaceContent"] is False


def test_session_stream_full_queue_recovers_when_old_assistant_delta_must_drop():
    subscriber = queue.Queue(maxsize=1)
    subscriber.put_nowait({"type": "assistant_delta", "contentDelta": "你"})

    delivered, dropped = session_service._put_session_stream_event(
        subscriber,
        {
            "type": "assistant_delta",
            "content": "你好",
            "thought": "思考",
            "contentDelta": "好",
            "thoughtDelta": "考",
            "replaceContent": False,
            "replaceThought": False,
        },
        recover_assistant_delta_on_drop=True,
    )

    assert delivered is True
    assert dropped == 1
    recovered = subscriber.get_nowait()
    assert recovered["contentDelta"] == "你好"
    assert recovered["thoughtDelta"] == "思考"
    assert recovered["replaceContent"] is True
    assert recovered["replaceThought"] is True


def test_get_session_detail_materializes_agent_directory_stub_without_switching_active(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-active",
            "updated_at": "2026-05-18T12:00:00",
            "conversations": [
                {
                    "conversation_id": "session-active",
                    "title": "唐望舒",
                    "agent_id": "agent-active",
                    "agentId": "agent-active",
                    "updated_at": "2026-05-18T12:00:00",
                }
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent_directory_service.save_state(
        {
            "agents": [
                {
                    "agentId": "agent-active",
                    "displayName": "唐望舒",
                    "directSessionId": "session-active",
                    "status": "active",
                    "workspacePath": "workspace/agents/agent-active",
                },
                {
                    "agentId": "agent-knowledge-steward",
                    "displayName": "资料入库",
                    "directSessionId": "agent-knowledge-steward-direct",
                    "status": "active",
                    "workspacePath": "workspace/agents/agent-knowledge-steward",
                },
            ]
        }
    )

    detail = session_service.get_session_detail("agent-knowledge-steward-direct")

    assert detail is not None
    assert detail["id"] == "agent-knowledge-steward-direct"
    assert detail["agentId"] == "agent-knowledge-steward"
    assert load_chat_state(tmp_path)["active_conversation_id"] == "session-active"


def test_image_attachment_with_concrete_prompt_defaults_to_vision_route(monkeypatch):
    monkeypatch.setattr(
        session_service,
        "_session_agent_supports_image_input",
        lambda agent_instance, *, slot: True,
    )
    monkeypatch.setattr(
        session_service,
        "_session_agent_llm_slot_model_id",
        lambda agent_instance, slot: "mimo-vision",
    )
    monkeypatch.setattr(
        session_service,
        "_session_agent_llm_model_name",
        lambda agent_instance, *, slot: "mimo-v2.5-pro",
    )

    route = session_service._resolve_image_attachment_turn_route(
        "这里为什么有三个cli,能关闭吗",
        agent_instance={"agentId": "agent-vision"},
    )

    assert route["intent"] == "vision_analysis"
    assert route["route"] == "vision"
    assert route["llm_slot"] == session_service.SESSION_LLM_SLOT_VISION
    assert route["supports_image_input"] is True


def test_image_attachment_empty_prompt_still_asks_for_clarification(monkeypatch):
    monkeypatch.setattr(
        session_service,
        "_session_agent_supports_image_input",
        lambda agent_instance, *, slot: True,
    )

    route = session_service._resolve_image_attachment_turn_route("", agent_instance={})

    assert route["intent"] == "clarify"
    assert route["route"] == "clarify"


def test_contextual_image_retry_still_requires_explicit_image_intent():
    assert session_service._is_retriable_image_request_prompt("继续") is False
    assert session_service._is_retriable_image_request_prompt("再看一下刚才那张图") is True


def test_session_image_support_uses_shared_model_capability_rules(monkeypatch):
    class DummyLlm:
        model_library = {
            "mimo_model": {
                "provider_id": "xiaomi_provider",
                "model": "mimo-v2.5",
            },
            "blocked_hint_model": {
                "provider_id": "relay_provider",
                "model": "gpt-5.5-vision-like",
                "capability_status": "unsupported",
            },
        }

        def get_provider(self, provider_id):
            if provider_id == "xiaomi_provider":
                return SimpleNamespace(kind="xiaomi")
            return SimpleNamespace(kind="relay")

    monkeypatch.setattr(session_service, "get_config", lambda: SimpleNamespace(llm=DummyLlm()))

    assert (
        session_service._session_agent_supports_image_input(
            {"llmBindings": {"vision": {"modelId": "mimo_model"}}},
            slot=session_service.SESSION_LLM_SLOT_VISION,
        )
        is True
    )
    assert (
        session_service._session_agent_supports_image_input(
            {"llmBindings": {"vision": {"modelId": "blocked_hint_model"}}},
            slot=session_service.SESSION_LLM_SLOT_VISION,
        )
        is False
    )
