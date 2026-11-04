from __future__ import annotations

from types import SimpleNamespace

import pytest

from config.model_catalog import load_model_catalog_state
from core.llm.image_input_feedback import (
    extract_response_text,
    messages_have_image_content,
    record_image_input_turn_feedback,
    reply_confirms_image_content,
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


def test_ok_only_image_turn_records_unknown_without_support(tmp_path) -> None:
    cache = tmp_path / "model-catalog-state.json"

    record_image_input_turn_feedback(_FakeClient(), _image_messages(), ok=True, cache_path=cache)

    record = _image_input_record(cache)
    assert record["value"] == "unknown"
    assert record["source"] == "runtime_probe"
    # Accepted-only evidence must never assert support.
    assert record.get("confidence", "") != "content_confirmed"


def test_reply_referencing_image_content_marks_supported(tmp_path) -> None:
    cache = tmp_path / "model-catalog-state.json"
    response = {"content": "The image shows a red barn next to a field."}

    record_image_input_turn_feedback(
        _FakeClient(),
        _image_messages(),
        ok=True,
        response=response,
        cache_path=cache,
    )

    record = _image_input_record(cache)
    assert record["value"] == "supported"
    assert record["source"] == "runtime_probe"
    assert record["confidence"] == "content_confirmed"


def test_turnoutcome_final_text_confirms_support(tmp_path) -> None:
    cache = tmp_path / "model-catalog-state.json"
    response = SimpleNamespace(final_text="I can see a small grey square in the image.")

    record_image_input_turn_feedback(
        _FakeClient(),
        _image_messages(),
        ok=True,
        response=response,
        cache_path=cache,
    )

    record = _image_input_record(cache)
    assert record["value"] == "supported"
    assert record["confidence"] == "content_confirmed"


def test_refusing_reply_stays_unknown(tmp_path) -> None:
    cache = tmp_path / "model-catalog-state.json"
    response = {"content": "I cannot see images, but I can help with text."}

    record_image_input_turn_feedback(
        _FakeClient(),
        _image_messages(),
        ok=True,
        response=response,
        cache_path=cache,
    )

    record = _image_input_record(cache)
    assert record["value"] == "unknown"


def test_reply_confirmation_is_conservative() -> None:
    # Bare affirmations prove nothing: an upstream that silently dropped the
    # image would produce them too.
    assert reply_confirms_image_content("ok") is False
    assert reply_confirms_image_content("done") is False
    assert reply_confirms_image_content("") is False
    assert reply_confirms_image_content("I cannot view images.") is False
    assert reply_confirms_image_content("我看不到图片。") is False
    assert reply_confirms_image_content("The image shows a red barn.") is True
    assert reply_confirms_image_content("图片中有一只猫。") is True


def test_extract_response_text_handles_common_shapes() -> None:
    assert extract_response_text(None) == ""
    assert extract_response_text({"content": "hello"}) == "hello"
    assert extract_response_text({"content": [{"type": "text", "text": "a"}, "b"]}) == "a\nb"
    assert extract_response_text(SimpleNamespace(final_text="final")) == "final"
    assert extract_response_text(object()) == ""


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
    seen: list[dict] = []

    def _fake_feedback(client, messages, *, ok, error=None, response=None):
        seen.append(
            {
                "ok": ok,
                "error": type(error).__name__ if error is not None else "",
                "response": response,
            }
        )
        return {}

    monkeypatch.setattr(
        "core.llm.image_input_feedback.record_image_input_turn_feedback",
        _fake_feedback,
    )

    client = _FakeClient(result={"content": "The image shows a square."})
    invoke_llm(client, _image_messages(), context=LLMInvocationContext(surface="chat"))
    assert seen[0]["ok"] is True
    assert seen[0]["response"] == {"content": "The image shows a square."}

    failing = _FakeClient(error=RuntimeError("model does not support image input"))
    with pytest.raises(RuntimeError):
        invoke_llm(failing, _image_messages(), context=LLMInvocationContext(surface="chat"))
    assert seen[-1] == {"ok": False, "error": "RuntimeError", "response": None}
