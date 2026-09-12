"""Tests for the stale blocked run cleanup client (no live backend)."""

from __future__ import annotations

import json

import pytest

from scripts.cleanup_stale_formal_runs import (
    CleanupApi,
    CleanupError,
    RunCandidate,
    apply_candidate,
    build_parser,
    planned_commands,
    run_cleanup,
    select_candidates,
)

_NOW_MS = 1_800_000_000_000
_HOUR_MS = 3_600_000
_WORKFLOW = "challenge-cup-research"


def _row(
    run_id: str,
    status: str,
    *,
    version: int = 1,
    updated_ms: int = _NOW_MS - 48 * _HOUR_MS,
    workflow_id: str = _WORKFLOW,
    question_id: str = "SCI-001",
) -> dict:
    return {
        "runId": run_id,
        "workflowId": workflow_id,
        "questionId": question_id,
        "status": status,
        "runVersion": version,
        "updatedAtMs": updated_ms,
    }


class _FakeApi:
    def __init__(self, rows: list[dict]):
        self.rows = [dict(row) for row in rows]
        self._by_id = {row["runId"]: row for row in self.rows}
        self.submitted: list[tuple[str, str, int]] = []
        self.snapshot_reads: list[str] = []

    def list_runs(self, workflow_id: str, team_id: str) -> list[dict]:
        return [
            dict(row) for row in self.rows if row["workflowId"] == workflow_id
        ]

    def run_snapshot(self, run_id: str, team_id: str) -> dict:
        self.snapshot_reads.append(run_id)
        return {"run": dict(self._by_id[run_id])}

    def submit_command(
        self,
        run_id: str,
        *,
        team_id: str,
        command: str,
        expected_run_version: int,
        payload: dict,
    ) -> dict:
        row = self._by_id[run_id]
        assert row["runVersion"] == expected_run_version
        self.submitted.append((run_id, command, expected_run_version))
        if command == "cancel_run":
            row["status"] = "cancelled"
        elif command == "archive_run":
            row["status"] = "archived"
        row["runVersion"] += 1
        return {
            "commandId": f"cmd-{len(self.submitted)}",
            "acceptedRunVersion": row["runVersion"],
        }


def _candidate(run: dict) -> RunCandidate:
    return RunCandidate.from_run(run)


def test_planned_commands_cover_cleanup_statuses() -> None:
    assert planned_commands("blocked") == ("cancel_run", "archive_run")
    assert planned_commands("reconciliation_required") == ("archive_run",)
    assert planned_commands("cancelled") == ("archive_run",)
    assert planned_commands("running") == ()


def test_select_candidates_filters_status_age_and_ids() -> None:
    runs = [
        _row("run-blocked-old", "blocked"),
        _row("run-blocked-fresh", "blocked", updated_ms=_NOW_MS - _HOUR_MS),
        _row("run-reconcile-old", "reconciliation_required"),
        _row("run-succeeded-old", "succeeded"),
    ]
    selected = select_candidates(
        runs,
        now_ms=_NOW_MS,
        older_than_ms=24 * _HOUR_MS,
    )
    assert [item.run_id for item in selected] == [
        "run-blocked-old",
        "run-reconcile-old",
    ]

    narrowed = select_candidates(
        runs,
        now_ms=_NOW_MS,
        older_than_ms=24 * _HOUR_MS,
        run_ids=frozenset({"run-reconcile-old"}),
    )
    assert [item.run_id for item in narrowed] == ["run-reconcile-old"]

    unfiltered = select_candidates(runs, now_ms=_NOW_MS, older_than_ms=0)
    assert [item.run_id for item in unfiltered] == [
        "run-blocked-old",
        "run-reconcile-old",
        "run-blocked-fresh",
    ]


def test_apply_candidate_cancels_then_archives_blocked_run() -> None:
    row = _row("run-blocked", "blocked", version=3)
    api = _FakeApi([row])

    result = apply_candidate(
        api,
        _candidate(row),
        team_id="research-team",
        reason="stale blocked run cleanup",
    )

    assert api.submitted == [
        ("run-blocked", "cancel_run", 3),
        ("run-blocked", "archive_run", 4),
    ]
    assert result["fromStatus"] == "blocked"
    assert result["finalStatus"] == "archived"
    assert [step["outcome"] for step in result["steps"]] == [
        "submitted",
        "submitted",
    ]
    assert api._by_id["run-blocked"]["status"] == "archived"


def test_apply_candidate_archives_reconciliation_run_directly() -> None:
    row = _row("run-reconcile", "reconciliation_required", version=7)
    api = _FakeApi([row])

    result = apply_candidate(
        api,
        _candidate(row),
        team_id="research-team",
        reason="stale blocked run cleanup",
    )

    assert api.submitted == [("run-reconcile", "archive_run", 7)]
    assert result["finalStatus"] == "archived"


def test_apply_candidate_archives_cancelled_run_directly() -> None:
    row = _row("run-cancelled", "cancelled", version=3)
    api = _FakeApi([row])

    result = apply_candidate(
        api,
        _candidate(row),
        team_id="research-team",
        reason="stale blocked run cleanup",
    )

    assert api.submitted == [("run-cancelled", "archive_run", 3)]
    assert result["finalStatus"] == "archived"


def test_run_cleanup_preview_never_submits() -> None:
    api = _FakeApi([_row("run-blocked", "blocked")])
    args = build_parser().parse_args(
        ["--workflow-ids", _WORKFLOW, "--older-than-hours", "0"]
    )

    report = run_cleanup(args, api)

    assert report["status"] == "preview"
    assert report["candidateCount"] == 1
    assert report["candidates"][0]["plannedCommands"] == [
        "cancel_run",
        "archive_run",
    ]
    assert report["results"] == []
    assert api.submitted == []


def test_run_cleanup_apply_archives_and_reports_remaining() -> None:
    api = _FakeApi(
        [
            _row("run-blocked", "blocked"),
            _row("run-reconcile", "reconciliation_required", version=2),
            _row("run-succeeded", "succeeded"),
        ]
    )
    args = build_parser().parse_args(
        ["--workflow-ids", _WORKFLOW, "--apply", "--older-than-hours", "0"]
    )

    report = run_cleanup(args, api)

    assert report["status"] == "applied"
    assert report["failures"] == 0
    assert report["remainingCandidates"] == 0
    assert [item["runId"] for item in report["results"]] == [
        "run-blocked",
        "run-reconcile",
    ]
    assert [command for _, command, _ in api.submitted] == [
        "cancel_run",
        "archive_run",
        "archive_run",
    ]


def test_control_token_is_fetched_once_and_attached() -> None:
    calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def transport(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        calls.append((method, url, headers, body))
        if url.endswith("/api/control-token"):
            payload = {"header": "X-Vibelution-Control-Token", "controlToken": "tok"}
        else:
            payload = {"runs": []}
        return 200, json.dumps(payload).encode("utf-8")

    api = CleanupApi("http://127.0.0.1:8000", transport=transport)
    api.list_runs(_WORKFLOW, "research-team")
    api.list_runs(_WORKFLOW, "research-team")

    token_calls = [call for call in calls if "control-token" in call[1]]
    assert len(token_calls) == 1
    assert calls[1][2]["X-Vibelution-Control-Token"] == "tok"


def test_cleanup_error_raised_on_http_failure() -> None:
    def transport(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        if url.endswith("/api/control-token"):
            return 200, b'{"header": "X-Vibelution-Control-Token", "controlToken": "tok"}'
        return 412, b'{"code": "node_not_ready", "message": "blocked"}'

    api = CleanupApi(
        "http://127.0.0.1:8000", transport=transport, retries=0
    )
    with pytest.raises(CleanupError):
        api.list_runs(_WORKFLOW, "research-team")


def test_transport_failure_raises_cleanup_error() -> None:
    def transport(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        raise TimeoutError("timed out")

    api = CleanupApi(
        "http://127.0.0.1:8000", transport=transport, retries=0
    )
    with pytest.raises(CleanupError):
        api.list_runs(_WORKFLOW, "research-team")


def test_transport_retries_until_success() -> None:
    calls: list[int] = []

    def transport(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        if url.endswith("/api/control-token"):
            return (
                200,
                b'{"header": "X-Vibelution-Control-Token", "controlToken": "tok"}',
            )
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("timed out")
        return 200, b'{"runs": []}'

    api = CleanupApi(
        "http://127.0.0.1:8000",
        transport=transport,
        retries=3,
        retry_delay_seconds=0.0,
    )
    assert api.list_runs(_WORKFLOW, "research-team") == []
    assert len(calls) == 3
