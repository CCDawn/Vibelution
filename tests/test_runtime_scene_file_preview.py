from pathlib import Path

import pytest

from core.web.services import runtime_scene_service as service


def _scene(tmp_path, monkeypatch):
    scene = tmp_path / "scenes" / "one"
    scene.mkdir(parents=True)
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service, "_resolve_scene_dir", lambda _id: scene)
    return scene


def test_growing_log_preview_reads_bounded_tail_and_sees_new_output(tmp_path, monkeypatch):
    scene = _scene(tmp_path, monkeypatch)
    path = scene / "large.log"
    path.write_bytes(("旧内容\n" * 100000).encode("utf-8") + b"LATEST_ONE\n")
    reads = []
    original_open = Path.open

    class CountedReader:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *args): self.stream.close()
        def seek(self, *args): return self.stream.seek(*args)
        def read(self, size=-1):
            assert size >= 0, "live preview must never read the whole file"
            raw = self.stream.read(size)
            reads.append(len(raw))
            return raw

    def counted_open(candidate, *args, **kwargs):
        stream = original_open(candidate, *args, **kwargs)
        return CountedReader(stream) if candidate == path and args == ("rb",) else stream

    monkeypatch.setattr(Path, "open", counted_open)
    first = service.read_runtime_scene_file("one", "large.log")
    assert first["truncated"]
    assert first["content"].endswith("LATEST_ONE\n")
    assert sum(reads) <= service.MAX_TEXT_CHARS * 4 + 8192
    reads.clear()
    with original_open(path, "ab") as stream:
        stream.write("最新追加\n".encode())
    second = service.read_runtime_scene_file("one", "large.log")
    assert second["content"].endswith("最新追加\n")
    assert second["content"] != first["content"]
    assert sum(reads) <= service.MAX_TEXT_CHARS * 4 + 8192


def test_small_text_preview_preserves_content_and_binary_rejection(tmp_path, monkeypatch):
    scene = _scene(tmp_path, monkeypatch)
    path = scene / "small.log"
    path.write_bytes("正常日志\n".encode("utf-8-sig"))
    payload = service.read_runtime_scene_file("one", "small.log")
    assert payload["content"] == "正常日志\n"
    assert not payload["truncated"]
    path.write_bytes(b"\x00binary")
    with pytest.raises(ValueError, match="Binary"):
        service.read_runtime_scene_file("one", "small.log")
    with pytest.raises(ValueError):
        service.read_runtime_scene_file("one", "../../outside.log")
