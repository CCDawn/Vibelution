"""Preview or clean up stale blocked research-workflow runs.

Dry-run by default.  ``--apply`` cancels every stale ``blocked`` run and then
archives it, and archives ``reconciliation_required`` runs directly, through the
existing run-command HTTP endpoint (run-version CAS + idempotent receipt).  The
script never edits the ledger; it is a thin client for the same commands the
workbench issues.  The backend must be running so the product runtime performs
the transitions.

Examples::

    python scripts/cleanup_stale_formal_runs.py
    python scripts/cleanup_stale_formal_runs.py --run-ids run-cc6ce68d11e2 --apply
    python scripts/cleanup_stale_formal_runs.py --older-than-hours 0
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TEAM_ID = "research-team"
DEFAULT_WORKFLOW_IDS = (
    "challenge-cup-research",
    "challenge-cup-knowledge-sideflow",
)
DEFAULT_TRANSPORT_RETRIES = 4
DEFAULT_RETRY_DELAY_SECONDS = 10.0
CLEANUP_STATUSES = ("blocked", "reconciliation_required", "cancelled")
DEFAULT_REASON = "stale blocked run cleanup"

Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


class CleanupError(RuntimeError):
    """One cleanup step could not be completed against the product API."""


def _urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method)
    for key, value in headers.items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as error:
        return int(error.code), error.read()


@dataclass(frozen=True, slots=True)
class RunCandidate:
    """One stale run that the cleanup plan would move to ``archived``."""

    run_id: str
    workflow_id: str
    question_id: str
    status: str
    run_version: int
    updated_at_ms: int

    @classmethod
    def from_run(cls, run: Mapping[str, Any]) -> RunCandidate:
        return cls(
            run_id=str(run.get("runId") or "").strip(),
            workflow_id=str(run.get("workflowId") or "").strip(),
            question_id=str(run.get("questionId") or "").strip(),
            status=str(run.get("status") or "").strip(),
            run_version=int(run.get("runVersion") or 0),
            updated_at_ms=int(run.get("updatedAtMs") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "workflowId": self.workflow_id,
            "questionId": self.question_id,
            "status": self.status,
            "runVersion": self.run_version,
            "updatedAtMs": self.updated_at_ms,
        }


def planned_commands(status: str) -> tuple[str, ...]:
    """Ordered command plan that ends in ``archived`` for one run status."""

    if status == "blocked":
        return ("cancel_run", "archive_run")
    if status in ("reconciliation_required", "cancelled"):
        return ("archive_run",)
    return ()


class CleanupApi:
    """Minimal client for the two run endpoints used by the cleanup."""

    def __init__(
        self,
        base_url: str,
        *,
        transport: Transport = _urllib_transport,
        retries: int = DEFAULT_TRANSPORT_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    ):
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._retries = max(0, int(retries))
        self._retry_delay_seconds = max(0.0, float(retry_delay_seconds))
        self._token_headers: dict[str, str] | None = None

    def _call(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        authorized: bool = True,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        raw_body: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            raw_body = json.dumps(dict(body)).encode("utf-8")
        if authorized:
            headers.update(self._control_token_headers())
        status, raw = self._transport_with_retry(
            method, f"{self._base_url}{path}", headers, raw_body
        )
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CleanupError(
                f"{method} {path} returned unreadable payload (status {status})"
            ) from error
        if status >= 400 or not isinstance(payload, dict):
            raise CleanupError(
                f"{method} {path} failed with status {status}: "
                f"{json.dumps(payload, ensure_ascii=False, default=str)[:400]}"
            )
        return payload

    def _control_token_headers(self) -> dict[str, str]:
        if self._token_headers is None:
            payload = self._call(
                "GET", "/api/control-token", authorized=False
            )
            header = str(payload.get("header") or "X-Vibelution-Control-Token")
            token = str(payload.get("controlToken") or "")
            if not token:
                raise CleanupError("control token payload is empty")
            self._token_headers = {header: token}
        return self._token_headers

    def _transport_with_retry(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> tuple[int, bytes]:
        """Retry transport failures; the body (and its idempotency key) is fixed."""

        attempts = self._retries + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return self._transport(method, url, headers, body)
            except CleanupError:
                raise
            except OSError as error:  # connection reset/refused/timeout
                last_error = error
                if attempt + 1 < attempts:
                    time.sleep(self._retry_delay_seconds)
        raise CleanupError(f"transport failure for {method} {url}: {last_error!r}")

    def list_runs(self, workflow_id: str, team_id: str) -> list[dict[str, Any]]:
        payload = self._call(
            "GET",
            f"/api/research/workflows/{workflow_id}/runs?teamId={team_id}",
        )
        runs = payload.get("runs")
        return [dict(run) for run in runs] if isinstance(runs, list) else []

    def run_snapshot(self, run_id: str, team_id: str) -> dict[str, Any]:
        return self._call(
            "GET",
            f"/api/research/workflow-runs/{run_id}/snapshot?teamId={team_id}",
        )

    def submit_command(
        self,
        run_id: str,
        *,
        team_id: str,
        command: str,
        expected_run_version: int,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._call(
            "POST",
            f"/api/research/workflow-runs/{run_id}/commands",
            body={
                "teamId": team_id,
                "command": command,
                "expectedRunVersion": expected_run_version,
                "idempotencyKey": (
                    f"cleanup-{command}-{run_id}-{uuid.uuid4().hex}"
                ),
                "payload": dict(payload),
            },
        )


def select_candidates(
    runs: Sequence[Mapping[str, Any]],
    *,
    now_ms: int,
    older_than_ms: int,
    run_ids: frozenset[str] = frozenset(),
) -> list[RunCandidate]:
    """Stale cleanup-status runs, ordered oldest first."""

    selected: list[RunCandidate] = []
    for run in runs:
        candidate = RunCandidate.from_run(run)
        if candidate.status not in CLEANUP_STATUSES or not candidate.run_id:
            continue
        if run_ids and candidate.run_id not in run_ids:
            continue
        if (
            older_than_ms > 0
            and candidate.updated_at_ms > 0
            and now_ms - candidate.updated_at_ms < older_than_ms
        ):
            continue
        selected.append(candidate)
    selected.sort(key=lambda item: (item.updated_at_ms, item.run_id))
    return selected


def apply_candidate(
    api: CleanupApi,
    candidate: RunCandidate,
    *,
    team_id: str,
    reason: str,
) -> dict[str, Any]:
    """Run the command plan, re-reading the CAS version between commands."""

    steps: list[dict[str, Any]] = []
    current = candidate
    for command in planned_commands(candidate.status):
        if current.status == "archived":
            steps.append({"command": command, "outcome": "skipped_archived"})
            break
        if current.status == "cancelled" and command == "cancel_run":
            steps.append({"command": command, "outcome": "skipped_cancelled"})
            continue
        if current.run_version < 1:
            raise CleanupError(
                f"{current.run_id} has no run version for {command}"
            )
        receipt = api.submit_command(
            current.run_id,
            team_id=team_id,
            command=command,
            expected_run_version=current.run_version,
            payload={"reason": reason},
        )
        steps.append(
            {
                "command": command,
                "outcome": "submitted",
                "acceptedRunVersion": receipt.get("acceptedRunVersion"),
                "commandId": receipt.get("commandId"),
            }
        )
        snapshot = api.run_snapshot(current.run_id, team_id)
        run = snapshot.get("run")
        if not isinstance(run, Mapping):
            raise CleanupError(
                f"{current.run_id} snapshot is missing the run after {command}"
            )
        refreshed = RunCandidate.from_run(
            {**dict(run), "workflowId": current.workflow_id}
        )
        current = refreshed
    return {
        "runId": candidate.run_id,
        "questionId": candidate.question_id,
        "fromStatus": candidate.status,
        "finalStatus": current.status,
        "steps": steps,
    }


def run_cleanup(args: argparse.Namespace, api: CleanupApi) -> dict[str, Any]:
    """Build the report; mutates only when ``args.apply`` is set."""

    workflow_ids = [
        item.strip() for item in str(args.workflow_ids).split(",") if item.strip()
    ]
    run_ids = frozenset(
        item.strip() for item in str(args.run_ids).split(",") if item.strip()
    )
    now_ms = int(time.time() * 1000)
    older_than_ms = int(float(args.older_than_hours) * 3_600_000)

    candidates: list[RunCandidate] = []
    for workflow_id in workflow_ids:
        runs = api.list_runs(workflow_id, args.team)
        candidates.extend(
            select_candidates(
                runs,
                now_ms=now_ms,
                older_than_ms=older_than_ms,
                run_ids=run_ids,
            )
        )
    candidates.sort(key=lambda item: (item.updated_at_ms, item.run_id))

    report: dict[str, Any] = {
        "status": "preview",
        "baseUrl": args.base_url,
        "teamId": args.team,
        "workflowIds": workflow_ids,
        "olderThanHours": float(args.older_than_hours),
        "candidateCount": len(candidates),
        "candidates": [
            {
                **candidate.to_dict(),
                "plannedCommands": list(planned_commands(candidate.status)),
            }
            for candidate in candidates
        ],
        "results": [],
        "failures": 0,
        "remainingCandidates": 0,
    }
    if not args.apply or not candidates:
        return report

    report["status"] = "applied"
    for candidate in candidates:
        try:
            report["results"].append(
                apply_candidate(
                    api, candidate, team_id=args.team, reason=args.reason
                )
            )
        except CleanupError as error:
            report["failures"] += 1
            report["results"].append(
                {"runId": candidate.run_id, "outcome": "failed", "error": str(error)}
            )

    remaining: list[RunCandidate] = []
    for workflow_id in workflow_ids:
        remaining.extend(
            select_candidates(
                api.list_runs(workflow_id, args.team),
                now_ms=int(time.time() * 1000),
                older_than_ms=older_than_ms,
                run_ids=run_ids,
            )
        )
    report["remainingCandidates"] = len(remaining)
    report["remaining"] = [candidate.to_dict() for candidate in remaining]
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--team", default=DEFAULT_TEAM_ID)
    parser.add_argument(
        "--workflow-ids",
        default=",".join(DEFAULT_WORKFLOW_IDS),
        help="comma separated workflow ids to scan",
    )
    parser.add_argument(
        "--run-ids",
        default="",
        help="optional comma separated run ids to restrict the selection",
    )
    parser.add_argument(
        "--older-than-hours",
        type=float,
        default=24.0,
        help="only runs not updated for this long; 0 disables the age filter",
    )
    parser.add_argument("--reason", default=DEFAULT_REASON)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="execute the plan; without it the script is a pure preview",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_cleanup(args, CleanupApi(args.base_url))
    except CleanupError as error:
        print(
            json.dumps(
                {"status": "failed", "error": str(error)}, ensure_ascii=False
            )
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failures"] or (
        report["status"] == "applied" and report["remainingCandidates"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
