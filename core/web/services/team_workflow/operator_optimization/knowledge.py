"""Freeze targeted requests and consume existing accepted evidence without calls.

This owner does not start knowledge child runs. Their currency budget bridge
must exist before the paid collection entry can be enabled.
"""

from __future__ import annotations

import json

from core.research.operator_optimization.contracts import (
    ArtifactRef,
    OptimizationHypothesis,
)
from core.research.operator_optimization.knowledge import (
    AcceptedOperatorPackage,
    OperatorKnowledgeRequest,
    OperatorKnowledgeSnapshot,
)

from ..research_runtime.artifact_readback_registry import load_scoped_artifact_payload
from ..research_runtime.formal_write_runtime import get_write_store
from ..research_runtime.human_acceptance_artifact import (
    load_accepted_knowledge_packages_from_invocations,
)
from ..research_runtime.knowledge_sideflow_service import (
    DEFAULT_SOURCE_POLICY_VERSION,
    compute_invocation_fingerprints,
    ensure_knowledge_invocation,
)
from .discussion import _write_readback, discussion_input
from .store import CampaignConflict, read_campaign, update_campaign


def round_context(team_id: str, run_id: str):
    inputs = discussion_input(team_id, run_id)
    context = inputs["context"]
    campaign = read_campaign(
        team_id, context["researchProjectId"], context["optimizationCampaignId"]
    )
    record = next(item for item in campaign.rounds if item.runId == run_id)
    if (
        record.hypothesisRef is None
        or record.hypothesisRef.kind != "optimization_hypothesis"
    ):
        raise CampaignConflict("Knowledge preparation requires the selected hypothesis")
    frozen = json.loads(get_write_store().get_run(run_id).input_snapshot_json)
    if (
        record.protocolRef.model_dump(mode="json")
        != frozen["evaluationContract"].get("protocolRef")
        or record.baselineCandidateRef.model_dump(mode="json")
        != context["baselineCandidateRef"]
    ):
        raise CampaignConflict("Round protocol or baseline differs from its frozen run")
    hypothesis = OptimizationHypothesis.model_validate(
        read_ref(team_id, run_id, record.hypothesisRef)
    )
    if (
        hypothesis.optimizationCampaignId,
        hypothesis.roundId,
        hypothesis.parentCandidateRef,
    ) != (
        campaign.optimizationCampaignId,
        record.roundId,
        record.parentCandidateRef,
    ) or any(
        ref.model_dump(mode="json") not in context["observationRefs"]
        for ref in hypothesis.observationRefs
    ):
        raise CampaignConflict("Selected hypothesis differs from the frozen round")
    return campaign, record, hypothesis


def read_ref(team_id: str, run_id: str, ref: ArtifactRef) -> dict:
    envelope = load_scoped_artifact_payload(
        ref.kind,
        team_id=team_id,
        workflow_run_id=run_id,
        authority_run_id=run_id,
        record_id=ref.artifactId,
        content_hash=ref.sha256,
    )
    if envelope is None:
        raise CampaignConflict("Operator handoff source cannot be read back")
    return envelope["payload"]


def build_knowledge_request(team_id: str, run_id: str) -> OperatorKnowledgeRequest:
    campaign, record, hypothesis = round_context(team_id, run_id)
    snapshot = json.loads(get_write_store().get_run(run_id).input_snapshot_json)
    roots = snapshot.get("managedSourceRootIds") or []
    normalized_roots = tuple(sorted({str(root).strip().lower() for root in roots}))
    return OperatorKnowledgeRequest(
        teamId=team_id,
        researchProjectId=campaign.researchProjectId,
        optimizationCampaignId=campaign.optimizationCampaignId,
        roundId=record.roundId,
        runId=run_id,
        hypothesisRef=record.hypothesisRef,
        evidenceGaps=hypothesis.evidenceGaps,
        observationRefs=hypothesis.observationRefs,
        managedSourceRootIds=normalized_roots,
        sourcePolicyVersion=DEFAULT_SOURCE_POLICY_VERSION,
        sourcePolicy=snapshot["sourcePolicy"],
        reuseRequirements={
            "proposedChange": hypothesis.proposedChange,
            "mechanism": hypothesis.mechanism,
            "prediction": hypothesis.prediction,
            "counterevidence": hypothesis.counterevidence,
            "parentCandidateSourceHash": hypothesis.parentCandidateRef.sourceHash,
            "observationHashes": [ref.sha256 for ref in hypothesis.observationRefs],
            "protocolHash": snapshot["evaluationContract"]["protocolHash"],
        },
    )


def prepare_knowledge_request(
    team_id: str, run_id: str
) -> tuple[ArtifactRef, OperatorKnowledgeRequest]:
    request = build_knowledge_request(team_id, run_id)
    _, ref = _write_readback(
        team_id,
        run_id,
        kind="optimization_knowledge_request",
        identity="operator-knowledge-request:" + request.roundId,
        payload=request.model_dump(mode="json"),
    )
    return ref, request


def knowledge_invocation_arguments(
    request: OperatorKnowledgeRequest, *, question_id: str
) -> dict:
    """One source for future collection and current reusable-package matching."""
    return {
        "question_id": question_id,
        "scope": {
            "teamId": request.teamId,
            "researchProjectId": request.researchProjectId,
            "managedSourceRootIds": list(request.managedSourceRootIds),
        },
        "search_envelope": {"claimsToInvestigate": list(request.evidenceGaps)},
        "requirements": {
            "operatorClaims": request.reuseRequirements,
            "sourcePolicy": request.sourcePolicy,
        },
        "consumer_context": request.model_dump(mode="json"),
        "source_policy_version": request.sourcePolicyVersion,
    }


def verified_packages(team_id: str, run_id: str, request: OperatorKnowledgeRequest):
    store = get_write_store()
    run = store.get_run(run_id)
    fingerprints = compute_invocation_fingerprints(
        **knowledge_invocation_arguments(request, question_id=run.question_id)
    )
    invocations = store.read(
        lambda repo: repo.list_knowledge_invocations_for_parent(run_id)
    )
    matching = {
        inv.invocation_id
        for inv in invocations
        if inv.parent_run_id == run_id
        and inv.parent_node_id == "optimization_knowledge"
        and inv.request_hash == fingerprints["requestHash"]
        and inv.scope_hash == fingerprints["scopeHash"]
        and inv.source_policy_version == request.sourcePolicyVersion
        # This batch only consumes zero-call reuse. A newly executed child
        # needs the campaign currency bridge before it can be consumed here.
        and not inv.knowledge_child_run_id
    }
    return [
        package
        for package in load_accepted_knowledge_packages_from_invocations(
            store, team_id=team_id, parent_run_id=run_id
        )
        if package["invocationId"] in matching
    ]


def reusable_package(team_id: str, run_id: str, request: OperatorKnowledgeRequest):
    """Find an accepted package in the same authorized semantic source scope."""
    store = get_write_store()
    fingerprints = compute_invocation_fingerprints(
        **knowledge_invocation_arguments(
            request, question_id=store.get_run(run_id).question_id
        )
    )
    source = store.read(
        lambda repo: repo.find_reusable_knowledge_invocation(
            scope_hash=fingerprints["scopeHash"],
            search_envelope_hash=fingerprints["searchEnvelopeHash"],
            requirements_hash=fingerprints["requirementsHash"],
            source_policy_version=request.sourcePolicyVersion,
        )
    )
    if source is None or source.parent_run_id == run_id:
        return None
    return next(
        (
            package
            for package in load_accepted_knowledge_packages_from_invocations(
                store, team_id=team_id, parent_run_id=source.parent_run_id
            )
            if package["invocationId"] == source.invocation_id
        ),
        None,
    )


def knowledge_reuse_available(
    team_id: str, run_id: str, request: OperatorKnowledgeRequest
) -> bool:
    return bool(
        verified_packages(team_id, run_id, request)
        or reusable_package(team_id, run_id, request)
    )


def attach_reused_package(team_id: str, run_id: str, request: OperatorKnowledgeRequest):
    if reusable_package(team_id, run_id, request) is None:
        raise CampaignConflict(
            "Knowledge gaps require a matching accepted package; paid collection is not connected"
        )
    store = get_write_store()
    attempt = store.latest_attempt(run_id, "optimization_knowledge")
    if attempt is None or attempt.status not in {"starting", "dispatching", "running"}:
        raise CampaignConflict(
            "Knowledge reuse requires the actual active node attempt"
        )
    ensure_knowledge_invocation(
        store,
        parent_run_id=run_id,
        parent_node_id="optimization_knowledge",
        parent_node_run_id=attempt.node_run_id,
        parent_attempt=attempt.attempt,
        reuse_only=True,
        managed_source_root_ids=request.managedSourceRootIds,
        **knowledge_invocation_arguments(
            request, question_id=store.get_run(run_id).question_id
        ),
    )


def attach_round_ref(
    team_id: str, run_id: str, campaign, record, *, field: str, ref: ArtifactRef
):
    def attach(current):
        if current.status != "running" or current.activeRunId != run_id:
            raise CampaignConflict("Operator round stopped before handoff attachment")
        active = next(item for item in current.rounds if item.roundId == record.roundId)
        if (
            active.hypothesisRef != record.hypothesisRef
            or active.knowledgeRef != record.knowledgeRef
        ):
            raise CampaignConflict("Operator handoff inputs changed")
        previous = getattr(active, field)
        if previous is not None and previous != ref:
            raise CampaignConflict("Operator handoff is immutable")
        return current.model_copy(
            update={
                "rounds": tuple(
                    item.model_copy(update={field: ref})
                    if item.roundId == record.roundId
                    else item
                    for item in current.rounds
                )
            }
        )

    update_campaign(
        team_id,
        campaign.researchProjectId,
        campaign.optimizationCampaignId,
        expected_version=None,
        command_key=f"operator-{field}:" + record.roundId,
        command={"action": field, "ref": ref.model_dump(mode="json")},
        transform=attach,
    )


def publish_knowledge_snapshot(team_id: str, run_id: str) -> ArtifactRef:
    request_ref, request = prepare_knowledge_request(team_id, run_id)
    campaign, record, _ = round_context(team_id, run_id)
    if record.knowledgeRef is not None:
        load_knowledge_snapshot(team_id, run_id)
        return record.knowledgeRef
    packages = (
        verified_packages(team_id, run_id, request) if request.evidenceGaps else []
    )
    if request.evidenceGaps and not packages:
        attach_reused_package(team_id, run_id, request)
        packages = verified_packages(team_id, run_id, request)
    if request.evidenceGaps and not packages:
        raise CampaignConflict(
            "Knowledge gaps require a matching accepted package; paid collection is not connected"
        )
    snapshot = OperatorKnowledgeSnapshot(
        optimizationCampaignId=campaign.optimizationCampaignId,
        roundId=record.roundId,
        runId=run_id,
        requestRef=request_ref,
        hypothesisRef=request.hypothesisRef,
        mode="accepted_packages" if packages else "existing_observations",
        observationRefs=request.observationRefs,
        evidenceGaps=request.evidenceGaps,
        packages=tuple(
            AcceptedOperatorPackage(
                invocationId=p["invocationId"],
                canonicalRef=p["knowledgePackageRef"],
                sha256=p["packageContentHash"],
            )
            for p in sorted(packages, key=lambda p: p["invocationId"])
        ),
    )
    _, ref = _write_readback(
        team_id,
        run_id,
        kind="optimization_knowledge",
        identity="operator-knowledge:" + record.roundId,
        payload=snapshot.model_dump(mode="json"),
    )
    attach_round_ref(team_id, run_id, campaign, record, field="knowledgeRef", ref=ref)
    return ref


def load_knowledge_snapshot(team_id: str, run_id: str) -> OperatorKnowledgeSnapshot:
    campaign, record, hypothesis = round_context(team_id, run_id)
    if (
        record.knowledgeRef is None
        or record.knowledgeRef.kind != "optimization_knowledge"
    ):
        raise CampaignConflict("Round has no canonical knowledge snapshot")
    snapshot = OperatorKnowledgeSnapshot.model_validate(
        read_ref(team_id, run_id, record.knowledgeRef)
    )
    expected = build_knowledge_request(team_id, run_id)
    if snapshot.requestRef.kind != "optimization_knowledge_request" or (
        OperatorKnowledgeRequest.model_validate(
            read_ref(team_id, run_id, snapshot.requestRef)
        )
        != expected
    ):
        raise CampaignConflict("Knowledge request differs from the frozen round")
    if (
        snapshot.runId,
        snapshot.roundId,
        snapshot.optimizationCampaignId,
        snapshot.hypothesisRef,
        snapshot.observationRefs,
        snapshot.evidenceGaps,
    ) != (
        run_id,
        record.roundId,
        campaign.optimizationCampaignId,
        record.hypothesisRef,
        hypothesis.observationRefs,
        hypothesis.evidenceGaps,
    ):
        raise CampaignConflict("Knowledge snapshot differs from the frozen request")
    if snapshot.packages:
        available = {
            (p["invocationId"], p["knowledgePackageRef"], p["packageContentHash"])
            for p in verified_packages(team_id, run_id, expected)
        }
        if any(
            (p.invocationId, p.canonicalRef, p.sha256) not in available
            for p in snapshot.packages
        ):
            raise CampaignConflict(
                "Accepted knowledge source is no longer readable or accepted"
            )
    return snapshot
