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
