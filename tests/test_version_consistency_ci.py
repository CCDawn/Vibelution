"""Contract tests for the CI version projection gate and its script."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
CHECK_SCRIPT = PROJECT_ROOT / "scripts" / "check_version_projection_consistency.py"


def workflow_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def job_blocks() -> dict[str, str]:
    lines = workflow_text().splitlines()
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[lines.index("jobs:") + 1 :]:
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
            current = line.strip()[:-1]
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return {name: "\n".join(body) for name, body in blocks.items()}


def test_ci_runs_version_consistency_on_every_push_and_pr() -> None:
    blocks = job_blocks()
    assert "version-consistency" in blocks
    body = blocks["version-consistency"]
    # Fast-layer member: no manual-dispatch gate, runs on push/PR like the
    # other integrity jobs.
    assert "if: github.event_name == 'workflow_dispatch'" not in body
    assert "python scripts/check_version_projection_consistency.py" in body


def test_ci_consistency_script_exists_and_is_dependency_free() -> None:
    text = CHECK_SCRIPT.read_text(encoding="utf-8")
    assert "import json" in text
    # The CI runner installs no project dependencies.
    for forbidden in ("from core", "from scripts", "import core", "import scripts"):
        assert forbidden not in text


def _run_check(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), "--repo", str(repo)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_check_passes_when_projections_agree(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("2.5.2\n", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text(
        json.dumps({"name": "w", "version": "2.5.2"}), encoding="utf-8"
    )
    (tmp_path / "web" / "package-lock.json").write_text(
        json.dumps({"version": "2.5.2", "packages": {"": {"version": "2.5.2"}}}),
        encoding="utf-8",
    )
    assert _run_check(tmp_path).returncode == 0


def test_check_fails_on_mismatch_or_missing_files(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("2.0.0\n", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text(
        json.dumps({"name": "w", "version": "9.9.9"}), encoding="utf-8"
    )
    (tmp_path / "web" / "package-lock.json").write_text(
        json.dumps({"version": "2.0.0", "packages": {"": {"version": "2.0.0"}}}),
        encoding="utf-8",
    )
    mismatch = _run_check(tmp_path)
    assert mismatch.returncode == 1
    assert "projection mismatch" in mismatch.stderr

    (tmp_path / "web" / "package.json").unlink()
    missing = _run_check(tmp_path)
    assert missing.returncode == 1

    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "VERSION").write_text("", encoding="utf-8")
    assert _run_check(empty).returncode == 1
