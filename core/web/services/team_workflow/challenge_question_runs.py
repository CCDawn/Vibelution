"""Validated storage for Challenge Cup single-question research outputs."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from core.infrastructure import developer_sandbox
from core.web.services import team_service
from core.web.services.runtime_scene_service import record_runtime_scene_event


STORE_SCHEMA_VERSION = 1
STORE_KIND = "challenge_question_run_store"
CATALOG_ID = "science-125-questions-2021"
OFFICIAL_PROVIDERS = {"dashscope", "bailian", "aliyun"}
APPROVED_GATE_DECISION = "approved"
REQUIRED_DIMENSIONS = {
    "evidence_support",
    "factual_accuracy",
    "novelty",
    "falsifiability",
    "plan_feasibility",
    "risk_and_ethics",
    "counterexample_coverage",
}
_STORE_LOCK = RLock()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _workflow_root(team_id: str) -> Path:
    return developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "teams",
        "".join(character if character.isalnum() or character in "._-" else "_" for character in team_id)[:96]
        or "team",
    )


def _store_path(team_id: str) -> Path:
    return _workflow_root(team_id) / "challenge_program" / "question_runs" / "index.json"


def _artifact_path(team_id: str, question_id: str, run_id: str) -> Path:
    return _workflow_root(team_id) / "challenge_program" / "question_runs" / question_id / f"{run_id}.json"


def _schema_path() -> Path:
    return _project_root() / "挑战杯" / "schemas" / "challenge_question_output.schema.json"


def _catalog_path() -> Path:
    return _project_root() / "挑战杯" / "data" / "science_125_questions.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _catalog_sha256() -> str:
    return _sha256_bytes(_catalog_path().read_bytes())


def _catalog_question(question_id: str) -> dict[str, Any] | None:
    catalog = _read_json(_catalog_path())
    for item in catalog.get("questions") if isinstance(catalog.get("questions"), list) else []:
        if isinstance(item, dict) and str(item.get("id") or "") == question_id:
            return item
    return None


def _output_sha256(output: dict[str, Any]) -> str:
    hashable = deepcopy(output)
    audit = hashable.setdefault("audit", {})
    audit["output_sha256"] = "0" * 64
    encoded = json.dumps(hashable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


def _schema_issues(output: dict[str, Any]) -> list[dict[str, str]]:
    schema = _read_json(_schema_path())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    issues: list[dict[str, str]] = []
    for error in sorted(
        validator.iter_errors(output),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    ):
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        issues.append({"path": path, "message": error.message})
    return issues


def _citation_validation(output: dict[str, Any], checks: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = output.get("evidence") if isinstance(output.get("evidence"), list) else []
    expected_urls = {str(item.get("source_url") or "").strip() for item in evidence if isinstance(item, dict)}
    passed_urls = {
        str(item.get("sourceUrl") or "").strip()
        for item in checks
        if isinstance(item, dict) and str(item.get("status") or "").lower() == "passed"
    }
    authoritative_count = sum(
        1
        for item in evidence
        if isinstance(item, dict)
        and str(item.get("source_type") or "")
        in {"peer_reviewed_paper", "dataset", "standard", "official_document"}
    )
    challenge_count = sum(
        1
        for item in evidence
        if isinstance(item, dict) and str(item.get("relation") or "") in {"challenges", "boundary"}
    )
    missing_urls = sorted(url for url in expected_urls if url not in passed_urls)
    passed = (
        len(evidence) >= 4
        and authoritative_count >= 2
        and challenge_count >= 1
        and bool(expected_urls)
        and not missing_urls
    )
    return {
        "status": "passed" if passed else "failed",
        "evidenceCount": len(evidence),
        "authoritativeCount": authoritative_count,
        "challengeOrBoundaryCount": challenge_count,
        "checkedUrlCount": len(expected_urls & passed_urls),
        "missingUrls": missing_urls,
    }


def _semantic_validation(output: dict[str, Any]) -> dict[str, Any]:
    hypotheses = output.get("hypotheses") if isinstance(output.get("hypotheses"), list) else []
    reviews = output.get("dimension_reviews") if isinstance(output.get("dimension_reviews"), list) else []
    hypothesis_ids = {
        str(item.get("hypothesis_id") or "")
        for item in hypotheses
        if isinstance(item, dict) and item.get("hypothesis_id")
    }
    coverage = {
        hypothesis_id: {
            str(item.get("dimension") or "")
            for item in reviews
            if isinstance(item, dict) and str(item.get("hypothesis_id") or "") == hypothesis_id
        }
        for hypothesis_id in hypothesis_ids
    }
    missing_dimensions = {
        hypothesis_id: sorted(REQUIRED_DIMENSIONS - dimensions)
        for hypothesis_id, dimensions in coverage.items()
        if dimensions != REQUIRED_DIMENSIONS
    }
    selection = output.get("selection") if isinstance(output.get("selection"), dict) else {}
    selected_id = str(selection.get("selected_hypothesis_id") or "")
    feedback = output.get("feedback_iterations") if isinstance(output.get("feedback_iterations"), list) else []
    research_plan_present = isinstance(output.get("research_plan"), dict) and bool(output.get("research_plan"))
    issues: list[dict[str, str]] = []
    if len(hypothesis_ids) < 2:
        issues.append({"path": "hypotheses", "message": "At least two distinct hypotheses are required."})
    if missing_dimensions:
        issues.append(
            {
                "path": "dimension_reviews",
                "message": "Every hypothesis must be reviewed on all seven independent dimensions.",
            }
        )
    if selected_id not in hypothesis_ids:
        issues.append({"path": "selection.selected_hypothesis_id", "message": "Selected hypothesis must exist."})
    if not feedback:
        issues.append({"path": "feedback_iterations", "message": "At least one feedback revision is required."})
    if not research_plan_present:
        issues.append({"path": "research_plan", "message": "A research plan is required."})
    return {
        "status": "passed" if not issues else "failed",
        "issues": issues,
        "hypothesisCount": len(hypothesis_ids),
        "allSevenDimensionsReviewed": not missing_dimensions and bool(hypothesis_ids),
        "researchPlanPresent": research_plan_present,
        "feedbackRevisionCount": len(feedback),
    }


def _human_gate_summary(output: dict[str, Any]) -> dict[str, Any]:
    problem = output.get("problem_understanding") if isinstance(output.get("problem_understanding"), dict) else {}
    selection = output.get("selection") if isinstance(output.get("selection"), dict) else {}
    plan = output.get("research_plan") if isinstance(output.get("research_plan"), dict) else {}
    audit = output.get("audit") if isinstance(output.get("audit"), dict) else {}
    h4_decision = {
        "passed": "approved",
        "revision_requested": "revision_requested",
        "rejected": "rejected",
    }.get(str(audit.get("human_review_status") or ""), "pending")
    decisions = {
        "H1_problem_understanding": str((problem.get("human_gate") or {}).get("decision") or "pending"),
        "H2_hypothesis_selection": str((selection.get("human_gate") or {}).get("decision") or "pending"),
        "H3_research_plan": str((plan.get("human_gate") or {}).get("decision") or "pending"),
        "H4_external_output": h4_decision,
    }
    return {
        "decisions": decisions,
        "approvedCount": sum(decision == APPROVED_GATE_DECISION for decision in decisions.values()),
        "allApproved": all(decision == APPROVED_GATE_DECISION for decision in decisions.values()),
    }


def _set_pending_human_gates(output: dict[str, Any]) -> None:
    for field in ("problem_understanding", "selection", "research_plan"):
        section = output.get(field) if isinstance(output.get(field), dict) else {}
        gate = section.get("human_gate") if isinstance(section.get("human_gate"), dict) else {}
        gate.update(
            {
                "required": True,
                "decision": "pending",
                "rationale": "Awaiting explicit human review.",
            }
        )
        gate.pop("reviewer", None)
        gate.pop("decided_at", None)
        section["human_gate"] = gate
        output[field] = section
    output.setdefault("audit", {})["human_review_status"] = "pending"
    if str(output.get("status") or "") not in {"blocked", "failed"}:
        output["status"] = "review_required"


def _official_model_evidence_ids(team_id: str) -> set[str]:
    store = _read_json(_workflow_root(team_id) / "official_model_evidence" / "index.json")
    evidence = store.get("evidence") if isinstance(store.get("evidence"), list) else []
    return {
        str(item.get("evidenceId") or "")
        for item in evidence
        if isinstance(item, dict)
        and str(item.get("modelProvider") or "").lower() in OFFICIAL_PROVIDERS
        and str(item.get("status") or "").lower() != "derived_from_candidate_store"
    }


def _load_store(team_id: str) -> dict[str, Any]:
    store = _read_json(_store_path(team_id))
    if store.get("schemaVersion") == STORE_SCHEMA_VERSION and store.get("storeKind") == STORE_KIND:
        return store
    return {
        "schemaVersion": STORE_SCHEMA_VERSION,
        "storeKind": STORE_KIND,
        "teamId": team_id,
        "records": [],
        "updatedAt": "",
    }


def challenge_question_run_summary(team_id: str) -> dict[str, Any]:
    records = _load_store(team_id).get("records")
    records = records if isinstance(records, list) else []
    valid_candidates = [
        record
        for record in records
        if isinstance(record, dict)
        and (record.get("validation") or {}).get("schemaValidation") == "passed"
        and (record.get("validation") or {}).get("citationValidation") == "passed"
        and (record.get("validation") or {}).get("officialModelCall") is True
    ]
    completed = [
        record
        for record in valid_candidates
        if (record.get("humanGates") or {}).get("allApproved") is True
        and str(record.get("status") or "") == "approved"
    ]
    completed_question_ids = sorted({str(record.get("questionId") or "") for record in completed})
    return {
        "recordCount": len(records),
        "validCandidateCount": len(valid_candidates),
        "completedCount": len(completed_question_ids),
        "completedQuestionIds": completed_question_ids,
        "latestCandidate": deepcopy(valid_candidates[-1]) if valid_candidates else None,
    }


def get_challenge_question_run_status(team_id: str) -> dict[str, Any]:
    team_service.get_team(team_id)
    return {
        "teamId": team_id,
        "summary": challenge_question_run_summary(team_id),
        "storePath": str(_store_path(team_id)),
    }


def register_challenge_question_output(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    team_service.get_team(team_id)
    raw_output = payload.get("output")
    if not isinstance(raw_output, dict):
        raise ValueError("output must be an object.")
    output = deepcopy(raw_output)
    _set_pending_human_gates(output)
    audit = output.setdefault("audit", {})
    audit["source_catalog_sha256"] = _catalog_sha256()
    audit["output_sha256"] = "0" * 64
    checks = payload.get("citationChecks") if isinstance(payload.get("citationChecks"), list) else []
    citation = _citation_validation(output, checks)
    semantic = _semantic_validation(output)
    audit["citation_validation"] = citation["status"]
    output_hash = _output_sha256(output)
    audit["output_sha256"] = output_hash
    issues = _schema_issues(output)
    audit["schema_validation"] = "passed" if not issues else "failed"

    run = output.get("run") if isinstance(output.get("run"), dict) else {}
    model_provider = str(run.get("model_provider") or "").strip().lower()
    evidence_refs = run.get("invocation_evidence_refs") if isinstance(run.get("invocation_evidence_refs"), list) else []
    registered_official_evidence = _official_model_evidence_ids(team_id)
    matched_evidence_refs = sorted({str(item) for item in evidence_refs} & registered_official_evidence)
    official_call = model_provider in OFFICIAL_PROVIDERS and bool(matched_evidence_refs)
    gates = _human_gate_summary(output)
    question_id = str(output.get("question_id") or "").strip()
    run_id = str(run.get("run_id") or "").strip()
    if not question_id or not run_id:
        raise ValueError("output.question_id and output.run.run_id are required.")
    parent_run_id = str(payload.get("parentRunId") or "").strip()
    if parent_run_id == run_id:
        raise ValueError("parentRunId must reference an earlier run.")
    raw_lineage_refs = payload.get("lineageRefs")
    lineage_refs = list(
        dict.fromkeys(
            str(item).strip()
            for item in (raw_lineage_refs if isinstance(raw_lineage_refs, list) else [])
            if str(item).strip()
        )
    )
    catalog_question = _catalog_question(question_id)
    if catalog_question is None:
        issues.append({"path": "question_id", "message": "Question id is not present in the official catalog."})
    elif str(catalog_question.get("question_en") or "") != str(output.get("question_en") or ""):
        issues.append({"path": "question_en", "message": "Question text does not match the official catalog."})
    issues.extend(semantic["issues"])
    audit["schema_validation"] = "passed" if not issues else "failed"
    output_hash = _output_sha256(output)
    audit["output_sha256"] = output_hash

    record = {
        "recordId": f"{question_id}:{run_id}",
        "questionId": question_id,
        "runId": run_id,
        "status": str(output.get("status") or ""),
        "modelProvider": model_provider,
        "modelId": str(run.get("model_id") or ""),
        "invocationEvidenceRefs": [str(item) for item in evidence_refs],
        "matchedOfficialEvidenceRefs": matched_evidence_refs,
        "validation": {
            "schemaValidation": audit["schema_validation"],
            "schemaIssues": issues,
            "citationValidation": citation["status"],
            "citation": citation,
            "semanticValidation": semantic["status"],
            "semantic": semantic,
            "officialModelCall": official_call,
        },
        "humanGates": gates,
        "outputSha256": output_hash,
        "artifactPath": str(_artifact_path(team_id, question_id, run_id)),
        "registeredAt": _utc_now(),
        "registeredBy": str(payload.get("registeredBy") or ""),
    }
    if parent_run_id or lineage_refs:
        record["lineage"] = {
            "relation": "revises" if parent_run_id else "derived_from_evidence",
            "parentRunId": parent_run_id,
            "refs": lineage_refs,
        }
    with _STORE_LOCK:
        store = _load_store(team_id)
        records = [item for item in store.get("records", []) if isinstance(item, dict)]
        existing_record = next(
            (item for item in records if item.get("recordId") == record["recordId"]),
            None,
        )
        if existing_record is not None:
            existing_output = _read_json(_artifact_path(team_id, question_id, run_id))
            if (
                not existing_output
                or _output_sha256(existing_output) != existing_record.get("outputSha256")
            ):
                raise ValueError(
                    "Existing challenge question run artifact does not match its immutable index record."
                )
            if (
                existing_record.get("outputSha256") == output_hash
                and existing_record.get("lineage") == record.get("lineage")
            ):
                return {
                    "record": deepcopy(existing_record),
                    "output": existing_output,
                    "summary": challenge_question_run_summary(team_id),
                    "idempotent": True,
                }
            raise ValueError(
                "Challenge question runs are immutable; use a new run_id for revised output."
            )
        if parent_run_id and not any(
            item.get("questionId") == question_id and item.get("runId") == parent_run_id
            for item in records
        ):
            raise ValueError("parentRunId was not found for this challenge question.")
        _write_json(_artifact_path(team_id, question_id, run_id), output)
        records.append(record)
        store["records"] = records
        store["updatedAt"] = _utc_now()
        _write_json(_store_path(team_id), store)
        summary = challenge_question_run_summary(team_id)
    record_runtime_scene_event(
        "team_workflow_orchestration",
        "challenge_question_run",
        "challenge_question_run.registered",
        message="Challenge Cup question output was validated and registered.",
        outcome="passed" if record["validation"]["schemaValidation"] == "passed" else "blocked",
        fields={
            "teamId": team_id,
            "questionId": question_id,
            "runId": run_id,
            "parentRunId": parent_run_id,
            "schemaValidation": record["validation"]["schemaValidation"],
            "citationValidation": record["validation"]["citationValidation"],
            "officialModelCall": official_call,
            "humanGateApprovedCount": gates["approvedCount"],
        },
        lifecycle=True,
    )
    return {
        "record": record,
        "output": output,
        "summary": summary,
    }


def review_challenge_question_output(
    team_id: str,
    question_id: str,
    run_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    team_service.get_team(team_id)
    reviewer = str(payload.get("reviewer") or "").strip()
    rationale = str(payload.get("rationale") or "").strip()
    decisions = payload.get("decisions") if isinstance(payload.get("decisions"), dict) else {}
    required_gates = {
        "H1_problem_understanding",
        "H2_hypothesis_selection",
        "H3_research_plan",
        "H4_external_output",
    }
    if not reviewer or not rationale:
        raise ValueError("reviewer and rationale are required.")
    if set(decisions) != required_gates:
        raise ValueError("decisions must explicitly include H1, H2, H3 and H4.")
    allowed_decisions = {"approved", "revision_requested", "rejected"}
    if any(str(value) not in allowed_decisions for value in decisions.values()):
        raise ValueError("Each human gate decision must be approved, revision_requested or rejected.")

    artifact_path = _artifact_path(team_id, question_id, run_id)
    output = _read_json(artifact_path)
    if not output:
        raise ValueError("Challenge question output artifact was not found.")
    decided_at = _utc_now()
    field_by_gate = {
        "H1_problem_understanding": "problem_understanding",
        "H2_hypothesis_selection": "selection",
        "H3_research_plan": "research_plan",
    }
    for gate_name, field in field_by_gate.items():
        gate = output[field]["human_gate"]
        gate.update(
            {
                "decision": str(decisions[gate_name]),
                "reviewer": reviewer,
                "decided_at": decided_at,
                "rationale": rationale,
            }
        )
    h4_decision = str(decisions["H4_external_output"])
    all_approved = all(str(value) == "approved" for value in decisions.values())
    output["audit"]["human_review_status"] = (
        "passed"
        if h4_decision == "approved"
        else "revision_requested"
        if h4_decision == "revision_requested"
        else "rejected"
    )
    output["status"] = "approved" if all_approved else "needs_revision"
    output["audit"]["output_sha256"] = _output_sha256(output)
    gates = _human_gate_summary(output)

    with _STORE_LOCK:
        store = _load_store(team_id)
        record = next(
            (
                item
                for item in store.get("records", [])
                if isinstance(item, dict)
                and item.get("questionId") == question_id
                and item.get("runId") == run_id
            ),
            None,
        )
        if record is None:
            raise ValueError("Challenge question run record was not found.")
        validation = record.get("validation") if isinstance(record.get("validation"), dict) else {}
        if (
            validation.get("schemaValidation") != "passed"
            or validation.get("citationValidation") != "passed"
            or validation.get("semanticValidation") != "passed"
            or validation.get("officialModelCall") is not True
        ):
            raise ValueError("Only fully validated official-model candidates can enter human review.")
        record["status"] = output["status"]
        record["humanGates"] = gates
        record["outputSha256"] = output["audit"]["output_sha256"]
        record["review"] = {
            "reviewer": reviewer,
            "rationale": rationale,
            "decisions": {key: str(value) for key, value in decisions.items()},
            "decidedAt": decided_at,
        }
        store["updatedAt"] = decided_at
        _write_json(artifact_path, output)
        _write_json(_store_path(team_id), store)
        summary = challenge_question_run_summary(team_id)
    record_runtime_scene_event(
        "team_workflow_orchestration",
        "challenge_question_run",
        "challenge_question_run.reviewed",
        message="Challenge Cup question output human gates were recorded.",
        outcome="passed" if all_approved else "blocked",
        fields={
            "teamId": team_id,
            "questionId": question_id,
            "runId": run_id,
            "reviewer": reviewer,
            "approvedGateCount": gates["approvedCount"],
            "status": output["status"],
        },
        lifecycle=True,
    )
    return {"record": deepcopy(record), "output": output, "summary": summary}
