"""Isolated native Journal metadata inventory and branch-authority regressions."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.chat import turn_journal, turn_journal_inventory as inventory


@pytest.fixture
def journals(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    root.mkdir()
    monkeypatch.setattr(inventory, "_authority_snapshot", lambda project: (root, lambda: None))
    return root


def event(sid, tid, sequence, kind="turn_started", **values):
    return {"sessionId": sid, "turnId": tid, "sequence": sequence, "eventType": kind,
            "eventId": f"event-{sequence}", "payload": {"content": "SECRET body C:/private/path"}, **values}


def write(root, sid, events):
    path = turn_journal.turn_journal_path(root, sid, journal_workspace_root=root)
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in events))
    return path


def read(root, **kwargs):
    return inventory.read_turn_journal_inventory(root.parent, **kwargs)


def test_journal_only_open_turn_is_metadata_without_claiming_worker_liveness(journals, monkeypatch):
    path = write(journals, "session-a", [event("session-a", "turn-a", 1),
        event("session-a", "turn-a", 2, "user_message")])
    monkeypatch.setattr(turn_journal, "load_turn_events", lambda *args: pytest.fail("hydration"))
    monkeypatch.setattr(turn_journal, "turn_journal_workspace_root", lambda *args: pytest.fail("creating resolver"))
    before = {p: p.read_bytes() for p in journals.rglob("*") if p.is_file()}
    result = read(journals)
    assert result["complete"] is True and result["invalidCount"] == 0
    assert result["turns"] == [{"sessionId": "session-a", "turnId": "turn-a", "agentId": "",
        "status": "unknown", "stopRequested": False, "releasedToUser": False,
        "liveControl": False, "sources": ["journal"]}]
    assert "SECRET" not in json.dumps(result)
    assert before == {p: p.read_bytes() for p in journals.rglob("*") if p.is_file()}
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("terminal", ["turn_completed", "turn_failed", "turn_interrupted"])
def test_native_terminal_events_close_journal_turns(journals, terminal):
    write(journals, "session-a", [event("session-a", "turn-a", 1), event("session-a", "turn-a", 2, terminal)])
    assert read(journals)["turns"] == [] and read(journals)["complete"] is True


@pytest.mark.parametrize("operation,target,expected", [
    ("edit", "", ""), ("regenerate", "", ""), ("head_select", "event-2", "turn-a"),
    ("head_select", "unknown-event", "turn-b"),
])
def test_original_head_and_branch_selection_semantics_are_reused(journals, operation, target, expected, monkeypatch):
    rows = [event("session-a", "turn-a", 1), event("session-a", "turn-a", 2, "user_message"),
        event("session-a", "turn-b", 3, "branch_rebase", payload={"operation": "edit", "fromEventId": ""}),
        event("session-a", "turn-b", 4), event("session-a", "turn-b", 5, "user_message"),
        event("session-a", "turn-b", 6, "branch_rebase", payload={"operation": operation,
            "fromEventId": target, "branchId": "branch-a", "content": "SECRET"})]
    write(journals, "session-a", rows)
    original = turn_journal.latest_open_turn_id
    observed = []
    def native(events):
        observed.append(events)
        assert all(set(item.payload) <= {"operation", "fromEventId", "branchId"} for item in events)
        return original(events)
    monkeypatch.setattr(turn_journal, "latest_open_turn_id", native)
    result = read(journals)
    assert [item["turnId"] for item in result["turns"]] == ([expected] if expected else [])
    assert observed and result["complete"] is True


def test_terminal_on_superseded_branch_still_closes_selected_turn(journals):
    rows = [event("session-a", "turn-a", 1), event("session-a", "turn-a", 2, "user_message"),
        event("session-a", "turn-a", 3, "turn_completed"),
        event("session-a", "turn-b", 4, "branch_rebase", payload={"operation": "head_select", "fromEventId": "event-2"})]
    write(journals, "session-a", rows)
    assert read(journals)["turns"] == []


@pytest.mark.parametrize("tail", [b'{broken}\n', b'{"eventType":"turn_completed"}',
                                   b'{"eventId":"a","eventId":"b"}\n'])
def test_corrupt_or_partial_tail_never_turns_a_prefix_into_open_truth(journals, tail):
    path = write(journals, "session-a", [event("session-a", "turn-a", 1)])
    with path.open("ab") as stream:
        stream.write(tail)
    write(journals, "healthy", [event("healthy", "turn-healthy", 1)])
    result = read(journals)
    assert [item["turnId"] for item in result["turns"]] == ["turn-healthy"]
    assert result["complete"] is False and result["invalidCount"] == 1
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("budget", [{"max_bytes": 1}, {"max_lines": 1}, {"max_line_bytes": 32}])
def test_byte_line_and_record_budgets_never_publish_partial_journal_truth(journals, budget):
    write(journals, "session-a", [event("session-a", "turn-a", 1), event("session-a", "turn-a", 2, "turn_completed")])
    result = read(journals, **budget)
    assert result["turns"] == [] and result["truncated"] is True and result["complete"] is False


def test_directory_budget_is_explicit_and_total_reads_include_verification(journals, monkeypatch):
    for number in range(3):
        write(journals, f"session-{number}", [event(f"session-{number}", f"turn-{number}", 1)])
    original, consumed = inventory.read_stable_file, []
    def measured(*args, **kwargs):
        result = original(*args, **kwargs)
        consumed.append(len(result.raw))
        return result
    monkeypatch.setattr(inventory, "read_stable_file", measured)
    result = read(journals, max_directories=1, max_bytes=2048)
    assert len(result["turns"]) == 1 and result["truncated"] is True
    assert len(consumed) == 2 and sum(consumed) <= 2048


@pytest.mark.parametrize("exact", [False, True])
def test_total_byte_budget_stops_namespace_scan_and_verifies_accepted_facts(journals, monkeypatch, exact):
    accepted = write(journals, "session-a", [event("session-a", "turn-a", 1)])
    overflow = write(journals, "session-b", [event("session-b", "turn-b", 1)])
    original_iterdir, original_read = Path.iterdir, inventory.read_stable_file
    budget = accepted.stat().st_size * 2 + (0 if exact else overflow.stat().st_size * 2 - 1)
    consumed = []

    def bounded_entries(path):
        if path != journals:
            yield from original_iterdir(path)
            return
        yield accepted.parent
        yield overflow.parent
        pytest.fail("traversed the namespace after exhausting the source byte budget")

    def measured(*args, **kwargs):
        snapshot = original_read(*args, **kwargs)
        consumed.append((args[0], len(snapshot.raw)))
        return snapshot

    monkeypatch.setattr(Path, "iterdir", bounded_entries)
    monkeypatch.setattr(inventory, "read_stable_file", measured)
    result = read(journals, max_bytes=budget)
    assert [item["turnId"] for item in result["turns"]] == ["turn-a"]
    assert result["truncated"] is True and result["complete"] is False
    assert result["reason"] == "budget_exceeded" and result["invalidCount"] == 0
    assert [path for path, _ in consumed] == [accepted, accepted]
    assert sum(size for _, size in consumed) <= budget
    assert "SECRET" not in json.dumps(result)


def test_oversized_single_journal_does_not_hide_later_healthy_sibling(journals, monkeypatch):
    oversized = write(journals, "large", [event("large", "turn-large", 1, payload={"content": "x" * 2048})])
    healthy = write(journals, "healthy", [event("healthy", "turn-healthy", 1)])
    monkeypatch.setattr(inventory, "MAX_FILE_BYTES", healthy.stat().st_size)
    original_iterdir = Path.iterdir
    monkeypatch.setattr(Path, "iterdir", lambda path: iter([oversized.parent, healthy.parent])
                        if path == journals else original_iterdir(path))
    result = read(journals)
    assert [item["turnId"] for item in result["turns"]] == ["turn-healthy"]
    assert result["complete"] is False and result["truncated"] is True
    assert result["invalidCount"] == 0


def test_source_changes_before_verification_discard_affected_journal(journals, monkeypatch):
    path = write(journals, "session-a", [event("session-a", "turn-a", 1)])
    original, count = inventory.read_stable_file, 0
    def changed(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            path.write_bytes(path.read_bytes() + json.dumps(event("session-a", "turn-a", 2, "turn_completed")).encode() + b"\n")
        return original(*args, **kwargs)
    monkeypatch.setattr(inventory, "read_stable_file", changed)
    result = read(journals)
    assert result["turns"] == [] and result["reason"] == "source_changed" and result["complete"] is False


def test_linked_and_misbound_journals_are_not_followed(journals, tmp_path):
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(json.dumps(event("linked", "turn-a", 1)).encode() + b"\n")
    folder = journals / "linked"
    folder.mkdir()
    try:
        os.link(outside, folder / "turn_journal.jsonl")
    except OSError:
        pytest.skip("hardlinks are unavailable on this filesystem")
    write(journals, "wrong-folder", [event("different-session", "turn-other", 1)])
    result = read(journals)
    assert result["turns"] == [] and result["invalidCount"] == 2


def test_symlinked_session_directory_is_rejected_without_reading_target(journals, tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (journals / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this filesystem")
    monkeypatch.setattr(inventory, "read_stable_file", lambda *args, **kwargs: pytest.fail("followed linked source"))
    result = read(journals)
    assert result["turns"] == [] and result["invalidCount"] == 1 and result["complete"] is False


def test_growth_before_initial_open_is_rejected_before_read_budget_can_expand(journals, monkeypatch):
    path = write(journals, "session-a", [event("session-a", "turn-a", 1)])
    original = inventory.read_stable_file
    def grow(*args, **kwargs):
        path.write_bytes(path.read_bytes() + b" " * 2048)
        return original(*args, **kwargs)
    monkeypatch.setattr(inventory, "read_stable_file", grow)
    result = read(journals, max_bytes=1024)
    assert result["turns"] == [] and result["reason"] == "source_changed"


def test_directory_changes_discard_the_non_atomic_scan(journals, monkeypatch):
    write(journals, "session-a", [event("session-a", "turn-a", 1)])
    original, changed = inventory.read_stable_file, False
    def add_directory(*args, **kwargs):
        nonlocal changed
        result = original(*args, **kwargs)
        if not changed:
            changed = True
            (journals / "new-session").mkdir()
        return result
    monkeypatch.setattr(inventory, "read_stable_file", add_directory)
    result = read(journals)
    assert result["turns"] == [] and result["reason"] == "source_changed"


def test_existing_authority_resolution_does_not_ensure_or_create_state(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    sessions = workspace / "sessions"
    sessions.mkdir(parents=True)
    config = tmp_path / "existing.toml"
    config.write_text("[launcher.developer_mode]\nenabled = false\n", encoding="utf-8")
    monkeypatch.setattr(inventory.developer_sandbox, "CONFIG_PATH", config)
    monkeypatch.setattr(inventory.developer_sandbox, "workspace_routing_fingerprint", lambda root: ("existing",))
    monkeypatch.setattr(inventory.developer_sandbox, "_active_state_path", lambda root: tmp_path / "missing-active.json")
    monkeypatch.setattr(inventory.developer_sandbox, "formal_workspace_path", lambda root, *parts: workspace.joinpath(*parts))
    monkeypatch.setattr(inventory.developer_sandbox, "sandbox_root", lambda *args, **kwargs: pytest.fail("ensure"))
    before = sorted(str(path) for path in tmp_path.rglob("*"))
    result = inventory.read_turn_journal_inventory(tmp_path)
    assert result["complete"] is True and result["turns"] == []
    assert before == sorted(str(path) for path in tmp_path.rglob("*"))
    write(sessions, "session-a", [event("session-a", "turn-a", 1)])
    original, changed = inventory.read_stable_file, False
    def change_routing(*args, **kwargs):
        nonlocal changed
        snapshot = original(*args, **kwargs)
        if not changed:
            changed = True
            config.write_text(config.read_text(encoding="utf-8") + "\n# routing changed\n", encoding="utf-8")
        return snapshot
    monkeypatch.setattr(inventory, "read_stable_file", change_routing)
    changed_result = inventory.read_turn_journal_inventory(tmp_path)
    assert changed_result["turns"] == [] and changed_result["reason"] == "source_changed"
    config.unlink()
    assert inventory.read_turn_journal_inventory(tmp_path)["unavailable"] is True
    assert not config.exists()


def test_native_inventory_includes_journal_only_turn_without_control(journals, monkeypatch):
    from core.web.services.session import runtime_inventory
    write(journals, "session-a", [event("session-a", "turn-a", 1)])
    owner = SimpleNamespace(PROJECT_ROOT=journals.parent, _RUNNING_SESSIONS_LOCK=threading.Lock(),
        _RUNNING_SESSION_IDS=set(), _SESSION_ACTIVE_TURN_IDS={}, _SESSION_TURN_CONTROLS_LOCK=threading.Lock(),
        _SESSION_TURN_CONTROLS={}, _SESSION_TURN_SCHEDULER=SimpleNamespace(snapshot_queued_turn_metadata=lambda **kw:
            {"entries": [], "invalidCount": 0, "truncated": False, "pendingAdmissionCount": 0, "externalReservationCount": 0}))
    monkeypatch.setattr(runtime_inventory, "_service", lambda: owner)
    monkeypatch.setattr(runtime_inventory, "_queued_rows", lambda *args, **kw: ([], runtime_inventory._coverage("persisted_queue")))
    result = runtime_inventory.read_session_runtime_inventory(journals.parent)
    assert [item["turnId"] for item in result["turns"]] == ["turn-a"]
    assert next(item for item in result["sourceCoverage"] if item["source"] == "journal")["complete"] is True
    assert result["complete"] is False and result["consistency"] == "non_atomic"
