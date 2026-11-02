"""Atomic self-subject reductions in the existing native grant authority.

The transport/native manage adapter must require high-risk approval. This owner
also requires the real server operator and current capability/binding; it never
takes an actor, alternate subject, force or approval flag from parameters.
Scopes, revision and immutable receipt share ONE subject-file atomic replace.
There is no second grant authority or request-file receipt commit.
"""
from __future__ import annotations

from copy import deepcopy
import secrets

from pydantic import ValidationError

from .authorization_reduction_contracts import AUTHORIZATION_REDUCTION_MODELS, AuthorizationReductionResponse, _scopes
from .authorization_upgrade import UpgradeOwner, _binding
from .service import ManagementError
from .store import digest

_MAX_PROOFS = 32
_ACTIONS = frozenset(AUTHORIZATION_REDUCTION_MODELS)


def _error(code="AUTHORIZATION_STATE_INVALID", status=503):
    raise ManagementError(code, status)


def _operator():
    from core.web.services.team_workflow.research_runtime.operator_authorization import current_server_operator
    from core.web.services.team_workflow.research_runtime.operator_permissions import operator_has_privileged_role
    operator = current_server_operator()
    if operator is None or not operator.operator_id or not operator_has_privileged_role(operator.roles):
        _error("OPERATOR_CONTROL_REQUIRED", 403)
    return operator.operator_id


def _fingerprint(subject, action, binding, authority, parameters):
    return digest({"subjectId": subject, "action": action, "binding": binding,
                   "authority": authority, "parameters": parameters})


def _validate_proof(subject, grant, key, proof):
    if (not isinstance(proof, dict) or set(proof) != {"action", "requestId", "fingerprint", "binding", "authority",
            "capabilityHash", "operatorId", "parameters", "receipt"} or proof.get("action") not in _ACTIONS
            or proof.get("binding") != grant["binding"] or proof.get("authority") != grant["authority"]
            or key != digest([subject, proof["action"], proof.get("requestId")])
            or not isinstance(proof["operatorId"], str) or not proof["operatorId"]
            or proof["capabilityHash"] != digest(grant["subject_capability"])):
        raise ValueError("Invalid authorization reduction proof")
    parameters = AUTHORIZATION_REDUCTION_MODELS[proof["action"]].model_validate(proof["parameters"]).model_dump()
    receipt = AuthorizationReductionResponse.model_validate(proof["receipt"])
    if (receipt.status != "completed" or receipt.reused or receipt.action != proof["action"]
            or receipt.requestId != proof["requestId"] or receipt.authorization.subjectId != subject
            or receipt.authorization.previousScopes != parameters["expected_scopes"]
            or receipt.authorization.grantRevision != parameters["expected_grant_revision"] + 1
            or receipt.authorization.removedScopes != parameters.get("remove_scopes", parameters["expected_scopes"])
            or receipt.authorization.grantRevision > grant.get("grantRevision", 0)
            or proof["fingerprint"] != _fingerprint(subject, proof["action"], grant["binding"], grant["authority"], parameters)):
        raise ValueError("Conflicting authorization reduction proof")
    return receipt


def validate_reduction_state(subject, grant):
    """Validate history and current effective state after any native reduction.

    UpgradeOwner calls this after validating its historical upgrade proofs. A
    historical upgrade remains truthful even when a later reduction removed its
    scopes; only the greatest committed revision represents current authority.
    """
    proofs = grant.get("scopeReductions", {})
    revoked = grant.get("revoked", False)
    _scopes(grant.get("scopes"))
    _binding(grant.get("binding"))
    if (grant.get("subject_id") != subject or not isinstance(grant.get("authority"), str) or not grant["authority"]
            or type(grant.get("grantRevision", 0)) is not int or grant.get("grantRevision", 0) < 0
            or type(revoked) is not bool or not isinstance(proofs, dict) or len(proofs) > _MAX_PROOFS
            or "scopeReductions" in grant and not proofs):
        raise ValueError("Invalid reduction authority")
    results, previous_states = {}, {}
    revocations = []
    for key, proof in proofs.items():
        receipt = _validate_proof(subject, grant, key, proof)
        revision = receipt.authorization.grantRevision
        if revision in results:
            raise ValueError("Conflicting reduction revisions")
        results[revision] = receipt.authorization.scopes
        previous_states[revision] = receipt.authorization.previousScopes
        if receipt.action == "authorization_revoke":
            revocations.append((key, proof, receipt.authorization))
    for proof in grant.get("scopeUpgrades", {}).values():
        authorization = proof["authorization"]
        revision = authorization["grantRevision"]
        if revision in results:
            raise ValueError("Conflicting authorization revisions")
        results[revision] = authorization["scopes"]
        previous_states[revision] = authorization["previousScopes"]
    if proofs:
        if (not results or max(results) != grant.get("grantRevision", 0)
                or len(results) != grant["grantRevision"]
                or results[max(results)] != ([] if revoked else grant["scopes"])):
            raise ValueError("Current authorization differs from committed history")
        for revision in sorted(results)[1:]:
            if previous_states[revision] != results[revision - 1]:
                raise ValueError("Authorization history is not a continuous native CAS chain")
    if revoked:
        if len(revocations) != 1:
            raise ValueError("Revoked grant requires its one immutable revoke proof")
        key, proof, authorization = revocations[0]
        expected = {"requestKey": key, "capabilityHash": proof["capabilityHash"], "operatorId": proof["operatorId"]}
        if (grant.get("revocationRecovery") != expected
                or authorization.grantRevision != grant["grantRevision"]
                or grant["scopes"] != authorization.previousScopes):
            raise ValueError("Invalid exact-receipt recovery authority")
    elif revocations or "revocationRecovery" in grant:
        raise ValueError("Active grant cannot contain a revocation recovery identity")


class ReductionOwner:
    def __init__(self, store, authorize_callback, identity_callback):
        self.store, self.authorize, self.identity = store, authorize_callback, identity_callback
        self.upgrades = UpgradeOwner(store, authorize_callback, identity_callback)

    def _read(self, subject):
        try:
            return self.store.read(self.store.path("subjects", subject))
        except (ValueError, TypeError, KeyError):
            _error()

    @staticmethod
    def _unknown(action, request_id, *, reused):
        return AuthorizationReductionResponse(action=action, requestId=request_id, status="unknown",
            verified=False, reused=reused).model_dump(exclude_none=True)

    def _bound_receipt_grant(self, subject, capability):
        """Dedicated recovery identity; never authorizes any business action."""
        grant = self._read(subject)
        if (not grant or grant.get("subject_id") != subject or not isinstance(grant.get("subject_capability"), str)
                or not secrets.compare_digest(digest(grant["subject_capability"]), digest(capability))):
            _error("SUBJECT_DENIED", 403)
        current = self.identity()
        if (grant.get("binding") != _binding(current.binding) or grant.get("authority") != current.signature):
            _error("TARGET_BINDING_CHANGED", 409)
        try:
            # Validate legacy upgrade proofs against a view that cannot treat
            # sealed historical scopes as current business authorization.
            for key, proof in grant.get("scopeUpgrades", {}).items():
                UpgradeOwner._proof(subject, grant, key, proof)
            validate_reduction_state(subject, grant)
        except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
            _error()
        return grant

    def invoke(self, subject, capability, action, request_id, expected_binding=None, **parameters):
        operator_id = _operator()
        UpgradeOwner._actor(subject, capability)
        UpgradeOwner._request_id(request_id)
        if action not in _ACTIONS:
            _error("UNKNOWN_ACTION", 404)
        try:
            expected_binding = _binding(expected_binding)
            parameters = AUTHORIZATION_REDUCTION_MODELS[action].model_validate(parameters).model_dump()
        except (ValidationError, ValueError, TypeError):
            _error("INVALID_INPUT", 422)
        try:
            # Lock order is identical to UpgradeOwner. Both serialize on the
            # same native subject lock and atomically write the same record.
            self.upgrades._grant(subject, capability, expected_binding)
            key = digest([subject, action, request_id])
            with self.store.lock("requests", key), self.store.lock("subjects", subject):
                grant = self.upgrades._grant(subject, capability, expected_binding)
                fingerprint = _fingerprint(subject, action, expected_binding, grant["authority"], parameters)
                proofs = grant.get("scopeReductions", {})
                if key in proofs:
                    if proofs[key]["fingerprint"] != fingerprint:
                        _error("IDEMPOTENCY_CONFLICT", 409)
                    return {**proofs[key]["receipt"], "reused": True}
                if (grant["scopes"] != parameters["expected_scopes"]
                        or grant.get("grantRevision", 0) != parameters["expected_grant_revision"]):
                    _error("AUTHORIZATION_CONFLICT", 409)
                if len(proofs) >= _MAX_PROOFS:
                    _error("AUTHORIZATION_REDUCTION_LIMIT", 409)
                revoke = action == "authorization_revoke"
                removed = parameters.get("remove_scopes", parameters["expected_scopes"])
                remaining = sorted(set(grant["scopes"]) - set(removed))
                receipt = AuthorizationReductionResponse(action=action, requestId=request_id, status="completed", verified=True,
                    authorization={"subjectId": subject, "previousScopes": grant["scopes"], "removedScopes": removed,
                        "scopes": remaining, "grantRevision": grant.get("grantRevision", 0) + 1, "revoked": revoke}
                    ).model_dump(exclude={"reused"}, exclude_none=True)
                updated = deepcopy(grant)
                updated["grantRevision"] = receipt["authorization"]["grantRevision"]
                updated["revoked"] = revoke
                if not revoke:
                    updated["scopes"] = remaining
                proof = {"action": action, "requestId": request_id, "fingerprint": fingerprint, "binding": expected_binding,
                    "authority": grant["authority"], "operatorId": operator_id, "capabilityHash": digest(capability),
                    "parameters": parameters, "receipt": receipt}
                updated.setdefault("scopeReductions", {})[key] = proof
                if revoke:
                    updated["revocationRecovery"] = {"requestKey": key, "capabilityHash": digest(capability), "operatorId": operator_id}
                validate_reduction_state(subject, updated)
                try:
                    self.store.write(self.store.path("subjects", subject), updated)
                except Exception:
                    # A replace may commit before its acknowledgement fails.
                    # Never infer completion from scopes or perform a second
                    # write: only this request's atomic proof can establish it.
                    try:
                        persisted = self._bound_receipt_grant(subject, capability)
                    except Exception:
                        return self._unknown(action, request_id, reused=False)
                    if persisted == grant:
                        _error("AUTHORIZATION_UNAVAILABLE", 503)
                    stored = persisted.get("scopeReductions", {}).get(key)
                    if stored != proof:
                        return self._unknown(action, request_id, reused=False)
                    return {**stored["receipt"], "reused": False}
                try:
                    persisted = self._bound_receipt_grant(subject, capability)
                except Exception:
                    return self._unknown(action, request_id, reused=False)
                if persisted.get("scopeReductions", {}).get(key) != proof:
                    return self._unknown(action, request_id, reused=False)
                return {**persisted["scopeReductions"][key]["receipt"], "reused": False}
        except ManagementError:
            raise
        except Exception:
            _error("AUTHORIZATION_UNAVAILABLE", 503)

    def receipt(self, subject, capability, action, request_id):
        operator_id = _operator()
        UpgradeOwner._actor(subject, capability)
        UpgradeOwner._request_id(request_id)
        if action not in _ACTIONS:
            _error("UNKNOWN_ACTION", 404)
        try:
            key = digest([subject, action, request_id])
            with self.store.lock("requests", key), self.store.lock("subjects", subject):
                grant = self._bound_receipt_grant(subject, capability)
                if grant.get("revoked", False):
                    recovery = grant["revocationRecovery"]
                    if (action != "authorization_revoke" or key != recovery["requestKey"]
                            or operator_id != recovery["operatorId"]
                            or not secrets.compare_digest(digest(capability), recovery["capabilityHash"])):
                        _error("SUBJECT_DENIED", 403)
                else:
                    self.upgrades._grant(subject, capability)
                record = grant.get("scopeReductions", {}).get(key)
                if record is None:
                    _error("REQUEST_UNAVAILABLE", 404)
                return {**record["receipt"], "reused": True}
        except ManagementError:
            raise
        except Exception:
            _error("AUTHORIZATION_UNAVAILABLE", 503)
