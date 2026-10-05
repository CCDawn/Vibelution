from __future__ import annotations

import pytest

from core.web.services.agent_directory import mutations
from core.web.services import agent_operation_service


def test_generic_agent_metadata_update_cannot_write_perception_policy(monkeypatch):
    class Directory:
        AgentDirectoryError = ValueError

    monkeypatch.setattr(mutations, "_service", lambda: Directory())
    with pytest.raises(ValueError, match="operator-only perception configuration API"):
        mutations.update_agent_instance("agent-a", metadata={"perceptionPolicy": {"enabled": True}})


def test_agent_creation_mutation_cannot_seed_perception_policy(monkeypatch):
    class Directory:
        AgentDirectoryError = ValueError

    monkeypatch.setattr(mutations, "_service", lambda: Directory())
    with pytest.raises(ValueError, match="cannot be set at Agent creation"):
        mutations.create_agent_instance(metadata={"perceptionPolicy": {"enabled": True}})


def test_agent_catalog_creation_rejects_policy_before_creating_a_session(monkeypatch):
    monkeypatch.setattr(
        agent_operation_service.session_service,
        "create_chat_session",
        lambda **_kwargs: pytest.fail("a rejected Agent create must not create a session"),
    )
    with pytest.raises(agent_operation_service.AgentDirectoryError, match="cannot be set at Agent creation"):
        agent_operation_service.create_agent_from_catalog_request(
            display_name="test agent",
            metadata={"perceptionPolicy": {"enabled": True}},
        )
