"""Backfill of the cross-run feedback_iterations authority from round chains.

Production break (run-332a539909a6): a challenge formal run failed result
packaging with ``canonical feedback_iterations contains no actual revision``
while the hypothesis-first round store held a complete, truthful revision
lineage (ten linked rounds, every ``revisionEnvelope`` an actual review
revision) — the canonical artifacts simply never landed for the run's
authority.  These tests pin the recovery: the sweep replays the stored chain
through the canonical writer so ``result_package_v2._feedback_iterations``'
cross-run walk returns N contiguous rows, and stays fail-closed (no partial
chains, nothing synthesized) on incomplete evidence.

The shared artifact store is replaced with an in-memory append-only double
(the same seam the canonical-writer contract tests use).
"""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from core.web.services.team_workflow.research_runtime import (
    feedback_iterations_artifact_writer as writer,
)
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import (
    result_package_v2,
    workflow_artifact_store,
)

_TEAM_ID = "team-feedback-backfill"
_QUESTION_ID = "SCI-009"
_FORMAL_RUN_ID = "run-332a539909a6"
_AUTHORITY_ID = "dprun-20260908162239665012-2cd75f2c"
_NODE_RUN_ID = f"nr-{_FORMAL_RUN_ID}-hypothesis_design-a1"
_CHAIN_LENGTH = 10
_ROUND_IDS = [f"hround-{index:02x}" for index in range(1, _CHAIN_LENGTH + 1)]


class _MemoryArtifactStore:
    """Append-only double of the scoped workflow artifact store."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def list(self, _team_id: str, **kwargs) -> list[dict[str, Any]]:
        want_wf = str(kwargs.get("workflow_run_id") or "").strip()
        want_sc = str(kwargs.get("source_collection_run_id") or "").strip()
        matched = []
        for row in self.rows:
            if want_wf and row["workflowRunId"] != want_wf:
                continue
            if want_sc and row["sourceCollectionRunId"] != want_sc:
                continue
            matched.append(deepcopy(row))
        return matched

    def put(self, _team_id: str, **kwargs) -> dict[str, Any]:
        identity = kwargs["artifact_identity"]
        content_hash = writer.canonical_sha256(kwargs["payload"])
        for row in self.rows:
            if row["recordId"] == identity:
                if row["contentHash"] != content_hash:
                    raise AssertionError(
                        "immutable artifact identity replayed with new content"
                    )
                return deepcopy(row)
        record = {
            "recordId": identity,
            "kind": kwargs["kind"],
            "workflowRunId": kwargs["workflow_run_id"],
            "sourceCollectionRunId": kwargs["source_collection_run_id"],
            "contentHash": content_hash,
            "payload": deepcopy(kwargs["payload"]),
        }
        self.rows.append(record)
        return deepcopy(record)


def _patch_store(monkeypatch: pytest.MonkeyPatch) -> _MemoryArtifactStore:
    store = _MemoryArtifactStore()
    monkeypatch.setattr(writer, "list_workflow_artifacts", store.list)
    monkeypatch.setattr(writer, "put_workflow_artifact", store.put)
    monkeypatch.setattr(
        workflow_artifact_store, "list_workflow_artifacts", store.list
    )
    return store


def _hex(index: int) -> str:
    return f"{index % 100:02d}" * 32


def _round_record(
    index: int,
    *,
    status: str = "closed",
    actual: bool = True,
    human_feedback: str = "",
    lineage: list[dict[str, str]] | None = None,
    with_envelope: bool = True,
) -> dict[str, Any]:
    round_id = _ROUND_IDS[index - 1]
    candidates = [
        {
            "candidateId": f"hyp-{index}-a",
            "claim": f"claim-a-round-{index}",
            "rationale": f"mechanism a for round {index}",
            "testablePrediction": f"prediction a {index}",
            "falsifier": f"falsifier a {index}",
            "axisProfile": {"axis": f"axis-{index}"},
        },
        {
            "candidateId": f"hyp-{index}-b",
            "claim": f"claim-b-round-{index}",
            "rationale": f"mechanism b for round {index}",
            "testablePrediction": f"prediction b {index}",
            "falsifier": f"falsifier b {index}",
            "axisProfile": {"axis": f"axis-{index}"},
        },
    ]
    if lineage is None:
        lineage = (
            [{"kind": "candidate", "id": "hyp-seed-a"}, {"kind": "candidate", "id": "hyp-seed-b"}]
            if index == 1
            else [{"kind": "round", "id": _ROUND_IDS[index - 2]}]
        )
    record: dict[str, Any] = {
        "schemaVersion": 1,
        "roundId": round_id,
        "question": _QUESTION_ID,
        "status": status,
        "candidates": candidates,
        "lineage": lineage,
        "meetingRefs": [
            {"kind": "meeting_round", "id": f"meeting-{index}"},
            {"kind": "meeting_digest", "id": f"digest-{index}"},
        ],
        "createdAt": f"2026-09-08T00:{index - 1:02d}:00Z",
    }
    if with_envelope:
        record["revisionEnvelope"] = {
            "schemaVersion": 1,
            "phase": "review_revision",
            "parentCandidateId": "" if index == 1 else "hyp-1-a",
            "revisionReceiptRef": (
                f"model-receipt-hypothesis-review-invocation:{index:04d}"
            ),
            "feedback": {
                "trigger": "formal_hypothesis_review",
                "humanFeedback": human_feedback
                or f"meta-review rationale for round {index}",
                "inputRefs": [f"hypothesis_candidate:hyp-{index}-a:r1"],
                "inputHash": _hex(index),
            },
            "revision": {
                "changes": [f"revised hyp-{index}-a per review round {index}"],
                "unresolvedIssues": [],
                "outputRefs": [f"hypothesis_candidate:hyp-{index}-a:r{index}"],
                "outputHash": _hex(index + 50),
                "status": "completed",
                "actual": actual,
            },
        }
    return record


def _production_chain(**overrides: Any) -> list[dict[str, Any]]:
    """Mirror the live run-332a539909a6 lineage: 10 rounds, one chain."""

    return [
        _round_record(index, **overrides)
        for index in range(1, _CHAIN_LENGTH + 1)
    ]


def _backfill(
    monkeypatch: pytest.MonkeyPatch,
    rounds: list[dict[str, Any]],
    **kwargs: Any,
) -> dict[str, Any]:
    return chain.backfill_feedback_iterations_from_round_chain(
        team_id=_TEAM_ID,
        workflow_run_id=_FORMAL_RUN_ID,
        question_id=_QUESTION_ID,
        source_collection_run_id=_AUTHORITY_ID,
        node_run_id=_NODE_RUN_ID,
        rounds=rounds,
        **kwargs,
    )


def test_backfill_writes_full_chain_and_reader_walks_contiguous_rows(
    monkeypatch,
) -> None:
    store = _patch_store(monkeypatch)
    result = _backfill(monkeypatch, _production_chain())

    assert result["status"] == "written"
    assert result["written"] == _CHAIN_LENGTH
    assert result["rounds"] == _CHAIN_LENGTH
    assert store.rows and len(store.rows) == _CHAIN_LENGTH

    payloads = [row["payload"] for row in store.rows]
    # Distinct node id + schema v1: the same-run hypothesis_design validator
    # must never claim these rows; only the cross-run walk may read them.
    assert all(
        payload["nodeId"] == "hypothesis_review_revision" for payload in payloads
    )
    assert all(payload["schemaVersion"] == 1 for payload in payloads)
    assert [payload["iterationRound"] for payload in payloads] == list(
        range(1, _CHAIN_LENGTH + 1)
    )
    # Chain mapping: iteration k<N points at round k; the terminal iteration
    # anchors at the formal run with an empty childRunId.  The writer omits
    # empty parent/child keys; the reader treats absent as empty.
    for index, payload in enumerate(payloads, start=1):
        if index < _CHAIN_LENGTH:
            assert payload["childRunId"] == _ROUND_IDS[index - 1]
        else:
            assert payload.get("childRunId", "") == ""
        assert payload.get("parentRunId", "") == (
            "" if index == 1 else _ROUND_IDS[index - 2]
        )
        assert payload["sourceCollectionRunId"] == _AUTHORITY_ID
        assert payload["workflowRunId"] == _FORMAL_RUN_ID
    # Nothing synthesized: feedback and changes are the stored round evidence
    # (the writer's v2 row carries snake_case fields).
    assert payloads[3]["feedbackIteration"]["human_feedback"] == (
        "meta-review rationale for round 4"
    )
    assert payloads[3]["feedbackIteration"]["changes"] == [
        "revised hyp-4-a per review round 4"
    ]
    assert (
        "model-receipt-hypothesis-review-invocation:0004"
        in payloads[3]["inputRefs"]
    )
    assert "hypothesis_round:" + _ROUND_IDS[3] in payloads[3]["inputRefs"]

    monkeypatch.setattr(
        result_package_v2,
        "list_workflow_artifacts",
        lambda *_args, **_kwargs: deepcopy(store.rows),
    )
    rows = result_package_v2._feedback_iterations(
        team_id=_TEAM_ID,
        workflow_run_id=_FORMAL_RUN_ID,
        authority_run_id=_AUTHORITY_ID,
    )
    assert [row["round"] for row in rows] == list(range(1, _CHAIN_LENGTH + 1))
    assert all(row["human_feedback"] for row in rows)
    assert all(row["changes"] for row in rows)


def test_package_reader_ignores_old_unrelated_run_rows(monkeypatch) -> None:
    store = _patch_store(monkeypatch)
    assert _backfill(monkeypatch, _production_chain())["status"] == "written"

    rows = store.rows + [
        # The live store's pre-existing rows: an older, unrelated run with a
        # different authority. The reader filters by authority, the walk never
        # reaches their run ids.
        {
            "workflowRunId": "run-old-1",
            "sourceCollectionRunId": "dprun-old-authority",
            "payload": {
                "schemaVersion": 1,
                "nodeId": "iteration_decision",
                "childRunId": "run-old-2",
                "parentRunId": "run-old-1",
                "feedbackIteration": {"round": 1},
            },
        }
    ]
    monkeypatch.setattr(
        result_package_v2,
        "list_workflow_artifacts",
        lambda *_args, **_kwargs: deepcopy(rows),
    )
    assert [
        row["round"]
        for row in result_package_v2._feedback_iterations(
            team_id=_TEAM_ID,
            workflow_run_id=_FORMAL_RUN_ID,
            authority_run_id=_AUTHORITY_ID,
        )
    ] == list(range(1, _CHAIN_LENGTH + 1))


@pytest.mark.parametrize(
    ("overrides", "blocker"),
    [
        ({"index": 5, "actual": False}, "feedback_iteration_chain_not_actual"),
        (
            {"index": 7, "human_feedback": "  "},
            "feedback_iteration_chain_feedback_missing",
        ),
        (
            {"index": 6, "with_envelope": False},
            "feedback_iteration_chain_revision_missing",
        ),
        (
            {"index": 3, "lineage": [{"kind": "candidate", "id": "hyp-x"}]},
            "feedback_iteration_chain_ambiguous",
        ),
    ],
)
def test_incomplete_chain_blocks_entirely_without_writing(
    monkeypatch, overrides, blocker
) -> None:
    store = _patch_store(monkeypatch)
    rounds = _production_chain()
    broken_index = overrides.pop("index")
    rounds[broken_index - 1] = _round_record(broken_index, **overrides)

    result = _backfill(monkeypatch, rounds)

    assert result["status"] == "blocked"
    assert result["blockerCodes"] == [blocker]
    assert result["written"] == 0
    # No partial chains: a defect anywhere stops the whole backfill.
    assert store.rows == []


def test_changes_missing_blocks_and_first_round_without_input_hash_blocks(
    monkeypatch,
) -> None:
    store = _patch_store(monkeypatch)
    rounds = _production_chain()
    rounds[8]["revisionEnvelope"]["revision"]["changes"] = ["", "  "]
    result = _backfill(monkeypatch, rounds)
    assert result["status"] == "blocked"
    assert result["blockerCodes"] == ["feedback_iteration_chain_changes_missing"]
    assert store.rows == []

    # Round 1 without an envelope inputHash has no truthful input state to
    # bind (there is no prior round to snapshot), so it fails closed too.
    store = _patch_store(monkeypatch)
    rounds = _production_chain()
    del rounds[0]["revisionEnvelope"]["feedback"]["inputHash"]
    result = _backfill(monkeypatch, rounds)
    assert result["status"] == "blocked"
    assert result["blockerCodes"] == [
        "feedback_iteration_chain_input_state_missing"
    ]
    assert store.rows == []


def test_missing_envelope_hashes_fall_back_to_candidate_snapshots(
    monkeypatch,
) -> None:
    """Older envelopes without hashes derive hashes from stored candidates."""

    store = _patch_store(monkeypatch)
    rounds = _production_chain()
    for index, record in enumerate(rounds, start=1):
        if index == 1:
            # Round 1's pre-revision state exists only through its own stored
            # envelope hash (fail-closed without it — covered above).
            continue
        record["revisionEnvelope"]["feedback"].pop("inputHash", None)
        record["revisionEnvelope"]["revision"].pop("outputHash", None)

    result = _backfill(monkeypatch, rounds)

    assert result["status"] == "written"
    payloads = [row["payload"] for row in store.rows]
    assert all(len(payload["inputHash"]) == 64 for payload in payloads)
    assert all(len(payload["outputHash"]) == 64 for payload in payloads)
    # Continuity: round k's input hash binds the prior round's candidate state.
    assert payloads[4]["inputHash"] == payloads[3]["outputHash"]


def test_replay_is_idempotent(monkeypatch) -> None:
    store = _patch_store(monkeypatch)
    rounds = _production_chain()
    first = _backfill(monkeypatch, rounds)
    identities = [row["recordId"] for row in store.rows]

    second = _backfill(monkeypatch, _production_chain())

    assert first["status"] == "written"
    assert second["status"] == "written"
    assert second["rounds"] == _CHAIN_LENGTH
    assert [row["recordId"] for row in store.rows] == identities
    assert len(store.rows) == _CHAIN_LENGTH


def test_sweep_backfills_blocked_run_and_replays_idempotently(monkeypatch) -> None:
    store = _patch_store(monkeypatch)
    rounds = _production_chain()
    monkeypatch.setattr(
        chain,
        "_question_hypothesis_rounds",
        lambda _team_id, _question: rounds
        if str(_question).upper() == _QUESTION_ID
        else [],
    )

    def fake_list_runs(*, team_id: str, workflow_id: str) -> dict[str, Any]:
        return {
            "workflowId": workflow_id,
            "runs": [
                {
                    "runId": _FORMAL_RUN_ID,
                    "questionId": _QUESTION_ID,
                    "status": "blocked",
                },
                {
                    "runId": "run-still-running",
                    "questionId": _QUESTION_ID,
                    "status": "running",
                },
                {
                    "runId": "run-other-question",
                    "questionId": "SCI-125",
                    "status": "blocked",
                },
            ],
        }

    from core.web.services.team_workflow.research_runtime import formal_read_runtime
    from core.web.services.team_workflow.research_runtime import runtime_factory

    monkeypatch.setattr(
        formal_read_runtime, "get_query_service", lambda: SimpleNamespace(
            list_runs=fake_list_runs
        )
    )
    ledger_store = SimpleNamespace(
        get_run=lambda run_id: SimpleNamespace(
            input_snapshot_json=json.dumps({"sourceCollectionRunId": _AUTHORITY_ID})
        ),
        latest_attempt=lambda run_id, node_id: SimpleNamespace(
            node_run_id=f"nr-{run_id}-{node_id}-a1"
        ),
    )
    monkeypatch.setattr(
        runtime_factory,
        "production_workflow_runtime",
        lambda: SimpleNamespace(store=ledger_store),
    )

    first = chain.auto_backfill_missing_feedback_iterations(
        _TEAM_ID, question_id=_QUESTION_ID.lower()
    )

    assert first["status"] == "written"
    assert first["written"] == _CHAIN_LENGTH
    assert len(first["runs"]) == 1
    assert first["runs"][0]["runId"] == _FORMAL_RUN_ID
    assert len(store.rows) == _CHAIN_LENGTH

    second = chain.auto_backfill_missing_feedback_iterations(
        _TEAM_ID, question_id=_QUESTION_ID
    )
    assert second["status"] == "written"
    assert len(store.rows) == _CHAIN_LENGTH

    monkeypatch.setattr(
        result_package_v2,
        "list_workflow_artifacts",
        lambda *_args, **_kwargs: deepcopy(store.rows),
    )
    rows = result_package_v2._feedback_iterations(
        team_id=_TEAM_ID,
        workflow_run_id=_FORMAL_RUN_ID,
        authority_run_id=_AUTHORITY_ID,
    )
    assert [row["round"] for row in rows] == list(range(1, _CHAIN_LENGTH + 1))


def test_sweep_skips_without_target_run_or_runtime(monkeypatch) -> None:
    from core.web.services.team_workflow.research_runtime import formal_read_runtime
    from core.web.services.team_workflow.research_runtime import runtime_factory

    monkeypatch.setattr(
        formal_read_runtime,
        "get_query_service",
        lambda: SimpleNamespace(
            list_runs=lambda **_kwargs: {
                "runs": [
                    {
                        "runId": _FORMAL_RUN_ID,
                        "questionId": _QUESTION_ID,
                        "status": "running",
                    }
                ]
            }
        ),
    )
    result = chain.auto_backfill_missing_feedback_iterations(
        _TEAM_ID, question_id=_QUESTION_ID
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "no_target_formal_run"

    monkeypatch.setattr(
        runtime_factory, "production_workflow_runtime", lambda: None
    )
    monkeypatch.setattr(
        formal_read_runtime,
        "get_query_service",
        lambda: SimpleNamespace(
            list_runs=lambda **_kwargs: {
                "runs": [
                    {
                        "runId": _FORMAL_RUN_ID,
                        "questionId": _QUESTION_ID,
                        "status": "blocked",
                    }
                ]
            }
        ),
    )
    result = chain.auto_backfill_missing_feedback_iterations(
        _TEAM_ID, question_id=_QUESTION_ID
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "formal_runtime_unavailable"


def test_sweep_reports_blocked_chain_without_writing(monkeypatch) -> None:
    store = _patch_store(monkeypatch)
    rounds = _production_chain()
    rounds[3] = _round_record(4, actual=False)
    monkeypatch.setattr(
        chain,
        "_question_hypothesis_rounds",
        lambda _team_id, _question: rounds,
    )
    from core.web.services.team_workflow.research_runtime import formal_read_runtime
    from core.web.services.team_workflow.research_runtime import runtime_factory

    monkeypatch.setattr(
        formal_read_runtime,
        "get_query_service",
        lambda: SimpleNamespace(
            list_runs=lambda **_kwargs: {
                "runs": [
                    {
                        "runId": _FORMAL_RUN_ID,
                        "questionId": _QUESTION_ID,
                        "status": "blocked",
                    }
                ]
            }
        ),
    )
    ledger_store = SimpleNamespace(
        get_run=lambda run_id: SimpleNamespace(
            input_snapshot_json=json.dumps({"sourceCollectionRunId": _AUTHORITY_ID})
        ),
        latest_attempt=lambda run_id, node_id: SimpleNamespace(
            node_run_id=f"nr-{run_id}-{node_id}-a1"
        ),
    )
    monkeypatch.setattr(
        runtime_factory,
        "production_workflow_runtime",
        lambda: SimpleNamespace(store=ledger_store),
    )

    result = chain.auto_backfill_missing_feedback_iterations(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert result["status"] == "blocked"
    assert result["blocked"] == 1
    assert result["runs"][0]["blockerCodes"] == [
        "feedback_iteration_chain_not_actual"
    ]
    assert store.rows == []


def test_sweep_skips_authority_owned_by_another_pipeline(monkeypatch) -> None:
    store = _patch_store(monkeypatch)
    store.rows.append(
        {
            "recordId": "feedback_iterations:owned-elsewhere",
            "kind": "feedback_iterations",
            "workflowRunId": _FORMAL_RUN_ID,
            "sourceCollectionRunId": _AUTHORITY_ID,
            "contentHash": "0" * 64,
            "payload": {
                "schemaVersion": 1,
                "nodeId": "iteration_decision",
                "questionId": _QUESTION_ID,
                "iterationRound": 1,
                "feedbackIteration": {"round": 1},
            },
        }
    )
    monkeypatch.setattr(
        chain,
        "_question_hypothesis_rounds",
        lambda _team_id, _question: _production_chain(),
    )
    from core.web.services.team_workflow.research_runtime import formal_read_runtime
    from core.web.services.team_workflow.research_runtime import runtime_factory

    monkeypatch.setattr(
        formal_read_runtime,
        "get_query_service",
        lambda: SimpleNamespace(
            list_runs=lambda **_kwargs: {
                "runs": [
                    {
                        "runId": _FORMAL_RUN_ID,
                        "questionId": _QUESTION_ID,
                        "status": "blocked",
                    }
                ]
            }
        ),
    )
    ledger_store = SimpleNamespace(
        get_run=lambda run_id: SimpleNamespace(
            input_snapshot_json=json.dumps({"sourceCollectionRunId": _AUTHORITY_ID})
        ),
        latest_attempt=lambda run_id, node_id: SimpleNamespace(
            node_run_id=f"nr-{run_id}-{node_id}-a1"
        ),
    )
    monkeypatch.setattr(
        runtime_factory,
        "production_workflow_runtime",
        lambda: SimpleNamespace(store=ledger_store),
    )

    result = chain.auto_backfill_missing_feedback_iterations(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert result["status"] == "blocked"
    assert result["runs"][0]["blockerCodes"] == [
        "feedback_iteration_authority_owned_elsewhere"
    ]
    assert len(store.rows) == 1
