"""Resolve existing plans by their stored project, never the current switcher."""
from __future__ import annotations


def resolve_experiment_plan_project(team_id: str, plan_id: str, project_id: str = "") -> str:
    from core.web.services import team_workflow_orchestration_service as s

    requested = s._trim_text(project_id, max_length=160)
    projects = (
        [s.get_research_project(team_id, requested)]
        if requested else s.list_research_projects(team_id)["projects"]
    )
    owners: list[str] = []
    for project in projects:
        owner = str(project["projectId"])
        path = s._experiment_plan_store_path(team_id, owner)
        if not path.is_file():
            continue
        plan = s._find_experiment_plan(s._read_json(path), plan_id)
        if plan is None:
            continue
        recorded_owner = str(plan.get("researchProjectId") or owner)
        if recorded_owner != owner:
            raise s.TeamWorkflowOrchestrationError("Experiment plan does not belong to this research project.")
        owners.append(owner)
    if not owners:
        raise s.TeamWorkflowOrchestrationError("Experiment plan not found in the requested project scope.")
    if len(owners) != 1:
        raise s.TeamWorkflowOrchestrationError("Experiment plan project is ambiguous; researchProjectId is required.")
    return owners[0]
