from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.runtime_manager import instances_registry as registry

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "desktop"
    / "electron"
    / "src"
    / "lifecycle"
    / "__fixtures__"
    / "instanceOwnerLease.cases.json"
)


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


FIXTURE = _load_fixture()
CASES = FIXTURE["cases"]


def test_owner_lease_protocol_constants():
    protocol = FIXTURE["protocol"]
    assert int(protocol["registrySchemaVersion"]) == registry.REGISTRY_SCHEMA_VERSION
    assert int(protocol["ownerLeaseTtlMs"]) == registry.OWNER_LEASE_TTL_MS
    assert int(protocol["ownerLeaseHeartbeatMs"]) == registry.OWNER_LEASE_HEARTBEAT_MS


@pytest.mark.parametrize("case", CASES, ids=lambda item: str(item.get("id") or "missing-id"))
def test_python_hang_predicate_matches_shared_fixture(case: dict):
    now = datetime.fromtimestamp(int(FIXTURE["nowMs"]) / 1000, tz=UTC)
    raw_input = case.get("input") if isinstance(case.get("input"), dict) else {}
    stale = registry.is_stale_in_flight_start(
        case.get("entry") if isinstance(case.get("entry"), dict) else {},
        now=now,
        backend_alive=bool(raw_input.get("backendAlive")),
        backend_listening=bool(raw_input.get("backendListening")),
        window_open=bool(raw_input.get("windowOpen")),
    )
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    assert stale is bool(expected.get("stale"))
