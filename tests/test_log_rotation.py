from core.logging.log_rotation import (
    append_rotating_text,
    read_log_tail_bytes,
    rotate_log_file,
    write_log_tail_copy,
)


def test_append_rotating_text_rotates_before_projected_write_exceeds_limit(tmp_path):
    log_path = tmp_path / "events.jsonl"
    log_path.write_text("12345678", encoding="utf-8")

    result = append_rotating_text(log_path, "abcd", max_bytes=10, backup_count=2)

    assert result["rotated"] is True
    assert result["writtenBytes"] == 4
    assert log_path.read_text(encoding="utf-8") == "abcd"
    assert (tmp_path / "events.jsonl.1").read_text(encoding="utf-8") == "12345678"


def test_append_rotating_text_rejects_one_record_larger_than_current_file_limit(tmp_path):
    log_path = tmp_path / "events.jsonl"

    result = append_rotating_text(log_path, "x" * 11, max_bytes=10)

    assert result["errorType"] == "OutputLimitError"
    assert result["writtenBytes"] == 0
    assert not log_path.exists()


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
