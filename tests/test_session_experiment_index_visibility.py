from __future__ import annotations

from core.ui.chat_state import save_chat_state
from core.web.services import agent_directory_service, session_service


def _team_session_summary(*, experiment_binding: dict | None, hidden: bool = False) -> dict:
    return {
        "id": "session-experiment-source-finder",
        "agentId": "agent-source-finder",
        "agentMissing": False,
        "hiddenFromIndex": hidden,
        "sessionKind": "main",
        "conversationIndexKind": agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        "conversationIndexVisibility": agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE,
        "experimentBinding": experiment_binding,
    }


def test_experiment_bound_team_session_is_visible_in_flat_session_index() -> None:
    summary = _team_session_summary(
        experiment_binding={
            "teamId": "research-team",
            "researchProjectId": "research-alpha",
            "experimentName": "Alpha experiment",
            "agentId": "agent-source-finder",
            "roleKey": "source_finder",
            "attempt": 1,
        }
    )

    assert session_service._session_agent_visible_in_indexes(summary) is True


def test_team_session_without_valid_experiment_binding_stays_private() -> None:
    assert session_service._session_agent_visible_in_indexes(
        _team_session_summary(experiment_binding=None)
    ) is False


def test_list_sessions_includes_experiment_bound_team_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent_directory_service.save_state(
        {
            "agents": [
                {
                    "agentId": "agent-source-finder",
                    "agentCode": "A015",
                    "displayName": "资料寻找",
                    "kind": "persistent",
                    "status": "active",
                    "primaryMode": "research",
                    "roleKey": "source_finder",
                    "directSessionId": "legacy-direct-session",
                    "metadata": {
                        "conversationIndexKind": "team_agent",
                        "conversationIndexVisibility": "team_private",
                        "challengeCupTeamId": "research-team",
                        "showInSessionIndex": False,
                    },
                }
            ]
        }
    )
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-experiment-source-finder",
            "updated_at": "2026-07-27T13:47:44Z",
            "conversations": [
                {
                    "conversation_id": "session-experiment-source-finder",
                    "title": "Alpha experiment｜资料寻找",
                    "agent_id": "agent-source-finder",
                    "agentId": "agent-source-finder",
                    "session_kind": "main",
                    "updated_at": "2026-07-27T13:47:44Z",
                    "messages": [],
                    "experiment_binding": {
                        "teamId": "research-team",
                        "researchProjectId": "research-alpha",
                        "experimentName": "Alpha experiment",
                        "agentId": "agent-source-finder",
                        "roleKey": "source_finder",
                        "attempt": 1,
                    },
                }
            ],
        },
    )
    session_service._invalidate_session_list_cache()

    listed = session_service.list_sessions()

    assert [item["id"] for item in listed] == ["session-experiment-source-finder"]
    assert listed[0]["title"] == "Alpha experiment｜资料寻找"
    assert listed[0]["experimentBinding"]["researchProjectId"] == "research-alpha"
    assert session_service._session_agent_visible_in_indexes(
        _team_session_summary(
            experiment_binding={
                "teamId": "research-team",
                "researchProjectId": "research-alpha",
                "agentId": "another-agent",
            }
        )
    ) is False
    assert session_service._session_agent_visible_in_indexes(
        _team_session_summary(
            experiment_binding={
                "teamId": "research-team",
                "researchProjectId": "research-alpha",
                "agentId": "agent-source-finder",
            },
            hidden=True,
        )
    ) is False
