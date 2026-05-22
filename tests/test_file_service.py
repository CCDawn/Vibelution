from __future__ import annotations

import pytest

from core.web.services import file_service


def test_file_service_reads_relative_project_files(tmp_path, monkeypatch):
    target = tmp_path / "docs" / "note.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"# note\n")
    monkeypatch.setattr(file_service, "PROJECT_ROOT", tmp_path)

    payload = file_service.read_text_file("docs/note.md")
    dot_prefixed_payload = file_service.read_text_file("./docs/note.md")

    assert payload["path"] == "docs/note.md"
    assert payload["language"] == "markdown"
    assert payload["content"] == "# note\n"
    assert dot_prefixed_payload["content"] == "# note\n"


@pytest.mark.parametrize(
    "path",
    [
        r"C:inside.txt",
        r"C:\Users\17533\secret.txt",
        r"\Windows\system32\drivers\etc\hosts",
        "/etc/passwd",
        r"..\outside.txt",
    ],
)
def test_file_service_rejects_absolute_and_drive_qualified_paths(tmp_path, monkeypatch, path):
    (tmp_path / "inside.txt").write_bytes(b"inside\n")
    monkeypatch.setattr(file_service, "PROJECT_ROOT", tmp_path)

    with pytest.raises(ValueError, match="project root"):
        file_service.read_text_file(path)
