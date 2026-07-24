"""Role-default agent avatars: specific duties beat broad modes."""

from __future__ import annotations

from core.web.services import agent_directory_service as s


AVAILABLE = list(s.AGENT_AVATAR_FILENAMES)


def _agent(
    *,
    code: str = "A01",
    primary_mode: str = "chat",
    role_key: str = "",
    metadata: dict | None = None,
) -> dict:
    return {
        "agentCode": code,
        "primaryMode": primary_mode,
        "roleKey": role_key,
        "metadata": dict(metadata or {}),
    }


def _filename(agent: dict) -> str:
    return s._default_agent_avatar_filename(agent, available_avatar_filenames=AVAILABLE)


def test_chat_session_agent_uses_session_avatar():
    assert _filename(_agent(primary_mode="chat", role_key="")) == "01-session-agent.png"


def test_knowledge_steward_not_stolen_by_general_mode():
    agent = _agent(
        primary_mode="general",
        role_key="knowledge_steward",
        metadata={"systemRole": "knowledge_steward", "functionalDisplayName": "知识库管理员"},
    )
    assert _filename(agent) == "15-anime-memory-steward-agent.png"


def test_supervised_roles_are_distinguishable():
    baseline = _filename(
        _agent(
            primary_mode="supervised_evolution",
            role_key="baseline",
            metadata={"supervisedRole": "baseline"},
        )
    )
    candidate = _filename(
        _agent(
            primary_mode="supervised_evolution",
            role_key="candidate",
            metadata={"supervisedRole": "candidate"},
        )
    )
    judge = _filename(
        _agent(
            primary_mode="supervised_evolution",
            role_key="judge",
            metadata={"supervisedRole": "judge"},
        )
    )
    assert baseline == "03-inspect-agent.png"
    assert candidate == "12-anime-tool-executor-agent.png"
    assert judge == "09-card-planner.png"
    assert len({baseline, candidate, judge}) == 3


def test_self_evolution_subroles_not_collapsed_to_mode_face():
    executor = _filename(
        _agent(
            primary_mode="self_evolution",
            role_key="executor",
            metadata={"selfEvolutionRole": "executor"},
        )
    )
    observer = _filename(
        _agent(
            primary_mode="self_evolution",
            role_key="observer",
            metadata={"selfEvolutionRole": "observer"},
        )
    )
    reviewer = _filename(
        _agent(
            primary_mode="self_evolution",
            role_key="reviewer",
            metadata={"selfEvolutionRole": "reviewer"},
        )
    )
    assert executor == "12-anime-tool-executor-agent.png"
    assert observer == "16-anime-self-evolution-agent.png"
    assert reviewer == "13-anime-review-evaluator-agent.png"
    assert len({executor, observer, reviewer}) == 3


def test_capability_manager_uses_system_face():
    agent = _agent(
        primary_mode="general",
        role_key="capability_manager",
        metadata={"functionalDisplayName": "能力管家"},
    )
    assert _filename(agent) == "18-anime-system-service-agent.png"


def test_ensure_does_not_override_custom_avatar(tmp_path, monkeypatch):
    from tests.test_agent_avatar_model_repair import _use_isolated_agent_directory

    _use_isolated_agent_directory(tmp_path, monkeypatch)
    avatar_dir = tmp_path / "data" / "workspace" / "avatars"
    avatar_dir.mkdir(parents=True)
    custom = "10-anime-session-agent.png"
    (avatar_dir / custom).write_bytes(b"\x89PNG\r\n\x1a\ncustom")
    (avatar_dir / "01-session-agent.png").write_bytes(b"\x89PNG\r\n\x1a\nsession")

    agent = {
        "agentId": "agent-x",
        "agentCode": "A99",
        "primaryMode": "chat",
        "roleKey": "",
        "metadata": {
            "avatarImagePath": f"workspace/avatars/{custom}",
            "avatarImageSource": "custom",
        },
    }
    changed = s._ensure_agent_default_avatar(agent)
    assert changed is False
    assert agent["metadata"]["avatarImagePath"].endswith(custom)


def test_projection_fills_default_path_when_metadata_missing():
    agent = _agent(primary_mode="chat", role_key="")
    path = s.resolve_agent_avatar_path_for_projection(agent, available_avatar_filenames=AVAILABLE)
    assert path == "workspace/avatars/01-session-agent.png"
