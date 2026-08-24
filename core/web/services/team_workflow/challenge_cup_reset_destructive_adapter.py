"""Live, governed destructive adapter for the Challenge Cup reset service.

This is intentionally a composition layer: each state owner supplies its own
stage/purge/restore port.  The adapter never opens a JSON/SQLite data store or
walks an arbitrary data root itself.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.web.services.team_workflow.challenge_cup_reset_live_adapter import (
    build_live_challenge_cup_inventory_reader,
)
from core.web.services.team_workflow.challenge_cup_reset_service import (
    GOLDEN_SAMPLE_BOOTSTRAP_ID,
    GOLDEN_SAMPLE_PROJECT_ID,
    GOLDEN_SAMPLE_QUESTION_ID,
    RESEARCH_TEAM_ID,
    RETAINED_AGENT_ROLE_KEYS,
    ChallengeCupResetService,
)


_LOCK = threading.RLock()
_RESULT_KIND = "challenge_cup_reset_result"
_RESULT_SCHEMA_VERSION = 1


class ChallengeCupDestructiveAdapterError(RuntimeError):
    """Raised when a governed reset owner cannot prove its required scope."""


def _text(value: Any, *, field: str = "value") -> str:
    result = str(value or "").strip()
    if not result:
        raise ChallengeCupDestructiveAdapterError(f"{field} is required")
    return result


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _result_root() -> Path:
    from core.web.services.team_workflow.research_runtime.paths import research_workflow_data_root

    return research_workflow_data_root() / "challenge_cup_reset_results"


def _result_path(purge_plan_id: str) -> Path:
    normalized = _text(purge_plan_id, field="purgePlanId")
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized.lower()):
        raise ChallengeCupDestructiveAdapterError("purgePlanId must be a SHA-256 value")
    return _result_root() / f"{normalized.lower()}.json"


def _read_result(purge_plan_id: str) -> dict[str, Any] | None:
    path = _result_path(purge_plan_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ChallengeCupDestructiveAdapterError("reset result record cannot be read") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != _RESULT_SCHEMA_VERSION or payload.get("kind") != _RESULT_KIND:
        raise ChallengeCupDestructiveAdapterError("reset result record is invalid")
    if str(payload.get("purgePlanId") or "") != purge_plan_id:
        raise ChallengeCupDestructiveAdapterError("reset result record belongs to another plan")
    return payload


def _write_result(payload: Mapping[str, Any]) -> None:
    from core.web.services.team_workflow.research_runtime.atomic_fs import atomic_write_text

    plan_id = _text(payload.get("purgePlanId"), field="purgePlanId")
    path = _result_path(plan_id)
    safe = {
        "schemaVersion": _RESULT_SCHEMA_VERSION,
        "kind": _RESULT_KIND,
        "status": str(payload.get("status") or "succeeded"),
        "teamId": str(payload.get("teamId") or ""),
        "purgePlanId": plan_id,
        "inventoryHash": str(payload.get("inventoryHash") or ""),
        "otherTeamProtectionHash": str(payload.get("otherTeamProtectionHash") or ""),
        "deleteObjectCount": int(payload.get("deleteObjectCount") or 0),
        "bootstrapId": str(payload.get("bootstrapId") or ""),
        "completedAt": str(payload.get("completedAt") or ""),
    }
    atomic_write_text(path, json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _plan_ids(plan: Mapping[str, Any], family: str) -> list[str]:
    delete_set = plan.get("deleteSet") if isinstance(plan.get("deleteSet"), Mapping) else {}
    values = delete_set.get(family) if isinstance(delete_set.get(family), list) else []
    ids = [str(value or "").strip() for value in values]
    if any(not value for value in ids):
        raise ChallengeCupDestructiveAdapterError(f"reset plan contains an empty {family} id")
    return sorted(set(ids))


def _retained_agent_ids(plan: Mapping[str, Any]) -> list[str]:
    retained = plan.get("retained") if isinstance(plan.get("retained"), Mapping) else {}
    agents = retained.get("agents") if isinstance(retained.get("agents"), list) else []
    by_role: dict[str, str] = {}
    for agent in agents:
        if not isinstance(agent, Mapping):
            raise ChallengeCupDestructiveAdapterError("retained Agent authority is invalid")
        role = str(agent.get("roleKey") or "").strip()
        agent_id = str(agent.get("agentId") or "").strip()
        if not role or not agent_id or role in by_role:
            raise ChallengeCupDestructiveAdapterError("retained Agent authority is incomplete")
        by_role[role] = agent_id
    if tuple(sorted(by_role)) != tuple(sorted(RETAINED_AGENT_ROLE_KEYS)):
        raise ChallengeCupDestructiveAdapterError("the six retained Challenge Cup Agents are not authoritative")
    return [by_role[role] for role in RETAINED_AGENT_ROLE_KEYS]


def _run_scope_authority(team_id: str) -> list[dict[str, str]]:
    # The inventory reader owns the same exact scope extraction used by the
    # receipt/checkpoint readers.  Reusing it avoids a second interpretation
    # of formal run authority in this orchestration module.
    from core.web.services.team_workflow.challenge_cup_reset_live_adapter import _run_scope_rows

    return _run_scope_rows(team_id)


class ChallengeCupLiveDestructiveAdapter:
    """Bind the reset service to real, team-scoped owner ports."""

    def __init__(self) -> None:
        self._stages: dict[str, dict[str, Any]] = {}

    def lookup_completed(self, purge_plan_id: str) -> Mapping[str, Any] | None:
        with _LOCK:
            result = _read_result(purge_plan_id)
        return dict(result) if result and result.get("status") == "succeeded" else None

    def fence(self, team_id: str, plan: Mapping[str, Any]) -> Mapping[str, Any]:
        self._assert_plan(team_id, plan)
        from core.web.services.team_workflow.research_runtime.challenge_cup_maintenance_fence import acquire_fence

        return acquire_fence(
            team_id,
            purge_plan_id=str(plan["purgePlanId"]),
            inventory_hash=str(plan["inventoryHash"]),
            acquired_by="challenge_cup_governed_reset",
        )

    def drain_check(self, team_id: str, plan: Mapping[str, Any]) -> Mapping[str, Any]:
        self._assert_plan(team_id, plan)
        inventory = build_live_challenge_cup_inventory_reader().read_inventory(team_id)
        active = inventory.get("activeWork") if isinstance(inventory.get("activeWork"), Mapping) else {}
        return {
            "authorityPresent": bool(active.get("authorityPresent")),
            "activeCount": int(active.get("activeCount") or 0),
            "items": list(active.get("items") or []),
            "statuses": dict(active.get("statuses") or {}),
        }

    def stage(self, team_id: str, plan: Mapping[str, Any]) -> Mapping[str, Any]:
        self._assert_plan(team_id, plan)
        plan_id = str(plan["purgePlanId"])
        with _LOCK:
            existing = self._stages.get(plan_id)
            if existing is not None:
                return self._stage_summary(existing)
        self._discard_recovered_staging(team_id, plan_id)

        from core.research.workflow.checkpoint_store import prepare_checkpoint_reset_stage
        from core.research.workflow.ledger import prepare_team_ledger_reset_stage
        from core.research.workflow.ledger import WorkflowLedgerStore
        from core.web.services.chat_room_service import prepare_team_chat_room_reset
        from core.web.services.session.agent_sessions import stage_team_agent_session_reset
        from core.web.services.team_workflow.research_projects import prepare_challenge_cup_experiment_state_reset
        from core.web.services.team_workflow.research_runtime.model_invocation_receipt_registry import prepare_model_invocation_receipt_reset_stage
        from core.web.services.team_workflow.research_runtime.paths import workflow_ledger_path
        from core.web.services.team_workflow.research_runtime.workflow_artifact_store import prepare_workflow_artifact_reset

        handles: dict[str, Any] = {}
        completed: list[str] = []
        temporary_store: WorkflowLedgerStore | None = None
        # Artifact staging removes the canonical legacy run evidence from the
        # active store.  Resolve all checkpoint/receipt scope authority before
        # any owner moves its recoverable data into staging, then retain that
        # exact proof in the stage for commit and compensation.
        authority = _run_scope_authority(team_id)
        checkpoint_ids = _plan_ids(plan, "checkpoints")
        receipt_ids = _plan_ids(plan, "receipts")
        receipt_authority = [
            {"teamId": team_id, "questionId": item["questionId"], "workflowRunId": item["runId"]}
            for item in authority
            if item.get("questionId")
        ]
        handles["_scopeAuthority"] = authority
        handles["_receiptScopeAuthority"] = receipt_authority
        try:
            handles["rooms"] = prepare_team_chat_room_reset(
                team_id,
                reset_id=plan_id,
                room_ids=_plan_ids(plan, "rooms"),
            )
            completed.append("rooms")
            handles["sessions"] = stage_team_agent_session_reset(
                team_id,
                _retained_agent_ids(plan),
                plan_id,
            )
            completed.append("sessions")
            handles["workspace"] = prepare_challenge_cup_experiment_state_reset(
                team_id,
                reset_id=plan_id,
                entry_ids=_plan_ids(plan, "workspace_state"),
            )
            completed.append("workspace")
            handles["artifacts"] = prepare_workflow_artifact_reset(
                team_id,
                reset_id=plan_id,
                plan=plan,
            )
            completed.append("artifacts")
            if checkpoint_ids:
                handles["checkpoints"] = prepare_checkpoint_reset_stage(
                    team_id,
                    plan_id,
                    scope_authority=authority,
                )
                completed.append("checkpoints")
            if receipt_ids:
                handles["receipts"] = prepare_model_invocation_receipt_reset_stage(
                    team_id,
                    plan_id,
                    scope_authority=receipt_authority,
                )
                completed.append("receipts")
            store, temporary_store = self._ledger_store(workflow_ledger_path())
            handles["ledger"] = prepare_team_ledger_reset_stage(store, team_id, plan_id)
            completed.append("ledger")
        except Exception:
            try:
                self._restore_handles(
                    team_id,
                    plan_id,
                    handles,
                    reversed(completed),
                    temporary_store=temporary_store,
                )
                self._discard_recovered_staging(team_id, plan_id)
            except Exception as recovery_exc:
                raise ChallengeCupDestructiveAdapterError(
                    "Reset staging failed and recovered staging cleanup was incomplete."
                ) from recovery_exc
            raise
        finally:
            if temporary_store is not None:
                temporary_store.close()
        stage = {
            "planId": plan_id,
            "teamId": team_id,
            "handles": handles,
            "scopeAuthority": authority,
            "receiptScopeAuthority": receipt_authority,
            "status": "staged",
        }
        with _LOCK:
            self._stages[plan_id] = stage
        return self._stage_summary(stage)

    def commit(self, team_id: str, plan: Mapping[str, Any], stage: Mapping[str, Any]) -> Mapping[str, Any]:
        self._assert_plan(team_id, plan)
        current = self._stage(plan, stage)
        from core.research.workflow.checkpoint_store import purge_checkpoint_reset_stage
        from core.research.workflow.ledger import purge_team_ledger_reset_stage
        from core.web.services.chat_room_service import purge_team_chat_room_reset
        from core.web.services.session.agent_sessions import purge_team_agent_session_reset
        from core.web.services.team_workflow.research_projects import purge_challenge_cup_experiment_state_reset
        from core.web.services.team_workflow.research_runtime.model_invocation_receipt_registry import purge_model_invocation_receipt_reset_stage
        from core.web.services.team_workflow.research_runtime.paths import workflow_ledger_path
        from core.web.services.team_workflow.research_runtime.workflow_artifact_store import purge_workflow_artifact_reset

        handles = current["handles"]
        authority = list(current.get("scopeAuthority") or [])
        receipt_authority = list(current.get("receiptScopeAuthority") or [])
        store, temporary_store = self._ledger_store(workflow_ledger_path())
        try:
            results = {
                "rooms": purge_team_chat_room_reset(handles["rooms"], reset_id=current["planId"]),
                "sessions": purge_team_agent_session_reset(team_id, current["planId"], handles["sessions"]),
                "workspace": purge_challenge_cup_experiment_state_reset(handles["workspace"], reset_id=current["planId"]),
                "artifacts": purge_workflow_artifact_reset(team_id, reset_id=current["planId"], stage=handles["artifacts"]),
            }
            if "checkpoints" in handles:
                results["checkpoints"] = purge_checkpoint_reset_stage(
                    handles["checkpoints"], scope_authority=authority, reset_id=current["planId"]
                )
            if "receipts" in handles:
                results["receipts"] = purge_model_invocation_receipt_reset_stage(
                    handles["receipts"],
                    scope_authority=receipt_authority,
                    reset_id=current["planId"],
                )
            results["ledger"] = purge_team_ledger_reset_stage(
                store, handles["ledger"], reset_id=current["planId"]
            )
        finally:
            if temporary_store is not None:
                temporary_store.close()
        current["status"] = "purged"
        return {**self._stage_summary(current), "ports": results}

    def restore(self, team_id: str, plan: Mapping[str, Any], stage: Mapping[str, Any]) -> Mapping[str, Any]:
        self._assert_plan(team_id, plan)
        current = self._stage(plan, stage)
        self._restore_handles(team_id, current["planId"], current["handles"], ("ledger", "receipts", "checkpoints", "artifacts", "workspace", "sessions", "rooms"))
        self._discard_recovered_staging(team_id, current["planId"])
        current["status"] = "restored"
        summary = self._stage_summary(current)
        with _LOCK:
            self._stages.pop(current["planId"], None)
        return summary

    def verify_zero(self, team_id: str, plan: Mapping[str, Any]) -> Mapping[str, Any]:
        self._assert_plan(team_id, plan)
        preview = ChallengeCupResetService(
            inventory_reader=build_live_challenge_cup_inventory_reader()
        ).preview(team_id).to_dict()
        remaining = dict(preview.get("impact", {}).get("familyCounts") or {})
        return {
            "verified": bool(preview.get("safeToConfirm")) and not remaining,
            "remainingCount": sum(int(value or 0) for value in remaining.values()),
            "remaining": remaining,
        }

    def rebootstrap(self, team_id: str, plan: Mapping[str, Any]) -> Mapping[str, Any]:
        self._assert_plan(team_id, plan)
        from core.research.competition.resources import load_science_question_catalog
        from core.web.services import agent_directory_service, session_service
        from core.web.services.team_workflow.research_projects import ensure_challenge_question_project

        catalog = load_science_question_catalog()
        questions = catalog.get("questions") if isinstance(catalog, Mapping) else []
        question = next(
            (
                item for item in questions
                if isinstance(item, Mapping)
                and str(
                    item.get("id") or item.get("question_id") or item.get("questionId") or ""
                ).strip().upper()
                == GOLDEN_SAMPLE_QUESTION_ID
            ),
            None,
        )
        if not isinstance(question, Mapping):
            raise ChallengeCupDestructiveAdapterError("SCI-096 is missing from the immutable catalog")
        title = str(question.get("question_en") or question.get("question") or question.get("title") or "").strip()
        if not title:
            raise ChallengeCupDestructiveAdapterError("SCI-096 title is missing from the immutable catalog")
        project = ensure_challenge_question_project(
            team_id,
            question_id=GOLDEN_SAMPLE_QUESTION_ID,
            title=title,
            topic=title,
        )
        direct_sessions: list[str] = []
        for agent_id in _retained_agent_ids(plan):
            agent = agent_directory_service.get_agent(agent_id, include_archived=False)
            if not isinstance(agent, Mapping):
                raise ChallengeCupDestructiveAdapterError("retained Agent disappeared during rebootstrap")
            role_label = str(agent.get("name") or agent.get("roleKey") or agent_id).strip()
            session_service.update_agent_instance(agent_id, direct_session_id="")
            created = session_service.ensure_agent_direct_session(
                agent_id=agent_id,
                title=role_label,
                created_by="challenge_cup_reset_rebootstrap",
                conversation_index_kind=agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
            )
            direct_session_id = str(created.get("id") or created.get("sessionId") or "").strip() if isinstance(created, Mapping) else ""
            if not direct_session_id:
                raise ChallengeCupDestructiveAdapterError("rebootstrap did not create a retained Agent direct session")
            direct_sessions.append(direct_session_id)
        return {
            "projectId": str((project.get("project") or {}).get("projectId") or ""),
            "questionId": GOLDEN_SAMPLE_QUESTION_ID,
            "bootstrapId": GOLDEN_SAMPLE_BOOTSTRAP_ID,
            "status": "initialized",
            "directSessionCount": len(direct_sessions),
            "counts": {key: 0 for key in ("plans", "runs", "results", "rooms", "checkpoints", "artifacts", "receipts", "candidates", "selections", "meetings", "rounds", "legacyParticipantBindings")},
        }

    def destroy_staging(self, team_id: str, plan: Mapping[str, Any], stage: Mapping[str, Any]) -> Mapping[str, Any]:
        self._assert_plan(team_id, plan)
        current = self._stage(plan, stage)
        if current.get("status") not in {"purged", "destroyed"}:
            raise ChallengeCupDestructiveAdapterError("only a purged reset stage can be finalized")
        from core.research.workflow.checkpoint_store import destroy_checkpoint_reset_stage
        from core.research.workflow.ledger import destroy_team_ledger_reset_stage
        from core.web.services.chat_room_service import destroy_team_chat_room_reset
        from core.web.services.session.agent_sessions import destroy_team_agent_session_reset
        from core.web.services.team_workflow.research_projects import destroy_challenge_cup_experiment_state_reset
        from core.web.services.team_workflow.research_runtime.challenge_cup_maintenance_fence import release_fence
        from core.web.services.team_workflow.research_runtime.model_invocation_receipt_registry import destroy_model_invocation_receipt_reset_stage
        from core.web.services.team_workflow.research_runtime.workflow_artifact_store import destroy_workflow_artifact_reset

        handles = current["handles"]
        results = {
            "ledger": destroy_team_ledger_reset_stage(handles["ledger"], reset_id=current["planId"]),
        }
        if "receipts" in handles:
            results["receipts"] = destroy_model_invocation_receipt_reset_stage(
                handles["receipts"], reset_id=current["planId"]
            )
        if "checkpoints" in handles:
            results["checkpoints"] = destroy_checkpoint_reset_stage(
                handles["checkpoints"], reset_id=current["planId"]
            )
        results.update(
            {
                "artifacts": destroy_workflow_artifact_reset(team_id, reset_id=current["planId"], stage=handles["artifacts"]),
                "workspace": destroy_challenge_cup_experiment_state_reset(handles["workspace"], reset_id=current["planId"]),
                "sessions": destroy_team_agent_session_reset(team_id, current["planId"], handles["sessions"]),
                "rooms": destroy_team_chat_room_reset(handles["rooms"], reset_id=current["planId"]),
            }
        )
        result = {
            "schemaVersion": _RESULT_SCHEMA_VERSION,
            "kind": _RESULT_KIND,
            "status": "succeeded",
            "teamId": team_id,
            "purgePlanId": current["planId"],
            "inventoryHash": str(plan["inventoryHash"]),
            "otherTeamProtectionHash": str(plan.get("otherTeamProtectionHash") or ""),
            "deleteObjectCount": int((plan.get("impact") or {}).get("deleteObjectCount") or 0),
            "bootstrapId": GOLDEN_SAMPLE_BOOTSTRAP_ID,
            "completedAt": "completed",
        }
        _write_result(result)
        fence = release_fence(team_id, purge_plan_id=current["planId"], inventory_hash=str(plan["inventoryHash"]))
        current["status"] = "destroyed"
        return {"destroyed": True, "ports": results, "fence": fence}

    def _ledger_store(self, path: Path):
        from core.research.workflow.ledger import WorkflowLedgerStore
        from core.web.services.team_workflow.research_runtime.runtime_factory import production_workflow_runtime

        runtime = production_workflow_runtime()
        if runtime is not None:
            if runtime.store.path.resolve(strict=False) != path.resolve(strict=False):
                raise ChallengeCupDestructiveAdapterError("the active workflow runtime uses another ledger path")
            return runtime.store, None
        temporary = WorkflowLedgerStore(path, queue_size=8, enqueue_timeout_ms=250)
        temporary.open()
        return temporary, temporary

    def _restore_handles(
        self,
        team_id: str,
        plan_id: str,
        handles: Mapping[str, Any],
        order: Any,
        *,
        temporary_store: Any | None = None,
    ) -> None:
        from core.research.workflow.checkpoint_store import restore_checkpoint_reset_stage
        from core.research.workflow.ledger import restore_team_ledger_reset_stage
        from core.web.services.chat_room_service import restore_team_chat_room_reset
        from core.web.services.session.agent_sessions import restore_team_agent_session_reset
        from core.web.services.team_workflow.research_projects import restore_challenge_cup_experiment_state_reset
        from core.web.services.team_workflow.research_runtime.model_invocation_receipt_registry import restore_model_invocation_receipt_reset_stage
        from core.web.services.team_workflow.research_runtime.paths import workflow_ledger_path
        from core.web.services.team_workflow.research_runtime.workflow_artifact_store import restore_workflow_artifact_reset

        current_stage = self._stages.get(plan_id) or {}
        authority = list(current_stage.get("scopeAuthority") or handles.get("_scopeAuthority") or [])
        receipt_authority = list(current_stage.get("receiptScopeAuthority") or handles.get("_receiptScopeAuthority") or [])
        store = temporary_store
        temporary = None
        if store is None:
            store, temporary = self._ledger_store(workflow_ledger_path())
        try:
            for name in order:
                if name not in handles:
                    continue
                if name == "ledger":
                    restore_team_ledger_reset_stage(store, handles[name], reset_id=plan_id)
                elif name == "receipts":
                    restore_model_invocation_receipt_reset_stage(handles[name], scope_authority=receipt_authority, reset_id=plan_id)
                elif name == "checkpoints":
                    restore_checkpoint_reset_stage(handles[name], scope_authority=authority, reset_id=plan_id)
                elif name == "artifacts":
                    restore_workflow_artifact_reset(team_id, reset_id=plan_id, stage=handles[name])
                elif name == "workspace":
                    restore_challenge_cup_experiment_state_reset(handles[name], reset_id=plan_id)
                elif name == "sessions":
                    restore_team_agent_session_reset(team_id, plan_id, handles[name])
                elif name == "rooms":
                    restore_team_chat_room_reset(handles[name], reset_id=plan_id)
        finally:
            if temporary is not None:
                temporary.close()

    def _discard_recovered_staging(self, team_id: str, plan_id: str) -> dict[str, Any]:
        """Let each owner drop only its verified-restored recovery material."""

        from core.web.services.session.agent_sessions import (
            discard_restored_team_agent_session_reset_staging,
        )
        from core.web.services.team_workflow.research_projects import (
            discard_restored_challenge_cup_experiment_state_reset,
        )
        from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
            discard_restored_workflow_artifact_reset,
        )

        return {
            "artifacts": discard_restored_workflow_artifact_reset(
                team_id, reset_id=plan_id
            ),
            "workspace": discard_restored_challenge_cup_experiment_state_reset(
                team_id, reset_id=plan_id
            ),
            "sessions": discard_restored_team_agent_session_reset_staging(team_id, plan_id),
        }

    def _stage(self, plan: Mapping[str, Any], stage: Mapping[str, Any]) -> dict[str, Any]:
        plan_id = str(plan.get("purgePlanId") or "")
        if str(stage.get("planId") or "") != plan_id:
            raise ChallengeCupDestructiveAdapterError("reset stage does not belong to this plan")
        with _LOCK:
            current = self._stages.get(plan_id)
        if current is None or current is not stage:
            # The service passes a detached Mapping boundary in production; it
            # need not preserve Python object identity, only the plan binding.
            if current is None:
                raise ChallengeCupDestructiveAdapterError("reset stage is unavailable")
        return current

    def _stage_summary(self, stage: Mapping[str, Any]) -> dict[str, Any]:
        handles = stage.get("handles") if isinstance(stage.get("handles"), Mapping) else {}
        return {
            "planId": str(stage.get("planId") or ""),
            "teamId": str(stage.get("teamId") or ""),
            "status": str(stage.get("status") or "staged"),
            "ports": sorted(key for key in handles if not key.startswith("_")),
            "stageHash": _hash({key: value.get("stageId", "") if isinstance(value, Mapping) else "" for key, value in handles.items() if not key.startswith("_")}),
        }

    def _assert_plan(self, team_id: str, plan: Mapping[str, Any]) -> None:
        if team_id != RESEARCH_TEAM_ID:
            raise ChallengeCupDestructiveAdapterError("Challenge Cup reset is restricted to research-team")
        if not isinstance(plan, Mapping):
            raise ChallengeCupDestructiveAdapterError("reset plan is invalid")
        _text(plan.get("purgePlanId"), field="purgePlanId")
        _text(plan.get("inventoryHash"), field="inventoryHash")


def build_live_challenge_cup_destructive_adapter() -> ChallengeCupLiveDestructiveAdapter:
    return ChallengeCupLiveDestructiveAdapter()


def build_live_challenge_cup_reset_service() -> ChallengeCupResetService:
    """Bind the canonical live reader and destructive owner as one operation.

    This prevents an operator entry point from previewing one source while
    executing a different store adapter.
    """

    return ChallengeCupResetService(
        inventory_reader=build_live_challenge_cup_inventory_reader(),
        destructive_adapter=build_live_challenge_cup_destructive_adapter(),
    )


def preview_live_challenge_cup_reset(*, team_id: str = RESEARCH_TEAM_ID) -> dict[str, Any]:
    """Read the current governed reset preview without changing any state."""

    return build_live_challenge_cup_reset_service().preview(team_id).to_dict()


def execute_live_challenge_cup_reset(
    *,
    purge_plan_id: str,
    confirmation_phrase: str,
    team_id: str = RESEARCH_TEAM_ID,
) -> dict[str, Any]:
    """Execute exactly the previewed live reset through managed owner ports."""

    return build_live_challenge_cup_reset_service().execute(
        purge_plan_id=purge_plan_id,
        confirmation_phrase=confirmation_phrase,
        team_id=team_id,
    )


__all__ = [
    "ChallengeCupDestructiveAdapterError",
    "ChallengeCupLiveDestructiveAdapter",
    "build_live_challenge_cup_reset_service",
    "build_live_challenge_cup_destructive_adapter",
    "execute_live_challenge_cup_reset",
    "preview_live_challenge_cup_reset",
]
