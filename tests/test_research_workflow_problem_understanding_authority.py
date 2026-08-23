from __future__ import annotations

import pytest

from core.web.services.team_workflow.research_runtime import workflow_artifact_store
from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
    build_canonical_ref,
    load_scoped_artifact_payload,
    read_domain_artifact,
)
from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
    canonical_sha256,
)
from core.web.services.team_workflow.research_runtime.problem_understanding_artifact_writer import (
    validate_problem_understanding,
    write_problem_understanding_artifact,
)


def _payload() -> dict:
    return {
        "scope": "可证伪的记忆提取机制",
        "subquestions": ["哪些机制可以被区分？"],
        "assumptions": ["输入数据能够覆盖对照条件"],
        "known_unknowns": ["跨任务泛化仍未知"],
        "human_gate": {
            "required": True,
            "decision": "pending",
            "rationale": "需要研究负责人确认范围后再搜集资料。",
        },
    }


def test_problem_understanding_writer_enforces_exact_v2_shape() -> None:
    assert validate_problem_understanding(_payload()) == _payload()
    with pytest.raises(ValueError, match="unsupported fields"):
        validate_problem_understanding({**_payload(), "score": 1})
    with pytest.raises(ValueError, match="required must be true"):
        validate_problem_understanding(
            {**_payload(), "human_gate": {**_payload()["human_gate"], "required": False}}
        )
    with pytest.raises(ValueError, match="rationale"):
        validate_problem_understanding(
            {**_payload(), "human_gate": {**_payload()["human_gate"], "rationale": ""}}
        )


def test_problem_understanding_is_read_back_by_full_envelope_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    written = write_problem_understanding_artifact(
        team_id="team-a",
        workflow_run_id="run-a",
        source_collection_run_id="sc-a",
        node_run_id="nr-problem-a1",
        problem_understanding=_payload(),
    )
    envelope = {
        "teamId": "team-a",
        "kind": "problem_understanding",
        "workflowRunId": "run-a",
        "sourceCollectionRunId": "sc-a",
        "payload": _payload(),
    }
    expected_hash = canonical_sha256(envelope)
    assert written["contentHash"] == expected_hash
    loaded = load_scoped_artifact_payload(
        "problem_understanding",
        team_id="team-a",
        authority_run_id="sc-a",
        workflow_run_id="run-a",
        content_hash=expected_hash,
    )
    assert loaded == envelope
    ref = build_canonical_ref(
        kind="problem_understanding",
        team_id="team-a",
        authority_run_id="sc-a",
        content_hash=expected_hash,
    )
    readback = read_domain_artifact(ref)
    assert readback is not None
    assert readback.content_hash == expected_hash
