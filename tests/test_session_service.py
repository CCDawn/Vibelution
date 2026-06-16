from types import SimpleNamespace

from core.web.services import session_service


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
