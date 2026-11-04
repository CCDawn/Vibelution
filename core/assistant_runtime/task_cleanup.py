"""Operator-only cleanup of registered Launcher tasks; never a model action.

Previews are bounded, short-lived and bound to the active assistant and exact
native identities. A partial deletion retains its local reference for retry.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from collections import OrderedDict
from pathlib import Path
from typing import Annotated, Literal, Union

import anyio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.external_agent.backend_client import BackendClientError
from core.external_agent.contracts import TASK_ACTIVE_STATUSES, TASK_TERMINAL_STATUSES
from core.infrastructure.atomic_io import atomic_write_json
from .dispatch import DispatchError, _bounded_native_request, _checked_task_receipt

_REQUEST_PROOF_BUDGET = 25.0


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


_Id = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]


class DispatchTarget(_Closed):
    kind: Literal["dispatch"]
    projectId: _Id
    dispatchId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    localOnly: bool = False


class TeamTarget(_Closed):
    kind: Literal["team_run"]
    projectId: _Id
    requestId: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    originAction: Literal["team_run", "flow_start"]
    teamId: _Id | None = None
    flowId: _Id | None = None
    runId: _Id | None = None
    localOnly: bool = False


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


def _absent(path):
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    return False


def _dispatch_binding(row):
    return tuple(row.get(key) for key in ("dispatchId", "projectId", "projectBinding", "agentId", "nativeTaskId", "requestDigest"))


def _failure_reason(error):
    code = getattr(error, "code", "") or str(error)
    reasons = {
        "cleanup_task_active": "任务仍在运行或停止尚未确认，请结束任务后重试。",
        "TASK_NOT_TERMINAL": "任务仍在运行或停止尚未确认，请结束任务后重试。",
        "cleanup_source_unconfirmed": "尚未确认源任务的身份和状态，已保留任务关联。",
        "TASK_CLEANUP_UNAVAILABLE": "此任务不属于当前 Launcher 的本地任务，无法清理源资源。",
        "LAUNCHER_AUTHORITY_REQUIRED": "当前 Launcher 的任务清理权限不可用，请恢复连接后重试。",
        "REQUEST_UNAVAILABLE": "源团队请求记录已缺失，无法确认任务已结束，已保留助理任务关联。",
        "OPERATION_UNAVAILABLE": "源运行记录已缺失，无法确认任务已结束，已保留助理任务关联。",
        "OPERATION_SOURCE_UNAVAILABLE": "源运行状态当前不可读取，已保留助理任务关联，请恢复连接后重试。",
        "TASK_NOT_FOUND": "源任务、访问凭据或权限不可用，无法确认清理范围，已保留任务关联。",
        "BACKEND_TIMEOUT": "源项目未及时响应，清理结果尚未确认，请稍后重试。",
        "BACKEND_UNAVAILABLE": "源项目当前无法连接，已保留任务关联，请恢复连接后重试。",
        "cleanup_reference_changed": "任务关联或项目绑定已变化，请刷新后重试。",
        "cleanup_run_changed": "团队任务身份与所选关联不一致，请刷新后重试。",
        "cleanup_path_invalid": "任务记录路径不安全，已保留记录。",
        "cleanup_request_unconfirmed": "无法确认原请求是否已受理或结束，已保留任务关联。",
        "cleanup_request_identity_unconfirmed": "原请求标识缺失或与任务不一致，无法核实受理状态，已保留任务关联。",
        "UNKNOWN_REQUEST": "原请求访问凭据不可用，无法核实受理状态，已保留任务关联。",
        "BACKEND_PROTOCOL_ERROR": "源项目返回的任务身份或状态无法核对，已保留任务关联。",
        "cleanup_bound_terminal_unconfirmed": "源任务仍有关联，尚未确认已结束。请确认结束状态后再移除记录。",
        "cleanup_completion_unconfirmed": "任务关联已不在，但缺少与当前身份匹配的清理凭据，无法确认此前清理结果。",
    }
    if isinstance(error, TimeoutError):
        return reasons["BACKEND_TIMEOUT"]
    if isinstance(error, PermissionError):
        return "任务记录或清理凭据暂时无法访问，清理未完成，请稍后重试。"
    return reasons.get(code, "当前无法确认任务身份、终态或删除范围，请刷新后重试。")


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

    def _marker_path(self, target):
        if target.kind == "dispatch":
            return self.dispatch._root / "deleted" / (target.dispatchId + ".json")
        adapter = self.dispatch.management
        key = adapter._key(target.projectId, target.originAction, target.requestId)
        return adapter._root / "cleanup_tombstones" / (key + ".json")

    def _marker_scope(self, target, payload, project_binding=None):
        if project_binding is None:
            binding = self.dispatch._project_read_binding(target.projectId)
            project_binding = self.dispatch._binding(binding[1])
        scope = {"schemaVersion": 1, "kind": target.kind, "projectId": target.projectId,
                 "projectBinding": project_binding,
                 "agentId": payload.agentId, "directSessionId": payload.directSessionId, "localOnly": target.localOnly}
        if target.kind == "dispatch":
            scope["dispatchId"] = target.dispatchId
        else:
            scope.update(originAction=target.originAction, requestId=target.requestId)
        return scope

    def _row(self, dispatch_id):
        """Read a dispatch record, tolerating a since-unregistered source project.

        Registered reads still verify the registry binding; this fallback only
        unlocks the reference-only exits where the proof itself reports the
        unregistered project. A changed-but-registered binding keeps raising.
        """
        try:
            return self.dispatch._read(dispatch_id)
        except DispatchError as error:
            if error.code != "PROJECT_NOT_AUTHORIZED":
                raise
        return self.dispatch._read(dispatch_id, require_authorized=False)

    def _completed_plan(self, target, payload, path):
        binding = self.dispatch._project_read_binding(target.projectId)
        marker = self._marker_path(target)
        try:
            if _size(marker) > 4096:
                raise ValueError("cleanup_completion_unconfirmed")
            data = json.loads(marker.read_text(encoding="utf-8"))
            scope = self._marker_scope(target, payload)
            if (not isinstance(data, dict) or type(data.get("schemaVersion")) is not int or type(data.get("localOnly")) is not bool
                    or any(data.get(key) != value for key, value in scope.items())):
                raise ValueError("cleanup_completion_unconfirmed")
            if target.kind == "dispatch":
                if not re.fullmatch(r"[a-f0-9]{64}", str(data.get("requestDigest", ""))):
                    raise ValueError("cleanup_completion_unconfirmed")
            else:
                from .team_patrol import _ID
                for key in ("teamId", "flowId", "runId"):
                    value = data.get(key)
                    if target.localOnly and value is None and getattr(target, key) is None:
                        continue
                    if (not isinstance(value, str) or not _ID.fullmatch(value)
                            or getattr(target, key) is not None and value != getattr(target, key)):
                        raise ValueError("cleanup_completion_unconfirmed")
        except (OSError, ValueError, TypeError):
            raise ValueError("cleanup_completion_unconfirmed") from None
        if not _absent(path) or self.dispatch._project_read_binding(target.projectId) != binding:
            raise ValueError("cleanup_reference_changed")
        retained = [{"kind": "deduplication_marker", "reason": "仅保留任务与身份标识的清理凭据，不保存任务内容。"}]
        return {"path": path, "marker": marker, "markerData": data, "binding": binding, "alreadyDeleted": True}, {
            "status": "ready", "estimatedBytes": 0, "resources": [], "retained": retained}

    async def _dispatch_terminal_proof(self, target, record):
        receipt = record.get("receipt") or {}
        if not isinstance(receipt, dict):
            raise ValueError("cleanup_source_unconfirmed")
        if any(status in TASK_ACTIVE_STATUSES for status in (record.get("status"), receipt.get("status"))):
            raise ValueError("cleanup_task_active")
        task_id = record.get("nativeTaskId")
        if task_id:
            if (not isinstance(task_id, str) or receipt.get("taskId") != task_id
                    or receipt.get("status") not in TASK_TERMINAL_STATUSES):
                raise ValueError("cleanup_bound_terminal_unconfirmed")
            return "task", task_id, receipt["status"]
        request_id = "launcher-assistant:" + target.dispatchId
        if record.get("clientRequestId") != request_id:
            raise ValueError("cleanup_request_identity_unconfirmed")

        absence = None

        async def query(client):
            nonlocal absence
            # A lost start response can still hide an admitted task whose lease
            # patrol recovers through this exact request. Absence is accepted
            # only from this lookup, after the source handshake and the durable
            # capability check already succeeded; a credential denial or a 404
            # on the recovered task itself stays unconfirmed below.
            try:
                found = await _bounded_native_request(client.get_task_for_request(client_request_id=request_id))
            except BackendClientError as error:
                if error.code == "TASK_NOT_FOUND":
                    # Control token and capability header were both accepted;
                    # the source explicitly answered that no task is bound to
                    # this exact request for this adapter's own credential.
                    absence = "task_absent"
                elif error.code == "UNKNOWN_REQUEST":
                    # The credential ledger holds no capability for this
                    # request, so no lease patrol or reconcile path can ever
                    # recover a hidden task through this ledger generation.
                    # The source reachability handshake still ran first.
                    absence = "credential_unavailable"
                raise
            recovered_id = found.get("taskId") if isinstance(found, dict) else None
            if (not isinstance(recovered_id, str)
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", recovered_id)):
                raise ValueError("cleanup_source_unconfirmed")
            current = await _checked_task_receipt(client, recovered_id)
            # The current public task DTO omits agentId. The authenticated
            # original request binds its task; check optional identity if sent.
            if any(payload.get("agentId") is not None and payload["agentId"] != record.get("agentId")
                   for payload in (found, current)):
                raise ValueError("cleanup_reference_changed")
            if current.get("status") in TASK_ACTIVE_STATUSES:
                raise ValueError("cleanup_task_active")
            if current.get("status") not in TASK_TERMINAL_STATUSES:
                raise ValueError("cleanup_request_unconfirmed")
            return {"clientRequestId": request_id, "taskId": recovered_id, "status": current["status"]}

        try:
            with anyio.fail_after(_REQUEST_PROOF_BUDGET):
                proof = await self.dispatch._call(target.projectId, query)
        except (BackendClientError, DispatchError) as error:
            if error.code == "PROJECT_NOT_AUTHORIZED":
                # The registry lookup fails before any network I/O: the source
                # project is no longer admitted by this host, so the local
                # association cannot reference observable work there.
                return "request_absent", request_id, "project_unregistered"
            if absence is not None:
                return "request_absent", request_id, absence
            if error.code in {"UNKNOWN_REQUEST", "TASK_NOT_FOUND"}:
                raise ValueError("cleanup_request_unconfirmed") from None
            raise
        if (not isinstance(proof, dict) or proof.get("clientRequestId") != request_id
                or not isinstance(proof.get("taskId"), str) or proof.get("status") not in TASK_TERMINAL_STATUSES):
            raise ValueError("cleanup_source_unconfirmed")
        return "request", request_id, proof["taskId"], proof["status"]

    async def _local_only_plan(self, target, path):
        try:
            binding = self.dispatch._project_read_binding(target.projectId)
        except DispatchError as error:
            # An unregistered source project cannot host observable work; the
            # dispatch reference exits below carry their own proof instead.
            if error.code != "PROJECT_NOT_AUTHORIZED" or target.kind != "dispatch":
                raise
            binding = None
        if target.kind == "dispatch":
            record = self._row(target.dispatchId)
            if (record.get("projectId") != target.projectId
                    or not re.fullmatch(r"[a-f0-9]{64}", str(record.get("requestDigest", "")))):
                raise ValueError("cleanup_reference_changed")
        else:
            record = self.dispatch.management._read(path)
            if record.get("reference") != {"projectId": target.projectId,
                    "action": target.originAction, "requestId": target.requestId}:
                raise ValueError("cleanup_reference_changed")
        receipt = record.get("receipt")
        receipt = {} if receipt is None else receipt
        if not isinstance(receipt, dict):
            raise ValueError("cleanup_source_unconfirmed")
        run = receipt.get("teamRun", record.get("teamRun", {}))
        if not isinstance(run, dict):
            raise ValueError("cleanup_source_unconfirmed")
        statuses = record.get("status"), receipt.get("status"), run.get("status")
        active = {*TASK_ACTIVE_STATUSES, "dispatching", "waiting", "stopping", "preparing"}
        if any(status in active for status in statuses if isinstance(status, str)):
            raise ValueError("cleanup_task_active")
        source_status = statuses
        summary = {"status": "ready", "estimatedBytes": 0,
                   "resources": [{"kind": "launcher_task_record", "count": 1, "bytes": 0}],
                   "retained": [{"kind": "source_resources", "reason": "仅移除助理中的任务关联，源任务和共用资源均已保留。"}]}
        if target.kind == "dispatch":
            proof = await self._dispatch_terminal_proof(target, record)
            source_status = statuses, proof
            if proof[0] == "request_absent":
                summary["sourceConfirmed"] = proof[2]
        if target.kind == "team_run" and any(getattr(target, key) is not None
                and getattr(target, key) != run.get(key) for key in ("teamId", "flowId", "runId")):
            raise ValueError("cleanup_run_changed")
        if binding is not None and self.dispatch._project_read_binding(target.projectId) != binding:
            raise ValueError("cleanup_reference_changed")
        size = _size(path)
        plan = {"path": path, "bytes": size, "referenceOnly": True, "sourceStatus": source_status,
                "binding": _dispatch_binding(record) if target.kind == "dispatch" else binding,
                "record": record, "runBinding": tuple(run.get(key) for key in ("teamId", "flowId", "runId"))}
        summary["estimatedBytes"] = size
        summary["resources"] = [{"kind": "launcher_task_record", "count": 1, "bytes": size}]
        return plan, summary

    async def _team_plan(self, target):
        from .team_patrol import TeamPatrolObserver, _ID
        adapter = self.dispatch.management
        binding = self.dispatch._project_read_binding(target.projectId)
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
        if (not isinstance(run, dict) or any(not isinstance(run.get(key), str) or not _ID.fullmatch(run[key])
                for key in ("teamId", "flowId", "runId"))):
            raise ValueError("cleanup_source_unconfirmed")
        if any(getattr(target, key) is not None and run[key] != getattr(target, key)
               for key in ("teamId", "flowId", "runId")):
            raise ValueError("cleanup_run_changed")
        if run.get("status") not in {"completed", "failed", "stopped"}:
            raise ValueError("cleanup_task_active")
        if self.dispatch._project_read_binding(target.projectId) != binding:
            raise ValueError("cleanup_reference_changed")
        return {"path": path, "record": record, "binding": binding,
                "runBinding": tuple(run[key] for key in ("teamId", "flowId", "runId")),
                "revision": run.get("revision"), "status": run["status"], "bytes": _size(path)}

    async def _reference_plan(self, target, row, path):
        receipt = row.get("receipt")
        if receipt is None:
            receipt = {}
        if not isinstance(receipt, dict) or not re.fullmatch(r"[a-f0-9]{64}", str(row.get("requestDigest", ""))):
            raise ValueError("cleanup_source_unconfirmed")
        status = receipt.get("status") or row.get("status")
        if receipt.get("taskId"):
            raise ValueError("cleanup_reference_changed")
        proof = await self._dispatch_terminal_proof(target, row)
        size = _size(path)
        retained = [{"kind": "source_resources", "reason": "本次仅清理助理的任务关联，共用项目和其他源资源均已保留。"}]
        summary = {"status": "ready", "estimatedBytes": size,
                   "resources": [{"kind": "launcher_task_record", "count": 1, "bytes": size}], "retained": retained}
        if proof[0] == "request_absent":
            summary["sourceConfirmed"] = proof[2]
        return {"path": path, "binding": _dispatch_binding(row), "referenceOnly": True,
                "sourceStatus": (status, proof), "bytes": size}, summary

    async def _plan(self, target, payload):
        if target.kind == "dispatch":
            path = self.dispatch._path(target.dispatchId)
        else:
            adapter = self.dispatch.management
            key = adapter._key(target.projectId, target.originAction, target.requestId)
            path = adapter._root / (key + ".json")
        if _absent(path):
            return self._completed_plan(target, payload, path)
        if target.localOnly:
            return await self._local_only_plan(target, path)
        if target.kind == "team_run":
            plan = await self._team_plan(target)
            return plan, {"status": "ready", "estimatedBytes": plan["bytes"],
                          "resources": [{"kind": "launcher_task_record", "count": 1, "bytes": plan["bytes"]}],
                          "retained": [{"kind": "shared_team_resources", "reason": "团队、成员、运行历史和成果供其他功能共用，本次仅删除助理的任务关联记录。"}]}
        row = self._row(target.dispatchId)
        if row.get("projectId") != target.projectId:
            raise ValueError("cleanup_reference_changed")
        path = self.dispatch._path(target.dispatchId)
        if not row.get("nativeTaskId"):
            return await self._reference_plan(target, row, path)
        # TODO(cleanup): a bound nativeTaskId under a since-unregistered source
        # still dead-ends on PROJECT_NOT_AUTHORIZED here; freeing it needs a
        # product decision about silently abandoning source resources.
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
                plan, item = await self._plan(target, payload)
            except Exception as error:
                plan = None
                item = {"status": "blocked", "estimatedBytes": 0, "resources": [], "retained": [],
                        "reason": _failure_reason(error)}
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
                if plan.get("alreadyDeleted"):
                    if target.kind == "dispatch":
                        lock = self.dispatch._dispatch_lock(target.dispatchId)
                    else:
                        adapter = self.dispatch.management
                        key = adapter._key(target.projectId, target.originAction, target.requestId)
                        lock = adapter._locks.setdefault(key, anyio.Lock())
                    async with lock:
                        if not _absent(plan["path"]):
                            raise ValueError("cleanup_reference_changed")
                        current, summary = self._completed_plan(target, payload, plan["path"])
                        if any(current[key] != plan[key] for key in ("binding", "markerData")):
                            raise ValueError("cleanup_reference_changed")
                        self._identity(payload)
                        item.update(status="deleted", alreadyDeleted=True, retained=summary["retained"])
                elif target.kind == "dispatch":
                    async with self.dispatch._dispatch_lock(target.dispatchId):
                        row = self._row(target.dispatchId)
                        if _dispatch_binding(row) != plan["binding"]:
                            raise ValueError("cleanup_reference_changed")
                        marker = self._marker_path(target)
                        local_paths = [plan["path"], marker]
                        local_before = sum(_size(path) for path in local_paths if path.exists())
                        if plan.get("referenceOnly"):
                            current, summary = await self._plan(target, payload)
                            if (current is None or not current.get("referenceOnly") or any(current[key] != plan[key]
                                    for key in ("binding", "sourceStatus"))):
                                raise ValueError("cleanup_reference_changed")
                            if _dispatch_binding(self._row(target.dispatchId)) != plan["binding"]:
                                raise ValueError("cleanup_reference_changed")
                            item.update(status="deleted", retained=summary["retained"])
                            if summary.get("sourceConfirmed"):
                                item["sourceConfirmed"] = summary["sourceConfirmed"]
                        if not plan.get("referenceOnly"):
                            # Persist recovery before an irreversible native request.
                            # Local-only removal must not become a native-cleanup retry.
                            row["cleanupPending"] = True
                            self.dispatch._save(row)
                            native = plan["native"]
                            result = await self.dispatch._call(target.projectId, lambda client: client.cleanup_task(
                                task_id=row["nativeTaskId"], revision=native["revision"], fingerprint=native["fingerprint"]))
                            if not isinstance(result, dict) or result.get("taskId") != row["nativeTaskId"]:
                                raise ValueError("cleanup_receipt_invalid")
                            native_delta = result.get("storageDeltaBytes", result.get("releasedBytes", 0))
                            if type(native_delta) is not int:
                                raise ValueError("cleanup_accounting_invalid")
                            item.update(status=result.get("status", "partial"), releasedBytes=max(0, int(result.get("releasedBytes", 0))),
                                        retained=_retained(result.get("retained", [])), failures=[{
                                            "code": "TASK_RESOURCE_CLEANUP_FAILED", "message": "部分任务文件尚未删除，请重试清理。"
                                        } for failure in result.get("failures", []) if isinstance(failure, dict)])
                        if item["status"] == "deleted":
                            # This compact marker prevents a deleted dispatch ID
                            # from becoming a second execution after credential loss.
                            self._identity(payload)
                            if _dispatch_binding(self._row(target.dispatchId)) != plan["binding"]:
                                raise ValueError("cleanup_reference_changed")
                            # A reference-only plan is verified against the
                            # record's own binding digest, which equals the
                            # registry digest while the project stays admitted.
                            marker_data = {**self._marker_scope(target, payload,
                                plan["binding"][2] if plan.get("referenceOnly") else None),
                                "requestDigest": row["requestDigest"]}
                            atomic_write_json(marker, marker_data, strict_replace=True)
                            _size(plan["path"])
                            plan["path"].unlink()
                            item["retained"].append({"kind": "deduplication_marker", "reason": "仅保留防止重复执行的最小摘要，不保存任务内容。"})
                else:
                    adapter = self.dispatch.management
                    key = adapter._key(target.projectId, target.originAction, target.requestId)
                    async with adapter._locks.setdefault(key, anyio.Lock()):
                        current, summary = await self._plan(target, payload)
                        fields = ("record", "binding", "runBinding") if target.localOnly else (
                            "record", "binding", "runBinding", "revision", "status")
                        if current is None or any(current[key] != plan[key] for key in fields):
                            raise ValueError("cleanup_reference_changed")
                        self._identity(payload)
                        marker = self._marker_path(target)
                        local_paths = [current["path"], marker]
                        local_before = sum(_size(path) for path in local_paths if not _absent(path))
                        marker_data = {**self._marker_scope(target, payload),
                                       **dict(zip(("teamId", "flowId", "runId"), current["runBinding"]))}
                        atomic_write_json(marker, marker_data, strict_replace=True)
                        current["path"].unlink()
                        item.update(status="deleted", retained=[*summary["retained"],
                            {"kind": "deduplication_marker", "reason": "仅保留任务与身份标识的清理凭据，不保存任务内容。"}])
            except Exception as error:
                item["status"] = "partial" if item["releasedBytes"] else "blocked"
                item["failures"].append({"code": "TASK_CLEANUP_INCOMPLETE", "message": _failure_reason(error)})
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
