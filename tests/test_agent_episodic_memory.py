from pathlib import Path

import pytest

from core.web.services import agent_directory_service
from core.web.services.agent_directory import episodic_memory as episodic_memory_mod


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)


def _make_agent():
    return agent_directory_service.create_agent_instance(display_name="Episode Agent")


def _policy_path(agent_id: str, key: str) -> Path:
    policy = agent_directory_service.resolve_memory_policy_for_agent(agent_id)
    return agent_directory_service._resolve_project_path(str(policy.get(key) or ""))


def _jsonl_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_append_writes_policy_path_and_not_derived_or_public_stores(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = _make_agent()
    agent_id = agent["agentId"]

    event = agent_directory_service.append_episodic_event(
        agent_id,
        kind="preference",
        text="Prefer focused pytest over full suite.",
        refs=[{"type": "session", "id": "session-demo"}],
    )

    episode_path = _policy_path(agent_id, "episodicEventsPath")
    assert episode_path.exists()
    assert event["episodeId"]
    assert event["kind"] == "preference"
    assert event["validUntil"] == ""
    assert event["refs"] == [{"type": "session", "id": "session-demo"}]
    assert len(_jsonl_lines(episode_path)) == 1

    summaries_path = _policy_path(agent_id, "summariesPath")
    proposals_path = _policy_path(agent_id, "projectMemoryUpdatesPath")
    assert not summaries_path.exists()
    assert not proposals_path.exists()
    assert not (tmp_path / "workspace" / "knowledge" / "public").exists()


def test_supersede_keeps_jsonl_line_and_drops_from_current_list(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = _make_agent()
    agent_id = agent["agentId"]
    first = agent_directory_service.append_episodic_event(
        agent_id,
        kind="session_fact",
        text="Old fact",
        occurred_at="2026-08-15T01:00:00+00:00",
    )
    second = agent_directory_service.append_episodic_event(
        agent_id,
        kind="note",
        text="Replacement note",
        occurred_at="2026-08-15T02:00:00+00:00",
    )

    superseded = agent_directory_service.supersede_episodic_event(
        agent_id,
        first["episodeId"],
        successor_episode_id=second["episodeId"],
    )

    episode_path = _policy_path(agent_id, "episodicEventsPath")
    assert len(_jsonl_lines(episode_path)) == 2
    assert superseded["validUntil"]
    assert superseded["supersededByEpisodeId"] == second["episodeId"]

    current = agent_directory_service.list_current_episodic_events(agent_id)
    assert [item["episodeId"] for item in current] == [second["episodeId"]]
    assert current[0]["text"] == "Replacement note"


def test_list_current_is_newest_first(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = _make_agent()
    agent_id = agent["agentId"]
    older = agent_directory_service.append_episodic_event(
        agent_id,
        kind="private_note",
        text="Earlier",
        occurred_at="2026-08-14T10:00:00+00:00",
    )
    newer = agent_directory_service.append_episodic_event(
        agent_id,
        kind="private_note",
        text="Later",
        occurred_at="2026-08-15T10:00:00+00:00",
    )

    current = agent_directory_service.list_current_episodic_events(agent_id, limit=10)
    assert [item["episodeId"] for item in current] == [newer["episodeId"], older["episodeId"]]


def test_unknown_agent_and_missing_episode_raise(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    with pytest.raises(agent_directory_service.AgentNotFoundError):
        agent_directory_service.append_episodic_event("agent-missing", text="nope")

    agent = _make_agent()
    with pytest.raises(agent_directory_service.AgentEpisodicEventNotFoundError):
        agent_directory_service.supersede_episodic_event(agent["agentId"], "episode-missing")


def test_hot_path_module_does_not_import_llm():
    source = Path(episodic_memory_mod.__file__).read_text(encoding="utf-8")
    import_lines = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith("import ") or line.strip().startswith("from ")
    ]
    assert import_lines
    assert all("llm" not in line.lower() for line in import_lines)
