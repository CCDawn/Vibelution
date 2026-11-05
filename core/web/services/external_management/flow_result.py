"""Read the original flow_start's final output without workflow/Session repair."""
from __future__ import annotations

import json
from pathlib import Path

from core.assistant_runtime.migration_io import check_path
from core.infrastructure.tool_result import project_tool_result_for_model
from core.web.services.team_workflow.generic import service as workflows

from .contracts import FlowResultResponse
from .flow_contracts import FlowStart
from .state_snapshot import ExistingStateSnapshot
from .store import digest
from . import team_result

_MAX_RUN_BYTES = 2 * 1024 * 1024


def _response(request_id, query, *, status="unavailable", run_status="unknown"):
    return FlowResultResponse(requestId=request_id, teamId=query.team_id, flowId=query.flow_id,
        runId=query.run_id, status=status, runStatus=run_status,
        terminal=run_status in {"completed", "failed", "stopped"},
        text="", truncated=False, untrustedContent=True).model_dump()


def read_flow_result(native, store, grant, request_id, query):
    """Existing authorities only; authorization is checked by the service twice."""
    unavailable = _response(request_id, query)
    try:
        return _read(native, store, grant, request_id, query)
    except Exception:  # noqa: BLE001 -- unavailable evidence never exposes content or paths
        return unavailable


def _read(native, store, grant, request_id, query):
    root = Path(native.project_root).resolve()
    state = ExistingStateSnapshot(root, native._owners(), pin_workspace=True)
    key = digest([grant["subject_id"], "flow_start", request_id])
    request_path = store.path("requests", key)
    check_path(request_path)
    record = state.read_json(request_path, strict=True, max_bytes=64 * 1024)
    parameters = FlowStart.model_validate(record["parameters"]).model_dump()
    marker = {"subjectType": "operator", "subjectId": grant["subject_id"], "requestKey": key,
              "requestFingerprint": digest(parameters)}
    if (record.get("action") != "flow_start" or record.get("requestId") != request_id
            or record.get("binding") != grant["binding"] or record.get("marker") != marker
            or record.get("fingerprint") != digest(parameters) or record.get("failure")
            or (query.team_id, query.flow_id) != (parameters["team_id"], parameters["flow_id"])):
        raise ValueError("original request unavailable")
    native_key = "ops-flow-" + digest([str(root), "flow_start", key])
    run_id = "run-" + workflows.digest([query.flow_id, native_key])[:40]
    if query.run_id != run_id:
        raise ValueError("original run mismatch")
    teams_path = state.path("teams", "teams.json")
    run_path = state.path("teams", query.team_id, "generic-workflows", "runs", run_id + ".json")
    check_path(teams_path)
    check_path(run_path)
    teams = state.read_json(teams_path, strict=True)
    matches = [row for row in teams["teams"] if isinstance(row, dict) and row.get("teamId") == query.team_id]
    if len(matches) != 1 or matches[0].get("status") == "archived":
        raise ValueError("team unavailable")
    raw = state.read_json(run_path, strict=True, max_bytes=_MAX_RUN_BYTES)
    run = workflows.public(raw)
    if (run["id"] != run_id or run["teamId"] != query.team_id or run["flow"]["id"] != query.flow_id
            or type(raw["flow"].get("revision")) is not int or run["flow"]["revision"] != parameters["expectedRevision"]
            or run["values"] != parameters["values"]
            or raw.get("_createFingerprint") != workflows.digest(
                [query.flow_id, parameters["expectedRevision"], parameters["values"]])
            or type(raw.get("revision")) is not int or run["revision"] < 1
            or type(raw.get("current")) is not int or not 0 <= run["current"] <= len(run["flow"]["steps"])
            or type(raw.get("stopRequested")) is not bool
            or not run["flow"]["steps"] or len(run["attempts"]) > workflows.MAX_ATTEMPTS or workflows.supervised(run)):
        raise ValueError("admission or native run unavailable")

    def verify_source():
        state.verify_workspace()
        if (state.read_json(request_path, strict=True, max_bytes=64 * 1024) != record
                or state.read_json(teams_path, strict=True) != teams
                or state.read_json(run_path, strict=True, max_bytes=_MAX_RUN_BYTES) != raw):
            raise ValueError("original authority changed")

    if run["status"] != "completed":
        verify_source()
        return _response(request_id, query, status="partial", run_status=run["status"])
    if run["stopRequested"] or run["current"] != len(run["flow"]["steps"]):
        raise ValueError("incomplete native run")
    # Native output steps may be passive markers. Only the last executable
    # node's latest attempt owns a final answer; never expose prior prompts,
    # source-supervisor Sessions, or every intermediate artifact.
    steps = [step for step in run["flow"]["steps"] if workflows.executable(step)]
    answer = {"text": "", "truncated": False}
    if not steps:
        verify_source()
    else:
        step = steps[-1]
        attempts = [item for item in run["attempts"] if item["nodeId"] == step["id"]]
        if not attempts or attempts[-1] != run["attempts"][-1]:
            raise ValueError("final attempt unavailable")
        attempt = attempts[-1]
        members = matches[0].get("members")
        if (not isinstance(members, list) or sum(isinstance(row, dict) and row.get("agentId") == step["owner"]
                and row.get("status") != "archived" for row in members) != 1
                or attempt["agentId"] != step["owner"] or attempt["status"] != "completed"
                or type(raw["attempts"][-1].get("number")) is not int or attempt["number"] != len(attempts)
                or attempt["key"] != "gw-" + workflows.digest([str(run_path), run_id, step["id"], attempt["number"]])[:48]
                or any(not isinstance(attempt[field], str) or not team_result._TOKEN.fullmatch(attempt[field])
                       for field in ("agentId", "sessionId", "turnId", "originTurnId"))):
            raise ValueError("final attempt identity mismatch")
        answer = team_result.read_attempt_result(state, root, attempt, verify_source=verify_source)
    cleaned = json.loads(project_tool_result_for_model(json.dumps({"text": answer["text"]}, ensure_ascii=False)))["text"]
    cleaned.encode("utf-8")  # Escaped invalid Unicode must not escape through HTTP/model serialization.
    return FlowResultResponse(requestId=request_id, teamId=query.team_id, flowId=query.flow_id, runId=run_id,
        status="available" if cleaned else "empty", runStatus="completed", terminal=True,
        text=cleaned, truncated=answer["truncated"] if cleaned else False,
        textFiltered=cleaned != answer["text"], untrustedContent=True).model_dump()
