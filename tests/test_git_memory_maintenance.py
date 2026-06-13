from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from core.infrastructure.git_memory_maintenance import (
    build_git_memory_maintenance_report,
    build_python_git_memory_maintenance_report,
)


def _create_git_memory_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE GitWorkingTreeSnapshot(
                snapshot_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                base_rev TEXT,
                has_staged INTEGER NOT NULL DEFAULT 0,
                has_unstaged INTEGER NOT NULL DEFAULT 0,
                has_untracked INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE GitFileChange(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                commit_sha TEXT NOT NULL,
                path TEXT NOT NULL,
                change_type TEXT NOT NULL,
                old_path TEXT,
                is_worktree INTEGER NOT NULL DEFAULT 0,
                summary TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE GitEntityChange(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                commit_sha TEXT NOT NULL,
                path TEXT NOT NULL,
                entity_ref TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                change_type TEXT NOT NULL,
                is_worktree INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO GitEntityChange(
                commit_sha, path, entity_ref, entity_type, change_type, is_worktree, created_at
            ) VALUES ('commit-a', 'sample.py', 'alpha', 'function', 'modified', 0, '2026-01-01T00:00:00')
            """
        )
        for index in range(4):
            snapshot_id = f"wt-test-{index}"
            conn.execute(
                "INSERT INTO GitWorkingTreeSnapshot(snapshot_id, created_at) VALUES (?, ?)",
                (snapshot_id, f"2026-01-01T00:00:0{index}"),
            )
            conn.execute(
                """
                INSERT INTO GitFileChange(commit_sha, path, change_type, is_worktree, created_at)
                VALUES (?, 'sample.py', 'modified', 1, '2026-01-01T00:00:00')
                """,
                (snapshot_id,),
            )
            for entity_index in range(3):
                conn.execute(
                    """
                    INSERT INTO GitEntityChange(
                        commit_sha, path, entity_ref, entity_type, change_type, is_worktree, created_at
                    ) VALUES (?, 'sample.py', ?, 'function', 'modified', 1, '2026-01-01T00:00:00')
                    """,
                    (snapshot_id, f"entity_{entity_index}"),
                )


def _cargo_target_args() -> list[str]:
    forced_target = os.environ.get("VIBELUTION_RUST_TARGET", "").strip()
    if forced_target:
        return ["--target", forced_target]
    if sys.platform != "win32" or shutil.which("link"):
        return []
    if not shutil.which("gcc"):
        pytest.skip("MSVC link.exe is missing and no gcc linker is available")
    installed = subprocess.run(
        ["rustup", "target", "list", "--installed"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if "x86_64-pc-windows-gnu" not in installed.stdout:
        pytest.skip("MSVC link.exe is missing and x86_64-pc-windows-gnu is not installed")
    return ["--target", "x86_64-pc-windows-gnu"]


def _cargo_command() -> list[str]:
    forced_toolchain = os.environ.get("VIBELUTION_RUST_TOOLCHAIN", "").strip()
    if forced_toolchain:
        return ["cargo", f"+{forced_toolchain}"]
    if sys.platform != "win32" or shutil.which("link"):
        return ["cargo"]
    toolchains = subprocess.run(
        ["rustup", "toolchain", "list"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if "stable-x86_64-pc-windows-gnu" in toolchains.stdout:
        return ["cargo", "+stable-x86_64-pc-windows-gnu"]
    return ["cargo"]


def _cargo_env() -> dict[str, str]:
    env = os.environ.copy()
    if sys.platform == "win32" and not shutil.which("link"):
        env.setdefault("CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER", "rust-lld")
    return env


def test_python_git_memory_maintenance_report_is_read_only_prune_dry_run(tmp_path):
    db_path = tmp_path / "agent_brain.db"
    _create_git_memory_db(db_path)

    report = build_python_git_memory_maintenance_report(db_path, keep_latest=2)

    assert report["ok"] is True
    assert report["integrityCheckMode"] == "skipped"
    assert report["integrityCheck"] == "skipped"
    assert report["tables"]["gitWorkingTreeSnapshot"]["rowCount"] == 4
    assert report["tables"]["gitEntityChange"]["rowCount"] == 13
    assert report["tables"]["gitEntityChange"]["worktreeRows"] == 12
    assert report["pruneDryRun"] == {
        "candidateSnapshots": 2,
        "candidateFileRows": 2,
        "candidateEntityRows": 6,
        "sampleSnapshotIds": ["wt-test-1", "wt-test-0"],
    }
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM GitWorkingTreeSnapshot").fetchone()[0] == 4


def test_git_memory_maintenance_report_falls_back_when_rust_binary_missing(tmp_path):
    db_path = tmp_path / "agent_brain.db"
    _create_git_memory_db(db_path)

    report = build_git_memory_maintenance_report(
        db_path,
        keep_latest=2,
        executable=tmp_path / "missing" / "vibelution-maintenance.exe",
    )

    assert report["ok"] is True
    assert report["accelerator"]["available"] is False
    assert report["accelerator"]["reason"] == "rust_binary_missing"
    assert report["pruneDryRun"]["candidateEntityRows"] == 6


@pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo is not installed")
def test_rust_git_memory_cli_matches_python_dry_run_report(tmp_path):
    db_path = tmp_path / "agent_brain.db"
    _create_git_memory_db(db_path)
    repo_root = Path(__file__).resolve().parents[1]
    manifest_path = repo_root / "crates" / "vibelution-maintenance" / "Cargo.toml"

    completed = subprocess.run(
        [
            *_cargo_command(),
            "run",
            "--quiet",
            "--manifest-path",
            str(manifest_path),
            *_cargo_target_args(),
            "--",
            "git-memory",
            "--db",
            str(db_path),
            "--keep-latest",
            "2",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
        env=_cargo_env(),
    )
    rust_report = json.loads(completed.stdout)
    python_report = build_python_git_memory_maintenance_report(db_path, keep_latest=2)

    assert rust_report["ok"] is True
    assert rust_report["keepLatest"] == python_report["keepLatest"]
    assert rust_report["integrityCheckMode"] == python_report["integrityCheckMode"]
    assert rust_report["integrityCheck"] == python_report["integrityCheck"]
    assert rust_report["tables"] == python_report["tables"]
    assert rust_report["pruneDryRun"] == python_report["pruneDryRun"]
