"""Audit and remove invalid pre-approval SCI-091/SCI-096 experiment rounds."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.infrastructure.atomic_io import atomic_write_json
from vibelution_storage import resolve_project_data_home


TARGETS = {
    "challenge-sci-091": "SCI-091",
    "challenge-sci-096": "SCI-096",
}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"store must be a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _invalid_experiment_round(
    round_record: Mapping[str, Any],
    *,
    project_id: str,
    question_id: str,
) -> bool:
    if str(round_record.get("stageType") or "").strip() != "experiment":
        return False
    try:
        phase = int(round_record.get("programPhase") or 0)
    except (TypeError, ValueError):
        phase = 0
    return not (
        str(round_record.get("researchProjectId") or "").strip() == project_id
        and str(round_record.get("challengeQuestionId") or "").strip().upper()
        == question_id
        and phase == 2
        and str(round_record.get("programDirection") or "").strip().upper() == "B"
        and round_record.get("deepExperiment") is True
    )


def cleanup_invalid_stage2_rounds(
    project_roots: Mapping[str, Path],
    *,
    backup_root: Path,
    apply: bool,
) -> dict[str, Any]:
    backup_root = Path(backup_root).resolve(strict=False)
    if apply and backup_root.exists():
        raise ValueError("backup directory already exists")
    changes: list[dict[str, Any]] = []
    removed_round_ids: list[str] = []
    removed_plan_ids: list[str] = []

    for project_id, question_id in TARGETS.items():
        workspace_root = Path(project_roots[project_id]).resolve(strict=False)
        round_path = workspace_root / "research_stage_rounds" / "index.json"
        plan_path = workspace_root / "experiment_plans" / "index.json"
        round_store = _load_json(round_path)
        rounds = [item for item in list(round_store.get("rounds") or []) if isinstance(item, dict)]
        invalid_rounds = [
            item
            for item in rounds
            if _invalid_experiment_round(
                item,
                project_id=project_id,
                question_id=question_id,
            )
        ]
        invalid_ids = {
            str(item.get("stageRoundId") or "").strip()
            for item in invalid_rounds
            if str(item.get("stageRoundId") or "").strip()
        }
        plan_store = _load_json(plan_path)
        plans = [item for item in list(plan_store.get("plans") or []) if isinstance(item, dict)]
        invalid_plans = [
            item
            for item in plans
            if str(item.get("stageRoundId") or "").strip() in invalid_ids
        ]
        invalid_plan_ids = {
            str(item.get("planId") or "").strip()
            for item in invalid_plans
            if str(item.get("planId") or "").strip()
        }
        removed_round_ids.extend(sorted(invalid_ids))
        removed_plan_ids.extend(sorted(invalid_plan_ids))
        if not invalid_ids and not invalid_plan_ids:
            continue
        changes.append(
            {
                "projectId": project_id,
                "questionId": question_id,
                "roundPath": str(round_path),
                "planPath": str(plan_path),
                "removedRoundIds": sorted(invalid_ids),
                "removedPlanIds": sorted(invalid_plan_ids),
            }
        )
        if not apply:
            continue
        for source_path in (round_path, plan_path):
            if not source_path.is_file():
                continue
            relative = source_path.relative_to(workspace_root)
            backup_path = backup_root / project_id / relative
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, backup_path)
        if invalid_ids:
            round_store["rounds"] = [
                item
                for item in rounds
                if str(item.get("stageRoundId") or "").strip() not in invalid_ids
            ]
            round_store["updatedAt"] = datetime.now(UTC).isoformat()
            atomic_write_json(round_path, round_store)
        if invalid_plan_ids:
            plan_store["plans"] = [
                item
                for item in plans
                if str(item.get("planId") or "").strip() not in invalid_plan_ids
            ]
            if str(plan_store.get("activePlanId") or "").strip() in invalid_plan_ids:
                plan_store["activePlanId"] = ""
            plan_store["updatedAt"] = datetime.now(UTC).isoformat()
            atomic_write_json(plan_path, plan_store)

    report = {
        "schemaVersion": 1,
        "status": "applied" if apply else "dry_run",
        "targetProjectIds": list(TARGETS),
        "removedRoundIds": sorted(removed_round_ids),
        "removedPlanIds": sorted(removed_plan_ids),
        "changes": changes,
        "backupRoot": str(backup_root) if apply else "",
    }
    if apply:
        backup_sources = []
        for path in sorted(backup_root.rglob("index.json")):
            backup_sources.append(
                {
                    "path": str(path.relative_to(backup_root)).replace("\\", "/"),
                    "sha256": _sha256(path),
                }
            )
        report["backupSources"] = backup_sources
        atomic_write_json(backup_root / "manifest.json", report)
    return report


def _resolve_project_roots(data_root: Path, team_id: str) -> dict[str, Path]:
    team_component = str(team_id or "").strip()
    if not team_component or any(char in team_component for char in ("/", "\\", ".")):
        raise ValueError("team id is not a safe storage component")
    base = data_root / "workspace" / "teams" / team_component / "research_projects"
    return {
        project_id: base / project_id / "workspace"
        for project_id in TARGETS
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--team-id", default="research-team")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    data_root = Path(resolve_project_data_home(project_root)).resolve()
    backup_root = (
        args.backup_root.resolve(strict=False)
        if args.backup_root is not None
        else data_root
        / "maintenance_backups"
        / "challenge-stage2"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    try:
        backup_root.relative_to(data_root)
    except ValueError as exc:
        raise SystemExit("backup root must stay inside the current instance data root") from exc
    report = cleanup_invalid_stage2_rounds(
        _resolve_project_roots(data_root, args.team_id),
        backup_root=backup_root,
        apply=bool(args.apply),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
