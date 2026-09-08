"""Missing-link waiver operator surface (缺陷⑪): route + store write + gate.

读侧（``fetch_evidence_graph_stats`` / ``evaluate_knowledge_ingestion``）早已
支持 waiver 豁免统计，但全仓没有任何写豁免的路径。这里钉住三件事：

1. 路由契约：显式 confirmed + ≥8 字符理由是强制门（428），run/图/缺口
   404 族语义，写操作经 server_operator_scope。
2. 候选店写入面：豁免走 knowledge kernel 的窄更新（与
   ``build_candidate_graph`` 同一 load/lock/save 路径），缺口保留、
   ``missingLinkCount`` 不变，``summary.waiverCount`` 按读侧口径重算，
   已豁免目标是 no-op 且审计内容不被改写。
3. 就绪联动：豁免后的图 payload 让 ``fetch_evidence_graph_stats`` 报
   waiver_count>0，``evaluate_knowledge_ingestion`` 不再产出
   ``evidence_graph_incomplete`` blocker。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes.team_workflows import research_runtime as rt_routes
from core.web.services.team_workflow.research_runtime import evidence_graph_waiver
from core.web.services.team_workflow.research_runtime.evidence_graph_waiver import (
    waive_missing_link,
)
from core.web.services.team_workflow.research_runtime.readiness.knowledge import (
    evaluate_knowledge_ingestion,
)

_TEAM = "research-team"
_RUN = "run-1ca97605acf3"
_SC = "sc-20260908171904"
_ROUTE = f"/api/research/workflow-runs/{_RUN}/evidence-graph/missing-links/waive"
_JUSTIFICATION = (
    "relation mapper asserted a random candidate id typo; "
    "the real candidate exists and the edge is accepted by review"
)


def _client() -> TestClient:
    return TestClient(
        create_app(),
        headers={CONTROL_TOKEN_HEADER: get_control_token()},
    )


def _waive_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "teamId": _TEAM,
        "sourceCandidateId": "candidate-a",
        "targetCandidateId": "candidate-20260908171904-9143d4d6",
        "relation": "supports",
        "justification": _JUSTIFICATION,
        "confirmed": True,
    }
    payload.update(overrides)
    return payload


def _run_record(
    *,
    team_id: str = _TEAM,
    input_snapshot: dict[str, Any] | None = None,
) -> SimpleNamespace:
    snapshot = {"questionId": "SCI-009"}
    if input_snapshot is not None:
        snapshot = input_snapshot
    return SimpleNamespace(
        run_id=_RUN,
        team_id=team_id,
        input_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
    )


class _FakeLedgerStore:
    def __init__(self, run: SimpleNamespace | None) -> None:
        self._run = run

    def get_run(self, run_id: str) -> SimpleNamespace | None:
        _ = run_id
        return self._run


@pytest.fixture
def fake_ledger(monkeypatch: pytest.MonkeyPatch):
    holder: dict[str, SimpleNamespace | None] = {"run": None}

    def _install(run: SimpleNamespace | None) -> None:
        holder["run"] = run

    def _fake_get_write_store():
        return _FakeLedgerStore(holder["run"])

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.formal_write_runtime.get_write_store",
        _fake_get_write_store,
    )
    return _install


# -- route contract -----------------------------------------------------------


def test_waive_route_refuses_missing_confirmation(fake_ledger, monkeypatch) -> None:
    def fail_kernel(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("waiver must not run without explicit confirmation")

    monkeypatch.setattr(
        "core.web.services.team_workflow.knowledge_kernel.apply_missing_link_waiver",
        fail_kernel,
    )
    response = _client().post(_ROUTE, json=_waive_payload(confirmed=False))
    assert response.status_code == 428
    assert response.json()["detail"]["code"] == "waiver_confirmation_required"


def test_waive_route_refuses_thin_justification(fake_ledger, monkeypatch) -> None:
    def fail_kernel(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("waiver must not run without an auditable justification")

    monkeypatch.setattr(
        "core.web.services.team_workflow.knowledge_kernel.apply_missing_link_waiver",
        fail_kernel,
    )
    response = _client().post(_ROUTE, json=_waive_payload(justification="太短"))
    assert response.status_code == 428
    assert response.json()["detail"]["code"] == "waiver_justification_required"

    response = _client().post(_ROUTE, json=_waive_payload(justification="       "))
    assert response.status_code == 428
    assert response.json()["detail"]["code"] == "waiver_justification_required"


def test_waive_route_rejects_unknown_fields(fake_ledger) -> None:
    response = _client().post(_ROUTE, json=_waive_payload(surprise="x"))
    assert response.status_code == 422


def test_waive_route_returns_404_for_unknown_run(fake_ledger) -> None:
    fake_ledger(None)
    response = _client().post(_ROUTE, json=_waive_payload())
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "run_not_found"


def test_waive_route_returns_404_on_team_scope_mismatch(fake_ledger) -> None:
    fake_ledger(_run_record(team_id="other-team"))
    response = _client().post(_ROUTE, json=_waive_payload())
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "team_scope_mismatch"


def test_waive_route_returns_404_without_source_collection_run(fake_ledger) -> None:
    fake_ledger(_run_record(input_snapshot={"questionId": "SCI-009"}))
    response = _client().post(_ROUTE, json=_waive_payload())
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "graph_not_found"


def test_waive_route_maps_missing_link_not_found(fake_ledger, monkeypatch) -> None:
    fake_ledger(_run_record(input_snapshot={"sourceCollectionRunId": _SC}))

    def fake_kernel(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"outcome": "missing_link_not_found", "teamId": _TEAM}

    monkeypatch.setattr(
        "core.web.services.team_workflow.knowledge_kernel.apply_missing_link_waiver",
        fake_kernel,
    )
    response = _client().post(_ROUTE, json=_waive_payload())
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "missing_link_not_found"


def test_waive_route_executes_confirmed_waiver_with_operator_identity(
    fake_ledger, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("VIBELUTION_RESEARCH_OPERATOR_ID", raising=False)
    fake_ledger(_run_record(input_snapshot={"sourceCollectionRunId": _SC}))
    captured: dict[str, Any] = {}

    def fake_kernel(team_id: str, **kwargs: Any) -> dict[str, Any]:
        captured["team_id"] = team_id
        captured.update(kwargs)
        return {
            "outcome": "waived",
            "alreadyWaived": False,
            "teamId": team_id,
            "sourceCollectionRunId": _SC,
            "graphCandidateIds": ["candidate-graph-1"],
            "waiverCount": 1,
            "missingLinkCount": 1,
            "waiver": {
                "by": str(kwargs.get("operator_id") or ""),
                "at": "2026-09-08T00:00:00Z",
                "justification": str(kwargs.get("justification") or ""),
            },
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.knowledge_kernel.apply_missing_link_waiver",
        fake_kernel,
    )
    response = _client().post(_ROUTE, json=_waive_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "waived"
    assert body["alreadyWaived"] is False
    assert body["waiverCount"] == 1
    assert body["missingLinkCount"] == 1
    assert body["graphCandidateIds"] == ["candidate-graph-1"]
    assert captured["team_id"] == _TEAM
    assert captured["authority_run_id"] == _SC
    assert captured["source_candidate_id"] == "candidate-a"
    assert captured["target_candidate_id"] == "candidate-20260908171904-9143d4d6"
    assert captured["relation"] == "supports"
    assert captured["justification"] == _JUSTIFICATION
    # Operator identity is server-side (never client-declared headers).
    assert captured["operator_id"] == "local-control-operator"


def test_waive_route_is_registered_on_the_router() -> None:
    posted = {
        route.path
        for route in rt_routes.router.routes
        if getattr(route, "methods", None) and "POST" in route.methods
    }
    assert "/research/workflow-runs/{run_id}/evidence-graph/missing-links/waive" in posted


# -- candidate-store write surface (knowledge kernel) -------------------------


def _graph_record(
    candidate_id: str,
    *,
    sc_run_id: str,
    missing_links: list[dict[str, Any]],
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    graph_summary = {"missingLinkCount": len(missing_links), **(summary or {})}
    return {
        "schemaVersion": "1.0",
        "candidateId": candidate_id,
        "candidateType": "candidate_graph",
        "teamId": _TEAM,
        "title": f"graph {candidate_id}",
        "metadata": {
            "sourceCollectionRunId": sc_run_id,
            "graph": {
                "nodes": [{"candidateId": "candidate-a", "title": "A"}],
                "edges": [],
                "missingLinks": missing_links,
                "summary": graph_summary,
            },
            "missingLinkCount": len(missing_links),
        },
        "createdAt": "2026-09-08T10:00:00Z",
        "updatedAt": "2026-09-08T10:00:00Z",
    }


def _missing_link(
    source: str = "candidate-a",
    target: str = "candidate-20260908171904-9143d4d6",
    relation: str = "supports",
) -> dict[str, Any]:
    return {"sourceCandidateId": source, "targetCandidateId": target, "relation": relation}


@pytest.fixture
def store_surface(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Mount the kernel waiver on an in-memory store + tmp file write path."""
    from core.web.services import team_workflow_orchestration_service as service_module

    state: dict[str, Any] = {
        "store": {"candidates": []},
        "writes": [],
    }

    def fake_load_candidate_store(team_id: str, run_id: str = ""):
        _ = team_id
        state["loadedRunId"] = run_id
        return state["store"]

    def fake_candidate_store_path(team_id: str, run_id: str = "", research_project_id: str = ""):
        _ = team_id, research_project_id
        return tmp_path / f"candidate-store-{run_id or 'team'}.json"

    def fake_write_json(path: Path, payload: dict[str, Any]) -> None:
        state["writes"].append(str(path))
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(service_module, "_load_candidate_store", fake_load_candidate_store)
    monkeypatch.setattr(service_module, "_candidate_store_path", fake_candidate_store_path)
    monkeypatch.setattr(service_module, "_write_json", fake_write_json)

    from core.web.services.team_workflow.knowledge_kernel import apply_missing_link_waiver

    def _call(**overrides: Any) -> dict[str, Any]:
        kwargs = {
            "authority_run_id": _SC,
            "source_candidate_id": "candidate-a",
            "target_candidate_id": "candidate-20260908171904-9143d4d6",
            "relation": "supports",
            "justification": _JUSTIFICATION,
            "operator_id": "local-control-operator",
        }
        kwargs.update(overrides)
        return apply_missing_link_waiver(_TEAM, **kwargs)

    return SimpleNamespace(call=_call, state=state)


def test_kernel_waiver_marks_missing_link_and_recounts_summary(store_surface) -> None:
    store_surface.state["store"]["candidates"] = [
        _graph_record("candidate-graph-1", sc_run_id=_SC, missing_links=[_missing_link()]),
    ]
    outcome = store_surface.call()
    assert outcome["outcome"] == "waived"
    assert outcome["graphCandidateIds"] == ["candidate-graph-1"]
    assert outcome["waiverCount"] == 1
    assert outcome["missingLinkCount"] == 1

    graph = store_surface.state["store"]["candidates"][0]["metadata"]["graph"]
    item = graph["missingLinks"][0]
    assert item["waived"] is True
    assert item["status"] == "waived"
    assert item["waiver"]["by"] == "local-control-operator"
    assert item["waiver"]["justification"] == _JUSTIFICATION
    assert item["waiver"]["at"]
    assert graph["summary"]["waiverCount"] == 1
    # Gate must not be loosened: the gap stays counted.
    assert graph["summary"]["missingLinkCount"] == 1
    # Saved through the canonical run-scoped store path.
    assert store_surface.state["writes"], "waiver must persist via the store write surface"
    assert store_surface.state["loadedRunId"] == _SC


def test_kernel_waiver_is_idempotent_no_op_on_waived_target(store_surface) -> None:
    store_surface.state["store"]["candidates"] = [
        _graph_record("candidate-graph-1", sc_run_id=_SC, missing_links=[_missing_link()]),
    ]
    first = store_surface.call()
    assert first["outcome"] == "waived"
    writes_after_first = len(store_surface.state["writes"])
    original_updated_at = store_surface.state["store"]["candidates"][0]["updatedAt"]
    original_waiver = dict(
        store_surface.state["store"]["candidates"][0]["metadata"]["graph"]["missingLinks"][0][
            "waiver"
        ]
    )

    second = store_surface.call(
        justification="a different second justification text that is long enough"
    )
    assert second["outcome"] == "already_waived"
    assert second["alreadyWaived"] is True
    # No rewrite: the original audit content and timestamps stay untouched.
    assert len(store_surface.state["writes"]) == writes_after_first
    record = store_surface.state["store"]["candidates"][0]
    assert record["updatedAt"] == original_updated_at
    assert record["metadata"]["graph"]["missingLinks"][0]["waiver"] == original_waiver


def test_kernel_waiver_updates_all_scoped_graph_records(store_surface) -> None:
    store_surface.state["store"]["candidates"] = [
        _graph_record(
            "candidate-graph-older",
            sc_run_id=_SC,
            missing_links=[_missing_link()],
        ),
        _graph_record(
            "candidate-graph-latest",
            sc_run_id=_SC,
            missing_links=[_missing_link(), _missing_link(relation="contradicts")],
        ),
        # Not scoped to this authority run — must never be touched.
        _graph_record(
            "candidate-graph-other-run",
            sc_run_id="sc-other",
            missing_links=[_missing_link()],
        ),
    ]
    outcome = store_surface.call()
    assert outcome["outcome"] == "waived"
    assert sorted(outcome["graphCandidateIds"]) == [
        "candidate-graph-latest",
        "candidate-graph-older",
    ]
    records = {
        record["candidateId"]: record
        for record in store_surface.state["store"]["candidates"]
    }
    for graph_id in ("candidate-graph-older", "candidate-graph-latest"):
        graph = records[graph_id]["metadata"]["graph"]
        waived = [item for item in graph["missingLinks"] if item.get("waived")]
        assert len(waived) == 1
        assert graph["summary"]["waiverCount"] == 1
    untouched = records["candidate-graph-other-run"]["metadata"]["graph"]
    assert all(not item.get("waived") for item in untouched["missingLinks"])
    assert "waiverCount" not in untouched["summary"]


def test_kernel_waiver_404_semantics(store_surface) -> None:
    # No scoped graph records at all.
    store_surface.state["store"]["candidates"] = []
    assert store_surface.call()["outcome"] == "graph_not_found"

    # Scoped graph exists but the exact link is absent.
    store_surface.state["store"]["candidates"] = [
        _graph_record(
            "candidate-graph-1",
            sc_run_id=_SC,
            missing_links=[_missing_link(target="candidate-999")],
        ),
    ]
    assert store_surface.call()["outcome"] == "missing_link_not_found"

    # Matching requires an exact (source, target, relation) triple.
    store_surface.state["store"]["candidates"] = [
        _graph_record(
            "candidate-graph-1",
            sc_run_id=_SC,
            missing_links=[_missing_link(relation="contradicts")],
        ),
    ]
    assert store_surface.call()["outcome"] == "missing_link_not_found"


def test_service_level_waiver_end_to_end_over_fake_store(
    store_surface, fake_ledger, monkeypatch
) -> None:
    """Full chain minus HTTP: run resolution -> scoped graph -> store write."""
    fake_ledger(_run_record(input_snapshot={"sourceCollectionRunId": _SC}))
    store_surface.state["store"]["candidates"] = [
        _graph_record("candidate-graph-1", sc_run_id=_SC, missing_links=[_missing_link()]),
    ]
    result = waive_missing_link(
        run_id=_RUN,
        team_id=_TEAM,
        source_candidate_id="candidate-a",
        target_candidate_id="candidate-20260908171904-9143d4d6",
        relation="supports",
        justification=_JUSTIFICATION,
        operator=None,
    )
    body = result.to_dict()
    assert body["status"] == "waived"
    assert body["waiverCount"] == 1
    assert body["missingLinkCount"] == 1
    assert body["sourceCollectionRunId"] == _SC
    assert body["graphCandidateIds"] == ["candidate-graph-1"]
    assert body["waiver"]["justification"] == _JUSTIFICATION


def test_service_confirmation_assertions() -> None:
    from core.web.services.team_workflow.research_runtime.evidence_graph_waiver import (
        assert_missing_link_waiver_confirmation,
    )

    with pytest.raises(Exception) as exc_info:
        assert_missing_link_waiver_confirmation(confirmed=False, justification=_JUSTIFICATION)
    assert getattr(exc_info.value, "code", "") == "waiver_confirmation_required"

    with pytest.raises(Exception) as exc_info:
        assert_missing_link_waiver_confirmation(confirmed=True, justification="短")
    assert getattr(exc_info.value, "code", "") == "waiver_justification_required"

    assert (
        assert_missing_link_waiver_confirmation(confirmed=True, justification=_JUSTIFICATION)
        is None
    )


# -- readiness gate linkage ---------------------------------------------------


def _graph_stats_payload(missing_links: list[dict[str, Any]], waiver_count: int) -> dict[str, Any]:
    return {
        "nodes": [{"candidateId": "candidate-a"}],
        "edges": [],
        "missingLinks": missing_links,
        "summary": {
            "missingLinkCount": len(missing_links),
            "waiverCount": waiver_count,
        },
    }


def _evaluate(monkeypatch: pytest.MonkeyPatch, graph: dict[str, Any] | None):
    from core.web.services.team_workflow.research_runtime import readiness_providers

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.artifact_readback_registry.load_scoped_artifact_payload",
        lambda *_args, **_kwargs: graph,
    )
    stats = readiness_providers.fetch_evidence_graph_stats(
        _TEAM,
        _RUN,
        input_snapshot={"sourceCollectionRunId": _SC},
    )
    context = SimpleNamespace(evidence_graph_stats=lambda team_id, run_id: stats)
    run = SimpleNamespace(team_id=_TEAM, run_id=_RUN)
    common = SimpleNamespace(domain_revision_vector={"k": "v"})
    return stats, evaluate_knowledge_ingestion(
        run=run,
        node=SimpleNamespace(nodeId="knowledge_ingestion"),
        common=common,
        context=context,
    )


def test_waived_graph_still_counts_gap_but_no_longer_blocks(monkeypatch) -> None:
    waived = _missing_link()
    waived.update(
        {
            "waived": True,
            "status": "waived",
            "waiver": {"by": "local-control-operator", "at": "x", "justification": _JUSTIFICATION},
        }
    )
    stats, verdict = _evaluate(
        monkeypatch, _graph_stats_payload([waived], waiver_count=1)
    )
    assert stats is not None
    assert stats["missing_link_count"] == 1, "豁免不得抹掉缺口计数"
    assert stats["waiver_count"] == 1
    assert all(
        getattr(blocker, "code", "") != "evidence_graph_incomplete"
        for blocker in verdict.blockers
    )


def test_unwaived_graph_still_blocks_knowledge_ingestion(monkeypatch) -> None:
    stats, verdict = _evaluate(
        monkeypatch, _graph_stats_payload([_missing_link()], waiver_count=0)
    )
    assert stats is not None
    assert stats["waiver_count"] == 0
    assert any(
        getattr(blocker, "code", "") == "evidence_graph_incomplete"
        for blocker in verdict.blockers
    )


def test_readiness_waiver_count_follows_read_side_rule(monkeypatch) -> None:
    """summary.waiverCount and per-item markers are both honored (读侧口径)."""
    legacy = _missing_link()
    legacy["status"] = "accepted"
    stats, _ = _evaluate(monkeypatch, _graph_stats_payload([legacy], waiver_count=0))
    assert stats is not None
    assert stats["waiver_count"] == 1, "status=accepted counts via the read-side rule"
