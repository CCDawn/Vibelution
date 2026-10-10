"""Lifecycle-owned serial worker for bounded AI backtest runs."""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.web.services import financial_assistant_service
from core.web.services.financial_backtest import (
    basket_data,
    data,
    engine,
    evaluation,
    portfolio_engine,
)
from core.web.services.financial_backtest.contract import (
    MAX_OUTPUT_TOKENS_PER_DECISION,
    FinancialBacktestConflict,
    FinancialBacktestStoreError,
    sha256_json,
)
from core.web.services.financial_backtest.decision import (
    build_basket_decision_input,
    build_decision_input,
    build_messages,
    infer_decision,
    reserve_decision_call,
)
from core.web.services.financial_backtest.service import (
    _iso,
    _model_fingerprint,
    _now,
    _reserved_for_run,
    _sync_runtime_task,
    _validate_action_binding,
    _validate_fee_binding,
)
from core.web.services.financial_backtest.store import (
    FinancialBacktestStore,
    default_store,
)

_LOGGER = logging.getLogger(__name__)
RUNNER_LEASE_SECONDS = 300.0
LEASE_HEARTBEAT_SECONDS = 20.0
POLL_INTERVAL_SECONDS = 0.5
MAX_RUNS_PER_TICK = 4


class FinancialBacktestWorker:
    """Run one backtest per owner at a time with a durable pre-submit marker."""

    def __init__(
        self,
        *,
        store: FinancialBacktestStore | None = None,
        assistant_loader: Callable[[], list[str]] | None = None,
        decision_runner: Callable[..., dict[str, Any]] | None = None,
        now_provider: Callable[[], datetime] | None = None,
        worker_id: str | None = None,
        max_runs_per_tick: int = MAX_RUNS_PER_TICK,
    ) -> None:
        self._store = store or default_store()
        self._assistant_loader = assistant_loader or _financial_assistant_ids
        self._decision_runner = decision_runner or infer_decision
        self._now_provider = now_provider
        self._worker_id = worker_id or str(uuid4())
        self._max_runs_per_tick = max(1, min(int(max_runs_per_tick), 16))
        self._held_leases: set[tuple[str, str]] = set()

    def process_pending_once(self, *, stop_requested: Callable[[], bool] | None = None) -> int:
        should_stop = stop_requested or (lambda: False)
        processed = 0
        try:
            owners = self._assistant_loader()
        except Exception as exc:  # noqa: BLE001 - one owner registry fault is retried next tick
            _log_worker_error("assistant-scan", exc)
            return 0
        for agent_id in owners:
            if should_stop() or processed >= self._max_runs_per_tick:
                break
            # Plans only coordinate ordinary owned runs. No provider calls occur
            # here: child execution remains fenced by this worker's run lease.
            try:
                from .walk_forward_service import advance_walk_forward_workflows

                advance_walk_forward_workflows(
                    agent_id, store=self._store, now_provider=self._now_provider, limit=1,
                )
            except Exception as exc:  # noqa: BLE001 - one corrupt plan must not starve ordinary runs
                _log_worker_error("walk-forward-advance", exc)
            try:
                candidates = [
                    row
                    for row in self._store.list_runs(agent_id)
                    if str(row.get("status") or "") in {"queued", "running", "stop_requested"}
                ]
            except Exception as exc:  # noqa: BLE001 - isolate owner storage failures
                _log_worker_error("run-scan", exc)
                continue
            candidates.sort(key=lambda row: (str(row.get("createdAt") or ""), str(row.get("runId") or "")))
            if not candidates:
                continue
            run_id = str(candidates[0].get("runId") or "")
            if not run_id:
                continue
            now = _now(self._now_provider)
            try:
                acquired = self._store.acquire_runner_lease(
                    agent_id,
                    run_id=run_id,
                    worker_id=self._worker_id,
                    now_epoch=now.timestamp(),
                    lease_seconds=RUNNER_LEASE_SECONDS,
                )
            except Exception as exc:  # noqa: BLE001 - retry on next tick
                _log_worker_error("runner-lease", exc)
                continue
            if not acquired:
                continue
            self._held_leases.add((agent_id, run_id))
            processed += 1
            try:
                self._process_run(agent_id, run_id, should_stop=should_stop)
            except Exception as exc:  # noqa: BLE001 - quarantine unexpected state, never retry unknown calls
                _log_worker_error("run-process", exc)
                self._fail_known_state(agent_id, run_id, type(exc).__name__, cause=exc)
            try:
                latest = self._store.load_run(agent_id, run_id)
            except Exception:  # noqa: BLE001 - unreadable state retains its lease until expiry
                latest = {}
            if str(latest.get("status") or "") not in {"queued", "running", "stop_requested"}:
                self._release_lease(agent_id, run_id)
        return processed

    def run_forever(self, *, stop_requested: Callable[[], bool]) -> None:
        try:
            while not stop_requested():
                try:
                    self.process_pending_once(stop_requested=stop_requested)
                except Exception as exc:  # noqa: BLE001 - keep the lifecycle owner alive
                    _log_worker_error("worker-tick", exc)
                remaining = POLL_INTERVAL_SECONDS
                while remaining > 0 and not stop_requested():
                    wait = min(0.05, remaining)
                    time.sleep(wait)
                    remaining -= wait
        finally:
            for agent_id, run_id in tuple(self._held_leases):
                self._release_lease(agent_id, run_id)

    def _process_run(self, agent_id: str, run_id: str, *, should_stop: Callable[[], bool]) -> None:
        run = self._store.load_run(agent_id, run_id)
        _sync_runtime_task(agent_id, run, str(run.get("status") or ""), rearm=str(run.get("status") or "") == "queued")
        submission = run.get("decisionSubmission")
        if isinstance(submission, Mapping) and str(submission.get("status") or "") == "submitting":
            self._mark_unknown(
                agent_id,
                run_id,
                str(submission.get("date") or ""),
                "worker_recovered_after_submit",
                expected_attempt_id=str(submission.get("attemptId") or ""),
            )
            return
        status = str(run.get("status") or "")
        if status == "stop_requested":
            self._mark_stopped(agent_id, run_id, "用户停止了回测")
            return
        if status not in {"queued", "running"}:
            return
        try:
            _validate_fee_binding(run)
        except FinancialBacktestStoreError:
            self._mark_blocked(
                agent_id,
                run_id,
                "fee_policy_mismatch",
                "冻结费用模型或审计已变化，回测已阻断",
            )
            return
        self._validate_frozen_model(agent_id, run)
        self._commit_legacy_unknown_reservation(agent_id, run_id, run)
        run = self._store.load_run(agent_id, run_id)
        if str(run.get("status") or "") not in {"queued", "running"}:
            return
        latest_submission = run.get("decisionSubmission")
        if isinstance(latest_submission, Mapping) and str(latest_submission.get("status") or "") == "submitting":
            return
        snapshot = _restore_snapshot(self._store.load_snapshot(agent_id, str(run.get("dataHash") or "")))
        _validate_action_binding(snapshot, run)
        is_basket = isinstance(snapshot, basket_data.BasketSnapshot)
        params = dict(run.get("params") or {})
        schedule = tuple(str(item) for item in run.get("decisionSchedule", []))
        research_snapshot = _load_research_snapshot_for_run(
            self._store,
            agent_id,
            run,
            snapshot,
            schedule,
        )
        decisions = [dict(item) for item in run.get("decisions", []) if isinstance(item, Mapping)]
        by_date = {str(item.get("date") or ""): item for item in decisions}
        if run.get("resumeUnknownDecisionDate"):
            decision_date = str(run.get("resumeUnknownDecisionDate") or "")
            if decision_date not in schedule or decision_date in by_date:
                self._mark_failed(agent_id, run_id, "resume_schedule_mismatch", "回测恢复点与决策计划不一致")
                return
        else:
            decision_date = next((item for item in schedule if item not in by_date), "")

        while decision_date:
            if should_stop():
                return
            run = self._store.load_run(agent_id, run_id)
            status = str(run.get("status") or "")
            if status == "stop_requested":
                self._mark_stopped(agent_id, run_id, "用户停止了回测")
                return
            if status not in {"queued", "running"}:
                return
            decisions = [dict(item) for item in run.get("decisions", []) if isinstance(item, Mapping)]
            previous: list[dict[str, Any]] = []
            for item in decisions:
                if str(item.get("date") or "") >= decision_date:
                    continue
                prior = {"date": item["date"], "reason": item["reason"]}
                if is_basket:
                    prior["targetWeights"] = {
                        str(symbol): float(weight) / 100.0
                        for symbol, weight in (item.get("targetWeights") or {}).items()
                    }
                else:
                    prior["targetWeight"] = float(item["targetWeight"]) / 100.0
                if item.get("confidence") is not None:
                    prior["confidence"] = item["confidence"]
                previous.append(prior)
            if is_basket:
                portfolio = portfolio_engine.portfolio_at(snapshot, params, previous, decision_date)
                if research_snapshot is not None:
                    from core.web.services.financial_backtest.research_inputs import (
                        decision_research_material,
                    )

                    research_material = decision_research_material(
                        research_snapshot,
                        symbols=list(snapshot.symbols),
                        decision_date=decision_date,
                    )
                    decision_input = build_basket_decision_input(
                        snapshot,
                        params,
                        as_of_date=decision_date,
                        portfolio=portfolio,
                        research_material=research_material,
                    )
                else:
                    decision_input = build_basket_decision_input(
                        snapshot, params, as_of_date=decision_date, portfolio=portfolio
                    )
            else:
                portfolio = engine.portfolio_at(snapshot, params, previous, decision_date)
                if research_snapshot is not None:
                    from core.web.services.financial_backtest.research_inputs import (
                        decision_research_material,
                    )

                    research_material = decision_research_material(
                        research_snapshot,
                        symbols=[snapshot.symbol],
                        decision_date=decision_date,
                    )
                    decision_input = build_decision_input(
                        snapshot,
                        params,
                        as_of_date=decision_date,
                        portfolio=portfolio,
                        research_material=research_material,
                    )
                else:
                    decision_input = build_decision_input(
                        snapshot, params, as_of_date=decision_date, portfolio=portfolio
                    )
            input_hash = sha256_json(decision_input)
            reserved_call_tokens = reserve_decision_call(build_messages(decision_input))
            plan = run.get("reservationPlan") if isinstance(run.get("reservationPlan"), Mapping) else {}
            frozen_reservation = max(0, int(plan.get(decision_date) or 0))
            if not frozen_reservation or reserved_call_tokens > frozen_reservation:
                self._mark_blocked(agent_id, run_id, "token_reservation_changed", "当前请求超过预览阶段冻结的预算预留，请重新预览")
                return
            committed = max(0, int(run.get("budgetTokensCommitted") or 0))
            if committed + frozen_reservation > max(0, int(run.get("maxTokens") or 0)):
                self._mark_blocked(agent_id, run_id, "token_budget_exhausted", "剩余token预算不足以安全提交下一次模型调用")
                return
            # Re-check the frozen route for every decision in a long-running job.
            self._validate_frozen_model(agent_id, run)
            previous_submission = run.get("decisionSubmission") if isinstance(run.get("decisionSubmission"), Mapping) else {}
            retrying_unknown = str(run.get("resumeUnknownDecisionDate") or "") == decision_date
            attempt = max(1, int(previous_submission.get("attempt") or 0) + (1 if retrying_unknown else 0))
            started = _iso(_now(self._now_provider))
            attempt_id = self._mark_submitting(
                agent_id,
                run_id,
                decision_date=decision_date,
                input_hash=input_hash,
                attempt=attempt,
                estimated_tokens=frozen_reservation,
                started_at=started,
            )
            if not attempt_id:
                latest = self._store.load_run(agent_id, run_id)
                if str(latest.get("status") or "") == "stop_requested":
                    self._mark_stopped(agent_id, run_id, "用户停止了回测")
                return
            # Refresh the owner lease before a potentially long provider call.
            lease_renewed = self._store.acquire_runner_lease(
                agent_id,
                run_id=run_id,
                worker_id=self._worker_id,
                now_epoch=_now(self._now_provider).timestamp(),
                lease_seconds=RUNNER_LEASE_SECONDS,
            )
            if not lease_renewed:
                # Keep the durable submitting marker for the lease owner to
                # quarantine as unknown; a stale worker must never call the model.
                self._release_lease(agent_id, run_id)
                return
            try:
                with self._lease_heartbeat(agent_id, run_id):
                    decision = self._decision_runner(
                        agent_id=agent_id,
                        model_id=str(run.get("modelId") or ""),
                        run_id=run_id,
                        decision_input=decision_input,
                        max_position_pct=float(params.get("maxPositionPct", 100)),
                    )
                if str(decision.get("inputHash") or "") != input_hash:
                    raise ValueError("decision input hash mismatch")
                _validate_decision_result(
                    decision,
                    expected_date=decision_date,
                    model_id=str(run.get("modelId") or ""),
                    is_basket=is_basket,
                    symbols=tuple(snapshot.symbols) if is_basket else (),
                    max_position_pct=float(params.get("maxPositionPct", 100)),
                )
            except Exception as exc:  # noqa: BLE001 - provider outcome/charge can be unknown
                self._mark_unknown(
                    agent_id, run_id, decision_date, _safe_error_code(exc), expected_attempt_id=attempt_id
                )
                return

            accepted = self._accept_decision(agent_id, run_id, decision, attempt=attempt, attempt_id=attempt_id)
            if not accepted:
                return
            run = self._store.load_run(agent_id, run_id)
            if int(run.get("budgetTokensCommitted") or 0) > int(run.get("maxTokens") or 0):
                self._mark_blocked(agent_id, run_id, "token_budget_exceeded", "模型实际token用量超过预览阶段的保守预算预留，后续调用已阻断")
                return
            if str(run.get("status") or "") == "stop_requested":
                self._mark_stopped(agent_id, run_id, "用户停止了回测")
                return
            by_date = {
                str(item.get("date") or ""): item
                for item in run.get("decisions", [])
                if isinstance(item, Mapping)
            }
            decision_date = next((item for item in schedule if item not in by_date), "")
            if not decision_date:
                self._complete_run(agent_id, run_id, snapshot, params)
                return

        self._complete_run(agent_id, run_id, snapshot, params)

    def _commit_legacy_unknown_reservation(self, agent_id: str, run_id: str, run: Mapping[str, Any]) -> None:
        """Account for unknown attempts persisted before reservation fencing existed."""
        decision_date = str(run.get("resumeUnknownDecisionDate") or "")
        submission = run.get("decisionSubmission") if isinstance(run.get("decisionSubmission"), Mapping) else {}
        if (
            not decision_date
            or str(submission.get("status") or "") != "unknown"
            or str(submission.get("date") or "") != decision_date
            or submission.get("budgetReservationCommitted") is True
        ):
            return
        plan = run.get("reservationPlan") if isinstance(run.get("reservationPlan"), Mapping) else {}
        reservation = max(
            0,
            int(submission.get("estimatedTokens") or plan.get(decision_date) or MAX_OUTPUT_TOKENS_PER_DECISION),
        )
        expected_attempt_id = str(submission.get("attemptId") or "")

        def mutate(state: dict[str, Any]) -> None:
            current = state.get("decisionSubmission") if isinstance(state.get("decisionSubmission"), Mapping) else {}
            if (
                str(state.get("resumeUnknownDecisionDate") or "") != decision_date
                or str(current.get("status") or "") != "unknown"
                or str(current.get("date") or "") != decision_date
                or str(current.get("attemptId") or "") != expected_attempt_id
                or current.get("budgetReservationCommitted") is True
            ):
                return False
            current = {**dict(current), "budgetReservationCommitted": True}
            state["decisionSubmission"] = current
            state["budgetTokensCommitted"] = max(0, int(state.get("budgetTokensCommitted") or 0)) + reservation
            state["tokenAccounting"] = "reserved"
            return True

        self._store.update_run(agent_id, run_id, mutate)

    def _validate_frozen_model(self, agent_id: str, run: Mapping[str, Any]) -> None:
        from core.web.services import agent_directory_service as directory
        from core.web.services.financial_backtest.service import (
            _source_run_id,
            _validate_candidate_model,
        )

        run_model_id = str(run.get("modelId") or "").strip()
        derived = bool(_source_run_id(run))
        if derived:
            try:
                _validate_candidate_model(run_model_id)
                fingerprint = _model_fingerprint(run_model_id) if run_model_id else ""
            except Exception:  # noqa: BLE001 - candidate authority failure blocks derived runs
                fingerprint = ""
            if not run_model_id or fingerprint != str(run.get("modelFingerprint") or ""):
                self._mark_blocked(
                    agent_id,
                    str(run.get("runId") or ""),
                    "model_candidate_changed",
                    "派生回测模型候选资格或冻结路由已变化，回测已暂停",
                )
                raise _AlreadySettled()
            return

        agent = directory.get_agent(agent_id)
        selected = str(directory.agent_dialogue_model_id(agent) if isinstance(agent, dict) else "").strip()
        fingerprint = _model_fingerprint(selected) if selected else ""
        if not selected or selected != run_model_id or fingerprint != str(run.get("modelFingerprint") or ""):
            self._mark_blocked(agent_id, str(run.get("runId") or ""), "model_binding_changed", "炒股智能体模型绑定已变化，回测已暂停")
            raise _AlreadySettled()

    def _mark_submitting(self, agent_id: str, run_id: str, **fields: Any) -> str:
        attempt_id = str(uuid4())
        def mutate(run: dict[str, Any]) -> None:
            if str(run.get("status") or "") == "stop_requested":
                return False
            if str(run.get("status") or "") not in {"queued", "running"}:
                return False
            reservation = max(0, int(fields["estimated_tokens"]))
            committed = max(0, int(run.get("budgetTokensCommitted") or 0))
            if committed + reservation > max(0, int(run.get("maxTokens") or 0)):
                run["status"] = "blocked"
                run["errorCode"] = "token_budget_exhausted"
                run["terminalReason"] = "剩余token预算不足以安全提交下一次模型调用"
                run["completedAt"] = _iso(_now(self._now_provider))
                run["currentDecisionDate"] = None
                run["decisionSubmission"] = None
                run["tokensReserved"] = _reserved_for_run(run)
                return False
            run["status"] = "running"
            run["startedAt"] = run.get("startedAt") or _iso(_now(self._now_provider))
            run["currentDecisionDate"] = fields["decision_date"]
            run["callsUsed"] = int(run.get("callsUsed") or 0) + 1
            run["decisionSubmission"] = {
                "status": "submitting",
                "date": fields["decision_date"],
                "inputHash": fields["input_hash"],
                "attempt": fields["attempt"],
                "attemptId": attempt_id,
                "workerId": self._worker_id,
                "estimatedTokens": reservation,
                "budgetReservationCommitted": True,
                "startedAt": fields["started_at"],
            }
            run["budgetTokensCommitted"] = committed + reservation
            run["resumeUnknownDecisionDate"] = None
            run["tokenAccounting"] = "reserved"
            run["tokensReserved"] = _reserved_for_run(run)
            return True
        state, started = self._store.update_run(agent_id, run_id, mutate)
        if not started:
            if str(state.get("status") or "") == "blocked":
                _sync_runtime_task(agent_id, state, "blocked")
            return ""
        _sync_runtime_task(agent_id, state, "running")
        return attempt_id

    def _accept_decision(self, agent_id: str, run_id: str, decision: Mapping[str, Any], *, attempt: int, attempt_id: str) -> bool:
        def mutate(run: dict[str, Any]) -> None:
            submission = run.get("decisionSubmission") if isinstance(run.get("decisionSubmission"), Mapping) else {}
            if (
                str(run.get("status") or "") not in {"running", "stop_requested"}
                or str(submission.get("status") or "") != "submitting"
                or str(submission.get("attemptId") or "") != attempt_id
                or str(submission.get("workerId") or "") != self._worker_id
            ):
                return False
            rows = [dict(item) for item in run.get("decisions", []) if isinstance(item, Mapping)]
            if any(str(item.get("date") or "") == str(decision.get("date") or "") for item in rows):
                raise FinancialBacktestConflict("回测决策日期已经存在，不重复写入")
            public = {
                "date": str(decision["date"]),
                "reason": str(decision["reason"]),
                "modelId": str(decision["modelId"]),
                "inputHash": str(decision["inputHash"]),
                "decisionHash": str(decision["decisionHash"]),
                "attempts": max(1, int(attempt)),
                "tokens": max(0, int(decision.get("tokens") or 0)),
            }
            if isinstance(decision.get("targetWeights"), Mapping):
                public["targetWeights"] = {
                    str(symbol): float(weight)
                    for symbol, weight in decision["targetWeights"].items()
                }
            else:
                public["targetWeight"] = float(decision["targetWeight"])
            if decision.get("confidence") is not None:
                public["confidence"] = float(decision["confidence"])
            rows.append(public)
            rows.sort(key=lambda item: item["date"])
            run["decisions"] = rows
            run["completedDecisionCount"] = len(rows)
            run["progress"] = len(rows) / max(1, int(run.get("decisionCount") or 1))
            run["tokensUsed"] = max(0, int(run.get("tokensUsed") or 0)) + max(0, int(decision.get("tokens") or 0))
            planned = max(0, int((run.get("reservationPlan") or {}).get(str(decision.get("date") or "")) or 0))
            reserved = max(0, int(submission.get("estimatedTokens") or planned))
            reserved_already_committed = submission.get("budgetReservationCommitted") is True
            budget_charge = (
                max(0, int(decision.get("tokens") or 0))
                if decision.get("tokenAccounting") == "measured"
                else reserved
            )
            committed = max(0, int(run.get("budgetTokensCommitted") or 0))
            if reserved_already_committed:
                committed = max(0, committed - reserved)
            run["budgetTokensCommitted"] = committed + budget_charge
            run["tokenAccounting"] = "estimated" if decision.get("tokenAccounting") == "estimated" or run.get("tokenAccounting") == "estimated" else "measured"
            run["decisionSubmission"] = None
            run["currentDecisionDate"] = None
            run["uncertainDecisionDate"] = None
            run["terminalReason"] = None
            run["errorCode"] = None
            run["tokensReserved"] = _reserved_for_run(run)
            return True
        state, accepted = self._store.update_run(agent_id, run_id, mutate)
        if not accepted:
            _record_event(agent_id, run_id, "financial_backtest.decision.late_result_dropped", str(state.get("status") or "unknown"), "attempt_fence")
            return False
        _sync_runtime_task(agent_id, state, str(state.get("status") or "running"))
        return True

    def _mark_unknown(
        self,
        agent_id: str,
        run_id: str,
        decision_date: str,
        error_code: str,
        *,
        expected_attempt_id: str | None = None,
    ) -> None:
        def mutate(run: dict[str, Any]) -> None:
            submission = run.get("decisionSubmission") if isinstance(run.get("decisionSubmission"), Mapping) else {}
            if str(submission.get("status") or "") != "submitting":
                return False
            if expected_attempt_id is not None and str(submission.get("attemptId") or "") != expected_attempt_id:
                return False
            if str(run.get("status") or "") not in {"queued", "running", "stop_requested"}:
                return False
            reservation = max(
                0,
                int(
                    submission.get("estimatedTokens")
                    or (run.get("reservationPlan") or {}).get(decision_date)
                    or MAX_OUTPUT_TOKENS_PER_DECISION
                ),
            )
            if submission.get("budgetReservationCommitted") is not True:
                run["budgetTokensCommitted"] = max(0, int(run.get("budgetTokensCommitted") or 0)) + reservation
                submission = {**dict(submission), "budgetReservationCommitted": True}
            run["status"] = "paused_unknown"
            run["decisionSubmission"] = {**dict(submission), "status": "unknown", "date": decision_date}
            run["decisionSubmission"].pop("workerId", None)
            run["currentDecisionDate"] = decision_date
            run["uncertainDecisionDate"] = decision_date
            run["errorCode"] = str(error_code or "model_result_unknown")[:100]
            run["terminalReason"] = "模型调用结果未能确认。为避免重复计费，已暂停；只有人工明确确认可能重复计费后才能重试。"
            run["tokenAccounting"] = "reserved"
            run["tokensReserved"] = max(MAX_OUTPUT_TOKENS_PER_DECISION, _reserved_for_run(run))
            return True
        state, changed = self._store.update_run(agent_id, run_id, mutate)
        if changed:
            _sync_runtime_task(agent_id, state, "paused_unknown")
            _record_event(agent_id, run_id, "financial_backtest.decision.unknown", "paused_unknown", error_code)

    def _mark_stopped(self, agent_id: str, run_id: str, reason: str) -> None:
        def mutate(run: dict[str, Any]) -> None:
            if str(run.get("status") or "") == "paused_unknown":
                return
            run["status"] = "stopped"
            run["terminalReason"] = reason
            run["completedAt"] = _iso(_now(self._now_provider))
            run["currentDecisionDate"] = None
            run["decisionSubmission"] = None
            run["tokensReserved"] = _reserved_for_run(run)
        state, _ = self._store.update_run(agent_id, run_id, mutate)
        _sync_runtime_task(agent_id, state, str(state.get("status") or "stopped"))

    def _mark_blocked(self, agent_id: str, run_id: str, error_code: str, reason: str) -> None:
        def mutate(run: dict[str, Any]) -> None:
            run["status"] = "blocked"
            run["errorCode"] = error_code[:100]
            run["terminalReason"] = reason[:500]
            run["completedAt"] = _iso(_now(self._now_provider))
            run["currentDecisionDate"] = None
            run["decisionSubmission"] = None
            run["tokensReserved"] = _reserved_for_run(run)
        state, _ = self._store.update_run(agent_id, run_id, mutate)
        _sync_runtime_task(agent_id, state, "blocked")

    def _mark_failed(
        self,
        agent_id: str,
        run_id: str,
        error_code: str,
        reason: str,
        *,
        execution_failure: dict[str, Any] | None = None,
    ) -> None:
        def mutate(run: dict[str, Any]) -> None:
            run["status"] = "failed"
            run["errorCode"] = error_code[:100]
            run["terminalReason"] = reason[:500]
            if execution_failure is not None:
                run["executionFailure"] = execution_failure
            run["completedAt"] = _iso(_now(self._now_provider))
            run["tokensReserved"] = _reserved_for_run(run)

        state, _ = self._store.update_run(agent_id, run_id, mutate)
        _sync_runtime_task(agent_id, state, "failed")

    def _fail_known_state(
        self,
        agent_id: str,
        run_id: str,
        error_code: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        try:
            run = self._store.load_run(agent_id, run_id)
            submission = (
                run.get("decisionSubmission")
                if isinstance(run.get("decisionSubmission"), Mapping)
                else {}
            )
            if str(submission.get("status") or "") == "submitting":
                self._mark_unknown(
                    agent_id,
                    run_id,
                    str(submission.get("date") or ""),
                    "worker_failure_during_submit",
                    expected_attempt_id=str(submission.get("attemptId") or ""),
                )
            elif str(run.get("status") or "") in {
                "queued",
                "running",
                "stop_requested",
            }:
                evidence = None
                if (
                    isinstance(cause, engine.BacktestDecisionError)
                    and cause.metadata.get("failure")
                    == "insufficient_cash_for_dividend_tax"
                ):
                    # Only this locally generated accounting failure is retained; arbitrary
                    # exceptions, provider responses and prompts never enter the artifact.
                    evidence = {
                        key: cause.metadata[key]
                        for key in (
                            "failure",
                            "date",
                            "symbol",
                            "availableCash",
                            "dividendTaxDue",
                            "projectedCashAfterTax",
                            "order",
                            "trade",
                        )
                    }
                self._mark_failed(
                    agent_id,
                    run_id,
                    "insufficient_cash_for_dividend_tax" if evidence else error_code,
                    "卖出后可用现金不足以支付现金分红递延税款，回测已阻断。"
                    if evidence
                    else "回测运行遇到内部错误，未继续发送后续模型调用",
                    execution_failure=evidence,
                )
        except Exception as exc:  # noqa: BLE001 - no secondary failure may cause a retry
            _log_worker_error("failure-quarantine", exc)

    def _complete_run(
        self,
        agent_id: str,
        run_id: str,
        snapshot: data.BacktestSnapshot | basket_data.BasketSnapshot,
        params: Mapping[str, Any],
    ) -> None:
        run = self._store.load_run(agent_id, run_id)
        schedule = tuple(str(item) for item in run.get("decisionSchedule", []))
        rows = [dict(item) for item in run.get("decisions", []) if isinstance(item, Mapping)]
        if {str(item.get("date") or "") for item in rows} != set(schedule):
            self._mark_failed(agent_id, run_id, "decision_plan_incomplete", "完整回测缺少AI决策点，不能计算绩效")
            return
        if isinstance(snapshot, basket_data.BasketSnapshot):
            engine_decisions = [
                {
                    "date": str(item["date"]),
                    "targetWeights": {
                        str(symbol): float(weight) / 100.0
                        for symbol, weight in item["targetWeights"].items()
                    },
                    "reason": str(item["reason"]),
                    **({"confidence": item["confidence"]} if item.get("confidence") is not None else {}),
                    "inputHash": str(item["inputHash"]),
                }
                for item in rows
            ]
            result = portfolio_engine.simulate(snapshot, params, engine_decisions)
        else:
            engine_decisions = [
                {
                    "date": str(item["date"]),
                    "targetWeight": float(item["targetWeight"]) / 100.0,
                    "reason": str(item["reason"]),
                    **({"confidence": item["confidence"]} if item.get("confidence") is not None else {}),
                    "inputHash": str(item["inputHash"]),
                }
                for item in rows
            ]
            result = engine.simulate(snapshot, params, engine_decisions)
        out_of_sample_start = run.get("outOfSampleStartDate") or params.get("outOfSampleStartDate")
        window_evaluation = (
            evaluation.evaluate_windows(
                result["equity"],
                result["orders"],
                initial_cash=float(params["initialCash"]),
                out_of_sample_start_date=str(out_of_sample_start),
            )
            if out_of_sample_start
            else None
        )
        def mutate(state: dict[str, Any]) -> None:
            if str(state.get("status") or "") == "stop_requested":
                # The last requested decision completed; the result is complete and deterministic.
                pass
            state["status"] = "completed"
            state["completedDecisionCount"] = len(rows)
            state["progress"] = 1.0
            state["metrics"] = result["metrics"]
            for key in ("dividendAccounting", "benchmarkDividendAccounting"):
                if key in result:
                    state[key] = result[key]
            state["evaluation"] = window_evaluation
            if out_of_sample_start:
                state["outOfSampleStartDate"] = str(out_of_sample_start)
            state["equity"] = result["equity"]
            state["trades"] = result["trades"]
            state["orders"] = result["orders"]
            state["benchmarkOrders"] = result.get("benchmarkOrders", [])
            state["benchmarkStatus"] = result.get("benchmarkStatus")
            state["unfilledBenchmarkSymbols"] = list(
                result.get("unfilledBenchmarkSymbols") or []
            )
            state["completedAt"] = _iso(_now(self._now_provider))
            state["currentDecisionDate"] = None
            state["decisionSubmission"] = None
            state["terminalReason"] = "回测完成"
            state["errorCode"] = None
            state["tokensReserved"] = 0
        state, _ = self._store.update_run(agent_id, run_id, mutate)
        _sync_runtime_task(agent_id, state, "completed")
        _record_event(agent_id, run_id, "financial_backtest.run.completed", "completed", "")

    def _release_lease(self, agent_id: str, run_id: str) -> None:
        try:
            self._store.release_runner_lease(agent_id, run_id=run_id, worker_id=self._worker_id)
        except Exception as exc:  # noqa: BLE001 - lease expires if cleanup fails
            _log_worker_error("runner-release", exc)
        self._held_leases.discard((agent_id, run_id))

    def _lease_heartbeat(self, agent_id: str, run_id: str):
        worker = self
        class LeaseHeartbeat:
            def __enter__(self):
                self.stop = threading.Event()
                def beat() -> None:
                    while not self.stop.wait(LEASE_HEARTBEAT_SECONDS):
                        try:
                            renewed = worker._store.acquire_runner_lease(
                                agent_id,
                                run_id=run_id,
                                worker_id=worker._worker_id,
                                now_epoch=_now(worker._now_provider).timestamp(),
                                lease_seconds=RUNNER_LEASE_SECONDS,
                            )
                            if not renewed:
                                return
                        except Exception as exc:  # noqa: BLE001 - another worker remains fenced by expiry
                            _log_worker_error("lease-heartbeat", exc)
                self.thread = threading.Thread(target=beat, name="financial-backtest-lease-heartbeat", daemon=True)
                self.thread.start()
                return self
            def __exit__(self, *_args: object) -> None:
                self.stop.set()
                self.thread.join(timeout=1.0)
        return LeaseHeartbeat()


class _AlreadySettled(Exception):
    """Private control flow after model-binding change quarantines a run."""


def run_forever(*, stop_requested: Callable[[], bool]) -> None:
    FinancialBacktestWorker().run_forever(stop_requested=stop_requested)


def _financial_assistant_ids() -> list[str]:
    return [
        str(agent.get("agentId") or "").strip()
        for agent in financial_assistant_service._agents()
        if str(agent.get("status") or "active") == "active"
        and str(agent.get("agentId") or "").strip()
    ]


def _validate_decision_result(
    decision: Mapping[str, Any],
    *,
    expected_date: str,
    model_id: str,
    is_basket: bool,
    symbols: tuple[str, ...],
    max_position_pct: float,
) -> None:
    if not isinstance(decision, Mapping):
        raise TypeError("decision result must be an object")
    if str(decision.get("date") or "") != expected_date:
        raise ValueError("decision date mismatch")
    if str(decision.get("modelId") or "") != model_id:
        raise ValueError("decision model mismatch")
    reason = decision.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 2_000:
        raise ValueError("decision reason is invalid")
    confidence = decision.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise TypeError("decision confidence is invalid")
        if not math.isfinite(float(confidence)) or not 0 <= float(confidence) <= 1:
            raise ValueError("decision confidence is invalid")
    if is_basket:
        weights = decision.get("targetWeights")
        if not isinstance(weights, Mapping) or set(weights) != set(symbols):
            raise ValueError("decision targetWeights do not match the frozen symbols")
        if decision.get("targetWeight") is not None:
            raise ValueError("basket decision has single-symbol targetWeight")
        values: list[float] = []
        for symbol in symbols:
            value = weights[symbol]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"decision target weight is invalid for {symbol}")
            normalized = float(value)
            if not math.isfinite(normalized) or normalized < 0 or normalized > max_position_pct:
                raise ValueError(f"decision target weight is out of range for {symbol}")
            values.append(normalized)
        if sum(values) > 100:
            raise ValueError("decision target weights exceed 100 percent")
        return
    value = decision.get("targetWeight")
    if decision.get("targetWeights") is not None:
        raise ValueError("single-symbol decision has targetWeights")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("decision targetWeight is invalid")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0 or normalized > max_position_pct:
        raise ValueError("decision targetWeight is out of range")


def _restore_snapshot(payload: Mapping[str, Any]) -> data.BacktestSnapshot | basket_data.BasketSnapshot:
    try:
        basket_payload = payload.get("basketSnapshot")
        if basket_payload is not None:
            if not isinstance(basket_payload, Mapping):
                raise TypeError("basketSnapshot must be an object")
            snapshot = basket_data.restore_basket_snapshot(basket_payload)
            if str(payload.get("dataHash") or "") != snapshot.data_hash:
                raise ValueError("basket data hash mismatch")
            return snapshot
        coverage_payload = dict(payload["coverage"])
        coverage_payload["providerWindows"] = tuple(
            coverage_payload.get("providerWindows") or []
        )
        coverage = data.BacktestCoverage(**coverage_payload)
        candles = tuple(
            data.Candle(**dict(item)) for item in payload.get("candles", [])
        )
        warmup = tuple(
            data.Candle(**dict(item)) for item in payload.get("warmupCandles", [])
        )
        snapshot = data.BacktestSnapshot(
            symbol=str(payload["symbol"]),
            start_date=str(payload["startDate"]),
            end_date=str(payload["endDate"]),
            candles=candles,
            warmup_candles=warmup,
            source=str(payload["source"]),
            source_url=str(payload["sourceUrl"]),
            fetched_at=str(payload["fetchedAt"]),
            data_hash=str(payload["dataHash"]),
            coverage=coverage,
            actions_status=str(payload["actionsStatus"]),
            action_dates=tuple(str(item) for item in payload.get("actionDates", [])),
            notice=tuple(str(item) for item in payload.get("notice", [])),
            corporate_actions=payload.get("corporateActions"),
            price_limits=payload.get("priceLimits"),
        )
        validator = getattr(data, "validate_snapshot", None)
        if callable(validator):
            validator(snapshot)
        return snapshot
    except (KeyError, TypeError, ValueError) as exc:
        raise FinancialBacktestConflict("已冻结回测行情快照格式无效") from exc


def _load_research_snapshot_for_run(
    store: FinancialBacktestStore,
    agent_id: str,
    run: Mapping[str, Any],
    snapshot: data.BacktestSnapshot | basket_data.BasketSnapshot,
    schedule: tuple[str, ...],
) -> dict[str, Any] | None:
    """Restore only owner-local frozen research; never fetch during replay."""
    mode = str(run.get("researchInput") or "price_only")
    research_hash = str(run.get("researchHash") or "").strip()
    if mode == "price_only":
        if research_hash:
            raise FinancialBacktestConflict("纯行情回测包含不匹配的公告摘要")
        return None
    if mode not in {"announcements", "financial_reports"} or not research_hash:
        raise FinancialBacktestConflict("回测研究输入或公告快照引用无效")
    if len(research_hash) != 64 or any(
        char not in "0123456789abcdef" for char in research_hash
    ):
        raise FinancialBacktestConflict("回测公告快照摘要无效")
    payload = store.load_research_snapshot(agent_id, research_hash)
    from core.web.services.financial_backtest.research_inputs import (
        validate_research_snapshot,
    )

    symbols = list(snapshot.symbols) if isinstance(snapshot, basket_data.BasketSnapshot) else [snapshot.symbol]
    try:
        return validate_research_snapshot(
            payload,
            expected_hash=research_hash,
            symbols=symbols,
            decision_dates=schedule,
            expected_kind=mode,
        )
    except data.BacktestInputError as exc:
        raise FinancialBacktestConflict("回测公告快照与冻结标的或决策计划不匹配") from exc


def _safe_error_code(exc: Exception) -> str:
    code = str(getattr(exc, "code", "") or "").strip()
    if code and code.replace("_", "").isalnum():
        return code[:100]
    name = type(exc).__name__
    return name[:100] if name.isalnum() else "model_result_unknown"


def _record_event(agent_id: str, run_id: str, event_code: str, status: str, reason: str) -> None:
    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "financial_backtest",
            "run",
            event_code,
            message=event_code,
            outcome=status,
            fields={"agentId": agent_id[:160], "runId": run_id[:160], "status": status[:40], "reason": reason[:100]},
            lifecycle=True,
        )
    except Exception:  # noqa: BLE001 - observability must not affect simulation
        return


def _log_worker_error(stage: str, exc: Exception) -> None:
    _LOGGER.warning("financial backtest worker %s failed (%s)", stage, type(exc).__name__)


__all__ = ["FinancialBacktestWorker", "run_forever"]
