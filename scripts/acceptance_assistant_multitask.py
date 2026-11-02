#!/usr/bin/env python3
"""Real delegated parallel reads followed by a result-dependent third task.

The parent runner owns lifecycle and public error recording. This case submits
only human messages; every goal, dispatch and receipt must come from real model
tool events. Journal times, file tool results and arithmetic establish business
acceptance independently of the task status projection.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import secrets
import time

from scripts import acceptance_local_assistant_development as base
from scripts.assistant_acceptance_support import AssistantAcceptanceFixture, tool_calls

require = base.require
AcceptanceFailure = base.AcceptanceFailure
INPUT_DIR = Path("tests/fixtures/assistant_scheduling")
SUCCESS_MARKER = "ASSISTANT_MULTITASK_VERIFIED"


def event_time(event: dict) -> float:
    raw = event.get("timestamp")
    require(isinstance(raw, str) and raw, "journal_timestamp_missing")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise AcceptanceFailure("journal_timestamp_invalid") from None
    require(value.tzinfo is not None, "journal_timestamp_not_qualified")
    return value.timestamp()


def tagged_value(text: str, name: str, expected: int) -> bool:
    plain = re.sub(r"[`*]", "", text)
    matches = re.findall(rf"(?<![A-Za-z0-9_]){re.escape(name)}\s*[=:：]\s*(-?\d+)(?![\w.])", plain)
    # A normal assistant may present the same exact label/value association in
    # a table. Accept the bounded first two cells, never an unlabelled number.
    matches += re.findall(rf"(?m)^\s*\|\s*{re.escape(name)}\s*\|\s*(-?\d+)\s*\|", plain)
    return bool(matches) and all(int(value) == expected for value in matches)


def input_snapshot(path: Path) -> dict:
    require(path.is_file() and not path.is_symlink() and path.stat().st_size < 16000, "fixture_input_invalid")
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
        rows = data["rows"]
        require(isinstance(rows, list) and 1 <= len(rows) <= 16, "fixture_input_invalid")
        require(all(isinstance(row, dict) and type(row.get("quantity")) is int
                    and type(row.get("unit_value")) is int for row in rows), "fixture_input_invalid")
        total = sum(row["quantity"] * row["unit_value"] for row in rows)
    except (ValueError, KeyError, TypeError):
        raise AcceptanceFailure("fixture_input_invalid") from None
    return {"path": path.resolve(), "text": raw.decode("utf-8"), "sha256": hashlib.sha256(raw).hexdigest(),
            "total": total, "rowCount": len(rows)}


def actions(events: list[dict]) -> list[dict]:
    rows = []
    for call in tool_calls(events):
        if call["callName"] not in {"personal_assistant_manage_tool", "personal_assistant_action_tool"}:
            continue
        args = call["args"]
        parameters = base.object_value(args.get("arguments_json") or args.get("parameters"))
        rows.append({**call, "action": args.get("action"), "parameters": parameters})
    return rows


def read_proof(events: list[dict], snapshot: dict) -> dict:
    """Require the actual read's content, not its path or an asserted summary."""
    expected = re.sub(r"\s+", "", snapshot["text"])
    for call in tool_calls(events):
        if call["callName"] != "read_file_tool" or call["status"] in {"failed", "error", "blocked", "cancelled"}:
            continue
        args = call["args"]
        path = args.get("file_path")
        if not isinstance(path, str) or not Path(path).is_absolute() or Path(path).resolve() != snapshot["path"]:
            continue
        output = call["resultText"]
        output = re.sub(r"(?m)^第\s*\d+\s*行\s*\|\s?", "", output)
        if expected in re.sub(r"\s+", "", output):
            return {"inputSha256": snapshot["sha256"], "readCallId": call["callId"],
                    "readResultSha256": hashlib.sha256(call["resultText"].encode()).hexdigest()}
    raise AcceptanceFailure("real_input_file_read_not_observed")


def native_proof(task: dict, events: list[dict], whole_session: list[dict],
                 expected_values: dict[str, int], snapshots: list[dict]) -> dict:
    require(task.get("status") == "succeeded", "native_task_failed")
    starts = [row for row in events if row.get("eventType") == "turn_started"]
    completed = [row for row in events if row.get("eventType") == "turn_completed"]
    users = [row for row in whole_session if row.get("eventType") == "user_message"]
    require(len(users) == 1 and users[0].get("turnId") == task["turnId"], "native_user_admission_not_unique")
    require(len(starts) == 1 and len(completed) == 1, "native_turn_completion_not_unique")
    require(not any(row.get("eventType") in {"turn_failed", "turn_interrupted"} for row in events), "native_turn_failed")
    answer = base.final_answer(events)
    require(all(tagged_value(answer, name, value) for name, value in expected_values.items()), "native_arithmetic_result_incorrect")
    return {"nativeTaskId": task["taskId"], "sessionId": task["sessionId"], "turnId": task["turnId"],
            "nativeStatus": task["status"], "userAdmissions": len(users),
            "startedAt": starts[0]["timestamp"], "completedAt": completed[0]["timestamp"],
            "startEpoch": event_time(starts[0]), "endEpoch": event_time(completed[0]),
            "values": expected_values, "reads": [read_proof(events, snapshot) for snapshot in snapshots]}


def concurrency_and_dependency(first: dict, second: dict, third: dict, receipt_times: list[float],
                               third_dispatch_time: float) -> dict:
    overlap = min(first["endEpoch"], second["endEpoch"]) - max(first["startEpoch"], second["startEpoch"])
    require(overlap > 0, "parallel_native_execution_not_observed")
    require(len(receipt_times) == 2, "successful_prerequisite_receipts_missing")
    ready = max(first["endEpoch"], second["endEpoch"], *receipt_times)
    require(third_dispatch_time >= ready and third["startEpoch"] >= third_dispatch_time,
            "dependent_task_started_before_prerequisites")
    return {"parallelOverlapSeconds": overlap, "parallelExecutionObserved": True,
            "dependencyReadyEpoch": ready, "dependentDispatchEpoch": third_dispatch_time,
            "dependentStartedAfterPrerequisites": True}


def task_message(project_id: str, agent_ids: list[str], goal_id: str, dispatch_ids: list[str],
                 paths: list[Path]) -> str:
    return (
        "这是已授权的真实本机多Agent调度验收。请你自己规划、派遣并核验一个有限目标："
        "两个Agent分别从两个原始输入独立计算加权总额，随后用第三项依赖任务复核并汇总。"
        f"唯一项目 project_id={project_id}；目标A agent_id={agent_ids[0]}，目标B agent_id={agent_ids[1]}。"
        f"保持 goal_id={goal_id}；三项稳定 dispatch_id 依次为 {', '.join(dispatch_ids)}。"
        "先用真实index/describe发现契约，使用delegation_goal_create绑定这两个目标，"
        "permission_profile=read_only，max_tasks=3，ttl_minutes=30。"
        "随后使用dispatch_derived自主编写任务；参数为goal_id/project_id/agent_id/dispatch_id/task/permission_profile，"
        "不要传title。前两项必须先后快速派给不同Agent，全部发完才开始查receipt，不能等第一项完成才派第二项。"
        "目标Agent只读：每项必须用真实read_file_tool读取指定文件的绝对路径、offset=0/max_lines=0；"
        "不能只猜数字，不得执行终端、写文件、调用外部模型、继续派遣或修改权限/配置。"
        f"第一项给目标A，读取 {paths[0]}，对rows每行quantity乘unit_value后求和，"
        "逐行列乘积，再独立复算一次，输出 ALPHA_TOTAL=<真实总额> 和行数。"
        f"第二项给目标B，读取 {paths[1]}，用相同规则独立计算，"
        "逐行列乘积并复算，输出 BETA_TOTAL=<真实总额> 和行数。"
        "你通过receipt（参数只有dispatch_id）分别拿到前两项真实成功结果后，才可创建第三项。"
        f"第三项给目标A，用dispatch_id={dispatch_ids[2]}，任务正文必须包含从两份真实回执取得的"
        "ALPHA_TOTAL=<值>、BETA_TOTAL=<值>；让它再次读取这两个原始绝对路径，独立核对两份中间值，"
        "确认一致后计算 FINAL_TOTAL=ALPHA_TOTAL*BETA_TOTAL+ALPHA_TOTAL-BETA_TOTAL。"
        "第三项回答必须包含三个TOTAL标签及各自真实整数结果。"
        "持续查询原三项receipt直到真实完成；未知时保留原ID，禁止新ID重派，禁止新增第四项。"
        f"你最终回答必须带 {SUCCESS_MARKER}、三个TOTAL标签及实际整数结果，并说明前两项是否确有并行证据。"
        "遇到审批或能力限制如实保留未完成，不宣称成功。不要创建Agent或修改其他文件。"
    )


def run_case(fixture: AssistantAcceptanceFixture, evidence: dict, timeout: float = 900) -> None:
    backend = fixture.start_backend()
    agent_ids = [fixture.create_agent("Scheduling independent alpha"), fixture.create_agent("Scheduling independent beta")]
    paths = [fixture.source / INPUT_DIR / name for name in ("alpha.json", "beta.json")]
    snapshots = [input_snapshot(path) for path in paths]
    for path in paths:
        require(bool(base.git(fixture.source, "ls-files", "--error-unmatch", path.relative_to(fixture.source).as_posix()).strip()),
                "fixture_input_not_tracked")
    totals = {"ALPHA_TOTAL": snapshots[0]["total"], "BETA_TOTAL": snapshots[1]["total"]}
    totals["FINAL_TOTAL"] = totals["ALPHA_TOTAL"] * totals["BETA_TOTAL"] + totals["ALPHA_TOTAL"] - totals["BETA_TOTAL"]
    generation = secrets.token_hex(6)
    goal_id = "parallel-goal-" + generation
    dispatch_ids = [f"parallel-{generation}-{name}" for name in ("alpha", "beta", "combine")]
    evidence.update(goalId=goal_id, projectId=backend.project_id, agentIds=agent_ids, dispatchIds=dispatch_ids,
                    inputHashes=[snapshot["sha256"] for snapshot in snapshots], expectedValues=totals,
                    approvalCount=0, reminders=0, nativeTasks=[])
    fixture.start_host()
    fixture.send(task_message(backend.project_id, agent_ids, goal_id, dispatch_ids, paths), request_id=goal_id)
    deadline = time.monotonic() + timeout
    last_reminder = time.monotonic()
    tasks: dict[str, dict] = {}
    while time.monotonic() < deadline:
        require(fixture.host_process is not None and fixture.host_process.poll() is None, "assistant_host_exited")
        fixture.assert_no_approvals()
        dispatches = fixture.dispatches()
        require(all(row.get("dispatchId") in dispatch_ids for row in dispatches), "unexpected_extra_dispatch")
        require(len({row.get("dispatchId") for row in dispatches}) == len(dispatches), "duplicate_dispatch_record")
        for dispatch in dispatches:
            index = dispatch_ids.index(dispatch["dispatchId"])
            require(dispatch.get("projectId") == backend.project_id
                    and dispatch.get("agentId") == agent_ids[0 if index == 2 else index], "dispatch_target_mismatch")
            if dispatch.get("nativeTaskId"):
                task = fixture.task(dispatch["nativeTaskId"])
                tasks[dispatch["dispatchId"]] = task
                if task.get("status") in base.TERMINAL:
                    require(task["status"] == "succeeded", "native_task_failed")
        evidence["nativeTasks"] = [{"dispatchId": dispatch_id, "nativeTaskId": task.get("taskId"),
                                    "status": task.get("status")} for dispatch_id, task in tasks.items()]
        events = fixture.assistant_events()
        answer = base.final_answer(events)
        if len(tasks) == 3 and all(task.get("status") == "succeeded" for task in tasks.values()) \
                and SUCCESS_MARKER in answer and all(tagged_value(answer, name, value) for name, value in totals.items()):
            break
        starts = {row.get("turnId") for row in events if row.get("eventType") == "turn_started"}
        ends = {row.get("turnId") for row in events if row.get("eventType") in {"turn_completed", "turn_failed", "turn_interrupted"}}
        if evidence["reminders"] < 3 and time.monotonic() - last_reminder > 45 and starts and starts <= ends:
            fixture.send(f"继续原goal_id={goal_id}，仅使用原三项dispatch_id：{', '.join(dispatch_ids)}。"
                         "先核对已保存任务，只补尚未派出的原ID，已派的只查receipt；"
                         "依赖两项真实成功回执后再做第三项，不要新goal或新ID。真实完成后按原约定标签汇总。",
                         request_id=f"{goal_id}-continue-{evidence['reminders']}")
            evidence["reminders"] += 1
            last_reminder = time.monotonic()
        time.sleep(2)
    else:
        raise AcceptanceFailure("multitask_model_acceptance_timeout")
    require(len({task.get("taskId") for task in tasks.values()}) == 3, "native_tasks_not_distinct")
    task_records = list((backend.runtime_root / "local_assistant_tasks" / "tasks").glob("*.json"))
    require({path.stem for path in task_records} == {task["taskId"] for task in tasks.values()}, "unexpected_native_task_records")
    proofs = []
    for index, dispatch_id in enumerate(dispatch_ids):
        task = tasks[dispatch_id]
        expected = totals if index == 2 else {("ALPHA_TOTAL", "BETA_TOTAL")[index]: snapshots[index]["total"]}
        proof = native_proof(task, fixture.target_events(task), base.journal_events(fixture.home, task["sessionId"]),
                             expected, snapshots if index == 2 else [snapshots[index]])
        proof["dispatchId"] = dispatch_id
        proofs.append(proof)
    calls = actions(fixture.assistant_events())
    goals = [row for row in calls if row["action"] == "delegation_goal_create" and row["result"].get("goalId") == goal_id]
    require(goals and all(row["parameters"].get("goal_id") == goal_id for row in goals), "real_delegation_goal_not_observed")
    expected_targets = {(backend.project_id, agent_id) for agent_id in agent_ids}
    for row in goals:
        args = row["parameters"]
        require({(target.get("project_id"), target.get("agent_id")) for target in args.get("targets", [])} == expected_targets
                and args.get("permission_profile") == "read_only" and args.get("max_tasks") == 3
                and args.get("ttl_minutes") == 30,
                "delegation_goal_envelope_mismatch")
    derived: dict[str, dict] = {}
    for row in calls:
        if row["action"] == "dispatch_derived" and row["result"].get("nativeTaskId"):
            args = row["parameters"]
            dispatch_id = args.get("dispatch_id")
            require(dispatch_id in dispatch_ids and args.get("goal_id") == goal_id
                    and args.get("permission_profile") == "read_only", "derived_goal_binding_mismatch")
            require(row["result"].get("nativeTaskId") == tasks[dispatch_id]["taskId"], "derived_native_binding_mismatch")
            if dispatch_id in derived:
                require(args == derived[dispatch_id]["parameters"], "derived_retry_payload_changed")
            else:
                derived[dispatch_id] = row
    require(set(derived) == set(dispatch_ids), "real_derived_dispatch_not_observed")
    third = derived[dispatch_ids[2]]
    require(all(tagged_value(third["parameters"].get("task", ""), name, totals[name])
                for name in ("ALPHA_TOTAL", "BETA_TOTAL")), "derived_task_missing_real_intermediate_values")
    third_time = event_time({"timestamp": third["startedAt"]})
    require(type(third["startedSequence"]) is int, "assistant_tool_sequence_missing")
    receipt_times = []
    for dispatch_id in dispatch_ids[:2]:
        receipts = [row for row in calls if row["action"] == "receipt" and row["parameters"] == {"dispatch_id": dispatch_id}
                    and row["result"].get("nativeTaskId") == tasks[dispatch_id]["taskId"]
                    and (row["result"].get("receipt") or {}).get("status") == "succeeded"
                    and type(row["finishedSequence"]) is int and row["finishedSequence"] < third["startedSequence"]]
        require(receipts, "successful_prerequisite_receipts_missing")
        receipt_times.append(min(event_time({"timestamp": row["finishedAt"]}) for row in receipts))
    evidence.update(concurrency_and_dependency(*proofs, receipt_times, third_time))
    # A serialized first receipt followed by second dispatch is not parallel scheduling.
    second_sent = event_time({"timestamp": derived[dispatch_ids[1]]["finishedAt"]})
    receipt_starts = [event_time({"timestamp": row["startedAt"]}) for row in calls
                      if row["action"] == "receipt" and row["parameters"].get("dispatch_id") in dispatch_ids[:2]]
    require(receipt_starts and second_sent <= min(receipt_starts), "receipt_queried_before_both_dispatches")
    receipt_sequences = [row["startedSequence"] for row in calls if row["action"] == "receipt"
                         and row["parameters"].get("dispatch_id") in dispatch_ids[:2]]
    second_sequence = derived[dispatch_ids[1]]["finishedSequence"]
    require(type(second_sequence) is int and all(type(value) is int and value > second_sequence
                for value in receipt_sequences), "receipt_queried_before_both_dispatches")
    require(all(input_snapshot(snapshot["path"])["sha256"] == snapshot["sha256"] for snapshot in snapshots), "fixture_input_changed")
    fixture.assert_no_approvals()
    for agent_id in agent_ids:
        policy = fixture.backend(backend.project_id, "/api/agents/" + agent_id).get("toolPolicy") or {}
        require(all(policy.get(key) == [] for key in ("allowedTools", "preferredTools", "readScopes", "writeScopes")),
                "target_permanent_tool_policy_changed")
    evidence.update(nativeTasks=proofs, goalToolResultCount=len(goals), derivedDispatchCount=len(derived),
                    modelRequests=base.model_requests(fixture.home), assistantFinalValues=totals,
                    assistantReturnedVerifiedResult=True, ordinaryAgentPoliciesRemainEmpty=True,
                    prerequisiteReceiptSequenceVerified=True)
    require(all(value > 0 for value in evidence["modelRequests"].values()), "real_model_requests_not_observed")
