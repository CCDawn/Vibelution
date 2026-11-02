"""Operator-only cleanup of registered Launcher tasks; never a model action.

Previews are bounded, short-lived and bound to the active assistant and exact
native identities. A partial deletion retains its local reference for retry.
"""
from __future__ import annotations

import json
import secrets
import time
from collections import OrderedDict
from pathlib import Path
from typing import Annotated, Literal, Union

import anyio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.infrastructure.atomic_io import atomic_write_json


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


_Id = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]


class DispatchTarget(_Closed):
    kind: Literal["dispatch"]
    projectId: _Id
    dispatchId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class TeamTarget(_Closed):
    kind: Literal["team_run"]
    projectId: _Id
    requestId: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    originAction: Literal["team_run", "flow_start"]
    teamId: _Id
    flowId: _Id
    runId: _Id


Target = Annotated[Union[DispatchTarget, TeamTarget], Field(discriminator="kind")]


class CleanupPreview(_Closed):
    agentId: _Id
    directSessionId: _Id
    targets: list[Target] = Field(min_length=1, max_length=32)


class CleanupExecute(CleanupPreview):
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


def target_key(target):
    return json.dumps([target.kind, target.projectId,
                       target.dispatchId if target.kind == "dispatch" else target.originAction,
                       target.requestId if target.kind == "team_run" else None], separators=(",", ":"))


def _size(path: Path) -> int:
    stat = path.lstat()
    if path.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400 or not path.is_file():
        raise ValueError("cleanup_path_invalid")
    return stat.st_size


def _dispatch_binding(row):
    return tuple(row.get(key) for key in ("dispatchId", "projectId", "projectBinding", "agentId", "nativeTaskId", "requestDigest"))


def _retained(rows):
    reasons = {
        "shared_project_source": "项目源码由其他任务共用。",
        "workspace_has_uncommitted_or_ignored_files": "工作区含未提交的改动或尚不能确认可丢弃的忽略文件；任务记录会保留，处理后可重试。",
        "workspace_has_unmerged_commits": "工作区含未合入的提交，已保留代码。",
        "workspace_shared_by_task": "工作区仍被其他任务引用，仅清理本项的独占记录。",
        "workspace_registration_changed": "工作区注册或锁定状态已变化；任务记录会保留，核对后可重试。",
        "workspace_preparation_active": "工作区仍在准备，请等待准备结束后重新预览；任务记录会保留。",
        "workspace_preparation_unconfirmed": "工作区准备失败，尚不能确认遗留目录的位置；请先核对分支工作区，任务记录会保留。",
        "shared_database_and_git_objects": "数据库和 Git 对象由其他任务共用。",
        "native_recovery_and_admission_guards": "仅保留原生删除标记和并发锁，不保存会话内容。",
        "prevent_request_replay": "仅保留防止重复执行的最小摘要，不保存任务内容。",
        "branch_delete_failed": "文件已清理，本地分支尚未移除。",
        "branch_changed": "本地分支已发生变化，已保留。",
        "session_family_shared": "会话有关联的父子会话，本次无法安全删除。",
        "session_shared_by_task": "会话仍被其他任务引用。",
        "session_directory_shared": "会话目录仍被其他会话使用。",
        "session_direct_binding": "会话是 Agent 的主会话，不能随这项任务删除。",
        "session_active": "会话仍有活动，请结束后重试。",
        "session_ownership_unproven": "尚不能确认会话由这项任务独占。",
        "unsafe_resource_link": "资源路径包含链接，未执行删除。",
    }
    return [{"kind": str(row.get("kind", "resource"))[:100],
             "reason": reasons.get(row.get("reason"), "资源归属或清理条件尚未确认，已保留。")}
            for row in rows if isinstance(row, dict)][:128]


class TaskCleanup:
    def __init__(self, dispatch, identity):
        self.dispatch = dispatch
        self.identity = identity
        self._previews = OrderedDict()
        self._lock = anyio.Lock()

    def _identity(self, payload):
        identity = self.identity()
        if not isinstance(identity, dict) or (identity.get("agentId"), identity.get("directSessionId")) != (payload.agentId, payload.directSessionId):
            raise HTTPException(409, detail={"code": "TASK_CLEANUP_IDENTITY_CHANGED"})

    async def _team_plan(self, target):
        from .team_patrol import TeamPatrolObserver
        adapter = self.dispatch.management
        key = adapter._key(target.projectId, target.originAction, target.requestId)
        path = adapter._root / (key + ".json")
        record = adapter._read(path)
        ref = {"projectId": target.projectId, "action": target.originAction, "requestId": target.requestId}
        if record.get("reference") != ref:
            raise ValueError("cleanup_reference_changed")
        observer = TeamPatrolObserver(self.dispatch)
        receipt = await observer._read_receipt(ref)
        if receipt.get("verified") is not True or receipt.get("status") != "completed":
            raise ValueError("cleanup_source_unconfirmed")
        run = await observer._flow_run(ref, receipt) if target.originAction == "flow_start" else receipt.get("teamRun")
        if not isinstance(run, dict) or any(run.get(k) != getattr(target, k) for k in ("teamId", "flowId", "runId")):
            raise ValueError("cleanup_run_changed")
        if run.get("status") not in {"completed", "failed", "stopped"}:
            raise ValueError("cleanup_task_active")
        return {"path": path, "record": record, "binding": self.dispatch._project_read_binding(target.projectId),
                "revision": run.get("revision"), "status": run["status"], "bytes": _size(path)}

    async def _plan(self, target):
        if target.kind == "team_run":
            plan = await self._team_plan(target)
            return plan, {"status": "ready", "estimatedBytes": plan["bytes"],
                          "resources": [{"kind": "launcher_task_record", "count": 1, "bytes": plan["bytes"]}],
                          "retained": [{"kind": "shared_team_resources", "reason": "团队、成员、运行历史和成果供其他功能共用，本次仅删除助理的任务关联记录。"}]}
        row = self.dispatch._read(target.dispatchId)
        if row.get("projectId") != target.projectId or not row.get("nativeTaskId"):
            raise ValueError("cleanup_reference_changed")
        path = self.dispatch._path(target.dispatchId)
        native = await self.dispatch._call(target.projectId,
            lambda client: client.preview_task_cleanup(task_id=row["nativeTaskId"]))
        if (not isinstance(native, dict) or native.get("taskId") != row["nativeTaskId"]
                or not isinstance(native.get("fingerprint"), str)):
            raise ValueError("cleanup_source_unconfirmed")
        if native.get("status", "ready") != "ready":
            return None, {"status": "blocked", "estimatedBytes": 0, "resources": [],
                          "retained": _retained(native.get("retained", [])), "reason": "有资源尚不能安全删除，请处理保留原因后重试。"}
        return {"path": path, "binding": _dispatch_binding(row), "native": native, "bytes": _size(path)}, {
            "status": "ready", "estimatedBytes": _size(path) + max(0, int(native.get("estimatedBytes", 0))),
            "resources": [{"kind": "launcher_task_record", "count": 1, "bytes": _size(path)}, *native.get("resources", [])],
            "retained": _retained(native.get("retained", []))}

    async def preview(self, payload):
        self._identity(payload)
        keys = [target_key(target) for target in payload.targets]
        if len(set(keys)) != len(keys):
            raise HTTPException(422, detail={"code": "TASK_CLEANUP_DUPLICATE"})
        items, plans = [], []
        for target, key in zip(payload.targets, keys):
            try:
                plan, item = await self._plan(target)
            except Exception:
                plan = None
                item = {"status": "blocked", "estimatedBytes": 0, "resources": [], "retained": [],
                        "reason": "当前无法确认任务身份、终态或删除范围，请刷新后重试。"}
            items.append({"key": key, "title": target.dispatchId if target.kind == "dispatch" else target.requestId, **item})
            plans.append(plan)
        self._identity(payload)
        token, now = secrets.token_hex(32), time.monotonic()
        async with self._lock:
            self._previews = OrderedDict((key, value) for key, value in self._previews.items() if now - value[0] < 300)
            while len(self._previews) >= 16:
                self._previews.popitem(last=False)
            self._previews[token] = (now, payload.model_dump(), plans)
        return {"schemaVersion": 1, "fingerprint": token, "estimatedBytes": sum(item["estimatedBytes"] for item in items), "items": items}

    async def execute(self, payload):
        self._identity(payload)
        async with self._lock:
            saved = self._previews.pop(payload.fingerprint, None)
        if saved is None or time.monotonic() - saved[0] >= 300 or saved[1] != payload.model_dump(exclude={"fingerprint"}):
            raise HTTPException(409, detail={"code": "TASK_CLEANUP_PREVIEW_EXPIRED"})
        items = []
        for target, plan in zip(payload.targets, saved[2]):
            self._identity(payload)
            item = {"key": target_key(target), "status": "blocked", "releasedBytes": 0, "retained": [], "failures": []}
            local_before = None
            local_paths = []
            native_delta = 0
            try:
                if plan is None:
                    raise ValueError("cleanup_preview_blocked")
                if target.kind == "dispatch":
                    async with self.dispatch._dispatch_lock(target.dispatchId):
                        row = self.dispatch._read(target.dispatchId)
                        if _dispatch_binding(row) != plan["binding"]:
                            raise ValueError("cleanup_reference_changed")
                        native = plan["native"]
                        marker = self.dispatch._root / "deleted" / (target.dispatchId + ".json")
                        local_paths = [plan["path"], marker]
                        local_before = sum(_size(path) for path in local_paths if path.exists())
                        # Persist recovery before an irreversible native request.
                        # A later TASK_NOT_FOUND during patrol must not make a
                        # partially cleaned task unreachable from the operator UI.
                        row["cleanupPending"] = True
                        self.dispatch._save(row)
                        result = await self.dispatch._call(target.projectId, lambda client: client.cleanup_task(
                            task_id=row["nativeTaskId"], revision=native["revision"], fingerprint=native["fingerprint"]))
                        if not isinstance(result, dict) or result.get("taskId") != row["nativeTaskId"]:
                            raise ValueError("cleanup_receipt_invalid")
                        native_delta = result.get("storageDeltaBytes", result.get("releasedBytes", 0))
                        if type(native_delta) is not int:
                            raise ValueError("cleanup_accounting_invalid")
                        item.update(status=result.get("status", "partial"), releasedBytes=max(0, int(result.get("releasedBytes", 0))),
                                    retained=_retained(result.get("retained", [])), failures=[{
                                        "code": "TASK_RESOURCE_CLEANUP_FAILED", "message": "部分任务文件尚未删除，请重新预览后重试。"
                                    } for failure in result.get("failures", []) if isinstance(failure, dict)])
                        if item["status"] == "deleted":
                            # This compact marker prevents a deleted dispatch ID
                            # from becoming a second execution after credential loss.
                            atomic_write_json(marker, {"schemaVersion": 1, "requestDigest": row["requestDigest"]}, strict_replace=True)
                            _size(plan["path"])
                            plan["path"].unlink()
                            item["retained"].append({"kind": "deduplication_marker", "reason": "仅保留防止重复执行的最小摘要，不保存任务内容。"})
                else:
                    adapter = self.dispatch.management
                    key = adapter._key(target.projectId, target.originAction, target.requestId)
                    async with adapter._locks.setdefault(key, anyio.Lock()):
                        current = await self._team_plan(target)
                        if any(current[key] != plan[key] for key in ("record", "binding", "revision", "status")):
                            raise ValueError("cleanup_reference_changed")
                        current["path"].unlink()
                        item.update(status="deleted", releasedBytes=current["bytes"],
                                    retained=[{"kind": "shared_team_resources", "reason": "共用团队、成员、运行历史和成果已保留。"}])
            except Exception:
                item["status"] = "partial" if item["releasedBytes"] else "blocked"
                item["failures"].append({"code": "TASK_CLEANUP_INCOMPLETE", "message": "清理未完成，任务引用已保留；请重新预览后重试。"})
            if local_before is not None:
                try:
                    delta = native_delta + local_before - sum(_size(path) for path in local_paths if path.exists())
                except (OSError, ValueError):
                    delta = 0
                    item["failures"].append({"code": "TASK_CLEANUP_ACCOUNTING_UNAVAILABLE", "message": "暂时无法核实已释放空间。"})
                item["storageDeltaBytes"] = delta
                item["releasedBytes"] = max(0, delta)
            items.append(item)
        delta = sum(item.get("storageDeltaBytes", item["releasedBytes"]) for item in items)
        return {"schemaVersion": 1, "releasedBytes": max(0, delta), "storageDeltaBytes": delta, "items": items}


def create_task_cleanup_router(dispatch, native, app):
    router = APIRouter()

    def identity():
        value = getattr(native, "assistant", None)
        if not isinstance(value, dict):
            value = getattr(app.state, "assistant", {}).get("assistant")
        return value

    service = TaskCleanup(dispatch, identity)

    @router.post("/api/assistant/task-cleanup/preview")
    async def preview(payload: CleanupPreview):
        return await service.preview(payload)

    @router.post("/api/assistant/task-cleanup/execute")
    async def execute(payload: CleanupExecute):
        return await service.execute(payload)

    return router
