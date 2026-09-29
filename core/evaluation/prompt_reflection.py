"""GEPA-style prompt reflection over supervised evolution failures.

Domain layer, pure logic only (no I/O, no LLM calls):

- :func:`collect_reflection_samples` turns a stored supervised decision
  payload (see ``supervised_workbench._load_decision_payload``) into a
  bounded list of failure samples worth reflecting on. A sample is the
  per-case decision summary plus the fields a reflection LLM needs to
  produce a "natural-language gradient" against the target prompt.
- :func:`pareto_nondominated` keeps the Pareto front of prompt-reflection
  proposals over multiple metrics (e.g. sample success rate, cost, latency)
  so the proposal pool holds non-dominated candidates instead of a single
  leaderboard winner (GEPA's candidate pool rule).
- :func:`reflection_proposal_payload` assembles the proposal record written
  into the existing supervised proposals directory; records carry
  ``kind == "prompt_reflection"`` and start in the standard initial state so
  the existing review/approval flow governs them like any other proposal.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Mapping, Sequence

REFLECTION_PROPOSAL_KIND = "prompt_reflection"
REFLECTION_PROPOSAL_INITIAL_STATUS = "observing"
DEFAULT_MAX_REFLECTION_SAMPLES = 8


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _is_failure_status(status: str) -> bool:
    normalized = status.strip().lower()
    return normalized in {"failed", "error", "timeout", "incorrect", "rejected", "blocked"} or normalized.startswith("fail")


def collect_reflection_samples(
    decision_payload: Mapping[str, Any],
    *,
    max_samples: int = DEFAULT_MAX_REFLECTION_SAMPLES,
) -> List[Dict[str, Any]]:
    """Select the failure cases a reflection pass should focus on.

    Deterministic: input order is preserved, no randomness, no clock. A case
    enters the sample when either side failed; candidate-side failures come
    first (the reflection targets the candidate prompt), baseline-only
    failures follow.
    """

    limit = max(1, int(max_samples))
    candidate_failures: List[Dict[str, Any]] = []
    baseline_failures: List[Dict[str, Any]] = []
    for raw in decision_payload.get("case_summaries") or []:
        if not isinstance(raw, Mapping):
            continue
        sample = {
            "case_id": _text(raw.get("case_id")),
            "case_type": _text(raw.get("case_type")),
            "baseline_status": _text(raw.get("baseline_status")),
            "candidate_status": _text(raw.get("candidate_status")),
            "baseline_reason": _text(raw.get("baseline_reason")),
            "candidate_reason": _text(raw.get("candidate_reason")),
            "decision_signal": _text(raw.get("decision_signal")),
            "difference_summary": _text(raw.get("difference_summary")),
            "difference_reasons": [
                _text(item) for item in (raw.get("difference_reasons") or []) if _text(item)
            ],
            "failure_taxonomy": [
                _text(item) for item in (raw.get("failure_taxonomy") or []) if _text(item)
            ],
            "score_breakdown": dict(raw.get("score_breakdown") or {}),
        }
        if not sample["case_id"]:
            continue
        candidate_failed = _is_failure_status(sample["candidate_status"])
        baseline_failed = _is_failure_status(sample["baseline_status"])
        if candidate_failed:
            candidate_failures.append(sample)
        elif baseline_failed:
            baseline_failures.append(sample)
    ordered = [*candidate_failures, *baseline_failures]
    return ordered[:limit]


def pareto_nondominated(
    candidates: Sequence[Mapping[str, Any]],
    metrics: Sequence[str],
    *,
    maximize: Sequence[str] = (),
) -> List[Dict[str, Any]]:
    """Return the Pareto front over ``metrics`` (ties keep both).

    ``maximize`` lists metrics where larger is better (default: smaller is
    better). Deterministic: output preserves input order; domination requires
    being at least equal everywhere and strictly better somewhere.
    """

    metric_list = [str(m) for m in metrics if str(m)]
    if not metric_list or len(candidates) <= 1:
        return [dict(item) for item in candidates]

    def metric_values(item: Mapping[str, Any]) -> List[float]:
        values: List[float] = []
        for metric in metric_list:
            raw = item.get(metric)
            try:
                values.append(float(raw))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                values.append(float("inf"))
        return values

    higher_is_better = [metric in set(maximize) for metric in metric_list]

    def dominates(left: List[float], right: List[float]) -> bool:
        at_least_equal = True
        strictly_better = False
        for lv, rv, higher in zip(left, right, higher_is_better):
            if higher:
                if lv < rv:
                    at_least_equal = False
                    break
                if lv > rv:
                    strictly_better = True
            else:
                if lv > rv:
                    at_least_equal = False
                    break
                if lv < rv:
                    strictly_better = True
        return at_least_equal and strictly_better

    items = [(dict(item), metric_values(item)) for item in candidates]
    front: List[Dict[str, Any]] = []
    for item, values in items:
        if any(dominates(other_values, values) for _, other_values in items if other_values is not values):
            continue
        front.append(item)
    return front


def reflection_proposal_id(*, session_id: str, target_prompt_template_id: str) -> str:
    digest = hashlib.sha1(
        f"{session_id}|{target_prompt_template_id}|prompt_reflection".encode("utf-8")
    ).hexdigest()[:12]
    return f"prompt-reflection-{digest}"


def reflection_proposal_payload(
    *,
    proposal_id: str,
    session_id: str,
    bundle_name: str,
    target: Mapping[str, Any],
    critique: str,
    suggested_prompt_delta: str,
    sample_case_ids: Sequence[str],
    metrics: Mapping[str, Any],
    generated_at: str,
    model_ref: str = "",
) -> Dict[str, Any]:
    """Assemble a prompt-reflection proposal record (proposals-dir schema)."""

    return {
        "proposal_id": proposal_id,
        "session_id": _text(session_id),
        "bundle_name": _text(bundle_name),
        "kind": REFLECTION_PROPOSAL_KIND,
        "status": REFLECTION_PROPOSAL_INITIAL_STATUS,
        "target": dict(target or {}),
        "candidate_prompt": "",
        "reflection": {
            "critique": _text(critique),
            "suggestedPromptDelta": _text(suggested_prompt_delta),
            "sampleCaseIds": [ _text(item) for item in sample_case_ids if _text(item) ],
            "metrics": dict(metrics or {}),
            "modelRef": _text(model_ref),
            "generatedAt": _text(generated_at),
        },
        "observation_count": 1,
        "created_at": _text(generated_at),
    }
