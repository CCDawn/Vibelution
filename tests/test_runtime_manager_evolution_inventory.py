"""Manager-memory inventory and native evolution CAS never repair on reads."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

from core.runtime_manager import command_queue, constants, evolution_control as control, process_identity, state_store
from core.web.services import self_evolution_control_service as self_service
from core.web.services import supervised_control_service as supervised

pytestmark = pytest.mark.serial


@pytest.fixture
def native(tmp_path, monkeypatch):
    owner = {"pid": os.getpid(), "createTime": 100.5, "executable": sys.executable}
    monkeypatch.setattr(constants, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(state_store, "PID_PATH", tmp_path / "daemon.pid")
    monkeypatch.setattr(state_store, "DAEMON_IDENTITY_PATH", tmp_path / "daemon.identity.json")
    monkeypatch.setattr(state_store, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(state_store, "capture_process_identity", lambda _pid: dict(owner))
    monkeypatch.setattr(process_identity, "capture_process_identity", lambda _pid: dict(owner))
    monkeypatch.setattr(process_identity, "inspect_process_identity", lambda _owner: {"status": "match"})
    monkeypatch.setattr(process_identity, "is_runtime_manager_process", lambda _pid: True)
    import psutil
    monkeypatch.setattr(psutil, "Process", lambda _pid: SimpleNamespace(cwd=lambda: str(tmp_path)))
    calls = []
    controller = SimpleNamespace(request_pause=lambda: calls.append("pause"),
                                 request_resume=lambda: calls.append("resume"),
                                 request_stop=lambda: calls.append("stop"))
    for service, kind in ((supervised, "supervised"), (self_service, "self")):
        state = {"runId": "live-a", "status": "running", "updatedAt": "2026-11-03T10:00:00",
                 "sessionId": "session-a", "runtimeManagerControl": {"ownerPid": owner["pid"], "kind": kind},
                 "goal": "SECRET goal", "summary": "SECRET body", "eventTail": [{"body": "SECRET event"}],
                 "messages": [], "pauseRequested": False, "stopRequested": False}
        monkeypatch.setattr(service, "_RUN_STATES", {"live-a": state})
        monkeypatch.setattr(service, "_ACTIVE_RUN_ID", "live-a")
        monkeypatch.setattr(service, "get_web_language", lambda: "zh")
        monkeypatch.setattr(service, "_publish_run_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(supervised, "_RUN_CONTROLLERS", {"live-a": controller})
    monkeypatch.setattr(supervised, "get_supervised_run_snapshot", lambda rid: deepcopy(supervised._RUN_STATES[rid]))
    monkeypatch.setattr(self_service, "get_self_evolution_run_snapshot", lambda rid: deepcopy(self_service._RUN_STATES[rid]))
    monkeypatch.setattr(self_service, "get_session_state", lambda: SimpleNamespace(note_scope_completion=lambda *_args: None))
    monkeypatch.setattr(self_service, "active_session_has_write_leases", lambda: False)
    monkeypatch.setattr(self_service, "_raise_if_self_lease_conflict", lambda **_kwargs: None)
    monkeypatch.setattr(self_service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(self_service, "_RUN_EXECUTOR", SimpleNamespace(submit=lambda *_args, **_kwargs: None))
    queue_root = tmp_path / "queue"
    for name, folder in (("INBOX_DIR", "inbox"), ("PROCESSING_DIR", "processing"),
                         ("RESULTS_DIR", "results"), ("INTERRUPTS_DIR", "interrupts")):
        directory = queue_root / folder
        directory.mkdir(parents=True)
        monkeypatch.setattr(command_queue, name, directory)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "_append_queue_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(command_queue, "clear_lifecycle_interrupt", lambda *_args: None)
    monkeypatch.setattr(command_queue, "_shutdown_in_progress_state", lambda: None)
    state_store.PID_PATH.write_text(str(owner["pid"]), encoding="utf-8")
    state_store.DAEMON_IDENTITY_PATH.write_text(json.dumps(owner), encoding="utf-8")
    return SimpleNamespace(root=tmp_path, owner=owner, calls=calls)


@pytest.fixture
def endpoint(native):
    server = control.MetadataServer(native.owner)
    state_store.publish_evolution_control_endpoint(native.owner, server.start())
    try:
        yield server
    finally:
        server.close()


def _files(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _request(server, method="GET", path="/evolution/metadata?kind=supervised", *, auth=True, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", server._server.server_port, timeout=2)
    try:
        headers = {"Authorization": "Bearer " + server.capability} if auth else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


@pytest.mark.parametrize("kind", ["supervised", "self"])
def test_inventory_observes_real_memory_without_getters_repairs_or_disk_writes(native, endpoint, monkeypatch, kind):
    from core.runtime_manager import daemon, work_run_store
    def forbidden(*_args, **_kwargs):
        pytest.fail("metadata read attempted initialization, repair, or queue mutation")
    for name in ("ensure_daemon_running", "load_runtime_snapshot"):
        monkeypatch.setattr(daemon, name, forbidden)
    monkeypatch.setattr(command_queue, "submit_command", forbidden)
    monkeypatch.setattr(work_run_store, "_load_json", forbidden)
    monkeypatch.setattr(supervised, "get_active_supervised_run", forbidden)
    monkeypatch.setattr(self_service, "get_active_self_evolution_run", forbidden)
    before = _files(native.root)
    snapshot = control.read_inventory(native.root, kind)
    assert snapshot["complete"] is True and snapshot["owner"] == native.owner
    assert snapshot["rows"][0]["runId"] == "live-a"
    assert snapshot["rows"][0]["commands"] == ["stop", "pause"]
    assert "SECRET" not in json.dumps(snapshot) and endpoint.capability not in json.dumps(snapshot)
    assert _files(native.root) == before


def test_slot_membership_not_durable_pid_authorizes_controls(native, endpoint):
    supervised._RUN_CONTROLLERS.clear()
    row = control.read_inventory(native.root, "supervised")["rows"][0]
    assert row["commands"] == []
    with pytest.raises(control.Conflict):
        control.command(native.root, "supervised", "live-a", "stop", row["revision"])
    supervised._RUN_STATES.clear()
    supervised._ACTIVE_RUN_ID = None
    assert control.read_inventory(native.root, "supervised")["rows"] == []
    with pytest.raises(control.NotFound):
        control.read_inventory(native.root, "supervised", run_id="live-a")


@pytest.mark.parametrize("status", ["mismatch", "dead", "unknown"])
def test_identity_uncertainty_is_unavailable_never_complete_empty(native, endpoint, monkeypatch, status):
    monkeypatch.setattr(process_identity, "inspect_process_identity", lambda _owner: {"status": status})
    before = _files(native.root)
    with pytest.raises(control.Unavailable):
        control.read_inventory(native.root, "supervised")
    assert _files(native.root) == before


@pytest.mark.parametrize("change", ["createTime", "capability", "missing", "legacy"])
def test_daemon_epoch_and_protocol_change_invalidate_reads(native, endpoint, monkeypatch, change):
    original = control._observe_owner
    count = 0
    def observe(root):
        nonlocal count
        count += 1
        if count == 2:
            record = json.loads(state_store.DAEMON_IDENTITY_PATH.read_text(encoding="utf-8"))
            if change == "createTime":
                record["createTime"] += 1
            elif change == "capability":
                record["evolutionControl"]["capability"] = "x" * 43
            elif change == "legacy":
                record.pop("evolutionControl")
            else:
                state_store.DAEMON_IDENTITY_PATH.unlink()
                return original(root)
            state_store.DAEMON_IDENTITY_PATH.write_text(json.dumps(record), encoding="utf-8")
        return original(root)
    monkeypatch.setattr(control, "_observe_owner", observe)
    with pytest.raises(control.Unavailable):
        control.read_inventory(native.root, "supervised")


@pytest.mark.parametrize("method,path,auth,body,expected", [
    ("POST", "/evolution/metadata?kind=self", True, None, 405),
    ("GET", "/evolution/metadata?kind=self&call=repair", True, None, 400),
    ("GET", "/evolution/metadata?kind=self&kind=supervised", True, None, 400),
    ("GET", "/arbitrary?kind=self", True, None, 400),
    ("GET", "/evolution/metadata?kind=self", False, None, 403),
    ("GET", "/evolution/metadata?kind=self", True, "body", 403),
])
def test_closed_http_read_protocol(native, endpoint, method, path, auth, body, expected):
    status, raw = _request(endpoint, method, path, auth=auth, body=body)
    assert status == expected and endpoint.capability.encode() not in raw and b"SECRET" not in raw


def test_missing_identity_and_stopped_endpoint_do_not_initialize_manager(native, endpoint):
    endpoint.close()
    before = _files(native.root)
    with pytest.raises(control.Unavailable):
        control.read_inventory(native.root, "supervised")
    assert _files(native.root) == before


_METHODS = {
    "supervised": {"pause": "_LOCAL_REQUEST_PAUSE_SUPERVISED_RUN", "resume": "_LOCAL_REQUEST_RESUME_SUPERVISED_RUN",
                   "stop": "_LOCAL_REQUEST_STOP_SUPERVISED_RUN"},
    "self": {"pause": "_LOCAL_REQUEST_PAUSE_SELF_EVOLUTION_RUN", "resume": "_LOCAL_RESUME_SELF_EVOLUTION_RUN",
             "stop": "_LOCAL_REQUEST_STOP_SELF_EVOLUTION_RUN"},
}


@pytest.mark.parametrize("kind", ["supervised", "self"])
@pytest.mark.parametrize("action", ["pause", "resume", "stop"])
def test_cas_rejects_changed_state_before_native_mutation(native, kind, action):
    service = supervised if kind == "supervised" else self_service
    if action == "resume":
        service._RUN_STATES["live-a"]["status"] = "paused"
        service._RUN_STATES["live-a"]["pauseRequested"] = True
    before = service.read_managed_evolution_metadata(native.owner, run_id="live-a")[0]
    service._RUN_STATES["live-a"]["updatedAt"] = "2026-11-03T10:00:01"
    changed = deepcopy(service._RUN_STATES)
    with pytest.raises(control.Conflict):
        getattr(service, _METHODS[kind][action])("live-a", expected_revision=before["revision"], expected_owner=native.owner)
    assert service._RUN_STATES == changed and native.calls == []


@pytest.mark.parametrize("kind", ["supervised", "self"])
@pytest.mark.parametrize("action", ["pause", "resume", "stop"])
def test_matching_cas_reuses_native_control_and_rejects_replay(native, kind, action):
    service = supervised if kind == "supervised" else self_service
    if action == "resume":
        service._RUN_STATES["live-a"]["status"] = "paused"
        service._RUN_STATES["live-a"]["pauseRequested"] = True
    before = service.read_managed_evolution_metadata(native.owner, run_id="live-a")[0]
    method = getattr(service, _METHODS[kind][action])
    method("live-a", expected_revision=before["revision"], expected_owner=native.owner)
    after = service.read_managed_evolution_metadata(native.owner, run_id="live-a")[0]
    assert after["revision"] != before["revision"]
    with pytest.raises(control.Conflict):
        method("live-a", expected_revision=before["revision"], expected_owner=native.owner)
    if kind == "supervised":
        assert native.calls == [action]


def test_queue_control_has_closed_reply_and_no_manager_start(native, endpoint, monkeypatch):
    from core.runtime_manager import daemon
    manager = daemon.RuntimeManagerDaemon()
    monkeypatch.setattr(manager, "_finish_command", lambda command_id, **kwargs:
                        {"commandId": command_id, "accepted": True, "ok": kwargs["ok"], **kwargs["result_data"]})
    monkeypatch.setattr(daemon, "capture_process_identity", lambda _pid: native.owner)
    monkeypatch.setattr(daemon, "ensure_daemon_running", lambda **_kwargs: pytest.fail("control started a manager"))
    requests = []
    def submit(command_type, *, args, requested_by):
        requests.append((command_type, args, requested_by))
        return {"commandId": "cmd-a"}
    monkeypatch.setattr(command_queue, "submit_command", submit)
    monkeypatch.setattr(command_queue, "wait_for_result", lambda _cid:
                        manager._handle_managed_evolution_control(command_id="cmd-a", args=requests[-1][1]))
    row = control.read_inventory(native.root, "supervised")["rows"][0]
    result = control.command(native.root, "supervised", "live-a", "pause", row["revision"])
    assert len(requests) == 1 and requests[0][0] == "managed_evolution_control"
    assert result["revisionCheck"] == "native_cas" and result["accepted"] is True
    assert native.calls == ["pause"] and "SECRET" not in json.dumps(result)


def test_queue_restart_and_lost_ack_do_not_replay_or_initialize(native, endpoint, monkeypatch):
    requests = []
    monkeypatch.setattr(command_queue, "submit_command", lambda *_args, **_kwargs:
                        requests.append(True) or {"commandId": "cmd-a"})
    def lost(_cid):
        raise TimeoutError("lost acknowledgement")
    monkeypatch.setattr(command_queue, "wait_for_result", lost)
    row = control.read_inventory(native.root, "supervised")["rows"][0]
    with pytest.raises(control.Unavailable):
        control.command(native.root, "supervised", "live-a", "stop", row["revision"])
    assert requests == [True] and native.calls == []


def test_handler_rejects_same_pid_new_process_and_arbitrary_dispatch(native, monkeypatch):
    from core.runtime_manager import daemon
    manager = daemon.RuntimeManagerDaemon()
    row = supervised.read_managed_evolution_metadata(native.owner)[0]
    args = {"kind": "supervised", "runId": "live-a", "action": "pause", "expectedRevision": row["revision"],
            "owner": {**native.owner, "createTime": native.owner["createTime"] - 1}}
    with pytest.raises(control.Conflict):
        manager._handle_managed_evolution_control(command_id="cmd-a", args=args)
    with pytest.raises(control.InputError):
        manager._handle_managed_evolution_control(command_id="cmd-a", args={**args, "method": "arbitrary"})
    assert native.calls == []


def test_unknown_state_and_oversized_response_never_claim_complete(native, endpoint, monkeypatch):
    supervised._RUN_STATES["live-a"]["status"] = "invented"
    with pytest.raises(control.Unavailable):
        control.read_inventory(native.root, "supervised")
    supervised._RUN_STATES["live-a"]["status"] = "running"
    monkeypatch.setattr(control, "MAX_RESPONSE_BYTES", 64)
    status, raw = _request(endpoint)
    assert status == 503 and b"SECRET" not in raw


def test_same_second_legacy_pause_resume_cannot_restore_an_old_cas_token(native, monkeypatch):
    monkeypatch.setattr(supervised, "_now_timestamp", lambda: "2026-11-03T10:00:00")
    supervised._LOCAL_REQUEST_PAUSE_SUPERVISED_RUN("live-a")
    supervised._LOCAL_REQUEST_RESUME_SUPERVISED_RUN("live-a")
    old = supervised.read_managed_evolution_metadata(native.owner)[0]
    supervised._LOCAL_REQUEST_PAUSE_SUPERVISED_RUN("live-a")
    supervised._LOCAL_REQUEST_RESUME_SUPERVISED_RUN("live-a")
    new = supervised.read_managed_evolution_metadata(native.owner)[0]
    assert old["status"] == new["status"] and old["commands"] == new["commands"]
    assert old["revision"] != new["revision"] and supervised._RUN_STATES["live-a"]["controlRevision"] == 4
    with pytest.raises(control.Conflict):
        supervised._LOCAL_REQUEST_PAUSE_SUPERVISED_RUN("live-a", expected_revision=old["revision"], expected_owner=native.owner)


def test_simultaneous_commands_only_admit_one_matching_version(native):
    row = supervised.read_managed_evolution_metadata(native.owner)[0]
    barrier = threading.Barrier(2)
    def pause():
        barrier.wait(timeout=2)
        try:
            supervised._LOCAL_REQUEST_PAUSE_SUPERVISED_RUN("live-a", expected_revision=row["revision"], expected_owner=native.owner)
            return "accepted"
        except control.Conflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _number: pause(), range(2)))
    assert sorted(results) == ["accepted", "conflict"] and native.calls == ["pause"]


def test_daemon_publishes_existing_identity_and_closes_task_owned_listener(native):
    from core.runtime_manager import daemon
    manager = daemon.RuntimeManagerDaemon()
    manager._start_evolution_metadata_server()
    try:
        assert manager._evolution_metadata_server is not None
        assert control.read_inventory(native.root, "supervised")["rows"][0]["runId"] == "live-a"
        assert set(state_store.load_pid_identity()) == {"pid", "createTime", "executable", "evolutionControl"}
    finally:
        manager._close_evolution_metadata_server()
    assert manager._evolution_metadata_server is None
    with pytest.raises(control.Unavailable):
        control.read_inventory(native.root, "supervised")


@pytest.mark.parametrize("kind", ["supervised", "self"])
def test_dangling_active_slot_cannot_be_reported_as_empty_or_repaired(native, endpoint, kind):
    service = supervised if kind == "supervised" else self_service
    service._RUN_STATES.clear()
    before = _files(native.root)
    with pytest.raises(control.Unavailable):
        control.read_inventory(native.root, kind)
    assert service._ACTIVE_RUN_ID == "live-a" and _files(native.root) == before


def _stable_args(native, action="pause"):
    row = supervised.read_managed_evolution_metadata(native.owner)[0]
    return {"kind": "supervised", "runId": "live-a", "action": action,
            "expectedRevision": row["revision"], "owner": native.owner}


def _outcome(native, args, request_id="request-a"):
    return control.read_command_outcome(native.root, args["kind"], args["runId"], args["action"],
                                        args["expectedRevision"], request_id=request_id)


def test_concurrent_stable_requests_create_one_original_queue_record(native):
    args = _stable_args(native)
    with ThreadPoolExecutor(max_workers=8) as executor:
        queued = list(executor.map(lambda _number: command_queue.submit_managed_evolution_command(
            native.root, "request-a", args=args), range(8)))
    assert len({item["commandId"] for item in queued}) == 1
    assert len(list(command_queue.INBOX_DIR.glob("*.json"))) == 1
    record = json.loads(next(command_queue.INBOX_DIR.glob("*.json")).read_text(encoding="utf-8"))
    assert len(record["managedBinding"]["argsSha256"]) == 64
    claimed = command_queue.claim_next_command()
    assert claimed is not None and command_queue.claim_next_command() is None
    assert _outcome(native, args)["state"] == "pending"


def test_stable_binding_rejects_same_address_with_changed_owner_or_payload(native):
    args = _stable_args(native)
    queued = command_queue.submit_managed_evolution_command(native.root, "request-a", args=args)
    with pytest.raises(command_queue.ManagedCommandConflict):
        command_queue.submit_managed_evolution_command(native.root, "request-a",
            args={**args, "owner": {**native.owner, "createTime": native.owner["createTime"] + 1}})
    path = command_queue.INBOX_DIR / (queued["commandId"] + ".json")
    record = json.loads(path.read_text(encoding="utf-8"))
    record["args"]["action"] = "stop"
    path.write_text(json.dumps(record), encoding="utf-8")
    before = _files(native.root)
    with pytest.raises(control.Conflict):
        _outcome(native, args)
    assert _files(native.root) == before


def test_lost_ack_recovers_original_native_result_after_manager_restart(native, endpoint, monkeypatch):
    from core.runtime_manager import daemon
    manager = daemon.RuntimeManagerDaemon()
    monkeypatch.setattr(manager, "_finish_command", lambda command_id, **kwargs:
                        {"commandId": command_id, "accepted": True, "completed": True, "ok": kwargs["ok"], **kwargs["result_data"]})
    monkeypatch.setattr(daemon, "capture_process_identity", lambda _pid: native.owner)
    args = _stable_args(native)
    def finish_then_lose(_command_id):
        path, payload = command_queue.claim_next_command()
        result = manager._handle_managed_evolution_control(command_id=payload["commandId"], args=payload["args"])
        command_queue.complete_command(path, result)
        raise TimeoutError("acknowledgement transport failed after native persistence")
    monkeypatch.setattr(command_queue, "wait_for_result", finish_then_lose)
    with pytest.raises(control.Unavailable):
        control.command(native.root, "supervised", "live-a", "pause", args["expectedRevision"], request_id="request-a")
    endpoint.close()
    state_store.DAEMON_IDENTITY_PATH.unlink()
    before = _files(native.root)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: pytest.fail("recovery initialized queue"))
    outcome = _outcome(native, args)
    assert outcome["state"] == "completed" and outcome["revisionCheck"] == "native_cas"
    assert outcome["operation"]["commands"] == ["stop", "resume"]
    replay = control.command(native.root, "supervised", "live-a", "pause", args["expectedRevision"], request_id="request-a")
    assert replay["operation"] == outcome["operation"] and native.calls == ["pause"]
    assert _files(native.root) == before and "SECRET" not in json.dumps(outcome)


def test_processing_after_restart_stays_unconfirmed_and_is_never_replayed(native, endpoint, monkeypatch):
    args = _stable_args(native)
    command_queue.submit_managed_evolution_command(native.root, "request-a", args=args)
    path, _payload = command_queue.claim_next_command()
    endpoint.close()
    assert command_queue.recover_processing_queue() == [] and path.exists()
    monkeypatch.setattr(command_queue, "submit_managed_evolution_command", lambda *_args, **_kwargs: pytest.fail("unknown native request replayed"))
    monkeypatch.setattr(command_queue, "wait_for_result", lambda _cid: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(control.Unavailable):
        control.command(native.root, "supervised", "live-a", "pause", args["expectedRevision"], request_id="request-a")
    assert _outcome(native, args)["state"] == "pending" and native.calls == []


def test_disappeared_original_record_is_not_automatically_enqueued_again(native, endpoint):
    args = _stable_args(native)
    queued = command_queue.submit_managed_evolution_command(native.root, "request-a", args=args)
    (command_queue.INBOX_DIR / (queued["commandId"] + ".json")).unlink()
    assert _outcome(native, args)["state"] == "unknown"
    with pytest.raises(control.Unavailable):
        control.command(native.root, "supervised", "live-a", "pause", args["expectedRevision"], request_id="request-a")
    assert list(command_queue.INBOX_DIR.glob("*.json")) == []


def test_shutdown_rejection_keeps_exact_original_native_request_proof(native, monkeypatch):
    args = _stable_args(native)
    monkeypatch.setattr(command_queue, "_shutdown_in_progress_state", lambda: {"stateVersion": 1})
    command_queue.submit_managed_evolution_command(native.root, "request-a", args=args)
    before = _files(native.root)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: pytest.fail("outcome read initialized state"))
    outcome = _outcome(native, args)
    assert outcome["state"] == "rejected" and outcome["operation"] is None and outcome["accepted"] is False
    assert _files(native.root) == before and native.calls == []


@pytest.mark.parametrize("action", ["pause", "resume", "stop"])
def test_original_ack_recovers_when_worker_settled_before_post_action_snapshot(native, action):
    from core.web.services.external_management.runtime_operations import read_command_receipt
    from core.web.services.external_management.runtime_contracts import RuntimeCommandResponse
    if action == "resume":
        supervised._RUN_STATES["live-a"].update(status="paused", pauseRequested=True)
    args = _stable_args(native, action)
    command_queue.submit_managed_evolution_command(native.root, "request-a", args=args)
    path, packet = command_queue.claim_next_command()
    # A worker can settle after the native control lock releases, before the
    # daemon's original result snapshot. Preserve that final observed state.
    final = {**supervised._RUN_STATES["live-a"], "status": "cancelled", "stopRequested": True}
    row = control.metadata_row("supervised", final, native.owner, live_context=True)
    command_queue.complete_command(path, {"commandId": packet["commandId"], "accepted": True,
        "completed": True, "ok": True, "operation": row, "revisionCheck": "native_cas"})
    outcome = _outcome(native, args)
    assert outcome["state"] == "completed" and outcome["stopRequested"] is (action == "stop")
    result = read_command_receipt(SimpleNamespace(project_root=native.root), {
        "kind": "supervised_run", "resource_id": "live-a", "command": action,
        "expected_revision": args["expectedRevision"]}, request_id="request-a")
    RuntimeCommandResponse.model_validate(result)
    assert result["operation"]["status"] == "cancelled" and result["stopRequested"] is (action == "stop")


@pytest.mark.parametrize("failure", [OSError, control.NotFound, control.InputError])
def test_post_admission_publication_failure_stays_unknown_and_never_replays(native, monkeypatch, failure):
    from core.runtime_manager import daemon
    manager = daemon.RuntimeManagerDaemon()
    monkeypatch.setattr(daemon, "capture_process_identity", lambda _pid: native.owner)
    monkeypatch.setattr(daemon, "should_execute_workbench_queue_command", lambda _kind: True)
    monkeypatch.setattr(daemon, "load_state", lambda: {})
    monkeypatch.setattr(daemon, "save_state", lambda state: state)
    monkeypatch.setattr(daemon, "_append_event", lambda *a, **kw: None)
    monkeypatch.setattr(manager, "_finish_command", lambda command_id, **kw: {
        "commandId": command_id, "accepted": True, "completed": True, "ok": kw["ok"],
        "errorType": kw.get("error_type", ""), **kw.get("result_data", {})})
    args = _stable_args(native)
    queued = command_queue.submit_managed_evolution_command(native.root, "request-a", args=args)
    path, payload = command_queue.claim_next_command()
    def fail_publish(*a, **kw):
        raise failure("publication failed after native controller accepted")
    monkeypatch.setattr(supervised, "_publish_run_snapshot", fail_publish)
    result = manager._handle_command(payload)
    command_queue.complete_command(path, result)
    assert native.calls == ["pause"]
    assert supervised._RUN_STATES["live-a"]["pauseRequested"] is True
    assert _outcome(native, args)["state"] == "unknown"
    # The original result itself fences replay even if its sidecar disappears.
    lock = command_queue.lock_path_for(command_queue.INBOX_DIR / (queued["commandId"] + ".json"))
    lock.unlink(missing_ok=True)
    before = _files(native.root)
    monkeypatch.setattr(control, "read_inventory", lambda *a, **kw: pytest.fail("uncertain result read current owner"))
    with pytest.raises(control.Unavailable):
        control.command(native.root, "supervised", "live-a", "pause", args["expectedRevision"], request_id="request-a")
    command_queue.submit_managed_evolution_command(native.root, "request-a", args=args)
    assert not list(command_queue.INBOX_DIR.glob("*.json")) and native.calls == ["pause"]
    # Rejoining may recreate only its lock; the original native result remains.
    assert all(_files(native.root)[key] == value for key, value in before.items())


def test_absent_outcome_is_pure_unknown(native, monkeypatch):
    args = _stable_args(native)
    before = _files(native.root)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: pytest.fail("unknown lookup initialized state"))
    outcome = _outcome(native, args)
    assert outcome["state"] == "unknown" and outcome["operation"] is None and outcome["accepted"] is False
    assert _files(native.root) == before
