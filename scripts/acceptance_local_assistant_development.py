#!/usr/bin/env python3
"""Exercise real local-assistant dispatch, worktree editing, tests and receipt.

This opt-in acceptance spends real model requests. It never approves a pending
tool request. All product state and evidence live below a new system-temp home;
the target's native owner creates its own Git worktree from main. Run with the
project's installed Python environment, --source-config and a qualified
--model-id. The source config is read only. No provider or tool is mocked.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
import tomllib
from typing import Any, Iterator
import urllib.error
import urllib.request


SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))
sys.dont_write_bytecode = True

from scripts import acceptance_runtime
from scripts.windowless_subprocess import no_window_subprocess_kwargs


TEST_COMMAND = "python -m unittest test_isolated_demo -v"
SUCCESS_MARKER = "LOCAL_ASSISTANT_DEVELOPMENT_TESTS_PASSED"
FIXTURE_FILES = {"isolated_demo.py", "test_isolated_demo.py"}
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_JOURNAL_BYTES = 32 * 1024 * 1024
TERMINAL = {"succeeded", "failed", "cancelled", "timed_out", "stop_unconfirmed"}
SECRET_KEYS = {"api_key", "apikey", "token", "access_token", "refresh_token", "secret",
               "password", "authorization", "x-api-key", "api-key", "x-auth-token", "cookie"}


class AcceptanceFailure(RuntimeError):
    """Only controlled diagnostic codes may be written to public evidence."""


def require(condition: Any, code: str) -> None:
    if not condition:
        raise AcceptanceFailure(code)


def inside(path: Path, root: Path) -> bool:
    return path.resolve() != root.resolve() and path.resolve().is_relative_to(root.resolve())


@contextmanager
def environment(values: dict[str, str]) -> Iterator[None]:
    previous = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(values)
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def read_json(path: Path, limit: int = MAX_JSON_BYTES) -> dict[str, Any]:
    require(path.stat().st_size <= limit, "json_evidence_limit_exceeded")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(payload, dict), "invalid_json_object")
    return payload


def private_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def request(base: str, path: str, *, token: str, payload: dict | None = None,
            backend: bool = False, timeout: float = 15) -> Any:
    """Do not include HTTP bodies, URLs, tokens or exception strings in errors."""
    headers = {"X-Vibelution-Control-Token": token} if backend else {"Authorization": "Bearer " + token}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(base + path, data=body, headers=headers)
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as response:
            raw = response.read(MAX_JSON_BYTES + 1)
        require(len(raw) <= MAX_JSON_BYTES, "http_response_limit_exceeded")
        return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise AcceptanceFailure(f"http_{exc.code}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise AcceptanceFailure("private_http_unavailable") from None


def routing_snapshot(source: dict[str, Any], model_id: str) -> dict[str, Any]:
    """Keep one real canonical route; point every role at that selected model."""
    provider_id, separator, model_key = model_id.partition("/")
    require(separator and provider_id and model_key, "qualified_model_id_required")
    llm = source.get("llm") or {}
    require(llm.get("schema_version") == 2, "canonical_llm_schema_v2_required")
    provider = deepcopy((llm.get("providers") or {}).get(provider_id))
    require(isinstance(provider, dict), "selected_provider_not_found")
    model = (provider.get("models") or {}).get(model_key)
    require(isinstance(model, dict), "selected_model_not_found")
    provider["models"] = {model_key: deepcopy(model)}

    def no_inline_secrets(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                require(not (str(key).lower() in SECRET_KEYS and child), "inline_credentials_forbidden")
                no_inline_secrets(child)
        elif isinstance(value, list):
            for child in value:
                no_inline_secrets(child)

    no_inline_secrets(provider)
    original_profiles = llm.get("profiles") or {}
    selected = next((item for item in original_profiles.values()
                     if isinstance(item, dict) and item.get("model_ref") == model_id), {})
    profile = {"model_ref": model_id}
    if selected.get("overrides"):
        profile["overrides"] = deepcopy(selected["overrides"])
    profiles = {key: deepcopy(profile) for key in {*original_profiles, "primary"}}
    result = {"llm": {"schema_version": 2, "providers": {provider_id: provider},
                      "profiles": profiles},
              "runtime": {"profile": (source.get("runtime") or {}).get("profile", "")}}
    no_inline_secrets(result)
    return result


def isolated_environment(home: Path, snapshot: dict[str, Any]) -> dict[str, str]:
    from config.llm_key_env import configured_llm_key_env_names
    from config.public_config import read_persisted_user_env_var

    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("VIBELUTION_", "AGENT_WORKBENCH_", "GIT_", "PYTEST_"))}
    # Read existing persisted user credentials before disabling that fallback in
    # children. Values stay in memory/environment, never in config or evidence.
    provider = next(iter(snapshot["llm"]["providers"].values()))
    for name in configured_llm_key_env_names(snapshot):
        value = str(os.environ.get(name) or read_persisted_user_env_var(name) or "")
        if value:
            env[name] = value
    credential = str(provider.get("credential_ref") or "none")
    if credential.startswith("env:") and provider.get("requires_credential", True):
        require(bool(env.get(credential[4:])), "selected_provider_credential_unavailable")
    for key, suffix in {
        "LOCALAPPDATA": "localappdata", "APPDATA": "appdata",
        "VIBELUTION_PROJECTS_HOME": "projects", "VIBELUTION_DATA_HOME": "data",
        "VIBELUTION_CONFIG_HOME": "config", "TEMP": "tmp", "TMP": "tmp", "TMPDIR": "tmp",
        "XDG_CACHE_HOME": "cache", "XDG_STATE_HOME": "state", "HF_HOME": "cache/huggingface",
        "TIKTOKEN_CACHE_DIR": "cache/tiktoken", "CUSTOM_TIKTOKEN_CACHE_DIR": "cache/tiktoken",
    }.items():
        path = home / suffix
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                "VIBELUTION_ENABLE_USER_ENV_FALLBACK": "0", "VIBELUTION_LLM_STARTUP_WARMUP": "0"})
    return env


def write_config(path: Path, snapshot: dict[str, Any], data: Path) -> None:
    from config.toml_writer import dumps_public_config
    payload = deepcopy(snapshot)
    payload["storage"] = {"data_home": str(data)}
    payload["launcher"] = {"developer_mode": {"enabled": False}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_public_config(payload), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def wait_host(process: subprocess.Popen, ready: Path, instance_id: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        require(process.poll() is None, "assistant_host_exited_before_ready")
        if ready.is_file():
            state = read_json(ready)
            import psutil
            owned_pid = state.get("pid") == process.pid or (
                type(state.get("pid")) is int and psutil.Process(state["pid"]).ppid() == process.pid)
            require(owned_pid and state.get("instanceId") == instance_id
                    and state.get("role") == "launcher_assistant", "assistant_host_identity_mismatch")
            require(type(state.get("port")) is int and 0 < state["port"] < 65536, "invalid_assistant_port")
            return state
        time.sleep(0.25)
    raise AcceptanceFailure("assistant_host_readiness_timeout")


def native_task(runtime_root: Path, task_id: str) -> dict:
    require(re.fullmatch(r"[A-Za-z0-9_-]{1,160}", task_id), "invalid_native_task_id")
    path = runtime_root / "local_assistant_tasks" / "tasks" / (task_id + ".json")
    require(inside(path, runtime_root), "native_task_path_escape")
    return read_json(path)


def journal_events(root: Path, session_id: str, turn_id: str = "") -> list[dict]:
    events: list[dict] = []
    paths = list(root.rglob("turn_journal.jsonl"))
    require(len(paths) <= 24, "unexpected_journal_count")
    total = 0
    for path in paths:
        require(inside(path, root), "journal_path_escape")
        total += path.stat().st_size
        require(total <= MAX_JOURNAL_BYTES, "journal_evidence_limit_exceeded")
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                # A live writer can still be appending the current tail.
                if not line.endswith("\n"):
                    continue
                row = json.loads(line)
                if row.get("sessionId") == session_id and (not turn_id or row.get("turnId") == turn_id):
                    events.append(row)
    return events


def object_value(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            pass
    return {}


def tool_evidence(events: list[dict]) -> dict:
    calls: dict[str, dict] = {}
    results: list[dict] = []
    edits: set[str] = set()
    terminal_tests: set[str] = set()
    terminal_output: dict[str, str] = {}
    test_exit = None
    for event in events:
        if event.get("eventType") not in {"tool_call_started", "tool_result"}:
            continue
        call = (event.get("payload") or {}).get("toolCall") or event.get("payload") or {}
        name = str(call.get("name") or call.get("toolName") or "")
        call_id = str(event.get("toolCallId") or call.get("id") or call.get("toolCallId") or "")
        args = object_value(call.get("arguments") or call.get("args"))
        if event.get("eventType") == "tool_call_started":
            calls[call_id] = {"name": name, "args": args}
            continue
        previous = calls.get(call_id) or {}
        name = name or previous.get("name", "")
        args = args or previous.get("args") or {}
        result = object_value(call.get("result"))
        exit_code = result.get("exitCode", result.get("exit_code", call.get("exitCode", call.get("exit_code"))))
        if (name in {"write_file_tool", "apply_diff_edit_tool", "apply_patch_tool"}
                and event.get("status") not in {"failed", "error", "blocked", "cancelled"}):
            edits.add(name)
        command = str(args.get("cmd") or args.get("command") or "").strip()
        terminal_id = str(result.get("terminalSessionId") or "")
        is_test = name == "exec_command" and command == TEST_COMMAND
        if is_test and terminal_id:
            terminal_tests.add(terminal_id)
        if name == "write_stdin" and str(args.get("session_id") or "") in terminal_tests:
            is_test = True
        output = str(result.get("stdout") or "") + "\n" + str(result.get("stderr") or "")
        if terminal_id:
            # Running chunks can contain the test summary before a later,
            # output-free poll delivers its exit code. Never mix terminals.
            terminal_output[terminal_id] = (terminal_output.get(terminal_id, "") + output)[-65536:]
            output = terminal_output[terminal_id]
        if (is_test and type(exit_code) is int and exit_code == 0
                and re.search(r"Ran 3 tests?\b", output) and re.search(r"(?m)^OK\s*$", output)):
            test_exit = 0
        results.append({"name": name[:100], "exitCode": exit_code if type(exit_code) is int else None,
                        "isAcceptanceTest": is_test})
    require(len(results) <= 100, "tool_evidence_limit_exceeded")
    return {"tools": results, "fileEditTools": sorted(edits), "testExitCode": test_exit}


def final_answer(events: list[dict]) -> str:
    texts = []
    completed = {row.get("turnId") for row in events if row.get("eventType") == "turn_completed"}
    for event in events:
        if event.get("turnId") not in completed:
            continue
        payload = event.get("payload") or {}
        if event.get("eventType") == "assistant_item_committed":
            if (payload.get("kind") != "assistant_message" or payload.get("channel") != "answer"
                    or payload.get("phase") != "final_answer"):
                continue
            content = payload.get("text") or ""
        elif event.get("eventType") == "assistant_message":
            content = payload.get("content") or object_value(payload.get("message")).get("content") or ""
        else:
            continue
        if isinstance(content, str):
            texts.append(content)
    return "\n".join(texts)


def reports_exit_zero(answer: str) -> bool:
    """Allow presentation markup; real success still requires the tool exit code."""
    plain = re.sub(r"[`*_]", "", answer)
    return re.search(r"(?:exitCode|退出码)\s*[=:：]?\s*0(?![\w.])", plain, re.IGNORECASE) is not None


def model_requests(home: Path) -> dict[str, int]:
    counts = {"assistant": 0, "target": 0}
    paths = list(home.rglob("conversation_*.jsonl"))
    require(len(paths) <= 100, "model_log_count_exceeded")
    total = 0
    for path in paths:
        require(inside(path, home), "model_log_path_escape")
        total += path.stat().st_size
        require(total <= 64 * 1024 * 1024, "model_log_limit_exceeded")
        owner = "assistant" if "DesktopShell" in path.parts else "target"
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if json.loads(line).get("type") == "llm_request":
                    counts[owner] += 1
    return counts


def git(root: Path, *args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = subprocess.run(["git", "-C", str(root), *args], env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=30, **no_window_subprocess_kwargs())
    require(result.returncode == 0, "git_evidence_failed")
    require(len(result.stdout) <= MAX_JSON_BYTES, "git_evidence_limit_exceeded")
    return result.stdout


def verify_workspace(workspace: Path, source: Path, main_head: str) -> dict:
    require(workspace.resolve() != source.resolve() and workspace.is_dir(), "task_workspace_not_isolated")
    worktrees = git(source, "worktree", "list", "--porcelain")
    registered = any(Path(line[9:]).resolve() == workspace.resolve()
                     for line in worktrees.splitlines() if line.startswith("worktree "))
    require(registered and (workspace / ".git").is_file(), "task_workspace_not_native_git_worktree")
    branch = git(workspace, "branch", "--show-current").strip()
    require(branch.startswith("codex/assistant-"), "unexpected_task_branch")
    require(git(workspace, "merge-base", "HEAD", main_head).strip() == main_head, "task_workspace_not_from_main")
    changed = set(git(workspace, "diff", "--name-only", "-z", main_head).split("\0")) - {""}
    changed.update(set(git(workspace, "ls-files", "--others", "--exclude-standard", "-z").split("\0")) - {""})
    require(changed == FIXTURE_FILES, "task_changed_files_outside_fixture_or_missing_fixture")
    for name in FIXTURE_FILES:
        path = workspace / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 16000, "fixture_file_invalid")
    return {"taskWorkspace": str(workspace), "changedFiles": sorted(changed)}


def task_message(project_id: str, agent_id: str, dispatch_id: str) -> str:
    return (
        f"这是一次已授权的真实本机开发验收。目标 project_id={project_id}，agent_id={agent_id}，"
        f"dispatch_id={dispatch_id}。如果你是 Launcher 个人助理，请通过真实工具发现 projects/agents，"
        "再调用 personal_assistant_manage_tool 的 dispatch_write，将本条用户消息完整原文逐字作为 task；"
        "不要截取、改写或另建任务。派遣后持续调用 receipt 查询同一 dispatch_id，直到目标业务完成；"
        "等待期间可间隔查询。不要创建 Agent、修改权限或配置。若遇到审批或错误，如实报告。"
        "如果你是被派遣的目标项目 Agent：只在系统为本任务绑定的专属 Git worktree 内工作；"
        "文件工具总是使用该 workspace 的绝对路径，不要把相对路径解释为父源码目录。"
        "开始先用真实 exec_command 检查现场：将专属 worktree 的绝对路径填入双引号，"
        "运行 cd /d \"<专属worktree绝对路径>\" && git status --short && dir /b；不要保留占位符。"
        "只新建 isolated_demo.py 和 test_isolated_demo.py 两个文件，不修改任何其他文件，不提交 Git。"
        "isolated_demo.py 实现 add(a, b)，返回两整数之和。test_isolated_demo.py 使用 stdlib unittest，"
        "恰好三个 test 方法，分别断言 add(2, 3)==5、add(-2, -3)==-5、add(0, 0)==0。"
        f"必须调用真实 exec_command，cwd 明确为专属 worktree 的绝对路径，cmd 逐字为 {TEST_COMMAND}。"
        "若返回 running，调用 write_stdin 轮询到 exitCode=0。禁止用别的模型或子 Agent，禁止网络请求、"
        "安装依赖、删除、发布、远端 Git、修改正式配置。只能读取必要文件，不要运行大测试集。"
        f"目标完成后回答 {SUCCESS_MARKER}，说明三个测试通过、测试命令和退出码。"
        "Launcher 个人助理须收到同一任务真实成功回执后，向我回传该标记、实际工作区、测试命令和退出码；"
        "未完成时不要宣称成功。"
    )


def run(args: argparse.Namespace, evidence: dict[str, Any]) -> None:
    home, source = args.runtime_home.resolve(), args.project_root.resolve()
    system_temp = Path(tempfile.gettempdir()).resolve()
    require(inside(home, system_temp) and not home.is_relative_to(source), "runtime_home_must_be_private_system_temp")
    require(not home.exists() or not any(home.iterdir()), "runtime_home_must_be_unused")
    require(source == SOURCE_ROOT and (source / ".git").exists(), "driver_must_use_its_source_worktree")
    source_bytes = args.source_config.resolve().read_bytes()
    require(len(source_bytes) <= MAX_JSON_BYTES, "source_config_limit_exceeded")
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    evidence["sourceConfigSnapshotSha256"] = source_hash
    snapshot = routing_snapshot(tomllib.loads(source_bytes.decode("utf-8-sig")), args.model_id)
    home.mkdir(parents=True, exist_ok=True)
    evidence["runtimeOwned"] = True
    env = isolated_environment(home, snapshot)
    instance_id = "local-dev-" + secrets.token_hex(6)
    config_path = home / instance_id / "config" / "config.toml"
    write_config(config_path, snapshot, home / instance_id / "data")
    host_config = home / "assistant-config" / "config.toml"
    profile = Path(env["LOCALAPPDATA"]) / "Vibelution" / "DesktopShell" / "assistant" / "profile"
    write_config(host_config, snapshot, profile / "data")
    env["VIBELUTION_WEB_CONTROL_TOKEN"] = secrets.token_urlsafe(32)
    host_token = secrets.token_urlsafe(32)
    host_process = None
    host_url = ""
    backend_started = False
    evidence.update({"schemaVersion": 1, "status": "failed", "modelId": args.model_id,
                     "approvalCount": 0, "testExitCode": None, "modelRequests": {"assistant": 0, "target": 0}})
    try:
        with environment(env):
            backend = acceptance_runtime.start_instance(instance_id=instance_id, project_root=source,
                runtime_home=home, backend_only=True, readiness_timeout=args.readiness_timeout)
            backend_started = True
            from vibelution_storage import resolve_project_runtime_home
            runtime_root = resolve_project_runtime_home(source)
        require(inside(runtime_root, home), "target_runtime_not_isolated")
        private_json(runtime_root / "launcher" / "state.json", {
            "url": backend["backendUrl"], "runtimeProjectRoot": str(source),
            "runtimeSourceCommit": backend["sourceCommit"],
        })
        require(acceptance_runtime.status_instance(instance_id=instance_id, runtime_home=home)["status"] == "running",
                "backend_not_running")
        agent = request(backend["backendUrl"], "/api/agents", token=env["VIBELUTION_WEB_CONTROL_TOKEN"], backend=True,
            timeout=args.readiness_timeout,
            payload={"displayName": "Local development acceptance target", "primaryMode": "chat",
                "roleKey": "assistant_worker", "promptTemplateId": "prompt-chat-default",
                "llmBindings": {"dialogue": {"modelId": args.model_id}},
                "toolPolicy": {"allowedTools": [], "preferredTools": [], "readScopes": [], "writeScopes": [],
                               "networkAccess": "none", "mutationAccess": "restricted"},
                "metadata": {"acceptanceGeneration": instance_id}})
        agent_id = agent.get("agentId")
        require(isinstance(agent_id, str) and agent_id, "target_agent_creation_failed")
        require(agent.get("status") == "active" and not agent.get("protected"), "target_must_be_active_ordinary_agent")
        project_id = "acceptance-local-development"
        dispatch_id = "dev-" + secrets.token_hex(8)
        projects_path = home / "projects.json"
        private_json(projects_path, {"schemaVersion": 1, "revision": 1, "projects": {project_id: str(source)}})
        host_env = {**env, "VIBELUTION_CONFIG_HOME": str(host_config.parent),
                    "VIBELUTION_CONFIG_PATH": str(host_config), "VIBELUTION_ASSISTANT_TOKEN": host_token}
        host_runtime = home / "assistant-runtime"
        host_runtime.mkdir()
        with (home / "assistant.stdout.log").open("ab", buffering=0) as stdout, \
                (home / "assistant.stderr.log").open("ab", buffering=0) as stderr:
            host_process = subprocess.Popen([sys.executable, str(source / "scripts" / "assistant_host.py"),
                "--profile-root", str(profile), "--runtime-dir", str(host_runtime), "--instance-id", instance_id,
                "--projects-file", str(projects_path)], cwd=str(source), env=host_env, stdin=subprocess.DEVNULL,
                stdout=stdout, stderr=stderr, **no_window_subprocess_kwargs())
        ready = wait_host(host_process, host_runtime / "ready.json", instance_id, args.readiness_timeout)
        require("token" not in ready and "capability" not in ready, "credential_in_public_ready")
        host_url = f"http://127.0.0.1:{ready['port']}"
        identity = request(host_url, "/api/assistant", token=host_token)
        assistant = identity.get("assistant") or {}
        session_id = assistant.get("directSessionId")
        require(isinstance(session_id, str) and session_id, "assistant_session_missing")
        main_head = git(source, "rev-parse", "main").strip()
        request(host_url, "/api/assistant/messages", token=host_token,
                payload={"message": task_message(project_id, agent_id, dispatch_id), "requestId": dispatch_id})
        deadline = time.monotonic() + args.timeout
        reminders, last_reminder = 0, time.monotonic()
        dispatch = None
        task = None
        while time.monotonic() < deadline:
            require(host_process.poll() is None, "assistant_host_exited")
            pending = request(host_url, "/api/assistant/approvals", token=host_token)
            pending_rows = pending if isinstance(pending, list) else pending.get("requests", pending.get("approvals", []))
            evidence["approvalCount"] += len(pending_rows)
            require(not pending_rows, "unexpected_assistant_approval")
            rows = request(host_url, "/api/assistant/dispatches", token=host_token).get("dispatches") or []
            require(len(rows) <= 1, "unexpected_extra_dispatch")
            dispatch = next((row for row in rows if row.get("dispatchId") == dispatch_id), None)
            if dispatch:
                require(dispatch.get("projectId") == project_id and dispatch.get("agentId") == agent_id,
                        "dispatch_target_mismatch")
                receipt = dispatch.get("receipt") or {}
                approvals = receipt.get("pendingApprovals") or []
                evidence["approvalCount"] += len(approvals)
                require(not approvals and receipt.get("status") != "awaiting_approval", "unexpected_target_approval")
                native_id = dispatch.get("nativeTaskId")
                if native_id:
                    task = native_task(runtime_root, native_id)
                    evidence["nativeTaskStatus"] = task.get("status")
                    evidence["nativeTaskId"] = native_id
                    if task.get("status") in TERMINAL:
                        require(task["status"] == "succeeded", "native_task_failed")
                        assistant_events = journal_events(profile, session_id)
                        answer = final_answer(assistant_events)
                        if SUCCESS_MARKER in answer and TEST_COMMAND in answer and reports_exit_zero(answer):
                            break
            # A genuine follow-up can ask the real assistant to continue receipt
            # checks after it returned early. No driver-generated tool result.
            detail = request(host_url, "/api/assistant/session", token=host_token)
            require(isinstance(detail, dict), "invalid_assistant_session_detail")
            assistant_events = journal_events(profile, session_id)
            started_turns = {row.get("turnId") for row in assistant_events if row.get("eventType") == "turn_started"}
            terminal_turns = {row.get("turnId") for row in assistant_events
                              if row.get("eventType") in {"turn_completed", "turn_failed", "turn_interrupted"}}
            idle = bool(started_turns) and started_turns <= terminal_turns
            if reminders < 3 and time.monotonic() - last_reminder > 45 and idle:
                request(host_url, "/api/assistant/messages", token=host_token, payload={
                    "message": f"继续用 receipt 查询原 dispatch_id={dispatch_id}，不要再次派遣。只有真实完成后回传标记、测试命令与退出码。",
                    "requestId": f"{dispatch_id}-receipt-{reminders}"})
                reminders += 1
                last_reminder = time.monotonic()
            time.sleep(2)
        else:
            raise AcceptanceFailure("model_acceptance_timeout")
        require(task and dispatch, "native_task_missing")
        target_events = journal_events(home, task["sessionId"], task["turnId"])
        proof = tool_evidence(target_events)
        evidence.update(proof)
        require(proof["fileEditTools"], "real_file_edit_not_observed")
        require(proof["testExitCode"] == 0, "real_unittest_exit_zero_not_observed")
        require(any(row.get("eventType") == "turn_completed" for row in target_events), "native_turn_not_completed")
        require(SUCCESS_MARKER in final_answer(target_events), "target_final_answer_missing_success")
        workspace_value = task.get("localWorkspacePath")
        require(isinstance(workspace_value, str) and Path(workspace_value).is_absolute(), "task_workspace_missing")
        evidence.update(verify_workspace(Path(workspace_value), source, main_head))
        evidence["observedMainAdvanced"] = git(source, "rev-parse", "main").strip() != main_head
        require(not git(source, "status", "--porcelain", "--", *sorted(FIXTURE_FILES)).strip(),
                "fixture_written_in_parent_checkout")
        evidence["assistantReturnedTestSuccess"] = True
        evidence["sourceConfigUnchanged"] = hashlib.sha256(args.source_config.resolve().read_bytes()).hexdigest() == source_hash
        # The source is read-only; concurrent operator edits must not invalidate
        # a run against the private configuration snapshot created above.
        evidence["modelRequests"] = model_requests(home)
        require(all(value > 0 for value in evidence["modelRequests"].values()), "real_model_requests_not_observed")
        evidence["status"] = "passed"
    finally:
        cleanup: dict[str, Any] = {}
        if host_process is not None:
            if host_process.poll() is None and host_url:
                try:
                    request(host_url, "/api/assistant/shutdown", token=host_token, payload={}, timeout=12)
                    host_process.wait(timeout=20)
                    cleanup["assistantNativeShutdown"] = True
                except Exception:
                    cleanup["assistantNativeShutdown"] = False
            if host_process.poll() is None:
                # The Popen object belongs to this invocation; never stop an
                # ambient PID or another acceptance generation.
                host_process.terminate()
                try:
                    host_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    host_process.kill()
                    host_process.wait(timeout=5)
            cleanup["assistantStopped"] = host_process.poll() is not None
        if backend_started:
            try:
                stopped = acceptance_runtime.stop_instance(instance_id=instance_id, runtime_home=home)
                status = acceptance_runtime.status_instance(instance_id=instance_id, runtime_home=home)
                cleanup["backendStopped"] = stopped.get("status") == "stopped" and not any(
                    (status.get("processAlive") or {}).values())
            except Exception:
                cleanup["backendStopped"] = False
        evidence["cleanup"] = cleanup
        if home.is_dir():
            try:
                evidence["modelRequests"] = model_requests(home)
            except Exception:
                evidence["modelRequestEvidenceIncomplete"] = True
            evidence["sourceConfigCurrentSha256"] = hashlib.sha256(args.source_config.resolve().read_bytes()).hexdigest()
            evidence["sourceConfigUnchanged"] = evidence["sourceConfigCurrentSha256"] == source_hash
        if evidence.get("status") == "passed" and not all(cleanup.values()):
            evidence.update(status="failed", failureCode="runtime_cleanup_unconfirmed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--runtime-home", required=True, type=Path)
    parser.add_argument("--source-config", required=True, type=Path)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--readiness-timeout", type=float, default=90)
    args = parser.parse_args()
    evidence: dict[str, Any] = {"status": "failed"}
    try:
        run(args, evidence)
    except AcceptanceFailure as exc:
        evidence.update(status="failed", failureCode=str(exc))
    except Exception as exc:
        # Native/provider exception messages may contain request bodies or
        # credentials. Report the class only; retain private runtime logs.
        evidence.update(status="failed", failureCode="unexpected_" + type(exc).__name__)
    home = args.runtime_home.resolve()
    if evidence.pop("runtimeOwned", False) and home.is_dir() and inside(home, Path(tempfile.gettempdir()).resolve()):
        private_json(home / "evidence.json", evidence)
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if evidence.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
