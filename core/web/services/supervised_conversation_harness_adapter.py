"""Conversation-chain harness adapter for supervised evolution."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.chat.turn_journal import EVENT_TOOL_RESULT, load_turn_events
from core.evaluation.supervised_evolution import (
    normalize_supervised_mental_model_mode,
    supervised_mental_model_enabled_for_mode,
)
from scripts.evolution_harness import (
    HarnessResult,
    infer_evolution_summary,
    infer_result_status,
    materialize_scenario_prompt,
)

from .session_service import (
    create_supervised_agent_session,
    get_session_detail,
    get_session_turn_completion_snapshot,
    request_stop_session_turn,
    submit_session_message,
)

CONVERSATION_HARNESS_CANCEL_GRACE_SECONDS = 8.0
_CONVERSATION_HARNESS_TRANSCRIPT_LIMIT = 8
_CONVERSATION_HARNESS_MESSAGE_FIELDS = {
    "id",
    "role",
    "content",
    "timestamp",
    "thought",
    "streamStage",
    "mentalSnapshot",
    "feedbackEvents",
    "streaming",
    "toolCalls",
    "tool_calls",
    "attachments",
    "references",
    "metadata",
}


def run_supervised_conversation_harness(
    *,
    repo_root: Path,
    mode: str,
    prompt: str | None,
    timeout_seconds: int,
    expect_restart: bool,
    post_restart_observe_seconds: int,
    keep_worktree: bool,
    scenario: str = "restart",
    max_steps: int | None = None,
    agent_binding: dict[str, Any] | None = None,
    mental_model_mode: str = "follow",
    mental_model_enabled: bool | None = None,
    progress_callback: Any = None,
    cancel_checker: Any = None,
) -> HarnessResult:
    del mode, post_restart_observe_seconds, keep_worktree, max_steps
    started_at = _now_timestamp()
    binding = dict(agent_binding or {}) if isinstance(agent_binding, dict) else {}
    agent_id = str(binding.get("agentId") or "").strip()
    role = str(binding.get("role") or binding.get("supervisedRole") or "").strip()
    run_id = f"conversation-{uuid4().hex[:12]}"
    normalized_mental_mode = normalize_supervised_mental_model_mode(mental_model_mode)
    if mental_model_enabled is None:
        mental_model_enabled = supervised_mental_model_enabled_for_mode(normalized_mental_mode)
    if not agent_id:
        return _conversation_harness_result(
            run_id=run_id,
            status="failed",
            reason="监督 Agent 绑定缺少 agentId，无法创建隐藏对话会话。",
            started_at=started_at,
            repo_root=repo_root,
            timeout_seconds=timeout_seconds,
            expect_restart=expect_restart,
            scenario=scenario,
            agent_binding=binding,
            session_id="",
            prompt_text=str(prompt or ""),
            assistant_text="",
            evolution_summary={},
            primary_returncode=1,
            mental_model_mode=normalized_mental_mode,
            mental_model_enabled=mental_model_enabled,
        )

    prompt_text = materialize_scenario_prompt(scenario, prompt, repo_root) or ""
    session = create_supervised_agent_session(
        agent_id=agent_id,
        title=f"监督进化 {role or 'role'} {scenario}",
        metadata={
            "runId": run_id,
            "role": role,
            "scenario": scenario,
            "mentalModelMode": normalized_mental_mode,
            "mentalModelEnabled": mental_model_enabled,
        },
    )
    session_id = str(session.get("id") or "").strip()
    turn_id = ""
    created_at = _now_timestamp()
    if callable(progress_callback):
        progress_callback(
            {
                "phase": "conversation_session_created",
                "conversation_path": f"session:{session_id}",
                "conversation_session_id": session_id,
                "conversation_turn_id": "",
                "latest_input": prompt_text,
                "latest_output": "",
                "latest_output_kind": "status",
                "latest_output_label": "conversation_session_created",
                "updated_at": created_at,
                "transcript": [
                    {
                        "timestamp": created_at,
                        "kind": "input",
                        "label": "supervised prompt",
                        "content": prompt_text,
                        "status": "submitted",
                    }
                ],
                "conversation_messages": _conversation_harness_prompt_messages(session_id, prompt_text, created_at),
                "mental_model_mode": normalized_mental_mode,
                "mental_model_enabled": mental_model_enabled,
            }
        )

    try:
        accepted = submit_session_message(
            session_id,
            prompt_text,
            mental_model_enabled=mental_model_enabled,
            message_metadata={
                "supervisedEvolution": True,
                "supervisedRunId": run_id,
                "supervisedRole": role,
                "scenario": scenario,
                "mentalModelMode": normalized_mental_mode,
            },
            message_source="supervised_evolution",
            include_started_turn_id=True,
            lightweight_response=True,
        )
        turn_id = str(accepted.get("turnId") or accepted.get("startedTurnId") or "").strip()
    except Exception as exc:
        return _conversation_harness_result(
            run_id=run_id,
            status="failed",
            reason=f"隐藏监督会话提交失败：{type(exc).__name__}: {exc}",
            started_at=started_at,
            repo_root=repo_root,
            timeout_seconds=timeout_seconds,
            expect_restart=expect_restart,
            scenario=scenario,
            agent_binding=binding,
            session_id=session_id,
            prompt_text=prompt_text,
            assistant_text="",
            evolution_summary={},
            primary_returncode=1,
            mental_model_mode=normalized_mental_mode,
            mental_model_enabled=mental_model_enabled,
        )

    deadline = time.monotonic() + max(1, int(timeout_seconds or 1))
    cancel_requested = False
    cancel_reason_text = ""
    cancel_deadline: float | None = None
    latest_detail: dict[str, Any] = {}
    latest_completion_snapshot: dict[str, Any] = {}
    while True:
        cancel_reason = str(cancel_checker() or "").strip() if callable(cancel_checker) else ""
        if cancel_reason and not cancel_requested:
            cancel_requested = True
            cancel_reason_text = cancel_reason
            cancel_deadline = time.monotonic() + max(0.5, float(CONVERSATION_HARNESS_CANCEL_GRACE_SECONDS))
            try:
                request_stop_session_turn(session_id)
            except Exception:
                pass
            if callable(progress_callback):
                progress_callback(
                    {
                        "phase": "conversation_cancel_requested",
                        "conversation_path": f"session:{session_id}",
                        "conversation_session_id": session_id,
                        "conversation_turn_id": turn_id,
                        "latest_input": prompt_text,
                        "latest_output": cancel_reason,
                        "latest_output_kind": "status",
                        "latest_output_label": "cancel_requested",
                        "updated_at": _now_timestamp(),
                        "transcript": _conversation_harness_transcript(latest_detail),
                        "conversation_messages": _conversation_harness_messages(latest_detail),
                        "mental_model_mode": normalized_mental_mode,
                        "mental_model_enabled": mental_model_enabled,
                    }
                )
        latest_detail = get_session_detail(session_id) or {}
        latest_completion_snapshot = get_session_turn_completion_snapshot(session_id, turn_id)
        completion_terminal = bool(latest_completion_snapshot.get("terminal"))
        last_status = str(
            latest_completion_snapshot.get("terminalStatus")
            or latest_completion_snapshot.get("lastTurnStatus")
            or latest_detail.get("lastTurnStatus")
            or ""
        ).strip().lower()
        if callable(progress_callback):
            latest_output = str(latest_completion_snapshot.get("assistantText") or "").strip() or _conversation_harness_latest_assistant(latest_detail)
            progress_callback(
                {
                    "phase": "conversation_turn_finished" if completion_terminal or last_status not in {"queued", "running"} else "conversation_turn_running",
                    "conversation_path": f"session:{session_id}",
                    "conversation_session_id": session_id,
                    "conversation_turn_id": turn_id,
                    "latest_input": prompt_text,
                    "latest_output": latest_output,
                    "latest_output_kind": "assistant" if latest_output else "status",
                    "latest_output_label": "hidden conversation",
                    "updated_at": str(latest_detail.get("updatedAt") or _now_timestamp()),
                    "transcript": _conversation_harness_transcript(latest_detail),
                    "conversation_messages": _conversation_harness_messages(latest_detail),
                    "turn_id": turn_id,
                    "last_turn_status": last_status,
                    "completion_source": str(latest_completion_snapshot.get("completionSource") or "").strip(),
                    "completion_recovered": bool(latest_completion_snapshot.get("completionRecovered")),
                    "mental_model_mode": normalized_mental_mode,
                    "mental_model_enabled": mental_model_enabled,
                }
            )
        if completion_terminal or (last_status and last_status not in {"queued", "running"}):
            break
        if cancel_requested and cancel_deadline is not None and time.monotonic() >= cancel_deadline:
            assistant_text = str(latest_completion_snapshot.get("assistantText") or "").strip() or _conversation_harness_latest_assistant(latest_detail)
            evolution_summary = _conversation_harness_evolution_summary(
                latest_detail,
                assistant_text=assistant_text,
                restart_expected=expect_restart,
                repo_root=repo_root,
            )
            if callable(progress_callback):
                progress_callback(
                    {
                        "phase": "conversation_cancelled",
                        "conversation_path": f"session:{session_id}",
                        "conversation_session_id": session_id,
                        "conversation_turn_id": turn_id,
                        "latest_input": prompt_text,
                        "latest_output": cancel_reason_text or "监督运行已按请求终止。",
                        "latest_output_kind": "status",
                        "latest_output_label": "cancelled",
                        "updated_at": str(latest_detail.get("updatedAt") or _now_timestamp()),
                        "transcript": _conversation_harness_transcript(latest_detail),
                        "conversation_messages": _conversation_harness_messages(latest_detail),
                        "turn_id": turn_id,
                        "last_turn_status": last_status,
                        "mental_model_mode": normalized_mental_mode,
                        "mental_model_enabled": mental_model_enabled,
                    }
                )
            return _conversation_harness_result(
                run_id=run_id,
                status="cancelled",
                reason=cancel_reason_text or "监督运行已按请求终止。",
                started_at=started_at,
                repo_root=repo_root,
                timeout_seconds=timeout_seconds,
                expect_restart=expect_restart,
                scenario=scenario,
                agent_binding=binding,
                session_id=session_id,
                prompt_text=prompt_text,
                assistant_text=assistant_text,
                evolution_summary=evolution_summary,
                primary_returncode=None,
                mental_model_mode=normalized_mental_mode,
                mental_model_enabled=mental_model_enabled,
                completion_snapshot=latest_completion_snapshot,
            )
        if time.monotonic() >= deadline:
            latest_completion_snapshot = get_session_turn_completion_snapshot(session_id, turn_id)
            if bool(latest_completion_snapshot.get("terminal")):
                latest_detail = get_session_detail(session_id) or latest_detail
                break
            try:
                request_stop_session_turn(session_id)
            except Exception:
                pass
            assistant_text = str(latest_completion_snapshot.get("assistantText") or "").strip() or _conversation_harness_latest_assistant(latest_detail)
            evolution_summary = _conversation_harness_evolution_summary(
                latest_detail,
                assistant_text=assistant_text,
                restart_expected=expect_restart,
                repo_root=repo_root,
            )
            return _conversation_harness_result(
                run_id=run_id,
                status="timeout",
                reason="隐藏监督会话运行超时。",
                started_at=started_at,
                repo_root=repo_root,
                timeout_seconds=timeout_seconds,
                expect_restart=expect_restart,
                scenario=scenario,
                agent_binding=binding,
                session_id=session_id,
                prompt_text=prompt_text,
                assistant_text=assistant_text,
                evolution_summary=evolution_summary,
                primary_returncode=None,
                mental_model_mode=normalized_mental_mode,
                mental_model_enabled=mental_model_enabled,
                completion_snapshot=latest_completion_snapshot,
            )
        time.sleep(0.5)

    assistant_text = str(latest_completion_snapshot.get("assistantText") or "").strip() or _conversation_harness_latest_assistant(latest_detail)
    evolution_summary = _conversation_harness_evolution_summary(
        latest_detail,
        assistant_text=assistant_text,
        restart_expected=expect_restart,
        repo_root=repo_root,
    )
    last_status = str(
        latest_completion_snapshot.get("terminalStatus")
        or latest_completion_snapshot.get("lastTurnStatus")
        or latest_detail.get("lastTurnStatus")
        or ""
    ).strip().lower()
    primary_returncode = 0 if last_status in {"ready", "completed", "done", "success", "paused_limit"} else 1
    inferred_status, inferred_reason = infer_result_status(
        timed_out=False,
        restart_expected=expect_restart,
        restart_reentered=False,
        primary_returncode=primary_returncode,
        last_observation={"phase": last_status or "unknown", "turn_stats": {"session_id": session_id}},
        scenario=scenario,
        evolution_summary=evolution_summary,
        stdout_tail=assistant_text.splitlines(),
    )
    if cancel_requested:
        inferred_status = "cancelled"
        inferred_reason = "监督运行已按请求终止。"
    elif last_status == "failed":
        turn_error = latest_detail.get("lastTurnError") if isinstance(latest_detail.get("lastTurnError"), dict) else {}
        error_message = str(turn_error.get("message") or inferred_reason or "隐藏监督会话执行失败。").strip()
        inferred_status = "failed"
        inferred_reason = error_message
    return _conversation_harness_result(
        run_id=run_id,
        status=inferred_status,
        reason=inferred_reason,
        started_at=started_at,
        repo_root=repo_root,
        timeout_seconds=timeout_seconds,
        expect_restart=expect_restart,
        scenario=scenario,
        agent_binding=binding,
        session_id=session_id,
        prompt_text=prompt_text,
        assistant_text=assistant_text,
        evolution_summary=evolution_summary,
        primary_returncode=primary_returncode,
        mental_model_mode=normalized_mental_mode,
        mental_model_enabled=mental_model_enabled,
        completion_snapshot=latest_completion_snapshot,
    )


def _conversation_harness_result(
    *,
    run_id: str,
    status: str,
    reason: str,
    started_at: str,
    repo_root: Path,
    timeout_seconds: int,
    expect_restart: bool,
    scenario: str,
    agent_binding: dict[str, Any],
    session_id: str,
    prompt_text: str,
    assistant_text: str,
    evolution_summary: dict[str, Any],
    primary_returncode: int | None,
    mental_model_mode: str,
    mental_model_enabled: bool | None,
    completion_snapshot: dict[str, Any] | None = None,
) -> HarnessResult:
    ended_at = _now_timestamp()
    completion = dict(completion_snapshot or {}) if isinstance(completion_snapshot, dict) else {}
    runtime_env = {
        "VIBELUTION_TURN_MODE": "supervised_evolution",
        "VIBELUTION_TURN_RUN_KIND": "supervised_evaluation",
        "VIBELUTION_TURN_SESSION_ID": session_id,
        "VIBELUTION_TURN_AGENT_ID": str(agent_binding.get("agentId") or "").strip(),
        "VIBELUTION_SUPERVISED_ROLE": str(agent_binding.get("role") or "").strip(),
        "VIBELUTION_SUPERVISED_MENTAL_MODEL_MODE": mental_model_mode,
    }
    if mental_model_enabled is not None:
        runtime_env["VIBELUTION_SUPERVISED_MENTAL_MODEL_ENABLED"] = "true" if mental_model_enabled else "false"
    return HarnessResult(
        harness_id=run_id,
        status=status,
        reason=reason,
        started_at=started_at,
        ended_at=ended_at,
        repo_root=str(repo_root),
        worktree_path="",
        base_head="",
        checkpoint_commit="",
        checkpoint_ref=None,
        tracked_dirty=False,
        untracked_files=[],
        command=["session_service.submit_session_message", session_id],
        returncode=primary_returncode,
        timeout_seconds=timeout_seconds,
        restarts_observed=0,
        normalized_restarts_observed=0,
        restart_expected=expect_restart,
        restart_reentered=False,
        process_history=[],
        process_summary={
            "backend": "conversation_chain",
            "session_id": session_id,
            "scenario": scenario,
            "mental_model_mode": mental_model_mode,
            "mental_model_enabled": mental_model_enabled,
        },
        new_conversation_files=[f"session:{session_id}"] if session_id else [],
        new_debug_files=[],
        stdout_tail=assistant_text.splitlines()[-40:],
        stderr_tail=[] if status != "failed" else [reason],
        agent_realtime_tail=[],
        last_observation={
            "phase": status,
            "session_id": session_id,
            "assistant_preview": assistant_text[:400],
        },
        post_restart_observation={},
        evolution_summary={
            **(evolution_summary or {}),
            "conversation_backend": {
                "enabled": True,
                "session_id": session_id,
                "mental_model_mode": mental_model_mode,
                "mental_model_enabled": mental_model_enabled,
                "completion_source": str(completion.get("completionSource") or "").strip(),
                "completion_recovered": bool(completion.get("completionRecovered")),
                "observed_last_turn_status": str(completion.get("lastTurnStatus") or "").strip(),
                "observed_terminal_status": str(completion.get("terminalStatus") or "").strip(),
                "observed_active_turn_id": str(completion.get("activeTurnId") or "").strip(),
                "observed_message_count": int(completion.get("messageCount") or 0),
            },
        },
        agent_binding=agent_binding,
        primary_returncode=primary_returncode,
        effective_returncode=primary_returncode,
        agent_runtime_env=runtime_env,
    )


def _conversation_harness_transcript(detail: dict[str, Any]) -> list[dict[str, Any]]:
    transcript: list[dict[str, Any]] = []
    for message in list((detail or {}).get("messages") or [])[-_CONVERSATION_HARNESS_TRANSCRIPT_LIMIT:]:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        content = str(message.get("content") or "").strip()
        if not role and not content:
            continue
        transcript.append(
            {
                "timestamp": str(message.get("timestamp") or "").strip(),
                "kind": role or "message",
                "label": role or "message",
                "content": content,
                "status": str((message.get("metadata") or {}).get("status") or "").strip(),
            }
        )
    return transcript


def _conversation_harness_prompt_messages(session_id: str, prompt_text: str, timestamp: str) -> list[dict[str, Any]]:
    if not prompt_text:
        return []
    return [
        {
            "id": f"{session_id or 'supervised'}-prompt",
            "role": "user",
            "content": prompt_text,
            "timestamp": timestamp,
            "metadata": {"status": "submitted", "source": "supervised_evolution"},
        }
    ]


def _conversation_harness_messages(detail: dict[str, Any]) -> list[dict[str, Any]]:
    session_id = str((detail or {}).get("id") or (detail or {}).get("sessionId") or "supervised").strip() or "supervised"
    messages: list[dict[str, Any]] = []
    for index, raw in enumerate(list((detail or {}).get("messages") or [])):
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip().lower()
        content = str(raw.get("content") or "").strip()
        if role not in {"user", "assistant"} and not content:
            continue
        message: dict[str, Any] = {}
        for key in _CONVERSATION_HARNESS_MESSAGE_FIELDS:
            if key in raw:
                message[key] = raw[key]
        message["id"] = str(message.get("id") or f"{session_id}-message-{index + 1}").strip()
        message["role"] = role if role in {"user", "assistant"} else "assistant"
        message["content"] = str(message.get("content") or content)
        message["timestamp"] = str(message.get("timestamp") or "").strip()
        messages.append(message)
    return messages


def _conversation_harness_latest_assistant(detail: dict[str, Any]) -> str:
    for message in reversed(list((detail or {}).get("messages") or [])):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip().lower() != "assistant":
            continue
        content = str(message.get("content") or "").strip()
        if content:
            return content
    return ""


def _conversation_harness_tool_event(tool: dict[str, Any]) -> dict[str, Any] | None:
    tool_name = str(tool.get("name") or tool.get("tool_name") or tool.get("tool") or "").strip()
    if not tool_name:
        return None
    raw_args = tool.get("arguments") if isinstance(tool.get("arguments"), dict) else tool.get("tool_args")
    if not isinstance(raw_args, dict):
        raw_args = tool.get("args") if isinstance(tool.get("args"), dict) else {}
    result_value: Any = ""
    for key in ("result", "resultPreview", "tool_result", "summary", "error"):
        value = tool.get(key)
        if value not in (None, ""):
            result_value = value
            break
    if isinstance(result_value, (dict, list)):
        result_text = json.dumps(result_value, ensure_ascii=False)
    else:
        result_text = str(result_value or "").strip()
    return {
        "type": "tool_call",
        "tool_name": tool_name,
        "status": str(tool.get("status") or "").strip(),
        "tool_args": dict(raw_args),
        "tool_result": result_text,
    }


def _conversation_harness_tool_event_key(event: dict[str, Any]) -> str:
    try:
        args_text = json.dumps(event.get("tool_args") or {}, ensure_ascii=False, sort_keys=True)
    except TypeError:
        args_text = str(event.get("tool_args") or {})
    return "|".join(
        [
            str(event.get("tool_name") or ""),
            str(event.get("status") or ""),
            args_text,
            str(event.get("tool_result") or ""),
        ]
    )


def _conversation_harness_turn_journal_tool_events(
    repo_root: Path | None,
    session_id: str,
) -> list[dict[str, Any]]:
    if repo_root is None or not session_id:
        return []
    try:
        journal_events = load_turn_events(Path(repo_root), session_id)
    except Exception:
        return []
    events: list[dict[str, Any]] = []
    for journal_event in journal_events:
        if journal_event.event_type != EVENT_TOOL_RESULT:
            continue
        payload = journal_event.payload if isinstance(journal_event.payload, dict) else {}
        tool = payload.get("toolCall") if isinstance(payload.get("toolCall"), dict) else {}
        tool_event = _conversation_harness_tool_event(tool)
        if tool_event is not None:
            events.append(tool_event)
    return events


def _conversation_harness_events(
    detail: dict[str, Any],
    *,
    assistant_text: str,
    repo_root: Path | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    tool_event_keys: set[str] = set()
    session_id = str((detail or {}).get("id") or (detail or {}).get("sessionId") or "").strip()

    def add_tool_event(tool_event: dict[str, Any] | None) -> None:
        if tool_event is None:
            return
        event_key = _conversation_harness_tool_event_key(tool_event)
        if event_key in tool_event_keys:
            return
        tool_event_keys.add(event_key)
        events.append(tool_event)

    for message in list((detail or {}).get("messages") or []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        content = str(message.get("content") or "").strip()
        if role == "assistant" and content:
            events.append({"type": "llm_response", "content": content})
        for tool in list(message.get("toolCalls") or message.get("tool_calls") or []):
            if not isinstance(tool, dict):
                continue
            add_tool_event(_conversation_harness_tool_event(tool))
    for tool_event in _conversation_harness_turn_journal_tool_events(repo_root, session_id):
        add_tool_event(tool_event)
    if assistant_text and not any(event.get("type") == "llm_response" for event in events):
        events.append({"type": "llm_response", "content": assistant_text})
    return events


def _conversation_harness_evolution_summary(
    detail: dict[str, Any],
    *,
    assistant_text: str,
    restart_expected: bool,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    events = _conversation_harness_events(detail, assistant_text=assistant_text, repo_root=repo_root)
    debug_lines: list[str] = []
    stdout_lines = assistant_text.splitlines()
    return infer_evolution_summary(
        events,
        debug_lines,
        stdout_lines,
        restart_expected=restart_expected,
        restart_reentered=False,
        child_first_event_phase="conversation_chain",
    )


def _now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")
