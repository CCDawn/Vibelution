"""Bounded Research metadata reads and the existing formal command owner.

No human prompt, decision body, artifact, Session or checkpoint body is read.
Native receipt lookup is read-only: unknown acknowledgements never authorize a
second submit. All command authority comes from the server operator context.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from pydantic import ValidationError

from . import runtime_operations as runtime
from .research_contracts import ResearchCommand, ResearchCommandResponse, ResearchReadQuery, ResearchReadResponse
from .service import ManagementError

_REASON = "launcher_assistant_operator_control"
_TERMINAL = {"succeeded", "failed", "cancelled", "archived"}
_LATEST = (" FROM node_attempts n WHERE n.run_id=? AND NOT EXISTS "
           "(SELECT 1 FROM node_attempts later WHERE later.run_id=n.run_id "
           "AND later.node_id=n.node_id AND later.attempt>n.attempt)")
_HUMAN = (" FROM human_tasks h LEFT JOIN node_attempts n ON n.node_run_id=h.node_run_id "
          "AND n.run_id=h.run_id WHERE h.run_id=? AND h.status='pending'")


def _request(model, parameters):
    try:
        return model.model_validate(runtime._parameters(parameters))
    except (ValidationError, ValueError, TypeError):
        raise ManagementError("INVALID_INPUT", 422) from None


def _run(repo, reference):
    row = repo.execute("SELECT run_id,team_id,workflow_id,status,run_version,"
        "EXISTS(SELECT 1 FROM node_attempts a WHERE a.run_id=workflow_runs.run_id),last_event_sequence,active_node_id "
        "FROM workflow_runs WHERE run_id=? LIMIT 1", (reference.run_id,)).fetchone()
    if row is None or row[1:3] != (reference.team_id, reference.flow_id):
        raise ManagementError("run_not_found", 404)
    if type(row[4]) is not int or not 1 <= row[4] <= 2**63 - 1:
        raise ManagementError("RESEARCH_UNAVAILABLE", 503)
    return {"runId": row[0], "teamId": row[1], "flowId": row[2], "status": row[3], "revision": row[4],
            "_hasAttempts": bool(row[5]), "lastEventSequence": row[6], "activeNodeId": row[7]}


def _store(gateway):
    gateway._owners()
    try:
        return runtime._research_store(gateway)
    except ManagementError:
        raise
    except Exception:
        raise ManagementError("RESEARCH_UNAVAILABLE", 503) from None


def _can_control(gateway):
    if runtime._operator_context() is None:
        return False
    try:
        runtime._research_command_owner(gateway)
        return True
    except Exception:
        return False


def _checkpoint_ref(gateway, store, parameters, node_id, task_id, revision):
    from core.web.services.team_workflow.research_runtime import formal_read_runtime
    from core.web.services.team_workflow.research_runtime.query_service import WorkflowQueryError
    try:
        owner = formal_read_runtime.get_query_service()
        if Path(owner._store.path).resolve() != Path(store.path).resolve():
            raise ManagementError("TARGET_BINDING_CHANGED", 409)
        ref = owner.get_revise_checkpoint_ref(team_id=parameters.team_id, run_id=parameters.run_id,
            workflow_id=parameters.flow_id, node_id=node_id, task_id=task_id, expected_run_version=revision)
    except WorkflowQueryError as exc:
        raise ManagementError(exc.code, 409 if exc.code in {"run_version_conflict", "command_not_allowed"} else 404) from None
    except ManagementError:
        raise
    except Exception:
        return None
    if ref is None:
        return None
    expected = {"runId": parameters.run_id, "teamId": parameters.team_id, "flowId": parameters.flow_id,
                "nodeId": node_id, "taskId": task_id, "revision": str(revision)}
    if not isinstance(ref, dict) or set(ref) != {*expected, "checkpointId"} or any(ref[key] != value for key, value in expected.items()):
        raise ManagementError("TARGET_BINDING_CHANGED", 409)
    try:
        runtime._token(ref["checkpointId"])
    except ValueError:
        raise ManagementError("TARGET_BINDING_CHANGED", 409) from None
    return ref


def _hash_metadata(snapshot, value):
    snapshot.update(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                               allow_nan=False).encode("utf-8"))
    snapshot.update(b"\n")


def _directory_page(repo, sql, run_id, offset, limit, snapshot, kind):
    """Hash the full ordered metadata cursor, retaining only the requested page."""
    rows, total = [], 0
    _hash_metadata(snapshot, kind)
    for row in repo.execute(sql, (run_id,)):
        # A pending task with no attempt in this run cannot silently disappear
        # from a supposedly complete inventory (the query uses a LEFT JOIN).
        if any(value is None for value in row) or total >= 1_000_000:
            raise ManagementError("RESEARCH_UNAVAILABLE", 503)
        _hash_metadata(snapshot, row)
        if offset <= total < offset + limit:
            rows.append(row)
        total += 1
    _hash_metadata(snapshot, total)
    return rows, total


def read(gateway, parameters):
    query = _request(ResearchReadQuery, parameters)
    store = _store(gateway)
    control = _can_control(gateway)

    def metadata(repo):
        run = _run(repo, query)
        if query.expected_revision and str(run["revision"]) != query.expected_revision:
            raise ManagementError("RESEARCH_REVISION_CHANGED", 409)
        snapshot = hashlib.sha256()
        _hash_metadata(snapshot, ["research_directory_v1", run, control])
        nodes, node_total = _directory_page(repo,
            "SELECT n.node_id,n.node_run_id,n.status,n.attempt" + _LATEST + " ORDER BY n.node_id,n.node_run_id",
            query.run_id, query.node_offset, query.limit, snapshot, "latest_nodes")
        tasks, task_total = _directory_page(repo,
            "SELECT h.task_id,n.node_id,h.node_run_id,h.status" + _HUMAN + " ORDER BY h.task_id",
            query.run_id, query.human_task_offset, query.limit, snapshot, "pending_human_tasks")
        version = snapshot.hexdigest()
        if query.expected_snapshot is not None and query.expected_snapshot != version:
            raise ManagementError("RESEARCH_SNAPSHOT_CHANGED", 409)
        return run, nodes, node_total, tasks, task_total, version

    try:
        run, nodes, node_total, tasks, task_total, snapshot = store.read(metadata)
        active = run["status"] not in _TERMINAL
        result = {"operation": runtime._project("research_run", {**run, "_operatorControl": control}), "snapshot": snapshot,
            "nodes": [{"nodeId": row[0], "nodeRunId": row[1], "status": row[2], "attempt": row[3],
                "commands": ["retry_node"] if control and active and row[2] in {"failed", "blocked", "cancelled"} else []}
                for row in nodes],
            "humanTasks": [{"taskId": row[0], "nodeId": row[1], "nodeRunId": row[2], "status": row[3],
                "commands": ["resolve_human_task"] if control and active else [],
                "decisions": ["accept", "reject"] if control and active else [], "checkpointId": ""} for row in tasks],
            "commands": ["reconcile_run"] if control and run["status"] in {"blocked", "reconciliation_required"} else [],
            "nodeOffset": query.node_offset, "humanTaskOffset": query.human_task_offset,
            "nodeTotal": node_total, "humanTaskTotal": task_total,
            "nextNodeOffset": query.node_offset + len(nodes) if query.node_offset + len(nodes) < node_total else None,
            "nextHumanTaskOffset": query.human_task_offset + len(tasks)
                if query.human_task_offset + len(tasks) < task_total else None,
            "complete": True, "untrustedContent": True}
        if control and active:
            for task in result["humanTasks"]:
                ref = _checkpoint_ref(gateway, store, query, task["nodeId"], task["taskId"], run["revision"])
                if ref is not None:
                    task["checkpointId"] = ref["checkpointId"]
                    task["decisions"].append("revise")
        # Retain exact offsets when long native identities reduce a page below
        # the requested limit. Never truncate an identity or silently lose it.
        while len(json.dumps(result, ensure_ascii=False)) > 3000:
            key = max((key for key in ("nodes", "humanTasks") if len(result[key]) > 1),
                      key=lambda key: len(json.dumps(result[key])), default=None)
            if key is None:
                break
            result[key].pop()
        result["nextNodeOffset"] = query.node_offset + len(result["nodes"]) \
            if query.node_offset + len(result["nodes"]) < node_total else None
        result["nextHumanTaskOffset"] = query.human_task_offset + len(result["humanTasks"]) \
            if query.human_task_offset + len(result["humanTasks"]) < task_total else None
        return ResearchReadResponse.model_validate(result).model_dump()
    except ManagementError:
        raise
    except Exception:
        raise ManagementError("RESEARCH_UNAVAILABLE", 503) from None


def _native_request(parameters, request_id):
    from core.research.workflow.contracts import ActorRef, CommandRequest, WorkflowCommandKind
    try:
        runtime._token(request_id)
    except ValueError:
        raise ManagementError("INVALID_INPUT", 422) from None
    operator = runtime._operator_context()
    if operator is None:
        raise ManagementError("command_forbidden", 403)
    payload = {"reason": _REASON}
    if parameters.command == "resolve_human_task":
        payload.update(taskId=parameters.task_id, decision=parameters.decision)
        if parameters.decision == "revise":
            payload.update(fromNodeId=parameters.node_id, checkpointId=parameters.checkpoint_id)
    return CommandRequest(command_id="management-" + runtime._fingerprint(request_id)[:32],
        run_id=parameters.run_id, team_id=parameters.team_id, command=WorkflowCommandKind(parameters.command),
        node_id=parameters.node_id or None, expected_run_version=int(parameters.expected_revision),
        idempotency_key=request_id, payload=payload, requested_by=ActorRef("user", operator.operator_id),
        requested_at_ms=int(time.time() * 1000))


def _target(repo, parameters):
    run = _run(repo, parameters)
    if parameters.command == "retry_node":
        if repo.execute("SELECT 1 FROM node_attempts WHERE run_id=? AND node_id=? LIMIT 1",
                        (parameters.run_id, parameters.node_id)).fetchone() is None:
            raise ManagementError("node_not_found", 404)
    elif parameters.command == "resolve_human_task":
        if repo.execute("SELECT 1 FROM human_tasks h JOIN node_attempts n ON n.node_run_id=h.node_run_id "
            "AND n.run_id=h.run_id WHERE h.run_id=? AND h.task_id=? AND n.node_id=? LIMIT 1",
            (parameters.run_id, parameters.task_id, parameters.node_id)).fetchone() is None:
            raise ManagementError("task_not_found", 404)
    return run


def _proof(gateway, store, parameters, request):
    if Path(_store(gateway).path).resolve() != Path(store.path).resolve():
        raise ManagementError("TARGET_BINDING_CHANGED", 409)
    record = store.get_command_by_idempotency(parameters.run_id, request.idempotency_key)
    if record is None:
        raise ManagementError("OPERATION_UNCONFIRMED", 503)
    if record.request_hash != request.request_hash():
        raise ManagementError("idempotency_conflict", 409)
    if (record.run_id != parameters.run_id or record.team_id != parameters.team_id
            or record.command_kind != parameters.command or (record.node_id or "") != parameters.node_id
            or record.expected_run_version != int(parameters.expected_revision) or record.idempotency_key != request.idempotency_key
            or record.status != "accepted" or type(record.accepted_run_version) is not int
            or not int(parameters.expected_revision) < record.accepted_run_version <= 2**63 - 1):
        raise ManagementError("OPERATION_UNCONFIRMED", 503)
    run = store.read(lambda repo: _run(repo, parameters))
    if run["revision"] < record.accepted_run_version:
        raise ManagementError("OPERATION_UNCONFIRMED", 503)
    child_run_id = ""
    if parameters.decision == "revise":
        children = store.read(lambda repo: repo.execute(
            "SELECT r.run_id,r.team_id,r.workflow_id FROM workflow_runs r JOIN node_attempts a ON a.run_id=r.run_id "
            "WHERE r.parent_run_id=? AND r.forked_from_checkpoint_id=? AND a.command_id=? AND a.node_id=? "
            "AND a.attempt=1 LIMIT 2", (parameters.run_id, parameters.checkpoint_id, record.command_id,
                                       parameters.node_id)).fetchall())
        if len(children) != 1 or children[0][1:] != (parameters.team_id, parameters.flow_id):
            raise ManagementError("OPERATION_UNCONFIRMED", 503)
        child_run_id = children[0][0]
    result = {"operation": runtime._project("research_run", {**run, "_operatorControl": _can_control(gateway)}),
        "command": parameters.command, "accepted": True, "revisionCheck": "native_cas", "untrustedContent": True,
        "receipt": {"commandId": record.command_id, "runId": record.run_id, "teamId": record.team_id,
            "flowId": parameters.flow_id, "command": record.command_kind, "requestId": record.idempotency_key,
            "expectedRevision": str(record.expected_run_version), "acceptedRevision": str(record.accepted_run_version),
            "nodeId": parameters.node_id, "taskId": parameters.task_id, "decision": parameters.decision,
            "checkpointId": parameters.checkpoint_id, "childRunId": child_run_id}}
    return ResearchCommandResponse.model_validate(result).model_dump()


def read_receipt(gateway, parameters, *, request_id=""):
    """Verify the stored native request hash without resubmitting any command."""
    parameters = _request(ResearchCommand, parameters)
    request = _native_request(parameters, request_id)
    store = _store(gateway)
    try:
        return _proof(gateway, store, parameters, request)
    except ManagementError:
        raise
    except Exception:
        raise ManagementError("OPERATION_UNCONFIRMED", 503) from None


def command(gateway, parameters, *, request_id=""):
    parameters = _request(ResearchCommand, parameters)
    request = _native_request(parameters, request_id)
    store = _store(gateway)
    # Exact native receipts are sufficient on replay. Never call submit again,
    # even if the native command owner's original acknowledgement was lost.
    try:
        if store.get_command_by_idempotency(parameters.run_id, request_id) is not None:
            return read_receipt(gateway, parameters, request_id=request_id)
        store.read(lambda repo: _target(repo, parameters))
        if parameters.decision == "revise":
            ref = _checkpoint_ref(gateway, store, parameters, parameters.node_id, parameters.task_id,
                                  int(parameters.expected_revision))
            if ref is None:
                raise ManagementError("COMMAND_UNAVAILABLE", 409)
            if ref["checkpointId"] != parameters.checkpoint_id:
                raise ManagementError("TARGET_BINDING_CHANGED", 409)
        owner = runtime._research_command_owner(gateway)
    except ManagementError:
        raise
    except Exception:
        raise ManagementError("RESEARCH_UNAVAILABLE", 503) from None
    from core.research.workflow.ledger import CommandNotAllowedError, IdempotencyConflictError, RunVersionConflictError
    from core.web.services.team_workflow.research_runtime import command_service as native
    try:
        receipt = owner.submit(request)
    except native.CommandForbiddenError:
        raise ManagementError("command_forbidden", 403) from None
    except (RunVersionConflictError, IdempotencyConflictError, CommandNotAllowedError) as exc:
        raise ManagementError(exc.code, 409) from None
    except native.RunNotFoundError:
        raise ManagementError("run_not_found", 404) from None
    except native.TeamScopeMismatchError:
        raise ManagementError("team_scope_mismatch", 404) from None
    except native.NodeNotReadyError:
        raise ManagementError("node_not_ready", 412) from None
    except native.HumanTaskNotFoundError:
        raise ManagementError("task_not_found", 404) from None
    except native.InvalidHumanTaskStateError:
        raise ManagementError("invalid_human_task_state", 409) from None
    except native.WorkflowDefinitionUnavailableError as exc:
        raise ManagementError(exc.code, 422) from None
    except native.WorkflowCommandError:
        raise ManagementError("unknown_command", 422) from None
    except Exception:
        raise ManagementError("OPERATION_UNCONFIRMED", 503) from None
    try:
        if (receipt.run_id != parameters.run_id or receipt.idempotency_key != request_id
                or receipt.status != "accepted"):
            raise ManagementError("OPERATION_UNCONFIRMED", 503)
        return _proof(gateway, store, parameters, request)
    except Exception:
        # A read/validation failure after submit cannot prove no side effect.
        raise ManagementError("OPERATION_UNCONFIRMED", 503) from None
