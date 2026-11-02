"""Bounded, body-free card reads over existing assistant request associations.

Native receipts own progress. This query owns no ledger, monitor, admission,
delivery, or cache; every page rechecks its local association/binding snapshot.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Literal

import anyio
from pydantic import BaseModel, ConfigDict, Field

from .team_patrol import TeamPatrolObserver, _ID, _key

_PAGE_SIZE = 16
_BUDGET = 4.0
_CONCURRENCY = 4
_TITLE_BUDGET = 0.2
_CURSOR = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Assistant(_Closed):
    agentId: str
    directSessionId: str


class _TeamRun(_Closed):
    projectId: str
    requestId: str
    originAction: Literal["team_run", "flow_start"]
    teamId: str | None
    flowId: str | None
    runId: str | None
    status: str | None
    revision: str | None
    title: str = Field(max_length=160)
    readState: Literal["ready", "unknown"]
    observedAt: str | None
    businessAcceptance: Literal["not_evaluated"]


class _Coverage(_Closed):
    kind: Literal["local_associations"]
    historyComplete: Literal[False]
    legacyUnrecoverable: int = Field(ge=0)
    invalidRecords: int = Field(ge=0)


class TeamTaskCardsPage(_Closed):
    schemaVersion: Literal[1]
    assistant: _Assistant
    teamRuns: list[_TeamRun] = Field(max_length=_PAGE_SIZE)
    offset: int = Field(ge=0)
    total: int = Field(ge=0)
    nextCursor: str | None
    coverage: _Coverage
    state: Literal["ready", "partial"]


class TeamTaskCardsError(ValueError):
    def __init__(self, status_code, code):
        super().__init__(code)
        self.status_code = status_code
        self.code = code


def _cursor_decode(cursor):
    if cursor is None:
        return None, 0
    try:
        if not isinstance(cursor, str) or not _CURSOR.fullmatch(cursor):
            raise ValueError
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        value = json.loads(raw)
        if (not isinstance(value, dict) or set(value) != {"snapshot", "offset"}
                or not isinstance(value["snapshot"], str) or not _DIGEST.fullmatch(value["snapshot"])
                or type(value["offset"]) is not int or value["offset"] < 0
                or base64.urlsafe_b64encode(raw).decode().rstrip("=") != cursor):
            raise ValueError
        return value["snapshot"], value["offset"]
    except (ValueError, TypeError, binascii.Error):
        raise TeamTaskCardsError(422, "team_runs_cursor_invalid") from None


def _cursor_encode(snapshot, offset):
    raw = json.dumps({"snapshot": snapshot, "offset": offset}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _snapshot(observer):
    rows, source_coverage = observer._requests()
    rows = sorted(rows, key=_key)
    coverage = {"kind": "local_associations", "historyComplete": False,
                **{key: source_coverage[key] for key in ("legacyUnrecoverable", "invalidRecords")}}
    bindings = {}
    for project in sorted({row["projectId"] for row in rows}):
        try:
            bindings[project] = observer._binding(project)
        except Exception:
            # A missing local binding cannot confirm a row. Other projects
            # remain readable; recovery changes the snapshot on the next page.
            bindings[project] = None
    encoded = json.dumps([rows, coverage, bindings], sort_keys=True, ensure_ascii=True,
                         separators=(",", ":"), default=str).encode()
    return rows, coverage, bindings, hashlib.sha256(encoded).hexdigest()


def _unknown(row):
    return {"projectId": row["projectId"], "requestId": row["requestId"], "originAction": row["action"],
            "teamId": None, "flowId": None, "runId": None, "status": None, "revision": None,
            "title": "", "readState": "unknown", "observedAt": None, "businessAcceptance": "not_evaluated"}


def _title(value):
    """Public names are untrusted display text, never instructions."""
    if not isinstance(value, str):
        return ""
    visible = (" " if char.isspace() else char for char in value
               if char.isspace() or unicodedata.category(char) not in {"Cc", "Cf", "Cs"})
    return " ".join("".join(visible).split())[:160]


async def read_team_task_cards(dispatch, assistant, *, cursor=None):
    """Return one stable association page, keeping each unconfirmed native row."""
    expected, offset = _cursor_decode(cursor)
    observer = TeamPatrolObserver(dispatch)
    deadline = time.monotonic() + _BUDGET
    try:
        with anyio.fail_after(_BUDGET):
            before = await anyio.to_thread.run_sync(_snapshot, observer, abandon_on_cancel=True)
            rows, coverage, bindings, snapshot = before
            if expected is not None and expected != snapshot:
                raise TeamTaskCardsError(409, "team_runs_snapshot_changed")
            if offset > len(rows):
                raise TeamTaskCardsError(422, "team_runs_cursor_invalid")
            selected = rows[offset:offset + _PAGE_SIZE]
            cards = [_unknown(row) for row in selected]
            semaphore = anyio.Semaphore(_CONCURRENCY)
            titles, title_locks = {}, {}
            team_reader = getattr(dispatch.management, "team", None)

            async def team_title(project_id, team_id):
                if not callable(team_reader):
                    return ""
                key = project_id, team_id
                async with title_locks.setdefault(key, anyio.Lock()):
                    if key not in titles:
                        titles[key] = ""
                        try:
                            with anyio.move_on_after(_TITLE_BUDGET):
                                result = await team_reader(project_id, team_id=team_id)
                                team = result.get("team") if isinstance(result, dict) else None
                                if (isinstance(result, dict) and result.get("projectId") == project_id
                                        and isinstance(team, dict) and team.get("id") == team_id):
                                    titles[key] = _title(team.get("name"))
                        except Exception:
                            pass  # Optional display metadata cannot invalidate native progress.
                    return titles[key]

            async def read(index, row):
                async with semaphore:
                    try:
                        if bindings[row["projectId"]] is None:
                            return
                        receipt = await observer._read_receipt(row)
                        if receipt.get("verified") is not True or receipt.get("status") != "completed":
                            return
                        run = (await observer._flow_run(row, receipt) if row["action"] == "flow_start"
                               else receipt.get("teamRun"))
                        if (not isinstance(run, dict) or any(not isinstance(run.get(key), str)
                                or not _ID.fullmatch(run[key]) for key in ("teamId", "flowId", "runId", "status"))):
                            return
                        revision = run.get("revision")
                        if type(revision) is int and revision >= 0:
                            revision = str(revision)
                        if not isinstance(revision, str) or not _ID.fullmatch(revision):
                            revision = None
                        cards[index] = {**cards[index], **{key: run[key] for key in
                            ("teamId", "flowId", "runId", "status")}, "revision": revision,
                            "readState": "ready", "observedAt": datetime.now(timezone.utc).isoformat()}
                        cards[index]["title"] = await team_title(row["projectId"], run["teamId"])
                    except Exception:
                        pass  # No target error, path, prompt or result body crosses this boundary.

            # Reserve a small part of the same page budget for the local
            # after-scan, so a slow project does not discard healthy peers.
            remaining = max(0, deadline - time.monotonic() - min(0.1, _BUDGET / 4))
            with anyio.move_on_after(remaining):
                async with anyio.create_task_group() as tasks:
                    for index, row in enumerate(selected):
                        tasks.start_soon(read, index, row)
            after = await anyio.to_thread.run_sync(_snapshot, observer, abandon_on_cancel=True)
            if after[3] != snapshot:
                raise TeamTaskCardsError(409, "team_runs_snapshot_changed")
    except TeamTaskCardsError:
        raise
    except Exception:
        raise TeamTaskCardsError(503, "team_runs_unavailable") from None
    end = offset + len(cards)
    return {"schemaVersion": 1, "assistant": {key: assistant[key] for key in ("agentId", "directSessionId")},
            "teamRuns": cards, "offset": offset, "total": len(rows),
            "nextCursor": _cursor_encode(snapshot, end) if end < len(rows) else None,
            "coverage": coverage, "state": "partial" if any(card["readState"] != "ready" for card in cards)
            or coverage["legacyUnrecoverable"] or coverage["invalidRecords"] else "ready"}
