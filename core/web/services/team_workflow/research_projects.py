"""Team-scoped research project registry and active workspace resolver."""

from __future__ import annotations

import json
import os
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
    return "".join(character if character.isalnum() or character in "._-" else "_" for character in str(team_id or ""))[:96] or "team"


def team_workspace_root(team_id: str) -> Path:
    return developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "teams",
        _safe_team_id(team_id),
    )


def _store_path(team_id: str) -> Path:
    return team_workspace_root(team_id) / "research_projects" / "index.json"


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
    phases = list(stage_status.get("phases") or [])
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
        "currentStage": str(stage_status.get("currentStage") or ""),
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
    base_root = team_workspace_root(team_id)
    if normalized_project_id == LEGACY_PROJECT_ID:
        return base_root
    return base_root / "research_projects" / normalized_project_id / "workspace"


def resolve_team_program_root(team_id: str) -> Path:
    """Return the stable team-level root for cross-project program ledgers."""
    team_service.assert_team_exists(team_id)
    return team_workspace_root(team_id)


def resolve_team_workflow_root(team_id: str) -> Path:
    """Resolve the canonical workflow root for the team's active research project."""
    with _STORE_LOCK:
        store = _load_store(team_id)
        active_project_id = store["activeProjectId"]
    return resolve_research_project_workspace_root(team_id, active_project_id)


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
