"""Team workflow routes: research template baselines.

薄路由层：模板基线的创建/冻结（幂等）、列表与 frozen 视图透传。业务语义
（append-only 冻结、子版本语义变更重审）留在
``core/web/services/team_workflow/research_templates.py``；route 只做边界
校验与错误映射。前端通过这些端点解除 ``template_baseline_missing``
readiness blocker。
"""

from __future__ import annotations

from fastapi import status

from core.research.workflow.contracts import ContractValidationError
from core.web.services.team_service import TeamNotFoundError, TeamServiceError
from core.web.services.team_workflow import research_templates
from core.web.services.team_workflow.research_templates import (
    ResearchTemplateBaselineNotFoundError,
    ResearchTemplateError,
)

from ._errors import _raise_team_workflow_route_error
from ._router import router
from .research_templates_models import (
    TemplateBaselineCreatePayload,
    TemplateBaselineRouteResponse,
)


@router.post(
    "/teams/{team_id}/workflow-orchestration/template-baselines",
    status_code=status.HTTP_201_CREATED,
    response_model=TemplateBaselineRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_template_baseline_create(
    team_id: str, payload: TemplateBaselineCreatePayload
) -> dict:
    try:
        return research_templates.create_template_baseline(
            team_id, payload.model_dump()
        )
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "template_baseline.create", team_id, exc, status_code=404
        )
    except ContractValidationError as exc:
        _raise_team_workflow_route_error(
            "template_baseline.create",
            team_id,
            exc,
            status_code=422,
            fields={"templateId": payload.templateId},
        )
    except ResearchTemplateError as exc:
        _raise_team_workflow_route_error(
            "template_baseline.create",
            team_id,
            exc,
            status_code=409,
            fields={"templateId": payload.templateId},
        )
    except TeamServiceError as exc:
        _raise_team_workflow_route_error(
            "template_baseline.create", team_id, exc, status_code=422
        )


@router.get(
    "/teams/{team_id}/workflow-orchestration/template-baselines",
    response_model=TemplateBaselineRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_template_baseline_list(team_id: str) -> dict:
    try:
        return research_templates.list_template_baselines(team_id)
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "template_baseline.list", team_id, exc, status_code=404
        )
    except TeamServiceError as exc:
        _raise_team_workflow_route_error(
            "template_baseline.list", team_id, exc, status_code=422
        )


@router.get(
    "/teams/{team_id}/workflow-orchestration/template-baselines/{baseline_id}",
    response_model=TemplateBaselineRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_template_baseline_get(team_id: str, baseline_id: str) -> dict:
    try:
        return research_templates.frozen_template_view(team_id, baseline_id)
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "template_baseline.get", team_id, exc, status_code=404
        )
    except ResearchTemplateBaselineNotFoundError as exc:
        _raise_team_workflow_route_error(
            "template_baseline.get",
            team_id,
            exc,
            status_code=404,
            fields={"baselineId": baseline_id},
        )
    except (ResearchTemplateError, TeamServiceError) as exc:
        _raise_team_workflow_route_error(
            "template_baseline.get",
            team_id,
            exc,
            status_code=422,
            fields={"baselineId": baseline_id},
        )
