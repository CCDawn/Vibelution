"""CLI Agent terminal JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.cli_agent_models import CliAgentTerminalSessionResponse

CLI_AGENT_PUBLIC_STATE_FIELDS = {
    "terminalSessionId",
    "adapterId",
    "agentType",
    "label",
    "sourceSessionId",
    "sourceMessageId",
    "sourceRunId",
    "linkedSourceMessageIds",
    "linkedSourceRunIds",
    "cliRunId",
    "lockKey",
    "cwd",
    "mode",
    "taskHash",
    "taskPreview",
    "cliSessionId",
    "cliSessionIdSource",
    "sessionDiscoveryStatus",
    "commandPreview",
    "resumed",
    "status",
    "alive",
    "transport",
    "rows",
    "cols",
    "transcriptPath",
    "transcriptTail",
    "transcriptTailReplayable",
    "transcriptTailRenderReason",
    "screenText",
    "screenReplay",
    "screenQuality",
    "screenRows",
    "screenCols",
    "screenParserVersion",
    "processStartedAt",
    "processStartedAtMs",
    "userClosed",
    "closedAt",
    "closedTerminalSessionIds",
    "closeReason",
    "supersededByTerminalSessionId",
    "semanticStatus",
    "interactionState",
    "canInput",
    "canResume",
    "canStart",
    "resumeAction",
    "displayMode",
    "stateReason",
    "tuiState",
    "createdAt",
    "updatedAt",
}


def test_cli_agent_terminal_session_publishes_known_schema_fields() -> None:
    properties = set(CliAgentTerminalSessionResponse.model_json_schema().get("properties") or {})
    assert CLI_AGENT_PUBLIC_STATE_FIELDS <= properties, (
        f"CliAgentTerminalSessionResponse is missing fields: {sorted(CLI_AGENT_PUBLIC_STATE_FIELDS - properties)}"
    )


def test_cli_agent_terminal_session_keeps_unknown_fields() -> None:
    payload = CliAgentTerminalSessionResponse.model_validate(
        {
            "terminalSessionId": "term-1",
            "status": "accepted",
            "lifecycleEvent": {"metadata": {"kind": "cli_agent_lifecycle"}},
        }
    ).model_dump()

    assert payload["lifecycleEvent"] == {"metadata": {"kind": "cli_agent_lifecycle"}}


def test_cli_agent_terminal_session_accepts_public_state_shape() -> None:
    payload = CliAgentTerminalSessionResponse.model_validate(
        {
            "terminalSessionId": "cli-term-interrupted",
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "cwd": r"C:\project",
            "mode": "readonly",
            "status": "running",
            "alive": True,
            "commandPreview": ["mimo", "code"],
            "interactionState": "live",
            "canInput": True,
            "tuiState": "interrupted",
            "semanticStatus": "attached",
        }
    ).model_dump(exclude_unset=True)

    assert payload["tuiState"] == "interrupted"
    assert payload["commandPreview"] == ["mimo", "code"]
    assert payload["canInput"] is True


def test_cli_agent_terminal_session_keeps_unknown_fields_without_injecting_defaults() -> None:
    payload = CliAgentTerminalSessionResponse.model_validate(
        {
            "terminalSessionId": "term-2",
            "status": "attached",
            "canInput": True,
            "futureHint": {"owner": "cli"},
        }
    ).model_dump(exclude_unset=True)

    assert payload == {
        "terminalSessionId": "term-2",
        "status": "attached",
        "canInput": True,
        "futureHint": {"owner": "cli"},
    }
