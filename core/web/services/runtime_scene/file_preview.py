"""Bounded previews of runtime scene files, including the latest live output."""
from __future__ import annotations

import os


def read_runtime_scene_file(scene_id: str, relative_path: str) -> dict:
    from core.web.services import runtime_scene_service as s

    scene_dir = s._resolve_scene_dir(scene_id)
    relative = s._normalize_relative_path(relative_path)
    file_path = s._resolve_scene_child(scene_dir, relative)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Runtime scene file not found: {relative}")
    # UTF-8 needs at most four bytes per character. Read a fixed window from
    # the same open handle so a growing or rotated file cannot trigger read-all.
    byte_limit = max(1, int(s.MAX_TEXT_CHARS)) * 4
    with file_path.open("rb") as stream:
        head = stream.read(min(8192, byte_limit))
        if b"\x00" in head:
            raise ValueError("Binary runtime scene files are not supported in the preview yet")
        size = stream.seek(0, os.SEEK_END)
        offset = max(0, size - byte_limit)
        stream.seek(offset)
        raw = stream.read(byte_limit)
    content = raw.decode("utf-8-sig", errors="replace")
    truncated = offset > 0 or len(content) > s.MAX_TEXT_CHARS
    if truncated:
        content = "... earlier content omitted ...\n\n" + content[-s.MAX_TEXT_CHARS:]
    scene_root_path = scene_dir.relative_to(s.PROJECT_ROOT).as_posix()
    return {
        "rootId": "runtime_scenes",
        "rootPath": scene_root_path,
        "relativePath": relative,
        "path": f"{scene_root_path}/{relative}".replace("//", "/"),
        "language": s.LANGUAGE_BY_SUFFIX.get(file_path.suffix.lower(), "text"),
        "content": content,
        "truncated": truncated,
        "diagnostics": s._analyze_runtime_scene_content(scene_id, relative, content),
    }
