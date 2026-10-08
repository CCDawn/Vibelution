"""Local decision-model catalog.

Entries are System One endpoints, not chat models. The operator can store
several. Agent handoff uses only the one bound id, and only when that entry
is enabled. An empty binding does not guess.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from config.llm_security import is_llm_local_network_base_url

_SYSTEMONE_PATH = "/v1/systemone"
_MAX_ENTRIES = 24
_TIMEOUT_SECONDS = 20


@dataclass(frozen=True, slots=True)
class DecisionModelPreset:
    preset_id: str
    label: str
    model_id: str
    base_url: str
    note_zh: str
    note_en: str


DECISION_MODEL_PRESETS: tuple[DecisionModelPreset, ...] = (
    DecisionModelPreset(
        "d1-3b",
        "d1-3B",
        "LiquidAI/d1-3B",
        "http://127.0.0.1:8088/v1/systemone",
        "本机可跑的 3B 决策模型。LFM 许可，年收入低于 1000 万美元可商用。",
        "3B decision model that fits this machine. LFM license, free commercial use under $10M annual revenue.",
    ),
    DecisionModelPreset(
        "julia-1",
        "Julia-1",
        "ggml-org/Julia-1-GGUF",
        "http://127.0.0.1:8089/v1/systemone",
        "144M，Apache 2.0，约 50 种语言。",
        "144M, Apache 2.0, about 50 languages.",
    ),
    DecisionModelPreset(
        "laya",
        "Laya",
        "ggml-org/Laya-GGUF",
        "http://127.0.0.1:8090/v1/systemone",
        "421M，Apache 2.0，英语。",
        "421M, Apache 2.0, English.",
    ),
    DecisionModelPreset(
        "kev-4b",
        "Kev-4B",
        "ggml-org/Kev-4B-GGUF",
        "http://127.0.0.1:8091/v1/systemone",
        "4B，Apache 2.0，Q4 约 3GB。",
        "4B, Apache 2.0, Q4 is about 3GB.",
    ),
    DecisionModelPreset(
        "lev",
        "lev",
        "ggml-org/lev-GGUF",
        "http://127.0.0.1:8092/v1/systemone",
        "4B，Apache 2.0。",
        "4B, Apache 2.0.",
    ),
    DecisionModelPreset(
        "openjev",
        "OpenJev",
        "ggml-org/OpenJev-GGUF",
        "http://127.0.0.1:8093/v1/systemone",
        "27B，本机显存放不下。CC BY-NC 4.0，只允许非商用。",
        "27B, does not fit this GPU. CC BY-NC 4.0, non-commercial only.",
    ),
)


def decision_model_preset_payloads() -> list[dict[str, str]]:
    return [
        {
            "presetId": item.preset_id,
            "label": item.label,
            "modelId": item.model_id,
            "baseUrl": item.base_url,
            "noteZh": item.note_zh,
            "noteEn": item.note_en,
        }
        for item in DECISION_MODEL_PRESETS
    ]


def normalize_decision_base_url(value: object) -> str:
    """Accept a local origin or a full System One URL."""

    raw = str(value or "").strip()
    if not raw or any(char.isspace() for char in raw):
        raise ValueError("decision model base_url must be a local /v1/systemone URL")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("decision model base_url must be a local /v1/systemone URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("decision model base_url must be a local /v1/systemone URL")
    path = parsed.path or ""
    if path in {"", "/"}:
        path = _SYSTEMONE_PATH
    if path.rstrip("/") != _SYSTEMONE_PATH:
        raise ValueError("decision model base_url must end at /v1/systemone")
    port = f":{parsed.port}" if parsed.port else ""
    normalized = f"{parsed.scheme}://{parsed.hostname}{port}{path}"
    if not is_llm_local_network_base_url(normalized):
        raise ValueError("decision model base_url must be a local address")
    return normalized


def _clean_text(value: object, *, field_name: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"decision model {field_name} is required")
    if len(text) > limit:
        raise ValueError(f"decision model {field_name} is too long")
    return text


def _entry_id(value: object) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 64:
        raise ValueError("decision model id must be 1-64 letters, digits, or hyphens")
    if not text[0].isalnum() or any(
        (char != "-" and not char.isalnum()) or char.isupper() for char in text
    ):
        raise ValueError("decision model id must be 1-64 letters, digits, or hyphens")
    return text


def normalize_decision_entry(entry_id: object, raw: Mapping) -> dict[str, object]:
    try:
        probability = float(raw.get("min_probability", 0.80))
    except (TypeError, ValueError) as exc:
        raise ValueError("decision model min_probability must be between 0 and 1") from exc
    if not 0.0 < probability <= 1.0:
        raise ValueError("decision model min_probability must be between 0 and 1")
    note = str(raw.get("note") or "").strip()
    if len(note) > 240:
        raise ValueError("decision model note is too long")
    return {
        "label": _clean_text(raw.get("label"), field_name="label", limit=80),
        "model_id": _clean_text(raw.get("model_id"), field_name="model_id", limit=200),
        "base_url": normalize_decision_base_url(raw.get("base_url")),
        "min_probability": probability,
        "enabled": bool(raw.get("enabled", True)),
        "note": note,
    }


def validate_decision_catalog(models: Mapping, handoff_model_id: object) -> dict[str, dict[str, object]]:
    if not isinstance(models, Mapping):
        raise ValueError("llm.decision_models must be a table")
    if len(models) > _MAX_ENTRIES:
        raise ValueError("llm.decision_models accepts at most 24 entries")
    normalized: dict[str, dict[str, object]] = {}
    for key, raw in models.items():
        entry_id = _entry_id(key)
        if not isinstance(raw, Mapping):
            raise ValueError(f"llm.decision_models.{entry_id} must be a table")
        normalized[entry_id] = normalize_decision_entry(entry_id, raw)
    handoff = str(handoff_model_id or "").strip()
    if handoff:
        _entry_id(handoff)
        entry = normalized.get(handoff)
        if entry is None or not entry["enabled"]:
            raise ValueError("decision handoff must bind an enabled decision model")
    return normalized


class DecisionModelConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    model_id: str
    base_url: str
    min_probability: float = Field(default=0.80, gt=0.0, le=1.0)
    enabled: bool = True
    note: str = ""


def bound_decision_model(models: Mapping, handoff_model_id: object) -> dict[str, object] | None:
    """Return the one enabled bound entry. Missing or disabled bindings do not guess."""

    try:
        catalog = validate_decision_catalog(models, "")
    except ValueError:
        return None
    handoff = str(handoff_model_id or "").strip()
    if not handoff:
        return None
    entry = catalog.get(handoff)
    if entry is None or not entry["enabled"]:
        return None
    return {"id": handoff, **entry}


def post_systemone(url: str, body: Mapping, *, timeout: float = _TIMEOUT_SECONDS) -> dict | None:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def probe_decision_model(base_url: object, model_id: object) -> dict[str, object]:
    """Send one two-option choice. Connection failure stays a result, not a crash."""

    url = normalize_decision_base_url(base_url)
    model = _clean_text(model_id, field_name="model_id", limit=200)
    payload = post_systemone(
        url,
        {
            "model": model,
            "state": {
                "roundId": "probe",
                "inputHash": "probe",
                "feedback": "connectivity check",
                "evaluation": "none",
            },
            "questions": {
                "next": {
                    "type": "choice",
                    "instructions": "Choose one option.",
                    "criteria": {
                        "discuss": "Talk before changing the plan",
                        "stop": "Stop the loop",
                    },
                }
            },
        },
    )
    if payload is None:
        return {"ok": False, "baseUrl": url, "model": model, "error": "decision model did not answer"}
    answer = payload.get("answers")
    choice_body = answer.get("next") if isinstance(answer, dict) else None
    if not isinstance(choice_body, dict):
        return {"ok": False, "baseUrl": url, "model": model, "error": "decision model returned no choice"}
    choice = str(choice_body.get("choice") or "")
    probabilities = choice_body.get("probabilities")
    if choice not in {"discuss", "stop"} or not isinstance(probabilities, dict):
        return {"ok": False, "baseUrl": url, "model": model, "error": "decision model returned an illegal choice"}
    try:
        probability = float(probabilities.get(choice))
    except (TypeError, ValueError):
        return {"ok": False, "baseUrl": url, "model": model, "error": "decision model returned no probability"}
    return {
        "ok": True,
        "baseUrl": url,
        "model": model,
        "choice": choice,
        "probability": round(probability, 4),
    }
