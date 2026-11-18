from __future__ import annotations

from pathlib import Path

from scripts import changelog_declaration_guard as guard


def test_product_paths_are_guarded():
    assert guard.is_product_path("core/web/app.py")
    assert guard.is_product_path("web/src/app/AppShell.tsx")
    assert guard.is_product_path("config/runtime.toml")
    assert guard.is_product_path("agent.py")


def test_non_product_paths_are_exempt():
    assert not guard.is_product_path("tests/test_x.py")
    assert not guard.is_product_path("docs/guide.md")
    assert not guard.is_product_path("scripts/tool.py")
    assert not guard.is_product_path("web/src/app/README.md")


def test_unreleased_section_stops_at_next_release_heading():
    text = "# Changelog\n\n## Unreleased\n\n### Added\n- a\n\n## 2.0.0 - 2026-10-03\n- b\n"
    section = guard.unreleased_section(text)
    assert "- a" in section
    assert "- b" not in section


def test_has_new_declaration_detects_only_added_lines():
    old = "## Unreleased\n### Added\n- a\n\n## 2.0.0 - 2026-10-03\n"
    newer = "## Unreleased\n### Added\n- a\n- b\n\n## 2.0.0 - 2026-10-03\n"
    assert not guard.has_new_declaration(old, old)
    assert guard.has_new_declaration(old, newer)


def test_evaluate_requires_a_declaration_for_product_code(monkeypatch):
    monkeypatch.setattr(guard, "staged_paths", lambda repo: ["core/web/app.py"])
    monkeypatch.setattr(guard, "file_at", lambda repo, revision: "## Unreleased\n\n## 2.0.0\n")
    ok, detail = guard.evaluate(Path("."))
    assert not ok
    assert "Unreleased" in detail


def test_evaluate_passes_when_changelog_line_is_added(monkeypatch):
    old = "## Unreleased\n### Added\n- a\n\n## 2.0.0\n"
    newer = "## Unreleased\n### Added\n- a\n- b\n\n## 2.0.0\n"
    monkeypatch.setattr(guard, "staged_paths", lambda repo: ["core/web/app.py", "CHANGELOG.md"])
    monkeypatch.setattr(guard, "file_at", lambda repo, revision: old if revision == "HEAD" else newer)
    ok, _ = guard.evaluate(Path("."))
    assert ok


def test_evaluate_ignores_test_only_commits(monkeypatch):
    monkeypatch.setattr(guard, "staged_paths", lambda repo: ["tests/test_x.py"])
    ok, _ = guard.evaluate(Path("."))
    assert ok

def test_test_and_spec_files_are_not_product_code():
    assert not guard.is_product_path("web/src/routes/chat/useSessionIndexEventStream.test.ts")
    assert not guard.is_product_path("core/web/app.spec.py")
    assert guard.is_product_path("web/src/routes/chat/useSessionIndexEventStream.ts")
