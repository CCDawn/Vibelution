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

    return {
        "sessionId": normalized_session_id,
        "turnId": normalized_turn_id,
        "paths": {
            "journal": str(journal_path),
            "liveOutput": str(live_output_path),
            "runtimeScenes": str(root / "logs" / "runtime_scenes"),
        },
        "journal": _summarize_journal(journal_path, normalized_turn_id),
        "liveOutput": _summarize_live_output(live_output_path, normalized_turn_id),
        "runtimeEvidence": _find_runtime_evidence(
            root,
            normalized_session_id,
            normalized_turn_id,
            max_matches=max_runtime_matches,
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

    for jsonl_path in sorted(runtime_root.rglob("*.jsonl")):
        if len(matches) >= max_matches:
            break
        try:
            with jsonl_path.open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if len(matches) >= max_matches:
                        break
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
                    matches.append(_runtime_match_summary(parsed, jsonl_path, project_root, line_number))
        except OSError as exc:
            decode_errors.append(
                {
                    "path": _display_path(jsonl_path, project_root),
                    "line": 0,
                    "error": str(exc),
                    "position": 0,
                }
            )

    return {
        "exists": True,
        "searchedRoot": str(runtime_root),
        "matchCount": len(matches),
        "matches": matches,
        "decodeErrors": decode_errors,
    }


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
        "timestamp": str(parsed.get("timestamp") or ""),
        "eventCode": str(parsed.get("eventCode") or parsed.get("event_code") or ""),
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
