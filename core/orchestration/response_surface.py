# -*- coding: utf-8 -*-
"""响应后的感知、展示与落账控制器。"""

from __future__ import annotations

from typing import Any, Callable, Dict, Sequence

from core.mental_model_flags import is_mental_model_enabled
from core.llm.usage import cached_input_tokens_from_usage, usage_tokens_from_dict


def _resolve_mental_model_enabled(override: bool | None = None) -> bool:
    if override is not None:
        return bool(override)
    return is_mental_model_enabled()


class TokenUsageObservation:
    """Tuple-compatible token usage with provider-observation metadata."""

    def __new__(
        cls,
        input_tokens: int,
        output_tokens: int,
        *,
        cached_input_tokens: int = 0,
        observed: bool = False,
    ) -> "TokenUsageObservation":
        value = super().__new__(cls)
        value._input_tokens = max(0, int(input_tokens or 0))
        value._output_tokens = max(0, int(output_tokens or 0))
        value.cached_input_tokens = max(0, int(cached_input_tokens or 0))
        value.observed = bool(observed)
        return value

    def __iter__(self):
        yield self.input_tokens
        yield self.output_tokens

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index: int) -> int:
        return (self.input_tokens, self.output_tokens)[index]

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, tuple):
            return (self.input_tokens, self.output_tokens) == other
        return super().__eq__(other)

    @property
    def input_tokens(self) -> int:
        return self._input_tokens

    @property
    def output_tokens(self) -> int:
        return self._output_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ResponseSurfaceController:
    """集中处理响应后的感知、副作用记录、UI 输出和 token 落账。"""

    def __init__(
        self,
        *,
        estimate_tokens: Callable[[Sequence[Any]], int],
        ui_getter: Callable[[], Any],
        logger: Any,
        debug_logger: Any,
        pet_getter: Callable[[], Any],
        print_tokens: Callable[[int, int], None],
    ) -> None:
        self._estimate_tokens = estimate_tokens
        self._ui_getter = ui_getter
        self._logger = logger
        self._debug_logger = debug_logger
        self._pet_getter = pet_getter
        self._print_tokens = print_tokens

    def build_state_block(
        self,
        *,
        raw_content: str,
        has_tool_calls: bool,
        consecutive_failures: int,
        iteration: int,
        messages: Sequence[Any],
        mental_model: Any,
        effective_max_token_limit: int,
        mental_model_enabled: bool | None = None,
    ) -> str:
        if not _resolve_mental_model_enabled(mental_model_enabled):
            return ""
        should_sense = has_tool_calls or consecutive_failures >= 2 or iteration == 1
        if not should_sense:
            return ""
        try:
            recent_tools = list(getattr(mental_model, "_tool_history", []))[-5:]
            tool_summary = "\n".join(
                f"- {t.tool_name}({'✓' if t.success else '✗'}) {t.args_summary}"
                for t in recent_tools
            ) or "尚无工具调用"
            current_tokens = self._estimate_tokens(messages)
            token_ratio = (
                current_tokens / effective_max_token_limit
                if effective_max_token_limit > 0
                else 0.0
            )
            return mental_model.sense_state(
                think_content=raw_content,
                tool_summary=tool_summary,
                token_ratio=token_ratio,
                iteration=iteration,
            )
        except Exception:
            return ""

    def apply_state_feedback(
        self,
        *,
        processed: Any,
        record_language_drift: Callable[[str], None],
        record_inference_activity: Callable[[str], None],
        mental_model_enabled: bool | None = None,
    ) -> Dict[str, str]:
        raw_content_clean = processed.raw_content_clean
        record_language_drift(raw_content_clean)
        record_inference_activity(raw_content_clean)

        if not _resolve_mental_model_enabled(mental_model_enabled):
            return {}

        state_info = processed.state_info or {}
        if state_info.get("mood"):
            ui = self._ui_getter()
            ui.set_pet_mental_state(
                mood=state_info.get("mood", ""),
                feeling=state_info.get("feeling", ""),
                whisper=state_info.get("whisper", ""),
            )
            mood = state_info["mood"]
            if mood not in ("专注", "自信"):
                self._debug_logger.info(
                    f"[感知] {mood} | {state_info.get('feeling', '')} | {state_info.get('whisper', '')}",
                    tag="STATE",
                )
        return state_info

    def record_token_usage(
        self,
        *,
        response: Any,
        round_state: Any,
        current_turn: int,
        messages: Sequence[Any] | None = None,
        raw_content: str = "",
        estimate_output_tokens: Callable[[str], int] | None = None,
    ) -> "TokenUsageObservation":
        ui = self._ui_getter()
        input_tokens = 0
        output_tokens = 0
        cached_input_tokens = 0
        usage = self._extract_usage_payload(response)
        if usage:
            input_tokens, output_tokens = self._extract_usage_tokens(usage)
            cached_input_tokens = self._extract_cached_input_tokens(usage)

        usage_observation = self._extract_usage_observation(response)
        if usage_observation:
            cached_input_tokens = max(
                cached_input_tokens,
                self._read_int_from_mapping(
                    usage_observation,
                    "cached_input_tokens",
                    "cachedInputTokens",
                    "cached_tokens",
                ),
            )

        estimated = False
        observed_usage = bool(usage or usage_observation)
        if not input_tokens and messages is not None:
            input_tokens = max(0, int(self._estimate_tokens(messages) or 0))
            estimated = input_tokens > 0
        if not output_tokens and raw_content and estimate_output_tokens is not None:
            output_tokens = max(0, int(estimate_output_tokens(raw_content) or 0))
            estimated = estimated or output_tokens > 0

        if estimated:
            self._debug_logger.info(
                f"[TOKEN] usage metadata missing/incomplete; estimated input={input_tokens} output={output_tokens}",
                tag="TOKEN",
            )

        if input_tokens or output_tokens:
            round_state.add_token_usage(input_tokens, output_tokens)

            self._print_tokens(input_tokens, output_tokens)
            self._logger.log_token_usage(input_tokens, output_tokens, current_turn)

            try:
                pet = self._pet_getter()
                pet.record_tokens(input_tokens, output_tokens)
                pet.trigger_heartbeat()
            except Exception:
                pass
            ui.note_token_usage(
                input_tokens,
                output_tokens,
                cached_input_tokens=cached_input_tokens,
                observed=observed_usage,
            )
        else:
            ui.note_token_usage(observed=False)
        return TokenUsageObservation(
            input_tokens,
            output_tokens,
            cached_input_tokens=cached_input_tokens,
            observed=observed_usage,
        )

    @staticmethod
    def _extract_usage_payload(response: Any) -> Dict[str, Any]:
        for attr in ("usage_metadata", "usage"):
            usage = getattr(response, attr, None)
            if isinstance(usage, dict) and usage:
                return usage

        response_metadata = getattr(response, "response_metadata", None)
        if isinstance(response_metadata, dict):
            for key in ("token_usage", "usage", "usage_metadata"):
                usage = response_metadata.get(key)
                if isinstance(usage, dict) and usage:
                    return usage

        return {}

    @staticmethod
    def _extract_usage_observation(response: Any) -> Dict[str, Any]:
        response_metadata = getattr(response, "response_metadata", None)
        if isinstance(response_metadata, dict):
            usage_observation = response_metadata.get("usage_observation")
            if isinstance(usage_observation, dict) and usage_observation:
                return usage_observation
        return {}

    @staticmethod
    def _extract_usage_tokens(usage: Dict[str, Any] | Any) -> tuple[int, int]:
        input_tokens, output_tokens, _total_tokens = usage_tokens_from_dict(usage)
        return input_tokens, output_tokens

    @staticmethod
    def _read_int_from_mapping(data: Dict[str, Any] | Any, *keys: str) -> int:
        if not isinstance(data, dict):
            return 0
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                try:
                    return max(0, int(value))
                except (TypeError, ValueError):
                    continue
        return 0

    @classmethod
    def _extract_cached_input_tokens(cls, usage: Dict[str, Any] | Any) -> int:
        return cached_input_tokens_from_usage(usage)

    def emit_visible_response(
        self,
        *,
        raw_content: str,
        processed: Any,
        tool_call_count: int,
    ) -> Dict[str, Any]:
        if not raw_content.strip():
            return {
                "last_visible_response_text": "",
                "last_response_tool_calls": 0,
            }

        ui = self._ui_getter()
        stream_response = getattr(ui, "stream_response", None)
        if callable(stream_response):
            stream_response(processed.visible_text, done=True)
        else:
            ui.stream_thought(processed.visible_text, done=True)
        if not tool_call_count:
            for chunk in processed.visible_text.splitlines():
                if chunk.strip():
                    ui.add_content(chunk)
        return {
            "last_visible_response_text": processed.visible_text,
            "last_response_tool_calls": tool_call_count,
        }
