"""Evidence-request circuit tests: duplicate detection, rewrite, gap marker.

Covers the SCI-001 r2/r4 regression shape: a review round re-issues the same
EVIDENCE_REQUEST goal and the retrieval layer must not re-run the identical
search.  The three circuit parts are asserted separately plus the hard
zero-difference guarantee for brand-new requests.
"""

from __future__ import annotations

import copy

import pytest

from core.research.workflow.contracts import scope_hash_for
from core.web.services import (
    data_processing_service,
    team_workflow_orchestration_service,
)
from core.web.services.team_workflow.source_collection import facade
from core.web.services.team_workflow.source_collection import (
    runs as source_collection_runs,
)
from core.web.services.team_workflow.source_collection import search_circuit
from core.web.services.team_workflow.source_collection import (
    search_execution,
)

PROVIDERS = ["crossref_rest_api", "arxiv_api", "openalex_api"]

# SCI-001 r2/r4 measured goal shape: bilingual keywords, papers only,
# primary peer-reviewed evidence requested.
SCI001_SEARCH_ENVELOPE = {
    "keywords": ["大语言模型幻觉", "hallucination detection"],
    "sourceTypes": ["paper"],
    "evidenceLevels": ["primary", "peer_reviewed"],
}


def _valid_envelope() -> dict:
    scope_hash = scope_hash_for(
        program="XH-202619",
        theme="cc-gpu-operator-001",
        campaign="cc-campaign-gpu-operator-001",
        question="SCI-001",
        branch="main",
        workflow="hypothesis_and_plan",
        agent_id="agent-alpha",
        mode="formal",
    )
    return {
        "program": "XH-202619",
        "theme": "cc-gpu-operator-001",
        "campaign": "cc-campaign-gpu-operator-001",
        "question": "SCI-001",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-alpha",
        "mode": "formal",
        "scopeHash": scope_hash,
        "artifactLocator": (
            f"research-artifact://XH-202619/cc-gpu-operator-001/"
            f"cc-campaign-gpu-operator-001/main/SCI-001/{scope_hash}"
        ),
        "ledgerRoot": (
            f"research-ledger://XH-202619/cc-gpu-operator-001/"
            f"cc-campaign-gpu-operator-001/{scope_hash}"
        ),
        "cacheKey": f"scope:{scope_hash}:main:agent-alpha",
    }


# ---------------------------------------------------------------------------
# Part 1: duplicate detection (pure kernel).
# ---------------------------------------------------------------------------


def test_goal_key_is_order_and_case_insensitive():
    key_a = search_circuit.canonical_goal_key(SCI001_SEARCH_ENVELOPE)
    key_b = search_circuit.canonical_goal_key(
        {
            "keywords": ["Hallucination Detection", " 大语言模型幻觉 "],
            "sourceTypes": ["PAPER"],
            "evidenceLevels": ["peer_reviewed", "primary"],
        }
    )
    assert key_a == key_b


def test_goal_key_differs_for_new_keyword_or_levels():
    base = search_circuit.canonical_goal_key(SCI001_SEARCH_ENVELOPE)
    new_keyword = search_circuit.canonical_goal_key(
        {**SCI001_SEARCH_ENVELOPE, "keywords": [*SCI001_SEARCH_ENVELOPE["keywords"], "rag evaluation"]}
    )
    new_levels = search_circuit.canonical_goal_key(
        {**SCI001_SEARCH_ENVELOPE, "evidenceLevels": ["primary"]}
    )
    assert base != new_keyword
    assert base != new_levels


def test_first_duplicate_decides_rewrite_then_exhausts_after_n_zero_rewrites():
    goal_key = search_circuit.canonical_goal_key(SCI001_SEARCH_ENVELOPE)
    entries: list[dict] = []

    first = search_circuit.decide_circuit_action(
        entries, SCI001_SEARCH_ENVELOPE, providers=PROVIDERS
    )
    assert first["action"] == "execute_original"

    # r2 executed and added five (off-topic) records.
    entry_original = search_circuit.new_attempt_entry(
        goal_key=goal_key,
        goal_scope="question:sci-001",
        question="SCI-001",
        run_id="dprun-r2",
        search_envelope=SCI001_SEARCH_ENVELOPE,
        fingerprint="fp",
        attempt_kind="original",
        now_iso="2026-09-01T00:00:00Z",
    )
    entries.append(
        search_circuit.apply_attempt_outcome(
            [entry_original],
            "dprun-r2",
            {"status": "executed", "recordCount": 5, "resultCount": 5},
            now_iso="2026-09-01T00:05:00Z",
        )[0]
    )

    # r4 repeats the same goal: must not re-run the identical search.
    second = search_circuit.decide_circuit_action(
        entries, SCI001_SEARCH_ENVELOPE, providers=PROVIDERS
    )
    assert second["action"] == "execute_rewrite"
    assert second["variantIndex"] == 1
    assert second["variant"]["strategy"] == "keyword_synonym_expansion"

    # Each rewrite executes but keeps adding zero new relevant records.
    run_ids = ["dprun-r4", "dprun-r6", "dprun-r8"]
    decision = second
    for index, run_id in enumerate(run_ids, start=1):
        variant = decision["variant"]
        entry = search_circuit.new_attempt_entry(
            goal_key=goal_key,
            goal_scope="question:sci-001",
            question="SCI-001",
            run_id=run_id,
            search_envelope=variant["searchEnvelope"],
            fingerprint="fp",
            attempt_kind="rewrite",
            variant_index=decision["variantIndex"],
            strategy=variant["strategy"],
            now_iso="2026-09-01T00:00:00Z",
        )
        entries.append(
            search_circuit.apply_attempt_outcome(
                [entry], run_id, {"status": "executed", "recordCount": 0}, now_iso="2026-09-01T01:00:00Z"
            )[0]
        )
        decision = search_circuit.decide_circuit_action(
            entries, SCI001_SEARCH_ENVELOPE, providers=PROVIDERS
        )
        if index < 3:
            assert decision["action"] == "execute_rewrite"
            assert decision["variantIndex"] == index + 1

    # N=3 zero-new rewrites later: the rewrite space is exhausted.
    assert decision["action"] == "mark_unavailable"
    assert decision["latestAttemptRunId"] == "dprun-r8"
    assert len(decision["attempts"]) == 4


def test_in_flight_attempt_is_reused_not_restarted():
    goal_key = search_circuit.canonical_goal_key(SCI001_SEARCH_ENVELOPE)
    entry = search_circuit.new_attempt_entry(
        goal_key=goal_key,
        goal_scope="question:sci-001",
        question="SCI-001",
        run_id="dprun-r2",
        search_envelope=SCI001_SEARCH_ENVELOPE,
        fingerprint="fp",
        attempt_kind="original",
        now_iso="2026-09-01T00:00:00Z",
    )
    decision = search_circuit.decide_circuit_action(
        [entry], SCI001_SEARCH_ENVELOPE, providers=PROVIDERS
    )
    assert decision["action"] == "reuse_in_flight"
    assert decision["runId"] == "dprun-r2"


def test_a_fruitful_rewrite_keeps_the_circuit_open():
    goal_key = search_circuit.canonical_goal_key(SCI001_SEARCH_ENVELOPE)
    entry = search_circuit.new_attempt_entry(
        goal_key=goal_key,
        goal_scope="question:sci-001",
        question="SCI-001",
        run_id="dprun-r2",
        search_envelope=SCI001_SEARCH_ENVELOPE,
        fingerprint="fp",
        attempt_kind="original",
        now_iso="2026-09-01T00:00:00Z",
    )
    entry = search_circuit.apply_attempt_outcome(
        [entry], "dprun-r2", {"status": "executed", "recordCount": 5}, now_iso="2026-09-01T00:05:00Z"
    )[0]
    rewrite = search_circuit.new_attempt_entry(
        goal_key=goal_key,
        goal_scope="question:sci-001",
        question="SCI-001",
        run_id="dprun-r4",
        search_envelope=SCI001_SEARCH_ENVELOPE,
        fingerprint="fp",
        attempt_kind="rewrite",
        variant_index=1,
        strategy="keyword_synonym_expansion",
        now_iso="2026-09-01T00:10:00Z",
    )
    rewrite = search_circuit.apply_attempt_outcome(
        [rewrite], "dprun-r4", {"status": "executed", "recordCount": 2}, now_iso="2026-09-01T00:20:00Z"
    )[0]
    decision = search_circuit.decide_circuit_action(
        [entry, rewrite], SCI001_SEARCH_ENVELOPE, providers=PROVIDERS
    )
    assert decision["action"] == "execute_rewrite"
    assert decision["variantIndex"] == 2


# ---------------------------------------------------------------------------
# Part 2: rewrite variant generation (deterministic rules, no LLM).
# ---------------------------------------------------------------------------


def test_rewrite_variants_cover_the_three_contract_strategies():
    variants = search_circuit.build_rewrite_variants(
        SCI001_SEARCH_ENVELOPE, providers=PROVIDERS
    )
    strategies = [variant["strategy"] for variant in variants]
    assert "keyword_synonym_expansion" in strategies
    assert "provider_priority_rotation" in strategies
    assert "evidence_level_relaxation" in strategies
    assert len(variants) <= search_circuit.DEFAULT_MAX_REWRITE_ATTEMPTS
    # Every variant must differ from the original goal identity.
    original_key = search_circuit.canonical_goal_key(SCI001_SEARCH_ENVELOPE)
    for variant in variants:
        assert search_circuit.canonical_goal_key(variant["searchEnvelope"]) != original_key
        assert variant["querySeeds"]


def test_keyword_expansion_adds_table_synonyms_only():
    variants = search_circuit.build_rewrite_variants(
        SCI001_SEARCH_ENVELOPE, providers=PROVIDERS
    )
    expansion = next(
        v for v in variants if v["strategy"] == "keyword_synonym_expansion"
    )
    keywords = expansion["searchEnvelope"]["keywords"]
    assert "大语言模型幻觉" in keywords
    assert any("幻觉" in keyword or "hallucination" in keyword for keyword in keywords)
    assert keywords != sorted(SCI001_SEARCH_ENVELOPE["keywords"])


def test_provider_rotation_and_relaxation_change_order_and_levels():
    variants = search_circuit.build_rewrite_variants(
        SCI001_SEARCH_ENVELOPE, providers=PROVIDERS
    )
    rotation = next(v for v in variants if v["strategy"] == "provider_priority_rotation")
    relaxation = next(v for v in variants if v["strategy"] == "evidence_level_relaxation")
    assert rotation["providerOrder"][0] != PROVIDERS[0]
    assert set(rotation["providerOrder"]) == set(PROVIDERS)
    assert "secondary" in rotation["searchEnvelope"]["evidenceLevels"]
    assert set(relaxation["providerOrder"]) == set(PROVIDERS)
    assert relaxation["providerOrder"] != rotation["providerOrder"]
    assert "preprint" in relaxation["searchEnvelope"]["evidenceLevels"]
    # Different seeds per variant: rewrites execute genuinely new queries.
    seeds_by_strategy = {v["strategy"]: set(v["querySeeds"]) for v in variants}
    assert seeds_by_strategy["provider_priority_rotation"] != seeds_by_strategy["keyword_synonym_expansion"]


# ---------------------------------------------------------------------------
# Part 3: evidence_gap_unavailable marker shape.
# ---------------------------------------------------------------------------


def test_marker_carries_goal_attempts_and_reasons_summary():
    goal_key = search_circuit.canonical_goal_key(SCI001_SEARCH_ENVELOPE)
    entry = search_circuit.new_attempt_entry(
        goal_key=goal_key,
        goal_scope="question:sci-001",
        question="SCI-001",
        run_id="dprun-r2",
        search_envelope=SCI001_SEARCH_ENVELOPE,
        fingerprint="fp",
        attempt_kind="original",
        now_iso="2026-09-01T00:00:00Z",
    )
    entry = search_circuit.apply_attempt_outcome(
        [entry],
        "dprun-r2",
        {
            "status": "executed",
            "recordCount": 0,
            "resultCount": 5,
            "rejectedResultCount": 3,
            "skippedDuplicateCount": 2,
        },
        now_iso="2026-09-01T00:05:00Z",
    )[0]
    marker = search_circuit.build_evidence_gap_marker(
        goal_key=goal_key,
        goal_scope="question:sci-001",
        question="SCI-001",
        original_search_envelope=SCI001_SEARCH_ENVELOPE,
        attempts=[entry],
        latest_attempt_run_id="dprun-r2",
        now_iso="2026-09-01T02:00:00Z",
    )
    assert marker["marker"] == "evidence_gap_unavailable"
    assert marker["originalSearchEnvelope"] == {
        "keywords": ["hallucination detection", "大语言模型幻觉"],
        "sourceTypes": ["paper"],
        "evidenceLevels": ["peer_reviewed", "primary"],
    }
    assert marker["attempts"][0]["runId"] == "dprun-r2"
    assert marker["attempts"][0]["outcome"]["rejectedResultCount"] == 3
    summary = marker["unavailableReasonsSummary"]
    assert summary["resultCount"] == 5
    assert summary["rejectedResultCount"] == 3
    assert summary["skippedDuplicateCount"] == 2
    assert summary["newRecordCount"] == 0
    assert summary["summary"]


def test_exhausted_duplicate_result_maps_to_completed_terminal():
    marker = {"marker": "evidence_gap_unavailable", "markerId": "scrgap-1"}
    result = search_circuit.build_exhausted_duplicate_result(
        marker,
        run={"runId": "dprun-r8"},
        run_status=None,
        assignments=[{"assignmentId": "a1"}],
    )
    assert result["status"] == "evidence_gap_unavailable"
    assert result["executedQueryCount"] == 0
    assert result["attemptedQueryCount"] == 0
    assert result["evidenceGap"]["markerId"] == "scrgap-1"
    terminal = team_workflow_orchestration_service._source_collection_work_run_terminal_status(
        result
    )
    # The chain bridge only handoffs on "completed"; the marker result must
    # never wedge the collection request in recovery.
    assert terminal == "completed"


# ---------------------------------------------------------------------------
# Facade wiring: dedupe on ensure, rewrite run creation, unavailable response.
# ---------------------------------------------------------------------------


class _MemoryStore:
    def __init__(self):
        self.store: dict = {"entries": [], "markers": []}

    def install(self, monkeypatch):
        monkeypatch.setattr(search_circuit, "load_circuit_store", lambda team_id: copy.deepcopy(self.store))
        monkeypatch.setattr(search_circuit, "save_circuit_store", self._save)
        monkeypatch.setattr(facade, "_search_providers", lambda: list(PROVIDERS))
        monkeypatch.setattr(facade, "_utc_now_iso", lambda: "2026-09-01T00:00:00Z")
        monkeypatch.setattr(facade, "_record_circuit_workflow_event", lambda *a, **k: None)
        # The facade only trusts ledger entries whose run is verifiably open;
        # fake run ids simulate live runs here.
        monkeypatch.setattr(
            facade,
            "_circuit_live_run",
            lambda team_id, run_id: {"runId": run_id, "status": "collecting"} if run_id else None,
        )

    def _save(self, team_id, store):
        self.store = copy.deepcopy(store)


def _install_facade(monkeypatch, store: _MemoryStore, run_ids: list[str]):
    store.install(monkeypatch)
    created_payloads: list[dict] = []
    counter = {"n": 0}

    def fake_start_run(team_id, payload):
        counter["n"] += 1
        run_id = run_ids[counter["n"] - 1] if counter["n"] <= len(run_ids) else f"dprun-extra-{counter['n']}"
        created_payloads.append({"teamId": team_id, "payload": payload, "runId": run_id})
        return {"run": {"runId": run_id}}

    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        lambda **kwargs: {"runs": []},
    )
    monkeypatch.setattr(
        source_collection_runs,
        "start_source_collection_run",
        fake_start_run,
    )
    monkeypatch.setattr(
        source_collection_runs,
        "get_source_collection_summary",
        lambda team_id, *, run_id: {
            "status": "collecting",
            "runId": run_id,
            "runStatus": {"status": "collecting"},
            "summary": {"recordCount": 0},
            "stageCards": [],
        },
    )
    return created_payloads


def test_facade_ensure_normal_path_stays_byte_compatible(monkeypatch):
    store = _MemoryStore()
    created = _install_facade(monkeypatch, store, ["dprun-r2"])
    result = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=SCI001_SEARCH_ENVELOPE,
        team_id="research-team",
    )
    # Exact legacy ensure response shape for a brand-new request.
    assert result["status"] == "ok"
    assert result["created"] is True
    assert result["idempotent"] is False
    assert result["found"] is False
    assert "evidenceGap" not in result
    assert "searchRewrite" not in result
    assert "evidenceCircuit" not in result
    # The created run payload must not carry any circuit-only fields.
    payload = created[0]["payload"]
    assert "searchCircuit" not in payload
    assert "querySeeds" not in payload
    assert payload["searchEnvelopeFingerprint"]
    # The ledger still records the attempt for future duplicate detection.
    assert len(store.store["entries"]) == 1
    assert store.store["entries"][0]["attemptKind"] == "original"
    assert store.store["entries"][0]["runId"] == "dprun-r2"


def test_facade_ensure_duplicate_creates_rewrite_run(monkeypatch):
    store = _MemoryStore()
    created = _install_facade(monkeypatch, store, ["dprun-r2", "dprun-r4"])
    facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=SCI001_SEARCH_ENVELOPE,
        team_id="research-team",
    )
    # r2 executed and added records; then r4 repeats the same goal.
    store.store["entries"] = search_circuit.apply_attempt_outcome(
        store.store["entries"],
        "dprun-r2",
        {"status": "executed", "recordCount": 5},
        now_iso="2026-09-01T00:05:00Z",
    )
    result = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=SCI001_SEARCH_ENVELOPE,
        team_id="research-team",
    )
    assert result["created"] is True
    assert result["searchRewrite"]["attemptKind"] == "rewrite"
    assert result["searchRewrite"]["variantIndex"] == 1
    rewrite_payload = created[1]["payload"]
    assert rewrite_payload["searchCircuit"]["attemptKind"] == "rewrite"
    assert rewrite_payload["searchCircuit"]["baseGoalKey"]
    assert rewrite_payload["searchCircuit"]["querySeeds"]
    assert rewrite_payload["querySeeds"]
    assert len(store.store["entries"]) == 2
    assert store.store["entries"][1]["attemptKind"] == "rewrite"


def test_facade_ensure_exhausted_goal_marks_gap_and_skips_run(monkeypatch):
    store = _MemoryStore()
    created = _install_facade(monkeypatch, store, ["dprun-r2", "dprun-r4", "dprun-r6", "dprun-r8"])
    goal_key = search_circuit.canonical_goal_key(SCI001_SEARCH_ENVELOPE)

    def drive(run_id: str, record_count: int) -> None:
        result = facade.research_knowledge_collection_facade(
            action="ensure",
            scope=_valid_envelope(),
            searchEnvelope=SCI001_SEARCH_ENVELOPE,
            team_id="research-team",
        )
        assert result["locator"]["runId"] == run_id
        store.store["entries"] = search_circuit.apply_attempt_outcome(
            store.store["entries"],
            run_id,
            {"status": "executed", "recordCount": record_count},
            now_iso="2026-09-01T01:00:00Z",
        )

    drive("dprun-r2", 5)
    drive("dprun-r4", 0)
    drive("dprun-r6", 0)
    drive("dprun-r8", 0)
    assert len(created) == 4

    exhausted = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=SCI001_SEARCH_ENVELOPE,
        team_id="research-team",
    )
    assert exhausted["status"] == "evidence_gap_unavailable"
    assert exhausted["created"] is False
    assert len(created) == 4  # no fifth run was created
    marker = exhausted["evidenceGap"]
    assert marker["marker"] == "evidence_gap_unavailable"
    assert marker["goalKey"] == goal_key
    assert marker["latestAttemptRunId"] == "dprun-r8"
    assert exhausted["locator"]["runId"] == "dprun-r8"
    assert marker["attempts"][-1]["outcome"]["newRecordCount"] == 0
    # Marker persisted for the review-side consumer.
    assert store.store["markers"][-1]["goalKey"] == goal_key


def test_facade_ignores_stale_ledger_entry_with_unverifiable_run(monkeypatch):
    """A ledger entry whose run is gone must never gate a fresh collection.

    Regression shape: the circuit ledger survived on disk while the referenced
    run did not (unit-test fake or aborted creation).  Without the liveness
    gate the stale ``starting`` entry hijacks every later ensure into
    ``reuse_in_flight`` and no run is ever created again.
    """
    store = _MemoryStore()
    created = _install_facade(monkeypatch, store, ["dprun-r2"])
    store.store["entries"] = [
        search_circuit.new_attempt_entry(
            goal_key=search_circuit.canonical_goal_key(SCI001_SEARCH_ENVELOPE),
            goal_scope="question:sci-001",
            question="SCI-001",
            run_id="dprun-vanished",
            search_envelope=SCI001_SEARCH_ENVELOPE,
            fingerprint="fp",
            attempt_kind="original",
            now_iso="2026-08-30T00:00:00Z",
        )
    ]
    # The real run store cannot verify this run (dead/never existed).
    monkeypatch.setattr(facade, "_circuit_live_run", lambda team_id, run_id: None)

    result = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=SCI001_SEARCH_ENVELOPE,
        team_id="research-team",
    )
    assert result["status"] == "ok"
    assert result["created"] is True
    assert "evidenceCircuit" not in result
    assert created[0]["runId"] == "dprun-r2"


def test_facade_skips_ledger_append_when_run_unverifiable(monkeypatch):
    """No ledger entry is persisted for a run the run store cannot confirm.

    Keeps the circuit ledger free of phantom attempts (legacy facade tests
    with faked run creation must not write runtime state).
    """
    store = _MemoryStore()
    created = _install_facade(monkeypatch, store, ["dprun-r2"])
    monkeypatch.setattr(facade, "_circuit_live_run", lambda team_id, run_id: None)

    result = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=_valid_envelope(),
        searchEnvelope=SCI001_SEARCH_ENVELOPE,
        team_id="research-team",
    )
    assert result["created"] is True
    assert created[0]["runId"] == "dprun-r2"
    assert store.store["entries"] == []
    assert store.store["markers"] == []


# ---------------------------------------------------------------------------
# Executor wiring: provider order override + exhausted duplicate replay.
# ---------------------------------------------------------------------------


def test_circuit_provider_order_helper_reads_only_circuit_runs():
    assert (
        search_execution._source_collection_circuit_provider_order(
            {"metadata": {"searchEnvelopeFingerprint": "fp"}}
        )
        == []
    )
    assert search_execution._source_collection_circuit_provider_order({}) == []
    order = search_execution._source_collection_circuit_provider_order(
        {
            "metadata": {
                "searchCircuit": {
                    "providerOrder": [
                        "openalex_api",
                        "crossref_rest_api",
                        "arxiv_api",
                        "not_a_provider",
                    ]
                }
            }
        }
    )
    assert order == ["openalex_api", "crossref_rest_api", "arxiv_api"]


def test_apply_attempt_outcome_is_idempotent_per_run():
    entry = search_circuit.new_attempt_entry(
        goal_key="g",
        goal_scope="question:sci-001",
        question="SCI-001",
        run_id="dprun-r2",
        search_envelope=SCI001_SEARCH_ENVELOPE,
        fingerprint="fp",
        attempt_kind="original",
        now_iso="2026-09-01T00:00:00Z",
    )
    once = search_circuit.apply_attempt_outcome(
        [entry],
        "dprun-r2",
        {"status": "executed", "recordCount": 5},
        now_iso="2026-09-01T00:05:00Z",
    )
    twice = search_circuit.apply_attempt_outcome(
        once,
        "dprun-r2",
        {"status": "executed", "recordCount": 9},
        now_iso="2026-09-01T00:06:00Z",
    )
    assert twice[0]["outcome"]["newRecordCount"] == 5


def test_unrelated_run_outcome_is_ignored():
    entry = search_circuit.new_attempt_entry(
        goal_key="g",
        goal_scope="question:sci-001",
        question="SCI-001",
        run_id="dprun-r2",
        search_envelope=SCI001_SEARCH_ENVELOPE,
        fingerprint="fp",
        attempt_kind="original",
        now_iso="2026-09-01T00:00:00Z",
    )
    unchanged = search_circuit.apply_attempt_outcome(
        [entry],
        "dprun-other",
        {"status": "executed", "recordCount": 5},
        now_iso="2026-09-01T00:05:00Z",
    )
    assert unchanged[0]["status"] == "starting"
    assert unchanged[0]["outcome"] == {}


@pytest.mark.parametrize(
    "module",
    [facade, source_collection_runs, search_execution, search_circuit],
)
def test_circuit_modules_import_cleanly(module):
    assert module is not None


# ---------------------------------------------------------------------------
# Full-stack replay: an exhausted goal's run never repeats provider search.
# ---------------------------------------------------------------------------


def test_execute_search_replays_exhausted_goal_with_zero_queries(tmp_path, monkeypatch):
    """Re-executing an exhausted goal's run returns the gap marker, runs nothing.

    This is the consumer-facing shape on the collection run status: terminal
    status completed (the chain bridge handoffs), counts at zero, and the
    evidenceGapUnavailable/evidenceGapMarkerId fields persisted on the work
    run snapshot.
    """
    from core.web.services import team_service
    from tests._support.team_workflow.helpers import (
        _use_fake_local_research_config,
        _use_tmp_project_root,
    )

    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "large language model hallucination",
            "querySeeds": ["large language model hallucination"],
            "agentRoles": ["source_finder"],
        },
    )
    run_id = run_response["run"]["runId"]
    marker = search_circuit.build_evidence_gap_marker(
        goal_key=search_circuit.canonical_goal_key(SCI001_SEARCH_ENVELOPE),
        goal_scope="question:sci-001",
        question="SCI-001",
        original_search_envelope=SCI001_SEARCH_ENVELOPE,
        attempts=[],
        latest_attempt_run_id=run_id,
        now_iso="2026-09-01T02:00:00Z",
        marker_id="scrgap-test-1",
    )
    search_circuit.record_evidence_gap_marker(team["teamId"], marker)

    persisted = []
    real_persist = team_workflow_orchestration_service._persist_source_collection_work_run

    def capture_persist(*args, **kwargs):
        snapshot = real_persist(*args, **kwargs)
        persisted.append(snapshot)
        return snapshot

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_persist_source_collection_work_run",
        capture_persist,
    )

    execution = team_workflow_orchestration_service.execute_source_collection_search(
        team["teamId"],
        run_id,
        {"maxQueries": 1, "maxResultsPerQuery": 2},
    )
    assert execution["status"] == "evidence_gap_unavailable"
    assert execution["attemptedQueryCount"] == 0
    assert execution["executedQueryCount"] == 0
    assert execution["recordCount"] == 0
    assert execution["evidenceGap"]["markerId"] == "scrgap-test-1"
    # A replay must not have created records or imported candidates.
    assert data_processing_service.list_records(run_id)["records"] == []
    # The terminal work run snapshot carries the circuit verdict for consumers.
    terminal = persisted[-1]
    assert terminal["status"] == "completed"
    assert terminal["evidenceGapUnavailable"] is True
    assert terminal["evidenceGapMarkerId"] == "scrgap-test-1"
    assert terminal["executedQueryCount"] == 0
    assert terminal["recordCount"] == 0
    # The marker stays queryable from the ledger for the review-side consumer.
    stored = search_circuit.load_circuit_store(team["teamId"])
    assert stored["markers"][-1]["marker"] == "evidence_gap_unavailable"
    assert stored["markers"][-1]["latestAttemptRunId"] == run_id
