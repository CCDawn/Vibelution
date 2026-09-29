"""GEPA-style prompt reflection orchestration for supervised evolution.

Web-layer orchestration only (see evolution_services.md layering): reads one
stored supervised decision payload, lets the evaluator LLM reflect on the
failure samples (natural-language gradient against the candidate prompts),
and writes ``prompt_reflection`` proposals into the existing proposals
directory where the standard review/approval flow governs them. The
proposal pool is kept on its Pareto front over the recorded metrics.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from core.evaluation.prompt_reflection import (
    REFLECTION_PROPOSAL_KIND,
    collect_reflection_samples,
    pareto_nondominated,
    reflection_proposal_id,
    reflection_proposal_payload,
)
from core.evaluation.selection_policy import _proposals_dir, _safe_proposal_file_stem
from core.infrastructure.workspace_manager import get_workspace
from core.llm import LLMInvocationContext, get_llm_client, invoke_llm
from core.llm.agent_runtime import config_for_agent_llm_model
from core.logging import debug as _debug_logger
from config import get_config

REFLECTION_LLM_PROFILE_ID = "supervised_prompt_reflection"
PARETO_METRICS = ("sampleSuccessRate", "avgCostTokens", "avgLatencyMs")
PARETO_MAXIMIZE = ("sampleSuccessRate",)

REFLECTION_SYSTEM_PROMPT = (
    "你是监督进化的提示词反思器（GEPA 风格）。你会看到若干失败样本的决策摘要"
    "（含失败分类、基线/候选差异与得分）。请针对这些失败产出对候选提示词的"
    "『自然语言梯度』：先给出批判性分析，再给出可执行的提示词修改建议。"
    '只输出 JSON：{"critique": "...", "suggestedPromptDelta": "..."}，'
    "两个键都必须是非空字符串，中文，合计不超过 1200 字。"
)


class PromptReflectionError(ValueError):
    def __init__(self, message: str, *, code: str = "reflection_failed") -> None:
        super().__init__(message)
        self.code = code


def _project_root(project_root: Path | None) -> Path:
    if project_root is not None:
        return project_root.resolve()
    return get_workspace().project_root.resolve()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_decision_payload(decision_path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(Path(decision_path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise PromptReflectionError(f"decision payload unreadable: {exc}", code="decision_unreadable") from exc
    except json.JSONDecodeError as exc:
        raise PromptReflectionError(f"decision payload is not JSON: {exc}", code="decision_invalid") from exc
    if not isinstance(payload, dict):
        raise PromptReflectionError("decision payload must be a JSON object", code="decision_invalid")
    return payload


def _reflection_runtime_config(model_ref: str):
    return config_for_agent_llm_model(
        get_config(),
        model_id=model_ref,
        runtime_profile_id=REFLECTION_LLM_PROFILE_ID,
        slot="dialogue",
    )


def _invoke_reflection_llm(model_ref: str, samples: List[Dict[str, Any]]) -> Dict[str, str]:
    runtime_config = _reflection_runtime_config(model_ref)
    client = get_llm_client(profile_id=REFLECTION_LLM_PROFILE_ID, config=runtime_config)
    samples_text = json.dumps(samples, ensure_ascii=False, indent=1)
    response = invoke_llm(
        client,
        [
            {"role": "system", "content": REFLECTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"失败样本决策摘要：\n{samples_text}"},
        ],
        context=LLMInvocationContext(
            surface="supervised_prompt_reflection",
            run_kind="tool_assistant_task",
            agent_id="prompt_reflection_service",
            llm_slot="summary",
            model_id=model_ref,
            cache_scope="prompt_reflection",
            cache_partition=f"prompt-reflection-{model_ref}",
            prompt_purpose="supervised_prompt_reflection",
            conversation_bound=False,
        ),
        metadata={"feature": "supervised_prompt_reflection", "sampleCount": len(samples)},
    )
    content = str(getattr(response, "content", "") or "").strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise PromptReflectionError(
            f"reflection LLM did not return JSON: {content[:200]}", code="reflection_output_invalid"
        ) from exc
    if not isinstance(parsed, dict):
        raise PromptReflectionError("reflection output must be a JSON object", code="reflection_output_invalid")
    critique = str(parsed.get("critique") or "").strip()
    delta = str(parsed.get("suggestedPromptDelta") or "").strip()
    if not critique or not delta:
        raise PromptReflectionError(
            "reflection output missing critique/suggestedPromptDelta", code="reflection_output_invalid"
        )
    return {"critique": critique, "suggestedPromptDelta": delta}


def _load_reflection_pool(proposals_dir: Path) -> List[Dict[str, Any]]:
    pool: List[Dict[str, Any]] = []
    for path in sorted(proposals_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("kind") == REFLECTION_PROPOSAL_KIND:
            pool.append(payload)
    return pool


def generate_prompt_reflection_proposal(
    decision_path: str | Path,
    *,
    model_ref: str,
    project_root: Path | None = None,
    max_samples: int = 8,
) -> Dict[str, Any]:
    """Reflect on one decision's failures and write one prompt-reflection proposal."""

    root = _project_root(project_root)
    decision = _load_decision_payload(Path(decision_path))
    session_id = str(decision.get("session_id") or "").strip()
    bundle_name = str(decision.get("bundle_name") or "").strip()
    if not session_id:
        raise PromptReflectionError("decision payload has no session_id", code="decision_invalid")

    samples = collect_reflection_samples(decision, max_samples=max_samples)
    if not samples:
        raise PromptReflectionError(
            "decision has no failure samples to reflect on", code="no_failure_samples"
        )

    reflection = _invoke_reflection_llm(model_ref, samples)

    sample_success_rate = 0.0
    total_cost = 0.0
    total_latency = 0.0
    for sample in samples:
        breakdown = sample.get("score_breakdown") or {}
        try:
            sample_success_rate += float(breakdown.get("successRate") or 0.0)
            total_cost += float(breakdown.get("costTokens") or 0.0)
            total_latency += float(breakdown.get("latencyMs") or 0.0)
        except (TypeError, ValueError):
            continue
    metrics = {
        "sampleSuccessRate": round(sample_success_rate / len(samples), 4),
        "avgCostTokens": round(total_cost / len(samples), 2),
        "avgLatencyMs": round(total_latency / len(samples), 2),
    }

    proposal_id = reflection_proposal_id(
        session_id=session_id, target_prompt_template_id=bundle_name or "bundle"
    )
    proposal = reflection_proposal_payload(
        proposal_id=proposal_id,
        session_id=session_id,
        bundle_name=bundle_name,
        target={"bundleName": bundle_name, "caseTypes": sorted({s["case_type"] for s in samples if s["case_type"]})},
        critique=reflection["critique"],
        suggested_prompt_delta=reflection["suggestedPromptDelta"],
        sample_case_ids=[s["case_id"] for s in samples],
        metrics=metrics,
        generated_at=_utc_now_iso(),
        model_ref=model_ref,
    )

    proposals_dir = _proposals_dir(root)
    pool = _load_reflection_pool(proposals_dir)
    # Same-id records are version updates (the new proposal replaces the old
    # one); Pareto domination is judged between *different* proposals only.
    others = [item for item in pool if item.get("proposal_id") != proposal_id]

    # Pareto metrics live under reflection.metrics; flatten onto a scratch copy
    # so the domain filter can read them as plain top-level keys.
    def _with_flat_metrics(item: Dict[str, Any]) -> Dict[str, Any]:
        flattened = dict(item)
        flattened.update((item.get("reflection") or {}).get("metrics") or {})
        return flattened

    front = pareto_nondominated(
        [_with_flat_metrics(item) for item in [*others, proposal]],
        PARETO_METRICS,
        maximize=PARETO_MAXIMIZE,
    )
    front_ids = {item.get("proposal_id") for item in front}
    now = _utc_now_iso()
    if proposal.get("proposal_id") not in front_ids:
        raise PromptReflectionError(
            "generated proposal is dominated by the existing pool; nothing to add",
            code="proposal_dominated",
        )
    for item in others:
        item_id = item.get("proposal_id")
        path = proposals_dir / f"{_safe_proposal_file_stem(str(item_id))}.json"
        if item_id in front_ids:
            path.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        elif item.get("status") == "observing":
            item["status"] = "rejected"
            item["rejected_at"] = now
            item["rejection_reason"] = "pareto_dominated"
            path.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    proposal_path = proposals_dir / f"{_safe_proposal_file_stem(proposal_id)}.json"
    proposal_path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _debug_logger.info(
        f"[prompt_reflection] proposal {proposal_id} written ({len(samples)} samples, front={len(front_ids)})",
        tag="EVOLUTION",
    )
    return {
        "proposalId": proposal_id,
        "kind": REFLECTION_PROPOSAL_KIND,
        "sampleCount": len(samples),
        "metrics": metrics,
        "critique": reflection["critique"],
        "suggestedPromptDelta": reflection["suggestedPromptDelta"],
        "poolFrontSize": len(front_ids),
    }
