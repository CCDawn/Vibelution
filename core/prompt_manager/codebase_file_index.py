"""Bounded, versioned Python metadata index shared by codebase map consumers.

Only derived metadata is retained, never source text or AST trees. Stat checks
keep edits, atomic replacements and deletions visible without reparsing unchanged
files. The lock coalesces concurrent reads of an uncached file.
"""
from __future__ import annotations

import ast
import os
import threading
from collections import OrderedDict
from pathlib import Path

_MAX_ENTRIES = 8192
_cache: OrderedDict[str, tuple[tuple[int, ...], dict | None]] = OrderedDict()
_lock = threading.Lock()


def file_version(path: Path) -> tuple[int, ...] | None:
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_dev, stat.st_ino)
    except OSError:
        return None


def _copy_metadata(info: dict | None) -> dict | None:
    return {**info, "imports": list(info["imports"])} if info is not None else None


def _remember(key: str, version: tuple[int, ...], info: dict | None) -> None:
    _cache[key] = (version, info)
    while len(_cache) > _MAX_ENTRIES:
        _cache.popitem(last=False)


def scan_python_file(path: Path) -> dict | None:
    key = os.path.normcase(os.path.abspath(path))
    with _lock:
        version = file_version(path)
        if version is None:
            _cache.pop(key, None)
            return None
        cached = _cache.get(key)
        if cached is not None and cached[0] == version:
            _cache.move_to_end(key)
            return _copy_metadata(cached[1])
        _cache.pop(key, None)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            doc = ast.get_docstring(tree)
            imports: list[str] = []
            classes = functions = methods = 0
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ClassDef):
                    classes += 1
                    methods += sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in node.body)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions += 1
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names if alias.name.startswith(("core", "tools", "config")))
                elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(("core", "tools", "config")):
                    imports.append(node.module)
            info = {
                "line_count": len(source.splitlines()),
                "docstring": doc.split("\n")[0].strip() if doc else "",
                "imports": list(dict.fromkeys(imports)),
                "n_classes": classes,
                "n_tests": methods + functions,
            }
            # Do not publish metadata parsed while a writer changed this file.
            if file_version(path) != version:
                return None
            _remember(key, version, info)
            return _copy_metadata(info)
        except (SyntaxError, UnicodeError):
            # Malformed source is also versioned: fixtures should not be parsed
            # on every scoring pass; fixing the file invalidates this entry.
            if file_version(path) == version:
                _remember(key, version, None)
            return None
        except Exception:
            return None
