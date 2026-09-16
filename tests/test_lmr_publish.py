from __future__ import annotations

"""Tests for the LMR publish queue (``scripts/lmr_publish.py``).

Each test builds a throwaway git repository plus a local ``git init --bare``
origin, isolated from any inherited repository-level git environment
variables (AGENTS.md red line). Scenarios cover: below-threshold no-op,
``--now`` immediate publish with record flip, age/batch thresholds, secret
hygiene fail-loud (defaults and env extension), unreachable remote retries
without blocking integration, dry-run preview, and tolerant ledger scanning.
"""

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import lmr_publish


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    completed = subprocess.run(
        ["git", *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and completed.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {completed.stderr}")
    return completed


@pytest.fixture()
def isolated_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in list(os.environ):
        if var.startswith("GIT_"):
            monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture()
def publish_repo(tmp_path: Path, isolated_git_env: None) -> Path:
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "--initial-branch=main", str(repo))
    _git(repo, "config", "user.name", "LMR Publish Test")
    _git(repo, "config", "user.email", "lmr-publish@test.local")
    readme = repo / "README.md"
    with open(readme, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")
    return repo


def _commit_file(repo: Path, rel_path: str, content: str, message: str) -> str:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    _git(repo, "add", rel_path)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ledger_dir(repo: Path) -> Path:
    return repo / ".git" / "lmr"


def _write_record(
    repo: Path,
    record_id: str,
    head_sha: str | None,
    *,
    publish_state: str = "pending_publish",
    merged_at: datetime | None = None,
) -> Path:
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "id": record_id,
        "branch": f"codex/{record_id}",
        "base": "main",
        "title": f"task {record_id}",
        "tier": "show",
        "state": "merged",
        "publishState": publish_state,
        "createdAt": _iso(now - timedelta(minutes=40)),
        "mergedAt": _iso(merged_at or now),
        "updatedAt": _iso(now),
    }
    if head_sha is not None:
        payload["headSha"] = head_sha
    path = _ledger_dir(repo) / f"{record_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def _read_record(repo: Path, record_id: str) -> dict[str, object]:
    path = _ledger_dir(repo) / f"{record_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _origin_tip(origin: Path) -> str:
    return _git(origin, "rev-parse", "refs/heads/main").stdout.strip()


def _run(
    repo: Path, capsys: pytest.CaptureFixture[str], *args: str
) -> tuple[int, dict[str, object], str]:
    exit_code = lmr_publish.main(["--repo", str(repo), *args])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert isinstance(payload, dict)
    return exit_code, payload, captured.err


def test_below_threshold_does_not_push(
    publish_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = publish_repo
    origin = repo.parent / "origin.git"
    before = _origin_tip(origin)
    sha = _commit_file(repo, "feature.txt", "one\n", "task one")
    _write_record(repo, "lmr-001", sha)

    exit_code, payload, _ = _run(repo, capsys)

    assert exit_code == 0
    assert payload["action"] == "skip"
    assert payload["trigger"] == "below_threshold"
    assert "pushed" not in payload
    assert _origin_tip(origin) == before
    assert _read_record(repo, "lmr-001")["publishState"] == "pending_publish"


def test_now_pushes_and_marks_published(
    publish_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = publish_repo
    origin = repo.parent / "origin.git"
    sha = _commit_file(repo, "src/app.txt", "value\n", "task one")
    _write_record(repo, "lmr-001", sha)

    exit_code, payload, _ = _run(repo, capsys, "--now")

    assert exit_code == 0
    assert payload["action"] == "publish"
    assert payload["pushed"] is True
    assert payload["trigger"] == "manual"
    assert payload["commitCount"] == 1
    assert payload["push"]["attempts"] == 1
    assert payload["publishedRecordIds"] == ["lmr-001"]
    assert _origin_tip(origin) == _git(repo, "rev-parse", "HEAD").stdout.strip()
    record = _read_record(repo, "lmr-001")
    assert record["publishState"] == "published"
    assert isinstance(record.get("publishedAt"), str)


def test_age_threshold_triggers_push(
    publish_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = publish_repo
    origin = repo.parent / "origin.git"
    sha = _commit_file(repo, "aged.txt", "old\n", "aged task")
    _write_record(
        repo, "lmr-aged", sha, merged_at=datetime.now(timezone.utc) - timedelta(minutes=31)
    )

    exit_code, payload, _ = _run(repo, capsys)

    assert exit_code == 0
    assert payload["action"] == "publish"
    assert payload["trigger"] == "oldest_age"
    assert _origin_tip(origin) == sha
    assert _read_record(repo, "lmr-aged")["publishState"] == "published"


def test_batch_threshold_from_env_triggers_push(
    publish_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = publish_repo
    origin = repo.parent / "origin.git"
    shas = [
        _commit_file(repo, f"batch-{index}.txt", f"{index}\n", f"batch {index}")
        for index in range(2)
    ]
    for index, sha in enumerate(shas):
        _write_record(repo, f"lmr-batch-{index}", sha)
    monkeypatch.setenv("LMR_PUBLISH_BATCH_THRESHOLD", "2")

    exit_code, payload, _ = _run(repo, capsys)

    assert exit_code == 0
    assert payload["action"] == "publish"
    assert payload["trigger"] == "batch_count"
    assert sorted(payload["publishedRecordIds"]) == ["lmr-batch-0", "lmr-batch-1"]
    assert _origin_tip(origin) == shas[-1]


def test_secret_hits_block_push(
    publish_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = publish_repo
    origin = repo.parent / "origin.git"
    before = _origin_tip(origin)
    sha = _commit_file(repo, "feature.txt", "code\n", "task with leaks")
    _commit_file(repo, ".env", "TOKEN=1\n", "add env")
    _commit_file(repo, "config/server.key", "key\n", "add key")
    _write_record(repo, "lmr-secret", sha)

    exit_code, payload, err = _run(repo, capsys, "--now")

    assert exit_code == lmr_publish.EXIT_SECRETS_DETECTED
    assert payload["ok"] is False
    assert payload["error"] == "secrets_detected"
    assert ".env" in payload["hits"]
    assert "config/server.key" in payload["hits"]
    assert _origin_tip(origin) == before
    assert _read_record(repo, "lmr-secret")["publishState"] == "pending_publish"
    assert "secrets_detected" in err


def test_secret_patterns_env_extension(
    publish_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = publish_repo
    sha = _commit_file(repo, "auth.token", "token\n", "add token")
    _write_record(repo, "lmr-token", sha)
    monkeypatch.setenv("LMR_PUBLISH_SECRET_PATTERNS", "*.token")

    exit_code, payload, _ = _run(repo, capsys, "--now")
    assert exit_code == lmr_publish.EXIT_SECRETS_DETECTED
    assert "auth.token" in payload["hits"]

    monkeypatch.delenv("LMR_PUBLISH_SECRET_PATTERNS")
    exit_code, payload, _ = _run(repo, capsys, "--now")
    assert exit_code == 0
    assert payload["publishedRecordIds"] == ["lmr-token"]


def test_unreachable_remote_retries_then_fails(
    publish_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = publish_repo
    origin = repo.parent / "origin.git"
    before = _origin_tip(origin)
    sha = _commit_file(repo, "offline.txt", "data\n", "offline task")
    _write_record(repo, "lmr-offline", sha)
    _git(repo, "remote", "set-url", "origin", str((repo.parent / "missing-origin").as_posix()))
    monkeypatch.setenv("LMR_PUBLISH_RETRY_BACKOFF_SECONDS", "0")

    exit_code, payload, err = _run(repo, capsys, "--now")

    assert exit_code == lmr_publish.EXIT_PUSH_FAILED
    assert payload["ok"] is False
    assert payload["error"] == "push_failed"
    assert payload["hint"] == lmr_publish.INTEGRATION_UNAFFECTED_HINT
    assert payload["attempts"] == lmr_publish.DEFAULT_MAX_RETRIES + 1
    assert _origin_tip(origin) == before
    assert _read_record(repo, "lmr-offline")["publishState"] == "pending_publish"
    assert "本地集成不受影响，仅镜像滞后" in err


def test_dry_run_previews_without_pushing(
    publish_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = publish_repo
    origin = repo.parent / "origin.git"
    before = _origin_tip(origin)
    sha = _commit_file(repo, "preview.txt", "preview\n", "preview task")
    _write_record(repo, "lmr-preview", sha)

    exit_code, payload, _ = _run(repo, capsys, "--dry-run")

    assert exit_code == 0
    assert payload["action"] == "dry-run"
    assert payload["wouldPush"] is False
    assert payload["trigger"] == "below_threshold"
    assert payload["wouldPublishRecordIds"] == ["lmr-preview"]
    assert payload["commitCount"] == 1
    assert _origin_tip(origin) == before
    assert _read_record(repo, "lmr-preview")["publishState"] == "pending_publish"

    exit_code, payload, _ = _run(repo, capsys, "--now", "--dry-run")

    assert exit_code == 0
    assert payload["action"] == "dry-run"
    assert payload["wouldPush"] is True
    assert _origin_tip(origin) == before
    assert _read_record(repo, "lmr-preview")["publishState"] == "pending_publish"


def test_core_ledger_timestamp_aliases_drive_threshold(
    publish_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Core ledger writes ``created``/``updated``; aging must honor them.

    Regression: with these aliases missing, a single fresh core-format record
    read as ageless and triggered an immediate publish instead of waiting for
    the batch/age thresholds.
    """

    repo = publish_repo
    origin = repo.parent / "origin.git"
    before = _origin_tip(origin)

    def write_core_record(record_id: str, created: datetime) -> str:
        sha = _commit_file(repo, f"{record_id}.txt", "data\n", record_id)
        payload = {
            "id": record_id,
            "branch": f"codex/{record_id}",
            "state": "merged",
            "publishState": "pending_publish",
            "headSha": sha,
            "created": _iso(created),
            "updated": _iso(created),
        }
        path = _ledger_dir(repo) / f"{record_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return sha

    write_core_record("lmr-core-fresh", datetime.now(timezone.utc))

    exit_code, payload, _ = _run(repo, capsys)

    assert exit_code == 0
    assert payload["action"] == "skip"
    assert payload["trigger"] == "below_threshold"
    assert _origin_tip(origin) == before
    assert _read_record(repo, "lmr-core-fresh")["publishState"] == "pending_publish"

    old_sha = write_core_record(
        "lmr-core-old", datetime.now(timezone.utc) - timedelta(minutes=31)
    )

    exit_code, payload, _ = _run(repo, capsys)

    assert exit_code == 0
    assert payload["action"] == "publish"
    assert payload["trigger"] == "oldest_age"
    assert _origin_tip(origin) == old_sha
    assert _read_record(repo, "lmr-core-fresh")["publishState"] == "published"
    assert _read_record(repo, "lmr-core-old")["publishState"] == "published"


def test_malformed_and_headless_records_are_tolerated(
    publish_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = publish_repo
    sha = _commit_file(repo, "tolerant.txt", "data\n", "tolerant task")
    broken = _ledger_dir(repo) / "broken.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    with open(broken, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("{not json")
    _write_record(repo, "lmr-ok", sha)
    _write_record(repo, "lmr-nosha", None)

    exit_code, payload, _ = _run(repo, capsys, "--now")

    assert exit_code == 0
    assert payload["action"] == "publish"
    assert payload["malformedRecordFiles"] == ["broken.json"]
    assert payload["publishedRecordIds"] == ["lmr-ok"]
    assert _read_record(repo, "lmr-ok")["publishState"] == "published"
    assert _read_record(repo, "lmr-nosha")["publishState"] == "pending_publish"
