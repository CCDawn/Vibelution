"""Durable neutral Team intents, delegating every effect to native owners."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.web.services.team_workflow import one_shot
from core.web.services.team_workflow.generic import service as workflows
from core.web.services.team_workflow.generic import store as workflow_store
from core.web.services.team_workflow.generic.models import Flow, SaveFlow

from .store import Store, digest


@dataclass(frozen=True)
class TeamOwner:
    """Created by ManagementService only after its operator grant is validated."""

    subject_id: str
    binding: dict
    authority: str
    record_root: Path


class TeamIntents:
    def __init__(self, owner: TeamOwner, native):
        self.owner = owner
        self.native = native
        self.store = Store(owner.record_root)

    def _key(self, request_id):
        return digest([self.owner.subject_id, self.owner.binding, self.owner.authority, request_id])

    def _check(self, record, request_id):
        from .service import ManagementError
        if (record.get("subjectId") != self.owner.subject_id or record.get("binding") != self.owner.binding
            or record.get("authority") != self.owner.authority):
            raise ManagementError("TARGET_BINDING_CHANGED", 409)
        key = self._key(request_id)
        if (record.get("requestId") != request_id or record.get("flowId") != "ops-dev-" + key[:32]
            or record.get("marker") != {"subjectType": "operator", "subjectId": self.owner.subject_id,
                "binding": self.owner.binding, "requestKey": key, "requestFingerprint": record.get("fingerprint"),
                "teamSource": "external_team:" + key[:40]}):
            raise ManagementError("IDEMPOTENCY_CONFLICT", 409)

    def _run_view(self, record):
        run_id = record.get("runId") or "run-" + workflows.digest([record["flowId"], record["requestId"]])[:40]
        run = workflows.get_run(record["teamId"], run_id)
        values = run.get("values")
        if not isinstance(values, dict) or set(values) != {"goal"} or digest(values["goal"]) != record["goalHash"]:
            raise ValueError("Native run input identity changed")
        run = one_shot._verify_run(run, record, record["requestId"], values["goal"])
        raw = workflow_store.read(workflow_store.path(record["teamId"], "runs", run_id))
        if raw.get("_createFingerprint") != workflows.digest([record["flowId"], 1, values]):
            raise ValueError("Native admission fingerprint changed")
        summary = one_shot._summary(run)
        view = {key: value for key, value in summary.items() if key not in {"ok", "reused"}}
        # Pointers only: querying an artifact body would enter Session reads.
        view["artifactRefs"] = [{key: str(item.get(key) or "")[:160] for key in ("nodeId", "sessionId", "turnId")}
                                for item in (run.get("attempts") or [])[-20:]
                                if item.get("status") == "completed" and item.get("sessionId") and item.get("turnId")]
        return view

    @staticmethod
    def _accepted(result, evidence, view):
        result.update(status="completed", verified=True, phase="started", resumeAllowed=False, teamRun=view)
        result.pop("code", None)
        evidence.update(runId=view["runId"], phase="started")
        return result, evidence, None

    def _view(self, record, *, reused):
        """Read-only native evidence. Missing evidence never authorizes materialization."""
        result = {"status": "unknown", "action": "team_run", "requestId": record["requestId"], "verified": False,
                  "reused": reused, "code": "OPERATION_UNCONFIRMED", "phase": "materialization_pending", "resumeAllowed": False}
        evidence = dict(record)
        try:
            # A persisted run identity no longer depends on today's role profile;
            # ordinary native config/flow edits must not invalidate frozen pins.
            # This also recovers native start acceptance before a local ledger ack.
            if evidence.get("teamId") and evidence.get("flowFingerprint"):
                if not self.native.owns(evidence["teamId"], record["marker"]):
                    return result, evidence, None
                try:
                    return self._accepted(result, evidence, self._run_view(evidence))
                except workflow_store.NotFound:
                    if record.get("runId"):
                        return result, evidence, None
            if record.get("flowRecipeFingerprint") != one_shot.recipe_fingerprint():
                return result, evidence, None
            created = self.native.recover(record["marker"], record["recipeFingerprint"])
            if not created:
                return result, evidence, None
            team_id = workflow_store.token(created["team"]["teamId"])
            if evidence.get("teamId") and team_id != evidence["teamId"]:
                return result, evidence, None
            flow = one_shot._flow(record["flowId"], created)
            fingerprint = one_shot._flow_fingerprint(flow.model_dump(exclude_none=True))
            if record.get("flowFingerprint") and record["flowFingerprint"] != fingerprint:
                return result, evidence, None
            evidence.update(teamId=team_id, flowFingerprint=fingerprint)
            if not self.native.owns(evidence["teamId"], record["marker"]):
                return result, evidence, None
            result.update(phase="materialized", teamRun={"teamId": evidence["teamId"], "flowId": record["flowId"]})
            try:
                saved = Flow.model_validate(workflow_store.read(workflow_store.path(evidence["teamId"], "flows", record["flowId"])), strict=True)
            except workflow_store.NotFound:
                # Only a verified complete Team can reach this safe CAS-create stage.
                result["resumeAllowed"] = not bool(record.get("runId") or record.get("flowSaved"))
                return result, evidence, flow
            if saved.revision != 1 or one_shot._flow_fingerprint(saved.model_dump(exclude_none=True)) != evidence["flowFingerprint"]:
                return result, evidence, None
            evidence.update(flowSaved=True, phase="flow_saved")
            result["phase"] = "flow_saved"
            try:
                view = self._run_view(evidence)
            except workflow_store.NotFound:
                result["resumeAllowed"] = not bool(record.get("runId"))
                return result, evidence, saved
            return self._accepted(result, evidence, view)
        except Exception:  # noqa: BLE001 -- unavailable native evidence cannot grant a retry
            result["resumeAllowed"] = False
            return result, evidence, None

    def receipt(self, request_id):
        from .service import ManagementError
        key = self._key(request_id)
        # No workflow/start/write calls, including no local receipt mutations.
        record = self.store.read(self.store.path("team-requests", key))
        if record is None:
            raise ManagementError("REQUEST_UNAVAILABLE", 404)
        self._check(record, request_id)
        return self._view(record, reused=True)[0]

    def run(self, request_id, parameters):
        from .service import ManagementError
        key = self._key(request_id)
        path = self.store.path("team-requests", key)
        with self.store.lock("team-requests", key):
            record = self.store.read(path)
            reused = record is not None
            if record is not None:
                self._check(record, request_id)
                if record.get("fingerprint") != digest(parameters):
                    raise ManagementError("IDEMPOTENCY_CONFLICT", 409)
            else:
                marker = {"subjectType": "operator", "subjectId": self.owner.subject_id, "binding": self.owner.binding,
                          "requestKey": key, "requestFingerprint": digest(parameters), "teamSource": "external_team:" + key[:40]}
                record = {"subjectId": self.owner.subject_id, "binding": self.owner.binding, "authority": self.owner.authority,
                          "requestId": request_id, "fingerprint": digest(parameters), "goalHash": digest(parameters["goal"]),
                          "marker": marker, "recipeFingerprint": self.native.recipe_fingerprint(parameters["template_id"]),
                          "flowRecipeFingerprint": one_shot.recipe_fingerprint(),
                          "flowId": "ops-dev-" + key[:32], "phase": "materialization_pending"}
                self.store.write(path, record)  # Intent precedes even the first role Agent.
                try:
                    self.native.materialize(parameters, marker)
                except Exception:  # noqa: BLE001 -- do not rebuild after any native side effect or lost acknowledgement
                    return self._view(record, reused=False)[0]
            try:
                return self._advance(path, record, request_id, parameters, reused=reused)
            except Exception:  # noqa: BLE001 -- native or ledger ack loss recovers only by readback of the original intent
                return self._view(record, reused=reused)[0]

    def _advance(self, path, record, request_id, parameters, *, reused):
        result, evidence, flow = self._view(record, reused=reused)
        if result["verified"]:
            self.store.write(path, evidence)
            return result
        if not result["resumeAllowed"]:
            return result
        # Only POST of the original parameters advances a proven safe stage.
        self.store.write(path, evidence)
        if not evidence.get("flowSaved"):
            try:
                workflows.save_flow(evidence["teamId"], evidence["flowId"], SaveFlow(flow=flow, expectedRevision=0).model_dump(exclude_none=True))
            except Exception:  # noqa: BLE001 -- read exact revision/fingerprint after a lost save acknowledgement
                return self._view(evidence, reused=reused)[0]
            evidence.update(flowSaved=True, phase="flow_saved")
            self.store.write(path, evidence)
        args = one_shot.TeamRunArguments.model_validate({**parameters, "request_id": request_id})
        # Shared legacy/native start recipe: exact key + frozen revision, with readback.
        one_shot._launch(path, evidence, args, reused=reused)
        return self._view(evidence, reused=reused)[0]
