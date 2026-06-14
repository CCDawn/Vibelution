"""Adapter-specific parsing helpers for persistent CLI Agent task output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@dataclass(frozen=True)
class CliTaskProtocol:
    adapter_id: str
    idle_completion_seconds: float
    min_completion_seconds: float
    max_tail_segments: int
    failure_patterns: tuple[str, ...]
    completion_patterns: tuple[str, ...]


DEFAULT_PROTOCOL = CliTaskProtocol(
    adapter_id="default",
    idle_completion_seconds=30.0,
    min_completion_seconds=3.0,
    max_tail_segments=8,
    failure_patterns=(
        r"(?i)\b(error|failed|exception|traceback)\b",
        r"(执行失败|运行失败|报错|异常)",
    ),
    completion_patterns=(
        r"(?i)\b(done|completed|finished|success)\b",
        r"(已完成|完成|成功)",
    ),
)


PROTOCOLS: dict[str, CliTaskProtocol] = {
    "mimo_code": CliTaskProtocol(
        adapter_id="mimo_code",
        idle_completion_seconds=25.0,
        min_completion_seconds=4.0,
        max_tail_segments=8,
        failure_patterns=(
            r"(?i)\b(error|failed|exception|traceback)\b",
            r"(执行失败|运行失败|报错|异常|失败)",
        ),
        completion_patterns=(
            r"(?i)\b(done|completed|finished|success)\b",
            r"(已完成|完成|成功|你好！我是)",
        ),
    ),
    "codex_code": CliTaskProtocol(
        adapter_id="codex_code",
        idle_completion_seconds=25.0,
        min_completion_seconds=4.0,
        max_tail_segments=8,
        failure_patterns=(
            r"(?i)\b(error|failed|exception|traceback|permission denied)\b",
            r"(执行失败|运行失败|报错|异常|失败)",
        ),
        completion_patterns=(
            r"(?i)\b(done|completed|finished|success)\b",
            r"(已完成|完成|成功)",
        ),
    ),
}


def protocol_for_adapter(adapter_id: str) -> CliTaskProtocol:
    return PROTOCOLS.get(str(adapter_id or "").strip().lower().replace("-", "_"), DEFAULT_PROTOCOL)


def task_input_for_adapter(adapter_id: str, task: str) -> str:
    """Return the interactive input payload for one task."""

    text = str(task or "").strip()
    if not text:
        return ""
    return f"{text}\r\n"


def strip_terminal_controls(text: str) -> str:
    value = ANSI_RE.sub("", str(text or ""))
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(ch for ch in value if ch == "\n" or ch == "\t" or ch.isprintable())
    return value


def split_semantic_segments(adapter_id: str, text: str) -> list[dict[str, Any]]:
    """Split output into semantic-ish transcript fragments instead of raw character tails."""

    cleaned = strip_terminal_controls(text)
    if not cleaned.strip():
        return []
    blocks = _paragraph_blocks(cleaned)
    segments: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        normalized = _normalize_segment_text(block)
        if not normalized:
            continue
        segments.append(
            {
                "index": index,
                "kind": _classify_segment_kind(adapter_id, normalized),
                "text": normalized,
            }
        )
    return segments


def tail_semantic_segments(adapter_id: str, text: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    protocol = protocol_for_adapter(adapter_id)
    max_segments = protocol.max_tail_segments if limit is None else max(1, int(limit or 1))
    segments = split_semantic_segments(adapter_id, text)
    return segments[-max_segments:]


def detect_task_status(adapter_id: str, text: str) -> str:
    cleaned = strip_terminal_controls(text)
    if not cleaned.strip():
        return ""
    protocol = protocol_for_adapter(adapter_id)
    for pattern in protocol.failure_patterns:
        if _safe_search(pattern, cleaned):
            return "failed"
    for pattern in protocol.completion_patterns:
        if _safe_search(pattern, cleaned):
            return "completed"
    return ""


def summarize_segments(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in list(segments or []):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        kind = str(item.get("kind") or "output").strip() or "output"
        lines.append(f"[{kind}] {text}")
    return "\n\n".join(lines).strip()


def _paragraph_blocks(text: str) -> list[str]:
    lines = [line.rstrip() for line in str(text or "").splitlines()]
    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue
        if _looks_like_new_block(stripped) and current:
            blocks.append("\n".join(current).strip())
            current = [stripped]
            continue
        current.append(stripped)
    if current:
        blocks.append("\n".join(current).strip())
    return blocks


def _looks_like_new_block(line: str) -> bool:
    return bool(
        re.match(
            r"^(Thought|Answer|Build|Error|Traceback|Status|状态|回答|思考|执行|运行|[$>#])\b",
            line,
            flags=re.IGNORECASE,
        )
    )


def _normalize_segment_text(text: str) -> str:
    lines = []
    for line in str(text or "").splitlines():
        stripped = re.sub(r"\s+", " ", line).strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines).strip()


def _classify_segment_kind(adapter_id: str, text: str) -> str:
    lowered = text.lower()
    if detect_task_status(adapter_id, text) == "failed":
        return "error"
    if lowered.startswith("thought") or text.startswith("思考"):
        return "thought"
    if lowered.startswith("answer") or text.startswith("回答"):
        return "answer"
    if lowered.startswith("build") or lowered.startswith("status") or text.startswith(("状态", "执行", "运行")):
        return "status"
    return "output"


def _safe_search(pattern: str, text: str) -> bool:
    try:
        return bool(re.search(pattern, text))
    except re.error:
        return False

