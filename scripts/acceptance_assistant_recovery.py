#!/usr/bin/env python3
"""Real native tasks: outlive a 300s lease/host restart, then confirm cancellation.

Only the opt-in parent runner starts this case. The model must write and run the
ordinary unittest itself; this driver never supplies a tool result, edits task
records, renews leases, or shortens the real 330 second test.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import math
from pathlib import Path
import re
import secrets
import socket
import threading
import time
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from scripts import acceptance_local_assistant_development as base
from scripts.assistant_acceptance_support import (
    AssistantAcceptanceFixture, terminal_evidence, tool_calls,
)

require = base.require
AcceptanceFailure = base.AcceptanceFailure
WAIT_SECONDS = 330
LEASE_SECONDS = 300
TERMINAL_EVENTS = {"turn_completed", "turn_failed", "turn_interrupted"}
FAILED_TASKS = {"failed", "cancelled", "timed_out", "stop_unconfirmed"}
LOCAL_TASK_PREFIX = "/api/local-assistant/v1/external-agent/"
ACK_SUCCESS_MARKER = "ACK_PROBE_READ_COMPLETE"


class LostAcknowledgementProxy:
    """Owned loopback byte forwarder; drop one real accepted task response."""

    def __init__(self, upstream: str, client_request_id: str):
        parsed = urlsplit(upstream)
        try:
            loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
            port = parsed.port
        except ValueError:
            loopback, port = False, None
        require(parsed.scheme == "http" and loopback and port is not None and 0 < port < 65536
                and not parsed.username and not parsed.password and parsed.path in {"", "/"}
                and not parsed.query and not parsed.fragment, "ack_proxy_requires_loopback_upstream")
        self._upstream_host, self._upstream_port = parsed.hostname, port
        self._request_id = client_request_id
        self._lock = threading.Lock()
        self._quiet = threading.Condition(self._lock)
        self._active = 0
        self._post_ids: set[str] = set()
        self._lookup_ids: set[str] = set()
        self._counts = {key: 0 for key in ("forwardedRequestCount", "taskPostAttempts", "taskPostSuccessCount",
            "droppedAckCount", "requestLookupAttempts", "requestLookupSuccessCount", "proxyErrorCount")}
        self.url = ""
        self.closed = False

    def evidence(self) -> dict:
        with self._lock:
            return {**self._counts, "postNativeTaskIds": sorted(self._post_ids),
                    "lookupNativeTaskIds": sorted(self._lookup_ids)}

    @staticmethod
    def _allowed_path(method: str, path: str) -> bool:
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            return False
        if method == "GET" and parsed.path in {"/api/control-token", "/api/v1/external-agent/info"}:
            return True
        if not parsed.path.startswith(LOCAL_TASK_PREFIX):
            return False
        suffix = parsed.path[len(LOCAL_TASK_PREFIX):]
        return bool((method == "GET" and (suffix in {"agents", "task-request"}
                     or re.fullmatch(r"tasks/[A-Za-z0-9_-]{1,160}", suffix)))
                    or (method == "POST" and (suffix == "tasks"
                     or re.fullmatch(r"tasks/[A-Za-z0-9_-]{1,160}/(?:heartbeat|cancel)", suffix))))

    def __enter__(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass  # Never log paths, headers, request/response bodies or credentials.

            def setup(self):
                super().setup()
                self.connection.settimeout(15)

            def do_GET(self):
                owner._forward(self)

            def do_POST(self):
                owner._forward(self)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.url = "http://127.0.0.1:" + str(self._server.server_port)
        self._thread = threading.Thread(target=lambda: self._server.serve_forever(poll_interval=0.1),
                                        name="acceptance-lost-ack-proxy", daemon=True)
        try:
            self._thread.start()
        except Exception:
            self._server.server_close()
            raise AcceptanceFailure("ack_proxy_start_failed") from None
        return self

    def _forward(self, handler: BaseHTTPRequestHandler) -> None:
        with self._quiet:
            self._active += 1
        connection = None
        try:
            require(self._allowed_path(handler.command, handler.path), "ack_proxy_path_forbidden")
            length = int(handler.headers.get("Content-Length", "0"))
            require(0 <= length <= base.MAX_JSON_BYTES and not handler.headers.get("Transfer-Encoding"),
                    "ack_proxy_request_invalid")
            body = handler.rfile.read(length)
            require(len(body) == length, "ack_proxy_request_incomplete")
            parsed = urlsplit(handler.path)
            is_post = handler.command == "POST" and parsed.path == LOCAL_TASK_PREFIX + "tasks"
            is_lookup = (handler.command == "GET" and parsed.path == LOCAL_TASK_PREFIX + "task-request"
                         and parse_qs(parsed.query).get("client_request_id") == [self._request_id])
            if is_post:
                payload = json.loads(body)
                is_post = isinstance(payload, dict) and payload.get("client_request_id") == self._request_id
            with self._lock:
                self._counts["forwardedRequestCount"] += 1
                self._counts["taskPostAttempts"] += int(is_post)
                self._counts["requestLookupAttempts"] += int(is_lookup)
            hop = {"connection", "proxy-connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade"}
            headers = {key: value for key, value in handler.headers.items() if key.lower() not in hop | {"host"}}
            connection = http.client.HTTPConnection(self._upstream_host, self._upstream_port, timeout=15)
            connection.request(handler.command, handler.path, body=body or None, headers=headers)
            response = connection.getresponse()
            raw = response.read(base.MAX_JSON_BYTES + 1)
            require(len(raw) <= base.MAX_JSON_BYTES, "ack_proxy_response_limit_exceeded")
            drop = False
            if (is_post or is_lookup) and 200 <= response.status < 300:
                task_id = base.object_value(raw.decode("utf-8")).get("taskId")
                require(isinstance(task_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", task_id),
                        "ack_proxy_accepted_task_identity_missing")
                with self._lock:
                    if is_post:
                        self._counts["taskPostSuccessCount"] += 1
                        self._post_ids.add(task_id)
                        if self._counts["droppedAckCount"] == 0:
                            self._counts["droppedAckCount"] = 1
                            drop = True
                    if is_lookup:
                        self._counts["requestLookupSuccessCount"] += 1
                        self._lookup_ids.add(task_id)
            if drop:
                # The upstream has really committed its task. Send no status,
                # headers or body to the real SDK, producing an actual lost ACK.
                handler.close_connection = True
                try:
                    handler.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                handler.connection.close()
                return
            handler.send_response_only(response.status)
            for key, value in response.getheaders():
                if key.lower() not in hop | {"content-length"}:
                    handler.send_header(key, value)
            handler.send_header("Content-Length", str(len(raw)))
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.wfile.write(raw)
            handler.close_connection = True
        except Exception:
            with self._lock:
                self._counts["proxyErrorCount"] += 1
            try:
                handler.send_error(502)
            except OSError:
                pass
        finally:
            if connection is not None:
                connection.close()
            with self._quiet:
                self._active -= 1
                self._quiet.notify_all()

    def __exit__(self, *_exc):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=3)
        with self._quiet:
            quiet = self._quiet.wait_for(lambda: self._active == 0, timeout=20)
        self.closed = not self._thread.is_alive() and quiet
        require(self.closed, "ack_proxy_stop_unconfirmed")


def assert_lost_ack_proof(proof: dict, native_id: str, native_record_count: int) -> None:
    require(proof.get("taskPostSuccessCount", 0) >= 1 and proof.get("droppedAckCount") == 1,
            "ack_proxy_did_not_drop_real_acceptance")
    require(proof.get("requestLookupSuccessCount", 0) >= 1, "ack_request_lookup_not_observed")
    require(proof.get("postNativeTaskIds") == [native_id] and proof.get("lookupNativeTaskIds") == [native_id]
            and native_record_count == 1, "ack_recovery_created_duplicate_or_changed_task")
    require(proof.get("proxyErrorCount") == 0, "ack_proxy_forwarding_error")


def probe_source(marker_name: str) -> str:
    require(marker_name in {"recovery_probe.marker", "cancel_probe.marker"}, "invalid_probe_marker")
    return (
        "import os\nimport time\nimport unittest\nfrom pathlib import Path\n\n"
        f"MARKER = Path(__file__).with_name({marker_name!r})\n\n"
        "class RecoveryProbe(unittest.TestCase):\n"
        "    def test_authorized_bounded_wait(self):\n"
        "        values = (19, 23)\n"
        "        with MARKER.open('a', encoding='utf-8') as handle:\n"
        "            handle.write(f'START {time.monotonic():.6f} {os.getpid()}\\n')\n"
        "            handle.flush()\n"
        f"        time.sleep({WAIT_SECONDS})\n"
        "        self.assertEqual(sum(values), 42)\n"
        "        with MARKER.open('a', encoding='utf-8') as handle:\n"
        "            handle.write(f'FINISH {time.monotonic():.6f} {os.getpid()}\\n')\n"
        "            handle.flush()\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n"
    )


def probe_message(project_id: str, agent_id: str, dispatch_id: str, *, cancel: bool = False) -> str:
    module = "test_cancel_probe" if cancel else "test_recovery_probe"
    marker = "cancel_probe.marker" if cancel else "recovery_probe.marker"
    source = probe_source(marker)
    return (
        "这是用户明确授权的真实普通开发验收，包括测试体内330秒的有界等待。"
        f"目标 project_id={project_id}，agent_id={agent_id}，dispatch_id={dispatch_id}。"
        "如果你是 Launcher 个人助理：用真实工具发现projects/agents，再调用"
        "personal_assistant_manage_tool(action=dispatch_write)，将本条用户消息完整原文作为task，"
        "使用给定的project_id、agent_id、dispatch_id，只派遣一次。派遣被接收后简短回复并结束本轮，"
        "不要循环查询receipt，不创建Agent，不修改权限或配置。后续用户可能要求取消原任务。"
        "如果你是目标项目Agent：只使用系统为本任务绑定的专属Git worktree，文件工具路径与cwd"
        "必须是该worktree的绝对路径。禁止子Agent、其他AI CLI、网络、依赖安装、删除、提交Git、"
        "修改配置与其他文件。只允许新建下述两个文件。必须用真实write_file_tool分别新建"
        f"空文件{marker}和模块{module}.py；模块内容逐字如下（不要改动等待时长或添加测试）：\n"
        "```python\n" + source + "```\n"
        f"随后只启动一次真实exec_command：cmd逐字为python -m unittest {module} -v，"
        "cwd是专属worktree绝对路径，timeout=600，yield_time_ms=1000。"
        "这是用户授权的实际unittest，禁止改用python -c或其他睡眠命令。返回running时使用同一"
        "terminalSessionId调用write_stdin(chars为空，yield_time_ms=10000)，一直轮询到真实退出；"
        "不得重启命令、重置marker或提前结束。测试负责写START/FINISH并断言数据；"
        "若正常完成，报告真实命令、1个test OK及退出码；若取消，如实停止，不伪报成功。"
    )


def marker_rows(path: Path) -> list[dict]:
    """Read only complete appends; reject duplicates and malformed time evidence."""
    if not path.exists():
        return []
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 2048,
            "probe_marker_invalid")
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        if not line.endswith("\n"):
            continue  # a live writer may be between write and flush
        fields = line.split()
        require(len(fields) == 3 and fields[0] in {"START", "FINISH"}, "probe_marker_malformed")
        try:
            seconds, pid = float(fields[1]), int(fields[2])
        except ValueError:
            raise AcceptanceFailure("probe_marker_malformed") from None
        require(math.isfinite(seconds) and seconds > 0 and pid > 0, "probe_marker_malformed")
        rows.append({"phase": fields[0], "seconds": seconds, "pid": pid})
    require([row["phase"] for row in rows] in ([], ["START"], ["START", "FINISH"]),
            "probe_marker_duplicate_or_reordered")
    if len(rows) == 2:
        require(rows[0]["pid"] == rows[1]["pid"] and rows[1]["seconds"] > rows[0]["seconds"],
                "probe_marker_process_or_time_changed")
    return rows


def native_identity(dispatch: dict, task: dict) -> dict:
    identity = {"dispatchId": dispatch.get("dispatchId"), "nativeTaskId": dispatch.get("nativeTaskId"),
                "sessionId": task.get("sessionId"), "turnId": task.get("turnId")}
    require(all(isinstance(value, str) and value for value in identity.values()), "native_identity_missing")
    require(identity["nativeTaskId"] == task.get("taskId"), "native_task_identity_mismatch")
    return identity


def assert_same_identity(expected: dict, dispatch: dict, task: dict) -> None:
    require(native_identity(dispatch, task) == expected, "native_identity_changed")


def single_native_turn(events: list[dict], task: dict, terminal: str = "") -> dict:
    admissions = [row for row in events if row.get("eventType") == "user_message"]
    starts = [row for row in events if row.get("eventType") == "turn_started"]
    require(len(admissions) == 1 and len(starts) == 1, "native_admission_or_turn_duplicated")
    require(all(row.get("sessionId") == task["sessionId"] and row.get("turnId") == task["turnId"]
                for row in [*admissions, *starts]), "native_admission_binding_changed")
    terminals = [row for row in events if row.get("eventType") in TERMINAL_EVENTS]
    if terminal:
        require(len(terminals) == 1 and terminals[0].get("eventType") == terminal
                and terminals[0].get("turnId") == task["turnId"], "native_journal_terminal_unconfirmed")
    else:
        require(not terminals, "native_turn_ended_before_fault")
    return {"userAdmissionCount": len(admissions), "turnCount": len(starts), "terminalCount": len(terminals)}


def long_duration(rows: list[dict], observed_seconds: float) -> float:
    require(len(rows) == 2, "long_probe_start_finish_missing")
    elapsed = rows[1]["seconds"] - rows[0]["seconds"]
    # Independent driver time protects the claim even if marker data is wrong.
    require(elapsed > LEASE_SECONDS and observed_seconds > LEASE_SECONDS,
            "real_long_task_did_not_exceed_lease")
    return elapsed


def running_terminal(events: list[dict], command: str) -> str:
    calls = tool_calls(events)
    launches = [row for row in calls if row["callName"] == "exec_command"
                and str(row["args"].get("cmd") or row["args"].get("command") or "").strip() == command]
    require(len(launches) == 1, "probe_command_missing_or_duplicated")
    result = launches[0]["result"]
    terminal_id = str(result.get("terminalSessionId") or "")
    require(terminal_id and result.get("status") == "running"
            and type(result.get("exitCode", result.get("exit_code"))) is not int,
            "probe_terminal_not_running")
    for row in calls:
        if row["callName"] == "write_stdin" and row["args"].get("session_id") == terminal_id:
            require(row["result"].get("status") == "running"
                    and type(row["result"].get("exitCode", row["result"].get("exit_code"))) is not int,
                    "probe_terminal_already_completed")
    return terminal_id


def _assistant_action(events: list[dict], action: str, identity: dict, project_id: str) -> bool:
    for row in tool_calls(events):
        args = row["args"]
        if row["callName"] != "personal_assistant_manage_tool" or args.get("action") != action:
            continue
        parameters = base.object_value(args.get("arguments_json") or args.get("arguments"))
        if (parameters.get("dispatch_id") == identity["dispatchId"] and parameters.get("project_id") == project_id
                and (action != "dispatch_cancel" or parameters.get("native_task_id") == identity["nativeTaskId"])
                and row["status"] not in {"failed", "error", "blocked", "cancelled"}):
            return True
    return False


def _lease(value: Any) -> float:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        require(parsed.tzinfo is not None, "native_lease_invalid")
        return parsed.timestamp()
    except (ValueError, OverflowError):
        raise AcceptanceFailure("native_lease_invalid") from None


def _process_identity(pid: int) -> tuple[int, float]:
    import psutil
    try:
        process = psutil.Process(pid)
        require(process.is_running(), "probe_process_not_running")
        return pid, process.create_time()
    except psutil.Error:
        raise AcceptanceFailure("probe_process_not_running") from None


def _process_alive(identity: tuple[int, float]) -> bool:
    import psutil
    try:
        process = psutil.Process(identity[0])
        return process.is_running() and abs(process.create_time() - identity[1]) < 0.01
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        raise AcceptanceFailure("probe_process_state_unavailable") from None


def _workspace(task: dict, source: Path) -> Path:
    value = task.get("localWorkspacePath")
    require(isinstance(value, str) and Path(value).is_absolute(), "probe_workspace_missing")
    path = Path(value)
    require(path.resolve() != source.resolve() and path.is_dir() and (path / ".git").is_file(),
            "probe_workspace_not_native_worktree")
    return path


def _verify_files(task: dict, events: list[dict], source: Path, main_head: str, *, cancel: bool) -> dict:
    workspace = _workspace(task, source)
    module = "test_cancel_probe" if cancel else "test_recovery_probe"
    marker = "cancel_probe.marker" if cancel else "recovery_probe.marker"
    allowed = {module + ".py", marker}
    changed = set(base.git(workspace, "diff", "--name-only", "-z", main_head).split("\0")) - {""}
    changed.update(set(base.git(workspace, "ls-files", "--others", "--exclude-standard", "-z").split("\0")) - {""})
    require(changed == allowed, "probe_changed_files_outside_fixture_or_missing")
    require(base.git(workspace, "branch", "--show-current").strip().startswith("codex/assistant-"),
            "probe_workspace_branch_invalid")
    require(base.git(workspace, "rev-parse", "HEAD").strip() == main_head, "probe_agent_committed_changes")
    registered = base.git(source, "worktree", "list", "--porcelain")
    require(any(Path(line[9:]).resolve() == workspace.resolve()
                for line in registered.splitlines() if line.startswith("worktree ")),
            "probe_workspace_not_registered")
    content_path = workspace / (module + ".py")
    require(not content_path.is_symlink() and content_path.stat().st_size <= 8192, "probe_module_invalid")
    require(content_path.read_text(encoding="utf-8").strip() == probe_source(marker).strip(),
            "probe_module_changed_authorized_test")
    written = []
    command = f"python -m unittest {module} -v"
    for row in tool_calls(events):
        if row["callName"] == "write_file_tool" and row["status"] not in {"failed", "error", "blocked", "cancelled"}:
            value = row["args"].get("file_path")
            require(isinstance(value, str) and Path(value).is_absolute(), "probe_write_path_not_absolute")
            names = [name for name in allowed if Path(value).resolve() == (workspace / name).resolve()]
            require(len(names) == 1, "probe_write_outside_allowed_files")
            name = names[0]
            expected_content = "" if name == marker else probe_source(marker)
            actual_content = row["args"].get("content")
            require(isinstance(actual_content, str) and actual_content.strip() == expected_content.strip(),
                    "probe_written_content_changed")
            written.append(name)
        require(row["callName"] not in {"apply_diff_edit_tool", "apply_patch_tool", "cli_tool"},
                "unexpected_probe_mutation_or_shell_tool")
        if row["callName"] == "exec_command":
            require(str(row["args"].get("cmd") or "").strip() == command, "unexpected_probe_shell_command")
            require(Path(str(row["args"].get("cwd") or "")).resolve() == workspace.resolve(),
                    "probe_command_cwd_outside_workspace")
    require(len(written) == 2 and set(written) == allowed, "probe_real_write_file_tools_missing_or_repeated")
    require(not base.git(source, "status", "--porcelain", "--", *sorted(allowed)).strip(),
            "probe_files_written_in_parent_checkout")
    return {"workspaceSha256": hashlib.sha256(str(workspace.resolve()).encode()).hexdigest(),
            "moduleSha256": hashlib.sha256(content_path.read_bytes()).hexdigest(),
            "changedFileCount": len(changed), "writeFileCount": len(written)}


def _dispatch_task(fixture: AssistantAcceptanceFixture, dispatch_id: str, allowed_ids: set[str], agent_id: str):
    require(fixture.host_process is not None and fixture.host_process.poll() is None, "assistant_host_exited")
    fixture.assert_no_approvals()
    rows = fixture.dispatches()
    require(all(row.get("dispatchId") in allowed_ids for row in rows), "unexpected_recovery_dispatch")
    matches = [row for row in rows if row.get("dispatchId") == dispatch_id]
    require(len(matches) <= 1, "duplicate_recovery_dispatch")
    if not matches:
        return None, None
    dispatch = matches[0]
    require(dispatch.get("projectId") == fixture.primary_project_id and dispatch.get("agentId") == agent_id,
            "recovery_dispatch_target_changed")
    native_id = dispatch.get("nativeTaskId")
    return dispatch, fixture.task(native_id) if native_id else None


def _events(fixture: AssistantAcceptanceFixture, task: dict) -> list[dict]:
    # Read the whole native session so a second admission/turn cannot be hidden
    # by target_events' intentional per-turn filter.
    return base.journal_events(fixture.home, task["sessionId"])


def _await_running(fixture, dispatch_id, allowed_ids, agent_id, command, marker, deadline, record):
    while time.monotonic() < deadline:
        dispatch, task = _dispatch_task(fixture, dispatch_id, allowed_ids, agent_id)
        if record.get("nativeTaskId"):
            require(dispatch is not None and task is not None
                    and dispatch.get("nativeTaskId") == record["nativeTaskId"], "native_identity_changed")
        if task:
            require(dispatch.get("dispatchId") == dispatch_id
                    and isinstance(task.get("taskId"), str) and task["taskId"]
                    and dispatch.get("nativeTaskId") == task["taskId"], "native_identity_changed")
            observed = {"dispatchId": dispatch_id, "nativeTaskId": task["taskId"],
                        "sessionId": task.get("sessionId"), "turnId": task.get("turnId")}
            for key, value in observed.items():
                if record.get(key):
                    require(record[key] == value, "native_identity_changed")
                elif value:
                    require(isinstance(value, str), "native_identity_missing")
                    record[key] = value
            record["nativeTaskStatus"] = task.get("status")
            # Admission can persist the native task before the worker creates
            # its workspace/session. Keep the original binding while queued.
            if task.get("status") == "queued":
                time.sleep(2)
                continue
            workspace = _workspace(task, fixture.source)
            require(task.get("status") not in FAILED_TASKS | {"succeeded"}, "probe_ended_before_fault")
            events = _events(fixture, task)
            rows = marker_rows(workspace / marker)
            matching = [row for row in tool_calls(events) if row["callName"] == "exec_command"
                        and str(row["args"].get("cmd") or "").strip() == command]
            if task.get("status") == "running" and rows and matching:
                require(len(rows) == 1, "probe_finished_before_fault")
                identity = native_identity(dispatch, task)
                record.update(identity)
                record.update(single_native_turn(events, task))
                terminal_id = running_terminal(events, command)
                process = _process_identity(rows[0]["pid"])
                require(_assistant_action(fixture.assistant_events(), "dispatch_write", identity,
                                          fixture.primary_project_id), "real_assistant_dispatch_write_missing")
                record.update(terminalSessionId=terminal_id, processId=process[0], startCount=1, finishCount=0,
                              workspaceBaseCommit=base.git(workspace, "rev-parse", "HEAD").strip())
                return dispatch, task, terminal_id, process
        time.sleep(2)
    raise AcceptanceFailure("probe_running_evidence_timeout")


def assert_confirmed_cancel(task: dict, events: list[dict], detail: dict, rows: list[dict], process_alive: bool) -> None:
    require(task.get("status") == "cancelled" and str(task.get("reasonCode") or "").endswith("_confirmed")
            and task.get("stopRequestedAt") and task.get("stopSignalSentAt"), "native_cancel_not_confirmed")
    single_native_turn(events, task, "turn_interrupted")
    runtime = detail.get("runtime") if isinstance(detail.get("runtime"), dict) else {}
    phase = str(detail.get("phase") or detail.get("status") or detail.get("lastTurnStatus")
                or runtime.get("phase") or runtime.get("status") or detail.get("currentPhase") or "").lower()
    flags = [detail[key] for key in ("running", "isRunning") if type(detail.get(key)) is bool]
    require(True not in flags and (False in flags or phase in {"stopped", "cancelled", "interrupted", "idle", "ready"})
            and phase not in {"queued", "running", "working", "busy", "stopping", "cancelling"},
            "native_worker_stop_unconfirmed")
    require(len(rows) == 1 and rows[0]["phase"] == "START", "cancelled_probe_reached_finish")
    require(not process_alive, "cancelled_probe_process_still_running")


def _run_lost_ack(fixture: AssistantAcceptanceFixture, record: dict, deadline: float,
                  agent_id: str, previous_ids: set[str]) -> None:
    """Submit one short read-only task through the real model/SDK/backend."""
    backend = fixture.backends[fixture.primary_project_id]
    descriptor = backend.runtime_root / "launcher" / "state.json"
    require(base.inside(descriptor, fixture.home) and descriptor.is_file() and not descriptor.is_symlink(),
            "ack_descriptor_not_private")
    original = descriptor.read_bytes()
    require(len(original) <= base.MAX_JSON_BYTES, "ack_descriptor_limit_exceeded")
    descriptor_value = base.object_value(original.decode("utf-8-sig"))
    require(descriptor_value.get("url") == backend.url, "ack_descriptor_backend_changed")
    fixture.stop_host()  # No adapter can retain the old URL while it changes.
    dispatch_id = "lost-ack-" + secrets.token_hex(8)
    client_request_id = "launcher-assistant:" + dispatch_id
    readme = backend.root / "README.md"
    with readme.open(encoding="utf-8-sig") as handle:
        expected_line = handle.readline(2048).strip()
    require(expected_line, "ack_read_fixture_empty")
    proxy = LostAcknowledgementProxy(backend.url, client_request_id)
    changed_descriptor = False
    record.update(status="starting", dispatchId=dispatch_id)
    try:
        with proxy:
            base.private_json(descriptor, {**descriptor_value, "url": proxy.url})
            changed_descriptor = True
            try:
                fixture.start_host()
                message = (
                    "这是用户授权的本机丢失接收确认验收，只派遣一个短只读任务。"
                    f"project_id={fixture.primary_project_id}，agent_id={agent_id}，dispatch_id={dispatch_id}。"
                    "如果你是Launcher个人助理：用personal_assistant_action_tool(action=dispatch, parameters对象)"
                    "派遣给定目标，task为本条完整原文，只提交一次。即使返回连接错误也不能重复提交或换ID，"
                    "只用receipt查询原dispatch_id，或等待原生host恢复原引用，不修改配置、权限或创建Agent。"
                    "如果你是目标Agent：只调用一次真实read_file_tool，"
                    f"file_path={json.dumps(str(readme), ensure_ascii=False)}，offset=0，max_lines=5。"
                    "不要执行命令、写文件、创建子Agent或访问网络。读取成功后只回答标记"
                    f" {ACK_SUCCESS_MARKER}。"
                )
                fixture.send(message, request_id=dispatch_id)
                record["status"] = "waiting_for_original_request_lookup"
                identity = None
                while time.monotonic() < deadline:
                    dispatch, task = _dispatch_task(fixture, dispatch_id, previous_ids | {dispatch_id}, agent_id)
                    record.update(proxy.evidence())
                    if task:
                        record.update(nativeTaskId=task.get("taskId"), nativeTaskStatus=task.get("status"))
                        require(task.get("status") not in FAILED_TASKS, "ack_native_task_failed")
                        if task.get("status") != "queued":
                            current = native_identity(dispatch, task)
                            require(identity is None or current == identity, "ack_native_identity_changed")
                            identity = current
                            record.update(current)
                        if task.get("status") == "succeeded":
                            require(task.get("effectivePermissionProfile") == "read_only"
                                    and (dispatch.get("receipt") or {}).get("effectivePermissionProfile") == "read_only",
                                    "ack_probe_not_read_only")
                            events = _events(fixture, task)
                            calls = tool_calls(events)
                            reads = [row for row in calls if row["callName"] == "read_file_tool"
                                     and Path(str(row["args"].get("file_path") or "")).resolve() == readme.resolve()]
                            require(len(calls) == len(reads) == 1 and expected_line in reads[0]["resultText"],
                                    "ack_real_read_only_tool_evidence_missing")
                            require(ACK_SUCCESS_MARKER in base.final_answer(events), "ack_target_read_receipt_missing")
                            launches = [row for row in tool_calls(fixture.assistant_events())
                                if row["callName"] == "personal_assistant_action_tool"
                                and row["args"].get("action") == "dispatch"
                                and base.object_value(row["args"].get("parameters")).get("dispatch_id") == dispatch_id]
                            require(launches, "ack_real_assistant_dispatch_missing")
                            task_paths = list((backend.runtime_root / "local_assistant_tasks" / "tasks").glob("*.json"))
                            require(len(task_paths) <= 16, "ack_native_task_evidence_limit_exceeded")
                            count = sum(base.read_json(path).get("clientRequestId") == client_request_id for path in task_paths)
                            assert_lost_ack_proof(proxy.evidence(), task["taskId"], count)
                            record.update(single_native_turn(events, task, "turn_completed"))
                            record.update(nativeRecordCount=count,
                                readOutputSha256=hashlib.sha256(reads[0]["resultText"].encode()).hexdigest())
                            break
                    time.sleep(2)
                else:
                    raise AcceptanceFailure("ack_original_request_recovery_timeout")
            finally:
                # Quiesce the real adapter before stopping its proxy or restoring
                # discovery; this shutdown never cancels remote native tasks.
                try:
                    fixture.stop_host()
                except Exception:
                    fixture.force_stop_host_after_failure()
                    raise
    finally:
        record.update(proxy.evidence(), proxyStopped=proxy.closed)
        stopped = fixture.host_process is None or fixture.host_process.poll() is not None
        record["descriptorRestored"] = not changed_descriptor
        if changed_descriptor and stopped and proxy.closed:
            descriptor.write_bytes(original)
            record["descriptorRestored"] = descriptor.read_bytes() == original
        require(stopped, "ack_host_stop_unconfirmed")
        require(not changed_descriptor or proxy.closed, "ack_proxy_stop_unconfirmed")
        require(record["descriptorRestored"], "ack_descriptor_restore_unconfirmed")
    record["status"] = "passed"


def run_case(fixture: AssistantAcceptanceFixture, evidence: dict, timeout: float = 1100) -> None:
    require(WAIT_SECONDS > LEASE_SECONDS, "probe_wait_must_exceed_real_lease")
    deadline = time.monotonic() + timeout
    project_root = fixture.source
    fixture.start_backend()
    agent_id = fixture.create_agent("Recovery acceptance ordinary target")
    fixture.start_host()
    require(not fixture.dispatches(), "recovery_fixture_must_start_empty")
    long_id, cancel_id = "recovery-" + secrets.token_hex(8), "cancel-" + secrets.token_hex(8)
    long_record: dict[str, Any] = {"status": "starting", "waitSeconds": WAIT_SECONDS, "leaseSeconds": LEASE_SECONDS}
    cancel_record: dict[str, Any] = {"status": "not_started", "waitSeconds": WAIT_SECONDS}
    evidence.update(longTask=long_record, cancellation=cancel_record, lostAcknowledgement={"status": "not_tested"})
    fixture.send(probe_message(fixture.primary_project_id, agent_id, long_id), request_id=long_id)
    _, task, terminal_id, process = _await_running(fixture, long_id, {long_id}, agent_id,
        "python -m unittest test_recovery_probe -v", "recovery_probe.marker", deadline, long_record)
    running_observed_at = time.monotonic()
    identity = dict((key, long_record[key]) for key in ("dispatchId", "nativeTaskId", "sessionId", "turnId"))
    initial_lease = _lease(task.get("leaseExpiresAt"))
    initial_created = _lease(task.get("createdAt"))
    require(abs(initial_lease - initial_created - LEASE_SECONDS) <= 1 or initial_lease > initial_created + LEASE_SECONDS,
            "unexpected_native_lease")
    long_record.update(status="waiting_before_restart", leaseExpiresAtFirst=task["leaseExpiresAt"])
    # Observe at least one real resident heartbeat before interrupting the host.
    while time.monotonic() < deadline:
        dispatch, task = _dispatch_task(fixture, long_id, {long_id}, agent_id)
        require(task is not None, "native_task_lost")
        assert_same_identity(identity, dispatch, task)
        require(task.get("status") == "running", "native_task_ended_before_restart")
        require(len(marker_rows(_workspace(task, fixture.source) / "recovery_probe.marker")) == 1,
                "probe_finished_before_restart")
        if _lease(task.get("leaseExpiresAt")) > initial_lease:
            break
        time.sleep(2)
    else:
        raise AcceptanceFailure("resident_heartbeat_not_observed")
    before_restart_lease = _lease(task["leaseExpiresAt"])
    old_host, assistant_session = fixture.host_process, fixture.session_id
    long_record.update(status="restarting_host", hostPidBefore=old_host.pid, leaseExpiresAtBeforeRestart=task["leaseExpiresAt"])
    fixture.restart_host()
    require(old_host.poll() is not None and fixture.host_process.pid != old_host.pid, "host_restart_not_observed")
    require(fixture.session_id == assistant_session and _process_alive(process), "restart_changed_session_or_probe_process")
    dispatch, task = _dispatch_task(fixture, long_id, {long_id}, agent_id)
    require(task is not None and task.get("status") == "running", "native_task_not_running_after_restart")
    assert_same_identity(identity, dispatch, task)
    require(running_terminal(_events(fixture, task), "python -m unittest test_recovery_probe -v") == terminal_id,
            "probe_terminal_changed_on_restart")
    single_native_turn(_events(fixture, task), task)
    long_record.update(status="waiting_after_restart", hostPidAfter=fixture.host_process.pid)
    while time.monotonic() < deadline:
        dispatch, task = _dispatch_task(fixture, long_id, {long_id}, agent_id)
        require(task is not None, "native_task_lost_after_restart")
        assert_same_identity(identity, dispatch, task)
        long_record.update(nativeTaskStatus=task.get("status"), leaseExpiresAtLast=task.get("leaseExpiresAt"))
        require(task.get("status") not in FAILED_TASKS, "native_long_task_failed")
        if task.get("status") == "succeeded":
            events = _events(fixture, task)
            proof = terminal_evidence(events, "python -m unittest test_recovery_probe -v", expected_tests=1)
            require(len(proof["terminals"]) == 1 and proof["terminals"][0]["terminalSessionId"] == terminal_id
                    and proof["testExitCode"] == 0, "real_long_unittest_exit_zero_missing")
            rows = marker_rows(_workspace(task, fixture.source) / "recovery_probe.marker")
            observed_elapsed = time.monotonic() - running_observed_at
            elapsed = long_duration(rows, observed_elapsed)
            require(_lease(task["leaseExpiresAt"]) > before_restart_lease, "heartbeat_after_restart_missing")
            long_record.update(single_native_turn(events, task, "turn_completed"))
            long_record.update(_verify_files(task, events, project_root, long_record["workspaceBaseCommit"], cancel=False))
            long_record.update(proof)
            long_record.update(status="passed", startCount=1, finishCount=1, elapsedSeconds=round(elapsed, 3),
                               observedElapsedSeconds=round(observed_elapsed, 3),
                               leaseAdvanced=True, sameNativeIdentity=True)
            evidence["longTaskPassed"] = True
            break
        time.sleep(2)
    else:
        raise AcceptanceFailure("native_long_task_timeout")

    cancel_record["status"] = "starting"
    fixture.send(probe_message(fixture.primary_project_id, agent_id, cancel_id, cancel=True), request_id=cancel_id)
    _, task, _, process = _await_running(fixture, cancel_id, {long_id, cancel_id}, agent_id,
        "python -m unittest test_cancel_probe -v", "cancel_probe.marker", deadline, cancel_record)
    identity = dict((key, cancel_record[key]) for key in ("dispatchId", "nativeTaskId", "sessionId", "turnId"))
    fixture.send(
        f"现在明确要求停止刚才的测试任务：project_id={fixture.primary_project_id}，"
        f"dispatch_id={cancel_id}，native_task_id={identity['nativeTaskId']}。"
        "请调用personal_assistant_manage_tool(action=dispatch_cancel)，只取消这一个原任务。"
        "不要再派遣，不要修改文件或权限；stop_unconfirmed只是请求已发出，必须如实报告尚未确认。",
        request_id=cancel_id + "-user-cancel")
    cancel_record["status"] = "cancel_requested"
    last_failure = "native_cancel_not_confirmed"
    while time.monotonic() < deadline:
        dispatch, task = _dispatch_task(fixture, cancel_id, {long_id, cancel_id}, agent_id)
        require(task is not None, "native_cancel_task_lost")
        assert_same_identity(identity, dispatch, task)
        rows = marker_rows(_workspace(task, fixture.source) / "cancel_probe.marker")
        cancel_record.update(nativeTaskStatus=task.get("status"), startCount=sum(row["phase"] == "START" for row in rows),
                             finishCount=sum(row["phase"] == "FINISH" for row in rows))
        require(len(rows) == 1, "cancelled_probe_reached_finish")
        require(task.get("status") not in {"succeeded", "failed", "timed_out"}, "native_cancel_task_wrong_terminal")
        if task.get("status") == "cancelled":
            events = _events(fixture, task)
            detail = fixture.backend(fixture.primary_project_id,
                "/api/sessions/" + quote(task["sessionId"], safe="") + "?messageLimit=0&transcriptScope=none&includeSecondary=false")
            try:
                assert_confirmed_cancel(task, events, detail, rows, _process_alive(process))
                require(_assistant_action(fixture.assistant_events(), "dispatch_cancel", identity,
                                          fixture.primary_project_id), "real_assistant_dispatch_cancel_missing")
            except AcceptanceFailure as exc:
                last_failure = str(exc)
            else:
                cancel_record.update(single_native_turn(events, task, "turn_interrupted"))
                cancel_record.update(_verify_files(task, events, project_root, cancel_record["workspaceBaseCommit"], cancel=True))
                cancel_record.update(status="passed", startCount=1, finishCount=0, workerStopped=True,
                                     processStopped=True, reasonCode=task.get("reasonCode"), sameNativeIdentity=True)
                evidence["cancellationPassed"] = True
                fixture.assert_no_approvals()
                break
        time.sleep(2)
    else:
        raise AcceptanceFailure(last_failure)
    _run_lost_ack(fixture, evidence["lostAcknowledgement"], deadline, agent_id, {long_id, cancel_id})
