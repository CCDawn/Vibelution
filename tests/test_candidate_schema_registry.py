"""Candidate Schema Registry 测试：防漂移锚点 + envelope 校验 + 声明式 schema。

防漂移：registry 是声明式外壳，但其候选类型与 local-research 任务输出契约必须与
team_workflow_orchestration_service 的运行期常量保持一致；任一侧改动而另一侧未同步时，
本测试失败，从而避免「schema 与代码脱节」（PRD 风险 R7）。
"""

from __future__ import annotations

import json

from core.web.services import candidate_schema_registry as registry
from core.web.services import team_workflow_orchestration_service as service


def test_candidate_types_match_service():
    assert set(registry.CANDIDATE_TYPES) == set(service.CANDIDATE_TYPES)


def test_research_task_outputs_match_service():
    assert set(registry.RESEARCH_TASK_REQUIRED_OUTPUT) == set(service.LOCAL_RESEARCH_TASKS)
    for task, fields in registry.RESEARCH_TASK_REQUIRED_OUTPUT.items():
        assert tuple(service.LOCAL_RESEARCH_TASKS[task]["requiredOutput"]) == fields, task


def test_research_task_target_types_match_service():
    for task, target in registry.RESEARCH_TASK_TARGET_TYPE.items():
        assert service.LOCAL_RESEARCH_TASKS[task]["targetCandidateType"] == target, task


def test_schema_files_exist_and_load():
    for name in registry.candidate_schema_ids():
        path = registry.SCHEMA_DIR / name
        assert path.exists(), f"missing schema file: {name}"
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded.get("$id") == name
    envelope = registry.load_schema("universal_candidate_envelope.schema.json")
    assert envelope["required"] == list(registry.ENVELOPE_REQUIRED_FIELDS)
    assert set(envelope["properties"]["candidateType"]["enum"]) == set(registry.CANDIDATE_TYPES)


def test_research_task_outputs_schema_defs_match_registry():
    schema = registry.load_schema("research_task_outputs.schema.json")
    defs = schema["$defs"]
    assert set(defs) == set(registry.RESEARCH_TASK_REQUIRED_OUTPUT)
    for task, fields in registry.RESEARCH_TASK_REQUIRED_OUTPUT.items():
        assert defs[task]["required"] == list(fields)


def test_validate_envelope_rejects_missing_fields():
    result = registry.validate_envelope({"candidateType": "source_manifest"})
    assert result["valid"] is False
    codes = {issue["code"] for issue in result["issues"] if issue["severity"] == "error"}
    assert "missing_field" in codes


def test_validate_envelope_rejects_unknown_candidate_type():
    candidate = registry.build_candidate_envelope(
        candidate_id="c1", candidate_type="not_a_type", team_id="t1", status="source_registered"
    )
    result = registry.validate_envelope(candidate)
    assert result["valid"] is False
    assert any(issue["code"] == "invalid_candidate_type" for issue in result["issues"])


def test_build_candidate_envelope_passes_validation():
    candidate = registry.build_candidate_envelope(
        candidate_id="cand_1",
        candidate_type="algorithm_hypothesis",
        team_id="research-team",
        status="hypothesis_candidate",
        source_trace=["source_1", "paper_note_1"],
        requires_steward_approval=True,
    )
    result = registry.validate_envelope(candidate, strict=True)
    assert result["valid"] is True
    assert candidate["officialBoundary"]["officialWriteAllowed"] is False
    assert candidate["officialBoundary"]["requiresStewardApproval"] is True
