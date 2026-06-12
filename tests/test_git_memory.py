#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest
from core.infrastructure.agent_session import get_session_state, reset_session_state
from core.infrastructure.event_bus import EventNames
from core.infrastructure import git_memory
from core.infrastructure.git_memory import GitMemoryService, WorkingTreeFile, WorkingTreeSnapshot
from tools.git_tools import (
    get_git_status_summary_tool,
    open_evolution_transaction_tool,
    close_evolution_transaction_tool,
)

pytestmark = pytest.mark.slow


class FakeWorkspace:
    def __init__(self, project_root: Path, db_path: Path):
        self.project_root = project_root
        self._db_path = db_path

    @contextmanager
    def get_db_connection(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _run(cmd: str, cwd: Path) -> None:
    import subprocess

    subprocess.run(cmd, cwd=str(cwd), shell=True, check=True, capture_output=True, text=True)


def test_run_git_hides_console_windows_on_windows(monkeypatch, tmp_path):
    import subprocess

    calls = []
    service = GitMemoryService.__new__(GitMemoryService)
    service._project_root = tmp_path

    monkeypatch.setattr(git_memory.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(git_memory.subprocess, "run", fake_run)

    service._run_git(["status", "--porcelain=1"])

    assert calls[0][0] == ["git", "status", "--porcelain=1"]
    assert calls[0][1]["creationflags"] & 0x08000000


def _init_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run("git init", repo)
    _run('git config user.email "tests@example.com"', repo)
    _run('git config user.name "Tests"', repo)
    (repo / "sample.py").write_text(
        "def alpha():\n    return 1\n\n\nclass Beta:\n    def gamma(self):\n        return 2\n",
        encoding="utf-8",
    )
    _run("git add sample.py", repo)
    _run('git commit -m "initial commit"', repo)
    return repo


class TestGitMemoryService:
    def test_scan_working_tree_skips_git_dir_preflight(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def publish(self, name, data=None, source=None):
                return None

            def subscribe(self, name, handler, priority=0):
                return True

        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: FakeBus())

        service = GitMemoryService()
        calls = []

        def fake_run_git(args):
            calls.append(args)
            if args == ["status", "--porcelain=1"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
            if args == ["rev-parse", "HEAD"]:
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="abcdef\n", stderr="")
            raise AssertionError(f"unexpected git command: {args}")

        monkeypatch.setattr(service, "_run_git", fake_run_git)

        snapshot = service.scan_working_tree(store=False)

        assert snapshot.available is True
        assert snapshot.base_rev == "abcdef"
        assert calls == [["status", "--porcelain=1"], ["rev-parse", "HEAD"]]

    def test_refresh_indexes_commits_and_worktree(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        published = []

        class FakeBus:
            def publish(self, name, data=None, source=None):
                published.append((name, data, source))

        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: FakeBus())

        service = GitMemoryService()
        state = service.refresh_git_memory(force=True)

        assert state.available is True
        changes = service.get_recent_project_changes(limit=5)
        assert changes
        assert any(change.path == "sample.py" for change in changes)
        assert any(event[0] == EventNames.GIT_INDEX_UPDATED for event in published)

    def test_worktree_snapshot_retention_prunes_old_worktree_rows(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def publish(self, name, data=None, source=None):
                return None

            def subscribe(self, name, handler, priority=0):
                return True

        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: FakeBus())

        service = GitMemoryService(worktree_snapshot_retention_limit=2)
        with fake_workspace.get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO GitEntityChange(
                    commit_sha, path, entity_ref, entity_type, change_type, is_worktree, created_at
                ) VALUES ('commit-a', 'sample.py', 'alpha', 'function', 'modified', 0, '2026-01-01T00:00:00')
                """
            )

        for index in range(4):
            service._store_worktree_snapshot(
                WorkingTreeSnapshot(
                    snapshot_id=f"wt-test-{index}",
                    created_at=f"2026-01-01T00:00:0{index}",
                    base_rev="abcdef",
                    has_staged=False,
                    has_unstaged=True,
                    has_untracked=False,
                    files=[
                        WorkingTreeFile(
                            path="sample.py",
                            status=" M",
                            unstaged=True,
                        )
                    ],
                )
            )

        with fake_workspace.get_db_connection() as conn:
            cursor = conn.cursor()
            snapshot_ids = [
                row["snapshot_id"]
                for row in cursor.execute(
                    "SELECT snapshot_id FROM GitWorkingTreeSnapshot ORDER BY created_at"
                ).fetchall()
            ]
            worktree_file_rows = cursor.execute(
                "SELECT COUNT(*) AS count FROM GitFileChange WHERE is_worktree = 1"
            ).fetchone()["count"]
            worktree_entity_rows = cursor.execute(
                "SELECT COUNT(*) AS count FROM GitEntityChange WHERE is_worktree = 1"
            ).fetchone()["count"]
            commit_entity_rows = cursor.execute(
                "SELECT COUNT(*) AS count FROM GitEntityChange WHERE is_worktree = 0"
            ).fetchone()["count"]

        assert snapshot_ids == ["wt-test-2", "wt-test-3"]
        assert worktree_file_rows == 2
        assert worktree_entity_rows == 6
        assert commit_entity_rows == 1

    def test_prune_worktree_snapshots_can_vacuum_after_deleting_rows(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def publish(self, name, data=None, source=None):
                return None

            def subscribe(self, name, handler, priority=0):
                return True

        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: FakeBus())

        service = GitMemoryService(worktree_snapshot_retention_limit=10)
        for index in range(3):
            service._store_worktree_snapshot(
                WorkingTreeSnapshot(
                    snapshot_id=f"wt-vacuum-{index}",
                    created_at=f"2026-01-01T00:00:0{index}",
                    base_rev="abcdef",
                    has_staged=False,
                    has_unstaged=True,
                    has_untracked=False,
                    files=[
                        WorkingTreeFile(
                            path="sample.py",
                            status=" M",
                            unstaged=True,
                        )
                    ],
                )
            )

        stats = service.prune_worktree_snapshots(keep_latest=1, vacuum=True)

        with fake_workspace.get_db_connection() as conn:
            snapshot_count = conn.execute(
                "SELECT COUNT(*) AS count FROM GitWorkingTreeSnapshot"
            ).fetchone()["count"]

        assert stats["snapshots_deleted"] == 2
        assert stats["file_rows_deleted"] == 2
        assert stats["entity_rows_deleted"] == 6
        assert stats["vacuumed"] is True
        assert snapshot_count == 1

    def test_note_file_modified_tracks_entities(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def publish(self, name, data=None, source=None):
                return None

        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: FakeBus())

        service = GitMemoryService()
        service.note_file_modified("sample.py")
        attention = get_session_state().get_attention_snapshot()

        assert "sample.py" in attention["modified_paths"]
        assert "alpha" in attention["modified_entities"]
        assert "Beta.gamma" in attention["modified_entities"]

    def test_open_and_close_evolution_transaction_tools(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def publish(self, name, data=None, source=None):
                return None

        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: FakeBus())

        service = GitMemoryService()
        monkeypatch.setattr("tools.git_tools.get_git_memory_service", lambda: service)
        session = reset_session_state()

        opened = open_evolution_transaction_tool("touch core loop")
        assert "txn_id" in opened
        import json
        txn_id = json.loads(opened)["txn_id"]
        assert session.get_active_evolution_txn() == txn_id

        closed = close_evolution_transaction_tool(txn_id=txn_id, status="failed", summary="test failed")
        payload = json.loads(closed)
        assert payload["transaction_status"] == "failed"
        assert session.get_active_evolution_txn() is None

    def test_close_evolution_transaction_recreates_missing_table_and_reports_missing_txn(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def publish(self, name, data=None, source=None):
                return None

        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: FakeBus())

        service = GitMemoryService()
        txn_id = service.open_evolution_transaction("schema loss probe")
        with fake_workspace.get_db_connection() as conn:
            conn.execute("DROP TABLE EvolutionTransaction")

        try:
            service.close_evolution_transaction(txn_id=txn_id, status="success", summary="should diagnose")
        except ValueError as exc:
            assert txn_id in str(exc)
            assert "not found" in str(exc)
        else:
            raise AssertionError("missing transaction close should be diagnosed")

        with fake_workspace.get_db_connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'EvolutionTransaction'"
            ).fetchone()

        assert row is not None

    def test_validation_event_does_not_auto_close_active_evolution_transaction(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def __init__(self):
                self.handlers = {}

            def publish(self, name, data=None, source=None):
                for handler in self.handlers.get(name, []):
                    handler(type("Evt", (), {"data": data or {}, "source": source})())

            def subscribe(self, name, handler, priority=0):
                self.handlers.setdefault(name, []).append(handler)
                return True

        fake_bus = FakeBus()
        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: fake_bus)

        service = GitMemoryService()
        session = reset_session_state()
        txn_id = service.open_evolution_transaction("explicit close required")
        session.set_active_evolution_txn(txn_id)

        fake_bus.publish(
            EventNames.VALIDATION_COMPLETED,
            {"kind": "lint", "passed": True, "message": "ruff lint passed"},
            source="test",
        )

        assert session.get_active_evolution_txn() == txn_id
        with fake_workspace.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, closed_at FROM EvolutionTransaction WHERE txn_id = ?", (txn_id,))
            row = cursor.fetchone()

        assert row is not None
        assert row["status"] == "open"
        assert row["closed_at"] is None

    def test_validation_event_syncs_attention_cache(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def __init__(self):
                self.handlers = {}

            def publish(self, name, data=None, source=None):
                for handler in self.handlers.get(name, []):
                    handler(type("Evt", (), {"data": data or {}, "source": source})())

            def subscribe(self, name, handler, priority=0):
                self.handlers.setdefault(name, []).append(handler)
                return True

        fake_bus = FakeBus()
        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: fake_bus)

        service = GitMemoryService()
        session = get_session_state()
        session.record_validation_result("Environment smoke passed", True)

        fake_bus.publish(
            EventNames.VALIDATION_COMPLETED,
            {"kind": "environment", "passed": True, "message": "Environment smoke passed"},
            source="test",
        )

        with fake_workspace.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT last_validation_summary FROM GitAttentionCache WHERE session_id = ?", ("default",))
            row = cursor.fetchone()

        assert row is not None
        assert row["last_validation_summary"] == "Environment smoke passed"

    def test_get_git_status_summary_tool_accepts_string_limit(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def publish(self, name, data=None, source=None):
                return None

            def subscribe(self, name, handler, priority=0):
                return True

        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: FakeBus())

        service = GitMemoryService()
        service.refresh_git_memory(force=True)
        monkeypatch.setattr("tools.git_tools.get_git_memory_service", lambda: service)

        import json

        payload = json.loads(get_git_status_summary_tool(limit="5"))
        assert payload["dirty_summary"] == "工作区干净"
        assert isinstance(payload["recent_changes"], list)
        assert len(payload["recent_changes"]) <= 5
        assert payload["recent_changes"][0]["path"] == "sample.py"

    def test_clean_refresh_clears_stale_attention_but_keeps_validation(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def publish(self, name, data=None, source=None):
                return None

            def subscribe(self, name, handler, priority=0):
                return True

        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: FakeBus())

        service = GitMemoryService()
        session = get_session_state()
        session.record_modified_path("sample.py")
        session.record_modified_entities("sample.py", ["alpha"])
        session.record_validation_result("All tests passed", True)

        state = service.refresh_git_memory(force=True)
        attention = session.get_attention_snapshot()

        assert state.dirty is False
        assert attention["modified_paths"] == []
        assert attention["modified_entities"] == []
        assert attention["last_validation_summary"] == "All tests passed"

    def test_note_file_modified_tracks_risky_path_without_opening_txn(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def __init__(self):
                self.handlers = {}

            def publish(self, name, data=None, source=None):
                for handler in self.handlers.get(name, []):
                    handler(type("Evt", (), {"data": data or {}, "source": source})())

            def subscribe(self, name, handler, priority=0):
                self.handlers.setdefault(name, []).append(handler)
                return True

        fake_bus = FakeBus()
        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: fake_bus)

        service = GitMemoryService()
        session = get_session_state()

        service.note_file_modified("core/example.py")

        assert session.get_active_evolution_txn() is None

        fake_bus.publish(
            EventNames.VALIDATION_COMPLETED,
            {"kind": "tests", "passed": True, "message": "All tests passed"},
            source="test",
        )

        assert session.get_active_evolution_txn() is None

        with fake_workspace.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS count FROM EvolutionTransaction")
            row = cursor.fetchone()

        assert row is not None
        assert row["count"] == 0
