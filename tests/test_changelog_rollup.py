from pathlib import Path

from scripts import changelog_rollup


def _write(repo: Path, changelog: str, declarations: dict[str, str]) -> None:
    (repo / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    directory = repo / ".changelog"
    directory.mkdir()
    for name, body in declarations.items():
        (directory / name).write_text(body, encoding="utf-8")


def test_no_consume_keeps_declaration_files(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "# Changelog\n\n## Unreleased\n\n## 1.0.0 - 2026-01-01\n- old: shipped\n",
        {"task.md": "- feat: new thing\n"},
    )

    result = changelog_rollup.rollup(tmp_path, no_consume=True)

    assert result["inserted"] == 1
    assert (tmp_path / ".changelog" / "task.md").is_file()
    assert "- feat: new thing" in (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")


def test_consume_removes_declaration_files(tmp_path: Path) -> None:
    _write(tmp_path, "# Changelog\n\n## Unreleased\n", {"task.md": "- fix: thing\n"})

    result = changelog_rollup.rollup(tmp_path)

    assert result["inserted"] == 1
    assert not (tmp_path / ".changelog" / "task.md").exists()


def test_archived_entry_is_not_folded_again(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "# Changelog\n\n## Unreleased\n\n## 1.0.0 - 2026-01-01\n- feat: shipped\n",
        {"task.md": "- feat: shipped\n"},
    )

    result = changelog_rollup.rollup(tmp_path, no_consume=True)

    assert result["inserted"] == 0
    text = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text.count("- feat: shipped") == 1
