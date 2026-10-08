"""Local Liquid d1-3B choice for one operator iteration action.

The model only picks among actions the server already marked available.
A missing server, a low probability, or an illegal label returns None so
the existing decision Agent still writes the reason.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping

_DEFAULT_URL = "http://127.0.0.1:8088/v1/systemone"
_DEFAULT_MIN_PROBABILITY = 0.80
_MODEL_ID = "LiquidAI/d1-3B"
_TIMEOUT_SECONDS = 20
_STATE_LIMIT = 6000

_ACTION_CRITERIA = {
    "discuss": "Hold a discussion because the evidence is disputed or the next step needs alignment",
    "collect_knowledge": "Use or fetch source material without opening a discussion",
    "plan_candidate": "Plan the next experiment from the selected hypothesis and knowledge",
    "retest": "Run the already frozen plan again",
    "repair_baseline": "Repair the baseline implementation or the evaluation program",
    "stop": "Stop because the work is done or further changes are not worth running",
}


def systemone_url() -> str:
    """Return the local endpoint. An empty env value disables the call."""

    if "VIBELUTION_D1_SYSTEMONE_URL" in os.environ:
        return os.environ["VIBELUTION_D1_SYSTEMONE_URL"].strip()
    return _DEFAULT_URL


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
    """Ask d1-3B for one legal action. None means use the decision Agent."""

    url = systemone_url()
    if not url:
        return None
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
        "model": _MODEL_ID,
        "state": state,
        "questions": {
            "next": {
                "type": "choice",
                "instructions": "Choose the single next research action. Use only these options.",
                "criteria": criteria,
            }
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeError, ValueError):
        return None
    if not isinstance(payload, dict):
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
    if probability < min_probability():
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
        "model": _MODEL_ID,
        "inputTokens": max(0, input_tokens),
    }
