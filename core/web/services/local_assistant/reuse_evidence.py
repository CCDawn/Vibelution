"""Write only the current Launcher task's small-fix reuse evidence."""
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .consent import require_local_workspace_write
from .policy import workspace_paths_allowed


class LocalReuseEvidenceArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: str = Field(min_length=1, max_length=240, description="The concrete change under review.")
    local_reuse_decision: Literal["REUSE", "ADAPT", "REPLACE", "UNUSED"]
    local_owner_paths: list[str] = Field(min_length=1, max_length=8, description="Existing repository-relative owning paths.")
    reason: str = Field(min_length=1, max_length=800, description="Why the existing local path and this decision fit.")
    implementation_boundary: str = Field(min_length=1, max_length=800)
    verification_strategy: str = Field(min_length=1, max_length=800)


def record_local_reuse_evidence(arguments: LocalReuseEvidenceArguments) -> dict:
    from core.infrastructure.branch_workspace import resolve_branch_workspace
    from core.web.services import agent_directory_service as directory
    from scripts.reuse_research_contract import (
        ReuseEvidenceWorkspace, ReuseResearchEvidenceError, record_evidence,
    )

    task = require_local_workspace_write(directory.current_agent_runtime(bound_only=True))
    workspace = task["workspace"]
    try:
        project_root = Path(directory.PROJECT_ROOT).resolve(strict=True)
        layout = resolve_branch_workspace(project_root)
        slug = "assistant-" + task["taskId"]
        if layout.worktree_root != project_root or workspace != layout.branch_pool / slug:
            raise ReuseResearchEvidenceError("The workspace is outside the assigned project task slot.")
        for path in arguments.local_owner_paths:
            if not workspace_paths_allowed("read_file_tool", {"file_path": path}, workspace):
                raise ReuseResearchEvidenceError("Local owners must stay inside the assigned worktree.")
        binding = ReuseEvidenceWorkspace("codex/" + slug, layout.git_common_dir)
        evidence = record_evidence(
            workspace,
            **arguments.model_dump(),
            research_mode="LOCAL_ONLY",
            decision="BUILD_IN_HOUSE",
            candidate_ids=(),
            borrowed_slices=(),
            rejected_alternatives=(),
            risk_notes=(),
            source_refs=(),
            workspace_binding=binding,
        )
    except ReuseResearchEvidenceError as exc:
        return {"ok": False, "error": str(exc)[:300]}
    except (OSError, RuntimeError, TimeoutExpired):
        return {"ok": False, "error": "Could not record reuse evidence for the assigned worktree."}
    return {"ok": True, "taskId": task["taskId"], "branch": evidence["branch"], "researchMode": "LOCAL_ONLY"}
