#!/usr/bin/env python3
"""Private, opt-in fixtures for real assistant acceptance (never a provider mock).

Raw prompts, credentials and tool outputs stay in the private fixture home. Only
the deliberately small ``record`` dictionary is suitable for exported evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import tomllib
from typing import Any

from scripts import acceptance_local_assistant_development as base
from scripts import acceptance_runtime
from scripts.windowless_subprocess import no_window_subprocess_kwargs

SOURCE_ROOT = Path(__file__).resolve().parents[1]
AcceptanceFailure = base.AcceptanceFailure
require = base.require


@dataclass(frozen=True)
class Backend:
    project_id: str
    root: Path
    instance_id: str
    url: str
    runtime_root: Path


def tool_calls(events: list[dict]) -> list[dict]:
    """Bind results only to the same call ID, session and turn; keep data private."""
    starts: dict[tuple[str, str, str], dict] = {}
    rows: list[dict] = []
    for event in events:
        kind = event.get("eventType")
        if kind not in {"tool_call_started", "tool_result"}:
            continue
        payload = event.get("payload") or {}
        call = payload.get("toolCall") or payload
        call_id = str(event.get("toolCallId") or call.get("id") or call.get("toolCallId") or call.get("callId") or "")
        key = (str(event.get("sessionId") or ""), str(event.get("turnId") or ""), call_id)
        name = str(call.get("name") or call.get("toolName") or "")
        args = base.object_value(call.get("arguments") or call.get("args"))
        if kind == "tool_call_started":
            if call_id:
                starts[key] = {"callName": name, "args": args, "startedAt": event.get("timestamp"),
                               "startedSequence": event.get("sequence")}
            continue
        previous = starts.get(key, {}) if call_id else {}
        rows.append({"callId": call_id, "callName": name or previous.get("callName", ""),
                     "args": args or previous.get("args", {}),
                     "result": base.object_value(call.get("result")),
                     "resultText": call.get("result") if isinstance(call.get("result"), str) else json.dumps(call.get("result"), ensure_ascii=False),
                     "status": event.get("status") or call.get("status"),
                     "startedAt": previous.get("startedAt"), "finishedAt": event.get("timestamp"),
                     "startedSequence": previous.get("startedSequence"), "finishedSequence": event.get("sequence"),
                     "sessionId": key[0], "turnId": key[1]})
    require(len(rows) <= 2000, "tool_call_evidence_limit_exceeded")
    return rows


def terminal_evidence(events: list[dict], command: str, expected_tests: int | None = None) -> dict:
    """Aggregate matching exec/poll chunks without borrowing another terminal's exit."""
    terminals: dict[tuple[str, str, str], dict] = {}
    completed: list[dict] = []
    for row in tool_calls(events):
        args, result = row["args"], row["result"]
        terminal_id = str(result.get("terminalSessionId") or "")
        name = row["callName"]
        current_command = str(args.get("cmd") or args.get("command") or "").strip()
        scope = (row["sessionId"], row["turnId"])
        if name == "exec_command" and current_command == command:
            key = (*scope, terminal_id or "call:" + row["callId"])
            require(bool(terminal_id or row["callId"]), "terminal_call_identity_missing")
            state = terminals.setdefault(key, {"output": "", "exitCode": None})
        elif name == "write_stdin":
            key = (*scope, str(args.get("session_id") or ""))
            state = terminals.get(key)
            if state is None or (terminal_id and terminal_id != key[-1]):
                continue
        else:
            continue
        state["output"] = (state["output"] + str(result.get("stdout") or "") + "\n"
                           + str(result.get("stderr") or ""))[-65536:]
        exit_code = result.get("exitCode", result.get("exit_code"))
        if type(exit_code) is int:
            state["exitCode"] = exit_code
    for key, state in terminals.items():
        output = state["output"]
        tests_ok = expected_tests is None or bool(
            re.search(rf"Ran {expected_tests} tests?\b", output) and re.search(r"(?m)^OK\s*$", output))
        completed.append({"terminalSessionId": key[-1], "exitCode": state["exitCode"],
                          "expectedTestsObserved": tests_ok, "outputSha256": hashlib.sha256(output.encode()).hexdigest(),
                          "outputBytes": len(output.encode())})
    success = any(row["exitCode"] == 0 and row["expectedTestsObserved"] for row in completed)
    return {"testExitCode": 0 if success else None, "terminals": completed}


class AssistantAcceptanceFixture:
    """Own only isolated state and processes created by this context manager."""

    def __init__(self, home: Path, source_config: Path, model_id: str,
                 source: Path = SOURCE_ROOT, readiness_timeout: float = 120):
        self.home, self.source_config, self.source = home.resolve(), source_config.resolve(), source.resolve()
        self.runtime_home = self.home / "backends"
        self.model_id, self.readiness_timeout = model_id, readiness_timeout
        self.env: dict[str, str] = {}
        self.profile = self.home / "localappdata" / "Vibelution" / "DesktopShell" / "assistant" / "profile"
        self.host_url = ""
        self.host_process: subprocess.Popen | None = None
        self.session_id = ""
        self.backends: dict[str, Backend] = {}
        self._owned_backend_ids: dict[str, str] = {}
        self.primary_project_id = "acceptance-primary"
        self.cleanup: dict[str, bool] = {"assistantStopped": True, "backendsStopped": True}
        self.record: dict[str, Any] = {"schemaVersion": 1, "modelId": model_id, "cleanup": self.cleanup}
        self._host_token = secrets.token_urlsafe(32)
        self._host_instance_id = "assistant-acceptance-" + secrets.token_hex(6)
        self._host_create_time: float | None = None
        self._entered = False

    def __enter__(self):
        require(not self._entered, "fixture_already_entered")
        require(base.inside(self.home, Path(tempfile.gettempdir())) and not self.home.is_relative_to(self.source),
                "runtime_home_must_be_private_system_temp")
        require(not self.home.exists() or not any(self.home.iterdir()), "runtime_home_must_be_unused")
        require((self.source / ".git").exists(), "fixture_source_must_be_git_checkout")
        source_bytes = self.source_config.read_bytes()
        require(len(source_bytes) <= base.MAX_JSON_BYTES, "source_config_limit_exceeded")
        self.record["sourceConfigSnapshotSha256"] = hashlib.sha256(source_bytes).hexdigest()
        self._snapshot = base.routing_snapshot(tomllib.loads(source_bytes.decode("utf-8-sig")), self.model_id)
        self.home.mkdir(parents=True, exist_ok=True)
        self.env = base.isolated_environment(self.home, self._snapshot)
        for key in ("USERPROFILE", "HOME"):
            self.env[key] = str(self.home / "user")
        (self.home / "user").mkdir()
        self.env["VIBELUTION_WEB_CONTROL_TOKEN"] = secrets.token_urlsafe(32)
        self._host_config = self.home / "assistant-config" / "config.toml"
        base.write_config(self._host_config, self._snapshot, self.profile / "data")
        self._host_runtime = self.home / "assistant-runtime"
        self._host_runtime.mkdir()
        self._entered = True
        self.record["runtimeOwned"] = True
        return self

    def start_backend(self, project_id: str = "acceptance-primary", root: Path | None = None) -> Backend:
        require(self._entered, "fixture_not_entered")
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", project_id), "invalid_fixture_project_id")
        root = (root or self.source).resolve()
        if project_id in self.backends:
            require(self.backends[project_id].root == root, "project_id_root_changed")
            return self.backends[project_id]
        require(self.host_process is None or self.host_process.poll() is not None, "backend_registry_already_running")
        require(all(item.root != root for item in self.backends.values()), "duplicate_backend_project_root")
        instance_id = "target-" + secrets.token_hex(6)
        base.write_config(self.runtime_home / instance_id / "config" / "config.toml", self._snapshot,
                          self.runtime_home / instance_id / "data")
        with base.environment(self.env):
            state = acceptance_runtime.start_instance(instance_id=instance_id, project_root=root,
                runtime_home=self.runtime_home, backend_only=True, readiness_timeout=self.readiness_timeout)
            self._owned_backend_ids[project_id] = instance_id
            self.cleanup["backendsStopped"] = False
            from vibelution_storage import resolve_project_runtime_home
            runtime_root = resolve_project_runtime_home(root)
        # Register ownership before checking or writing subsequent descriptors.
        backend = Backend(project_id, root, instance_id, state["backendUrl"], runtime_root)
        self.backends[project_id] = backend
        if len(self.backends) == 1:
            self.primary_project_id = project_id
        require(base.inside(runtime_root, self.home), "target_runtime_not_isolated")
        base.private_json(runtime_root / "launcher" / "state.json", {
            "url": backend.url, "runtimeProjectRoot": str(root), "runtimeSourceCommit": state["sourceCommit"]})
        require(acceptance_runtime.status_instance(instance_id=instance_id, runtime_home=self.runtime_home)["status"] == "running",
                "backend_not_running")
        return backend

    def create_agent(self, display_name: str, project_id: str | None = None) -> str:
        agent = self.backend(project_id or self.primary_project_id, "/api/agents", timeout=self.readiness_timeout,
            payload={"displayName": display_name, "primaryMode": "chat", "roleKey": "assistant_worker",
                "promptTemplateId": "prompt-chat-default", "llmBindings": {"dialogue": {"modelId": self.model_id}},
                "toolPolicy": {"allowedTools": [], "preferredTools": [], "readScopes": [], "writeScopes": [],
                               "networkAccess": "none", "mutationAccess": "restricted"},
                "metadata": {"acceptanceGeneration": self._host_instance_id}})
        require(isinstance(agent.get("agentId"), str) and agent["agentId"], "target_agent_creation_failed")
        require(agent.get("status") == "active" and not agent.get("protected"), "target_must_be_active_ordinary_agent")
        policy = agent.get("toolPolicy")
        require(isinstance(policy, dict) and all(policy.get(key) == [] for key in (
            "allowedTools", "preferredTools", "readScopes", "writeScopes")), "target_permanent_tool_policy_not_empty")
        self.record.setdefault("ordinaryAgentIds", []).append(agent["agentId"])
        return agent["agentId"]

    def start_host(self) -> None:
        require(self._entered and self.backends, "fixture_backend_required")
        require(self.host_process is None or self.host_process.poll() is not None, "assistant_host_already_running")
        ready_path = self._host_runtime / "ready.json"
        # The old process was observed exited above; stale readiness cannot be
        # removed while another generation still owns the profile.
        ready_path.unlink(missing_ok=True)
        projects = self.home / "projects.json"
        base.private_json(projects, {"schemaVersion": 1, "revision": 1,
                                   "projects": {key: str(item.root) for key, item in self.backends.items()}})
        host_env = {**self.env, "VIBELUTION_CONFIG_HOME": str(self._host_config.parent),
                    "VIBELUTION_CONFIG_PATH": str(self._host_config), "VIBELUTION_ASSISTANT_TOKEN": self._host_token}
        with (self.home / "assistant.stdout.log").open("ab", buffering=0) as stdout, \
                (self.home / "assistant.stderr.log").open("ab", buffering=0) as stderr:
            self.host_process = subprocess.Popen([sys.executable, str(self.source / "scripts" / "assistant_host.py"),
                "--profile-root", str(self.profile), "--runtime-dir", str(self._host_runtime),
                "--instance-id", self._host_instance_id, "--projects-file", str(projects)],
                cwd=str(self.source), env=host_env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                **no_window_subprocess_kwargs())
        self._host_create_time = acceptance_runtime._process_create_time(self.host_process.pid)
        self.cleanup["assistantStopped"] = False
        ready = base.wait_host(self.host_process, ready_path, self._host_instance_id, self.readiness_timeout)
        require("token" not in ready and "capability" not in ready, "credential_in_public_ready")
        self.host_url = f"http://127.0.0.1:{ready['port']}"
        assistant = self.native("/api/assistant").get("assistant") or {}
        session_id = assistant.get("directSessionId")
        require(isinstance(session_id, str) and session_id, "assistant_session_missing")
        require(not self.session_id or self.session_id == session_id, "assistant_session_changed_on_restart")
        self.session_id = session_id
        self.record.setdefault("hostGenerations", []).append({"pid": ready["pid"], "instanceId": ready["instanceId"]})

    def native(self, path: str, payload: dict | None = None, timeout: float = 15):
        require(path == "/api/assistant" or path.startswith("/api/assistant/"), "invalid_native_api_path")
        require(bool(self.host_url), "assistant_host_not_started")
        return base.request(self.host_url, path, token=self._host_token, payload=payload, timeout=timeout)

    def backend(self, project_id: str, path: str, payload: dict | None = None, timeout: float = 120):
        require(project_id in self.backends, "unknown_fixture_project")
        require(path.startswith("/api/"), "invalid_backend_api_path")
        return base.request(self.backends[project_id].url, path, token=self.env["VIBELUTION_WEB_CONTROL_TOKEN"],
                            backend=True, payload=payload, timeout=timeout)

    def send(self, message: str, request_id: str | None = None):
        return self.native("/api/assistant/messages", {"message": message,
                           "requestId": request_id or "acceptance-" + secrets.token_hex(8)}, timeout=self.readiness_timeout)

    def dispatches(self) -> list[dict]:
        rows = self.native("/api/assistant/dispatches").get("dispatches") or []
        require(isinstance(rows, list) and len(rows) <= 32, "dispatch_evidence_limit_exceeded")
        return rows

    def task(self, native_id: str, project_id: str | None = None) -> dict:
        project_id = project_id or self.primary_project_id
        require(project_id in self.backends, "unknown_fixture_project")
        task = base.native_task(self.backends[project_id].runtime_root, native_id)
        workspace = task.get("localWorkspacePath")
        if isinstance(workspace, str) and workspace and Path(workspace).resolve() != self.backends[project_id].root:
            rows = self.record.setdefault("taskWorkspacesRetained", [])
            if workspace not in rows:
                rows.append(workspace)
        return task

    def assistant_events(self) -> list[dict]:
        return base.journal_events(self.profile, self.session_id) if self.session_id else []

    def target_events(self, task: dict) -> list[dict]:
        return base.journal_events(self.home, task["sessionId"], task["turnId"])

    def assert_no_approvals(self) -> None:
        pending = self.native("/api/assistant/approvals")
        rows = pending if isinstance(pending, list) else pending.get("requests", pending.get("approvals", []))
        require(isinstance(rows, list) and not rows, "unexpected_assistant_approval")
        for dispatch in self.dispatches():
            receipt = dispatch.get("receipt") or {}
            require(not receipt.get("pendingApprovals") and receipt.get("status") != "awaiting_approval",
                    "unexpected_target_approval")
        self.record["approvalCount"] = 0

    def stop_host(self) -> None:
        process = self.host_process
        if process is None or process.poll() is not None:
            self.cleanup["assistantStopped"] = True
            return
        require(acceptance_runtime._process_matches(process.pid, self._host_create_time), "assistant_process_ownership_changed")
        # The native HTTP endpoint stops this host; SDK lifecycle shutdown would
        # cancel remote tasks and therefore is deliberately never used here.
        self.native("/api/assistant/shutdown", {}, timeout=12)
        try:
            process.wait(timeout=25)
        except subprocess.TimeoutExpired:
            raise AcceptanceFailure("assistant_native_shutdown_timeout") from None
        self.cleanup["assistantStopped"] = True
        self.host_url = ""

    def restart_host(self) -> None:
        self.stop_host()
        require(self.host_process is not None and self.host_process.poll() is not None, "old_assistant_host_still_running")
        self.start_host()

    def force_stop_host_after_failure(self) -> None:
        """Stop only the recorded generation; never fall back to a bare PID."""
        process, created = self.host_process, self._host_create_time
        if process is None or process.poll() is not None:
            self.cleanup["assistantStopped"] = True
            return
        require(type(created) in {int, float} and math.isfinite(created) and created > 0,
                "assistant_process_ownership_unconfirmed")
        require(acceptance_runtime._process_matches(process.pid, created), "assistant_process_ownership_changed")
        stopped = acceptance_runtime._terminate_recorded(process.pid, created)
        self.cleanup.update(assistantStopped=stopped and process.poll() is not None, assistantForcedStop=True)
        require(self.cleanup["assistantStopped"], "assistant_forced_stop_unconfirmed")
        self.host_url = ""

    def configuration_evidence(self) -> dict:
        evidence = {"sourceConfigSnapshotSha256": self.record.get("sourceConfigSnapshotSha256")}
        try:
            current = hashlib.sha256(self.source_config.read_bytes()).hexdigest()
            evidence.update(sourceConfigCurrentSha256=current,
                sourceConfigObservedChange=current != evidence["sourceConfigSnapshotSha256"])
        except OSError:
            evidence["sourceConfigCurrentHashUnavailable"] = True
        return evidence

    def __exit__(self, exc_type, exc, traceback):
        cleanup = self.cleanup
        try:
            self.stop_host()
        except Exception:
            cleanup["assistantStopped"] = False
            try:
                self.force_stop_host_after_failure()
            except Exception:
                cleanup["assistantStopped"] = False
        for project_id, instance_id in self._owned_backend_ids.items():
            try:
                stopped = acceptance_runtime.stop_instance(instance_id=instance_id, runtime_home=self.runtime_home)
                state = acceptance_runtime.status_instance(instance_id=instance_id, runtime_home=self.runtime_home)
                cleanup["backendStopped:" + project_id] = stopped.get("status") == "stopped" and not any(
                    (state.get("processAlive") or {}).values())
            except Exception:
                cleanup["backendStopped:" + project_id] = False
        cleanup["backendsStopped"] = all(cleanup.get("backendStopped:" + project_id, False) for project_id in self._owned_backend_ids)
        self.record.update(self.configuration_evidence())
        self._entered = False
        return False
