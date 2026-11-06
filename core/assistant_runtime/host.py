"""Private loopback API for the Launcher assistant, without Workbench lifespan."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import secrets
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from contextlib import nullcontext
from functools import partial
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .budget_parameters import AssistantBudgetParameters
from .cache_usage import AssistantUsageSummary

# The renderer polls /api/assistant at a multi-second cadence while chat detail
# and submit hold native._LOCK for their own reads. Serving the lock-bound
# identity reads from this snapshot bounds every status response without
# holding the native lock; only background refreshes touch it, at most one
# outstanding refresh per facade.
IDENTITY_SNAPSHOT_TTL_SECONDS = 2.0


_INITIAL_PREPARE_CODES = frozenset({
    "initial_migration_request_invalid", "initial_migration_busy", "initial_migration_unavailable",
    "initial_migration_turn_invalid", "initial_migration_binding_invalid", "initial_migration_binding_changed",
    "initial_migration_directory_identity_unavailable", "initial_intent_invalid", "initial_intent_limit",
    "initial_intent_exists", "initial_intent_claimed_unknown", "initial_profile_owner_unavailable",
    "initial_delivery_unavailable", "history_preview_expired", "history_preview_changed",
    "history_source_unavailable", "source_unavailable", "source_changed",
    "knowledge_sync_baseline_unavailable", "knowledge_sync_prior_unknown", "knowledge_sync_intent_exists",
    "knowledge_sync_recovery_invalid", "knowledge_sync_recovery_finished", "knowledge_sync_recovery_pending",
    "initial_receipts_unknown",
    "source_unavailable_or_changed", "source_guard_unavailable", "source_authority_required",
    "migration_lock_unavailable", "target_directory_unavailable", "target_namespace_unavailable",
    "target_pending_changed", "target_publish_unavailable", "target_lock_leaf_unavailable",
})


def _initial_prepare_failure_code(error):
    """Use only a closed list of internal codes; exceptions may contain paths or secrets."""
    from .migration_io import MigrationIOError
    if isinstance(error, MigrationIOError):
        code = str(error)
        return code if code in _INITIAL_PREPARE_CODES else "migration_error"
    if isinstance(error, PermissionError):
        return "permission_error"
    if isinstance(error, FileNotFoundError):
        return "filesystem_missing"
    if isinstance(error, OSError):
        return "filesystem_error"
    if isinstance(error, ValueError):
        return "value_error"
    return "unexpected_error"


class MigrationQuiescenceUnavailable(RuntimeError):
    """No completed drain proof; keep the resident host and retry later."""


_MIGRATION_BARRIER_CODES = frozenset({
    "dispatch_unavailable", "session_unavailable", "history_busy", "session_busy_or_unknown",
    "session_release_unknown", "dispatch_busy_or_unknown", "main_control_busy_or_unknown",
    "ASSISTANT_QUIESCENCE_BUSY", "ASSISTANT_QUIESCENCE_UNKNOWN", "ASSISTANT_QUIESCENCE_UNAVAILABLE",
    "ASSISTANT_IDENTITY_INVALID", "DISPATCH_DRAIN_ADMISSION_BUSY", "DISPATCH_DRAIN_ACTIVE",
    "DISPATCH_DRAIN_INACTIVE", "DISPATCH_DRAIN_OWNER", "DISPATCH_DRAIN_SEALED",
    "PROJECT_REGISTRY_RECONCILE_REQUIRED", "records_unknown", "records_changed", "not_terminal",
    "reminder_lease_owner_closed", "reminder_lease_unavailable", "cancelled",
})


def _log_migration_quiescence_failure(stage, reason, started, *, barrier=False):
    """Emit only fixed codes; exception messages and observations remain private."""
    code = reason if isinstance(reason, str) else getattr(reason, "code", None)
    if code is None and isinstance(reason, BaseException) and len(reason.args) == 1:
        code = reason.args[0]
    if type(code) is not str or code not in _MIGRATION_BARRIER_CODES:
        code = "unexpected"
    logging.getLogger(__name__).warning("%s stage=%s code=%s elapsed_ms=%d",
        "assistant_migration_barrier" if barrier else "assistant_migration_quiescence",
        stage, code, max(0, round((time.monotonic() - started) * 1000)))


@asynccontextmanager
async def migration_runtime_quiescence(native, dispatch, history_control, main_control):
    """Hold native Session, history writer, and dispatch fences together.

    Caller must first fence and drain every external/main producer, including
    reminder senders and HTTP mutation admission, and retain those fences for
    this entire scope. This helper never itself authorizes host shutdown.
    """
    started = time.monotonic()
    if dispatch is None or not callable(getattr(dispatch, "drain_fence", None)):
        _log_migration_quiescence_failure("dispatch_fence", "dispatch_unavailable", started)
        raise MigrationQuiescenceUnavailable("dispatch_unavailable")
    session_quiescence = getattr(native, "session_quiescence", None)
    if not callable(session_quiescence):
        _log_migration_quiescence_failure("native_quiescence", "session_unavailable", started)
        raise MigrationQuiescenceUnavailable("session_unavailable")
    loop = asyncio.get_running_loop()
    ready = loop.create_future()
    release = threading.Event()

    def worker():
        stage = "native_quiescence"
        try:
            with session_quiescence():
                stage = "history_import"
                lock = getattr(history_control, "_import_lock", None) if history_control is not None else None
                if history_control is not None and (lock is None or not lock.acquire(blocking=False)):
                    raise MigrationQuiescenceUnavailable("history_busy")
                try:
                    stage = "barrier_hold"
                    loop.call_soon_threadsafe(lambda: not ready.done() and ready.set_result(None))
                    release.wait()
                finally:
                    stage = "history_release"
                    if lock is not None:
                        lock.release()
                stage = "native_release"
            return True
        except Exception as error:
            _log_migration_quiescence_failure(stage, error, started)
            loop.call_soon_threadsafe(lambda: not ready.done() and ready.set_exception(
                MigrationQuiescenceUnavailable("session_busy_or_unknown")))
            return False

    owner = asyncio.create_task(asyncio.to_thread(worker))
    try:
        await ready
        stage = "dispatch_fence"
        try:
            async with dispatch.drain_fence() as fence:
                stage = "dispatch_observation"
                observation = await fence.observe()
                blocked = None
                if not isinstance(observation, dict) or observation.get("drained") is not True:
                    blocked = "dispatch_busy_or_unknown"
                    reason = observation.get("reason", blocked) if isinstance(observation, dict) else blocked
                    _log_migration_quiescence_failure(stage, reason, started)
                elif main_control is not None:
                    stage = "main_control"
                    pending = getattr(main_control, "_pending", None)
                    tokens = getattr(main_control, "_initial_tokens", None)
                    if not isinstance(pending, dict) or pending or not isinstance(tokens, set) or any(
                            not token._done.is_set() for token in tokens):
                        blocked = "main_control_busy_or_unknown"
                        _log_migration_quiescence_failure(stage, blocked, started)
                if blocked is None:
                    stage = "barrier_hold"
                    yield
                stage = "dispatch_release"
        except Exception as error:
            _log_migration_quiescence_failure(stage, error, started)
            raise
        if blocked is not None:
            raise MigrationQuiescenceUnavailable(blocked)
    finally:
        release.set()
        if not await asyncio.shield(owner):
            raise MigrationQuiescenceUnavailable("session_release_unknown")


class ControlContinuation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    agentId: str = Field(min_length=1, max_length=160, pattern=r"^\S(?:.*\S)?$")
    sessionId: str = Field(min_length=1, max_length=160, pattern=r"^\S(?:.*\S)?$")
    turnId: str = Field(min_length=1, max_length=160, pattern=r"^\S(?:.*\S)?$")
    headId: str = Field(min_length=1, max_length=200, pattern=r"^\S(?:.*\S)?$")
    ledgerSeq: int = Field(ge=1, le=2**53 - 1)


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(max_length=64000)
    requestId: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    attachmentIds: list[str] = Field(default_factory=list, max_length=8)
    references: list[dict] = Field(default_factory=list, max_length=8)
    controlContinuation: ControlContinuation | None = None

    @model_validator(mode="after")
    def validate_content(self):
        if "controlContinuation" in self.model_fields_set:
            from .control_continuation import CONTROL_CONTINUATION_MESSAGE
            if (self.controlContinuation is None or self.message != CONTROL_CONTINUATION_MESSAGE
                    or self.attachmentIds or self.references):
                raise ValueError("Invalid control continuation message")
        if not self.message.strip() and not self.attachmentIds:
            raise ValueError("Message or attachments required")
        if any(not isinstance(item, str) or not item or len(item) > 255
               or item in {".", ".."} or not all(ch.isascii() and (ch.isalnum() or ch in "_.-") for ch in item)
               for item in self.attachmentIds):
            raise ValueError("Invalid attachment IDs")
        return self


class AttachmentRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    artifactId: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_.-]+$")


class SetModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    modelId: str = Field(min_length=1, max_length=200, pattern=r"^[^\s\x00-\x1f\x7f]+$")


class SetManagementPermission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    preset: Literal["request_approval", "auto_review", "full_access"]
    expectedRevision: int = Field(ge=0, le=2**53 - 1)


class ManagementPermission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    preset: Literal["request_approval", "auto_review", "full_access"]
    revision: int = Field(ge=0, le=2**53 - 1)


class StopTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turnId: str = Field(min_length=1, max_length=160, pattern=r"\S", strict=True)


class QueuedTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    queuedTurnId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")


class UpdateQueuedTurn(QueuedTurn):
    content: str | None = Field(default=None, max_length=64000)
    position: int | None = Field(default=None, ge=1, le=2**53 - 1)
    status: Literal["paused", "queued"] | None = None

    @model_validator(mode="after")
    def reject_null_fields(self):
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Queue update fields cannot be null")
        return self


class SendNowQueuedTurn(QueuedTurn):
    expectedTurnId: str | None = Field(default=None, min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")

    @model_validator(mode="after")
    def reject_null_turn(self):
        if "expectedTurnId" in self.model_fields_set and self.expectedTurnId is None:
            raise ValueError("Expected turn cannot be null")
        return self


class SwitchHead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodeId: str = Field(min_length=1, max_length=200, pattern=r"\S", strict=True)


class RegenerateMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messageId: str = Field(min_length=1, max_length=160, pattern=r"\S", strict=True)
    requestId: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$", strict=True)


class Guidance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=64000)
    mode: Literal["safe", "interrupt"]

    @model_validator(mode="after")
    def validate_content(self):
        if not self.content.strip():
            raise ValueError("Guidance content required")
        return self


class Continuation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turnId: str = Field(min_length=1, max_length=160, pattern=r"\S", strict=True)
    headId: str = Field(min_length=1, max_length=200, pattern=r"\S", strict=True)
    ledgerSeq: int = Field(ge=1, strict=True)
    agentId: str = Field(min_length=1, max_length=160, pattern=r"\S", strict=True)


class ContinueTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$", strict=True)
    continuation: Continuation


class Curation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messageId: str = Field(min_length=1, max_length=160)
    action: str = Field(min_length=1, max_length=40)


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    decision: Literal["accept", "decline"]


class DispatchApprovalPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dispatchId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    taskId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    approvalId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")


class DispatchApprovalDecline(DispatchApprovalPreview):
    revision: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$")


class DispatchApprovalBoundDecision(DispatchApprovalPreview):
    revision: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    decision: Literal["accept", "decline"]


class DispatchCorruptDismiss(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dispatchId: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    confirmed: bool
    reason: str = Field(default="", max_length=300)


class ReminderSettlement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    eventId: str = Field(pattern=r"^reminder:[0-9]{8}:[a-f0-9]{64}$")
    attemptToken: str = Field(pattern=r"^[a-f0-9]{64}$")
    channel: Literal["assistant_window", "system_notification", "attention_fallback"]


class ReminderFallback(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    eventId: str = Field(pattern=r"^reminder:[0-9]{8}:[a-f0-9]{64}$")
    attemptToken: str = Field(pattern=r"^[a-f0-9]{64}$")


class LegacyReminderReservation(BaseModel):
    """Private main-only request; sourceKey is bound by Electron main."""
    model_config = ConfigDict(extra="forbid", strict=True)
    sourceKey: str = Field(pattern=r"^[a-f0-9]{64}$")
    eventId: str = Field(max_length=128, pattern=r"^affair-reminder:[A-Za-z0-9._:-]{1,103}:[0-9]{8}$")


class LegacyReminderAttempt(LegacyReminderReservation):
    attemptToken: str = Field(pattern=r"^[a-f0-9]{64}$")


class LegacyReminderSettlement(LegacyReminderAttempt):
    channel: Literal["assistant_window", "system_notification", "attention_fallback"]


class LegacyReminderInventory(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LegacyReminderSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    projectId: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
    revision: int = Field(ge=0, le=2**53 - 1)


class LegacyReminderPermit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    permitId: str = Field(pattern=r"^[a-f0-9]{64}$")


class LegacyReminderPermitAcquire(LegacyReminderSource):
    permitId: str = Field(pattern=r"^[a-f0-9]{64}$")


class ProjectSnapshot(BaseModel):
    """Main-only authorization projection; deliberately absent from renderer IPC."""
    model_config = ConfigDict(extra="forbid", strict=True)
    schemaVersion: Literal[1]
    revision: int = Field(ge=0)
    projects: dict[str, str] = Field(max_length=128)


class SuspendProjects(BaseModel):
    """Main may only close the gate; restoring requires a full snapshot PUT."""
    model_config = ConfigDict(extra="forbid", strict=True)


class HistoryImport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    projectId: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
    previewId: str = Field(pattern=r"^[a-f0-9]{64}$")
    turnId: str = Field(min_length=1, max_length=160, pattern=r"^\S+$")
    revision: int = Field(ge=0)
    operationId: str = Field(pattern=r"^[a-f0-9]{32}$")


class HistoryReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    projectId: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
    previewId: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(ge=0)


class AffairsSync(HistoryImport):
    recoverSyncId: str | None = Field(default=None, pattern=r"^affairs-[a-f0-9]{40}$")


class EpisodicSync(HistoryImport):
    recoverSyncId: str | None = Field(default=None, pattern=r"^episodic-[a-f0-9]{40}$")
    resolveSyncId: str | None = Field(default=None, pattern=r"^episodic-[a-f0-9]{40}$")
    reviewToken: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def resolution_binding(self):
        if ((self.resolveSyncId is None) != (self.reviewToken is None)
                or self.resolveSyncId is not None and self.recoverSyncId is not None):
            raise ValueError("Invalid episodic resolution")
        return self


class InitialMigrationPrepare(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    deliveryId: str = Field(pattern=r"^[a-f0-9]{32}$")
    projectId: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
    previewId: str = Field(pattern=r"^[a-f0-9]{64}$")
    turnId: str = Field(min_length=1, max_length=160, pattern=r"^\S+$")
    revision: int = Field(ge=0)
    operationId: str = Field(pattern=r"^(?:initial|ksync|krec)-[a-f0-9]{40}$")
    category: Literal["personal", "knowledge", "knowledge_sync", "knowledge_recovery", "reminder_handoff"]
    originalSyncId: str | None = Field(default=None, pattern=r"^ksync-[a-f0-9]{40}$")
    reauthorize: bool | None = None

    @model_validator(mode="after")
    def recovery_binding(self):
        if (self.category == "knowledge_recovery") != (self.originalSyncId is not None):
            raise ValueError("Invalid knowledge recovery binding")
        if "reauthorize" in self.model_fields_set and (self.reauthorize is not True or self.category != "reminder_handoff"):
            raise ValueError("Invalid reminder recovery binding")
        return self


class InitialMigrationDrain(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    deliveryId: str = Field(pattern=r"^[a-f0-9]{32}$")
    operationId: str = Field(pattern=r"^(?:initial|ksync|krec)-[a-f0-9]{40}$")


class CancelHistoryImport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operationId: str = Field(pattern=r"^[a-f0-9]{32}$")
    previewId: str = Field(pattern=r"^[a-f0-9]{64}$")


def _operator_profile() -> dict[str, str] | None:
    """Read only the two display fields from the bound operator document."""
    from config.editor_schema_data import USER_AVATAR_PRESET_OPTIONS
    from config.paths import resolve_config_path
    from config.public_config import read_existing_config_snapshot

    try:
        config = read_existing_config_snapshot(resolve_config_path())
    except (OSError, ValueError):
        return None
    profile = config.get("user_profile", {})
    if not isinstance(profile, dict):
        return None
    name = profile.get("display_name", "")
    preset = profile.get("avatar_preset", "default")
    if (not isinstance(name, str) or len(name) > 120
            or (name.strip() and any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in name))
            or not isinstance(preset, str) or preset not in USER_AVATAR_PRESET_OPTIONS):
        return None
    name = name.strip()
    if not name:
        from core.web.services.runtime_service import _local_user_name
        name = _local_user_name()
        if (len(name) > 120 or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in name)):
            return None
    return {"displayName": name, "avatarPreset": preset}


def _model_image_input_support(agent_id: str) -> bool | None:
    """Best-effort image-input capability of the assistant's dialogue model.

    Same source as the chat page's submit preflight. ``None`` means unknown
    (catalog, snapshot or service unavailable): the renderer stays quiet and
    never blocks a send on unknown capability. Failures here must not degrade
    the lightweight status read."""
    if not isinstance(agent_id, str) or not agent_id.strip():
        return None
    try:
        from core.web.services import agent_directory_service, session_service

        agent = agent_directory_service.get_agent_parameter_snapshot(agent_id, include_archived=False)
        if not isinstance(agent, dict) or agent.get("agentId") != agent_id:
            return None
        value = session_service._resolve_image_attachment_capability(agent_instance=agent).get("supports_image_input")
        return value if isinstance(value, bool) else None
    except Exception:  # noqa: BLE001 - a capability read failure only means "unknown".
        return None


class NativeFacade:
    """Bind the narrow host API to one immutable native assistant identity."""

    def __init__(self, root):
        self.root = root
        self.assistant = None
        # The three native reads below all serialize on native._LOCK. The
        # renderer's lightweight status poll used to queue behind chat detail
        # and submit holds (observed >15s). The snapshot is served stale while
        # one background refresh recomputes it, so status reads never wait on
        # the native lock. Identity is immutable after bootstrap; settings
        # setters invalidate their mutable projection. Lock-free reads
        # (operator assets/profile, image-input capability) stay per-call.
        self._snapshot_lock = threading.Lock()
        self._identity_snapshot: dict[str, Any] | None = None
        self._identity_refreshing = False
        self._identity_generation = 0

    def bootstrap(self):
        from . import native
        result = native.bootstrap(self.root)
        self.assistant = result["assistant"]
        with self._snapshot_lock:
            self._identity_generation += 1
            self._identity_snapshot = None
        return result

    def get_detail(self, before_message_index=None):
        from . import native
        return native.get_detail(self.assistant["directSessionId"], **(
            {"before_message_index": before_message_index} if before_message_index is not None else {}))

    def _identity_snapshot_refresh(self):
        from . import native
        with self._snapshot_lock:
            generation = self._identity_generation
        projection = native.identity()
        settings = native.assistant_settings()
        avatar_revision = native.assistant_avatar_revision()
        with self._snapshot_lock:
            # A settings write that invalidated mid-read must not be undone
            # by this older generation landing late.
            if generation == self._identity_generation:
                self._identity_snapshot = {"at": time.monotonic(), "projection": projection,
                                           "settings": settings, "avatarRevision": avatar_revision}

    def _identity_snapshot_for_read(self):
        """A fresh-enough snapshot immediately; stale ones recompute in background."""
        with self._snapshot_lock:
            snapshot = self._identity_snapshot
            stale = snapshot is not None and time.monotonic() - snapshot["at"] >= IDENTITY_SNAPSHOT_TTL_SECONDS
            if stale and not self._identity_refreshing:
                self._identity_refreshing = True
            elif snapshot is not None:
                stale = False
        if snapshot is None:
            # A setter can invalidate the generation while a cold read is in
            # flight. Retry once without holding the publication lock across
            # native reads; persistent contention stays a bounded 503.
            for _attempt in range(2):
                self._identity_snapshot_refresh()
                with self._snapshot_lock:
                    snapshot = self._identity_snapshot
                if snapshot is not None:
                    return snapshot
            from .native import AssistantSessionError
            raise AssistantSessionError("ASSISTANT_NOT_READY")
        if stale:
            def refresh():
                try:
                    self._identity_snapshot_refresh()
                except Exception:  # noqa: BLE001 - keep serving the last validated snapshot.
                    pass
                finally:
                    with self._snapshot_lock:
                        self._identity_refreshing = False
            try:
                threading.Thread(target=refresh, daemon=True,
                                 name="assistant_identity_refresh").start()
            except Exception:  # noqa: BLE001 - retry the refresh on the next read.
                with self._snapshot_lock:
                    self._identity_refreshing = False
        return snapshot

    def identity(self):
        from . import operator_assets
        snapshot = self._identity_snapshot_for_read()
        result = dict(snapshot["projection"])
        result["operatorAssetsVersion"] = 1
        result["operatorAssetRevisions"] = operator_assets.operator_asset_revisions()
        result["assistantAvatarVersion"] = 1
        result["assistantAvatarRevision"] = snapshot["avatarRevision"]
        result["attachmentVersion"] = 1
        # Copies keep the stored snapshot untouched by response-level hints.
        result["settings"] = dict(snapshot["settings"])
        # Additive capability hint for the renderer's attach gate; the tool
        # contract's own settings payload stays untouched.
        result["settings"]["supportsImageInput"] = _model_image_input_support(
            str((result.get("assistant") or {}).get("agentId") or ""))
        profile = _operator_profile()
        if profile is not None:
            result["operatorProfile"] = profile
        return result

    def set_model(self, model_id):
        from . import native
        result = native.set_model(model_id)
        # settings.modelId changed; the next status read must observe it, and
        # any refresh already reading old settings must not land afterwards.
        with self._snapshot_lock:
            self._identity_generation += 1
            self._identity_snapshot = None
        return result

    def set_management_permission(self, preset, expected_revision):
        from . import native
        result = native.set_management_permission(preset, expected_revision)
        with self._snapshot_lock:
            self._identity_generation += 1
            self._identity_snapshot = None
        return result

    def usage_summary(self):
        from . import native
        return native.usage_summary()

    def budget_parameters(self):
        from . import native
        return native.budget_parameters()

    def set_budget_parameters(self, max_calls_per_turn, expected_revision):
        from . import native
        return native.set_budget_parameters(max_calls_per_turn, expected_revision)

    def avatar(self):
        from . import native
        return native.read_assistant_avatar()

    def approvals(self):
        from core.web.services.session.tool_approvals import list_tool_approval_requests
        return list_tool_approval_requests(self.assistant["directSessionId"], status="pending")

    def resolve_approval(self, request_id, decision):
        from core.web.services.session.tool_approvals import (
            resolve_tool_approval_request,
        )
        return resolve_tool_approval_request(self.assistant["directSessionId"], request_id, decision=decision)

    def submit(self, message, request_id, attachment_ids=None, references=None, *, control_continuation=None):
        from . import native
        if control_continuation is not None:
            return native.submit(message, request_id, attachment_ids, references,
                                 control_continuation=control_continuation)
        return native.submit(message, request_id, attachment_ids, references)

    def upload_attachment(self, payload, filename, content_type):
        from . import native
        return native.upload_attachment(payload, filename=filename, content_type=content_type)

    def upload_secret_attachment(self, value, kind="secret", label=""):
        from . import native
        return native.upload_secret_attachment(value, kind=kind, label=label)

    def read_attachment(self, artifact_id):
        from . import native
        return native.read_attachment(artifact_id)

    def stop(self, turn_id):
        from . import native
        return native.stop(turn_id)

    def update_queued_turn(self, queued_turn_id, *, content=None, position=None, status=None):
        from . import native
        return native.update_queued_turn(queued_turn_id, content=content, position=position, status=status)

    def remove_queued_turn(self, queued_turn_id):
        from . import native
        return native.remove_queued_turn(queued_turn_id)

    def send_now_queued_turn(self, queued_turn_id, *, expected_turn_id=""):
        from . import native
        return native.send_now_queued_turn(queued_turn_id, expected_turn_id=expected_turn_id)

    def continue_turn(self, request_id, continuation):
        from . import native
        return native.continue_turn(request_id, continuation)

    def switch_head(self, node_id):
        from . import native
        return native.switch_head(node_id)

    def regenerate(self, message_id, request_id):
        from . import native
        return native.regenerate(message_id, request_id)

    def guidance(self, content, mode):
        from . import native
        return native.guidance(content, mode)

    def shutdown(self):
        from . import native
        return native.shutdown()

    def session_quiescence(self):
        from . import native
        return native.session_quiescence()

    def lifecycle_status(self):
        from . import native
        return native.lifecycle_status()

    def commit_quiescent_shutdown(self):
        from . import native
        return native.commit_quiescent_shutdown()

    def config(self):
        from core.web.services.config_service import get_config_bootstrap
        return get_config_bootstrap()

    def curation(self):
        from core.web.services import session_service
        return session_service.get_session_message_curation(self.assistant["directSessionId"])

    def curate(self, message_id, action):
        from core.web.services import session_service
        return session_service.set_session_message_curation(
            self.assistant["directSessionId"], message_id, action=action)

    async def events(self, last_event_id):
        from core.web.services import session_service
        session_id = self.assistant["directSessionId"]
        cursor = session_service.parse_session_stream_last_event_id(last_event_id)
        async for event in session_service.stream_session_events_async(
            session_id, initial="full", last_event_id=cursor
        ):
            yield event


def create_app(*, native, token: str, dispatch=None, main_control=None, history_control=None, on_ready: Callable | None = None,
               on_shutdown: Callable | None = None) -> FastAPI:
    if len(token) < 16:
        raise ValueError("Assistant host requires a private bearer credential")
    if main_control is not None and history_control is not None:
        bind_retirement = getattr(main_control, "bind_preview_retirement", None)
        if callable(bind_retirement):
            bind_retirement(history_control.retire_preview)

    source_permits = None
    if dispatch is not None and history_control is not None:
        preview = getattr(history_control, "_preview", None)
        if getattr(preview, "_dispatch", None) is dispatch:
            from .reminder_source_lease import ReminderSourceLeaseOwner
            source_permits = ReminderSourceLeaseOwner(dispatch, preview)
    source_fence_lock = asyncio.Lock()

    @asynccontextmanager
    async def source_permit_fence():
        if source_permits is None:
            yield
            return
        async with source_fence_lock:
            source_permits.begin_revocation()
            drained = False
            try:
                await asyncio.to_thread(source_permits.wait_revocation)
                drained = True
                yield
            finally:
                # An interrupted wait cannot certify that the sender drained.
                if drained:
                    source_permits.end_revocation()

    migration = {"gate": False, "writers": 0, "changed": asyncio.Event(),
                 "task": None, "release": None, "state": "idle", "committing": False}

    # Receipt store outcomes, split so the desktop and recovery flows can
    # distinguish "retry the identical request" from "reconcile instead".
    _LEGACY_UNKNOWN_OUTCOME_CODES = {"receipt_commit_outcome_unknown", "receipt_close_unavailable",
                                     "legacy_reminder_owner_closed"}
    _LEGACY_TRANSIENT_CODES = {"receipt_store_busy", "receipt_store_unavailable",
                               "receipt_open_unavailable", "receipt_leaf_unavailable",
                               "receipt_journal_unavailable", "receipt_sync_unavailable"}
    # Permit lease states a caller may wait out and retry (bounded capacity or
    # a transiently failed release whose pins stay attested), versus states
    # that need a different permit id, a changed source, or owner recovery.
    _PERMIT_RETRYABLE_CODES = {"reminder_lease_capacity", "reminder_lease_release_unavailable"}

    def permit_failure(error):
        from .migration_io import MigrationIOError
        code = str(error) if isinstance(error, MigrationIOError) else "reminder_lease_unavailable"
        return HTTPException(409, detail={"code": code,
                                          "retryable": code in _PERMIT_RETRYABLE_CODES})

    async def hold_migration_barrier():
        started = time.monotonic()
        stage = "http_writers"
        try:
            while migration["writers"]:
                migration["changed"].clear()
                if migration["writers"]:
                    await migration["changed"].wait()
            stage = "source_permits"
            async with source_permit_fence():
                stage = "runtime_quiescence"
                async with migration_runtime_quiescence(native, dispatch, history_control, main_control):
                    if migration["release"].is_set():
                        migration["state"] = "released"
                        return
                    migration["state"] = "ready"
                    stage = "barrier_hold"
                    await migration["release"].wait()
                    stage = "runtime_release"
                stage = "source_permits_release"
            migration["state"] = "released"
        except asyncio.CancelledError:
            _log_migration_quiescence_failure(stage, "cancelled", started, barrier=True)
            migration["state"] = "busy"
            raise
        except Exception as error:
            _log_migration_quiescence_failure(stage, error, started, barrier=True)
            migration["state"] = "busy"
        finally:
            if not migration["committing"]:
                migration["gate"] = False

    @asynccontextmanager
    async def initial_fence(turn_id=None, *, registry=False):
        if main_control is None or not getattr(main_control, "initial_migration_enabled", False):
            yield
            return
        tokens = main_control.begin_initial_fence(turn_id)
        try:
            if not await asyncio.to_thread(main_control.drain_initial_fence, tokens):
                raise HTTPException(503, detail="Initial migration publication outcome unknown")
            if registry and tokens and history_control is not None:
                if not await asyncio.to_thread(history_control.wait_guard_idle):
                    raise HTTPException(503, detail="Initial migration publication outcome unknown")
            yield
        finally:
            main_control.end_initial_fence(turn_id)

    async def patrol_call(method, *args):
        # Cancellation must not release the owner while its thread is still
        # admitting a native turn or committing a receipt.
        work = asyncio.create_task(asyncio.to_thread(method, *args))
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            with suppress(Exception):
                await work
            raise

    async def create_patrol(*args):
        from .patrol import LauncherPatrol
        work = asyncio.create_task(asyncio.to_thread(LauncherPatrol, *args))
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            # Constructor acquires a process-global owner and directory pin.
            # An abandoned executor future could acquire them after shutdown.
            try:
                owner = await work
            except Exception:
                pass
            else:
                await asyncio.to_thread(owner.close)
            raise

    async def maintain_dispatches():
        while True:
            try:
                await dispatch.heartbeat()
                patrol = getattr(app.state, "patrol", None)
                if patrol is not None:
                    # Heartbeat omits previously terminal tasks; use the full
                    # durable native projection so delayed wakeups survive.
                    await patrol.refresh_stale_terminals(dispatch.list_dispatches())
                    teams = await patrol.refresh_team_runs()
                    platform = await patrol.refresh_platform_runs()
                    result = await patrol_call(patrol.inspect, [*dispatch.list_dispatches(), *teams, *platform])
                    app.state.patrol_status = {"state": "ready", "deliveryStates": result.get("deliveryStates", {}),
                                              "teamRuns": patrol.team_observation,
                                              "platform": patrol.platform_observation,
                                              "deliveryEscalations": patrol.delivery_escalations}
            except Exception:  # noqa: BLE001 - private backend data stays out of logs.
                # Native IDs and credentials remain durable. A failed poll is
                # not permission to repeat a task or cancel it.
                if getattr(app.state, "patrol", None) is not None:
                    app.state.patrol_status = {"state": "unavailable", "deliveryStates": {}}
            await asyncio.sleep(10)

    @asynccontextmanager
    async def lifespan(app):
        task = None
        bound = False
        reminder_executor = None
        legacy_reminder_executor = None
        patrol = None
        app.state.patrol = None
        app.state.patrol_status = None
        try:
            if dispatch is not None:
                from .actions import bind_actions, unbind_actions
                bind_actions(dispatch, asyncio.get_running_loop(), main_control=main_control)
                bound = True
            # Native startup recovery can immediately resume a tool-using
            # worker. Its authorized action owner must already be available.
            app.state.assistant = await asyncio.to_thread(native.bootstrap)
            if isinstance(native, NativeFacade):
                from .reminders import LauncherReminders
                reminder_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="assistant-reminders")
                app.state.reminder_executor = reminder_executor
                app.state.reminders = await asyncio.get_running_loop().run_in_executor(
                    reminder_executor, LauncherReminders, native.root, native.assistant["agentId"])
                from .legacy_reminder_receipts import LegacyReminderReceipts
                legacy_reminder_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="legacy-reminder-receipts")
                app.state.legacy_reminder_executor = legacy_reminder_executor
                app.state.legacy_reminder_receipts = await asyncio.get_running_loop().run_in_executor(
                    legacy_reminder_executor, LegacyReminderReceipts, native.root / "legacy_reminder_receipts")
            if dispatch is not None and isinstance(native, NativeFacade):
                try:
                    patrol = await create_patrol(native.root, native.assistant["agentId"],
                                                 native.assistant["directSessionId"], dispatch)
                    state = await patrol_call(patrol.reconcile)
                    app.state.patrol = patrol
                    app.state.patrol_status = {"state": "ready", "deliveryStates": state,
                                              "deliveryEscalations": patrol.delivery_escalations}
                except Exception:  # noqa: BLE001 - corrupted patrol state must not block chat startup.
                    if patrol is not None:
                        await asyncio.to_thread(patrol.close)
                        patrol = None
                    app.state.patrol_status = {"state": "unavailable", "deliveryStates": {}}
            if dispatch is not None:
                task = asyncio.create_task(maintain_dispatches())
            if on_ready is not None:
                on_ready()
            yield
        finally:
            barrier_task = migration["task"]
            if barrier_task is not None and not barrier_task.done():
                barrier_task.cancel()
                with suppress(asyncio.CancelledError):
                    await barrier_task
            if source_permits is not None:
                await asyncio.to_thread(source_permits.close)
            if history_control is not None:
                await asyncio.to_thread(history_control.close)
            # Release synchronous tool waiters before draining their native
            # worker; shutdown must never wait on its own main-control request.
            if main_control is not None:
                main_control.close()
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            # Native own chat is drained; remote tasks are never cancelled by
            # an HTTP connection, renderer close, or this host's shutdown.
            try:
                try:
                    try:
                        if legacy_reminder_executor is not None and hasattr(app.state, "legacy_reminder_receipts"):
                            await asyncio.get_running_loop().run_in_executor(legacy_reminder_executor, app.state.legacy_reminder_receipts.close)
                    finally:
                        if reminder_executor is not None and hasattr(app.state, "reminders"):
                            await asyncio.get_running_loop().run_in_executor(reminder_executor, app.state.reminders.close)
                finally:
                    try:
                        if legacy_reminder_executor is not None:
                            await asyncio.to_thread(legacy_reminder_executor.shutdown, wait=True)
                    finally:
                        try:
                            if reminder_executor is not None:
                                await asyncio.to_thread(reminder_executor.shutdown, wait=True)
                        finally:
                            closed = await asyncio.to_thread(native.shutdown)
                            # Native plugin cancellation/finalization can still
                            # use patrol until the real session owner is closed.
                            if patrol is not None and isinstance(closed, dict) and closed.get("closed") is True:
                                await asyncio.to_thread(patrol.close)
            finally:
                if bound:
                    unbind_actions(dispatch)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    from .native import AssistantSessionError

    from fastapi.exceptions import RequestValidationError
    from fastapi.exception_handlers import request_validation_exception_handler

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request, error: RequestValidationError):
        if request.url.path == "/api/assistant/budget-parameters":
            return JSONResponse({"detail": {"code": "ASSISTANT_BUDGET_INVALID",
                "message": "The assistant budget request is invalid"}}, status_code=422)
        if request.url.path == "/api/assistant/management-permission":
            return JSONResponse({"detail": {"code": "ASSISTANT_PERMISSION_INVALID",
                "message": "The management permission request is invalid"}}, status_code=422)
        return await request_validation_exception_handler(request, error)

    @app.exception_handler(AssistantSessionError)
    async def session_command_error(_request: Request, error: AssistantSessionError):
        errors = {
            "ASSISTANT_NOT_READY": (503, "Native assistant is not ready"),
            "ASSISTANT_STOPPING": (503, "Native assistant is stopping"),
            "ASSISTANT_IDENTITY_INVALID": (409, "Native assistant identity changed"),
            "SESSION_NOT_FOUND": (404, "Native assistant session not found"),
            "SESSION_CONFLICT": (409, "Native session changed; refresh before retrying"),
            "SESSION_INVALID": (422, "Native session command is invalid"),
            "ASSISTANT_MODEL_BUSY": (409, "Wait for the assistant to finish before changing its model"),
            "ASSISTANT_MODEL_CONFLICT": (409, "Assistant model changed; refresh before retrying"),
            "ASSISTANT_MODEL_INVALID": (422, "The assistant model is not available for selection"),
            "ASSISTANT_MODEL_UNAVAILABLE": (503, "The assistant model settings are unavailable"),
            "ASSISTANT_PERMISSION_INVALID": (422, "The management permission request is invalid"),
            "ASSISTANT_PERMISSION_CONFLICT": (409, "Management permission changed; refresh before retrying"),
            "ASSISTANT_PERMISSION_UNAVAILABLE": (503, "Management permission settings are unavailable"),
            "ASSISTANT_BUDGET_INVALID": (422, "The assistant budget request is invalid"),
            "ASSISTANT_BUDGET_CONFLICT": (409, "Assistant budget changed; refresh before retrying"),
            "ASSISTANT_BUDGET_UNAVAILABLE": (503, "Assistant budget settings are unavailable"),
            "ASSISTANT_USAGE_INVALID": (422, "The assistant usage request is invalid"),
            "ASSISTANT_USAGE_UNAVAILABLE": (503, "Assistant usage is unavailable"),
            "ASSISTANT_QUIESCING": (503, "Native assistant is quiescing; retry after the migration fence"),
            "ASSISTANT_QUIESCENCE_BUSY": (503, "Native assistant is quiescing; retry after the migration fence"),
            "ATTACHMENT_NOT_FOUND": (404, "Native assistant attachment not found"),
            "OFFLINE_MIGRATION_READ_ONLY": (503, "Native assistant is read-only during migration"),
        }
        status, message = errors.get(error.code, (500, "Native session command failed"))
        code = error.code if error.code in errors else "SESSION_OPERATION_FAILED"
        return JSONResponse({"detail": {"code": code, "message": message}}, status_code=status)

    @app.middleware("http")
    async def private_launcher_boundary(request: Request, call_next):
        host = request.url.hostname
        if host not in {"127.0.0.1", "localhost"} or request.headers.get("origin"):
            return JSONResponse({"error": "launcher_origin_required"}, status_code=403)
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied, "Bearer " + token):
            return JSONResponse({"error": "launcher_auth_required"}, status_code=401)
        path = request.url.path
        control = path.startswith("/api/assistant/migration-barrier/") or path == "/api/assistant/shutdown"
        writing = request.method not in {"GET", "HEAD", "OPTIONS"} and not control
        # Existing control deliveries must be able to settle normally; their
        # native waiter remains part of the barrier until settlement finishes.
        settling_control = path in {"/api/assistant/main-control/settle", "/api/assistant/legacy-reminders/settle",
                                   "/api/assistant/legacy-reminders/abandon", "/api/assistant/legacy-reminders/permit/release",
                                   "/api/assistant/computer/confirm"} or (
            path.startswith("/api/assistant/configuration-reference/contexts/") and path.endswith("/ack"))
        if writing and migration["gate"] and not settling_control:
            return JSONResponse({"error": "assistant_migration_wait"}, status_code=503)
        if writing:
            migration["writers"] += 1
        try:
            return await call_next(request)
        finally:
            if writing:
                migration["writers"] -= 1
                migration["changed"].set()

    @app.get("/api/assistant/lifecycle-status")
    async def lifecycle_status(request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid lifecycle status request")
        observe = getattr(native, "lifecycle_status", None)
        if not callable(observe):
            return {"schemaVersion": 1, "state": "unknown"}
        try:
            result = await asyncio.to_thread(observe)
            if (type(result) is dict and set(result) == {"schemaVersion", "state"}
                    and type(result["schemaVersion"]) is int and result["schemaVersion"] == 1
                    and result["state"] in {"idle", "active", "unknown"}):
                return result
        except Exception:
            pass
        return {"schemaVersion": 1, "state": "unknown"}

    @app.get("/health")
    def health():
        return {"status": "ok", "role": "launcher_assistant", "protocolVersion": 1,
                **({"mainControlVersion": 1} if main_control is not None else {}),
                **({"initialMigrationControlVersion": 1} if main_control is not None and getattr(main_control, "initial_migration_enabled", False) else {}),
                **({"appearanceControlVersion": 1} if main_control is not None and getattr(main_control, "appearance_enabled", False) else {}),
                **({"browserControlVersion": 1} if main_control is not None and getattr(main_control, "browser_enabled", False) else {})}

    async def reminder_call(method, *args, **kwargs):
        from .reminder_receipts import ReminderReceiptError
        if not hasattr(app.state, "reminders"):
            raise HTTPException(503, detail={"code": "reminder_unavailable"})
        try:
            return await asyncio.get_running_loop().run_in_executor(
                app.state.reminder_executor, partial(getattr(app.state.reminders, method), *args, **kwargs))
        except ReminderReceiptError as error:
            code = str(error)
            permanent = {
                "reminder_imported_profile_blocked", "receipt_capacity_exceeded",
                "receipt_admission_closed", "receipt_schema_invalid",
                "receipt_integrity_failed", "receipt_owner_or_capacity_mismatch",
                "receipt_header_invalid", "receipt_namespace_invalid",
                "receipt_file_budget_exceeded",
            }
            raise HTTPException(409 if code in permanent else 503, detail={"code": code}) from None
        except Exception:
            raise HTTPException(503, detail={"code": "reminder_unavailable"}) from None

    @app.post("/api/assistant/reminders/next")
    async def reminder_next(request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid reminder request")
        return JSONResponse(await reminder_call("next"), headers={"Cache-Control": "no-store"})

    @app.post("/api/assistant/reminders/submitted")
    async def reminder_submitted(payload: ReminderSettlement, request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid reminder request")
        result = await reminder_call("settle", payload.eventId, payload.attemptToken, payload.channel, opened=False)
        return {"schemaVersion": 1, "receipt": result}

    @app.post("/api/assistant/reminders/opened")
    async def reminder_opened(payload: ReminderSettlement, request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid reminder request")
        result = await reminder_call("settle", payload.eventId, payload.attemptToken, payload.channel, opened=True)
        return {"schemaVersion": 1, "receipt": result}

    @app.post("/api/assistant/reminders/fallback")
    async def reminder_fallback(payload: ReminderFallback, request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid reminder request")
        result = await reminder_call("fallback", payload.eventId, payload.attemptToken)
        return {"schemaVersion": 1, "receipt": result}

    async def legacy_reminder_call(method, payload, request):
        from .reminder_receipts import ReminderReceiptError
        if request.query_params:
            raise HTTPException(422, detail="Invalid legacy reminder request")
        if not hasattr(app.state, "legacy_reminder_receipts"):
            raise HTTPException(503, detail={"code": "legacy_reminder_unavailable"})
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                app.state.legacy_reminder_executor,
                partial(getattr(app.state.legacy_reminder_receipts, method), *(() if method == "inventory" else (payload.model_dump(),))))
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except ReminderReceiptError as error:
            code = str(error)
            if code in _LEGACY_UNKNOWN_OUTCOME_CODES:
                # A committed write whose outcome cannot be known. Retrying
                # could double-apply it, so the caller must reconcile instead.
                raise HTTPException(503, detail={"code": code, "retryable": False}) from None
            if code in _LEGACY_TRANSIENT_CODES:
                # Nothing committed; the same request may be retried once the
                # transient store condition clears.
                raise HTTPException(503, detail={"code": code, "retryable": True}) from None
            # A request-level refusal (invalid input, wrong or destroyed
            # attempt token, settled attempt, capacity). Retrying the same
            # request cannot change this verdict; recovery or a fresh attempt
            # must decide the next step.
            raise HTTPException(409, detail={"code": code, "retryable": False}) from None
        except Exception:
            # The RPC result may be unknown after a committed write. Do not retry.
            raise HTTPException(503, detail={"code": "legacy_reminder_unavailable",
                                             "retryable": False}) from None

    @app.post("/api/assistant/legacy-reminders/reserve")
    async def legacy_reminder_reserve(payload: LegacyReminderReservation, request: Request):
        return await legacy_reminder_call("reserve", payload, request)

    @app.post("/api/assistant/legacy-reminders/settle")
    async def legacy_reminder_settle(payload: LegacyReminderSettlement, request: Request):
        return await legacy_reminder_call("settle", payload, request)

    @app.post("/api/assistant/legacy-reminders/abandon")
    async def legacy_reminder_abandon(payload: LegacyReminderAttempt, request: Request):
        return await legacy_reminder_call("abandon", payload, request)

    @app.post("/api/assistant/legacy-reminders/inventory")
    async def legacy_reminder_inventory(payload: LegacyReminderInventory, request: Request):
        # Electron owns the global writer barrier; the dedicated host thread
        # must not try to acquire that same Windows mutex across this RPC.
        return await legacy_reminder_call("inventory", payload, request)

    if main_control is not None:
        async def main_control_body(request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid main control protocol")
            body = bytearray()
            async for chunk in request.stream():
                limit = (4 * 1024 * 1024 if getattr(main_control, "configuration_enabled", False)
                         and request.url.path.endswith("/settle") else
                         128 * 1024 if getattr(main_control, "browser_enabled", False) else 4096)
                if len(body) + len(chunk) > limit:
                    raise HTTPException(413, detail="Main control payload is too large")
                body.extend(chunk)
            return body

        @app.get("/api/assistant/main-control/next")
        async def main_control_next(request: Request):
            if await main_control_body(request):
                raise HTTPException(422, detail="Invalid main control protocol")
            return await main_control.claim()

        @app.post("/api/assistant/main-control/settle")
        async def main_control_settle(request: Request):
            body = await main_control_body(request)

            def unique_object(pairs):
                value = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError("Duplicate protocol field")
                    value[key] = item
                return value

            try:
                payload = json.loads(body, object_pairs_hook=unique_object)
                if (type(payload) is not dict or set(payload) != {"schemaVersion", "deliveryId", "result"}
                        or type(payload["schemaVersion"]) is not int or payload["schemaVersion"] != 1
                        or type(payload["result"]) is not dict):
                    raise ValueError("Invalid main control envelope")
                accepted = main_control.settle(payload["deliveryId"], payload["result"])
            except (ValueError, UnicodeDecodeError, RecursionError):
                raise HTTPException(422, detail="Invalid main control protocol") from None
            return {"schemaVersion": 1, "accepted": accepted}

    if main_control is not None and getattr(main_control, "configuration_enabled", False):
        from . import configuration_contexts

        async def configuration_context_body(context_id, request):
            if not configuration_contexts.valid_context_id(context_id):
                raise HTTPException(422, detail="Invalid configuration context")
            body = await main_control_body(request)
            if request.method == "GET":
                if body:
                    raise HTTPException(422, detail="Invalid configuration context")
            else:
                # Exact closed protocol; duplicate keys and boolean versions
                # must not become a completion acknowledgement.
                try:
                    pairs = json.loads(body, object_pairs_hook=lambda items: items)
                except (ValueError, UnicodeDecodeError, RecursionError):
                    raise HTTPException(422, detail="Invalid configuration context") from None
                if pairs != [("schemaVersion", 1)] or type(pairs[0][1]) is not int:
                    raise HTTPException(422, detail="Invalid configuration context")

        @app.get("/api/assistant/configuration-reference/contexts/{context_id}")
        async def configuration_context_state(context_id: str, request: Request):
            await configuration_context_body(context_id, request)
            return configuration_contexts.state(main_control, context_id)

        @app.post("/api/assistant/configuration-reference/contexts/{context_id}/ack")
        async def configuration_context_ack(context_id: str, request: Request):
            await configuration_context_body(context_id, request)
            return configuration_contexts.acknowledge(main_control, context_id)

    if on_shutdown is not None:
        @app.post("/api/assistant/migration-barrier/prepare")
        async def migration_barrier_prepare(request: Request):
            if request.query_params or migration["gate"] or migration["committing"]:
                raise HTTPException(409, detail="Migration barrier unavailable")
            if dispatch is None or not callable(getattr(native, "session_quiescence", None)):
                raise HTTPException(503, detail="Migration barrier unavailable")
            migration["gate"] = True
            migration["state"] = "probing"
            migration["release"] = asyncio.Event()
            migration["task"] = asyncio.create_task(hold_migration_barrier())
            return {"schemaVersion": 1, "state": "probing"}

        @app.get("/api/assistant/migration-barrier/status")
        async def migration_barrier_status(request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid migration barrier request")
            return {"schemaVersion": 1, "state": migration["state"]}

        @app.post("/api/assistant/migration-barrier/release")
        async def migration_barrier_release(request: Request):
            if request.query_params or migration["committing"]:
                raise HTTPException(409, detail="Migration barrier unavailable")
            task = migration["task"]
            if task is not None and not task.done():
                # Never cancel an observation that owns native/thread fences;
                # wait for its actual exit before reopening HTTP admission.
                migration["release"].set()
                with suppress(asyncio.CancelledError):
                    await task
            migration["gate"] = False
            migration["state"] = "idle"
            migration["task"] = None
            return {"schemaVersion": 1, "state": "idle"}

        @app.post("/api/assistant/shutdown")
        async def shutdown():
            if migration["gate"]:
                if migration["state"] != "ready":
                    raise HTTPException(409, detail="Migration barrier not ready")
                commit_stop = getattr(native, "commit_quiescent_shutdown", None)
                if not callable(commit_stop):
                    raise HTTPException(503, detail="Native admission handoff unavailable")
                await asyncio.to_thread(commit_stop)
                migration["committing"] = True
                migration["release"].set()
                await migration["task"]
                if migration["state"] != "released":
                    raise HTTPException(503, detail="Migration barrier release unknown")
            # Wake main-control long polls on their owning event loop before
            # Uvicorn starts waiting for HTTP requests to drain.
            async with source_permit_fence():
                if main_control is not None:
                    main_control.close()
                if history_control is not None:
                    await asyncio.to_thread(history_control.close)
            if source_permits is not None:
                # Same event-loop turn: no admission can slip between fence
                # release and owner close.
                source_permits.close()
            on_shutdown()
            return {"stopping": True}

    if dispatch is not None:
        @app.post("/api/assistant/project-registry/suspend")
        async def suspend_project_registry(payload: SuspendProjects, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid private project suspension")
            async with source_permit_fence():
                if history_control is not None:
                    history_control.signal_registry_change()
                async with initial_fence(registry=True):
                    with history_control.guard() if history_control is not None else nullcontext():
                        if history_control is not None:
                            history_control.registry_changed()
                        return dispatch.suspend_projects()

        @app.put("/api/assistant/project-registry")
        async def project_registry(payload: ProjectSnapshot):
            from .dispatch import DispatchError
            try:
                # One event loop owns this immutable view and all native calls.
                # No background thread may race an admission with this update.
                async with source_permit_fence():
                    if history_control is not None:
                        history_control.signal_registry_change()
                    async with initial_fence(registry=True):
                        with history_control.guard() if history_control is not None else nullcontext():
                            if history_control is not None:
                                history_control.registry_changed()
                            return dispatch.replace_projects(payload.model_dump())
            except DispatchError as exc:
                raise HTTPException(409, detail={"code": exc.code}) from None

    if history_control is not None:
        @app.post("/api/assistant/legacy-reminders/permit/acquire")
        async def acquire_legacy_source_permit(payload: LegacyReminderPermitAcquire, request: Request):
            if request.query_params or source_permits is None:
                raise HTTPException(409, detail={"code": "reminder_lease_unavailable", "retryable": False})
            try:
                result = await asyncio.to_thread(source_permits.acquire_permit, payload.projectId, payload.revision, payload.permitId)
            except Exception as error:
                raise permit_failure(error) from None
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        @app.post("/api/assistant/legacy-reminders/permit/check")
        async def check_legacy_source_permit(payload: LegacyReminderPermit, request: Request):
            if request.query_params or source_permits is None:
                raise HTTPException(409, detail={"code": "reminder_lease_unavailable", "retryable": False})
            try:
                result = await asyncio.to_thread(source_permits.check_permit, payload.permitId)
            except Exception as error:
                raise permit_failure(error) from None
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        @app.post("/api/assistant/legacy-reminders/permit/release")
        async def release_legacy_source_permit(payload: LegacyReminderPermit, request: Request):
            if request.query_params or source_permits is None:
                raise HTTPException(409, detail={"code": "reminder_lease_unavailable", "retryable": False})
            try:
                await asyncio.to_thread(source_permits.release_permit, payload.permitId)
            except Exception as error:
                # A transiently failed release keeps the pins attested and the
                # id retired; the caller's retry loop completes it. A gate
                # that cannot certify release reports non-retryable instead.
                raise permit_failure(error) from None
            return JSONResponse({"schemaVersion": 1, "released": True}, headers={"Cache-Control": "no-store"})

        @app.post("/api/assistant/legacy-reminders/source")
        async def legacy_reminder_source(payload: LegacyReminderSource, request: Request):
            from .migration_io import MigrationIOError
            if request.query_params:
                raise HTTPException(422, detail="Invalid legacy reminder source request")
            try:
                result = await asyncio.to_thread(history_control.legacy_reminder_source,
                                                 payload.projectId, payload.revision)
            except MigrationIOError:
                raise HTTPException(409, detail="Legacy reminder source unavailable") from None
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        @app.post("/api/assistant/legacy-reminders/source-ledger")
        async def legacy_reminder_ledger(payload: LegacyReminderSource, request: Request):
            from .migration_io import MigrationIOError
            if request.query_params:
                raise HTTPException(422, detail="Invalid legacy reminder source request")
            try:
                result = await asyncio.to_thread(history_control.legacy_reminder_ledger,
                                                 payload.projectId, payload.revision)
            except (MigrationIOError, ValueError):
                raise HTTPException(409, detail="Legacy reminder ledger unavailable") from None
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        @app.post("/api/assistant/legacy-reminders/handoff-receipt")
        async def legacy_reminder_handoff_receipt(payload: LegacyReminderSource, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid reminder handoff receipt request")
            def read():
                from .actions import _reminder_handoff_receipt
                with history_control.guard():
                    if dispatch._registry_revision != payload.revision:
                        raise ValueError("registration changed")
                    return _reminder_handoff_receipt(dispatch, payload.projectId)
            try:
                result = await asyncio.to_thread(read)
            except Exception:
                raise HTTPException(409, detail="Reminder handoff receipt unavailable") from None
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        @app.post("/api/assistant/legacy-reminders/handoff-source")
        async def legacy_reminder_handoff_source(payload: LegacyReminderSource, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid reminder handoff source request")
            try:
                result = await asyncio.to_thread(history_control.legacy_reminder_handoff, payload.projectId, payload.revision)
            except Exception:
                raise HTTPException(409, detail="Reminder handoff source unavailable") from None
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        if main_control is not None and getattr(main_control, "initial_migration_enabled", False):
            @app.post("/api/assistant/initial-migration/prepare")
            async def prepare_initial_migration(payload: InitialMigrationPrepare, request: Request):
                if request.query_params:
                    raise HTTPException(422, detail="Invalid initial migration request")
                bound = {key: getattr(payload, key) for key in ("projectId", "previewId", "turnId", "category", "operationId")}
                if payload.originalSyncId is not None:
                    bound["originalSyncId"] = payload.originalSyncId
                if payload.reauthorize is not None:
                    bound["reauthorize"] = payload.reauthorize
                publication = main_control.initial_delivery(payload.deliveryId, bound, admit=True)
                if not publication:
                    logging.getLogger(__name__).warning("assistant_initial_prepare category=%s phase=admission code=delivery_unavailable", payload.category)
                    raise HTTPException(409, detail="Initial migration delivery unavailable")
                def prepare():
                    from .history_host import InitialPrepareBusy
                    try:
                        deadline = time.monotonic() + 0.4
                        while True:
                            publication.check()
                            try:
                                return history_control.prepare_initial_source(payload.projectId, payload.previewId,
                                    payload.revision, payload.turnId, payload.operationId, payload.category, publication,
                                    retry_busy=True,
                                    **({"reauthorize": True} if payload.reauthorize is True else {}),
                                    **({"original_sync_id": payload.originalSyncId} if payload.originalSyncId is not None else {}))
                            except InitialPrepareBusy:
                                remaining = deadline - time.monotonic()
                                if remaining <= 0:
                                    raise
                                publication.wait_retry(min(0.025, remaining))
                    finally:
                        publication.finished()
                phase = "prepare"
                try:
                    result = await asyncio.to_thread(prepare)
                    phase = "confirmation"
                    if not main_control.initial_delivery(payload.deliveryId, bound, confirm=True):
                        raise ValueError("delivery changed")
                except Exception as error:
                    logging.getLogger(__name__).warning("assistant_initial_prepare category=%s phase=%s code=%s",
                        payload.category, phase, _initial_prepare_failure_code(error))
                    retired = history_control.retire_preview(payload.previewId, "initial_migration_queue", payload.operationId)
                    from .history_host import InitialPrepareBusy
                    if (retired and phase == "prepare" and type(error) is InitialPrepareBusy
                            and main_control.initial_delivery(payload.deliveryId, bound, busy=True)):
                        return JSONResponse({"schemaVersion": 1, "operationId": payload.operationId,
                                             "state": "rejected", "code": "busy"},
                                            headers={"Cache-Control": "no-store"})
                    raise HTTPException(409, detail="Initial migration source unavailable") from None
                return JSONResponse(result, headers={"Cache-Control": "no-store"})

            @app.post("/api/assistant/initial-migration/drain")
            async def drain_initial_migration(payload: InitialMigrationDrain, request: Request):
                if request.query_params:
                    raise HTTPException(422, detail="Invalid initial migration request")
                found, publication = main_control.begin_initial_drain(payload.deliveryId, payload.operationId)
                drained = found and (publication is None or await asyncio.to_thread(publication.wait_finished, 2.0))
                return JSONResponse({"schemaVersion": 1, "operationId": payload.operationId,
                                     "state": "unknown", "drained": bool(drained)},
                                    status_code=200 if drained else 503,
                                    headers={"Cache-Control": "no-store"})

        @app.post("/api/assistant/affairs-sync")
        async def affairs_sync(payload: AffairsSync, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid affairs sync request")
            args = (payload.projectId, payload.previewId, payload.revision, payload.turnId, payload.operationId)
            if payload.recoverSyncId is None:
                result = await asyncio.to_thread(history_control.sync_affairs, *args)
            else:
                result = await asyncio.to_thread(history_control.sync_affairs, *args, payload.recoverSyncId)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        @app.post("/api/assistant/affairs-sync/cancel")
        async def affairs_sync_cancel(payload: CancelHistoryImport, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid affairs sync cancellation")
            try:
                return await asyncio.to_thread(history_control.cancel_affairs, payload.operationId, payload.previewId, "affairs_sync")
            except Exception:
                raise HTTPException(503, detail="Affairs sync cancellation unavailable") from None

        @app.post("/api/assistant/episodic-sync")
        async def episodic_sync(payload: EpisodicSync, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid episodic sync request")
            args = (payload.projectId, payload.previewId, payload.revision, payload.turnId, payload.operationId)
            result = await asyncio.to_thread(history_control.sync_episodic, *args, payload.recoverSyncId,
                                             payload.resolveSyncId, payload.reviewToken)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        @app.post("/api/assistant/episodic-sync/cancel")
        async def episodic_sync_cancel(payload: CancelHistoryImport, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid episodic sync cancellation")
            try:
                return await asyncio.to_thread(history_control.cancel_affairs, payload.operationId, payload.previewId, "episodic_sync")
            except Exception:
                raise HTTPException(503, detail="Episodic sync cancellation unavailable") from None

        @app.post("/api/assistant/history-import")
        async def history_import(payload: HistoryImport, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid history import request")
            result = await asyncio.to_thread(history_control.import_history, payload.projectId,
                payload.previewId, payload.revision, payload.turnId, payload.operationId)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        @app.post("/api/assistant/history-receipt")
        async def history_receipt(payload: HistoryReceipt, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid history receipt request")
            result = await asyncio.to_thread(history_control.history_receipt, payload.projectId,
                                             payload.previewId, payload.revision)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        @app.post("/api/assistant/history-import/cancel")
        async def history_cancel(payload: CancelHistoryImport, request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid history import request")
            try:
                return await asyncio.to_thread(history_control.cancel, payload.operationId, payload.previewId)
            except Exception:
                raise HTTPException(503, detail="History cancellation unavailable") from None

    @app.get("/api/assistant")
    def assistant():
        result = native.identity() if callable(getattr(native, "identity", None)) else app.state.assistant
        patrol_status = getattr(app.state, "patrol_status", None)
        if isinstance(result, dict):
            supported = callable(getattr(getattr(dispatch, "management", None), "list_requests", None))
            queue_supported = all(callable(getattr(native, operation, None)) for operation in (
                "update_queued_turn", "remove_queued_turn", "send_now_queued_turn"))
            return {**result, **({"teamRunsVersion": 1} if supported else {}),
                    **({"followupQueueVersion": 1} if queue_supported else {}),
                    **({"patrol": patrol_status} if patrol_status is not None else {})}
        return result

    @app.post("/api/assistant/model")
    def set_model(payload: SetModel, request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid assistant model request")
        return native.set_model(payload.modelId)

    @app.post("/api/assistant/management-permission", response_model=ManagementPermission)
    def set_management_permission(payload: SetManagementPermission, request: Request, response: Response):
        if request.query_params:
            raise AssistantSessionError("ASSISTANT_PERMISSION_INVALID")
        setter = getattr(native, "set_management_permission", None)
        if not callable(setter):
            raise AssistantSessionError("ASSISTANT_PERMISSION_UNAVAILABLE")
        response.headers["Cache-Control"] = "no-store"
        return setter(payload.preset, payload.expectedRevision)

    @app.get("/api/assistant/usage-summary", response_model=AssistantUsageSummary)
    async def usage_summary(request: Request, response: Response):
        if request.query_params or await request.body():
            raise AssistantSessionError("ASSISTANT_USAGE_INVALID")
        getter = getattr(native, "usage_summary", None)
        if not callable(getter):
            raise AssistantSessionError("ASSISTANT_USAGE_UNAVAILABLE")
        try:
            result = AssistantUsageSummary.model_validate(await asyncio.to_thread(getter))
            identity = (getattr(app.state, "assistant", {}) or {}).get("assistant", {})
            if result.sessionId != identity.get("directSessionId") or result.agentId != identity.get("agentId"):
                raise ValueError("usage_identity_mismatch")
        except Exception:
            raise AssistantSessionError("ASSISTANT_USAGE_UNAVAILABLE") from None
        response.headers["Cache-Control"] = "no-store"
        return result

    @app.get("/api/assistant/budget-parameters", response_model=AssistantBudgetParameters)
    def budget_parameters(request: Request, response: Response):
        if request.query_params:
            raise AssistantSessionError("ASSISTANT_BUDGET_INVALID")
        getter = getattr(native, "budget_parameters", None)
        if not callable(getter):
            raise AssistantSessionError("ASSISTANT_BUDGET_UNAVAILABLE")
        response.headers["Cache-Control"] = "no-store"
        return getter()

    @app.patch("/api/assistant/budget-parameters", response_model=AssistantBudgetParameters)
    def set_budget_parameters(payload: AssistantBudgetParameters, request: Request, response: Response):
        if request.query_params:
            raise AssistantSessionError("ASSISTANT_BUDGET_INVALID")
        setter = getattr(native, "set_budget_parameters", None)
        if not callable(setter):
            raise AssistantSessionError("ASSISTANT_BUDGET_UNAVAILABLE")
        response.headers["Cache-Control"] = "no-store"
        return setter(payload.maxCallsPerTurn, payload.revision)

    from .team_task_cards import TeamTaskCardsError, TeamTaskCardsPage, read_team_task_cards

    @app.get("/api/assistant/team-runs", response_model=TeamTaskCardsPage)
    async def team_runs(request: Request, response: Response):
        if (set(request.query_params) - {"cursor"}
                or len(request.query_params.getlist("cursor")) > 1):
            raise HTTPException(422, detail="team_runs_cursor_invalid")
        try:
            identity = getattr(native, "assistant", None)
            if not isinstance(identity, dict):
                bootstrapped = getattr(app.state, "assistant", {})
                identity = bootstrapped.get("assistant") if isinstance(bootstrapped, dict) else None
            if not isinstance(identity, dict) or any(not isinstance(identity.get(key), str)
                    for key in ("agentId", "directSessionId")):
                raise HTTPException(503, detail="team_runs_unavailable")
            result = await read_team_task_cards(dispatch, identity, cursor=request.query_params.get("cursor"))
            response.headers["Cache-Control"] = "no-store"
            return result
        except TeamTaskCardsError as exc:
            raise HTTPException(exc.status_code, detail=exc.code) from None

    @app.get("/api/assistant/approvals")
    def approvals():
        return native.approvals()

    @app.post("/api/assistant/approvals/decision")
    def resolve_approval(payload: ApprovalDecision):
        from core.web.services.session.tool_approvals import (
            ToolApprovalConflictError,
            ToolApprovalError,
            ToolApprovalNotFoundError,
        )
        try:
            return native.resolve_approval(payload.requestId, payload.decision)
        except ToolApprovalNotFoundError:
            raise HTTPException(404, detail="Native approval not found") from None
        except ToolApprovalConflictError:
            raise HTTPException(409, detail="Native approval already resolved") from None
        except ToolApprovalError:
            raise HTTPException(422, detail="Native approval could not be resolved") from None

    @app.get("/api/assistant/session")
    def detail(before_message_index: int | None = Query(default=None, ge=1, le=2_147_483_647)):
        return native.get_detail() if before_message_index is None else native.get_detail(before_message_index=before_message_index)

    @app.get("/api/assistant/config")
    def config():
        return native.config()

    @app.get("/api/assistant/avatar")
    async def assistant_avatar(request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid assistant avatar request")
        async for chunk in request.stream():
            if chunk:
                raise HTTPException(422, detail="Invalid assistant avatar request")
        try:
            return await asyncio.to_thread(native.avatar)
        except Exception:  # noqa: BLE001 - private asset errors must not disclose paths or configuration.
            raise HTTPException(503, detail={"code": "assistant_avatar_unavailable"}) from None

    @app.get("/api/assistant/operator-assets/{kind}")
    async def operator_asset(kind: Literal["avatar", "background"], request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid operator asset request")
        from .operator_assets import read_operator_asset
        try:
            return await asyncio.to_thread(read_operator_asset, kind)
        except ValueError:
            raise HTTPException(503, detail={"code": "operator_asset_unavailable"}) from None

    if main_control is not None and getattr(main_control, "appearance_enabled", False):
        @app.post("/api/assistant/operator-assets/{kind}")
        async def import_operator_asset(kind: Literal["avatar", "background"], request: Request):
            if request.query_params:
                raise HTTPException(422, detail="Invalid operator asset request")
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 14 * 1024 * 1024:
                    raise HTTPException(413, detail="Operator image payload is too large")
                body.extend(chunk)
            def unique(pairs):
                value = {}
                for key, item in pairs:
                    if key in value: raise ValueError("Duplicate field")
                    value[key] = item
                return value
            try:
                payload = json.loads(body, object_pairs_hook=unique)
                if type(payload) is not dict or set(payload) != {"deliveryId", "filename", "contentType", "dataBase64"} or any(type(v) is not str for v in payload.values()):
                    raise ValueError("Invalid payload")
            except (ValueError, UnicodeDecodeError, RecursionError):
                raise HTTPException(422, detail="Invalid operator image payload") from None
            if not main_control.admit_image_import(payload["deliveryId"], kind):
                raise HTTPException(409, detail="Operator image request is no longer active")
            from .operator_image_actions import import_operator_image
            return await asyncio.to_thread(import_operator_image, kind, payload["filename"], payload["contentType"], payload["dataBase64"])

    @app.get("/api/assistant/curation")
    def curation():
        return native.curation()

    @app.post("/api/assistant/curation")
    def curate(payload: Curation):
        from core.web.services import session_service
        try:
            return native.curate(payload.messageId, payload.action)
        except session_service.SessionNotFoundError as exc:
            raise HTTPException(404, detail=str(exc)) from exc
        except session_service.SessionMessageCurationStateError as exc:
            raise HTTPException(409, detail=str(exc)) from exc
        except session_service.SessionValidationError as exc:
            raise HTTPException(422, detail=str(exc)) from exc

    @app.post("/api/assistant/messages")
    def message(payload: Message):
        try:
            if payload.controlContinuation is not None:
                return native.submit(payload.message, payload.requestId,
                                     control_continuation=payload.controlContinuation.model_dump())
            if payload.attachmentIds or payload.references:
                return native.submit(payload.message, payload.requestId, payload.attachmentIds or None,
                                     payload.references or None)
            return native.submit(payload.message, payload.requestId)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/assistant/attachments/upload")
    async def upload_attachment(request: Request):
        if request.query_params or not callable(getattr(native, "upload_attachment", None)):
            raise HTTPException(422, detail="Attachment upload unavailable")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 12 * 1024 * 1024:
                raise HTTPException(413, detail="Attachment payload too large")
            body.extend(chunk)
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("Duplicate field")
                value[key] = item
            return value
        try:
            payload = json.loads(body, object_pairs_hook=unique)
            if type(payload) is not dict or any(type(value) is not str for value in payload.values()):
                raise ValueError("Invalid attachment")
            if payload.get("kind") == "user_secret":
                # Privacy attachment: the plaintext is staged in native process
                # memory and only its one-shot sec_ id is returned; no base64
                # or filesystem path is involved. Only this native PA link
                # accepts the kind; ordinary session endpoints never do.
                if set(payload) not in (
                    {"kind", "value"},
                    {"kind", "value", "secretKind"},
                    {"kind", "value", "label"},
                    {"kind", "value", "secretKind", "label"},
                ) or not payload["value"].strip() or len(payload["value"]) > 8192:
                    raise ValueError("Invalid attachment")
                return await asyncio.to_thread(
                    native.upload_secret_attachment, payload["value"],
                    kind=payload.get("secretKind") or "secret",
                    label=payload.get("label") or "",
                )
            if (set(payload) != {"filename", "contentType", "dataBase64"}
                    or not 0 < len(payload["filename"]) <= 255 or not 0 < len(payload["contentType"]) <= 128
                    or not 0 < len(payload["dataBase64"]) <= ((8 * 1024 * 1024 + 2) // 3) * 4):
                raise ValueError("Invalid attachment")
            raw = base64.b64decode(payload["dataBase64"], validate=True)
            if not raw or len(raw) > 8 * 1024 * 1024 or base64.b64encode(raw).decode("ascii") != payload["dataBase64"]:
                raise ValueError("Invalid attachment")
        except (ValueError, UnicodeError, RecursionError, binascii.Error):
            raise HTTPException(422, detail="Invalid attachment payload") from None
        try:
            return await asyncio.to_thread(native.upload_attachment, raw, payload["filename"], payload["contentType"])
        except (ValueError, OSError):
            raise HTTPException(422, detail="Attachment could not be stored") from None

    @app.post("/api/assistant/attachments/read")
    async def read_attachment(payload: AttachmentRead, request: Request):
        if request.query_params or payload.artifactId in {".", ".."} or not callable(getattr(native, "read_attachment", None)):
            raise HTTPException(422, detail="Attachment unavailable")
        try:
            raw, content_type = await asyncio.to_thread(native.read_attachment, payload.artifactId)
            if type(raw) is not bytes or not raw or len(raw) > 8 * 1024 * 1024 or type(content_type) is not str or len(content_type) > 128:
                raise ValueError("Invalid attachment")
            return {"contentType": content_type, "dataBase64": base64.b64encode(raw).decode("ascii")}
        except (ValueError, OSError):
            raise HTTPException(404, detail="Attachment unavailable") from None

    @app.post("/api/assistant/stop", status_code=202)
    async def stop(payload: StopTurn):
        async with initial_fence(payload.turnId.strip()):
            if history_control is not None:
                result = await asyncio.to_thread(history_control.stop_native_turn, native.stop, payload.turnId.strip())
            else:
                result = await asyncio.to_thread(native.stop, payload.turnId)
            if main_control is not None and getattr(main_control, "appearance_enabled", False):
                main_control.cancel_image_imports(payload.turnId.strip())
            cancel_history = getattr(main_control, "cancel_history_imports", None)
            if callable(cancel_history):
                cancel_history(payload.turnId.strip())
            return result

    @app.post("/api/assistant/queued-turns/update")
    def update_queued_turn(payload: UpdateQueuedTurn, request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid queued turn request")
        return native.update_queued_turn(payload.queuedTurnId, content=payload.content,
                                         position=payload.position, status=payload.status)

    @app.post("/api/assistant/queued-turns/remove")
    def remove_queued_turn(payload: QueuedTurn, request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid queued turn request")
        return native.remove_queued_turn(payload.queuedTurnId)

    @app.post("/api/assistant/queued-turns/send-now", status_code=202)
    async def send_now_queued_turn(payload: SendNowQueuedTurn, request: Request):
        if request.query_params:
            raise HTTPException(422, detail="Invalid queued turn request")
        turn_id = payload.expectedTurnId
        if turn_id is None:
            detail = await asyncio.to_thread(native.get_detail)
            if not isinstance(detail, dict):
                raise AssistantSessionError("ASSISTANT_IDENTITY_INVALID")
            active_turn_id = detail.get("activeTurnId")
            turn_id = "" if active_turn_id is None else active_turn_id
            if (not isinstance(turn_id, str) or len(turn_id) > 160
                    or any(not ch.isascii() or not (ch.isalnum() or ch in "_-") for ch in turn_id)):
                raise AssistantSessionError("SESSION_INVALID")
        if not turn_id:
            # An idle snapshot has no Turn-scoped PA work to revoke. The
            # per-request non-Turn ID lets native stop remain a no-op while
            # still idle, but reject a Turn that starts after this read.
            idle_fence = "assistant-idle-" + secrets.token_hex(16)
            return await asyncio.to_thread(native.send_now_queued_turn, payload.queuedTurnId, expected_turn_id=idle_fence)

        def promote(expected_turn_id):
            # Keep the native helper's pin -> stop -> rollback transaction;
            # native.stop would freeze the queue and invalidate the promotion.
            return native.send_now_queued_turn(payload.queuedTurnId, expected_turn_id=expected_turn_id)

        def accepted(result):
            return isinstance(result, dict) and result.get("stopRequested") is True

        async with initial_fence(turn_id):
            if history_control is not None:
                result = await asyncio.to_thread(history_control.stop_native_turn, promote, turn_id, accepted=accepted)
            else:
                result = await asyncio.to_thread(promote, turn_id)
            if accepted(result):
                if main_control is not None and getattr(main_control, "appearance_enabled", False):
                    main_control.cancel_image_imports(turn_id)
                cancel_history = getattr(main_control, "cancel_history_imports", None)
                if callable(cancel_history):
                    cancel_history(turn_id)
            return result

    @app.post("/api/assistant/continue", status_code=202)
    def continue_turn(payload: ContinueTurn):
        return native.continue_turn(payload.requestId, payload.continuation.model_dump())

    @app.post("/api/assistant/head", status_code=202)
    def switch_head(payload: SwitchHead):
        return native.switch_head(payload.nodeId)

    @app.post("/api/assistant/messages/regenerate", status_code=202)
    def regenerate(payload: RegenerateMessage):
        return native.regenerate(payload.messageId, payload.requestId)

    @app.post("/api/assistant/guidance", status_code=202)
    def guidance(payload: Guidance):
        return native.guidance(payload.content, payload.mode)

    @app.get("/api/assistant/events")
    async def events(request: Request):
        try:
            from core.web.services import session_service
            session_service.parse_session_stream_last_event_id(request.headers.get("last-event-id", ""))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid native event cursor") from exc
        return StreamingResponse(native.events(request.headers.get("last-event-id", "")),
                                 media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    if dispatch is not None:
        @app.get("/api/assistant/dispatches")
        async def dispatches():
            from .task_card_metadata import enrich_dispatch_cards
            return {"dispatches": await enrich_dispatch_cards(dispatch, dispatch.list_dispatches())}

        from .task_cleanup import create_task_cleanup_router
        app.include_router(create_task_cleanup_router(dispatch, native, app))

        @app.post("/api/assistant/dispatches/approval/preview")
        async def preview_dispatch_approval(payload: DispatchApprovalPreview):
            from .dispatch import DispatchError
            try:
                result = await dispatch.preview_bound_approval(payload.dispatchId, task_id=payload.taskId, approval_id=payload.approvalId)
                return JSONResponse(result, headers={"Cache-Control": "no-store"})
            except DispatchError as exc:
                raise HTTPException(409, detail={"code": exc.code}) from None

        @app.post("/api/assistant/dispatches/approval/decision")
        async def decide_dispatch_approval(payload: DispatchApprovalBoundDecision):
            from .dispatch import DispatchError
            try:
                return await dispatch.decide_bound_approval(payload.dispatchId, task_id=payload.taskId,
                    approval_id=payload.approvalId, revision=payload.revision, decision=payload.decision)
            except DispatchError as exc:
                raise HTTPException(409, detail={"code": exc.code}) from None

        @app.post("/api/assistant/dispatches/approval/decline")
        async def decline_dispatch_approval(payload: DispatchApprovalDecline):
            from .dispatch import DispatchError
            try:
                return await dispatch.decline_presented_approval(payload.dispatchId, task_id=payload.taskId,
                    approval_id=payload.approvalId, expected_revision=payload.revision)
            except DispatchError as exc:
                raise HTTPException(409, detail={"code": exc.code}) from None

        @app.post("/api/assistant/dispatches/dismiss")
        async def dismiss_corrupt_dispatch(payload: DispatchCorruptDismiss):
            from .dispatch import DispatchError
            try:
                return await dispatch.dismiss_corrupt(payload.dispatchId, confirmed=payload.confirmed,
                                                      reason=payload.reason)
            except DispatchError as exc:
                raise HTTPException(409, detail={"code": exc.code}) from None

    # Operator-only single-window controls retain the host bearer boundary;
    # the model only sees the separate scoped computer tools.
    from .computer_control import create_router as create_computer_router
    app.include_router(create_computer_router(token))
    return app
