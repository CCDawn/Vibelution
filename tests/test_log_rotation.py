from pathlib import Path

from core.logging.log_rotation import (
    read_log_tail_bytes,
    rotate_log_file,
    write_log_tail_copy,
)


def test_rotate_log_file_rotates_when_exceeding_max_bytes(tmp_path):
    log_path = tmp_path / "backend.stdout.log"
    log_path.write_text("x" * 10, encoding="utf-8")

    result = rotate_log_file(log_path, max_bytes=3, backup_count=2)

    assert result["rotated"] is True
    assert result["action"] == "rotated"
    assert log_path.read_text(encoding="utf-8") == ""
    assert (tmp_path / "backend.stdout.log.1").read_text(encoding="utf-8") == "x" * 10


def test_write_log_tail_copy_writes_bounded_tail(tmp_path):
    source = tmp_path / "backend.stdout.log"
    destination = tmp_path / "scene" / "raw" / "backend.stdout.log"
    source.write_text("line\n" + ("y" * 200), encoding="utf-8")

    result = write_log_tail_copy(source, destination, max_bytes=20)

    assert result["copied"] is True
    assert destination.exists()
    assert len(destination.read_bytes()) <= 20


def test_read_log_tail_bytes_skips_partial_first_line(tmp_path):
    path = tmp_path / "sample.log"
    path.write_bytes(b"0123456789abcdef\nTAIL\n")

    tail = read_log_tail_bytes(path, max_bytes=8)

    assert tail == b"TAIL\n"
