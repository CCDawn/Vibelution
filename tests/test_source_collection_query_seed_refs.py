"""Regression coverage for projecting lineage refs into search seeds."""

from __future__ import annotations

import pytest

from core.web.services import team_workflow_orchestration_service as service


@pytest.mark.parametrize(
    ("input_ref", "expected_seed"),
    [
        ("neural predictive coding", "neural predictive coding"),
        ("seed-query:neural gating", "neural gating"),
        ("query:independent baseline", "independent baseline"),
        ("keyword:反例证据", "反例证据"),
        ("topic:causal mechanism", "causal mechanism"),
        ("10.1234/ABC-1", "10.1234/ABC-1"),
        ("doi:10.1234/ABC-1", "10.1234/ABC-1"),
        ("https://doi.org/10.1234/ABC-1", "10.1234/ABC-1"),
    ],
)
def test_search_seed_projection_preserves_queries_and_exact_dois(
    input_ref: str,
    expected_seed: str,
) -> None:
    assert service._source_collection_seed_from_input_ref(input_ref) == expected_seed


@pytest.mark.parametrize(
    "input_ref",
    [
        "challenge-question-catalog://XH-202619/SCI-011/review-run/sha256:abc",
        "challenge-question-artifact://XH-202619/SCI-011/review-run/sha256:def",
        "dimension_reviews://team/run/review-hash",
        "sha256:" + "a" * 64,
        "a" * 64,
        r"C:\research\sources\paper.pdf",
        "/research/sources/paper.pdf",
        "./research/sources/paper.pdf",
        "notes.md",
        "https://publisher.example/paper/123",
    ],
)
def test_search_seed_projection_ignores_lineage_locators_and_paths(input_ref: str) -> None:
    assert service._source_collection_seed_from_input_ref(input_ref) == ""


def test_query_plan_keeps_catalog_ref_in_lineage_but_excludes_it_from_seeds() -> None:
    catalog_ref = "challenge-question-catalog://XH-202619/SCI-011/review-run/sha256:abc"
    plan = service._build_source_collection_search_plan(
        team_id="team-seed-ref",
        run_id="run-seed-ref",
        payload={"querySeeds": [], "searchLanguages": ["en"], "sourceTypes": ["paper"]},
        scope={"topic": "neural gating"},
        input_refs=[catalog_ref],
        roles=["source_finder"],
        prompt_cache_policy={"requirement": "disabled", "modelId": ""},
    )

    assert catalog_ref not in plan["querySeeds"]
    assert plan["querySeeds"] == ["neural gating"]
