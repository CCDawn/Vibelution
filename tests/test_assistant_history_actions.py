"""Imported history is native-profile scoped, read-only and model-budget bounded."""
import json

import pytest

from core.assistant_runtime import history_actions as actions
from core.assistant_runtime import migration_history as history
from tests.test_assistant_migration_history import discover, source


def imported(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "import-1")
    monkeypatch.setattr(actions, "assistant_native_root", lambda: target)
    return actions.execute("history_list", {})["histories"][0]["historyId"]


def test_import_is_readable_through_closed_native_history_actions(tmp_path, monkeypatch):
    hid = imported(tmp_path, monkeypatch)
    listing = actions.execute("history_list", {})
    assert listing["total"] == 1 and listing["nextOffset"] is None
    assert listing["partial"] is False and listing["conflictCount"] == 0 and listing["unavailableArchiveCount"] == 0
    assert str(tmp_path) not in json.dumps(listing)
    result = actions.execute("history_read", {"history_id": hid})
    assert "PRIVATE_PROMPT" in result["text"]
    assert result["readOnly"] and result["untrustedContent"] and not result["canContinue"]
    assert str(tmp_path) not in json.dumps(result)
    assert all(key not in result for key in ("sourceBody", "events", "path", "projectRoot"))


def test_listing_discloses_conflicts_without_blocking_other_history(tmp_path, monkeypatch):
    workspace = source(tmp_path, [{"id": "direct", "agent_id": "agent-pa"},
                                  {"id": "other", "agent_id": "agent-pa"}])
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    journal = workspace / "sessions/direct/turn_journal.jsonl"
    journal.write_bytes(journal.read_bytes().replace(b"answer", b"edited"))
    with monkeypatch.context() as patch:
        # Recreate a legacy v2 import that predates both chain guards.
        patch.setattr(history, "_validate_history_extension", lambda *args, **kwargs: None)
        patch.setattr(history, "_incremental_manifest", lambda root, manifest, copies, **kwargs: (manifest, copies))
        history.import_history(discover(workspace), target, "two")
    monkeypatch.setattr(actions, "assistant_native_root", lambda: target)
    result = actions.execute("history_list", {})
    assert result["partial"] is True and result["conflictCount"] == 1 and result["total"] == 1
    assert result["histories"][0]["sessionId"] == "other"
    assert str(tmp_path) not in json.dumps(result) and "PRIVATE_PROMPT" not in json.dumps(result)
    search = actions.execute("history_search", {"query": "PRIVATE_PROMPT"})
    assert search["partial"] and search["conflictCount"] == 1
    assert len(search["matches"]) == 1 and search["nextCursor"] is None


def test_listing_reports_unavailable_v3_and_returns_independent_history(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    other = source(tmp_path / "other")
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    history.import_history(discover(other), target, "other")
    from tests.test_assistant_migration_history import append_turn
    append_turn(workspace, "direct")
    history.import_history(discover(workspace), target, "two")
    path = target / "history_archive/migrations/two/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["histories"][0]["base"] = None
    path.write_bytes(history._encoded(manifest))
    monkeypatch.setattr(actions, "assistant_native_root", lambda: target)
    result = actions.execute("history_list", {})
    assert result["partial"] and result["conflictCount"] == 1 and result["unavailableArchiveCount"] == 1
    assert result["total"] == 1 and result["histories"][0]["sourceScope"]["projectId"] == "project-1"
    assert "PRIVATE_PROMPT" in actions.execute("history_read", {"history_id": result["histories"][0]["historyId"]})["text"]
    assert str(tmp_path) not in json.dumps(result) and "PRIVATE_PROMPT" not in json.dumps(result)


def test_chunks_reconstruct_the_requested_original_message_without_loss(tmp_path, monkeypatch):
    hid = imported(tmp_path, monkeypatch)
    offset, parts = 0, []
    while True:
        result = actions.execute("history_read", {"history_id": hid, "character_offset": offset, "max_characters": 7})
        parts.append(result["text"])
        offset = result["nextCharacterOffset"]
        if offset is None:
            break
    decoded = json.loads("".join(parts))
    assert decoded["content"] == "PRIVATE_PROMPT"


@pytest.mark.parametrize("action,args", [("history_read", {"history_id": "../other"}),
    ("history_list", {"path": "C:/private"}), ("history_read", {"history_id": "a" * 64, "force": True}),
    ("history_list", {"offset": True}), ("history_list", {"limit": 13})])
def test_bad_or_path_parameters_never_enter_archive_read(monkeypatch, action, args):
    monkeypatch.setattr(history, "list_history", lambda *_: pytest.fail("unexpected archive read"))
    monkeypatch.setattr(history, "history_detail", lambda *_: pytest.fail("unexpected archive read"))
    with pytest.raises(ValueError):
        actions.execute(action, args)


def test_ordinary_process_cannot_read_imported_history(monkeypatch):
    def not_assistant():
        raise RuntimeError("ordinary process")
    monkeypatch.setattr(actions, "assistant_native_root", not_assistant)
    monkeypatch.setattr(history, "list_history", lambda *_: pytest.fail("unexpected archive read"))
    with pytest.raises(ValueError):
        actions.execute("history_list", {})


def test_invalid_history_list_limit_reports_usable_bound_without_echoing_input(monkeypatch):
    monkeypatch.setattr(history, "list_history", lambda *_: pytest.fail("unexpected archive read"))
    with pytest.raises(ValueError, match="limit为1至12") as error:
        actions.execute("history_list", {"limit": 50, "path": "C:/private"})
    assert "C:/private" not in str(error.value)


def test_navigation_and_escaped_text_remain_inside_native_model_budget(tmp_path, monkeypatch):
    hid = imported(tmp_path, monkeypatch)
    detail = history.history_detail(tmp_path / "target", hid)
    detail["messages"] = [{"role": "user", "content": "\x00" * 10000}]
    monkeypatch.setattr(history, "history_detail", lambda *_: detail)
    result = actions.execute("history_read", {"history_id": hid, "max_characters": 1600})
    assert len(json.dumps(result, ensure_ascii=False)) <= 3300
    assert result["nextCharacterOffset"] > 0


def test_empty_and_unknown_archive_return_bounded_unavailable(tmp_path, monkeypatch):
    target = tmp_path / "empty"
    target.mkdir()
    monkeypatch.setattr(actions, "assistant_native_root", lambda: target)
    assert actions.execute("history_list", {})["total"] == 0
    result = actions.execute("history_read", {"history_id": "a" * 64})
    assert result["status"] == "unavailable" and result["error"] == "history_not_found"


def test_search_finds_visible_text_and_read_uses_returned_index(tmp_path, monkeypatch):
    hid = imported(tmp_path, monkeypatch)
    result = actions.execute("history_search", {"query": "  private_prompt  "})
    match, = result["matches"]
    assert {key: match[key] for key in ("historyId", "messageIndex", "role")} == {
        "historyId": hid, "messageIndex": 0, "role": "user"}
    assert len(match["journalSha256"]) == 64
    assert result["nextCursor"] is None and not result["partial"]
    assert result["readOnly"] and result["untrustedContent"] and not result["scanLimited"]
    assert "PRIVATE_PROMPT" not in json.dumps(result) and str(tmp_path) not in json.dumps(result)
    assert "PRIVATE_PROMPT" in actions.execute("history_read", {"history_id": hid,
        "message_index": match["messageIndex"], "journal_sha256": match["journalSha256"]})["text"]
    assert actions.execute("history_search", {"query": "private.png"})["matches"] == []
    assert actions.execute("history_search", {"query": "answer"})["matches"][0]["role"] == "assistant"


def test_search_paging_binds_query_and_archive_snapshot(tmp_path, monkeypatch):
    workspace = source(tmp_path, [{"id": "direct", "agent_id": "agent-pa"},
                                  {"id": "other", "agent_id": "agent-pa"}])
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    monkeypatch.setattr(actions, "assistant_native_root", lambda: target)
    first = actions.execute("history_search", {"query": "PRIVATE_PROMPT", "limit": 1})
    cursor = first["nextCursor"]
    second = actions.execute("history_search", {"query": " private_prompt ", "limit": 1, "cursor": cursor})
    assert len(first["matches"]) == len(second["matches"]) == 1
    assert first["matches"][0] != second["matches"][0] and second["nextCursor"] is None
    invalid = actions.execute("history_search", {"query": "answer", "cursor": cursor})
    assert invalid["error"] == "history_search_cursor_invalidated"
    from tests.test_assistant_migration_history import append_turn
    append_turn(workspace, "direct")
    history.import_history(discover(workspace), target, "two")
    changed = actions.execute("history_search", {"query": "private_prompt", "cursor": cursor})
    assert changed["error"] == "history_search_cursor_invalidated"


def test_search_limits_and_invalid_parameters_do_not_echo(monkeypatch, tmp_path):
    imported(tmp_path, monkeypatch)
    for args in ({"query": " "}, {"query": "\ud800"}, {"query": "SECRET", "path": "C:/private"},
                 {"query": "SECRET", "limit": 13}, {"query": "SECRET", "cursor": "invalid"}):
        try:
            result = actions.execute("history_search", args)
            assert result["status"] == "unavailable"
            output = json.dumps(result)
        except ValueError as error:
            output = str(error)
        assert "SECRET" not in output and "C:/private" not in output
    original = history.project_conversation_ledger
    def large_projection(*args, **kwargs):
        if kwargs.get("include_visible_messages"):
            return type("Projection", (), {"visible_messages": [{"role": "user", "content": "x" * 2000001, "metadata": {"kind": "journal_user_message", "eventId": "direct-e2"}}]})()
        return original(*args, **kwargs)
    monkeypatch.setattr(history, "project_conversation_ledger", large_projection)
    result = actions.execute("history_search", {"query": "x"})
    assert result["partial"] and result["scanLimited"] and not result["matches"]


def test_search_native_catalog_dispatch_and_ignores_non_message_data(tmp_path, monkeypatch):
    from core.assistant_runtime import local_actions
    from core.assistant_runtime.actions import _index_page
    imported(tmp_path, monkeypatch)
    contracts = local_actions.contracts()
    page = _index_page({"query": "关键词"}, {}, contracts, {})
    assert "history_search" in {item["action"] for item in page["actions"]}
    original = history.project_conversation_ledger
    def projection(*args, **kwargs):
        if kwargs.get("include_visible_messages"):
            return type("Projection", (), {"visible_messages": [
                {"role": "tool", "content": "SECRET_TOOL"},
                {"role": "user", "content": "hello", "attachments": [{"path": "SECRET_PATH"}],
                 "metadata": {"kind": "journal_user_message", "eventId": "direct-e2", "text": "SECRET_METADATA"}},
            ]})()
        return original(*args, **kwargs)
    monkeypatch.setattr(history, "project_conversation_ledger", projection)
    for query in ("SECRET_TOOL", "SECRET_PATH", "SECRET_METADATA"):
        assert local_actions.execute("history_search", {"query": query}, {})["matches"] == []
    result = local_actions.execute("history_search", {"query": "hello"}, {})
    assert result["matches"][0]["messageIndex"] == 1


def test_search_archive_budget_failure_is_explicit(tmp_path, monkeypatch):
    imported(tmp_path, monkeypatch)
    original = history._select_history_versions
    def limited(root, budget, **kwargs):
        budget.bytes_left = 1
        return original(root, budget, **kwargs)
    monkeypatch.setattr(history, "_select_history_versions", limited)
    result = actions.execute("history_search", {"query": "PRIVATE_PROMPT"})
    assert result["error"] == "history_archive_limit"
    assert result["partial"] and result["scanLimited"] and result["readOnly"]
    assert "PRIVATE_PROMPT" not in json.dumps(result)


def test_search_binding_rejects_after_edit_branch_replaces_message(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    monkeypatch.setattr(actions, "assistant_native_root", lambda: target)
    match, = actions.execute("history_search", {"query": "PRIVATE_PROMPT"})["matches"]
    read_args = {"history_id": match["historyId"], "message_index": match["messageIndex"],
                 "journal_sha256": match["journalSha256"]}
    assert "PRIVATE_PROMPT" in actions.execute("history_read", read_args)["text"]
    path = workspace / "sessions/direct/turn_journal.jsonl"
    events = [("branch_rebase", {"operation": "edit", "branchId": "branch-new", "fromEventId": ""}),
              ("turn_started", {}), ("user_message", {"content": "changed request"}),
              ("assistant_message", {"content": "changed response"}), ("turn_completed", {})]
    with path.open("a", encoding="utf-8") as stream:
        for seq, (kind, payload) in enumerate(events, 5):
            stream.write(json.dumps({"eventId": f"edit-{seq}", "sessionId": "direct", "turnId": "turn-2",
                "sequence": seq, "eventType": kind, "payload": payload}) + "\n")
    history.import_history(discover(workspace), target, "two")
    stale = actions.execute("history_read", read_args)
    assert stale["error"] == "history_version_changed" and "text" not in stale
    assert "changed request" in actions.execute("history_read", {"history_id": match["historyId"]})["text"]
    fresh, = actions.execute("history_search", {"query": "changed request"})["matches"]
    assert fresh["journalSha256"] != match["journalSha256"]
    result = actions.execute("history_read", {"history_id": fresh["historyId"],
        "message_index": fresh["messageIndex"], "journal_sha256": fresh["journalSha256"]})
    assert "changed request" in result["text"] and result["journalSha256"] == fresh["journalSha256"]


def test_real_multimodal_events_expose_only_explicit_text_parts(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    path = workspace / "sessions/direct/turn_journal.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[1]["payload"]["content"] = [
        {"type": "text", "text": "visible user words"},
        {"type": "image_url", "image_url": {"url": "file:///SECRET_PATH"}},
        {"type": "file", "path": "SECRET_FILE"},
        {"type": "unknown", "text": "SECRET_UNKNOWN"},
        {"type": {}, "text": "SECRET_INVALID"}]
    rows[2]["payload"]["content"] = [
        {"type": "output_text", "text": "visible assistant words"},
        {"type": "image_url", "image_url": {"url": "SECRET_IMAGE"}}]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    monkeypatch.setattr(actions, "assistant_native_root", lambda: target)
    for role, query in (("user", "visible user words"), ("assistant", "visible assistant words")):
        match, = actions.execute("history_search", {"query": query})["matches"]
        assert match["role"] == role
        result = actions.execute("history_read", {"history_id": match["historyId"],
            "message_index": match["messageIndex"], "journal_sha256": match["journalSha256"]})
        assert query in result["text"] and "SECRET_" not in result["text"]
    for query in ("SECRET_PATH", "SECRET_FILE", "SECRET_UNKNOWN", "SECRET_INVALID", "SECRET_IMAGE"):
        assert actions.execute("history_search", {"query": query})["matches"] == []


def test_bound_read_uses_the_same_selected_bytes_when_archive_changes_during_read(tmp_path, monkeypatch):
    from tests.test_assistant_migration_history import append_turn
    workspace = source(tmp_path)
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    monkeypatch.setattr(actions, "assistant_native_root", lambda: target)
    match, = actions.execute("history_search", {"query": "PRIVATE_PROMPT"})["matches"]
    original = history._select_history_versions
    def selected_then_append(*args, **kwargs):
        selected = original(*args, **kwargs)
        monkeypatch.setattr(history, "_select_history_versions", original)
        append_turn(workspace, "direct")
        history.import_history(discover(workspace), target, "two")
        return selected
    monkeypatch.setattr(history, "_select_history_versions", selected_then_append)
    args = {"history_id": match["historyId"], "message_index": match["messageIndex"],
            "journal_sha256": match["journalSha256"]}
    first = actions.execute("history_read", args)
    assert "PRIVATE_PROMPT" in first["text"] and first["journalSha256"] == match["journalSha256"]
    assert actions.execute("history_read", args)["error"] == "history_version_changed"


def test_real_tool_lifecycle_is_not_searchable_or_exposed_as_message_text(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    path = workspace / "sessions/direct/turn_journal.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[-1]["sequence"] = 5
    rows.insert(3, {"eventId": "tool-lifecycle", "sessionId": "direct", "turnId": "turn-1",
                    "sequence": 4, "eventType": "cli_session_lifecycle",
                    "payload": {"lifecycle": {"event": "linked", "label": {"path": "SECRET_TOOL_PATH"}}}})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    monkeypatch.setattr(actions, "assistant_native_root", lambda: target)
    assert not actions.execute("history_search", {"query": "SECRET_TOOL_PATH"})["matches"]
    hid = actions.execute("history_list", {})["histories"][0]["historyId"]
    detail = history.history_detail(target, hid)
    for index in range(len(detail["messages"])):
        result = actions.execute("history_read", {"history_id": hid, "message_index": index})
        assert "SECRET_TOOL_PATH" not in json.dumps(result)


def test_search_maximum_page_stays_inside_model_output_budget(tmp_path, monkeypatch):
    rows = [{"id": "direct", "agent_id": "agent-pa"}] + [
        {"id": f"session-{i}", "agent_id": "agent-pa"} for i in range(11)]
    workspace = source(tmp_path, rows)
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    monkeypatch.setattr(actions, "assistant_native_root", lambda: target)
    result = actions.execute("history_search", {"query": "PRIVATE_PROMPT", "limit": 12})
    assert len(result["matches"]) == 12 and len(json.dumps(result, ensure_ascii=False)) <= 3300


def test_real_guidance_events_keep_text_and_derive_source_from_journal(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    path = workspace / "sessions/direct/turn_journal.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[2]["sequence"] = 6
    rows[3]["sequence"] = 7
    for sequence, kind, content in ((3, "user_guidance", "GUIDANCE_WORDS"),
                                    (4, "user_interrupt_guidance", "INTERRUPT_WORDS")):
        rows.insert(sequence - 1, {"eventId": f"guidance-{sequence}", "sessionId": "direct",
            "turnId": "turn-1", "sequence": sequence, "eventType": "user_message",
            "payload": {"content": content, "metadata": {"kind": kind, "eventId": "tool-lifecycle"}}})
    rows.insert(4, {"eventId": "tool-lifecycle", "sessionId": "direct", "turnId": "turn-1",
                    "sequence": 5, "eventType": "cli_session_lifecycle",
                    "payload": {"lifecycle": {"event": "linked", "label": "SECRET_TOOL_TEXT"}}})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    monkeypatch.setattr(actions, "assistant_native_root", lambda: target)
    for index, query in ((1, "GUIDANCE_WORDS"), (2, "INTERRUPT_WORDS")):
        result = actions.execute("history_search", {"query": query})
        match, = result["matches"]
        assert match["role"] == "user" and match["messageIndex"] == index
        assert "excludes timeline-only" in result["searchScope"]
        read = actions.execute("history_read", {"history_id": match["historyId"],
            "message_index": match["messageIndex"], "journal_sha256": match["journalSha256"]})
        assert query in read["text"]
    assert actions.execute("history_search", {"query": "SECRET_TOOL_TEXT"})["matches"] == []


def test_search_scope_excludes_timeline_only_commentary_and_partial_delta(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    path = workspace / "sessions/direct/turn_journal.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[2]["sequence"] = 5
    rows[3]["sequence"] = 6
    rows.insert(2, {"eventId": "commentary", "sessionId": "direct", "turnId": "turn-1",
                    "sequence": 3, "eventType": "assistant_item_committed",
                    "payload": {"kind": "assistant_message", "channel": "commentary",
                                "phase": "commentary", "text": "COMMENTARY_TEXT"}})
    rows.insert(3, {"eventId": "partial", "sessionId": "direct", "turnId": "turn-1",
                    "sequence": 4, "eventType": "assistant_partial",
                    "payload": {"content": "PARTIAL_TEXT"}})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    target = tmp_path / "target"
    history.import_history(discover(workspace), target, "one")
    monkeypatch.setattr(actions, "assistant_native_root", lambda: target)
    for query in ("COMMENTARY_TEXT", "PARTIAL_TEXT"):
        result = actions.execute("history_search", {"query": query})
        assert result["matches"] == [] and "excludes timeline-only" in result["searchScope"]
    assert actions.execute("history_search", {"query": "answer"})["matches"][0]["role"] == "assistant"
