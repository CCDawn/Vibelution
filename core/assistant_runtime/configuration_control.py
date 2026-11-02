"""Launcher-only configuration mutations under native registry/reference leases."""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from . import configuration_protocol as protocol
from . import configuration_contexts as contexts


class ReferenceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["model", "provider"]
    reference: str = Field(min_length=1, max_length=320)


def available():
    from core.infrastructure.native_runtime import is_launcher_assistant_process
    from .actions import _binding
    return bool(is_launcher_assistant_process() and _binding is not None
                and getattr(_binding[2], "configuration_enabled", False))


class NativeRegistryLease:
    def __init__(self, broker, loop, runtime):
        self.broker, self.loop, self.runtime = broker, loop, runtime
        self.context_id = "cfg-" + uuid4().hex
        self.inventory = None
        self.closed = False
        self.entered = False

    def _send(self, action):
        request = {"contextId": self.context_id}
        if action != "configuration_reference_acquire":
            request.update(leaseId=self.inventory["leaseId"], snapshotDigest=self.inventory["snapshotDigest"])
        value = asyncio.run_coroutine_threadsafe(self.broker.invoke(action, request,
            turn_id=self.runtime["turnId"]), self.loop).result(timeout=25)
        return protocol.validate_result(action, request, value)

    def __enter__(self):
        from .configuration_references import ConfigurationReferenceError
        if self.entered:
            raise ConfigurationReferenceError("REFERENCE_REGISTRY_CONTEXT_REUSED")
        try:
            contexts.register(self.broker, self.context_id)
        except (ValueError, RuntimeError):
            raise ConfigurationReferenceError("REFERENCE_REGISTRY_LEASE_UNAVAILABLE") from None
        self.entered = True
        try:
            self.inventory = self._send("configuration_reference_acquire")
            if self.inventory.get("complete") is not True:
                # Only explicit busy means this context owned no admission.
                # Unavailable also represents a lost ACK and stays pinned.
                self.closed = self.inventory.get("code") == "busy"
                raise ConfigurationReferenceError("REFERENCE_REGISTRY_LEASE_UNAVAILABLE")
            from core.infrastructure.native_runtime import assistant_native_root
            if Path(self.inventory["nativeAssistantRoot"]).resolve() != assistant_native_root():
                self.close()
                raise ConfigurationReferenceError("REFERENCE_REGISTRY_IDENTITY_CHANGED")
            return self
        except BaseException:
            contexts.complete(self.broker, self.context_id, released=self.closed)
            raise

    def assert_current(self):
        from .configuration_references import ConfigurationReferenceError
        if (self.closed or not contexts.owned(self.broker, self.context_id)
                or not self.inventory or self.inventory.get("complete") is not True):
            raise ConfigurationReferenceError("REFERENCE_REGISTRY_LEASE_UNAVAILABLE")
        value = self._send("configuration_reference_validate")
        if value.get("valid") is not True or value["revision"] != self.inventory["revision"]:
            raise ConfigurationReferenceError("REFERENCE_REGISTRY_LEASE_UNAVAILABLE")

    def close(self):
        from .configuration_references import ConfigurationReferenceError
        from core.infrastructure.model_reference_fence import model_reference_fence_owned
        if not contexts.owned(self.broker, self.context_id) or model_reference_fence_owned():
            raise ConfigurationReferenceError("REFERENCE_REGISTRY_SCOPE_STILL_ACTIVE")
        if self.closed or not self.inventory or self.inventory.get("complete") is not True:
            return
        for _ in range(2):
            try:
                value = self._send("configuration_reference_release")
                if value.get("released") is True:
                    self.closed = True
                    return
            except (ValueError, RuntimeError, TimeoutError):
                continue
        raise ConfigurationReferenceError("REFERENCE_REGISTRY_RELEASE_UNCONFIRMED")

    def __exit__(self, *_):
        try:
            self.close()
        finally:
            contexts.complete(self.broker, self.context_id, released=self.closed)


def _lease(runtime):
    from .actions import _binding
    from .configuration_references import ConfigurationReferenceError
    if (not available() or not isinstance(runtime, dict)
            or any(not isinstance(runtime.get(k), str) or not runtime[k] for k in ("agentId", "sessionId", "turnId"))):
        raise ConfigurationReferenceError("REFERENCE_REGISTRY_LEASE_UNAVAILABLE")
    return NativeRegistryLease(_binding[2], _binding[1], runtime)


def inspect(parameters, runtime):
    from .configuration_references import ConfigurationReferenceGuard, ConfigurationReferenceError
    query = ReferenceQuery.model_validate(parameters)
    try:
        with _lease(runtime) as lease:
            proof = ConfigurationReferenceGuard(lambda: lease.inventory).scan(query.kind, query.reference)
            lease.assert_current()
            return {"ok": True, "status": "observed", **proof.summary()}
    except ConfigurationReferenceError as exc:
        return {"ok": False, "status": "unavailable", "error": exc.code,
            "message": "跨项目引用权威暂不可用，不能把未知视为零引用。"}


def mutate(action, parameters, runtime, *, governed):
    from .configuration_references import ConfigurationReferenceGuard, ConfigurationReferenceError
    if governed is not True:
        return {"ok": False, "status": "approval_required", "action": action, "tool": "personal_assistant_manage_tool"}
    kind = "provider" if action.startswith("provider_") else "model"
    reference = parameters.get("provider_id" if kind == "provider" else "model_id")
    try:
        with _lease(runtime) as lease:
            guard = ConfigurationReferenceGuard(lambda: lease.inventory)
            with guard.zero_references(kind, reference, registry_lease=lease) as permit:
                from tools import pa_platform_actions
                result = pa_platform_actions.execute_extension(action, parameters, runtime, governed=True)
                if result.get("verified") is True and result.get("resultHash"):
                    permit.confirm_commit_hash(result["resultHash"])
                return result
    except ConfigurationReferenceError as exc:
        proof = getattr(exc, "proof", None)
        return {"ok": False, "status": "unknown" if "UNCONFIRMED" in exc.code or "STATE_CHANGED" in exc.code else "unavailable",
            "action": action, "error": exc.code,
            "message": "模型配置操作未获完整确认；请读取现有配置和引用状态，不重复未知操作。",
            **({"referenceCheck": proof.summary()} if proof is not None else {})}
