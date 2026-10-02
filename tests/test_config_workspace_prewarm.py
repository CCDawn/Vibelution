"""Cold-start prewarm workers: config workspace cache and freshness cache.

Pins the two cold-start prewarm wirings added to the web lifespan:

- ``_prewarm_config_workspace_on_startup``: waits for the session directory
  startup, builds the config workspace payload once (single-flight shared
  with early requests), records a lifecycle runtime-scene event, and skips
  under pytest like the directory runtime itself.
- ``_prewarm_git_memory_on_startup``: additionally fills the code-freshness
  verdict cache (45s fast-path TTL) so the frontend's first delayed poll is
  a cache hit; a freshness failure is best effort and never fails the git
  prewarm result.
"""

from __future__ import annotations

import pytest

from core.web import lifecycle
from core.web.services import code_freshness
from core.web.services import config_service
from core.web.services.session import directory_runtime

pytestmark = pytest.mark.serial


@pytest.fixture(autouse=True)
def _reset_freshness_caches():
    code_freshness.reset_freshness_caches_for_tests()
    yield
    code_freshness.reset_freshness_caches_for_tests()


def test_prewarm_config_workspace_waits_builds_and_records(monkeypatch):
    sequence: list[str] = []
    monkeypatch.setattr(
        directory_runtime,
        "should_skip_directory_runtime_for_pytest",
        lambda: False,
    )

    def fake_wait(*, timeout=None):
        sequence.append("wait")
        return "idle"

    monkeypatch.setattr(directory_runtime, "wait_for_directory_startup", fake_wait)
    monkeypatch.setattr(
        config_service,
        "prewarm_config_workspace",
        lambda: sequence.append("build"),
    )
    events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    result = lifecycle._prewarm_config_workspace_on_startup()

    # 目录启动等待必须先于构建（serving root 对齐后才扫别名引用）。
    assert sequence == ["wait", "build"]
    assert result["totalMs"] >= 0
    assert len(events) == 1
    args, kwargs = events[0]
    assert args[:3] == ("config", "startup_prewarm", "config.workspace_prewarmed")
    assert kwargs["outcome"] == "completed"
    assert kwargs["fields"] == {"totalMs": result["totalMs"]}
    assert kwargs["lifecycle"] is True


def test_prewarm_config_workspace_skips_under_pytest(monkeypatch):
    monkeypatch.setattr(
        directory_runtime,
        "should_skip_directory_runtime_for_pytest",
        lambda: True,
    )
    touched: list[str] = []
    monkeypatch.setattr(
        directory_runtime,
        "wait_for_directory_startup",
        lambda *a, **kw: touched.append("wait"),
    )
    monkeypatch.setattr(
        config_service,
        "prewarm_config_workspace",
        lambda: touched.append("build"),
    )

    result = lifecycle._prewarm_config_workspace_on_startup()

    assert result == {"skipped": "pytest"}
    assert touched == []


def test_git_memory_prewarm_fills_freshness_cache(monkeypatch, tmp_path):
    # Minimal fake repo so the zero-process HEAD observation is non-empty:
    # the verdict cache only stores when the file-read HEAD agrees with the
    # resolved disk HEAD (the module's trust rule for the fast path).
    head_sha = "abc123def456abc123def456abc123def456abcd"
    refs_dir = tmp_path / ".git" / "refs" / "heads"
    refs_dir.mkdir(parents=True)
    (refs_dir / "main").write_text(head_sha + "\n", encoding="utf-8")
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    monkeypatch.setattr(
        "core.infrastructure.git_memory.refresh_git_memory",
        lambda force=False, **kwargs: {"ok": True},
    )
    # The worker resolves PROJECT_ROOT from the runtime routes module at call
    # time; rebind it to the tmp root so the real (patched-collaborator)
    # freshness resolution runs hermetically.
    monkeypatch.setattr("core.web.routes.runtime.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        code_freshness,
        "_throttled_dirty_summary",
        lambda project_root, *, head_text, fingerprint_stamp: {"available": False},
    )
    backend_calls: list[int] = []

    def fake_backend(*, project_root, fallback_snapshot=None, dirty_summary=None):
        backend_calls.append(1)
        return {"available": True, "behind": False, "disk": {"head": head_sha}}

    monkeypatch.setattr(code_freshness, "resolve_backend_freshness", fake_backend)
    monkeypatch.setattr(
        code_freshness,
        "resolve_frontend_freshness",
        lambda *, project_root: {"available": False, "stale": False},
    )

    state, duration_ms = lifecycle._prewarm_git_memory_on_startup()

    assert state == {"ok": True}
    assert duration_ms >= 0
    # Prewarm paid the full git-backed resolution exactly once and the verdict
    # landed in the fast-path cache.
    assert backend_calls == [1]
    first = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert first["verdict"] == "unknown"
    # Same root, unchanged HEAD/fingerprint observation, TTL not elapsed: the
    # user's first poll replays the cached verdict without resolving again.
    second = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert backend_calls == [1]
    assert second == first


def test_git_memory_prewarm_survives_freshness_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "core.infrastructure.git_memory.refresh_git_memory",
        lambda force=False, **kwargs: {"ok": True},
    )
    monkeypatch.setattr("core.web.routes.runtime.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        code_freshness,
        "resolve_code_freshness",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("injected")),
    )

    state, duration_ms = lifecycle._prewarm_git_memory_on_startup()

    # Freshness 预热是 best effort：失败不影响 git 预热结果与返回签名。
    assert state == {"ok": True}
    assert duration_ms >= 0
