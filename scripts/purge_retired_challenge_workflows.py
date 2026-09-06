"""Preview or purge retired Challenge Cup workflow runs from the active instance."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.research.workflow.checkpoint_store import (
    default_checkpoint_path,
    list_checkpoint_thread_ids,
    prepare_operator_checkpoint_thread_purge,
    purge_operator_checkpoint_thread_purge,
)
from core.research.workflow.definition import (
    CHALLENGE_CUP_WORKFLOW_ID,
    build_challenge_cup_workflow_definition,
)
from core.research.workflow.definition_registry import definition_identity
from core.research.workflow.ledger import (
    WorkflowLedgerStore,
    destroy_run_ledger_reset_stage,
    prepare_run_ledger_reset_stage,
    purge_run_ledger_reset_stage,
    restore_run_ledger_reset_stage,
)
from core.web.services.team_workflow.research_runtime.paths import workflow_ledger_path

ACTIVE_STATUSES = frozenset(
    {
        "queued",
        "starting",
        "dispatching",
        "running",
        "stopping",
        "paused",
        "waiting_human",
        "summarizing",
        "awaiting_approval",
        "collecting",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Remove only Challenge Cup runs whose workflow definition identity no longer "
            "matches the current registered definition. Preview is the default."
        )
    )
    parser.add_argument("--team-id", default="research-team")
    parser.add_argument("--apply", action="store_true")
    return parser


def _run_summary(run: Any) -> dict[str, Any]:
    payload = asdict(run)
    return {
        "runId": payload["run_id"],
        "questionId": payload["question_id"],
        "status": payload["status"],
        "workflowVersionId": payload["workflow_version_id"],
        "structureHash": payload["structure_hash"],
        "threadId": payload["thread_id"],
    }


def main() -> int:
    args = _parser().parse_args()
    team_id = str(args.team_id or "").strip()
    if not team_id:
        raise SystemExit("--team-id is required")

    identity = definition_identity(build_challenge_cup_workflow_definition())
    ledger_path = workflow_ledger_path()
    checkpoint_path = default_checkpoint_path()
    store = WorkflowLedgerStore(ledger_path)
    store.open()
    try:
        runs = store.list_runs_for_team(team_id, CHALLENGE_CUP_WORKFLOW_ID)
        retired = sorted(
            (
                run
                for run in runs
                if run.workflow_version_id != identity.workflowVersionId
                or run.structure_hash != identity.structureHash
            ),
            key=lambda run: run.run_id,
        )
        active = [run.run_id for run in retired if run.status in ACTIVE_STATUSES]
        if active:
            raise RuntimeError(
                "retired workflow runs are still active: " + ", ".join(active)
            )
        run_ids = [run.run_id for run in retired]
        candidate_threads = {
            value
            for run in retired
            for value in (run.run_id, run.thread_id)
            if value
        }
        existing_threads = set(list_checkpoint_thread_ids(checkpoint_path))
        checkpoint_threads = sorted(candidate_threads & existing_threads)
        result: dict[str, Any] = {
            "status": "preview",
            "teamId": team_id,
            "workflowId": CHALLENGE_CUP_WORKFLOW_ID,
            "currentIdentity": identity.to_dict(),
            "retiredRuns": [_run_summary(run) for run in retired],
            "retiredRunCount": len(retired),
            "checkpointThreads": checkpoint_threads,
            "checkpointThreadCount": len(checkpoint_threads),
            "ledgerPath": str(ledger_path),
            "checkpointPath": str(checkpoint_path),
        }
        if not args.apply or not run_ids:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        reset_id = f"retired-workflow-{uuid4().hex}"
        ledger_stage = prepare_run_ledger_reset_stage(
            store,
            run_ids,
            reset_id,
            team_id=team_id,
        )
        checkpoint_preflight = (
            prepare_operator_checkpoint_thread_purge(
                reset_id,
                checkpoint_threads,
                checkpoint_path=checkpoint_path,
            )
            if checkpoint_threads
            else None
        )
        ledger_result = purge_run_ledger_reset_stage(
            store,
            ledger_stage,
            reset_id=reset_id,
        )
        try:
            checkpoint_result = (
                purge_operator_checkpoint_thread_purge(
                    checkpoint_preflight,
                    checkpoint_path=checkpoint_path,
                    reset_id=reset_id,
                )
                if checkpoint_preflight is not None
                else {"deletedCheckpoints": 0, "deletedWrites": 0}
            )
        except Exception:
            restore_run_ledger_reset_stage(
                store,
                ledger_stage,
                reset_id=reset_id,
            )
            raise
        destroy_run_ledger_reset_stage(ledger_stage, reset_id=reset_id)

        remaining = store.list_runs_for_team(team_id, CHALLENGE_CUP_WORKFLOW_ID)
        remaining_retired = [
            run.run_id
            for run in remaining
            if run.workflow_version_id != identity.workflowVersionId
            or run.structure_hash != identity.structureHash
        ]
        if remaining_retired:
            raise RuntimeError(
                "retired workflow runs remain after purge: " + ", ".join(remaining_retired)
            )
        remaining_threads = set(list_checkpoint_thread_ids(checkpoint_path))
        stale_threads = sorted(set(checkpoint_threads) & remaining_threads)
        if stale_threads:
            raise RuntimeError(
                "retired checkpoint threads remain after purge: " + ", ".join(stale_threads)
            )
        result.update(
            {
                "status": "applied",
                "resetId": reset_id,
                "ledger": ledger_result,
                "checkpoints": checkpoint_result,
                "remainingRunCount": len(remaining),
                "remainingRetiredRunIds": [],
                "remainingRetiredCheckpointThreads": [],
            }
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
