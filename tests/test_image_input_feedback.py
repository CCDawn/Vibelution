from __future__ import annotations

import pytest

from config.model_catalog import load_model_catalog_state
from core.llm.image_input_feedback import (
    messages_have_image_content,
    record_image_input_turn_feedback,
)
from core.llm.invocation import invoke_llm
from core.llm.invocation_context import LLMInvocationContext


class _FakeProfile:
    provider_id = "deepseek_main"
    model = "deepseek-v4-flash"


class _FakeProvider:
    provider_id = "deepseek_main"


class _FakeClient:
    def __init__(self, *, result: object = None, error: Exception | None = None) -> None:
        self.profile = _FakeProfile()
        self.provider = _FakeProvider()
        self._result = result if result is not None else {"ok": True}
        self._error = error
        self.invocations = 0

    def invoke(self, messages, **kwargs):
        self.invocations += 1
        if self._error is not None:
            raise self._error
        return self._result


def _image_messages() -> list[dict]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "look at this"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        }
    ]


def _text_messages() -> list[dict]:
    return [{"role": "user", "content": "hello"}]


def _image_input_record(cache_path) -> dict:
    state = load_model_catalog_state(cache_path)
    return state["providers"]["deepseek_main"]["models"]["deepseek-v4-flash"]["capabilities"][
        "image_input"
    ]


def test_detects_image_content_blocks() -> None:
    assert messages_have_image_content(_image_messages()) is True
    assert messages_have_image_content(_text_messages()) is False


def test_text_only_turn_never_writes_capability(tmp_path) -> None:
    cache = tmp_path / "model-catalog-state.json"

    record_image_input_turn_feedback(_FakeClient(), _text_messages(), ok=True, cache_path=cache)

    assert not cache.exists()


def test_successful_image_turn_marks_supported(tmp_path) -> None:
    cache = tmp_path / "model-catalog-state.json"

    record_image_input_turn_feedback(_FakeClient(), _image_messages(), ok=True, cache_path=cache)

    record = _image_input_record(cache)
    assert record["value"] == "supported"
    assert record["source"] == "runtime_probe"


def test_unsupported_error_marks_unsupported_with_evidence(tmp_path) -> None:
    cache = tmp_path / "model-catalog-state.json"
    error = RuntimeError("model does not support image input")

    record_image_input_turn_feedback(
        _FakeClient(),
        _image_messages(),
        ok=False,
        error=error,
        cache_path=cache,
    )

    record = _image_input_record(cache)
    assert record["value"] == "unsupported"
    assert record["source"] == "runtime_probe"
    assert record["error"] == "unsupported"


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("429 rate limit exceeded"),
        RuntimeError("connection reset by peer"),
        RuntimeError("invalid api key"),
    ],
)
def test_non_capability_errors_never_deny_image_input(tmp_path, error: Exception) -> None:
    cache = tmp_path / "model-catalog-state.json"

    record_image_input_turn_feedback(
        _FakeClient(),
        _image_messages(),
        ok=False,
        error=error,
        cache_path=cache,
    )

    assert not cache.exists()


def test_invoke_llm_reports_outcome_of_image_turns(monkeypatch) -> None:
    seen: list[tuple[bool, str]] = []

    def _fake_feedback(client, messages, *, ok, error=None):
        seen.append((ok, type(error).__name__ if error is not None else ""))
        return {}

    monkeypatch.setattr(
        "core.llm.image_input_feedback.record_image_input_turn_feedback",
        _fake_feedback,
    )

    invoke_llm(_FakeClient(), _image_messages(), context=LLMInvocationContext(surface="chat"))
    assert seen == [(True, "")]

    failing = _FakeClient(error=RuntimeError("model does not support image input"))
    with pytest.raises(RuntimeError):
        invoke_llm(failing, _image_messages(), context=LLMInvocationContext(surface="chat"))
    assert seen[-1] == (False, "RuntimeError")
