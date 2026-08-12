"""Shared legacy JSON Run fixtures for T8 migration tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def build_legacy_run_record(**overrides) -> dict:
    run_id = str(overrides.get("runId") or "run-audittest")
    node_run_id = f"nr-{run_id}-source_finding-a1"
    record = {
        "runId": run_id,
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "challenge-cup-research-v2.1.0",
        "structureHash": "a" * 64,
        "teamId": "research-team",
        "projectId": "challenge-sci-096",
        "questionId": "SCI-096",
        "threadId": "thread-audittest",
        "status": "queued",
        "runVersion": 1,
        "createdAt": "2026-08-12T00:00:00Z",
        "updatedAt": "2026-08-12T00:00:00Z",
        "inputSnapshot": {
            "teamId": "research-team",
            "projectId": "challenge-sci-096",
            "questionId": "SCI-096",
            "workflowVersionId": "challenge-cup-research-v2.1.0",
            "snapshotHash": "b" * 64,
            "budgetPolicy": {},
            "agentBindingSnapshot": [],
        },
        "bindingSnapshots": [],
        "events": [
            {
                "eventId": "evt-audit1",
                "sequence": 1,
                "occurredAt": "2026-08-12T00:00:00Z",
                "runId": run_id,
                "type": "run.queued",
                "summary": {},
            }
        ],
        "humanTasks": [],
        "handoffs": [],
        "sessionBindings": {},
        "iterationDecisions": [],
        "taskLeases": [],
        "commandReceipts": [],
        "outbox": [],
        "budgetLedgers": [],
        "budgetReservations": [],
        "artifactManifests": [],
        "nodeRuns": [
            {
                "nodeRunId": node_run_id,
                "runId": run_id,
                "nodeId": "source_finding",
                "attempt": 1,
                "actorType": "agent",
                "agentId": "agent-sci-096-finder",
                "taskId": "",
                "sessionId": "",
                "status": "ready",
                "inputSnapshotHash": "b" * 64,
                "idempotencyKey": f"{run_id}:source_finding:1",
                "artifactRefs": [],
                "checkpointId": "",
                "startedAt": "",
                "finishedAt": "",
            }
        ],
        "completionKind": "",
        "terminalReason": "",
        "createIdempotencyKey": f"create:{run_id}",
        "createInputFingerprint": "c" * 64,
        "langGraph": {"engine": "challenge_cup_graph", "checkpointId": "", "completedNodeIds": []},
    }
    record.update(overrides)
    return record


def write_legacy_run(data_root: Path, record: dict) -> Path:
    runs = data_root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / f"{record['runId']}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_checkpoint(data_root: Path, thread_id: str = "thread-audittest") -> Path:
    data_root.mkdir(parents=True, exist_ok=True)
    path = data_root / "checkpoints.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS checkpoints (thread_id TEXT NOT NULL)")
    conn.execute("INSERT INTO checkpoints (thread_id) VALUES (?)", (thread_id,))
    conn.commit()
    conn.close()
    return path
