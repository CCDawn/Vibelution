"""Team-scoped research project registry and active workspace resolver."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.research.workflow.contracts import (
    DEFAULT_PROGRAM_ID,
    ContractValidationError,
    ResearchCampaignActivation,
    build_campaign_activation_payload,
)
from core.web.services import team_service
from core.web.services.runtime_scene_service import record_runtime_scene_event

SCHEMA_VERSION = 1
ACTIVATION_SCHEMA_VERSION = 1
LEGACY_PROJECT_ID = "legacy-default"
CHALLENGE_PROJECT_ID_PREFIX = "challenge-"
CHALLENGE_CUP_RESET_TEAM_ID = "research-team"
CHALLENGE_CUP_EXPERIMENT_STATE_ENTRIES = (
    "candidate_store",
    "challenge_cup_dev_controls",
    "challenge_cup_real_batch",
    "claim_evidence",
    "experiment_plans",
    "knowledge",
    "official_model_evidence",
    "research_loops",
    "research_projects",
    "research_question_trees",
    "research_stage_rounds",
    "research_workflow",
    "source_collection_runs",
    "workflow_orchestration.json",
)
_CHALLENGE_CUP_WORKSPACE_RESET_STAGES: dict[str, dict[str, Any]] = {}
_STORE_LOCK = threading.RLock()


class ResearchProjectError(RuntimeError):
    """Base error for research-project persistence."""


class ResearchProjectNotFoundError(ResearchProjectError):
    """Raised when a team research project does not exist."""


class ResearchProjectNameLockedError(ResearchProjectError):
    """Raised when a frozen research project name would be changed."""

    code = "research_project_name_locked"


class ResearchProjectQuestionMismatchError(ResearchProjectError):
    """Raised when a canonical Challenge Cup project identity conflicts."""

    code = "research_project_question_mismatch"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _safe_team_id(team_id: str) -> str:
    from core.web.services.team_workflow.storage_ids import safe_storage_component

    return safe_storage_component(team_id, fallback="team")


def team_workspace_root(team_id: str) -> Path:
    """Return the developer-mode workspace used by DEV-only controls."""

    return developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "teams",
        _safe_team_id(team_id),
    )


def formal_team_workspace_root(team_id: str) -> Path:
    """Return the current project's canonical workspace for product state."""

    return developer_sandbox.formal_workspace_path(
        _project_root(),
        "teams",
        _safe_team_id(team_id),
    )


def _store_path(team_id: str) -> Path:
    return formal_team_workspace_root(team_id) / "research_projects" / "index.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _default_project(now: str) -> dict[str, Any]:
    return {
        "projectId": LEGACY_PROJECT_ID,
        "name": "默认研究项目",
        "topic": "",
        "experimentMethod": "",
        "storageMode": "legacy",
        "challengeQuestionId": "",
        "themeId": "",
        "campaignId": "",
        "activationRef": "",
        "activatedAt": "",
        "nameLocked": False,
        "nameLockedAt": "",
        "nameLockReason": "",
        "createdAt": now,
        "updatedAt": now,
    }


def _normalize_project(project: dict[str, Any], *, fallback_now: str) -> dict[str, Any]:
    project_id = str(project.get("projectId") or "").strip()
    storage_mode = "legacy" if project_id == LEGACY_PROJECT_ID else "isolated"
    return {
        "projectId": project_id,
        "name": str(project.get("name") or "未命名研究项目").strip()[:160] or "未命名研究项目",
        "topic": str(project.get("topic") or "").strip()[:1000],
        "experimentMethod": str(project.get("experimentMethod") or "").strip()[:120],
        "storageMode": storage_mode,
        "challengeQuestionId": str(project.get("challengeQuestionId") or "").strip()[:32],
        "themeId": str(project.get("themeId") or "").strip()[:96],
        "campaignId": str(project.get("campaignId") or "").strip()[:96],
        "activationRef": str(project.get("activationRef") or "").strip()[:240],
        "activatedAt": str(project.get("activatedAt") or "").strip()[:120],
        "nameLocked": bool(project.get("nameLocked")),
        "nameLockedAt": str(project.get("nameLockedAt") or ""),
        "nameLockReason": str(project.get("nameLockReason") or "").strip()[:160],
        "createdAt": str(project.get("createdAt") or fallback_now),
        "updatedAt": str(project.get("updatedAt") or fallback_now),
    }


def _load_store(team_id: str) -> dict[str, Any]:
    now = _utc_now()
    payload = _read_json(_store_path(team_id))
    raw_projects = payload.get("projects") if isinstance(payload.get("projects"), list) else []
    projects = [
        _normalize_project(item, fallback_now=now)
        for item in raw_projects
        if isinstance(item, dict) and str(item.get("projectId") or "").strip()
    ]
    if not any(item["projectId"] == LEGACY_PROJECT_ID for item in projects):
        projects.insert(0, _default_project(now))
    active_project_id = str(payload.get("activeProjectId") or LEGACY_PROJECT_ID).strip()
    if not any(item["projectId"] == active_project_id for item in projects):
        active_project_id = LEGACY_PROJECT_ID
    activations = payload.get("activations") if isinstance(payload.get("activations"), dict) else {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "activationSchemaVersion": ACTIVATION_SCHEMA_VERSION,
        "teamId": str(team_id),
        "activeProjectId": active_project_id,
        "projects": projects,
        "activations": activations,
        "updatedAt": str(payload.get("updatedAt") or now),
    }


def _persist_store(team_id: str, store: dict[str, Any]) -> None:
    store["updatedAt"] = _utc_now()
    _write_json(_store_path(team_id), store)


def _project_payload(store: dict[str, Any], project_id: str) -> dict[str, Any]:
    for project in store["projects"]:
        if project["projectId"] == project_id:
            return project
    raise ResearchProjectNotFoundError("Research project not found.")


def list_research_projects(team_id: str) -> dict[str, Any]:
    team_service.get_team(team_id)
    with _STORE_LOCK:
        store = _load_store(team_id)
        if not _store_path(team_id).exists():
            _persist_store(team_id, store)
        return store


def read_research_projects_snapshot(team_id: str) -> dict[str, Any]:
    """Read project identities without creating or repairing a missing store."""

    team_service.get_team(team_id)
    with _STORE_LOCK:
        if not _store_path(team_id).exists():
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": str(team_id),
                "activeProjectId": "",
                "projects": [],
                "activations": {},
            }
        return _load_store(team_id)


def create_research_project(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    team_service.get_team(team_id)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ResearchProjectError("Research project name is required.")
    now = _utc_now()
    with _STORE_LOCK:
        store = _load_store(team_id)
        project = {
            "projectId": f"research-{uuid.uuid4().hex[:12]}",
            "name": name[:160],
            "topic": str(payload.get("topic") or "").strip()[:1000],
            "experimentMethod": str(payload.get("experimentMethod") or "").strip()[:120],
            "storageMode": "isolated",
            "challengeQuestionId": "",
            "themeId": "",
            "campaignId": "",
            "activationRef": "",
            "activatedAt": "",
            "nameLocked": False,
            "nameLockedAt": "",
            "nameLockReason": "",
            "createdAt": now,
            "updatedAt": now,
        }
        store["projects"].append(project)
        _persist_store(team_id, store)
    _record_project_event("research_project.created", team_id, project["projectId"])
    return {"project": project, **store}


def ensure_challenge_question_project(
    team_id: str,
    *,
    question_id: str,
    title: str,
    topic: str,
) -> dict[str, Any]:
    """Resolve the one canonical project identity for an approved question.

    Generic research projects are deliberately not reused: a legacy project may
    be historical evidence, but it cannot become the authoritative identity of
    a Challenge Cup question by name or by the active-project pointer alone.
    """

    team_service.get_team(team_id)
    normalized_question_id = str(question_id or "").strip().upper()[:32]
    normalized_title = str(title or "").strip()[:160]
    normalized_topic = str(topic or "").strip()[:1000]
    if not normalized_question_id or not normalized_title:
        raise ResearchProjectError("Challenge question identity is required.")
    project_id = f"{CHALLENGE_PROJECT_ID_PREFIX}{_safe_team_id(normalized_question_id).lower()}"
    canonical_name = f"{normalized_question_id} · {normalized_title}"[:160]
    with _STORE_LOCK:
        store = _load_store(team_id)
        matching_question = next(
            (
                item
                for item in store["projects"]
                if str(item.get("challengeQuestionId") or "").strip().upper()
                == normalized_question_id
            ),
            None,
        )
        matching_project_id = next(
            (item for item in store["projects"] if item["projectId"] == project_id),
            None,
        )
        if matching_question is not None and matching_question["projectId"] != project_id:
            raise ResearchProjectQuestionMismatchError(
                "A Challenge Cup question is already bound to a different research project."
            )
        if matching_project_id is not None and str(
            matching_project_id.get("challengeQuestionId") or ""
        ).strip().upper() != normalized_question_id:
            raise ResearchProjectQuestionMismatchError(
                "The canonical Challenge Cup project id is occupied by a different project."
            )
        project = matching_question or matching_project_id
        if project is None:
            now = _utc_now()
            project = {
                "projectId": project_id,
                "name": canonical_name,
                "topic": normalized_topic,
                "experimentMethod": "",
                "storageMode": "isolated",
                "challengeQuestionId": normalized_question_id,
                "themeId": "",
                "campaignId": "",
                "activationRef": "",
                "activatedAt": "",
                "nameLocked": False,
                "nameLockedAt": "",
                "nameLockReason": "",
                "createdAt": now,
                "updatedAt": now,
            }
            store["projects"].append(project)
        else:
            if bool(project.get("nameLocked")) and project["name"] != canonical_name:
                raise ResearchProjectQuestionMismatchError(
                    "The canonical Challenge Cup project name is locked to a different question title."
                )
            project["name"] = canonical_name
            project["topic"] = normalized_topic
            project["challengeQuestionId"] = normalized_question_id
            project["updatedAt"] = _utc_now()
        store["activeProjectId"] = project_id
        _persist_store(team_id, store)
    _record_project_event("research_project.challenge_question_resolved", team_id, project_id)
    return {"project": dict(project), **store}


def update_research_project(team_id: str, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    team_service.get_team(team_id)
    with _STORE_LOCK:
        store = _load_store(team_id)
        project = _project_payload(store, project_id)
        if "name" in payload:
            name = str(payload.get("name") or "").strip()
            if not name:
                raise ResearchProjectError("Research project name is required.")
            if bool(project.get("nameLocked")) and name[:160] != project["name"]:
                raise ResearchProjectNameLockedError(
                    "Research project name is locked after its first experiment session or task."
                )
            project["name"] = name[:160]
        if "topic" in payload and payload.get("topic") is not None:
            project["topic"] = str(payload.get("topic") or "").strip()[:1000]
        if "experimentMethod" in payload and payload.get("experimentMethod") is not None:
            project["experimentMethod"] = str(payload.get("experimentMethod") or "").strip()[:120]
        project["updatedAt"] = _utc_now()
        _persist_store(team_id, store)
    _record_project_event("research_project.updated", team_id, project_id)
    return {"project": project, **store}


def activate_research_project(team_id: str, project_id: str) -> dict[str, Any]:
    team_service.get_team(team_id)
    with _STORE_LOCK:
        store = _load_store(team_id)
        project = _project_payload(store, project_id)
        store["activeProjectId"] = project_id
        _persist_store(team_id, store)
    _record_project_event("research_project.activated", team_id, project_id)
    _maybe_wire_theme_campaign_activation(team_id, project)
    return {"project": project, **store}


def get_theme_activation(team_id: str, theme_id: str) -> dict[str, Any]:
    """Read the persisted formal activation record for one theme.

    Returns an empty dict when the theme has never been formally activated so
    the research-scope facade keeps enforcing the DEV/platform-only regime.
    """
    team_service.get_team(team_id)
    normalized_theme_id = str(theme_id or "").strip()
    if not normalized_theme_id:
        return {}
    with _STORE_LOCK:
        store = _load_store(team_id)
        record = store["activations"].get(normalized_theme_id)
        return dict(record) if isinstance(record, dict) else {}


def record_theme_campaign_activation(
    team_id: str,
    *,
    activation: dict[str, Any],
) -> dict[str, Any]:
    """Persist one formal campaign activation inside the existing project store.

    The activation contract is validated before anything is written; an
    unhashable or malformed activation is rejected without touching the store.
    """
    team_service.get_team(team_id)
    parsed = ResearchCampaignActivation.from_dict(activation)
    with _STORE_LOCK:
        store = _load_store(team_id)
        record = parsed.to_dict()
        store["activations"][parsed.themeId] = record
        for project in store["projects"]:
            if str(project.get("challengeQuestionId") or "").strip().upper() != _question_for_theme(parsed.themeId):
                continue
            project["themeId"] = parsed.themeId
            project["campaignId"] = parsed.campaignId
            project["activationRef"] = parsed.activationRef
            project["activatedAt"] = parsed.activatedAt
            project["updatedAt"] = _utc_now()
        _persist_store(team_id, store)
    _record_project_event("research_campaign.activated", team_id, parsed.themeId)
    return dict(record)


def _frozen_theme_records() -> list[dict[str, Any]]:
    from core.research.competition.resources import load_competition_program_core

    try:
        program = load_competition_program_core()
    except Exception:
        return []
    experiments = program.get("requiredDeepExperiments") if isinstance(program, dict) else []
    return [item for item in experiments if isinstance(item, dict)] if isinstance(experiments, list) else []


def _theme_for_question(question_id: str) -> dict[str, Any] | None:
    normalized_question_id = str(question_id or "").strip().upper()
    if not normalized_question_id:
        return None
    for item in _frozen_theme_records():
        if str(item.get("questionId") or "").strip().upper() == normalized_question_id:
            return {
                "programId": DEFAULT_PROGRAM_ID,
                "themeId": str(item.get("themeId") or "").strip(),
                "campaignId": str(item.get("campaignId") or "").strip(),
                "questionId": normalized_question_id,
            }
    return None


def _question_for_theme(theme_id: str) -> str:
    for item in _frozen_theme_records():
        if str(item.get("themeId") or "").strip() == str(theme_id or "").strip():
            return str(item.get("questionId") or "").strip().upper()
    return ""


def _maybe_wire_theme_campaign_activation(team_id: str, project: dict[str, Any]) -> None:
    """Best-effort formal activation when the project is bound to a real theme.

    DEV themes and question-less projects never match a frozen theme, so they
    stay inactive and keep the DEV/platform-only regime enforced by the scope
    facade.
    """
    theme = _theme_for_question(str(project.get("challengeQuestionId") or ""))
    if not theme or not theme["themeId"] or not theme["campaignId"]:
        return
    try:
        activation = build_campaign_activation_payload(
            program_id=theme["programId"],
            theme_id=theme["themeId"],
            campaign_id=theme["campaignId"],
            activated_by="research_project_activation",
            activation_ref=f"research-project://{str(project.get('projectId') or '')}",
        )
        record_theme_campaign_activation(team_id, activation=activation)
    except (ContractValidationError, ResearchProjectError):
        return


def get_research_project(team_id: str, project_id: str) -> dict[str, Any]:
    team_service.get_team(team_id)
    with _STORE_LOCK:
        store = _load_store(team_id)
        return dict(_project_payload(store, str(project_id or "").strip()))


def get_active_research_project(team_id: str) -> dict[str, Any]:
    team_service.assert_team_exists(team_id)
    with _STORE_LOCK:
        store = _load_store(team_id)
        return dict(_project_payload(store, store["activeProjectId"]))


def get_research_project_progress(team_id: str, project_id: str = "") -> dict[str, Any]:
    """Aggregate one research project's stage/source facts for overview UX.

    Only the active project is supported (same boundary as source/progress reset).
    """

    from core.web.services import team_workflow_orchestration_service as workflow
    from core.web.services.team_workflow.source_collection.runs import (
        _candidate_belongs_to_research_project,
        _project_source_collection_run_ids,
        _stage_round_belongs_to_research_project,
    )

    normalized_team_id = str(team_id or "").strip()
    team_service.get_team(normalized_team_id)
    active_project = get_active_research_project(normalized_team_id)
    requested_project_id = str(project_id or "").strip()
    if requested_project_id and requested_project_id != str(active_project.get("projectId") or ""):
        raise ResearchProjectError(
            "Research project progress is only available for the active research project."
        )
    normalized_project_id = str(active_project.get("projectId") or "").strip()
    run_ids = _project_source_collection_run_ids(normalized_team_id, normalized_project_id)
    stage_status = workflow.get_research_stage_round_status(normalized_team_id)
    # Prefer full store rounds for counts (activeRounds alone undercounts).
    with workflow._WORKFLOW_LOCK:
        stage_store = workflow._load_stage_round_store(normalized_team_id)
        all_rounds = workflow._stage_rounds(stage_store)
        candidate_store = workflow._load_candidate_store(normalized_team_id)
        plan_store = workflow._load_experiment_plan_store(normalized_team_id)
        workflow_record = workflow._load_or_create_workflow(normalized_team_id)
    project_rounds = [
        item
        for item in all_rounds
        if _stage_round_belongs_to_research_project(item, normalized_project_id, run_ids)
    ]
    stage_round_counts = {
        "knowledge_collection": 0,
        "experiment": 0,
        "iteration": 0,
    }
    for item in project_rounds:
        stage_type = str(item.get("stageType") or "").strip()
        if stage_type in stage_round_counts:
            stage_round_counts[stage_type] += 1

    candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    project_candidates = [
        item
        for item in candidates
        if _candidate_belongs_to_research_project(item, normalized_project_id, run_ids)
    ]
    source_candidate_count = sum(
        1 for item in project_candidates if str(item.get("candidateType") or "") == "source_manifest"
    )
    downstream_candidate_count = len(project_candidates) - source_candidate_count
    plans = [item for item in list(plan_store.get("plans") or []) if isinstance(item, dict)]
    project_plans = [
        item
        for item in plans
        if str(item.get("researchProjectId") or "").strip() == normalized_project_id
    ]
    frozen_plan_count = sum(
        1
        for item in project_plans
        if bool(item.get("designFrozen") or item.get("frozen") or str(item.get("status") or "").lower() in {"frozen", "design_frozen"})
    )
    # Rebuild phases from project-scoped rounds: the team-level stage status
    # mixes every project's rounds, which would leak other projects' active
    # rounds and readiness into this project's phase view.
    team_snapshot = workflow._source_collection_team_identity_snapshot(normalized_team_id)
    phases = [
        workflow._stage_phase_status(
            normalized_team_id,
            stage_type,
            project_rounds,
            workflow=workflow_record,
            team=team_snapshot,
        )
        for stage_type in workflow.RESEARCH_STAGE_TYPES
    ]
    current_stage = workflow._current_research_stage(phases, workflow_record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "researchProjectId": normalized_project_id,
        "experimentName": str(active_project.get("name") or ""),
        "sourceRunCount": len(run_ids),
        "sourceCandidateCount": source_candidate_count,
        "downstreamCandidateCount": max(0, downstream_candidate_count),
        "stageRoundCounts": stage_round_counts,
        "experimentPlanCount": len(project_plans),
        "frozenExperimentPlanCount": frozen_plan_count,
        "currentStage": current_stage,
        "phases": phases,
        "canResetSourceOnly": len(run_ids) > 0 and stage_round_counts["experiment"] == 0 and stage_round_counts["iteration"] == 0 and downstream_candidate_count == 0,
        "canResetProgress": len(run_ids) > 0 or sum(stage_round_counts.values()) > 0 or len(project_candidates) > 0 or len(project_plans) > 0,
        "updatedAt": str(stage_status.get("updatedAt") or active_project.get("updatedAt") or _utc_now()),
    }


def lock_research_project_name(
    team_id: str,
    project_id: str,
    *,
    reason: str = "first_experiment_session",
) -> dict[str, Any]:
    """Idempotently freeze the display name used by experiment session titles."""
    team_service.get_team(team_id)
    with _STORE_LOCK:
        store = _load_store(team_id)
        project = _project_payload(store, project_id)
        if not bool(project.get("nameLocked")):
            now = _utc_now()
            project["nameLocked"] = True
            project["nameLockedAt"] = now
            project["nameLockReason"] = str(reason or "first_experiment_session").strip()[:160]
            project["updatedAt"] = now
            _persist_store(team_id, store)
            _record_project_event("research_project.name_locked", team_id, project_id)
        return dict(project)


def resolve_research_project_workspace_root(team_id: str, project_id: str) -> Path:
    normalized_project_id = str(project_id or "").strip()
    with _STORE_LOCK:
        store = _load_store(team_id)
        _project_payload(store, normalized_project_id)
    base_root = formal_team_workspace_root(team_id)
    if normalized_project_id == LEGACY_PROJECT_ID:
        return base_root
    return base_root / "research_projects" / normalized_project_id / "workspace"


def resolve_team_program_root(team_id: str) -> Path:
    """Return the stable team-level root for cross-project program ledgers."""
    team_service.assert_team_exists(team_id)
    return formal_team_workspace_root(team_id)


def resolve_team_workflow_root(team_id: str) -> Path:
    """Resolve the canonical workflow root for the team's active research project."""
    with _STORE_LOCK:
        store = _load_store(team_id)
        active_project_id = store["activeProjectId"]
    return resolve_research_project_workspace_root(team_id, active_project_id)


def _challenge_cup_reset_value(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ResearchProjectError(f"{field} is required")
    return normalized


def _challenge_cup_workspace_reset_root(team_id: str, reset_id: str) -> Path:
    root = formal_team_workspace_root(team_id).resolve(strict=False)
    candidate = (root / ".challenge_cup_reset_staging" / reset_id).resolve(strict=False)
    if not candidate.is_relative_to(root):
        raise ResearchProjectError("Challenge Cup reset staging path is unsafe")
    return candidate


def list_challenge_cup_experiment_state(team_id: str) -> list[dict[str, Any]]:
    """Read the bounded reset allowlist without walking unrelated team state."""

    if str(team_id or "").strip() != CHALLENGE_CUP_RESET_TEAM_ID:
        raise ResearchProjectError("Challenge Cup reset is restricted to research-team")
    root = formal_team_workspace_root(team_id)
    result: list[dict[str, Any]] = []
    for name in CHALLENGE_CUP_EXPERIMENT_STATE_ENTRIES:
        path = root / name
        if path.exists() or path.is_symlink():
            result.append({"id": name, "teamId": team_id, "kind": "team_experiment_state"})
    return result


def _challenge_cup_workspace_stage_summary(stage: dict[str, Any]) -> dict[str, Any]:
    entries = stage.get("entries") if isinstance(stage.get("entries"), list) else []
    return {
        "kind": "challenge_cup_workspace_reset",
        "schemaVersion": 1,
        "stageId": str(stage["stageId"]),
        "resetId": str(stage["resetId"]),
        "teamId": str(stage["teamId"]),
        "status": str(stage.get("status") or "staged"),
        "entryCount": len(entries),
        "entryIds": [str(item.get("name") or "") for item in entries],
    }


def _challenge_cup_workspace_stage(stage: dict[str, Any], *, reset_id: str | None = None) -> dict[str, Any]:
    if not isinstance(stage, dict) or stage.get("kind") != "challenge_cup_workspace_reset" or stage.get("schemaVersion") != 1:
        raise ResearchProjectError("Challenge Cup workspace reset stage schema is invalid")
    stage_id = _challenge_cup_reset_value(stage.get("stageId"), field="stageId")
    cached = _CHALLENGE_CUP_WORKSPACE_RESET_STAGES.get(stage_id)
    if cached is None:
        raise ResearchProjectError("Challenge Cup workspace reset stage is unavailable")
    for key in ("resetId", "teamId"):
        if str(stage.get(key) or "") != str(cached.get(key) or ""):
            raise ResearchProjectError(f"Challenge Cup workspace reset stage {key} does not match")
    if reset_id is not None and str(reset_id).strip() != str(cached["resetId"]):
        raise ResearchProjectError("Challenge Cup workspace reset stage resetId does not match")
    return cached


def prepare_challenge_cup_experiment_state_reset(
    team_id: str,
    *,
    reset_id: str,
    entry_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Move only the fixed experiment-state allowlist into recoverable staging.

    Team identity, roles, canvas, Program and workflow artifacts are outside
    this port.  They have their own authorities or are explicitly retained.
    """

    team = _challenge_cup_reset_value(team_id, field="teamId")
    reset = _challenge_cup_reset_value(reset_id, field="resetId")
    if team != CHALLENGE_CUP_RESET_TEAM_ID:
        raise ResearchProjectError("Challenge Cup reset is restricted to research-team")
    requested = {str(value or "").strip() for value in (entry_ids or [])}
    if "" in requested or not requested.issubset(set(CHALLENGE_CUP_EXPERIMENT_STATE_ENTRIES)):
        raise ResearchProjectError("Challenge Cup workspace reset plan is invalid")
    with _STORE_LOCK:
        root = formal_team_workspace_root(team).resolve(strict=False)
        current = {item["id"] for item in list_challenge_cup_experiment_state(team)}
        if requested and requested != current:
            raise ResearchProjectError("Challenge Cup workspace reset plan does not match current experiment state")
        staging_root = _challenge_cup_workspace_reset_root(team, reset)
        if staging_root.exists():
            raise ResearchProjectError("Challenge Cup workspace reset staging already exists")
        staging_root.mkdir(parents=True, exist_ok=False)
        entries = [{"name": name} for name in sorted(current)]
        stage = {
            "kind": "challenge_cup_workspace_reset",
            "schemaVersion": 1,
            "stageId": f"team-workspace-stage-{uuid.uuid4().hex}",
            "resetId": reset,
            "teamId": team,
            "entries": entries,
            "stagingRoot": str(staging_root),
            "status": "preparing",
        }
        _write_json(staging_root / "manifest.json", stage)
        moved: list[str] = []
        try:
            for entry in entries:
                name = str(entry["name"])
                source = (root / name).resolve(strict=False)
                destination = (staging_root / name).resolve(strict=False)
                if not source.is_relative_to(root) or not destination.is_relative_to(staging_root):
                    raise ResearchProjectError("Challenge Cup workspace reset path is unsafe")
                os.replace(source, destination)
                moved.append(name)
        except Exception as exc:
            for name in reversed(moved):
                source = (root / name).resolve(strict=False)
                destination = (staging_root / name).resolve(strict=False)
                if destination.exists() and not source.exists():
                    os.replace(destination, source)
            shutil.rmtree(staging_root, ignore_errors=True)
            raise ResearchProjectError("Challenge Cup workspace staging failed and was restored") from exc
        stage["status"] = "staged"
        _write_json(staging_root / "manifest.json", stage)
        _CHALLENGE_CUP_WORKSPACE_RESET_STAGES[str(stage["stageId"])] = stage
        return _challenge_cup_workspace_stage_summary(stage)


def purge_challenge_cup_experiment_state_reset(
    stage: dict[str, Any],
    *,
    reset_id: str | None = None,
) -> dict[str, Any]:
    """Mark staged team experiment state committed without destroying recovery data."""

    with _STORE_LOCK:
        cached = _challenge_cup_workspace_stage(stage, reset_id=reset_id)
        if cached.get("status") == "destroyed":
            raise ResearchProjectError("A finalized workspace reset cannot be purged")
        root = formal_team_workspace_root(str(cached["teamId"])).resolve(strict=False)
        staging_root = Path(str(cached["stagingRoot"])).resolve(strict=False)
        for entry in cached.get("entries") or []:
            name = str(entry.get("name") or "")
            if (root / name).exists() or not (staging_root / name).exists():
                raise ResearchProjectError("Challenge Cup workspace changed after reset staging")
        cached["status"] = "purged"
        _write_json(staging_root / "manifest.json", cached)
        return {**_challenge_cup_workspace_stage_summary(cached), "operation": "purge"}


def restore_challenge_cup_experiment_state_reset(
    stage: dict[str, Any],
    *,
    reset_id: str | None = None,
) -> dict[str, Any]:
    """Move recoverable experiment state back after a later port failure."""

    with _STORE_LOCK:
        cached = _challenge_cup_workspace_stage(stage, reset_id=reset_id)
        if cached.get("status") == "destroyed":
            raise ResearchProjectError("A finalized workspace reset cannot be restored")
        root = formal_team_workspace_root(str(cached["teamId"])).resolve(strict=False)
        staging_root = Path(str(cached["stagingRoot"])).resolve(strict=False)
        moved: list[str] = []
        try:
            for entry in cached.get("entries") or []:
                name = str(entry.get("name") or "")
                source = (root / name).resolve(strict=False)
                destination = (staging_root / name).resolve(strict=False)
                if source.exists():
                    raise ResearchProjectError("Challenge Cup workspace restore conflicts with current state")
                if destination.exists():
                    os.replace(destination, source)
                    moved.append(name)
        except Exception as exc:
            for name in reversed(moved):
                source = (root / name).resolve(strict=False)
                destination = (staging_root / name).resolve(strict=False)
                if source.exists() and not destination.exists():
                    os.replace(source, destination)
            raise ResearchProjectError("Challenge Cup workspace restore failed") from exc
        cached["status"] = "restored"
        _write_json(staging_root / "manifest.json", cached)
        return {**_challenge_cup_workspace_stage_summary(cached), "operation": "restore", "restoredCount": len(moved)}


def discard_restored_challenge_cup_experiment_state_reset(
    team_id: str,
    *,
    reset_id: str,
) -> dict[str, Any]:
    """Discard a fully restored, reset-owned workspace staging directory.

    This is recovery cleanup, not reset finalization: it only accepts the
    durable ``restored`` state after every allowlisted entry is back in its
    canonical workspace, allowing the same preview plan to retry safely.
    """

    team = _challenge_cup_reset_value(team_id, field="teamId")
    reset = _challenge_cup_reset_value(reset_id, field="resetId")
    if team != CHALLENGE_CUP_RESET_TEAM_ID:
        raise ResearchProjectError("Challenge Cup reset is restricted to research-team")
    with _STORE_LOCK:
        root = formal_team_workspace_root(team).resolve(strict=False)
        staging_root = _challenge_cup_workspace_reset_root(team, reset)
        if not staging_root.exists():
            return {
                "status": "absent",
                "teamId": team,
                "resetId": reset,
                "stagingDestroyed": False,
            }
        if staging_root.is_symlink():
            raise ResearchProjectError("Challenge Cup workspace recovery staging is unsafe")
        manifest_path = staging_root / "manifest.json"
        manifest = _read_json(manifest_path)
        if (
            manifest.get("kind") != "challenge_cup_workspace_reset"
            or manifest.get("schemaVersion") != 1
            or str(manifest.get("teamId") or "") != team
            or str(manifest.get("resetId") or "") != reset
            or str(manifest.get("status") or "") != "restored"
        ):
            raise ResearchProjectError("Challenge Cup workspace staging is not a verified restored reset")
        entries = manifest.get("entries") if isinstance(manifest.get("entries"), list) else []
        names = [str(entry.get("name") or "") for entry in entries if isinstance(entry, dict)]
        if (
            len(names) != len(entries)
            or len(set(names)) != len(names)
            or any(not name for name in names)
            or not set(names).issubset(set(CHALLENGE_CUP_EXPERIMENT_STATE_ENTRIES))
        ):
            raise ResearchProjectError("Challenge Cup workspace recovery authority is invalid")
        for name in names:
            source = (root / name).resolve(strict=False)
            staged = (staging_root / name).resolve(strict=False)
            if not source.is_relative_to(root) or not staged.is_relative_to(staging_root):
                raise ResearchProjectError("Challenge Cup workspace recovery path is unsafe")
            if not source.exists() or staged.exists():
                raise ResearchProjectError("Challenge Cup workspace was not fully restored")
        unexpected = [path for path in staging_root.iterdir() if path.name != "manifest.json"]
        if unexpected:
            raise ResearchProjectError("Challenge Cup workspace staging still contains recoverable data")
        shutil.rmtree(staging_root)
        for stage_id, cached in list(_CHALLENGE_CUP_WORKSPACE_RESET_STAGES.items()):
            if str(cached.get("teamId") or "") == team and str(cached.get("resetId") or "") == reset:
                _CHALLENGE_CUP_WORKSPACE_RESET_STAGES.pop(stage_id, None)
        return {
            "status": "discarded",
            "teamId": team,
            "resetId": reset,
            "entryCount": len(names),
            "stagingDestroyed": True,
        }


def destroy_challenge_cup_experiment_state_reset(
    stage: dict[str, Any],
    *,
    reset_id: str | None = None,
) -> dict[str, Any]:
    """Destroy only the reset-owned staging directory after successful bootstrap."""

    with _STORE_LOCK:
        cached = _challenge_cup_workspace_stage(stage, reset_id=reset_id)
        if cached.get("status") not in {"purged", "destroyed"}:
            raise ResearchProjectError("Only a purged workspace reset can be finalized")
        staging_root = Path(str(cached["stagingRoot"])).resolve(strict=False)
        expected = _challenge_cup_workspace_reset_root(str(cached["teamId"]), str(cached["resetId"])).resolve(strict=False)
        if staging_root != expected:
            raise ResearchProjectError("Challenge Cup workspace staging path changed")
        if staging_root.exists():
            _destroy_challenge_cup_workspace_staging(staging_root)
        cached["status"] = "destroyed"
        cached["entries"] = []
        return _challenge_cup_workspace_stage_summary(cached)


def _destroy_challenge_cup_workspace_staging(staging_root: Path) -> None:
    """Destroy a verified staging tree even when its Windows path is long."""

    target = _challenge_cup_workspace_reset_native_path(staging_root)

    for attempt in range(2):
        if not staging_root.exists():
            return
        try:
            shutil.rmtree(target)
        except FileNotFoundError:
            if attempt:
                raise
        if not staging_root.exists():
            return
    raise ResearchProjectError("Challenge Cup workspace staging cleanup is incomplete")


def _challenge_cup_workspace_reset_native_path(path: Path) -> str:
    """Use the Windows extended path syntax only for an already-validated root."""

    value = str(path.resolve(strict=False))
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    return "\\\\?\\" + value


def _challenge_cup_workspace_reset_path_is_reparse_point(path: Path) -> bool:
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0) or 0)
    except OSError:
        return False
    return bool(attributes & 0x400)


def destroy_orphaned_purged_challenge_cup_experiment_state_reset_staging(
    team_id: str,
    *,
    reset_id: str,
) -> dict[str, Any]:
    """Finalize a durable purged workspace stage whose coordinator is gone."""

    team = _challenge_cup_reset_value(team_id, field="teamId")
    reset = _challenge_cup_reset_value(reset_id, field="resetId")
    if team != CHALLENGE_CUP_RESET_TEAM_ID:
        raise ResearchProjectError("Challenge Cup reset is restricted to research-team")
    with _STORE_LOCK:
        root = formal_team_workspace_root(team).resolve(strict=False)
        staging_root = _challenge_cup_workspace_reset_root(team, reset)
        if not staging_root.exists():
            return {
                "status": "absent",
                "teamId": team,
                "resetId": reset,
                "stagingDestroyed": False,
            }
        if staging_root.is_symlink() or _challenge_cup_workspace_reset_path_is_reparse_point(staging_root):
            raise ResearchProjectError("Challenge Cup workspace orphaned staging is unsafe")
        manifest = _read_json(staging_root / "manifest.json")
        if (
            manifest.get("kind") != "challenge_cup_workspace_reset"
            or manifest.get("schemaVersion") != 1
            or str(manifest.get("teamId") or "") != team
            or str(manifest.get("resetId") or "") != reset
            or str(manifest.get("status") or "") != "purged"
            or Path(str(manifest.get("stagingRoot") or "")).resolve(strict=False) != staging_root
        ):
            raise ResearchProjectError("Challenge Cup workspace staging is not a verified purged reset")
        entries = manifest.get("entries") if isinstance(manifest.get("entries"), list) else []
        names = [str(entry.get("name") or "") for entry in entries if isinstance(entry, dict)]
        if (
            len(names) != len(entries)
            or len(set(names)) != len(names)
            or any(not name for name in names)
            or not set(names).issubset(set(CHALLENGE_CUP_EXPERIMENT_STATE_ENTRIES))
        ):
            raise ResearchProjectError("Challenge Cup workspace orphaned staging authority is invalid")
        expected_entries = {"manifest.json", *names}
        if any(path.name not in expected_entries for path in staging_root.iterdir()):
            raise ResearchProjectError("Challenge Cup workspace orphaned staging contains unexpected data")
        for name in names:
            staged = (staging_root / name).resolve(strict=False)
            if not staged.is_relative_to(staging_root) or (
                staged.exists()
                and (staged.is_symlink() or _challenge_cup_workspace_reset_path_is_reparse_point(staged))
            ):
                raise ResearchProjectError("Challenge Cup workspace orphaned staging path is unsafe")
        _destroy_challenge_cup_workspace_staging(staging_root)
        for stage_id, cached in list(_CHALLENGE_CUP_WORKSPACE_RESET_STAGES.items()):
            if str(cached.get("teamId") or "") == team and str(cached.get("resetId") or "") == reset:
                _CHALLENGE_CUP_WORKSPACE_RESET_STAGES.pop(stage_id, None)
        return {
            "status": "destroyed",
            "teamId": team,
            "resetId": reset,
            "entryCount": len(names),
            "stagingDestroyed": True,
        }


def _record_project_event(event_name: str, team_id: str, project_id: str) -> None:
    try:
        record_runtime_scene_event(
            "team_workflow_orchestration",
            "research_project",
            event_name,
            outcome="succeeded",
            fields={
                "teamId": str(team_id)[:160],
                "projectId": str(project_id)[:160],
            },
        )
    except Exception:
        return
