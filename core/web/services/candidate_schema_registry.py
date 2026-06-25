"""Candidate Schema Registry —— PRD T-01 的薄外壳（不重做现有校验）。

设计原则（与 PRD「增量建设、复用底座」一致）：
- 逐类型的深层校验仍由 ``team_workflow_orchestration_service`` 的
  ``validate_candidate_record`` / ``validate_local_research_model_output`` 承担。
- 本模块只提供三件事：①统一的 ``UniversalCandidateEnvelope`` 形态与 envelope 级校验；
  ②声明式 ``schemas/*.schema.json`` 索引（供 prd:validate 检索）；③候选类型与
  local-research 任务输出契约的单一声明源。
- 本模块**刻意不 import 业务服务**，以避免循环依赖；它持有的常量与服务常量的一致性
  由 ``tests/test_candidate_schema_registry.py`` 的防漂移测试锁定。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_REGISTRY_VERSION = "2026-06-25.v1"

# repo_root/schemas（core/web/services/<this> → parents[3] = repo root）
SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas"

# 候选类型（须与 team_workflow_orchestration_service.CANDIDATE_TYPES 一致；drift 测试锁定）。
CANDIDATE_TYPES: tuple[str, ...] = (
    "source_manifest",
    "paper_note",
    "neuro_mechanism",
    "mechanism_mapping",
    "algorithm_hypothesis",
    "review_record",
    "candidate_graph",
)

# UniversalCandidateEnvelope 的 envelope 级必填字段。
ENVELOPE_REQUIRED_FIELDS: tuple[str, ...] = (
    "candidateId",
    "candidateType",
    "teamId",
    "schemaVersion",
    "currentState",
)

# local-research-model 通用输出字段（须与 service.LOCAL_RESEARCH_OUTPUT_FIELDS 一致）。
_LOCAL_RESEARCH_OUTPUT_FIELDS: tuple[str, ...] = (
    "candidateType",
    "sourceRefs",
    "evidenceRefs",
    "claims",
    "uncertainty",
    "riskFlags",
    "confidence",
    "nextAction",
    "requiresReview",
)

# 各 local-research 任务的 requiredOutput（须与 service.LOCAL_RESEARCH_TASKS 一致）。
RESEARCH_TASK_REQUIRED_OUTPUT: dict[str, tuple[str, ...]] = {
    "source_screening": (
        "candidateType",
        "sourceRefs",
        "evidenceRefs",
        "claims",
        "riskFlags",
        "confidence",
        "nextAction",
        "requiresReview",
    ),
    "paper_note_draft": (*_LOCAL_RESEARCH_OUTPUT_FIELDS, "keyFindings", "methods", "limitations", "citations"),
    "neuro_mechanism_extract": (
        *_LOCAL_RESEARCH_OUTPUT_FIELDS,
        "paperNoteIds",
        "description",
        "brainSystems",
        "cognitiveFunctions",
        "experimentalPhenomena",
        "authorInterpretation",
        "projectInterpretation",
    ),
    "mechanism_mapping": (
        *_LOCAL_RESEARCH_OUTPUT_FIELDS,
        "neuroMechanismIds",
        "computationalAbstraction",
        "factLayer",
        "inferenceLayer",
        "overAnalogyRisk",
        "engineeringImplication",
    ),
    "algorithm_hypothesis_draft": (
        *_LOCAL_RESEARCH_OUTPUT_FIELDS,
        "mechanismMappingIds",
        "hypothesis",
        "baseline",
        "expectedBenefit",
        "expectedComputeCost",
        "experimentPlan",
    ),
    "review_prefilter": (*_LOCAL_RESEARCH_OUTPUT_FIELDS, "candidateIds", "checklist", "comments", "requiredChanges", "needsDecision"),
    "steward_pack_draft": (
        *_LOCAL_RESEARCH_OUTPUT_FIELDS,
        "candidateIds",
        "targetDomain",
        "sourceTrace",
        "riskSummary",
        "proposalPayload",
        "ratingSuggestion",
        "approvalRequired",
    ),
}

# 任务类型 → 目标候选类型（须与 service.LOCAL_RESEARCH_TASKS[*].targetCandidateType 一致）。
RESEARCH_TASK_TARGET_TYPE: dict[str, str] = {
    "source_screening": "source_manifest",
    "paper_note_draft": "paper_note",
    "neuro_mechanism_extract": "neuro_mechanism",
    "mechanism_mapping": "mechanism_mapping",
    "algorithm_hypothesis_draft": "algorithm_hypothesis",
    "review_prefilter": "review_record",
    "steward_pack_draft": "review_record",
}


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def validate_envelope(candidate: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
    """Envelope 级校验：必填字段 + candidateType 合法性 + officialBoundary 形态。

    深层逐类型校验仍由服务层 ``validate_candidate_record`` 承担；这里只做统一最外层守卫。
    返回 ``{valid, issues, schemaRegistryVersion}``；``strict=True`` 且不通过时抛 ``ValueError``。
    """
    obj = candidate if isinstance(candidate, dict) else {}
    issues: list[dict[str, str]] = []
    for field in ENVELOPE_REQUIRED_FIELDS:
        if not _has_value(obj.get(field)):
            issues.append({"severity": "error", "code": "missing_field", "message": f"Missing required envelope field: {field}"})
    candidate_type = str(obj.get("candidateType") or "").strip()
    if candidate_type and candidate_type not in CANDIDATE_TYPES:
        issues.append({"severity": "error", "code": "invalid_candidate_type", "message": f"Unsupported candidateType: {candidate_type}"})
    official_boundary = obj.get("officialBoundary")
    if official_boundary is not None and not isinstance(official_boundary, dict):
        issues.append({"severity": "error", "code": "invalid_official_boundary", "message": "officialBoundary must be an object."})
    valid = not any(item["severity"] == "error" for item in issues)
    result = {"valid": valid, "issues": issues, "schemaRegistryVersion": SCHEMA_REGISTRY_VERSION}
    if strict and not valid:
        raise ValueError(f"Candidate envelope validation failed: {issues}")
    return result


def build_candidate_envelope(
    *,
    candidate_id: str,
    candidate_type: str,
    team_id: str,
    status: str,
    stage_round_id: str = "",
    source_trace: list[str] | None = None,
    created_by_agent: str = "",
    risk_flags: list[str] | None = None,
    requires_steward_approval: bool = True,
    payload: dict[str, Any] | None = None,
    schema_version: int = 1,
) -> dict[str, Any]:
    """构造统一的 UniversalCandidateEnvelope。officialBoundary 默认候选区、禁止 official 写入。"""
    return {
        "candidateId": candidate_id,
        "candidateType": candidate_type,
        "teamId": team_id,
        "status": status,
        "currentState": status,
        "stageRoundId": stage_round_id,
        "schemaVersion": schema_version,
        "sourceTrace": list(source_trace or []),
        "createdByAgent": created_by_agent,
        "riskFlags": list(risk_flags or []),
        "officialBoundary": {
            "candidateOnly": True,
            "officialWriteAllowed": False,
            "requiresStewardApproval": bool(requires_steward_approval),
        },
        "payload": payload or {},
    }


def candidate_schema_ids() -> list[str]:
    """供 prd:validate 检索的 schema 文件名清单。"""
    ids = ["universal_candidate_envelope.schema.json", "research_task_outputs.schema.json"]
    return ids


def load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _envelope_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "universal_candidate_envelope.schema.json",
        "title": "UniversalCandidateEnvelope",
        "description": "挑战杯科研候选统一信封；所有 Agent 写 CandidateStore 前的最外层契约。",
        "type": "object",
        "required": list(ENVELOPE_REQUIRED_FIELDS),
        "properties": {
            "candidateId": {"type": "string"},
            "candidateType": {"type": "string", "enum": list(CANDIDATE_TYPES)},
            "teamId": {"type": "string"},
            "schemaVersion": {"type": ["integer", "string"]},
            "currentState": {"type": "string"},
            "stageRoundId": {"type": "string"},
            "sourceTrace": {"type": "array", "items": {"type": "string"}},
            "createdByAgent": {"type": "string"},
            "riskFlags": {"type": "array", "items": {"type": "string"}},
            "officialBoundary": {
                "type": "object",
                "properties": {
                    "candidateOnly": {"type": "boolean"},
                    "officialWriteAllowed": {"type": "boolean"},
                    "requiresStewardApproval": {"type": "boolean"},
                },
            },
            "payload": {"type": "object"},
        },
    }


def _research_task_outputs_schema() -> dict[str, Any]:
    defs = {
        task: {
            "type": "object",
            "required": list(fields),
            "x-targetCandidateType": RESEARCH_TASK_TARGET_TYPE[task],
        }
        for task, fields in RESEARCH_TASK_REQUIRED_OUTPUT.items()
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "research_task_outputs.schema.json",
        "title": "ResearchTaskOutputs",
        "description": "local-research-model 各任务输出契约；与 service.LOCAL_RESEARCH_TASKS 同步。",
        "type": "object",
        "$defs": defs,
    }


def build_schema_files() -> list[str]:
    """把当前 registry 物化为 schemas/*.schema.json（生成式，单一声明源）。"""
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, payload in (
        ("universal_candidate_envelope.schema.json", _envelope_schema()),
        ("research_task_outputs.schema.json", _research_task_outputs_schema()),
    ):
        (SCHEMA_DIR / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(name)
    return written
