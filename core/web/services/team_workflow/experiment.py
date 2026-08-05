"""Experiment plan/status/methods/smoke/full-run and knowledge-ingestion hooks.

Clarity B6: implementations live under ``experiment_api/`` submodules.
This module re-exports the public surface for stable import paths
(``team_workflow.experiment`` and facade re-exports).

Late-bound facade keeps route imports and monkeypatches on
``team_workflow_orchestration_service`` stable during P0 mechanical splits.
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
    "run_experiment_smoke_run",
]
