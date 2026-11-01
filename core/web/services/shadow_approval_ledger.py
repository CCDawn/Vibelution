"""SQLite shadow-approval ledger (批四 Lane S, observe-only).

影子审批台账：为每个进入审批判定点的工具调用记录一行「四假设终态 + 真实
终态」，供聚合只读端点回答「关掉某个假设对象会多出多少 pending」。纯观察：
台账的任何失败都绝不影响真实审批链（observe never-raise），也绝不进入额度、
计数、预算或 humanAttention 车道。

独立新库，形制借 ``personal_assistant_dispatch_ledger``（STRICT 表 + CHECK、
``user_version`` 迁移、每次变更一个 ``BEGIN IMMEDIATE``、忙超时梯度、读信任
前一次性 ``quick_check``、行数上限截断），不改它的 schema。单写者纪律：每次
变更在按操作新开的连接上提交，不持有跨调用的句柄。重复记录幂等：
``INSERT ... ON CONFLICT DO UPDATE`` 以真实终态回填合并。

真实终态回填机制：``authorize_or_wait`` 是同步调用——决议（接受/拒绝）与
超时/取消都发生在挂载点这一次调用内部，真实 outcome code 在调用返回那一刻
即已权威可得。因此回填在挂载点「调用返回后、同一调用栈内」完成（一条
upsert 同时落四假设与真实终态），不需要额外的 turn 级对账任务：等待中进程
崩溃的调用本就没有真实终态，行缺失即诚实信号；额外的对账 pass 只会引入
I/O 与陈旧窗口，零覆盖增益。
"""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
import time
from typing import Any, Mapping

from core.logging import debug as _debug_logger

from core.authorization.shadow_approval_evaluator import (
    HYPOTHESIS_NO_ACTION_WINDOW,
    HYPOTHESIS_NO_EXTERNAL_WRITE_OVERRIDE,
    HYPOTHESIS_NO_PA_MESSAGE_OVERRIDE,
    PA_MESSAGE_OVERRIDE_TOOL,
    SHADOW_OUTCOMES,
    shadow_approval_telemetry,
    shadow_approvals_enabled,
)


LEDGER_DIR_NAME = "shadow_approval_ledger"
LEDGER_FILENAME = "shadow_approvals.sqlite3"
SCHEMA_VERSION = 1

# 台账行数上限：超出即按写入时间截断最旧行。影子观察是滚动诊断面，不是
# 权威存储；5000 行足够聚合端点的窗口统计并封死无界增长。
MAX_LEDGER_ROWS = 5000
# 聚合读取窗口与样本数上限（只读、有界）。
SUMMARY_WINDOW_ROWS = 1000
SUMMARY_SAMPLE_SIZE = 5

_BUSY_TIMEOUT_STEPS_MS = (250, 1000, 2000)

_HYPOTHESIS_OUTCOME_COLUMNS = {
    HYPOTHESIS_NO_PA_MESSAGE_OVERRIDE: "hyp_no_pa_message_override",
    HYPOTHESIS_NO_EXTERNAL_WRITE_OVERRIDE: "hyp_no_external_write_override",
    HYPOTHESIS_NO_ACTION_WINDOW: "hyp_no_action_window",
}
_HYPOTHESIS_LABELS = {
    HYPOTHESIS_NO_PA_MESSAGE_OVERRIDE: f"关闭 {PA_MESSAGE_OVERRIDE_TOOL} 派发免批豁免",
    HYPOTHESIS_NO_EXTERNAL_WRITE_OVERRIDE: "关闭外部代理写工具 always 覆盖",
    HYPOTHESIS_NO_ACTION_WINDOW: "关闭助理低风险 manage action 窗口",
}

# 真实 outcome code → 真实终态分类（挂载点回填口径）。
_REAL_CATEGORY_BY_CODE = {
    "approval_not_required": "auto_approved",
    "full_access_auto_approved": "auto_approved",
    "approved_for_action_window": "auto_approved",
    "approved_for_session": "auto_approved",
    "approved_for_agent": "auto_approved",
    "auto_approved": "auto_approved",
    "approved": "human_approved",
    "approval_declined": "declined",
    "approval_timeout": "timeout",
    "approval_cancelled": "cancelled",
}
_REAL_OUTCOME_CATEGORIES = ("", "auto_approved", "human_approved", "declined", "timeout", "cancelled")


_META_SQL = """CREATE TABLE ledger_meta (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    quick_check_at TEXT NOT NULL DEFAULT ''
) STRICT"""
_SHADOW_APPROVALS_SQL = """CREATE TABLE shadow_approvals (
    agent_id TEXT NOT NULL,
    turn_id TEXT NOT NULL DEFAULT '',
    call_id TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    tool_name TEXT NOT NULL,
    risk TEXT NOT NULL DEFAULT '',
    permission_preset TEXT NOT NULL DEFAULT '',
    approval_baseline TEXT NOT NULL DEFAULT '',
    approval_descriptor TEXT NOT NULL DEFAULT '',
    baseline_outcome TEXT NOT NULL CHECK(baseline_outcome IN
        ('approved_auto','approved_for_session','needs_human')),
    baseline_rule_id TEXT NOT NULL DEFAULT '',
    hyp_no_pa_message_override TEXT NOT NULL CHECK(hyp_no_pa_message_override IN
        ('approved_auto','approved_for_session','needs_human')),
    hyp_no_pa_message_override_rule_id TEXT NOT NULL DEFAULT '',
    hyp_no_external_write_override TEXT NOT NULL CHECK(hyp_no_external_write_override IN
        ('approved_auto','approved_for_session','needs_human')),
    hyp_no_external_write_override_rule_id TEXT NOT NULL DEFAULT '',
    hyp_no_action_window TEXT NOT NULL CHECK(hyp_no_action_window IN
        ('approved_auto','approved_for_session','needs_human')),
    hyp_no_action_window_rule_id TEXT NOT NULL DEFAULT '',
    real_outcome TEXT NOT NULL DEFAULT '',
    real_outcome_category TEXT NOT NULL DEFAULT '' CHECK(real_outcome_category IN
        ('','auto_approved','human_approved','declined','timeout','cancelled')),
    baseline_replica_agrees INTEGER NOT NULL CHECK(baseline_replica_agrees IN (0,1)),
    created_at TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL CHECK(created_at_ms >= 0),
    PRIMARY KEY (agent_id, turn_id, call_id)
) STRICT"""
_INDEX_SQL = (
    """CREATE INDEX idx_shadow_approvals_window
       ON shadow_approvals(created_at_ms DESC, agent_id, turn_id)""",
)


class ShadowApprovalLedgerUnavailableError(Exception):
    """The ledger cannot be opened/migrated; callers degrade to empty views."""


def ledger_database_path():
    """Workspace-routed ledger path (same routing as every workspace file)."""

    from core.web.services import agent_directory_service as directory

    return directory._workspace_path(
        LEDGER_DIR_NAME, LEDGER_FILENAME, intent="state", seed=False
    )


def _connect(path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=0.05, isolation_level=None)
    connection.execute("PRAGMA journal_mode=PERSIST")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute("PRAGMA trusted_schema=OFF")
    return connection


def _migrate(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise ShadowApprovalLedgerUnavailableError("shadow_approval_ledger_schema_ahead")
    connection.execute("BEGIN IMMEDIATE")
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
            )
        }
        if version == 0:
            if names:
                # A non-empty v0 database is a foreign or corrupted file.
                raise ShadowApprovalLedgerUnavailableError("shadow_approval_ledger_schema_invalid")
            connection.execute(_META_SQL)
            connection.execute(_SHADOW_APPROVALS_SQL)
            for statement in _INDEX_SQL:
                connection.execute(statement)
            connection.execute("INSERT INTO ledger_meta(singleton) VALUES (1)")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        elif version == SCHEMA_VERSION:
            if not {"ledger_meta", "shadow_approvals"}.issubset(names):
                raise ShadowApprovalLedgerUnavailableError("shadow_approval_ledger_schema_invalid")
        else:
            raise ShadowApprovalLedgerUnavailableError("shadow_approval_ledger_schema_invalid")
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def _open_writable() -> sqlite3.Connection:
    """Open with a busy-timeout gradient; each step re-opens on a fresh
    connection (retrying beats spinning inside one contended handle)."""

    path = ledger_database_path()
    last_error: Exception | None = None
    for step, timeout_ms in enumerate(_BUSY_TIMEOUT_STEPS_MS):
        try:
            connection = _connect(path)
            connection.execute(f"PRAGMA busy_timeout={timeout_ms}")
            _migrate(connection)
            return connection
        except sqlite3.OperationalError as exc:
            last_error = exc
            time.sleep(0.02 * (step + 1))
    raise ShadowApprovalLedgerUnavailableError(f"shadow_approval_ledger_busy ({type(last_error).__name__})")


def _open_readable() -> sqlite3.Connection:
    """Open for reads; the ledger becomes trusted only after one quick_check.

    一次性完整性门：meta 标记为空时先跑 ``PRAGMA quick_check`` 并落标记
    （与 pa_dispatch_ledger 同形制）；之后每次读 O(1) 直进。标记前检查失败
    或库缺失一律抛不可用错误，由读取方降级为空视图。
    """

    path = ledger_database_path()
    if not path.exists():
        raise ShadowApprovalLedgerUnavailableError("shadow_approval_ledger_missing")
    connection = _connect(path)
    try:
        connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_STEPS_MS[-1]}")
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != SCHEMA_VERSION:
            raise ShadowApprovalLedgerUnavailableError("shadow_approval_ledger_schema_invalid")
        marker = connection.execute(
            "SELECT quick_check_at FROM ledger_meta WHERE singleton=1"
        ).fetchone()
        if marker and not str(marker[0] or "").strip():
            connection.execute("BEGIN IMMEDIATE")
            try:
                if list(connection.execute("PRAGMA quick_check")) != [("ok",)]:
                    raise ShadowApprovalLedgerUnavailableError("shadow_approval_ledger_integrity_failed")
                connection.execute(
                    "UPDATE ledger_meta SET quick_check_at=? WHERE singleton=1",
                    (_utc_now(),),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return connection
    except Exception:
        connection.close()
        raise


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _iso_to_ms(value: str) -> int:
    raw = str(value or "").strip()
    if not raw:
        return 0
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, int(parsed.timestamp() * 1000))


# ---------------------------------------------------------------------------
# Recording (write-side observer; never raises; real-outcome backfill merge)
# ---------------------------------------------------------------------------


def _record_row(connection: sqlite3.Connection, record: Mapping[str, Any], created_at: str, now_ms: int) -> None:
    agent_id = str(record.get("agentId") or "").strip()
    turn_id = str(record.get("turnId") or "").strip()
    call_id = str(record.get("callId") or "").strip()
    if not agent_id or not call_id:
        return
    real_outcome = str(record.get("realOutcome") or "").strip()
    row = (
        agent_id,
        turn_id,
        call_id,
        str(record.get("sessionId") or "").strip(),
        str(record.get("toolName") or "").strip(),
        str(record.get("risk") or "").strip(),
        str(record.get("permissionPreset") or "").strip(),
        str(record.get("approvalBaseline") or "").strip(),
        str(record.get("approvalDescriptor") or "").strip(),
        str(record.get("baselineOutcome") or "").strip(),
        str(record.get("baselineRuleId") or "").strip(),
        str(record.get("hypNoPaMessageOverride") or "").strip(),
        str(record.get("hypNoPaMessageOverrideRuleId") or "").strip(),
        str(record.get("hypNoExternalWriteOverride") or "").strip(),
        str(record.get("hypNoExternalWriteOverrideRuleId") or "").strip(),
        str(record.get("hypNoActionWindow") or "").strip(),
        str(record.get("hypNoActionWindowRuleId") or "").strip(),
        real_outcome,
        _REAL_CATEGORY_BY_CODE.get(real_outcome, ""),
        1 if record.get("baselineReplicaAgrees") else 0,
        created_at,
        now_ms,
    )
    if not set(row[9:17:2]).issubset(SHADOW_OUTCOMES):
        raise ShadowApprovalLedgerUnavailableError("shadow_approval_outcome_invalid")
    connection.execute(
        """INSERT INTO shadow_approvals (
               agent_id, turn_id, call_id, session_id, tool_name, risk,
               permission_preset, approval_baseline, approval_descriptor,
               baseline_outcome, baseline_rule_id,
               hyp_no_pa_message_override, hyp_no_pa_message_override_rule_id,
               hyp_no_external_write_override, hyp_no_external_write_override_rule_id,
               hyp_no_action_window, hyp_no_action_window_rule_id,
               real_outcome, real_outcome_category, baseline_replica_agrees,
               created_at, created_at_ms
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(agent_id, turn_id, call_id) DO UPDATE SET
               session_id=excluded.session_id,
               tool_name=excluded.tool_name,
               risk=excluded.risk,
               permission_preset=excluded.permission_preset,
               approval_baseline=excluded.approval_baseline,
               approval_descriptor=excluded.approval_descriptor,
               baseline_outcome=excluded.baseline_outcome,
               baseline_rule_id=excluded.baseline_rule_id,
               hyp_no_pa_message_override=excluded.hyp_no_pa_message_override,
               hyp_no_pa_message_override_rule_id=excluded.hyp_no_pa_message_override_rule_id,
               hyp_no_external_write_override=excluded.hyp_no_external_write_override,
               hyp_no_external_write_override_rule_id=excluded.hyp_no_external_write_override_rule_id,
               hyp_no_action_window=excluded.hyp_no_action_window,
               hyp_no_action_window_rule_id=excluded.hyp_no_action_window_rule_id,
               real_outcome=excluded.real_outcome,
               real_outcome_category=excluded.real_outcome_category,
               baseline_replica_agrees=excluded.baseline_replica_agrees,
               created_at=excluded.created_at,
               created_at_ms=excluded.created_at_ms
        """,
        row,
    )
    _truncate_locked(connection)


def _truncate_locked(connection: sqlite3.Connection) -> None:
    count = int(connection.execute("SELECT COUNT(*) FROM shadow_approvals").fetchone()[0])
    overflow = count - MAX_LEDGER_ROWS
    if overflow <= 0:
        return
    connection.execute(
        """DELETE FROM shadow_approvals WHERE (agent_id, turn_id, call_id) IN (
               SELECT agent_id, turn_id, call_id FROM shadow_approvals
               ORDER BY created_at_ms ASC, created_at ASC, agent_id ASC, turn_id ASC, call_id ASC
               LIMIT ?
           )""",
        (overflow,),
    )


def record_shadow_approval(record: Mapping[str, Any]) -> None:
    """Record one shadow approval row (hypotheses + real outcome backfill).

    Never raises: a ledger failure must never reach the real approval chain.
    幂等：同一 (agent, turn, call) 重复记录以最新一行合并（真实终态回填）。
    """

    try:
        if not isinstance(record, Mapping):
            return
        now = _utc_now()
        connection = _open_writable()
        try:
            connection.execute("BEGIN IMMEDIATE")
            _record_row(connection, record, now, _iso_to_ms(now))
            connection.execute("COMMIT")
        finally:
            connection.close()
    except Exception as exc:
        from core.authorization.shadow_approval_evaluator import bump_shadow_telemetry

        bump_shadow_telemetry(ledger_write_failures=1)
        _debug_logger.warning(
            f"Shadow approval ledger record failed silently. error={type(exc).__name__}"
        )


# ---------------------------------------------------------------------------
# Read-only aggregation (summary endpoint surface; empty view on any failure)
# ---------------------------------------------------------------------------


def read_shadow_approval_summary() -> dict[str, Any]:
    """Aggregate per-hypothesis pending deltas and recent samples (read-only).

    永不抛错：任何失败（库缺失/损坏/忙）都降级为空视图。聚合只读：
    SELECT-only，绝不写台账、绝不带任何 action 语义。
    """

    hypotheses: list[dict[str, Any]] = []
    try:
        connection = _open_readable()
        try:
            row_count = int(connection.execute("SELECT COUNT(*) FROM shadow_approvals").fetchone()[0])
            rows = connection.execute(
                """SELECT agent_id, turn_id, call_id, tool_name, risk,
                          permission_preset, approval_baseline, approval_descriptor,
                          baseline_outcome, baseline_rule_id,
                          hyp_no_pa_message_override, hyp_no_pa_message_override_rule_id,
                          hyp_no_external_write_override, hyp_no_external_write_override_rule_id,
                          hyp_no_action_window, hyp_no_action_window_rule_id,
                          real_outcome, real_outcome_category, created_at
                   FROM shadow_approvals
                   ORDER BY created_at_ms DESC, created_at DESC, agent_id DESC
                   LIMIT ?""",
                (SUMMARY_WINDOW_ROWS,),
            ).fetchall()
        finally:
            connection.close()
    except Exception as exc:
        _debug_logger.warning(
            f"Shadow approval ledger summary unavailable. error={type(exc).__name__}"
        )
        return {
            "enabled": shadow_approvals_enabled(),
            "rowCount": 0,
            "hypotheses": [],
            "degraded": True,
        }
    records = [dict(zip(_SUMMARY_ROW_KEYS, row)) for row in rows]
    for key in (
        HYPOTHESIS_NO_PA_MESSAGE_OVERRIDE,
        HYPOTHESIS_NO_EXTERNAL_WRITE_OVERRIDE,
        HYPOTHESIS_NO_ACTION_WINDOW,
    ):
        outcome_column = _HYPOTHESIS_OUTCOME_COLUMNS[key]
        rule_column = f"{outcome_column}_rule_id"
        extra_pending: list[dict[str, Any]] = []
        avoided_pending: list[dict[str, Any]] = []
        for item in records:
            baseline_outcome = str(item.get("baseline_outcome") or "")
            hypothesis_outcome = str(item.get(outcome_column) or "")
            if baseline_outcome == hypothesis_outcome:
                continue
            sample = _sample_projection(item, hypothesis_outcome, str(item.get(rule_column) or ""))
            if baseline_outcome in ("approved_auto", "approved_for_session") and hypothesis_outcome == "needs_human":
                extra_pending.append(sample)
            elif baseline_outcome == "needs_human" and hypothesis_outcome in ("approved_auto", "approved_for_session"):
                avoided_pending.append(sample)
        hypotheses.append(
            {
                "key": key,
                "label": _HYPOTHESIS_LABELS[key],
                "extraPendingCount": len(extra_pending),
                "avoidedPendingCount": len(avoided_pending),
                "recentSamples": {
                    "extraPending": extra_pending[:SUMMARY_SAMPLE_SIZE],
                    "avoidedPending": avoided_pending[:SUMMARY_SAMPLE_SIZE],
                },
            }
        )
    telemetry = shadow_approval_telemetry()
    engaged = int(telemetry.get("engaged", 0))
    return {
        "enabled": shadow_approvals_enabled(),
        "rowCount": row_count,
        "hypotheses": hypotheses,
        "degraded": False,
        "telemetry": {
            **telemetry,
            "failureRateMilli": (
                int(round(1000.0 * int(telemetry.get("ledger_write_failures", 0)) / engaged))
                if engaged > 0
                else 0
            ),
        },
    }


_SUMMARY_ROW_KEYS = (
    "agent_id", "turn_id", "call_id", "tool_name", "risk",
    "permission_preset", "approval_baseline", "approval_descriptor",
    "baseline_outcome", "baseline_rule_id",
    "hyp_no_pa_message_override", "hyp_no_pa_message_override_rule_id",
    "hyp_no_external_write_override", "hyp_no_external_write_override_rule_id",
    "hyp_no_action_window", "hyp_no_action_window_rule_id",
    "real_outcome", "real_outcome_category", "created_at",
)


def _sample_projection(item: dict[str, Any], hypothesis_outcome: str, rule_id: str) -> dict[str, Any]:
    return {
        "toolName": str(item.get("tool_name") or ""),
        "agentId": str(item.get("agent_id") or ""),
        "turnId": str(item.get("turn_id") or ""),
        "baselineOutcome": str(item.get("baseline_outcome") or ""),
        "hypothesisOutcome": hypothesis_outcome,
        "ruleId": rule_id,
        "realOutcome": str(item.get("real_outcome") or ""),
        "createdAt": str(item.get("created_at") or ""),
    }


def reset_shadow_approval_ledger() -> None:
    """Wipe the ledger (tests and explicit invalidation); never raises."""

    try:
        connection = _open_writable()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM shadow_approvals")
            connection.execute("UPDATE ledger_meta SET quick_check_at='' WHERE singleton=1")
            connection.execute("COMMIT")
        finally:
            connection.close()
    except Exception as exc:
        _debug_logger.warning(
            f"Shadow approval ledger reset failed silently. error={type(exc).__name__}"
        )
