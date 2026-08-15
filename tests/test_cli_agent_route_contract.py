"""CLI Agent terminal JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.cli_agent_models import CliAgentTerminalSessionResponse


def test_cli_agent_terminal_session_publishes_known_schema_fields() -> None:
    properties = set(CliAgentTerminalSessionResponse.model_json_schema().get("properties") or {})
    expected = {"terminalSessionId", "status"}
    assert expected <= properties, (
        f"CliAgentTerminalSessionResponse is missing fields: {sorted(expected - properties)}"
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
