from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.web.services import (
    financial_team_service,
    runtime_task_registry,
    session_service,
)
from core.web.services.financial_jobs import contract, runtime, service
from core.web.services.financial_jobs.errors import (
    FinancialJobConflictError,
    FinancialJobValidationError,
)
from core.web.services.financial_jobs.store import FinancialResearchJobStore
from core.web.services.financial_team import runs as financial_runs

BEIJING = ZoneInfo("Asia/Shanghai")
ASSISTANT_ID = "finance-agent-test"


def _store(tmp_path: Path) -> FinancialResearchJobStore:
    return FinancialResearchJobStore(
        path_resolver=lambda owner: tmp_path / f"{owner}-financial-jobs.json"
    )


def _request(*, symbols=None, scheduled_at="2026-10-06T18:00:00+08:00"):
    return {
        "symbols": symbols or ["600000"],
        "periodDays": 30,
        "depth": "standard",
        "execution": {
            "kind": "once",
            "timezone": "Asia/Shanghai",
            "scheduledAt": scheduled_at,
        },
    }


def _schedule(*, kind="daily", time_of_day="18:00", next_run="2026-10-07T18:00:00+08:00"):
    return {
        "enabled": True,
        "execution": {
            "kind": kind,
            "scheduledAt": None,
            "timeOfDay": time_of_day if kind in {"daily", "weekdays"} else None,
            "timezone": "Asia/Shanghai",
        },
        "nextRunAt": next_run,
        "lastOccurrence": None,
    }


def _batch_snapshot(batch_id: str, items: list[dict], *, status="queued"):
    snapshot = runtime_task_registry.new_snapshot(
        kind=runtime_task_registry.KIND_RESEARCH_TASK,
        task_id=runtime.batch_task_id(batch_id),
        status=status,
        label=service.TASK_LABEL,
        backgrounding_disabled=True,
        branch_generation=0,
    )
    snapshot.update(
        {
            "coordinationOwner": service.TASK_OWNER,
            "financialResearchAssistantAgentId": ASSISTANT_ID,
            "financialResearchBatchId": batch_id,
            "financialResearchAttemptCounts": {},
            "financialResearchBatch": {
                "batchId": batch_id,
                "scheduleId": "",
                "assistantAgentId": ASSISTANT_ID,
                "status": "queued",
                "triggeredAt": "2026-10-06T10:00:00+08:00",
                "updatedAt": "2026-10-06T10:00:00+08:00",
                "researchDate": "2026-10-06",
                "periodDays": 30,
                "depth": "standard",
                "symbols": [item["symbol"] for item in items],
                "terminalReason": None,
                "items": items,
            },
        }
    )
    return snapshot


def _item(
    symbol: str,
    *,
    status="queued",
    run_id=None,
    turn_refs=None,
    terminal_reason=None,
):
    return {
        "symbol": symbol,
        "status": status,
        "runId": run_id,
        "startedAt": None,
        "completedAt": None,
        "terminalReason": terminal_reason,
        "turnRefs": turn_refs or [],
    }


def _private_financial_team_run(
    run_id: str,
    *,
    coordination_status: str = "blocked",
    submission_states: dict[str, str] | None = None,
    turn_ids: dict[str, str] | None = None,
) -> dict:
    states = submission_states or {}
    turns = turn_ids or {}
    return {
        "schemaVersion": financial_runs._SCHEMA_VERSION,
        "runId": run_id,
        "assistantAgentId": ASSISTANT_ID,
        "teamId": "team-finance-test",
        "symbol": "SH600000",
        "periodDays": 30,
        "researchDate": "2026-10-06",
        "depth": "standard",
        "createdAt": "2026-10-06T10:00:00+08:00",
        "stage": "research",
        "coordinationStatus": coordination_status,
        "analysts": {
            role: {
                "agentId": f"agent-{role}",
                "sessionId": f"session-{role}",
                "clientSubmissionId": f"submission-{role}",
                "turnId": turns.get(role, ""),
                "submissionState": states.get(role, "reserved"),
            }
            for role in financial_runs.ROLE_SPECS
        },
        "synthesis": {
            "agentId": ASSISTANT_ID,
            "sessionId": "session-owner",
            "clientSubmissionId": "submission-synthesis",
            "turnId": turns.get("synthesis", ""),
            "submissionState": states.get("synthesis", "reserved"),
        },
    }


def _store_private_financial_team_run(tmp_path, monkeypatch, run: dict) -> dict:
    run_root = tmp_path / "financial-team-runs"
    run_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        financial_runs, "_run_root", lambda _assistant_agent_id, create=False: run_root
    )
    path = financial_runs._run_path(ASSISTANT_ID, run["runId"])
    financial_runs._write_run(path, run)
    return financial_runs._project_run(run)


def test_due_occurrence_respects_saved_next_run_after_late_create_or_resume():
    schedule = _schedule(next_run="2026-10-07T18:00:00+08:00")
    now = datetime(2026, 10, 6, 20, 0, tzinfo=BEIJING)

    assert contract.due_occurrence(schedule, now=now) is None


def test_due_occurrence_after_offline_day_fires_only_current_valid_occurrence():
    schedule = _schedule(next_run="2026-10-05T18:00:00+08:00")
    now = datetime(2026, 10, 6, 20, 0, tzinfo=BEIJING)

    assert contract.due_occurrence(schedule, now=now) == datetime(
        2026, 10, 6, 18, 0, tzinfo=BEIJING
    )


def test_expired_one_time_schedule_cannot_be_restored():
    now = datetime(2026, 10, 6, 12, 0, tzinfo=BEIJING)
    schedule = {
        "enabled": True,
        "execution": {
            "kind": "once",
            "scheduledAt": "2026-10-06T11:00:00+08:00",
        },
    }

    assert contract.schedule_next_run(schedule, now=now) is None


def test_create_request_canonicalizes_a_hk_and_us_symbols():
    normalized = contract.normalize_create_request(
        {**_request(), "symbols": ["600000", "000001", "830001", "hk700", "usbrk.b"]},
        now=datetime(2026, 10, 6, 9, 0, tzinfo=timezone.utc),
    )
    assert normalized["symbols"] == ["sh600000", "sz000001", "bj830001", "hk00700", "usBRK.B"]

    with pytest.raises(FinancialJobValidationError, match="港股或美股"):
        contract.normalize_create_request(
            {**_request(), "symbols": ["AAPL"]},
            now=datetime(2026, 10, 6, 9, 0, tzinfo=timezone.utc),
        )


def test_iso_utc_legacy_helper_emits_beijing_offset():
    assert contract.iso_utc(datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)) == (
        "2026-10-06T12:00:00+08:00"
    )


def test_worker_default_clock_is_aware_and_assistant_cache_loads_at_epoch_zero(tmp_path):
    worker = runtime.FinancialResearchJobsWorker(
        store=_store(tmp_path),
        task_store=runtime_task_registry.RuntimeTaskStore(
            tmp_path / "tasks", branch_generation_reader=lambda _session_id: 0
        ),
        assistant_loader=lambda: [ASSISTANT_ID],
    )

    assert worker._now_provider().tzinfo is not None
    assert worker._assistant_ids(0.0) == [ASSISTANT_ID]


def test_once_create_replay_after_due_returns_original_and_changed_payload_conflicts(
    tmp_path, monkeypatch
):
    selected_store = _store(tmp_path)
    provisioned = []
    monkeypatch.setattr(service, "_require_financial_owner", lambda _assistant_id: None)
    monkeypatch.setattr(
        service.financial_team_service,
        "provision_financial_team",
        lambda assistant_id: provisioned.append(assistant_id),
    )
    initial_now = datetime(2026, 10, 6, 9, 0, tzinfo=BEIJING)
    result = service.create_financial_research_schedule(
        ASSISTANT_ID,
        _request(scheduled_at="2026-10-06T10:00:00+08:00"),
        idempotency_key="once-create-idempotency-01",
        now=initial_now,
        store=selected_store,
    )

    replay = service.create_financial_research_schedule(
        ASSISTANT_ID,
        _request(scheduled_at="2026-10-06T10:00:00+08:00"),
        idempotency_key="once-create-idempotency-01",
        now=datetime(2026, 10, 6, 12, 0, tzinfo=BEIJING),
        store=selected_store,
    )

    assert replay["schedule"]["scheduleId"] == result["schedule"]["scheduleId"]
    assert replay["schedule"]["createdAt"] == "2026-10-06T09:00:00+08:00"
    assert provisioned == [ASSISTANT_ID]
    with pytest.raises(FinancialJobConflictError, match="不能用于不同"):
        service.create_financial_research_schedule(
            ASSISTANT_ID,
            _request(symbols=["000001"], scheduled_at="2026-10-06T10:00:00+08:00"),
            idempotency_key="once-create-idempotency-01",
            now=datetime(2026, 10, 6, 12, 0, tzinfo=BEIJING),
            store=selected_store,
        )


def test_first_time_expired_once_create_still_rejects(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "_require_financial_owner", lambda _assistant_id: None)
    with pytest.raises(FinancialJobValidationError, match="必须设置为未来"):
        service.create_financial_research_schedule(
            ASSISTANT_ID,
            _request(scheduled_at="2026-10-06T10:00:00+08:00"),
            idempotency_key="expired-once-create-key-01",
            now=datetime(2026, 10, 6, 12, 0, tzinfo=BEIJING),
            store=_store(tmp_path),
        )


def test_expired_once_plan_cannot_be_reenabled(tmp_path, monkeypatch):
    selected_store = _store(tmp_path)
    monkeypatch.setattr(service, "_require_financial_owner", lambda _assistant_id: None)
    monkeypatch.setattr(
        service.financial_team_service, "provision_financial_team", lambda _assistant_id: None
    )
    created = service.create_financial_research_schedule(
        ASSISTANT_ID,
        _request(scheduled_at="2026-10-06T10:00:00+08:00"),
        idempotency_key="expired-once-toggle-key-01",
        now=datetime(2026, 10, 6, 9, 0, tzinfo=BEIJING),
        store=selected_store,
    )
    schedule_id = created["schedule"]["scheduleId"]
    service.update_financial_research_schedule(
        ASSISTANT_ID,
        schedule_id,
        enabled=False,
        now=datetime(2026, 10, 6, 9, 30, tzinfo=BEIJING),
        store=selected_store,
    )

    with pytest.raises(FinancialJobConflictError, match="时间已过"):
        service.update_financial_research_schedule(
            ASSISTANT_ID,
            schedule_id,
            enabled=True,
            now=datetime(2026, 10, 6, 10, 1, tzinfo=BEIJING),
            store=selected_store,
        )


def test_future_once_plan_can_be_reenabled(tmp_path, monkeypatch):
    selected_store = _store(tmp_path)
    monkeypatch.setattr(service, "_require_financial_owner", lambda _assistant_id: None)
    monkeypatch.setattr(
        service.financial_team_service, "provision_financial_team", lambda _assistant_id: None
    )
    created = service.create_financial_research_schedule(
        ASSISTANT_ID,
        _request(scheduled_at="2026-10-06T18:00:00+08:00"),
        idempotency_key="future-once-toggle-key-01",
        now=datetime(2026, 10, 6, 9, 0, tzinfo=BEIJING),
        store=selected_store,
    )
    schedule_id = created["schedule"]["scheduleId"]
    service.update_financial_research_schedule(
        ASSISTANT_ID,
        schedule_id,
        enabled=False,
        now=datetime(2026, 10, 6, 9, 30, tzinfo=BEIJING),
        store=selected_store,
    )

    resumed = service.update_financial_research_schedule(
        ASSISTANT_ID,
        schedule_id,
        enabled=True,
        now=datetime(2026, 10, 6, 10, 1, tzinfo=BEIJING),
        store=selected_store,
    )

    assert resumed["enabled"] is True
    assert resumed["nextRunAt"] == "2026-10-06T18:00:00+08:00"


def test_batch_continues_after_verified_failed_symbol_and_finishes_partial(
    tmp_path, monkeypatch
):
    tasks = runtime_task_registry.RuntimeTaskStore(
        tmp_path / "tasks", branch_generation_reader=lambda _session_id: 0
    )
    batch_id = "5bbca55e-84d8-4d23-9301-4a0bc2d4dcb7"
    first, second = "sh600000", "sz000001"
    state = _batch_snapshot(batch_id, [_item(first), _item(second)])
    tasks.register_task(state, branch_generation=0)
    worker = runtime.FinancialResearchJobsWorker(
        store=_store(tmp_path), task_store=tasks, assistant_loader=list
    )
    now = datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)
    created_symbols = []

    def create_run(_assistant_id, *, symbol, **_kwargs):
        created_symbols.append(symbol)
        return {
            "runId": f"run-{symbol}",
            "assistantAgentId": ASSISTANT_ID,
            "coordinationStatus": "ready",
            "analysts": {},
        }

    def submit_role(_assistant_id, run_id, role):
        if run_id == f"run-{first}":
            raise session_service.SessionNotFoundError("missing session")
        return {
            "runId": run_id,
            "assistantAgentId": ASSISTANT_ID,
            "coordinationStatus": "running",
            "analysts": {},
        }

    def load_private_run(_assistant_id, run_id):
        status = "blocked" if run_id == f"run-{first}" else "completed"
        return {
            "runId": run_id,
            "assistantAgentId": ASSISTANT_ID,
            "coordinationStatus": status,
            "analysts": {},
        }

    monkeypatch.setattr(runtime.financial_team_service, "create_financial_team_run", create_run)
    monkeypatch.setattr(
        runtime.financial_team_service, "submit_financial_team_primary_role", submit_role
    )
    monkeypatch.setattr(runtime, "_load_private_financial_team_run", load_private_run)

    worker._process_batch(tasks.load_state(runtime.batch_task_id(batch_id)), should_stop=lambda: False, now=now)
    after_first = tasks.load_state(runtime.batch_task_id(batch_id))["financialResearchBatch"]
    assert [item["status"] for item in after_first["items"]] == ["failed", "queued"], after_first
    assert after_first["status"] == "running"

    worker._process_batch(tasks.load_state(runtime.batch_task_id(batch_id)), should_stop=lambda: False, now=now)
    after_second = tasks.load_state(runtime.batch_task_id(batch_id))["financialResearchBatch"]
    assert [item["status"] for item in after_second["items"]] == ["failed", "completed"]
    assert created_symbols == [first, second]

    worker._process_batch(tasks.load_state(runtime.batch_task_id(batch_id)), should_stop=lambda: False, now=now)
    finished = tasks.load_state(runtime.batch_task_id(batch_id))["financialResearchBatch"]
    assert finished["status"] == "partial"
    assert [item["symbol"] for item in finished["items"] if item["status"] == "completed"] == [second]


def test_batch_reads_private_state_after_create_and_primary_submit_projection(
    tmp_path, monkeypatch
):
    tasks = runtime_task_registry.RuntimeTaskStore(
        tmp_path / "tasks", branch_generation_reader=lambda _session_id: 0
    )
    batch_id = "6f183f0d-e319-4f34-8fdd-4923f4d5d7c0"
    run_id = "e18ff6c9-e088-4b49-9da7-09510f669c8f"
    snapshot = _batch_snapshot(batch_id, [_item("sh600000")])
    tasks.register_task(snapshot, branch_generation=0)
    public_projections = []

    def create_run(_assistant_id, **_kwargs):
        run = _private_financial_team_run(run_id, coordination_status="running")
        projection = _store_private_financial_team_run(tmp_path, monkeypatch, run)
        public_projections.append(projection)
        return projection

    def submit_role(_assistant_id, submitted_run_id, role):
        assert submitted_run_id == run_id
        path = financial_runs._run_path(ASSISTANT_ID, run_id)
        run = financial_runs._load_run(path, ASSISTANT_ID)
        run["analysts"][role]["submissionState"] = "accepted"
        run["analysts"][role]["turnId"] = f"turn-{role}"
        financial_runs._write_run(path, run)
        projection = financial_runs._project_run(run)
        assert "submissionState" not in projection["analysts"][role]
        public_projections.append(projection)
        return projection

    monkeypatch.setattr(
        runtime.financial_team_service, "create_financial_team_run", create_run
    )
    monkeypatch.setattr(
        runtime.financial_team_service,
        "submit_financial_team_primary_role",
        submit_role,
    )
    monkeypatch.setattr(
        runtime.financial_team_service,
        "get_financial_team_run",
        lambda *_args: public_projections[-1],
    )

    worker = runtime.FinancialResearchJobsWorker(
        store=_store(tmp_path), task_store=tasks, assistant_loader=list
    )
    worker._process_batch(
        tasks.load_state(runtime.batch_task_id(batch_id)),
        should_stop=lambda: False,
        now=datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc),
    )

    batch = tasks.load_state(runtime.batch_task_id(batch_id))["financialResearchBatch"]
    assert batch["items"][0]["status"] == "running"
    assert batch["items"][0]["turnRefs"] == [
        {
            "role": role,
            "sessionId": f"session-{role}",
            "turnId": f"turn-{role}",
        }
        for role in runtime.PRIMARY_ROLES
    ]


def test_session_busy_keeps_current_item_queued_with_existing_native_ids(tmp_path):
    tasks = runtime_task_registry.RuntimeTaskStore(
        tmp_path / "tasks", branch_generation_reader=lambda _session_id: 0
    )
    batch_id = "fbc36ed7-820f-4ed6-8f49-f28635f0e7bc"
    item = _item(
        "sh600000",
        status="running",
        run_id="run-existing",
        turn_refs=[{"role": "market", "sessionId": "session-1", "turnId": "turn-1"}],
    )
    snapshot = _batch_snapshot(batch_id, [item])
    tasks.register_task(snapshot, branch_generation=0)
    worker = runtime.FinancialResearchJobsWorker(
        store=_store(tmp_path), task_store=tasks, assistant_loader=list
    )
    batch = snapshot["financialResearchBatch"]

    worker._wait_for_session(runtime.batch_task_id(batch_id), batch, item, now=datetime.now(timezone.utc))

    saved = tasks.load_state(runtime.batch_task_id(batch_id))["financialResearchBatch"]
    assert saved["status"] == "queued"
    assert saved["items"][0]["status"] == "queued"
    assert saved["items"][0]["runId"] == "run-existing"
    assert saved["items"][0]["turnRefs"][0]["turnId"] == "turn-1"


def test_stop_waits_for_unknown_queued_run_then_blocks_instead_of_reporting_stopped(
    tmp_path, monkeypatch
):
    tasks = runtime_task_registry.RuntimeTaskStore(
        tmp_path / "tasks", branch_generation_reader=lambda _session_id: 0
    )
    batch_id = "b0864db2-0dae-4907-87b1-9d4fddeef0d1"
    snapshot = _batch_snapshot(batch_id, [_item("sh600000", status="queued", run_id="run-unknown")])
    snapshot["stopInitiator"] = "user"
    now = datetime(2026, 10, 6, 12, 0, tzinfo=BEIJING)
    snapshot["stopRequestedAt"] = contract.iso_beijing(now - timedelta(minutes=16))
    tasks.register_task(snapshot, branch_generation=0)
    worker = runtime.FinancialResearchJobsWorker(
        store=_store(tmp_path), task_store=tasks, assistant_loader=list
    )
    monkeypatch.setattr(
        runtime,
        "_load_private_financial_team_run",
        lambda *_args: (_ for _ in ()).throw(
            financial_team_service.FinancialTeamRunNotFoundError("unknown run")
        ),
    )

    worker._settle_stop(tasks.load_state(runtime.batch_task_id(batch_id)), now=now)

    settled = tasks.load_state(runtime.batch_task_id(batch_id))["financialResearchBatch"]
    assert settled["status"] == "blocked"
    assert settled["items"][0]["status"] == "blocked"


def test_turn_refs_require_accepted_complete_native_identity(monkeypatch):
    item = {}
    run = {
        "analysts": {
            "market": {
                "sessionId": "session-market",
                "turnId": "turn-market",
                "submissionState": "accepted",
            },
            "fundamental": {
                "sessionId": "session-fundamental",
                "turnId": "turn-fundamental",
                "submissionState": "rejected",
            },
            "news": {
                "sessionId": "session-news",
                "submissionState": "accepted",
            },
        }
    }
    runtime._sync_turn_refs(item, run)

    assert item["turnRefs"] == [
        {"role": "market", "sessionId": "session-market", "turnId": "turn-market"}
    ]


def test_stop_requests_only_accepted_native_turns(tmp_path, monkeypatch):
    requested = []
    run_id = "34f3f6e8-51d7-4dc1-ad29-4c3f0a500006"
    run = _private_financial_team_run(
        run_id,
        submission_states={
            "market": "accepted",
            "fundamental": "rejected",
            "news": "accepted",
        },
        turn_ids={"market": "turn-market", "fundamental": "turn-fundamental"},
    )
    public_run = _store_private_financial_team_run(tmp_path, monkeypatch, run)
    assert "submissionState" not in public_run["analysts"]["market"]
    assert "submissionState" not in public_run["analysts"]["fundamental"]
    item = {}
    runtime._sync_turn_refs(
        item, runtime._load_private_financial_team_run(ASSISTANT_ID, run_id)
    )
    assert item["turnRefs"] == [
        {"role": "market", "sessionId": "session-market", "turnId": "turn-market"}
    ]
    monkeypatch.setattr(
        runtime.financial_team_service,
        "get_financial_team_run",
        lambda *_args: public_run,
    )
    monkeypatch.setattr(
        session_service,
        "request_stop_session_turn",
        lambda session_id, **kwargs: requested.append(
            (session_id, kwargs["expected_turn_id"])
        ),
    )

    runtime._request_exact_batch_turns(
        ASSISTANT_ID,
        {"items": [{"runId": run_id}]},
        task_store=runtime_task_registry.RuntimeTaskStore(
            tmp_path / "tasks", branch_generation_reader=lambda _session_id: 0
        ),
        request_coordinator=False,
    )

    assert requested == [("session-market", "turn-market")]


def test_retry_uses_private_state_when_projection_hides_unknown_submission(
    tmp_path, monkeypatch
):
    run_id = "708b7453-89c0-4cf6-97fb-8cd39c7d5a01"
    run = _private_financial_team_run(
        run_id,
        coordination_status="blocked",
        submission_states={"market": "submitting"},
    )
    public_run = _store_private_financial_team_run(tmp_path, monkeypatch, run)
    assert "submissionState" not in public_run["analysts"]["market"]

    tasks = runtime_task_registry.RuntimeTaskStore(
        tmp_path / "tasks", branch_generation_reader=lambda _session_id: 0
    )
    batch_id = "d41ec63e-3550-4c85-9b3a-3a7e71b23d1a"
    snapshot = _batch_snapshot(
        batch_id, [_item("sh600000", status="failed", run_id=run_id)]
    )
    snapshot["financialResearchBatch"]["status"] = "failed"
    tasks.register_task(snapshot, branch_generation=0)
    monkeypatch.setattr(
        runtime.financial_team_service,
        "get_financial_team_run",
        lambda *_args: public_run,
    )

    with pytest.raises(FinancialJobConflictError, match="未知提交"):
        runtime.retry_batch(ASSISTANT_ID, batch_id, task_store=tasks)

    saved = tasks.load_state(runtime.batch_task_id(batch_id))["financialResearchBatch"]
    assert saved["status"] == "failed"
    assert saved["items"][0]["runId"] == run_id


def test_stop_waits_for_financial_team_coordinator_after_primary_turns_settle(
    tmp_path, monkeypatch
):
    from core.web.services.financial_team import coordinator

    tasks = runtime_task_registry.RuntimeTaskStore(
        tmp_path / "tasks", branch_generation_reader=lambda _session_id: 0
    )
    batch_id = "8cfe81e9-0a5f-4458-9f5b-1d8f72350b05"
    run_id = "run-primary-finished-debate-reserved"
    now = datetime(2026, 10, 6, 12, 0, tzinfo=BEIJING)
    batch_state = _batch_snapshot(
        batch_id, [_item("sh600000", status="queued", run_id=run_id)]
    )
    batch_state["stopInitiator"] = "user"
    batch_state["stopRequestedAt"] = contract.iso_beijing(now)
    tasks.register_task(batch_state, branch_generation=0)

    coord_id = coordinator.coordination_task_id(run_id)
    coord_state = runtime_task_registry.new_snapshot(
        kind=runtime_task_registry.KIND_RESEARCH_TASK,
        task_id=coord_id,
        status="running",
        label=coordinator.TASK_LABEL,
        backgrounding_disabled=True,
        branch_generation=0,
    )
    coord_state.update(
        {
            "coordinationOwner": coordinator.TASK_OWNER,
            "financialTeamAssistantAgentId": ASSISTANT_ID,
            "financialTeamRunId": run_id,
        }
    )
    tasks.register_task(coord_state, branch_generation=0)

    def accepted(role):
        return {
            "sessionId": f"session-{role}",
            "turnId": f"turn-{role}",
            "submissionState": "accepted",
        }

    run = {
        "runId": run_id,
        "assistantAgentId": ASSISTANT_ID,
        "coordinationStatus": "waiting",
        "analysts": {
            "market": accepted("market"),
            "fundamental": accepted("fundamental"),
            "news": accepted("news"),
            "bull": {"submissionState": "reserved"},
            "bear": {"submissionState": "reserved"},
        },
    }
    stop_calls = []
    monkeypatch.setattr(
        runtime,
        "_load_private_financial_team_run",
        lambda *_args: run,
    )
    monkeypatch.setattr(
        session_service,
        "get_session_turn_completion_snapshot",
        lambda session_id, turn_id: {
            "sessionId": session_id,
            "turnId": turn_id,
            "terminal": True,
        },
    )
    monkeypatch.setattr(
        session_service,
        "request_stop_session_turn",
        lambda session_id, **kwargs: stop_calls.append(
            (session_id, kwargs["expected_turn_id"])
        ),
    )
    worker = runtime.FinancialResearchJobsWorker(
        store=_store(tmp_path), task_store=tasks, assistant_loader=list
    )

    worker._settle_stop(tasks.load_state(runtime.batch_task_id(batch_id)), now=now)
    waiting_batch = tasks.load_state(runtime.batch_task_id(batch_id))["financialResearchBatch"]
    requested_coord = tasks.load_state(coord_id)
    assert requested_coord["stopInitiator"] == "user"
    assert waiting_batch["status"] == "stop_requested"
    assert stop_calls == [
        ("session-market", "turn-market"),
        ("session-fundamental", "turn-fundamental"),
        ("session-news", "turn-news"),
    ]

    tasks.mark_task_terminal(coord_id, status="blocked", reason="user stop")
    worker._settle_stop(tasks.load_state(runtime.batch_task_id(batch_id)), now=now)
    settled_batch = tasks.load_state(runtime.batch_task_id(batch_id))["financialResearchBatch"]
    assert settled_batch["status"] == "stopped"


def test_worker_shutdown_does_not_turn_into_user_stop(tmp_path, monkeypatch):
    tasks = runtime_task_registry.RuntimeTaskStore(
        tmp_path / "tasks", branch_generation_reader=lambda _session_id: 0
    )
    batch_id = "8f2373fb-5caa-4336-b580-c9d0b337527a"
    item = _item("sh600000", run_id="run-shutdown")
    snapshot = _batch_snapshot(batch_id, [item])
    tasks.register_task(snapshot, branch_generation=0)
    worker = runtime.FinancialResearchJobsWorker(
        store=_store(tmp_path), task_store=tasks, assistant_loader=list
    )
    monkeypatch.setattr(
        runtime.financial_team_service,
        "create_financial_team_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not submit")),
    )
    monkeypatch.setattr(
        runtime.session_service,
        "request_stop_session_turn",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not stop")),
    )

    worker._advance_item(
        snapshot,
        item,
        should_stop=lambda: True,
        now=datetime(2026, 10, 6, 12, 0, tzinfo=BEIJING),
    )

    saved = tasks.load_state(runtime.batch_task_id(batch_id))
    assert saved["stopInitiator"] is None
    assert saved["financialResearchBatch"]["status"] == "queued"


def test_retry_resets_only_failed_or_unstarted_items(tmp_path, monkeypatch):
    tasks = runtime_task_registry.RuntimeTaskStore(
        tmp_path / "tasks", branch_generation_reader=lambda _session_id: 0
    )
    batch_id = "133d3e14-b1c9-4d03-b52e-e31e003a8c68"
    items = [
        _item("sh600000", status="completed", run_id="run-complete"),
        _item("sz000001", status="failed", terminal_reason="verified error"),
        _item("sh600519", status="skipped", terminal_reason="not started"),
    ]
    snapshot = _batch_snapshot(batch_id, items, status="completed")
    snapshot["financialResearchBatch"]["status"] = "partial"
    snapshot["status"] = "completed"
    tasks.register_task(snapshot, branch_generation=0)
    monkeypatch.setattr(service, "_require_financial_owner", lambda _assistant_id: None)

    result = service.retry_financial_research_batch(
        ASSISTANT_ID, batch_id, task_store=tasks
    )

    assert [item["status"] for item in result["items"]] == [
        "completed",
        "queued",
        "queued",
    ]


def test_create_if_absent_and_concurrent_stop_share_runtime_lock_order(tmp_path, monkeypatch):
    jobs = _store(tmp_path)
    tasks = runtime_task_registry.RuntimeTaskStore(
        tmp_path / "tasks", branch_generation_reader=lambda _session_id: 0
    )
    schedule_id = "59fa9c16-7b38-4d8f-9b92-677c3ffccaf9"
    batch_id = "c118d0bf-651d-46d5-9f63-a8e30aecdc76"
    occurrence = {
        "batchId": batch_id,
        "triggeredAt": "2026-10-06T12:00:00+08:00",
        "researchDate": "2026-10-06",
        "materialized": False,
    }
    schedule = {
        "scheduleId": schedule_id,
        "assistantAgentId": ASSISTANT_ID,
        "symbols": ["sh600000"],
        "periodDays": 30,
        "depth": "standard",
        "execution": {"kind": "daily", "timeOfDay": "18:00"},
        "enabled": True,
    }
    jobs.update(
        ASSISTANT_ID,
        lambda state: state["schedules"].update(
            {schedule_id: {**schedule, "lastOccurrence": dict(occurrence)} }
        ),
    )
    create_entered = threading.Event()
    release_create = threading.Event()
    stop_lock_attempted = threading.Event()
    original_load = tasks._load_state_unlocked

    class ObservedRLock:
        def __init__(self):
            self.inner = threading.RLock()

        def acquire(self, *args, **kwargs):
            if threading.current_thread().name == "batch-stop":
                stop_lock_attempted.set()
            return self.inner.acquire(*args, **kwargs)

        def release(self):
            return self.inner.release()

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, *_args):
            self.release()

    tasks._lock = ObservedRLock()

    def blocking_load(task_id):
        result = original_load(task_id)
        if task_id == runtime.batch_task_id(batch_id) and threading.current_thread().name == "batch-create" and not result:
            create_entered.set()
            if not release_create.wait(3):
                raise TimeoutError("create barrier timed out")
        return result

    monkeypatch.setattr(tasks, "_load_state_unlocked", blocking_load)

    def create_batch():
        return runtime.ensure_occurrence_batch(
            schedule, occurrence, store=jobs, task_store=tasks
        )

    def stop_batch():
        task_id = runtime.batch_task_id(batch_id)

        def request_stop(state):
            state["stopInitiator"] = "user"
            state["stopRequestedAt"] = "2026-10-06T12:00:01+08:00"
            return state

        return tasks.update_task(task_id, request_stop)

    results = {}
    errors = []

    def capture(name, function):
        try:
            results[name] = function()
        except Exception as exc:  # noqa: BLE001 - surface worker-thread failures in the assertion below
            errors.append(exc)

    create_thread = threading.Thread(
        target=capture, args=("created", create_batch), name="batch-create"
    )
    stop_thread = threading.Thread(
        target=capture, args=("stopped", stop_batch), name="batch-stop"
    )
    create_thread.start()
    assert create_entered.wait(1)
    stop_thread.start()
    assert stop_lock_attempted.wait(1)
    release_create.set()
    create_thread.join(timeout=3)
    stop_thread.join(timeout=3)
    assert not create_thread.is_alive()
    assert not stop_thread.is_alive()
    assert not errors, errors
    created = results["created"]
    stopped = results["stopped"]

    assert created["batchId"] == batch_id
    assert stopped["stopInitiator"] == "user"
    assert tasks.load_state(runtime.batch_task_id(batch_id))["stopInitiator"] == "user"
