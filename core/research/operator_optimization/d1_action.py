"""Local decision-model choice for one operator iteration action.

The bound catalog entry picks among actions the server already marked
available. A missing binding, a missing server, a low probability, or an
illegal label returns None so the existing decision Agent still writes
the reason. An empty VIBELUTION_D1_SYSTEMONE_URL disables the call.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping

from config.decision_models import bound_decision_model, normalize_decision_base_url, post_systemone

_DEFAULT_MIN_PROBABILITY = 0.80
_ENV_MODEL_ID = "LiquidAI/d1-3B"
_STATE_LIMIT = 6000

_ACTION_CRITERIA = {
    "discuss": "Hold a discussion because the evidence is disputed or the next step needs alignment",
    "collect_knowledge": "Use or fetch source material without opening a discussion",
    "plan_candidate": "Plan the next experiment from the selected hypothesis and knowledge",
    "retest": "Run the already frozen plan again",
    "repair_baseline": "Repair the baseline implementation or the evaluation program",
    "stop": "Stop because the work is done or further changes are not worth running",
}


def decision_reason_name(model_id: str) -> str:
    """Short name stored on a local decision. d1 keeps its existing label."""

    text = str(model_id or "").strip()
    if text in {"", "LiquidAI/d1-3B"}:
        return "d1-3B"
    return text


def systemone_url() -> str:
    """Return an explicit env override. Missing means use the bound catalog entry."""

    if "VIBELUTION_D1_SYSTEMONE_URL" in os.environ:
        return os.environ["VIBELUTION_D1_SYSTEMONE_URL"].strip()
    return ""


def _load_bound_entry() -> dict | None:
    try:
        from config.settings import get_config

        llm = get_config().llm
    except Exception:
        return None
    raw_models = {
        key: value.model_dump() if hasattr(value, "model_dump") else value
        for key, value in dict(llm.decision_models or {}).items()
    }
    return bound_decision_model(raw_models, llm.decision_handoff_model_id)


def _runtime_target() -> tuple[str, str, float] | None:
    if "VIBELUTION_D1_SYSTEMONE_URL" in os.environ:
        raw_url = os.environ["VIBELUTION_D1_SYSTEMONE_URL"].strip()
        if not raw_url:
            return None
        try:
            url = normalize_decision_base_url(raw_url)
        except ValueError:
            return None
        model = os.environ.get("VIBELUTION_D1_MODEL_ID", "").strip() or _ENV_MODEL_ID
        return url, model, min_probability()
    bound = _load_bound_entry()
    if not bound:
        return None
    return str(bound["base_url"]), str(bound["model_id"]), float(bound["min_probability"])


def min_probability() -> float:
    raw = os.environ.get("VIBELUTION_D1_MIN_PROBABILITY", "").strip()
    if not raw:
        return _DEFAULT_MIN_PROBABILITY
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_MIN_PROBABILITY
    if not 0.0 < value <= 1.0:
        return _DEFAULT_MIN_PROBABILITY
    return value


def _clip(value: object) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(text) <= _STATE_LIMIT:
        return text
    return text[:_STATE_LIMIT]


def choose_iteration_action(inputs: Mapping) -> dict | None:
    """Ask the bound decision model for one legal action. None uses the decision Agent."""

    target = _runtime_target()
    if target is None:
        return None
    url, model_id, cutoff = target
    policy = inputs.get("actionPolicy")
    if not isinstance(policy, Mapping):
        return None
    available = [str(item) for item in policy.get("availableActions") or [] if str(item)]
    if len(available) < 2:
        return None
    criteria = {name: _ACTION_CRITERIA.get(name, name) for name in available}
    state = {
        "roundId": inputs.get("roundId"),
        "inputHash": inputs.get("inputHash"),
        "feedback": _clip(inputs.get("feedback")),
        "evaluation": _clip(inputs.get("evaluation")),
    }
    body = {
        "model": model_id,
        "state": state,
        "questions": {
            "next": {
                "type": "choice",
                "instructions": "Choose the single next research action. Use only these options.",
                "criteria": criteria,
            }
        },
    }
    payload = post_systemone(url, body)
    if payload is None:
        return None
    answers = payload.get("answers")
    answer = answers.get("next") if isinstance(answers, dict) else None
    if not isinstance(answer, dict):
        return None
    kind = str(answer.get("choice") or "")
    probabilities = answer.get("probabilities")
    if kind not in criteria or not isinstance(probabilities, dict):
        return None
    try:
        probability = float(probabilities.get(kind))
    except (TypeError, ValueError):
        return None
    if probability < cutoff:
        return None
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    try:
        input_tokens = int(usage.get("input_tokens") or 0)
    except (TypeError, ValueError):
        input_tokens = 0
    return {
        "kind": kind,
        "probability": round(probability, 4),
        "inputHash": str(inputs.get("inputHash") or ""),
        "model": model_id,
        "inputTokens": max(0, input_tokens),
    }
