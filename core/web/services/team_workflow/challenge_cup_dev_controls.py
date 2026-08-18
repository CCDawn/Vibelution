"""Team-scoped Challenge Cup DEV platform controls service.

Owns team storage resolution and persistence for the DEV-only control surface:
the persisted ChallengeCupPlatformDevelopmentReadinessReport and the dev-1/dev-5
fixture ``CatalogExecutionState`` checkpoints. The state machines and fixture
adapters live in ``core.research.competition``; this module never starts a real
experiment, Qwen invocation, network collection, CUDA/GPU benchmark, DANDI
download or formal submission.
"""

from __future__ import annotations

import json
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure.atomic_io import atomic_write_json
from core.research.competition.catalog_execution import (
    CatalogExecutionError,
    CatalogExecutionState,
)
from core.research.competition.dev_control_batch import (
    ALLOWED_DEV_BATCH_PLAN_IDS,
    FORBIDDEN_DEV_BATCH_PLAN_IDS,
    DevBatchError,
    new_dev_batch_state,
    project_dev_batch_checkpoint,
    project_dev_batch_outcomes,
    project_dev_batch_state,
    run_dev_fixture_batch,
    validate_dev_batch_max_items,
    validate_dev_batch_plan,
)
from core.research.competition.platform_flow_ready import (
    REPORT_KIND,
    build_platform_flow_readiness_report,
)
from core.web.services import team_service
from core.web.services.runtime_scene_service import record_runtime_scene_event
from core.web.services.team_workflow.research_projects import team_workspace_root

CONTROLS_DIRNAME = "challenge_cup_dev_controls"
REPORT_FILENAME = "readiness_report.json"
BATCH_DIRNAME = "batches"
REPORT_ENVELOPE_SCHEMA_VERSION = 1
BATCH_ENVELOPE_SCHEMA_VERSION = 1
SNAPSHOT_SCHEMA_VERSION = 1
DEV_ONLY_MODE = "dev"

_STORE_LOCK = threading.RLock()


class ChallengeCupDevControlsError(ValueError):
    """A Challenge Cup DEV control request is invalid or fail-closed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _controls_root(team_id: str) -> Path:
    return team_workspace_root(team_id) / CONTROLS_DIRNAME


def _report_path(team_id: str) -> Path:
    return _controls_root(team_id) / REPORT_FILENAME


def _batch_path(team_id: str, plan_id: str) -> Path:
    return _controls_root(team_id) / BATCH_DIRNAME / f"{plan_id}.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _load_batch_checkpoint(team_id: str, plan_id: str) -> tuple[bool, dict[str, Any], str]:
    payload = _read_json(_batch_path(team_id, plan_id))
    checkpoint = payload.get("checkpoint")
    if not isinstance(checkpoint, dict):
        return False, {}, ""
    return True, checkpoint, str(payload.get("updatedAt") or "")


def _project_report(team_id: str) -> dict[str, Any] | None:
    payload = _read_json(_report_path(team_id))
    report = payload.get("report")
    if not isinstance(report, dict):
        return None
    return {
        "schemaVersion": 1,
        "reportKind": str(report.get("reportKind") or REPORT_KIND),
        "status": str(report.get("status") or ""),
        "mode": str(report.get("mode") or DEV_ONLY_MODE),
        "realCampaignAllowed": bool(report.get("realCampaignAllowed") is True),
        "researchAuthorizationRequired": bool(report.get("researchAuthorizationRequired") or True),
        "nextLegalAction": str(report.get("nextLegalAction") or ""),
        "generatedAt": str(report.get("generatedAt") or ""),
        "updatedAt": str(payload.get("updatedAt") or ""),
        "gates": report.get("gates") if isinstance(report.get("gates"), list) else [],
    }


def _project_batch(team_id: str, plan_id: str) -> dict[str, Any] | None:
    present, checkpoint, updated_at = _load_batch_checkpoint(team_id, plan_id)
    if not present:
        return None
    try:
        return project_dev_batch_checkpoint(checkpoint, updated_at=updated_at)
    except (CatalogExecutionError, ValueError):
        return None


def _require_team(team_id: str) -> None:
    """Assert the team exists before any read or write on its controls."""
    team_service.get_team(team_id)


def _record_scene_event(
    event_code: str,
    *,
    message: str,
    outcome: str,
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "team_workflow_orchestration",
            "challenge_cup_dev_controls",
            event_code,
            message=message,
            outcome=outcome,
            fields=fields,
            lifecycle=True,
        )
    except Exception:  # noqa: BLE001 - diagnostics must never fail the caller
        pass


def _snapshot_next_legal_action(
    report: dict[str, Any] | None,
    batches: dict[str, Any],
) -> str:
    """Derive the next legal action from persisted state, never a parallel lifecycle.

    Order: readiness -> dev-1 -> dev-5 initial/resume -> RESEARCH_AUTHORIZATION_REQUIRED.
    A dev-1 or dev-5 checkpoint with failed or blocked items demands an explicit
    repair action and never advances to the next stage.
    """
    if report is None:
        return "run_dev_readiness"
    if report["status"] != "READY":
        return "repair_failed_platform_gates"
    dev_1 = batches.get("dev-1")
    if dev_1 is not None and (dev_1["failedCount"] > 0 or dev_1["blockedCount"] > 0):
        return "repair_dev_1_fixture_batch"
    if dev_1 is None or dev_1["pendingCount"] > 0:
        return "run_dev_1_fixture_batch"
    dev_5 = batches.get("dev-5")
    if dev_5 is not None and (dev_5["failedCount"] > 0 or dev_5["blockedCount"] > 0):
        return "repair_dev_5_fixture_batch"
    if dev_5 is None:
        return "run_dev_5_fixture_batch"
    if dev_5["pendingCount"] > 0:
        return "resume_dev_5_fixture_batch"
    return "RESEARCH_AUTHORIZATION_REQUIRED"


def _boundary_fields() -> dict[str, Any]:
    return {
        "mode": DEV_ONLY_MODE,
        "realCampaignAllowed": False,
        "authorizedPlans": list(ALLOWED_DEV_BATCH_PLAN_IDS),
        "forbiddenPlans": list(FORBIDDEN_DEV_BATCH_PLAN_IDS),
        "forbiddenFeatures": [
            "real_qwen_invocation",
            "network_collection",
            "cuda_gpu",
            "dandi_download",
            "formal_submission",
            "g1_g5_g12_g125_real_gates",
        ],
        "fixtureOnly": True,
    }


def get_challenge_cup_dev_control_snapshot(team_id: str) -> dict[str, Any]:
    """Return one typed team-scoped DEV control snapshot.

    Derived purely from the persisted serialized ``CatalogExecutionState``
    checkpoints and the latest persisted readiness report; it never invents a
    parallel lifecycle. The team must exist before any read.
    """
    _require_team(team_id)
    report = _project_report(team_id)
    batches: dict[str, Any] = {}
    for plan_id in ALLOWED_DEV_BATCH_PLAN_IDS:
        projection = _project_batch(team_id, plan_id)
        if projection is not None:
            batches[plan_id] = projection
    return {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "teamId": str(team_id or ""),
        "generatedAt": _utc_now(),
        "mode": DEV_ONLY_MODE,
        "realCampaignAllowed": False,
        "nextLegalAction": _snapshot_next_legal_action(report, batches),
        "report": report,
        "batches": batches,
        "boundary": _boundary_fields(),
    }


def _persist_report(team_id: str, report: dict[str, Any]) -> dict[str, Any]:
    if report.get("realCampaignAllowed") is not False:
        raise ChallengeCupDevControlsError(
            "Challenge Cup readiness report must never allow a real campaign."
        )
    envelope = {
        "schemaVersion": REPORT_ENVELOPE_SCHEMA_VERSION,
        "report": report,
        "realCampaignAllowed": False,
        "updatedAt": _utc_now(),
    }
    with _STORE_LOCK:
        atomic_write_json(_report_path(team_id), envelope, sort_keys=True)
    return envelope


def run_challenge_cup_dev_readiness(team_id: str, *, mode: str = DEV_ONLY_MODE) -> dict[str, Any]:
    """Build and atomically persist the DEV readiness report (R1 pytest included).

    The clean-clone destination is a task-owned temporary directory that is
    always cleaned up, even when the report build fails. A dirty working tree is
    never READY: ``require_clean`` is always True and ``run_pytest`` is always
    True under ``build_platform_flow_readiness_report``, and
    ``realCampaignAllowed`` can never become true.
    """
    if str(mode or "").strip().lower() != DEV_ONLY_MODE:
        _record_scene_event(
            "challenge_cup_dev_controls.readiness.rejected",
            message="Challenge Cup readiness rejected a non-dev mode.",
            outcome="blocked",
            fields={"teamId": team_id, "errorType": "ChallengeCupDevControlsError"},
        )
        raise ChallengeCupDevControlsError(
            "Challenge Cup readiness is DEV-only; formal modes are not authorized."
        )
    _require_team(team_id)
    _record_scene_event(
        "challenge_cup_dev_controls.readiness.started",
        message="Challenge Cup DEV readiness build started.",
        outcome="started",
        fields={"teamId": team_id, "mode": DEV_ONLY_MODE},
    )
    from core.infrastructure.path_containment import PROJECT_ROOT

    try:
        with tempfile.TemporaryDirectory(prefix="challenge-cup-r1-") as tmp_dir:
            report = build_platform_flow_readiness_report(
                PROJECT_ROOT,
                clone_dest=Path(tmp_dir) / "clone",
                require_clean=True,
                run_pytest=True,
                mode=DEV_ONLY_MODE,
            )
    except Exception as exc:
        _record_scene_event(
            "challenge_cup_dev_controls.readiness.failed",
            message="Challenge Cup DEV readiness build failed.",
            outcome="failed",
            fields={
                "teamId": team_id,
                "errorType": type(exc).__name__,
                "errorDetail": str(exc)[:320],
            },
        )
        raise
    envelope = _persist_report(team_id, report)
    _record_scene_event(
        "challenge_cup_dev_controls.readiness.succeeded",
        message="Challenge Cup DEV readiness report was persisted.",
        outcome="succeeded",
        fields={
            "teamId": team_id,
            "status": str(report.get("status") or ""),
            "nextLegalAction": str(report.get("nextLegalAction") or ""),
        },
    )
    return {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "teamId": str(team_id or ""),
        "report": _project_report(team_id),
        "cleanedUp": True,
        "updatedAt": str(envelope.get("updatedAt") or ""),
    }


def run_challenge_cup_dev_batch(
    team_id: str,
    plan_id: str,
    max_items: int | None,
) -> dict[str, Any]:
    """Execute/resume only dev-1 or dev-5 fixture batches and persist checkpoints.

    The checkpoint is persisted after every completed/failed item, so a dev-5
    interruption can always be resumed without re-running succeeded items.
    dev-12/dev-125 and formal/real scopes are rejected fail-closed. The team
    must exist before any read or write.
    """
    _require_team(team_id)
    try:
        normalized_plan = validate_dev_batch_plan(plan_id)
        bounded = validate_dev_batch_max_items(max_items)
    except Exception as exc:
        _record_scene_event(
            "challenge_cup_dev_controls.batch.rejected",
            message="Challenge Cup DEV fixture batch was rejected.",
            outcome="blocked",
            fields={
                "teamId": team_id,
                "planId": str(plan_id or "")[:80],
                "errorType": type(exc).__name__,
                "errorDetail": str(exc)[:320],
            },
        )
        raise
    _record_scene_event(
        "challenge_cup_dev_controls.batch.started",
        message="Challenge Cup DEV fixture batch started.",
        outcome="started",
        fields={
            "teamId": team_id,
            "planId": normalized_plan,
            "maxItems": bounded,
        },
    )
    try:
        with _STORE_LOCK:
            present, checkpoint, _ = _load_batch_checkpoint(team_id, normalized_plan)
            state = (
                CatalogExecutionState.from_checkpoint(checkpoint)
                if present
                else new_dev_batch_state(normalized_plan)
            )

            def persist(_item: dict[str, Any]) -> None:
                envelope = {
                    "schemaVersion": BATCH_ENVELOPE_SCHEMA_VERSION,
                    "planId": normalized_plan,
                    "updatedAt": _utc_now(),
                    "checkpoint": state.to_checkpoint(),
                }
                atomic_write_json(_batch_path(team_id, normalized_plan), envelope, sort_keys=True)

            result = run_dev_fixture_batch(state, max_items=bounded, on_item=persist)
            persisted_at = _utc_now()
            persist(None)
            projection = project_dev_batch_state(state, updated_at=persisted_at)
    except Exception as exc:
        _record_scene_event(
            "challenge_cup_dev_controls.batch.failed",
            message="Challenge Cup DEV fixture batch failed.",
            outcome="failed",
            fields={
                "teamId": team_id,
                "planId": normalized_plan,
                "errorType": type(exc).__name__,
                "errorDetail": str(exc)[:320],
            },
        )
        raise
    _record_scene_event(
        "challenge_cup_dev_controls.batch.succeeded",
        message="Challenge Cup DEV fixture batch completed and was persisted.",
        outcome="succeeded",
        fields={
            "teamId": team_id,
            "planId": normalized_plan,
            "attemptedCount": len(result["attempted"]),
            "succeededCount": projection["succeededCount"],
            "pendingCount": projection["pendingCount"],
            "canResume": projection["canResume"],
        },
    )
    return {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "teamId": str(team_id or ""),
        "planId": normalized_plan,
        "gateId": projection["gateId"],
        "attempted": result["attempted"],
        "outcomes": project_dev_batch_outcomes(result["outcomes"]),
        "checkpoint": projection,
        "persistedAt": persisted_at,
        "persisted": True,
    }