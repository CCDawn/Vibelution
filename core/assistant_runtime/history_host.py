"""Main-only binding of one approved native-turn preview to archive import."""
from __future__ import annotations

import re
import logging
from contextlib import contextmanager, ExitStack
from pathlib import Path
from threading import Event, Lock, RLock

from .migration_io import MigrationIOError
from .online_history import AuthorizedHistorySource, OnlineHistoryOwner

_LOGGER = logging.getLogger(__name__)
_HISTORY_DIAGNOSTICS = frozenset({
    "history_target_unavailable", "history_target_invalid", "history_generation_changed",
    "history_cancelled", "history_authority_revoked", "history_profile_changed",
    "history_preview_expired", "history_preview_changed", "history_outcome_unknown",
    "history_discovery_incomplete", "history_archive_invalid", "history_source_unavailable",
    "source_guard_unavailable", "source_changed", "migration_lock_unavailable",
    "target_namespace_unavailable", "target_directory_unavailable", "target_publish_unavailable",
    "target_pending_changed",
})


class InitialPrepareBusy(MigrationIOError):
    """A local admission lock was unavailable before preview consumption."""


class HistoryHost:
    def __init__(self, profile_root: Path, generation: str, dispatch, preview, *, initial_owner_check=None):
        self._lock = RLock()
        self._import_lock = Lock()
        self._active = True
        self._generation = generation
        self._dispatch = dispatch
        self._preview = preview
        # Trusted host supplies a nonblocking lifecycle check while it holds
        # the profile's OS host-owner lock. Missing proof forbids refresh.
        self._initial_owner_check = initial_owner_check
        self._cancelled = set()
        self._operation = None
        self._operation_turn = None
        self._operation_stopped = False
        self._sync_signal_lock = Lock()
        self._sync_active = None
        self._sync_cancelled = {}
        self._sync_seen = {}
        self._owner = OnlineHistoryOwner(profile_root=profile_root, generation=generation,
                                         sources={}, generation_guard=self.guard)

    @contextmanager
    def guard(self, generation=None):
        with self._lock:
            if not self._active or generation is not None and generation != self._generation:
                raise MigrationIOError("history_generation_changed")
            if generation is not None and (self._operation_stopped or self._operation in self._cancelled):
                raise MigrationIOError("history_cancelled")
            yield

    def registry_changed(self):
        """Called under guard before any project snapshot or suspension."""
        self._owner.suspend()

    def wait_guard_idle(self, timeout=2.0):
        """Bounded worker-side drain before event-loop registry mutation."""
        if not self._lock.acquire(timeout=timeout):
            return False
        self._lock.release()
        return True

    def retire_preview(self, preview_id):
        self._preview.retire(preview_id)

    def signal_registry_change(self):
        """Revoke an admitted sync before waiting for the generation guard."""
        self._signal_sync()

    def legacy_reminder_source(self, project_id, revision):
        """Return a point-in-time main-only identity, never an import authority."""
        from .initial_migration_binding import authority_identity, source_identity

        with self.guard():
            if self._dispatch._registry_revision != revision:
                raise MigrationIOError("history_preview_changed")
            preview = self._preview.preview(project_id)
            token = preview["previewId"]
            try:
                # HistoryPreview owns the snapshot and verifies its complete
                # route. Keep its lock while reading its private proof tuple.
                with self._preview._lock:
                    public = self._preview.verify_preview(token)
                    row = self._preview._previews[token]
                    root, workspace, paths, snapshots = row[3], row[4], row[5], row[7]
                    scope = {"projectId": paths.project_id, "instanceId": paths.instance_id,
                             "agentId": public["assistantAgentId"]}
                    digest, project_identity, _ = source_identity(scope, root, workspace)
                    authority = authority_identity(snapshots)
                    self._preview.verify_preview(token)
                    if self._dispatch._registry_revision != revision:
                        raise MigrationIOError("history_preview_changed")
                    return {"schemaVersion": 1, "projectId": project_id, "revision": revision,
                            "sourceScope": scope, "sourceIdentityDigest": digest,
                            "authorityDigest": authority, "projectDirectory": project_identity}
            finally:
                self._preview.discard(token)

    def legacy_reminder_ledger(self, project_id, revision):
        """Return a point-in-time ledger digest for private main diagnostics.

        This result is not a live verification capability or sender proof.
        Main must independently revalidate the source before any operation.
        """
        from .reminder_source_identity import observe_reminder_source
        from core.infrastructure.reminder_source_mutex import trusted_reminder_source_mutex_key

        with self.guard():
            with observe_reminder_source(self._dispatch, self._preview, project_id, revision) as observation:
                before = self.legacy_reminder_source(project_id, revision)
                key = trusted_reminder_source_mutex_key(observation)
                after = self.legacy_reminder_source(project_id, revision)
                observation._check()
                if before != after or before["sourceScope"]["agentId"] != observation.agent_id:
                    raise MigrationIOError("reminder_source_observation_changed")
                return {**before, "ledgerKey": key}

    def legacy_reminder_handoff(self, project_id, revision):
        """Revalidate one published handoff against the live source and target."""
        from . import native
        from .initial_migration_binding import target_identity
        from .reminder_handoff_intent import read_handoff_intent
        from core.infrastructure.native_runtime import assistant_native_root
        with self.guard():
            if self._dispatch._registry_revision != revision:
                raise MigrationIOError("reminder_handoff_source_unavailable")
            with native._LOCK:
                if not native._STARTED or native._OFFLINE_MIGRATION:
                    raise MigrationIOError("reminder_handoff_source_unavailable")
                root = assistant_native_root()
                intent = read_handoff_intent(root, project_id)
                if (intent is None or (native._AGENT_ID, native._SESSION_ID) != (intent["targetAgentId"], intent["targetSessionId"])
                        or target_identity(root, native._AGENT_ID, native._SESSION_ID) != (intent["targetIdentityDigest"], intent["targetDirectory"])):
                    raise MigrationIOError("reminder_handoff_source_unavailable")
                source = self.legacy_reminder_source(project_id, revision)
                if (source["sourceScope"] != intent["sourceScope"] or source["sourceIdentityDigest"] != intent["sourceIdentityDigest"]
                        or source["authorityDigest"] != intent["registryDigest"] or source["projectDirectory"] != intent["projectDirectory"]
                        or self._dispatch._registry_revision != revision):
                    raise MigrationIOError("reminder_handoff_source_unavailable")
                return intent

    def _signal_sync(self, *, turn_id=None, operation_id=None, preview_id=None):
        with self._sync_signal_lock:
            current = self._sync_active
            if (current is not None and (turn_id is None or current["turnId"] == turn_id)
                    and (operation_id is None or current["operationId"] == operation_id)
                    and (preview_id is None or current["previewId"] == preview_id)):
                current["owner"].revoke()

    def close(self):
        self._signal_sync()
        with self._lock:
            self._active = False
            self._owner.close()

    def stop_native_turn(self, native_stop, turn_id):
        """Order a successful native stop against the final archive commit."""
        self._signal_sync(turn_id=turn_id)
        with self._lock:
            result = native_stop(turn_id)
            self._preview.stop_turn(turn_id)
            if self._operation_turn == turn_id:
                self._operation_stopped = True
                self._owner.suspend()
            return result

    def prepare_initial_source(self, project_id, preview_id, revision, turn_id, operation_id, category, publication, original_sync_id=None, *, retry_busy=False):
        """Publish one intent under the live native Turn and source guards."""
        from . import native
        from .initial_migration_binding import authority_identity, source_identity, target_identity, publish_initial_intent
        from .main_control import initial_migration_id, initial_model_env_unavailable, knowledge_sync_id, knowledge_recovery_id
        from .migration_io import check_path, pinned_source_files
        from core.infrastructure.native_runtime import assistant_native_root
        from core.web.services import session_service as sessions
        from core.web.services.session import directory_runtime
        from core.web.services.personal_assistant_project.windows_read import lock_source_directory

        if (category not in ("personal", "knowledge", "knowledge_sync", "knowledge_recovery", "reminder_handoff")
                or category == "knowledge_recovery" and (type(original_sync_id) is not str
                    or re.fullmatch(r"ksync-[a-f0-9]{40}", original_sync_id) is None)
                or category != "knowledge_recovery" and original_sync_id is not None
                or operation_id != (knowledge_recovery_id(project_id, preview_id, original_sync_id) if category == "knowledge_recovery"
                                    else knowledge_sync_id(project_id, preview_id) if category == "knowledge_sync"
                                    else initial_migration_id(project_id, preview_id, category))):
            self._preview.discard(preview_id)
            raise MigrationIOError("initial_migration_request_invalid")
        if not self._import_lock.acquire(blocking=False):
            if not retry_busy:
                self._preview.discard(preview_id)
            raise InitialPrepareBusy("initial_migration_busy")
        running = locked = False
        try:
            if not self._lock.acquire(blocking=False):
                raise InitialPrepareBusy("initial_migration_busy")
            locked = True
            if (not self._active or native._STOP_REQUESTED.is_set() or not native._STARTED or native._OFFLINE_MIGRATION):
                raise MigrationIOError("initial_migration_unavailable")
            if not sessions._RUNNING_SESSIONS_LOCK.acquire(blocking=False):
                raise InitialPrepareBusy("initial_migration_busy")
            running = True
            if (native._SESSION_ID not in sessions._RUNNING_SESSION_IDS
                    or sessions._SESSION_ACTIVE_TURN_IDS.get(native._SESSION_ID) != turn_id):
                raise MigrationIOError("initial_migration_turn_invalid")
            if not native._LOCK.acquire(blocking=False):
                raise InitialPrepareBusy("initial_migration_busy")
            try:
                project, workspace, paths, source_agent, verify, snapshots = self._preview.consume_for_import(
                    preview_id, project_id, revision, turn_id, purpose="knowledge" if category in ("knowledge_sync", "knowledge_recovery") else "personal" if category == "reminder_handoff" else category)
                root = check_path(self._owner._profile).resolve()
                if (not native._AGENT_ID or not native._SESSION_ID or assistant_native_root() != root
                        or directory_runtime.directory_store_project_root() != root
                        or any(root.is_relative_to(path.resolve()) or path.resolve().is_relative_to(root)
                               for path in (project, workspace))):
                    raise MigrationIOError("initial_migration_binding_invalid")
                scope = {"projectId": paths.project_id, "instanceId": paths.instance_id, "agentId": source_agent}
                with ExitStack() as stack:
                    stack.enter_context(pinned_source_files(snapshots))
                    for directory in (project, workspace):
                        stack.enter_context(lock_source_directory(Path(directory.anchor), directory, allow_child_replacement=True))
                    verify()
                    source_digest, project_identity, workspace_identity = source_identity(scope, project, workspace)
                    registry_digest = authority_identity(snapshots)
                    target_digest, target_directory = target_identity(root, native._AGENT_ID, native._SESSION_ID)
                    verify()
                    binding = {"schemaVersion": 1, "registeredProjectId": project_id, "sourceScope": scope,
                               "category": category, "turnId": turn_id, "operationId": operation_id, "revision": revision,
                               "sourceIdentityDigest": source_digest, "registryDigest": registry_digest,
                               "targetIdentityDigest": target_digest, "projectDirectory": project_identity,
                               "workspaceDirectory": workspace_identity, "targetDirectory": target_directory,
                               "targetAgentId": native._AGENT_ID, "targetSessionId": native._SESSION_ID,
                               "authority": "native_policy_admitted", "readyForCutover": False}
                    if category in ("knowledge_sync", "knowledge_recovery"):
                        binding.update(previewId=preview_id,
                            baselineMigrationId=initial_migration_id(project_id, "", "knowledge"))
                        if category == "knowledge_recovery":
                            binding["originalSyncId"] = original_sync_id
                    def recheck():
                        verify()
                        if (initial_model_env_unavailable()
                                or source_identity(scope, project, workspace) != (source_digest, project_identity, workspace_identity)
                                or authority_identity(snapshots) != registry_digest
                                or target_identity(root, native._AGENT_ID, native._SESSION_ID) != (target_digest, target_directory)):
                            raise MigrationIOError("initial_migration_binding_changed")
                    if category == "reminder_handoff":
                        from .reminder_handoff_intent import publish_handoff_intent, sync_id
                        binding.update(syncId=sync_id(project_id), baselineId=None, baselineState="unknown")
                        return publish_handoff_intent(root, binding, publication, recheck)
                    return publish_initial_intent(root, binding, publication, recheck,
                                                  owner_check=self._initial_owner_check)
            finally:
                native._LOCK.release()
        except BaseException as error:
            if not (retry_busy and type(error) is InitialPrepareBusy):
                self._preview.discard(preview_id)
            raise
        finally:
            if running:
                sessions._RUNNING_SESSIONS_LOCK.release()
            if locked:
                self._lock.release()
            self._import_lock.release()

    @contextmanager
    def _sync_guard(self, generation, turn_id, operation_id):
        """Pin the admitted native Turn, generation and registry without waiting."""
        from . import native
        from core.web.services import session_service as sessions

        if not self._lock.acquire(blocking=False):
            raise MigrationIOError("affairs_sync_busy")
        running = False
        try:
            with self._sync_signal_lock:
                current = self._sync_active
                valid = (self._active and generation == self._generation and current is not None
                         and current["operationId"] == operation_id and current["turnId"] == turn_id
                         and operation_id not in self._sync_cancelled)
            if not valid or native._STOP_REQUESTED.is_set() or not native._STARTED or native._OFFLINE_MIGRATION:
                raise MigrationIOError("affairs_sync_cancelled")
            if not sessions._RUNNING_SESSIONS_LOCK.acquire(blocking=False):
                raise MigrationIOError("affairs_sync_busy")
            running = True
            if (native._SESSION_ID not in sessions._RUNNING_SESSION_IDS
                    or sessions._SESSION_ACTIVE_TURN_IDS.get(native._SESSION_ID) != turn_id):
                raise MigrationIOError("affairs_sync_turn_invalid")
            yield
        finally:
            if running:
                sessions._RUNNING_SESSIONS_LOCK.release()
            self._lock.release()

    def cancel_affairs(self, operation_id, preview_id):
        """Revoke before waiting; cancellation acknowledges only a drained owner."""
        with self._sync_signal_lock:
            seen = self._sync_seen.get(operation_id)
            current = self._sync_active
            if (seen is not None and seen["previewId"] != preview_id
                    or current is not None and current["operationId"] == operation_id
                    and current["previewId"] != preview_id):
                raise ValueError("affairs_sync_operation_mismatch")
            if operation_id not in self._sync_cancelled and len(self._sync_cancelled) >= 256:
                raise MigrationIOError("affairs_sync_cancel_capacity")
            self._sync_cancelled[operation_id] = preview_id
            if current is not None and current["operationId"] == operation_id:
                current["owner"].revoke()
                done = current["done"]
            else:
                done = None
        if done is not None and not done.wait(timeout=10):
            raise MigrationIOError("affairs_sync_drain_unconfirmed")
        # The sync guard holds this lock until the write capability drains.
        with self._lock:
            self._preview.discard(preview_id)
            return {"schemaVersion": 1, "operationId": operation_id, "cancelled": True}

    def sync_affairs(self, project_id, preview_id, revision, turn_id, operation_id, recover_sync_id=None):
        """Consume exactly one main-approved preview and synchronize its affairs."""
        from .main_control import affairs_migration_id
        from .migration_affairs_conflicts import (discover_affairs_baseline_locked, locked_affairs_target,
            _BaselineVerifier, _sync_candidates, _verify_record_sources)
        from .migration_affairs_convergence import converge_affairs
        from .migration_io import pinned_source_files
        from .online_affairs_sync import synchronize_affairs
        from .online_affairs_sync_lease import OnlineAffairsSyncOwner

        if recover_sync_id is not None and (not isinstance(recover_sync_id, str)
                or not re.fullmatch(r"affairs-[a-f0-9]{40}", recover_sync_id)):
            raise ValueError("affairs_sync_recovery_id_invalid")
        mid = recover_sync_id or affairs_migration_id(project_id, preview_id)
        base = {"schemaVersion": 1, "projectId": project_id, "previewId": preview_id,
                "migrationId": mid, "readyForCutover": False}
        binding_key = (project_id, preview_id, revision, turn_id, recover_sync_id)
        if not self._import_lock.acquire(blocking=False):
            with self._sync_signal_lock:
                active = self._sync_active
                same_preview = active is not None and active["previewId"] == preview_id
            if not same_preview:
                self._preview.discard(preview_id)
            return {**base, "state": "unknown", "code": "unknown"} if recover_sync_id else {**base, "state": "rejected", "code": "busy"}
        owner = OnlineAffairsSyncOwner(self._generation,
            lambda generation, turn: self._sync_guard(generation, turn, operation_id))
        current = {"operationId": operation_id, "previewId": preview_id, "turnId": turn_id,
                   "owner": owner, "done": Event()}
        try:
            with self._sync_signal_lock:
                previous = self._sync_seen.get(operation_id)
                if previous is not None:
                    if previous["binding"] != binding_key:
                        return {**base, "state": "unknown", "code": "unknown"}
                    return previous.get("result") or {**base, "state": "unknown", "code": "unknown"}
                if operation_id in self._sync_cancelled:
                    if self._sync_cancelled[operation_id] != preview_id:
                        return {**base, "state": "unknown", "code": "unknown"}
                    self._preview.discard(preview_id)
                    # A cancel may arrive after an evicted successful result.
                    # Its tombstone fences future work, not prior effects.
                    return {**base, "state": "unknown", "code": "unknown"}
                if len(self._sync_seen) >= 256:
                    # A cached terminal result is evictable only after its
                    # preview was consumed or explicitly discarded. A late
                    # duplicate then cannot acquire a fresh write capability.
                    terminal = next((key for key, entry in self._sync_seen.items()
                                     if entry["result"] is not None), None)
                    if terminal is None:
                        return {**base, "state": "unknown", "code": "unknown"} if recover_sync_id else {**base, "state": "rejected", "code": "busy"}
                    del self._sync_seen[terminal]
                self._sync_seen[operation_id] = {"binding": binding_key, "previewId": preview_id, "result": None}
                self._sync_active = current
            validation_phase = "preview"
            convergence_attempted = False
            try:
                with self._sync_guard(self._generation, turn_id, operation_id):
                    binding = self._preview.consume_for_import(preview_id, project_id, revision, turn_id)
                    validation_phase = "baseline"
                    paths, source_agent = binding[2], binding[3]
                    scope = {"projectId": paths.project_id, "instanceId": paths.instance_id, "agentId": source_agent}
                    from . import native
                    if not native._LOCK.acquire(blocking=False):
                        raise MigrationIOError("affairs_sync_busy")
                    try:
                        if recover_sync_id is not None:
                            from .migration_affairs_conflicts import _load
                            record = _load(self._owner._profile, mid, scope, native._AGENT_ID)
                            if record["snapshotMigrationId"] != mid:
                                raise MigrationIOError("affairs_sync_recovery_binding_invalid")
                            baseline = record["baselineMigrationId"]
                            unresolved = None
                        else:
                            with locked_affairs_target(self._owner._profile, target_agent_id=native._AGENT_ID) as target:
                                try:
                                    baseline = discover_affairs_baseline_locked(self._owner._profile, source_scope=scope,
                                        target_agent_id=native._AGENT_ID, target=target)["baselineMigrationId"]
                                    unresolved = None
                                except MigrationIOError as error:
                                    if str(error) != "affairs_baseline_unresolved":
                                        raise
                                    verifier = _BaselineVerifier(self._owner._profile, scope, native._AGENT_ID, target=target)
                                    verifier.candidates = _sync_candidates(self._owner._profile, scope, native._AGENT_ID)
                                    pending = []
                                    for links in verifier.candidates.values():
                                        for record, receipt, record_snapshot, receipt_snapshot in links:
                                            if receipt["published"] is not True or receipt["conflictCount"] == 0:
                                                continue
                                            _verify_record_sources(self._owner._profile, record, verifier)
                                            verifier.snapshots.extend((record_snapshot, receipt_snapshot))
                                            if not verifier.converged(record, receipt):
                                                pending.append((record["syncId"], record["baselineMigrationId"]))
                                    verifier.finish()
                                    if len(pending) != 1:
                                        raise MigrationIOError("affairs_baseline_unresolved")
                                    unresolved = pending[0]
                    finally:
                        native._LOCK.release()
                if unresolved is not None:
                    sync_id, old_baseline = unresolved
                    # Leave the non-reentrant session guard before owner.admit;
                    # admit reacquires the same Turn/registry guard once.
                    with owner.admit(generation=self._generation, turn_id=turn_id,
                                     baseline_migration_id=old_baseline, source_scope=scope) as lease:
                        binding[4]()
                        with pinned_source_files(binding[5]):
                            binding[4]()
                            convergence_attempted = True
                            converge_affairs(lease, sync_id=sync_id, source_scope=scope)
                            binding[4]()
                    with self._sync_guard(self._generation, turn_id, operation_id):
                        binding[4]()
                        if not native._LOCK.acquire(blocking=False):
                            raise MigrationIOError("affairs_sync_busy")
                        try:
                            with locked_affairs_target(self._owner._profile, target_agent_id=native._AGENT_ID) as target:
                                baseline = discover_affairs_baseline_locked(self._owner._profile, source_scope=scope,
                                    target_agent_id=native._AGENT_ID, target=target)["baselineMigrationId"]
                        finally:
                            native._LOCK.release()
            except Exception as error:
                with self._sync_signal_lock:
                    cancelled = operation_id in self._sync_cancelled or owner._revoked.is_set()
                if recover_sync_id is not None:
                    result = {**base, "state": "unknown", "code": "unknown"}
                elif convergence_attempted and str(error) not in {"affairs_convergence_not_reached", "affairs_convergence_not_required"}:
                    result = {**base, "state": "unknown", "code": "unknown"}
                elif not cancelled and validation_phase == "preview" and str(error) == "history_preview_expired":
                    # The preview may already have been consumed by an evicted
                    # completed request; absence cannot prove it did not write.
                    result = {**base, "state": "unknown", "code": "unknown"}
                else:
                    baseline_codes = {"affairs_baseline_unresolved": "unresolved",
                                      "affairs_convergence_not_reached": "unresolved",
                                      "affairs_convergence_not_required": "unresolved",
                                      "affairs_baseline_pending": "pending",
                                      "affairs_baseline_not_found": "baseline_unavailable"}
                    code = ("cancelled" if cancelled else "busy" if str(error) == "affairs_sync_busy"
                            else baseline_codes.get(str(error), "project_unavailable") if validation_phase == "baseline"
                            else "preview_invalid")
                    result = {**base, "state": "rejected", "code": code}
            else:
                try:
                    if recover_sync_id is None:
                        outcome = synchronize_affairs(preview_binding=binding, owner=owner, generation=self._generation,
                            turn_id=turn_id, migration_id=mid, baseline_migration_id=baseline)
                    else:
                        from .migration_affairs_sync import reconcile_affairs
                        from .migration_affairs_conflicts import _digest, _load, _sync_receipt
                        with owner.admit(generation=self._generation, turn_id=turn_id,
                                         baseline_migration_id=baseline, source_scope=scope) as lease:
                            binding[4]()
                            with pinned_source_files(binding[5]):
                                binding[4]()
                                # Keep the ledger and receipt mutex held through
                                # confirmation, including for published receipts.
                                with locked_affairs_target(lease.root, target_agent_id=lease.agent_id) as target:
                                    record = _load(lease.root, mid, scope, lease.agent_id)
                                    if (record["baselineMigrationId"] != baseline
                                            or record["snapshotMigrationId"] != mid):
                                        raise MigrationIOError("affairs_sync_recovery_binding_invalid")
                                    receipt, _ = _sync_receipt(lease.root, record)
                                    if receipt is None or _digest(target.rows(lease.root, lease.agent_id)) != receipt["targetSha256"]:
                                        raise MigrationIOError("affairs_sync_outcome_unknown")
                                    sync = reconcile_affairs(lease, sync_id=mid, source_scope=scope,
                                                             confirmation_only=True)
                                binding[4]()
                                lease.check()
                        # A matching ledger confirms the planned result, but
                        # cannot attribute the writes to the interrupted run.
                        outcome = {"state": "confirmed", "code": "matched", "conflictCount": sync["conflictCount"]}
                except Exception:
                    outcome = {}
                if not isinstance(outcome, dict):
                    outcome = {}
                state, code = outcome.get("state"), outcome.get("code")
                valid_counts = (type(outcome.get("appliedCount")) is int
                    and 0 <= outcome["appliedCount"] <= 4096
                    and type(outcome.get("conflictCount")) is int
                    and 0 <= outcome["conflictCount"] <= 4096)
                if (recover_sync_id is not None and state == "confirmed" and code == "matched"
                        and type(outcome.get("conflictCount")) is int and 0 <= outcome["conflictCount"] <= 4096):
                    result = {**base, "state": state, "code": code, "conflictCount": outcome["conflictCount"]}
                elif valid_counts and state == "complete" and code == "synchronized" and outcome["conflictCount"] == 0:
                    result = {**base, "state": state, "code": code, "appliedCount": outcome["appliedCount"], "conflictCount": 0}
                elif valid_counts and state == "partial" and code == "unresolved" and outcome["conflictCount"] > 0:
                    result = {**base, "state": state, "code": code, "appliedCount": outcome["appliedCount"], "conflictCount": outcome["conflictCount"]}
                else:
                    result = {**base, "state": "unknown", "code": "unknown"}
            # Includes guard failures before consume: such previews must not
            # become executable after their result leaves the bounded cache.
            self._preview.discard(preview_id)
            with self._sync_signal_lock:
                self._sync_seen[operation_id]["result"] = result
            return result
        finally:
            with self._sync_signal_lock:
                if self._sync_active is current:
                    self._sync_active = None
                current["done"].set()
            self._import_lock.release()

    def sync_episodic(self, project_id, preview_id, revision, turn_id, operation_id, recover_sync_id=None,
                      resolve_sync_id=None, review_token=None):
        """Consume an approved preview under the same cancellation fence as affairs."""
        from .main_control import episodic_migration_id, initial_migration_id
        from .online_episodic_sync import EpisodicSyncPrewrite, OnlineEpisodicSyncOwner, synchronize_episodic
        if recover_sync_id is not None and (not isinstance(recover_sync_id, str)
                or not re.fullmatch(r"episodic-[a-f0-9]{40}", recover_sync_id)):
            raise ValueError("episodic_sync_recovery_id_invalid")
        if ((resolve_sync_id is None) != (review_token is None)
                or resolve_sync_id is not None and (recover_sync_id is not None
                    or not isinstance(resolve_sync_id, str) or not re.fullmatch(r"episodic-[a-f0-9]{40}", resolve_sync_id)
                    or not isinstance(review_token, str) or not re.fullmatch(r"[a-f0-9]{64}", review_token))):
            raise ValueError("episodic_sync_resolution_invalid")
        mid = recover_sync_id or episodic_migration_id(project_id, preview_id)
        base = {"schemaVersion": 1, "projectId": project_id, "previewId": preview_id,
                "migrationId": mid, "readyForCutover": False}
        unknown = {**base, "state": "unknown", "code": "unknown"}
        binding_key = ("episodic", project_id, preview_id, revision, turn_id, recover_sync_id, resolve_sync_id, review_token)
        if not self._import_lock.acquire(blocking=False):
            with self._sync_signal_lock:
                active = self._sync_active
                same = active is not None and active["previewId"] == preview_id
            if not same:
                self._preview.discard(preview_id)
            return unknown if recover_sync_id else {**base, "state": "rejected", "code": "busy"}
        owner = OnlineEpisodicSyncOwner(self._generation,
            lambda generation, turn: self._sync_guard(generation, turn, operation_id))
        current = {"operationId": operation_id, "previewId": preview_id, "turnId": turn_id,
                   "owner": owner, "done": Event()}
        try:
            with self._sync_signal_lock:
                previous = self._sync_seen.get(operation_id)
                if previous is not None:
                    if previous["binding"] != binding_key:
                        self._preview.discard(preview_id)
                        return unknown
                    return previous.get("result") or unknown
                if operation_id in self._sync_cancelled:
                    self._preview.discard(preview_id)
                    return unknown
                if len(self._sync_seen) >= 256:
                    terminal = next((key for key, value in self._sync_seen.items() if value["result"] is not None), None)
                    if terminal is None:
                        self._preview.discard(preview_id)
                        return unknown
                    del self._sync_seen[terminal]
                self._sync_seen[operation_id] = {"binding": binding_key, "previewId": preview_id, "result": None}
                self._sync_active = current
            phase = "preview"
            try:
                with self._sync_guard(self._generation, turn_id, operation_id):
                    binding = self._preview.consume_for_import(preview_id, project_id, revision, turn_id)
                phase = "sync"
                options = ({"resolve_sync_id": resolve_sync_id, "review_token": review_token} if resolve_sync_id is not None else {})
                outcome = synchronize_episodic(preview_binding=binding, owner=owner, generation=self._generation,
                    turn_id=turn_id, initial_operation_id=initial_migration_id(project_id, "", "personal"),
                    sync_id=mid, confirmation_only=recover_sync_id is not None, **options)
                if (type(outcome) is not dict or type(outcome.get("appliedCount")) is not int
                        or not 0 <= outcome["appliedCount"] <= 4096 or type(outcome.get("conflictCount")) is not int
                        or not 0 <= outcome["conflictCount"] <= 4096
                        or resolve_sync_id is not None and (outcome["appliedCount"] != 0 or outcome["conflictCount"] != 0)):
                    result = unknown
                elif recover_sync_id is not None:
                    result = {**base, "state": "confirmed", "code": "matched", "conflictCount": outcome["conflictCount"]}
                else:
                    conflict = outcome["conflictCount"]
                    result = {**base, "state": "partial" if conflict else "complete",
                              "code": "unresolved" if conflict else "resolved" if resolve_sync_id is not None else "synchronized",
                              "appliedCount": outcome["appliedCount"], "conflictCount": conflict}
            except EpisodicSyncPrewrite as error:
                code = str(error)
                result = (unknown if recover_sync_id is not None or code not in {
                    "busy", "baseline_unavailable", "cancelled", "project_unavailable", "unresolved", "pending", "row_limit", "review_changed"}
                    else {**base, "state": "rejected", "code": code})
            except MigrationIOError as error:
                code = str(error)
                if recover_sync_id is not None or phase != "preview" or code == "history_preview_expired":
                    result = unknown
                else:
                    result = {**base, "state": "rejected", "code": (
                        "busy" if code == "affairs_sync_busy" else "cancelled" if code == "affairs_sync_cancelled"
                        else "preview_invalid")}
            except Exception:
                # Once the approved operation starts, loss of acknowledgement
                # never authorizes another write under a replacement ID.
                result = unknown
            self._preview.discard(preview_id)
            with self._sync_signal_lock:
                self._sync_seen[operation_id]["result"] = result
            return result
        finally:
            with self._sync_signal_lock:
                if self._sync_active is current:
                    self._sync_active = None
                current["done"].set()
            self._import_lock.release()

    def cancel(self, operation_id, preview_id):
        """Fence publication before acknowledging cancellation, even if early."""
        with self._lock:
            if operation_id not in self._cancelled and len(self._cancelled) >= 256:
                raise MigrationIOError("history_cancel_capacity")
            self._cancelled.add(operation_id)
            self._preview.discard(preview_id)
            if self._operation == operation_id:
                self._owner.suspend()
            return {"schemaVersion": 1, "operationId": operation_id, "cancelled": True}

    @contextmanager
    def _history_target_guard(self):
        from . import native
        from core.infrastructure.native_runtime import assistant_native_root
        if not native._LOCK.acquire(blocking=False):
            raise MigrationIOError("history_target_unavailable")
        try:
            if (not native._STARTED or native._OFFLINE_MIGRATION or native._STOP_REQUESTED.is_set()
                    or assistant_native_root() != self._owner._profile
                    or not native._AGENT_ID or not native._SESSION_ID):
                raise MigrationIOError("history_target_unavailable")
            yield native._AGENT_ID, native._SESSION_ID
        finally:
            native._LOCK.release()

    def history_receipt(self, project_id, preview_id, revision):
        """Read a past result against a freshly reconstructed source authority."""
        base = {"schemaVersion": 1, "projectId": project_id, "previewId": preview_id,
                "state": "unknown", "code": "unknown", "readyForCutover": False}
        if not self._import_lock.acquire(blocking=False):
            return base
        fresh = None
        try:
            with self.guard():
                if self._dispatch._registry_revision != revision:
                    return base
            fresh = self._preview.preview(project_id)["previewId"]
            with self._preview._lock:
                public = self._preview.verify_preview(fresh)
                row = self._preview._previews[fresh]
                root, workspace, paths, snapshots = row[3], row[4], row[5], row[7]
                verify = row[1]
            @contextmanager
            def authority():
                verify()
                yield
                verify()
            source = AuthorizedHistorySource(root, workspace, paths.instance_id,
                public["assistantAgentId"], paths.project_id, authority, snapshots)
            self._owner.replace_sources({project_id: source})
            outcome = self._owner.read_bound_history(project_id, preview_id, target_guard=self._history_target_guard)
            with self.guard():
                if outcome is None or self._dispatch._registry_revision != revision:
                    return base
                return {**base, "state": "published", "code": "imported",
                        "requestId": outcome["requestId"], "migrationId": outcome["migrationId"],
                        "historyCount": outcome["historyCount"]}
        except Exception:
            return base
        finally:
            self._owner.suspend()
            if fresh is not None:
                self._preview.discard(fresh)
            self._import_lock.release()

    def import_history(self, project_id, preview_id, revision, turn_id, operation_id):
        base = {"schemaVersion": 1, "projectId": project_id, "previewId": preview_id,
                "readyForCutover": False}
        if not self._import_lock.acquire(blocking=False):
            self._preview.discard(preview_id)
            return {**base, "state": "rejected", "code": "busy"}
        try:
            try:
                with self._lock:
                    if operation_id in self._cancelled:
                        self._preview.discard(preview_id)
                        return {**base, "state": "rejected", "code": "cancelled"}
                    self._operation = operation_id
                    self._operation_turn = turn_id
                    self._operation_stopped = False
                with self.guard():
                    root, workspace, paths, agent_id, verify, snapshots = self._preview.consume_for_import(
                        preview_id, project_id, revision, turn_id, purpose="history")

                    @contextmanager
                    def authority():
                        verify()
                        yield
                        verify()

                    source = AuthorizedHistorySource(root, workspace, paths.instance_id, agent_id,
                                                     paths.project_id, authority, snapshots)
                    self._owner.replace_sources({project_id: source})
            except (MigrationIOError, ValueError):
                self._preview.discard(preview_id)
                code = "cancelled" if operation_id in self._cancelled else "preview_invalid"
                return {**base, "state": "rejected", "code": code}
            try:
                result = self._owner.import_bound_history(project_id, preview_id, turn_id,
                                                          target_guard=self._history_target_guard)
                return {**base, "state": "published", "code": "imported",
                        "historyCount": result["historyCount"]}
            except Exception as error:
                # The writer may have reserved or published before losing its
                # final confirmation. Never replay or guess from an exception.
                code = str(error) if type(error) is MigrationIOError and str(error) in _HISTORY_DIAGNOSTICS else "unclassified"
                _LOGGER.warning("history_import_unconfirmed reason=%s", code)
                self._preview.discard(preview_id)
                return {**base, "state": "unknown", "code": "unknown"}
            finally:
                self._owner.suspend()
        finally:
            with self._lock:
                self._operation = None
                self._operation_turn = None
                self._operation_stopped = False
            self._import_lock.release()
