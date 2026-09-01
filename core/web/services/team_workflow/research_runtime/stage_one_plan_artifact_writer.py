"""Canonical stage-one plan and competition-alignment projection.

Both artifacts are copied from one already-approved Challenge Cup question
artifact.  The writer never fills absent plan/alignment fields and never uses
review scores or prose summaries as substitutes for the canonical output.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from core.research.competition.stage_one_completion_policy import (
    load_stage_one_completion_policy,
)
from core.research.competition.stage_one_requirement_matrix import (
    G1_REQUIRED_EVIDENCE_KINDS,
    evaluate_stage_one_requirement_matrix,
    matrix_to_dict,
)

from .artifact_readback_registry import build_canonical_ref
from .human_gate_artifacts import canonical_sha256
from .workflow_artifact_store import list_workflow_artifacts, put_workflow_artifact

STAGE_ONE_RESEARCH_PLAN_KIND = "stage1_research_plan"
COMPETITION_ALIGNMENT_KIND = "competition_alignment"
SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_COMPETITION_VIEW_FIELDS = frozenset(
    {
        "problem_statement",
        "rationale",
        "technical_details",
        "datasets",
        "methods",
        "experiments",
        "results",
        "references",
        "paper_title",
        "paper_abstract",
    }
)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _blocked(*codes: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "reason": "NEEDS_CONTEXT",
        "blockerCodes": list(dict.fromkeys(codes)),
        "missingAuthorities": [
            STAGE_ONE_RESEARCH_PLAN_KIND,
            COMPETITION_ALIGNMENT_KIND,
        ],
        "artifacts": {},
    }


def _descriptor(
    *,
    kind: str,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
    payload: Mapping[str, Any],
    record: Mapping[str, Any],
) -> dict[str, Any]:
    envelope = {
        "teamId": team_id,
        "kind": kind,
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": source_collection_run_id,
        "payload": dict(payload),
    }
    canonical_hash = canonical_sha256(envelope)
    return {
        "recordId": _text(record.get("recordId")),
        "kind": kind,
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": source_collection_run_id,
        "contentHash": _text(record.get("contentHash")),
        "canonicalHash": canonical_hash,
        "canonicalRef": build_canonical_ref(
            kind=kind,
            team_id=team_id,
            authority_run_id=source_collection_run_id,
            content_hash=canonical_hash,
        ),
    }


# Evidence for the official requirement matrix is read back from the same
# immutable workflow artifact store the closure authorities were written to.
_MATRIX_STORE_EVIDENCE_KINDS = tuple(
    dict.fromkeys(
        kind
        for kinds in G1_REQUIRED_EVIDENCE_KINDS.values()
        for kind in kinds
        if kind != STAGE_ONE_RESEARCH_PLAN_KIND
    )
)


def _stored_evidence_refs(
    team: str,
    *,
    workflow_run_id: str,
    source_collection_run_id: str,
) -> dict[str, tuple[str, ...]]:
    refs: dict[str, list[str]] = {}
    for kind in _MATRIX_STORE_EVIDENCE_KINDS:
        rows = list_workflow_artifacts(team, kind=kind, workflow_run_id=workflow_run_id)
        if not rows:
            continue
        latest = rows[-1]
        content_hash = _text(latest.get("contentHash")).lower()
        if not _SHA256_RE.fullmatch(content_hash):
            continue
        refs.setdefault(kind, []).append(
            build_canonical_ref(
                kind=kind,
                team_id=team,
                authority_run_id=_text(latest.get("sourceCollectionRunId"))
                or source_collection_run_id,
                content_hash=content_hash,
            )
        )
    return {kind: tuple(items) for kind, items in refs.items()}


def _requirement_evidence(
    evidence_by_kind: Mapping[str, Sequence[str]],
    *,
    plan_ref: str,
) -> dict[str, tuple[str, ...]]:
    resolved: dict[str, tuple[str, ...]] = {}
    for requirement_id, kinds in G1_REQUIRED_EVIDENCE_KINDS.items():
        refs: list[str] = []
        for kind in kinds:
            if kind == STAGE_ONE_RESEARCH_PLAN_KIND:
                if plan_ref:
                    refs.append(plan_ref)
                continue
            refs.extend(evidence_by_kind.get(kind) or ())
        if refs:
            resolved[requirement_id] = tuple(refs)
    return resolved


def _official_requirement_matrix(plan_ref: str, team: str, workflow: str, source: str) -> dict[str, Any]:
    matrix_items = evaluate_stage_one_requirement_matrix(
        _requirement_evidence(
            _stored_evidence_refs(
                team,
                workflow_run_id=workflow,
                source_collection_run_id=source,
            ),
            plan_ref=plan_ref,
        )
    )
    return matrix_to_dict(
        matrix_items,
        scope_id=load_stage_one_completion_policy().scopeId,
    )


def write_stage_one_plan_artifacts(
    *,
    team_id: Any,
    workflow_run_id: Any,
    node_run_id: Any,
    question_id: Any,
    selected_candidate_id: Any,
    question_detail: Mapping[str, Any] | None,
    source_collection_run_id: Any = "",
) -> dict[str, Any]:
    """Project exact approved-question sections into two immutable artifacts."""

    team = _text(team_id)
    workflow = _text(workflow_run_id)
    node = _text(node_run_id)
    question = _text(question_id).upper()
    selected = _text(selected_candidate_id)
    source = _text(source_collection_run_id) or workflow
    detail = _mapping(question_detail)
    record = _mapping(detail.get("record"))
    artifact = _mapping(detail.get("artifact"))
    output = _mapping(detail.get("output"))
    identity = _mapping(output.get("identity"))
    selection = _mapping(output.get("selection"))
    research_plan = _mapping(output.get("research_plan"))
    competition_view = _mapping(output.get("competition_result_view"))
    hypotheses = [
        dict(item)
        for item in list(output.get("hypotheses") or [])
        if isinstance(item, Mapping)
    ]

    blockers: list[str] = []
    if not all((team, workflow, node, question, selected, source)):
        blockers.append("stage_one_plan_scope_incomplete")
    if (
        record.get("schemaVersion") != 2
        or _text(record.get("status")) != "approved"
        or _text(record.get("questionId")).upper() != question
        or output.get("schema_version") != 2
    ):
        blockers.append("stage_one_question_authority_not_approved")
    validation = _mapping(record.get("validation"))
    if (
        validation.get("schemaValidation") != "passed"
        or validation.get("citationValidation") != "passed"
        or validation.get("officialModelCall") is not True
        or artifact.get("immutable") is not True
        or not _SHA256_RE.fullmatch(_text(artifact.get("sha256")))
    ):
        blockers.append("stage_one_question_authority_invalid")
    if _text(identity.get("question_id")).upper() != question or not _text(
        identity.get("catalog_id")
    ):
        blockers.append("competition_alignment_identity_missing")
    if _text(selection.get("selected_hypothesis_id")) != selected:
        blockers.append("stage_one_selected_hypothesis_mismatch")
    if _mapping(selection.get("human_gate")).get("decision") != "approved":
        blockers.append("stage_one_selection_not_approved")
    selected_row = next(
        (
            item
            for item in hypotheses
            if _text(item.get("hypothesis_id")) == selected
            and _text(item.get("statement"))
        ),
        None,
    )
    if selected_row is None:
        blockers.append("stage_one_selected_hypothesis_missing")
    if not research_plan:
        blockers.append("stage_one_research_plan_source_missing")
    if _mapping(research_plan.get("human_gate")).get("decision") != "approved":
        blockers.append("stage_one_research_plan_not_approved")
    if not competition_view or not _COMPETITION_VIEW_FIELDS.issubset(competition_view):
        blockers.append("competition_alignment_source_missing")
    if blockers:
        return _blocked(*blockers)

    alignment_payload = {
        "schemaVersion": SCHEMA_VERSION,
        "artifactKind": COMPETITION_ALIGNMENT_KIND,
        "questionIdentity": deepcopy(identity),
        "selectedHypothesis": {
            "hypothesisId": selected,
            "statement": _text(selected_row.get("statement")),
        },
        "competitionResultView": deepcopy(competition_view),
        "sourceQuestionRunId": _text(record.get("runId")),
        "sourceArtifactSha256": _text(artifact.get("sha256")).lower(),
    }
    plan_payload = deepcopy(research_plan)
    plan_stored = put_workflow_artifact(
        team,
        kind=STAGE_ONE_RESEARCH_PLAN_KIND,
        workflow_run_id=workflow,
        source_collection_run_id=source,
        artifact_identity=f"{STAGE_ONE_RESEARCH_PLAN_KIND}:{node}:{question}",
        payload=plan_payload,
    )
    plan_descriptor = _descriptor(
        kind=STAGE_ONE_RESEARCH_PLAN_KIND,
        team_id=team,
        workflow_run_id=workflow,
        source_collection_run_id=source,
        payload=plan_payload,
        record=plan_stored,
    )
    # The §2.5 matrix is materialized from real artifact refs only: the plan
    # descriptor above plus the closure authorities already in the store.
    alignment_payload["officialRequirementMatrix"] = _official_requirement_matrix(
        str(plan_descriptor.get("canonicalRef") or ""),
        team,
        workflow,
        source,
    )
    alignment_stored = put_workflow_artifact(
        team,
        kind=COMPETITION_ALIGNMENT_KIND,
        workflow_run_id=workflow,
        source_collection_run_id=source,
        artifact_identity=f"{COMPETITION_ALIGNMENT_KIND}:{node}:{question}",
        payload=alignment_payload,
    )
    alignment_descriptor = _descriptor(
        kind=COMPETITION_ALIGNMENT_KIND,
        team_id=team,
        workflow_run_id=workflow,
        source_collection_run_id=source,
        payload=alignment_payload,
        record=alignment_stored,
    )
    return {
        "status": "written",
        "reason": "",
        "blockerCodes": [],
        "missingAuthorities": [],
        "artifacts": {
            STAGE_ONE_RESEARCH_PLAN_KIND: plan_descriptor,
            COMPETITION_ALIGNMENT_KIND: alignment_descriptor,
        },
    }


__all__ = [
    "COMPETITION_ALIGNMENT_KIND",
    "SCHEMA_VERSION",
    "STAGE_ONE_RESEARCH_PLAN_KIND",
    "write_stage_one_plan_artifacts",
]
