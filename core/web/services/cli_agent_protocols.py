"""Adapter-specific parsing helpers for persistent CLI Agent task output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


ANSI_RE = re.compile(
    r"(?:"
    r"\x1b\][^\x07]*(?:\x07|\x1b\\)"  # OSC
    r"|\x1b[P_X^][\s\S]*?\x1b\\"  # DCS/SOS/PM/APC
    r"|\x1b\[[0-?]*[ -/]*[@-~]"  # CSI
    r"|\x1b[@-Z\\-_]"  # single-character ESC
    r")"
)
COMPLETION_MARKER_RE = re.compile(r"\[VIBELUTION_CLI_DONE:[A-Za-z0-9_.:-]+\]")


@dataclass(frozen=True)
class CliTaskProtocol:
    adapter_id: str
    idle_completion_seconds: float
    min_completion_seconds: float
    max_tail_segments: int
    failure_patterns: tuple[str, ...]
    completion_patterns: tuple[str, ...]
    marker_completion_required: bool = False
    allow_idle_completion_with_marker: bool = False


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
            r"(?im)^\s*(error|failed|exception|traceback|fatal)\b",
            r"(?m)^\s*(执行失败|运行失败|报错|异常)\b",
        ),
        completion_patterns=(),
        marker_completion_required=True,
        allow_idle_completion_with_marker=True,
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
    "claude_code": CliTaskProtocol(
        adapter_id="claude_code",
        idle_completion_seconds=35.0,
        min_completion_seconds=4.0,
        max_tail_segments=10,
        failure_patterns=(
            r"(?i)\b(error|failed|exception|traceback|permission denied|aborted|tool use failed)\b",
            r"(执行失败|运行失败|报错|异常|失败|权限被拒绝|已中止)",
        ),
        completion_patterns=(
            r"(?i)\b(done|completed|finished|success)\b",
            r"(已完成|完成|成功)",
        ),
    ),
}


def protocol_for_adapter(adapter_id: str) -> CliTaskProtocol:
    return PROTOCOLS.get(str(adapter_id or "").strip().lower().replace("-", "_"), DEFAULT_PROTOCOL)


def task_input_for_adapter(
    adapter_id: str,
    task: str,
    *,
    completion_marker: str = "",
) -> str:
    """Return the interactive input payload for one task."""

    text = str(task or "").strip()
    if not text:
        return ""
    protocol = protocol_for_adapter(adapter_id)
    marker = str(completion_marker or "").strip()
    if protocol.marker_completion_required and marker:
        marker_body = marker.strip("[]")
        text = (
            f"{text}\n\n"
            "完成本任务后，请在最终回复最后单独输出结束标记。"
            "标记格式是：左方括号 + "
            f"{marker_body}"
            " + 右方括号。"
        )
    return f"{text}\r\n"


def strip_terminal_controls(text: str) -> str:
    value = ANSI_RE.sub("", str(text or ""))
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(ch for ch in value if ch == "\n" or ch == "\t" or ch.isprintable())
    return value


def split_semantic_segments(adapter_id: str, text: str) -> list[dict[str, Any]]:
    """Split output into semantic-ish transcript fragments instead of raw character tails."""

    cleaned = remove_protocol_markers(strip_terminal_controls(text))
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


def detect_task_status(adapter_id: str, text: str, *, completion_marker: str = "") -> str:
    cleaned = strip_terminal_controls(text)
    if not cleaned.strip():
        return ""
    protocol = protocol_for_adapter(adapter_id)
    marker = str(completion_marker or "").strip()
    if marker and marker in cleaned:
        return "completed"
    for pattern in protocol.failure_patterns:
        if _safe_search(pattern, cleaned):
            return "failed"
    if protocol.marker_completion_required:
        return ""
    for pattern in protocol.completion_patterns:
        if _safe_search(pattern, cleaned):
            return "completed"
    return ""


def summarize_segments(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in list(segments or []):
        text = remove_protocol_markers(str(item.get("text") or "")).strip()
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
            r"^(Thought|Answer|Build|Error|Status|状态|回答|思考|执行|运行|[$>#])\b",
            line,
            flags=re.IGNORECASE,
        )
    )


def _normalize_segment_text(text: str) -> str:
    lines = []
    for line in str(text or "").splitlines():
        stripped = re.sub(r"\s+", " ", remove_protocol_markers(line)).strip()
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


def completion_marker_for_task(task_id: str) -> str:
    normalized = "".join(ch if ch.isalnum() or ch in {"-", "_", ".", ":"} else "_" for ch in str(task_id or "").strip())
    return f"[VIBELUTION_CLI_DONE:{normalized}]" if normalized else ""


def remove_protocol_markers(text: str) -> str:
    return COMPLETION_MARKER_RE.sub("", str(text or ""))
