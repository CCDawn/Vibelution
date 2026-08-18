"""Experiment service sub-surface (Clarity P5/B6).

Ownership:
- plan.py — status, catalog, plan create/revision, freeze, baseline
- hypothesis.py — proxy materialize + complete from design
- smoke.py — smoke run + result register
- full_run.py — prepare/execute/register full run
- knowledge.py — result knowledge ingestion + reconcile

Import via ``core.web.services.team_workflow.experiment`` or the facade for
stable public paths.
"""

from __future__ import annotations

from core.web.services.team_workflow.experiment_api.full_run import (
    execute_experiment_full_run,
    prepare_experiment_full_run,
    register_experiment_full_run_result,
)
from core.web.services.team_workflow.experiment_api.hypothesis import (
    complete_experiment_hypothesis_from_design,
    materialize_experiment_proxy_hypothesis,
)
from core.web.services.team_workflow.experiment_api.knowledge import (
    reconcile_experiment_knowledge_ingestion,
    request_experiment_result_knowledge_ingestion,
)
from core.web.services.team_workflow.experiment_api.plan import (
    create_experiment_plan,
    create_experiment_plan_revision_from_hypothesis,
    create_experiment_plan_revision_from_iteration,
    freeze_experiment_design,
    get_experiment_method_catalog,
    get_experiment_planning_status,
    register_experiment_baseline_artifact,
    resume_experiment_hypothesis,
)
from core.web.services.team_workflow.experiment_api.smoke import (
    register_experiment_smoke_result,
    run_experiment_smoke_run,
)

__all__ = [
    "complete_experiment_hypothesis_from_design",
    "create_experiment_plan",
    "create_experiment_plan_revision_from_hypothesis",
    "create_experiment_plan_revision_from_iteration",
    "execute_experiment_full_run",
    "freeze_experiment_design",
    "get_experiment_method_catalog",
    "get_experiment_planning_status",
    "materialize_experiment_proxy_hypothesis",
    "prepare_experiment_full_run",
    "reconcile_experiment_knowledge_ingestion",
    "register_experiment_baseline_artifact",
    "register_experiment_full_run_result",
    "register_experiment_smoke_result",
    "request_experiment_result_knowledge_ingestion",
    "resume_experiment_hypothesis",
    "run_experiment_smoke_run",
]
