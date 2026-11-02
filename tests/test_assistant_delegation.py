"""Goal provenance stays separate from ordinary exact-span dispatch."""
import hashlib
from copy import deepcopy
from pathlib import Path

import anyio
import pytest

from core.assistant_runtime.delegation import DelegationManager, GoalCreate, DerivedDispatch, contracts
from core.assistant_runtime.dispatch import DispatchError


@pytest.fixture
def setup_goal(tmp_path):
    class Dispatch:
        _root = tmp_path / "assistant_dispatch"
        _dispatch_admission = anyio.Lock()
        projects = {"project-1": tmp_path / "project"}
        calls = []

        def _project(self, pid):
            if pid not in self.projects:
                raise DispatchError("revoked", code="PROJECT_NOT_AUTHORIZED")
            return self.projects[pid]

        @staticmethod
        def _binding(path):
            return hashlib.sha256(str(path).casefold().encode()).hexdigest()

        def _check_dispatch_unfenced(self):
            pass

        async def _dispatch(self, pid, **kwargs):
            self.calls.append((pid, kwargs))
            return {"dispatchId": kwargs["dispatch_id"], "nativeTaskId": "native-" + kwargs["dispatch_id"]}

    source = {"schemaVersion": 1, "agentId": "assistant", "sessionId": "session", "turnId": "operator-turn",
        "eventId": "original-user-event", "start": 0, "end": 5, "contentHash": "a" * 64,
        "spanHash": "b" * 64, "selectorHash": "c" * 64}
    runtime = {"agentId": "assistant", "sessionId": "session", "turnId": "patrol-turn"}
    seen = []
    now = [1000.0]

    def read_source(current, ref):
        assert current["agentId"] == "assistant"
        assert ref == source
        seen.append(deepcopy(current))
        return ref

    dispatch = Dispatch()
    owner = DelegationManager(dispatch, source_reader=read_source,
        source_resolver=lambda *_a, **_kw: ("operator goal", deepcopy(source)), clock=lambda: now[0])
    goal = {"goal_id": "goal-1", "targets": [{"project_id": "project-1", "agent_id": "worker"}],
        "permission_profile": "workspace_write", "max_tasks": 2, "ttl_minutes": 10}
    return owner, dispatch, runtime, goal, now, seen


def child(**overrides):
    return {"goal_id": "goal-1", "project_id": "project-1", "agent_id": "worker", "dispatch_id": "child-1",
        "task": "Inspect the failed component and fix the verified defect.", "permission_profile": "workspace_write", **overrides}


def test_derived_work_can_differ_from_operator_words_and_survive_owner_reconstruction(setup_goal):
    owner, dispatch, runtime, goal, now, seen = setup_goal
    owner.create(goal, runtime)
    restored = DelegationManager(dispatch, source_reader=owner._source_reader, clock=lambda: now[0])
    result = anyio.run(restored.derived, child(), runtime)
    assert result["nativeTaskId"] == "native-child-1"
    _, call = dispatch.calls[0]
    assert call["task"] == child()["task"]
    assert call["derived_ref"]["sourceEventId"] == "original-user-event"
    assert call["derived_ref"]["sourceTurnId"] == "operator-turn"
    assert "source_ref" not in call
    assert seen[-1]["turnId"] == "patrol-turn"
    text = next(owner.root.glob("*.json")).read_text(encoding="utf-8")
    assert "operator goal" not in text and child()["task"] not in text


def test_same_child_keeps_quota_and_new_id_cannot_recreate_same_work(setup_goal):
    owner, dispatch, runtime, goal, *_ = setup_goal
    owner.create(goal, runtime)
    anyio.run(owner.derived, child(), runtime)
    anyio.run(owner.derived, child(), runtime)
    assert owner.get("goal-1", runtime)["usedTasks"] == 1
    with pytest.raises(DispatchError, match="派生") as error:
        anyio.run(owner.derived, child(dispatch_id="replacement-id"), runtime)
    assert error.value.code == "DELEGATION_ORIGINAL_DISPATCH_REQUIRED"
    with pytest.raises(DispatchError) as error:
        anyio.run(owner.derived, child(task="Changed task"), runtime)
    assert error.value.code == "DELEGATION_DISPATCH_CONFLICT"


@pytest.mark.parametrize("kind", ["expiry", "revoke", "project", "binding", "quota", "target", "permission"])
def test_goal_boundaries_precede_native_effect(setup_goal, kind):
    owner, dispatch, runtime, goal, now, *_ = setup_goal
    if kind == "permission":
        goal["permission_profile"] = "read_only"
    if kind == "quota":
        goal["max_tasks"] = 1
    owner.create(goal, runtime)
    if kind == "expiry":
        now[0] = 1600
    elif kind == "revoke":
        anyio.run(owner.revoke, "goal-1", runtime)
    elif kind == "project":
        dispatch.projects.clear()
    elif kind == "binding":
        dispatch.projects["project-1"] = Path("different-root")
    elif kind == "quota":
        anyio.run(owner.derived, child(dispatch_id="used", task="Prior distinct task"), runtime)
    before = len(dispatch.calls)
    with pytest.raises(DispatchError):
        anyio.run(owner.derived, child(agent_id="other") if kind == "target" else child(), runtime)
    assert len(dispatch.calls) == before


def test_goal_id_reuse_does_not_extend_expiry_or_restore_revocation(setup_goal):
    owner, _, runtime, goal, now, *_ = setup_goal
    first = owner.create(goal, runtime)
    now[0] += 30
    assert owner.create(goal, runtime)["expiresAt"] == first["expiresAt"]
    anyio.run(owner.revoke, "goal-1", runtime)
    assert owner.create(goal, runtime)["revoked"] is True
    with pytest.raises(DispatchError):
        owner.create({**goal, "max_tasks": 3}, runtime)


def test_unknown_native_dispatch_reserves_work_and_forbids_replacement_id(setup_goal):
    owner, dispatch, runtime, goal, *_ = setup_goal
    owner.create(goal, runtime)

    async def lose_ack(*args, **kwargs):
        raise DispatchError("unknown", code="OPERATION_UNCONFIRMED")

    dispatch._dispatch = lose_ack
    with pytest.raises(DispatchError):
        anyio.run(owner.derived, child(), runtime)
    assert owner.get("goal-1", runtime)["usedTasks"] == 1
    with pytest.raises(DispatchError) as error:
        anyio.run(owner.derived, child(dispatch_id="new-id"), runtime)
    assert error.value.code == "DELEGATION_ORIGINAL_DISPATCH_REQUIRED"


@pytest.mark.parametrize("changes", [{"permission_profile": "full_access"}, {"max_tasks": True},
    {"ttl_minutes": 1441}, {"actor": "operator"}, {"targets": []}])
def test_goal_contract_rejects_unbounded_or_model_actor(changes):
    with pytest.raises(ValueError):
        GoalCreate.model_validate({"goal_id": "g", "targets": [{"project_id": "p", "agent_id": "a"}], **changes})


def test_contracts_keep_derived_write_governed_and_exact_task_display():
    from core.assistant_runtime.delegation import approval_summary
    assert contracts()["dispatch_derived"]["governed"] is True
    assert contracts()["delegation_goal_create"]["governed"] is True
    summary = approval_summary("dispatch_derived", child())
    assert summary["assistantTask"] == child()["task"]
    assert summary["assistantTargets"]["goal_id"] == "goal-1"
    assert DerivedDispatch.model_validate(child()).permission_profile == "workspace_write"


def test_revoke_linearizes_with_inflight_native_admission(setup_goal):
    owner, dispatch, runtime, goal, *_ = setup_goal
    owner.create(goal, runtime)

    async def scenario():
        entered, release, revoked = anyio.Event(), anyio.Event(), anyio.Event()
        posts = []

        async def native_admission(pid, **kwargs):
            entered.set()
            await release.wait()  # asynchronous SDK diagnostics/handshake
            assert not revoked.is_set()
            posts.append(kwargs["dispatch_id"])
            return {"dispatchId": kwargs["dispatch_id"], "nativeTaskId": "native"}

        async def revoke():
            await owner.revoke("goal-1", runtime)
            revoked.set()

        dispatch._dispatch = native_admission
        async with anyio.create_task_group() as group:
            group.start_soon(owner.derived, child(), runtime)
            await entered.wait()
            group.start_soon(revoke)
            await anyio.sleep(0)
            assert not revoked.is_set()
            release.set()
        assert revoked.is_set() and posts == ["child-1"]
        with pytest.raises(DispatchError):
            await owner.derived(child(dispatch_id="child-2", task="New work"), runtime)
        assert posts == ["child-1"]

    anyio.run(scenario)
