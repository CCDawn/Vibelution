"""Bounded checkout text discovery. Operational data never enters this reader."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import time
from pathlib import Path, PureWindowsPath

from .windows_read import lock_source_directory, read_source_bytes

MAX_FILE_BYTES = 256_000
MAX_SCAN_FILES = 2500
MAX_SCAN_BYTES = 4_000_000
MAX_RESULT_CHARS = 12_000
SOURCE_DIRS = frozenset({"core", "tools", "config", "web", "desktop", "scripts", "tests", "docs"})
ROOT_FILES = frozenset({"readme.md", "agents.md", "pyproject.toml", "requirements.txt", "package.json", "agent.py", "main.py", "vibelution_storage.py"})
TEXT_EXTENSIONS = frozenset({".py", ".ts", ".tsx", ".js", ".cjs", ".mjs", ".json", ".md", ".toml", ".yaml", ".yml", ".css", ".html", ".txt", ".rs", ".c", ".h"})
SKIP_DIRS = frozenset({"node_modules", "dist", "build", "coverage", "__pycache__", "logs", "log_info", "workspace", "sessions", "cache", "data", "private", "secrets"})
PRIVATE_NAMES = frozenset({"config.toml", "token.txt", "credentials.json", "credentials.toml", "secrets.json", "secrets.toml", "id_rsa", "id_ed25519"})
_SECRET_LITERAL = re.compile(r'''(?i)(?:api[_-]?key|password|passwd|secret|access[_-]?token|refresh[_-]?token|authorization)\s*["']?\s*[:=]\s*["'][^"'\r\n]+["']''')


class WorkspaceReadDenied(ValueError):
    pass


def redact(text: str) -> str:
    """Do not echo literal credentials found in code or diagnostic text."""
    return _SECRET_LITERAL.sub("[REDACTED_CREDENTIAL]", text)


def _allowed_parts(parts: tuple[str, ...]) -> bool:
    lower = tuple(part.casefold() for part in parts)
    if not lower or any(part.startswith(".") or part in SKIP_DIRS for part in lower):
        return False
    if lower[-1] in PRIVATE_NAMES or any(word in lower[-1] for word in ("credentials.", "secrets.", ".pem", ".pfx", ".key")):
        return False
    if any(part.endswith((".", " ")) or PureWindowsPath(part).is_reserved() for part in parts):
        return False
    return lower[0] in SOURCE_DIRS or (len(parts) == 1 and lower[0] in ROOT_FILES)


def _check_links(root: Path, path: Path) -> None:
    for item in [path, *path.parents]:
        if item == root:
            break
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise WorkspaceReadDenied("代码查询不读取链接或重解析路径。")
        if item == path and stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise WorkspaceReadDenied("代码查询不读取硬链接文件。")


def resolve_source(root: Path, value: str, *, directory: bool = False) -> Path:
    raw = str(value or "").replace("\\", "/")
    if not raw or Path(raw).is_absolute() or PureWindowsPath(raw).drive or ":" in raw:
        raise WorkspaceReadDenied("请使用当前项目内的相对源码路径。")
    parts = Path(raw).parts
    if ".." in parts or (raw != "." and not _allowed_parts(parts)):
        raise WorkspaceReadDenied("该路径不属于可读取的项目源码。")
    root = root.resolve()
    path = root / raw
    if not path.exists():
        raise WorkspaceReadDenied("源码路径不存在。")
    _check_links(root, path)
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or (resolved != root and not _allowed_parts(resolved.relative_to(root).parts)):
        raise WorkspaceReadDenied("源码路径超出当前项目读取范围。")
    if directory:
        if not path.is_dir():
            raise WorkspaceReadDenied("需要源码目录。")
    elif not path.is_file() or path.suffix.casefold() not in TEXT_EXTENSIONS:
        raise WorkspaceReadDenied("只允许读取项目源码和文本文档。")
    return path


def _read_text(root: Path, path: Path) -> tuple[str, str]:
    path = resolve_source(root, path.relative_to(root).as_posix())
    try:
        data = read_source_bytes(root, path, MAX_FILE_BYTES)
    except ValueError as exc:
        raise WorkspaceReadDenied("源码安全读取校验未通过，或文件超过预算。") from exc
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise WorkspaceReadDenied("该文件不是 UTF-8 文本。") from exc
    if "\x00" in text:
        raise WorkspaceReadDenied("不读取二进制内容。")
    return text, hashlib.sha256(data).hexdigest()


def read_source(root: Path, path: str, *, line: int, max_lines: int) -> dict:
    target = resolve_source(root, path)
    text, digest = _read_text(root, target)
    lines = text.splitlines()
    selected = "\n".join(lines[line - 1:line - 1 + max_lines])
    return {"path": target.relative_to(root).as_posix(), "line": line, "text": redact(selected)[:MAX_RESULT_CHARS],
            "totalLines": len(lines), "contentHash": digest,
            "truncated": line - 1 + max_lines < len(lines) or len(selected) > MAX_RESULT_CHARS}


def discover_sources(root: Path, *, path: str, query: str, offset: int, limit: int, search: bool) -> dict:
    if os.name != "nt":
        raise WorkspaceReadDenied("当前安全源码读取适配器仅支持 Windows。")
    base = resolve_source(root, path or ".", directory=True)
    root = root.resolve()
    pending = [base]
    items, scanned, scanned_bytes, skipped, visited = [], 0, 0, 0, 0
    deadline = time.monotonic() + 3
    exhausted = False
    while pending and not exhausted:
        folder = pending.pop(0)
        # Recheck every directory immediately before enumeration (also for junctions).
        try:
            resolve_source(root, folder.relative_to(root).as_posix() or ".", directory=True)
            with lock_source_directory(root, folder), os.scandir(folder) as entries:
                # Bound collection before sorting so native directory order does
                # not make ordinary pagination unstable or allocate without limit.
                ordered = []
                for entry in entries:
                    visited += 1
                    if visited > 6000 or time.monotonic() > deadline:
                        exhausted = True
                        break
                    ordered.append(entry)
                for entry in sorted(ordered, key=lambda item: item.name.casefold()):
                    if time.monotonic() > deadline:
                        exhausted = True
                        break
                    target = Path(entry.path)
                    relative = target.relative_to(root)
                    if not _allowed_parts(relative.parts) or entry.is_symlink():
                        continue
                    try:
                        _check_links(root, target)
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(target)
                            continue
                        if target.suffix.casefold() not in TEXT_EXTENSIONS:
                            continue
                        scanned += 1
                        if scanned > MAX_SCAN_FILES or scanned_bytes > MAX_SCAN_BYTES:
                            exhausted = True
                            break
                        if not search:
                            if not query or query.casefold() in relative.as_posix().casefold():
                                items.append({"path": relative.as_posix()})
                        else:
                            size = entry.stat(follow_symlinks=False).st_size
                            if size > MAX_FILE_BYTES:
                                skipped += 1
                                continue
                            if scanned_bytes + size > MAX_SCAN_BYTES:
                                exhausted = True
                                break
                            scanned_bytes += size
                            text, _ = _read_text(root, target)
                            for number, content in enumerate(text.splitlines(), 1):
                                if query.casefold() in content.casefold():
                                    items.append({"path": relative.as_posix(), "line": number, "text": redact(content)[:240]})
                                    if len(items) >= offset + limit + 1:
                                        break
                        if len(items) >= offset + limit + 1:
                            exhausted = True
                            break
                    except (OSError, ValueError):
                        skipped += 1
        except (OSError, ValueError):
            skipped += 1
    return {"items": items[offset:offset + limit], "nextOffset": offset + limit if len(items) > offset + limit else None,
            "truncated": exhausted or bool(skipped), "scannedFiles": scanned, "skippedFiles": skipped,
            "coverage": "bounded checkout scan; partial results do not prove absence"}
