"""Deterministic schema migrations with checksums (spec 6.1/6.2).

Migrations are static statement lists. The checksum of an applied version must
match; a mismatch fails startup instead of silently migrating a drifted DB.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    version: int
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        return hashlib.sha256("\n".join(self.statements).encode("utf-8")).hexdigest()


SCHEMA_VERSION = 5


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        statements=(
            """
            CREATE TABLE workflow_runs (
              run_id TEXT PRIMARY KEY,
              team_id TEXT NOT NULL,
              workflow_id TEXT NOT NULL,
              workflow_version_id TEXT NOT NULL,
              thread_id TEXT NOT NULL UNIQUE,
              project_id TEXT NOT NULL,
              question_id TEXT NOT NULL,
              status TEXT NOT NULL CHECK (status IN (
                'created','running','waiting_human','blocked',
                'reconciliation_required','succeeded','failed','cancelled','archived'
              )),
              run_version INTEGER NOT NULL CHECK (run_version >= 1),
              last_event_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_event_sequence >= 0),
              input_snapshot_json TEXT NOT NULL CHECK (json_valid(input_snapshot_json)),
              input_snapshot_hash TEXT NOT NULL,
              safety_limits_json TEXT NOT NULL CHECK (json_valid(safety_limits_json)),
              binding_snapshot_set_id TEXT NOT NULL,
              active_node_id TEXT,
              parent_run_id TEXT,
              forked_from_checkpoint_id TEXT,
              completion_kind TEXT,
              terminal_reason TEXT,
              blocked_problem_json TEXT CHECK (
                blocked_problem_json IS NULL OR json_valid(blocked_problem_json)
              ),
              created_at_ms INTEGER NOT NULL,
              updated_at_ms INTEGER NOT NULL,
              completed_at_ms INTEGER,
              FOREIGN KEY (parent_run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT
            )
            """,
            """
            CREATE INDEX idx_workflow_runs_team_recent
            ON workflow_runs(team_id, workflow_id, created_at_ms DESC, run_id DESC)
            """,
            """
            CREATE INDEX idx_workflow_runs_status
            ON workflow_runs(status, updated_at_ms, run_id)
            """,
            """
            CREATE TABLE workflow_commands (
              command_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              team_id TEXT NOT NULL,
              node_id TEXT,
              command_kind TEXT NOT NULL,
              expected_run_version INTEGER NOT NULL,
              accepted_run_version INTEGER,
              idempotency_key TEXT NOT NULL,
              request_hash TEXT NOT NULL,
              request_json TEXT NOT NULL CHECK (json_valid(request_json)),
              requested_by_json TEXT NOT NULL CHECK (json_valid(requested_by_json)),
              status TEXT NOT NULL CHECK (status IN ('accepted','completed','failed')),
              result_json TEXT CHECK (result_json IS NULL OR json_valid(result_json)),
              problem_json TEXT CHECK (problem_json IS NULL OR json_valid(problem_json)),
              created_at_ms INTEGER NOT NULL,
              completed_at_ms INTEGER,
              UNIQUE (run_id, idempotency_key),
              FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT
            )
            """,
            """
            CREATE INDEX idx_workflow_commands_run_created
            ON workflow_commands(run_id, created_at_ms DESC, command_id DESC)
            """,
            """
            CREATE TABLE node_attempts (
              node_run_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              node_id TEXT NOT NULL,
              attempt INTEGER NOT NULL CHECK (attempt >= 1),
              actor_kind TEXT NOT NULL CHECK (actor_kind IN ('agent','system','human')),
              status TEXT NOT NULL CHECK (status IN (
                'starting','dispatching','running','waiting_human','succeeded',
                'failed','blocked','cancelled','stale'
              )),
              command_id TEXT NOT NULL,
              binding_snapshot_id TEXT,
              input_snapshot_hash TEXT NOT NULL,
              pending_action_id TEXT,
              execution_anchor_id TEXT,
              retry_of_node_run_id TEXT,
              problem_json TEXT CHECK (problem_json IS NULL OR json_valid(problem_json)),
              started_at_ms INTEGER NOT NULL,
              updated_at_ms INTEGER NOT NULL,
              finished_at_ms INTEGER,
              UNIQUE (run_id, node_id, attempt),
              FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT,
              FOREIGN KEY (command_id) REFERENCES workflow_commands(command_id) ON DELETE RESTRICT,
              FOREIGN KEY (retry_of_node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT
            )
            """,
            """
            CREATE INDEX idx_node_attempts_run_status
            ON node_attempts(run_id, status, node_id, attempt DESC)
            """,
            """
            CREATE TABLE workflow_events (
              run_id TEXT NOT NULL,
              sequence INTEGER NOT NULL CHECK (sequence >= 1),
              event_id TEXT NOT NULL UNIQUE,
              run_version INTEGER NOT NULL CHECK (run_version >= 1),
              event_type TEXT NOT NULL,
              actor_json TEXT NOT NULL CHECK (json_valid(actor_json)),
              correlation_id TEXT NOT NULL,
              causation_id TEXT,
              payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
              occurred_at_ms INTEGER NOT NULL,
              PRIMARY KEY (run_id, sequence),
              FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE outbox_actions (
              action_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              command_id TEXT,
              node_run_id TEXT,
              action_kind TEXT NOT NULL CHECK (action_kind IN (
                'graph_dispatch','adapter_dispatch','event_publish','reconcile',
                'checkpoint_fork'
              )),
              idempotency_key TEXT NOT NULL UNIQUE,
              payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
              status TEXT NOT NULL CHECK (status IN (
                'pending','leased','succeeded','failed','cancelled'
              )),
              attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
              available_at_ms INTEGER NOT NULL,
              lease_owner TEXT,
              lease_expires_at_ms INTEGER,
              last_problem_json TEXT CHECK (
                last_problem_json IS NULL OR json_valid(last_problem_json)
              ),
              created_at_ms INTEGER NOT NULL,
              updated_at_ms INTEGER NOT NULL,
              CHECK (action_kind = 'reconcile' OR command_id IS NOT NULL),
              FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT,
              FOREIGN KEY (command_id) REFERENCES workflow_commands(command_id) ON DELETE RESTRICT,
              FOREIGN KEY (node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT
            )
            """,
            """
            CREATE INDEX idx_outbox_ready
            ON outbox_actions(status, available_at_ms, lease_expires_at_ms, action_id)
            """,
            """
            CREATE TABLE execution_anchors (
              anchor_id TEXT PRIMARY KEY,
              node_run_id TEXT NOT NULL UNIQUE,
              actor_kind TEXT NOT NULL CHECK (actor_kind IN ('agent','system','human')),
              agent_id TEXT,
              role_key TEXT,
              session_id TEXT,
              session_attempt INTEGER,
              task_id TEXT,
              turn_id TEXT,
              system_action_id TEXT,
              human_task_id TEXT,
              checkpoint_id TEXT,
              status TEXT NOT NULL,
              anchor_json TEXT NOT NULL CHECK (json_valid(anchor_json)),
              created_at_ms INTEGER NOT NULL,
              FOREIGN KEY (node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE artifact_receipts (
              receipt_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              node_run_id TEXT NOT NULL,
              team_id TEXT NOT NULL,
              artifact_kind TEXT NOT NULL,
              canonical_ref_json TEXT NOT NULL CHECK (json_valid(canonical_ref_json)),
              artifact_version TEXT NOT NULL,
              sha256 TEXT NOT NULL,
              domain_revision TEXT NOT NULL,
              materialized INTEGER NOT NULL CHECK (materialized IN (0,1)),
              verified_at_ms INTEGER NOT NULL,
              UNIQUE (node_run_id, artifact_kind, artifact_version, sha256),
              FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT,
              FOREIGN KEY (node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE budget_receipts (
              receipt_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              node_run_id TEXT NOT NULL,
              reservation_id TEXT NOT NULL UNIQUE,
              stage_id TEXT NOT NULL,
              policy_hash TEXT NOT NULL,
              reserved_json TEXT NOT NULL CHECK (json_valid(reserved_json)),
              settled_json TEXT CHECK (settled_json IS NULL OR json_valid(settled_json)),
              status TEXT NOT NULL CHECK (status IN ('reserved','settled','released','failed')),
              created_at_ms INTEGER NOT NULL,
              updated_at_ms INTEGER NOT NULL,
              FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT,
              FOREIGN KEY (node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE handoffs (
              handoff_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              edge_id TEXT NOT NULL,
              from_node_run_id TEXT NOT NULL,
              to_node_id TEXT NOT NULL,
              to_node_run_id TEXT,
              gate_kind TEXT NOT NULL,
              input_snapshot_hash TEXT NOT NULL,
              status TEXT NOT NULL CHECK (status IN (
                'pending','ready','waiting_human','accepted','rejected',
                'superseded','failed'
              )),
              accepted_by_json TEXT CHECK (accepted_by_json IS NULL OR json_valid(accepted_by_json)),
              rejection_problem_json TEXT CHECK (
                rejection_problem_json IS NULL OR json_valid(rejection_problem_json)
              ),
              supersedes_handoff_id TEXT,
              offered_at_ms INTEGER NOT NULL,
              accepted_at_ms INTEGER,
              UNIQUE (run_id, edge_id, from_node_run_id, input_snapshot_hash),
              FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT,
              FOREIGN KEY (from_node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT,
              FOREIGN KEY (to_node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT,
              FOREIGN KEY (supersedes_handoff_id) REFERENCES handoffs(handoff_id) ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE handoff_receipts (
              handoff_id TEXT NOT NULL,
              receipt_id TEXT NOT NULL,
              ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
              PRIMARY KEY (handoff_id, receipt_id),
              UNIQUE (handoff_id, ordinal),
              FOREIGN KEY (handoff_id) REFERENCES handoffs(handoff_id) ON DELETE RESTRICT,
              FOREIGN KEY (receipt_id) REFERENCES artifact_receipts(receipt_id) ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE human_tasks (
              task_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              node_run_id TEXT NOT NULL,
              handoff_id TEXT,
              task_kind TEXT NOT NULL,
              prompt_json TEXT NOT NULL CHECK (json_valid(prompt_json)),
              status TEXT NOT NULL CHECK (status IN ('pending','accepted','rejected','revised','cancelled')),
              decision_json TEXT CHECK (decision_json IS NULL OR json_valid(decision_json)),
              created_at_ms INTEGER NOT NULL,
              resolved_at_ms INTEGER,
              FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT,
              FOREIGN KEY (node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT,
              FOREIGN KEY (handoff_id) REFERENCES handoffs(handoff_id) ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE recovery_records (
              recovery_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              problem_code TEXT NOT NULL,
              evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
              status TEXT NOT NULL CHECK (status IN ('open','resolved','waived')),
              resolution_json TEXT CHECK (resolution_json IS NULL OR json_valid(resolution_json)),
              created_at_ms INTEGER NOT NULL,
              resolved_at_ms INTEGER,
              FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE projection_cursors (
              projection_name TEXT NOT NULL,
              run_id TEXT NOT NULL,
              last_sequence INTEGER NOT NULL CHECK (last_sequence >= 0),
              updated_at_ms INTEGER NOT NULL,
              PRIMARY KEY (projection_name, run_id),
              FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE CASCADE
            )
            """,
        ),
    ),
    # Additive: accept budget reservation terminal status `voided` (crash /
    # compensation). Existing v1 DBs rebuild the table; new DBs apply v1 then v2.
    # Tests recreate the ledger DB and therefore pick this up automatically.
    Migration(
        version=2,
        statements=(
            """
            CREATE TABLE budget_receipts__v2 (
              receipt_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              node_run_id TEXT NOT NULL,
              reservation_id TEXT NOT NULL UNIQUE,
              stage_id TEXT NOT NULL,
              policy_hash TEXT NOT NULL,
              reserved_json TEXT NOT NULL CHECK (json_valid(reserved_json)),
              settled_json TEXT CHECK (settled_json IS NULL OR json_valid(settled_json)),
              status TEXT NOT NULL CHECK (status IN (
                'reserved','settled','released','failed','voided'
              )),
              created_at_ms INTEGER NOT NULL,
              updated_at_ms INTEGER NOT NULL,
              FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT,
              FOREIGN KEY (node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT
            )
            """,
            """
            INSERT INTO budget_receipts__v2 (
              receipt_id, run_id, node_run_id, reservation_id, stage_id,
              policy_hash, reserved_json, settled_json, status,
              created_at_ms, updated_at_ms
            )
            SELECT
              receipt_id, run_id, node_run_id, reservation_id, stage_id,
              policy_hash, reserved_json, settled_json, status,
              created_at_ms, updated_at_ms
            FROM budget_receipts
            """,
            "DROP TABLE budget_receipts",
            "ALTER TABLE budget_receipts__v2 RENAME TO budget_receipts",
        ),
    ),
    # Additive: accept outbox action kind `delivery_orchestration` (post-run
    # delivery chain) and let run-scoped kinds skip command_id, like
    # `reconcile`. Existing v2 DBs rebuild the table; new DBs apply v1..v3.
    Migration(
        version=3,
        statements=(
            """
            CREATE TABLE outbox_actions__v3 (
              action_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              command_id TEXT,
              node_run_id TEXT,
              action_kind TEXT NOT NULL CHECK (action_kind IN (
                'graph_dispatch','adapter_dispatch','event_publish','reconcile',
                'checkpoint_fork','delivery_orchestration'
              )),
              idempotency_key TEXT NOT NULL UNIQUE,
              payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
              status TEXT NOT NULL CHECK (status IN (
                'pending','leased','succeeded','failed','cancelled'
              )),
              attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
              available_at_ms INTEGER NOT NULL,
              lease_owner TEXT,
              lease_expires_at_ms INTEGER,
              last_problem_json TEXT CHECK (
                last_problem_json IS NULL OR json_valid(last_problem_json)
              ),
              created_at_ms INTEGER NOT NULL,
              updated_at_ms INTEGER NOT NULL,
              CHECK (action_kind IN ('reconcile','delivery_orchestration')
                     OR command_id IS NOT NULL),
              FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT,
              FOREIGN KEY (command_id) REFERENCES workflow_commands(command_id) ON DELETE RESTRICT,
              FOREIGN KEY (node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT
            )
            """,
            """
            INSERT INTO outbox_actions__v3 (
              action_id, run_id, command_id, node_run_id, action_kind,
              idempotency_key, payload_json, status, attempt_count,
              available_at_ms, lease_owner, lease_expires_at_ms,
              last_problem_json, created_at_ms, updated_at_ms
            )
            SELECT
              action_id, run_id, command_id, node_run_id, action_kind,
              idempotency_key, payload_json, status, attempt_count,
              available_at_ms, lease_owner, lease_expires_at_ms,
              last_problem_json, created_at_ms, updated_at_ms
            FROM outbox_actions
            """,
            "DROP TABLE outbox_actions",
            "ALTER TABLE outbox_actions__v3 RENAME TO outbox_actions",
            """
            CREATE INDEX idx_outbox_ready
            ON outbox_actions(status, available_at_ms, lease_expires_at_ms, action_id)
            """,
        ),
    ),
    Migration(
        version=4,
        statements=(
            (
                "ALTER TABLE execution_anchors "
                "ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
            ),
        ),
    ),
    Migration(
        version=5,
        statements=(
            """
            CREATE TABLE catalog_run_authorizations (
              authorization_id TEXT PRIMARY KEY,
              team_id TEXT NOT NULL,
              plan_id TEXT NOT NULL,
              batch_scope_json TEXT NOT NULL CHECK (json_valid(batch_scope_json)),
              scope_hash TEXT NOT NULL,
              approved_by TEXT NOT NULL,
              approved_at_ms INTEGER NOT NULL CHECK (approved_at_ms > 0),
              readiness_report_sha256 TEXT NOT NULL,
              record_hash TEXT NOT NULL,
              created_at_ms INTEGER NOT NULL CHECK (created_at_ms > 0),
              UNIQUE (team_id, plan_id, scope_hash, readiness_report_sha256)
            )
            """,
            """
            CREATE INDEX idx_catalog_run_authorizations_lookup
            ON catalog_run_authorizations(
              team_id, plan_id, scope_hash, readiness_report_sha256,
              approved_at_ms DESC, authorization_id
            )
            """,
        ),
    ),
)
