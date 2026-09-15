"""Freeze targeted requests, reuse accepted evidence or wait for native collection."""

from __future__ import annotations

import json

from core.research.operator_optimization.contracts import (
    ArtifactRef,
    OperatorRunContext,
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
    source_round_id = record.roundId
    if record.stage2SeedRef is not None and record.hypothesisRef is not None:
        from .rounds import read_stage2_seed

        seed = read_stage2_seed(team_id, record.stage2SeedRef)
        if record.hypothesisRef == seed.hypothesisRef:
            source_round_id = seed.hypothesisRoundId
    if (
        hypothesis.optimizationCampaignId,
        hypothesis.roundId,
        hypothesis.parentCandidateRef,
    ) != (
        campaign.optimizationCampaignId,
        source_round_id,
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
        run = get_write_store().get_run(run_id)
        try:
            context = OperatorRunContext.model_validate(
                json.loads(run.input_snapshot_json)["researchObjectiveContract"]
            )
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            context = None
        if context is not None and context.stage2SeedRef is not None:
            from .rounds import read_stage2_seed

            seed = read_stage2_seed(team_id, context.stage2SeedRef)
            direct_refs = {
                candidate: owner
                for candidate, owner in (
                    (seed.hypothesisRef, seed.hypothesisRunId),
                    (seed.knowledgeRef, seed.knowledgeRunId),
                    (seed.planRef, seed.planRunId),
                    (seed.evaluationRef, seed.sourceRunId),
                    (seed.feedbackRef, seed.sourceRunId),
                )
                if candidate is not None and owner
            }
            owner = direct_refs.get(ref)
            if owner:
                envelope = load_scoped_artifact_payload(
                    ref.kind,
                    team_id=team_id,
                    workflow_run_id=owner,
                    authority_run_id=owner,
                    record_id=ref.artifactId,
                    content_hash=ref.sha256,
                )
    if envelope is None:
        raise CampaignConflict("Operator handoff source cannot be read back")
    return envelope["payload"]


def _seed_for_record(team_id: str, record):
    if record.stage2SeedRef is None:
        return None
    from .rounds import read_stage2_seed

    return read_stage2_seed(team_id, record.stage2SeedRef)


def _read_seed_nested_ref(team_id: str, seed, ref: ArtifactRef) -> dict:
    envelope = load_scoped_artifact_payload(
        ref.kind,
        team_id=team_id,
        workflow_run_id=seed.knowledgeRunId,
        authority_run_id=seed.knowledgeRunId,
        record_id=ref.artifactId,
        content_hash=ref.sha256,
    )
    if envelope is None:
        raise CampaignConflict("Stage 2 nested knowledge source cannot be read back")
    return envelope["payload"]


def _verified_seed_packages(team_id: str, seed, snapshot: OperatorKnowledgeSnapshot):
    available = load_accepted_knowledge_packages_from_invocations(
        get_write_store(), team_id=team_id, parent_run_id=seed.knowledgeRunId
    )
    by_identity = {
        (p["invocationId"], p["knowledgePackageRef"], p["packageContentHash"]): p
        for p in available
        if child_costs_settled(get_write_store(), p.get("producerRunId", ""))
    }
    wanted = [
        (p.invocationId, p.canonicalRef, p.sha256) for p in snapshot.packages
    ]
    if any(identity not in by_identity for identity in wanted):
        raise CampaignConflict("Stage 2 accepted knowledge is no longer verifiable")
    return [by_identity[identity] for identity in wanted]


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
        and inv.request_hash == compute_invocation_fingerprints(
            **knowledge_invocation_arguments(request, question_id=run.question_id),
            invocation_attempt=inv.parent_attempt,
        )["requestHash"]
        and inv.scope_hash == fingerprints["scopeHash"]
        and inv.source_policy_version == request.sourcePolicyVersion
        and child_costs_settled(store, inv.knowledge_child_run_id)
    }
    return [
        package
        for package in load_accepted_knowledge_packages_from_invocations(
            store, team_id=team_id, parent_run_id=run_id
        )
        if package["invocationId"] in matching
    ]


def child_costs_settled(store, child_run_id):
    return store.read(lambda repo: child_costs_settled_in_repo(repo, child_run_id))


def child_costs_settled_in_repo(repo, child_run_id):
    if not child_run_id:
        return True
    from .knowledge_budget_runtime import SOURCE_NODES

    child = repo.get_run(child_run_id)
    if child is None or child.status != "succeeded":
        return False
    parent = repo.get_run(child.parent_run_id) if child.parent_run_id else None
    if parent is None:
        return False
    if parent.workflow_id != "operator-optimization":
        return True
    rows = repo.execute("SELECT node_run_id, status, settled_json FROM budget_receipts WHERE run_id = ?",
                        (child_run_id,)).fetchall()
    by_node = {row[0]: row for row in rows}
    for node_id in SOURCE_NODES:
        attempt = repo.latest_attempt(child_run_id, node_id)
        row = by_node.get(attempt.node_run_id) if attempt else None
        metadata = json.loads(row[2] or "{}").get("operatorModelBudget", {}) if row else {}
        if (attempt is None or attempt.status != "succeeded" or row is None or row[1] != "settled"
                or metadata.get("budgetKind") != "knowledge" or not metadata.get("callsUsed")
                or metadata.get("costStatus") != "settled"):
            return False
    return all(row[1] in {"settled", "released", "voided"} for row in rows)


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
    if source is None or source.parent_run_id == run_id or not child_costs_settled(store, source.knowledge_child_run_id):
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


def collect_or_wait(team_id: str, run_id: str, request: OperatorKnowledgeRequest):
    from .knowledge_wait import KnowledgeChildPending

    store = get_write_store()
    campaign, _, _ = round_context(team_id, run_id)
    if not campaign.authorizedBy or not campaign.budget.authorized or campaign.budget.knowledge is None:
        raise CampaignConflict("Knowledge collection requires its explicit authorized budget")
    attempt = store.latest_attempt(run_id, "optimization_knowledge")
    if attempt is None or attempt.status not in {"starting", "dispatching", "running"}:
        raise CampaignConflict("Knowledge collection requires its actual active node attempt")
    result = ensure_knowledge_invocation(store, parent_run_id=run_id,
        parent_node_id="optimization_knowledge", parent_node_run_id=attempt.node_run_id,
        parent_attempt=attempt.attempt, managed_source_root_ids=request.managedSourceRootIds,
        **knowledge_invocation_arguments(request, question_id=store.get_run(run_id).question_id))
    invocation = store.read(lambda repo: repo.get_knowledge_invocation(result["invocation"].invocation_id))
    if invocation.parent_node_run_id != attempt.node_run_id:
        raise CampaignConflict("Knowledge invocation belongs to a previous parent attempt")
    if invocation.status in {"failed", "cancelled"}:
        raise CampaignConflict("Knowledge collection failed; inspect the child run before a new experiment")
    if invocation.status == "completed" and invocation.handoff_state == "accepted":
        from ..research_runtime.knowledge_sideflow_service import knowledge_result_event_id

        if invocation.knowledge_child_run_id and store.get_event_by_id(
                knowledge_result_event_id(invocation.invocation_id, invocation.package_content_hash)) is None:
            raise KnowledgeChildPending(invocation.invocation_id, invocation.knowledge_child_run_id)
        if not child_costs_settled(store, invocation.knowledge_child_run_id):
            raise CampaignConflict("Knowledge collection costs are not settled")
        return
    if not invocation.knowledge_child_run_id:
        raise CampaignConflict("Knowledge collection has no canonical child run")
    raise KnowledgeChildPending(invocation.invocation_id, invocation.knowledge_child_run_id)


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
        if reusable_package(team_id, run_id, request) is not None:
            attach_reused_package(team_id, run_id, request)
        else:
            collect_or_wait(team_id, run_id, request)
        packages = verified_packages(team_id, run_id, request)
    if request.evidenceGaps and not packages:
        raise CampaignConflict(
            "Knowledge gaps require a delivered accepted package"
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
    seed = _seed_for_record(team_id, record)
    if seed is not None and record.knowledgeRef == seed.knowledgeRef:
        if (
            snapshot.runId,
            snapshot.optimizationCampaignId,
            snapshot.hypothesisRef,
        ) != (
            seed.knowledgeRunId,
            campaign.optimizationCampaignId,
            seed.hypothesisRef,
        ):
            raise CampaignConflict("Stage 2 knowledge differs from its frozen seed")
        request = OperatorKnowledgeRequest.model_validate(
            _read_seed_nested_ref(team_id, seed, snapshot.requestRef)
        )
        if (
            request.runId,
            request.optimizationCampaignId,
            request.hypothesisRef,
        ) != (
            seed.knowledgeRunId,
            campaign.optimizationCampaignId,
            seed.hypothesisRef,
        ):
            raise CampaignConflict("Stage 2 knowledge request differs from its seed")
        _verified_seed_packages(team_id, seed, snapshot)
        return snapshot
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


def planning_knowledge_evidence(team_id: str, run_id: str, record, snapshot):
    seed = _seed_for_record(team_id, record)
    if seed is not None and record.knowledgeRef == seed.knowledgeRef:
        return _verified_seed_packages(team_id, seed, snapshot)
    if not snapshot.packages:
        return []
    return [
        package
        for package in verified_packages(
            team_id, run_id, build_knowledge_request(team_id, run_id)
        )
        if package["invocationId"] in {ref.invocationId for ref in snapshot.packages}
    ]
