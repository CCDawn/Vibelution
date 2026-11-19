"""Contract tests for the version projection sync script."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from core.platform_version.ledger import (
    Cadence,
    VersionEntry,
    VersionLedger,
    extract_unreleased,
    parse_version,
)
from core.platform_version.settler import VersionWatcher
from scripts.sync_platform_version_projections import (
    COMMIT_MESSAGE_PREFIX,
    archive_unreleased,
    sync_version_projections,
)

TODAY = "2026-11-19"

CHANGELOG_WITH_PENDING = """\
# Changelog

## Unreleased
- feat: first declared change.
- fix: second declared change.

## 2.0.0 - 2026-10-03

- baseline entry.
"""

PACKAGE_JSON = {
    "name": "fixture-web",
    "private": True,
    "version": "2.0.0",
    "type": "module",
}

PACKAGE_LOCK_JSON = {
    "name": "fixture-web",
    "lockfileVersion": 3,
    "version": "2.0.0",
    "packages": {
        "": {"name": "fixture-web", "version": "2.0.0"},
        "node_modules/left-pad": {"version": "1.3.0"},
    },
}


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A git repo whose VERSION projections lag an already-settled ledger."""

    root = tmp_path / "repo"
    root.mkdir()
    assert _run_git(root, "init").returncode == 0
    _run_git(root, "config", "user.email", "sync@example.invalid")
    _run_git(root, "config", "user.name", "Sync Test")
    (root / "VERSION").write_text("2.0.0\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(CHANGELOG_WITH_PENDING, encoding="utf-8", newline="\n")
    _write_json(root / "web" / "package.json", PACKAGE_JSON)
    _write_json(root / "web" / "package-lock.json", PACKAGE_LOCK_JSON)
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "seed")
    _run_git(root, "branch", "-M", "main")
    return root


def _ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "ledger.jsonl"


def _sync(root: Path, tmp_path: Path, **kwargs):
    """Run a real sync; temp repos have no guard hooks, so a test claim id
    satisfies the main-branch permit parameter."""

    kwargs.setdefault("integration_claim_id", "claim-test")
    return sync_version_projections(root, ledger_path=_ledger_path(tmp_path), **kwargs)


def _seed_ledger(tmp_path: Path, root: Path, tail_version: str) -> VersionLedger:
    """A ledger already settled to ``tail_version`` (baseline plus one entry)."""

    ledger = VersionLedger(root, ledger_path=_ledger_path(tmp_path))
    ledger.append(
        VersionEntry(
            seq=1,
            version="2.0.0",
            build=0,
            head_sha="",
            head_subject="baseline from VERSION",
            kind="baseline",
            summary="baseline",
            changelog_digest="",
            recorded_at="2026-11-01T00:00:00+00:00",
            anchor="baseline",
        )
    )
    tail = parse_version(tail_version) or Cadence()
    ledger.append(
        VersionEntry(
            seq=2,
            version=tail.version,
            build=1,
            head_sha="a" * 40,
            head_subject="feat: earlier settled merge",
            kind="feature",
            summary="earlier",
            changelog_digest="d" * 64,
            recorded_at="2026-11-02T00:00:00+00:00",
            anchor="settle",
        )
    )
    return ledger


def test_sync_projects_tail_archives_verbatim_and_commits(
    repo: Path, tmp_path: Path
) -> None:
    _seed_ledger(tmp_path, repo, "2.0.3")

    payload = _sync(repo, tmp_path, today=TODAY)

    assert payload["ok"] is True
    assert payload["settled"] is True
    assert payload["oldVersion"] == "2.0.0"
    assert payload["newVersion"] == "2.0.4"
    assert payload["versionChanged"] is True
    assert payload["committed"] is True
    assert payload["commitMessage"] == f"{COMMIT_MESSAGE_PREFIX} 2.0.4"
    assert payload["boundary"] is None

    assert (repo / "VERSION").read_text(encoding="utf-8") == "2.0.4\n"
    package = json.loads((repo / "web" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((repo / "web" / "package-lock.json").read_text(encoding="utf-8"))
    assert package["version"] == "2.0.4"
    assert lock["version"] == "2.0.4"
    assert lock["packages"][""]["version"] == "2.0.4"
    # A dependency pin must never be touched by the projection.
    assert lock["packages"]["node_modules/left-pad"]["version"] == "1.3.0"

    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 2.0.4 - 2026-11-19" in changelog
    assert "- feat: first declared change." in changelog
    assert "- fix: second declared change." in changelog
    unreleased = extract_unreleased(changelog)
    assert unreleased is None

    head = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
    assert head == payload["commitSha"]
    assert _run_git(repo, "status", "--porcelain").stdout.strip() == ""
    subject = _run_git(repo, "log", "-1", "--format=%s").stdout.strip()
    assert subject == f"{COMMIT_MESSAGE_PREFIX} 2.0.4"
    # Single author identity, no bot attribution.
    author = _run_git(repo, "log", "-1", "--format=%an %ae").stdout.strip()
    assert author == "Sync Test sync@example.invalid"


def test_sync_is_idempotent(repo: Path, tmp_path: Path) -> None:
    _seed_ledger(tmp_path, repo, "2.0.4")
    first = _sync(repo, tmp_path, today=TODAY)
    assert first["ok"] is True

    commits_after_first = _run_git(repo, "rev-list", "--count", "HEAD").stdout.strip()
    snapshots = {
        path: (repo / path).read_bytes()
        for path in ("VERSION", "CHANGELOG.md", "web/package.json", "web/package-lock.json")
    }

    second = _sync(repo, tmp_path, today=TODAY)

    assert second["ok"] is True
    assert second["settled"] is False
    assert second["versionChanged"] is False
    assert second["changedFiles"] == []
    assert second["committed"] is False
    assert second["boundary"] is None
    assert _run_git(repo, "rev-list", "--count", "HEAD").stdout.strip() == commits_after_first
    assert snapshots == {
        path: (repo / path).read_bytes()
        for path in ("VERSION", "CHANGELOG.md", "web/package.json", "web/package-lock.json")
    }


def test_sync_commit_does_not_resettle(repo: Path, tmp_path: Path) -> None:
    """The sync commit itself must not advance the ledger again."""

    _seed_ledger(tmp_path, repo, "2.0.4")
    payload = _sync(repo, tmp_path, today=TODAY)
    assert payload["ok"] is True
    ledger = VersionLedger(repo, ledger_path=_ledger_path(tmp_path))
    count_before = len(ledger.read())

    watcher = VersionWatcher(repo, ledger_path=_ledger_path(tmp_path))
    settled_by_watcher = asyncio.run(watcher.tick())

    assert settled_by_watcher is False
    assert len(ledger.read()) == count_before

    # Even if the archived text were re-declared verbatim under Unreleased,
    # the digest dedup refuses to count it twice.
    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    archived = changelog.split("## 2.1.0 - 2026-11-19", 1)[1].split("## 2.0.0", 1)[0]
    redeclared = changelog.replace("## Unreleased\n", f"## Unreleased\n{archived.strip()}\n", 1)
    (repo / "CHANGELOG.md").write_text(redeclared, encoding="utf-8", newline="\n")
    unreleased = extract_unreleased(redeclared)
    assert unreleased is not None
    head_sha = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
    assert ledger.settle(head_sha=head_sha, head_subject="resync", unreleased=unreleased) is None
    assert len(ledger.read()) == count_before


def test_sync_settles_when_the_watcher_never_ran(repo: Path, tmp_path: Path) -> None:
    """Option A: the sync settles pending declarations itself, idempotently."""

    ledger = VersionLedger(repo, ledger_path=_ledger_path(tmp_path))
    assert ledger.read() == []

    payload = _sync(repo, tmp_path, today=TODAY)

    assert payload["ok"] is True
    assert payload["settled"] is True
    assert payload["newVersion"] == "2.0.1"
    entries = VersionLedger(repo, ledger_path=_ledger_path(tmp_path)).read()
    assert [entry.version for entry in entries] == ["2.0.0", "2.0.1"]
    assert entries[-1].anchor == "settle"


def test_sync_boundary_minor_and_major(tmp_path: Path) -> None:
    """5-patch and 10-minor carries emit boundary signals with the tag name."""

    # Minor carry: 2.0.4 -> 2.1.0.
    root = tmp_path / "minor"
    root.mkdir()
    assert _run_git(root, "init").returncode == 0
    _run_git(root, "config", "user.email", "sync@example.invalid")
    _run_git(root, "config", "user.name", "Sync Test")
    (root / "VERSION").write_text("2.0.4\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n- feat: crosses the minor edge.\n\n## 2.0.4 - 2026-11-18\n\n- prior.\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_json(root / "web" / "package.json", dict(PACKAGE_JSON, version="2.0.4"))
    _write_json(root / "web" / "package-lock.json", dict(PACKAGE_LOCK_JSON, version="2.0.4"))
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "seed")
    ledger = VersionLedger(root, ledger_path=tmp_path / "minor-ledger.jsonl")
    ledger.append(
        VersionEntry(
            seq=1,
            version="2.0.4",
            build=4,
            head_sha="",
            head_subject="baseline",
            kind="baseline",
            summary="baseline",
            changelog_digest="",
            recorded_at="2026-11-01T00:00:00+00:00",
            anchor="baseline",
        )
    )

    minor = sync_version_projections(
        root, ledger_path=ledger.path, today=TODAY, integration_claim_id="claim-test",
    )
    assert minor["ok"] is True
    assert minor["newVersion"] == "2.1.0"
    assert minor["boundary"] is not None
    assert minor["boundary"]["kind"] == "minor"
    assert minor["boundary"]["tag"] == "v2.1.0"
    assert "crosses the minor edge" in minor["boundary"]["notes"]

    # Major carry: 2.9.4 -> 3.0.0.
    root = tmp_path / "major"
    root.mkdir()
    assert _run_git(root, "init").returncode == 0
    _run_git(root, "config", "user.email", "sync@example.invalid")
    _run_git(root, "config", "user.name", "Sync Test")
    (root / "VERSION").write_text("2.9.4\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n- feat: crosses the major edge.\n\n## 2.9.4 - 2026-11-18\n\n- prior.\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_json(root / "web" / "package.json", dict(PACKAGE_JSON, version="2.9.4"))
    _write_json(root / "web" / "package-lock.json", dict(PACKAGE_LOCK_JSON, version="2.9.4"))
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "seed")
    ledger = VersionLedger(root, ledger_path=tmp_path / "major-ledger.jsonl")
    ledger.append(
        VersionEntry(
            seq=1,
            version="2.9.4",
            build=49,
            head_sha="",
            head_subject="baseline",
            kind="baseline",
            summary="baseline",
            changelog_digest="",
            recorded_at="2026-11-01T00:00:00+00:00",
            anchor="baseline",
        )
    )

    major = sync_version_projections(
        root, ledger_path=ledger.path, today=TODAY, integration_claim_id="claim-test",
    )
    assert major["ok"] is True
    assert major["newVersion"] == "3.0.0"
    assert major["boundary"] is not None
    assert major["boundary"]["kind"] == "major"
    assert major["boundary"]["tag"] == "v3.0.0"
    assert "crosses the major edge" in major["boundary"]["notes"]
    # Notes carry the CHANGELOG text of the crossed (old, new] range: the new
    # block itself, not blocks at or below the previous VERSION.
    assert "## 3.0.0 - 2026-11-19" in major["boundary"]["notes"]
    assert "## 2.9.4" not in major["boundary"]["notes"]


def test_dry_run_matches_the_real_run(repo: Path, tmp_path: Path) -> None:
    _seed_ledger(tmp_path, repo, "2.0.4")
    before = {
        path: (repo / path).read_bytes()
        for path in ("VERSION", "CHANGELOG.md", "web/package.json", "web/package-lock.json")
    }

    plan = sync_version_projections(
        repo, ledger_path=_ledger_path(tmp_path), dry_run=True, today=TODAY,
    )

    assert plan["ok"] is True
    assert plan["dryRun"] is True
    assert before == {
        path: (repo / path).read_bytes()
        for path in ("VERSION", "CHANGELOG.md", "web/package.json", "web/package-lock.json")
    }, "dry run must not touch any file"
    assert VersionLedger(repo, ledger_path=_ledger_path(tmp_path)).tail().version == "2.0.4"

    result = _sync(repo, tmp_path, today=TODAY)

    assert result["ok"] is True
    for field in ("settled", "oldVersion", "newVersion", "versionChanged", "boundary", "changedFiles"):
        assert plan[field] == result[field], field
    assert plan["archive"]["needed"] == result["archive"]["needed"]
    assert result["committed"] is True


def test_sync_on_main_branch_moves_the_guarded_ref(tmp_path: Path) -> None:
    """On ``main`` the commit goes through the permit path, not a plain commit."""

    root = tmp_path / "mainrepo"
    root.mkdir()
    assert _run_git(root, "init").returncode == 0
    _run_git(root, "config", "user.email", "sync@example.invalid")
    _run_git(root, "config", "user.name", "Sync Test")
    (root / "VERSION").write_text("2.0.0\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n- feat: pending on main.\n\n## 2.0.0 - 2026-10-03\n\n- old.\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_json(root / "web" / "package.json", PACKAGE_JSON)
    _write_json(root / "web" / "package-lock.json", PACKAGE_LOCK_JSON)
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "seed")
    _run_git(root, "branch", "-M", "main")
    old_sha = _run_git(root, "rev-parse", "HEAD").stdout.strip()
    ledger = VersionLedger(root, ledger_path=tmp_path / "main-ledger.jsonl")
    ledger.append(
        VersionEntry(
            seq=1,
            version="2.0.0",
            build=0,
            head_sha="",
            head_subject="baseline",
            kind="baseline",
            summary="baseline",
            changelog_digest="",
            recorded_at="2026-11-01T00:00:00+00:00",
            anchor="baseline",
        )
    )

    payload = sync_version_projections(
        root,
        ledger_path=ledger.path,
        today=TODAY,
        integration_claim_id="claim-test",
    )

    assert payload["ok"] is True
    assert payload["committed"] is True
    assert payload["commitMode"] == "permit"
    assert payload["newVersion"] == "2.0.1"
    assert _run_git(root, "rev-parse", "refs/heads/main").stdout.strip() == payload["commitSha"]
    assert _run_git(root, "status", "--porcelain").stdout.strip() == ""
    assert old_sha in _run_git(root, "log", "--format=%H", "HEAD").stdout
    permit = (
        Path(_run_git(root, "rev-parse", "--git-common-dir").stdout.strip())
        / "vibelution-cache"
        / "main-ref-permit.json"
    )
    assert not permit.exists()


def test_archive_unreleased_keeps_wording_and_layout() -> None:
    new_text, archived = archive_unreleased(
        CHANGELOG_WITH_PENDING, version="2.0.1", date_label=TODAY,
    )
    assert archived == ["- feat: first declared change.", "- fix: second declared change."]
    assert new_text == (
        "# Changelog\n"
        "\n"
        "## Unreleased\n"
        "\n"
        "## 2.0.1 - 2026-11-19\n"
        "- feat: first declared change.\n"
        "- fix: second declared change.\n"
        "\n"
        "## 2.0.0 - 2026-10-03\n"
        "\n"
        "- baseline entry.\n"
    )


def test_archive_unreleased_is_noop_when_section_is_empty() -> None:
    text = "# Changelog\n\n## Unreleased\n\n## 2.0.0 - 2026-10-03\n\n- old.\n"
    new_text, archived = archive_unreleased(text, version="2.0.1", date_label=TODAY)
    assert archived == []
    assert new_text == text
