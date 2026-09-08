import json

from core.web.services.team_workflow.meeting_rounds import extract_discussion_markers


def _message(content):
    return {"status": "completed", "participantId": "researcher", "content": content}


def test_candidate_families_keep_highest_revision_and_original_order():
    result = extract_discussion_markers([_message("\n".join([
        "CANDIDATE: C01 | original | reason",
        "CANDIDATE: independent | other mechanism | reason",
        "CANDIDATE: C01-R2 | revised twice | reason",
        "CANDIDATE: C01-R1 | stale revision | reason",
        "CANDIDATE: C01 | echoed original | reason",
        "CANDIDATE: OTHER-RISK | independent | reason",
    ]))])
    assert [(c["candidateId"], c["statement"]) for c in result["proposedCandidates"]] == [
        ("C01-R2", "revised twice"), ("independent", "other mechanism"), ("OTHER-RISK", "independent"),
    ]


def test_evidence_requests_follow_revision_and_deduplicate_only_exact_requests():
    request = {"candidateRefs": ["C01"], "rationale": "test cost", "searchEnvelope": {"keywords": ["cost"]}}
    revised = {**request, "candidateRefs": ["C01-R1"]}
    distinct = {**revised, "searchEnvelope": {"keywords": ["toxicity"]}}
    messages = [_message("CANDIDATE: C01 | original | reason\nCANDIDATE: C01-R1 | revised | reason")]
    messages += [_message("EVIDENCE_REQUEST: " + json.dumps(r)) for r in (request, revised, distinct)]
    result = extract_discussion_markers(messages)
    assert result["evidenceRequests"] == [revised, distinct]


def test_request_without_candidate_proposal_keeps_bound_identity():
    request = {"candidateRefs": ["existing-R1"], "rationale": "test"}
    result = extract_discussion_markers([_message("EVIDENCE_REQUEST: " + json.dumps(request))])
    assert result["evidenceRequests"] == [request]


def test_revised_search_scope_replaces_old_scope_and_reports_unknown_alias():
    rows = [
        {"candidateRefs": ["C01"], "searchEnvelope": {"keywords": ["old scope"]}},
        {"candidateRefs": ["C01-R1"], "searchEnvelope": {"keywords": ["revised scope"]}},
        {"candidateRefs": ["A015-C01"], "searchEnvelope": {"keywords": ["invented alias"]}},
    ]
    messages = [_message("CANDIDATE: C01 | original | reason\nCANDIDATE: C01-R1 | revised | reason")]
    messages += [_message("EVIDENCE_REQUEST: " + json.dumps(r)) for r in rows]
    result = extract_discussion_markers(messages)
    assert result["evidenceRequests"] == [rows[1], rows[2]]
    from core.web.services.team_workflow.meeting_runtime import _collect_evidence_requests
    _, errors = _collect_evidence_requests(
        {"meetingType": "hypothesis_candidate_generation"}, result, [],
    )
    assert any(error["code"] == "candidate_ref_unbound" for error in errors)
