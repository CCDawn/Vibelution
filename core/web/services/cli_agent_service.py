"""Controlled non-interactive adapters for external CLI coding agents."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
USER_CLI_AGENT_CONFIG_PATH = Path.home() / "Documents" / "Vibelution" / "config" / "cli_agents.json"
CLI_AGENT_REGISTRY_PATH = USER_CLI_AGENT_CONFIG_PATH
RUN_RECORD_DIR = PROJECT_ROOT / ".runtime" / "cli_agents" / "runs"
DEFAULT_TIMEOUT_SECONDS = 600
MAX_TIMEOUT_SECONDS = 1800
DEFAULT_OUTPUT_LIMIT = 12000
MAX_OUTPUT_LIMIT = 50000
SUPPORTED_MODES = ("readonly", "worktree")

DEFAULT_CLI_AGENT_ADAPTERS: dict[str, dict[str, Any]] = {
    "mimo_code": {
        "id": "mimo_code",
        "label": "MiMo Code",
        "description": "Run MiMo Code through the configured CLI Agent protocol.",
        "protocol": "pty_agent",
        "executableCandidates": ["mimo.cmd", "mimo.exe", "mimo"],
        "supportedModes": list(SUPPORTED_MODES),
        "terminal": {
            "enabled": True,
            "launch": {"argv": ["{exe}", "{cwd}"]},
            "resume": {"argv": ["{exe}", "{cwd}", "--session", "{cliSessionId}"]},
            "initialInput": "{task}\r\n",
            "sessionId": {
                "source": "stdout_regex",
                "regex": "(?i)(?:session|conversation|thread)[ _-]?id[:=]\\s*([A-Za-z0-9_.:-]+)",
            },
            "sessionDiscovery": {
                "source": "mimocode_sqlite",
                "databasePath": "{home}/.local/share/mimocode/mimocode.db",
                "pollAttempts": 10,
                "pollIntervalSeconds": 0.75,
                "createdGraceMs": 5000,
                "maxRows": 80,
            },
            "capabilities": {
                "interactive": True,
                "pty": True,
                "resume": True,
                "transcript": True,
            },
        },
    },
    "codex_code": {
        "id": "codex_code",
        "label": "Codex Code",
        "description": "Run OpenAI Codex CLI through the configured CLI Agent protocol.",
        "protocol": "pty_agent",
        "executableCandidates": ["codex.exe", "codex"],
        "supportedModes": list(SUPPORTED_MODES),
        "terminal": {
            "enabled": True,
            "launch": {"argv": ["{exe}", "--cd", "{cwd}"]},
            "resume": {"argv": ["{exe}", "resume", "{cliSessionId}", "--cd", "{cwd}"]},
            "initialInput": "{task}\r\n",
            "sessionId": {
                "source": "stdout_regex",
                "regex": "(?i)(?:session|conversation|thread)[ _-]?id[:=]\\s*([A-Za-z0-9_.:-]+)",
            },
            "capabilities": {
                "interactive": True,
                "pty": True,
                "resume": True,
                "transcript": True,
            },
        },
    },
    "claude_code": {
        "id": "claude_code",
        "label": "Claude Code",
        "description": "Run Anthropic Claude Code through the configured CLI Agent protocol.",
        "protocol": "pty_agent",
        "executableCandidates": ["claude.cmd", "claude.exe", "claude"],
        "supportedModes": list(SUPPORTED_MODES),
        "terminal": {
            "enabled": True,
            "launch": {"argv": ["{exe}", "--permission-mode", "{permissionMode}"]},
            "resume": {"argv": ["{exe}", "--resume", "{cliSessionId}", "--permission-mode", "{permissionMode}"]},
            "initialInput": "{task}\r\n",
            "sessionId": {
                "source": "stdout_regex",
                "regex": "(?i)(?:session|conversation|thread)[ _-]?id[:=]\\s*([A-Za-z0-9_.:-]+)",
            },
            "sessionDiscovery": {
                "source": "claude_code_project_jsonl",
                "projectDir": "{home}/.claude/projects/{encodedCwd}",
                "pollAttempts": 10,
                "pollIntervalSeconds": 0.75,
                "createdGraceMs": 5000,
                "maxRows": 80,
                "idRegex": r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
            },
            "capabilities": {
                "interactive": True,
                "pty": True,
                "resume": True,
                "transcript": True,
            },
        },
    },
}


def list_cli_agent_adapters() -> list[dict[str, Any]]:
    """Return the currently known built-in CLI agent adapters."""

    adapters = _load_adapter_definitions()
    return [_adapter_summary(adapter) for adapter in adapters.values()]


def run_cli_agent(
    agent_type: str = "",
    task: str = "",
    cwd: str = "",
    mode: str = "readonly",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
    model: str = "",
    agent: str = "",
    allow_unsafe_permissions: bool = False,
    source_session_id: str = "",
    source_message_id: str = "",
    source_run_id: str = "",
    action: str = "task",
    terminal_session_id: str = "",
    input_text: str = "",
) -> dict[str, Any]:
    """Run a supported CLI agent with bounded non-interactive arguments."""

    started_at = time.perf_counter()
    normalized_type = _normalize_id(agent_type)
    normalized_action = _normalize_action(action)
    adapters = _load_adapter_definitions()
    adapter = adapters.get(normalized_type)
    if not adapter:
        return _error_result(
            "UNSUPPORTED_CLI_AGENT",
            f"Unsupported CLI agent type: {normalized_type or agent_type}",
            agent_type=normalized_type,
            supportedAgentTypes=sorted(adapters),
        )

    task_text = str(task or "").strip()
    if normalized_action == "send" and not str(input_text or "").strip():
        input_text = task_text
    if normalized_action in {"task", "send"} and not (str(input_text or "").strip() if normalized_action == "send" else task_text):
        return _error_result("MISSING_TASK", "cli_agent_run_tool requires a non-empty task.", agent_type=normalized_type)

    normalized_mode = str(mode or "readonly").strip().lower()
    if normalized_mode not in SUPPORTED_MODES:
        return _error_result(
            "UNSUPPORTED_MODE",
            f"Unsupported CLI agent mode: {normalized_mode}",
            agent_type=normalized_type,
            supportedModes=list(SUPPORTED_MODES),
        )

    cwd_result = _resolve_run_cwd(cwd, mode=normalized_mode)

    if not cwd_result.get("ok"):
        return _error_result(
            str(cwd_result.get("code") or "INVALID_CWD"),
            str(cwd_result.get("message") or "Invalid CLI agent working directory."),
            agent_type=normalized_type,
            cwd=str(cwd_result.get("cwd") or cwd or ""),
        )
    run_cwd = Path(str(cwd_result["cwd"]))
    timeout_seconds = _clamp_int(timeout, DEFAULT_TIMEOUT_SECONDS, 1, MAX_TIMEOUT_SECONDS)
    max_output_chars = _clamp_int(output_limit, DEFAULT_OUTPUT_LIMIT, 1000, MAX_OUTPUT_LIMIT)
    task_hash = _task_hash(task_text)

    terminal = adapter.get("terminal") if isinstance(adapter.get("terminal"), dict) else {}
    if bool(terminal.get("enabled")):
        try:
            from . import cli_agent_terminal_service

            if normalized_action != "task":
                controller_result = _run_terminal_controller_action(
                    action=normalized_action,
                    terminal_session_id=terminal_session_id,
                    agent_type=normalized_type,
                    task=task_text,
                    input_text=input_text,
                    cwd=str(run_cwd),
                    mode=normalized_mode,
                    model=model,
                    agent=agent,
                    allow_unsafe_permissions=allow_unsafe_permissions,
                    source_session_id=source_session_id,
                    source_message_id=source_message_id,
                    source_run_id=source_run_id,
                    started_at=started_at,
                )
                controller_result["runId"] = controller_result.get("terminalSessionId") or _new_run_id()
                controller_result["logPath"] = controller_result.get("logPath") or _write_run_record(controller_result)
                _record_event(
                    "cli_agent.run.controller_action",
                    outcome="succeeded" if controller_result.get("status") != "error" else "failed",
                    fields=_event_fields(controller_result, task_hash=task_hash),
                )
                return controller_result

            from . import cli_agent_task_kernel

            terminal_session = cli_agent_terminal_service.ensure_cli_agent_terminal_session(
                agent_type=normalized_type,
                task=task_text,
                cwd=str(run_cwd),
                mode=normalized_mode,
                model=model,
                agent=agent,
                source_session_id=source_session_id,
                source_message_id=source_message_id,
                source_run_id=source_run_id,
                allow_unsafe_permissions=allow_unsafe_permissions,
                send_initial_task=False,
            )
            task_result = cli_agent_task_kernel.submit_cli_agent_task(
                terminal_session=terminal_session,
                task=task_text,
                timeout_seconds=timeout_seconds,
                output_limit=max_output_chars,
                source="cli_agent_run_tool",
            )
            task_result["durationMs"] = round((time.perf_counter() - started_at) * 1000, 3)
            task_result["runId"] = task_result.get("taskId") or _new_run_id()
            task_result["commandPreview"] = list(terminal_session.get("commandPreview") or [])
            task_result["logPath"] = task_result.get("logPath") or _write_run_record(task_result)
            _record_event(
                "cli_agent.run.task_brokered",
                outcome="succeeded" if task_result.get("status") != "error" else "failed",
                fields=_event_fields(task_result, task_hash=task_hash),
            )
            return task_result
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
            result = _error_result(
                getattr(exc, "code", "") or "CLI_AGENT_TERMINAL_BROKER_FAILED",
                getattr(exc, "message", "") or str(exc),
                agent_type=normalized_type,
                cwd=str(run_cwd),
                mode=normalized_mode,
                durationMs=duration_ms,
            )
            if result.get("code") == "CLI_AGENT_NOT_FOUND":
                result["executableCandidates"] = list(adapter.get("executableCandidates") or [])
            result["logPath"] = _write_run_record(result)
            _record_event("cli_agent.run.task_broker_failed", outcome="failed", fields=_event_fields(result, task_hash=task_hash))
            return result
    if normalized_action != "task":
        return _error_result(
            "CLI_AGENT_TERMINAL_NOT_SUPPORTED",
            f"{adapter['label']} does not support persistent terminal controller actions.",
            agent_type=normalized_type,
            cwd=str(run_cwd),
            mode=normalized_mode,
            action=normalized_action,
        )

    executable = _resolve_executable(adapter)
    if not executable:
        return _error_result(
            "CLI_AGENT_NOT_FOUND",
            f"{adapter['label']} executable was not found on PATH.",
            agent_type=normalized_type,
            executableCandidates=list(adapter.get("executableCandidates") or []),
        )

    args_result = _build_command_args(
        adapter,
        executable=executable,
        cwd=run_cwd,
        task=task_text,
        task_hash=task_hash,
        mode=normalized_mode,
        model=model,
        agent=agent,
        allow_unsafe_permissions=allow_unsafe_permissions,
    )
    args = list(args_result["args"])
    command_preview = list(args_result["preview"])
    run_id = _new_run_id()
    _record_event(
        "cli_agent.run.started",
        outcome="started",
        fields={
            "runId": run_id,
            "agentType": normalized_type,
            "mode": normalized_mode,
            "cwd": str(run_cwd),
            "taskHash": task_hash,
            "timeoutSeconds": timeout_seconds,
            "commandPreview": command_preview,
        },
    )

    try:
        completed = subprocess.run(
            args,
            cwd=str(run_cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            env=_run_environment(),
            **_subprocess_no_window_kwargs(),
        )
        duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
        stdout_preview = _clip(completed.stdout or "", max_output_chars)
        stderr_preview = _clip(completed.stderr or "", max_output_chars)
        status = "ok" if completed.returncode == 0 else "error"
        result = {
            "status": status,
            "code": "COMPLETED" if status == "ok" else "CLI_AGENT_EXITED_NONZERO",
            "runId": run_id,
            "agentType": normalized_type,
            "label": str(adapter["label"]),
            "mode": normalized_mode,
            "cwd": str(run_cwd),
            "commandPreview": command_preview,
            "exitCode": int(completed.returncode),
            "durationMs": duration_ms,
            "timedOut": False,
            "stdoutPreview": stdout_preview,
            "stderrPreview": stderr_preview,
            "logPath": "",
        }
        result["logPath"] = _write_run_record(result)
        _record_event(
            "cli_agent.run.completed",
            outcome="succeeded" if status == "ok" else "failed",
            fields=_event_fields(result, task_hash=task_hash),
        )
        return result
    except subprocess.TimeoutExpired as exc:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
        result = {
            "status": "timeout",
            "code": "CLI_AGENT_TIMEOUT",
            "runId": run_id,
            "agentType": normalized_type,
            "label": str(adapter["label"]),
            "mode": normalized_mode,
            "cwd": str(run_cwd),
            "commandPreview": command_preview,
            "exitCode": None,
            "durationMs": duration_ms,
            "timedOut": True,
            "timeoutSeconds": timeout_seconds,
            "stdoutPreview": _clip(_decode_timeout_output(exc.stdout), max_output_chars),
            "stderrPreview": _clip(_decode_timeout_output(exc.stderr), max_output_chars),
            "logPath": "",
        }
        result["logPath"] = _write_run_record(result)
        _record_event("cli_agent.run.timeout", outcome="failed", fields=_event_fields(result, task_hash=task_hash))
        return result
    except OSError as exc:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
        result = _error_result(
            "CLI_AGENT_LAUNCH_FAILED",
            str(exc),
            agent_type=normalized_type,
            runId=run_id,
            cwd=str(run_cwd),
            mode=normalized_mode,
            commandPreview=command_preview,
            durationMs=duration_ms,
        )
        result["logPath"] = _write_run_record(result)
        _record_event("cli_agent.run.launch_failed", outcome="failed", fields=_event_fields(result, task_hash=task_hash))
        return result


def _run_terminal_controller_action(
    *,
    action: str,
    terminal_session_id: str,
    agent_type: str,
    task: str,
    input_text: str,
    cwd: str,
    mode: str,
    model: str,
    agent: str,
    allow_unsafe_permissions: bool,
    source_session_id: str,
    source_message_id: str,
    source_run_id: str,
    started_at: float,
) -> dict[str, Any]:
    from . import cli_agent_terminal_service

    normalized_terminal_session_id = str(terminal_session_id or "").strip()
    terminal_session: dict[str, Any] = {}
    if normalized_terminal_session_id:
        if action == "stop":
            stopped = cli_agent_terminal_service.stop_cli_agent_terminal_session(normalized_terminal_session_id)
            return _terminal_controller_result(
                "closed",
                "CLI_AGENT_TERMINAL_CLOSED",
                stopped,
                action=action,
                message="CLI Agent terminal session was closed.",
                duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )
        terminal_session = cli_agent_terminal_service.get_cli_agent_terminal_session(
            normalized_terminal_session_id,
            include_transcript_tail=action == "status",
        )
    else:
        intent = "start" if action == "start" else "view"
        terminal_session = cli_agent_terminal_service.ensure_cli_agent_terminal_session(
            agent_type=agent_type,
            task=task,
            cwd=cwd,
            mode=mode,
            model=model,
            agent=agent,
            source_session_id=source_session_id,
            source_message_id=source_message_id,
            source_run_id=source_run_id,
            allow_unsafe_permissions=allow_unsafe_permissions,
            send_initial_task=False,
            intent=intent,
        )
        normalized_terminal_session_id = str(terminal_session.get("terminalSessionId") or "").strip()
        if action == "stop":
            stopped = cli_agent_terminal_service.stop_cli_agent_terminal_session(normalized_terminal_session_id)
            return _terminal_controller_result(
                "closed",
                "CLI_AGENT_TERMINAL_CLOSED",
                stopped,
                action=action,
                message="CLI Agent terminal session was closed.",
                duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )

    if action == "send":
        data = str(input_text or task or "")
        if data and not data.endswith(("\n", "\r")):
            data = f"{data}\r\n"
        ack = cli_agent_terminal_service.write_cli_agent_terminal_input(normalized_terminal_session_id, data)
        merged = {**terminal_session, **ack}
        return _terminal_controller_result(
            "input_sent",
            "CLI_AGENT_TERMINAL_INPUT_SENT",
            merged,
            action=action,
            message="Input was sent to the CLI Agent terminal session.",
            duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
        )

    alive = bool(terminal_session.get("alive"))
    status = "attached" if alive else (str(terminal_session.get("status") or "").strip().lower() or "closed")
    code = "CLI_AGENT_TERMINAL_ATTACHED" if alive else "CLI_AGENT_TERMINAL_HISTORY_ATTACHED"
    return _terminal_controller_result(
        status,
        code,
        terminal_session,
        action=action,
        message="CLI Agent terminal session is available." if alive else "CLI Agent terminal history is available.",
        duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
    )


def _terminal_controller_result(
    status: str,
    code: str,
    terminal_session: dict[str, Any],
    *,
    action: str,
    message: str,
    duration_ms: float,
) -> dict[str, Any]:
    return {
        "status": status,
        "semanticStatus": status,
        "internalStatus": str(terminal_session.get("status") or status or "").strip(),
        "code": code,
        "message": message,
        "action": action,
        "agentType": str(terminal_session.get("agentType") or terminal_session.get("adapterId") or "").strip(),
        "adapterId": str(terminal_session.get("adapterId") or terminal_session.get("agentType") or "").strip(),
        "label": str(terminal_session.get("label") or terminal_session.get("adapterId") or "CLI Agent").strip(),
        "mode": str(terminal_session.get("mode") or "").strip(),
        "cwd": str(terminal_session.get("cwd") or "").strip(),
        "terminalSessionId": str(terminal_session.get("terminalSessionId") or "").strip(),
        "cliRunId": str(terminal_session.get("cliRunId") or "").strip(),
        "lockKey": str(terminal_session.get("lockKey") or "").strip(),
        "cliSessionId": str(terminal_session.get("cliSessionId") or "").strip(),
        "terminalAlive": bool(terminal_session.get("alive")),
        "terminalStatus": str(terminal_session.get("status") or "").strip(),
        "canInput": bool(terminal_session.get("canInput")),
        "canResume": bool(terminal_session.get("canResume")),
        "interactionState": str(terminal_session.get("interactionState") or "").strip(),
        "resumeAction": str(terminal_session.get("resumeAction") or "").strip(),
        "terminalReuse": bool(terminal_session.get("reusedActiveLock")),
        "commandPreview": list(terminal_session.get("commandPreview") or []),
        "durationMs": duration_ms,
    }


def _load_adapter_definitions() -> dict[str, dict[str, Any]]:
    adapters = copy.deepcopy(DEFAULT_CLI_AGENT_ADAPTERS)
    payload = _read_registry_payload()
    records: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        raw = payload.get("adapters") or payload.get("agents") or []
        if isinstance(raw, dict):
            records = [dict({"id": key}, **value) for key, value in raw.items() if isinstance(value, dict)]
        elif isinstance(raw, list):
            records = [item for item in raw if isinstance(item, dict)]
    elif isinstance(payload, list):
        records = [item for item in payload if isinstance(item, dict)]

    for record in records:
        adapter_id = _normalize_id(record.get("id") or record.get("agentType") or "")
        if adapter_id not in adapters:
            continue
        allowed_keys = {
            "label",
            "description",
            "protocol",
            "executablePath",
            "executableCandidates",
            "supportedModes",
            "defaultModel",
            "defaultAgent",
            "terminal",
        }
        _merge_adapter_definition(adapters[adapter_id], {key: record[key] for key in allowed_keys if key in record})
    return adapters


def _merge_adapter_definition(adapter: dict[str, Any], override: dict[str, Any]) -> None:
    terminal_override = override.pop("terminal", None)
    adapter.update(override)
    if not isinstance(terminal_override, dict):
        return
    terminal = adapter.setdefault("terminal", {})
    if not isinstance(terminal, dict):
        adapter["terminal"] = dict(terminal_override)
        return
    for key, value in terminal_override.items():
        if isinstance(value, dict) and isinstance(terminal.get(key), dict):
            terminal[key] = {**terminal[key], **value}
        else:
            terminal[key] = value


def _read_registry_payload() -> Any:
    path = Path(CLI_AGENT_REGISTRY_PATH)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _adapter_summary(adapter: dict[str, Any]) -> dict[str, Any]:
    executable = _resolve_executable(adapter)
    terminal = adapter.get("terminal") if isinstance(adapter.get("terminal"), dict) else {}
    capabilities = terminal.get("capabilities") if isinstance(terminal.get("capabilities"), dict) else {}
    return {
        "id": str(adapter.get("id") or ""),
        "label": str(adapter.get("label") or adapter.get("id") or ""),
        "description": str(adapter.get("description") or ""),
        "protocol": str(adapter.get("protocol") or "cli_agent"),
        "supportedModes": list(adapter.get("supportedModes") or SUPPORTED_MODES),
        "available": bool(executable),
        "executablePath": executable or "",
        "executableCandidates": list(adapter.get("executableCandidates") or []),
        "configPath": str(Path(CLI_AGENT_REGISTRY_PATH)),
        "terminal": {
            "enabled": bool(terminal.get("enabled")),
            "launch": bool(isinstance(terminal.get("launch"), dict)),
            "resume": bool(isinstance(terminal.get("resume"), dict)),
            "capabilities": {
                "interactive": bool(capabilities.get("interactive")),
                "pty": bool(capabilities.get("pty")),
                "resume": bool(capabilities.get("resume")),
                "transcript": bool(capabilities.get("transcript")),
            },
        },
    }


def _resolve_executable(adapter: dict[str, Any]) -> str:
    configured = str(adapter.get("executablePath") or "").strip()
    if configured:
        path = Path(configured)
        if path.exists():
            return str(path)
    for candidate in list(adapter.get("executableCandidates") or []):
        resolved = shutil.which(str(candidate or "").strip())
        if resolved:
            return resolved
    return ""


def _resolve_run_cwd(raw_cwd: str, *, mode: str) -> dict[str, Any]:
    root = Path(PROJECT_ROOT).resolve()
    raw = str(raw_cwd or "").strip()
    candidate = (Path(raw).resolve() if raw else root) if Path(raw or ".").is_absolute() else (root / raw).resolve()
    if not candidate.exists() or not candidate.is_dir():
        return {"ok": False, "code": "CWD_NOT_FOUND", "message": "CLI agent cwd does not exist.", "cwd": str(candidate)}

    allowed_roots = _allowed_cwd_roots(root)
    if not _is_within_any(candidate, allowed_roots):
        return {
            "ok": False,
            "code": "CWD_OUTSIDE_ALLOWED_ROOTS",
            "message": "CLI agent cwd must stay inside the project root or the sibling worktree root.",
            "cwd": str(candidate),
        }
    if mode == "worktree" and not _is_within_any(candidate, [_worktrees_root(root)]):
        return {
            "ok": False,
            "code": "WORKTREE_REQUIRED",
            "message": "Writable CLI agent mode requires a dedicated sibling worktree cwd.",
            "cwd": str(candidate),
        }
    return {"ok": True, "cwd": str(candidate)}


def _allowed_cwd_roots(root: Path) -> list[Path]:
    return [root, _worktrees_root(root)]


def _worktrees_root(root: Path) -> Path:
    return (root.parent / f"{root.name}-worktrees").resolve()


def _is_within_any(path: Path, roots: Sequence[Path]) -> bool:
    for root in roots:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _build_command_args(
    adapter: dict[str, Any],
    *,
    executable: str,
    cwd: Path,
    task: str,
    task_hash: str,
    mode: str,
    model: str,
    agent: str,
    allow_unsafe_permissions: bool,
) -> dict[str, list[str]]:
    adapter_id = str(adapter.get("id") or "").strip()
    model_value = str(model or adapter.get("defaultModel") or "").strip()
    agent_value = str(agent or adapter.get("defaultAgent") or "").strip()
    if adapter_id == "mimo_code":
        args = [executable, "run", "--dir", str(cwd), "--format", "json"]
        preview = [executable, "run", "--dir", str(cwd), "--format", "json"]
        if model_value:
            args.extend(["--model", model_value])
            preview.extend(["--model", model_value])
        if agent_value:
            args.extend(["--agent", agent_value])
            preview.extend(["--agent", agent_value])
        if mode == "worktree" and allow_unsafe_permissions:
            args.append("--dangerously-skip-permissions")
            preview.append("--dangerously-skip-permissions")
        args.append(task)
        preview.append(f"<task:{task_hash}>")
        return {"args": args, "preview": preview}

    if adapter_id == "codex_code":
        sandbox = "read-only" if mode == "readonly" else "workspace-write"
        args = [
            executable,
            "exec",
            "--cd",
            str(cwd),
            "--sandbox",
            sandbox,
            "--ask-for-approval",
            "never",
            "--json",
        ]
        preview = list(args)
        if model_value:
            args.extend(["--model", model_value])
            preview.extend(["--model", model_value])
        args.append(task)
        preview.append(f"<task:{task_hash}>")
        return {"args": args, "preview": preview}

    if adapter_id == "claude_code":
        permission_mode = "plan" if mode == "readonly" else "auto"
        args = [
            executable,
            "--print",
            "--output-format",
            "json",
            "--permission-mode",
            permission_mode,
        ]
        preview = list(args)
        if model_value:
            args.extend(["--model", model_value])
            preview.extend(["--model", model_value])
        if agent_value:
            args.extend(["--agent", agent_value])
            preview.extend(["--agent", agent_value])
        if mode == "worktree" and allow_unsafe_permissions:
            args.append("--dangerously-skip-permissions")
            preview.append("--dangerously-skip-permissions")
        args.append(task)
        preview.append(f"<task:{task_hash}>")
        return {"args": args, "preview": preview}

    raise ValueError(f"Unsupported adapter id: {adapter_id}")


def _subprocess_no_window_kwargs() -> dict[str, Any]:
    if not _is_windows_platform():
        return {}
    kwargs: dict[str, Any] = {}
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if flags:
        kwargs["creationflags"] = flags
    startupinfo = _hidden_startup_info()
    if startupinfo is not None:
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _hidden_startup_info() -> subprocess.STARTUPINFO | None:
    if not _is_windows_platform() or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    return startupinfo


def _is_windows_platform() -> bool:
    return os.name == "nt"


def _run_environment() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("NO_COLOR", "1")
    env.setdefault("CI", "1")
    return env


def _write_run_record(result: dict[str, Any]) -> str:
    try:
        run_id = str(result.get("runId") or _new_run_id())
        run_dir = Path(RUN_RECORD_DIR)
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{_safe_filename(run_id)}.json"
        payload = {
            "schemaVersion": 1,
            "recordedAt": _now_iso(),
            **result,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return _relative_to_project(path)
    except Exception:
        return ""


def _record_event(event_code: str, *, outcome: str, fields: dict[str, Any]) -> None:
    try:
        record_runtime_scene_event(
            "cli_agent",
            "run",
            event_code,
            message=event_code,
            outcome=outcome,
            fields=fields,
            lifecycle=True,
        )
    except Exception:
        return


def _event_fields(result: dict[str, Any], *, task_hash: str) -> dict[str, Any]:
    return {
        "runId": str(result.get("runId") or ""),
        "agentType": str(result.get("agentType") or ""),
        "mode": str(result.get("mode") or ""),
        "cwd": str(result.get("cwd") or ""),
        "status": str(result.get("status") or ""),
        "code": str(result.get("code") or ""),
        "terminalSessionId": str(result.get("terminalSessionId") or ""),
        "cliRunId": str(result.get("cliRunId") or ""),
        "terminalReuse": bool(result.get("terminalReuse")),
        "exitCode": result.get("exitCode"),
        "durationMs": result.get("durationMs"),
        "timedOut": bool(result.get("timedOut")),
        "taskHash": task_hash,
        "logPath": str(result.get("logPath") or ""),
        "commandPreview": list(result.get("commandPreview") or []),
    }


def _error_result(code: str, message: str, *, agent_type: str = "", **extra: Any) -> dict[str, Any]:
    return {
        "status": "error",
        "code": code,
        "message": message,
        "agentType": agent_type,
        **extra,
    }


def _normalize_id(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _normalize_action(value: Any) -> str:
    normalized = str(value or "task").strip().lower().replace("-", "_")
    aliases = {
        "run": "task",
        "submit": "task",
        "message": "send",
        "input": "send",
        "close": "stop",
        "shutdown": "stop",
        "attach": "status",
        "view": "status",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in {"task", "start", "status", "send", "stop"}:
        return normalized
    return "task"


def _task_hash(task: str) -> str:
    return hashlib.sha256(task.encode("utf-8", errors="replace")).hexdigest()[:12]


def _clip(value: str, limit: int) -> str:
    text = str(value or "")
    if limit <= 0 or len(text) <= limit:
        return text
    head = max(500, limit // 2)
    tail = max(500, limit - head)
    return f"{text[:head]}\n\n[output truncated: original {len(text)} chars]\n\n{text[-tail:]}"


def _find_reusable_terminal_session(*, agent_type: str, cwd: str) -> dict[str, Any]:
    state_dir = Path(PROJECT_ROOT) / ".runtime" / "cli_agents" / "sessions"
    if not state_dir.exists():
        return {}
    normalized_agent_type = _normalize_id(agent_type)
    normalized_cwd = _normalize_path_for_match(cwd)
    candidates: list[dict[str, Any]] = []
    for path in state_dir.glob("*.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(state, dict):
            continue
        if bool(state.get("userClosed")):
            continue
        status = str(state.get("status") or "").strip().lower()
        if status in {"closed", "stopping", "stopped", "exited", "stale"}:
            continue
        state_agent_type = _normalize_id(state.get("adapterId") or state.get("agentType"))
        if state_agent_type != normalized_agent_type:
            continue
        if _normalize_path_for_match(str(state.get("cwd") or "")) != normalized_cwd:
            continue
        if not bool(state.get("alive")) and status not in {"running", "starting"}:
            continue
        candidates.append(state)
    if not candidates:
        return {}
    candidates.sort(
        key=lambda item: _timestamp_sort_key(str(item.get("updatedAt") or item.get("createdAt") or "")),
        reverse=True,
    )
    return dict(candidates[0])


def _normalize_path_for_match(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(Path(text).resolve()).replace("\\", "/").lower()
    except Exception:
        return text.replace("\\", "/").lower()


def _timestamp_sort_key(value: str) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _decode_timeout_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"cliagent-{stamp}-{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)[:120] or "run"


def _relative_to_project(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(PROJECT_ROOT).resolve()).as_posix()
    except ValueError:
        return str(path)
