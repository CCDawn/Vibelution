"""Closed, task-bound transport for messages to the Launcher assistant.

These rows are delivery envelopes, not a second conversation. Native Session
history remains the message authority after delivery. Unknown writes are never
automatically replayed.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import stat
import time
from contextlib import contextmanager
from pathlib import Path

_ID = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
MAX_TEXT = 1000


def valid_tool_call(args):
    if not isinstance(args, dict) or set(args) - {"operation", "request_id", "content"}:
        return False
    operation, request_id, content = args.get("operation", "describe"), args.get("request_id", ""), args.get("content", "")
    try:
        if operation == "describe":
            return request_id == "" and content == ""
        if operation == "receipt":
            return _id(request_id) == request_id and content == ""
        return operation == "send" and bool(_id(request_id)) and bool(_text(content))
    except ValueError:
        return False


def _text(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT
            or any(ord(c) < 32 and c not in "\n\t" for c in value)):
        raise ValueError("contact_text_invalid")
    return value.strip()


def _id(value):
    if not isinstance(value, str) or re.fullmatch(_ID, value) is None:
        raise ValueError("contact_request_id_invalid")
    return value


class TaskContacts:
    """Bounded SQLite delivery receipts, isolated from the native task store."""

    def __init__(self, root: Path):
        self.root = Path(root)

    @contextmanager
    def _db(self, *, create=True):
        path = self.root / "contacts.sqlite3"
        if not create and not path.exists():
            yield None
            return
        self.root.mkdir(parents=True, exist_ok=True)
        for part in (*reversed(self.root.parents), self.root, path):
            if part.exists() or part.is_symlink():
                info = part.lstat()
                if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
                        or part == path and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)
                        or part != path and not stat.S_ISDIR(info.st_mode)):
                    raise ValueError("contact_storage_unavailable")
        db = sqlite3.connect(path, timeout=1, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS contacts (task TEXT, request TEXT, payload TEXT, PRIMARY KEY(task,request))")
            db.execute("CREATE TABLE IF NOT EXISTS presence (task TEXT PRIMARY KEY, observed REAL)")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _row(self, db, task_id, request_id):
        row = db.execute("SELECT payload FROM contacts WHERE task=? AND request=?", (task_id, _id(request_id))).fetchone()
        if row is None:
            raise ValueError("contact_not_found")
        return json.loads(row[0])

    def _save(self, db, row):
        db.execute("UPDATE contacts SET payload=? WHERE task=? AND request=?",
                   (json.dumps(row, ensure_ascii=False), row["taskId"], row["requestId"]))

    def describe(self, task_id):
        observed = 0
        with self._db(create=False) as db:
            if db is not None:
                row = db.execute("SELECT observed FROM presence WHERE task=?", (task_id,)).fetchone()
                observed = row[0] if row else 0
        return {"contact": "launcher_assistant", "authorized": True, "scope": "original_launcher_task",
                "availability": "observed_online" if time.time() - observed < 35 else "offline_or_unobserved",
                "asynchronous": True, "maxTextChars": MAX_TEXT,
                "message": "Replies return only to this task Agent and Session; queued does not mean delivered."}

    def send(self, task, request_id, content):
        request_id, content = _id(request_id), _text(content)
        identity = {key: task[key] for key in ("taskId", "agentId", "sessionId", "localAuthorityFingerprint")}
        with self._db() as db:
            old = db.execute("SELECT payload FROM contacts WHERE task=? AND request=?", (task["taskId"], request_id)).fetchone()
            if old is not None:
                row = json.loads(old[0])
                if row["identity"] != identity or row["content"] != content:
                    raise ValueError("contact_request_conflict")
                return self.public(row)
            if db.execute("SELECT count(*) FROM contacts WHERE task=?", (task["taskId"],)).fetchone()[0] >= 32:
                raise ValueError("contact_capacity_reached")
            row = {"schemaVersion": 1, "taskId": task["taskId"], "requestId": request_id,
                   "identity": identity, "content": content, "state": "undelivered", "createdAt": time.time()}
            db.execute("INSERT INTO contacts VALUES (?,?,?)", (task["taskId"], request_id, json.dumps(row, ensure_ascii=False)))
            return self.public(row)

    def receipt(self, task, request_id):
        with self._db(create=False) as db:
            if db is None:
                raise ValueError("contact_not_found")
            row = self._row(db, task["taskId"], request_id)
            self._identity(row, task)
            return self.public(row)

    @staticmethod
    def _identity(row, task):
        if row["identity"] != {key: task[key] for key in ("taskId", "agentId", "sessionId", "localAuthorityFingerprint")}:
            raise ValueError("contact_identity_changed")

    def pending(self, task):
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO presence VALUES (?,?)", (task["taskId"], time.time()))
            rows = [json.loads(r[0]) for r in db.execute("SELECT payload FROM contacts WHERE task=? ORDER BY request", (task["taskId"],))]
            for row in rows:
                self._identity(row, task)
            return {"schemaVersion": 1, "taskId": task["taskId"], "contacts": [self.public(r, content=True) for r in rows]}

    def delivery(self, task, request_id, state):
        if state not in {"delivery_unknown", "received"}:
            raise ValueError("contact_state_invalid")
        with self._db() as db:
            row = self._row(db, task["taskId"], request_id)
            self._identity(row, task)
            changed = False
            if (state == "delivery_unknown" and row["state"] == "undelivered"
                    or state == "received" and row["state"] == "delivery_unknown"):
                row["state"] = state
                self._save(db, row)
                changed = True
            return {**self.public(row), "changed": changed}

    def reply(self, task, request_id, content, deliver):
        content = _text(content)
        digest = hashlib.sha256(content.encode()).hexdigest()
        with self._db() as db:
            row = self._row(db, task["taskId"], request_id)
            self._identity(row, task)
            if row.get("replyDigest"):
                if row["replyDigest"] != digest:
                    raise ValueError("contact_reply_conflict")
                return self.public(row)
            if row["state"] != "received":
                raise ValueError("contact_not_received")
            row.update(state="reply_unknown", replyDigest=digest)
            self._save(db, row)
        # Reserve before native delivery. A failure/crash retains unknown and
        # the same request cannot cause another native write.
        delivery = deliver(task["agentId"], task["sessionId"], request_id, content)
        with self._db() as db:
            row = self._row(db, task["taskId"], request_id)
            self._identity(row, task)
            if delivery.get("historyStatus") == "appended":
                row.update(state="replied", reply=content, delivery=delivery)
                self._save(db, row)
            return self.public(row)

    @staticmethod
    def public(row, *, content=False):
        result = {key: row[key] for key in ("schemaVersion", "taskId", "requestId", "state", "createdAt")}
        if content:
            result.update(content=row["content"], sourceAgentId=row["identity"]["agentId"],
                          sourceSessionId=row["identity"]["sessionId"])
        if row.get("reply"):
            result["reply"] = row["reply"]
        return {**result, "untrustedContent": True, "businessCompletion": "not_evaluated"}


def contacts_for_project(project_root):
    from vibelution_storage import resolve_project_runtime_home
    return TaskContacts(resolve_project_runtime_home(Path(project_root)) / "local_assistant_contacts")


def owned_task(service, owner_id, task_id):
    service._require_gateway_enabled()
    task = service._owned_task(owner_id, task_id)
    service._require_cleanup_ownership(task)
    if not task.get("localAuthorityFingerprint") or not task.get("agentId") or not task.get("sessionId"):
        raise ValueError("contact_task_unavailable")
    return task


def deliver_reply(agent_id, session_id, request_id, content):
    from core.web.services import session_service
    from core.agent_kernel import submit_agent_message_event
    detail = session_service.get_session_detail(session_id, message_limit=0, transcript_scope="none", include_secondary=False)
    if not detail or detail.get("agentId") != agent_id or detail.get("archived"):
        raise ValueError("contact_reply_target_unavailable")
    result = submit_agent_message_event(source="launcher_assistant_contact", sender={"type": "system", "id": "launcher_assistant"},
        recipient_agent_ids=[agent_id], content=content, correlation_id=request_id, wake_target=False,
        source_id="launcher-contact-reply:" + hashlib.sha256((session_id + "\0" + request_id).encode()).hexdigest(),
        metadata={"targetSessionId": session_id, "inboxKind": "agent_inbox_reply", "sourceSurface": "launcher_assistant_contact",
                  "messageSummary": content, "untrustedContent": True})
    rows = (result.get("outcome") or {}).get("deliveries") or []
    return rows[0] if len(rows) == 1 else {"historyStatus": "pending"}
