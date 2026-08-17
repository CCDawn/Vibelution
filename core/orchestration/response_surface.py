# -*- coding: utf-8 -*-
"""响应后的感知、展示与落账控制器。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Callable, Dict, Sequence

from core.mental_model_flags import is_mental_model_enabled
from core.llm.usage import (
    cache_creation_input_tokens_from_usage,
    cached_input_tokens_from_usage,
    usage_tokens_from_dict,
)


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def _maybe_json(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _as_mapping(value: Any) -> Dict[str, Any]:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _mapping_get(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def _object_field(value: Any, *names: str) -> Any:
    mapped = _as_mapping(value)
    if mapped:
        for name in names:
            if name in mapped:
                return mapped.get(name)
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _coerce_nonnegative_int(value: Any, *, default: int = 0) -> int:
    if isinstance(value, bool) or value is None:
        return max(0, int(default or 0))
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        try:
            return max(0, int(default or 0))
        except (TypeError, ValueError):
            return 0


def _coerce_item_list(value: Any) -> list:
    value = _maybe_json(value)
    if value is None or isinstance(value, (str, bytes, bytearray, memoryview)):
        return []
    if isinstance(value, Mapping):
        nested = value.get("messages")
        if nested is None:
            nested = value.get("items")
        if nested is None:
            nested = value.get("history")
        if nested is None:
            nested = value.get("tool_history")
        if nested is None:
            nested = value.get("toolHistory")
        if nested is not None:
            return _coerce_item_list(nested)
        return [dict(value)] if value else []
    try:
        return list(value)
    except TypeError:
        return []


def _resolve_mental_model_enabled(override: Any = None) -> bool:
    if override is None:
        return is_mental_model_enabled()
    return _coerce_bool(override, default=False)


class TokenUsageObservation:
    """Tuple-compatible token usage with provider-observation metadata."""

    def __new__(
        cls,
        input_tokens: int,
        output_tokens: int,
        *,
        cached_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        uncached_input_tokens: int | None = None,
        observed: bool = False,
    ) -> "TokenUsageObservation":
        value = super().__new__(cls)
        value._input_tokens = _coerce_nonnegative_int(input_tokens)
        value._output_tokens = _coerce_nonnegative_int(output_tokens)
        cached_count = _coerce_nonnegative_int(cached_input_tokens)
        if value._input_tokens:
            cached_count = min(cached_count, value._input_tokens)
        value.cached_input_tokens = cached_count
        cache_creation_count = _coerce_nonnegative_int(cache_creation_input_tokens)
        if value._input_tokens:
            cache_creation_count = min(cache_creation_count, value._input_tokens)
        value.cache_creation_input_tokens = cache_creation_count
        if uncached_input_tokens is None:
            value.uncached_input_tokens = max(0, value._input_tokens - cached_count)
        else:
            value.uncached_input_tokens = _coerce_nonnegative_int(uncached_input_tokens)
        value.observed = _coerce_bool(observed, default=False)
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
        failures = _coerce_nonnegative_int(consecutive_failures)
        iteration_index = _coerce_nonnegative_int(iteration)
        should_sense = _coerce_bool(has_tool_calls, default=False) or failures >= 2 or iteration_index == 1
        if not should_sense:
            return ""
        try:
            recent_tools = _coerce_item_list(getattr(mental_model, "_tool_history", []))[-5:]
            tool_summary = "\n".join(
                f"- {t.tool_name}({'✓' if t.success else '✗'}) {t.args_summary}"
                for t in recent_tools
            ) or "尚无工具调用"
            current_tokens = _coerce_nonnegative_int(self._estimate_tokens(_coerce_item_list(messages)))
            limit = _coerce_nonnegative_int(effective_max_token_limit)
            token_ratio = current_tokens / limit if limit > 0 else 0.0
            return mental_model.sense_state(
                think_content=_coerce_text(raw_content),
                tool_summary=tool_summary,
                token_ratio=token_ratio,
                iteration=iteration_index,
            )
        except Exception as exc:
            self._debug_logger.warning(f"[响应感知] 构建工具感知 block 失败: {type(exc).__name__}: {exc}")
            return ""

    def apply_state_feedback(
        self,
        *,
        processed: Any,
        record_language_drift: Callable[[str], None],
        record_inference_activity: Callable[[str], None],
        mental_model_enabled: bool | None = None,
    ) -> Dict[str, str]:
        raw_content_clean = _coerce_text(
            _object_field(processed, "raw_content_clean", "rawContentClean")
        )
        record_language_drift(raw_content_clean)
        record_inference_activity(raw_content_clean)

        if not _resolve_mental_model_enabled(mental_model_enabled):
            return {}

        state_info = _as_mapping(
            _object_field(processed, "state_info", "stateInfo")
        )
        mood = _coerce_text(_mapping_get(state_info, "mood"))
        if mood:
            ui = self._ui_getter()
            feeling = _coerce_text(_mapping_get(state_info, "feeling"))
            whisper = _coerce_text(_mapping_get(state_info, "whisper"))
            ui.set_pet_mental_state(
                mood=mood,
                feeling=feeling,
                whisper=whisper,
            )
            if mood not in ("专注", "自信"):
                self._debug_logger.info(
                    f"[感知] {mood} | {feeling} | {whisper}",
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
        cache_creation_input_tokens = 0
        uncached_input_tokens: int | None = None
        usage = self._extract_usage_payload(response)
        if usage:
            input_tokens, output_tokens = self._extract_usage_tokens(usage)
            cached_input_tokens = self._extract_cached_input_tokens(usage)
            cache_creation_input_tokens = self._extract_cache_creation_input_tokens(usage)

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
            cache_creation_input_tokens = max(
                cache_creation_input_tokens,
                self._read_int_from_mapping(
                    usage_observation,
                    "cache_creation_input_tokens",
                    "cacheCreationInputTokens",
                    "cache_write_input_tokens",
                    "cacheWriteInputTokens",
                ),
            )
            uncached_input_tokens = self._read_int_from_mapping(
                usage_observation,
                "uncached_input_tokens",
                "uncachedInputTokens",
            )

        estimated = False
        observed_usage = bool(usage or usage_observation)
        if not input_tokens and messages is not None:
            input_tokens = _coerce_nonnegative_int(self._estimate_tokens(_coerce_item_list(messages)))
            estimated = input_tokens > 0
        if not output_tokens and raw_content and estimate_output_tokens is not None:
            output_tokens = _coerce_nonnegative_int(estimate_output_tokens(raw_content))
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
            except Exception as exc:
                self._debug_logger.warning(f"[响应感知] PET 记录 token 心跳失败: {type(exc).__name__}: {exc}")
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
            cache_creation_input_tokens=cache_creation_input_tokens,
            uncached_input_tokens=uncached_input_tokens,
            observed=observed_usage,
        )

    @staticmethod
    def _extract_usage_payload(response: Any) -> Dict[str, Any]:
        for attr in ("usage_metadata", "usage", "usageMetadata"):
            usage = _as_mapping(_object_field(response, attr))
            if usage:
                return usage

        response_metadata = _as_mapping(
            _object_field(response, "response_metadata", "responseMetadata")
        )
        for key in ("token_usage", "tokenUsage", "usage", "usage_metadata", "usageMetadata"):
            usage = _as_mapping(response_metadata.get(key))
            if usage:
                return usage

        mapped = _as_mapping(response)
        if mapped and any(
            key in mapped
            for key in (
                "input_tokens",
                "inputTokens",
                "prompt_tokens",
                "promptTokens",
                "output_tokens",
                "outputTokens",
                "completion_tokens",
                "completionTokens",
            )
        ):
            return mapped

        return {}

    @staticmethod
    def _extract_usage_observation(response: Any) -> Dict[str, Any]:
        response_metadata = _as_mapping(
            _object_field(response, "response_metadata", "responseMetadata")
        )
        return _as_mapping(
            _mapping_get(response_metadata, "usage_observation", "usageObservation")
        )

    @staticmethod
    def _extract_usage_tokens(usage: Dict[str, Any] | Any) -> tuple[int, int]:
        input_tokens, output_tokens, _total_tokens = usage_tokens_from_dict(usage)
        return input_tokens, output_tokens

    @staticmethod
    def _read_int_from_mapping(data: Dict[str, Any] | Any, *keys: str) -> int:
        mapping = _as_mapping(data)
        if not mapping:
            return 0
        for key in keys:
            if key not in mapping:
                continue
            value = mapping.get(key)
            if value in (None, ""):
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, (bytes, bytearray, memoryview)):
                value = bytes(value).decode("utf-8", errors="replace")
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
        return 0

    @classmethod
    def _extract_cached_input_tokens(cls, usage: Dict[str, Any] | Any) -> int:
        return cached_input_tokens_from_usage(usage)

    @classmethod
    def _extract_cache_creation_input_tokens(cls, usage: Dict[str, Any] | Any) -> int:
        return cache_creation_input_tokens_from_usage(usage)

    def emit_visible_response(
        self,
        *,
        raw_content: str,
        processed: Any,
        tool_call_count: int,
    ) -> Dict[str, Any]:
        count = _coerce_nonnegative_int(tool_call_count)
        visible_text = _coerce_text(
            _object_field(processed, "visible_text", "visibleText")
        )
        if not _coerce_text(raw_content).strip():
            return {
                "last_visible_response_text": "",
                "last_response_tool_calls": count,
            }

        ui = self._ui_getter()
        stream_response = getattr(ui, "stream_response", None)
        if callable(stream_response):
            stream_response(visible_text, done=True)
        else:
            ui.stream_thought(visible_text, done=True)
        if not count:
            for chunk in visible_text.splitlines():
                if chunk.strip():
                    ui.add_content(chunk)
        return {
            "last_visible_response_text": visible_text,
            "last_response_tool_calls": count,
        }
