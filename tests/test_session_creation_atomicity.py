"""Session creation atomicity regressions."""

from __future__ import annotations

import pytest

from core.infrastructure import developer_sandbox
from core.ui.chat_state import list_session_runtime_ids
from core.web.services import session_service


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


def test_failed_agent_initialization_does_not_leave_session_runtime_row(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_ensure_conversation_workspace_metadata",
        lambda _conversation: False,
    )
    monkeypatch.setattr(session_service, "_sync_agent_directory_project_root", lambda: None)

    def fail_agent_initialization(*_args, **_kwargs):
        raise RuntimeError("agent initialization failed")

    monkeypatch.setattr(session_service, "ensure_agent_for_session", fail_agent_initialization)

    with pytest.raises(RuntimeError, match="agent initialization failed"):
        session_service.create_chat_session(title="Atomic create", lightweight=True)

    assert list_session_runtime_ids(tmp_path) == []
