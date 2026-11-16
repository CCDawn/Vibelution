"""Code freshness poll cache: HEAD drift must not disable the fast path.

During active development the on-disk HEAD moves past the head the running
process recorded.  The verdict cache used to require the two to be equal, so
every poll re-paid the full git-backed resolution (7-19s per request observed
on 2026-11-16).  These tests pin the replacement contract: a readable HEAD is
enough to cache the verdict, with a shorter TTL while the heads disagree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.web.services import code_freshness


def _patch_inputs(
    monkeypatch,
    *,
    observation: tuple[str, tuple] = ("head-new", ()),
    disk_head: str = "head-old",
    backend_calls: list[int] | None = None,
) -> list[int]:
    calls: list[int] = backend_calls if backend_calls is not None else []

    monkeypatch.setattr(
        code_freshness,
        "_observe_freshness_inputs",
        lambda root: observation,
    )
    monkeypatch.setattr(
        code_freshness,
        "_throttled_dirty_summary",
        lambda root, *, head_text, fingerprint_stamp: {},
    )

    def fake_backend(*, project_root, fallback_snapshot, dirty_summary):
        calls.append(1)
        return {
            "available": True,
            "behind": False,
            "behindCount": 0,
            "reason": "",
            "source": "test",
            "running": {"head": "head-new"},
            "disk": {"head": disk_head, "branch": "main", "dirty": False},
        }

    monkeypatch.setattr(code_freshness, "resolve_backend_freshness", fake_backend)
    monkeypatch.setattr(
        code_freshness,
        "resolve_frontend_freshness",
        lambda *, project_root: {
            "available": True,
            "stale": False,
            "reason": "",
            "builtFromCommit": "head-new",
            "frontendTree": "tree",
        },
    )
    return calls


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    code_freshness.reset_freshness_caches_for_tests()
    yield
    code_freshness.reset_freshness_caches_for_tests()


def test_head_drift_still_caches_with_short_ttl(tmp_path: Path, monkeypatch) -> None:
    calls = _patch_inputs(monkeypatch, disk_head="head-old")

    first = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert first["verdict"] == "current"

    key = code_freshness._freshness_cache_key(tmp_path, None)
    entry = code_freshness._freshness_cache[key]
    assert entry["ttl"] == code_freshness.FRESHNESS_HEAD_DRIFT_TTL_SECONDS
    assert code_freshness.FRESHNESS_HEAD_DRIFT_TTL_SECONDS < code_freshness.FRESHNESS_FAST_PATH_TTL_SECONDS

    second = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert second == first
    assert len(calls) == 1, "same observation must replay the cached verdict"


def test_matching_head_keeps_long_ttl(tmp_path: Path, monkeypatch) -> None:
    _patch_inputs(monkeypatch, observation=("head-same", ()), disk_head="head-same")

    code_freshness.resolve_code_freshness(project_root=tmp_path)

    key = code_freshness._freshness_cache_key(tmp_path, None)
    assert code_freshness._freshness_cache[key]["ttl"] == code_freshness.FRESHNESS_FAST_PATH_TTL_SECONDS


def test_observation_change_misses_the_cache(tmp_path: Path, monkeypatch) -> None:
    calls = _patch_inputs(monkeypatch, observation=("head-new", ()), disk_head="head-old")

    code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert len(calls) == 1

    monkeypatch.setattr(
        code_freshness,
        "_observe_freshness_inputs",
        lambda root: ("head-newer", ()),
    )
    code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert len(calls) == 2, "a moved HEAD must not replay the old verdict"


def test_unreadable_head_stays_uncached(tmp_path: Path, monkeypatch) -> None:
    calls = _patch_inputs(monkeypatch, observation=("", ()), disk_head="head-old")

    code_freshness.resolve_code_freshness(project_root=tmp_path)
    key = code_freshness._freshness_cache_key(tmp_path, None)
    assert key not in code_freshness._freshness_cache

    code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert len(calls) == 2


def test_cached_response_is_deep_copied(tmp_path: Path, monkeypatch) -> None:
    _patch_inputs(monkeypatch, disk_head="head-old")

    first = code_freshness.resolve_code_freshness(project_root=tmp_path)
    first["verdict"] = "mutated"
    first["backend"]["available"] = False

    second = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert second["verdict"] == "current"
    assert second["backend"]["available"] is True
