"""Private native acknowledgements, never another runtime state machine.

Only a completed, closed native response is recorded. An absent record cannot
prove a mutation did not happen. Reads never create a directory, lock or file.
The gateway must explicitly supply this owner; test fakes cannot discover a
product data path merely by possessing a project_root attribute.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.assistant_runtime.migration_io import check_path, read_stable_file, strict_json, validate_path

from .store import Store, digest

_HASH = r"^[a-f0-9]{64}$"
ReconciliationState = Literal["confirmed", "requires_review", "unavailable"]
ReconciliationEvidence = Literal["native_outcome", "research_ledger", "flow_start_identity", "none"]
ReconciliationCode = Literal["NATIVE_OUTCOME_CONFIRMED", "NATIVE_OUTCOME_REQUIRES_REVIEW", "NATIVE_OUTCOME_UNAVAILABLE"]


class NativeOutcomeUnavailable(ValueError):
    pass


class _Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schemaVersion: Literal[1]
    projectRoot: str = Field(min_length=1, max_length=4096)
    subjectType: Literal["operator"]
    subjectId: str = Field(pattern=r"^ops-[a-f0-9]{32}$")
    action: str = Field(pattern=r"^[a-z][a-z_]{0,79}$")
    requestKey: str = Field(pattern=_HASH)
    requestFingerprint: str = Field(pattern=_HASH)
    parametersFingerprint: str = Field(pattern=_HASH)
    resultFingerprint: str = Field(pattern=_HASH)
    result: dict


def _binding(project_root, action, parameters, marker):
    from .platform_actions import PLATFORM_ACTIONS
    if (action not in PLATFORM_ACTIONS or not isinstance(marker, dict)
            or set(marker) != {"subjectType", "subjectId", "requestKey", "requestFingerprint"}
            or marker.get("requestFingerprint") != digest(parameters)):
        raise NativeOutcomeUnavailable("native outcome binding unavailable")
    binding = {"projectRoot": str(Path(project_root).resolve()).casefold(), "action": action,
               **marker, "parametersFingerprint": digest(parameters)}
    # Validate marker grammar before it is used to select any persistent file.
    _Outcome.model_validate({"schemaVersion": 1, **binding, "resultFingerprint": "0" * 64, "result": {}})
    return binding


def _closed(action, parameters, marker, raw):
    from .platform_actions import native_result, verify_target
    result = native_result(action, raw)
    verify_target(action, result, parameters, marker)
    return result


class NativeOutcomeStore:
    def __init__(self, root, *, project_root):
        self.root = validate_path(Path(root).absolute())
        self.project_root = Path(project_root).resolve()
        self.store = Store(self.root)

    def _path(self, binding):
        key = digest([binding["projectRoot"], binding["subjectId"], binding["action"], binding["requestKey"]])
        return self.store.path("acknowledgements", key)

    @staticmethod
    def _check(path):
        path = validate_path(path)
        while True:
            try:
                path.lstat()
                break
            except FileNotFoundError:
                path = path.parent
        check_path(path)

    def read(self, action, parameters, marker):
        binding = _binding(self.project_root, action, parameters, marker)
        path = self._path(binding)
        self._check(path)
        try:
            path.lstat()
        except FileNotFoundError:
            return None
        raw = strict_json(read_stable_file(path, 64 * 1024).raw)
        record = _Outcome.model_validate(raw).model_dump()
        if any(record[key] != value for key, value in binding.items()):
            raise NativeOutcomeUnavailable("native outcome binding changed")
        result = _closed(action, parameters, marker, record["result"])
        if result != record["result"] or digest(result) != record["resultFingerprint"]:
            raise NativeOutcomeUnavailable("native outcome acknowledgement changed")
        return result

    def write(self, action, parameters, marker, raw):
        binding = _binding(self.project_root, action, parameters, marker)
        result = _closed(action, parameters, marker, raw)
        path = self._path(binding)
        self._check(path)
        record = _Outcome.model_validate({"schemaVersion": 1, **binding,
            "resultFingerprint": digest(result), "result": result}).model_dump()
        with self.store.lock("acknowledgements", path.stem):
            self._check(path)
            existing = self.read(action, parameters, marker)
            if existing is not None:
                if existing != result:
                    raise NativeOutcomeUnavailable("native outcome cannot be overwritten")
                return existing
            self.store.write(path, record)
        return result


def owner(native):
    factory = getattr(native, "operation_receipts", None)
    if factory is None:
        return None
    if not callable(factory):
        raise NativeOutcomeUnavailable("native outcome owner unavailable")
    result = factory()
    if not isinstance(result, NativeOutcomeStore) or result.project_root != Path(native.project_root).resolve():
        raise NativeOutcomeUnavailable("native outcome owner changed")
    return result


def record_success(native, action, parameters, marker, raw):
    """Native adapter boundary: validate and durably acknowledge before return."""
    from .service import ManagementError
    try:
        result = _closed(action, parameters, marker, raw)
        target = owner(native)
        return target.write(action, parameters, marker, result) if target is not None else result
    except Exception:
        # The native mutation already returned; a receipt failure is unknown,
        # never a safe no-write rejection or permission to run it again.
        raise ManagementError("OPERATION_UNCONFIRMED", 503) from None
