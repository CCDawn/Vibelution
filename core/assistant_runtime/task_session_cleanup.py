"""Model access to session-only cleanup via an original Launcher dispatch."""
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.external_agent.contracts import TASK_TERMINAL_STATUSES
from .dispatch import DispatchError
from .task_cleanup import _retained


class TaskSessionCleanupPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    project_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    dispatch_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")


class TaskSessionCleanup(TaskSessionCleanupPreview):
    native_task_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    session_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    expected_revision: int = Field(ge=1)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


async def task_session_cleanup(service, args, *, execute):
    project_id, dispatch_id = args["project_id"], args["dispatch_id"]
    async with service._dispatch_lock(dispatch_id):
        row = service._read(dispatch_id)
        native_id = row.get("nativeTaskId")
        receipt = row.get("receipt") or {}
        if row.get("projectId") != project_id or not native_id or (
                execute and native_id != args["native_task_id"]):
            raise DispatchError("派遣与项目或原生任务引用不一致。", code="TASK_CLEANUP_REFERENCE_CHANGED")
        if not isinstance(receipt, dict) or receipt.get("status") not in TASK_TERMINAL_STATUSES:
            raise DispatchError("请先读取原派遣回执并确认任务已结束。", code="TASK_NOT_TERMINAL")
        if execute:
            value = await service._call(project_id, lambda client: client.cleanup_task_session(
                task_id=native_id, session_id=args["session_id"], revision=args["expected_revision"],
                fingerprint=args["fingerprint"]))
            valid = (isinstance(value, dict) and value.get("sessionId") == args["session_id"]
                and value.get("status") in {"deleted", "partial", "blocked"})
        else:
            value = await service._call(project_id, lambda client: client.preview_task_session_cleanup(task_id=native_id))
            valid = isinstance(value, dict) and value.get("status") in {"ready", "blocked"}
        if not valid or value.get("taskId") != native_id:
            raise DispatchError("源项目返回的任务会话无法核对。", code="BACKEND_PROTOCOL_ERROR")
        result = {"projectId": project_id, "dispatchId": dispatch_id, "nativeTaskId": native_id,
                  "sessionId": value.get("sessionId"), "status": value["status"],
                  "alreadyDeleted": value.get("alreadyDeleted") is True,
                  "retained": _retained(value.get("retained") or [])}
        if execute:
            result["failures"] = _retained(value.get("failures") or [])
        elif value["status"] == "ready" and not result["alreadyDeleted"]:
            try:
                bound = TaskSessionCleanup(project_id=project_id, dispatch_id=dispatch_id, native_task_id=native_id,
                    session_id=value.get("sessionId"), expected_revision=value.get("revision"), fingerprint=value.get("fingerprint"))
            except ValidationError as error:
                raise DispatchError("无法验证源项目的清理预览。", code="BACKEND_PROTOCOL_ERROR") from error
            result["executeArguments"] = bound.model_dump()
        return result
