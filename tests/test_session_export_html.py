"""Session local HTML export: route contract, assembly, and escape safety.

User content is untrusted input — the XSS cases below are the primary
acceptance gate and take precedence over rendering convenience.
"""

from __future__ import annotations

import base64

import pytest

from core.web.routes.session_export_models import SessionExportHtmlPayload
from core.web.services import session_service
from tests.test_agent_config_workspace_service import (
    _fake_config_workspace,
    _use_tmp_project_root,
    client,
)

_MINIMAL_PNG = b"\x89PNG\r\n\x1a\n" + (b"\x00" * 32)


def _create_session(tmp_path, monkeypatch, title: str) -> dict:
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(session_service, "_agent_lookup_for_conversations", lambda *args, **kwargs: {})
    return session_service.create_chat_session(title=title)


def _seed_turn(
    session_id: str,
    turn_id: str,
    role: str,
    content: str,
    timestamp: str,
) -> None:
    from core.chat.conversation_ledger import append_conversation_event
    from core.chat.turn_journal import EVENT_ASSISTANT_MESSAGE, EVENT_USER_MESSAGE

    append_conversation_event(
        session_service.PROJECT_ROOT,
        session_id,
        turn_id,
        EVENT_USER_MESSAGE if role == "user" else EVENT_ASSISTANT_MESSAGE,
        status="recorded" if role == "user" else "completed",
        payload={"content": content},
        source="test.session_export_html",
        timestamp=timestamp,
    )


def _export(session_id: str, payload: dict | None = None):
    body = payload if payload is not None else {}
    return client.post(f"/api/sessions/{session_id}/export-html", json=body)


def test_export_returns_turn_grouped_html(tmp_path, monkeypatch):
    session = _create_session(tmp_path, monkeypatch, "导出内容测试")
    sid = session["id"]
    _seed_turn(sid, "turn-1", "user", "帮我总结一下要点", "2026-01-02T10:30:00")
    _seed_turn(sid, "turn-1", "assistant", "要点如下：**加粗**与 `code` 片段。", "2026-01-02T10:30:05")
    _seed_turn(sid, "turn-2", "user", "第二问", "2026-01-02T10:31:00")
    _seed_turn(sid, "turn-2", "assistant", "第二答", "2026-01-02T10:31:10")

    response = _export(session["id"])

    assert response.status_code == 200
    payload = response.json()
    assert payload["skippedTurnIds"] == []
    assert payload["filename"].startswith("vibelution-")
    assert payload["filename"].endswith(".html")
    html = payload["html"]
    assert "帮我总结一下要点" in html
    assert "第二答" in html
    # Two user-anchored turns, each carrying user + assistant bubbles.
    assert html.count('<div class="turn">') == 2
    assert html.count('<span class="role">用户</span>') == 2
    assert html.count('<span class="role">助手</span>') == 2
    assert "2026-01-02 10:30" in html
    # Inline markdown is reduced to markup, and the standalone document is complete.
    assert "<strong>加粗</strong>" in html
    assert "<code>code</code>" in html
    assert html.lstrip().startswith("<!doctype html>")
    assert "</html>" in html


def test_export_selected_turn_ids_skip_unknown(tmp_path, monkeypatch):
    session = _create_session(tmp_path, monkeypatch, "轮次选择")
    sid = session["id"]
    _seed_turn(sid, "turn-a", "user", "第一轮", "2026-01-02T10:00:00")
    _seed_turn(sid, "turn-a", "assistant", "答一", "2026-01-02T10:00:10")
    _seed_turn(sid, "turn-b", "user", "第二轮", "2026-01-02T10:05:00")
    _seed_turn(sid, "turn-b", "assistant", "答二", "2026-01-02T10:05:10")

    response = _export(session["id"], {"turnIds": ["turn-b", "ghost-turn"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["skippedTurnIds"] == ["ghost-turn"]
    html = payload["html"]
    assert "第二轮" in html
    assert "答二" in html
    assert "第一轮" not in html
    assert html.count('<div class="turn">') == 1


def test_export_neutralizes_script_onerror_and_javascript_links(tmp_path, monkeypatch):
    session = _create_session(tmp_path, monkeypatch, "转义安全")
    _seed_turn(
        session["id"],
        "turn-xss",
        "user",
        (
            "<script>alert(1)</script> <img src=x onerror=alert(2)> "
            '[坏链](javascript:alert(3)) [好链](https://example.com/a?b=1) '
            '"quoted" <b>raw</b>'
        ),
        "2026-01-02T10:00:00",
    )

    payload = _export(session["id"]).json()
    html = payload["html"]

    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=alert(2)&gt;" in html
    assert 'href="javascript:' not in html
    assert "javascript:alert(3)" not in html
    # Safe links render with the isolation attributes; quotes cannot break out.
    assert (
        '<a href="https://example.com/a?b=1" rel="noopener noreferrer" target="_blank">好链</a>' in html
    )
    assert "&quot;quoted&quot;" in html
    assert "&lt;b&gt;raw&lt;/b&gt;" in html


def test_export_renders_fenced_code_block_without_inline_transforms(tmp_path, monkeypatch):
    session = _create_session(tmp_path, monkeypatch, "围栏代码")
    _seed_turn(
        session["id"],
        "turn-1",
        "assistant",
        "前文\n```python\nx = **not bold** <img src=x>\n```\n后文",
        "2026-01-02T10:00:00",
    )

    html = _export(session["id"]).json()["html"]

    assert "<pre><code>x = **not bold** &lt;img src=x&gt;\n</code></pre>" in html
    assert "<p>前文</p>" in html
    assert "<p>后文</p>" in html


def test_export_embeds_image_attachment_and_lists_file_attachments(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    from core.web.services.session import export_html as export_html_service

    artifact_path = tmp_path / "artifacts" / "shot.png"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(_MINIMAL_PNG)

    def fake_resolve(session_id: str, artifact_id: str):
        if artifact_id == "ghost-image.png":
            raise FileNotFoundError("session artifact not found")
        return artifact_path, "image/png"

    monkeypatch.setattr(export_html_service, "resolve_session_image_artifact", fake_resolve)
    monkeypatch.setattr(
        export_html_service,
        "get_session_detail",
        lambda session_id, **kwargs: {
            "id": session_id,
            "title": "附件内嵌",
            "messages": [
                {
                    "id": f"{session_id}-message-1",
                    "role": "user",
                    "content": "看这张图和这份文件",
                    "timestamp": "2026-01-02T10:00:00",
                    "attachments": [
                        {
                            "artifactId": "real-image",
                            "filename": "shot.png",
                            "contentType": "image/png",
                            "sizeBytes": len(_MINIMAL_PNG),
                            "kind": "user_image",
                            "status": "ready",
                        },
                        {
                            "artifactId": "ghost-image.png",
                            "filename": "missing.png",
                            "contentType": "image/png",
                            "sizeBytes": 10,
                            "kind": "user_image",
                            "status": "ready",
                        },
                        {
                            "artifactId": "doc-1",
                            "filename": "notes.txt",
                            "contentType": "text/plain",
                            "sizeBytes": 4,
                            "kind": "user_document",
                            "status": "ready",
                        },
                    ],
                },
            ],
        },
    )

    result = export_html_service.export_session_html("attachment-session", include_attachments=True)
    html = result["html"]

    expected_data_uri = f"data:image/png;base64,{base64.b64encode(_MINIMAL_PNG).decode('ascii')}"
    assert expected_data_uri in html
    assert "[图片无法内嵌] missing.png" in html
    assert "[文件] notes.txt · 4 B" in html

    result_without = export_html_service.export_session_html("attachment-session", include_attachments=False)
    assert "base64," not in result_without["html"]
    assert "[图片未内嵌] shot.png" in result_without["html"]


def test_export_missing_session_returns_404(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(session_service, "_agent_lookup_for_conversations", lambda *args, **kwargs: {})

    assert _export("no-such-session").status_code == 404

    with pytest.raises(session_service.SessionNotFoundError):
        session_service.export_session_html("no-such-session")


def test_export_empty_session_renders_document_without_turns(tmp_path, monkeypatch):
    session = _create_session(tmp_path, monkeypatch, "空会话")

    payload = _export(session["id"]).json()

    assert payload["skippedTurnIds"] == []
    assert "没有可导出的轮次" in payload["html"]
    assert '<div class="turn">' not in payload["html"]


def test_export_payload_defaults_and_validation():
    payload = SessionExportHtmlPayload()
    assert payload.turnIds == []
    assert payload.includeAttachments is True

    payload = SessionExportHtmlPayload.model_validate({"turnIds": ["turn-1"], "includeAttachments": False, "extra": "ignored"})
    assert payload.turnIds == ["turn-1"]
    assert payload.includeAttachments is False
    assert not hasattr(payload, "extra")

    with pytest.raises(ValueError):
        SessionExportHtmlPayload.model_validate({"turnIds": "turn-1"})


def test_grouping_and_selection_cover_assistant_anchored_turns():
    from core.web.services.session.export_html import _group_messages_into_turns, _select_turns

    messages = [
        {"role": "assistant", "content": "开场", "id": "s-message-1", "turnId": "turn-open"},
        {"role": "user", "content": "问题", "id": "s-message-2"},
        {"role": "assistant", "content": "回答", "id": "s-message-3", "turnId": "turn-answer"},
        {"role": "user", "content": "还没回答的问题", "id": "s-message-4"},
    ]

    turns = _group_messages_into_turns(messages)
    assert [turn["turnId"] for turn in turns] == ["turn-open", "turn-answer", "s-message-4"]
    assert turns[1]["user"]["id"] == "s-message-2"
    assert turns[2]["assistant"] is None

    selected, skipped = _select_turns(turns, ["s-message-4", "turn-open", "nope", "nope"])
    assert [turn["turnId"] for turn in selected] == ["turn-open", "s-message-4"]
    assert skipped == ["nope"]

    all_turns, skipped = _select_turns(turns, [])
    assert len(all_turns) == 3
    assert skipped == []
