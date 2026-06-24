from __future__ import annotations

from core.agent_kernel.source_authority import (
    SOURCE_AUTHORITY_VERSION,
    attach_source_ref,
    projection_edit_contract,
    source_ref,
)


def test_agent_source_ref_points_to_agent_directory_deeplink() -> None:
    ref = source_ref("agent", "agent-alpha")

    assert ref["owner"] == "AgentDirectory"
    assert ref["factAuthority"] is True
    assert ref["projectionCanWrite"] is False
    assert ref["canonicalEditRoute"] == "/agents?agent=agent-alpha&pane=config"
    assert ref["canonicalMutationApi"] == "/api/agents/agent-alpha"
    assert ref["sourceAuthorityVersion"] == SOURCE_AUTHORITY_VERSION


def test_projection_edit_contract_for_session_requires_deeplink_to_source() -> None:
    contract = projection_edit_contract("session", "session-alpha")

    assert contract["canWrite"] is False
    assert contract["mode"] == "deep_link_to_source"
    assert contract["sourceOwner"] == "ConversationLedger"
    assert contract["canonicalEditRoute"] == "/chat?session=session-alpha"


def test_mode_binding_projection_deeplinks_to_agent_configuration() -> None:
    contract = projection_edit_contract(
        "mode_binding",
        "research",
        {"agentId": "agent-research", "field": "pool"},
    )

    assert contract["canWrite"] is False
    assert contract["mode"] == "deep_link_to_source"
    assert contract["sourceOwner"] == "AgentModeBindingService"
    assert contract["canonicalEditRoute"] == "/agents?agent=agent-research&pane=config"
    assert contract["canonicalMutationApi"] == "/api/agents/agent-research/mode-membership"


def test_message_projection_uses_source_session_for_deeplink() -> None:
    ref = attach_source_ref(
        {"kind": "conversation_message", "id": "message-alpha"},
        {"sourceSessionId": "session-alpha"},
    )

    assert ref["sourceOwner"] == "ConversationLedger"
    assert ref["projectionCanWrite"] is False
    assert ref["canonicalEditRoute"] == "/chat?session=session-alpha&message=message-alpha"
    assert ref["sourceRef"]["canonicalEditRoute"] == "/chat?session=session-alpha&message=message-alpha"
