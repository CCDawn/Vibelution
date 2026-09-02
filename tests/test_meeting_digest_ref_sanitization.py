"""Digest draft ``proposedCandidates`` lineageRefs sanitization.

LLM digest drafts cite refs that drift out of the meeting's
``allowedEvidenceRefs`` whitelist (timestamp prefix transposition, truncated
prefixes, discussion ``msg:`` refs).  Saved unvalidated, the draft only
explodes later in ``approve_meeting_digest`` candidate registration with a 422
after partial closure side effects.  These tests pin the save-time sanitizer:

- case D: transposed/truncated refs are repaired to their whitelist full
  names, ``msg:`` refs are dropped, the content hash covers the sanitized
  content, and the surviving candidates pass the formal grounded registration
  whitelist check (no more 422);
- case E: candidates that cannot be repaired are dropped from
  ``proposedCandidates`` with ``validationErrors`` entries while untouched
  candidates and all other draft fields survive.
"""

from __future__ import annotations

import pytest

from core.web.services import team_service
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow.research_runtime import (
    agent_claim_evidence_materializer as materializer,
)
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from tests._support.team_workflow.helpers import _use_tmp_project_root

_WHITELIST = [
    "candidate-20260902171051-4876c228",
    "candidate-20260902171051-2adc8993",
    "artifact:boundary-matrix-1",
]


def _team(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    return team_service.create_team(name="digest sanitize team")["teamId"]


def _meeting(**overrides):
    payload = {
        "program": "XH-202619",
        "theme": "cc-gpu-operator-001",
        "campaign": "cc-campaign-gpu-operator-001",
        "question": "SCI-096",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-coordinator",
        "mode": "formal",
        "meetingRoundId": "meeting-digest-sanitize-1",
        "meetingType": "hypothesis_candidate_generation",
        "participants": ["agent-alpha", "agent-beta"],
        "discussionItemRefs": ["hypothesis_round:hround-demo-1"],
        "candidateAuthority": "formal_grounded_candidate",
        "allowedEvidenceRefs": list(_WHITELIST),
        "exploratoryDraftRefs": ["exploratory_draft:r0-a"],
        "revisionOrdinal": 1,
    }
    payload.update(overrides)
    return payload


def _proposal(candidate_id: str, refs: list[str]) -> dict:
    return {
        "candidateId": candidate_id,
        "statement": f"{candidate_id} is bounded and falsifiable.",
        "rationale": "strongest bounded evidence plan",
        "proposedBy": "agent-alpha",
        "lineageRefs": list(refs),
        "testablePrediction": "CHECK: blocking the receptor restores the outcome.",
        "falsifier": "Mechanism fails when the intervention is removed.",
        "axisProfile": {
            "mechanism": "receptor blockade restores signaling",
            "intervention": "antagonist administration",
            "observable": "task performance recovery",
            "population": "adult cohort",
            "boundary": "effect vanishes without the intervention",
        },
    }


def _draft(proposals: list[dict]) -> dict:
    return {
        "summary": "生成评审收敛出候选假说草案。",
        "agendaSummary": "候选生成议程",
        "agreements": [{"text": "以边界证据为准", "holders": ["agent-alpha"]}],
        "disagreements": [],
        "actionItems": [
            {"ownerRoleId": "role-researcher", "action": "补充边界证据"}
        ],
        "risks": ["证据边界不足"],
        "knowledgeCandidates": [],
        "sourceMessageRefs": ["msg:A015", "msg:A016"],
        "proposedCandidates": proposals,
    }


def _open_summarizing_meeting(team_id: str, **meeting_overrides) -> dict:
    meetings.create_meeting_round(team_id, _meeting(**meeting_overrides))
    meetings.begin_meeting_summary(
        team_id, "meeting-digest-sanitize-1", human_triggered=True
    )
    return meetings.get_meeting_round(team_id, "meeting-digest-sanitize-1")[
        "meetingRound"
    ]


# ---------------------------------------------------------------------------
# Case D — repair transposed/truncated refs, drop msg refs, hash the result
# ---------------------------------------------------------------------------


def test_digest_save_repairs_refs_and_hash_covers_sanitized_content(
    tmp_path, monkeypatch
):
    team_id = _team(tmp_path, monkeypatch)
    meeting_round = _open_summarizing_meeting(team_id)
    draft = _draft(
        [
            # Timestamp prefix transposed + a discussion message ref.
            _proposal(
                "san-1",
                [
                    "candidate-20260902170937-4876c228",
                    "msg:A015",
                ],
            ),
            # Truncated prefix only.
            _proposal("san-2", ["2adc8993"]),
        ]
    )

    result = meetings.submit_meeting_digest_draft(
        team_id, "meeting-digest-sanitize-1", draft
    )
    assert result["status"] == "awaiting_approval"
    saved = result["digestDraft"]

    candidates = saved["proposedCandidates"]
    assert [item["candidateId"] for item in candidates] == ["san-1", "san-2"]
    assert candidates[0]["lineageRefs"] == ["candidate-20260902171051-4876c228"]
    assert candidates[1]["lineageRefs"] == ["candidate-20260902171051-2adc8993"]
    # Nothing was dropped, so no validation errors were appended.
    assert saved.get("validationErrors", []) == []

    # The saved content hash covers the sanitized content: recomputing it over
    # the sanitized draft matches, while the pre-sanitization draft disagrees.
    assert saved["contentHash"] == meetings._digest_content_hash(saved)
    pre_sanitization = dict(saved)
    pre_sanitization["proposedCandidates"] = [
        _proposal("san-1", ["candidate-20260902170937-4876c228", "msg:A015"]),
        _proposal("san-2", ["2adc8993"]),
    ]
    assert saved["contentHash"] != meetings._digest_content_hash(pre_sanitization)

    # Non-candidate fields are untouched.
    assert saved["summary"] == draft["summary"]
    assert saved["agreements"] == draft["agreements"]
    assert saved["sourceMessageRefs"] == draft["sourceMessageRefs"]

    # The registration whitelist check behind approve_meeting_digest no longer
    # raises: the surviving refs are all inside the meeting whitelist.
    allowed = set(
        meetings._normalized_str_list(meeting_round.get("allowedEvidenceRefs"))
    )
    assert allowed
    for item in candidates:
        assert item["lineageRefs"] and set(item["lineageRefs"]) <= allowed

    # End to end: the real registration path accepts the sanitized proposals.
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain as chain_module

    monkeypatch.setattr(
        materializer,
        "materialize_candidate_claim_bindings_from_existing_evidence",
        lambda **_: [],
    )
    monkeypatch.setattr(
        chain_module,
        "_question_scope_envelope",
        lambda _team_id, _question_id: {
            "program": "XH-202619",
            "theme": "cc-gpu-operator-001",
            "campaign": "cc-campaign-gpu-operator-001",
            "question": "SCI-096",
            "branch": "main",
            "workflow": "hypothesis_first",
            "agentId": "agent-coordinator",
            "mode": "dev",
        },
    )
    appended = chain._append_generation_candidates(team_id, meeting_round, candidates)
    # Registration mints content-hash candidate ids; identity is the statement.
    assert len(appended) == 2
    assert {item["statement"] for item in appended} == {
        item["statement"] for item in candidates
    }
    for item in appended:
        assert item["candidateAuthority"] == "formal_grounded_candidate"
        assert set(item["lineageRefs"]) <= allowed


# ---------------------------------------------------------------------------
# Case E — unrepairable candidates are dropped with validationErrors
# ---------------------------------------------------------------------------


def test_digest_save_drops_unrepairable_candidates_with_validation_errors(
    tmp_path, monkeypatch
):
    team_id = _team(tmp_path, monkeypatch)
    _open_summarizing_meeting(team_id)
    clean = _proposal("clean-1", ["artifact:boundary-matrix-1"])
    draft = _draft(
        [
            clean,
            # One unresolvable ref among otherwise valid ones.
            _proposal(
                "broken-1",
                [
                    "candidate-20260902170937-deadbeef",
                    "artifact:boundary-matrix-1",
                ],
            ),
            # Only discussion message refs: empty after sanitization.
            _proposal("msg-only-1", ["msg:A015", "msg:A016"]),
            # No lineageRefs at all.
            _proposal("refs-missing-1", []),
        ]
    )

    result = meetings.submit_meeting_digest_draft(
        team_id, "meeting-digest-sanitize-1", draft
    )
    assert result["status"] == "awaiting_approval"
    saved = result["digestDraft"]

    # Only the clean candidate survives, byte-identical in its refs.
    candidates = saved["proposedCandidates"]
    assert [item["candidateId"] for item in candidates] == ["clean-1"]
    assert candidates[0]["lineageRefs"] == ["artifact:boundary-matrix-1"]

    # Every dropped candidate left a structured validation error.
    errors = saved["validationErrors"]
    assert {item["candidateId"] for item in errors} == {
        "broken-1",
        "msg-only-1",
        "refs-missing-1",
    }
    by_candidate = {item["candidateId"]: item["reason"] for item in errors}
    assert "candidate-20260902170937-deadbeef" in by_candidate["broken-1"]
    assert "lineage_refs_empty_after_sanitization" in by_candidate["msg-only-1"]
    assert "lineage_refs_empty_after_sanitization" in by_candidate["refs-missing-1"]

    # The saved hash still covers the sanitized content.
    assert saved["contentHash"] == meetings._digest_content_hash(saved)
