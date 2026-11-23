"""Bounded private peer envelopes; native Sessions remain transcript owners.

Enrollment and revocation are operator APIs, never contact tool operations.
The composition owner must authenticate those calls and the native Agent/Session
before calling assistant_exchange. This store additionally checks the frozen
Launcher process role. A queued envelope does not prove native delivery, and
reply_ready only proves a stored response; ack records its sender's receipt.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat

from core.assistant_runtime.migration_io import (
    check_path, pinned_mutable_file, pinned_target_directory, read_stable_file,
    strict_json, validate_path,
)
from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock, lock_path_for

MAX_PEERS = 64
MAX_REQUESTS_PER_PEER = 64
MAX_TEXT = 1000
INBOX_LIMIT = 4
MAX_STORAGE_BYTES = 12 * 1024 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,128}")
_HEX32 = re.compile(r"[0-9a-f]{32}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_DIRECTIONS = {"peer_to_assistant", "assistant_to_peer"}
_STATES = {"queued", "reply_ready", "acknowledged"}


class PeerContactError(ValueError):
    """A public stable code, never a filesystem path or underlying exception."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code):
    raise PeerContactError(code)


def _identifier(value, pattern=_ID):
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        _fail("PEER_INPUT_INVALID")
    return value


def _text(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT
            or any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in value)):
        _fail("PEER_INPUT_INVALID")
    try:
        value.encode("utf-8")
    except UnicodeError:
        _fail("PEER_INPUT_INVALID")
    return value


def _digest(salt, credential):
    return hashlib.sha256((salt + "\0" + credential).encode("ascii")).hexdigest()


def _empty():
    return {"schemaVersion": 1, "peers": {}, "messages": {}}


def _validate(state):
    """Reject damaged grants or envelopes instead of repairing authority."""
    try:
        if (not isinstance(state, dict) or set(state) != {"schemaVersion", "peers", "messages"}
                or type(state["schemaVersion"]) is not int or state["schemaVersion"] != 1
                or not isinstance(state["peers"], dict) or len(state["peers"]) > MAX_PEERS
                or not isinstance(state["messages"], dict)
                or set(state["messages"]) != set(state["peers"])):
            raise ValueError
        for peer, grant in state["peers"].items():
            _identifier(peer)
            if (not isinstance(grant, dict)
                    or set(grant) != {"platform", "salt", "credentialDigest", "generation", "revoked"}
                    or type(grant["revoked"]) is not bool):
                raise ValueError
            _identifier(grant["platform"])
            for key, pattern in (("salt", _HEX32), ("generation", _HEX32), ("credentialDigest", _HEX64)):
                if not isinstance(grant[key], str) or pattern.fullmatch(grant[key]) is None:
                    raise ValueError
            messages = state["messages"][peer]
            if not isinstance(messages, dict) or len(messages) > MAX_REQUESTS_PER_PEER:
                raise ValueError
            for request, row in messages.items():
                _identifier(request, _REQUEST)
                if (not isinstance(row, dict)
                        or set(row) not in ({"generation", "direction", "state", "content"},
                                            {"generation", "direction", "state", "content", "reply"})
                        or not isinstance(row["generation"], str) or _HEX32.fullmatch(row["generation"]) is None
                        or row["direction"] not in _DIRECTIONS or row["state"] not in _STATES):
                    raise ValueError
                _text(row["content"])
                if (row["state"] == "queued") != ("reply" not in row):
                    raise ValueError
                if "reply" in row:
                    _text(row["reply"])
    except (KeyError, TypeError, ValueError):
        _fail("CONTACT_STORAGE_UNAVAILABLE")
    return state


class PeerContacts:
    """Atomic, capacity-limited contact envelopes inside a private PA profile.

    Request IDs are reserved for the peer's lifetime, including revoked grant
    generations. Capacity is deliberately never reclaimed implicitly: deleting
    a receipt must not let a retry silently create a new message with its ID.
    """

    def __init__(self, profile_root):
        try:
            self.root = validate_path(Path(profile_root)) / "peer_contacts"
        except (OSError, TypeError, ValueError):
            _fail("CONTACT_STORAGE_UNAVAILABLE")

    @staticmethod
    def _leaf(path):
        check_path(path, missing_ok=True)
        if path.exists():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                _fail("CONTACT_STORAGE_UNAVAILABLE")

    @contextmanager
    def _state(self, *, write=False, create=False):
        try:
            failure = None
            check_path(self.root, missing_ok=True)
            if not self.root.exists() and not create:
                yield _empty()
                return
            if os.name != "nt" and create:
                self.root.mkdir(parents=True, exist_ok=True)
            directory = pinned_target_directory(self.root, create=create) if os.name == "nt" else nullcontext()
            with directory:
                check_path(self.root)
                if not self.root.is_dir():
                    _fail("CONTACT_STORAGE_UNAVAILABLE")
                path = self.root / "envelopes.json"
                lock = lock_path_for(path)
                self._leaf(path)
                self._leaf(lock)
                pinned = pinned_mutable_file(lock) if os.name == "nt" else nullcontext()
                with pinned, cross_process_file_lock(path, timeout=2):
                    self._leaf(path)
                    state = _validate(strict_json(read_stable_file(path, MAX_STORAGE_BYTES).raw)) if path.exists() else _empty()
                    try:
                        yield state
                        if write:
                            raw = json.dumps(state, ensure_ascii=False, indent=None).encode("utf-8")
                            if len(raw) > MAX_STORAGE_BYTES:
                                _fail("CONTACT_CAPACITY")
                            self._leaf(path)
                            atomic_write_json(path, state, indent=None, strict_replace=True, ensure_parent_dir=False,
                                              retry_timeout_seconds=0, lock_timeout_seconds=2)
                    except PeerContactError as error:
                        # Migration path guards translate ValueError at their
                        # boundary. Keep public domain errors outside those
                        # guards, and never commit the rejected mutation.
                        failure = error
            if failure is not None:
                raise failure
        except PeerContactError:
            raise
        except (OSError, ValueError, TypeError, RecursionError):
            _fail("CONTACT_STORAGE_UNAVAILABLE")

    @staticmethod
    def _grant(state, peer_id, credential=None, *, assistant=False):
        grant = state["peers"].get(peer_id)
        if not grant or grant["revoked"]:
            _fail("PEER_NOT_AUTHORIZED")
        if not assistant and (not isinstance(credential, str) or _TOKEN.fullmatch(credential) is None
                or not hmac.compare_digest(grant["credentialDigest"], _digest(grant["salt"], credential))):
            _fail("PEER_NOT_AUTHORIZED")
        return grant

    def enroll(self, peer_id, platform):
        """Operator-only: issue a new bearer once; never return an existing one."""
        _identifier(peer_id)
        _identifier(platform)
        with self._state(write=True, create=True) as state:
            old = state["peers"].get(peer_id)
            if old and not old["revoked"]:
                _fail("PEER_ALREADY_ENROLLED")
            if old is None and len(state["peers"]) >= MAX_PEERS:
                _fail("CONTACT_CAPACITY")
            credential, salt = secrets.token_urlsafe(32), secrets.token_hex(16)
            state["peers"][peer_id] = {"platform": platform, "salt": salt,
                "credentialDigest": _digest(salt, credential), "generation": secrets.token_hex(16), "revoked": False}
            state["messages"].setdefault(peer_id, {})
        return credential

    def revoke(self, peer_id):
        """Operator-only, idempotent revocation; old messages stay inaccessible."""
        _identifier(peer_id)
        with self._state(write=True) as state:
            if peer_id not in state["peers"]:
                _fail("PEER_NOT_FOUND")
            state["peers"][peer_id]["revoked"] = True
        return {"peerId": peer_id, "status": "revoked"}

    def peers(self):
        """Static enrolled identities only; no credentials, messages or online claim."""
        with self._state() as state:
            return [{"peerId": peer, "platform": grant["platform"]}
                    for peer, grant in sorted(state["peers"].items()) if not grant["revoked"]]

    def describe(self, peer_id, credential):
        _identifier(peer_id)
        with self._state() as state:
            grant = self._grant(state, peer_id, credential)
            return {"peerId": peer_id, "platform": grant["platform"], "contact": "launcher_assistant",
                    "authorized": True, "asynchronous": True, "availability": "host_state_not_checked",
                    "maxTextChars": MAX_TEXT, "inboxLimit": INBOX_LIMIT, "maxRequests": MAX_REQUESTS_PER_PEER}

    def exchange(self, peer_id, credential, operation, request_id="", content=""):
        return self._exchange(peer_id, operation, request_id, content, credential=credential)

    def assistant_exchange(self, peer_id, operation, request_id="", content=""):
        from core.infrastructure.native_runtime import is_launcher_assistant_process
        if not is_launcher_assistant_process():
            _fail("CONTACT_ROLE_DENIED")
        return self._exchange(peer_id, operation, request_id, content, assistant=True)

    @staticmethod
    def _public(peer_id, request_id, row):
        return {"peerId": peer_id, "requestId": request_id,
                **{key: row[key] for key in ("direction", "state", "content", "reply") if key in row}}

    def _exchange(self, peer_id, operation, request_id, content, *, credential=None, assistant=False):
        _identifier(peer_id)
        if not isinstance(operation, str) or operation not in {"send", "inbox", "receipt", "reply", "ack"}:
            _fail("PEER_INPUT_INVALID")
        if operation == "inbox":
            if request_id != "" or content != "":
                _fail("PEER_INPUT_INVALID")
        else:
            _identifier(request_id, _REQUEST)
            if operation in {"send", "reply"}:
                _text(content)
            elif content != "":
                _fail("PEER_INPUT_INVALID")
        direction = "assistant_to_peer" if assistant else "peer_to_assistant"
        with self._state(write=operation in {"send", "reply", "ack"}) as state:
            grant = self._grant(state, peer_id, credential, assistant=assistant)
            messages = state["messages"][peer_id]
            if operation == "inbox":
                rows = [self._public(peer_id, request, row) for request, row in messages.items()
                        if row["generation"] == grant["generation"]
                        and (row["state"] == "queued" and row["direction"] != direction
                             or row["state"] == "reply_ready" and row["direction"] == direction)]
                return {"peerId": peer_id, "messages": rows[:INBOX_LIMIT], "hasMore": len(rows) > INBOX_LIMIT}
            row = messages.get(request_id)
            if operation == "send":
                if row is not None:
                    if (row["generation"] != grant["generation"] or row["direction"] != direction
                            or row["content"] != content):
                        _fail("CONTACT_CONFLICT")
                else:
                    if len(messages) >= MAX_REQUESTS_PER_PEER:
                        _fail("CONTACT_CAPACITY")
                    row = {"generation": grant["generation"], "direction": direction,
                           "state": "queued", "content": content}
                    messages[request_id] = row
            else:
                if row is None or row["generation"] != grant["generation"]:
                    _fail("CONTACT_NOT_FOUND")
                if operation == "reply":
                    if row["direction"] == direction:
                        _fail("CONTACT_ROLE_DENIED")
                    if "reply" in row and row["reply"] != content:
                        _fail("CONTACT_CONFLICT")
                    if "reply" not in row:
                        row.update(reply=content, state="reply_ready")
                elif operation == "ack":
                    if row["direction"] != direction:
                        _fail("CONTACT_ROLE_DENIED")
                    if row["state"] == "queued":
                        _fail("CONTACT_CONFLICT")
                    row["state"] = "acknowledged"
            return self._public(peer_id, request_id, row)
