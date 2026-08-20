from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.runtime_manager import instances_registry as registry

from datetime import UTC, datetime


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "desktop"
    / "electron"
    / "src"
    / "lifecycle"
    / "__fixtures__"
    / "instanceRegistryCas.cases.json"
)


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


FIXTURE = _load_fixture()
CASES = FIXTURE["cases"]


def _clone_registry(raw: dict | None) -> dict:
    payload = json.loads(json.dumps(raw or {"schemaVersion": 2, "instances": {}}))
    payload.setdefault("schemaVersion", registry.REGISTRY_SCHEMA_VERSION)
    payload.setdefault("instances", {})
    return payload


def _snapshot(entry: dict) -> dict:
    return {
        "generation": int(entry.get("generation") or 0),
        "status": str(entry.get("status") or ""),
        "phase": str(entry.get("phase") or ""),
        "desiredState": str(entry.get("desiredState") or ""),
        "port": int(entry.get("port") or 0),
        "controlPort": int(entry.get("controlPort") or 0),
        "spawnPid": int(entry.get("spawnPid") or 0),
        "commandId": str(entry.get("commandId") or ""),
        "failureMessage": str(entry.get("failureMessage") or ""),
        "ownerPid": int(entry.get("ownerPid") or 0),
        "ownerId": str((entry.get("ownerLease") or {}).get("ownerId") or "") if isinstance(entry.get("ownerLease"), dict) else "",
        "ownerLeaseExpiresAt": str((entry.get("ownerLease") or {}).get("expiresAt") or "") if isinstance(entry.get("ownerLease"), dict) else "",
    }


def _assert_expected(actual: dict, expected: dict | None) -> None:
    if not expected:
        return
    for key, value in expected.items():
        assert actual.get(key) == value, f"{key}: {actual.get(key)!r} != {value!r}"


def _now_from_ms(raw_input: dict) -> datetime | None:
    if "nowMs" not in raw_input:
        return None
    return datetime.fromtimestamp(int(raw_input.get("nowMs") or 0) / 1000, tz=UTC)


def _run_op(payload: dict, op: str, raw_input: dict, monkeypatch) -> dict:
    busy = {int(port) for port in (raw_input.get("busyPorts") or [])}
    monkeypatch.setattr(registry, "_port_is_free", lambda port, host: int(port) not in busy)
    if op == "claimStart":
        try:
            entry = registry.apply_claim_start(
                payload,
                instance_id=str(raw_input.get("instanceId") or ""),
                project_root=str(raw_input.get("projectRoot") or ""),
                branch=str(raw_input.get("branch") or ""),
                operation=str(raw_input.get("operation") or "start"),
                command_id=str(raw_input.get("commandId") or ""),
                deadline_at=str(raw_input.get("deadlineAt") or ""),
                owner_pid=int(raw_input.get("ownerPid") or 0),
                owner_id=str(raw_input.get("ownerId") or ""),
                extra_used={int(port) for port in (raw_input.get("extraUsed") or [])},
                preferred_backend=int(raw_input.get("preferredBackend") or registry.DEFAULT_BASE_PORT),
                preferred_control=int(raw_input.get("preferredControl") or registry.DEFAULT_CONTROL_PORT),
                started_at=raw_input.get("startedAt"),
                now=_now_from_ms(raw_input),
            )
        except registry.InstanceBusyError as exc:
            return {
                "ok": False,
                "code": exc.code,
                "generation": exc.generation,
                "status": exc.status,
            }
        return {"ok": True, **_snapshot(entry)}
    if op == "claimStop":
        entry = registry.apply_claim_stop(
            payload,
            instance_id=str(raw_input.get("instanceId") or ""),
            project_root=str(raw_input.get("projectRoot") or ""),
        )
        return {"ok": True, **_snapshot(entry)}
    if op in {"observeReady", "observeError"}:
        applied, entry = registry.apply_observe(
            payload,
            instance_id=str(raw_input.get("instanceId") or ""),
            operation="observe-ready" if op == "observeReady" else "observe-error",
            expected_generation=int(raw_input.get("expectedGeneration") or 0),
            message=str(raw_input.get("message") or ""),
        )
        return {"applied": applied, **_snapshot(entry)}
    if op == "recordSpawnPid":
        applied, entry = registry.apply_record_spawn_pid(
            payload,
            str(raw_input.get("instanceId") or ""),
            int(raw_input.get("spawnPid") or 0),
            int(raw_input.get("expectedGeneration") or 0),
        )
        return {"applied": applied, **_snapshot(entry)}
    if op == "reclaimStale":
        applied, entry = registry.apply_reclaim_stale_in_flight_start(
            payload,
            instance_id=str(raw_input.get("instanceId") or ""),
            now=_now_from_ms(raw_input),
        )
        return {"applied": applied, **_snapshot(entry)}
    if op == "renewOwnerLease":
        applied, entry = registry.apply_renew_owner_lease(
            payload,
            instance_id=str(raw_input.get("instanceId") or ""),
            owner_id=str(raw_input.get("ownerId") or ""),
            expected_generation=int(raw_input.get("expectedGeneration") or 0),
            now=_now_from_ms(raw_input),
        )
        return {"applied": applied, **_snapshot(entry)}
    if op == "upsert":
        applied, entry = registry.apply_upsert(
            payload,
            str(raw_input.get("instanceId") or ""),
            dict(raw_input.get("fields") or {}),
            expected_generation=raw_input.get("expectedGeneration"),
        )
        return {"applied": applied, **_snapshot(entry)}
    raise AssertionError(f"unknown op {op}")


def test_shared_cas_fixture_has_unique_cases():
    assert len(CASES) >= 15
    ids = [str(item.get("id") or "") for item in CASES]
    assert "" not in ids
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("case", CASES, ids=lambda item: str(item.get("id") or "missing-id"))
def test_python_registry_cas_matches_shared_fixture(case: dict, monkeypatch):
    payload = _clone_registry(case.get("registry") if isinstance(case.get("registry"), dict) else None)
    steps = case.get("steps") if isinstance(case.get("steps"), list) and case.get("steps") else [
        {"op": case.get("op"), "input": case.get("input") or {}, "expected": case.get("expected")}
    ]
    last = {}
    for step in steps:
        last = _run_op(payload, str(step.get("op") or ""), step.get("input") or {}, monkeypatch)
        _assert_expected(last, step.get("expected") if isinstance(step.get("expected"), dict) else None)
    _assert_expected(last, case.get("expected") if isinstance(case.get("expected"), dict) else None)
