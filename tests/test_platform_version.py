"""Contract tests for the local platform-version ledger."""

from __future__ import annotations

from pathlib import Path

from core.platform_version.ledger import (
    Cadence,
    VersionLedger,
    advance,
    extract_unreleased,
    parse_version,
    resolve_ledger_path,
    snapshot,
)


def test_advance_carries_five_patches_into_one_minor() -> None:
    cadence = Cadence(major=2, minor=0, patch=0, build=10)
    seen: list[str] = []
    for _ in range(5):
        cadence = advance(cadence)
        seen.append(cadence.version)
    assert seen == ["2.0.1", "2.0.2", "2.0.3", "2.0.4", "2.1.0"]
    assert cadence.build == 15


def test_advance_carries_ten_minors_into_one_major() -> None:
    cadence = advance(Cadence(major=2, minor=9, patch=4, build=0))
    assert cadence.version == "3.0.0"
    assert cadence.build == 1


def test_parse_version_tolerates_prefix_and_rejects_junk() -> None:
    assert parse_version("v2.1.3") == Cadence(major=2, minor=1, patch=3, build=0)
    assert parse_version("2.1") is None
    assert parse_version("") is None


def test_empty_unreleased_does_not_settle() -> None:
    changelog = "# Changelog\n\n## Unreleased\n\n## 2.0.0\n\n- an old change\n"
    assert extract_unreleased(changelog) is None


def test_missing_unreleased_heading_does_not_settle() -> None:
    assert extract_unreleased("# Changelog\n\n## 2.0.0\n\n- an old change\n") is None


def test_unreleased_classification_and_summary() -> None:
    changelog = (
        "# Changelog\n\n## Unreleased\n\n### Breaking\n\n- Drop the legacy path.\n\n"
        "## 2.0.0\n\n- old\n"
    )
    entry = extract_unreleased(changelog)
    assert entry is not None
    assert entry.kind == "breaking"
    assert entry.summary == "Drop the legacy path."
    assert entry.digest


def test_feature_and_fix_classification() -> None:
    added = extract_unreleased("## Unreleased\n\n### Added\n\n- New surface.\n")
    fixed = extract_unreleased("## Unreleased\n\n### Fixed\n\n- Broken surface.\n")
    assert added is not None and added.kind == "feature"
    assert fixed is not None and fixed.kind == "fix"


def test_ledger_settle_is_idempotent_per_head(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("2.0.0", encoding="utf-8")
    ledger = VersionLedger(tmp_path, ledger_path=tmp_path / "ledger.jsonl")
    unreleased = extract_unreleased("## Unreleased\n\n### Added\n\n- A feature.\n")
    assert unreleased is not None
    first = ledger.settle(head_sha="a" * 40, head_subject="feat: thing", unreleased=unreleased)
    assert first is not None
    assert first.version == "2.0.1"
    assert first.seq == 2
    assert ledger.settle(head_sha="a" * 40, head_subject="feat: thing", unreleased=unreleased) is None
    assert len(ledger.read()) == 2


def test_settle_advances_from_previous_position(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("2.0.0", encoding="utf-8")
    ledger = VersionLedger(tmp_path, ledger_path=tmp_path / "ledger.jsonl")
    unreleased = extract_unreleased("## Unreleased\n\n### Fixed\n\n- One fix.\n")
    assert unreleased is not None
    versions = []
    for index in range(6):
        entry = ledger.settle(
            head_sha=f"{index:040d}", head_subject="fix", unreleased=unreleased
        )
        assert entry is not None
        versions.append(entry.version)
    assert versions == ["2.0.1", "2.0.2", "2.0.3", "2.0.4", "2.1.0", "2.1.1"]


def test_snapshot_reports_projection_lag(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("2.0.0", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n\n### Added\n\n- A feature.\n", encoding="utf-8"
    )
    ledger_path = tmp_path / "ledger.jsonl"
    ledger = VersionLedger(tmp_path, ledger_path=ledger_path)
    unreleased = extract_unreleased((tmp_path / "CHANGELOG.md").read_text(encoding="utf-8"))
    assert unreleased is not None
    assert ledger.settle(head_sha="b" * 40, head_subject="feat", unreleased=unreleased) is not None

    payload = snapshot(tmp_path, ledger_path=ledger_path)
    assert payload["currentVersion"] == "2.0.1"
    assert payload["fileVersion"] == "2.0.0"
    assert payload["fileBehind"] is True
    assert payload["progress"] == {"patchInMinor": 1, "minorInMajor": 0}
    assert payload["cadence"]["patchPerMinor"] == 5
    assert payload["cadence"]["minorPerMajor"] == 10
    assert payload["entries"][0]["version"] == "2.0.1"


def test_resolve_ledger_path_honors_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBELUTION_PLATFORM_VERSION_ROOT", str(tmp_path / "state"))
    assert resolve_ledger_path(tmp_path) == tmp_path / "state" / "ledger.jsonl"


def test_resolve_ledger_path_stays_outside_checkout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VIBELUTION_PLATFORM_VERSION_ROOT", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    resolved = resolve_ledger_path(tmp_path / "checkout")
    assert (tmp_path / "checkout") not in resolved.parents
