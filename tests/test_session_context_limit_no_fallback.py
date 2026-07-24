"""Context window resolution must fail closed without inventing defaults."""

from __future__ import annotations

from types import SimpleNamespace

from core.web.services.session import conversation_index, runtime_glue


class _FakeService:
    def _coerce_nonnegative_int(self, value):
        try:
            number = int(value or 0)
        except Exception:
            return 0
        return number if number > 0 else 0

    def _first_positive_int(self, *values):
        for value in values:
            number = self._coerce_nonnegative_int(value)
            if number > 0:
                return number
        return 0

    def get_config(self):
        return SimpleNamespace()

    def _conversation_agent_dialogue_context_window_payload(self, cfg, conversation):
        return {"limit": 0, "modelId": "model-missing", "agentId": "agent-a", "source": "missing"}


def test_session_context_limit_payload_does_not_invent_static_or_compression_defaults(monkeypatch):
    fake = _FakeService()
    monkeypatch.setattr(runtime_glue, "_service", lambda: fake)

    payload = runtime_glue._session_context_limit_payload({"id": "session-a"})

    assert payload["limit"] == 0
    assert payload["source"] == "missing"
    assert payload["modelId"] == "model-missing"
    assert "禁止" in str(payload.get("error") or "") or "context_window" in str(payload.get("error") or "")
    assert payload["limit"] != 128000
    assert payload["source"] != "static_fallback"
    assert payload["source"] != "context_compression_fallback"


def test_provider_context_window_default_is_none():
    from config.models import ProviderConfig

    provider = ProviderConfig(provider_id="p-test", kind="openai")
    assert provider.context_window is None


def test_conversation_agent_window_payload_returns_zero_without_configured_window(monkeypatch):
    class _Service:
        def agent_dialogue_model_id(self, agent):
            return "model-x"

        def _conversation_agent_for_context_limit(self, conversation):
            return {"agentId": "agent-x"}

        def _first_positive_int(self, *values):
            for value in values:
                try:
                    number = int(value or 0)
                except Exception:
                    continue
                if number > 0:
                    return number
            return 0

        def get_provider(self, provider_id):
            return SimpleNamespace(context_window=0)

    class _Cfg:
        class llm:
            model_library = {
                "model-x": {
                    "provider_id": "p1",
                    "model": "unknown-model",
                }
            }

            @staticmethod
            def get_provider(provider_id):
                return SimpleNamespace(context_window=0)

    monkeypatch.setattr(conversation_index, "_service", lambda: _Service())
    payload = conversation_index._conversation_agent_dialogue_context_window_payload(
        _Cfg(),
        {"id": "s1", "agentId": "agent-x"},
    )
    assert payload["limit"] == 0
    assert payload["source"] == "missing"
