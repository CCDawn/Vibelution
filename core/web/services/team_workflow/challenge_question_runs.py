"""Validated storage for Challenge Cup single-question research outputs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import quote, unquote, urlparse
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

from core.research.competition.question_result_package import (
    QuestionResultPackageError,
    canonical_model_policy,
)
from core.research.competition.resources import (
    CATALOG_SHA256,
    QUESTION_CATALOG_PATH,
    CompetitionResourceError,
    load_competition_program_core,
    load_science_question_catalog,
)
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
)
from core.web.services import team_service
from core.web.services.runtime_scene_service import record_runtime_scene_event
from core.web.services.team_workflow.research_projects import (
    resolve_research_project_workspace_root,
    resolve_team_program_root,
)

STORE_SCHEMA_VERSION = 1
STORE_KIND = "challenge_question_run_store"
OFFICIAL_EVIDENCE_SCHEMA_VERSION = 2
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
REQUIRED_HUMAN_GATE_KEYS = {
    "H1_problem_understanding",
    "H2_hypothesis_selection",
    "H3_research_plan",
    "H4_external_output",
}
MODEL_INVOCATION_RECEIPT_STAGES = ("generation", "review", "revision")
_STORE_LOCK = RLock()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _workflow_root(team_id: str) -> Path:
    return resolve_team_program_root(team_id)


def _store_path(team_id: str) -> Path:
    return _workflow_root(team_id) / "challenge_program" / "question_runs" / "index.json"


def _artifact_path(team_id: str, question_id: str, run_id: str) -> Path:
    return _workflow_root(team_id) / "challenge_program" / "question_runs" / question_id / f"{run_id}.json"


def _result_package_artifact_path(team_id: str, question_id: str, run_id: str) -> Path:
    return (
        _workflow_root(team_id)
        / "challenge_program"
        / "question_runs"
        / question_id
        / f"{run_id}.result-package.v2.json"
    )


def _schema_path(version: int = 2) -> Path:
    return _project_root() / "schemas" / f"challenge_question_output.v{version}.schema.json"


def _catalog_path() -> Path:
    return QUESTION_CATALOG_PATH


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


def _replace_staged_json(source: Path, target: Path) -> None:
    source.replace(target)


def _write_json_bundle(entries: list[tuple[Path, dict[str, Any]]]) -> None:
    """Stage and promote related JSON files with best-effort rollback."""

    token = uuid4().hex
    operations = [
        {
            "target": target,
            "stage": target.with_name(f".{target.name}.{token}.stage"),
            "backup": target.with_name(f".{target.name}.{token}.backup"),
            "backedUp": False,
            "promoted": False,
            "value": value,
        }
        for target, value in entries
    ]
    failure: BaseException | None = None
    completed = False
    try:
        for operation in operations:
            _write_json(operation["stage"], operation["value"])
        for operation in operations:
            target = operation["target"]
            backup = operation["backup"]
            if target.exists():
                _replace_staged_json(target, backup)
                operation["backedUp"] = True
            _replace_staged_json(operation["stage"], target)
            operation["promoted"] = True
        completed = True
    except Exception as exc:
        failure = exc
        for operation in reversed(operations):
            target = operation["target"]
            backup = operation["backup"]
            try:
                if operation["promoted"] and target.exists():
                    target.unlink()
                if operation["backedUp"] and backup.exists():
                    _replace_staged_json(backup, target)
            except Exception as rollback_error:
                exc.add_note(
                    f"bundle rollback failed for {target}: {rollback_error}"
                )
        raise
    finally:
        for operation in operations:
            stage = operation["stage"]
            stage_temporary = stage.with_suffix(f"{stage.suffix}.tmp")
            backup = operation["backup"]
            for disposable in (stage, stage_temporary):
                try:
                    if disposable.exists():
                        disposable.unlink()
                except OSError as cleanup_error:
                    if failure is None:
                        raise
                    failure.add_note(
                        f"bundle cleanup failed for {disposable}: {cleanup_error}"
                    )
            if completed and backup.exists() and operation["target"].exists():
                backup.unlink()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _catalog_sha256() -> str:
    load_science_question_catalog()
    return CATALOG_SHA256.lower()


def _required_deep_experiment_question_ids() -> set[str]:
    """Deep-experiment question ids from the frozen competition program.

    Fails closed to an empty set: an unreadable resource keeps deep-experiment
    readiness blocked instead of failing the whole run summary.
    """
    try:
        program = load_competition_program_core()
    except CompetitionResourceError:
        return set()
    return {
        str(item.get("questionId") or "")
        for item in program.get("requiredDeepExperiments") or []
        if isinstance(item, dict) and str(item.get("questionId") or "")
    }


def _catalog_question(question_id: str) -> dict[str, Any] | None:
    catalog = load_science_question_catalog()
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


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_CANONICAL_OUTPUT_REF_SCHEME = "turn-journal"


def _source_result_package_hash(payload: dict[str, Any]) -> str:
    """Return the optional immutable result-package binding for a registration.

    The bridge that moves a canonical workflow result into the Challenge
    Program store supplies this value.  It is deliberately kept outside the
    v2 output hash: the output remains the producer's immutable artifact while
    the index records which workflow package authorized its registration.
    """

    value = str(
        payload.get("sourceResultPackageHash")
        or payload.get("source_result_package_hash")
        or ""
    ).strip().lower()
    if value and not _SHA256_RE.fullmatch(value):
        raise ValueError(
            "sourceResultPackageHash must be a 64-character SHA-256 value."
        )
    return value


def _canonical_output_ref(
    session_id: str,
    source_run_id: str,
    task_id: str,
    turn_id: str,
) -> str:
    """Build a server-owned reference to one canonical final turn artifact."""
    return (
        f"{_CANONICAL_OUTPUT_REF_SCHEME}://{quote(session_id, safe='')}"
        f"/{quote(source_run_id, safe='')}/{quote(task_id, safe='')}/{quote(turn_id, safe='')}"
    )


def _parse_canonical_output_ref(output_ref: str) -> dict[str, str] | None:
    parsed = urlparse(str(output_ref or "").strip())
    if parsed.scheme != _CANONICAL_OUTPUT_REF_SCHEME or not parsed.netloc:
        return None
    parts = [unquote(item) for item in parsed.path.split("/") if item]
    if len(parts) != 3 or parsed.query or parsed.fragment:
        return None
    session_id = unquote(parsed.netloc)
    source_run_id, task_id, turn_id = parts
    if not all((session_id, source_run_id, task_id, turn_id)):
        return None
    return {
        "sessionId": session_id,
        "sourceRunId": source_run_id,
        "taskId": task_id,
        "turnId": turn_id,
    }


def _json_object_from_turn_text(value: Any) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
        if text.lower().startswith("json\n"):
            text = text[5:].lstrip()
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_canonical_turn_output(
    *,
    session_id: str,
    source_run_id: str,
    task_id: str,
    turn_id: str,
    output_ref: str = "",
) -> dict[str, Any] | None:
    """Read and hash the actual server-committed final assistant artifact.

    Task/result dictionaries and request payloads are not output authorities.
    Only an assistant item committed by ``canonical_turn_outcome`` can bind a
    Challenge output.  The reference is checked against all four immutable
    identities before the journal is read.
    """
    normalized = {
        "sessionId": str(session_id or "").strip(),
        "sourceRunId": str(source_run_id or "").strip(),
        "taskId": str(task_id or "").strip(),
        "turnId": str(turn_id or "").strip(),
    }
    if not all(normalized.values()):
        return None
    expected_ref = _canonical_output_ref(
        normalized["sessionId"],
        normalized["sourceRunId"],
        normalized["taskId"],
        normalized["turnId"],
    )
    if output_ref and str(output_ref).strip() != expected_ref:
        return None
    try:
        from core.chat.turn_journal import (
            EVENT_ASSISTANT_ITEM_COMMITTED,
            load_turn_events,
        )

        events = load_turn_events(_project_root(), normalized["sessionId"])
    except (OSError, ValueError):
        return None
    for event in reversed(events):
        if str(getattr(event, "turn_id", "") or "").strip() != normalized["turnId"]:
            continue
        if str(getattr(event, "event_type", "") or "").strip() != EVENT_ASSISTANT_ITEM_COMMITTED:
            continue
        if str(getattr(event, "source", "") or "").strip() != "canonical_turn_outcome":
            continue
        payload = getattr(event, "payload", {})
        if not isinstance(payload, dict):
            continue
        if (
            str(payload.get("kind") or "").strip() != "assistant_message"
            or str(payload.get("channel") or "").strip().lower() != "answer"
            or str(payload.get("phase") or "").strip().lower() != "final_answer"
            or not bool(payload.get("terminal"))
        ):
            continue
        output = _json_object_from_turn_text(payload.get("text"))
        if output is None:
            continue
        output_run = output.get("run") if isinstance(output.get("run"), dict) else {}
        if str(output_run.get("run_id") or "").strip() != normalized["sourceRunId"]:
            continue
        return {
            **normalized,
            "output": output,
            "outputSha256": _output_sha256(output),
            "outputRef": expected_ref,
        }
    return None


def _canonical_turn_binding_for_evidence(
    evidence: dict[str, Any],
) -> dict[str, Any] | None:
    source_session_id = str(evidence.get("sourceSessionId") or "").strip()
    source_run_id = str(evidence.get("sourceRunId") or "").strip()
    task_id = str(evidence.get("taskId") or "").strip()
    turn_id = str(evidence.get("turnId") or "").strip()
    output_ref = str(evidence.get("outputRef") or "").strip()
    binding = _read_canonical_turn_output(
        session_id=source_session_id,
        source_run_id=source_run_id,
        task_id=task_id,
        turn_id=turn_id,
        output_ref=output_ref,
    )
    if binding is None:
        return None
    output = binding.get("output") if isinstance(binding.get("output"), dict) else {}
    return {
        **binding,
        "questionId": _output_question_id(output),
        "runId": str((output.get("run") or {}).get("run_id") or "").strip(),
    }


def _canonical_evidence_output_binding(evidence: dict[str, Any]) -> dict[str, str]:
    """Read the immutable output binding carried by a project evidence row.

    Evidence written before the canonical output binding existed is deliberately
    not upgraded in place.  Such rows remain readable, but publishing through
    them fails closed and asks the producer to record a fresh evidence row.
    """
    source_run_id = str(evidence.get("sourceRunId") or "").strip()
    task_id = str(evidence.get("taskId") or "").strip()
    turn_id = str(evidence.get("turnId") or "").strip()
    if not all((source_run_id, task_id, turn_id)):
        raise ValueError(
            "challenge_question_publish_legacy_evidence_unusable: project evidence "
            "must carry canonical sourceRunId, taskId and turnId; re-record canonical evidence."
        )
    metadata = evidence.get("metadata") if isinstance(evidence.get("metadata"), dict) else {}
    hash_value = ""
    ref_value = ""
    for container in (evidence, metadata):
        if not hash_value:
            for key in ("outputSha256", "outputHash", "output_sha256"):
                value = str(container.get(key) or "").strip()
                if value:
                    hash_value = value.removeprefix("sha256:").strip()
                    break
        if not ref_value:
            for key in ("outputRef", "outputReference", "output_ref"):
                value = str(container.get(key) or "").strip()
                if value:
                    ref_value = value
                    break
    if hash_value and not _SHA256_RE.fullmatch(hash_value):
        raise ValueError(
            "challenge_question_publish_evidence_output_binding_invalid: canonical output hash "
            "must be a 64-character SHA-256 value; re-record canonical evidence."
        )
    if not hash_value and not ref_value:
        raise ValueError(
            "challenge_question_publish_legacy_evidence_unusable: project evidence lacks a "
            "canonical output hash/ref; re-record canonical evidence before publishing."
        )
    return {
        "sourceRunId": source_run_id,
        "taskId": task_id,
        "turnId": turn_id,
        "outputSha256": hash_value.lower(),
        "outputRef": ref_value,
    }


def _output_schema_version(output: dict[str, Any]) -> int:
    value = output.get("schema_version")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _output_identity(output: dict[str, Any]) -> dict[str, Any]:
    if _output_schema_version(output) == 2:
        identity = output.get("identity")
        return identity if isinstance(identity, dict) else {}
    return output


def _output_question_id(output: dict[str, Any]) -> str:
    return str(_output_identity(output).get("question_id") or "").strip()


def _output_catalog_id(output: dict[str, Any]) -> str:
    return str(_output_identity(output).get("catalog_id") or "").strip()


def _output_question_en(output: dict[str, Any]) -> str:
    return str(_output_identity(output).get("question_en") or "").strip()


def _output_result_classification(output: dict[str, Any]) -> dict[str, Any]:
    if _output_schema_version(output) == 2:
        result = output.get("result_classification")
        return result if isinstance(result, dict) else {}
    return output


def _output_status(output: dict[str, Any]) -> str:
    return str(_output_result_classification(output).get("status") or "").strip()


def _set_output_status(output: dict[str, Any], status: str) -> None:
    _output_result_classification(output)["status"] = status


def _output_final_summary(output: dict[str, Any]) -> dict[str, Any]:
    summary = _output_result_classification(output).get("final_summary")
    return summary if isinstance(summary, dict) else {}


def _require_writable_schema(output: dict[str, Any]) -> None:
    version = _output_schema_version(output)
    if version == 1:
        raise ValueError("Challenge question output schema v1 is read-only; new writes require v2.")
    if version != 2:
        raise ValueError(f"Unsupported challenge question schema version: {version}.")


def _schema_issues(output: dict[str, Any]) -> list[dict[str, str]]:
    version = _output_schema_version(output)
    if version not in {1, 2}:
        return [
            {
                "path": "schema_version",
                "message": f"Unsupported challenge question schema version: {version}.",
            }
        ]
    schema = _read_json(_schema_path(version))
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
    review = output.get("review") if isinstance(output.get("review"), dict) else {}
    audit = output.get("audit") if isinstance(output.get("audit"), dict) else {}
    human_review_status = (
        review.get("human_review_status")
        if _output_schema_version(output) == 2
        else audit.get("human_review_status")
    )
    h4_decision = {
        "passed": "approved",
        "revision_requested": "revision_requested",
        "rejected": "rejected",
    }.get(str(human_review_status or ""), "pending")
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
    if _output_schema_version(output) == 2:
        output.setdefault("review", {})["human_review_status"] = "pending"
        output.setdefault("submission", {}).update(
            {"eligible": False, "projection_version": "1.0-review.1", "blockers": ["human_review_pending"]}
        )
    if _output_status(output) not in {"blocked", "failed"}:
        _set_output_status(output, "review_required")


def _all_human_gates_approved(gates: Any) -> bool:
    if not isinstance(gates, dict) or gates.get("allApproved") is not True:
        return False
    decisions = gates.get("decisions")
    return (
        isinstance(decisions, dict)
        and set(decisions) == REQUIRED_HUMAN_GATE_KEYS
        and all(str(decisions[key]) == APPROVED_GATE_DECISION for key in REQUIRED_HUMAN_GATE_KEYS)
    )


def _official_model_evidence_ids(team_id: str) -> set[str]:
    store = _read_json(_workflow_root(team_id) / "official_model_evidence" / "index.json")
    evidence = store.get("evidence") if isinstance(store.get("evidence"), list) else []
    return {
        str(item.get("evidenceId") or "")
        for item in evidence
        if isinstance(item, dict)
        and any(
            marker in str(item.get("modelProvider") or "").lower()
            for marker in OFFICIAL_PROVIDERS
        )
        and str(item.get("status") or "").lower() != "derived_from_candidate_store"
    }


def _official_model_evidence_store(team_id: str) -> dict[str, Any]:
    store = _read_json(_workflow_root(team_id) / "official_model_evidence" / "index.json")
    evidence = store.get("evidence") if isinstance(store.get("evidence"), list) else []
    receipts = store.get("receipts") if isinstance(store.get("receipts"), list) else []
    return {
        "schemaVersion": store.get("schemaVersion", 1),
        "storeKind": store.get("storeKind", ""),
        "evidence": [deepcopy(item) for item in evidence if isinstance(item, dict)],
        "receipts": [deepcopy(item) for item in receipts if isinstance(item, dict)],
    }


def _bounded_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def ensure_official_model_evidence_for_receipt_refs(
    team_id: str,
    *,
    question_id: str,
    workflow_run_id: str,
    receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Mirror validated invocation receipts into the official evidence store.

    Writes the exact store this module's official-call gate reads
    (``_official_model_evidence_ids`` over ``_workflow_root(team_id) /
    official_model_evidence / index.json``), so a registered run's
    ``invocation_evidence_refs`` can intersect registered evidence instead of
    intersecting an empty store.  Every ``question_model_invocation_receipts``
    row already proves a real succeeded model call; rows are appended
    idempotently under the stable ``model-invocation-receipt:{receiptId}``
    evidence id, rows without receiptId/provider are skipped and counted (a
    single bad receipt never fails the batch), and nothing here promotes
    formal knowledge.  modelProvider keeps the receipt's concrete provider id
    (e.g. ``dashscope_main``); the gate matches it by contains-marker.
    """
    normalized_team_id = str(team_id or "").strip()
    normalized_question = str(question_id or "").strip().upper()
    normalized_run = str(workflow_run_id or "").strip()
    rows = [item for item in list(receipts or []) if isinstance(item, dict)]
    evidence_path = _evidence_store_path(_workflow_root(normalized_team_id))
    registered = 0
    skipped = 0
    now = _utc_now()
    with _STORE_LOCK:
        store = _load_evidence_store(evidence_path, normalized_team_id)
        evidence = [item for item in store.get("evidence", []) if isinstance(item, dict)]
        existing = {str(item.get("evidenceId") or "") for item in evidence}
        for receipt in rows:
            receipt_id = _bounded_text(receipt.get("receiptId"), 160)
            provider = _bounded_text(receipt.get("provider"), 120)
            if not receipt_id or not provider:
                skipped += 1
                continue
            evidence_id = f"model-invocation-receipt:{receipt_id}"
            if evidence_id in existing:
                skipped += 1
                continue
            scope = receipt.get("scope") if isinstance(receipt.get("scope"), dict) else {}
            stage_id = _bounded_text(scope.get("stageId"), 128)
            evidence.append(
                {
                    "schemaVersion": store.get("schemaVersion", 1),
                    "evidenceId": evidence_id,
                    "teamId": normalized_team_id,
                    "workflowId": "",
                    "workflowKind": "",
                    "taskType": "",
                    "workflowNode": "",
                    "candidateId": "",
                    "stageRoundId": stage_id,
                    "sourceRunId": normalized_run,
                    "taskId": _bounded_text(scope.get("taskId"), 128),
                    "modelProvider": provider,
                    "modelId": _bounded_text(receipt.get("requestedModel"), 160),
                    "modelName": _bounded_text(receipt.get("model"), 240),
                    "modelProfileId": "",
                    "evidenceKind": "invocation_log",
                    "artifactPath": "",
                    "screenshotPath": "",
                    "logRef": "",
                    "promptSummary": "",
                    "outputSummary": "",
                    "sourceRefs": [normalized_run] if normalized_run else [],
                    "evidenceRefs": [],
                    "status": "registered",
                    "recordedByAgent": "stage_one_command_service",
                    "metadata": {
                        "questionId": normalized_question,
                        "workflowRunId": normalized_run,
                        "stageId": stage_id,
                        "nodeRunId": _bounded_text(receipt.get("nodeRunId"), 160),
                        "formalNodeId": _bounded_text(scope.get("formalNodeId"), 160),
                        "attempt": receipt.get("attempt"),
                    },
                    "officialBoundary": {
                        "candidateOnly": True,
                        "writesFormalKnowledge": False,
                        "writesRag": False,
                        "writesOfficialGraph": False,
                        "requiresStewardApproval": True,
                        "boundary": "model_evidence_only_not_formal_knowledge",
                    },
                    "createdAt": now,
                    "updatedAt": now,
                }
            )
            existing.add(evidence_id)
            registered += 1
        if registered:
            store["evidence"] = evidence
            store["updatedAt"] = now
            _write_json(evidence_path, store)
    if registered:
        try:
            record_runtime_scene_event(
                "team_workflow_orchestration",
                "challenge_question_run",
                "official_model_evidence.receipt_refs_ensured",
                message="Stage-one invocation receipts were mirrored into the official model evidence store.",
                outcome="passed",
                fields={
                    "teamId": normalized_team_id,
                    "questionId": normalized_question,
                    "workflowRunId": normalized_run,
                    "registeredCount": registered,
                    "skippedCount": skipped,
                    "receiptCount": len(rows),
                },
            )
        except Exception:  # noqa: BLE001 - observability must never gate the mirror
            pass
    return {
        "registered": registered,
        "skipped": skipped,
        "evidenceStorePath": str(evidence_path),
    }


def _evidence_store_path(root: Path) -> Path:
    return root / "official_model_evidence" / "index.json"


def _load_evidence_store(path: Path, team_id: str) -> dict[str, Any]:
    store = _read_json(path)
    if store.get("storeKind") == "official_model_evidence_store" and isinstance(store.get("evidence"), list):
        return store
    now = _utc_now()
    return {
        "schemaVersion": 1,
        "storeKind": "official_model_evidence_store",
        "teamId": team_id,
        "evidence": [],
        "createdAt": now,
        "updatedAt": now,
    }


def _receipt_scope_value(scope: dict[str, Any], *keys: str, field: str) -> str:
    values = [str(scope.get(key) or "").strip() for key in keys if key in scope]
    if not values or not values[0]:
        raise ValueError(f"challenge_task_model_evidence_receipt_missing_{field}")
    if any(value != values[0] for value in values[1:]):
        raise ValueError(f"challenge_task_model_evidence_receipt_conflicting_{field}")
    return values[0]


def _receipt_locator_value(locator: dict[str, Any], *keys: str, field: str) -> str:
    values = [str(locator.get(key) or "").strip() for key in keys if key in locator]
    if not values or not values[0]:
        raise ValueError(f"challenge_task_model_evidence_receipt_missing_{field}")
    if any(value != values[0] for value in values[1:]):
        raise ValueError(f"challenge_task_model_evidence_receipt_conflicting_{field}")
    return values[0]


def _validate_challenge_model_invocation_receipt(
    value: Any,
    *,
    stage_id: str,
    model_policy_sha256: str,
    question_id: str,
    run_id: str,
    task_id: str,
    turn_id: str,
    output_sha256: str,
    output_ref: str,
    expected_provider: str,
    usage_provider: str,
    expected_model: str,
) -> ModelInvocationReceipt:
    if stage_id not in {"generation", "review", "revision"}:
        raise ValueError(
            "challenge_task_model_evidence_receipt_stage_invalid: "
            "stageId must be generation, review or revision."
        )
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(model_policy_sha256 or "")):
        raise ValueError(
            "challenge_task_model_evidence_receipt_policy_invalid: "
            "modelPolicySha256 must be a SHA-256 digest."
        )
    try:
        receipt = (
            value
            if isinstance(value, ModelInvocationReceipt)
            else ModelInvocationReceipt.from_dict(value)
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError(
            "challenge_task_model_evidence_receipt_invalid: "
            "modelInvocationReceipt is not a valid receipt."
        ) from exc
    if receipt.status not in {ModelInvocationStatus.SUCCEEDED, ModelInvocationStatus.RETRIED}:
        raise ValueError(
            "challenge_task_model_evidence_receipt_status_invalid: "
            "only succeeded or retried receipts are eligible."
        )
    if receipt.run_id != run_id:
        raise ValueError("challenge_task_model_evidence_receipt_run_mismatch")
    accepted_providers = {
        str(usage_provider or "").strip().lower(),
        str(expected_provider or "").strip().lower(),
        str(expected_provider or "").partition("_")[0].lower(),
    }
    if receipt.provider.strip().lower() not in accepted_providers:
        raise ValueError("challenge_task_model_evidence_receipt_provider_mismatch")
    if receipt.model.strip().lower() != str(expected_model or "").strip().lower():
        raise ValueError("challenge_task_model_evidence_receipt_model_mismatch")
    if receipt.requested_model.strip().lower() != str(expected_model or "").strip().lower():
        raise ValueError("challenge_task_model_evidence_receipt_requested_model_mismatch")
    scope = dict(receipt.scope or {})
    if _receipt_scope_value(scope, "questionId", "question_id", "question", field="question") != question_id:
        raise ValueError("challenge_task_model_evidence_receipt_question_mismatch")
    if _receipt_scope_value(scope, "runId", "run_id", field="run") != run_id:
        raise ValueError("challenge_task_model_evidence_receipt_scope_run_mismatch")
    if _receipt_scope_value(scope, "taskId", "task_id", "task", field="task") != task_id:
        raise ValueError("challenge_task_model_evidence_receipt_task_mismatch")
    if _receipt_scope_value(scope, "turnId", "turn_id", "turn", field="turn") != turn_id:
        raise ValueError("challenge_task_model_evidence_receipt_turn_mismatch")
    if _receipt_scope_value(scope, "stageId", "stage_id", "stage", "nodeId", field="stage") != stage_id:
        raise ValueError("challenge_task_model_evidence_receipt_stage_mismatch")
    if _receipt_scope_value(scope, "modelPolicySha256", "model_policy_sha256", field="model_policy") .lower() != str(model_policy_sha256).lower():
        raise ValueError("challenge_task_model_evidence_receipt_policy_mismatch")
    locator = dict(receipt.evidence_locator or {})
    if _receipt_locator_value(locator, "outputSha256", "output_sha256", "outputHash", field="output_sha256").removeprefix("sha256:").lower() != output_sha256.lower():
        raise ValueError("challenge_task_model_evidence_receipt_output_hash_mismatch")
    if _receipt_locator_value(locator, "outputRef", "output_ref", "ref", field="output_ref") != output_ref:
        raise ValueError("challenge_task_model_evidence_receipt_output_ref_mismatch")
    return receipt


def _normalized_string_list(value: Any, *, max_items: int = 16, max_length: int = 160) -> list[str]:
    values = value if isinstance(value, list) else []
    result: list[str] = []
    for item in values:
        normalized = str(item or "").strip()[:max_length]
        if normalized and normalized not in result:
            result.append(normalized)
        if len(result) >= max_items:
            break
    return result


def normalize_challenge_research_task_policy(
    question_id: Any,
    required_model_policy: Any,
) -> dict[str, Any]:
    """Validate the explicit question and frozen server model route contract."""
    normalized_question_id = str(question_id or "").strip()[:32]
    policy = dict(required_model_policy) if isinstance(required_model_policy, dict) else {}
    if not normalized_question_id and not policy:
        return {}
    if not normalized_question_id or not policy:
        raise ValueError("challenge_task_contract_incomplete: questionId and requiredModelPolicy are both required.")
    if _catalog_question(normalized_question_id) is None:
        raise ValueError("challenge_task_question_unknown: questionId is not present in the official catalog.")
    canonical_policy: dict[str, Any] | None = None
    if "family" in policy or "policySha256" in policy:
        try:
            canonical_policy = canonical_model_policy(policy)
        except QuestionResultPackageError as exc:
            raise ValueError(
                "challenge_task_model_policy_invalid: requiredModelPolicy is not canonical."
            ) from exc
        supplied_hash = str(policy.get("policySha256") or "").strip().lower()
        if supplied_hash and supplied_hash != canonical_policy["policySha256"]:
            raise ValueError(
                "challenge_task_model_policy_invalid: requiredModelPolicy hash does not match."
            )
        policy = canonical_policy
    provider_ids = _normalized_string_list(policy.get("providerIds"))
    model_ids = _normalized_string_list(policy.get("modelIds"))
    require_official = policy.get("requireOfficialProvider")
    if (
        not provider_ids
        or not model_ids
        or not isinstance(require_official, bool)
    ):
        raise ValueError(
            "challenge_task_model_policy_invalid: providerIds, modelIds and a boolean requireOfficialProvider are required."
        )
    if require_official and any(
        not any(marker in provider_id.lower() for marker in OFFICIAL_PROVIDERS)
        for provider_id in provider_ids
    ):
        raise ValueError("challenge_task_model_policy_invalid: providerIds must identify DashScope/Bailian/Aliyun.")
    required_policy = (
        canonical_policy
        if canonical_policy is not None
        else {
            "providerIds": provider_ids,
            "modelIds": model_ids,
            "requireOfficialProvider": require_official,
        }
    )
    contract = {
        "questionId": normalized_question_id,
        "requiredModelPolicy": required_policy,
    }
    if canonical_policy is not None:
        contract["modelPolicySha256"] = canonical_policy["policySha256"]
    return contract


def derive_challenge_required_model_policy(model_ref: Any) -> dict[str, Any]:
    """Recover a narrow frozen-model policy from a canonical provider/model ref."""
    normalized_model_ref = str(model_ref or "").strip()[:160]
    provider_id, separator, model_id = normalized_model_ref.partition("/")
    if (
        not separator
        or not provider_id
        or not model_id
    ):
        return {}
    return {
        "providerIds": [provider_id],
        "modelIds": [model_id],
        "requireOfficialProvider": any(
            marker in provider_id.lower() for marker in OFFICIAL_PROVIDERS
        ),
    }


def is_challenge_official_model_evidence_eligible(
    policy: Any,
    *,
    provider_id: Any,
    model_ref: Any = "",
    model_id: Any = "",
) -> bool:
    """Return whether a server-owned route can mint official model evidence.

    Execution is intentionally independent from this gate: the current Flash
    route remains executable, but only a canonical Qwen policy with an
    official DashScope/Bailian/Aliyun provider may enter the official ledger.
    """
    if not isinstance(policy, dict):
        return False
    if str(policy.get("family") or "").strip().casefold() != "qwen":
        return False
    if policy.get("requireOfficialProvider") is not True:
        return False
    try:
        if canonical_model_policy(policy) != policy:
            return False
    except QuestionResultPackageError:
        return False
    normalized_provider = str(provider_id or "").strip().casefold()
    if not normalized_provider:
        return False
    provider_is_official = any(
        normalized_provider == marker
        or normalized_provider.startswith((f"{marker}_", f"{marker}-"))
        for marker in OFFICIAL_PROVIDERS
    )
    allowed_provider_ids = {
        str(item or "").strip().casefold()
        for item in policy.get("providerIds", [])
    }
    allowed_model_ids = {
        str(item or "").strip().casefold()
        for item in policy.get("modelIds", [])
    }
    model_candidates = {
        str(model_ref or "").strip().casefold(),
        str(model_id or "").strip().casefold(),
    }
    model_candidates.discard("")
    return (
        normalized_provider in allowed_provider_ids
        and bool(model_candidates & allowed_model_ids)
        and provider_is_official
    )


def _official_call_from_canonical_package(
    *,
    model_policy: Any,
    model_provider: Any,
    model_ref: Any,
    receipt_refs: Any,
) -> bool:
    """Derive the catalog gate from canonical policy and verified receipts."""

    normalized_model_ref = str(model_ref or "").strip()
    model_id = normalized_model_ref.rpartition("/")[2]
    normalized_policy = dict(model_policy) if isinstance(model_policy, Mapping) else model_policy
    if isinstance(normalized_policy, dict):
        for field in ("providerIds", "modelIds"):
            if isinstance(normalized_policy.get(field), tuple):
                normalized_policy[field] = list(normalized_policy[field])
    return bool(receipt_refs) and is_challenge_official_model_evidence_eligible(
        normalized_policy,
        provider_id=model_provider,
        model_ref=normalized_model_ref,
        model_id=model_id,
    )


def bind_challenge_research_task_model(
    *,
    team_id: str,
    research_project_id: str,
    question_id: Any,
    required_model_policy: Any,
    dialogue_model_id: Any,
    model_library: dict[str, Any],
) -> dict[str, Any]:
    """Resolve the configured Agent route and classify its official-evidence eligibility."""
    contract = normalize_challenge_research_task_policy(question_id, required_model_policy)
    if not contract:
        return {}
    resolve_research_project_workspace_root(team_id, research_project_id)
    model_ref = str(dialogue_model_id or "").strip()
    entry = model_library.get(model_ref) if isinstance(model_library, dict) else None
    if not model_ref or not isinstance(entry, dict):
        raise ValueError(
            "challenge_required_model_unavailable: Agent dialogue model is missing from the effective model library."
        )
    provider_id = str(entry.get("provider_id") or "").strip() or model_ref.partition("/")[0]
    upstream_model_id = str(entry.get("upstream_id") or entry.get("model") or "").strip()
    policy = contract["requiredModelPolicy"]
    official_evidence_eligible = is_challenge_official_model_evidence_eligible(
        policy,
        provider_id=provider_id,
        model_ref=model_ref,
        model_id=upstream_model_id,
    )
    return {
        **contract,
        "researchProjectId": research_project_id,
        "effectiveRoute": {
            "modelRef": model_ref,
            "providerId": provider_id,
            "modelId": upstream_model_id,
        },
        "executionPolicy": {
            "routeSource": "agent_dialogue_binding",
            "configuredModelAuthoritative": True,
        },
        "evidencePolicy": {
            "recordCanonicalSuccessOnly": True,
            "rawPayloadPersistence": "forbidden",
            "publishRequiredForProgramLedger": True,
            "officialEvidenceEligible": official_evidence_eligible,
        },
    }


def register_challenge_task_model_evidence(
    team_id: str,
    task: dict[str, Any],
    *,
    final_status: str,
    llm_usage: dict[str, Any] | None,
    model_invocation_receipt: ModelInvocationReceipt | dict[str, Any] | None = None,
    stage_id: str | None = None,
    model_policy_sha256: str | None = None,
) -> dict[str, Any] | None:
    """Idempotently bind a successful canonical call to a project/task/turn."""
    contract = task.get("challengeTaskContract") if isinstance(task.get("challengeTaskContract"), dict) else {}
    usage = dict(llm_usage) if isinstance(llm_usage, dict) else {}
    if not contract or str(final_status or "").strip() != "completed":
        return None
    evidence_policy = (
        contract.get("evidencePolicy")
        if isinstance(contract.get("evidencePolicy"), dict)
        else {}
    )
    if evidence_policy.get("officialEvidenceEligible") is not True:
        return None
    if str(usage.get("source") or "").strip() in {"", "missing", "not_called", "not_called_preflight"}:
        return None
    effective = contract.get("effectiveRoute") if isinstance(contract.get("effectiveRoute"), dict) else {}
    if not is_challenge_official_model_evidence_eligible(
        contract.get("requiredModelPolicy"),
        provider_id=effective.get("providerId"),
        model_ref=effective.get("modelRef"),
        model_id=effective.get("modelId"),
    ):
        return None
    usage_provider = str(usage.get("provider") or "").strip()
    usage_model = str(usage.get("model") or "").strip()
    usage_model_ref = str(usage.get("llmModelId") or "").strip()
    expected_provider = str(effective.get("providerId") or "").strip()
    expected_model = str(effective.get("modelId") or "").strip()
    expected_model_ref = str(effective.get("modelRef") or "").strip()
    if (
        not usage_provider
        or usage_provider.lower() not in {expected_provider.lower(), expected_provider.partition("_")[0].lower()}
        or usage_model.lower() != expected_model.lower()
        or (usage_model_ref and usage_model_ref != expected_model_ref)
    ):
        return None
    research_project_id = str(contract.get("researchProjectId") or task.get("researchProjectId") or "").strip()
    question_id = str(contract.get("questionId") or "").strip()
    task_id = str(task.get("taskId") or "").strip()
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    turn_id = str(turn.get("turnId") or "").strip()
    if not all((research_project_id, question_id, task_id, turn_id)):
        return None
    source_session_id = str(task.get("sessionId") or turn.get("sessionId") or "").strip()
    challenge_contract = (
        task.get("challengeTaskContract")
        if isinstance(task.get("challengeTaskContract"), dict)
        else {}
    )
    source_run_id = next(
        (
            value
            for value in (
                task.get("runId"),
                task.get("workflowRunId"),
                challenge_contract.get("runId"),
            )
            if str(value or "").strip()
        ),
        "",
    )
    source_binding = _read_canonical_turn_output(
        session_id=source_session_id,
        source_run_id=source_run_id,
        task_id=task_id,
        turn_id=turn_id,
    )
    if source_binding is None:
        return None
    formal_receipt = model_invocation_receipt is not None or stage_id is not None or model_policy_sha256 is not None
    if formal_receipt and (
        model_invocation_receipt is None
        or not str(stage_id or "").strip()
        or not str(model_policy_sha256 or "").strip()
    ):
        raise ValueError(
            "challenge_task_model_evidence_receipt_contract_incomplete: "
            "modelInvocationReceipt, stageId and modelPolicySha256 are required together."
        )
    validated_receipt: ModelInvocationReceipt | None = None
    normalized_stage_id = str(stage_id or "").strip()
    normalized_policy_sha256 = str(model_policy_sha256 or "").strip().lower()
    if formal_receipt:
        validated_receipt = _validate_challenge_model_invocation_receipt(
            model_invocation_receipt,
            stage_id=normalized_stage_id,
            model_policy_sha256=normalized_policy_sha256,
            question_id=question_id,
            run_id=source_run_id,
            task_id=task_id,
            turn_id=turn_id,
            output_sha256=source_binding["outputSha256"],
            output_ref=source_binding["outputRef"],
            expected_provider=expected_provider,
            usage_provider=usage_provider,
            expected_model=expected_model,
        )
    identity = f"{team_id}|{research_project_id}|{question_id}|{task_id}|{turn_id}|{expected_model_ref}"
    if formal_receipt:
        identity += f"|{normalized_stage_id}"
    evidence_id = f"model-evidence-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"
    path = _evidence_store_path(resolve_research_project_workspace_root(team_id, research_project_id))
    with _STORE_LOCK:
        store = _load_evidence_store(path, team_id)
        evidence = [item for item in store.get("evidence", []) if isinstance(item, dict)]
        existing = next((item for item in evidence if str(item.get("evidenceId") or "") == evidence_id), None)
        if existing is not None:
            if (
                str(existing.get("sourceSessionId") or "").strip() != source_binding["sessionId"]
                or str(existing.get("sourceRunId") or "").strip() != source_binding["sourceRunId"]
                or str(existing.get("taskId") or "").strip() != source_binding["taskId"]
                or str(existing.get("turnId") or "").strip() != source_binding["turnId"]
                or str(existing.get("outputSha256") or "").strip().lower() != source_binding["outputSha256"]
                or str(existing.get("outputRef") or "").strip() != source_binding["outputRef"]
            ):
                raise ValueError(
                    "challenge_task_model_evidence_provenance_conflict: existing evidence "
                    "does not match the canonical server turn artifact."
                )
            if formal_receipt:
                if (
                    str(existing.get("receiptId") or "") != validated_receipt.receipt_id
                    or str(existing.get("stageId") or "") != normalized_stage_id
                    or str(existing.get("modelPolicySha256") or "").lower() != normalized_policy_sha256
                ):
                    raise ValueError(
                        "challenge_task_model_evidence_receipt_provenance_conflict: "
                        "existing evidence is bound to a different receipt."
                    )
                stored_receipts = [
                    item
                    for item in store.get("receipts", [])
                    if isinstance(item, dict)
                ]
                stored = next(
                    (
                        item
                        for item in stored_receipts
                        if str(item.get("receiptId") or "") == validated_receipt.receipt_id
                    ),
                    None,
                )
                if stored is None or stored != validated_receipt.to_dict():
                    raise ValueError(
                        "challenge_task_model_evidence_receipt_provenance_conflict: "
                        "stored receipt does not match the submitted receipt."
                    )
            return deepcopy(existing)
        now = _utc_now()
        record = {
            "schemaVersion": 1,
            "evidenceId": evidence_id,
            "teamId": team_id,
            "researchProjectId": research_project_id,
            "questionId": question_id,
            "sourceRunId": source_binding["sourceRunId"],
            "sourceSessionId": source_binding["sessionId"],
            "taskId": task_id,
            "turnId": turn_id,
            "taskType": str(task.get("agentRole") or task.get("stageId") or ""),
            "workflowNode": str(task.get("stageId") or ""),
            "modelProvider": usage_provider,
            "providerId": expected_provider,
            "modelId": usage_model,
            "modelRef": expected_model_ref,
            "evidenceKind": "invocation_log",
            "logRef": f"session:{task.get('sessionId', '')}/turn:{turn_id}",
            "status": "canonical_success",
            "recordedByAgent": str(task.get("agentId") or ""),
            "metadata": {
                "llmUsageSource": str(usage.get("source") or ""),
                "inputTokens": int(usage.get("inputTokens") or 0),
                "outputTokens": int(usage.get("outputTokens") or 0),
                "totalTokens": int(usage.get("totalTokens") or 0),
            },
            "officialBoundary": {
                "candidateOnly": True,
                "publishRequired": True,
                "humanApprovalGranted": False,
                "rawPayloadPersisted": False,
            },
            "createdAt": now,
            "updatedAt": now,
        }
        if formal_receipt:
            record.update(
                {
                    "schemaVersion": 2,
                    "receiptId": validated_receipt.receipt_id,
                    "stageId": normalized_stage_id,
                    "modelPolicySha256": normalized_policy_sha256,
                    "logRef": source_binding["outputRef"],
                }
            )
        record["outputSha256"] = source_binding["outputSha256"]
        record["outputRef"] = source_binding["outputRef"]
        if formal_receipt:
            stored_receipts = [
                item
                for item in store.get("receipts", [])
                if isinstance(item, dict)
            ]
            existing_receipt = next(
                (
                    item
                    for item in stored_receipts
                    if str(item.get("receiptId") or "") == validated_receipt.receipt_id
                ),
                None,
            )
            serialized_receipt = validated_receipt.to_dict()
            if existing_receipt is not None and existing_receipt != serialized_receipt:
                raise ValueError(
                    "challenge_task_model_evidence_receipt_provenance_conflict: "
                    "receiptId is already bound to different content."
                )
            if existing_receipt is None:
                stored_receipts.append(serialized_receipt)
            store["receipts"] = stored_receipts
            store["schemaVersion"] = OFFICIAL_EVIDENCE_SCHEMA_VERSION
        evidence.append(record)
        store["evidence"] = evidence
        store["updatedAt"] = now
        _write_json(path, store)
        return deepcopy(record)


def publish_research_project_challenge_question_output(
    team_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Promote one validated project result into the stable program candidate ledger."""
    team_service.get_team(team_id)
    research_project_id = str(payload.get("researchProjectId") or "").strip()
    question_id = str(payload.get("questionId") or "").strip()
    task_id = str(payload.get("taskId") or "").strip()
    turn_id = str(payload.get("turnId") or "").strip()
    evidence_id = str(payload.get("projectEvidenceId") or "").strip()
    if not all((research_project_id, question_id, task_id, turn_id, evidence_id)):
        raise ValueError(
            "challenge_question_publish_contract_incomplete: researchProjectId, questionId, taskId, turnId and projectEvidenceId are required."
        )
    project_evidence_path = _evidence_store_path(
        resolve_research_project_workspace_root(team_id, research_project_id)
    )
    project_store = _load_evidence_store(project_evidence_path, team_id)
    project_evidence = next(
        (
            item
            for item in project_store.get("evidence", [])
            if isinstance(item, dict) and str(item.get("evidenceId") or "") == evidence_id
        ),
        None,
    )
    if project_evidence is None:
        raise ValueError("challenge_question_publish_evidence_missing: project evidence was not found.")
    expected_binding = {
        "researchProjectId": research_project_id,
        "questionId": question_id,
        "taskId": task_id,
        "turnId": turn_id,
    }
    if any(str(project_evidence.get(key) or "") != value for key, value in expected_binding.items()):
        raise ValueError("challenge_question_publish_evidence_mismatch: evidence binding does not match the publish request.")
    if str(project_evidence.get("status") or "") != "canonical_success":
        raise ValueError("challenge_question_publish_evidence_invalid: only canonical successful calls can be published.")
    canonical_binding = _canonical_evidence_output_binding(project_evidence)
    source_session_id = str(project_evidence.get("sourceSessionId") or "").strip()
    parsed_ref = _parse_canonical_output_ref(canonical_binding["outputRef"])
    if parsed_ref is None or parsed_ref.get("sessionId") != source_session_id:
        raise ValueError(
            "challenge_question_publish_evidence_output_ref_invalid: project evidence outputRef "
            "must be a server-issued canonical turn-journal reference."
        )
    canonical_artifact = _read_canonical_turn_output(
        session_id=source_session_id,
        source_run_id=canonical_binding["sourceRunId"],
        task_id=canonical_binding["taskId"],
        turn_id=canonical_binding["turnId"],
        output_ref=canonical_binding["outputRef"],
    )
    if canonical_artifact is None:
        raise ValueError(
            "challenge_question_publish_canonical_artifact_missing: canonical turn output "
            "could not be read from the server journal."
        )
    if (
        canonical_artifact["outputSha256"] != canonical_binding["outputSha256"]
        or canonical_artifact["outputRef"] != canonical_binding["outputRef"]
    ):
        raise ValueError(
            "challenge_question_publish_provenance_conflict: project evidence binding does "
            "not match the canonical server turn artifact."
        )

    raw_output = payload.get("output")
    if not isinstance(raw_output, dict):
        raise TypeError("output must be an object.")
    output = deepcopy(raw_output)
    # Artifact filesystem paths are built from client-supplied ids; reject
    # anything path-shaped (Windows backslashes, "..", separators) before
    # any other processing — it is a store-escape write primitive.
    from core.web.services.team_workflow.storage_ids import validate_artifact_component

    _early_run = output.get("run") if isinstance(output.get("run"), dict) else {}
    _early_question_id = _output_question_id(output)
    _early_run_id = str(_early_run.get("run_id") or "").strip()
    if _early_question_id:
        validate_artifact_component(_early_question_id, field="output.identity.question_id")
    if _early_run_id:
        validate_artifact_component(_early_run_id, field="output.run.run_id")
    _require_writable_schema(output)
    if _output_question_id(output) != question_id:
        raise ValueError("challenge_question_publish_question_mismatch: output.question_id must match questionId.")
    run = output.get("run") if isinstance(output.get("run"), dict) else {}
    output_run_id = str(run.get("run_id") or "").strip()
    if output_run_id != canonical_binding["sourceRunId"]:
        raise ValueError(
            "challenge_question_publish_source_run_mismatch: output.run.run_id must match "
            "the canonical project evidence sourceRunId."
        )
    if (
        str(run.get("model_provider") or "").strip().lower() not in OFFICIAL_PROVIDERS
        or str(run.get("model_id") or "").strip().lower()
        not in {
            str(project_evidence.get("modelId") or "").strip().lower(),
            str(project_evidence.get("modelRef") or "").strip().lower(),
        }
    ):
        raise ValueError("challenge_question_publish_model_mismatch: output model does not match canonical evidence.")
    invocation_refs = _normalized_string_list(run.get("invocation_evidence_refs"), max_items=64)
    if evidence_id not in invocation_refs:
        raise ValueError(
            "challenge_question_publish_evidence_ref_mismatch: output.run.invocation_evidence_refs "
            "must explicitly contain projectEvidenceId."
        )
    output_hash = _output_sha256(output)
    if output_hash != canonical_artifact["outputSha256"]:
        raise ValueError(
            "challenge_question_publish_output_hash_mismatch: output does not match the "
            "canonical server turn artifact."
        )
    raw_lineage_refs = payload.get("lineageRefs")
    lineage_refs = list(
        dict.fromkeys(
            str(item).strip()
            for item in (raw_lineage_refs if isinstance(raw_lineage_refs, list) else [])
            if str(item).strip()
        )
    )
    if canonical_binding["outputRef"] and canonical_binding["outputRef"] not in lineage_refs:
        raise ValueError(
            "challenge_question_publish_output_ref_mismatch: lineageRefs must explicitly "
            "carry the canonical project evidence outputRef."
        )

    preview = deepcopy(output)
    _set_pending_human_gates(preview)
    citation_checks = payload.get("citationChecks") if isinstance(payload.get("citationChecks"), list) else []
    citation = _citation_validation(preview, citation_checks)
    semantic = _semantic_validation(preview)
    issues = _schema_issues(preview)
    catalog_question = _catalog_question(question_id)
    if catalog_question is None:
        issues.append({"path": "question_id", "message": "Question id is not present in the official catalog."})
    elif str(catalog_question.get("question_en") or "") != _output_question_en(preview):
        issues.append({"path": "identity.question_en", "message": "Question text does not match the official catalog."})
    issues.extend(semantic["issues"])
    if issues or citation["status"] != "passed" or semantic["status"] != "passed":
        raise ValueError("challenge_question_publish_not_ready: schema, citations, hypotheses, seven reviews and research plan must pass.")

    program_evidence_path = _evidence_store_path(_workflow_root(team_id))
    with _STORE_LOCK:
        program_store = _load_evidence_store(program_evidence_path, team_id)
        program_evidence = [item for item in program_store.get("evidence", []) if isinstance(item, dict)]
        program_receipts = [item for item in program_store.get("receipts", []) if isinstance(item, dict)]
        project_receipts = [item for item in project_store.get("receipts", []) if isinstance(item, dict)]
        receipts_changed = False
        for project_receipt in project_receipts:
            receipt_id = str(project_receipt.get("receiptId") or "").strip()
            if not receipt_id:
                raise ValueError(
                    "challenge_question_publish_receipt_invalid: project receipt is missing receiptId."
                )
            existing_receipt = next(
                (
                    item
                    for item in program_receipts
                    if str(item.get("receiptId") or "").strip() == receipt_id
                ),
                None,
            )
            if existing_receipt is not None and existing_receipt != project_receipt:
                raise ValueError(
                    "challenge_question_publish_receipt_provenance_conflict: "
                    "published receipt id is already bound to different content."
                )
            if existing_receipt is None:
                program_receipts.append(deepcopy(project_receipt))
                receipts_changed = True
        if project_receipts:
            program_store["receipts"] = program_receipts
            program_store["schemaVersion"] = OFFICIAL_EVIDENCE_SCHEMA_VERSION
        promoted = next((item for item in program_evidence if str(item.get("evidenceId") or "") == evidence_id), None)
        if promoted is not None:
            promoted_binding = _canonical_evidence_output_binding(promoted)
            if any(
                promoted_binding.get(key) != canonical_binding.get(key)
                for key in ("sourceRunId", "taskId", "turnId", "outputSha256", "outputRef")
            ):
                raise ValueError(
                    "challenge_question_publish_provenance_conflict: published evidence id is "
                    "already bound to different canonical provenance."
                )
            if str(promoted.get("sourceSessionId") or "").strip() != source_session_id:
                raise ValueError(
                    "challenge_question_publish_provenance_conflict: published evidence id is "
                    "already bound to a different canonical session."
                )
        else:
            promoted = {
                **deepcopy(project_evidence),
                "status": "published_to_challenge_program",
                "publishedAt": _utc_now(),
                "officialBoundary": {
                    "candidateOnly": False,
                    "publishedToChallengeProgram": True,
                    "humanApprovalGranted": False,
                    "rawPayloadPersisted": False,
                },
            }
            program_evidence.append(promoted)
            program_store["evidence"] = program_evidence
            program_store["updatedAt"] = promoted["publishedAt"]
            _write_json(program_evidence_path, program_store)
        if promoted is not None and receipts_changed:
            program_store["updatedAt"] = _utc_now()
            _write_json(program_evidence_path, program_store)
        registration_payload = {
            "output": output,
            "citationChecks": citation_checks,
            "registeredBy": str(payload.get("registeredBy") or ""),
            "parentRunId": str(payload.get("parentRunId") or ""),
            "lineageRefs": lineage_refs,
        }
        result_package = payload.get("resultPackage")
        if isinstance(result_package, dict):
            registration_payload["resultPackage"] = deepcopy(result_package)
        authorized_model_policy_sha256 = str(
            payload.get("authorizedModelPolicySha256") or ""
        ).strip()
        if authorized_model_policy_sha256:
            registration_payload["authorizedModelPolicySha256"] = (
                authorized_model_policy_sha256
            )
        registered = register_challenge_question_output(
            team_id,
            registration_payload,
        )
    return {
        **registered,
        "researchProjectId": research_project_id,
        "projectEvidenceId": evidence_id,
        "publishedEvidence": deepcopy(promoted),
        "humanReviewRequired": True,
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


def _receipt_locator_sha256(locator: dict[str, Any]) -> str:
    canonical = json.dumps(
        locator,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()


def _model_invocation_receipt_refs_from_package(package: Any) -> dict[str, dict[str, Any]]:
    """Project bounded receipt identities from the validated package authority."""

    from core.research.competition.result_set import QuestionResult

    return deepcopy(QuestionResult.from_package(package).manifest_entry()["receipts"])


def _question_model_invocation_trace_projection(
    team_id: str,
    record: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read and verify the immutable per-invocation projection for one run."""

    from core.web.services.team_workflow.research_runtime.model_invocation_receipt_registry import (
        model_invocation_receipt_coverage,
        question_model_invocation_receipt_refs,
    )

    question_id = str(record.get("questionId") or "").strip().upper()
    run_id = str(record.get("runId") or "").strip()
    refs = (
        question_model_invocation_receipt_refs(
            team_id,
            question_id=question_id,
            workflow_run_id=run_id,
        )
        if question_id and run_id
        else []
    )
    coverage = model_invocation_receipt_coverage(refs)
    refs_present = "modelInvocationReceiptTraceRefs" in record
    coverage_present = "modelInvocationReceiptCoverage" in record
    if (
        refs_present
        and record.get("modelInvocationReceiptTraceRefs") != refs
    ) or (
        coverage_present
        and record.get("modelInvocationReceiptCoverage") != coverage
    ):
        failed = model_invocation_receipt_coverage([])
        failed["integrityIssue"] = "stored_projection_mismatch"
        return [], failed
    return refs, coverage


def _apply_question_model_invocation_trace_projection(
    team_id: str,
    record: dict[str, Any],
) -> bool:
    refs_present = "modelInvocationReceiptTraceRefs" in record
    coverage_present = "modelInvocationReceiptCoverage" in record
    refs, coverage = _question_model_invocation_trace_projection(team_id, record)
    if coverage.get("integrityIssue") == "stored_projection_mismatch":
        raise ValueError(
            "challenge_question_run_receipt_trace_mismatch: immutable real "
            "invocation receipts changed."
        )
    changed = (
        record.get("teamId") != team_id
        or not refs_present
        or not coverage_present
        or record.get("modelInvocationReceiptTraceRefs") != refs
        or record.get("modelInvocationReceiptCoverage") != coverage
    )
    record["teamId"] = team_id
    record["modelInvocationReceiptTraceRefs"] = deepcopy(refs)
    record["modelInvocationReceiptCoverage"] = deepcopy(coverage)
    return changed


def _validated_model_invocation_receipt_refs(value: Any) -> dict[str, dict[str, Any]]:
    """Return canonical stored refs only when all stages and locator hashes verify."""

    if not isinstance(value, dict) or set(value) != set(MODEL_INVOCATION_RECEIPT_STAGES):
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for stage_id in MODEL_INVOCATION_RECEIPT_STAGES:
        item = value.get(stage_id)
        if not isinstance(item, dict):
            return {}
        receipt_id = str(item.get("receipt_id") or "").strip()
        node_run_id = str(item.get("node_run_id") or "").strip()
        locator = item.get("evidence_locator")
        locator_sha256 = str(item.get("evidence_locator_sha256") or "").strip().upper()
        if (
            not receipt_id
            or not node_run_id
            or not isinstance(locator, dict)
            or not locator
            or not re.fullmatch(r"[0-9A-F]{64}", locator_sha256)
        ):
            return {}
        try:
            expected_locator_sha256 = _receipt_locator_sha256(locator)
        except (TypeError, ValueError):
            return {}
        if locator_sha256 != expected_locator_sha256:
            return {}
        normalized[stage_id] = {
            "receipt_id": receipt_id,
            "node_run_id": node_run_id,
            "evidence_locator": deepcopy(locator),
            "evidence_locator_sha256": locator_sha256,
        }
    return normalized


def _apply_model_invocation_receipt_projection(
    record: dict[str, Any],
    expected_refs: dict[str, dict[str, Any]],
) -> bool:
    """Apply the derived projection and reject any conflicting persisted copy."""

    refs_field_present = "modelInvocationReceiptRefs" in record
    stored_refs = record.get("modelInvocationReceiptRefs")
    if refs_field_present:
        if expected_refs and (
            _validated_model_invocation_receipt_refs(stored_refs) != expected_refs
        ):
            raise ValueError(
                "challenge_question_run_receipt_mismatch: canonical package receipts "
                "do not match the index record."
            )
        if not expected_refs and stored_refs:
            raise ValueError(
                "challenge_question_run_receipt_mismatch: receipt refs exist without "
                "a canonical result package."
            )

    validation = (
        dict(record.get("validation"))
        if isinstance(record.get("validation"), dict)
        else {}
    )
    expected_status = "passed" if expected_refs else "failed"
    changed = (
        not refs_field_present
        or stored_refs != expected_refs
        or validation.get("modelInvocationReceipts") != expected_status
        or (
            bool(expected_refs)
            and "modelInvocationReceiptIssue" in validation
        )
        or (
            not expected_refs
            and validation.get("modelInvocationReceiptIssue")
            != "canonical_result_package_missing"
        )
    )
    record["modelInvocationReceiptRefs"] = deepcopy(expected_refs)
    validation["modelInvocationReceipts"] = expected_status
    if expected_refs:
        validation.pop("modelInvocationReceiptIssue", None)
    else:
        validation["modelInvocationReceiptIssue"] = (
            "canonical_result_package_missing"
        )
    record["validation"] = validation
    return changed


def _package_bound_model_invocation_receipt_refs(
    record: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Verify a stored projection against its immutable package before summary use."""

    package_metadata = record.get("resultPackage")
    if not isinstance(package_metadata, dict):
        return {}
    locator = str(package_metadata.get("locator") or "").strip()
    if not locator:
        return {}
    package_path = Path(locator)
    package_payload = _read_json(package_path)
    if not package_payload or not package_path.is_file():
        return {}
    try:
        from core.research.competition.question_result_package import (
            QuestionResultPackage,
        )
        from core.research.competition.result_set import CatalogScope

        restored_package = QuestionResultPackage.from_dict(
            package_payload,
            expected_model_policy_sha256=str(
                package_metadata.get("modelPolicySha256") or ""
            ),
        )
    except (TypeError, ValueError, KeyError):
        return {}
    if (
        package_metadata.get("schemaVersion") != restored_package.schema_version
        or str(package_metadata.get("packageId") or "") != restored_package.package_id
        or restored_package.canonical_hash
        != str(package_metadata.get("canonicalHash") or "")
        or restored_package.idempotency_key
        != str(package_metadata.get("idempotencyKey") or "")
        or restored_package.question_id
        != str(record.get("questionId") or "").strip().upper()
        or restored_package.run_id != str(record.get("runId") or "").strip()
        or restored_package.scope != CatalogScope.from_tracked_resources()
    ):
        return {}
    expected_refs = _model_invocation_receipt_refs_from_package(restored_package)
    if (
        _validated_model_invocation_receipt_refs(
            record.get("modelInvocationReceiptRefs")
        )
        != expected_refs
    ):
        return {}
    return expected_refs


def _summary_receipt_validation(
    record: dict[str, Any],
    receipt_refs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    validation = deepcopy(record.get("validation") or {})
    if isinstance(record.get("resultPackage"), dict):
        validation["modelInvocationReceipts"] = (
            "passed" if receipt_refs else "failed"
        )
        if receipt_refs:
            validation.pop("modelInvocationReceiptIssue", None)
        else:
            validation["modelInvocationReceiptIssue"] = (
                "canonical_result_package_receipt_mismatch"
            )
    else:
        validation["modelInvocationReceipts"] = "failed"
        validation["modelInvocationReceiptIssue"] = (
            "canonical_result_package_missing"
        )
    return validation


def challenge_question_run_summary(team_id: str) -> dict[str, Any]:
    records = _load_store(team_id).get("records")
    records = records if isinstance(records, list) else []
    valid_candidates = [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("schemaVersion") == 2
        and (record.get("validation") or {}).get("schemaValidation") == "passed"
        and (record.get("validation") or {}).get("citationValidation") == "passed"
        and (record.get("validation") or {}).get("officialModelCall") is True
    ]
    validated_candidates = [
        record
        for record in valid_candidates
        if (record.get("validation") or {}).get("semanticValidation") == "passed"
    ]
    receipt_refs_by_record_id: dict[str, dict[str, dict[str, Any]]] = {}
    trace_refs_by_record_id: dict[str, list[dict[str, Any]]] = {}
    trace_coverage_by_record_id: dict[str, dict[str, Any]] = {}
    receipt_ready_candidates: list[dict[str, Any]] = []
    for record in validated_candidates:
        receipt_refs = _package_bound_model_invocation_receipt_refs(record)
        record_id = str(record.get("recordId") or "")
        trace_refs, trace_coverage = _question_model_invocation_trace_projection(
            team_id, record
        )
        trace_refs_by_record_id[record_id] = trace_refs
        trace_coverage_by_record_id[record_id] = trace_coverage
        if receipt_refs:
            receipt_refs_by_record_id[record_id] = receipt_refs
        if receipt_refs and trace_coverage.get("status") == "passed":
            receipt_ready_candidates.append(record)
    completed = [
        record
        for record in valid_candidates
        if record.get("submissionEligible") is True
        and _all_human_gates_approved(record.get("humanGates"))
        and str(record.get("status") or "") == "approved"
        and str(record.get("recordId") or "") in receipt_refs_by_record_id
        and trace_coverage_by_record_id.get(
            str(record.get("recordId") or ""), {}
        ).get("status")
        == "passed"
    ]
    completed_question_ids = sorted({str(record.get("questionId") or "") for record in completed})
    completed_question_results = [
        {
            "questionId": str(record.get("questionId") or ""),
            "teamId": team_id,
            "runId": str(record.get("runId") or ""),
            "schemaVersion": record.get("schemaVersion"),
            "submissionEligible": record.get("submissionEligible") is True,
            "status": str(record.get("status") or ""),
            "validation": _summary_receipt_validation(
                record,
                receipt_refs_by_record_id.get(str(record.get("recordId") or ""), {}),
            ),
            "humanGates": deepcopy(record.get("humanGates") or {}),
            "outputSha256": str(record.get("outputSha256") or ""),
            "artifactPath": str(record.get("artifactPath") or ""),
            "modelInvocationReceiptRefs": deepcopy(
                receipt_refs_by_record_id.get(str(record.get("recordId") or ""), {})
            ),
            "modelInvocationReceiptTraceRefs": deepcopy(
                trace_refs_by_record_id.get(str(record.get("recordId") or ""), [])
            ),
            "modelInvocationReceiptCoverage": deepcopy(
                trace_coverage_by_record_id.get(str(record.get("recordId") or ""), {})
            ),
            "resultPackage": deepcopy(record.get("resultPackage"))
            if isinstance(record.get("resultPackage"), dict)
            else None,
        }
        for record in completed
    ]
    latest_validated_by_question: dict[str, dict[str, Any]] = {}
    for record in validated_candidates:
        question_id = str(record.get("questionId") or "")
        if question_id:
            latest_validated_by_question[question_id] = record
    validated_question_ids = sorted(latest_validated_by_question)
    validated_outcome_counts: dict[str, int] = {}
    for record in latest_validated_by_question.values():
        status = str(record.get("status") or "unknown")
        validated_outcome_counts[status] = validated_outcome_counts.get(status, 0) + 1
    validated_question_results = [
        {
            "questionId": question_id,
            "teamId": team_id,
            "runId": str(record.get("runId") or ""),
            "status": str(record.get("status") or ""),
            "validation": _summary_receipt_validation(
                record,
                receipt_refs_by_record_id.get(str(record.get("recordId") or ""), {}),
            ),
            "humanGates": deepcopy(record.get("humanGates") or {}),
            "outputSha256": str(record.get("outputSha256") or ""),
            "artifactPath": str(record.get("artifactPath") or ""),
            "modelInvocationReceiptRefs": deepcopy(
                receipt_refs_by_record_id.get(str(record.get("recordId") or ""), {})
            ),
            "modelInvocationReceiptTraceRefs": deepcopy(
                trace_refs_by_record_id.get(str(record.get("recordId") or ""), [])
            ),
            "modelInvocationReceiptCoverage": deepcopy(
                trace_coverage_by_record_id.get(str(record.get("recordId") or ""), {})
            ),
            "resultPackage": deepcopy(record.get("resultPackage"))
            if isinstance(record.get("resultPackage"), dict)
            else None,
        }
        for question_id, record in sorted(latest_validated_by_question.items())
    ]
    deep_question_ids = _required_deep_experiment_question_ids()
    approved_deep_experiment_question_ids = [
        question_id for question_id in completed_question_ids if question_id in deep_question_ids
    ]
    receipt_ready_question_ids = sorted(
        {
            str(record.get("questionId") or "")
            for record in receipt_ready_candidates
            if str(record.get("questionId") or "")
        }
    )
    latest_candidate = deepcopy(valid_candidates[-1]) if valid_candidates else None
    if latest_candidate is not None:
        latest_receipt_refs = receipt_refs_by_record_id.get(
            str(latest_candidate.get("recordId") or ""), {}
        )
        latest_candidate["modelInvocationReceiptRefs"] = deepcopy(
            latest_receipt_refs
        )
        latest_record_id = str(latest_candidate.get("recordId") or "")
        latest_candidate["teamId"] = team_id
        latest_candidate["modelInvocationReceiptTraceRefs"] = deepcopy(
            trace_refs_by_record_id.get(latest_record_id, [])
        )
        latest_candidate["modelInvocationReceiptCoverage"] = deepcopy(
            trace_coverage_by_record_id.get(latest_record_id, {})
        )
        latest_candidate["validation"] = _summary_receipt_validation(
            latest_candidate, latest_receipt_refs
        )
    return {
        "recordCount": len(records),
        "validCandidateCount": len(valid_candidates),
        "validatedQuestionCount": len(validated_question_ids),
        "validatedQuestionIds": validated_question_ids,
        "validatedOutcomeCounts": dict(sorted(validated_outcome_counts.items())),
        "validatedQuestionResults": validated_question_results,
        "receiptReadyQuestionCount": len(receipt_ready_question_ids),
        "receiptReadyQuestionIds": receipt_ready_question_ids,
        "completedCount": len(completed_question_ids),
        "completedQuestionIds": completed_question_ids,
        "completedQuestionResults": completed_question_results,
        # Deep experiments share the per-question submission gate; the explicit
        # list exists so the program projection can confirm them independently.
        "approvedDeepExperimentQuestionIds": approved_deep_experiment_question_ids,
        "latestCandidate": latest_candidate,
    }


def get_challenge_question_run_status(team_id: str) -> dict[str, Any]:
    team_service.assert_team_exists(team_id)
    return {
        "teamId": team_id,
        "summary": challenge_question_run_summary(team_id),
        "storePath": str(_store_path(team_id)),
    }


def get_challenge_question_run_detail(
    team_id: str,
    question_id: str,
    *,
    run_id: str = "",
) -> dict[str, Any]:
    """Return one immutable Challenge Program question artifact without project fallback."""

    team_service.get_team(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    normalized_run_id = str(run_id or "").strip()
    if _catalog_question(normalized_question_id) is None:
        raise ValueError("challenge_question_run_not_found: question is not present in the official catalog.")

    records = _load_store(team_id).get("records")
    question_records = [
        deepcopy(record)
        for record in (records if isinstance(records, list) else [])
        if isinstance(record, dict)
        and str(record.get("questionId") or "").strip().upper() == normalized_question_id
    ]
    if not question_records:
        raise ValueError("challenge_question_run_not_found: no registered output exists for this question.")

    selected_record = next(
        (
            record
            for record in reversed(question_records)
            if not normalized_run_id or str(record.get("runId") or "") == normalized_run_id
        ),
        None,
    )
    if selected_record is None:
        raise ValueError("challenge_question_run_not_found: requested run was not registered for this question.")

    selected_run_id = str(selected_record.get("runId") or "").strip()
    output = _read_json(_artifact_path(team_id, normalized_question_id, selected_run_id))
    expected_sha256 = str(selected_record.get("outputSha256") or "")
    if (
        not output
        or _output_question_id(output).upper() != normalized_question_id
        or str((output.get("run") or {}).get("run_id") or "").strip() != selected_run_id
        or _output_sha256(output) != expected_sha256
    ):
        raise ValueError(
            "challenge_question_run_artifact_mismatch: immutable artifact does not match its index record."
        )

    result_package = None
    result_package_artifact = None
    package_metadata = selected_record.get("resultPackage")
    if isinstance(package_metadata, dict):
        package_path = Path(str(package_metadata.get("locator") or ""))
        package_payload = _read_json(package_path)
        try:
            from core.research.competition.question_result_package import (
                QuestionResultPackage,
            )

            restored_package = QuestionResultPackage.from_dict(
                package_payload,
                expected_model_policy_sha256=str(
                    package_metadata.get("modelPolicySha256") or ""
                ),
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(
                "challenge_question_run_package_mismatch: canonical package is invalid."
            ) from exc
        if (
            restored_package.canonical_hash
            != str(package_metadata.get("canonicalHash") or "")
            or restored_package.idempotency_key
            != str(package_metadata.get("idempotencyKey") or "")
            or not package_path.exists()
        ):
            raise ValueError(
                "challenge_question_run_package_mismatch: canonical package does not match its index record."
            )
        result_package = package_payload
        expected_receipt_refs = _model_invocation_receipt_refs_from_package(
            restored_package
        )
        _apply_model_invocation_receipt_projection(
            selected_record, expected_receipt_refs
        )
        result_package_artifact = {
            "path": str(package_path),
            "canonicalHash": restored_package.canonical_hash,
            "idempotencyKey": restored_package.idempotency_key,
            "immutable": True,
        }
    else:
        _apply_model_invocation_receipt_projection(selected_record, {})

    _apply_question_model_invocation_trace_projection(team_id, selected_record)

    return {
        "teamId": team_id,
        "questionId": normalized_question_id,
        "selectedRunId": selected_run_id,
        "record": selected_record,
        "output": output,
        "runs": question_records,
        "artifact": {
            "path": str(_artifact_path(team_id, normalized_question_id, selected_run_id)),
            "sha256": expected_sha256,
            "immutable": True,
        },
        "resultPackage": result_package,
        "resultPackageArtifact": result_package_artifact,
    }


def register_challenge_question_output(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    team_service.get_team(team_id)
    raw_output = payload.get("output")
    if not isinstance(raw_output, dict):
        raise TypeError("output must be an object.")
    output = deepcopy(raw_output)
    # Artifact filesystem paths are built from client-supplied ids; reject
    # anything path-shaped (Windows backslashes, "..", separators) before
    # any other processing — it is a store-escape write primitive.
    from core.web.services.team_workflow.storage_ids import validate_artifact_component

    _early_run = output.get("run") if isinstance(output.get("run"), dict) else {}
    _early_question_id = _output_question_id(output)
    _early_run_id = str(_early_run.get("run_id") or "").strip()
    if _early_question_id:
        validate_artifact_component(_early_question_id, field="output.identity.question_id")
    if _early_run_id:
        validate_artifact_component(_early_run_id, field="output.run.run_id")
    _require_writable_schema(output)
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
    question_id = _output_question_id(output)
    run_id = str(run.get("run_id") or "").strip()
    if not question_id or not run_id:
        raise ValueError("output.identity.question_id and output.run.run_id are required.")
    source_result_package_hash = _source_result_package_hash(payload)
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
        issues.append({"path": "identity.question_id", "message": "Question id is not present in the official catalog."})
    elif str(catalog_question.get("question_en") or "") != _output_question_en(output):
        issues.append({"path": "identity.question_en", "message": "Question text does not match the official catalog."})
    issues.extend(semantic["issues"])
    audit["schema_validation"] = "passed" if not issues else "failed"
    output_hash = _output_sha256(output)
    audit["output_sha256"] = output_hash

    canonical_package = None
    package_metadata: dict[str, Any] | None = None
    package_input = payload.get("resultPackage")
    package_mode = isinstance(package_input, dict) or any(
        key in payload
        for key in (
            "packageReceipts",
            "modelInvocationReceipts",
            "modelPolicy",
            "authorizedModelPolicySha256",
        )
    )
    if package_mode:
        if not isinstance(package_input, dict):
            package_input = {}
        evidence_store = _official_model_evidence_store(team_id)
        explicit_receipts = payload.get("packageReceipts")
        if explicit_receipts is None:
            explicit_receipts = payload.get("modelInvocationReceipts")
        receipts = (
            explicit_receipts
            if explicit_receipts is not None
            else (evidence_store["receipts"] if evidence_store["receipts"] else None)
        )
        model_policy = payload.get("modelPolicy")
        if not isinstance(model_policy, dict):
            model_policy = package_input.get("modelPolicy") or package_input.get("model_policy")
        authorized_policy_sha256 = (
            payload.get("authorizedModelPolicySha256")
            or payload.get("expectedModelPolicySha256")
            or package_input.get("authorizedModelPolicySha256")
            or package_input.get("expectedModelPolicySha256")
        )
        if not str(authorized_policy_sha256 or "").strip():
            raise ValueError(
                "challenge_question_result_package_policy_authorization_missing: "
                "authorized model policy hash is required."
            )
        from core.research.competition.result_set import CatalogScope
        from core.web.services.team_workflow.question_result_package_adapter import (
            adapt_question_result_package,
        )

        canonical_package = adapt_question_result_package(
            raw_output,
            catalog_scope=CatalogScope.from_tracked_resources(),
            run_binding={"questionId": question_id, "runId": run_id},
            authorized_model_policy_sha256=str(authorized_policy_sha256),
            result_package=package_input,
            model_policy=model_policy if isinstance(model_policy, dict) else None,
            model_invocation_receipts=receipts,
            official_model_evidence=evidence_store,
            input_snapshot_sha256=str(
                payload.get("inputSnapshotSha256")
                or payload.get("input_snapshot_sha256")
                or ""
            ),
            package_id=str(payload.get("packageId") or ""),
            request_identity=payload,
            canonical_turn_resolver=_canonical_turn_binding_for_evidence,
        )
        package_path = _result_package_artifact_path(team_id, question_id, run_id)
        package_metadata = {
            "schemaVersion": canonical_package.schema_version,
            "packageId": canonical_package.package_id,
            "canonicalHash": canonical_package.canonical_hash,
            "idempotencyKey": canonical_package.idempotency_key,
            "modelPolicySha256": canonical_package.model_policy["policySha256"],
            "locator": str(package_path),
        }
    model_invocation_receipt_refs = (
        _model_invocation_receipt_refs_from_package(canonical_package)
        if canonical_package is not None
        else {}
    )
    if model_invocation_receipt_refs:
        receipt_evidence_refs = {
            str(item["evidence_locator"].get("evidenceId") or "").strip()
            for item in model_invocation_receipt_refs.values()
            if isinstance(item.get("evidence_locator"), dict)
        }
        matched_evidence_refs = sorted(
            set(matched_evidence_refs)
            | {item for item in receipt_evidence_refs if item}
        )
        official_call = _official_call_from_canonical_package(
            model_policy=canonical_package.model_policy,
            model_provider=model_provider,
            model_ref=run.get("model_id"),
            receipt_refs=model_invocation_receipt_refs,
        )

    record = {
        "recordId": f"{question_id}:{run_id}",
        "questionId": question_id,
        "runId": run_id,
        "schemaVersion": _output_schema_version(output),
        "submissionEligible": bool((output.get("submission") or {}).get("eligible")),
        "status": _output_status(output),
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
    _apply_model_invocation_receipt_projection(
        record, model_invocation_receipt_refs
    )
    _apply_question_model_invocation_trace_projection(team_id, record)
    if package_metadata is not None:
        record["resultPackage"] = package_metadata
    if source_result_package_hash:
        record["sourceResultPackageHash"] = source_result_package_hash
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
            existing_package_metadata = existing_record.get("resultPackage")
            if existing_package_metadata is not None and package_metadata is None:
                raise ValueError(
                    "Existing challenge question run is bound to a canonical result "
                    "package; idempotent replay must include the same package."
                )
            existing_source_result_package_hash = str(
                existing_record.get("sourceResultPackageHash") or ""
            ).strip().lower()
            if source_result_package_hash and (
                not existing_source_result_package_hash
                or existing_source_result_package_hash != source_result_package_hash
            ):
                raise ValueError(
                    "Existing challenge question run does not match the immutable "
                    "source result package binding."
                )
            if package_metadata is not None:
                if not isinstance(existing_package_metadata, dict):
                    raise ValueError(
                        "Challenge question run already exists without a canonical result package."
                    )
                existing_package_path = Path(str(existing_package_metadata.get("locator") or ""))
                existing_package = _read_json(existing_package_path)
                try:
                    from core.research.competition.question_result_package import (
                        QuestionResultPackage,
                    )

                    restored_package = QuestionResultPackage.from_dict(
                        existing_package,
                        expected_model_policy_sha256=str(
                            existing_package_metadata.get("modelPolicySha256") or ""
                        ),
                    )
                except (TypeError, ValueError, KeyError) as exc:
                    raise ValueError(
                        "Existing challenge question result package artifact is invalid."
                    ) from exc
                if (
                    not existing_package
                    or restored_package.canonical_hash
                    != str(existing_package_metadata.get("canonicalHash") or "")
                    or restored_package.idempotency_key
                    != str(existing_package_metadata.get("idempotencyKey") or "")
                    or str(existing_package_metadata.get("canonicalHash") or "")
                    != canonical_package.canonical_hash
                    or str(existing_package_metadata.get("idempotencyKey") or "")
                    != canonical_package.idempotency_key
                ):
                    raise ValueError(
                        "Existing challenge question result package does not match the immutable index record."
                    )
                if not existing_package_path.exists():
                    raise ValueError(
                        "Existing challenge question result package artifact is missing."
                    )
            if (
                existing_record.get("outputSha256") == output_hash
                and existing_record.get("lineage") == record.get("lineage")
                and (
                    package_metadata is None
                    or existing_package_metadata == package_metadata
                )
                and (
                    not source_result_package_hash
                    or existing_source_result_package_hash == source_result_package_hash
                )
            ):
                projection_changed = _apply_model_invocation_receipt_projection(
                    existing_record, model_invocation_receipt_refs
                )
                projection_changed = (
                    _apply_question_model_invocation_trace_projection(
                        team_id, existing_record
                    )
                    or projection_changed
                )
                if projection_changed:
                    store["updatedAt"] = _utc_now()
                    _write_json(_store_path(team_id), store)
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
        writes = [(_artifact_path(team_id, question_id, run_id), output)]
        if canonical_package is not None:
            writes.append(
                (
                    _result_package_artifact_path(team_id, question_id, run_id),
                    canonical_package.to_dict(),
                )
            )
        records.append(record)
        store["records"] = records
        store["updatedAt"] = _utc_now()
        writes.append((_store_path(team_id), store))
        _write_json_bundle(writes)
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
            "sourceResultPackageHash": source_result_package_hash,
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
    _require_writable_schema(output)
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
    human_review_status = (
        "passed"
        if h4_decision == "approved"
        else "revision_requested"
        if h4_decision == "revision_requested"
        else "rejected"
    )
    output["audit"]["human_review_status"] = human_review_status
    output.setdefault("review", {}).update(
        {
            "human_review_status": human_review_status,
            "reviewer": reviewer,
            "decided_at": decided_at,
            "rationale": rationale,
        }
    )
    submission = output.setdefault("submission", {})
    submission.update(
        {
            "eligible": all_approved,
            "projection_version": "1.0-review.1",
            "blockers": [] if all_approved else ["human_review_not_approved"],
        }
    )
    _set_output_status(output, "approved" if all_approved else "needs_revision")
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
        record["status"] = _output_status(output)
        record["submissionEligible"] = bool(submission.get("eligible"))
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
            "status": _output_status(output),
        },
        lifecycle=True,
    )
    return {"record": deepcopy(record), "output": output, "summary": summary}
