"""Router registration for the Web workbench app."""

from __future__ import annotations

from fastapi import FastAPI

from .routes.agents import router as agents_router
from .routes.chat_rooms import router as chat_rooms_router
from .routes.cli_agents import router as cli_agents_router
from .routes.computer_use import router as computer_use_router
from .routes.config import router as config_router
from .routes.conversations import router as conversations_router
from .routes.data_processing import router as data_processing_router
from .routes.diagnostics import router as diagnostics_router
from .routes.evolution import router as evolution_router
from .routes.files import router as files_router
from .routes.git import router as git_router
from .routes.kernel import router as kernel_router
from .routes.knowledge import router as knowledge_router
from .routes.launcher import router as launcher_router
from .routes.logs import router as logs_router
from .routes.memory import router as memory_router
from .routes.pet import router as pet_router
from .routes.project_agent_bus import router as project_agent_bus_router
from .routes.research import router as research_router
from .routes.research_loop import router as research_loop_router
from .routes.reset import router as reset_router
from .routes.runtime import router as runtime_router
from .routes.sessions import router as sessions_router
from .routes.skills import router as skills_router
from .routes.team_templates import router as team_templates_router
from .routes.team_workflows import router as team_workflows_router
from .routes.teams import router as teams_router
from .routes.tools import router as tools_router


def register_web_routers(app: FastAPI) -> None:
    app.include_router(runtime_router, prefix="/api")
    app.include_router(launcher_router, prefix="/api")
    app.include_router(agents_router, prefix="/api")
    app.include_router(conversations_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")
    app.include_router(chat_rooms_router, prefix="/api")
    app.include_router(cli_agents_router, prefix="/api")
    app.include_router(project_agent_bus_router, prefix="/api")
    app.include_router(kernel_router, prefix="/api")
    app.include_router(team_templates_router, prefix="/api")
    app.include_router(teams_router, prefix="/api")
    app.include_router(team_workflows_router, prefix="/api")
    app.include_router(skills_router, prefix="/api")
    app.include_router(tools_router, prefix="/api")
    app.include_router(computer_use_router, prefix="/api")
    app.include_router(files_router, prefix="/api")
    app.include_router(git_router, prefix="/api")
    app.include_router(data_processing_router, prefix="/api")
    app.include_router(knowledge_router, prefix="/api")
    app.include_router(logs_router, prefix="/api")
    app.include_router(memory_router, prefix="/api")
    app.include_router(research_router, prefix="/api")
    app.include_router(research_loop_router, prefix="/api")
    app.include_router(diagnostics_router, prefix="/api")
    app.include_router(evolution_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(reset_router, prefix="/api")
    app.include_router(pet_router, prefix="/api")
