"""Read-only local request references; target receipts remain authoritative."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.web.services.external_management.contracts import ACTION_MODELS

from .dispatch import DispatchError


_ManagementAction = Literal[tuple(["", *ACTION_MODELS])]


class ManagementRequestQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    project_id: str | None = Field(default=None, min_length=1, max_length=160,
                                   pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    action: _ManagementAction = ""
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=20)


class _RequestReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    projectId: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    action: str
    requestId: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def reference_page(rows, *, field, offset, limit, project=lambda row: row, **metadata):
    """Keep every reference reachable inside the native tool-result budget."""
    page = {field: [], "total": len(rows), "offset": offset, "limit": 0, "nextOffset": None, **metadata}
    for row in rows[offset:offset + limit]:
        selected = [*page[field], project(row)]
        end = offset + len(selected)
        candidate = {**page, field: selected, "limit": len(selected),
                     "nextOffset": end if end < len(rows) else None}
        wrapped = {"source": "launcher-assistant", "untrustedContent": True, **candidate}
        if len(json.dumps(wrapped, ensure_ascii=False)) > 3400:
            if not page[field]:
                raise ValueError("引用条目超过单页读取预算，请保留原引用查询")
            break
        page = candidate
    return page


def list_requests(adapter, *, project_id=None, action="", offset=0, limit=10):
    """Discover only recorded identities, without reading or resuming targets."""
    try:
        query = ManagementRequestQuery.model_validate({"project_id": project_id, "action": action,
                                                       "offset": offset, "limit": limit})
    except ValidationError:
        raise DispatchError("Invalid management directory query.", code="INVALID_MANAGEMENT_REQUEST") from None
    projects = dict(adapter._projects)
    if query.project_id is not None and query.project_id not in projects:
        raise DispatchError("Project is not authorized.", code="PROJECT_NOT_AUTHORIZED")
    rows = []
    legacy = invalid = 0
    try:
        paths = sorted(adapter._root.glob("*.json"))
    except OSError:
        raise DispatchError("Management directory is unavailable.", code="MANAGEMENT_DIRECTORY_UNAVAILABLE") from None
    for path in paths:
        try:
            record = adapter._read(path)
            if "reference" not in record:
                legacy += 1
                continue
            ref = _RequestReference.model_validate(record["reference"])
            if ref.action not in ACTION_MODELS:
                raise ValueError("Unknown management action")
            # Never expose refs for a revoked registration. Unknown legacy
            # records cannot be classified by project/action without guessing.
            if ref.projectId not in projects:
                continue
            key = adapter._key(ref.projectId, ref.action, ref.requestId)
            if path.stem != key:
                raise ValueError("Management reference binding changed")
        except (DispatchError, ValueError, TypeError):
            invalid += 1
            continue
        if ((query.project_id is None or query.project_id == ref.projectId)
                and (not query.action or query.action == ref.action)):
            rows.append(ref.model_dump())
    # Registry suspension/revocation during the scan must not leak old refs.
    if dict(adapter._projects) != projects:
        raise DispatchError("Project authorization changed during the directory read.",
                            code="PROJECT_REGISTRY_RECONCILE_REQUIRED")
    rows.sort(key=lambda row: (row["projectId"], row["action"], row["requestId"]))
    return reference_page(rows, field="requests", offset=query.offset, limit=query.limit,
        status="partial" if legacy or invalid else "ok", readOnly=True, untrustedContent=True,
        coverage={"kind": "local_associations", "historyComplete": False,
                  "legacyUnrecoverable": legacy, "invalidRecords": invalid},
        notice="仅列出本机可恢复的原请求引用；状态和对象请用原 project_id/action/request_id 查询 management_receipt。unknown 不得换 ID 重放。")
