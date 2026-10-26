"""Explicit additive grant CAS using the existing management intent/proof stores.

The caller must enforce operator control and native approval. Possessing an old
read scope is never approval to upgrade. An admitted request without a subject
proof stays unknown forever; retrying that request cannot repeat the mutation.
"""
from __future__ import annotations

from copy import deepcopy
import re
import secrets

from pydantic import ValidationError

from .contracts import Binding, SCOPES
from .service import ManagementError
from .store import digest


_ACTION = "authorization_upgrade"
_MAX_PROOFS = 32
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z")


def _error(code="AUTHORIZATION_STATE_INVALID", status=503):
    raise ManagementError(code, status)


def _scopes(value):
    if (not isinstance(value, list) or not value or any(type(scope) is not str or scope not in SCOPES for scope in value)
        or value != sorted(set(value))):
        raise ValueError("Invalid scopes")
    return list(value)


def _binding(value):
    return Binding.model_validate(value).model_dump()


def _fingerprint(subject, binding, authority, previous, additions):
    return digest({"subjectId": subject, "binding": binding, "authority": authority,
                   "expectedScopes": previous, "addScopes": additions})


class UpgradeOwner:
    def __init__(self, store, authorize_callback, identity_callback):
        self.store = store
        self.authorize = authorize_callback
        self.identity = identity_callback

    @staticmethod
    def _actor(subject, capability):
        if (not isinstance(subject, str) or not re.fullmatch(r"ops-[0-9a-f]{32}", subject)
            or not isinstance(capability, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", capability)):
            _error("SUBJECT_DENIED", 403)

    @staticmethod
    def _request_id(request_id):
        if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
            _error("INVALID_INPUT", 422)

    def _read(self, path):
        try:
            return self.store.read(path)
        except (ValueError, TypeError, KeyError):
            _error()

    def _grant(self, subject, capability, expected_binding=None):
        try:
            self.authorize(subject, capability, expected_binding)
        except ManagementError as exc:
            if exc.code in {"SUBJECT_DENIED", "TARGET_BINDING_CHANGED"}:
                _error(exc.code, 403 if exc.code == "SUBJECT_DENIED" else 409)
            _error("AUTHORIZATION_UNAVAILABLE", 503)
        current = self.identity()
        grant = self._read(self.store.path("subjects", subject))
        if (not isinstance(grant, dict) or grant.get("subject_id") != subject
            or not isinstance(grant.get("subject_capability"), str)
            or not secrets.compare_digest(grant["subject_capability"], capability)):
            _error("SUBJECT_DENIED", 403)
        try:
            bound = _binding(grant.get("binding"))
            if not isinstance(grant.get("authority"), str) or not grant["authority"] or not isinstance(current.signature, str) or not current.signature:
                raise ValueError("Invalid grant authority")
            if (bound != _binding(current.binding) or grant.get("authority") != current.signature
                or expected_binding is not None and expected_binding != bound):
                _error("TARGET_BINDING_CHANGED", 409)
            _scopes(grant.get("scopes"))
            revision, proofs = grant.get("grantRevision", 0), grant.get("scopeUpgrades", {})
            if type(revision) is not int or revision < 0 or not isinstance(proofs, dict) or len(proofs) > _MAX_PROOFS:
                raise ValueError("Invalid grant state")
            for key, proof in proofs.items():
                self._proof(subject, grant, key, proof)
        except (ValidationError, ValueError, TypeError, KeyError):
            _error()
        return grant

    @staticmethod
    def _proof(subject, grant, key, proof):
        if (not isinstance(proof, dict) or set(proof) != {"requestId", "fingerprint", "binding", "authority", "authorization"}
            or not isinstance(proof["requestId"], str) or not _REQUEST_ID.fullmatch(proof["requestId"])
            or key != digest([subject, _ACTION, proof["requestId"]])
            or proof["binding"] != grant["binding"] or proof["authority"] != grant["authority"]):
            raise ValueError("Invalid upgrade proof")
        authorization = proof["authorization"]
        if (not isinstance(authorization, dict)
            or set(authorization) != {"subjectId", "previousScopes", "addedScopes", "scopes", "grantRevision"}
            or authorization["subjectId"] != subject):
            raise ValueError("Invalid upgrade authorization")
        previous, additions, scopes = (_scopes(authorization[key]) for key in ("previousScopes", "addedScopes", "scopes"))
        revision = authorization["grantRevision"]
        if (set(previous) & set(additions) or scopes != sorted(set(previous) | set(additions))
            or not set(scopes).issubset(grant["scopes"])
            or type(revision) is not int or revision < 1 or revision > grant.get("grantRevision", 0)
            or proof["fingerprint"] != _fingerprint(subject, proof["binding"], proof["authority"], previous, additions)):
            raise ValueError("Conflicting upgrade proof")
        return authorization

    @staticmethod
    def _unknown(request_id, *, reused):
        return {"action": _ACTION, "requestId": request_id, "status": "unknown", "verified": False, "reused": reused}

    def _recover(self, subject, grant, key, record, *, reused):
        try:
            if (not isinstance(record, dict) or set(record) - {"action", "requestId", "fingerprint", "binding", "authority", "parameters", "receipt"}
                or record["action"] != _ACTION or key != digest([subject, _ACTION, record["requestId"]])
                or record["binding"] != grant["binding"] or record["authority"] != grant["authority"]):
                raise ValueError("Invalid upgrade intent")
            parameters = record["parameters"]
            if not isinstance(parameters, dict) or set(parameters) != {"expected_scopes", "add_scopes"}:
                raise ValueError("Invalid upgrade parameters")
            previous, additions = (_scopes(parameters[key]) for key in ("expected_scopes", "add_scopes"))
            if (set(previous) & set(additions) or record["fingerprint"] !=
                _fingerprint(subject, record["binding"], record["authority"], previous, additions)):
                raise ValueError("Invalid intent fingerprint")
            proof = grant.get("scopeUpgrades", {}).get(key)
            if proof is None:
                if record.get("receipt") is not None:
                    raise ValueError("Receipt missing its subject proof")
                return self._unknown(record["requestId"], reused=reused)
            authorization = self._proof(subject, grant, key, proof)
            if proof["fingerprint"] != record["fingerprint"]:
                raise ValueError("Mismatched intent proof")
            receipt = {"action": _ACTION, "requestId": record["requestId"], "status": "completed", "verified": True,
                       "authorization": deepcopy(authorization)}
            if record.get("receipt") is not None and record["receipt"] != receipt:
                raise ValueError("Conflicting historical receipt")
        except (ValueError, TypeError, KeyError):
            _error()
        if record.get("receipt") is None:
            try:
                self.store.write(self.store.path("requests", key), {**record, "receipt": receipt})
            except Exception:  # A proof is durable; only receipt recovery may retry.
                return self._unknown(record["requestId"], reused=reused)
        return {**receipt, "reused": reused}

    def invoke(self, subject, capability, request_id, expected_binding=None, expected_scopes=None, add_scopes=None, **extra):
        self._actor(subject, capability)
        self._request_id(request_id)
        try:
            if extra:
                raise ValueError("Unsupported fields")
            expected_binding = _binding(expected_binding)
            previous, additions = _scopes(expected_scopes), _scopes(add_scopes)
            if set(previous) & set(additions):
                raise ValueError("Upgrade must add only missing scopes")
        except (ValidationError, ValueError, TypeError):
            _error("INVALID_INPUT", 422)
        try:
            self._grant(subject, capability, expected_binding)
            key = digest([subject, _ACTION, request_id])
            with self.store.lock("requests", key), self.store.lock("subjects", subject):
                grant = self._grant(subject, capability, expected_binding)
                fingerprint = _fingerprint(subject, expected_binding, grant["authority"], previous, additions)
                path = self.store.path("requests", key)
                record = self._read(path)
                if record is not None:
                    if record.get("fingerprint") != fingerprint:
                        _error("IDEMPOTENCY_CONFLICT", 409)
                    return self._recover(subject, grant, key, record, reused=True)
                if key in grant.get("scopeUpgrades", {}):
                    _error()  # Missing intent is corruption, never a new admission.
                if grant["scopes"] != previous:
                    _error("AUTHORIZATION_CONFLICT", 409)
                if len(grant.get("scopeUpgrades", {})) >= _MAX_PROOFS:
                    _error("AUTHORIZATION_UPGRADE_LIMIT", 409)
                record = {"action": _ACTION, "requestId": request_id, "fingerprint": fingerprint,
                          "binding": expected_binding, "authority": grant["authority"],
                          "parameters": {"expected_scopes": previous, "add_scopes": additions}}
                try:
                    self.store.write(path, record)
                except Exception:
                    if self._read(path) == record:
                        return self._unknown(request_id, reused=False)
                    _error("AUTHORIZATION_UNAVAILABLE", 503)
                authorization = {"subjectId": subject, "previousScopes": previous, "addedScopes": additions,
                                 "scopes": sorted(set(previous) | set(additions)), "grantRevision": grant.get("grantRevision", 0) + 1}
                updated = deepcopy(grant)
                updated["scopes"], updated["grantRevision"] = authorization["scopes"], authorization["grantRevision"]
                updated.setdefault("scopeUpgrades", {})[key] = {
                    "requestId": request_id, "fingerprint": fingerprint, "binding": expected_binding,
                    "authority": grant["authority"], "authorization": authorization}
                try:
                    self.store.write(self.store.path("subjects", subject), updated)
                except Exception:
                    return self._unknown(request_id, reused=False)
                return self._recover(subject, self._grant(subject, capability, expected_binding), key, record, reused=False)
        except ManagementError:
            raise
        except Exception:
            _error("AUTHORIZATION_UNAVAILABLE", 503)

    def receipt(self, subject, capability, request_id):
        self._actor(subject, capability)
        self._request_id(request_id)
        try:
            self._grant(subject, capability)
            key = digest([subject, _ACTION, request_id])
            with self.store.lock("requests", key), self.store.lock("subjects", subject):
                grant = self._grant(subject, capability)
                record = self._read(self.store.path("requests", key))
                if record is None:
                    _error("REQUEST_UNAVAILABLE", 404)
                return self._recover(subject, grant, key, record, reused=True)
        except ManagementError:
            raise
        except Exception:
            _error("AUTHORIZATION_UNAVAILABLE", 503)

    def current_subject(self, subject, capability):
        self._actor(subject, capability)
        try:
            with self.store.lock("subjects", subject):
                grant = self._grant(subject, capability)
                return {"subjectId": subject, "binding": deepcopy(grant["binding"]),
                        "scopes": list(grant["scopes"]), "grantRevision": grant.get("grantRevision", 0)}
        except ManagementError:
            raise
        except Exception:
            _error("AUTHORIZATION_UNAVAILABLE", 503)
