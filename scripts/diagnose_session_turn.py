from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.chat.turn_journal import (  # noqa: E402
    EVENT_TURN_COMPLETED,
    EVENT_TURN_FAILED,
    EVENT_TURN_INTERRUPTED,
    TurnJournalEvent,
    turn_journal_path,
)


TERMINAL_EVENT_TYPES = {
    EVENT_TURN_COMPLETED,
    EVENT_TURN_FAILED,
    EVENT_TURN_INTERRUPTED,
}


def build_session_turn_diagnosis(
    project_root: Path | str,
    session_id: str,
    turn_id: str = "",
    *,
    max_runtime_matches: int = 20,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    journal_path = turn_journal_path(root, normalized_session_id)
    live_output_path = journal_path.with_name("live_output.json")

    journal = _summarize_journal(journal_path, normalized_turn_id)
    live_output = _summarize_live_output(live_output_path, normalized_turn_id)
    runtime_evidence = _find_runtime_evidence(
        root,
        normalized_session_id,
        normalized_turn_id,
        max_matches=max_runtime_matches,
    )

    return {
        "sessionId": normalized_session_id,
        "turnId": normalized_turn_id,
        "paths": {
            "journal": str(journal_path),
            "liveOutput": str(live_output_path),
            "runtimeScenes": str(root / "logs" / "runtime_scenes"),
        },
        "journal": journal,
        "liveOutput": live_output,
        "runtimeEvidence": runtime_evidence,
        "diagnosis": _build_agent_diagnosis(
            normalized_turn_id,
            journal,
            live_output,
            runtime_evidence,
        ),
    }


def _summarize_journal(path: Path, turn_id: str) -> dict[str, Any]:
    events: list[TurnJournalEvent] = []
    decode_errors: list[dict[str, Any]] = []
    invalid_events: list[dict[str, Any]] = []

    if not path.exists():
        return {
            "exists": False,
            "eventCount": 0,
            "latestSequence": 0,
            "terminalEvent": None,
            "eventTypes": [],
            "decodeErrors": [],
            "invalidEvents": [],
        }

    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError as exc:
                    decode_errors.append(
                        {"line": line_number, "error": exc.msg, "position": exc.pos}
                    )
                    continue
                event = TurnJournalEvent.from_dict(parsed)
                if event is None:
                    invalid_events.append({"line": line_number, "reason": "missing eventType"})
                    continue
                if turn_id and event.turn_id != turn_id:
                    continue
                events.append(event)
    except OSError as exc:
        decode_errors.append({"line": 0, "error": str(exc), "position": 0})

    events.sort(key=lambda item: (item.sequence, item.timestamp, item.event_id))
    terminal_events = [event for event in events if event.event_type in TERMINAL_EVENT_TYPES]
    terminal_event = terminal_events[-1].to_dict() if terminal_events else None

    return {
        "exists": True,
        "eventCount": len(events),
        "latestSequence": max((event.sequence for event in events), default=0),
        "terminalEvent": terminal_event,
        "eventTypes": [event.event_type for event in events],
        "decodeErrors": decode_errors,
        "invalidEvents": invalid_events,
    }


def _summarize_live_output(path: Path, turn_id: str) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "stage": "",
            "turnId": "",
            "turnMatches": bool(not turn_id),
            "contentLength": 0,
            "thoughtLength": 0,
            "toolCallCount": 0,
            "updatedAt": "",
            "decodeError": "",
        }

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "exists": True,
            "stage": "",
            "turnId": "",
            "turnMatches": False,
            "contentLength": 0,
            "thoughtLength": 0,
            "toolCallCount": 0,
            "updatedAt": "",
            "decodeError": str(exc),
        }

    if not isinstance(parsed, dict):
        return {
            "exists": True,
            "stage": "",
            "turnId": "",
            "turnMatches": False,
            "contentLength": 0,
            "thoughtLength": 0,
            "toolCallCount": 0,
            "updatedAt": "",
            "decodeError": "live_output.json is not an object",
        }

    checkpoint_turn_id = str(parsed.get("turnId") or "").strip()
    tool_calls = parsed.get("toolCalls")
    if not isinstance(tool_calls, list):
        tool_calls = []

    return {
        "exists": True,
        "stage": str(parsed.get("stage") or ""),
        "turnId": checkpoint_turn_id,
        "turnMatches": bool(not turn_id or checkpoint_turn_id == turn_id),
        "contentLength": len(str(parsed.get("content") or "")),
        "thoughtLength": len(str(parsed.get("thought") or "")),
        "toolCallCount": len(tool_calls),
        "updatedAt": str(parsed.get("updatedAt") or ""),
        "decodeError": "",
    }


def _find_runtime_evidence(
    project_root: Path,
    session_id: str,
    turn_id: str,
    *,
    max_matches: int,
) -> dict[str, Any]:
    runtime_root = project_root / "logs" / "runtime_scenes"
    tokens = [token for token in (session_id, turn_id) if token]
    matches: list[dict[str, Any]] = []
    decode_errors: list[dict[str, Any]] = []

    if not runtime_root.exists() or not tokens:
        return {
            "exists": runtime_root.exists(),
            "searchedRoot": str(runtime_root),
            "matchCount": 0,
            "matches": [],
            "decodeErrors": [],
        }

    if max_matches <= 0:
        return {
            "exists": True,
            "searchedRoot": str(runtime_root),
            "matchCount": 0,
            "matches": [],
            "decodeErrors": [],
        }

    for jsonl_path in sorted(runtime_root.rglob("*.jsonl"), reverse=True):
        if len(matches) >= max_matches:
            break
        file_matches: list[dict[str, Any]] = []
        try:
            with jsonl_path.open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    raw = line.strip()
                    if not raw or not any(token in raw for token in tokens):
                        continue
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        decode_errors.append(
                            {
                                "path": _display_path(jsonl_path, project_root),
                                "line": line_number,
                                "error": exc.msg,
                                "position": exc.pos,
                            }
                        )
                        continue
                    if not _runtime_event_matches_scope(
                        parsed,
                        session_id=session_id,
                        turn_id=turn_id,
                    ):
                        continue
                    file_matches.append(
                        _runtime_match_summary(
                            parsed,
                            jsonl_path,
                            project_root,
                            line_number,
                        )
                    )
        except OSError as exc:
            decode_errors.append(
                {
                    "path": _display_path(jsonl_path, project_root),
                    "line": 0,
                    "error": str(exc),
                    "position": 0,
                }
            )
        remaining = max_matches - len(matches)
        if remaining > 0 and file_matches:
            matches.extend(file_matches[-remaining:])

    return {
        "exists": True,
        "searchedRoot": str(runtime_root),
        "matchCount": len(matches),
        "matches": matches,
        "decodeErrors": decode_errors,
    }


def _runtime_event_matches_scope(
    parsed: Any,
    *,
    session_id: str,
    turn_id: str,
) -> bool:
    if not isinstance(parsed, dict):
        return False
    fields = parsed.get("fields")
    if not isinstance(fields, dict):
        fields = {}

    turn_values = {
        str(value).strip()
        for value in (
            fields.get("turnId"),
            fields.get("turn_id"),
            fields.get("runId"),
            fields.get("run_id"),
            parsed.get("turnId"),
            parsed.get("turn_id"),
            parsed.get("runId"),
            parsed.get("run_id"),
        )
        if str(value or "").strip()
    }
    if turn_id:
        return turn_id in turn_values

    session_values = {
        str(value).strip()
        for value in (
            fields.get("sessionId"),
            fields.get("session_id"),
            parsed.get("sessionId"),
            parsed.get("session_id"),
        )
        if str(value or "").strip()
    }
    return bool(session_id and session_id in session_values)


def _runtime_match_summary(
    parsed: Any,
    path: Path,
    project_root: Path,
    line_number: int,
) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        return {
            "path": _display_path(path, project_root),
            "line": line_number,
            "timestamp": "",
            "eventCode": "",
            "fields": {"valueType": type(parsed).__name__},
        }

    fields = parsed.get("fields")
    if not isinstance(fields, dict):
        fields = {}

    return {
        "path": _display_path(path, project_root),
        "line": line_number,
        "timestamp": str(parsed.get("timestamp") or parsed.get("ts") or ""),
        "eventCode": str(parsed.get("eventCode") or parsed.get("event_code") or ""),
        "level": str(parsed.get("level") or ""),
        "outcome": str(parsed.get("outcome") or ""),
        "fields": _compact_fields(fields),
    }


def _compact_fields(fields: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in sorted(fields.items()):
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = _compact_value(value)
        elif isinstance(value, list):
            compact[key] = {
                "type": "list",
                "length": len(value),
            }
        elif isinstance(value, dict):
            compact[key] = {
                "type": "object",
                "keys": sorted(str(item_key) for item_key in value.keys())[:20],
            }
        else:
            compact[key] = {"type": type(value).__name__}
    return compact


def _compact_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= 240:
        return value
    return f"{value[:240]}...<truncated {len(value) - 240} chars>"


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


def _build_agent_diagnosis(
    turn_id: str,
    journal: dict[str, Any],
    live_output: dict[str, Any],
    runtime_evidence: dict[str, Any],
) -> dict[str, Any]:
    matches = list(runtime_evidence.get("matches") or [])
    attempts: dict[tuple[int, str], dict[str, Any]] = {}
    root_causes: list[dict[str, Any]] = []
    evidence_refs: list[str] = []
    event_codes: list[str] = []

    for item in matches:
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        event_code = str(item.get("eventCode") or "")
        event_codes.append(event_code)
        path = str(item.get("path") or "")
        line = int(item.get("line") or 0)
        evidence_ref = f"{path}:{line}" if path and line else path
        if evidence_ref and evidence_ref not in evidence_refs:
            evidence_refs.append(evidence_ref)

        if event_code.startswith(("llm_route_", "llm_turn_")):
            route_attempt = _safe_int(
                fields.get("routeAttempt") or fields.get("routeAttempts"),
                default=0,
            )
            invocation_id = str(fields.get("invocationId") or "").strip()
            route_id = str(
                fields.get("routeId") or fields.get("fallbackRouteId") or ""
            ).strip()
            key = (route_attempt, invocation_id or route_id or f"attempt-{route_attempt}")
            attempt = attempts.setdefault(
                key,
                {
                    "routeAttempt": route_attempt,
                    "invocationId": invocation_id,
                    "routeId": route_id,
                    "status": "running",
                    "eventCodes": [],
                    "evidenceRefs": [],
                },
            )
            if event_code not in attempt["eventCodes"]:
                attempt["eventCodes"].append(event_code)
            if evidence_ref and evidence_ref not in attempt["evidenceRefs"]:
                attempt["evidenceRefs"].append(evidence_ref)
            if event_code == "llm_route_attempt_succeeded":
                attempt["status"] = "succeeded"
            elif event_code in {"llm_route_attempt_exhausted", "llm_turn_terminal"}:
                attempt["status"] = "failed"

        for field_name in ("errorCategory", "reasonCode", "errorType"):
            reason = str(fields.get(field_name) or "").strip()
            candidate = {
                "code": reason,
                "sourceField": field_name,
                "eventCode": event_code,
                "evidenceRef": evidence_ref,
            }
            if reason and candidate not in root_causes:
                root_causes.append(candidate)

    journal_status = _journal_terminal_status(journal, live_output)
    route_status = _route_terminal_status(event_codes)
    expected_route_status = {
        "completed": "succeeded",
        "failed": "failed",
        "interrupted": "failed",
    }.get(journal_status, "")
    consistent = bool(expected_route_status and route_status == expected_route_status)

    evidence_gaps: list[str] = []
    if not matches:
        evidence_gaps.append("runtime_evidence_missing")
    if journal_status == "completed" and route_status != "succeeded":
        evidence_gaps.append("missing_route_success")
    if journal_status in {"failed", "interrupted"} and route_status != "failed":
        evidence_gaps.append("missing_route_terminal")
    if any(
        attempt["status"] == "running"
        and attempt["eventCodes"] == ["llm_route_attempt_started"]
        for attempt in attempts.values()
    ):
        evidence_gaps.append("route_attempt_open")

    if journal_status in {"completed", "failed", "interrupted"} and evidence_gaps:
        status = "telemetry_gap"
    elif journal_status in {"completed", "failed", "interrupted"}:
        status = journal_status
    elif route_status in {"succeeded", "failed"}:
        status = "incomplete"
    else:
        status = "running"

    failure_stage = "none"
    if status != "completed":
        if "llm_fallback_selected" in event_codes:
            failure_stage = "fallback"
        elif any(
            code in event_codes
            for code in ("llm.turn_outcome.missing", "llm.turn_outcome.unsuccessful")
        ):
            failure_stage = "outcome_evaluation"
        elif any(
            code in event_codes
            for code in ("llm_route_attempt_exhausted", "llm_turn_terminal")
        ):
            failure_stage = "route"
        elif route_status in {"succeeded", "failed"} and journal_status == "unknown":
            failure_stage = "persistence"

    route_attempts = sorted(
        attempts.values(),
        key=lambda item: (item["routeAttempt"], item["invocationId"]),
    )
    return {
        "traceId": str(turn_id or "").strip(),
        "status": status,
        "failureStage": failure_stage,
        "routeAttempts": route_attempts,
        "rootCauseCandidates": root_causes[:8],
        "evidenceGaps": list(dict.fromkeys(evidence_gaps)),
        "terminalConsistency": {
            "journal": journal_status,
            "runtime": route_status,
            "consistent": consistent,
        },
        "nextMinimalAction": _next_minimal_action(
            status,
            evidence_gaps,
            root_causes,
        ),
        "evidenceRefs": evidence_refs[:20],
    }


def _journal_terminal_status(
    journal: dict[str, Any],
    live_output: dict[str, Any],
) -> str:
    terminal = (
        journal.get("terminalEvent")
        if isinstance(journal.get("terminalEvent"), dict)
        else {}
    )
    event_type = str(terminal.get("eventType") or terminal.get("event_type") or "")
    if event_type == EVENT_TURN_COMPLETED:
        return "completed"
    if event_type == EVENT_TURN_FAILED:
        return "failed"
    if event_type == EVENT_TURN_INTERRUPTED:
        return "interrupted"
    return "running" if bool(live_output.get("exists")) else "unknown"


def _route_terminal_status(event_codes: list[str]) -> str:
    if any(
        event_code in event_codes
        for event_code in (
            "llm.turn_outcome.missing",
            "llm.turn_outcome.unsuccessful",
        )
    ):
        return "failed"
    if "llm_route_attempt_succeeded" in event_codes:
        return "succeeded"
    if any(
        event_code in event_codes
        for event_code in (
            "llm_route_attempt_exhausted",
            "llm_turn_terminal",
            "llm.turn_outcome.missing",
            "llm.turn_outcome.unsuccessful",
        )
    ):
        return "failed"
    if "llm_route_attempt_started" in event_codes:
        return "running"
    return "unknown"


def _next_minimal_action(
    status: str,
    evidence_gaps: list[str],
    root_causes: list[dict[str, Any]],
) -> str:
    if evidence_gaps:
        return "inspect_telemetry"
    if status == "completed":
        return "no_action_needed"
    reasons = " ".join(
        str(item.get("code") or "").lower()
        for item in root_causes
    )
    if any(token in reasons for token in ("api_key", "auth", "credential")):
        return "configure_credentials"
    if any(
        token in reasons
        for token in ("rate", "server", "upstream", "timeout")
    ):
        return "retry_provider_later"
    if "protocol" in reasons:
        return "inspect_protocol_adapter"
    if "canonical_turn" in reasons:
        return "inspect_protocol_adapter"
    return "inspect_runtime_evidence"


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize one Vibelution chat session/turn across journal, live checkpoint, and runtime logs."
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--turn-id", default="")
    parser.add_argument("--max-runtime-matches", type=int, default=20)
    args = parser.parse_args(argv)

    report = build_session_turn_diagnosis(
        args.project_root,
        args.session_id,
        args.turn_id,
        max_runtime_matches=max(0, args.max_runtime_matches),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
