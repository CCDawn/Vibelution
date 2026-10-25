"""Reproject the registered OpenAPI owner as neutral, untrusted documentation."""
from __future__ import annotations

import json
import threading
from copy import deepcopy

from .contracts import DOCUMENTATION_ACTIONS, DocumentationEntry, DocumentationResponse

_SPEC_LOCK = threading.Lock()
_SPEC_APP = None


def _get_spec() -> dict:
    """Compile the actual route registry once, without any native startup owner."""
    global _SPEC_APP
    with _SPEC_LOCK:
        if _SPEC_APP is None:
            from fastapi import FastAPI

            from core.web.router_registry import register_web_routers
            # Do not import the workbench app or invoke its lifespan/bootstrap:
            # native get_spec() also creates bundled Agents and direct Sessions.
            app = FastAPI(title="Vibelution registered API documentation", docs_url=None, redoc_url=None, openapi_url=None)
            register_web_routers(app)
            app.openapi()
            _SPEC_APP = app
        return _SPEC_APP.openapi()


def _native_entry(method, path, operation):
    from core.web.services.personal_assistant_platform_api.catalog import (
        _catalog_identity_entry,
    )
    return _entry(_catalog_identity_entry(method, path, operation))


def _entry(raw: dict) -> dict:
    # Positive fields remove legacy PA tool advertisements, permissions,
    # execution arguments and read-gateway paths without rewriting OpenAPI.
    result = {key: deepcopy(raw[key]) for key in ("operationId", "method", "path", "summary", "tags")}
    action = DOCUMENTATION_ACTIONS.get((result["method"], result["path"]))
    result.update(access="operator_only", executable=False)
    if action:
        result.update(access="native_action", executable=True, action=action, capabilitySubset=True,
                      argumentHelp={"action": "describe", "parameters": {"action": action}})
    return DocumentationEntry.model_validate(result).model_dump(exclude_none=True)


def _project(raw: dict) -> dict:
    from core.web.services.personal_assistant_platform_api import catalog

    from .service import ManagementError
    allowed = DocumentationResponse.model_fields
    result = {key: deepcopy(value) for key, value in raw.items() if key in allowed and key not in {"operation", "operations"}}
    if "operations" in raw:
        result["operations"] = [_entry(row) for row in raw["operations"]]
    if "operation" in raw:
        result["operation"] = _entry(raw["operation"])
    result["untrustedContent"] = True
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > catalog.MAX_DESCRIPTION_CHARS:
        raise ManagementError("DOCUMENTATION_TOO_LARGE", 503)
    return DocumentationResponse.model_validate(result).model_dump(exclude_none=True)


def api_catalog(**parameters):
    from core.web.services.personal_assistant_platform_api.catalog import (
        api_catalog as native_catalog,
    )
    return _project(native_catalog(**parameters, spec=_get_spec(), entry_projector=_native_entry))


def api_describe(operation_id):
    from core.web.services.personal_assistant_platform_api.catalog import (
        api_describe as native_describe,
    )
    return _project(native_describe(operation_id, spec=_get_spec(), entry_projector=_native_entry))
