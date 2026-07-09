from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
for path in (REPO_ROOT, SCRIPTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from core.chat.turn_journal import (  # noqa: E402
    EVENT_ASSISTANT_MESSAGE,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_turn_event,
    turn_journal_path,
)
from diagnose_session_turn import build_session_turn_diagnosis  # noqa: E402


PROBE_PACKAGE_NAME = "probe_conversation_runtime_scene"
PROBE_EVENT_CODES = [
    "conversation_probe.message.submitted",
    "session.detail_snapshot.published",
    "conversation_probe.llm.status",
    "conversation_probe.tool.started",
    "conversation_probe.tool.completed",
    "session.assistant_delta.published",
    "conversation_probe.turn.persisted",
    "session.detail_snapshot.published",
]


def build_conversation_runtime_probe(
    project_root: Path | str,
    session_id: str = "",
    turn_id: str = "",
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    normalized_session_id = str(session_id or "").strip() or f"probe-session-{uuid4().hex[:12]}"
    normalized_turn_id = str(turn_id or "").strip() or f"probe-turn-{uuid4().hex[:12]}"

    _write_probe_journal(root, normalized_session_id, normalized_turn_id)
    _write_probe_live_output(root, normalized_session_id, normalized_turn_id)
    event_path = _write_probe_runtime_scene(root, normalized_session_id, normalized_turn_id)

    report = build_session_turn_diagnosis(
        root,
        normalized_session_id,
        normalized_turn_id,
        max_runtime_matches=len(PROBE_EVENT_CODES),
    )
    report["probe"] = {
        "packagePath": str(event_path.parents[1]),
        "eventPath": str(event_path),
        "runtimeEventCount": len(PROBE_EVENT_CODES),
        "eventCodes": list(PROBE_EVENT_CODES),
        "synthetic": True,
    }
    return report


def _write_probe_journal(project_root: Path, session_id: str, turn_id: str) -> None:
    append_turn_event(
        project_root,
        session_id,
        turn_id,
        EVENT_TURN_STARTED,
        status="running",
        source="conversation_runtime_probe",
    )
    append_turn_event(
        project_root,
        session_id,
        turn_id,
        EVENT_USER_MESSAGE,
        status="recorded",
        source="conversation_runtime_probe",
        payload={"content": "probe user message"},
    )
    append_turn_event(
        project_root,
        session_id,
        turn_id,
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        source="conversation_runtime_probe",
        payload={"content": "probe assistant response"},
    )
    append_turn_event(
        project_root,
        session_id,
        turn_id,
        EVENT_TURN_COMPLETED,
        status="completed",
        source="conversation_runtime_probe",
        payload={"summary": "probe assistant response"},
    )


def _write_probe_live_output(project_root: Path, session_id: str, turn_id: str) -> None:
    path = turn_journal_path(project_root, session_id).with_name("live_output.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "sessionId": session_id,
                "turnId": turn_id,
                "stage": "assistant_response",
                "content": "probe assistant response",
                "thought": "probe thought",
                "toolCalls": [
                    {
                        "toolCallId": "probe-tool-1",
                        "name": "probe_tool",
                        "status": "completed",
                    }
                ],
                "feedbackEvents": [],
                "updatedAt": _timestamp(5),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_probe_runtime_scene(project_root: Path, session_id: str, turn_id: str) -> Path:
    event_path = (
        project_root
        / "logs"
        / "runtime_scenes"
        / PROBE_PACKAGE_NAME
        / "events"
        / "conversation.jsonl"
    )
    event_path.parent.mkdir(parents=True, exist_ok=True)
    events = [
        _event(
            0,
            PROBE_EVENT_CODES[0],
            "submitted",
            session_id,
            turn_id,
            {"messageChars": 18},
        ),
        _event(
            1,
            PROBE_EVENT_CODES[1],
            "published",
            session_id,
            turn_id,
            {"currentPhase": "running", "messageCount": 1},
        ),
        _event(
            2,
            PROBE_EVENT_CODES[2],
            "streaming",
            session_id,
            turn_id,
            {"llmSlot": "dialogue", "provider": "probe", "streaming": True},
        ),
        _event(
            3,
            PROBE_EVENT_CODES[3],
            "started",
            session_id,
            turn_id,
            {"toolCallId": "probe-tool-1", "toolName": "probe_tool"},
        ),
        _event(
            4,
            PROBE_EVENT_CODES[4],
            "completed",
            session_id,
            turn_id,
            {"toolCallId": "probe-tool-1", "toolName": "probe_tool", "ok": True},
        ),
        _event(
            5,
            PROBE_EVENT_CODES[5],
            "published",
            session_id,
            turn_id,
            {
                "stage": "assistant_response",
                "contentChars": len("probe assistant response"),
                "thoughtChars": len("probe thought"),
                "done": False,
            },
        ),
        _event(
            6,
            PROBE_EVENT_CODES[6],
            "persisted",
            session_id,
            turn_id,
            {"terminalEvent": EVENT_TURN_COMPLETED, "assistantMessageChars": len("probe assistant response")},
        ),
        _event(
            7,
            PROBE_EVENT_CODES[7],
            "published",
            session_id,
            turn_id,
            {"currentPhase": "completed", "messageCount": 2},
        ),
    ]
    event_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n" for event in events),
        encoding="utf-8",
    )
    manifest_path = event_path.parents[1] / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": "conversation_runtime_probe",
                "synthetic": True,
                "sessionId": session_id,
                "turnId": turn_id,
                "eventPath": str(event_path),
                "eventCodes": list(PROBE_EVENT_CODES),
                "createdAt": _timestamp(0),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return event_path


def _event(
    offset_seconds: int,
    event_code: str,
    outcome: str,
    session_id: str,
    turn_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    payload_fields = {
        "sessionId": session_id,
        "turnId": turn_id,
        "probe": True,
    }
    payload_fields.update(fields)
    return {
        "timestamp": _timestamp(offset_seconds),
        "eventCode": event_code,
        "level": "info",
        "outcome": outcome,
        "message": "Synthetic conversation runtime-scene probe event.",
        "fields": payload_fields,
    }


def _timestamp(offset_seconds: int) -> str:
    value = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a synthetic conversation runtime-scene package and print the correlated diagnosis report."
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--session-id", default="")
    parser.add_argument("--turn-id", default="")
    args = parser.parse_args(argv)

    report = build_conversation_runtime_probe(args.project_root, args.session_id, args.turn_id)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
