"""Local self-contained HTML export for one session's conversation turns.

Intentional deviation from ZCode's cloud share: the export is a single HTML
file (inline CSS, base64-embedded images) the client saves via a Blob
download; no cloud round trip.

Security posture (escape red line, trumps feature completeness):
user and assistant text are untrusted input. Every content string goes through
``html.escape`` BEFORE any markdown-ish rendering, and the only markup this
module ever injects is produced by the whitelist transforms below — raw
`<script>`, `onerror=` attributes, and `javascript:` link targets can never
survive into the document. Links are restricted to http/https and always carry
``rel="noopener noreferrer" target="_blank"``.

Turn grouping mirrors the web turn directory
(``web/src/components/conversation/conversationTurnNavigation.ts``): a turn
opens at every user message and owns the first assistant message that follows
before the next user message; leading assistant messages form their own turns.
A turn's id is the assistant ``turnId`` when present, otherwise the anchoring
message id, so selections made in the dialog resolve here byte-identically.
"""

from __future__ import annotations

import base64
import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.web.services.session.image_attachments import resolve_session_image_artifact
from core.web.services.session.projection import get_session_detail

# Private-use sentinels for placeholder substitution; stripped from source text
# first so user content can never collide with the substitution stream.
_SENTINEL_OPEN = "\ue000"
_SENTINEL_CLOSE = "\ue001"

_FENCE_RE = re.compile(r"```[^\n]*\n?(.*?)(?:```|\Z)", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]*)\)")
_TIMESTAMP_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})")
_SLUG_STRIP_RE = re.compile(r"[^\w\u4e00-\u9fff-]+", re.UNICODE)

_MAX_TITLE_CHARS = 80
_MAX_FILENAME_STEM_CHARS = 40

_DOCUMENT_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #f6f7f9; color: #1c2024;
  font-family: -apple-system, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
  font-size: 14px; line-height: 1.65; }
.wrap { max-width: 860px; margin: 0 auto; padding: 32px 20px 64px; }
header.doc-head { border-bottom: 1px solid #e3e6ea; padding-bottom: 16px; margin-bottom: 24px; }
header.doc-head h1 { font-size: 20px; margin: 0 0 6px; }
header.doc-head .sub { color: #6b7280; font-size: 12px; margin: 0; }
.turn { background: #ffffff; border: 1px solid #e3e6ea; border-radius: 10px;
  padding: 16px 18px; margin-bottom: 16px; }
.turn-head { display: flex; justify-content: space-between; gap: 12px;
  color: #6b7280; font-size: 12px; margin-bottom: 12px; }
.msg { padding: 8px 0; }
.msg + .msg { border-top: 1px dashed #eceef1; }
.msg .meta { font-size: 12px; color: #8a919c; margin-bottom: 4px; }
.msg.user .meta .role { color: #2563eb; font-weight: 600; }
.msg.assistant .meta .role { color: #0f766e; font-weight: 600; }
.msg .body { overflow-wrap: anywhere; }
.msg .body p { margin: 0 0 8px; }
.msg .body p:last-child { margin-bottom: 0; }
pre { background: #f3f4f6; border: 1px solid #e3e6ea; border-radius: 8px;
  padding: 10px 12px; overflow-x: auto; font-size: 13px; margin: 8px 0; }
code { font-family: ui-monospace, Consolas, "Courier New", monospace;
  background: #f3f4f6; border-radius: 4px; padding: 1px 4px; font-size: 13px; }
pre code { background: transparent; padding: 0; }
a { color: #2563eb; }
table { border-collapse: collapse; margin: 8px 0; }
th, td { border: 1px solid #e3e6ea; padding: 4px 10px; text-align: left; }
th { background: #f3f4f6; }
img { max-width: 100%; border-radius: 8px; }
.attachments { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }
.attachments img { display: block; }
.attach-note, .attach-missing, .attach-file { font-size: 12px; color: #6b7280;
  background: #f6f7f9; border: 1px dashed #d7dbe0; border-radius: 6px;
  padding: 4px 8px; width: fit-content; }
"""


def export_session_html(
    session_id: str,
    *,
    turn_ids: list[str] | None = None,
    include_attachments: bool = True,
) -> dict[str, Any]:
    """Assemble the single-file HTML export for the selected turns.

    Returns ``{filename, html, skippedTurnIds}``. Raises ``SessionNotFoundError``
    when the session does not exist. Unknown requested turn ids are reported in
    ``skippedTurnIds`` (request order, deduplicated) instead of failing.
    """

    normalized_session_id = str(session_id or "").strip()
    detail = get_session_detail(
        normalized_session_id,
        include_secondary=False,
        transcript_scope="none",
    )
    if detail is None:
        from core.web.services.session_service import SessionNotFoundError

        raise SessionNotFoundError(f"Session not found: {normalized_session_id}")

    messages = detail.get("messages") if isinstance(detail, dict) else None
    turns = _group_messages_into_turns(messages if isinstance(messages, list) else [])

    selected, skipped = _select_turns(
        turns,
        turn_ids if isinstance(turn_ids, list) else None,
    )

    title = str((detail or {}).get("title") or "").strip() or normalized_session_id
    exported_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    body_turns = "\n".join(
        _render_turn(index, turn, include_attachments, session_id=normalized_session_id)
        for index, turn in enumerate(selected, start=1)
    )
    document = _render_document(
        title=title,
        exported_at=exported_at,
        turn_count=len(selected),
        body_turns=body_turns,
    )
    return {
        "filename": _export_filename(title),
        "html": document,
        "skippedTurnIds": skipped,
    }


# ---------------------------------------------------------------------------
# Turn grouping (mirrors conversationTurnNavigation.ts semantics)


def _message_kind(message: dict[str, Any]) -> str:
    role = str(message.get("role") or "").strip().lower()
    if role in {"user", "assistant"}:
        return role
    return "other"


def _message_turn_id(message: dict[str, Any]) -> str:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    turn_id = str(
        message.get("turnId")
        or metadata.get("turnId")
        or metadata.get("turn_id")
        or ""
    ).strip()
    return turn_id or str(message.get("id") or "").strip()


def _group_messages_into_turns(messages: list[Any]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        kind = _message_kind(raw)
        if kind == "user":
            current = {
                "turnId": _message_turn_id(raw),
                "user": raw,
                "assistant": None,
            }
            turns.append(current)
            continue
        if kind == "assistant":
            if current is not None and current["user"] is not None and current["assistant"] is None:
                current["assistant"] = raw
                assistant_turn_id = str(raw.get("turnId") or "").strip()
                if assistant_turn_id:
                    current["turnId"] = assistant_turn_id
                continue
            current = {
                "turnId": str(raw.get("turnId") or "").strip() or _message_turn_id(raw),
                "user": None,
                "assistant": raw,
            }
            turns.append(current)
    return turns


def _select_turns(
    turns: list[dict[str, Any]],
    turn_ids: list[str] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not turn_ids:
        return turns, []
    known_ids: dict[str, int] = {}
    for index, turn in enumerate(turns):
        turn_id = str(turn.get("turnId") or "").strip()
        if turn_id and turn_id not in known_ids:
            known_ids[turn_id] = index
    selected_indexes: list[int] = []
    skipped: list[str] = []
    seen_requested: set[str] = set()
    for raw_id in turn_ids:
        turn_id = str(raw_id or "").strip()
        if not turn_id or turn_id in seen_requested:
            continue
        seen_requested.add(turn_id)
        if turn_id in known_ids:
            selected_indexes.append(known_ids[turn_id])
        else:
            skipped.append(turn_id)
    # Keep document order regardless of selection order.
    selected_indexes.sort()
    return [turns[index] for index in selected_indexes], skipped


# ---------------------------------------------------------------------------
# Untrusted-text rendering: escape first, whitelist transforms second


def _escape_content(text: Any) -> str:
    """Strip substitution sentinels, then HTML-escape (quotes included)."""

    raw = str(text or "").replace(_SENTINEL_OPEN, "").replace(_SENTINEL_CLOSE, "")
    return html.escape(raw, quote=True)


def _safe_link(href: str) -> str:
    """Only http/https targets become links; everything else neutralizes."""

    normalized = href.strip()
    if re.match(r"^https?://", normalized, re.IGNORECASE):
        return normalized
    return ""


def _render_inline(text: str) -> str:
    """Whitelist inline markdown on already-escaped text.

    Inline code spans are lifted into sentinels so bold/link transforms never
    rewrite their contents; links keep escaped label/href text (escaped quotes
    make attribute breakout impossible) and only http/https schemes.
    """

    code_spans: list[str] = []

    def _stash_code(match: re.Match[str]) -> str:
        code_spans.append(f"<code>{match.group(1)}</code>")
        return f"{_SENTINEL_OPEN}{len(code_spans) - 1}{_SENTINEL_CLOSE}"

    text = _INLINE_CODE_RE.sub(_stash_code, text)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)

    def _render_link(match: re.Match[str]) -> str:
        label = match.group(1)
        href = _safe_link(match.group(2))
        if not href:
            return label
        return f'<a href="{href}" rel="noopener noreferrer" target="_blank">{label}</a>'

    text = _LINK_RE.sub(_render_link, text)

    def _restore_code(match: re.Match[str]) -> str:
        return code_spans[int(match.group(1))]

    text = re.sub(
        f"{re.escape(_SENTINEL_OPEN)}(\\d+){re.escape(_SENTINEL_CLOSE)}",
        _restore_code,
        text,
    )
    return text


def _render_rich_text(content: Any) -> str:
    """Escape, then reduce the text to fenced code blocks and paragraphs."""

    escaped = _escape_content(content)
    if not escaped.strip():
        return ""
    parts: list[str] = []
    position = 0
    for match in _FENCE_RE.finditer(escaped):
        leading = escaped[position:match.start()]
        parts.append(_render_text_block(leading))
        # Code-block contents stay escaped plain text; no inline transforms.
        parts.append(f"<pre><code>{match.group(1)}</code></pre>")
        position = match.end()
    parts.append(_render_text_block(escaped[position:]))
    return "".join(part for part in parts if part)


def _render_text_block(text: str) -> str:
    if not text.strip():
        return ""
    rendered = _render_inline(text.strip("\n")).replace("\r\n", "\n").replace("\n", "<br />")
    return f"<p>{rendered}</p>"


# ---------------------------------------------------------------------------
# Attachments


def _format_size(size_bytes: int) -> str:
    size = max(0, int(size_bytes or 0))
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


_IMAGE_KINDS = {"user_image", "image"}


def _render_attachment(
    session_id: str,
    attachment: dict[str, Any],
    *,
    include_attachments: bool,
) -> str:
    filename = str(attachment.get("filename") or "").strip() or "attachment"
    escaped_filename = html.escape(filename, quote=True)
    kind = str(attachment.get("kind") or "").strip().lower()
    if kind not in _IMAGE_KINDS:
        size_text = _format_size(attachment.get("sizeBytes"))
        return f'<div class="attach-file">[文件] {escaped_filename} · {size_text}</div>'
    if not include_attachments:
        return f'<div class="attach-note">[图片未内嵌] {escaped_filename}</div>'
    artifact_id = str(attachment.get("artifactId") or "").strip()
    content_type = str(attachment.get("contentType") or "").strip() or "image/png"
    try:
        path, resolved_content_type = resolve_session_image_artifact(session_id, artifact_id)
        payload = Path(path).read_bytes()
        content_type = resolved_content_type or content_type
    except Exception:
        return f'<div class="attach-missing">[图片无法内嵌] {escaped_filename}</div>'
    encoded = base64.b64encode(payload).decode("ascii")
    return (
        f'<img src="data:{html.escape(content_type, quote=True)};base64,{encoded}" '
        f'alt="{escaped_filename}" />'
    )


def _render_attachments(
    session_id: str,
    message: dict[str, Any] | None,
    *,
    include_attachments: bool,
) -> str:
    if message is None:
        return ""
    raw_attachments = message.get("attachments")
    if not isinstance(raw_attachments, list) or not raw_attachments:
        return ""
    rendered = [
        _render_attachment(session_id, item, include_attachments=include_attachments)
        for item in raw_attachments
        if isinstance(item, dict)
    ]
    if not rendered:
        return ""
    return f'<div class="attachments">{"".join(rendered)}</div>'


# ---------------------------------------------------------------------------
# Assistant text (turnItems agent_message items, final answer first)


def _assistant_text(message: dict[str, Any] | None) -> str:
    if message is None:
        return ""
    items = message.get("turnItems")
    if not isinstance(items, list):
        return ""
    final_parts: list[str] = []
    other_parts: list[str] = []
    for item in items:
        if not isinstance(item, dict) or str(item.get("type") or "") != "agent_message":
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if str(item.get("phase") or "") == "final_answer":
            final_parts.append(text)
        else:
            other_parts.append(text)
    selected = final_parts or other_parts
    return "\n\n".join(selected)


def _format_timestamp(message: dict[str, Any] | None) -> str:
    if message is None:
        return ""
    raw = str(message.get("timestamp") or "").strip()
    match = _TIMESTAMP_PREFIX_RE.match(raw)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    return raw


def _render_turn(
    index: int,
    turn: dict[str, Any],
    include_attachments: bool,
    *,
    session_id: str,
) -> str:
    user_message = turn.get("user")
    assistant_message = turn.get("assistant")
    user_time = _format_timestamp(user_message)
    assistant_time = _format_timestamp(assistant_message)
    user_body = _render_rich_text((user_message or {}).get("content"))
    assistant_body = _render_rich_text(_assistant_text(assistant_message))
    user_section = ""
    if user_message is not None:
        user_section = (
            '<div class="msg user">'
            f'<div class="meta"><span class="role">用户</span>'
            f"{f' · {html.escape(user_time, quote=True)}' if user_time else ''}</div>"
            f'<div class="body">{user_body}</div>'
            f"{_render_attachments(session_id, user_message, include_attachments=include_attachments)}"
            "</div>"
        )
    assistant_section = ""
    if assistant_message is not None:
        assistant_section = (
            '<div class="msg assistant">'
            f'<div class="meta"><span class="role">助手</span>'
            f"{f' · {html.escape(assistant_time, quote=True)}' if assistant_time else ''}</div>"
            f'<div class="body">{assistant_body}</div>'
            "</div>"
        )
    turn_time = user_time or assistant_time
    return (
        '<div class="turn">'
        '<div class="turn-head">'
        f"<span>第 {index} 轮</span>"
        f"{f'<span>{html.escape(turn_time, quote=True)}</span>' if turn_time else ''}"
        "</div>"
        f"{user_section}{assistant_section}"
        "</div>"
    )


# ---------------------------------------------------------------------------
# Document shell + filename


def _render_document(*, title: str, exported_at: str, turn_count: int, body_turns: str) -> str:
    escaped_title = _escape_content(title)
    empty_note = "" if turn_count else '<p class="sub">没有可导出的轮次。</p>'
    return (
        "<!doctype html>\n"
        '<html lang="zh">\n'
        "<head>\n"
        '<meta charset="utf-8" />\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        f"<title>{escaped_title}</title>\n"
        f"<style>{_DOCUMENT_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        '<main class="wrap">\n'
        '<header class="doc-head">\n'
        f"<h1>{escaped_title}</h1>\n"
        f'<p class="sub">Vibelution 会话导出 · {html.escape(exported_at, quote=True)} · {turn_count} 轮</p>\n'
        f"{empty_note}\n"
        "</header>\n"
        f"{body_turns}\n"
        "</main>\n"
        "</body>\n"
        "</html>\n"
    )


def _export_filename(title: str) -> str:
    raw = str(title or "").strip()[:_MAX_TITLE_CHARS]
    slug = _SLUG_STRIP_RE.sub("-", raw)
    slug = re.sub(r"-{2,}", "-", slug).strip("-").strip(".")[:_MAX_FILENAME_STEM_CHARS]
    slug = slug.strip("-")
    if not slug:
        slug = "session"
    date_part = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
    return f"vibelution-{slug}-{date_part}.html"
