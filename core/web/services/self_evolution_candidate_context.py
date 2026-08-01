"""Bounded source context for allowlisted self-evolution candidate targets."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_SOURCE_SECRET_RE = re.compile(
    r"(?i)(authorization|api[_-]?key|password|secret|token|cookie)"
    r"(\s*[:=]\s*)([\"']?)[^\"'\s,;]+"
)


def bounded_candidate_target_context(
    *,
    worktree_path: str,
    target_files: list[str],
    context: dict[str, Any],
    max_total_chars: int = 7000,
    max_file_chars: int = 3200,
) -> str:
    """Render bounded line-numbered excerpts from exact allowlisted targets."""

    root = Path(str(worktree_path or "")).resolve()
    plan = context.get("plan") if isinstance(context.get("plan"), dict) else {}
    request = (
        context.get("request")
        if isinstance(context.get("request"), dict)
        else {}
    )
    anchors = _context_anchors(
        " ".join(
            (
                str(request.get("goal") or ""),
                str(plan.get("summary") or ""),
                " ".join(
                    str(item.get("title") or item.get("description") or "")
                    for item in list(plan.get("steps") or [])
                    if isinstance(item, dict)
                ),
            )
        )
    )
    rendered: list[str] = []
    remaining = max(0, int(max_total_chars))
    for relative_path in target_files:
        if remaining <= 0:
            break
        candidate = (root / relative_path).resolve()
        try:
            candidate.relative_to(root)
            raw_text = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            continue
        lines = raw_text.replace("\x00", "").splitlines()
        indexes = _matching_line_indexes(lines, anchors)
        selected: set[int] = set()
        for index in indexes[:3]:
            selected.update(
                range(max(0, index - 10), min(len(lines), index + 15))
            )
        if not selected:
            selected.update(range(min(len(lines), 60)))
        body_lines = [
            f"{index + 1:>5}: {_redact_source_line(lines[index])}"
            for index in sorted(selected)
        ]
        body = f"--- {relative_path}\n" + "\n".join(body_lines)
        body = body[: max(0, int(max_file_chars))]
        if len(body) > remaining:
            body = body[:remaining]
        if body:
            rendered.append(body)
            remaining -= len(body)
    return "\n".join(rendered)


def _context_anchors(value: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", str(value or ""))
    unique_tokens = list(dict.fromkeys(tokens))
    symbol_tokens = sorted(
        (
            token
            for token in unique_tokens
            if "_" in token or token.startswith(("test", "def", "class"))
        ),
        key=lambda token: (
            token.count("_"),
            len(token),
        ),
        reverse=True,
    )
    prioritized: list[str] = []
    for token in symbol_tokens:
        prioritized.append(token)
        parts = [part for part in token.split("_") if part]
        if len(parts) < 4:
            continue
        for size in range(len(parts) - 1, 2, -1):
            prefix = "_".join(parts[:size])
            if len(prefix) >= 12:
                prioritized.append(prefix)
    return list(dict.fromkeys(prioritized + unique_tokens))[:36]


def _matching_line_indexes(
    lines: list[str],
    anchors: list[str],
) -> list[int]:
    if not anchors:
        return []
    scored: list[tuple[int, int, int, int]] = []
    anchor_count = len(anchors)
    for index, line in enumerate(lines):
        matched = [
            anchor_index
            for anchor_index, anchor in enumerate(anchors)
            if anchor in line
        ]
        if not matched:
            continue
        best_anchor_index = min(matched)
        scored.append(
            (
                anchor_count - best_anchor_index,
                len(anchors[best_anchor_index]),
                len(matched),
                -index,
            )
        )
    scored.sort(reverse=True)
    return [-item[3] for item in scored]


def _redact_source_line(line: str) -> str:
    return _SOURCE_SECRET_RE.sub(
        lambda match: (
            f"{match.group(1)}{match.group(2)}"
            f"{match.group(3)}[REDACTED]"
        ),
        str(line or ""),
    )
