"""Canonical stage-one plan and competition-alignment projection.

Both artifacts are copied from one already-approved Challenge Cup question
artifact.  The writer never fills absent plan/alignment fields and never uses
review scores or prose summaries as substitutes for the canonical output.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .artifact_readback_registry import build_canonical_ref
from .human_gate_artifacts import canonical_sha256
from .workflow_artifact_store import put_workflow_artifact

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
    payloads = {
        STAGE_ONE_RESEARCH_PLAN_KIND: deepcopy(research_plan),
        COMPETITION_ALIGNMENT_KIND: alignment_payload,
    }
    descriptors: dict[str, Any] = {}
    for kind, payload in payloads.items():
        stored = put_workflow_artifact(
            team,
            kind=kind,
            workflow_run_id=workflow,
            source_collection_run_id=source,
            artifact_identity=f"{kind}:{node}:{question}",
            payload=payload,
        )
        descriptors[kind] = _descriptor(
            kind=kind,
            team_id=team,
            workflow_run_id=workflow,
            source_collection_run_id=source,
            payload=payload,
            record=stored,
        )
    return {
        "status": "written",
        "reason": "",
        "blockerCodes": [],
        "missingAuthorities": [],
        "artifacts": descriptors,
    }


__all__ = [
    "COMPETITION_ALIGNMENT_KIND",
    "SCHEMA_VERSION",
    "STAGE_ONE_RESEARCH_PLAN_KIND",
    "write_stage_one_plan_artifacts",
]
