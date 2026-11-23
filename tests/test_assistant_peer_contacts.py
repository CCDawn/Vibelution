"""Private peer envelopes preserve exact ownership in both directions."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from core.assistant_runtime.peer_contacts import PeerContactError, PeerContacts


@pytest.fixture
def store(tmp_path, monkeypatch):
    from core.infrastructure import native_runtime
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    return PeerContacts(tmp_path / "profile")


def fails(code, operation):
    with pytest.raises(PeerContactError) as error:
        operation()
    assert error.value.code == code
    assert str(error.value) == code


def test_bidirectional_conversations_survive_restart_and_ack(store):
    bearer = store.enroll("codex", "codex")
    assert store.peers() == [{"peerId": "codex", "platform": "codex"}]
    assert store.describe("codex", bearer)["authorized"] is True
    sent = store.exchange("codex", bearer, "send", "q1", "question")
    assert sent == {"peerId": "codex", "requestId": "q1", "direction": "peer_to_assistant",
                    "state": "queued", "content": "question"}
    assert store.exchange("codex", bearer, "inbox")["messages"] == []
    assert store.assistant_exchange("codex", "inbox")["messages"] == [sent]
    reply = store.assistant_exchange("codex", "reply", "q1", "answer")
    assert reply["state"] == "reply_ready" and reply["reply"] == "answer"
    reopened = PeerContacts(store.root.parent)
    assert reopened.exchange("codex", bearer, "inbox")["messages"] == [reply]
    assert reopened.exchange("codex", bearer, "ack", "q1")["state"] == "acknowledged"
    assert reopened.exchange("codex", bearer, "inbox")["messages"] == []
    request = reopened.assistant_exchange("codex", "send", "q2", "peer question")
    assert request["direction"] == "assistant_to_peer"
    assert reopened.exchange("codex", bearer, "inbox")["messages"] == [request]
    reopened.exchange("codex", bearer, "reply", "q2", "peer answer")
    assert reopened.assistant_exchange("codex", "inbox")["messages"][0]["reply"] == "peer answer"
    assert reopened.assistant_exchange("codex", "ack", "q2")["state"] == "acknowledged"


def test_peer_credentials_and_rows_are_strictly_isolated(store):
    a, b = store.enroll("a", "codex"), store.enroll("b", "native")
    store.exchange("a", a, "send", "only-a", "private-a")
    for peer, credential in [("a", b), ("b", a), ("a", ""), ("missing", a)]:
        fails("PEER_NOT_AUTHORIZED", lambda: store.describe(peer, credential))
        fails("PEER_NOT_AUTHORIZED", lambda: store.exchange(peer, credential, "inbox"))
    assert store.exchange("b", b, "inbox")["messages"] == []
    fails("CONTACT_NOT_FOUND", lambda: store.exchange("b", b, "receipt", "only-a"))
    store.exchange("b", b, "send", "only-a", "independent-b")
    assert store.exchange("a", a, "receipt", "only-a")["content"] == "private-a"
    public = json.dumps([store.peers(), store.describe("a", a), store.exchange("a", a, "receipt", "only-a")])
    assert a not in public and b not in public and str(store.root) not in public
    raw = (store.root / "envelopes.json").read_text(encoding="utf-8")
    assert a not in raw and b not in raw


def test_first_message_reply_and_direction_are_immutable(store):
    key = store.enroll("peer", "codex")
    first = store.exchange("peer", key, "send", "same", " first ")
    assert store.exchange("peer", key, "send", "same", " first ") == first
    fails("CONTACT_CONFLICT", lambda: store.exchange("peer", key, "send", "same", "first"))
    fails("CONTACT_CONFLICT", lambda: store.assistant_exchange("peer", "send", "same", " first "))
    fails("CONTACT_ROLE_DENIED", lambda: store.exchange("peer", key, "reply", "same", "wrong"))
    fails("CONTACT_ROLE_DENIED", lambda: store.assistant_exchange("peer", "ack", "same"))
    fails("CONTACT_CONFLICT", lambda: store.exchange("peer", key, "ack", "same"))
    reply = store.assistant_exchange("peer", "reply", "same", "answer")
    assert store.assistant_exchange("peer", "reply", "same", "answer") == reply
    fails("CONTACT_CONFLICT", lambda: store.assistant_exchange("peer", "reply", "same", "changed"))
    ack = store.exchange("peer", key, "ack", "same")
    assert store.exchange("peer", key, "ack", "same") == ack
    assert store.assistant_exchange("peer", "reply", "same", "answer") == ack


def test_revoke_and_reenroll_do_not_restore_old_generation(store):
    old = store.enroll("peer", "codex")
    store.exchange("peer", old, "send", "old", "old content")
    fails("PEER_ALREADY_ENROLLED", lambda: store.enroll("peer", "codex"))
    assert store.revoke("peer")["status"] == "revoked"
    assert store.revoke("peer")["status"] == "revoked"
    assert store.peers() == []
    fails("PEER_NOT_AUTHORIZED", lambda: store.exchange("peer", old, "receipt", "old"))
    fails("PEER_NOT_AUTHORIZED", lambda: store.assistant_exchange("peer", "inbox"))
    new = store.enroll("peer", "codex")
    assert old != new
    fails("PEER_NOT_AUTHORIZED", lambda: store.describe("peer", old))
    assert store.exchange("peer", new, "inbox")["messages"] == []
    fails("CONTACT_NOT_FOUND", lambda: store.exchange("peer", new, "receipt", "old"))
    fails("CONTACT_CONFLICT", lambda: store.exchange("peer", new, "send", "old", "old content"))


@pytest.mark.parametrize("operation,request_id,content", [
    ("send", "../escape", "hello"), ("send", "ok", "x" * 1001),
    ("send", "ok", "  "), ("send", "ok", "hello\x00"), ("send", "ok", "bad\x7f"),
    ("send", "ok", "bad\ud800"), ("receipt", "ok", "unexpected"),
    ("inbox", "unexpected", ""), ("enroll", "", ""), ("revoke", "", ""),
])
def test_closed_input_contract(store, operation, request_id, content):
    key = store.enroll("peer", "codex")
    fails("PEER_INPUT_INVALID", lambda: store.exchange("peer", key, operation, request_id, content))


def test_native_gate_and_discovery_do_not_start_a_session(store, monkeypatch):
    from core.infrastructure import native_runtime
    store.enroll("peer", "codex")
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: False)
    assert store.peers() == [{"peerId": "peer", "platform": "codex"}]
    fails("CONTACT_ROLE_DENIED", lambda: store.assistant_exchange("peer", "inbox"))


def test_inbox_and_lifetime_capacity_are_bounded(store, monkeypatch):
    import core.assistant_runtime.peer_contacts as module
    monkeypatch.setattr(module, "MAX_REQUESTS_PER_PEER", 6)
    key = store.enroll("peer", "codex")
    for index in range(6):
        store.assistant_exchange("peer", "send", f"r{index}", "x" * 1000)
    inbox = store.exchange("peer", key, "inbox")
    assert len(inbox["messages"]) == 4 and inbox["hasMore"] is True
    fails("CONTACT_CAPACITY", lambda: store.assistant_exchange("peer", "send", "overflow", "x"))
    store.exchange("peer", key, "reply", "r0", "reply")
    store.assistant_exchange("peer", "ack", "r0")
    assert store.exchange("peer", key, "inbox")["messages"][0]["requestId"] == "r1"
    fails("CONTACT_CAPACITY", lambda: store.assistant_exchange("peer", "send", "overflow", "x"))


def test_concurrent_same_key_has_one_immutable_winner(store):
    key = store.enroll("peer", "codex")
    def send(content):
        try:
            return PeerContacts(store.root.parent).exchange("peer", key, "send", "race", content)
        except PeerContactError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(send, ["a", "b", "a", "b"]))
    winner = store.exchange("peer", key, "receipt", "race")["content"]
    assert all(result == "CONTACT_CONFLICT" or result["content"] == winner for result in results)


def test_independent_processes_share_the_same_request_reservation(store):
    key = store.enroll("peer", "codex")
    script = """
import json, sys
from core.assistant_runtime.peer_contacts import PeerContactError, PeerContacts
root, credential, content = json.loads(sys.stdin.read())
try:
    result = PeerContacts(root).exchange('peer', credential, 'send', 'race', content)
except PeerContactError as error:
    result = error.code
print(json.dumps(result))
"""
    def send(content):
        result = subprocess.run([sys.executable, "-c", script],
            input=json.dumps([str(store.root.parent), key, content]), text=True,
            capture_output=True, cwd=Path(__file__).resolve().parents[1], timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, ["process-a", "process-b"]))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert results.count("CONTACT_CONFLICT") == 1
    assert store.exchange("peer", key, "receipt", "race")["content"] in {"process-a", "process-b"}


def test_total_storage_and_peer_capacity_reject_without_mutation(store, monkeypatch):
    import core.assistant_runtime.peer_contacts as module
    key = store.enroll("peer", "codex")
    monkeypatch.setattr(module, "MAX_PEERS", 1)
    fails("CONTACT_CAPACITY", lambda: store.enroll("other", "codex"))
    path = store.root / "envelopes.json"
    before = path.read_bytes()
    monkeypatch.setattr(module, "MAX_STORAGE_BYTES", len(before) + 100)
    fails("CONTACT_CAPACITY", lambda: store.exchange("peer", key, "send", "big", "界" * 1000))
    assert path.read_bytes() == before
    assert store.exchange("peer", key, "inbox")["messages"] == []


def test_lost_write_ack_reuses_same_envelope_and_never_changes_content(store, monkeypatch):
    import core.assistant_runtime.peer_contacts as module
    key = store.enroll("peer", "codex")
    original = module.atomic_write_json
    def lost_ack(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("private-path-must-not-escape")
    monkeypatch.setattr(module, "atomic_write_json", lost_ack)
    fails("CONTACT_STORAGE_UNAVAILABLE", lambda: store.exchange("peer", key, "send", "lost", "once"))
    monkeypatch.setattr(module, "atomic_write_json", original)
    assert store.exchange("peer", key, "send", "lost", "once")["content"] == "once"
    assert len(store.assistant_exchange("peer", "inbox")["messages"]) == 1
    fails("CONTACT_CONFLICT", lambda: store.exchange("peer", key, "send", "lost", "different"))


def test_malformed_storage_fails_closed_without_repair(store):
    key = store.enroll("peer", "codex")
    path = store.root / "envelopes.json"
    path.write_text('{"schemaVersion":1,"schemaVersion":2}', encoding="utf-8")
    before = path.read_bytes()
    fails("CONTACT_STORAGE_UNAVAILABLE", lambda: store.describe("peer", key))
    fails("CONTACT_STORAGE_UNAVAILABLE", lambda: store.enroll("other", "codex"))
    assert path.read_bytes() == before


@pytest.mark.parametrize("damage", ["digest", "revoked", "reply_state"])
def test_structurally_corrupt_grants_and_messages_are_not_repaired(store, damage):
    key = store.enroll("peer", "codex")
    store.exchange("peer", key, "send", "r", "hello")
    path = store.root / "envelopes.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    if damage == "digest":
        state["peers"]["peer"]["credentialDigest"] = "not-a-digest"
    elif damage == "revoked":
        state["peers"]["peer"]["revoked"] = 0
    else:
        state["messages"]["peer"]["r"]["state"] = "reply_ready"
    path.write_text(json.dumps(state), encoding="utf-8")
    before = path.read_bytes()
    fails("CONTACT_STORAGE_UNAVAILABLE", lambda: store.exchange("peer", key, "receipt", "r"))
    assert path.read_bytes() == before


def test_unsafe_storage_aliases_fail_closed(store, tmp_path):
    store.enroll("peer", "codex")
    path = store.root / "envelopes.json"
    alias = tmp_path / "alias.json"
    os.link(path, alias)
    fails("CONTACT_STORAGE_UNAVAILABLE", store.peers)


def test_linked_private_directory_is_rejected(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink permission unavailable")
    fails("CONTACT_STORAGE_UNAVAILABLE", lambda: PeerContacts(link).enroll("peer", "codex"))
    assert list(target.iterdir()) == []


def test_discovery_of_absent_store_does_not_create_private_state(tmp_path):
    store = PeerContacts(tmp_path / "profile")
    assert store.peers() == []
    fails("PEER_NOT_AUTHORIZED", lambda: store.describe("none", "wrong"))
    assert not store.root.exists()
