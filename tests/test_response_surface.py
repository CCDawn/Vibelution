from types import SimpleNamespace

from core.orchestration.response_surface import ResponseSurfaceController, TokenUsageObservation
from core.orchestration.round_state import RoundStateController


def _controller(*, estimate_tokens=lambda _messages: 0, ui=None, debug=None):
    captured_ui = ui or SimpleNamespace(
        note_token_usage=lambda *args, **kwargs: None,
        stream_thought=lambda *_args, **_kwargs: None,
        add_content=lambda *_args, **_kwargs: None,
        set_pet_mental_state=lambda **_kwargs: None,
    )
    return ResponseSurfaceController(
        estimate_tokens=estimate_tokens,
        ui_getter=lambda: captured_ui,
        logger=SimpleNamespace(log_token_usage=lambda *_args, **_kwargs: None),
        debug_logger=debug or SimpleNamespace(
            info=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
        ),
        pet_getter=lambda: SimpleNamespace(
            record_tokens=lambda *_args, **_kwargs: None,
            trigger_heartbeat=lambda: None,
        ),
        print_tokens=lambda *_args, **_kwargs: None,
    )


def test_token_usage_observation_coerces_invalid_ints():
    usage = TokenUsageObservation("12", "bad", cached_input_tokens="3", cache_creation_input_tokens="nope")
    assert usage.input_tokens == 12
    assert usage.output_tokens == 0
    assert usage.cached_input_tokens == 3
    assert usage.cache_creation_input_tokens == 0
    assert usage == (12, 0)


def test_emit_visible_response_keeps_tool_count_when_raw_content_empty():
    processed = SimpleNamespace(visible_text="should not stream")
    surface = _controller().emit_visible_response(
        raw_content=None,
        processed=processed,
        tool_call_count="2",
    )
    assert surface["last_visible_response_text"] == ""
    assert surface["last_response_tool_calls"] == 2


def test_emit_visible_response_string_zero_still_prints_final_answer():
    contents = []
    ui = SimpleNamespace(
        note_token_usage=lambda *args, **kwargs: None,
        stream_thought=lambda *_args, **_kwargs: None,
        add_content=lambda chunk: contents.append(chunk),
        set_pet_mental_state=lambda **_kwargs: None,
    )
    processed = SimpleNamespace(visible_text="第一行\n第二行")
    surface = _controller(ui=ui).emit_visible_response(
        raw_content="继续",
        processed=processed,
        tool_call_count="0",
    )
    assert contents == ["第一行", "第二行"]
    assert surface["last_response_tool_calls"] == 0
    assert surface["last_visible_response_text"] == "第一行\n第二行"


def test_apply_state_feedback_ignores_non_mapping_state_info():
    processed = SimpleNamespace(raw_content_clean="ok", state_info="not-a-mapping")
    result = _controller().apply_state_feedback(
        processed=processed,
        record_language_drift=lambda _text: None,
        record_inference_activity=lambda _text: None,
        mental_model_enabled=True,
    )
    assert result == {}


def test_record_token_usage_coerces_invalid_estimates():
    round_state = RoundStateController(max_iterations=3)
    usage = _controller(estimate_tokens=lambda _messages: "not-a-number").record_token_usage(
        response=SimpleNamespace(),
        round_state=round_state,
        current_turn=1,
        messages=[SimpleNamespace(content="hello")],
        raw_content="answer",
        estimate_output_tokens=lambda _text: "also-bad",
    )
    assert usage == (0, 0)
    assert round_state.total_input_tokens == 0
