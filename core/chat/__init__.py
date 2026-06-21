# -*- coding: utf-8 -*-
"""Lightweight chat helper exports.

Keep this package initializer lazy.  Low-level modules such as
``core.llm.payload_builder`` import ``core.chat.model_messages`` during LLM
payload construction; importing UI/session helpers here would create a circular
``core.llm -> core.chat -> core.ui/config -> core.llm`` chain.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "assemble_conversation_context": (".context_assembler", "assemble_conversation_context"),
    "append_context_compression_checkpoint": (".conversation_ledger", "append_context_compression_checkpoint"),
    "append_conversation_event": (".conversation_ledger", "append_conversation_event"),
    "apply_context_compression_checkpoints": (".conversation_ledger", "apply_context_compression_checkpoints"),
    "build_chat_coding_result_contract": (".chat_result_contract", "build_chat_coding_result_contract"),
    "build_history_events": (".history_ledger", "build_history_events"),
    "format_chat_reply": (".chat_result_formatter", "format_chat_reply"),
    "load_conversation_events": (".conversation_ledger", "load_conversation_events"),
    "context_compression_projection": (".conversation_ledger", "context_compression_projection"),
    "project_conversation_ledger": (".conversation_ledger", "project_conversation_ledger"),
    "search_history_events": (".history_ledger", "search_history_events"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)
