"""Decode leading control envelopes observed on the OpenCode DeepSeek route.

These are content-channel leaks, never executable tool calls. Only a leading
envelope is recognized; quoted examples and markers inside prose stay text.
"""

from typing import Any

PROVIDER_CONTROL_LEAK = "chat.finish.provider_control_leak"
_ENVELOPES = {
    "<budget:token_budget>": "</budget:token_budget>",
    "<ds_safety>": "</ds_safety>Safe",
    "<｜｜tool▁calls▁begin｜｜>": "<｜｜tool▁calls▁end｜｜>",
    "｜DSML｜ calls>": "</｜DSML｜ calls>",
}
_RECALL = "@@RECALL\n"


def uses_provider_control_content(route: Any) -> bool:
    return (
        getattr(route, "provider_id", "") == "opencode_go"
        and getattr(route, "provider_kind", "") == "opencode"
        and getattr(route, "effective_model", "") == "deepseek-v4.1-flash"
    )


class ProviderControlContent:
    def __init__(self) -> None:
        self.detected = False
        self._buffer = ""
        self._visible = False
        self._recall = False

    def feed(self, text: str, *, final: bool = False) -> str:
        if self._recall:
            return ""
        if self._visible:
            return text
        self._buffer += text
        while self._buffer:
            candidate = self._buffer.lstrip()
            if candidate.startswith(_RECALL):
                self.detected = self._recall = True
                self._buffer = ""
                return ""
            opening = next((tag for tag in _ENVELOPES if candidate.startswith(tag)), "")
            if opening:
                closing = _ENVELOPES[opening]
                end = candidate.find(closing, len(opening))
                if end < 0:
                    if final:
                        self.detected = True
                        self._buffer = ""
                    return ""
                if opening == "<budget:token_budget>" and not candidate[len(opening):end].strip().isdigit():
                    return self._release()
                self.detected = True
                self._buffer = candidate[end + len(closing):]
                continue
            if not final and any(tag.startswith(candidate) for tag in (*_ENVELOPES, _RECALL)):
                return ""
            return self._release()
        return ""

    def _release(self) -> str:
        text, self._buffer = self._buffer, ""
        self._visible = True
        return text
