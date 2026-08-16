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


def test_response_surface_coerces_false_flags_json_usage_and_bytes_text():
    usage = TokenUsageObservation(True, b"8", cached_input_tokens=b"2", observed="false")
    assert usage.input_tokens == 0
    assert usage.output_tokens == 8
    assert usage.cached_input_tokens == 2
    assert usage.observed is False

    round_state = RoundStateController(max_iterations=3)
    recorded = _controller().record_token_usage(
        response=SimpleNamespace(usage_metadata='{"input_tokens": 9, "output_tokens": 4}'),
        round_state=round_state,
        current_turn="1",
    )
    assert recorded == (9, 4)
    assert recorded.observed is True

    observed = _controller().record_token_usage(
        response=SimpleNamespace(
            usage_metadata={"input_tokens": 12, "output_tokens": 1},
            responseMetadata={"usageObservation": {"cachedInputTokens": "5"}},
        ),
        round_state=RoundStateController(max_iterations=3),
        current_turn=1,
    )
    assert observed.cached_input_tokens == 5

    sensed = []
    mental = SimpleNamespace(
        _tool_history="not-a-list",
        sense_state=lambda **kwargs: sensed.append(kwargs) or "block",
    )
    surface = _controller()
    assert (
        surface.build_state_block(
            raw_content=b"think",
            has_tool_calls="false",
            consecutive_failures="0",
            iteration="3",
            messages="abc",
            mental_model=mental,
            effective_max_token_limit="8000",
            mental_model_enabled="true",
        )
        == ""
    )
    assert (
        surface.build_state_block(
            raw_content=b"think",
            has_tool_calls=True,
            consecutive_failures=0,
            iteration=1,
            messages=[],
            mental_model=mental,
            effective_max_token_limit=100,
            mental_model_enabled="false",
        )
        == ""
    )
    assert (
        surface.build_state_block(
            raw_content=b"think",
            has_tool_calls="true",
            consecutive_failures=0,
            iteration=2,
            messages="abc",
            mental_model=mental,
            effective_max_token_limit="8000",
            mental_model_enabled="true",
        )
        == "block"
    )
    assert sensed[0]["think_content"] == "think"
    assert "尚无工具调用" in sensed[0]["tool_summary"]

    pets = []
    ui = SimpleNamespace(
        note_token_usage=lambda *args, **kwargs: None,
        stream_thought=lambda *_args, **_kwargs: None,
        add_content=lambda *_args, **_kwargs: None,
        set_pet_mental_state=lambda **kwargs: pets.append(kwargs),
    )
    feedback = _controller(ui=ui).apply_state_feedback(
        processed=SimpleNamespace(
            raw_content_clean=b"ok",
            state_info='{"mood":"专注","feeling":"稳"}',
        ),
        record_language_drift=lambda _text: None,
        record_inference_activity=lambda _text: None,
        mental_model_enabled="true",
    )
    assert feedback["mood"] == "专注"
    assert pets[0]["mood"] == "专注"

    emitted = _controller(ui=ui).emit_visible_response(
        raw_content="继续".encode("utf-8"),
        processed=SimpleNamespace(visibleText="可见回答"),
        tool_call_count="0",
    )
    assert emitted["last_visible_response_text"] == "可见回答"
