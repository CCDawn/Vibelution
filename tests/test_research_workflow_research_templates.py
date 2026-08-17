"""D04 frozen research-template baseline and additive addendum tests."""

from __future__ import annotations

import pytest

from core.research.workflow.contracts import ContractValidationError
from core.web.services import team_service
from core.web.services.team_workflow import research_templates as service


def _team(tmp_path, monkeypatch):
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    return team_service.create_team(name="template team")["teamId"]


def _scope(**overrides):
    payload = {
        "program": "XH-202619",
        "theme": "cc-gpu-operator-001",
        "campaign": "cc-campaign-gpu-operator-001",
        "question": "SCI-091",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-planner",
        "mode": "formal",
    }
    payload.update(overrides)
    return payload


def _baseline(**overrides):
    payload = {
        **_scope(),
        "baselineId": "baseline-demo-v1",
        "templateId": "template-demo",
        "version": 1,
        "status": "frozen",
        "content": {
            "hypothesisFormat": "claim-rationale-falsifier",
            "evaluationDimensions": ["quality", "cost"],
        },
        "approvedBy": "human-reviewer",
        "approvalRef": "approval://baseline-demo-v1",
    }
    payload.update(overrides)
    return payload


def test_frozen_baseline_is_idempotent_and_cannot_be_overwritten(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    first = service.create_template_baseline(team_id, _baseline())
    repeated = service.create_template_baseline(team_id, _baseline())

    assert first["status"] == "created"
    assert repeated["status"] == "reused"
    assert first["baseline"]["status"] == "frozen"

    conflicting = _baseline(content={"hypothesisFormat": "silently changed"})
    with pytest.raises(service.ResearchTemplateError, match="cannot be reused"):
        service.create_template_baseline(team_id, conflicting)


def test_addendum_only_supplements_and_never_overwrites_frozen_keys(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    service.create_template_baseline(team_id, _baseline())
    addendum = {
        "addendumId": "addendum-demo-1",
        "reason": "record an extra reporting note",
        "deltas": {"reportingNote": "include per-question failure reasons"},
        "appendedBy": "agent-planner",
        "semanticChange": False,
    }
    created = service.append_template_addendum(team_id, "baseline-demo-v1", addendum)
    repeated = service.append_template_addendum(team_id, "baseline-demo-v1", addendum)
    view = service.frozen_template_view(team_id, "baseline-demo-v1")

    assert created["status"] == "created"
    assert repeated["status"] == "reused"
    assert view["content"]["hypothesisFormat"] == "claim-rationale-falsifier"
    assert view["content"]["reportingNote"] == "include per-question failure reasons"

    with pytest.raises(ContractValidationError, match="cannot overwrite"):
        service.append_template_addendum(
            team_id,
            "baseline-demo-v1",
            {
                "reason": "attempt to rewrite method",
                "deltas": {"hypothesisFormat": "replacement"},
                "appendedBy": "agent-planner",
            },
        )
    with pytest.raises(ContractValidationError, match="new baseline version"):
        service.append_template_addendum(
            team_id,
            "baseline-demo-v1",
            {
                "reason": "semantic rewrite",
                "deltas": {"newMethod": "replacement"},
                "appendedBy": "agent-planner",
                "semanticChange": True,
            },
        )


def test_semantic_change_requires_linked_next_version_and_fresh_approval(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    parent = service.create_template_baseline(team_id, _baseline())["baseline"]
    child = service.create_template_baseline(
        team_id,
        {
            **_baseline(
                baselineId="baseline-demo-v2",
                version=2,
                parentBaselineId="baseline-demo-v1",
                content={
                    "hypothesisFormat": "claim-rationale-falsifier",
                    "evaluationDimensions": ["quality", "cost", "robustness"],
                },
                approvedBy="human-reviewer-2",
                approvalRef="approval://baseline-demo-v2",
                semanticChangeReason="add robustness as a required dimension",
            )
        },
    )["baseline"]

    assert child["parentBaselineId"] == parent["baselineId"]
    assert child["parentVersion"] == 1
    assert child["version"] == 2
    assert service.get_template_baseline(team_id, parent["baselineId"])["baseline"]["content"] == parent["content"]

    with pytest.raises(ContractValidationError, match=r"parentVersion \+ 1"):
        service.create_template_baseline(
            team_id,
            _baseline(
                baselineId="baseline-demo-v4",
                version=4,
                parentBaselineId="baseline-demo-v1",
                content={"replacement": True},
                semanticChangeReason="invalid version jump",
                approvalRef="approval://baseline-demo-v4",
            ),
        )
    with pytest.raises(ContractValidationError, match="parent research scope"):
        service.create_template_baseline(
            team_id,
            _baseline(
                **_scope(theme="cc-neural-001", campaign="cc-campaign-neural-001"),
                baselineId="baseline-other-scope-v2",
                version=2,
                parentBaselineId="baseline-demo-v1",
                content={"replacement": True},
                semanticChangeReason="cross-scope mutation",
                approvalRef="approval://other-scope",
            ),
        )
