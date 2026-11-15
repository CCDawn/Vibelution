"""One approved enrollment when both records of a prior subject are gone."""
import secrets
import stat

from pydantic import Field, field_validator

from core.assistant_runtime.migration_io import check_path
from core.infrastructure.file_lock import lock_path_for

from .contracts import Binding, Closed, SCOPES, Scope
from .store import digest


class RecoveryIdentity(Closed):
    client_id: str = Field(pattern=r"^[A-Za-z0-9_-]{20,128}$")
    subject_id: str = Field(pattern=r"^ops-[0-9a-f]{32}$")
    expected_binding: Binding


class RecoverSubject(RecoveryIdentity):
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
    scopes: list[Scope] = Field(min_length=1, max_length=len(SCOPES))

    @field_validator("scopes")
    @classmethod
    def ordered(cls, scopes):
        if sorted(set(scopes)) != scopes:
            raise ValueError("Scopes must be unique and sorted")
        return scopes


def recovery_key(binding: dict, client_id: str, subject_id: str) -> str:
    return digest(["management-recovery", binding, client_id, subject_id])


def _read_record(store, path):
    check_path(path, missing_ok=True)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(mode):
        raise ValueError("Unverified management record")
    record = store.read(path)
    if record is None:
        raise ValueError("Management record changed under lock")
    return record


def recover(service, request: RecoveryIdentity, *, launcher_capability: str):
    from .service import ManagementError

    binding = request.expected_binding.model_dump()
    key = recovery_key(binding, request.client_id, request.subject_id)
    new_client = "recovered-" + key
    new_subject = "ops-" + key[:32]
    store = service.store
    old_subject_path = store.path("subjects", request.subject_id)
    old_index_path = store.path("clients", request.client_id)
    for record in (old_subject_path, old_index_path):
        check_path(lock_path_for(record.with_suffix(".lock")), missing_ok=True)
    with store.lock("clients", request.client_id), store.lock("subjects", request.subject_id):
        service._expected(binding)
        old_subject = _read_record(store, old_subject_path)
        if old_subject and old_subject.get("revoked") is True:
            raise ManagementError("SUBJECT_REVOKED")
        if old_subject is not None or _read_record(store, old_index_path) is not None:
            raise ManagementError("ORIGINAL_GRANT_PRESENT", 409)
        path = store.path("subjects", new_subject)
        index_path = store.path("clients", new_client)
        if not isinstance(request, RecoverSubject):
            return {"available": _read_record(store, path) is None and _read_record(store, index_path) is None}
        for record in (path, index_path):
            check_path(lock_path_for(record.with_suffix(".lock")), missing_ok=True)
            check_path(lock_path_for(record), missing_ok=True)
        with store.lock("clients", new_client), store.lock("subjects", new_subject):
            current = service._expected(binding)
            fingerprint = digest([current.signature, request.model_dump(), launcher_capability])
            previous = _read_record(store, path)
            actual = _read_record(store, index_path)
            expected_index = {"subject_id": new_subject}
            if actual is not None and (actual != expected_index or previous is None):
                raise ManagementError("RECOVERY_CONFLICT", 409)
            if previous is None:
                previous = {"subject_id": new_subject, "subject_capability": secrets.token_urlsafe(48),
                            "binding": current.binding, "authority": current.signature,
                            "scopes": request.scopes, "recoveryFingerprint": fingerprint}
                # The native subject is also the durable recovery receipt.
                store.write(path, previous)
            elif (previous.get("recoveryFingerprint") != fingerprint or previous.get("revoked")
                    or previous.get("subject_id") != new_subject or previous.get("binding") != current.binding
                    or previous.get("authority") != current.signature
                    or previous.get("scopes") != request.scopes or previous.get("grantRevision", 0) != 0):
                raise ManagementError("RECOVERY_CONFLICT", 409)
            if actual is None:
                store.write(index_path, expected_index)
            return {"protocolVersion": 1, "client_id": new_client, **{
                k: previous[k] for k in ("subject_id", "subject_capability", "binding", "scopes")
            }}
