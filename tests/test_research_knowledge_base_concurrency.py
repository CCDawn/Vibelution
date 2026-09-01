"""Concurrency guarantees for the research knowledge base read-modify-write."""

from __future__ import annotations

import json
import os
import threading

import pytest

from core.research.knowledge_base import (
    _REPLACE_RETRY_BACKOFF_SECONDS,
    KnowledgeBaseWriteError,
    ResearchKnowledgeBase,
)
from core.research.models import ResearchDiscoverySession, ResearchSource


def _source(worker: int, index: int, session_id: str) -> ResearchSource:
    return ResearchSource(
        source_id=f"source-{worker}-{index}",
        session_id=session_id,
        search_run_id=f"run-{worker}",
        kind="paper",
        title=f"Concurrent Source {worker}-{index}",
        url=f"https://example.test/concurrent/{worker}/{index}",
        snippet=f"Snippet from worker {worker} item {index}",
        reliability="normal",
    )


def _run_parallel_ingests(path, worker_count: int, sources_per_worker: int) -> list[dict]:
    barrier = threading.Barrier(worker_count)
    errors: list[Exception] = []
    results: list[dict] = []

    def _worker(worker: int) -> None:
        base = ResearchKnowledgeBase(path=path)
        session = ResearchDiscoverySession(session_id=f"session-{worker}")
        sources = [_source(worker, index, session.session_id) for index in range(sources_per_worker)]
        try:
            barrier.wait(timeout=10)
            results.append(
                base.ingest_sources(session=session, phase="broad", sources=sources)
            )
        except Exception as error:  # pragma: no cover - surfaced via assertion
            errors.append(error)

    threads = [threading.Thread(target=_worker, args=(worker,)) for worker in range(worker_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, f"ingest threads raised: {errors!r}"
    assert len(results) == worker_count
    return results


def test_concurrent_ingest_sources_retains_all_entries(tmp_path):
    """Parallel ingestion must merge instead of last-writer-wins."""
    path = tmp_path / "knowledge_base.json"
    worker_count = 4
    sources_per_worker = 5

    for _round in range(8):
        path.unlink(missing_ok=True)
        results = _run_parallel_ingests(path, worker_count, sources_per_worker)

        payload = ResearchKnowledgeBase(path=path).payload()
        assert payload["summary"]["entryCount"] == worker_count * sources_per_worker
        assert payload["summary"]["claimCount"] == worker_count * sources_per_worker
        titles = {entry["title"] for entry in payload["entries"]}
        assert len(titles) == worker_count * sources_per_worker
        # Every worker must see its own 5 sources as new adds; combined with
        # the final entryCount above this proves no run was overwritten.
        assert all(result["added"] == sources_per_worker for result in results)
        assert sum(result["added"] for result in results) == worker_count * sources_per_worker
        assert max(result["total"] for result in results) == worker_count * sources_per_worker


def test_payload_and_ingest_can_run_concurrently_without_errors(tmp_path):
    """Mixed reader/writer loops must not raise (Windows os.replace races)."""
    path = tmp_path / "knowledge_base.json"
    base = ResearchKnowledgeBase(path=path)
    session = ResearchDiscoverySession(session_id="session-writer")
    errors: list[Exception] = []
    stop = threading.Event()

    def _writer() -> None:
        try:
            for round_index in range(12):
                sources = [
                    _source(round_index, index, session.session_id) for index in range(2)
                ]
                base.ingest_sources(session=session, phase="broad", sources=sources)
        except Exception as error:  # pragma: no cover - surfaced via assertion
            errors.append(error)
        finally:
            stop.set()

    def _reader() -> None:
        try:
            while not stop.is_set():
                base.payload()
        except Exception as error:  # pragma: no cover - surfaced via assertion
            errors.append(error)

    threads = [threading.Thread(target=_reader) for _ in range(3)]
    threads.append(threading.Thread(target=_writer))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, f"concurrent read/write raised: {errors!r}"

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["entries"]) == 24


def test_os_replace_permission_error_is_retried(tmp_path, monkeypatch):
    """A transient PermissionError on os.replace must be retried, not raised."""
    path = tmp_path / "knowledge_base.json"
    base = ResearchKnowledgeBase(path=path)
    session = ResearchDiscoverySession(session_id="session-retry")
    real_replace = os.replace
    calls: list[tuple[str, str]] = []

    def _flaky_replace(src: str, dst: str) -> None:
        calls.append((src, dst))
        if len(calls) == 1:
            raise PermissionError(13, "The process cannot access the file")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _flaky_replace)

    result = base.ingest_sources(
        session=session,
        phase="broad",
        sources=[_source(0, 0, session.session_id)],
    )

    assert result["added"] == 1
    assert len(calls) == 2
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["entries"]) == 1


def test_os_replace_permission_error_exhaustion_raises_structured_error(tmp_path, monkeypatch):
    """Exhausted retries must surface a structured error, not fail silently."""
    path = tmp_path / "knowledge_base.json"
    base = ResearchKnowledgeBase(path=path)
    session = ResearchDiscoverySession(session_id="session-exhaust")
    monkeypatch.setattr(
        "core.research.knowledge_base._REPLACE_RETRY_BACKOFF_SECONDS",
        (0.0, 0.0, 0.0, 0.0),
    )

    def _always_busy(src: str, dst: str) -> None:
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(os, "replace", _always_busy)

    with pytest.raises(KnowledgeBaseWriteError) as excinfo:
        base.ingest_sources(
            session=session,
            phase="broad",
            sources=[_source(0, 0, session.session_id)],
        )

    assert isinstance(excinfo.value.__cause__, PermissionError)
    assert str(path) in str(excinfo.value)
    # The temp file must be cleaned up even after a failed replace.
    leftovers = [item for item in os.listdir(path.parent) if item != path.name]
    assert leftovers == []
    assert len(_REPLACE_RETRY_BACKOFF_SECONDS) == 4


def test_module_lock_is_shared_between_read_and_write_paths():
    """Reader and writer critical sections must use the same module lock."""
    from core.research import knowledge_base as kb_module
    import inspect

    ingest_source = inspect.getsource(kb_module.ResearchKnowledgeBase.ingest_sources)
    read_source = inspect.getsource(kb_module.ResearchKnowledgeBase._read)
    assert "with _LOCK:" in ingest_source
    assert "with _LOCK:" in read_source
    assert isinstance(kb_module._LOCK, type(__import__("threading").RLock()))
