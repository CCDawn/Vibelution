from pathlib import Path

from core.chat.skill_registry import build_skill_runtime_context, resolve_skill
from core.chat.slash_commands import parse_skill_slash_command


def _write_skill(root: Path, dirname: str, *, name: str, body: str = "Use this workflow.") -> Path:
    skill_dir = root / dirname
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        f"---\nname: {name}\ndescription: demo skill\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def test_parse_skill_slash_command_resolves_named_skill(tmp_path):
    _write_skill(tmp_path, "ccdawn-brt", name="ccdawn-brt", body="Stop before implementation.")

    command = parse_skill_slash_command("/ccdawn-brt 设计权限流", skill_roots=[tmp_path])

    assert command is not None
    assert command.command == "ccdawn-brt"
    assert command.args == "设计权限流"
    assert command.skill.name == "ccdawn-brt"
    assert command.skill.content_hash


def test_parse_skill_slash_command_accepts_newline_args(tmp_path):
    _write_skill(tmp_path, "brt", name="brt")

    command = parse_skill_slash_command("/brt\n设计多行输入", skill_roots=[tmp_path])

    assert command is not None
    assert command.command == "brt"
    assert command.args == "设计多行输入"


def test_parse_skill_slash_command_ignores_unknown_and_paths(tmp_path):
    _write_skill(tmp_path, "brt", name="brt")

    assert parse_skill_slash_command("/unknown 继续", skill_roots=[tmp_path]) is None
    assert parse_skill_slash_command("/config", skill_roots=[tmp_path]) is None
    assert parse_skill_slash_command("请用 /brt 分析", skill_roots=[tmp_path]) is None


def test_resolve_skill_accepts_versionless_directory_alias(tmp_path):
    _write_skill(tmp_path, "code-1.0.4", name="Code")

    skill = resolve_skill("code", roots=[tmp_path])

    assert skill is not None
    assert "code" in skill.aliases


def test_resolve_skill_accepts_versionless_directory_alias_without_frontmatter_name(tmp_path):
    skill_dir = tmp_path / "browser-agent-1.2.3"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Browser Agent\n\nUse browser automation.\n", encoding="utf-8")

    skill = resolve_skill("browser-agent", roots=[tmp_path])

    assert skill is not None
    assert "browser-agent" in skill.aliases


def test_build_skill_runtime_context_keeps_user_args_separate(tmp_path):
    _write_skill(tmp_path, "brt", name="brt", body="Ask one question at a time.")
    command = parse_skill_slash_command("/brt 设计斜杠指令", skill_roots=[tmp_path])

    context = build_skill_runtime_context(command.skill, command=command.command, args=command.args)

    assert "## Slash Skill Context" in context
    assert "Command: /brt" in context
    assert "SlashCommandArgs:" in context
    assert "设计斜杠指令" in context
    assert "Ask one question at a time." in context
