from core.web.services.session_service import _conversation_agent_direct_session_is_allowed


def test_workspace_session_is_a_valid_non_primary_agent_session() -> None:
    assert _conversation_agent_direct_session_is_allowed(
        conversation={"sessionKind": "main", "sessionRole": "workspace"},
        conversation_id="session-workspace",
        direct_session_id="session-primary",
    )


def test_unmarked_non_primary_root_session_remains_a_mismatch() -> None:
    assert not _conversation_agent_direct_session_is_allowed(
        conversation={"sessionKind": "main"},
        conversation_id="session-workspace",
        direct_session_id="session-primary",
    )
