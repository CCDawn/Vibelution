from core.ui.chat_state import build_chat_state, load_chat_state, save_chat_state
from scripts.clear_chat_journal_state import clear_chat_journal_state


def test_clear_chat_journal_state_requires_confirmation_and_clears_runtime(tmp_path):
    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    save_chat_state(
        project_root,
        build_chat_state(
            [{"role": "user", "content": "旧消息", "timestamp": "2026-06-16T00:00:00"}],
            conversation_id="session-1",
            title="旧会话",
        ),
    )
    sessions_dir = project_root / "workspace" / "sessions" / "session-1"
    cli_session_dir = project_root / ".runtime" / "cli_agents" / "sessions"
    sessions_dir.mkdir(parents=True)
    cli_session_dir.mkdir(parents=True)
    (sessions_dir / "turn_journal.jsonl").write_text("dirty\n", encoding="utf-8")
    (cli_session_dir / "cli-term-1.json").write_text("{}", encoding="utf-8")

    preview = clear_chat_journal_state(project_root, confirm_delete=False)

    assert preview["status"] == "preview"
    assert sessions_dir.exists()
    assert cli_session_dir.exists()
    assert load_chat_state(project_root)["conversations"][0]["messages"][0]["content"] == "旧消息"

    cleared = clear_chat_journal_state(project_root, confirm_delete=True)

    assert cleared["status"] == "cleared"
    assert not sessions_dir.exists()
    assert not cli_session_dir.exists()
    state = load_chat_state(project_root)
    assert state["conversations"][0]["conversation_id"] == "default"
    assert state["conversations"][0]["messages"] == []
