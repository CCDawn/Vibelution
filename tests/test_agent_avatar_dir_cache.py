"""Avatar directory cache: single scan, mtime-gated refresh, thread safety."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from core.web.services import agent_directory_service
from core.web.services.agent_directory import mutations as agent_directory_mutations
from tests.test_agent_config_workspace_service import (
    _seed_agent_avatars,
    _use_tmp_project_root,
)


@pytest.fixture(autouse=True)
def _fresh_avatar_dir_cache():
    agent_directory_mutations._invalidate_agent_avatar_dir_cache()
    yield
    agent_directory_mutations._invalidate_agent_avatar_dir_cache()


class _IoCounter:
    """Counts Path.stat / Path.iterdir calls restricted to the given roots."""

    def __init__(self, roots: list[Path], monkeypatch: pytest.MonkeyPatch) -> None:
        self.roots = [str(root) for root in roots]
        self.stat_calls = 0
        self.iterdir_calls = 0
        real_stat = Path.stat
        real_iterdir = Path.iterdir

        def tracked_stat(path_self: Path, *args, **kwargs):
            if str(path_self) in self.roots:
                self.stat_calls += 1
            return real_stat(path_self, *args, **kwargs)

        def tracked_iterdir(path_self: Path, *args, **kwargs):
            if str(path_self) in self.roots:
                self.iterdir_calls += 1
            return real_iterdir(path_self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", tracked_stat)
        monkeypatch.setattr(Path, "iterdir", tracked_iterdir)


def _custom_dir(tmp_path: Path) -> Path:
    return tmp_path / "config" / "avatars" / "agents"


def _bundled_dir(tmp_path: Path) -> Path:
    return tmp_path / "assets" / "agent-avatars"


def _legacy_dir(tmp_path: Path) -> Path:
    return tmp_path / "workspace" / "avatars"


def _available() -> list[str]:
    return agent_directory_mutations._available_agent_avatar_filenames()


def _expected(filenames: set[str]) -> list[str]:
    ordered = [
        filename
        for filename in agent_directory_service.AGENT_AVATAR_FILENAMES
        if filename in filenames
    ]
    return ordered + sorted(filenames.difference(ordered))


def test_repeated_calls_scan_each_directory_once(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_agent_avatars(tmp_path)
    custom_dir = _custom_dir(tmp_path)
    custom_dir.mkdir(parents=True)
    (custom_dir / "zz-custom-upload.png").write_bytes(b"\x89PNG\r\n\x1a\navatar")
    counter = _IoCounter(
        [custom_dir, _bundled_dir(tmp_path), _legacy_dir(tmp_path)], monkeypatch
    )

    first = _available()
    first_iterdir = counter.iterdir_calls
    first_stat = counter.stat_calls
    second = _available()
    warm_iterdir = counter.iterdir_calls - first_iterdir
    warm_stat = counter.stat_calls - first_stat

    seeded = set(agent_directory_service.AGENT_AVATAR_FILENAMES)
    assert first == second == _expected(seeded | {"zz-custom-upload.png"})
    # Cold pass walks each existing directory exactly once; the warm pass never
    # walks: one stat probe per storage directory plus the pre-existing
    # Path.resolve() stat on the legacy dir (unchanged by this cache).
    assert first_iterdir == 2
    assert warm_iterdir == 0
    assert warm_stat <= 4


def test_cache_refreshes_when_directory_mtime_changes(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_agent_avatars(tmp_path)
    assert "zz-new-upload.png" not in _available()
    bundled_dir = _bundled_dir(tmp_path)
    (bundled_dir / "zz-new-upload.png").write_bytes(b"\x89PNG\r\n\x1a\navatar")
    # Deterministic mtime flip: file creation may land in the same timestamp
    # tick as the cached probe, so move the directory mtime explicitly.
    marker = int(os.stat(bundled_dir).st_mtime_ns) + 1_000_000
    os.utime(bundled_dir, ns=(marker, marker))
    counter = _IoCounter([bundled_dir], monkeypatch)

    refreshed = _available()

    assert "zz-new-upload.png" in refreshed
    assert counter.iterdir_calls == 1  # only the changed bundled dir is rescanned


def test_explicit_invalidation_forces_full_rescan(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_agent_avatars(tmp_path)
    assert _available()
    counter = _IoCounter([_bundled_dir(tmp_path)], monkeypatch)

    agent_directory_mutations._invalidate_agent_avatar_dir_cache()
    rescan = _available()

    assert rescan == _expected(set(agent_directory_service.AGENT_AVATAR_FILENAMES))
    assert counter.iterdir_calls == 1


def test_model_filenames_stay_excluded_from_custom_directory(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    model_filename = "model-openai.svg"
    custom_dir = _custom_dir(tmp_path)
    custom_dir.mkdir(parents=True)
    (custom_dir / model_filename).write_text("<svg><path /></svg>", encoding="utf-8")

    assert model_filename not in _available()  # custom copies of model marks are ignored

    bundled_dir = _bundled_dir(tmp_path)
    bundled_dir.mkdir(parents=True)
    (bundled_dir / model_filename).write_text("<svg><path /></svg>", encoding="utf-8")

    assert model_filename in _available()  # only the bundled asset may carry the mark
    agent_directory_mutations._invalidate_agent_avatar_dir_cache()
    (custom_dir / "zz-custom-upload.png").write_bytes(b"\x89PNG\r\n\x1a\navatar")
    assert model_filename in _available()  # still bundled-only after a rescan
    assert "zz-custom-upload.png" in _available()


def test_concurrent_calls_are_safe_and_consistent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_agent_avatars(tmp_path)
    expected = _expected(set(agent_directory_service.AGENT_AVATAR_FILENAMES))
    threads = 16
    barrier = threading.Barrier(threads)
    results: list[list[str]] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            barrier.wait()
            local = _available()
            with lock:
                results.append(local)
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    workers = [threading.Thread(target=worker) for _ in range(threads)]
    for item in workers:
        item.start()
    for item in workers:
        item.join(timeout=30)

    assert errors == []
    assert results
    assert all(item == expected for item in results)
