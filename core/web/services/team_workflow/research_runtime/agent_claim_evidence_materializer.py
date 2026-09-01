"""Materialize verified Agent extraction output into canonical ClaimEvidence.

Source Collection remains the authority for candidate extraction writeback.  A
formal workflow may acknowledge an ``evidence_card_batch`` only after the
anchored claims have been copied into the canonical Evidence Store and can be
read back there.  This module is that explicit boundary; it deliberately skips
summaries that do not contain a verbatim, bounded source quote.

Every materializable claim is first proposed in the team's question-scoped
claim ledger (the production writer the R2.2 claim belief gate reads), and the
ClaimEvidence record is registered under the ledger's claim id.  That bridge is
what lets ``evaluate_claim_belief_gate`` find an evaluable ledger row for every
claim id an evidence record references; self-minted evidence ids without a
ledger row would keep the gate fail-closed forever.

Candidate dimensions: extraction records anchor source facts to *source*
candidate ids.  Hypothesis candidates receive separate core-claim rows only
when their own ``lineageRefs`` cite the exact source.  Evidence is never copied
across every hypothesis id, so one candidate cannot unlock another.

Chain-level collections (the hypothesis-first chain's ``request_new_evidence``
runs) never open an extraction stage task and never own a formal workflow run,
so the stage-task entry points above can never fire for them.  The chain-level
bridge (:func:`materialize_chain_collection_evidence`) crosses the same
boundary for their collected source candidates at handoff time, binding the
request's review decision candidates (``hypothesisCandidateIds``) instead of
formal ``lineageRefs``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .source_extraction_evidence_cards import normalize_challenge_evidence_fields


class EvidenceMaterializationError(RuntimeError):
    """Raised when a formal task cannot be materialized within its frozen scope."""


_LEDGER_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")


def _text(value: object) -> str:
    return str(value or "").strip()


def _sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _claim_locator(claim: dict[str, Any]) -> dict[str, Any] | None:
    explicit = claim.get("citationLocator")
    if isinstance(explicit, dict) and _text(explicit.get("kind")):
        locator = dict(explicit)
        if any(locator.get(key) not in (None, "") for key in ("page", "section", "anchor", "url")):
            return locator

    source_ref = _text(claim.get("sourceRef") or claim.get("source_url"))
    page = claim.get("page")
    if isinstance(page, int) and not isinstance(page, bool) and page > 0:
        return {"kind": "pdf_page", "page": page, **({"url": source_ref} if source_ref else {})}
    page_range = _text(claim.get("pageRange"))
    if page_range:
        return {"kind": "page_range", "anchor": page_range, **({"url": source_ref} if source_ref else {})}
    citation = _text(claim.get("citation"))
    if citation:
        return {"kind": "citation", "anchor": citation, **({"url": source_ref} if source_ref else {})}
    evidence_ref = _text(claim.get("evidenceRef"))
    if evidence_ref:
        return {"kind": "evidence_ref", "anchor": evidence_ref, **({"url": source_ref} if source_ref else {})}
    return None


def _materializable_claims(
    task: dict[str, Any],
) -> Iterable[tuple[dict[str, Any], dict[str, Any], str]]:
    """Yield ``(extraction, claim, path)`` for every claim the materializer touches.

    The path is the collection-qualified location of the claim inside the task
    result (``candidateExtractions[0].keyFindings[1]``), so contract errors name
    the exact entry the Agent must fix.  The writeback acceptance boundary
    reuses this generator together with
    :func:`normalize_challenge_evidence_fields` to reject violating writebacks
    at the door, which guarantees both boundaries enforce one rule set: a
    writeback is rejected exactly when materialization would raise.
    """
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    for collection in ("candidateExtractions", "recordExtractions"):
        for extraction_index, raw_extraction in enumerate(result.get(collection) or []):
            if not isinstance(raw_extraction, dict):
                continue
            extraction = dict(raw_extraction)
            if _text(extraction.get("decision")).lower() == "exclude":
                continue
            evidence_status = _text(extraction.get("evidenceStatus")).lower()
            if evidence_status in {"missing_evidence_anchor", "missing", "unverified"}:
                continue
            extraction_path = f"{collection}[{extraction_index}]"
            claims_items = list(extraction.get("claims") or [])
            findings_items = list(extraction.get("keyFindings") or [])
            nested_claims = [
                dict(item)
                for item in claims_items + findings_items
                if isinstance(item, dict)
            ]
            if nested_claims:
                for list_key, items in (
                    ("claims", claims_items),
                    ("keyFindings", findings_items),
                ):
                    for claim_index, raw_claim in enumerate(items):
                        if not isinstance(raw_claim, dict):
                            continue
                        yield (
                            extraction,
                            dict(raw_claim),
                            f"{extraction_path}.{list_key}[{claim_index}]",
                        )
                continue
            # The extraction writeback contract lists ``evidenceRefs`` beside
            # ``claims``/``keyFindings`` as a valid evidence anchor, and
            # ``build_source_extraction_evidence_cards`` already materializes
            # such flat extractions (``fact`` plus anchored ``evidenceRefs``)
            # as one card per source.  Bridge the same shape here instead of
            # dropping the extraction: the first quote-bearing evidenceRef
            # supplies the verbatim quote and its id the ``evidenceRef``
            # locator required by the anchor checks below.
            flat_fact = _text(extraction.get("fact"))
            if not flat_fact:
                continue
            for raw_ref in extraction.get("evidenceRefs") or []:
                if not isinstance(raw_ref, dict):
                    continue
                quote = _text(raw_ref.get("quote"))
                ref_id = _text(
                    raw_ref.get("id") or raw_ref.get("evidenceRefId") or raw_ref.get("refId")
                )
                if quote and ref_id:
                    yield extraction, {
                        "fact": flat_fact,
                        "quote": quote,
                        "evidenceRef": ref_id,
                    }, extraction_path
                    break


def _ledger_claim_id(
    *,
    question_scope: Mapping[str, Any],
    claim_text: str,
    candidate_id: str,
) -> str:
    """Deterministic, candidate-dimensioned ledger claim id.

    The ledger's own seed hashes only (claim, scopeHash, createdBy), so two
    hypothesis candidates whose statements are byte-identical would share one
    claim row and merge their evidence into a single belief entry.  The
    materializer therefore proposes an explicit id that also binds the
    candidate dimension: the same candidate replaying the same claim text
    still reuses its row, while a sibling candidate with identical text gets
    its own row and belief entry.
    """
    normalized_candidate = _text(candidate_id)
    if not normalized_candidate:
        raise EvidenceMaterializationError(
            "claim ledger proposal requires a candidate dimension"
        )
    seed = _sha256(
        {
            **{field: _text(question_scope.get(field)) for field in _LEDGER_SCOPE_FIELDS},
            "agentId": _text(question_scope.get("agentId")),
            "mode": _text(question_scope.get("mode")).lower(),
            "claim": claim_text,
            "candidateId": normalized_candidate,
        }
    )
    return f"claim-{seed[:20]}"


def _propose_ledger_claim(
    *,
    team_id: str,
    question_scope: Mapping[str, Any],
    claim_text: str,
    candidate_id: str = "",
) -> dict[str, Any]:
    """Propose one anchored claim in the question-scoped claim ledger.

    Hypothesis candidate core claims must pass ``candidate_id``: the ledger's
    own seed hashes only (claim, scopeHash, createdBy), so byte-identical
    candidate statements would otherwise share one claim row and merge their
    evidence into a single belief entry.  Source fact claims deliberately omit
    the dimension so identical facts across source candidates still collapse
    into one ledger row (the reconcile contract asserts that dedup, and fact
    rows never enter the hypothesis candidates' strict gate path).  Failures
    are surfaced as ``EvidenceMaterializationError`` instead of being
    swallowed, so an unproposable claim can never silently skip the claim
    belief gate.
    """
    from core.web.services.team_workflow import claim_ledger

    identity = {
        field: _text(question_scope.get(field)) for field in _LEDGER_SCOPE_FIELDS
    }
    agent_id = _text(question_scope.get("agentId"))
    mode = _text(question_scope.get("mode")).lower()
    if not all(identity.values()) or not agent_id:
        raise EvidenceMaterializationError(
            "question claim scope is incomplete for claim ledger proposal"
        )
    payload: dict[str, Any] = {
        **identity,
        "agentId": agent_id,
        "mode": mode or claim_ledger.DEFAULT_MODE,
        "claim": claim_text,
        "createdBy": agent_id,
        "source": "agent",
    }
    if _text(candidate_id):
        payload["claimId"] = _ledger_claim_id(
            question_scope=question_scope,
            claim_text=claim_text,
            candidate_id=candidate_id,
        )
    try:
        proposed = claim_ledger.propose_claim(team_id, payload)
    except Exception as exc:  # noqa: BLE001 - structured exposure, never swallowed
        raise EvidenceMaterializationError(
            f"claim ledger proposal failed for question {identity['question']}: {exc}"
        ) from exc
    claim = proposed.get("claim") if isinstance(proposed, Mapping) else None
    claim_id = _text(claim.get("claimId")) if isinstance(claim, Mapping) else ""
    if not claim_id:
        raise EvidenceMaterializationError(
            "claim ledger proposal returned no claim id"
        )
    return {"claimId": claim_id, "status": _text(proposed.get("status"))}


def _normalized_hypothesis_candidate_ids(value: object) -> list[str]:
    """Deduplicated, order-preserving hypothesis candidate id list."""
    raw = list(value) if isinstance(value, (list, tuple, set)) else []
    return list(dict.fromkeys(_text(item) for item in raw if _text(item)))


def _normalized_hypothesis_candidate_bindings(
    *,
    team_id: str,
    question_scope: Mapping[str, Any],
    candidate_ids: list[str],
    supplied: object,
) -> dict[str, dict[str, Any]]:
    """Resolve candidate-authored core claims and explicit lineage refs."""

    raw_bindings = supplied if isinstance(supplied, Mapping) else {}
    if not raw_bindings and candidate_ids:
        try:
            from .hypothesis_first_chain import list_hypothesis_candidates

            listing = list_hypothesis_candidates(
                _text(team_id),
                question_id=_text(question_scope.get("question")).upper(),
            )
            raw_bindings = {
                _text(item.get("candidateId")): {
                    "claimText": _text(item.get("statement"))[:4000],
                    "lineageRefs": item.get("lineageRefs") or [],
                }
                for item in list(listing.get("candidates") or [])
                if isinstance(item, Mapping) and _text(item.get("candidateId"))
            }
        except Exception as exc:  # noqa: BLE001 - expose unavailable authority
            raise EvidenceMaterializationError(
                f"hypothesis candidate lineage is unavailable: {exc}"
            ) from exc

    resolved: dict[str, dict[str, Any]] = {}
    for candidate_id in candidate_ids:
        raw = raw_bindings.get(candidate_id)
        if not isinstance(raw, Mapping):
            continue
        claim_text = _text(raw.get("claimText") or raw.get("statement"))[:4000]
        lineage_refs = list(
            dict.fromkeys(
                _text(item)[:300]
                for item in list(raw.get("lineageRefs") or [])
                if _text(item)[:300]
            )
        )
        if claim_text and lineage_refs:
            resolved[candidate_id] = {
                "claimText": claim_text,
                "lineageRefs": lineage_refs,
            }
    return resolved


def _collection_run_hypothesis_candidate_ids(source_collection_run_id: str) -> list[str]:
    """Read the hypothesis candidate ids persisted on the canonical run scope.

    Runs created before the bridge (or by entrypoints that never carry
    hypothesis candidates) have no ``scope.hypothesisCandidateIds``; they keep
    the legacy single-dimension materialization, so an unreadable run fails
    open to an empty list here while the downstream gate stays fail-closed.
    """
    from core.web.services import data_processing_service

    run_id = _text(source_collection_run_id)
    if not run_id:
        return []
    try:
        run = data_processing_service.get_processing_run(run_id)
    except Exception:  # noqa: BLE001 - absent run keeps legacy behavior
        return []
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    return _normalized_hypothesis_candidate_ids(scope.get("hypothesisCandidateIds"))


def _backfill_replayed_task_retrieved_at(task: dict[str, Any]) -> dict[str, Any]:
    """Normalize a persisted task result at the materializer read point.

    Production run-882610596ddb: a node retry (RETRY_NODE) replays the
    previously persisted task result straight into materialization without
    crossing the writeback boundary, so the writeback's ``retrieved_at``
    backfill never ran for it and the fail-closed contract rejected the
    replayed data 3 seconds after dispatch.  The same single-authoritative
    backfill (parent entries AND materializable nested claims) therefore runs
    here, on the read point, before the contract validator.  Read-point only:
    the canonical store keeps what the writeback boundary accepted.
    """
    from core.web.services.team_workflow.source_collection.extraction_retrieved_at_backfill import (
        backfill_persisted_extraction_task_retrieved_at,
    )

    return backfill_persisted_extraction_task_retrieved_at(task)


def materialize_claim_evidence_from_task(
    *,
    project_root: str | Path,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
    task: dict[str, Any],
    model_ref: str,
    question_scope: Mapping[str, Any],
    hypothesis_candidate_ids: object = None,
    hypothesis_candidate_bindings: object = None,
) -> list[dict[str, Any]]:
    """Register only fully anchored claims; repeated calls remain idempotent.

    ``question_scope`` is the server-authoritative scope envelope for the
    formal run's question (``_question_scope_envelope``).  Every materialized
    claim is proposed in the team claim ledger first and the canonical
    ClaimEvidence record is registered under the ledger claim id, so the
    claim belief gate can evaluate the candidate from real extraction output.

    A hypothesis candidate receives a relation only when its own formal
    statement and ``lineageRefs`` explicitly select this source.  Candidate
    ids alone are intentionally insufficient.
    """
    from core.research.evidence import ClaimEvidenceStore

    if not isinstance(question_scope, Mapping):
        raise EvidenceMaterializationError(
            "question claim scope is required to bridge materialized evidence "
            "to the claim ledger"
        )
    normalized_team = _text(team_id)
    normalized_workflow_run = _text(workflow_run_id)
    normalized_source_run = _text(source_collection_run_id)
    if _text(task.get("teamId")) != normalized_team:
        raise EvidenceMaterializationError("stage task team does not match the formal workflow")
    if _text(task.get("runId")) != normalized_source_run:
        raise EvidenceMaterializationError("stage task source collection run does not match the formal workflow")
    if _text(task.get("stageId")).lower() != "extraction":
        raise EvidenceMaterializationError("only extraction stage tasks may materialize ClaimEvidence")
    # Replay/read-point normalization before the fail-closed contract
    # validator: fresh writebacks were already backfilled at the writeback
    # boundary; replayed persisted results (node retry) are repaired here, so
    # both paths reach the validator with server-authoritative times.
    task = _backfill_replayed_task_retrieved_at(task)

    extractor_agent_id = _text(task.get("agentId"))
    normalized_model_ref = _text(model_ref)
    bridged_candidate_ids = _normalized_hypothesis_candidate_ids(
        hypothesis_candidate_ids
    )
    candidate_bindings = _normalized_hypothesis_candidate_bindings(
        team_id=normalized_team,
        question_scope=question_scope,
        candidate_ids=bridged_candidate_ids,
        supplied=hypothesis_candidate_bindings,
    )
    store = ClaimEvidenceStore(project_root)
    materialized: list[dict[str, Any]] = []
    for extraction, claim, claim_path in _materializable_claims(task):
        challenge_evidence = normalize_challenge_evidence_fields(
            claim,
            extraction,
            path=claim_path,
        )
        candidate_id = _text(
            challenge_evidence.get("candidateId")
            or challenge_evidence.get("recordId")
        )
        claim_text = _text(challenge_evidence.get("fact"))
        quote = _text(claim.get("quote"))
        source_ref = _text(
            claim.get("sourceRef") or challenge_evidence.get("source_url")
        )
        locator = _claim_locator(claim)
        if not all((candidate_id, claim_text, quote, source_ref, locator)):
            continue
        if not extractor_agent_id or not normalized_model_ref:
            raise EvidenceMaterializationError(
                "anchored model evidence requires extractorAgentId and modelRef"
            )
        source_revision = "sha256:" + _sha256(
            {
                "sourceRef": source_ref,
                "locator": locator,
                "quote": quote,
                "title": challenge_evidence["title"],
                "source_type": challenge_evidence["source_type"],
                "source_url": challenge_evidence["source_url"],
                "retrieved_at": challenge_evidence["retrieved_at"],
                "fact": challenge_evidence["fact"],
                "relation": challenge_evidence["relation"],
                "verification_status": challenge_evidence[
                    "verification_status"
                ],
            }
        )
        # The claim ledger owns the claim identity (content + scope hash), so
        # the evidence record bridges to the exact row the belief gate reads.
        # Self-minted ids (the legacy ``workflow-claim-<sha>`` scheme) could
        # never be proposed in advance because their hash included the future
        # workflow run id, which left the gate permanently claim-data-missing.
        # No candidate dimension here: identical facts across source
        # candidates intentionally collapse into one ledger row.
        proposed = _propose_ledger_claim(
            team_id=normalized_team,
            question_scope=question_scope,
            claim_text=claim_text,
        )
        relation_support_level = {
            "supports": "supports",
            "challenges": "contradicts",
        }.get(challenge_evidence["relation"], "insufficient")
        evidence_payload = {
            "claimId": proposed["claimId"],
            "candidateId": candidate_id,
            "sourceId": source_ref,
            "sourceRevision": source_revision,
            "locator": locator,
            "quote": quote,
            "evidenceKind": "primary_result",
            "reasoningRole": "fact",
            "supportLevel": relation_support_level,
            "extractionMethod": "model",
            "extractorAgentId": extractor_agent_id,
            "modelRef": normalized_model_ref,
            "sourceCollectionRunId": normalized_source_run,
            "workflowRunId": normalized_workflow_run,
        }
        stored = store.register(normalized_team, evidence_payload)
        # ClaimEvidenceStore intentionally owns its compact legacy record
        # shape.  Keep the explicit v2 envelope on the materialization result
        # so callers can carry the fields without teaching that core store to
        # infer or discard them; canonical v2 readback remains fail-closed if
        # the authority does not expose this envelope.
        materialized.append(
            {
                **stored,
                "challengeEvidence": challenge_evidence,
                "claimLedgerStatus": proposed["status"],
            }
        )
        # Candidate-specific relation: evidence is never copied to candidates
        # that did not cite this exact source in their formal lineage.
        for bridged_candidate_id, binding in candidate_bindings.items():
            if source_ref not in set(binding["lineageRefs"]):
                continue
            candidate_claim = _propose_ledger_claim(
                team_id=normalized_team,
                question_scope=question_scope,
                claim_text=binding["claimText"],
                candidate_id=bridged_candidate_id,
            )
            evidence_kind = (
                "counter_evidence"
                if challenge_evidence["relation"] in {"challenges", "boundary"}
                else "primary_result"
            )
            bridged = store.register(
                normalized_team,
                {
                    **evidence_payload,
                    "claimId": candidate_claim["claimId"],
                    "candidateId": bridged_candidate_id,
                    "reasoningRole": "hypothesis",
                    "evidenceKind": evidence_kind,
                },
            )
            materialized.append(
                {
                    **bridged,
                    "claimLedgerStatus": candidate_claim["status"],
                    "claimBinding": {
                        "candidateId": bridged_candidate_id,
                        "claimId": candidate_claim["claimId"],
                        "claimText": binding["claimText"],
                        "claimRole": "core",
                        "supportEvidenceIds": (
                            [bridged["claimEvidenceId"]]
                            if bridged["supportLevel"] == "supports"
                            else []
                        ),
                        "counterEvidenceIds": (
                            [bridged["claimEvidenceId"]]
                            if bridged["supportLevel"] == "contradicts"
                            else []
                        ),
                        "boundaryEvidenceIds": (
                            [bridged["claimEvidenceId"]]
                            if bridged["evidenceKind"] == "counter_evidence"
                            and bridged["supportLevel"] != "contradicts"
                            else []
                        ),
                        "beliefState": "untested",
                        "unresolvedReason": "candidate_evidence_relation_pending_review",
                    },
                }
            )
    return materialized


def materialize_candidate_claim_bindings_from_existing_evidence(
    *,
    project_root: str | Path,
    team_id: str,
    workflow_run_id: str,
    question_scope: Mapping[str, Any],
    candidates: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Bind formal candidate core claims to already-materialized lineage evidence.

    The source record remains a fact claim.  Each matching formal candidate
    gets a distinct claim row and a new pending relation that must be reviewed
    before the strict gate can count it as accepted support/boundary evidence.
    """

    from core.research.evidence import ClaimEvidenceStore
    from core.research.workflow.contracts import HypothesisClaimBinding

    normalized_team = _text(team_id)
    normalized_run = _text(workflow_run_id)
    store = ClaimEvidenceStore(project_root)
    source_records = [
        record
        for record in store.list(normalized_team)
        if _text(record.get("reasoningRole")).lower() != "hypothesis"
        and _text(record.get("reviewStatus")).lower() not in {"rejected", "stale"}
    ]
    materialized: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = _text(candidate.get("candidateId"))
        claim_text = _text(candidate.get("statement"))
        lineage_refs = {
            _text(item) for item in list(candidate.get("lineageRefs") or []) if _text(item)
        }
        if not candidate_id or not claim_text or not lineage_refs:
            continue
        matching = [
            record
            for record in source_records
            if _text(record.get("sourceId")) in lineage_refs
            or _text(record.get("claimEvidenceId")) in lineage_refs
        ]
        if not matching:
            continue
        candidate_claim = _propose_ledger_claim(
            team_id=normalized_team,
            question_scope=question_scope,
            claim_text=claim_text,
            candidate_id=candidate_id,
        )
        for source in matching:
            payload = {
                "claimId": candidate_claim["claimId"],
                "candidateId": candidate_id,
                "sourceId": source["sourceId"],
                "sourceRevision": source["sourceRevision"],
                "locator": source["locator"],
                "quote": source["quote"],
                "evidenceKind": source["evidenceKind"],
                "reasoningRole": "hypothesis",
                "supportLevel": source["supportLevel"],
                "extractionMethod": source["extractionMethod"],
                "extractorAgentId": source["extractorAgentId"],
                "modelRef": source["modelRef"],
                "sourceCollectionRunId": source["sourceCollectionRunId"],
                "workflowRunId": normalized_run or source["workflowRunId"],
            }
            bound = store.register(normalized_team, payload)
            support_refs = (
                [bound["claimEvidenceId"]]
                if bound["supportLevel"] == "supports"
                else []
            )
            counter_refs = (
                [bound["claimEvidenceId"]]
                if bound["supportLevel"] == "contradicts"
                else []
            )
            boundary_refs = (
                [bound["claimEvidenceId"]]
                if bound["evidenceKind"] == "counter_evidence"
                and bound["supportLevel"] != "contradicts"
                else []
            )
            binding = HypothesisClaimBinding.from_dict(
                {
                    "candidateId": candidate_id,
                    "claimId": candidate_claim["claimId"],
                    "claimText": claim_text,
                    "claimRole": "core",
                    "supportEvidenceIds": support_refs,
                    "counterEvidenceIds": counter_refs,
                    "boundaryEvidenceIds": boundary_refs,
                    "beliefState": "untested",
                    "unresolvedReason": "candidate_evidence_relation_pending_review",
                }
            ).to_dict()
            materialized.append(
                {
                    **bound,
                    "claimLedgerStatus": candidate_claim["status"],
                    "claimBinding": binding,
                }
            )
    return materialized


def _formal_question_scope(team_id: str, workflow_run_id: str) -> dict[str, str]:
    """Resolve the frozen formal run's question scope for ledger proposals.

    The workflow ledger owns the run→question binding, so the claim ledger
    proposal uses exactly the question the run was created for.  An
    unavailable ledger or a question-less run fails closed: materializing
    evidence that can never bridge to a claim row would only feed the belief
    gate permanent ``claim_data_missing`` verdicts.
    """
    from .formal_write_runtime import get_write_store
    from .hypothesis_first_chain import _question_scope_envelope

    try:
        run = get_write_store().get_run(_text(workflow_run_id))
    except Exception as exc:  # noqa: BLE001 - fail closed on unavailable ledger
        raise EvidenceMaterializationError(
            f"formal workflow run ledger is unavailable for claim scoping: {exc}"
        ) from exc
    question_id = _text(getattr(run, "question_id", "") if run is not None else "")
    if not question_id:
        raise EvidenceMaterializationError(
            "formal workflow run does not carry a question; claims cannot be "
            "proposed in the question-scoped claim ledger"
        )
    return _question_scope_envelope(team_id, question_id)


def _candidate_source_run_id(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    for key in ("importedFromDataRecord", "sourceCollectionTrace", "dataProcessingCollectionTrace"):
        value = metadata.get(key) if isinstance(metadata.get(key), dict) else {}
        run_id = _text(value.get("runId"))
        if run_id:
            return run_id
    return _text(metadata.get("sourceRunId"))


def build_formal_evidence_retry_contract(
    *,
    workflow_run_id: str,
    source_collection_run_id: str,
    candidates: list[dict[str, Any]] | None = None,
    evidence_records: list[dict[str, Any]] | None = None,
    team_id: str = "",
) -> dict[str, Any]:
    """Return a retry scope containing every candidate without canonical evidence."""
    normalized_workflow_run = _text(workflow_run_id)
    normalized_source_run = _text(source_collection_run_id)
    if candidates is None or evidence_records is None:
        if not _text(team_id):
            raise EvidenceMaterializationError("teamId is required to build evidence retry scope")
        from core.research.evidence import ClaimEvidenceStore
        from core.web.services import team_service
        from core.web.services.team_workflow.source_collection.candidates import (
            list_candidate_store,
        )

        if candidates is None:
            response = list_candidate_store(
                _text(team_id),
                limit=500,
                run_id=normalized_source_run,
            )
            candidates = [
                dict(item)
                for item in response.get("candidates") or []
                if isinstance(item, dict)
            ]
        if evidence_records is None:
            evidence_records = ClaimEvidenceStore(Path(team_service.PROJECT_ROOT)).list(
                _text(team_id)
            )

    scoped_candidate_ids = sorted(
        {
            _text(item.get("candidateId"))
            for item in candidates
            if isinstance(item, dict)
            and _candidate_source_run_id(item) == normalized_source_run
            and _text(item.get("candidateId"))
        }
    )
    covered_candidate_ids = {
        _text(item.get("candidateId"))
        for item in evidence_records
        if isinstance(item, dict)
        and _text(item.get("sourceCollectionRunId")) == normalized_source_run
        and _text(item.get("workflowRunId")) == normalized_workflow_run
        and _text(item.get("candidateId"))
    }
    gaps = [item for item in scoped_candidate_ids if item not in covered_candidate_ids]
    if not gaps:
        return {}
    return {
        "schemaVersion": 1,
        "parentRunId": normalized_workflow_run,
        "sourceNodeId": "source_extraction",
        "resolutionKind": "add_budget",
        "evidenceGapCandidateIds": gaps,
        "scopeCandidateIds": gaps,
        "requiredExistingLocatorFetch": True,
        "additionalBudget": {},
        "operatorReason": "canonical evidence_card_batch is incomplete",
    }


def materialize_completed_extraction_task(
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
    task_id: str,
) -> list[dict[str, Any]]:
    """Load the exact canonical stage task and cross the Evidence Store boundary."""
    from core.web.services import agent_directory_service, team_service
    from core.web.services.team_workflow.source_collection.stage_task_query import (
        get_source_collection_stage_session_task,
    )

    response = get_source_collection_stage_session_task(
        team_id,
        task_id,
    )
    task = response.get("task") if isinstance(response, dict) else None
    resolved_run_id = response.get("runId") if isinstance(response, dict) else ""
    if not isinstance(task, dict):
        raise EvidenceMaterializationError("canonical extraction stage task is missing")
    if _text(resolved_run_id) != _text(source_collection_run_id):
        raise EvidenceMaterializationError("canonical stage task resolved to a different source collection run")
    agent_id = _text(task.get("agentId"))
    agent = agent_directory_service.get_agent(agent_id) if agent_id else None
    bindings = agent.get("llmBindings") if isinstance(agent, dict) else {}
    dialogue = bindings.get("dialogue") if isinstance(bindings, dict) else {}
    model_ref = _text(dialogue.get("modelId")) if isinstance(dialogue, dict) else ""
    return materialize_claim_evidence_from_task(
        project_root=Path(team_service.PROJECT_ROOT),
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        source_collection_run_id=source_collection_run_id,
        task=task,
        model_ref=model_ref,
        question_scope=_formal_question_scope(team_id, workflow_run_id),
        hypothesis_candidate_ids=_collection_run_hypothesis_candidate_ids(
            source_collection_run_id
        ),
    )


# ---------------------------------------------------------------------------
# chain-level collection bridge (hypothesis-first chain, no formal run)
#
# Production incident (SCI-001, 2026-09-01): the chain drove five completed
# ``request_new_evidence`` collections for question SCI-001, but the team's
# claim ledger was never created, so ``evaluate_claim_belief_gate`` failed
# closed with ``claim_data_missing`` and the operator's accepted convergence
# was rejected forever.  Both stage-task entry points above require a formal
# workflow run (``_formal_question_scope``) and an extraction stage task;
# chain-level collection runs have neither.  The bridge below crosses the
# same Evidence Store boundary from the chain's own handoff authority.


def _chain_source_collection_candidates(
    team_id: str,
    collection_run_id: str,
) -> list[dict[str, Any]]:
    """Read one chain collection run's canonical source candidates."""
    from core.web.services.team_workflow.source_collection.candidates import (
        list_candidate_store,
    )

    response = list_candidate_store(_text(team_id), run_id=_text(collection_run_id), limit=500)
    return [
        dict(item)
        for item in list(response.get("candidates") or [])
        if isinstance(item, dict)
    ]


def _chain_candidate_anchor(candidate: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve the verbatim, locatable anchor of one collected source candidate.

    A candidate without a non-empty collected summary, or without any source
    locator (url, doi, or provider identity key), is not evidence: anchoring
    is what keeps the claim belief gate's inputs verifiable.
    """
    quote = _text(candidate.get("summary"))[:4000]
    if not quote:
        return None
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    record_metadata = (
        metadata.get("dataProcessingRecordMetadata")
        if isinstance(metadata.get("dataProcessingRecordMetadata"), dict)
        else {}
    )
    source_url = _text(candidate.get("sourceUrl")) or _text(metadata.get("sourceUrl"))
    doi = _text(metadata.get("doi")) or _text(record_metadata.get("doi"))
    identity_key = _text(record_metadata.get("sourceIdentityKey"))
    if source_url:
        source_ref = source_url
        locator = {"kind": "url", "url": source_url}
    elif doi:
        source_ref = f"doi:{doi}"
        locator = {"kind": "citation", "anchor": source_ref}
    elif identity_key:
        source_ref = identity_key
        locator = {"kind": "evidence_ref", "anchor": identity_key}
    else:
        return None
    title = _text(candidate.get("title")) or source_ref
    source_type = (
        _text(candidate.get("sourceKind"))
        or _text(candidate.get("candidateType"))
        or "collected_source"
    )
    return {
        "quote": quote,
        "sourceRef": source_ref,
        "locator": locator,
        "title": title[:500],
        "sourceType": source_type[:80],
        "sourceUrl": source_url,
        "retrievedAt": _text(candidate.get("createdAt")),
        "extractorAgentId": _text(candidate.get("createdByAgent")) or "source_collection",
    }


def _chain_agent_model_ref(agent_id: str) -> str:
    """Best-effort dialogue model ref for one collection agent."""
    from core.web.services import agent_directory_service

    agent = agent_directory_service.get_agent(_text(agent_id)) if _text(agent_id) else None
    bindings = agent.get("llmBindings") if isinstance(agent, dict) else {}
    dialogue = bindings.get("dialogue") if isinstance(bindings, dict) else {}
    return _text(dialogue.get("modelId")) if isinstance(dialogue, dict) else ""


def _chain_hypothesis_candidate_statements(
    team_id: str,
    question_scope: Mapping[str, Any],
    candidate_ids: list[str],
) -> dict[str, str]:
    """Resolve the formal statement of each request-bound hypothesis candidate.

    The collection request's persisted ``hypothesisCandidateIds`` (the review
    decision's ``candidateRefs``) are the binding authority here, not agent
    authored ``lineageRefs``: the review round explicitly requested evidence
    for exactly these candidates.  Candidates without a statement are skipped,
    so an empty statement can never mint a claim row.
    """
    from .hypothesis_first_chain import list_hypothesis_candidates

    listing = list_hypothesis_candidates(
        _text(team_id),
        question_id=_text(question_scope.get("question")).upper(),
    )
    statements = {
        _text(item.get("candidateId")): _text(item.get("statement"))[:4000]
        for item in list(listing.get("candidates") or [])
        if isinstance(item, Mapping) and _text(item.get("candidateId"))
    }
    return {
        candidate_id: statements[candidate_id]
        for candidate_id in candidate_ids
        if candidate_id in statements and statements[candidate_id]
    }


def materialize_chain_collection_evidence(
    *,
    project_root: str | Path,
    team_id: str,
    question_scope: Mapping[str, Any],
    collection_run_id: str,
    hypothesis_candidate_ids: object = None,
) -> dict[str, Any]:
    """Bridge one chain-level collection run into the claim ledger (idempotent).

    Chain ``request_new_evidence`` runs never own a formal workflow run or an
    extraction stage task, so neither stage-task entry point can materialize
    them.  This bridge proposes, for every collected source candidate with a
    verbatim anchored summary:

    - one question-scoped fact claim row (content-hash identity, so identical
      collected facts collapse) with a fact evidence record anchored to the
      source candidate dimension, and
    - for each hypothesis candidate the collection request explicitly served
      (its persisted ``hypothesisCandidateIds``), the candidate's core-claim
      row (candidate-dimensioned, replay-stable id) plus one evidence record
      per collected source in that candidate's dimension.

    Hypothesis-dimension evidence registers with ``reasoningRole=fact``: the
    chain's review/adjudication rounds are the acceptance authority for these
    claims, and hypothesis-role rows would wrongly pull legacy chain
    candidates onto the formal strict gate path, which demands an accepted
    evidence review the chain never runs.  ``contradicted``/``disputed``
    belief states still block; nothing about the gate changes.

    Ledger failures raise :class:`EvidenceMaterializationError`; repeated
    calls for the same run reuse every row and register no duplicates.
    """
    from core.research.evidence import ClaimEvidenceStore

    if not isinstance(question_scope, Mapping):
        raise EvidenceMaterializationError(
            "question claim scope is required to bridge chain collection "
            "evidence to the claim ledger"
        )
    normalized_team = _text(team_id)
    normalized_run = _text(collection_run_id)
    if not normalized_run:
        raise EvidenceMaterializationError(
            "chain claim materialization requires a collection run id"
        )
    bridged_candidate_ids = _normalized_hypothesis_candidate_ids(
        hypothesis_candidate_ids
    )
    statements = _chain_hypothesis_candidate_statements(
        normalized_team,
        question_scope,
        bridged_candidate_ids,
    )
    anchored: list[tuple[str, dict[str, Any]]] = []
    for candidate in _chain_source_collection_candidates(normalized_team, normalized_run):
        anchor = _chain_candidate_anchor(candidate)
        candidate_id = _text(candidate.get("candidateId"))
        if anchor is not None and candidate_id:
            anchored.append((candidate_id, anchor))
    # Without anchored collected sources there is no evidence to bridge; core
    # claim rows must never be minted empty, or the gate would read a claim
    # row that no evidence dimension can ever reach.
    if not anchored:
        return {
            "status": "skipped",
            "reason": "no_anchored_candidates",
            "collectionRunId": normalized_run,
            "sourceCandidateCount": 0,
            "factClaimCount": 0,
            "candidateClaimCount": 0,
            "evidenceCount": 0,
        }
    store = ClaimEvidenceStore(project_root)
    fact_claim_count = 0
    candidate_claim_ids: set[str] = set()
    evidence_count = 0
    for candidate_id, anchor in anchored:
        model_ref = _chain_agent_model_ref(anchor["extractorAgentId"])
        source_revision = "sha256:" + _sha256(
            {
                "sourceRef": anchor["sourceRef"],
                "locator": anchor["locator"],
                "quote": anchor["quote"],
                "title": anchor["title"],
                "source_type": anchor["sourceType"],
                "source_url": anchor["sourceUrl"],
                "retrieved_at": anchor["retrievedAt"],
                "fact": anchor["quote"],
                "relation": "supports",
                "verification_status": "collected_source_summary",
            }
        )
        fact_claim = _propose_ledger_claim(
            team_id=normalized_team,
            question_scope=question_scope,
            claim_text=anchor["quote"],
        )
        fact_claim_count += 1
        evidence_payload = {
            "claimId": fact_claim["claimId"],
            "candidateId": candidate_id,
            "sourceId": anchor["sourceRef"],
            "sourceRevision": source_revision,
            "locator": anchor["locator"],
            "quote": anchor["quote"],
            "evidenceKind": "primary_result",
            "reasoningRole": "fact",
            "supportLevel": "supports",
            "extractionMethod": "model" if model_ref else "manual",
            "extractorAgentId": anchor["extractorAgentId"],
            "modelRef": model_ref,
            "sourceCollectionRunId": normalized_run,
        }
        store.register(normalized_team, evidence_payload)
        evidence_count += 1
        for bridged_candidate_id, statement in statements.items():
            core_claim = _propose_ledger_claim(
                team_id=normalized_team,
                question_scope=question_scope,
                claim_text=statement,
                candidate_id=bridged_candidate_id,
            )
            candidate_claim_ids.add(core_claim["claimId"])
            store.register(
                normalized_team,
                {
                    **evidence_payload,
                    "claimId": core_claim["claimId"],
                    "candidateId": bridged_candidate_id,
                },
            )
            evidence_count += 1
    return {
        "status": "materialized",
        "collectionRunId": normalized_run,
        "sourceCandidateCount": len(anchored),
        "factClaimCount": fact_claim_count,
        "candidateClaimCount": len(candidate_claim_ids),
        "evidenceCount": evidence_count,
    }
