"""Metadata-only runtime discovery and delegation to the original command owners.

No read repairs an index, hydrates a Session, or interprets task content. Version
fingerprints on owners without CAS are preflight checks, never atomic fences.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from .service import ManagementError

KINDS = ("session_turn", "session_queue", "runtime_task", "external_task", "team_run", "supervised_run",
         "self_evolution_run", "research_run")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_STATUSES = frozenset({"idle", "created", "queued", "sent", "running", "waiting", "waiting_human",
    "waiting_external", "awaiting_approval", "paused", "pausing", "pause_requested", "stopping",
    "cancelling", "stop_unconfirmed", "done", "completed", "succeeded", "success", "failed",
    "error", "stopped", "cancelled", "canceled", "blocked", "closed", "dropped", "exited",
    "incomplete", "stale", "superseded", "timed_out", "timeout", "budget_exhausted",
    "reconciliation_required", "archived", "needs_continue", "paused_limit", "partial", "settled"})
_TERMINAL = _STATUSES - {"idle", "created", "queued", "sent", "running", "waiting", "waiting_human",
    "waiting_external", "awaiting_approval", "paused", "pausing", "pause_requested", "stopping",
    "cancelling", "stop_unconfirmed"}
_TERMINAL_BY_KIND = {"session_queue": {"cancelled"}, "team_run": {"completed", "failed", "stopped"},
    "external_task": {"succeeded", "failed", "cancelled", "timed_out"},
    "research_run": {"succeeded", "failed", "cancelled", "archived"}}
_KNOWN_BY_KIND = {
    "session_queue": {"queued", "starting", "paused", "blocked", "cancelled"},
    "runtime_task": {"queued", "sent", "running", "idle", "blocked", "canceled", "cancelled", "closed",
        "completed", "dropped", "error", "exited", "failed", "incomplete", "stale", "stopped",
        "superseded", "timed_out", "timeout"},
    "external_task": {"queued", "running", "awaiting_approval", "cancelling", "stop_unconfirmed",
        "succeeded", "failed", "cancelled", "timed_out"},
    "team_run": {"running", "waiting", "completed", "failed", "stopped"},
    "supervised_run": {"queued", "running", "stopping", "paused", "done", "failed", "cancelled"},
    "self_evolution_run": {"queued", "running", "stopping", "paused", "done", "failed", "cancelled"},
    "research_run": {"created", "running", "waiting_human", "blocked", "paused", "reconciliation_required",
        "succeeded", "failed", "cancelled", "archived"}}
_REFS = ("session_id", "team_id", "flow_id")
_MAX_FILES = 10000
_MAX_BYTES = 16 * 1024 * 1024


def _token(value):
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError("Invalid metadata identity")
    return value


def _parameters(value):
    return value.model_dump() if hasattr(value, "model_dump") else dict(value)


def _reference(kind, resource_id, refs):
    try:
        if kind not in KINDS or set(refs) - set(_REFS):
            raise ValueError("Unknown operation reference")
        _token(resource_id)
        refs = {key: value for key, value in refs.items() if value not in (None, "")}
        for value in refs.values():
            _token(value)
        required, allowed = ({"session_id"}, {"session_id"}) if kind in {"session_turn", "session_queue"} else (
            ({"team_id"}, {"team_id", "flow_id"}) if kind == "team_run" else (
            ({"team_id", "flow_id"}, {"team_id", "flow_id"}) if kind == "research_run" else (set(), set())))
        if not required <= set(refs) or set(refs) - allowed:
            raise ValueError("Invalid operation reference")
        return refs
    except (ValueError, TypeError):
        raise ManagementError("INVALID_INPUT", 422) from None


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _operator_context():
    from core.web.services.team_workflow.research_runtime.operator_authorization import current_server_operator
    from core.web.services.team_workflow.research_runtime.operator_permissions import operator_has_privileged_role
    operator = current_server_operator()
    return operator if operator and operator.operator_id and operator_has_privileged_role(operator.roles) else None


def _progress_fingerprint(kind, raw):
    """Hash only existing owner progress facts; heartbeat/CAS is not progress."""
    def counter(value):
        return type(value) is int and 0 <= value <= 2**63 - 1

    if kind == "team_run" and counter(raw.get("current")):
        attempts = raw.get("attempts")
        if not isinstance(attempts, list) or len(attempts) > 10000:
            return None
        facts = []
        for attempt in attempts:
            if (not isinstance(attempt, dict) or not counter(attempt.get("number"))
                    or attempt["number"] < 1 or attempt.get("status") not in {
                        "dispatching", "running", "completed", "failed", "stopped"}):
                return None
            try:
                facts.append([_token(attempt.get("nodeId")), attempt["number"], attempt["status"]])
            except ValueError:
                return None
        if raw.get("recovery") is not None:
            from .team_recovery_control import metadata
            try:
                recovery = metadata(raw)
            except (ValueError, TypeError):
                return None
            return _fingerprint([kind, raw["current"], facts, recovery])
        return _fingerprint([kind, raw["current"], facts])
    if kind == "research_run" and counter(raw.get("lastEventSequence")):
        node = raw.get("activeNodeId") or ""
        try:
            if node:
                _token(node)
        except ValueError:
            return None
        return _fingerprint([kind, raw["lastEventSequence"], node])
    # The remaining owner snapshots do not carry a verified business-progress
    # cursor. Do not upgrade arbitrary progress-shaped fields into authority.
    return None


def _project(kind, raw):
    """Closed projection: even values in metadata columns must satisfy grammar."""
    key = "taskId" if kind in {"runtime_task", "external_task"} else "id" if kind == "team_run" else "runId"
    rid = _token(raw.get(key))
    if any(key in raw and type(raw[key]) is not bool for key in ("pauseRequested", "stopRequested")):
        raise ValueError("Invalid native control flag")
    if kind == "runtime_task" and raw.get("kind", "cli_agent") not in {"cli_agent", "child_session", "research_task"}:
        raise ValueError("Unknown native task kind")
    if kind == "runtime_task" and raw.get("stopInitiator") not in (None, "", "user", "model"):
        raise ValueError("Invalid native stop initiator")
    status = raw.get("status")
    if not isinstance(status, str) or status not in _KNOWN_BY_KIND.get(kind, _STATUSES):
        status = "unknown"
    elif kind in {"session_turn", "supervised_run", "self_evolution_run"} and (
            raw.get("finishedAt") or raw.get("endedAt")) and status not in _TERMINAL:
        status = "settled"
    result = {"kind": kind, "resourceId": rid, "status": status,
              "agentId": "", "sessionId": "", "teamId": "", "flowId": ""}
    for field in ("agentId", "sessionId", "teamId", "flowId"):
        value = raw.get(field) or ""
        if kind == "team_run" and field == "flowId":
            value = (raw.get("flow") or {}).get("id") or ""
        if value:
            result[field] = _token(value)
    if kind in {"session_turn", "session_queue"} and not result.get("sessionId"):
        raise ValueError("Missing Session identity")
    if kind in {"team_run", "research_run"} and not all(result.get(key) for key in ("teamId", "flowId")):
        raise ValueError("Missing workflow identity")
    commands = []
    if (kind in {"session_turn", "runtime_task"} and status != "unknown" and status not in _TERMINAL
            and not raw.get("stopRequested") and not raw.get("stopInitiator")
            and (kind != "session_turn" or raw.get("_liveControl") is True)):
        commands = ["stop"]
    elif kind == "team_run" and status != "unknown":
        if status not in {"completed", "stopped"} and not raw.get("stopRequested"):
            commands.append("stop")
        if not raw.get("_recoveryParent"):
            if status == "waiting":
                commands.append("confirm")
            if status == "failed" and not raw.get("stopRequested"):
                recovery = raw.get("recovery") or {}
                if recovery.get("status") not in {"repairing", "awaiting_deployment"}:
                    commands.append("retry")
    elif (kind in {"supervised_run", "self_evolution_run"} and raw.get("_liveControl") is True
            and status in {"queued", "running", "paused"} and not raw.get("stopRequested")):
        commands.append("stop")
        commands.append("resume" if status == "paused" or raw.get("pauseRequested") else "pause")
    elif kind == "external_task" and raw.get("_operatorControl") and status in {
            "queued", "running", "awaiting_approval", "cancelling", "stop_unconfirmed"}:
        commands.append("stop")
    elif kind == "research_run" and raw.get("_operatorControl") and status in {
            "created", "running", "waiting_human", "blocked", "paused", "reconciliation_required"}:
        commands.append("stop")
        if status == "paused":
            commands.append("resume")
        elif status in {"running", "waiting_human"} and raw.get("_hasAttempts"):
            commands.append("pause")
    result["commands"] = commands
    if kind in {"supervised_run", "self_evolution_run"} and raw.get("_nativeCAS") is True:
        native_commands = raw["_nativeCommands"]
        if native_commands not in ([], ["stop", "pause"], ["stop", "resume"]):
            raise ValueError("Invalid native managed commands")
        result["commands"] = list(native_commands) if status != "unknown" else []
    if kind == "session_queue":
        from .runtime_contracts import RuntimeQueueMetadata
        result["commands"] = ["stop"] if (status in {"queued", "paused", "blocked"}
            and type(raw.get("_queueStateRevision")) is int and raw["_queueStateRevision"] >= 0) else []
        result["queue"] = RuntimeQueueMetadata.model_validate(raw["_queue"]).model_dump()
    if kind in {"team_run", "external_task", "research_run"}:
        revision = raw.get("revision")
        if type(revision) is not int or revision < 0:
            raise ValueError("Invalid native version")
        result["revision"] = str(revision)
    elif kind == "session_queue":
        result["revision"] = _fingerprint([result, raw.get("_queueStateRevision")])
    elif raw.get("_nativeCAS") is True:
        if not isinstance(raw.get("revision"), str) or re.fullmatch(r"[a-f0-9]{64}", raw["revision"]) is None:
            raise ValueError("Invalid native managed revision")
        result["revision"] = raw["revision"]
    else:
        # Include control-changing facts, never a prompt, summary, or transcript.
        result["revision"] = _fingerprint([result, {key: raw.get(key) for key in (
            "updatedAt", "pauseRequested", "stopRequested", "stopInitiator", "finishedAt")}])
    result["progressFingerprint"] = _progress_fingerprint(kind, raw)
    return result


def _json(path, max_bytes=2 * 1024 * 1024, *, read_file=None):
    from core.assistant_runtime.migration_io import read_stable_file, strict_json
    raw = (read_file or read_stable_file)(Path(path), max_bytes).raw
    row = strict_json(raw)
    if not isinstance(row, dict):
        raise ValueError("Invalid native metadata")
    return row, len(raw)


def _scan(folder, *, key, prefix="", budget=None):
    """Read all existing snapshots, including unindexed rows, without repair."""
    from core.assistant_runtime.migration_io import check_path, path_identity, stable_directory_reader
    folder = check_path(Path(folder))
    before = path_identity(folder)
    rows, paths, complete = [], [], True
    budget = [_MAX_FILES, _MAX_BYTES] if budget is None else budget
    with stable_directory_reader(folder) as read_file:
        for visited, path in enumerate(folder.iterdir()):
            if visited >= _MAX_FILES * 3:
                complete = False
                break
            if path.name.endswith(".json") and path.name.startswith(prefix) and not path.name.startswith("_"):
                paths.append(path)
                if len(paths) > budget[0]:
                    complete = False
                    break
        paths = sorted(paths)[:budget[0]]
        for path in paths:
            if budget[1] <= 0:
                complete = False
                break
            budget[0] -= 1
            try:
                allowance = min(2 * 1024 * 1024, budget[1])
                # Charge corrupt records too; invalid JSON must not bypass the
                # per-source byte budget and force thousands of full-size reads.
                budget[1] -= min(path.stat().st_size, allowance)
                row, _ = _json(path, allowance, read_file=read_file)
                if _token(row.get(key)) != path.stem:
                    raise ValueError("Snapshot identity mismatch")
                rows.append(row)
            except (OSError, ValueError, TypeError):
                complete = False
        return rows, complete and path_identity(folder) == before


def _root(gateway, *owners):
    if any(Path(owner.PROJECT_ROOT).resolve() != gateway.project_root for owner in owners):
        raise ManagementError("TARGET_BINDING_CHANGED", 409)


def _work_store(gateway):
    from core.web.services import session_service
    from core.infrastructure import developer_sandbox
    from vibelution_storage import resolve_project_runtime_home
    _root(gateway, session_service)
    expected = resolve_project_runtime_home(gateway.project_root) / "runtime-manager" / "work_runs"
    if developer_sandbox.is_developer_mode_enabled():
        sandbox = developer_sandbox.sandbox_root(gateway.project_root, ensure=False)
        if sandbox is None:
            raise ValueError("Missing runtime authority")
        expected = sandbox / ".runtime" / "runtime-manager" / "work_runs"
    store = session_service._WORK_RUN_STORE
    if Path(store.root).resolve() != expected.resolve():
        raise ValueError("Runtime authority mismatch")
    from core.assistant_runtime.migration_io import check_path
    check_path(Path(store.root))
    return store


def _observed_turn(fact, previous=None):
    previous = previous or {}
    return {**previous, "runId": fact["turnId"], "sessionId": fact["sessionId"],
        "agentId": fact["agentId"] or previous.get("agentId", ""), "status": fact["status"],
        "stopRequested": fact["stopRequested"], "finishedAt": "", "endedAt": "",
        "_liveControl": fact["liveControl"]}


def _sessions(gateway):
    from core.web.services import session_service as sessions
    _root(gateway, sessions)
    try:
        persisted, disk_complete = _scan(_work_store(gateway).runs_dir("chat_turn"), key="runId")
    except (OSError, ValueError):
        persisted, disk_complete = [], False
    by_id = {row["runId"]: {**row, "_liveControl": False} for row in persisted}
    try:
        observed = sessions.read_session_runtime_inventory(gateway.project_root, max_rows=_MAX_FILES)
    except Exception:
        observed = {"turns": [], "complete": False, "sourceCoverage": [
            {"source": source, "state": "unavailable", "complete": False, "reason": "read_failed"}
            for source in ("running_controller", "scheduler", "persisted_queue", "journal")]}
    for fact in observed["turns"]:
        rid = fact["turnId"]
        previous = by_id.get(rid, {})
        if previous.get("sessionId", fact["sessionId"]) != fact["sessionId"]:
            raise ValueError("Conflicting native Turn identity")
        by_id[rid] = _observed_turn(fact, previous)
    details = [*observed["sourceCoverage"], {"source": "work_runs",
        "state": "available" if disk_complete else "partial", "complete": disk_complete}]
    return list(by_id.values()), bool(disk_complete and observed["complete"]), details


def _session_queues(gateway):
    from core.web.services import session_service as sessions
    _root(gateway, sessions)
    observed = sessions.read_session_runtime_inventory(gateway.project_root, max_rows=_MAX_FILES)
    coverage = [item for item in observed["sourceCoverage"] if item["source"] == "persisted_queue"]
    if len(coverage) != 1:
        raise ValueError("Missing native queue authority")
    rows = [{"runId": row["queueId"], "sessionId": row["sessionId"], "agentId": row["agentId"],
        "status": row["status"], "_queueFact": row, "_queueStateRevision": coverage[0]["revision"], "_queue": {key: row[key] for key in (
            "queueKind", "position", "held", "sessionHeld", "sendNow", "branchGeneration", "sessionBranchGeneration")}}
        for row in observed["queues"]]
    return rows, coverage[0]["complete"], coverage


def _runtime_store(gateway):
    from core.web.services import runtime_task_registry as registry
    from vibelution_storage import resolve_project_runtime_home
    _root(gateway, registry)
    store = registry.default_store()
    expected = resolve_project_runtime_home(gateway.project_root) / registry.STORE_DIR_NAME
    if store.root.resolve() != expected.resolve():
        raise ValueError("Task authority mismatch")
    from core.assistant_runtime.migration_io import check_path
    check_path(store.root)
    return store


def _runtime_tasks(gateway):
    return _scan(_runtime_store(gateway).root, key="taskId")


def _external_store(gateway):
    from core.web.services.external_agent.store import ExternalAgentTaskStore
    from vibelution_storage import resolve_project_runtime_home
    from core.assistant_runtime.migration_io import check_path
    authority = resolve_project_runtime_home(gateway.project_root) / "external_agents"
    check_path(authority)
    return ExternalAgentTaskStore(authority)


def _external_tasks(gateway):
    store = _external_store(gateway)
    # The native list silently skips corrupt records; scan its whole namespace.
    rows, complete = _scan(store.tasks_dir, key="taskId", prefix="eat-")
    return [{**row, "_operatorControl": _operator_context() is not None} for row in rows], complete


def _team_context(gateway):
    from core.web.services import team_service
    from .state_snapshot import ExistingStateSnapshot
    _root(gateway, team_service)
    snapshot = ExistingStateSnapshot(gateway.project_root, gateway._owners(), pin_workspace=True)
    root = snapshot.path("teams")
    index, _ = _json(root / "teams.json")
    teams = index.get("teams")
    if not isinstance(teams, list):
        raise ValueError("Missing Team authority")
    if len(teams) > _MAX_FILES:
        raise ValueError("Team authority too large")
    ids = [_token(team.get("teamId")) for team in teams]
    if len(ids) != len(set(ids)):
        raise ValueError("Ambiguous Team authority")
    snapshot.verify_workspace()
    return snapshot, root, ids


def _team_runs(gateway):
    snapshot, root, team_ids = _team_context(gateway)
    rows, complete, budget = [], True, [_MAX_FILES, _MAX_BYTES]
    # Discover files even if an old bounded per-Team list would omit them.
    for tid in team_ids:
        folder = root / tid / "generic-workflows" / "runs"
        if not folder.exists():
            continue
        items, found_all = _scan(folder, key="id", budget=budget)
        complete = complete and found_all
        for row in items:
            if row.get("teamId") != tid:
                complete = False
            else:
                rows.append(row)
    snapshot.verify_workspace()
    return rows, complete


def _managed_directory(path):
    """Validate existing ancestors without initializing a missing namespace."""
    from core.assistant_runtime.migration_io import check_path, validate_path
    path = validate_path(Path(path))
    ancestor = path
    while True:
        try:
            ancestor.lstat()
        except FileNotFoundError:
            if ancestor == ancestor.parent:
                raise ValueError("Missing evolution ancestor") from None
            ancestor = ancestor.parent
            continue
        check_path(ancestor)
        if not ancestor.is_dir():
            raise ValueError("Invalid evolution directory")
        return ancestor == path


def _managed_store(gateway):
    from core.runtime_manager import constants, evolution_store
    from vibelution_storage import resolve_project_runtime_home
    _root(gateway, constants)
    expected = resolve_project_runtime_home(gateway.project_root) / "runtime-manager" / "evolution"
    store = evolution_store._WORK_RUN_STORE
    if (Path(store.root).resolve() != expected.resolve()
            or Path(evolution_store.EVOLUTION_DIR).resolve() != expected.resolve()):
        raise ValueError("Evolution authority mismatch")
    _managed_directory(store.root)
    return store


def _managed_manager_pid(gateway):
    try:
        import psutil
        from core.runtime_manager.process_identity import is_runtime_manager_process
        from core.web.services.runtime_manager_control_service import current_runtime_manager_pid
        pid = current_runtime_manager_pid(gateway.project_root)
        # The pid file and an alive PID alone cannot distinguish PID reuse.
        # Reuse the daemon's role check and its canonical launch cwd; this
        # remains observation only and must never ensure/start a manager.
        if (type(pid) is not int or pid <= 0 or not is_runtime_manager_process(pid)
                or Path(psutil.Process(pid).cwd()).resolve() != gateway.project_root):
            return 0
    except Exception:
        return 0
    return pid


def _managed_metadata(gateway, native_kind, row, *, manager_pid=None):
    # Durable ownerPid/claimedAt cannot prove a live slot in this daemon epoch.
    # Only the authenticated manager observation grants native commands.
    return {**row, "_liveControl": False}


def _native_managed_rows(gateway, native_kind, *, run_id=None):
    from core.runtime_manager import evolution_control
    snapshot = evolution_control.read_inventory(gateway.project_root, native_kind, run_id=run_id)
    if snapshot.get("complete") is not True:
        raise evolution_control.Unavailable("Incomplete native manager observation")
    return [{**row, "_nativeCAS": True, "_nativeCommands": row["commands"]}
            for row in snapshot["rows"]]


def _managed_runs(gateway, kind):
    native_kind = {"supervised_run": "supervised", "self_evolution_run": "self"}[kind]
    store = _managed_store(gateway)
    folder = store.runs_dir(native_kind)
    rows, complete = _scan(folder, key="runId") if _managed_directory(folder) else ([], True)
    durable = {row["runId"]: _managed_metadata(gateway, native_kind, row) for row in rows}
    from core.runtime_manager import evolution_control
    try:
        for row in _native_managed_rows(gateway, native_kind):
            durable[row["runId"]] = row
    except evolution_control.Unavailable:
        complete = False
    return list(durable.values()), complete


def _research_store(gateway):
    from core.web.services.team_workflow.research_runtime import formal_read_runtime, paths
    _root(gateway, paths)
    store = formal_read_runtime.get_formal_read_store()
    if Path(store.path).resolve() != paths.workflow_ledger_path().resolve():
        raise ValueError("Research authority mismatch")
    from core.assistant_runtime.migration_io import check_path
    check_path(paths.workflow_ledger_path())
    return store


def _research_runs(gateway):
    rows = _research_metadata(gateway)
    return rows[:_MAX_FILES], len(rows) <= _MAX_FILES


def _research_metadata(gateway, resource_id=None):
    store = _research_store(gateway)
    # Repository-owned read connection; fixed columns contain no content.
    suffix = " ORDER BY run_id LIMIT ?" if resource_id is None else " WHERE run_id=? LIMIT 2"
    parameters = (_MAX_FILES + 1,) if resource_id is None else (resource_id,)
    def metadata(repo):
        columns = {row[1] for row in repo.execute("PRAGMA table_info(workflow_runs)").fetchall()}
        progress = "last_event_sequence,active_node_id" if {"last_event_sequence", "active_node_id"} <= columns else "NULL,NULL"
        return repo.execute("SELECT run_id,team_id,workflow_id,status,run_version,"
            "EXISTS(SELECT 1 FROM node_attempts a WHERE a.run_id=workflow_runs.run_id)," + progress +
            " FROM workflow_runs" + suffix, parameters).fetchall()
    rows = store.read(metadata)
    control = False
    if _operator_context() is not None:
        try:
            _research_command_owner(gateway)
            control = True
        except Exception:
            pass  # Read coverage is independent of a configured write runtime.
    return [{"runId": row[0], "teamId": row[1], "flowId": row[2], "status": row[3], "revision": row[4]}
            | {"_hasAttempts": bool(row[5]), "_operatorControl": control,
               "lastEventSequence": row[6], "activeNodeId": row[7]}
            for row in rows]


def _research_command_owner(gateway):
    from core.web.services.team_workflow.research_runtime import formal_write_runtime
    store = _research_store(gateway)
    owner = formal_write_runtime.get_command_service()
    if (Path(formal_write_runtime.get_write_store().path).resolve() != Path(store.path).resolve()
            or Path(owner._store.path).resolve() != Path(store.path).resolve()):
        raise ManagementError("TARGET_BINDING_CHANGED", 409)
    return owner


def _research_command(gateway, before, action, expected, request_id):
    from core.research.workflow.contracts import ActorRef, CommandRequest, WorkflowCommandKind
    from core.research.workflow.ledger import CommandNotAllowedError, IdempotencyConflictError, RunVersionConflictError
    from core.web.services.team_workflow.research_runtime import command_service as native
    from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
        FormalWriteRuntimeUnavailable, WorkflowMigrationRequired)
    operator = _operator_context()
    if operator is None:
        raise ManagementError("command_forbidden", 403)
    try:
        owner = _research_command_owner(gateway)
    except (FormalWriteRuntimeUnavailable, WorkflowMigrationRequired) as exc:
        raise ManagementError(exc.code, 503) from None
    mapping = {"pause": WorkflowCommandKind.PAUSE_RUN, "resume": WorkflowCommandKind.RESUME_RUN,
               "stop": WorkflowCommandKind.CANCEL_RUN}
    request = CommandRequest(command_id="management-" + _fingerprint(request_id)[:32],
        run_id=before["resourceId"], team_id=before["teamId"], command=mapping[action], node_id=None,
        expected_run_version=int(expected), idempotency_key=request_id,
        payload={"reason": "launcher_assistant_operator_control"},
        requested_by=ActorRef("user", operator.operator_id), requested_at_ms=int(time.time() * 1000))
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
    except native.WorkflowDefinitionUnavailableError as exc:
        raise ManagementError(exc.code, 422) from None
    except native.WorkflowCommandError:
        raise ManagementError("unknown_command", 422) from None
    if receipt.run_id != before["resourceId"] or receipt.idempotency_key != request_id or receipt.status != "accepted":
        raise ManagementError("OPERATION_UNCONFIRMED", 503)
    refs = {"team_id": before["teamId"], "flow_id": before["flowId"]}
    return _after_command(gateway, "research_run", before["resourceId"], refs), True, action == "stop"


def _external_command(gateway, before, expected):
    from core.web.services.external_agent import service
    from vibelution_storage import resolve_project_runtime_home
    _external_store(gateway)
    owner = service.get_default_service(gateway.project_root)
    authority = resolve_project_runtime_home(gateway.project_root) / "external_agents"
    if owner.store.root.resolve() != authority.resolve():
        raise ManagementError("TARGET_BINDING_CHANGED", 409)
    try:
        result = owner.operator_cancel_task(task_id=before["resourceId"], expected_revision=int(expected))
    except service.ExternalAgentAccessError as exc:
        raise ManagementError(exc.code, 404 if exc.code == "TASK_NOT_FOUND" else 403) from None
    except service.ExternalAgentConflictError as exc:
        raise ManagementError(exc.code, 422 if exc.code == "INVALID_INPUT" else 409) from None
    return _project("external_task", {**result, "_operatorControl": True}), result["accepted"], result["stopRequested"]


def _source(gateway, kind):
    return {"session_turn": _sessions, "session_queue": _session_queues, "runtime_task": _runtime_tasks, "external_task": _external_tasks,
        "team_run": _team_runs, "research_run": _research_runs}.get(kind, lambda g: _managed_runs(g, kind))(gateway)


def _snapshot(gateway, kind):
    try:
        source = _source(gateway, kind)
        raw, complete = source[:2]
        details = source[2] if len(source) == 3 else []
    except Exception:
        # Source-local failures never erase other owners or claim an idle source.
        return [], {"source": kind, "state": "unavailable", "complete": False}
    rows, seen = [], set()
    for item in raw:
        try:
            projected = _project(kind, item)
            identity = tuple(projected[key] for key in ("resourceId", "sessionId", "teamId", "flowId"))
            if identity in seen:
                raise ValueError("Ambiguous operation identity")
            seen.add(identity)
            if projected["status"] == "unknown":
                complete = False
            rows.append(projected)
        except (ValueError, TypeError, AttributeError):
            complete = False
    coverage = {"source": kind, "state": "available" if complete else "partial", "complete": complete}
    if details:
        from .runtime_contracts import RuntimeInventorySource
        try:
            projected_details = [RuntimeInventorySource.model_validate(item).model_dump() for item in details]
            if len(projected_details) > 5 or len({item["source"] for item in projected_details}) != len(projected_details):
                raise ValueError("Ambiguous native coverage")
            coverage["details"] = projected_details
            if any(not item["complete"] for item in projected_details):
                coverage.update(state="partial", complete=False)
        except (ValueError, TypeError):
            coverage.update(state="partial", complete=False)
    return rows, coverage


def read_operations(gateway, query):
    from .runtime_legacy_contracts import LegacyRuntimeOperationsQuery, LEGACY_RUNTIME_KINDS
    allowed_kinds = LEGACY_RUNTIME_KINDS if isinstance(query, LegacyRuntimeOperationsQuery) else KINDS
    gateway._owners()
    query = _parameters(query)
    kind, offset, limit = query.get("kind"), query.get("offset", 0), query.get("limit", 3)
    filter_state = query.get("state", "active")
    expected_snapshot = query.get("expected_snapshot")
    if (set(query) - {"kind", "state", "offset", "limit", "expected_snapshot"} or kind not in (None, "", *KINDS)
            or filter_state not in {"active", "terminal", "all"}
            or expected_snapshot is not None and (not isinstance(expected_snapshot, str)
                or re.fullmatch(r"[a-f0-9]{64}", expected_snapshot) is None)
            or type(offset) is not int or not 0 <= offset <= 1000000 or type(limit) is not int or not 1 <= limit <= 3):
        raise ManagementError("INVALID_INPUT", 422)
    operations, coverage, observed = [], [], []
    for selected in (kind,) if kind else allowed_kinds:
        rows, source_state = _snapshot(gateway, selected)
        observed.extend(rows)
        operations.extend(row for row in rows if filter_state == "all" or
            (row["status"] in _TERMINAL_BY_KIND.get(selected, _TERMINAL)) == (filter_state == "terminal"))
        coverage.append(source_state)
    operations.sort(key=lambda row: (row["kind"], row["resourceId"]))
    # Bind the entire admitted observation, including rows outside this page and
    # the state filter. A digest of partial coverage never proves an unseen tail.
    # This is a consistency fence between scans, not a frozen native snapshot.
    observed.sort(key=lambda row: (row["kind"], row["resourceId"], row["sessionId"], row["teamId"], row["flowId"]))
    snapshot = _fingerprint({"kind": kind or None, "state": filter_state, "operations": observed, "coverage": coverage})
    if expected_snapshot is not None and expected_snapshot != snapshot:
        raise ManagementError("RUNTIME_SNAPSHOT_CHANGED", 409)
    result = {"snapshot": snapshot, "operations": [], "offset": offset, "total": len(operations), "nextOffset": None, "coverage": coverage,
        "complete": all(state["complete"] for state in coverage), "untrustedContent": True}
    for row in operations[offset:offset + limit]:
        candidate = {**result, "operations": [*result["operations"], row], "nextOffset": offset + limit}
        if len(json.dumps(candidate, ensure_ascii=False)) > 3000 and result["operations"]:
            break
        result["operations"].append(row)
    end = offset + len(result["operations"])
    result["nextOffset"] = end if end < len(operations) else None
    return result


def _file_reference(value):
    # A DTO token is also used by SQLite. File-backed owners additionally reject
    # Windows aliases, alternate streams, and device names before path lookup.
    devices = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if ":" in value or value.endswith(".") or value.split(".", 1)[0].upper() in devices:
        raise ManagementError("INVALID_INPUT", 422)


def _point_json(path, key, resource_id):
    from core.assistant_runtime.migration_io import check_path
    check_path(path.parent)
    if not path.exists():
        raise ManagementError("OPERATION_UNAVAILABLE", 404)
    row, _ = _json(path)
    if row.get(key) != resource_id:
        raise ValueError("Native target identity mismatch")
    return row


def _session_target(gateway, resource_id, session_id):
    from core.web.services import session_service as sessions
    store = _work_store(gateway)
    path = store.runs_dir("chat_turn") / (resource_id + ".json")
    controller = sessions._get_session_turn_control(session_id)
    with sessions._RUNNING_SESSIONS_LOCK:
        live = session_id in sessions._RUNNING_SESSION_IDS and sessions._SESSION_ACTIVE_TURN_IDS.get(session_id) == resource_id
    live = live and controller is not None and controller.turn_id == resource_id
    if path.exists():
        row = _point_json(path, "runId", resource_id)
        if row.get("sessionId") != session_id:
            raise ManagementError("OPERATION_UNAVAILABLE", 404)
    elif live:
        row = {"runId": resource_id, "sessionId": session_id}
    else:
        observed = sessions.read_session_runtime_inventory(gateway.project_root, max_rows=_MAX_FILES)
        facts = [fact for fact in observed["turns"] if (fact["sessionId"], fact["turnId"]) == (session_id, resource_id)]
        if len(facts) == 1:
            return _observed_turn(facts[0])
        if facts:
            raise ValueError("Ambiguous native Turn identity")
        turn_sources = {item["source"]: item for item in observed["sourceCoverage"]
                        if item["source"] in {"running_controller", "scheduler", "journal"}}
        complete = len(turn_sources) == 3 and all(item["complete"] for item in turn_sources.values())
        raise ManagementError("OPERATION_UNAVAILABLE" if complete else "OPERATION_SOURCE_UNAVAILABLE", 404 if complete else 503)
    if live:
        state = controller.snapshot()
        previous = row.get("status")
        row = {**row, "status": "stopping" if state.get("stopRequested") else previous if previous in ("queued", "running") else "running",
               "stopRequested": bool(state.get("stopRequested")), "finishedAt": "", "endedAt": ""}
    row["_liveControl"] = bool(live)
    return row


def _point_operation(gateway, kind, resource_id, refs):
    if kind == "session_queue":
        rows, complete, _ = _session_queues(gateway)
        matches = [row for row in rows if row["runId"] == resource_id and row["sessionId"] == refs["session_id"]]
        if len(matches) == 1:
            return matches[0]
        raise ManagementError("OPERATION_UNAVAILABLE" if complete else "OPERATION_SOURCE_UNAVAILABLE", 404 if complete else 503)
    if kind == "research_run":
        rows = _research_metadata(gateway, resource_id)
        if not rows:
            raise ManagementError("OPERATION_UNAVAILABLE", 404)
        if len(rows) != 1:
            raise ValueError("Ambiguous research identity")
        return rows[0]
    if kind == "session_turn":
        return _session_target(gateway, resource_id, refs["session_id"])
    if kind == "runtime_task":
        store = _runtime_store(gateway)
        path = store.task_state_path(resource_id)
        if path.stem != resource_id:
            raise ManagementError("INVALID_INPUT", 422)
        return _point_json(path, "taskId", resource_id)
    if kind == "external_task":
        store = _external_store(gateway)
        return {**_point_json(store.task_path(resource_id), "taskId", resource_id),
                "_operatorControl": _operator_context() is not None}
    if kind == "team_run":
        from core.web.services.team_workflow.generic import store
        for value in (resource_id, *refs.values()):
            store.token(value)
        snapshot, root, team_ids = _team_context(gateway)
        if refs["team_id"] not in team_ids:
            raise ManagementError("OPERATION_UNAVAILABLE", 404)
        row = _point_json(root / refs["team_id"] / "generic-workflows" / "runs" / (resource_id + ".json"), "id", resource_id)
        snapshot.verify_workspace()
        return row
    store = _managed_store(gateway)
    native_kind = "supervised" if kind == "supervised_run" else "self"
    from core.runtime_manager import evolution_control
    try:
        rows = _native_managed_rows(gateway, native_kind, run_id=resource_id)
        if len(rows) != 1 or rows[0]["runId"] != resource_id:
            raise ValueError("Native managed identity changed")
        return rows[0]
    except (evolution_control.Unavailable, evolution_control.NotFound):
        pass
    folder = store.runs_dir(native_kind)
    if not _managed_directory(folder):
        raise ManagementError("OPERATION_UNAVAILABLE", 404)
    row = _point_json(folder / (resource_id + ".json"), "runId", resource_id)
    return _managed_metadata(gateway, native_kind, row)


def read_operation(gateway, kind, resource_id, **refs):
    refs = _reference(kind, resource_id, refs)
    if kind != "research_run":
        for value in (resource_id, *refs.values()):
            _file_reference(value)
        if (kind == "runtime_task" and len(resource_id) > 120
                or kind == "external_task" and not re.fullmatch(r"[A-Za-z0-9_-]+", resource_id)
                or kind == "team_run" and any(len(value) > 96 for value in (resource_id, *refs.values()))):
            raise ManagementError("INVALID_INPUT", 422)
    gateway._owners()
    try:
        row = _project(kind, _point_operation(gateway, kind, resource_id, refs))
    except ManagementError:
        raise
    except Exception:
        raise ManagementError("OPERATION_SOURCE_UNAVAILABLE", 503) from None
    if row["resourceId"] != resource_id or any(
            row[{"session_id": "sessionId", "team_id": "teamId", "flow_id": "flowId"}[key]] != value for key, value in refs.items()):
        raise ManagementError("OPERATION_UNAVAILABLE", 404)
    return {"operation": row, "untrustedContent": True}


def _after_command(gateway, kind, rid, refs):
    try:
        return read_operation(gateway, kind, rid, **refs)["operation"]
    except Exception:
        raise ManagementError("OPERATION_UNCONFIRMED", 503) from None


def command(gateway, parameters, *, request_id=""):
    parameters = _parameters(parameters)
    if set(parameters) - {"kind", "resource_id", "command", "expected_revision", *_REFS}:
        raise ManagementError("INVALID_INPUT", 422)
    kind, rid, action = parameters.get("kind"), parameters.get("resource_id"), parameters.get("command")
    refs = _reference(kind, rid, {key: parameters[key] for key in _REFS if key in parameters})
    expected = parameters.get("expected_revision")
    if not isinstance(expected, str) or not expected or len(expected) > 160 or action not in {"stop", "pause", "resume", "retry", "confirm"}:
        raise ManagementError("INVALID_INPUT", 422)
    if kind in {"research_run", "external_task"} and _operator_context() is None:
        raise ManagementError("command_forbidden", 403)
    if kind == "research_run":
        if action not in {"pause", "resume", "stop"}:
            raise ManagementError("COMMAND_UNAVAILABLE", 409)
        if not expected.isdecimal():
            raise ManagementError("INVALID_INPUT", 422)
        try:
            _token(request_id)
        except ValueError:
            raise ManagementError("INVALID_INPUT", 422) from None
    before = read_operation(gateway, kind, rid, **refs)["operation"]
    replay = kind == "research_run" and _research_store(gateway).get_command_by_idempotency(rid, request_id) is not None
    if not replay and before["revision"] != expected:
        raise ManagementError("STATE_CONFLICT", 409)
    if not replay and action not in before["commands"]:
        raise ManagementError("COMMAND_UNAVAILABLE", 409)
    # Everything above is preflight and side-effect free. From here, an unknown
    # exception is a lost acknowledgement, not permission to repeat the command.
    try:
        accepted, stop_requested = True, False
        if kind == "session_queue":
            from core.web.services import session_service as sessions
            from core.web.services.session.queued_turns import cancel_session_queued_turn
            target = _point_operation(gateway, kind, rid, refs)
            if _project(kind, target)["revision"] != expected:
                raise ManagementError("STATE_CONFLICT", 409)
            try:
                result = cancel_session_queued_turn(refs["session_id"], rid,
                    expected_state_revision=target["_queueStateRevision"], expected_metadata=target["_queueFact"])
            except sessions.SessionBusyError:
                raise ManagementError("STATE_CONFLICT", 409) from None
            except sessions.SessionNotFoundError:
                raise ManagementError("OPERATION_UNAVAILABLE", 404) from None
            except sessions.SessionValidationError:
                raise ManagementError("COMMAND_UNAVAILABLE", 409) from None
            if (result.get("sessionId") != refs["session_id"] or result.get("queueId") != rid
                    or result.get("agentId") != target["agentId"] or result.get("queueMetadata") != target["_queueFact"]
                    or result.get("status") != "cancelled" or type(result.get("stateRevision")) is not int
                    or result["stateRevision"] <= target["_queueStateRevision"]):
                raise ManagementError("OPERATION_UNCONFIRMED", 503)
            after = _project(kind, {**target, "status": "cancelled", "_queueStateRevision": result["stateRevision"]})
        elif kind == "session_turn":
            from core.web.services import session_service as sessions
            from core.web.services.session.control import request_stop_session_turn
            controller = sessions._get_session_turn_control(refs["session_id"])
            if controller is None or controller.turn_id != rid or not sessions._is_session_running(refs["session_id"]):
                raise ManagementError("STATE_CONFLICT", 409)
            try:
                raw = request_stop_session_turn(refs["session_id"], expected_turn_id=rid, fast_ack=True, cascade=True)
            except sessions.SessionBusyError:
                raise ManagementError("STATE_CONFLICT", 409) from None
            except sessions.SessionNotFoundError:
                raise ManagementError("OPERATION_UNAVAILABLE", 404) from None
            if raw.get("activeTurnId") != rid or raw.get("stopRequested") is not True:
                raise ManagementError("OPERATION_UNCONFIRMED", 503)
            stop_requested = True
            after = _after_command(gateway, kind, rid, refs)
        elif kind == "runtime_task":
            from core.web.services import runtime_task_registry
            from core.web.services.runtime_task_query_service import RuntimeTaskQueryService
            raw = RuntimeTaskQueryService(runtime_task_registry.default_store()).stop_task(rid, initiator="user")
            if raw is None:
                raise ManagementError("OPERATION_UNCONFIRMED", 503)
            accepted, stop_requested = raw.get("accepted") is True, raw.get("accepted") is True
            after = _after_command(gateway, kind, rid, {})
        elif kind == "team_run":
            from core.web.services.team_workflow.generic import service, store
            try:
                raw = service.command_run(refs["team_id"], rid, {"action": action, "expectedRevision": int(expected)})
            except store.Conflict:
                raise ManagementError("STATE_CONFLICT", 409) from None
            except store.NotFound:
                raise ManagementError("OPERATION_UNAVAILABLE", 404) from None
            except store.WorkflowError:
                raise ManagementError("STATE_CONFLICT", 409) from None
            after = _project(kind, raw)
            stop_requested = action == "stop" and raw.get("stopRequested") is True
        elif kind == "research_run":
            after, accepted, stop_requested = _research_command(gateway, before, action, expected, request_id)
        elif kind == "external_task":
            after, accepted, stop_requested = _external_command(gateway, before, expected)
        else:
            from core.runtime_manager import evolution_control
            native_kind = "supervised" if kind == "supervised_run" else "self"
            try:
                result = evolution_control.command(gateway.project_root, native_kind, rid, action, expected,
                                                   request_id=request_id)
            except evolution_control.Conflict:
                raise ManagementError("STATE_CONFLICT", 409) from None
            except evolution_control.NotFound:
                raise ManagementError("OPERATION_UNAVAILABLE", 404) from None
            except evolution_control.InputError:
                raise ManagementError("INVALID_INPUT", 422) from None
            raw = result["operation"]
            after = _project(kind, {**raw, "_nativeCAS": True, "_nativeCommands": raw["commands"]})
            accepted, stop_requested = result["accepted"], action == "stop" and result["stopRequested"]
        if any(after.get(key) != before.get(key) for key in ("kind", "resourceId", "agentId", "sessionId", "teamId", "flowId")):
            raise ManagementError("OPERATION_UNCONFIRMED", 503)
        return {"operation": after, "command": action, "accepted": accepted, "stopRequested": stop_requested,
            "revisionCheck": "native_cas" if kind in {"session_queue", "team_run", "research_run", "supervised_run", "self_evolution_run"} else "preflight_only", "untrustedContent": True}
    except ManagementError:
        raise
    except Exception:
        raise ManagementError("OPERATION_UNCONFIRMED", 503) from None


def read_command_receipt(gateway, parameters, *, request_id):
    """Recover only the original manager command acknowledgement, never state."""
    from core.runtime_manager import evolution_control
    parameters = _parameters(parameters)
    kind, rid = parameters.get("kind"), parameters.get("resource_id")
    if kind not in {"supervised_run", "self_evolution_run"}:
        return None
    _reference(kind, rid, {key: parameters[key] for key in _REFS if key in parameters})
    outcome = evolution_control.read_command_outcome(
        gateway.project_root, "supervised" if kind == "supervised_run" else "self", rid,
        parameters["command"], parameters["expected_revision"], request_id=request_id)
    if outcome["state"] != "completed":
        return None
    raw = outcome["operation"]
    row = _project(kind, {**raw, "_nativeCAS": True, "_nativeCommands": raw["commands"]})
    return {"operation": row, "command": parameters["command"], "accepted": outcome["accepted"],
            "stopRequested": parameters["command"] == "stop" and outcome["stopRequested"],
            "revisionCheck": "native_cas", "untrustedContent": True}
