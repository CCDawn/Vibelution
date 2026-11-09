"""Regression: failure-event diagnostics must survive the telemetry item budget.

The runtime scene normalizer keeps at most ``MAX_TELEMETRY_FIELD_ITEMS`` (24)
entries per event in insertion order. ``_llm_retry_event_fields`` used to append
``errorType``/``attempt``/``error`` after ``role_fields``, and role fields alone
can exceed the budget, so the upstream error body was dropped from every failure
event. That made an intermittent provider 400 impossible to diagnose from the
scene log.
"""

from __future__ import annotations

from core.llm.client import _llm_retry_event_fields
from core.llm.types import LLMError

# Mirrors core.web.services.runtime_scene_service.MAX_TELEMETRY_FIELD_ITEMS.
TELEMETRY_FIELD_ITEM_BUDGET = 24

DIAGNOSTIC_KEYS = (
    "errorType",
    "retryable",
    "errorDisposition",
    "attempt",
    "maxAttempts",
    "error",
)

UPSTREAM_BODY = (
    "litellm.UnsupportedParamsError: openai does not support parameters: "
    "['reasoning_effort']. Received Model Group=deepseek-v4.1-flash"
)


def _rich_metadata() -> dict[str, object]:
    """Metadata carrying more role keys than the telemetry item budget allows."""
    metadata: dict[str, object] = {}
    for index in range(40):
        metadata[f"filler{index}"] = f"value-{index}"
    # Real role keys the normalizer copies into the event body.
    for key in (
        "sessionId",
        "turnId",
        "invocationId",
        "iteration",
        "invocationContextPresent",
        "conversationBound",
        "llmSlot",
        "promptPurpose",
        "llmInvocationSurface",
        "llmRunKind",
        "routeAttempt",
        "dialogueChainMode",
        "llmPayloadTraceId",
        "retryRequestMode",
        "messageRoles",
        "messageRoleCounts",
        "protocol",
        "selectedProtocol",
        "protocolSource",
        "protocolWarnings",
        "reasoningRoundtripEnabled",
        "thinkingFormat",
        "toolChoiceMode",
        "strictMessageKeys",
        "requiresStringContent",
        "allowAssistantPrefill",
        "payloadValidationResult",
        "payloadValidationErrorType",
        "modelLibraryId",
        "capabilitySource",
    ):
        metadata[key] = "x"
    return metadata


def _fields() -> dict[str, object]:
    return _llm_retry_event_fields(
        role="primary",
        profile_id="primary",
        provider="opencode",
        model="deepseek-v4.1-flash",
        message_count=310,
        tool_count=33,
        metadata=_rich_metadata(),
        attempt=2,
        max_attempts=5,
        llm_error=LLMError(
            "provider_protocol_error",
            UPSTREAM_BODY,
            retryable=False,
        ),
        disposition="permanent",
    )


def test_diagnostics_fit_inside_the_telemetry_item_budget() -> None:
    keys = list(_fields())
    positions = {key: keys.index(key) for key in DIAGNOSTIC_KEYS if key in keys}
    missing = [key for key in DIAGNOSTIC_KEYS if key not in positions]
    assert not missing, f"diagnostic fields dropped entirely: {missing}"
    over_budget = {
        key: position
        for key, position in positions.items()
        if position >= TELEMETRY_FIELD_ITEM_BUDGET
    }
    assert not over_budget, (
        "diagnostic fields fall outside the 24-item telemetry budget and would be "
        f"truncated from the scene event: {over_budget}"
    )


def test_upstream_error_body_is_preserved_verbatim() -> None:
    fields = _fields()
    assert fields["error"] == UPSTREAM_BODY
    assert fields["errorType"] == "provider_protocol_error"
    assert fields["attempt"] == 2
    assert fields["maxAttempts"] == 5


def test_role_fields_still_reach_the_event() -> None:
    fields = _fields()
    # Diagnostics moved forward; role context must not be pushed out entirely.
    assert fields["sessionId"] == "x"
    assert fields["turnId"] == "x"
