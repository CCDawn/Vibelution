"""Finite, revocable goal provenance for native Launcher-derived dispatch.

Ordinary dispatch keeps its exact-user-span contract. This separate governed
protocol binds derived work to an admitted operator event without pretending
that an assistant or patrol message was a new operator instruction.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Literal

import anyio
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock
from .dispatch import DispatchError
from .dispatch_approval import DispatchWrite
from .task_source import SourceReference, resolve_task

_ID = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$"
_DIRECTORY_FILES = 512
_DIRECTORY_ENTRIES = 2048


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Target(Closed):
    project_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
    agent_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


class GoalCreate(Closed):
    goal_id: str = Field(pattern=_ID)
    targets: list[Target] = Field(min_length=1, max_length=16)
    permission_profile: Literal["read_only", "workspace_write"] = "read_only"
    max_tasks: int = Field(default=8, ge=1, le=32)
    ttl_minutes: int = Field(default=60, ge=1, le=1440)

    @model_validator(mode="after")
    def unique_targets(self):
        if len({(row.project_id, row.agent_id) for row in self.targets}) != len(self.targets):
            raise ValueError("Duplicate delegation target")
        return self


class GoalQuery(Closed):
    goal_id: str = Field(pattern=_ID)


class GoalList(Closed):
    offset: int = Field(default=0, ge=0, le=_DIRECTORY_FILES)
    limit: int = Field(default=6, ge=1, le=6)
    expected_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class DerivedDispatch(DispatchWrite):
    goal_id: str = Field(pattern=_ID)
    permission_profile: Literal["read_only", "workspace_write"] = "read_only"


class DerivedReference(Closed):
    goalId: str = Field(pattern=_ID)
    goalFingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    sourceEventId: str = Field(min_length=1, max_length=160)
    sourceTurnId: str = Field(min_length=1, max_length=160)
    taskHash: str = Field(pattern=r"^[0-9a-f]{64}$")


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _error(code):
    return DispatchError("派生任务授权无法确认；请查询原目标或原派遣回执。", code=code)


def read_goal_source(runtime, reference):
    """Read only the goal's original operator event in the fixed native Journal.

    The current turn may be a real patrol admission. It must still be the
    trusted live Launcher turn; only the *original goal* must be an operator
    message. This does not change native.read_task_source's legacy gate.
    """
    from . import native
    from core.infrastructure.native_runtime import assistant_native_root
    from core.chat.turn_journal import EVENT_TURN_STARTED, EVENT_USER_MESSAGE, TERMINAL_EVENTS, load_turn_events

    ref = SourceReference.model_validate(reference).model_dump()
    with native._source_command() as (sessions, sid):
        root = assistant_native_root()
        directory, _, _, directory_runtime = native._services()
        trusted = directory.current_agent_runtime()
        if (not isinstance(runtime, dict) or not isinstance(trusted, dict)
                or any(not isinstance(runtime.get(k), str) or not runtime[k] or runtime[k] != trusted.get(k)
                    for k in ("agentId", "sessionId", "turnId"))
                or (runtime["agentId"], runtime["sessionId"]) != (native._AGENT_ID, sid)
                or (ref["agentId"], ref["sessionId"]) != (native._AGENT_ID, sid)
                or Path(sessions.PROJECT_ROOT).resolve() != root or Path(directory.PROJECT_ROOT).resolve() != root
                or directory_runtime.directory_store_project_root() != root
                or directory_runtime.get_open_directory_store() is None):
            raise _error("DELEGATION_IDENTITY_INVALID")
        events = load_turn_events(root, sid)
        current = [row for row in events if row.session_id == sid and row.turn_id == runtime["turnId"]]
        starts = [row for row in current if row.event_type == EVENT_TURN_STARTED]
        if (len(starts) != 1 or starts[0].payload.get("agentId") != native._AGENT_ID
                or any(row.event_type in TERMINAL_EVENTS for row in current)):
            raise _error("DELEGATION_TURN_UNAVAILABLE")
        original = [row for row in events if row.session_id == sid and row.turn_id == ref["turnId"]]
        users = [row for row in original if row.event_type == EVENT_USER_MESSAGE]
        starts = [row for row in original if row.event_type == EVENT_TURN_STARTED]
        if len(users) != 1 or len(starts) != 1:
            raise _error("DELEGATION_SOURCE_UNAVAILABLE")
        user, start = users[0], starts[0]
        meta = user.payload.get("metadata")
        if (not isinstance(meta, dict) or not isinstance(meta.get("clientSubmissionId"), str)
                or not meta["clientSubmissionId"] or user.correlation_id != meta["clientSubmissionId"]
                or user.event_id != ref["eventId"] or user.source != "submit_session_message"
                or user.source_kind not in {"", "user", "operator"} or user.payload.get("source") != "raw"
                or meta.get("kind") not in (None, "", "user") or meta.get("turnId") not in (None, "", ref["turnId"])
                or meta.get("source") not in (None, "", "user", "operator", "raw")
                or any(meta.get(k) not in (None, "", "user", "operator") for k in ("actor", "actorId", "actorType", "sourceKind"))
                or any(meta.get(k) for k in ("agentId", "actorAgentId", "proactive", "system", "sourceAgentId"))
                or start.source != "submit_session_message" or start.source_kind not in {"", "user", "operator"}
                or start.payload.get("agentId") != native._AGENT_ID or start.payload.get("source") != "raw"
                or start.correlation_id != user.correlation_id or user.sequence <= start.sequence or not user.visible_in_model):
            raise _error("DELEGATION_SOURCE_UNAVAILABLE")
        content = user.payload.get("content")
        if (not isinstance(content, str) or hashlib.sha256(content.encode()).hexdigest() != ref["contentHash"]
                or not 0 <= ref["start"] < ref["end"] <= len(content)
                or hashlib.sha256(content[ref["start"]:ref["end"]].encode()).hexdigest() != ref["spanHash"]):
            raise _error("DELEGATION_SOURCE_CHANGED")
        return ref


class DelegationManager:
    def __init__(self, dispatch, *, source_reader=None, source_resolver=None, clock=time.time):
        self.dispatch = dispatch
        self.root = dispatch._root.parent / "assistant_delegation"
        self._source_reader = source_reader or read_goal_source
        self._source_resolver = source_resolver or resolve_task
        self._clock = clock
        self._locks = {}

    def _path(self, goal_id):
        GoalQuery(goal_id=goal_id)
        return self.root / (_hash(goal_id) + ".json")

    def _read(self, goal_id, *, raw=None):
        path = self._path(goal_id)
        try:
            if raw is None:
                with path.open("rb") as handle:
                    raw = handle.read(64 * 1024 + 1)
            if len(raw) > 64 * 1024:
                raise ValueError("Goal record too large")
            row = json.loads(raw)
            if (not isinstance(row, dict) or set(row) != {"schemaVersion", "parameters", "source", "bindings",
                    "fingerprint", "createdAt", "expiresAt", "revoked", "children"} or row["schemaVersion"] != 1):
                raise ValueError("Invalid goal")
            args = GoalCreate.model_validate(row["parameters"])
            SourceReference.model_validate(row["source"])
            if (args.goal_id != goal_id or type(row["revoked"]) is not bool or type(row["children"]) is not dict
                    or len(row["children"]) > args.max_tasks or type(row["bindings"]) is not dict
                    or set(row["bindings"]) != {target.project_id for target in args.targets}
                    or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in row["bindings"].values())
                    or any(type(row[k]) not in (int, float) or not math.isfinite(row[k]) for k in ("createdAt", "expiresAt"))
                    or row["expiresAt"] != row["createdAt"] + args.ttl_minutes * 60
                    or row["fingerprint"] != _hash([row["parameters"], row["source"], row["bindings"]])
                    or any(not isinstance(k, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", k) or not isinstance(v, str)
                        or not re.fullmatch(r"[0-9a-f]{64}", v) for k, v in row["children"].items())):
                raise ValueError("Invalid goal binding")
            return row
        except (OSError, ValueError, TypeError, KeyError):
            raise _error("DELEGATION_GOAL_UNAVAILABLE") from None

    def _save(self, goal_id, row):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write_json(self._path(goal_id), row, strict_replace=True)

    def _bindings(self, targets):
        return {target.project_id: self.dispatch._binding(self.dispatch._project(target.project_id)) for target in targets}

    def _verify(self, row, runtime, *, active=True):
        self._source_reader(runtime, row["source"])
        args = GoalCreate.model_validate(row["parameters"])
        if self._bindings(args.targets) != row["bindings"]:
            raise _error("DELEGATION_PROJECT_CHANGED")
        if active and (row["revoked"] or self._clock() >= row["expiresAt"]):
            raise _error("DELEGATION_GOAL_INACTIVE")
        return args

    def _public(self, row):
        return {"goalId": row["parameters"]["goal_id"], "goalFingerprint": row["fingerprint"],
            "targets": row["parameters"]["targets"], "permissionProfile": row["parameters"]["permission_profile"],
            "maxTasks": row["parameters"]["max_tasks"], "usedTasks": len(row["children"]),
            "remainingTasks": row["parameters"]["max_tasks"] - len(row["children"]),
            "expiresAt": row["expiresAt"], "revoked": row["revoked"],
            "active": not row["revoked"] and self._clock() < row["expiresAt"],
            "sourceTurnId": row["source"]["turnId"], "sourceHash": row["source"]["spanHash"],
            "readOnly": True, "untrustedContent": True}

    def create(self, parameters, runtime):
        args = GoalCreate.model_validate(parameters)
        path = self._path(args.goal_id)
        with cross_process_file_lock(path.with_suffix(".lock"), timeout=5):
            if path.exists():
                row = self._read(args.goal_id)
                if row["parameters"] != args.model_dump():
                    raise _error("DELEGATION_GOAL_CONFLICT")
                self._verify(row, runtime, active=False)
                return self._public(row)
            _, source = self._source_resolver(runtime, task_source={})
            bindings = self._bindings(args.targets)
            now = self._clock()
            row = {"schemaVersion": 1, "parameters": args.model_dump(), "source": source,
                "bindings": bindings, "fingerprint": _hash([args.model_dump(), source, bindings]),
                "createdAt": now, "expiresAt": now + args.ttl_minutes * 60, "revoked": False, "children": {}}
            self._verify(row, runtime)
            self._save(args.goal_id, row)
            return self._public(row)

    def get(self, goal_id, runtime):
        row = self._read(goal_id)
        self._verify(row, runtime, active=False)
        return self._public(row)

    def _directory_identity(self, runtime):
        """Metadata identity only; listing never verifies an operator event."""
        from . import native
        from core.infrastructure.native_runtime import assistant_native_root, is_launcher_assistant_process
        try:
            with native._source_command() as (sessions, sid):
                directory, _, _, directory_runtime = native._services()
                trusted = directory.current_agent_runtime()
                root = assistant_native_root()
                if (not is_launcher_assistant_process() or not isinstance(runtime, dict) or not isinstance(trusted, dict)
                        or any(not isinstance(runtime.get(k), str) or not runtime[k] or runtime[k] != trusted.get(k)
                               for k in ("agentId", "sessionId", "turnId"))
                        or (runtime["agentId"], runtime["sessionId"]) != (native._AGENT_ID, sid)
                        or sid != native._SESSION_ID or self.root.parent.resolve() != root
                        or Path(sessions.PROJECT_ROOT).resolve() != root or Path(directory.PROJECT_ROOT).resolve() != root
                        or directory_runtime.directory_store_project_root() != root
                        or directory_runtime.get_open_directory_store() is None):
                    raise ValueError("Native identity changed")
                return runtime["agentId"], sid
        except Exception:
            raise _error("DELEGATION_DIRECTORY_IDENTITY_INVALID") from None

    def _directory_paths(self):
        paths, entries, invalid, complete = [], 0, 0, True
        if self.root.is_symlink():
            raise _error("DELEGATION_DIRECTORY_UNAVAILABLE")
        try:
            with os.scandir(self.root) as directory:
                for entry in directory:
                    if entries >= _DIRECTORY_ENTRIES:
                        complete = False
                        break
                    entries += 1
                    if not entry.name.endswith(".json"):
                        continue
                    if len(paths) >= _DIRECTORY_FILES:
                        complete = False
                        break
                    if not re.fullmatch(r"[a-f0-9]{64}\.json", entry.name) or not entry.is_file(follow_symlinks=False):
                        invalid += 1
                        continue
                    paths.append(Path(entry.path))
        except FileNotFoundError:
            if self.root.exists() or self.root.is_symlink():
                raise _error("DELEGATION_DIRECTORY_UNAVAILABLE") from None
        except OSError:
            raise _error("DELEGATION_DIRECTORY_UNAVAILABLE") from None
        return sorted(paths), entries, invalid, complete

    def _list(self, args, runtime):
        identity = self._directory_identity(runtime)
        paths, entries, invalid, scanned_complete = scan = self._directory_paths()
        observed, stamps = [], []
        for path in paths:
            try:
                with path.open("rb") as handle:
                    raw = handle.read(64 * 1024 + 1)
                stamps.append((path, hashlib.sha256(raw).hexdigest()))
                goal_id = json.loads(raw)["parameters"]["goal_id"]
                if path != self._path(goal_id):
                    raise ValueError("Goal filename changed")
                row = self._read(goal_id, raw=raw)
            except (OSError, ValueError, TypeError, KeyError, DispatchError):
                invalid += 1
                continue
            if (row["source"]["agentId"], row["source"]["sessionId"]) != identity:
                continue
            targets = GoalCreate.model_validate(row["parameters"]).targets
            try:
                if self._bindings(targets) == row["bindings"]:
                    observed.append((row, targets))
            except DispatchError:
                continue
        # Atomic records can still change between directory pages. Do not
        # concatenate quota/source revisions into a purported stable census.
        if self._directory_paths() != scan:
            raise _error("DELEGATION_DIRECTORY_CHANGED")
        for path, stamp in stamps:
            try:
                with path.open("rb") as handle:
                    unchanged = hashlib.sha256(handle.read(64 * 1024 + 1)).hexdigest() == stamp
            except OSError:
                unchanged = False
            if not unchanged:
                raise _error("DELEGATION_DIRECTORY_CHANGED")
        if self._directory_identity(runtime) != identity:
            raise _error("DELEGATION_DIRECTORY_IDENTITY_INVALID")
        rows = []
        for row, targets in observed:
            try:
                if self._bindings(targets) == row["bindings"]:
                    rows.append(row)
            except DispatchError:
                continue
        rows.sort(key=lambda row: row["parameters"]["goal_id"])
        coverage = {"scannedFiles": len(paths), "scannedEntries": entries, "scanLimit": _DIRECTORY_FILES,
                    "invalidRecords": invalid, "scanComplete": scanned_complete}
        snapshot = _hash({"rows": [_hash(row) for row in rows], "coverage": coverage})
        if args.expected_digest is not None and args.expected_digest != snapshot:
            raise _error("DELEGATION_DIRECTORY_CHANGED")
        if args.offset > len(rows):
            raise _error("DELEGATION_DIRECTORY_OFFSET_INVALID")
        complete = scanned_complete and not invalid
        page = {"goals": [], "offset": args.offset, "limit": 0, "nextOffset": None, "total": len(rows),
                "snapshotDigest": snapshot, "complete": complete, "status": "ok" if complete else "partial",
                "coverage": coverage, "sourceVerified": False, "readOnly": True, "untrustedContent": True}
        now = self._clock()
        for row in rows[args.offset:args.offset + args.limit]:
            parameters = row["parameters"]
            used = len(row["children"])
            item = {"goalId": parameters["goal_id"], "targetCount": len(parameters["targets"]),
                    "permissionProfile": parameters["permission_profile"], "maxTasks": parameters["max_tasks"],
                    "usedTasks": used, "remainingTasks": parameters["max_tasks"] - used, "expiresAt": row["expiresAt"],
                    "revoked": row["revoked"], "active": not row["revoked"] and now < row["expiresAt"], "sourceVerified": False}
            selected = [*page["goals"], item]
            end = args.offset + len(selected)
            candidate = {**page, "goals": selected, "limit": len(selected), "nextOffset": end if end < len(rows) else None}
            if len(json.dumps({"source": "launcher-assistant", **candidate}, ensure_ascii=False)) > 3400:
                if not page["goals"]:
                    raise _error("DELEGATION_DIRECTORY_BUDGET")
                break
            page = candidate
        return page

    async def list(self, parameters, runtime):
        """Discover current-profile metadata; get/derived still verify Journal."""
        args = GoalList.model_validate(parameters)
        return await anyio.to_thread.run_sync(self._list, args, dict(runtime))

    def _revoke(self, goal_id, runtime):
        with cross_process_file_lock(self._path(goal_id).with_suffix(".lock"), timeout=5):
            row = self._read(goal_id)
            self._verify(row, runtime, active=False)
            row["revoked"] = True
            self._save(goal_id, row)
            return self._public(row)

    async def revoke(self, goal_id, runtime):
        # Serialize revocation with the whole native admission, including the
        # SDK's asynchronous identity/permission preflight. Once revoke returns,
        # no child awaiting that admission can begin a new native POST.
        async with self._locks.setdefault(goal_id, anyio.Lock()):
            return await anyio.to_thread.run_sync(self._revoke, goal_id, runtime)

    async def derived(self, parameters, runtime):
        args = DerivedDispatch.model_validate(parameters)
        identity = _hash(args.model_dump(exclude={"dispatch_id"}))
        async with self.dispatch._dispatch_admission:
            self.dispatch._check_dispatch_unfenced()
            async with self._locks.setdefault(args.goal_id, anyio.Lock()):
                with cross_process_file_lock(self._path(args.goal_id).with_suffix(".lock"), timeout=5):
                    row = self._read(args.goal_id)
                    goal = await anyio.to_thread.run_sync(self._verify, row, runtime)
                    if (args.project_id, args.agent_id) not in {(t.project_id, t.agent_id) for t in goal.targets}:
                        raise _error("DELEGATION_TARGET_DENIED")
                    if args.permission_profile == "workspace_write" and goal.permission_profile != "workspace_write":
                        raise _error("DELEGATION_PERMISSION_DENIED")
                    previous = row["children"].get(args.dispatch_id)
                    if previous is not None and previous != identity:
                        raise _error("DELEGATION_DISPATCH_CONFLICT")
                    if previous is None:
                        if identity in row["children"].values():
                            raise _error("DELEGATION_ORIGINAL_DISPATCH_REQUIRED")
                        if len(row["children"]) >= goal.max_tasks:
                            raise _error("DELEGATION_QUOTA_EXHAUSTED")
                        row["children"][args.dispatch_id] = identity
                        self._save(args.goal_id, row)
                    reference = DerivedReference(goalId=args.goal_id, goalFingerprint=row["fingerprint"],
                        sourceEventId=row["source"]["eventId"], sourceTurnId=row["source"]["turnId"],
                        taskHash=hashlib.sha256(args.task.encode()).hexdigest()).model_dump()
                await anyio.to_thread.run_sync(self._verify, row, runtime)
                return await self.dispatch._dispatch(args.project_id, agent_id=args.agent_id, task=args.task,
                    dispatch_id=args.dispatch_id, permission_profile=args.permission_profile, derived_ref=reference)


def contracts():
    return {name: {"action": name, "parameters": model.model_json_schema(), "governed": governed,
        "description": description} for name, model, governed, description in (
        ("delegation_goal_create", GoalCreate, True, "将当前用户目标绑定到有限目标Agent、权限上限、任务额度和有效期；只存原生来源引用。稳定goal_id重试不延长有效期。需manage原生审批。"),
        ("delegation_goal_get", GoalQuery, False, "读取本会话已授权目标及额度/有效期，不返回用户正文；未知派遣查询原receipt。"),
        ("delegation_goal_list", GoalList, False, "分页发现当前助理会话的目标授权ID及额度/有效期元数据，不返回目标正文或源消息。sourceVerified=false，active只表示未撤销且未过期，不证明原生来源当前可执行；继续前必须用原goal_id查询/验证。partial不代表完整目录，续页保持expected_digest。"),
        ("delegation_goal_revoke", GoalQuery, True, "撤销原目标的新派工权限，不中止已有原生任务；已有任务仍用原receipt核验。"),
        ("dispatch_derived", DerivedDispatch, True, "在已授权goal_id范围内派遣助理拆出的任务，允许原生巡检续接。每次遵循具体任务/目标/权限原生审批；目标权限仍限制实际执行。稳定dispatch_id重试不重复扣额度、不更换ID重派未知任务。"),
    )}


def approval_summary(action, parameters):
    model = {"delegation_goal_create": GoalCreate, "delegation_goal_revoke": GoalQuery,
        "dispatch_derived": DerivedDispatch}[action]
    values = model.model_validate(parameters).model_dump()
    task = values.pop("task", None)
    return {"assistantAction": action, "assistantTargets": values,
        **({"assistantTask": task, "assistantRequestedPermission": values["permission_profile"]} if task is not None else {})}
