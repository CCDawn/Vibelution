"""Body-enabled session search: snippet derivation and bounded journal scans.

Message bodies stay in per-session workspace journals (never in the SQLite
control plane), so the scan helpers here are the searchable-body authority
for the session list query path.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.web.services.session import session_body_search


def _long_text(fill: str, keyword: str, repeats: int) -> str:
    return " ".join(f"{fill}{index}" for index in range(repeats)) + f" {keyword} tail"


def test_build_search_snippets_returns_at_most_four_match_centered_windows():
    text = _long_text("filler", "needle", 1) + (" more filler " * 40) + " needle again " + ("tail " * 80)
    snippets = session_body_search.build_search_snippets(text, "needle")
    assert 2 <= len(snippets) <= session_body_search.MAX_SEARCH_SNIPPETS
    for snippet in snippets:
        assert "needle" in snippet
        assert len(snippet) <= 200


def test_build_search_snippets_merges_overlapping_windows():
    text = "needle needle needle " + ("filler " * 200)
    snippets = session_body_search.build_search_snippets(text, "needle")
    # Adjacent hits inside one window must not produce four near-duplicates.
    assert len(snippets) == 1
    assert snippets[0].startswith("needle")


def test_build_search_snippets_empty_inputs():
    assert session_body_search.build_search_snippets("", "query") == []
    assert session_body_search.build_search_snippets("text", "") == []
    assert session_body_search.build_search_snippets("   ", "query") == []


def test_searchable_text_extracts_content_and_thought_fields():
    record = {
        "event": "user_message",
        "content": "讨论 renderPipeline 的缓存策略",
        "thought": "",
        "payload": {"content": "nested", "trace": "never"},
    }
    text = session_body_search.searchable_text_from_journal_record(record)
    assert "讨论 renderPipeline 的缓存策略" in text
    assert "nested" in text
    assert "never" not in text


def test_searchable_text_ignores_non_text_records():
    assert session_body_search.searchable_text_from_journal_record(None) == ""
    assert session_body_search.searchable_text_from_journal_record({"status": "ok"}) == ""
    assert session_body_search.searchable_text_from_journal_record(["list"]) == ""


def _write_journal(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def test_search_session_bodies_matches_logs_and_journal(tmp_path: Path):
    workspace = tmp_path / "session-1"
    _write_journal(
        workspace / "logs" / "conversation.jsonl",
        [
            {"role": "user", "content": "请帮我评估量子退相干的影响", "event": "user_message"},
            {"role": "assistant", "content": "好的，我们从退相干时间开始。", "event": "assistant_message"},
        ],
    )
    _write_journal(
        workspace / "turn_journal.jsonl",
        [
            {"eventType": "user_message", "payload": {"content": "另一条不相关消息"}},
            {"eventType": "assistant_message", "payload": {"content": "量子纠错需要表面码。"}},
        ],
    )
    (tmp_path / "session-empty").mkdir()
    matches = session_body_search.search_session_bodies(
        query="量子",
        session_ids=["session-1", "session-empty", "session-missing"],
        workspace_resolver=lambda session_id: tmp_path / session_id
        if (tmp_path / session_id).exists()
        else None,
    )
    assert set(matches) == {"session-1"}
    snippets = matches["session-1"]
    assert 1 <= len(snippets) <= session_body_search.MAX_SEARCH_SNIPPETS
    assert any("量子" in snippet for snippet in snippets)


def test_search_session_bodies_no_match_returns_empty(tmp_path: Path):
    workspace = tmp_path / "session-1"
    _write_journal(
        workspace / "logs" / "conversation.jsonl",
        [{"role": "user", "content": "完全无关的讨论"}],
    )
    matches = session_body_search.search_session_bodies(
        query="量子",
        session_ids=["session-1"],
        workspace_resolver=lambda session_id: tmp_path / session_id,
    )
    assert matches == {}


def test_search_session_bodies_caps_session_scans(tmp_path: Path, monkeypatch):
    scanned: list[str] = []

    def resolver(session_id: str) -> Path | None:
        scanned.append(session_id)
        workspace = tmp_path / session_id
        _write_journal(
            workspace / "logs" / "conversation.jsonl",
            [{"role": "user", "content": f"命中 {session_id} 目标词"}],
        )
        return workspace

    session_ids = [f"session-{index}" for index in range(10)]
    monkeypatch.setattr(session_body_search, "MAX_BODY_SEARCH_SESSIONS", 3)
    matches = session_body_search.search_session_bodies(
        query="目标词",
        session_ids=session_ids,
        workspace_resolver=resolver,
    )
    assert len(scanned) == 3
    assert set(matches) == set(session_ids[:3])


def test_search_session_bodies_bounds_tail_window(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "session-1"
    # One giant record above the per-file cap, then the match at the very end.
    _write_journal(
        workspace / "logs" / "conversation.jsonl",
        [
            {"role": "user", "content": "x" * (session_body_search.MAX_SCAN_BYTES_PER_FILE + 4096)},
            {"role": "user", "content": "结尾出现的独特关键词"},
        ],
    )
    monkeypatch.setattr(session_body_search, "MAX_SCAN_BYTES_PER_FILE", 4096)
    matches = session_body_search.search_session_bodies(
        query="独特关键词",
        session_ids=["session-1"],
        workspace_resolver=lambda session_id: tmp_path / session_id,
    )
    assert set(matches) == {"session-1"}
