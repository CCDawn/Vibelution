"""Hypothesis-level experiment checkpoint + resume projection.

Each experiment plan tracks one append-only progress record per selected
hypothesis (``plan['hypothesisProgress']``). Step states are *derived* from
existing ledger evidence (designGate, smoke/full-run results, outcome graph,
knowledge ingestion) so a refresh is idempotent: same evidence -> same
projection, and checkpoint events are only appended when a step actually
changes state. Legacy plans project progress in memory on load without
rewriting history.
"""

from __future__ import annotations

import hashlib
from typing import Any

from core.web.services.team_workflow.outcome_graph import (
    claim_id_for_hypothesis,
    current_edges,
)

HYPOTHESIS_PROGRESS_STEPS = ("design", "smoke", "full_run", "evaluation", "promotion")
_STEP_STATUSES = {"pending", "in_progress", "done", "failed"}
_MAX_CHECKPOINT_EVENTS = 64
_TERMINAL_RUN_STATUSES = {"passed", "failed"}
_PROMOTION_IN_PROGRESS_STATUSES = {
    "knowledge_steward_notified",
    "knowledge_steward_wake_pending",
}
_PROMOTION_FAILED_STATUSES = {"knowledge_steward_notification_failed"}


def refresh_hypothesis_progress(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Re-derive every selected hypothesis' checkpoint on ``plan`` (mutates plan)."""
    entries = _plan_hypothesis_entries(plan)
    stored = _stored_entries_by_key(plan)
    refreshed: list[dict[str, Any]] = []
    for entry in entries:
        key = _entry_key(entry)
        previous = stored.get(key)
        steps = _derive_steps(plan, entry)
        events = list(previous.get("checkpointEvents") or []) if previous else []
        previous_steps = (
            {str(item.get("step") or ""): item for item in list(previous.get("steps") or []) if isinstance(item, dict)}
            if previous
            else {}
        )
        for step in steps:
            prior_status = str((previous_steps.get(step["step"]) or {}).get("status") or "")
            if prior_status == step["status"]:
                # Keep the original checkpoint timestamp when nothing changed.
                prior_updated = str((previous_steps.get(step["step"]) or {}).get("updatedAt") or "")
                if prior_updated:
                    step["updatedAt"] = prior_updated
                continue
            event = _checkpoint_event(plan, key, step, from_status=prior_status)
            if all(str(item.get("eventId") or "") != event["eventId"] for item in events):
                events.append(event)
        refreshed.append(_finalize_entry(plan, entry, steps, events[-_MAX_CHECKPOINT_EVENTS:]))
    plan["hypothesisProgress"] = refreshed
    return refreshed


def hypothesis_progress_summary(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact per-hypothesis progress view embedded in status payloads."""
    if not isinstance(entry, dict):
        return None
    return {
        "candidateId": str(entry.get("candidateId") or ""),
        "claimId": str(entry.get("claimId") or ""),
        "planId": str(entry.get("planId") or ""),
        "status": str(entry.get("status") or "pending"),
        "currentStep": str(entry.get("currentStep") or ""),
        "nextStep": str(entry.get("nextStep") or ""),
        "completedCount": int(entry.get("completedCount") or 0),
        "totalSteps": int(entry.get("totalSteps") or len(HYPOTHESIS_PROGRESS_STEPS)),
        "evaluationOutcome": str(entry.get("evaluationOutcome") or ""),
        "updatedAt": str(entry.get("updatedAt") or ""),
    }


def progress_summary_by_candidate(plans: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Best (furthest-along) progress summary per candidate id across plans."""
    best: dict[str, dict[str, Any]] = {}
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        for entry in list(plan.get("hypothesisProgress") or []):
            if not isinstance(entry, dict):
                continue
            candidate_id = str(entry.get("candidateId") or "")
            if not candidate_id:
                continue
            summary = hypothesis_progress_summary(entry)
            if summary is None:
                continue
            existing = best.get(candidate_id)
            if existing is None or _summary_rank(summary) > _summary_rank(existing):
                best[candidate_id] = summary
    return best


def find_hypothesis_progress(
    plan: dict[str, Any],
    candidate_id: str,
) -> dict[str, Any] | None:
    for entry in list(plan.get("hypothesisProgress") or []):
        if isinstance(entry, dict) and str(entry.get("candidateId") or "") == candidate_id:
            return entry
    return None


def plan_tracks_hypothesis(plan: dict[str, Any], candidate_id: str) -> bool:
    if not candidate_id:
        return False
    if candidate_id in [str(item) for item in list(plan.get("hypothesisCandidateIds") or [])]:
        return True
    selection = plan.get("hypothesisSelection") if isinstance(plan.get("hypothesisSelection"), dict) else {}
    if str(selection.get("hypothesisCandidateId") or "") == candidate_id:
        return True
    for item in list(plan.get("selectedHypotheses") or []):
        if isinstance(item, dict) and str(item.get("candidateId") or "") == candidate_id:
            return True
    return False


def _summary_rank(summary: dict[str, Any]) -> tuple[int, str, str]:
    return (
        int(summary.get("completedCount") or 0),
        str(summary.get("updatedAt") or ""),
        str(summary.get("planId") or ""),
    )


def _plan_hypothesis_entries(plan: dict[str, Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in list(plan.get("selectedHypotheses") or []):
        if not isinstance(item, dict):
            continue
        candidate_id = _text(item.get("candidateId"), 160)
        hypothesis = _text(item.get("hypothesis"), 800)
        claim_id = claim_id_for_hypothesis(hypothesis)
        key = candidate_id or claim_id
        if not key or key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "candidateId": candidate_id,
                "claimId": claim_id,
                "hypothesis": _text(item.get("hypothesis"), 240) or _text(item.get("title"), 240),
            }
        )
    return entries


def _stored_entries_by_key(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stored: dict[str, dict[str, Any]] = {}
    for item in list(plan.get("hypothesisProgress") or []):
        if isinstance(item, dict):
            stored[_entry_key(item)] = item
    return stored


def _entry_key(entry: dict[str, Any]) -> str:
    return str(entry.get("candidateId") or "") or str(entry.get("claimId") or "")


def _derive_steps(plan: dict[str, Any], entry: dict[str, str]) -> list[dict[str, Any]]:
    design = _design_step(plan)
    smoke = _run_step(
        "smoke",
        _active_smoke_evidence(plan),
        id_keys=("smokeResultId", "smokeRunId"),
    )
    full_run = _run_step(
        "full_run",
        plan.get("activeFullRunResult") if isinstance(plan.get("activeFullRunResult"), dict) else None,
        id_keys=("fullRunResultId",),
    )
    evaluation = _evaluation_step(plan, entry, full_run)
    promotion = _promotion_step(plan, evaluation)
    return [design, smoke, full_run, evaluation, promotion]


def _design_step(plan: dict[str, Any]) -> dict[str, Any]:
    gate = plan.get("designGate") if isinstance(plan.get("designGate"), dict) else None
    refs = {"planId": str(plan.get("planId") or "")}
    if gate is not None:
        if str(gate.get("status") or "") == "frozen":
            return _step("design", "done", str(gate.get("frozenAt") or plan.get("updatedAt") or ""), refs)
        validation = plan.get("contractValidation") if isinstance(plan.get("contractValidation"), dict) else {}
        readiness = plan.get("readiness") if isinstance(plan.get("readiness"), dict) else {}
        if validation.get("valid") is True or readiness.get("readyForPlanReview") is True:
            return _step("design", "in_progress", str(plan.get("updatedAt") or plan.get("createdAt") or ""), refs)
        return _step("design", "pending", str(plan.get("createdAt") or ""), refs)
    # Legacy plans predate the explicit design gate: evidence of execution
    # implies the design was usable; otherwise the contract state decides.
    if _active_smoke_evidence(plan) is not None or isinstance(plan.get("activeFullRunResult"), dict):
        return _step("design", "done", str(plan.get("updatedAt") or plan.get("createdAt") or ""), refs)
    validation = plan.get("contractValidation") if isinstance(plan.get("contractValidation"), dict) else {}
    readiness = plan.get("readiness") if isinstance(plan.get("readiness"), dict) else {}
    if validation.get("valid") is True or readiness.get("readyForPlanReview") is True:
        return _step("design", "in_progress", str(plan.get("updatedAt") or plan.get("createdAt") or ""), refs)
    return _step("design", "pending", str(plan.get("createdAt") or ""), refs)


def _run_step(
    step_id: str,
    evidence: dict[str, Any] | None,
    *,
    id_keys: tuple[str, ...],
) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        return _step(step_id, "pending", "", {})
    status = str(evidence.get("status") or "").strip().lower()
    if status == "passed":
        step_status = "done"
    elif status == "failed":
        step_status = "failed"
    else:
        step_status = "in_progress"
    refs: dict[str, str] = {}
    for key in id_keys:
        value = _text(evidence.get(key), 160)
        if value:
            refs["resultId"] = value
            break
    result_path = _text(evidence.get("resultPath"), 500)
    if result_path:
        refs["resultPath"] = result_path
    return _step(
        step_id,
        step_status,
        str(evidence.get("recordedAt") or evidence.get("updatedAt") or ""),
        refs,
    )


def _evaluation_step(
    plan: dict[str, Any],
    entry: dict[str, str],
    full_run: dict[str, Any],
) -> dict[str, Any]:
    claim_id = str(entry.get("claimId") or "")
    # Evaluation is the *formal full-run* verdict: smoke runs also write
    # supports/falsifies edges, so only edges produced by the active full-run
    # result count here.
    full_run_result_id = str((full_run.get("refs") or {}).get("resultId") or "")
    if claim_id and full_run_result_id:
        for edge in current_edges(plan.get("outcomeGraph")):
            if str(edge.get("toId") or "") != claim_id:
                continue
            relation = str(edge.get("relation") or "")
            if relation not in {"supports", "falsifies"}:
                continue
            if str(edge.get("producedByEpisodeId") or "") != full_run_result_id:
                continue
            refs = {"claimId": claim_id, "relation": relation}
            return _step("evaluation", "done", str(edge.get("validFrom") or ""), {**refs, "resultId": full_run_result_id})
    # Legacy fallback: plans registered before the outcome graph still have a
    # terminal full-run verdict that *is* the evaluation.
    if full_run["status"] in {"done", "failed"}:
        relation = "supports" if full_run["status"] == "done" else "falsifies"
        refs = {"relation": relation}
        result_id = str((full_run.get("refs") or {}).get("resultId") or "")
        if result_id:
            refs["resultId"] = result_id
        return _step("evaluation", "done", str(full_run.get("updatedAt") or ""), refs)
    if full_run["status"] == "in_progress":
        return _step("evaluation", "in_progress", str(full_run.get("updatedAt") or ""), {})
    return _step("evaluation", "pending", "", {})


def _promotion_step(plan: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    ingestion = plan.get("knowledgeIngestion") if isinstance(plan.get("knowledgeIngestion"), dict) else None
    if ingestion is None:
        return _step("promotion", "pending", "", {})
    status = str(ingestion.get("status") or "").strip().lower()
    result = ingestion.get("result") if isinstance(ingestion.get("result"), dict) else {}
    refs: dict[str, str] = {}
    knowledge_item_id = _text(result.get("knowledgeItemId"), 160)
    if knowledge_item_id:
        refs["knowledgeItemId"] = knowledge_item_id
    pack = ingestion.get("experimentResultPack") if isinstance(ingestion.get("experimentResultPack"), dict) else {}
    pack_id = _text(pack.get("packId"), 160)
    if pack_id:
        refs["experimentResultPackId"] = pack_id
    updated_at = str(ingestion.get("updatedAt") or "")
    if status == "ingested":
        return _step("promotion", "done", updated_at, refs)
    if status in _PROMOTION_FAILED_STATUSES:
        return _step("promotion", "failed", updated_at, refs)
    if status in _PROMOTION_IN_PROGRESS_STATUSES or status:
        return _step("promotion", "in_progress", updated_at, refs)
    return _step("promotion", "pending", "", {})


def _finalize_entry(
    plan: dict[str, Any],
    entry: dict[str, str],
    steps: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    evaluation = next((item for item in steps if item["step"] == "evaluation"), {})
    evaluation_outcome = ""
    if evaluation.get("status") == "done":
        evaluation_outcome = str((evaluation.get("refs") or {}).get("relation") or "")
    completed = [item for item in steps if item["status"] == "done"]
    failed = next((item for item in steps if item["status"] == "failed"), None)
    in_progress = next((item for item in steps if item["status"] == "in_progress"), None)
    next_step = ""
    for item in steps:
        if item["status"] == "done":
            continue
        # A falsified hypothesis terminates at evaluation: there is nothing to promote.
        if item["step"] == "promotion" and evaluation_outcome == "falsifies":
            continue
        next_step = item["step"]
        break
    if failed is not None and next_step == failed["step"]:
        status = "failed"
    elif not next_step:
        status = "completed"
    elif in_progress is not None or completed:
        status = "in_progress"
    else:
        status = "pending"
    current_step = ""
    if in_progress is not None:
        current_step = in_progress["step"]
    elif failed is not None:
        current_step = failed["step"]
    elif completed:
        current_step = completed[-1]["step"]
    updated_at = max([str(item.get("updatedAt") or "") for item in steps] + [""])
    return {
        "candidateId": entry["candidateId"],
        "claimId": entry["claimId"],
        "hypothesis": entry["hypothesis"],
        "planId": str(plan.get("planId") or ""),
        "status": status,
        "currentStep": current_step,
        "nextStep": next_step,
        "completedCount": len(completed),
        "totalSteps": len(HYPOTHESIS_PROGRESS_STEPS),
        "evaluationOutcome": evaluation_outcome,
        "steps": steps,
        "checkpointEvents": events,
        "updatedAt": updated_at,
    }


def _checkpoint_event(
    plan: dict[str, Any],
    entry_key: str,
    step: dict[str, Any],
    *,
    from_status: str,
) -> dict[str, Any]:
    occurred_at = str(step.get("updatedAt") or plan.get("updatedAt") or "")
    digest = hashlib.sha256(
        f"{plan.get('planId') or ''}|{entry_key}|{step['step']}|{step['status']}|{occurred_at}".encode()
    ).hexdigest()[:12]
    return {
        "eventId": f"hcp-{digest}",
        "step": step["step"],
        "fromStatus": from_status,
        "toStatus": step["status"],
        "occurredAt": occurred_at,
        "source": "derived",
    }


def _active_smoke_evidence(plan: dict[str, Any]) -> dict[str, Any] | None:
    registered = plan.get("activeSmokeResult")
    if isinstance(registered, dict):
        return registered
    runner = plan.get("activeSmokeRun")
    return runner if isinstance(runner, dict) else None


def _step(step_id: str, status: str, updated_at: str, refs: dict[str, str]) -> dict[str, Any]:
    if status not in _STEP_STATUSES:
        status = "pending"
    return {
        "step": step_id,
        "status": status,
        "updatedAt": updated_at,
        "refs": dict(refs),
    }


def _text(value: Any, max_length: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_length]
