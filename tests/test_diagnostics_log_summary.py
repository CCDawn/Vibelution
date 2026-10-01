"""Health log-root summary: dedup walk, per-root parity, and TTL cache."""

import os

import pytest

from core.web.services import log_service


@pytest.fixture(autouse=True)
def _fresh_summary_cache():
    log_service._invalidate_log_root_summary_cache()
    yield
    log_service._invalidate_log_root_summary_cache()


def _counting_walk(monkeypatch):
    """Wrap _walk_summary_entries with a call counter and root recorder."""
    calls = {"count": 0, "roots": []}
    original_walk = log_service._walk_summary_entries

    def counting_walk(root_path, skip=None):
        calls["count"] += 1
        calls["roots"].append(str(root_path))
        return original_walk(root_path, skip=skip)

    monkeypatch.setattr(log_service, "_walk_summary_entries", counting_walk)
    return calls


def _seed_log_tree(tmp_path):
    logs = tmp_path / "logs"
    scenes = logs / "runtime_scenes"
    (scenes / "scene-a" / "raw").mkdir(parents=True)
    (scenes / "scene-b").mkdir()
    (scenes / "scene-a" / "raw" / "backend.log").write_text("aaaa", encoding="utf-8")
    (scenes / "scene-b" / "scene.log").write_text("bb", encoding="utf-8")
    (logs / "conversations").mkdir()
    (logs / "conversations" / "conversation_debug.jsonl").write_text('{"a":1}', encoding="utf-8")
    (logs / "agent_realtime.log").write_text("runtime", encoding="utf-8")
    (logs / "nested").mkdir()
    (logs / "nested" / "deep.log").write_text("deep!!", encoding="utf-8")
    (tmp_path / ".runtime" / "launcher").mkdir(parents=True)
    (tmp_path / ".runtime" / "launcher" / "backend.stdout.log").write_text("launcher", encoding="utf-8")
    (tmp_path / "workspace" / "logs").mkdir(parents=True)
    (tmp_path / "workspace" / "logs" / "turn.md").write_text("# t", encoding="utf-8")

    # Distinct mtimes keep the latestPath tie-breaking deterministic.
    stamps = {
        scenes / "scene-a" / "raw" / "backend.log": 1_700_000_100,
        scenes / "scene-b" / "scene.log": 1_700_000_200,
        logs / "conversations" / "conversation_debug.jsonl": 1_700_000_300,
        logs / "agent_realtime.log": 1_700_000_400,
        logs / "nested" / "deep.log": 1_700_000_500,
        tmp_path / ".runtime" / "launcher" / "backend.stdout.log": 1_700_000_600,
        tmp_path / "workspace" / "logs" / "turn.md": 1_700_000_700,
    }
    for path, stamp in stamps.items():
        os.utime(path, (stamp, stamp))


def test_collected_summaries_match_per_root_walk(tmp_path, monkeypatch):
    _seed_log_tree(tmp_path)
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    collected = log_service._collect_log_root_summaries()

    for root in log_service.LOG_ROOTS:
        root_id = root["id"]
        expected = log_service._summarize_log_root(root_id, log_service._resolve_log_root(root_id))
        assert collected[root_id] == expected, root_id

    # Hand-computed numbers for the seeded tree, proving each root is a
    # self-contained statistic of its own tree.
    assert collected["runtime_logs"] == {
        "health": "active",
        "fileCount": 2,
        "directoryCount": 1,
        "sizeBytes": 13,
        "lastModifiedAt": "2023-11-14T22:21:40Z",
        "latestPath": "nested/deep.log",
        "userGuide": log_service.ROOT_GUIDES["runtime_logs"]["userGuide"],
        "agentGuide": log_service.ROOT_GUIDES["runtime_logs"]["agentGuide"],
    }
    assert collected["runtime_scenes"]["fileCount"] == 2
    assert collected["runtime_scenes"]["directoryCount"] == 3
    assert collected["runtime_scenes"]["sizeBytes"] == 6
    assert collected["runtime_scenes"]["latestPath"] == "scene-b/scene.log"
    assert collected["conversation_logs"]["fileCount"] == 1
    assert collected["conversation_logs"]["latestPath"] == "conversation_debug.jsonl"
    assert collected["launcher_runtime"]["fileCount"] == 1
    assert collected["workspace_logs"]["fileCount"] == 1


def test_overlapping_roots_share_single_logs_walk(tmp_path, monkeypatch):
    _seed_log_tree(tmp_path)
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)
    calls = _counting_walk(monkeypatch)

    roots = log_service.list_log_roots()

    # One walk for the logs root covers runtime_scenes, runtime_logs, and
    # conversation_logs; launcher and workspace get one walk each.
    assert calls["count"] == 3
    assert calls["roots"].count(str(tmp_path / "logs")) == 1
    assert str(tmp_path / "logs" / "runtime_scenes") not in calls["roots"]
    assert str(tmp_path / "logs" / "conversations") not in calls["roots"]

    summary_by_id = {root["id"]: root["summary"] for root in roots}
    assert summary_by_id["runtime_logs"]["fileCount"] == 2
    assert summary_by_id["runtime_scenes"]["fileCount"] == 2
    assert summary_by_id["conversation_logs"]["fileCount"] == 1


def test_summary_cache_skips_rescan_within_ttl(tmp_path, monkeypatch):
    _seed_log_tree(tmp_path)
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)
    calls = _counting_walk(monkeypatch)

    first = log_service.list_log_roots()
    second = log_service.list_log_roots()

    assert calls["count"] == 3  # only the cold compute; the warm call rescans nothing
    assert first == second


def test_summary_cache_expires_after_ttl(tmp_path, monkeypatch):
    _seed_log_tree(tmp_path)
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(log_service, "ROOT_SUMMARY_CACHE_TTL_SECONDS", 0.0)
    calls = _counting_walk(monkeypatch)

    log_service.list_log_roots()
    log_service.list_log_roots()

    assert calls["count"] == 6  # expired TTL forces a full recompute per call


def test_cache_is_keyed_by_project_root(tmp_path, monkeypatch):
    tree_a = tmp_path / "a"
    tree_b = tmp_path / "b"
    (tree_a / "logs").mkdir(parents=True)
    (tree_a / "logs" / "one.log").write_text("1", encoding="utf-8")
    (tree_b / "logs").mkdir(parents=True)
    (tree_b / "logs" / "one.log").write_text("1", encoding="utf-8")
    (tree_b / "logs" / "two.log").write_text("2", encoding="utf-8")

    monkeypatch.setattr(log_service, "PROJECT_ROOT", tree_a)
    summary_a = {root["id"]: root["summary"] for root in log_service.list_log_roots()}
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tree_b)
    summary_b = {root["id"]: root["summary"] for root in log_service.list_log_roots()}

    assert summary_a["runtime_logs"]["fileCount"] == 1
    assert summary_b["runtime_logs"]["fileCount"] == 2


def test_delete_invalidates_summary_cache(tmp_path, monkeypatch):
    _seed_log_tree(tmp_path)
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    before = {root["id"]: root["summary"] for root in log_service.list_log_roots()}
    assert before["runtime_logs"]["fileCount"] == 2
    assert before["runtime_logs"]["latestPath"] == "nested/deep.log"

    log_service.delete_log_files("runtime_logs", ["nested/deep.log"])

    after = {root["id"]: root["summary"] for root in log_service.list_log_roots()}
    assert after["runtime_logs"]["fileCount"] == 1
    assert after["runtime_logs"]["latestPath"] == "agent_realtime.log"


def test_missing_and_empty_root_summaries(tmp_path, monkeypatch):
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    roots = {root["id"]: root for root in log_service.list_log_roots()}
    assert roots["runtime_logs"]["exists"] is False
    assert roots["runtime_logs"]["summary"]["health"] == "missing"
    assert roots["runtime_scenes"]["exists"] is False
    assert roots["runtime_scenes"]["summary"]["health"] == "missing"
    assert roots["conversation_logs"]["exists"] is False
    assert roots["conversation_logs"]["summary"]["health"] == "missing"
    assert roots["launcher_runtime"]["exists"] is False
    assert roots["workspace_logs"]["exists"] is False

    (tmp_path / ".runtime" / "launcher").mkdir(parents=True)
    log_service._invalidate_log_root_summary_cache()
    launcher = next(
        root for root in log_service.list_log_roots() if root["id"] == "launcher_runtime"
    )
    assert launcher["exists"] is True
    assert launcher["summary"]["health"] == "empty"
    assert launcher["summary"]["fileCount"] == 0
    assert launcher["summary"]["directoryCount"] == 0
