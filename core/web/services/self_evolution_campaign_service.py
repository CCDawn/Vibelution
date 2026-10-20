"""Bounded, durable campaigns delegating every candidate to the single-loop owner.

The parent contains budgets, authority, exact child references and short results.
It never owns candidate execution, transcripts, Git integration or deployment.
"""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.infrastructure.file_lock import cross_process_file_lock
from core.infrastructure.process_liveness import is_pid_alive
from core.runtime_manager.work_run_store import WorkRunStore, normalize_run_id
from .self_evolution_autonomous_loop_service import (
    AutonomousLoopConflictError, AutonomousLoopValidationError, _normalize_request,
)
from .self_evolution_local_integration import LocalIntegrationError, _digest

RUN_KIND = "self_evolution_campaign"
_ACTIVE = {"queued", "running", "stopping"}


class CampaignValidationError(AutonomousLoopValidationError):
    """Invalid or unavailable durable campaign evidence."""


class CampaignConflictError(AutonomousLoopConflictError):
    """A different request or worker owns this campaign."""


def _lock(store: WorkRunStore):
    # One short authority lock also serializes admission across processes.
    return cross_process_file_lock(store.kind_dir(RUN_KIND) / "campaign-authority")


def _normalize(request: dict) -> dict:
    if not isinstance(request, dict) or set(request) - {"goal", "maxIterations", "localIntegration", "rounds", "idempotencyKey"}:
        raise CampaignValidationError("Campaign request contains unsupported fields.")
    key = request.get("idempotencyKey")
    rounds = request.get("rounds", 3)
    if not isinstance(key, str) or not key.strip() or key != key.strip() or len(key) > 120:
        raise CampaignValidationError("idempotencyKey is required and must contain at most 120 characters.")
    if type(rounds) is not int or not 1 <= rounds <= 10:
        raise CampaignValidationError("rounds must be an integer between 1 and 10.")
    child = _normalize_request(request)
    if not child.get("localIntegration"):
        raise CampaignValidationError("Campaigns require explicit bounded localIntegration authorization.")
    return {**child, "rounds": rounds, "idempotencyKey": key}


def _child_request(parent: dict) -> dict:
    return {key: deepcopy(value) for key, value in parent["request"].items()
            if key not in {"rounds", "idempotencyKey"}}


def _source(store: WorkRunStore, campaign_id: str, number: int) -> dict:
    return {"campaignId": campaign_id, "round": number,
            "childRunId": f"{campaign_id}-round-{number}", "storeRoot": str(store.root.resolve())}


def _load(store: WorkRunStore, run_id: str, *, required: bool = True) -> dict | None:
    run_id = normalize_run_id(run_id)
    snapshot = store.load_snapshot(RUN_KIND, run_id)
    if snapshot is None:
        path = store.runs_dir(RUN_KIND) / f"{run_id}.json"
        index = store.load_run_index(RUN_KIND)
        known = [*(index.get("activeRunIds") or []), *(index.get("recentRunIds") or []),
                 index.get("activeRunId"), index.get("latestRunId")]
        admitted = store.kind_dir(RUN_KIND) / "admissions" / run_id
        if required or admitted.exists() or path.exists() or any(path.parent.glob(path.name + ".corrupt-*")) or run_id in known:
            raise CampaignValidationError("Known campaign snapshot is missing or unreadable.")
        return None
    if snapshot.get("runKind") != RUN_KIND or snapshot.get("runId") != run_id or snapshot.get("schemaVersion") != 1:
        raise CampaignValidationError("Campaign snapshot identity is invalid.")
    return snapshot


def _validate_parent(parent: dict, now: datetime) -> dict:
    try:
        request = _normalize(parent["request"])
        grant = parent["localIntegrationAuthorization"]
        local = request["localIntegration"]
        expiry = datetime.fromisoformat(grant["expiresAt"])
        issued = datetime.fromisoformat(grant["issuedAt"])
        principals = grant["principals"]
        valid = (parent.get("requestDigest") == _digest(request)
                 and grant.get("runId") == parent["runId"] and grant.get("revoked") is False
                 and grant.get("authorizationId") and grant.get("operatorId")
                 and grant.get("requestDigest") == _digest(local)
                 and grant.get("allowedFiles") == local["allowedFiles"]
                 and grant.get("teamId") == local["teamId"]
                 and expiry.tzinfo is not None and issued.tzinfo is not None
                 and 0 < (expiry - issued).total_seconds() <= local["validForSeconds"]
                 and expiry > now and parent.get("deadline") == grant["expiresAt"]
                 and set(principals) == {"observer", "executor", "reviewer"}
                 and all(isinstance(v, dict) and v.get("agentId") and v.get("fingerprint") for v in principals.values())
                 and len({v["agentId"] for v in principals.values()}) == 3)
    except (KeyError, TypeError, ValueError) as exc:
        raise LocalIntegrationError("Campaign authorization is invalid or expired.") from exc
    if not valid or parent.get("stopRequested") or parent.get("status") not in {"queued", "running"}:
        raise LocalIntegrationError("Campaign authorization is unavailable, revoked or expired.")
    return grant


def _delegation(context: dict, *, now: datetime | None = None) -> dict:
    source = context.get("_campaignSource")
    if not isinstance(source, dict) or set(source) != {"campaignId", "round", "childRunId", "storeRoot"}:
        raise LocalIntegrationError("Campaign child requires an exact private source.")
    try:
        campaign_id = normalize_run_id(source["campaignId"])
        number = source["round"]
        if type(number) is not int or not 1 <= number <= 10:
            raise ValueError("round")
        store = WorkRunStore(root=Path(source["storeRoot"]))
        if source != _source(store, campaign_id, number) or context.get("runId") != source["childRunId"]:
            raise ValueError("identity")
        parent = _load(store, campaign_id)
        grant = _validate_parent(parent, now or datetime.now(timezone.utc))
        refs = parent.get("rounds") or []
        if (number > parent["request"]["rounds"] or len(refs) != number
                or refs[-1].get("source") != source or refs[-1].get("runId") != source["childRunId"]
                or refs[-1].get("status") != "running" or context.get("request") != _child_request(parent)):
            raise ValueError("reference")
    except (KeyError, TypeError, ValueError) as exc:
        raise LocalIntegrationError("Campaign child source or canonical grant changed.") from exc
    delegated = deepcopy(grant)
    delegated.update(runId=context["runId"], sourceRunId=campaign_id,
                     requestDigest=_digest(context["request"]["localIntegration"]),
                     campaignSource=deepcopy(source), sourceDigest=_digest(source))
    supplied = context.get("localIntegrationAuthorization")
    if supplied is not None and supplied != delegated:
        raise LocalIntegrationError("Campaign child grant is stale.")
    return delegated


def delegated_authorization(context: dict) -> dict:
    """Derive authority from canonical parent evidence without renewing it."""
    source = context.get("_campaignSource") or {}
    if not source.get("storeRoot"):
        raise LocalIntegrationError("Campaign source is missing.")
    with _lock(WorkRunStore(root=Path(source["storeRoot"]))):
        return _delegation(context)


@contextmanager
def source_guard(context: dict):
    """Final merge lock order: campaign authority, then child authorization."""
    source = context.get("_campaignSource")
    if not source:
        grant = context.get("localIntegrationAuthorization") or {}
        if grant.get("campaignSource") or grant.get("sourceDigest"):
            raise LocalIntegrationError("Campaign private source was removed.")
        yield
        return
    with _lock(WorkRunStore(root=Path(source["storeRoot"]))):
        _delegation(context)
        yield


class SelfEvolutionCampaignService:
    def __init__(self, *, store: WorkRunStore, child: Any, authorize: Callable[[dict], dict],
                 now: Callable[[], datetime] | None = None, process_id: int | None = None,
                 process_alive: Callable[[int], bool] | None = None) -> None:
        self.store, self.child, self.authorize = store, child, authorize
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._pid = process_id or os.getpid()
        self._alive = process_alive or is_pid_alive
        self._owner = uuid.uuid4().hex

    def _save(self, parent: dict) -> dict:
        parent["updatedAt"] = self._now().isoformat()
        return self.store.persist_snapshot(RUN_KIND, parent, active_run_id=parent["runId"] if parent["status"] in _ACTIVE else "")

    def get(self, campaign_id: str) -> dict:
        with _lock(self.store):
            return _load(self.store, campaign_id)

    def active(self) -> dict | None:
        with _lock(self.store):
            index = self.store.load_run_index(RUN_KIND)
            active = index.get("activeRunId")
            return _load(self.store, active) if active else None

    def queue(self, request: dict) -> dict:
        normalized = _normalize(request)
        campaign_id = "self-campaign-" + _digest(normalized["idempotencyKey"])[:32]
        with _lock(self.store):
            previous = _load(self.store, campaign_id, required=False)
            if previous is not None:
                if previous.get("requestDigest") != _digest(normalized) or previous.get("request") != normalized:
                    raise CampaignConflictError("Idempotency key already belongs to another request.")
                return previous
            index = self.store.load_run_index(RUN_KIND)
            if index.get("activeRunIds") or index.get("activeRunId"):
                raise CampaignConflictError("An active self-evolution campaign already exists.")
            latest = index.get("latestRunId")
            if latest and _load(self.store, latest).get("childUnsettled"):
                raise CampaignConflictError("Previous campaign child execution is not settled.")
            # The bounded WorkRun index is an accelerator, not an authority to
            # forget active candidates when an index was lost or quarantined.
            for path in self.store.runs_dir(RUN_KIND).glob("*.json"):
                existing = _load(self.store, path.stem)
                if existing["status"] in _ACTIVE or existing.get("childUnsettled"):
                    raise CampaignConflictError("Another campaign owns an active or unsettled child.")
            now = self._now().isoformat()
            parent = {"schemaVersion": 1, "runKind": RUN_KIND, "runId": campaign_id,
                      "status": "queued", "phase": "queued", "request": normalized,
                      "requestDigest": _digest(normalized), "rounds": [], "stopRequested": False,
                      "runtimeOwner": {"pid": self._pid}, "_campaignExecutionSettled": True,
                      "createdAt": now, "updatedAt": now}
            grant = self.authorize(deepcopy(parent))
            parent.update(localIntegrationAuthorization=deepcopy(grant), deadline=grant.get("expiresAt"))
            _validate_parent(parent, self._now())
            # Retain a tiny durable admission tombstone beyond recent-index
            # retention. A missing known snapshot must never mint a new grant.
            admitted = self.store.kind_dir(RUN_KIND) / "admissions" / campaign_id
            admitted.parent.mkdir(parents=True, exist_ok=True)
            admitted.write_text(parent["requestDigest"], encoding="utf-8")
            return self._save(parent)

    def _stop(self, campaign_id: str, reason: str, *, revoke: bool = False) -> dict:
        with _lock(self.store):
            parent = _load(self.store, campaign_id)
            if parent["status"] == "completed":
                return parent
            status = "stopping" if parent.get("childUnsettled") else "stopped"
            parent.update(status=status, phase=status, stopRequested=True, stopReason=reason)
            if revoke:
                parent["localIntegrationAuthorization"]["revoked"] = True
            parent = self._save(parent)
            ref = deepcopy(parent["rounds"][-1]) if parent["rounds"] else None
        # Never acquire the child's lock or wait for its hook under the parent lock.
        if ref and ref.get("status") == "running":
            try:
                self.child.cancel_campaign(ref["runId"], source=ref["source"])
            except (ValueError, OSError):
                pass  # Durable stop/grant fencing remains effective.
        return self.get(campaign_id)

    def cancel(self, campaign_id: str) -> dict:
        return self._stop(campaign_id, "cancelled", revoke=True)

    def revoke(self, campaign_id: str) -> dict:
        return self._stop(campaign_id, "authorization_revoked", revoke=True)

    def check_deadline(self, campaign_id: str) -> dict:
        """A composition-owned timer may fence and cancel a blocked child."""
        with _lock(self.store):
            parent = _load(self.store, campaign_id)
            if parent["status"] not in _ACTIVE:
                return parent
            if parent.get("stopRequested"):
                return parent
            try:
                _validate_parent(parent, self._now())
                return parent
            except LocalIntegrationError:
                pass
        return self._stop(campaign_id, "authorization_expired_or_invalid", revoke=True)

    @staticmethod
    def _successful(child: dict | None, ref: dict) -> bool:
        if not isinstance(child, dict):
            return False
        integration, cleanup = child.get("integration") or {}, child.get("cleanup") or {}
        return (child.get("runId") == ref["runId"] and child.get("_campaignSource") == ref["source"]
                and child.get("status") == "completed" and child.get("_campaignExecutionSettled") is True
                and integration.get("status") == "committed" and bool(integration.get("commitSha"))
                and cleanup.get("status") == "cleaned" and cleanup.get("worktreeRemoved") is True
                and cleanup.get("localBranchDeleted") is True)

    def _record(self, campaign_id: str, ref: dict, child: dict | None,
                *, absence_confirmed: bool = False) -> bool:
        if child is not None and (child.get("runId") != ref["runId"] or child.get("_campaignSource") != ref["source"]):
            raise CampaignValidationError("Canonical child identity changed.")
        success = self._successful(child, ref)
        settled = bool(child and child.get("runId") == ref["runId"] and child.get("_campaignSource") == ref["source"]
                       and child.get("_campaignExecutionSettled") is True
                       and child.get("status") in {"completed", "failed", "partial", "stopped", "rejected", "cancelled"})
        settled = settled or (child is None and absence_confirmed)
        with _lock(self.store):
            parent = _load(self.store, campaign_id)
            current = parent["rounds"][-1]
            if current["source"] != ref["source"]:
                raise CampaignConflictError("Campaign child reference changed.")
            current.update(status="completed" if success else "stopped" if settled else "running",
                           childStatus=str((child or {}).get("status") or "unknown")[:80], settled=settled)
            # A merge can have committed before cancellation/cleanup failure.
            # Keep its concise receipt even when the whole round did not pass.
            integration = (child or {}).get("integration") or {}
            if integration.get("status") == "committed":
                current["integrationStatus"] = "committed"
                current["commitSha"] = str(integration.get("commitSha") or "")[:64]
            current["cleanupStatus"] = str(((child or {}).get("cleanup") or {}).get("status") or "unknown")[:80]
            receipt = (child or {}).get("independentReview") or {}
            for key in ("sessionId", "turnId"):
                if receipt.get(key):
                    current["review" + key[0].upper() + key[1:]] = str(receipt[key])[:160]
            parent["childUnsettled"] = not settled
            if not success or parent.get("stopRequested"):
                status = "stopped" if settled else "stopping"
                parent.update(status=status, phase=status, stopRequested=True)
                parent.setdefault("stopReason", "child_not_successful")
            self._save(parent)
        return success

    def run(self, campaign_id: str) -> dict:
        with _lock(self.store):
            parent = _load(self.store, campaign_id)
            if parent["status"] not in _ACTIVE:
                return parent
            if parent.get("_campaignExecutionSettled") is False:
                raise CampaignConflictError("Campaign execution already belongs to a worker.")
            if parent.get("rounds"):
                raise CampaignConflictError("Interrupted campaigns require recovery; children are never rerun.")
            parent.update(status="running", phase="running", _campaignExecutionSettled=False,
                          runtimeOwner={"pid": self._pid, "workerId": self._owner})
            self._save(parent)
        try:
            self._run_owned(campaign_id)
        except Exception:
            # Dispatch/worker errors can occur after durable child creation. Do
            # not retry an unknown candidate or log arbitrary exception content.
            self._stop(campaign_id, "execution_state_unknown", revoke=True)
        finally:
            self._settle_owned(campaign_id)
            with _lock(self.store):
                parent = _load(self.store, campaign_id)
                parent["_campaignExecutionSettled"] = True
                self._save(parent)
        return self.get(campaign_id)

    def _settle_owned(self, campaign_id: str) -> None:
        with _lock(self.store):
            parent = _load(self.store, campaign_id)
            ref = deepcopy(parent["rounds"][-1]) if parent["rounds"] else None
        if not ref or ref["status"] != "running":
            return
        try:
            child = self.child.get_campaign(ref["runId"], source=ref["source"])
            # Only this exiting synchronous owner can prove no dispatch remains
            # in flight. Missing/unreadable *known* children raise in get_child.
            self._record(campaign_id, ref, child, absence_confirmed=child is None)
        except (ValueError, OSError):
            pass

    def _run_owned(self, campaign_id: str) -> dict:
        while True:
            parent = self.check_deadline(campaign_id)
            if parent["status"] != "running":
                return parent
            with _lock(self.store):
                parent = _load(self.store, campaign_id)
                _validate_parent(parent, self._now())
                number = len(parent["rounds"]) + 1
                if number > parent["request"]["rounds"]:
                    parent.update(status="completed", phase="completed", deploymentRequired=True)
                    return self._save(parent)
                source = _source(self.store, campaign_id, number)
                ref = {"runId": source["childRunId"], "round": number, "source": source, "status": "running"}
                parent["rounds"].append(ref)
                parent["childUnsettled"] = True
                self._save(parent)  # Durable dispatch intent precedes every child side effect.
                request = _child_request(parent)
            self.check_deadline(campaign_id)
            if self.get(campaign_id)["status"] != "running":
                return self.get(campaign_id)
            self.child.queue_campaign(request, source=source, run_id=ref["runId"])
            self.check_deadline(campaign_id)
            if self.get(campaign_id)["status"] != "running":
                return self.get(campaign_id)
            self.child.run_until_review(ref["runId"])
            child = self.child.get_campaign(ref["runId"], source=source)
            if not self._record(campaign_id, ref, child):
                return self.get(campaign_id)

    def recover_active(self) -> dict | None:
        """Preserve proven child results after owner death; never launch a round."""
        with _lock(self.store):
            parent = self.active()
            if parent is None:
                return None
            owner = parent.get("runtimeOwner") or {}
            if (parent.get("_campaignExecutionSettled") is False or parent.get("status") == "queued") and self._alive(int(owner.get("pid") or 0)):
                return parent
            campaign_id = parent["runId"]
            ref = deepcopy(parent["rounds"][-1]) if parent["rounds"] else None
            status = "stopping" if parent.get("childUnsettled") else "stopped"
            parent.update(status=status, phase=status, stopRequested=True,
                          stopReason="interrupted_by_restart", _campaignExecutionSettled=True)
            parent["localIntegrationAuthorization"]["revoked"] = True
            self._save(parent)
        if ref and ref["status"] == "running":
            try:
                child = self.child.get_campaign(ref["runId"], source=ref["source"])
                self._record(campaign_id, ref, child, absence_confirmed=child is None)
            except (ValueError, OSError):
                pass
            try:
                self.child.cancel_campaign(ref["runId"], source=ref["source"])
                child = self.child.get_campaign(ref["runId"], source=ref["source"])
                self._record(campaign_id, ref, child, absence_confirmed=child is None)
            except (ValueError, OSError):
                pass
        return self.get(campaign_id)
