"""Project bounded source excerpts from the accepted knowledge child run."""

from __future__ import annotations

import json
from collections import defaultdict

from core.research.workflow.contracts._canonical import sha256_hex
from core.research.workflow.knowledge_sideflow_definition import KNOWLEDGE_SIDEFLOW_WORKFLOW_ID

from ..research_runtime.artifact_readback_registry import load_scoped_artifact_payload, parse_canonical_ref
from ..research_runtime.knowledge_artifact_authority import approved_package_source_candidates
from .store import CampaignConflict


_EVIDENCE_NODES = {
    "evidence_card_batch": "source_extraction",
    "evidence_relation_graph": "evidence_relations",
}
_MAX_PER_DIRECTION = 4
_QUOTE_LIMIT = 1000
_REFUTING_DISPOSITIONS = {"challenges_ontology", "alternative_interpretation"}


def _producing_run(repo, package):
    invocation = repo.get_knowledge_invocation(package["invocationId"])
    if invocation is None:
        raise CampaignConflict("Accepted knowledge invocation is missing")
    scope = invocation.scope_hash
    seen = set()
    while invocation is not None:
        if (invocation.invocation_id in seen or invocation.scope_hash != scope
                or invocation.status != "completed" or invocation.handoff_state != "accepted"
                or invocation.package_content_hash != package["packageContentHash"]):
            raise CampaignConflict("Accepted knowledge producer does not match the delivered package")
        seen.add(invocation.invocation_id)
        if invocation.knowledge_child_run_id:
            return repo.get_run(invocation.knowledge_child_run_id)
        event = repo.get_event_by_id(f"evt-{invocation.invocation_id}-reused")
        if event is None:
            # A historical package can predate persisted producer links.
            return None
        reused = json.loads(event.payload_json)
        if (event.run_id != invocation.parent_run_id
                or event.event_type != "knowledge_invocation_reused"
                or reused.get("invocationId") != invocation.invocation_id
                or reused.get("packageContentHash") != package["packageContentHash"]):
            raise CampaignConflict("Accepted knowledge reuse differs from its delivery event")
        invocation = repo.get_knowledge_invocation(reused.get("reusedFromInvocationId", ""))
    raise CampaignConflict("Accepted knowledge producer is missing")


def _receipt_reference(repo, child, kind, authority_run_id: str) -> str:
    attempt = repo.latest_attempt(child.run_id, _EVIDENCE_NODES[kind])
    refs = set()
    if attempt is not None and attempt.status == "succeeded":
        for row in repo.list_receipts_for_node_run(attempt.node_run_id):
            if (row[1], row[3], row[4], bool(row[9])) != (child.run_id, child.team_id, kind, True):
                continue
            ref = json.loads(row[5] or "{}").get("canonicalRef", "")
            parsed = parse_canonical_ref(ref)
            if parsed == {"kind": kind, "teamId": child.team_id,
                          "authorityRunId": authority_run_id, "contentHash": row[7]}:
                refs.add(ref)
    if len(refs) != 1:
        raise CampaignConflict(f"Accepted knowledge requires one verified {kind} receipt")
    return next(iter(refs))


def _package_receipts(repo, team_id: str, project_id: str, package):
    child = _producing_run(repo, package)
    if child is None and not package.get("producerRunId"):
        return None, {}
    scoped = parse_canonical_ref(package["knowledgePackageRef"])
    if (child is None or child.team_id != team_id or child.project_id != project_id
            or child.workflow_id != KNOWLEDGE_SIDEFLOW_WORKFLOW_ID or child.status != "succeeded"
            or scoped is None or scoped["teamId"] != team_id):
        raise CampaignConflict("Accepted knowledge producer is outside the planning scope")
    authority = scoped["authorityRunId"]
    return child, {kind: _receipt_reference(repo, child, kind, authority) for kind in _EVIDENCE_NODES}


def _read_evidence(ref: str, child) -> dict:
    parsed = parse_canonical_ref(ref)
    payload = load_scoped_artifact_payload(
        parsed["kind"], team_id=child.team_id, authority_run_id=parsed["authorityRunId"],
        workflow_run_id=child.run_id,
    )
    if payload is None or sha256_hex(payload) != parsed["contentHash"]:
        raise CampaignConflict(f"Accepted knowledge {parsed['kind']} changed after verification")
    return payload


def _excerpt_cards(evidence: dict, graph: dict, approved_sources: set[str]) -> list[dict]:
    counters = defaultdict(lambda: defaultdict(list))
    for counter in graph.get("counterEvidenceRefs", []):
        disposition = counter.get("disposition")
        claim = counter.get("claim")
        if disposition and claim:
            direction = "refutes" if disposition in _REFUTING_DISPOSITIONS else "qualifies"
            counters[counter["evidenceRef"]][direction].append({
                "claim": claim,
                "disposition": disposition,
            })
    linked = {ref for edge in graph.get("edges", []) for ref in edge.get("evidenceRefs", [])}

    selected = defaultdict(list)
    for card in evidence["evidenceCards"]:
        locator = card.get("locator") or {}
        quote = card.get("quote") or ""
        source = card.get("collectionEnvelope") or {}
        source_url = source.get("sourceUrl") or locator.get("url") or ""
        if (card.get("candidateId") not in approved_sources
                or card.get("reviewStatus") in {"rejected", "stale"}
                or (locator.get("kind") == "evidence_ref" and not source_url)
                or not locator or not quote):
            continue
        evidence_id = card["claimEvidenceId"]
        relations = dict(counters.get(evidence_id, {}))
        if not relations and evidence_id in linked and card.get("supportLevel") == "contradicts":
            relations["refutes"] = []
        if evidence_id in linked and card.get("supportLevel") == "supports":
            relations["supports"] = []
        for direction, counter_claims in relations.items():
            if len(selected[direction]) >= _MAX_PER_DIRECTION:
                continue
            selected[direction].append({
                "claimEvidenceId": evidence_id,
                "claimId": card["claimId"],
                "sourceSupportLevel": card.get("supportLevel"),
                "direction": direction,
                "counterClaims": counter_claims[:_MAX_PER_DIRECTION],
                "sourceId": card["sourceId"],
                "sourceRevision": card["sourceRevision"],
                "sourceUrl": source_url,
                "locator": locator,
                "quote": quote[:_QUOTE_LIMIT],
                "quoteHash": card["quoteHash"],
                "quoteTruncated": len(quote) > _QUOTE_LIMIT,
            })
    return [card for direction in ("supports", "refutes", "qualifies") for card in selected[direction]]


def project_package_evidence(store, team_id: str, project_id: str, package: dict) -> dict:
    child, refs = store.read(lambda repo: _package_receipts(repo, team_id, project_id, package))
    if child is None:
        return {**package, "evidenceCards": []}
    approved = approved_package_source_candidates(
        team_id=team_id, authority_run_id=parse_canonical_ref(package["knowledgePackageRef"])["authorityRunId"],
        workflow_run_id=child.run_id, package=package["package"],
    )
    cards = _read_evidence(refs["evidence_card_batch"], child)
    graph = _read_evidence(refs["evidence_relation_graph"], child)
    return {**package, "producerRunId": child.run_id, "evidenceArtifactRefs": refs,
            "evidenceCards": _excerpt_cards(cards, graph, approved)}
