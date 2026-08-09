"""T8 physical cleanup gates for the Challenge Cup workflow runtime."""

from __future__ import annotations

from core.web.routes.research import router as research_router
from core.web.services import research_service
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowRuntimeService,
)


def test_legacy_flow_canvas_execute_writer_is_not_mounted_or_exported() -> None:
    mounted_paths = {route.path for route in research_router.routes}

    assert "/research/flow-canvas/execute" not in mounted_paths
    assert not hasattr(research_service, "execute_research_flow_canvas_node")


def test_iteration_decisions_only_use_canonical_node_commands() -> None:
    assert not hasattr(ResearchWorkflowRuntimeService, "apply_iteration_decision")
