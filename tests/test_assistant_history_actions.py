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
    assert str(tmp_path) not in json.dumps(listing)
    result = actions.execute("history_read", {"history_id": hid})
    assert "PRIVATE_PROMPT" in result["text"]
    assert result["readOnly"] and result["untrustedContent"] and not result["canContinue"]
    assert str(tmp_path) not in json.dumps(result)
    assert all(key not in result for key in ("sourceBody", "events", "path", "projectRoot"))


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
