"""Finding prompts require balanced, traceable evidence discovery."""

from core.web.services.team_workflow.source_collection.stage_writeback_prompt_contracts import (
    stage_writeback_prompt_lines,
)
from core.web.services.team_workflow.source_collection.writeback_materialize import (
    _merge_source_collection_stage_writeback_agent_graph,
    _source_collection_stage_writeback_agent_graph_payload,
)


def test_finding_prompt_requires_counter_search_without_fabrication() -> None:
    prompt = "\n".join(stage_writeback_prompt_lines("finding"))

    assert "mechanism" in prompt
    assert "independent_baseline" in prompt
    assert "limitation_or_null" in prompt
    assert "falsification" in prompt
    assert "result.searchTrace[]" in prompt
    assert "status=found/no_credible_source" in prompt
    assert "status=needs_review" in prompt
    assert "不得伪造负面资料" in prompt


def test_unknown_stage_has_no_extra_writeback_contract() -> None:
    assert stage_writeback_prompt_lines("unknown") == []


def test_relation_prompt_candidate_relations_materialize_as_candidate_graph_edges() -> None:
    payload = _source_collection_stage_writeback_agent_graph_payload(
        {
            "themes": [{"id": "theme-baseline", "label": "Frozen baseline"}],
            "candidateRelations": [
                {
                    "from": "candidate-source-a",
                    "to": "theme-baseline",
                    "type": "compares_against",
                    "evidenceRefs": ["record-a#p4"],
                }
            ],
        }
    )

    assert payload["themeNodes"] == [
        {"id": "theme-baseline", "label": "Frozen baseline"}
    ]
    assert payload["sourceThemeEdges"] == [
        {
            "candidateId": "candidate-source-a",
            "themeId": "theme-baseline",
            "relation": "compares_against",
            "evidenceRefs": ["record-a#p4"],
        }
    ]
    graph = _merge_source_collection_stage_writeback_agent_graph(
        {"nodes": [{"candidateId": "candidate-source-a"}]},
        payload,
    )

    assert graph["summary"]["edgeCount"] == 1
    assert graph["edges"] == [
        {
            "sourceCandidateId": "candidate-source-a",
            "targetCandidateId": "source-theme:theme-baseline",
            "relation": "compares_against",
            "edgeState": "candidate_only",
            "evidenceRefs": ["record-a#p4"],
        }
    ]


def test_relation_prompt_candidate_graph_predicate_preserves_evidence_refs() -> None:
    payload = _source_collection_stage_writeback_agent_graph_payload(
        {
            "candidateGraph": {
                "nodes": [
                    {"id": "candidate-source-a", "type": "source"},
                    {"id": "theme-temporal", "type": "theme"},
                ],
                "edges": [
                    {
                        "from": "candidate-source-a",
                        "to": "theme-temporal",
                        "predicate": "supports_temporal_coding",
                        "evidenceRefs": ["record-a#results"],
                    }
                ],
            }
        }
    )

    graph = _merge_source_collection_stage_writeback_agent_graph({}, payload)

    assert graph["summary"]["edgeCount"] == 1
    assert graph["edges"] == [
        {
            "sourceCandidateId": "candidate-source-a",
            "targetCandidateId": "theme-temporal",
            "relation": "supports_temporal_coding",
            "edgeState": "candidate_only",
            "evidenceRefs": ["record-a#results"],
        }
    ]
