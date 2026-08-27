"""T2 RED: readiness registry — definition node set == evaluator key set."""

from __future__ import annotations

import pytest

from core.web.services.team_workflow.research_runtime.readiness import NodeReadinessService
from core.web.services.team_workflow.research_runtime.readiness.service import _build_registry
from tests._support.readiness_fakes import (
    DEFINITION,
    DEFINITION_NODE_IDS,
    FakeDomainContext,
    make_run,
)


def test_registry_keys_exactly_match_definition_nodes() -> None:
    assert set(_build_registry()) == DEFINITION_NODE_IDS
    # 17 nodes since the problem_understanding entry node joined the
    # canonical graph; the set equality above is the real contract.
    assert len(_build_registry()) == len(DEFINITION_NODE_IDS)


def test_registry_integrity_asserted_at_construction() -> None:
    runs = {"run-test": make_run()}

    def run_source(run_id: str):
        return runs.get(run_id)

    service = NodeReadinessService(run_source=run_source)
    service.assert_registry_complete()

    with pytest.raises(AssertionError):
        NodeReadinessService(
            run_source=run_source,
            definition=_DefinitionWithExtraNode(),
        )


def test_all_nodes_evaluate_to_a_readiness_result() -> None:
    runs = {"run-test": make_run()}
    service = NodeReadinessService(run_source=runs.get)
    context = FakeDomainContext()
    for node_id in DEFINITION_NODE_IDS:
        result = service.evaluate(
            team_id="research-team",
            run_id="run-test",
            node_id=node_id,
            context=context,
            use_cache=False,
            evaluated_at_ms=1,
        )
        assert result.node_id == node_id
        assert result.run_version == 1
        assert result.team_id == "research-team"
        assert isinstance(result.ready, bool)


def test_unknown_node_returns_blocker() -> None:
    runs = {"run-test": make_run()}
    service = NodeReadinessService(run_source=runs.get)
    result = service.evaluate(
        team_id="research-team",
        run_id="run-test",
        node_id="not_a_node",
        context=FakeDomainContext(),
        use_cache=False,
    )
    assert result.ready is False
    assert result.blockers[0].code == "unknown_node"


class _DefinitionWithExtraNode:
    nodes = list(DEFINITION.nodes) + [
        type(
            "Node",
            (),
            {"nodeId": "extra_node", "actorKind": type("K", (), {"value": "agent"})},
        )()
    ]
