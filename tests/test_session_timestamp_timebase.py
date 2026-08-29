"""Regression tests for the session timestamp time base (tz-aware UTC)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.web.services.session import runtime_glue
from core.web.services.session.timebase import parse_timestamp_utc
from core.web.services.team_workflow.research_runtime import agent_task_budget_usage


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def test_now_timestamp_is_tz_aware_utc_and_current() -> None:
    before = _utc_now()
    text = runtime_glue._now_timestamp()
    after = _utc_now()

    assert text.endswith("+00:00")
    parsed = datetime.fromisoformat(text)
    assert parsed.tzinfo is not None
    assert before <= parsed <= after.replace(microsecond=99) or abs((parsed - _utc_now()).total_seconds()) <= 2


def test_session_turn_control_turn_id_embeds_utc_clock() -> None:
    before = _utc_now()
    control = runtime_glue._create_session_turn_control("timebase-s1")
    after = _utc_now().replace(microsecond=0) + timedelta(seconds=1)

    turn_id = str(control.turn_id)
    assert turn_id.startswith("timebase-s1-")
    digits = turn_id.rsplit("-", 1)[-1]
    assert len(digits) == 20 and digits.isdigit()

    embedded = datetime.strptime(digits[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    # Minute-level tolerance: the embedded wall clock must be UTC, not local.
    assert before - timedelta(minutes=1) <= embedded <= after + timedelta(minutes=1)
    assert abs((embedded - _utc_now()).total_seconds()) <= 90


def test_parse_timestamp_utc_treats_naive_as_machine_local() -> None:
    now_local = datetime.now().astimezone()
    naive_text = now_local.replace(tzinfo=None).isoformat(timespec="seconds")
    aware_text = now_local.astimezone(timezone.utc).isoformat(timespec="seconds")

    from_naive = parse_timestamp_utc(naive_text)
    from_aware = parse_timestamp_utc(aware_text)

    assert from_naive is not None and from_aware is not None
    assert from_naive.tzinfo is not None
    assert from_naive == from_aware


def test_parse_timestamp_utc_sorts_mixed_legacy_and_new_values() -> None:
    # Legacy writer: naive machine-local wall time one hour ago.
    legacy_naive = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    # New writer: tz-aware UTC now.
    fresh_aware = _utc_now().isoformat(timespec="seconds")

    legacy = parse_timestamp_utc(legacy_naive)
    fresh = parse_timestamp_utc(fresh_aware)
    assert legacy is not None and fresh is not None
    # On a UTC+8 machine: local 12:04 == 04:04Z, so the legacy hour-old value
    # must still sort before the fresh UTC value (no 8-hour inversion).
    assert legacy < fresh
    assert abs((fresh - legacy - timedelta(hours=1)).total_seconds()) <= 5


def test_parse_timestamp_utc_handles_z_and_invalid_input() -> None:
    now_local = datetime.now().astimezone()
    z_text = now_local.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    from_z = parse_timestamp_utc(z_text)
    assert from_z is not None
    assert parse_timestamp_utc("not-a-timestamp") is None
    assert parse_timestamp_utc("") is None
    assert parse_timestamp_utc(None) is None


def test_parse_task_time_normalizes_naive_to_utc() -> None:
    now_local = datetime.now().astimezone()
    naive_text = now_local.replace(tzinfo=None).isoformat(timespec="seconds")
    aware_text = now_local.astimezone(timezone.utc).isoformat(timespec="seconds")

    from_naive = agent_task_budget_usage.parse_task_time(naive_text)
    from_aware = agent_task_budget_usage.parse_task_time(aware_text)

    assert from_naive is not None and from_aware is not None
    assert from_naive.tzinfo is not None
    assert from_naive == from_aware


def test_turn_diagnostics_work_run_timestamp_treats_naive_as_local() -> None:
    from core.web.services.session import turn_diagnostics

    now_local = datetime.now().astimezone()
    naive_text = now_local.replace(tzinfo=None).isoformat(timespec="seconds")

    parsed = turn_diagnostics._parse_work_run_timestamp(naive_text)
    expected = now_local.astimezone(timezone.utc)

    assert parsed is not None
    assert abs((parsed - expected).total_seconds()) <= 2
