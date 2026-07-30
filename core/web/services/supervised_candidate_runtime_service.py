"""Isolated execution contract for a supervised candidate harness."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

from core.infrastructure.codex_cli_sandbox import (
    start_codex_sandbox_terminal_session,
    write_codex_sandbox_terminal_stdin,
)
from scripts.evolution_harness import HarnessResult


CANDIDATE_RUNTIME_PROTOCOL_VERSION = 1
CANDIDATE_RUNTIME_RESULT_PREFIX = "VIBELUTION_CANDIDATE_RUNTIME_RESULT="
_CANDIDATE_RUNTIME_INPUT_LIMIT = 120_000
_CANDIDATE_RUNTIME_OUTPUT_LIMIT = 50_000
_CANDIDATE_RUNTIME_TIMEOUT_SECONDS = 90
_CANDIDATE_RUNTIME_TEXT_LIMIT = 2_000
_CANDIDATE_RUNTIME_ITEM_LIMIT = 24
_CANDIDATE_RUNTIME_DEPTH_LIMIT = 4
_CANDIDATE_RUNTIME_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATE_RUNTIME_SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)


class CandidateRuntimeExecutionError(RuntimeError):
    """Candidate harness did not produce a trustworthy bounded result."""


def _redacted_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(
        r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+",
        r"\1 [redacted]",
        text,
    )
    text = re.sub(
        r"(?i)\b(api[_-]?key|authorization|password|secret|token)\s*[:=]\s*[^\s,;]+",
        r"\1=[redacted]",
        text,
    )
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "sk-[redacted]", text)
    return text[:_CANDIDATE_RUNTIME_TEXT_LIMIT]


def _sensitive_key(value: Any) -> bool:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return any(fragment in normalized for fragment in _CANDIDATE_RUNTIME_SENSITIVE_KEY_FRAGMENTS)


def _bounded_value(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redacted_text(value)
    if depth >= _CANDIDATE_RUNTIME_DEPTH_LIMIT:
        return _redacted_text(value)
    if isinstance(value, dict):
        return {
            str(key)[:120]: (
                "[redacted]"
                if _sensitive_key(key)
                else _bounded_value(item, depth=depth + 1)
            )
            for key, item in list(value.items())[:_CANDIDATE_RUNTIME_ITEM_LIMIT]
        }
    if isinstance(value, (list, tuple)):
        return [
            _bounded_value(item, depth=depth + 1)
            for item in list(value)[:_CANDIDATE_RUNTIME_ITEM_LIMIT]
        ]
    return _redacted_text(value)


def _run_candidate_sandbox_command(
    command: str,
    *,
    timeout: int,
    cwd: str,
    _cancel_checker: Callable[[], str] | None = None,
    _environment_policy: str = "candidate_runtime",
) -> str:
    if _environment_policy != "candidate_runtime":
        raise CandidateRuntimeExecutionError("Candidate harness requires the isolated environment policy.")
    snapshot = start_codex_sandbox_terminal_session(
        command,
        timeout=timeout,
        cwd=cwd,
        yield_time_ms=1_000,
        max_output_chars=_CANDIDATE_RUNTIME_OUTPUT_LIMIT,
        _cancel_checker=_cancel_checker,
        _environment_policy=_environment_policy,
    )
    stdout_parts: list[str] = []
    while True:
        stdout_parts.append(str(snapshot.get("stdout") or ""))
        if bool(snapshot.get("truncated")) or int(snapshot.get("originalLength") or 0) > _CANDIDATE_RUNTIME_OUTPUT_LIMIT:
            session_id = str(snapshot.get("terminalSessionId") or "").strip()
            if str(snapshot.get("status") or "").strip().lower() == "running" and session_id:
                write_codex_sandbox_terminal_stdin(
                    session_id,
                    "",
                    yield_time_ms=0,
                    max_output_chars=256,
                    _cancel_checker=lambda: "candidate_runtime_output_limit",
                )
            raise CandidateRuntimeExecutionError("Candidate harness subprocess output exceeded the bounded contract.")
        status = str(snapshot.get("status") or "").strip().lower()
        if status != "running":
            if status != "completed" or int(snapshot.get("exitCode") or 0) != 0:
                raise CandidateRuntimeExecutionError(
                    f"Candidate harness subprocess ended with status {status or 'unknown'}."
                )
            return "".join(stdout_parts)
        session_id = str(snapshot.get("terminalSessionId") or "").strip()
        if not session_id:
            raise CandidateRuntimeExecutionError("Candidate harness terminal session identity is missing.")
        snapshot = write_codex_sandbox_terminal_stdin(
            session_id,
            "",
            yield_time_ms=1_000,
            max_output_chars=_CANDIDATE_RUNTIME_OUTPUT_LIMIT,
            _cancel_checker=_cancel_checker,
        )


def _candidate_runtime_events(result: HarnessResult) -> list[dict[str, Any]]:
    summary = result.evolution_summary if isinstance(result.evolution_summary, dict) else {}
    events: list[dict[str, Any]] = []
    for raw in list(summary.get("tool_trace") or [])[-12:]:
        if not isinstance(raw, dict):
            continue
        result_value = _bounded_value(raw.get("result"))
        events.append(
            {
                "type": "tool_call",
                "tool_name": str(raw.get("toolName") or "")[:160],
                "status": str(raw.get("status") or "")[:40],
                "timestamp": str(raw.get("timestamp") or "")[:80],
                "tool_args": _bounded_value(raw.get("arguments") or {}),
                "tool_result": json.dumps(result_value, ensure_ascii=False, sort_keys=True),
            }
        )
    assistant_text = "\n".join(str(item) for item in result.stdout_tail[-20:]).strip()
    if assistant_text:
        events.append(
            {
                "type": "llm_response",
                "content": assistant_text[:8_000],
            }
        )
    return events


def _runtime_input_path(candidate_path: Path) -> Path:
    runtime_dir = (candidate_path / ".runtime" / "supervised-candidate-runtime").resolve()
    if not runtime_dir.is_relative_to(candidate_path):
        raise CandidateRuntimeExecutionError("Candidate runtime input path escaped the candidate worktree.")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir / f"{uuid.uuid4().hex}.json"


def _cleanup_runtime_input(input_path: Path) -> None:
    try:
        input_path.unlink(missing_ok=True)
    except OSError:
        return
    runtime_dir = input_path.parent
    try:
        if runtime_dir.is_dir() and not any(runtime_dir.iterdir()):
            runtime_dir.rmdir()
        parent = runtime_dir.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        return


def _extract_candidate_result(output: str) -> dict[str, Any]:
    candidates = [
        line[len(CANDIDATE_RUNTIME_RESULT_PREFIX) :].strip()
        for line in str(output or "").splitlines()
        if line.startswith(CANDIDATE_RUNTIME_RESULT_PREFIX)
    ]
    if len(candidates) != 1:
        raise CandidateRuntimeExecutionError(
            "Candidate harness subprocess did not emit exactly one structured runtime result."
        )
    encoded = candidates[0]
    if not encoded or len(encoded) > _CANDIDATE_RUNTIME_OUTPUT_LIMIT:
        raise CandidateRuntimeExecutionError("Candidate harness result exceeded the bounded output contract.")
    try:
        payload = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise CandidateRuntimeExecutionError("Candidate harness result was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise CandidateRuntimeExecutionError("Candidate harness result must be a JSON object.")
    return payload


def _validated_variant(candidate_variant: dict[str, Any]) -> tuple[str, str]:
    variant_id = str(candidate_variant.get("variantId") or "").strip()
    patch_sha = str(candidate_variant.get("patchSha256") or "").strip().lower()
    if (
        str(candidate_variant.get("bindingStatus") or "") != "verified"
        or not variant_id
        or not _CANDIDATE_RUNTIME_HEX64.fullmatch(patch_sha)
    ):
        raise CandidateRuntimeExecutionError("Candidate variant is not bound and verified.")
    return variant_id, patch_sha


def run_candidate_runtime_evidence(
    *,
    candidate_path: Path,
    candidate_variant: dict[str, Any],
    harness_result: HarnessResult,
    cancel_checker: Callable[[], str] | None = None,
    sandbox_runner: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Execute candidate-owned harness code out of process and verify its envelope."""

    candidate_root = Path(candidate_path).resolve()
    if not candidate_root.is_dir():
        raise CandidateRuntimeExecutionError("Candidate worktree is unavailable.")
    module_path = (candidate_root / "scripts" / "evolution_harness.py").resolve()
    if not module_path.is_file() or not module_path.is_relative_to(candidate_root):
        raise CandidateRuntimeExecutionError("Candidate harness module is unavailable.")
    variant_id, patch_sha = _validated_variant(candidate_variant)
    module_sha = hashlib.sha256(module_path.read_bytes()).hexdigest()
    payload = {
        "protocolVersion": CANDIDATE_RUNTIME_PROTOCOL_VERSION,
        "candidateVariant": _bounded_value(candidate_variant),
        "events": _candidate_runtime_events(harness_result),
        "assistantText": "\n".join(str(item) for item in harness_result.stdout_tail[-20:])[:8_000],
        "restartExpected": bool(harness_result.restart_expected),
    }
    input_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(input_text.encode("utf-8")) > _CANDIDATE_RUNTIME_INPUT_LIMIT:
        raise CandidateRuntimeExecutionError("Candidate harness input exceeded the bounded contract.")

    input_path = _runtime_input_path(candidate_root)
    try:
        input_path.write_text(input_text, encoding="utf-8")
        relative_input = input_path.relative_to(candidate_root).as_posix()
        command = subprocess.list2cmdline(
            [
                sys.executable,
                "-m",
                "scripts.evolution_harness",
                "--candidate-runtime-input",
                relative_input,
            ]
        )
        try:
            output = (sandbox_runner or _run_candidate_sandbox_command)(
                command,
                timeout=_CANDIDATE_RUNTIME_TIMEOUT_SECONDS,
                cwd=str(candidate_root),
                _cancel_checker=cancel_checker,
                _environment_policy="candidate_runtime",
            )
        except CandidateRuntimeExecutionError:
            raise
        except Exception as exc:
            raise CandidateRuntimeExecutionError(
                f"Candidate harness subprocess could not be executed ({type(exc).__name__})."
            ) from exc
    finally:
        _cleanup_runtime_input(input_path)

    child = _extract_candidate_result(output)
    if int(child.get("protocolVersion") or 0) != CANDIDATE_RUNTIME_PROTOCOL_VERSION:
        raise CandidateRuntimeExecutionError("Candidate harness protocol version mismatch.")
    if str(child.get("status") or "").strip().lower() != "success":
        raise CandidateRuntimeExecutionError("Candidate harness subprocess reported failure.")
    if str(child.get("executionBackend") or "") != "isolated_candidate_subprocess":
        raise CandidateRuntimeExecutionError("Candidate harness execution backend was not isolated.")
    if str(child.get("candidateVariantId") or "") != variant_id:
        raise CandidateRuntimeExecutionError("Candidate harness variant identity mismatch.")
    if str(child.get("candidatePatchSha256") or "").lower() != patch_sha:
        raise CandidateRuntimeExecutionError("Candidate harness patch identity mismatch.")
    if str(child.get("moduleSha256") or "").lower() != module_sha:
        raise CandidateRuntimeExecutionError("Candidate harness module hash mismatch.")
    try:
        process_id = int(child.get("processId") or 0)
    except (TypeError, ValueError) as exc:
        raise CandidateRuntimeExecutionError("Candidate harness process identity is missing.") from exc
    if process_id <= 0 or process_id == os.getpid():
        raise CandidateRuntimeExecutionError("Candidate harness did not execute in a distinct process.")

    evidence = {
        "status": "verified",
        "runtimeEffect": "candidate_harness_executed",
        "executionBackend": "isolated_candidate_subprocess",
        "protocolVersion": CANDIDATE_RUNTIME_PROTOCOL_VERSION,
        "candidateVariantId": variant_id,
        "candidatePatchSha256": patch_sha,
        "moduleSha256": module_sha,
        "processId": process_id,
        "worktreePath": str(candidate_root),
        "evolutionSummary": _bounded_value(child.get("evolutionSummary") or {}),
        "workspaceEvidence": _bounded_value(child.get("workspaceEvidence") or {}),
        "extensionEvidence": _bounded_value(child.get("extensionEvidence") or {}),
    }
    if len(json.dumps(evidence, ensure_ascii=False).encode("utf-8")) > _CANDIDATE_RUNTIME_OUTPUT_LIMIT:
        raise CandidateRuntimeExecutionError("Candidate harness verified evidence exceeded the bounded contract.")
    return evidence


__all__ = [
    "CANDIDATE_RUNTIME_RESULT_PREFIX",
    "CandidateRuntimeExecutionError",
    "run_candidate_runtime_evidence",
]
