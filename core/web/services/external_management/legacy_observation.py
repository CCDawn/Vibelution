"""Durable subject-private observation proofs, with no execution capabilities."""
from __future__ import annotations

from copy import deepcopy
import json
import re

from pydantic import ValidationError

from .contracts import LegacyObserverCreate, LegacyObserverView, LegacyObserversResponse, LegacyReceiptsResponse
from .service import ManagementError
from .store import digest

_ACTION = "legacy_observer"
_MAX_OBSERVERS = 32


class LegacyObservationOwner:
    def __init__(self, store, authorize, native):
        self.store, self.authorize, self.native = store, authorize, native

    @staticmethod
    def _observer_id(subject, request_id):
        return "lob-" + digest([subject, _ACTION, request_id])

    def _read(self, path):
        try:
            return self.store.read(path)
        except (ValueError, TypeError, OSError):
            raise ManagementError("LEGACY_OBSERVATION_UNAVAILABLE", 503) from None

    def _proofs(self, subject, grant):
        proofs = grant.get("legacyObservers", {})
        if not isinstance(proofs, dict) or len(proofs) > _MAX_OBSERVERS:
            raise ManagementError("LEGACY_OBSERVATION_UNAVAILABLE", 503)
        for observer_id, proof in proofs.items():
            try:
                if (not isinstance(proof, dict) or set(proof) != {"request", "fingerprint", "binding", "authority", "sourceIdentity", "sourceAuthority", "dispatchBindings", "actions", "ownerEpoch"}
                        or proof["binding"] != grant["binding"] or proof["authority"] != grant["authority"]
                        or proof["actions"] != ["read_receipt"] or type(proof["ownerEpoch"]) is not int or proof["ownerEpoch"] != 1):
                    raise ValueError("Invalid observation")
                request = LegacyObserverCreate.model_validate(proof["request"]).model_dump()
                if (observer_id != self._observer_id(subject, request["request_id"])
                        or request["expected_binding"] != grant["binding"]
                        or proof["fingerprint"] != digest([subject, grant["binding"], grant["authority"], request])):
                    raise ValueError("Invalid observation binding")
                identity = proof["sourceIdentity"]
                if (not isinstance(identity, dict) or set(identity) != {"agentId", "sessionId", "roleKey", "profile"}
                        or identity["agentId"] != request["source_agent_id"] or identity["roleKey"] != "personal_assistant"
                        or identity["profile"] != "personal_assistant_v1" or not isinstance(proof["sourceAuthority"], str)
                        or not re.fullmatch(r"[a-f0-9]{64}", proof["sourceAuthority"])
                        or proof["sourceAuthority"] != request["expected_source_authority"]):
                    raise ValueError("Invalid source identity")
                summary = self._summary(subject, request, proof, reused=True)
                LegacyObserverView.model_validate(summary)
                bindings = proof["dispatchBindings"]
                if (not isinstance(bindings, list) or len(bindings) != len(request["legacy_message_ids"])
                        or [row["legacyMessageId"] for row in bindings] != request["legacy_message_ids"]
                        or any(not isinstance(row, dict) or set(row) != {"legacyMessageId", "targetAgentId", "targetSessionId", "nativeTurnId"}
                               or any(not isinstance(row[key], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", row[key])
                                      for key in ("legacyMessageId", "targetAgentId", "targetSessionId"))
                               or row["nativeTurnId"] is not None and (not isinstance(row["nativeTurnId"], str)
                                  or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", row["nativeTurnId"])) for row in bindings)):
                    raise ValueError("Invalid dispatch binding")
                key = digest([subject, _ACTION, request["request_id"]])
                record = self._read(self.store.path("requests", key))
                if record != {"action": _ACTION, "request": request, "fingerprint": proof["fingerprint"],
                              "binding": grant["binding"], "authority": grant["authority"]}:
                    raise ValueError("Missing observation intent")
            except (ValueError, TypeError, KeyError, ValidationError):
                raise ManagementError("LEGACY_OBSERVATION_UNAVAILABLE", 503) from None
        return proofs

    @staticmethod
    def _summary(subject, request, proof, *, reused):
        return {"requestId": request["request_id"], "observerId": LegacyObservationOwner._observer_id(subject, request["request_id"]),
                "status": "created" if proof is not None else "unknown", "reused": reused,
                "sourceAgentId": request["source_agent_id"], "sourceSessionId": proof["sourceIdentity"]["sessionId"] if proof else None,
                "legacyMessageIds": request["legacy_message_ids"], "actions": ["read_receipt"], "ownerEpoch": 1,
                "sourceQuiesced": False, "readyForCutover": False, "untrustedContent": True}

    def create(self, subject, capability, payload):
        try:
            request = LegacyObserverCreate.model_validate(payload).model_dump()
        except ValidationError:
            raise ManagementError("INVALID_INPUT", 422) from None
        self.authorize(subject, capability, request["expected_binding"])
        key = digest([subject, _ACTION, request["request_id"]])
        observer_id = self._observer_id(subject, request["request_id"])
        with self.store.lock("requests", key), self.store.lock("subjects", subject):
            grant = self.authorize(subject, capability, request["expected_binding"])
            proofs = self._proofs(subject, grant)
            fingerprint = digest([subject, grant["binding"], grant["authority"], request])
            record = {"action": _ACTION, "request": request, "fingerprint": fingerprint,
                      "binding": grant["binding"], "authority": grant["authority"]}
            path = self.store.path("requests", key)
            existing = self._read(path)
            if existing is not None:
                if existing != record:
                    raise ManagementError("IDEMPOTENCY_CONFLICT", 409)
                # An admitted intent is never prepared or replayed again. A lost
                # proof write remains unknown; a durable proof is sufficient.
                return LegacyObserverView.model_validate(self._summary(subject, request, proofs.get(observer_id), reused=True)).model_dump()
            if observer_id in proofs:
                raise ManagementError("LEGACY_OBSERVATION_UNAVAILABLE", 503)
            if len(proofs) >= _MAX_OBSERVERS:
                raise ManagementError("LEGACY_OBSERVATION_LIMIT", 409)
            prepared = self.native.legacy_observation_snapshot(grant["binding"], request["source_agent_id"],
                request["legacy_message_ids"], request["expected_registry_sha256"])
            if prepared.data["sourceAuthority"] != request["expected_source_authority"]:
                raise ManagementError("LEGACY_SOURCE_CHANGED", 409)
            proof = {"request": request, "fingerprint": fingerprint, "binding": grant["binding"], "authority": grant["authority"],
                     "sourceIdentity": prepared.data["sourceIdentity"], "sourceAuthority": prepared.data["sourceAuthority"],
                     "dispatchBindings": prepared.data["dispatchBindings"],
                     "actions": ["read_receipt"], "ownerEpoch": 1}
            updated = deepcopy(grant)
            updated.setdefault("legacyObservers", {})[observer_id] = proof
            if len(json.dumps(updated, ensure_ascii=False).encode()) > 64 * 1024:
                raise ManagementError("LEGACY_OBSERVATION_LIMIT", 409)
            prepared.verify()
            try:
                self.store.write(path, record)
            except Exception:
                if self._read(path) == record:
                    return LegacyObserverView.model_validate(self._summary(subject, request, None, reused=False)).model_dump()
                raise ManagementError("LEGACY_OBSERVATION_UNAVAILABLE", 503) from None
            try:
                prepared.verify()
                self.authorize(subject, capability, request["expected_binding"])
                self.store.write(self.store.path("subjects", subject), updated)
            except Exception:
                return LegacyObserverView.model_validate(self._summary(subject, request, None, reused=False)).model_dump()
            # Read the persisted authority before claiming the grant exists.
            persisted = self.authorize(subject, capability, request["expected_binding"])
            proof = self._proofs(subject, persisted).get(observer_id)
            return LegacyObserverView.model_validate(self._summary(subject, request, proof, reused=False)).model_dump()

    def _current(self, grant, proof):
        request = proof["request"]
        prepared = self.native.legacy_observation_snapshot(grant["binding"], request["source_agent_id"], request["legacy_message_ids"])
        if (prepared.data["sourceIdentity"] != proof["sourceIdentity"]
                or prepared.data["sourceAuthority"] != proof["sourceAuthority"]):
            raise ManagementError("LEGACY_SOURCE_CHANGED", 409)
        old, new = proof["dispatchBindings"], prepared.data["dispatchBindings"]
        if len(old) != len(new):
            raise ManagementError("LEGACY_SOURCE_CHANGED", 409)
        for previous, current in zip(old, new, strict=True):
            if (any(previous[key] != current[key] for key in ("legacyMessageId", "targetAgentId", "targetSessionId"))
                    or previous["nativeTurnId"] is not None and previous["nativeTurnId"] != current["nativeTurnId"]):
                raise ManagementError("LEGACY_SOURCE_CHANGED", 409)
        prepared.verify()
        return prepared.data

    def list(self, subject, capability):
        self.authorize(subject, capability)
        with self.store.lock("subjects", subject):
            grant = self.authorize(subject, capability)
            proofs = self._proofs(subject, grant)
            result = []
            for observer_id, proof in sorted(proofs.items()):
                self._current(grant, proof)
                result.append(self._summary(subject, proof["request"], proof, reused=True))
            self.authorize(subject, capability)
            return LegacyObserversResponse.model_validate({"observers": result, "untrustedContent": True}).model_dump()

    def read(self, subject, capability, observer_id):
        self.authorize(subject, capability)
        if not isinstance(observer_id, str) or not re.fullmatch(r"lob-[a-f0-9]{64}", observer_id):
            raise ManagementError("INVALID_INPUT", 422)
        with self.store.lock("subjects", subject):
            grant = self.authorize(subject, capability)
            proof = self._proofs(subject, grant).get(observer_id)
            if proof is None:
                raise ManagementError("LEGACY_OBSERVER_UNAVAILABLE", 404)
            current = self._current(grant, proof)
            self.authorize(subject, capability)
            return LegacyReceiptsResponse.model_validate({"observer": self._summary(subject, proof["request"], proof, reused=True),
                "dispatches": current["dispatches"], "untrustedContent": True}).model_dump()
