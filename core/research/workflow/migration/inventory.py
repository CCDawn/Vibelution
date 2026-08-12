"""Read-only inventory over the T0 audit report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts import audit_research_workflow_runtime as audit

from .validator import unknown_entries


def build_inventory(
    data_root: Path,
    *,
    project_root: Path,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    workspace = workspace_root or (data_root.parent / "workspace")
    report = audit.run_audit(
        data_root,
        project_root=project_root,
        workspace_root=workspace,
    )
    unknown = unknown_entries(list(report.get("runs") or []))
    report["unknownCount"] = len(unknown)
    report["unknownRunIds"] = [str(entry.get("runId") or "") for entry in unknown]
    return report
