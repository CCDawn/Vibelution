"""Read-only canonical Workflow Ledger audit used by the Challenge Cup CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.research.workflow.ledger import runtime as ledger_runtime
from core.research.workflow.ledger.schema import MIGRATIONS, V5_LEGACY_CHECKSUM
from core.research.workflow.ledger.schema import SCHEMA_VERSION as LEDGER_SCHEMA_VERSION

HARD_CATEGORIES = ("corrupt", "identity", "scope", "reconciliation")
LEDGER_TABLES = (
    "workflow_runs",
    "workflow_commands",
    "workflow_events",
    "node_attempts",
    "outbox_actions",
    "human_tasks",
    "execution_anchors",
    "artifact_receipts",
    "budget_receipts",
    "handoffs",
    "handoff_receipts",
    "catalog_run_authorizations",
    "knowledge_invocations",
)
ACTIVE_BUDGET_RUN_STATUSES = {"created", "running", "waiting_human"}


def _finding(code: str, detail: str, category: str) -> dict[str, str]:
    return {"code": code, "detail": detail, "category": category}


def default_ledger_path(data_root: Path) -> Path:
    return data_root / "workflow-ledger.sqlite"


def _ledger_table_counts(connection: Any) -> tuple[dict[str, int], list[dict[str, str]]]:
    present = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table'"
        )
    }
    counts: dict[str, int] = {}
    findings: list[dict[str, str]] = []
    for table in LEDGER_TABLES:
        if table not in present:
            findings.append(
                _finding(
                    "ledger_table_missing",
                    f"canonical Ledger 缺少表 {table}",
                    "corrupt",
                )
            )
            counts[table] = 0
            continue
        counts[table] = int(
            connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        )
    return counts, findings


def _ledger_migration_report(connection: Any) -> tuple[dict[str, Any], list[dict[str, str]]]:
    rows = list(
        connection.execute(
            "SELECT version, checksum, applied_at_ms FROM schema_migrations ORDER BY version"
        )
    )
    applied = {int(row[0]): str(row[1]) for row in rows}
    findings: list[dict[str, str]] = []
    for migration in MIGRATIONS:
        checksum = applied.get(migration.version)
        if checksum is None:
            findings.append(
                _finding(
                    "ledger_migration_missing",
                    f"canonical Ledger 缺少 migration v{migration.version}",
                    "corrupt",
                )
            )
            continue
        legacy_v5 = migration.version == 5 and checksum == V5_LEGACY_CHECKSUM
        if checksum != migration.checksum and not legacy_v5:
            findings.append(
                _finding(
                    "ledger_migration_checksum_mismatch",
                    f"canonical Ledger migration v{migration.version} checksum 不匹配",
                    "corrupt",
                )
            )
    actual_version = max(applied, default=0)
    if actual_version != LEDGER_SCHEMA_VERSION:
        findings.append(
            _finding(
                "ledger_schema_version_mismatch",
                f"canonical Ledger schema={actual_version}，代码要求 {LEDGER_SCHEMA_VERSION}",
                "corrupt",
            )
        )
    return {
        "actualVersion": actual_version,
        "expectedVersion": LEDGER_SCHEMA_VERSION,
        "appliedVersions": sorted(applied),
    }, findings


def _grouped_counts(connection: Any, sql: str) -> dict[str, int]:
    return {str(row[0]): int(row[1]) for row in connection.execute(sql)}


def audit_ledger(ledger_path: Path, *, data_root: Path) -> dict[str, Any]:
    """Audit the canonical SQLite Ledger without opening a writer or migrating it."""

    if not ledger_path.is_file():
        raise FileNotFoundError(f"canonical Ledger 不存在: {ledger_path}")

    ledger_runtime.require_safe_sqlite_runtime()
    connection = ledger_runtime.open_ledger_connection(str(ledger_path), read_only=True)
    try:
        integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
        integrity = str(integrity_row[0]) if integrity_row else "missing"
        table_counts, ledger_findings = _ledger_table_counts(connection)
        migration_report, migration_findings = _ledger_migration_report(connection)
        ledger_findings.extend(migration_findings)
        if integrity != "ok":
            ledger_findings.append(
                _finding(
                    "ledger_integrity_failed",
                    f"PRAGMA integrity_check={integrity}",
                    "corrupt",
                )
            )

        status_counts = _grouped_counts(
            connection,
            "SELECT status, COUNT(*) FROM workflow_runs GROUP BY status ORDER BY status",
        )
        budget_status_counts = _grouped_counts(
            connection,
            "SELECT status, COUNT(*) FROM budget_receipts GROUP BY status ORDER BY status",
        )
        outbox_status_counts = _grouped_counts(
            connection,
            "SELECT status, COUNT(*) FROM outbox_actions GROUP BY status ORDER BY status",
        )
        event_stats = {
            str(row[0]): {
                "count": int(row[1]),
                "minimum": int(row[2]),
                "maximum": int(row[3]),
            }
            for row in connection.execute(
                "SELECT run_id, COUNT(*), MIN(sequence), MAX(sequence) "
                "FROM workflow_events GROUP BY run_id"
            )
        }
        attempt_counts = _grouped_counts(
            connection,
            "SELECT run_id, COUNT(*) FROM node_attempts GROUP BY run_id",
        )
        handoff_counts = _grouped_counts(
            connection,
            "SELECT run_id, COUNT(*) FROM handoffs GROUP BY run_id",
        )
        artifact_counts = _grouped_counts(
            connection,
            "SELECT run_id, COUNT(*) FROM artifact_receipts GROUP BY run_id",
        )
        reserved_counts = _grouped_counts(
            connection,
            "SELECT run_id, COUNT(*) FROM budget_receipts "
            "WHERE status = 'reserved' GROUP BY run_id",
        )

        entries: list[dict[str, Any]] = []
        for row in connection.execute(
            "SELECT run_id, team_id, workflow_id, workflow_version_id, project_id, "
            "question_id, status, run_version, last_event_sequence, active_node_id, "
            "completion_kind, terminal_reason, blocked_problem_json, created_at_ms, "
            "updated_at_ms, completed_at_ms "
            "FROM workflow_runs ORDER BY updated_at_ms DESC, run_id DESC"
        ):
            run_id = str(row[0])
            status = str(row[6])
            last_event_sequence = int(row[8])
            stats = event_stats.get(
                run_id, {"count": 0, "minimum": 0, "maximum": 0}
            )
            findings: list[dict[str, str]] = []
            if (
                stats["count"] != last_event_sequence
                or stats["maximum"] != last_event_sequence
                or (stats["count"] > 0 and stats["minimum"] != 1)
            ):
                findings.append(
                    _finding(
                        "ledger_event_sequence_mismatch",
                        f"lastEventSequence={last_event_sequence}, events={stats}",
                        "corrupt",
                    )
                )
            reserved = int(reserved_counts.get(run_id, 0))
            if reserved and status not in ACTIVE_BUDGET_RUN_STATUSES:
                findings.append(
                    _finding(
                        "orphan_budget_reservation",
                        f"Run 状态 {status} 仍有 {reserved} 条 reserved 预算收据",
                        "reconciliation",
                    )
                )
            entries.append(
                {
                    "runId": run_id,
                    "teamId": str(row[1]),
                    "workflowId": str(row[2]),
                    "workflowVersionId": str(row[3]),
                    "projectId": str(row[4]),
                    "questionId": str(row[5]),
                    "status": status,
                    "runVersion": int(row[7]),
                    "lastEventSequence": last_event_sequence,
                    "activeNodeId": row[9],
                    "completionKind": row[10],
                    "terminalReason": row[11],
                    "blockedProblem": json.loads(row[12]) if row[12] else None,
                    "createdAtMs": int(row[13]),
                    "updatedAtMs": int(row[14]),
                    "completedAtMs": row[15],
                    "eventCount": stats["count"],
                    "nodeAttemptCount": int(attempt_counts.get(run_id, 0)),
                    "handoffCount": int(handoff_counts.get(run_id, 0)),
                    "artifactReceiptCount": int(artifact_counts.get(run_id, 0)),
                    "reservedBudgetReceiptCount": reserved,
                    "findings": findings,
                }
            )

        hard_findings: list[tuple[str, str]] = [
            ("ledger", finding["code"])
            for finding in ledger_findings
            if finding["category"] in HARD_CATEGORIES
        ]
        hard_findings.extend(
            (entry["runId"], finding["code"])
            for entry in entries
            for finding in entry["findings"]
            if finding["category"] in HARD_CATEGORIES
        )
        legacy_run_count = len(list((data_root / "runs").glob("run-*.json")))
        summary = {
            "runCount": int(table_counts.get("workflow_runs", 0)),
            "eventCount": int(table_counts.get("workflow_events", 0)),
            "handoffCount": int(table_counts.get("handoffs", 0)),
            "humanTaskCount": int(table_counts.get("human_tasks", 0)),
            "sessionBindingCount": 0,
            "taskBundleCount": int(table_counts.get("knowledge_invocations", 0)),
            "reservationCount": int(table_counts.get("budget_receipts", 0)),
            "artifactManifestCount": int(table_counts.get("artifact_receipts", 0)),
            "catalogRunAuthorizationCount": int(
                table_counts.get("catalog_run_authorizations", 0)
            ),
            "reservedBudgetReceiptCount": int(budget_status_counts.get("reserved", 0)),
            "pendingOutboxCount": int(outbox_status_counts.get("pending", 0)),
            "successfulRunCount": int(status_counts.get("succeeded", 0)),
            "statusCounts": status_counts,
            "budgetStatusCounts": budget_status_counts,
            "outboxStatusCounts": outbox_status_counts,
            "legacyJsonRunCount": legacy_run_count,
            "classifications": status_counts,
        }
        return {
            "schemaVersion": 2,
            "generatedAtMs": 0,
            "source": "workflow-ledger",
            "dataRoot": str(data_root),
            "ledgerPath": str(ledger_path),
            "ledger": {
                "integrity": integrity,
                "migration": migration_report,
                "tableCounts": table_counts,
                "findings": ledger_findings,
            },
            "passed": not hard_findings,
            "runs": entries,
            "summary": summary,
            "hardFindings": hard_findings,
        }
    finally:
        connection.close()
