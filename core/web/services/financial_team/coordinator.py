"""Bounded lifecycle-owned coordination for native financial-team turns.

The coordinator stores only identifiers and coordination state. Native Session
turns remain the sole transcript and completion authority.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from core.web.services import runtime_task_registry

from . import runs

TASK_OWNER = "financial_team"
TASK_LABEL = "股票分析团队后台协作"
TASK_ID_PREFIX = "financial-team-"
MAX_COORDINATION_ERROR_CHARS = 500
MAX_RUNS_PER_TICK = 4
MAX_TASK_IDS_SCANNED_PER_TICK = 64
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_RUN_TIMEOUT_SECONDS = 60 * 60

_PRIMARY_ROLES = ("market", "fundamental", "news")
_DEBATE_ROLES = ("bull", "bear")
_ALL_ANALYST_ROLES = (*_PRIMARY_ROLES, *_DEBATE_ROLES)
_TERMINAL_COORDINATION_STATES = frozenset({"blocked", "completed"})


class _NativeTurnTerminalWithoutFinal(ValueError):
    """A native turn settled without the exact final answer required downstream."""


def coordination_task_id(run_id: str) -> str:
    """Stable runtime-task identity for one persisted financial run."""

    normalized = str(run_id or "").strip()
    if not normalized:
        raise ValueError("Financial team coordination requires a run ID")
    return f"{TASK_ID_PREFIX}{normalized}"


class FinancialTeamCoordinator:
    """Advance accepted native turns while the page is absent.

    All side effects are injected at the service boundary so the state machine
    can be exercised with a fake native Session service. Submit failures are
    terminal: the underlying submit methods persist stable submission IDs and
    refuse to resend an ambiguous request.
    """

    def __init__(
        self,
        *,
        store: Any | None = None,
        run_loader: Callable[[str, str], dict[str, Any]] | None = None,
        status_writer: Callable[[str, str, str, str], dict[str, Any]] | None = None,
        final_answer_for_turn: Callable[[str, str], str] | None = None,
        completion_snapshot: Callable[[str, str], dict[str, Any]] | None = None,
        binding_validator: Callable[[str, str], None] | None = None,
        submit_debate: Callable[[str, str], dict[str, Any]] | None = None,
        submit_synthesis: Callable[[str, str], dict[str, Any]] | None = None,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        run_timeout_seconds: float = DEFAULT_RUN_TIMEOUT_SECONDS,
        max_runs_per_tick: int = MAX_RUNS_PER_TICK,
        max_task_ids_scanned_per_tick: int = MAX_TASK_IDS_SCANNED_PER_TICK,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store or runtime_task_registry.default_store()
        self._run_loader = run_loader or runs.get_financial_team_run
        self._status_writer = status_writer or runs.update_financial_team_coordination_status
        self._final_answer_for_turn = final_answer_for_turn or runs._final_answer_for_turn
        self._completion_snapshot = (
            completion_snapshot
            or runs.session_service.get_session_turn_completion_snapshot
        )
        self._binding_validator = (
            binding_validator or runs.require_current_financial_team_run_bindings
        )
        self._submit_debate = submit_debate or runs.submit_financial_team_debate
        self._submit_synthesis = submit_synthesis or runs.submit_financial_team_synthesis
        self._poll_interval_seconds = max(0.05, min(float(poll_interval_seconds), 30.0))
        self._run_timeout_seconds = max(1.0, min(float(run_timeout_seconds), 24 * 60 * 60))
        self._max_runs_per_tick = max(1, min(int(max_runs_per_tick), 16))
        self._max_task_ids_scanned_per_tick = max(
            self._max_runs_per_tick,
            min(int(max_task_ids_scanned_per_tick), 256),
        )
        self._monotonic = monotonic
        self._scan_cursor = 0
        self._lock = threading.Lock()

    def register_after_primary_acceptance(
        self, assistant_agent_id: str, run_id: str
    ) -> bool:
        """Register only after the three user-started primary turns are accepted."""

        try:
            run = self._run_loader(assistant_agent_id, run_id)
            if (
                int(run.get("schemaVersion") or 0) < 2
                or str(run.get("assistantAgentId") or "") != assistant_agent_id
                or str(run.get("runId") or "") != run_id
            ):
                return False
            if any(
                not _turn_id((run.get("analysts") or {}).get(role))
                for role in _PRIMARY_ROLES
            ):
                return False
            if str(run.get("coordinationStatus") or "") in _TERMINAL_COORDINATION_STATES:
                task_id = coordination_task_id(run_id)
                existing = self._store.load_state(task_id)
                if existing and runtime_task_registry.is_active_status(
                    str(existing.get("status") or "")
                ):
                    terminal = str(run.get("coordinationStatus") or "")
                    self._finish_task(task_id, terminal, str(run.get("coordinationError") or ""))
                return False

            task_id = coordination_task_id(run_id)
            existing = self._store.load_state(task_id)
            if existing and runtime_task_registry.is_terminal_status(
                str(existing.get("status") or "")
            ):
                task_status = str(existing.get("status") or "")
                terminal = "completed" if task_status == "completed" else "blocked"
                error = (
                    "后台协作已停止；系统不会自动重新提交，请核对原生会话。"
                    if terminal == "blocked"
                    else ""
                )
                self._status_writer(assistant_agent_id, run_id, terminal, error)
                return False
            if not existing:
                snapshot = runtime_task_registry.new_snapshot(
                    kind=runtime_task_registry.KIND_RESEARCH_TASK,
                    task_id=task_id,
                    status="running",
                    label=TASK_LABEL,
                    backgrounding_disabled=True,
                    branch_generation=0,
                )
                snapshot.update(
                    {
                        "coordinationOwner": TASK_OWNER,
                        "financialTeamAssistantAgentId": assistant_agent_id,
                        "financialTeamRunId": run_id,
                    }
                )
                self._store.register_task(snapshot, branch_generation=0)
            self._status_writer(assistant_agent_id, run_id, "waiting", "")
            return True
        except Exception:  # noqa: BLE001 - preserve accepted primary turns; fail closed
            try:
                self._status_writer(
                    assistant_agent_id,
                    run_id,
                    "blocked",
                    "后台协作任务无法安全登记，已停止自动推进。",
                )
            except Exception:  # noqa: BLE001 - status persistence may be the failure
                pass
            return False

    def process_pending_once(
        self, *, stop_requested: Callable[[], bool] | None = None
    ) -> int:
        """Process a bounded rotating slice of active financial-team tasks."""

        should_stop = stop_requested or (lambda: False)
        if should_stop():
            return 0
        with self._lock:
            active_ids = self._store.active_task_ids()
            if not active_ids:
                self._scan_cursor = 0
                return 0
            start = self._scan_cursor % len(active_ids)
            scanned = 0
            processed = 0
            while (
                scanned < min(len(active_ids), self._max_task_ids_scanned_per_tick)
                and processed < self._max_runs_per_tick
                and not should_stop()
            ):
                task_id = active_ids[(start + scanned) % len(active_ids)]
                scanned += 1
                state = self._store.load_state(task_id)
                if (
                    not state
                    or str(state.get("coordinationOwner") or "") != TASK_OWNER
                    or str(state.get("kind") or "")
                    != runtime_task_registry.KIND_RESEARCH_TASK
                ):
                    continue
                processed += 1
                self._process_task(state, should_stop=should_stop)
            self._scan_cursor = (start + scanned) % max(len(active_ids), 1)
            return processed

    def run_forever(self, *, stop_requested: Callable[[], bool]) -> None:
        """Run a poll loop that exits promptly when its lifespan owner stops."""

        while not stop_requested():
            self.process_pending_once(stop_requested=stop_requested)
            remaining = self._poll_interval_seconds
            while remaining > 0 and not stop_requested():
                interval = min(0.05, remaining)
                time.sleep(interval)
                remaining -= interval

    def _process_task(
        self,
        state: dict[str, Any],
        *,
        should_stop: Callable[[], bool],
    ) -> None:
        task_id = str(state.get("taskId") or "").strip()
        assistant_agent_id = str(state.get("financialTeamAssistantAgentId") or "").strip()
        run_id = str(state.get("financialTeamRunId") or "").strip()
        if not task_id or not assistant_agent_id or not run_id:
            self._block(state, "后台协作任务标识不完整，已停止自动推进。")
            return
        if str(state.get("stopInitiator") or "") in runtime_task_registry.STOP_INITIATORS:
            self._block(state, "后台协作已停止；系统不会自动重新提交。")
            return
        if self._is_timed_out(state):
            self._block(state, "等待原生分析 Turn 超时，已停止自动推进；不会自动重发。")
            return
        if should_stop():
            return

        try:
            run = self._run_loader(assistant_agent_id, run_id)
            if (
                str(run.get("assistantAgentId") or "") != assistant_agent_id
                or str(run.get("runId") or "") != run_id
            ):
                self._block(state, "金融助手或研究记录归属已变化，已停止自动推进。")
                return
            current_status = str(run.get("coordinationStatus") or "")
            if current_status in _TERMINAL_COORDINATION_STATES:
                self._finish_task(task_id, current_status, str(run.get("coordinationError") or ""))
                return
            if int(run.get("schemaVersion") or 0) < 2:
                self._block(state, "当前研究记录不支持多空协作，已停止自动推进。")
                return
            written = self._status_writer(assistant_agent_id, run_id, "running", "")
            if str((written or {}).get("coordinationStatus") or "") in _TERMINAL_COORDINATION_STATES:
                terminal = str(written.get("coordinationStatus") or "")
                self._finish_task(task_id, terminal, str(written.get("coordinationError") or ""))
                return
            if should_stop():
                return

            analysts = run.get("analysts") if isinstance(run.get("analysts"), dict) else {}
            synthesis_ref = run.get("synthesis") if isinstance(run.get("synthesis"), dict) else {}
            synthesis_turn_id = _turn_id(synthesis_ref)
            if synthesis_turn_id:
                for role in _ALL_ANALYST_ROLES:
                    ref = analysts.get(role)
                    if not _turn_id(ref):
                        self._block(state, "协作阶段缺少已保存的原生 Turn 关联，已停止自动推进。")
                        return
                    if not self._read_final(ref, role=role):
                        return
                if not self._read_final(synthesis_ref, role="synthesis"):
                    return
                if not self._validate_current_bindings(state, assistant_agent_id, run_id):
                    return
                self._complete(state)
                return

            for role in _PRIMARY_ROLES:
                ref = analysts.get(role)
                if not _turn_id(ref):
                    self._block(state, "基础分析 Turn 关联不完整，已停止自动推进。")
                    return
                if not self._read_final(ref, role=role):
                    return

            missing_debate_turns = [
                role for role in _DEBATE_ROLES if not _turn_id(analysts.get(role))
            ]
            if missing_debate_turns:
                if should_stop() or self._stop_requested(task_id, state):
                    return
                try:
                    self._submit_debate(assistant_agent_id, run_id)
                except Exception:  # noqa: BLE001 - accepted/unknown never auto-retried
                    self._block(
                        state,
                        "多空阶段提交失败或结果未知，已停止自动推进；系统不会自动重发。",
                    )
                    return
                updated = self._run_loader(assistant_agent_id, run_id)
                updated_analysts = (
                    updated.get("analysts")
                    if isinstance(updated.get("analysts"), dict)
                    else {}
                )
                if any(not _turn_id(updated_analysts.get(role)) for role in _DEBATE_ROLES):
                    self._block(
                        state,
                        "多空阶段没有返回完整的原生 Turn 关联，已停止自动推进。",
                    )
                return

            for role in _DEBATE_ROLES:
                if not self._read_final(analysts[role], role=role):
                    return

            if should_stop() or self._stop_requested(task_id, state):
                return
            if not self._validate_current_bindings(state, assistant_agent_id, run_id):
                return
            try:
                self._submit_synthesis(assistant_agent_id, run_id)
            except Exception:  # noqa: BLE001 - accepted/unknown never auto-retried
                self._block(
                    state,
                    "汇总阶段提交失败或结果未知，已停止自动推进；系统不会自动重发。",
                )
                return
            updated = self._run_loader(assistant_agent_id, run_id)
            updated_synthesis = (
                updated.get("synthesis")
                if isinstance(updated.get("synthesis"), dict)
                else {}
            )
            if not _turn_id(updated_synthesis):
                self._block(
                    state,
                    "汇总阶段没有返回准确的原生 Turn 关联，已停止自动推进。",
                )
        except _NativeTurnTerminalWithoutFinal as exc:
            self._block(state, str(exc))
        except Exception:  # noqa: BLE001 - reads and identity checks fail closed
            self._block(state, "无法核验金融团队原生 Turn 状态，已停止自动推进。")

    def _read_final(self, ref: Any, *, role: str) -> bool:
        if not isinstance(ref, dict):
            raise ValueError("Native turn reference is unavailable")
        session_id = str(ref.get("sessionId") or "").strip()
        turn_id = _turn_id(ref)
        if not session_id or not turn_id:
            raise ValueError("Native turn identity is incomplete")
        if str(self._final_answer_for_turn(session_id, turn_id) or "").strip():
            return True

        snapshot = self._completion_snapshot(session_id, turn_id)
        if not isinstance(snapshot, dict):
            raise ValueError("Native turn completion snapshot is unavailable")
        if (
            str(snapshot.get("sessionId") or "").strip() != session_id
            or str(snapshot.get("turnId") or "").strip() != turn_id
        ):
            raise ValueError("Native turn completion snapshot identity does not match")
        if not bool(snapshot.get("terminal")):
            return False

        terminal_status = str(snapshot.get("terminalStatus") or "").strip().lower()
        label = (
            "主助手汇总"
            if role == "synthesis"
            else str(runs.ROLE_SPECS.get(role, {}).get("label") or "研究")
        )
        if terminal_status in {
            "failed",
            "failed_provider",
            "failed_runtime",
            "paused_limit",
            "needs_continue",
            "superseded",
        }:
            outcome = "失败"
        elif terminal_status in {"stopped", "stopped_by_user", "cancelled"}:
            outcome = "已停止"
        else:
            outcome = "缺少最终回答"
        raise _NativeTurnTerminalWithoutFinal(
            f"{label}{outcome}，后续研究已暂停。"
        )

    def _validate_current_bindings(
        self, state: dict[str, Any], assistant_agent_id: str, run_id: str
    ) -> bool:
        try:
            self._binding_validator(assistant_agent_id, run_id)
            return True
        except runs.FinancialTeamRunConflictError as exc:
            self._block(state, f"{exc}；已停止自动推进。")
        except Exception:  # noqa: BLE001 - identity checks fail closed
            self._block(state, "金融团队角色身份、权限或原生会话已变化，已停止自动推进。")
        return False

    def _is_timed_out(self, state: dict[str, Any]) -> bool:
        raw = str(state.get("createdAt") or state.get("startedAt") or "").strip()
        if not raw:
            return True
        try:
            created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return True
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds()
        return age_seconds >= self._run_timeout_seconds

    def _stop_requested(self, task_id: str, fallback: dict[str, Any]) -> bool:
        latest = self._store.load_state(task_id) or fallback
        if str(latest.get("stopInitiator") or "") in runtime_task_registry.STOP_INITIATORS:
            self._block(latest, "后台协作已停止；系统不会自动重新提交。")
            return True
        return False

    def _block(self, state: dict[str, Any], error: str) -> None:
        assistant_agent_id = str(state.get("financialTeamAssistantAgentId") or "").strip()
        run_id = str(state.get("financialTeamRunId") or "").strip()
        task_id = str(state.get("taskId") or "").strip()
        bounded_error = str(error or "协作已停止自动推进。")[:MAX_COORDINATION_ERROR_CHARS]
        if assistant_agent_id and run_id:
            try:
                self._status_writer(assistant_agent_id, run_id, "blocked", bounded_error)
            except Exception:  # noqa: BLE001 - the task ledger remains a fallback record
                pass
        if task_id:
            self._finish_task(task_id, "blocked", bounded_error)

    def _complete(self, state: dict[str, Any]) -> None:
        assistant_agent_id = str(state.get("financialTeamAssistantAgentId") or "").strip()
        run_id = str(state.get("financialTeamRunId") or "").strip()
        task_id = str(state.get("taskId") or "").strip()
        if assistant_agent_id and run_id:
            try:
                self._status_writer(assistant_agent_id, run_id, "completed", "")
            except Exception:  # noqa: BLE001 - do not falsify completion in the task ledger
                self._block(state, "已提交汇总 Turn，但协调状态无法持久化；请核对原生会话。")
                return
        if task_id:
            self._finish_task(task_id, "completed", "")

    def _finish_task(self, task_id: str, status: str, summary: str) -> None:
        terminal = "completed" if status == "completed" else "blocked"
        try:
            self._store.mark_task_terminal(
                task_id,
                status=terminal,
                reason=str(summary or "")[:MAX_COORDINATION_ERROR_CHARS],
            )
            if summary:
                self._store.update_task(
                    task_id,
                    lambda snapshot: {
                        **snapshot,
                        "resultSummary": str(summary)[:MAX_COORDINATION_ERROR_CHARS],
                    },
                )
        except Exception:  # noqa: BLE001 - bounded coordinator must not crash its owner
            return


def _turn_id(ref: Any) -> str:
    return str(ref.get("turnId") or "").strip() if isinstance(ref, dict) else ""


def run_forever(*, stop_requested: Callable[[], bool]) -> None:
    """StartupJobGroup entry point for the financial-team router lifespan."""

    FinancialTeamCoordinator().run_forever(stop_requested=stop_requested)


def register_after_primary_acceptance(assistant_agent_id: str, run_id: str) -> dict[str, Any]:
    """Best-effort activation from an explicit primary-role submit request."""

    coordinator = FinancialTeamCoordinator()
    coordinator.register_after_primary_acceptance(assistant_agent_id, run_id)
    return runs.get_financial_team_run(assistant_agent_id, run_id)
