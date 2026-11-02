"""Exercise private configuration authority through real broker deliveries."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from core.assistant_runtime import actions, configuration_protocol as protocol
from core.assistant_runtime.configuration_control import NativeRegistryLease
from core.assistant_runtime.configuration_references import ConfigurationReferenceError
from core.assistant_runtime.main_control import MainControlBroker
from core.infrastructure import native_runtime


CONTEXT = "cfg-" + "a" * 32
LEASE = "b" * 64
DIGEST = "c" * 64
ACQUIRE = "configuration_reference_acquire"
VALIDATE = "configuration_reference_validate"
RELEASE = "configuration_reference_release"


def request(action):
    return {"contextId": CONTEXT, **({"leaseId": LEASE, "snapshotDigest": DIGEST} if action != ACQUIRE else {})}


@pytest.fixture
def census(tmp_path):
    return {"schemaVersion": 1, "leaseId": LEASE, "revision": 17, "snapshotDigest": DIGEST, "complete": True,
            "projects": [{"registrationId": "live:registration-one", "baseProjectId": "live", "root": str(tmp_path / "active"), "active": True},
                         {"registrationId": "offline:registration-two", "baseProjectId": "offline", "root": str(tmp_path / "inactive"), "active": False}],
            "nativeAssistantRoot": str(tmp_path / "native-assistant")}


def make_broker(**options):
    def admitted_projection_must_not_supply_full_registry():
        pytest.fail("Private census must not use admitted project IDs")

    return MainControlBroker(admitted_projection_must_not_supply_full_registry, configuration_enabled=True,
                             timeout_seconds=2, claim_seconds=0.2, **options)


async def delivered(owner, action, result, *, expected_error=False):
    pending = asyncio.create_task(owner.invoke(action, request(action), turn_id="trusted-native-turn"))
    wire = (await owner.claim())["request"]
    assert wire["action"] == action and {key: value for key, value in wire.items() if key not in {"action", "deliveryId"}} == request(action)
    if expected_error:
        with pytest.raises(ValueError):
            owner.settle(wire["deliveryId"], result)
        assert not pending.done()
        fallback = protocol.unavailable(action, request(action))
        assert owner.settle(wire["deliveryId"], fallback)
        assert await pending == fallback
    else:
        assert owner.settle(wire["deliveryId"], result)
        assert await pending == result
    assert owner.settle(wire["deliveryId"], result) is False


def test_real_broker_returns_complete_registered_census_including_inactive_and_native_root(census):
    async def scenario():
        owner = make_broker()
        try:
            await delivered(owner, ACQUIRE, census)
            await delivered(owner, VALIDATE, {"schemaVersion": 1, "leaseId": LEASE, "valid": True,
                                             "revision": 17, "snapshotDigest": DIGEST})
            await delivered(owner, RELEASE, {"schemaVersion": 1, "leaseId": LEASE, "released": True})
        finally:
            owner.close()

    asyncio.run(scenario())
    assert census["projects"][1]["active"] is False


@pytest.mark.parametrize("change", ["unknown_field", "wrong_version", "bool_version", "bad_lease", "bad_digest", "bool_revision",
    "negative_revision", "relative_native_root", "relative_project_root", "duplicate_registration", "extra_project_field", "bool_active"])
def test_acquire_rejects_nonclosed_or_incomplete_census_at_real_settle(census, change):
    value = deepcopy(census)
    if change == "unknown_field":
        value["admittedOnly"] = True
    elif change == "wrong_version":
        value["schemaVersion"] = 2
    elif change == "bool_version":
        value["schemaVersion"] = True
    elif change == "bad_lease":
        value["leaseId"] = "bad"
    elif change == "bad_digest":
        value["snapshotDigest"] = "bad"
    elif change == "bool_revision":
        value["revision"] = True
    elif change == "negative_revision":
        value["revision"] = -1
    elif change == "relative_native_root":
        value["nativeAssistantRoot"] = "relative/native"
    elif change == "relative_project_root":
        value["projects"][1]["root"] = "relative/project"
    elif change == "duplicate_registration":
        value["projects"][1]["registrationId"] = value["projects"][0]["registrationId"]
    elif change == "extra_project_field":
        value["projects"][0]["prompt"] = "SECRET"
    else:
        value["projects"][0]["active"] = 1

    async def scenario():
        owner = make_broker()
        try:
            await delivered(owner, ACQUIRE, value, expected_error=True)
        finally:
            owner.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("code", ["busy", "unavailable"])
def test_closed_acquire_refusal_can_settle_without_any_registry_details(code):
    async def scenario():
        owner = make_broker()
        try:
            result = {"schemaVersion": 1, "complete": False, "code": code}
            await delivered(owner, ACQUIRE, result)
            await delivered(owner, ACQUIRE, {**result, "projects": []}, expected_error=True)
        finally:
            owner.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("action,result", [
    (VALIDATE, {"schemaVersion": 1, "leaseId": LEASE, "valid": False}),
    (RELEASE, {"schemaVersion": 1, "leaseId": LEASE, "released": False}),
    (RELEASE, {"schemaVersion": 1, "leaseId": LEASE, "released": True}),
])
def test_validate_and_release_have_closed_failure_or_success_shapes(action, result):
    async def scenario():
        owner = make_broker()
        try:
            await delivered(owner, action, result)
            await delivered(owner, action, {**result, "root": "C:/forbidden"}, expected_error=True)
        finally:
            owner.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("action,result", [
    (VALIDATE, {"schemaVersion": 1, "leaseId": "d" * 64, "valid": False}),
    (VALIDATE, {"schemaVersion": 1, "leaseId": LEASE, "valid": True, "revision": 17, "snapshotDigest": "d" * 64}),
    (VALIDATE, {"schemaVersion": 1, "leaseId": LEASE, "valid": True, "revision": True, "snapshotDigest": DIGEST}),
    (RELEASE, {"schemaVersion": 1, "leaseId": "d" * 64, "released": True}),
    (RELEASE, {"schemaVersion": 1, "leaseId": LEASE, "released": 1}),
])
def test_wrong_lease_digest_or_result_types_never_settle(action, result):
    async def scenario():
        owner = make_broker()
        try:
            await delivered(owner, action, result, expected_error=True)
        finally:
            owner.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("action,parameters", [
    (ACQUIRE, {"contextId": CONTEXT, "root": "C:/forbidden"}),
    (ACQUIRE, {"contextId": CONTEXT, "projectId": "admitted-only"}),
    (ACQUIRE, {"contextId": "model-context"}),
    (VALIDATE, {"contextId": CONTEXT, "leaseId": "bad", "snapshotDigest": DIGEST}),
    (RELEASE, {"contextId": CONTEXT, "leaseId": LEASE}),
])
def test_private_request_cannot_accept_paths_admitted_subset_or_unbound_tokens(action, parameters):
    async def scenario():
        owner = make_broker()
        try:
            with pytest.raises(ValueError):
                await owner.invoke(action, parameters)
            assert (await owner.claim())["request"] is None
        finally:
            owner.close()

    asyncio.run(scenario())


def test_private_capability_disabled_rejects_every_operation_before_delivery():
    async def scenario():
        owner = MainControlBroker(lambda: ["admitted"], claim_seconds=0.01)
        try:
            for action in protocol.ACTIONS:
                with pytest.raises(ValueError, match="not enabled"):
                    await owner.invoke(action, request(action))
            assert (await owner.claim())["request"] is None
        finally:
            owner.close()

    asyncio.run(scenario())


def test_busy_closed_and_expired_delivery_keep_distinct_closed_refusals(census):
    async def scenario():
        owner = make_broker(max_pending=1)
        first = asyncio.create_task(owner.invoke(ACQUIRE, request(ACQUIRE)))
        wire = (await owner.claim())["request"]
        assert await owner.invoke(ACQUIRE, {"contextId": "cfg-" + "f" * 32}) == {"schemaVersion": 1, "complete": False, "code": "busy"}
        owner.close()
        assert await first == {"schemaVersion": 1, "complete": False, "code": "unavailable"}
        assert owner.settle(wire["deliveryId"], census) is False
        assert await owner.invoke(ACQUIRE, request(ACQUIRE)) == {"schemaVersion": 1, "complete": False, "code": "unavailable"}
        expired = MainControlBroker(lambda: (), configuration_enabled=True, timeout_seconds=0.2, claim_seconds=0.1)
        pending = asyncio.create_task(expired.invoke(ACQUIRE, request(ACQUIRE)))
        late = (await expired.claim())["request"]
        assert await pending == {"schemaVersion": 1, "complete": False, "code": "unavailable"}
        assert expired.settle(late["deliveryId"], census) is False
        expired.close()

    asyncio.run(scenario())


def test_private_census_transport_accepts_above_legacy_budget_but_keeps_four_mib_limit(census):
    import json
    large = deepcopy(census)
    large["projects"] = [{"registrationId": f"p:registration-{index}", "baseProjectId": "p",
        "root": "D:/registered/" + "nested/" * 140 + str(index), "active": bool(index % 2)} for index in range(100)]
    assert 64 * 1024 < len(json.dumps(large)) < protocol.MAX_RESULT_BYTES
    excessive = deepcopy(census)
    excessive["projects"] = [{"registrationId": f"p:registration-{index}", "baseProjectId": "p",
        "root": "D:/registered/" + "nested/" * 560 + str(index), "active": False} for index in range(1100)]
    assert len(json.dumps(excessive)) > protocol.MAX_RESULT_BYTES

    async def scenario():
        owner = make_broker()
        try:
            await delivered(owner, ACQUIRE, large)
            await delivered(owner, ACQUIRE, excessive, expected_error=True)
        finally:
            owner.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("revision_changed,release_retry", [(False, False), (True, False), (False, True)])
def test_native_registry_lease_thread_to_real_broker_does_not_deadlock_and_always_releases(census, monkeypatch, revision_changed, release_retry):
    from pathlib import Path
    monkeypatch.setattr(native_runtime, "assistant_native_root", lambda: Path(census["nativeAssistantRoot"]).resolve())

    async def scenario():
        owner, loop, deliveries = make_broker(), asyncio.get_running_loop(), []

        def worker():
            lease = NativeRegistryLease(owner, loop, {"agentId": "assistant", "sessionId": "native-session", "turnId": "native-turn"})
            with lease:
                assert lease.inventory["projects"][1]["active"] is False
                if revision_changed:
                    with pytest.raises(ConfigurationReferenceError):
                        lease.assert_current()
                else:
                    lease.assert_current()
            assert lease.closed

        task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            for index in range(4 if release_retry else 3):
                wire = (await owner.claim())["request"]
                assert wire is not None
                deliveries.append(wire)
                action = wire["action"]
                value = (census if action == ACQUIRE else {"schemaVersion": 1, "leaseId": LEASE,
                    **({"valid": True, "revision": 18 if revision_changed else 17, "snapshotDigest": DIGEST} if action == VALIDATE else
                       {"released": not release_retry or index == 3})})
                assert owner.settle(wire["deliveryId"], value)
            await asyncio.wait_for(task, timeout=2)
        finally:
            owner.close()
            await asyncio.gather(task, return_exceptions=True)
        assert [wire["action"] for wire in deliveries] == [ACQUIRE, VALIDATE, RELEASE] + ([RELEASE] if release_retry else [])
        assert len({wire["contextId"] for wire in deliveries}) == 1
        assert all(wire["leaseId"] == LEASE and wire["snapshotDigest"] == DIGEST for wire in deliveries[1:])

    asyncio.run(scenario())


def test_private_operations_are_absent_from_model_index_even_when_broker_enabled(monkeypatch):
    loop = asyncio.new_event_loop()
    owner = make_broker()
    monkeypatch.setattr(actions, "_binding", (SimpleNamespace(), loop, owner))
    try:
        page = actions.execute_action("index", {"query": "configuration_reference_"})
        assert page["actions"] == []
        for action in protocol.ACTIONS:
            with pytest.raises(ValueError, match="Unknown Launcher action"):
                actions.execute_action("describe", {"action": action})
    finally:
        loop.close()


def test_native_profile_root_mismatch_releases_acquired_lease_before_rejecting(census, monkeypatch, tmp_path):
    monkeypatch.setattr(native_runtime, "assistant_native_root", lambda: (tmp_path / "other-profile").resolve())

    async def scenario():
        owner, loop, seen = make_broker(), asyncio.get_running_loop(), []

        def worker():
            with pytest.raises(ConfigurationReferenceError) as error:
                with NativeRegistryLease(owner, loop, {"turnId": "native-turn"}):
                    pytest.fail("foreign profile must not enter configuration transaction")
            assert error.value.code == "REFERENCE_REGISTRY_IDENTITY_CHANGED"

        task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            for _ in range(2):
                wire = (await owner.claim())["request"]
                assert wire is not None
                seen.append(wire["action"])
                value = census if wire["action"] == ACQUIRE else {"schemaVersion": 1, "leaseId": LEASE, "released": True}
                assert owner.settle(wire["deliveryId"], value)
            await asyncio.wait_for(task, timeout=2)
        finally:
            owner.close()
            await asyncio.gather(task, return_exceptions=True)
        assert seen == [ACQUIRE, RELEASE]

    asyncio.run(scenario())
