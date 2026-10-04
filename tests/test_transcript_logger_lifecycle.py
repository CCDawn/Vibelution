import builtins
import threading
import time
from pathlib import Path

from core.logging import transcript_logger as transcript_logger_module
from core.logging.transcript_logger import TranscriptLogger
from core.logging.unified_logger import UnifiedLogger


def _new_logger(tmp_path: Path, *, max_pending_writes=512, max_pending_bytes=8 * 1024 * 1024):
    previous = TranscriptLogger._instance
    if previous is not None:
        previous.shutdown(timeout=1.0)
    TranscriptLogger._instance = None
    transcript_logger_module._transcript_logger = None

    logger = TranscriptLogger(
        max_pending_writes=max_pending_writes,
        max_pending_bytes=max_pending_bytes,
    )
    logger._logs_dir = tmp_path
    logger.start_session()
    return logger


def _install_blocking_sink(monkeypatch, logger):
    entered = threading.Event()
    release = threading.Event()
    real_open = builtins.open
    target = logger._get_transcript_file()

    def blocking_open(path, *args, **kwargs):
        if Path(path) == target and not entered.is_set():
            entered.set()
            release.wait(timeout=3.0)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", blocking_open)
    return entered, release


def test_queue_bounds_count_and_bytes_and_records_rejections(tmp_path, monkeypatch):
    logger = _new_logger(tmp_path, max_pending_writes=1, max_pending_bytes=8)
    entered, release = _install_blocking_sink(monkeypatch, logger)
    try:
        assert logger._enqueue_write("12345678") == 1
        assert entered.wait(timeout=1.0)
        assert logger._enqueue_write("x") is None  # pending item limit
        assert logger._enqueue_write("123456789") is None  # single item byte limit

        state = logger.diagnostics()
        assert state["pending_writes"] == 1
        assert state["pending_bytes"] == 8
        assert state["dropped_writes"] == 2
        assert state["dropped_capacity_writes"] == 1
        assert state["dropped_oversized_writes"] == 1
        assert logger.flush(timeout=0.01) is False

        release.set()
        assert logger.flush(timeout=1.0) is True
    finally:
        release.set()
        logger.shutdown(timeout=1.0)


def test_shutdown_timeout_is_retryable_and_begin_waits_for_old_writer(tmp_path, monkeypatch):
    logger = _new_logger(tmp_path)
    entered, release = _install_blocking_sink(monkeypatch, logger)
    try:
        logger._enqueue_write("pending")
        assert entered.wait(timeout=1.0)
        old_writer = logger._writer_thread

        first = logger.shutdown(timeout=0.02)
        assert first["closed"] is False
        assert first["timed_out"] is True
        assert first["writer_alive"] is True
        assert first["pending_writes"] == 1
        assert logger.begin() is False

        second = logger.shutdown(timeout=0.02)
        assert second["closed"] is False
        assert logger._writer_thread is old_writer

        release.set()
        retired = logger.shutdown(timeout=1.0)
        assert retired["closed"] is True
        assert retired["drained"] is True
        assert retired["writer_alive"] is False
        assert retired["pending_writes"] == 0
        assert logger.shutdown(timeout=0.2)["closed"] is True

        assert logger.begin() is True
        assert logger._writer_thread is not old_writer
        logger._enqueue_write("next lifespan")
        assert logger.shutdown(timeout=1.0)["closed"] is True
    finally:
        release.set()
        logger.shutdown(timeout=1.0)


def test_unified_end_session_flush_is_bounded_for_slow_sink(tmp_path, monkeypatch):
    logger = _new_logger(tmp_path)
    entered, release = _install_blocking_sink(monkeypatch, logger)
    try:
        logger._enqueue_write("slow record")
        assert entered.wait(timeout=1.0)

        class Conversation:
            ended = False

            def end_session(self, summary):
                self.ended = True

        unified = UnifiedLogger.__new__(UnifiedLogger)
        unified._conversation = Conversation()
        unified._transcript = logger

        started = time.monotonic()
        result = unified.end_session({"summary": "not copied into transcript"})
        elapsed = time.monotonic() - started

        assert unified._conversation.ended is True
        assert result is False
        assert elapsed < 0.8
        assert logger.diagnostics()["pending_writes"] >= 1

        release.set()
        assert logger.shutdown(timeout=1.0)["closed"] is True
    finally:
        release.set()
        logger.shutdown(timeout=1.0)


def test_write_failure_is_counted_and_end_session_reports_it(tmp_path, monkeypatch):
    logger = _new_logger(tmp_path)
    real_open = builtins.open
    target = logger._get_transcript_file()

    def failing_open(path, *args, **kwargs):
        if Path(path) == target:
            raise OSError("isolated transcript sink failure")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", failing_open)
    logger._enqueue_write("will fail")
    assert logger.flush(timeout=1.0) is True
    assert logger.end_session() is False

    result = logger.shutdown(timeout=1.0)
    assert result["closed"] is True
    assert result["write_failures"] >= 2
    assert result["pending_writes"] == 0


def test_module_lifecycle_api_does_not_construct_a_logger(tmp_path):
    TranscriptLogger._instance = None
    transcript_logger_module._transcript_logger = None

    absent_begin = transcript_logger_module.begin_transcript_logger_lifecycle()
    absent_shutdown = transcript_logger_module.shutdown_transcript_logger(
        deadline=time.monotonic() + 0.1
    )
    assert absent_begin == {
        "opened": False,
        "present": False,
        "reason": "not_initialized",
    }
    assert absent_shutdown["closed"] is True
    assert absent_shutdown["present"] is False
    assert TranscriptLogger._instance is None

    _new_logger(tmp_path)
    assert transcript_logger_module.begin_transcript_logger_lifecycle()["opened"] is True
    result = transcript_logger_module.shutdown_transcript_logger(
        deadline=time.monotonic() + 1.0
    )
    assert result["closed"] is True
    assert result["present"] is True
