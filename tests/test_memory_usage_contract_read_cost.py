from __future__ import annotations

import threading
from collections import Counter
from pathlib import Path

from core.web.services import memory_service, team_knowledge_service


class _ObservedBuildLock:
    """Expose the waiter's arrival without relying on scheduler timing."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._attempt_lock = threading.Lock()
        self._attempts = 0
        self.second_attempt = threading.Event()

    def __enter__(self) -> _ObservedBuildLock:
        with self._attempt_lock:
            self._attempts += 1
            if self._attempts >= 2:
                self.second_attempt.set()
        self._lock.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._lock.release()


def _prepare_usage_contract_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(memory_service, "PROJECT_ROOT", tmp_path)
    memory_service._clear_memory_usage_contract_cache()
    monkeypatch.setattr(memory_service, "_record_memory_contract_viewed_event", lambda *_args, **_kwargs: None)


def _install_source_fakes(monkeypatch, calls: Counter[str], *, overview) -> None:
    def counted(name: str, result: dict):
        def call(**_kwargs):
            calls[name] += 1
            return result

        return call

    monkeypatch.setattr(team_knowledge_service, "list_knowledge_overview", overview)
    monkeypatch.setattr(
        team_knowledge_service,
        "get_knowledge_operations_health",
        counted("health", {"summary": {"knowledgeBaseCount": 2, "findingCount": 1}}),
    )
    monkeypatch.setattr(
        team_knowledge_service,
        "get_knowledge_governance_plan",
        counted(
            "plan",
            {
                "summary": {"actionCount": 3},
                "operatingBoundary": {"formalKnowledgeRequiresReviewer": True},
            },
        ),
    )


def test_concurrent_usage_contract_cache_misses_share_one_build(tmp_path, monkeypatch):
    _prepare_usage_contract_cache(tmp_path, monkeypatch)
    calls: Counter[str] = Counter()
    overview_entered = threading.Event()
    release_overview = threading.Event()
    events: list[bool] = []

    def overview(*, internal=False):
        calls["overview"] += 1
        overview_entered.set()
        assert release_overview.wait(timeout=5)
        return {"summary": {"knowledgeBaseCount": 2, "itemCount": 7}}

    _install_source_fakes(monkeypatch, calls, overview=overview)
    monkeypatch.setattr(
        memory_service,
        "_record_memory_contract_viewed_event",
        lambda _contract, *, cache_hit, duration_ms: events.append(cache_hit),
    )
    build_lock = _ObservedBuildLock()
    monkeypatch.setattr(memory_service, "MEMORY_USAGE_CONTRACT_BUILD_LOCK", build_lock)
    results: list[dict] = []
    errors: list[BaseException] = []

    def request() -> None:
        try:
            results.append(memory_service.get_memory_usage_contract())
        except BaseException as exc:  # surfaced in the test thread below
            errors.append(exc)

    leader = threading.Thread(target=request)
    waiter = threading.Thread(target=request)
    leader.start()
    try:
        assert overview_entered.wait(timeout=5)
        waiter.start()
        assert build_lock.second_attempt.wait(timeout=5)
    finally:
        release_overview.set()
        leader.join(timeout=5)
        if waiter.ident is not None:
            waiter.join(timeout=5)

    assert not leader.is_alive()
    assert not waiter.is_alive()
    assert not errors
    assert calls == Counter({"overview": 1, "health": 1, "plan": 1})
    assert sorted(events) == [False, True]
    assert len(results) == 2
    assert all(result["currentState"]["knowledge"]["knowledgeBaseCount"] == 2 for result in results)
    assert all(result["currentState"]["knowledge"]["itemCount"] == 7 for result in results)
    assert all(result["currentState"]["governancePlan"]["actionCount"] == 3 for result in results)


def test_failed_usage_contract_build_is_retried_instead_of_cached(tmp_path, monkeypatch):
    _prepare_usage_contract_cache(tmp_path, monkeypatch)
    calls: Counter[str] = Counter()

    def overview(*, internal=False):
        calls["overview"] += 1
        if calls["overview"] == 1:
            raise OSError("temporary source read failure")
        return {"summary": {"knowledgeBaseCount": 1, "itemCount": 4}}

    _install_source_fakes(monkeypatch, calls, overview=overview)

    failed_result = memory_service.get_memory_usage_contract()
    recovered_result = memory_service.get_memory_usage_contract()

    assert failed_result["currentState"]["knowledge"] == {}
    assert recovered_result["currentState"]["knowledge"]["knowledgeBaseCount"] == 1
    assert recovered_result["currentState"]["knowledge"]["itemCount"] == 4
    assert calls == Counter({"overview": 2, "health": 1, "plan": 1})


def test_explicit_usage_contract_cache_clear_forces_a_fresh_build(tmp_path, monkeypatch):
    _prepare_usage_contract_cache(tmp_path, monkeypatch)
    calls: Counter[str] = Counter()

    def overview(*, internal=False):
        calls["overview"] += 1
        return {"summary": {"knowledgeBaseCount": calls["overview"]}}

    _install_source_fakes(monkeypatch, calls, overview=overview)

    first = memory_service.get_memory_usage_contract()
    cached = memory_service.get_memory_usage_contract()
    memory_service._clear_memory_usage_contract_cache()
    refreshed = memory_service.get_memory_usage_contract()

    assert first["currentState"]["knowledge"]["knowledgeBaseCount"] == 1
    assert cached["currentState"]["knowledge"]["knowledgeBaseCount"] == 1
    assert refreshed["currentState"]["knowledge"]["knowledgeBaseCount"] == 2
    assert calls == Counter({"overview": 2, "health": 2, "plan": 2})


def test_usage_contract_reuses_health_for_governance_plan_without_changing_summary(tmp_path, monkeypatch):
    _prepare_usage_contract_cache(tmp_path, monkeypatch)
    calls: Counter[str] = Counter()
    overview = {"summary": {"knowledgeBaseCount": 3, "itemCount": 11}}
    health = {
        "summary": {
            "knowledgeBaseCount": 3,
            "findingCount": 2,
            "corruptJsonlLineCount": 0,
            "storageReadErrorCount": 0,
        },
        "findings": [
            {
                "findingType": "unrated_items",
                "findingId": "health-finding-1",
                "knowledgeBaseId": "kb-1",
                "knowledgeBaseName": "Research",
            }
        ],
    }

    def build_health(*, agent_id="", internal=False):
        calls["health"] += 1
        return health

    def build_workbench(*, agent_id="", limit=12, internal=False):
        calls["workbench"] += 1
        return {"nextActions": [], "summary": {"recommendationCount": 4}}

    original_build_plan = team_knowledge_service._build_knowledge_governance_plan
    health_received_by_plan: list[dict] = []

    def capture_health_for_plan(**kwargs):
        health_received_by_plan.append(kwargs.get("health"))
        return original_build_plan(**kwargs)

    monkeypatch.setattr(
        team_knowledge_service,
        "list_knowledge_overview",
        lambda *, internal=False: calls.update(overview=1) or overview,
    )
    monkeypatch.setattr(team_knowledge_service, "_build_knowledge_operations_health", build_health)
    monkeypatch.setattr(team_knowledge_service, "_build_knowledge_steward_workbench", build_workbench)
    monkeypatch.setattr(team_knowledge_service, "_build_knowledge_governance_plan", capture_health_for_plan)
    monkeypatch.setattr(team_knowledge_service, "_record_event", lambda *_args, **_kwargs: None)

    contract = memory_service.get_memory_usage_contract()

    assert calls == Counter({"overview": 1, "health": 1, "workbench": 1})
    assert health_received_by_plan == [health]
    assert health_received_by_plan[0] is health
    assert contract["currentState"] == {
        "knowledge": overview["summary"],
        "operationsHealth": health["summary"],
        "governancePlan": {
            "actionCount": 1,
            "healthFindingCount": 2,
            "workbenchRecommendationCount": 4,
        },
        "operatingBoundary": {
            "canDirectlyApplyKnowledge": False,
            "canDeleteKnowledge": False,
            "canChangeAcl": False,
            "canBypassReviewer": False,
            "formalKnowledgeRequiresReviewer": True,
            "planOnly": True,
        },
    }


def test_cache_clear_during_build_prevents_stale_payload_from_waking_waiter(tmp_path, monkeypatch):
    _prepare_usage_contract_cache(tmp_path, monkeypatch)
    calls: Counter[str] = Counter()
    calls_lock = threading.Lock()
    first_overview_entered = threading.Event()
    release_first_overview = threading.Event()
    events: list[bool] = []

    def overview(*, internal=False):
        with calls_lock:
            calls["overview"] += 1
            call_number = calls["overview"]
        if call_number == 1:
            first_overview_entered.set()
            assert release_first_overview.wait(timeout=5)
        return {"summary": {"knowledgeBaseCount": call_number}}

    _install_source_fakes(monkeypatch, calls, overview=overview)
    monkeypatch.setattr(
        memory_service,
        "_record_memory_contract_viewed_event",
        lambda _contract, *, cache_hit, duration_ms: events.append(cache_hit),
    )
    build_lock = _ObservedBuildLock()
    monkeypatch.setattr(memory_service, "MEMORY_USAGE_CONTRACT_BUILD_LOCK", build_lock)
    results: dict[str, dict] = {}
    errors: list[BaseException] = []

    def request(name: str) -> None:
        try:
            results[name] = memory_service.get_memory_usage_contract()
        except BaseException as exc:  # surfaced in the test thread below
            errors.append(exc)

    leader = threading.Thread(target=request, args=("leader",))
    waiter = threading.Thread(target=request, args=("waiter",))
    leader.start()
    try:
        assert first_overview_entered.wait(timeout=5)
        memory_service._clear_memory_usage_contract_cache()
        waiter.start()
        assert build_lock.second_attempt.wait(timeout=5)
    finally:
        release_first_overview.set()
        leader.join(timeout=5)
        if waiter.ident is not None:
            waiter.join(timeout=5)

    assert not leader.is_alive()
    assert not waiter.is_alive()
    assert not errors
    assert results["leader"]["currentState"]["knowledge"]["knowledgeBaseCount"] == 1
    assert results["waiter"]["currentState"]["knowledge"]["knowledgeBaseCount"] == 2
    assert calls == Counter({"overview": 2, "health": 2, "plan": 2})
    assert events.count(False) == 2

    cached = memory_service.get_memory_usage_contract()
    assert cached["currentState"]["knowledge"]["knowledgeBaseCount"] == 2
    assert calls == Counter({"overview": 2, "health": 2, "plan": 2})
    assert events.count(True) == 1
