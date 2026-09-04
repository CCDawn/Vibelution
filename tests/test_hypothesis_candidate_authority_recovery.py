from __future__ import annotations

from core.web.services.team_workflow.research_runtime import hypothesis_first_chain as chain
from core.web.services.team_workflow.research_runtime import question_launch


def test_current_ledger_candidate_survives_unrelated_approved_question_artifact(
    monkeypatch,
) -> None:
    """An older approved result must not erase a newer selection candidate."""

    monkeypatch.setattr(
        question_launch,
        "_approved_details",
        lambda _team_id: {
            "SCI-020": {
                "output": {
                    "hypotheses": [
                        {
                            "hypothesis_id": "legacy-candidate",
                            "statement": "legacy statement",
                            "mechanism": "legacy mechanism",
                        }
                    ]
                }
            }
        },
    )
    monkeypatch.setattr(
        chain,
        "list_hypothesis_candidates",
        lambda *_args, **_kwargs: {
            "candidates": [
                {
                    "candidateId": "sci-020-current",
                    "statement": "current falsifiable statement",
                    "rationale": "current mechanism rationale",
                    "lineageRefs": ["meeting_round:generation-current"],
                }
            ]
        },
    )

    candidates = chain._build_round_candidates(
        "research-team",
        {
            "question": "SCI-020",
            "discussionItemRefs": ["hypothesis_candidate:sci-020-current"],
        },
        workflow_run_id="run-current",
    )

    assert candidates == [
        {
            "candidateId": "sci-020-current",
            "claim": "current falsifiable statement",
            "rationale": "current mechanism rationale",
            "candidateAuthority": "",
            "lineageRefs": ["meeting_round:generation-current"],
            "testablePrediction": "",
            "falsifier": "",
            "axisProfile": {},
        }
    ]


def test_approved_candidate_remains_authoritative_when_identity_matches(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        question_launch,
        "_approved_details",
        lambda _team_id: {
            "SCI-020": {
                "output": {
                    "hypotheses": [
                        {
                            "hypothesis_id": "shared-candidate",
                            "statement": "approved statement",
                            "mechanism": "approved mechanism",
                        }
                    ]
                }
            }
        },
    )
    monkeypatch.setattr(
        chain,
        "list_hypothesis_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("matching approved candidates must not read the ledger")
        ),
    )

    candidates = chain._build_round_candidates(
        "research-team",
        {
            "question": "SCI-020",
            "discussionItemRefs": ["hypothesis_candidate:shared-candidate"],
        },
        workflow_run_id="run-current",
    )

    assert candidates[0]["claim"] == "approved statement"
    assert candidates[0]["rationale"] == "approved mechanism"


def test_formal_review_recovers_exact_legacy_unscoped_candidate(
    monkeypatch,
) -> None:
    """A formal meeting may bind a candidate created before run scoping."""

    monkeypatch.setattr(
        question_launch,
        "_approved_details",
        lambda _team_id: {
            "SCI-020": {
                "output": {
                    "hypotheses": [
                        {
                            "hypothesis_id": "legacy-approved-other",
                            "statement": "older approved statement",
                            "mechanism": "older approved mechanism",
                        }
                    ]
                }
            }
        },
    )
    calls: list[str] = []

    def list_candidates(*_args, **kwargs):
        workflow_run_id = str(kwargs.get("workflow_run_id") or "")
        calls.append(workflow_run_id)
        if workflow_run_id:
            return {"candidates": []}
        return {
            "candidates": [
                {
                    "candidateId": "sci-020-legacy-bound",
                    "statement": "legacy but formally bound statement",
                    "rationale": "legacy but formally bound rationale",
                },
                {
                    "candidateId": "sci-020-unrelated",
                    "statement": "must not be selected",
                    "rationale": "must not be selected",
                },
            ]
        }

    monkeypatch.setattr(chain, "list_hypothesis_candidates", list_candidates)

    candidates = chain._build_round_candidates(
        "research-team",
        {
            "question": "SCI-020",
            "workflowRunId": "run-current",
            "discussionItemRefs": [
                "hypothesis_candidate:sci-020-legacy-bound"
            ],
        },
        workflow_run_id="run-current",
    )

    assert calls == ["run-current", ""]
    assert candidates[0]["candidateId"] == "sci-020-legacy-bound"
    assert candidates[0]["claim"] == "legacy but formally bound statement"
    assert candidates[0]["rationale"] == "legacy but formally bound rationale"
