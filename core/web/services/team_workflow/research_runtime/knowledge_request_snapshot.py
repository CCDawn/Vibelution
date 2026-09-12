"""Carry the fingerprinted knowledge request into the native collection scope."""
from __future__ import annotations

from copy import deepcopy


def validate_child_request(invocation, request: dict) -> dict:
    from .knowledge_sideflow_service import (
        KnowledgeSideflowError, compute_invocation_fingerprints,
    )

    frozen = deepcopy(request)
    actual = compute_invocation_fingerprints(
        question_id=invocation.question_id,
        scope=frozen["scope"],
        search_envelope=frozen["searchEnvelope"],
        requirements=frozen["requirements"],
        source_policy_version=invocation.source_policy_version,
        consumer_context=frozen["consumerContext"],
    )
    expected = {
        "scopeHash": invocation.scope_hash,
        "searchEnvelopeHash": invocation.search_envelope_hash,
        "requirementsHash": invocation.requirements_hash,
        "requestHash": invocation.request_hash,
    }
    if actual != expected:
        raise KnowledgeSideflowError(
            "Child request differs from its invocation", code="knowledge_request_mismatch"
        )
    return frozen


def collection_request_scope(snapshot: dict) -> dict:
    request = snapshot.get("knowledgeRequest")
    if request is None:
        return {}
    # This is evidence input, never a source of workflow/model authority.
    return {
        "knowledgeRequest": deepcopy(request),
        "searchEnvelope": deepcopy(request["searchEnvelope"]),
        "requirements": deepcopy(request["requirements"]),
        "seedQueries": list(request["searchEnvelope"].get("claimsToInvestigate") or [])
        + list(request["searchEnvelope"].get("keywords") or []),
    }
