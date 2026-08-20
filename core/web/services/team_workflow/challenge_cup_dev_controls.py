"""Team-scoped Challenge Cup DEV platform controls service.

Owns team storage resolution and persistence for the DEV-only control surface:
the persisted ChallengeCupPlatformDevelopmentReadinessReport and the dev-1/dev-5
fixture ``CatalogExecutionState`` checkpoints. The state machines and fixture
adapters live in ``core.research.competition``; this module never starts a real
experiment, Qwen invocation, network collection, CUDA/GPU benchmark, DANDI
download or formal submission.

All storage is team-scoped by the authoritative team id resolved from the team
service, never by the raw request value, so alias requests and similar team ids
stay isolated. The flow order readiness -> dev-1 -> dev-5 is enforced inside the
store lock and any out-of-order action raises ``DevFlowConflict`` (mapped to 409
by the route layer) without dispatching anything.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from core.research.competition.catalog_execution import (
    CatalogExecutionError,
    CatalogExecutionState,
    QuestionStatus,
    dev_plan,
)
from core.research.competition.dev_control_batch import (
    ALLOWED_DEV_BATCH_PLAN_IDS,
    FORBIDDEN_DEV_BATCH_PLAN_IDS,
    dev_fixture_adapter_id,
    new_dev_batch_state,
    project_dev_batch_checkpoint,
    project_dev_batch_outcomes,
    project_dev_batch_state,
    run_dev_fixture_batch,
    validate_dev_batch_max_items,
    validate_dev_batch_plan,
)
from core.research.competition.platform_flow_ready import (
    CATALOG_POLICY_VERSION,
    PROGRAM_CONTRACT_VERSION,
    REPORT_KIND,
    build_platform_flow_readiness_report,
    overall_status,
)
from core.research.competition.resources import (
    CORE_BEHAVIOR_HASH,
    CORE_POLICY_HASH,
    load_science_question_catalog,
)
from core.research.competition.result_set import CatalogScope, ResultSetContractError
from core.research.competition.source_boundary import git_is_dirty, git_output
from core.web.services import team_service
from core.web.services.runtime_scene_service import record_runtime_scene_event
from core.web.services.team_workflow.research_projects import team_workspace_root

CONTROLS_DIRNAME = "challenge_cup_dev_controls"
REPORT_FILENAME = "readiness_report.json"
BATCH_DIRNAME = "batches"
REPORT_ENVELOPE_SCHEMA_VERSION = 1
BATCH_ENVELOPE_SCHEMA_VERSION = 2
REPORT_SCHEMA_VERSION = 1
SNAPSHOT_SCHEMA_VERSION = 1
CATALOG_OVERVIEW_SCHEMA_VERSION = 1
DEV_ONLY_MODE = "dev"
READINESS_MAX_AGE_SECONDS = 24 * 60 * 60
REPORT_STATUSES = frozenset({"READY", "NOT_READY", "BLOCKED"})
REQUIRED_READINESS_GATES: tuple[str, ...] = (
    "program_hash",
    "r0_source_integrity",
    "r1_clean_clone",
    "adapters_dev_isolated",
    "catalog_batch_resume",
    "control_flow_contracts",
    "model_receipt",
    "multimodal",
    "product_projection",
)
_RUN_ACTIONS = {
    "dev-1": ("run_dev_1_fixture_batch",),
    "dev-5": ("run_dev_5_fixture_batch", "resume_dev_5_fixture_batch"),
}
_REPAIR_ACTIONS = {
    "dev-1": "repair_dev_1_fixture_batch",
    "dev-5": "repair_dev_5_fixture_batch",
}

_STORE_LOCK = threading.RLock()
_READINESS_IN_PROGRESS: set[str] = set()
_TEAM_TRANSACTIONS_IN_PROGRESS: set[str] = set()

_os_replace = os.replace
_os_fsync = os.fsync
_os_fdopen = os.fdopen
_mkstemp = tempfile.mkstemp


class ChallengeCupDevControlsError(ValueError):
    """A Challenge Cup DEV control request is invalid or fail-closed."""


class DevControlsStorageError(RuntimeError):
    """Persisted DEV control storage is corrupt or otherwise unusable."""


class DevFlowConflict(RuntimeError):
    """A Challenge Cup DEV control action violated the required flow order."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc_timestamp(value: Any, *, label: str) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DevControlsStorageError(f"{label} is not a valid UTC timestamp.") from exc
    if parsed.tzinfo is None:
        raise DevControlsStorageError(f"{label} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _current_source_commit() -> str:
    from core.infrastructure.path_containment import PROJECT_ROOT

    commit = git_output(PROJECT_ROOT, "rev-parse", "HEAD").strip().lower()
    if len(commit) != 40:
        raise DevControlsStorageError("Current source commit is unavailable.")
    return commit


def _current_tree_is_clean() -> bool:
    from core.infrastructure.path_containment import PROJECT_ROOT

    return not git_is_dirty(PROJECT_ROOT)


def _controls_root(team_id: str) -> Path:
    return team_workspace_root(team_id) / CONTROLS_DIRNAME


def _report_path(team_id: str) -> Path:
    return _controls_root(team_id) / REPORT_FILENAME


def _batch_path(team_id: str, plan_id: str) -> Path:
    return _controls_root(team_id) / BATCH_DIRNAME / f"{plan_id}.json"


def _team_lock_path(team_id: str) -> Path:
    return _controls_root(team_id) / ".transaction.lock"


def _try_lock_handle(handle: BinaryIO) -> bool:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock_handle(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _team_transaction(team_id: str) -> Iterator[None]:
    """Hold one non-blocking process + OS lock for a team's full transaction."""
    lock_path = _team_lock_path(team_id)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+b")
    except OSError as exc:
        raise DevControlsStorageError("DEV transaction lock is unavailable.") from exc
    acquired = False
    registered = False
    try:
        with _STORE_LOCK:
            if team_id in _TEAM_TRANSACTIONS_IN_PROGRESS:
                raise DevFlowConflict(
                    "DEV flow conflict: another transaction is running for this team."
                )
            _TEAM_TRANSACTIONS_IN_PROGRESS.add(team_id)
            registered = True
        acquired = _try_lock_handle(handle)
        if not acquired:
            raise DevFlowConflict(
                "DEV flow conflict: another process owns this team transaction."
            )
        yield
    finally:
        if acquired:
            try:
                _unlock_handle(handle)
            except OSError:
                pass
        handle.close()
        if registered:
            with _STORE_LOCK:
                _TEAM_TRANSACTIONS_IN_PROGRESS.discard(team_id)


def _strict_json_write(path: Path, payload: dict[str, Any]) -> None:
    """Atomically persist a JSON envelope with domain-strict durability.

    Writes via temp-file + flush + fsync + ``os.replace`` with no in-place
    fallback: any failure keeps the previous file untouched and propagates to
    the caller. The shared atomic-write helper with its in-place fallback is
    deliberately not used here because that fallback can overwrite state
    mid-race.
    """
    target = Path(path)
    fd = -1
    temp_name = ""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        fd, temp_name = _mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
        with _os_fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(encoded)
            handle.flush()
            _os_fsync(handle.fileno())
        _os_replace(temp_name, target)
    except Exception as exc:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise DevControlsStorageError(
            f"DEV control store write failed: {target.name}."
        ) from exc


def _read_strict_json(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DevControlsStorageError(f"DEV control store is unreadable: {path.name}.") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DevControlsStorageError(f"DEV control store is corrupt JSON: {path.name}.") from exc
    if not isinstance(value, dict):
        raise DevControlsStorageError(f"DEV control store root is not an object: {path.name}.")
    return value


def _validate_report_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise DevControlsStorageError("Readiness store root is not an object.")
    if str(envelope.get("schemaVersion") or "") != str(REPORT_ENVELOPE_SCHEMA_VERSION):
        raise DevControlsStorageError("Readiness envelope schema version mismatch.")
    if envelope.get("realCampaignAllowed") is not False:
        raise DevControlsStorageError("Readiness envelope must never allow a real campaign.")
    report = envelope.get("report")
    if not isinstance(report, dict):
        raise DevControlsStorageError("Readiness store has no report object.")
    if str(report.get("schemaVersion") or "") != str(REPORT_SCHEMA_VERSION):
        raise DevControlsStorageError("Readiness report schema version mismatch.")
    if str(report.get("reportKind") or "") != REPORT_KIND:
        raise DevControlsStorageError("Readiness report kind mismatch.")
    if str(report.get("mode") or "").strip().lower() != DEV_ONLY_MODE:
        raise DevControlsStorageError("Readiness report is not DEV-only.")
    if report.get("realCampaignAllowed") is not False:
        raise DevControlsStorageError("Readiness report must never allow a real campaign.")
    if report.get("researchAuthorizationRequired") is not True:
        raise DevControlsStorageError("Readiness report must require research authorization.")
    program_contract = report.get("programContract")
    if not isinstance(program_contract, dict) or program_contract != {
        "version": PROGRAM_CONTRACT_VERSION,
        "coreBehaviorHash": CORE_BEHAVIOR_HASH,
    }:
        raise DevControlsStorageError("Readiness report program contract is stale or invalid.")
    catalog_policy = report.get("catalogPolicy")
    if not isinstance(catalog_policy, dict) or catalog_policy != {
        "version": CATALOG_POLICY_VERSION,
        "corePolicyHash": CORE_POLICY_HASH,
    }:
        raise DevControlsStorageError("Readiness report catalog policy is stale or invalid.")
    status = str(report.get("status") or "")
    if status not in REPORT_STATUSES:
        raise DevControlsStorageError(f"Readiness report has an unknown status: {status!r}.")
    reported_commit = str(report.get("sourceCommit") or "").lower()
    current_commit = _current_source_commit()
    if status == "READY":
        if reported_commit != current_commit:
            raise DevControlsStorageError("Readiness report source commit is stale or invalid.")
        if not _current_tree_is_clean():
            raise DevControlsStorageError(
                "Readiness report cannot be READY while the working tree is dirty."
            )
    elif reported_commit and reported_commit != current_commit:
        raise DevControlsStorageError("Readiness report source commit is stale or invalid.")
    generated_at = _parse_utc_timestamp(
        report.get("generatedAt"), label="Readiness report generatedAt"
    )
    now = datetime.now(timezone.utc)
    if generated_at > now + timedelta(minutes=5):
        raise DevControlsStorageError("Readiness report generatedAt is in the future.")
    if now - generated_at > timedelta(seconds=READINESS_MAX_AGE_SECONDS):
        raise DevControlsStorageError("Readiness report is stale; rerun DEV readiness.")
    gates = report.get("gates")
    if not isinstance(gates, list):
        raise DevControlsStorageError("Readiness report gates must be an array.")
    gate_ids: set[str] = set()
    for gate in gates:
        if not isinstance(gate, dict) or not str(gate.get("gateId") or ""):
            raise DevControlsStorageError("Readiness report gate is malformed.")
        gate_id = str(gate["gateId"])
        if gate_id in gate_ids:
            raise DevControlsStorageError(f"Readiness report gate is duplicated: {gate_id}.")
        if str(gate.get("status") or "") not in {"PASS", "FAIL", "BLOCKED"}:
            raise DevControlsStorageError(
                f"Readiness report gate has an invalid status: {gate_id}."
            )
        gate_ids.add(gate_id)
    missing = [gate_id for gate_id in REQUIRED_READINESS_GATES if gate_id not in gate_ids]
    if missing:
        raise DevControlsStorageError(f"Readiness report is missing required gates: {missing}.")
    expected_status = overall_status(gates)
    if status != expected_status:
        raise DevControlsStorageError(
            f"Readiness report status is inconsistent with its gates: {status} != {expected_status}."
        )
    expected_action = (
        "RESEARCH_AUTHORIZATION_REQUIRED"
        if status == "READY"
        else "repair_failed_platform_gates"
    )
    if str(report.get("nextLegalAction") or "") != expected_action:
        raise DevControlsStorageError("Readiness report nextLegalAction is inconsistent.")
    return report


def _validate_batch_checkpoint(checkpoint: dict[str, Any], plan_id: str) -> None:
    expected_plan = dev_plan(plan_id)
    plan = checkpoint.get("plan")
    if not isinstance(plan, dict):
        raise DevControlsStorageError("Batch checkpoint plan is missing.")
    if str(plan.get("plan_id") or "") != plan_id:
        raise DevControlsStorageError("Batch checkpoint plan id mismatch.")
    if str(plan.get("gate_id") or "") != expected_plan.gate_id:
        raise DevControlsStorageError("Batch checkpoint gate id mismatch.")
    question_ids = plan.get("question_ids")
    if not isinstance(question_ids, list):
        raise DevControlsStorageError("Batch checkpoint question ids are missing.")
    if [str(item) for item in question_ids] != list(expected_plan.question_ids):
        raise DevControlsStorageError("Batch checkpoint question ids mismatch the DEV plan.")
    scope = checkpoint.get("scope")
    if not isinstance(scope, dict):
        raise DevControlsStorageError("Batch checkpoint scope is missing.")
    try:
        restored_scope = CatalogScope.from_dict(scope)
    except (ResultSetContractError, KeyError, TypeError, ValueError) as exc:
        raise DevControlsStorageError("Batch checkpoint scope is invalid.") from exc
    expected_scope = CatalogScope.from_tracked_resources()
    if restored_scope != expected_scope:
        raise DevControlsStorageError("Batch checkpoint scope is not the DEV catalog scope.")
    records = checkpoint.get("records")
    if not isinstance(records, list):
        raise DevControlsStorageError("Batch checkpoint records are missing.")
    if len(records) != expected_plan.question_count:
        raise DevControlsStorageError("Batch checkpoint records are incomplete.")
    seen: set[str] = set()
    raw_by_question: dict[str, dict[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, dict):
            raise DevControlsStorageError("Batch checkpoint record is malformed.")
        question_id = str(raw.get("question_id") or "")
        if question_id not in expected_plan.question_ids:
            raise DevControlsStorageError(
                f"Batch checkpoint record is not part of the plan: {question_id}."
            )
        if question_id in seen:
            raise DevControlsStorageError(f"Batch checkpoint record is duplicated: {question_id}.")
        attempts = raw.get("attempts")
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
            raise DevControlsStorageError(
                f"Batch checkpoint record attempts are invalid: {question_id}."
            )
        if not isinstance(raw.get("invalidated"), bool):
            raise DevControlsStorageError(
                f"Batch checkpoint record invalidated flag is invalid: {question_id}."
            )
        raw_result = raw.get("result")
        if raw_result is not None:
            if not isinstance(raw_result, dict):
                raise DevControlsStorageError(
                    f"Batch checkpoint record result is malformed: {question_id}."
                )
            model_locator = str(raw_result.get("model_receipt_locator") or "")
            expected_model_prefix = (
                f"model-receipt://dev/{dev_fixture_adapter_id(question_id)}/"
            )
            model_result_id = (
                model_locator.removeprefix(expected_model_prefix)
                if model_locator.startswith(expected_model_prefix)
                else ""
            )
            if (
                raw_result.get("status") != "dev_fixture"
                or raw_result.get("submission_eligible") is not False
                or re.fullmatch(r"[0-9a-fA-F]{64}", model_result_id) is None
                or raw_result.get("knowledge_locator")
                != f"knowledge://dev/{question_id}"
            ):
                raise DevControlsStorageError(
                    f"Batch checkpoint result is not a DEV fixture result: {question_id}."
                )
        seen.add(question_id)
        raw_by_question[question_id] = raw
    try:
        state = CatalogExecutionState.from_checkpoint(checkpoint)
    except (
        CatalogExecutionError,
        KeyError,
        ResultSetContractError,
        TypeError,
        ValueError,
    ) as exc:
        raise DevControlsStorageError("Batch checkpoint record semantics are invalid.") from exc
    for question_id in expected_plan.question_ids:
        raw = raw_by_question[question_id]
        status = state.status(question_id)
        attempts = state.attempts(question_id)
        result = state.result_for(question_id)
        invalidated = bool(raw["invalidated"])
        last_error = raw.get("last_error")
        if status is QuestionStatus.RUNNING:
            raise DevControlsStorageError(
                f"Batch checkpoint cannot persist a running record: {question_id}."
            )
        if status is QuestionStatus.PENDING and (
            attempts != 0 or result is not None or invalidated or last_error is not None
        ):
            raise DevControlsStorageError(
                f"Batch checkpoint pending record is inconsistent: {question_id}."
            )
        if status is QuestionStatus.SUCCEEDED and (
            attempts < 1 or result is None or invalidated or last_error is not None
        ):
            raise DevControlsStorageError(
                f"Batch checkpoint succeeded record is inconsistent: {question_id}."
            )
        if status in (QuestionStatus.FAILED, QuestionStatus.BLOCKED) and (
            attempts < 1 or not str(last_error or "").strip()
        ):
            raise DevControlsStorageError(
                f"Batch checkpoint failed/blocked record is inconsistent: {question_id}."
            )


def _load_batch_checkpoint(
    team_id: str,
    plan_id: str,
    readiness_evidence: dict[str, Any] | None,
) -> tuple[bool, dict[str, Any], str, str]:
    path = _batch_path(team_id, plan_id)
    if not path.exists():
        return False, {}, "", ""
    payload = _read_strict_json(path)
    schema_version = str(payload.get("schemaVersion") or "")
    if schema_version == "1":
        # Legacy DEV checkpoints have no readiness binding and are deliberately
        # treated as stale evidence. A fresh run overwrites them under schema 2.
        return False, {}, "", ""
    if schema_version != str(BATCH_ENVELOPE_SCHEMA_VERSION):
        raise DevControlsStorageError(f"Batch envelope schema version mismatch: {plan_id}.")
    if str(payload.get("planId") or "") != plan_id:
        raise DevControlsStorageError(f"Batch envelope plan id mismatch: {plan_id}.")
    stored_evidence = payload.get("readinessEvidence")
    if not isinstance(stored_evidence, dict):
        raise DevControlsStorageError(
            f"Batch readiness evidence is missing or malformed: {plan_id}."
        )
    if readiness_evidence is None or stored_evidence != readiness_evidence:
        return False, {}, "", ""
    checkpoint = payload.get("checkpoint")
    if not isinstance(checkpoint, dict):
        raise DevControlsStorageError(f"Batch checkpoint is missing: {plan_id}.")
    _validate_batch_checkpoint(checkpoint, plan_id)
    updated_at = str(payload.get("updatedAt") or "")
    _parse_utc_timestamp(updated_at, label=f"Batch {plan_id} updatedAt")
    upstream_updated_at = str(payload.get("upstreamCheckpointUpdatedAt") or "")
    if plan_id == "dev-5" and not upstream_updated_at:
        raise DevControlsStorageError(
            "dev-5 checkpoint has no bound dev-1 checkpoint version."
        )
    return True, checkpoint, updated_at, upstream_updated_at


def _read_report_state(
    team_id: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    path = _report_path(team_id)
    if not path.exists():
        return None
    payload = _read_strict_json(path)
    report = _validate_report_envelope(payload)
    updated_at = str(payload.get("updatedAt") or "")
    _parse_utc_timestamp(updated_at, label="Readiness envelope updatedAt")
    projection = {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "reportKind": str(report.get("reportKind") or REPORT_KIND),
        "status": str(report.get("status") or ""),
        "mode": str(report.get("mode") or DEV_ONLY_MODE),
        "realCampaignAllowed": bool(report.get("realCampaignAllowed") is True),
        "researchAuthorizationRequired": bool(report.get("researchAuthorizationRequired") or True),
        "nextLegalAction": str(report.get("nextLegalAction") or ""),
        "generatedAt": str(report.get("generatedAt") or ""),
        "updatedAt": updated_at,
        "gates": report.get("gates") if isinstance(report.get("gates"), list) else [],
    }
    evidence = {
        "reportUpdatedAt": updated_at,
        "sourceCommit": str(report.get("sourceCommit") or "").lower(),
        "programContract": dict(report.get("programContract") or {}),
        "catalogPolicy": dict(report.get("catalogPolicy") or {}),
    }
    return projection, evidence


def _project_report(team_id: str) -> dict[str, Any] | None:
    state = _read_report_state(team_id)
    return state[0] if state is not None else None


def _project_batch(
    team_id: str,
    plan_id: str,
    readiness_evidence: dict[str, Any] | None,
) -> dict[str, Any] | None:
    present, checkpoint, updated_at, _ = _load_batch_checkpoint(
        team_id, plan_id, readiness_evidence
    )
    if not present:
        return None
    try:
        return project_dev_batch_checkpoint(checkpoint, updated_at=updated_at)
    except (CatalogExecutionError, ValueError) as exc:
        raise DevControlsStorageError(
            f"Batch checkpoint is not projectable: {plan_id}."
        ) from exc


def _require_team(team_id: str) -> str:
    """Resolve the authoritative team id; the team must exist before any read/write."""
    detail = team_service.get_team(team_id)
    authoritative_team_id = str(detail.get("teamId") or "").strip()
    if not authoritative_team_id:
        raise ChallengeCupDevControlsError("Team detail has no authoritative teamId.")
    return authoritative_team_id


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


def _validate_cross_plan_invariants(
    team_id: str,
    batches: dict[str, Any],
    readiness_evidence: dict[str, Any] | None,
) -> None:
    dev_5 = batches.get("dev-5")
    if dev_5 is None:
        return
    dev_1 = batches.get("dev-1")
    if (
        dev_1 is None
        or dev_1["pendingCount"] > 0
        or dev_1["failedCount"] > 0
        or dev_1["blockedCount"] > 0
        or dev_1["succeededCount"] != dev_1["questionCount"]
    ):
        raise DevControlsStorageError(
            "dev-5 checkpoint is orphaned from a completed dev-1 checkpoint."
        )
    present, _, _, upstream_updated_at = _load_batch_checkpoint(
        team_id, "dev-5", readiness_evidence
    )
    if not present or upstream_updated_at != dev_1["lastUpdatedAt"]:
        raise DevControlsStorageError(
            "dev-5 checkpoint is bound to a stale dev-1 checkpoint version."
        )


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
    parallel lifecycle. The team must exist before any read, and its
    authoritative id is used for every storage path.
    """
    authoritative_team_id = _require_team(team_id)
    with _team_transaction(authoritative_team_id):
        return _get_challenge_cup_dev_control_snapshot_transaction(
            authoritative_team_id
        )


def _get_challenge_cup_dev_control_snapshot_transaction(
    authoritative_team_id: str,
) -> dict[str, Any]:
    """Project one snapshot while the caller holds the team transaction lock."""
    report_state = _read_report_state(authoritative_team_id)
    report = report_state[0] if report_state is not None else None
    readiness_evidence = report_state[1] if report_state is not None else None
    batches: dict[str, Any] = {}
    for plan_id in ALLOWED_DEV_BATCH_PLAN_IDS:
        projection = _project_batch(
            authoritative_team_id, plan_id, readiness_evidence
        )
        if projection is not None:
            batches[plan_id] = projection
    _validate_cross_plan_invariants(
        authoritative_team_id, batches, readiness_evidence
    )
    return {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "teamId": authoritative_team_id,
        "generatedAt": _utc_now(),
        "mode": DEV_ONLY_MODE,
        "realCampaignAllowed": False,
        "nextLegalAction": _snapshot_next_legal_action(report, batches),
        "report": report,
        "batches": batches,
        "boundary": _boundary_fields(),
    }


def get_challenge_cup_catalog_overview(team_id: str) -> dict[str, Any]:
    """Read-only 125-question catalog projection for the Program overview list.

    Merges the frozen question catalog with persisted DEV fixture checkpoints.
    Does not start batches or invent a second lifecycle.
    """
    authoritative_team_id = _require_team(team_id)
    with _team_transaction(authoritative_team_id):
        return _get_challenge_cup_catalog_overview_transaction(authoritative_team_id)


def _get_challenge_cup_catalog_overview_transaction(
    authoritative_team_id: str,
) -> dict[str, Any]:
    report_state = _read_report_state(authoritative_team_id)
    readiness_evidence = report_state[1] if report_state is not None else None
    records: dict[str, dict[str, Any]] = {}
    for plan_id in ALLOWED_DEV_BATCH_PLAN_IDS:
        present, checkpoint, _, _ = _load_batch_checkpoint(
            authoritative_team_id, plan_id, readiness_evidence
        )
        if not present:
            continue
        try:
            state = CatalogExecutionState.from_checkpoint(checkpoint)
        except (CatalogExecutionError, KeyError, ResultSetContractError, TypeError, ValueError):
            continue
        for question_id in state.plan.question_ids:
            status = state.status(question_id)
            merged = records.get(question_id)
            if merged and _execution_status_rank(str(merged["executionStatus"])) <= _execution_status_rank(
                status.value
            ):
                continue
            records[question_id] = {
                "executionStatus": status.value,
                "attempts": state.attempts(question_id),
                "planId": plan_id,
                "lastError": _catalog_last_error(state, question_id),
            }
    catalog = load_science_question_catalog()
    questions = [
        _catalog_overview_row(item, records.get(str(item.get("id") or "")))
        for item in list(catalog.get("questions") or [])
        if isinstance(item, dict)
    ]
    counts = {"queued": 0, "running": 0, "succeeded": 0, "failed": 0}
    for row in questions:
        counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
    return {
        "schemaVersion": CATALOG_OVERVIEW_SCHEMA_VERSION,
        "teamId": authoritative_team_id,
        "generatedAt": _utc_now(),
        "questionCount": len(questions),
        "counts": counts,
        "questions": questions,
    }


def _execution_status_rank(status: str) -> int:
    return {
        "failed": 0,
        "blocked": 0,
        "running": 1,
        "succeeded": 2,
        "pending": 3,
    }.get(str(status or "").strip().lower(), 4)


def _catalog_last_error(state: CatalogExecutionState, question_id: str) -> str:
    record = state._records.get(question_id)
    if record is None:
        return ""
    return str(record.last_error or "").strip()


def _catalog_display_status(execution_status: str) -> str:
    normalized = str(execution_status or "").strip().lower()
    if normalized in {"failed", "blocked"}:
        return "failed"
    if normalized == "running":
        return "running"
    if normalized == "succeeded":
        return "succeeded"
    return "queued"


def _catalog_overview_row(
    item: dict[str, Any],
    record: dict[str, Any] | None,
) -> dict[str, Any]:
    question_id = str(item.get("id") or "").strip()
    execution_status = str((record or {}).get("executionStatus") or "pending")
    display_status = _catalog_display_status(execution_status)
    attempts = int((record or {}).get("attempts") or 0)
    plan_id = str((record or {}).get("planId") or "")
    last_error = str((record or {}).get("lastError") or "").strip()
    stage = {
        "queued": "queued",
        "running": "catalog_execution",
        "succeeded": "complete",
        "failed": "blocked",
    }[display_status]
    checkpoint_done = 1 if display_status == "succeeded" or attempts > 0 else 0
    if display_status == "failed" and plan_id:
        action = "retry"
    elif display_status == "running" and plan_id:
        action = "continue"
    else:
        action = "view"
    blocker = None
    if display_status == "failed":
        blocker = {
            "code": "question_blocked" if execution_status == "blocked" else "question_failed",
            "message": last_error or "本题执行失败",
            "remediationLabel": "单行重试已有 DEV fixture 命令" if plan_id else "打开题目查看阻塞原因",
        }
    return {
        "questionId": question_id,
        "title": str(item.get("question_en") or "").strip(),
        "domain": str(item.get("domain") or "").strip(),
        "status": display_status,
        "executionStatus": execution_status,
        "currentStage": stage,
        "checkpointProgress": f"{checkpoint_done}/1",
        "attempts": attempts,
        "planId": plan_id,
        "action": action,
        "blocker": blocker,
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
    _validate_report_envelope(envelope)
    with _STORE_LOCK:
        _strict_json_write(_report_path(team_id), envelope)
    return envelope


def run_challenge_cup_dev_readiness(team_id: str, *, mode: str = DEV_ONLY_MODE) -> dict[str, Any]:
    """Build and atomically persist the DEV readiness report (R1 pytest included).

    The clean-clone destination is a task-owned temporary directory that is
    always cleaned up, even when the report build fails. A dirty working tree is
    never READY: ``require_clean`` is always True and ``run_pytest`` is always
    True under ``build_platform_flow_readiness_report``, and
    ``realCampaignAllowed`` can never become true. Repairing failed platform
    gates is always performed by re-running readiness.
    """
    authoritative_team_id = _require_team(team_id)
    if str(mode or "").strip().lower() != DEV_ONLY_MODE:
        _record_scene_event(
            "challenge_cup_dev_controls.readiness.rejected",
            message="Challenge Cup readiness rejected a non-dev mode.",
            outcome="blocked",
            fields={
                "teamId": authoritative_team_id,
                "errorType": "ChallengeCupDevControlsError",
            },
        )
        raise ChallengeCupDevControlsError(
            "Challenge Cup readiness is DEV-only; formal modes are not authorized."
        )
    with _team_transaction(authoritative_team_id):
        return _run_readiness_transaction(authoritative_team_id)


def _run_readiness_transaction(authoritative_team_id: str) -> dict[str, Any]:
    with _STORE_LOCK:
        if authoritative_team_id in _READINESS_IN_PROGRESS:
            raise DevFlowConflict("DEV readiness is already running for this team.")
        _READINESS_IN_PROGRESS.add(authoritative_team_id)
    try:
        _record_scene_event(
            "challenge_cup_dev_controls.readiness.started",
            message="Challenge Cup DEV readiness build started.",
            outcome="started",
            fields={"teamId": authoritative_team_id, "mode": DEV_ONLY_MODE},
        )
        from core.infrastructure.path_containment import PROJECT_ROOT

        with tempfile.TemporaryDirectory(prefix="challenge-cup-r1-") as tmp_dir:
            report = build_platform_flow_readiness_report(
                PROJECT_ROOT,
                clone_dest=Path(tmp_dir) / "clone",
                require_clean=True,
                run_pytest=True,
                mode=DEV_ONLY_MODE,
            )
        envelope = _persist_report(authoritative_team_id, report)
        _record_scene_event(
            "challenge_cup_dev_controls.readiness.succeeded",
            message="Challenge Cup DEV readiness report was persisted.",
            outcome="succeeded",
            fields={
                "teamId": authoritative_team_id,
                "status": str(report.get("status") or ""),
                "nextLegalAction": str(report.get("nextLegalAction") or ""),
            },
        )
        return {
            "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
            "teamId": authoritative_team_id,
            "report": _project_report(authoritative_team_id),
            "cleanedUp": True,
            "updatedAt": str(envelope.get("updatedAt") or ""),
        }
    except Exception as exc:
        _record_scene_event(
            "challenge_cup_dev_controls.readiness.failed",
            message="Challenge Cup DEV readiness build failed.",
            outcome="failed",
            fields={
                "teamId": authoritative_team_id,
                "errorType": type(exc).__name__,
                "errorDetail": str(exc)[:320],
            },
        )
        raise
    finally:
        with _STORE_LOCK:
            _READINESS_IN_PROGRESS.discard(authoritative_team_id)


def _next_legal_action(
    team_id: str,
) -> tuple[str, dict[str, Any] | None]:
    report_state = _read_report_state(team_id)
    report = report_state[0] if report_state is not None else None
    readiness_evidence = report_state[1] if report_state is not None else None
    batches: dict[str, Any] = {}
    for plan_id in ALLOWED_DEV_BATCH_PLAN_IDS:
        projection = _project_batch(team_id, plan_id, readiness_evidence)
        if projection is not None:
            batches[plan_id] = projection
    _validate_cross_plan_invariants(team_id, batches, readiness_evidence)
    return _snapshot_next_legal_action(report, batches), readiness_evidence


def _enforce_batch_flow(plan_id: str, *, next_action: str, retry_failed: bool) -> None:
    if retry_failed:
        repair_action = _REPAIR_ACTIONS[plan_id]
        if next_action != repair_action:
            raise DevFlowConflict(
                f"DEV flow conflict: {plan_id} repair requires retryFailed=true and "
                f"{repair_action}, but the next legal action is {next_action}."
            )
        return
    allowed = _RUN_ACTIONS[plan_id]
    if next_action not in allowed:
        raise DevFlowConflict(
            f"DEV flow conflict: {plan_id} is out of order; the next legal action "
            f"is {next_action}."
        )


def _invalidate_failed_blocked(state: CatalogExecutionState) -> list[str]:
    invalidated: list[str] = []
    for question_id in state.plan.question_ids:
        if state.status(question_id) in (QuestionStatus.FAILED, QuestionStatus.BLOCKED):
            state.invalidate(question_id, "repair retry requested")
            invalidated.append(question_id)
    return invalidated


def run_challenge_cup_dev_batch(
    team_id: str,
    plan_id: str,
    max_items: int | None,
    *,
    retry_failed: bool = False,
) -> dict[str, Any]:
    """Execute/resume/repair only dev-1 or dev-5 fixture batches and persist checkpoints.

    The flow order readiness -> dev-1 -> dev-5 is enforced inside the team's
    cross-process transaction lock; an out-of-order request raises ``DevFlowConflict`` and dispatches
    nothing. The checkpoint is persisted after every completed/failed item, so a
    dev-5 interruption can always be resumed without re-running succeeded items.
    ``retry_failed=True`` is only legal when the next legal action is this plan's
    repair action, and it invalidates only this plan's failed/blocked items;
    succeeded items are never re-run. dev-12/dev-125 and formal/real scopes are
    rejected fail-closed. The team must exist before any read or write and its
    authoritative id is used for every storage path and response field.
    """
    authoritative_team_id = _require_team(team_id)
    try:
        normalized_plan = validate_dev_batch_plan(plan_id)
        bounded = validate_dev_batch_max_items(max_items)
    except Exception as exc:
        _record_scene_event(
            "challenge_cup_dev_controls.batch.rejected",
            message="Challenge Cup DEV fixture batch was rejected.",
            outcome="blocked",
            fields={
                "teamId": authoritative_team_id,
                "planId": str(plan_id or "")[:80],
                "errorType": type(exc).__name__,
                "errorDetail": str(exc)[:320],
            },
        )
        raise
    try:
        with _team_transaction(authoritative_team_id):
            if authoritative_team_id in _READINESS_IN_PROGRESS:
                raise DevFlowConflict(
                    "DEV flow conflict: readiness is running for this team."
                )
            next_action, readiness_evidence = _next_legal_action(
                authoritative_team_id
            )
            _enforce_batch_flow(
                normalized_plan,
                next_action=next_action,
                retry_failed=retry_failed,
            )
            _record_scene_event(
                "challenge_cup_dev_controls.batch.started",
                message="Challenge Cup DEV fixture batch started.",
                outcome="started",
                fields={
                    "teamId": authoritative_team_id,
                    "planId": normalized_plan,
                    "maxItems": bounded,
                    "retryFailed": retry_failed,
                },
            )
            present, checkpoint, _, _ = _load_batch_checkpoint(
                authoritative_team_id, normalized_plan, readiness_evidence
            )
            state = (
                CatalogExecutionState.from_checkpoint(checkpoint)
                if present
                else new_dev_batch_state(normalized_plan)
            )
            if retry_failed:
                _invalidate_failed_blocked(state)
            upstream_checkpoint_updated_at = ""
            if normalized_plan == "dev-5":
                dev_1_projection = _project_batch(
                    authoritative_team_id, "dev-1", readiness_evidence
                )
                if dev_1_projection is None:
                    raise DevControlsStorageError(
                        "dev-5 cannot bind a missing dev-1 checkpoint."
                    )
                upstream_checkpoint_updated_at = dev_1_projection["lastUpdatedAt"]

            def persist(_item: dict[str, Any] | None) -> str:
                updated_at = _utc_now()
                envelope = {
                    "schemaVersion": BATCH_ENVELOPE_SCHEMA_VERSION,
                    "planId": normalized_plan,
                    "updatedAt": updated_at,
                    "readinessEvidence": readiness_evidence,
                    "upstreamCheckpointUpdatedAt": upstream_checkpoint_updated_at,
                    "checkpoint": state.to_checkpoint(),
                }
                _strict_json_write(
                    _batch_path(authoritative_team_id, normalized_plan), envelope
                )
                return updated_at

            result = run_dev_fixture_batch(state, max_items=bounded, on_item=persist)
            persisted_at = persist(None)
            projection = project_dev_batch_state(state, updated_at=persisted_at)
    except DevFlowConflict as exc:
        _record_scene_event(
            "challenge_cup_dev_controls.batch.conflict",
            message="Challenge Cup DEV fixture batch conflicted with the flow order.",
            outcome="blocked",
            fields={
                "teamId": authoritative_team_id,
                "planId": normalized_plan,
                "errorType": "DevFlowConflict",
                "errorDetail": str(exc)[:320],
            },
        )
        raise
    except Exception as exc:
        _record_scene_event(
            "challenge_cup_dev_controls.batch.failed",
            message="Challenge Cup DEV fixture batch failed.",
            outcome="failed",
            fields={
                "teamId": authoritative_team_id,
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
            "teamId": authoritative_team_id,
            "planId": normalized_plan,
            "attemptedCount": len(result["attempted"]),
            "succeededCount": projection["succeededCount"],
            "pendingCount": projection["pendingCount"],
            "canResume": projection["canResume"],
        },
    )
    return {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "teamId": authoritative_team_id,
        "planId": normalized_plan,
        "gateId": projection["gateId"],
        "attempted": result["attempted"],
        "outcomes": project_dev_batch_outcomes(result["outcomes"]),
        "checkpoint": projection,
        "persistedAt": persisted_at,
        "persisted": True,
    }
