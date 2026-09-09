import pytest
from pydantic import ValidationError

from core.web.routes.evolution_models import SupervisedWorktreeRunStartPayload
from core.web.services import supervised_worktree_evolution_service as service


def test_history_summary_preserves_identity_without_loading_evidence(monkeypatch):
    monkeypatch.setattr(service, "_action_states", lambda snapshot: {"merge": {"enabled": False}})
    run = {
        "runId": "run-1", "status": "done", "updatedAt": "2026-09-09",
        "decision": {"baselineScore": 60, "candidateScore": 80},
        "workflowProgress": {"transcript": "large evidence" * 1000},
        "workflowSteps": [{"prompt": "private task"}],
        "baseline": {"cases": [{"prompt": "private task"}]},
        "approvalDecision": {"status": "pending", "frozenEvidence": "large evidence" * 1000},
        "mergeAnalysis": {"evidence": "large evidence" * 1000},
    }
    summary = service.summarize_supervised_worktree_run(run)
    assert summary["runId"] == "run-1"
    assert summary["decision"]["candidateScore"] == 80
    assert summary["detailLevel"] == "summary"
    assert summary["approvalDecision"] == {"status": "pending"}
    assert summary["mergeAnalysis"] == {}
    assert not {"workflowProgress", "workflowSteps", "baseline"} & summary.keys()
    assert run["baseline"]["cases"]  # projection must not delete the detail evidence


@pytest.mark.parametrize("limit", [0, -1, 1.5, True, "2"])
def test_http_rejects_explicit_invalid_sample_limits(limit):
    with pytest.raises(ValidationError):
        SupervisedWorktreeRunStartPayload(datasetLimit=limit)


@pytest.mark.parametrize("limit", [0, -1, 1.5, True, "2"])
def test_service_rejects_invalid_limits_before_materialization(monkeypatch, tmp_path, limit):
    monkeypatch.setattr(service, "_storage_project_root_arg", lambda root: tmp_path)
    with pytest.raises(service.SupervisedWorktreeRunValidationError, match="整数"):
        service._normalize_start_payload({"datasetLimit": limit}, lang="zh", project_root=tmp_path)


def test_blank_limit_remains_explicitly_unlimited():
    assert SupervisedWorktreeRunStartPayload().datasetLimit is None
    assert SupervisedWorktreeRunStartPayload(datasetLimit=2).datasetLimit == 2
