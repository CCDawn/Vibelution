"""Approved assistant Team actions; native workflows own execution and history.

The manage-tool entrypoint owns identity/ToolPolicy and per-call approval. This
adapter accepts only one built-in template and never changes its permissions.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock
from core.web.services import agent_directory_service as directory
from core.web.services import team_template_service
from core.web.services.team_workflow.generic import service as generic_workflow, store
from core.web.services.team_workflow.generic.models import Flow, SaveFlow, StartRun


class TeamRunArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=12000)
    request_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    template_id: str = Field(default="dev-team", pattern=r"^dev-team$")


_ROLES = (
    ("dev_team_planner", "规划", "分析目标、约束与验收依据，给出分工和可执行计划。"),
    ("dev_team_developer_a", "开发 A", "依据规划给出第一部分实现方案、具体变更建议与验证依据。"),
    ("dev_team_developer_b", "开发 B", "复核前序结果，补齐实现方案、边界情况与验证建议。"),
    ("dev_team_reviewer", "评审", "独立检查目标和前序结果，报告已证实结论、风险与未验证边界。"),
)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _runtime() -> dict:
    runtime = directory.current_agent_runtime()
    if any(not isinstance(runtime.get(key), str) or not runtime[key].strip() or len(runtime[key]) > 160
           for key in ("agentId", "sessionId")):
        raise ValueError("缺少有效的个人助理会话身份。")
    return runtime


def _owner_source(runtime: dict) -> str:
    return "personal_assistant_action:" + _digest(runtime["agentId"])[:40]


def _failure(error: str, message: str, record: dict | None = None) -> dict:
    result = {"ok": False, "status": "unknown" if record else "error", "error": error, "message": message}
    for key in ("teamId", "flowId", "runId"):
        if record and record.get(key):
            result[key] = record[key]
    return result


def _flow(flow_id: str, created: dict) -> Flow:
    agents = created.get("createdAgents") or []
    team = created.get("team") or {}
    members = {item.get("agentId") for item in team.get("members", [])
               if isinstance(item, dict) and item.get("status") != "archived"}
    owners = {}
    for agent in agents:
        role = (agent.get("metadata") or {}).get("teamTemplateRole")
        if role in {item[0] for item in _ROLES}:
            if role in owners:
                raise ValueError("模板角色重复。")
            owners[role] = agent.get("agentId")
    if set(owners) != {item[0] for item in _ROLES} or len(set(owners.values())) != 4:
        raise ValueError("模板角色不完整。")
    if any(not owner or owner not in members for owner in owners.values()):
        raise ValueError("模板负责人不是团队成员。")
    # Validate against the canonical roster too; a materialization response is
    # not sufficient authority for executable membership.
    canonical = store.team(team["teamId"])
    active_members = {item.get("agentId") for item in canonical.get("members", [])
                      if isinstance(item, dict) and item.get("status") != "archived"}
    if canonical.get("status") == "archived" or not set(owners.values()).issubset(active_members):
        raise ValueError("团队成员已变化。")
    return Flow.model_validate({
        "id": flow_id, "name": "开发团队目标协作",
        "fields": [{"id": "goal", "label": "目标", "kind": "text", "required": True}],
        "steps": [{"id": role, "label": label, "kind": "agent", "owner": owners[role],
                   "instruction": "根据上下文 values.goal 和 previousResults 完成当前角色工作。"
                   + instruction + "按已有权限执行所需操作，输出结果和可核验证据；不自动合入、不部署、不修改授权或模型。"}
                  for role, label, instruction in _ROLES],
    }, strict=True)


def _summary(run: dict, *, reused: bool = False) -> dict:
    # Never return values, flow instructions, messages, errors or transcripts.
    attempts = run.get("attempts") or []
    keys = ("nodeId", "number", "agentId", "sessionId", "turnId", "status")
    return {"ok": True, "teamId": run["teamId"], "flowId": run["flow"]["id"], "runId": run["id"],
            "status": run["status"], "current": run["current"], "stepCount": len(run["flow"]["steps"]),
            "attemptCount": len(attempts),
            "attempts": [{key: item[key] if key == "number" else str(item.get(key) or "")[:160]
                          for key in keys} for item in attempts[-20:]],
            "attemptsTruncated": len(attempts) > 20, "reused": reused}


def _flow_fingerprint(flow: dict) -> str:
    normalized = Flow.model_validate(flow, strict=True).model_dump(exclude_none=True)
    return _digest({key: value for key, value in normalized.items() if key not in {"revision", "updatedAt"}})


def _verify_run(run: dict, record: dict, request_id: str, goal: str) -> dict:
    run_id = record.get("runId") or "run-" + _digest([record["flowId"], request_id])[:40]
    if (run.get("teamId") != record["teamId"] or run.get("id") != run_id
            or run.get("values") != {"goal": goal} or run.get("flow", {}).get("revision") != 1
            or _flow_fingerprint(run.get("flow", {})) != record.get("flowFingerprint")):
        raise ValueError("运行身份不一致。")
    return run


def _read_run(record: dict, request_id: str, goal: str) -> dict:
    run_id = record.get("runId") or "run-" + _digest([record["flowId"], request_id])[:40]
    return _verify_run(generic_workflow.get_run(record["teamId"], run_id), record, request_id, goal)


def _launch(path: Path, record: dict, args: TeamRunArguments, *, reused: bool) -> dict:
    if not record.get("flowSaved"):
        try:
            # A save may have committed before its acknowledgement was lost.
            # Read back only the known identity and exact frozen definition;
            # never rerun materialization or overwrite an unconfirmed flow.
            saved = Flow.model_validate(store.read(store.path(record["teamId"], "flows", record["flowId"])),
                                        strict=True).model_dump(exclude_none=True)
            if saved["revision"] != 1 or _flow_fingerprint(saved) != record.get("flowFingerprint"):
                raise ValueError("流程身份不一致。")
        except Exception:
            return _failure("materialization_unconfirmed", "上次团队或流程创建未确认，请按对象标识核验；不会重复物化模板。", record)
        record.update(flowSaved=True, status="flow_saved")
        atomic_write_json(path, record, strict_replace=True)
    payload = StartRun.model_validate({"expectedRevision": 1, "idempotencyKey": args.request_id,
                                       "values": {"goal": args.goal}}, strict=True).model_dump(exclude_none=True)
    try:
        # Same native key permits recovery after lost acknowledgement; native
        # admission freezes the flow and rejects mismatched input/revision.
        run = generic_workflow.start_run(record["teamId"], record["flowId"], payload)
        run = _verify_run(run, record, args.request_id, args.goal)
    except Exception:
        try:
            run = _read_run(record, args.request_id, args.goal)
        except Exception:
            return _failure("start_unconfirmed", "运行启动未确认；可用同一 request_id 核验并恢复，勿换 key 重建。", record)
    record.update(runId=run["id"], status="started")
    atomic_write_json(path, record, strict_replace=True)
    return _summary(run, reused=reused)


def team_run(name: str, goal: str, request_id: str, template_id: str = "dev-team") -> dict:
    """Create one dev-team and start its four native sequential Agent steps."""
    try:
        args = TeamRunArguments.model_validate({"name": name, "goal": goal, "request_id": request_id,
                                                "template_id": template_id})
        if not args.name.strip() or not args.goal.strip():
            raise ValueError("空白输入。")
        runtime = _runtime()
    except Exception:
        return _failure("invalid_input", "请提供有效会话身份、团队名称、目标、request_id 和内置 dev-team 模板。")
    key = _digest([runtime["agentId"], runtime["sessionId"], args.request_id])
    fingerprint = _digest([args.name, args.goal, args.template_id])
    record = None
    try:
        path = directory._workspace_path("personal-assistant-actions", "teams", key + ".json")
        with cross_process_file_lock(path, timeout=5):
            if path.exists():
                record = json.loads(path.read_text(encoding="utf-8"))
                if (record.get("fingerprint") != fingerprint or record.get("ownerAgentId") != runtime["agentId"]
                        or record.get("ownerSessionId") != runtime["sessionId"]):
                    return _failure("idempotency_conflict", "request_id 已用于不同参数，不能复用。")
                if record.get("runId"):
                    return _summary(_read_run(record, args.request_id, args.goal), reused=True)
                return _launch(path, record, args, reused=True)
            record = {"fingerprint": fingerprint, "ownerAgentId": runtime["agentId"],
                      "ownerSessionId": runtime["sessionId"], "status": "pending"}
            # This durable intent precedes every template side effect. An
            # interrupted materialization must never be retried automatically.
            atomic_write_json(path, record, strict_replace=True)
            created = team_template_service.instantiate_team_template(
                args.template_id, name=args.name.strip(), team_source=_owner_source(runtime))
            team_id = created.get("team", {}).get("teamId")
            store.token(team_id)
            record.update(teamId=team_id, flowId="pa-dev-" + key[:32])
            atomic_write_json(path, record, strict_replace=True)
            flow = _flow(record["flowId"], created)
            record["flowFingerprint"] = _flow_fingerprint(flow.model_dump(exclude_none=True))
            atomic_write_json(path, record, strict_replace=True)
            payload = SaveFlow(flow=flow, expectedRevision=0).model_dump(exclude_none=True)
            generic_workflow.save_flow(team_id, flow.id, payload)
            record.update(flowSaved=True, status="flow_saved")
            atomic_write_json(path, record, strict_replace=True)
            return _launch(path, record, args, reused=False)
    except TimeoutError:
        return _failure("busy", "同一请求正在处理中，请稍后使用同一 request_id 核验。", record)
    except Exception:
        return _failure("operation_unconfirmed", "团队操作未确认；已保留幂等记录和已知对象标识，请核验，不要重复创建。", record)


def _resolve_team_id(team_id: str | int, run_id: str, runtime: dict) -> str:
    if isinstance(team_id, str) and team_id:
        return store.token(team_id)
    if type(team_id) is not int and team_id != "":
        raise ValueError("团队标识无效。")
    # Team IDs can consist only of digits; models sometimes serialize them as
    # numbers. Resolve the exact opaque ID through our own run receipt instead
    # of guessing lost leading zeroes or accepting another controller's Team.
    home = directory._workspace_path("personal-assistant-actions", "teams")
    matches = set()
    for index, path in enumerate(home.glob("*.json")):
        if index >= 1000:
            raise ValueError("创建记录过多，请提供字符串团队标识。")
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("ownerAgentId") != runtime["agentId"] or record.get("runId") != run_id:
            continue
        candidate = str(record.get("teamId") or "")
        if team_id != "" and (not candidate.isdigit() or int(candidate) != team_id):
            continue
        matches.add(store.token(candidate))
    if len(matches) != 1:
        raise ValueError("未找到唯一的自有团队运行。")
    return matches.pop()


def team_run_status(team_id: str | int = "", run_id: str = "", wait_seconds: int = 0) -> dict:
    """Read owned workflow state and its final published artifact, never a transcript."""
    try:
        if type(wait_seconds) is not int or not 0 <= wait_seconds <= 30:
            return _failure("invalid_input", "等待时间必须是0到30秒的整数。")
        store.token(run_id)
        runtime = _runtime()
        team_id = _resolve_team_id(team_id, run_id, runtime)
        team = store.team(team_id)
        if team.get("teamSource") != _owner_source(runtime):
            return _failure("not_owned", "仅可读取当前个人助理创建的团队运行。")
        deadline = time.monotonic() + wait_seconds
        while True:
            # Recheck ownership after each wait; Team state can change while a run executes.
            if store.team(team_id).get("teamSource") != _owner_source(runtime):
                return _failure("not_owned", "团队归属已变化，停止读取。")
            run = generic_workflow.get_run(team_id, run_id)
            if run.get("status") != "running" or time.monotonic() >= deadline:
                break
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
        if run.get("teamId") != team_id or run.get("id") != run_id:
            raise ValueError("运行身份不一致。")
        result = _summary(run)
        if run.get("status") == "completed":
            # Workflow artifacts are the dedicated Team deliverables. Do not
            # open arbitrary participant sessions or return full transcripts.
            try:
                artifacts = generic_workflow.artifacts(team_id, run_id).get("artifacts", [])
            except Exception:
                artifacts = []
                result["resultUnavailable"] = True
            if artifacts:
                item = artifacts[-1]
                content = str(item.get("content") or "")
                result["result"] = {"content": content[:4000], "truncated": len(content) > 4000,
                    "sessionId": str(item.get("sessionId") or "")[:160],
                    "turnId": str(item.get("turnId") or "")[:160], "untrustedContent": True}
        return result
    except Exception:
        return _failure("status_unavailable", "无法读取该团队运行，请核对身份与对象标识。")
