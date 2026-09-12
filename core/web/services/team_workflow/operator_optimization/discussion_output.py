"""Strict structured output for one operator-optimization discussion seat.

The Chat Room keeps visible text for presentation, but the operator workflow
can only consume this explicitly bound structured payload.  In particular,
``rawModelOutput`` and visible ``content`` are never promoted to a domain
message when the structured payload is missing or invalid.
"""
from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from core.llm.semantic_messages import SemanticOutputSchema
from core.research.operator_optimization.discussion_contracts import (
    OperatorDiscussionMessage,
)


OUTPUT_SCHEMA_VERSION = 1
OUTPUT_SCHEMA_NAME = "operator_discussion_message_v1"


class OperatorDiscussionOutputError(ValueError):
    """Raised when a discussion speaker has no valid structured output."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code or "operator_discussion_output_invalid")


def _schema() -> dict[str, Any]:
    """Return an independent JSON-schema copy for provider binding."""

    schema = copy.deepcopy(OperatorDiscussionMessage.model_json_schema())
    # The domain model permits omission of nullable/default fields when it is
    # read from persisted data.  A model response still has one explicit
    # structured object; the provider schema retains the model's defaults so
    # ordinary seats may omit ``result`` and normalize it to null below.
    schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    schema["additionalProperties"] = False
    return schema


def output_contract() -> SemanticOutputSchema:
    """Build the provider-neutral strict contract for one discussion turn."""

    return SemanticOutputSchema(
        name=OUTPUT_SCHEMA_NAME,
        schema=_schema(),
        validator=_validate_payload,
    )


def _strip_json_code_fence(value: str) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(
        r"```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```",
        text,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else text


def _parse_raw(raw: Any) -> Mapping[str, Any]:
    if isinstance(raw, OperatorDiscussionMessage):
        return raw.model_dump(mode="json")
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OperatorDiscussionOutputError(
                "operator_discussion_output_encoding_invalid",
                "operator discussion output is not UTF-8",
            ) from exc
    if not isinstance(raw, str):
        raise OperatorDiscussionOutputError(
            "operator_discussion_output_type_invalid",
            "operator discussion output must be a JSON object",
        )
    text = _strip_json_code_fence(raw)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OperatorDiscussionOutputError(
            "operator_discussion_output_json_invalid",
            f"operator discussion output is not valid JSON: {exc.msg}",
        ) from exc
    if not isinstance(parsed, Mapping):
        raise OperatorDiscussionOutputError(
            "operator_discussion_output_schema_invalid",
            "operator discussion output must be a JSON object",
        )
    return dict(parsed)


def _validate_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise OperatorDiscussionOutputError(
            "operator_discussion_output_schema_invalid",
            "operator discussion output must be a JSON object",
        )
    if "rawModelOutput" in raw:
        raise OperatorDiscussionOutputError(
            "operator_discussion_raw_fallback_forbidden",
            "rawModelOutput cannot be used as an operator discussion result",
        )
    try:
        message = OperatorDiscussionMessage.model_validate(dict(raw))
    except (ValidationError, TypeError, ValueError) as exc:
        raise OperatorDiscussionOutputError(
            "operator_discussion_output_schema_invalid",
            "operator discussion output does not satisfy its strict schema",
        ) from exc
    return message.model_dump(mode="json")


def ingest_output(raw: Any) -> dict[str, Any]:
    """Parse and normalize the model's one structured response object.

    The returned mapping is the only payload eligible for persistence.  It is
    rebuilt from the validated domain contract, so unknown fields and any raw
    model-output wrapper are discarded by rejection rather than fallback.
    """

    return _validate_payload(_parse_raw(raw))


def _structured_payload_from_message(message: Any) -> Any:
    if isinstance(message, Mapping) and "operatorDiscussionPayload" in message:
        return message["operatorDiscussionPayload"]
    raise OperatorDiscussionOutputError(
        "operator_discussion_structured_payload_missing",
        "discussion message has no explicit structured payload",
    )


def validated_result(message: Any) -> OperatorDiscussionMessage:
    """Read one explicitly structured room message as a domain message."""

    payload = _structured_payload_from_message(message)
    normalized = ingest_output(payload)
    return OperatorDiscussionMessage.model_validate(normalized)


__all__ = [
    "OUTPUT_SCHEMA_NAME",
    "OUTPUT_SCHEMA_VERSION",
    "OperatorDiscussionOutputError",
    "ingest_output",
    "output_contract",
    "validated_result",
]
