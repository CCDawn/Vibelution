# -*- coding: utf-8 -*-
"""Project-root path containment (Python reference for Rust pilot P1).

Optional Rust sidecar: ``crates/vibelution-path-containment``.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path, PurePath
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUST_BIN_CANDIDATES = (
    PROJECT_ROOT
    / "crates"
    / "vibelution-path-containment"
    / "target"
    / "release"
    / "vibelution-path-containment.exe",
    PROJECT_ROOT
    / "crates"
    / "vibelution-path-containment"
    / "target"
    / "release"
    / "vibelution-path-containment",
    PROJECT_ROOT
    / "crates"
    / "vibelution-path-containment"
    / "target"
    / "debug"
    / "vibelution-path-containment.exe",
    PROJECT_ROOT
    / "crates"
    / "vibelution-path-containment"
    / "target"
    / "debug"
    / "vibelution-path-containment",
)


def _lexical_normalize(path: Path) -> Path:
    """Collapse . / .. without requiring the path to exist."""
    parts: list[str] = []
    for part in PurePath(path).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if parts and parts[-1] not in (Path(path.anchor).parts if path.anchor else ()):
                # Don't pop drive/root anchors
                if path.anchor and len(parts) <= len(PurePath(path.anchor).parts):
                    continue
                if parts and parts[-1] != "..":
                    parts.pop()
                    continue
            if not path.is_absolute():
                parts.append("..")
            continue
        parts.append(part)
    if path.anchor:
        # Rebuild with anchor: on Windows PurePath parts include drive.
        return Path(*parts) if parts else Path(path.anchor)
    return Path(*parts) if parts else Path(".")


def _normalize_root(project_root: str | Path) -> Path:
    root = Path(str(project_root or "").strip())
    if not str(root):
        raise ValueError("empty_root")
    if root.is_absolute():
        return _lexical_normalize(root)
    return _lexical_normalize(Path.cwd() / root)


def _make_absolute(root: Path, candidate: Path) -> Path:
    if candidate.is_absolute():
        return _lexical_normalize(candidate)
    return _lexical_normalize(root / candidate)


def _path_key(path: Path) -> str:
    text = str(path)
    if os.name == "nt":
        return text.replace("/", "\\").lower()
    return text


def _is_same_or_child(child: Path, parent: Path) -> bool:
    child_key = _path_key(child)
    parent_key = _path_key(parent)
    if child_key == parent_key:
        return True
    sep = "\\" if os.name == "nt" else "/"
    prefix = parent_key if parent_key.endswith(sep) else parent_key + sep
    return child_key.startswith(prefix)


def contain_path_dict(
    project_root: str | Path,
    candidate: str | Path,
    *,
    engine: str = "python",
) -> dict[str, Any]:
    root_raw = str(project_root or "").strip()
    cand_raw = str(candidate or "").strip()
    if not root_raw:
        return {
            "ok": False,
            "root": str(project_root or ""),
            "candidate": str(candidate or ""),
            "resolved": None,
            "relative": None,
            "error": "empty_root",
            "engine": engine,
        }
    if not cand_raw:
        return {
            "ok": False,
            "root": root_raw,
            "candidate": str(candidate or ""),
            "resolved": None,
            "relative": None,
            "error": "empty_candidate",
            "engine": engine,
        }
    if "\x00" in root_raw or "\x00" in cand_raw:
        return {
            "ok": False,
            "root": root_raw,
            "candidate": cand_raw,
            "resolved": None,
            "relative": None,
            "error": "null_byte",
            "engine": engine,
        }

    try:
        root = _normalize_root(root_raw)
    except ValueError:
        return {
            "ok": False,
            "root": root_raw,
            "candidate": cand_raw,
            "resolved": None,
            "relative": None,
            "error": "empty_root",
            "engine": engine,
        }
    resolved = _make_absolute(root, Path(cand_raw))
    if not _is_same_or_child(resolved, root):
        return {
            "ok": False,
            "root": str(root),
            "candidate": cand_raw,
            "resolved": str(resolved),
            "relative": None,
            "error": "outside_root",
            "engine": engine,
        }
    if _path_key(resolved) == _path_key(root):
        relative = ""
    else:
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError:
            # Windows case-fold: fall back to string strip
            root_s = _path_key(root).rstrip("\\/")
            child_s = _path_key(resolved)
            relative = child_s[len(root_s) :].lstrip("\\/").replace("\\", "/")
    return {
        "ok": True,
        "root": str(root),
        "candidate": cand_raw,
        "resolved": str(resolved),
        "relative": relative,
        "error": None,
        "engine": engine,
    }


def resolve_path_containment_binary() -> Path | None:
    override = str(os.environ.get("VIBELUTION_PATH_CONTAINMENT_BIN") or "").strip()
    if override:
        path = Path(override)
        return path if path.is_file() else None
    for candidate in DEFAULT_RUST_BIN_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def contain_path_via_rust(
    project_root: str | Path,
    candidate: str | Path,
    *,
    timeout_s: float = 2.0,
) -> dict[str, Any] | None:
    binary = resolve_path_containment_binary()
    if binary is None:
        return None
    payload = json.dumps(
        {"projectRoot": str(project_root), "candidate": str(candidate)},
        ensure_ascii=False,
    )
    try:
        # Sidecar is CUI; hide console or every path check flashes a window mid-turn.
        from scripts.windowless_subprocess import no_window_subprocess_kwargs

        completed = subprocess.run(
            [str(binary)],
            input=payload,
            text=True,
            capture_output=True,
            timeout=max(0.2, float(timeout_s)),
            check=False,
            **no_window_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or not str(completed.stdout or "").strip():
        return None
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def contain_path(
    project_root: str | Path,
    candidate: str | Path,
    *,
    prefer_rust: bool | None = None,
) -> dict[str, Any]:
    use_rust = prefer_rust
    if use_rust is None:
        flag = str(os.environ.get("VIBELUTION_PATH_CONTAINMENT_ENGINE") or "").strip().lower()
        if flag in {"rust", "python"}:
            use_rust = flag == "rust"
        else:
            use_rust = resolve_path_containment_binary() is not None
    if use_rust:
        rust = contain_path_via_rust(project_root, candidate)
        if rust is not None:
            rust = dict(rust)
            rust["engine"] = "rust"
            return rust
    return contain_path_dict(project_root, candidate, engine="python")


def assert_path_within_root(project_root: str | Path, candidate: str | Path) -> Path:
    """Raise PermissionError when candidate escapes project_root; else return resolved Path."""
    result = contain_path(project_root, candidate)
    if not result.get("ok"):
        raise PermissionError(
            f"path outside project root ({result.get('error') or 'outside_root'}): {candidate}"
        )
    return Path(str(result["resolved"]))
