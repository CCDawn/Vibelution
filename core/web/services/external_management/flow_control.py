"""Bounded definitions and thin writes to the original native Flow owner."""
from __future__ import annotations

import json
import re
from itertools import islice
from pathlib import Path

from pydantic import ValidationError

from core.assistant_runtime.migration_io import check_path
from core.infrastructure.tool_result import project_tool_result_for_model
from core.web.services.team_workflow.generic import service as workflows, store
from core.web.services.team_workflow.generic.models import Flow, SaveFlow, StartRun

from .flow_contracts import (FlowListQuery, FlowListResponse, FlowMutationResponse,
                             FlowReadQuery, FlowReadResponse, FlowSave, FlowStart, FlowSummary)
from .service import ManagementError
from .state_snapshot import ExistingStateSnapshot
from .store import digest

_MAX_FILES = 10000
_MAX_BYTES = 16 * 1024 * 1024
_MAX_FILE = 2 * 1024 * 1024
_BUDGET = 3400


def _request(model, value):
    try:
        return value if type(value) is model else model.model_validate(value)
    except (ValidationError, TypeError, ValueError):
        raise ManagementError("INVALID_INPUT", 422) from None


def _clean(value):
    return json.loads(project_tool_result_for_model(json.dumps({"value": value}, ensure_ascii=False)))["value"]


def _stable(value):
    try:
        value.encode("utf-8")
        return _clean(value) == value
    except UnicodeError:
        return False


def _size(value):
    # Reserve the complete wrapper including the longest registered project ID.
    return len(json.dumps({"source": "launcher-assistant", **value, "projectId": "p" * 160}, ensure_ascii=False))


def _kind(value):
    return ("object" if isinstance(value, dict) else "array" if isinstance(value, list)
            else "string" if isinstance(value, str) else "boolean" if isinstance(value, bool)
            else "null" if value is None else "number")


def _pointer_node(document, pointer):
    value = document
    for token in pointer.split("/")[1:] if pointer else ():
        key = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", key) and int(key) < len(value):
            value = value[int(key)]
        else:
            raise ManagementError("FLOW_NODE_UNAVAILABLE", 404)
    return value


def _node_page(flow, query):
    fingerprint = digest(flow)
    if query.expected_digest is not None and query.expected_digest != fingerprint:
        raise ManagementError("FLOW_CHANGED", 409)
    if not _stable(query.pointer):
        raise ManagementError("FLOW_POINTER_UNREPRESENTABLE", 422)
    value = _pointer_node(flow, query.pointer)
    kind = _kind(value)
    response = FlowReadResponse(teamId=query.team_id, flowId=query.flow_id, revision=flow["revision"],
        digest=fingerprint, pointer=query.pointer, nodeType=kind, offset=query.offset,
        limit=0, total=0, nextOffset=None).model_dump()
    if kind in {"object", "array"}:
        children = sorted(value.items()) if kind == "object" else list(enumerate(value))
        response["total"] = len(children)
        for key, child in children[query.offset:query.offset + query.limit]:
            pointer = query.pointer + "/" + str(key).replace("~", "~0").replace("/", "~1")
            if len(pointer) > 1024 or not _stable(pointer):
                raise ManagementError("FLOW_POINTER_UNREPRESENTABLE", 422)
            child_kind = _kind(child)
            node = {"pointer": pointer, "kind": child_kind, "childCount": None,
                    "value": None, "textFiltered": False}
            if child_kind in {"object", "array"}:
                node["childCount"] = len(child)
            elif child_kind == "string":
                clean = _clean(child)
                node["textFiltered"] = clean != child
                if len(clean) <= 128 and _stable(clean):
                    node["value"] = clean
                else:
                    node["childCount"] = len(clean)
            else:
                node["value"] = child
            candidate = {**response, "items": [*response["items"], node], "limit": response["limit"] + 1,
                         "textFiltered": response["textFiltered"] or node["textFiltered"]}
            end = query.offset + candidate["limit"]
            candidate["nextOffset"] = end if end < len(children) else None
            if _size(candidate) > _BUDGET:
                break
            response = candidate
    elif kind == "string":
        clean = _clean(value)
        response.update(total=len(clean), textFiltered=clean != value)
        count = min(query.limit, max(0, len(clean) - query.offset))
        while True:
            span = clean[query.offset:query.offset + count]
            text = _clean(span)
            candidate = {**response, "value": text, "limit": count,
                         "textFiltered": response["textFiltered"] or text != span,
                         "nextOffset": query.offset + count if query.offset + count < len(clean) else None}
            if _size(candidate) <= _BUDGET and _stable(text):
                response = candidate
                break
            if count == 0:
                raise ManagementError("FLOW_NODE_TOO_LARGE", 422)
            count -= 1
    else:
        response["total"] = 1
        if query.offset == 0:
            response.update(value=value, limit=1)
    if (_size(response) > _BUDGET or query.offset < response["total"] and response["limit"] == 0):
        raise ManagementError("FLOW_NODE_TOO_LARGE", 422)
    return FlowReadResponse.model_validate(response).model_dump()


class FlowControl:
    def __init__(self, native):
        self.native = native

    def _context(self, team_id):
        from core.web.services import team_service
        directory = self.native._owners()
        if (Path(team_service.PROJECT_ROOT).resolve() != self.native.project_root
                or team_service._project_root().resolve() != self.native.project_root):
            raise ManagementError("TARGET_BINDING_CHANGED", 409)
        snapshot = ExistingStateSnapshot(self.native.project_root, directory, pin_workspace=True)
        teams_root = snapshot.path("teams")
        index = snapshot.read_json(snapshot.path("teams", "teams.json"), strict=True)
        rows = index.get("teams")
        if (not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("teamId"), str) for row in rows)
            or len({row["teamId"] for row in rows}) != len(rows)):
            raise ManagementError("FLOW_UNAVAILABLE", 404)
        roster = next((row for row in rows if row["teamId"] == team_id), None)
        if roster is None:
            raise ManagementError("FLOW_UNAVAILABLE", 404)
        snapshot.verify_workspace()
        folder = teams_root / team_id / "generic-workflows"
        nearest = folder
        while not nearest.exists():
            nearest = nearest.parent
        check_path(nearest)
        if folder.resolve() != folder or folder.exists() and not folder.is_dir():
            raise ManagementError("TARGET_BINDING_CHANGED", 409)
        return snapshot, digest(roster), folder

    def _verify(self, team_id, context):
        snapshot, roster, folder = context
        snapshot.verify_workspace()
        current = self._context(team_id)
        if current[1:] != (roster, folder):
            raise ManagementError("TARGET_BINDING_CHANGED", 409)

    @staticmethod
    def _flow(folder, flow_id):
        path = folder / "flows" / (flow_id + ".json")
        check_path(path)
        raw = ExistingStateSnapshot.read_json(path, strict=True, max_bytes=_MAX_FILE)
        flow = Flow.model_validate(raw).model_dump()
        if flow["id"] != flow_id or type(raw.get("revision")) is not int or flow["revision"] < 1:
            raise ValueError("Flow identity changed")
        return flow

    def read_flow(self, query):
        query = _request(FlowReadQuery, query)
        try:
            context = self._context(query.team_id)
            flow = self._flow(context[2], query.flow_id)
            result = _node_page(flow, query)
            self._verify(query.team_id, context)
            return result
        except ManagementError:
            raise
        except (OSError, ValueError, TypeError):
            raise ManagementError("FLOW_UNAVAILABLE", 404) from None

    def list_flows(self, query):
        query = _request(FlowListQuery, query)
        try:
            context = self._context(query.team_id)
            folder = context[2] / "flows"
            if folder.exists():
                check_path(folder)
                if not folder.is_dir():
                    raise ValueError("Flow namespace unavailable")
            paths = sorted(islice(folder.glob("*.json"), _MAX_FILES + 1))
            rows, remaining, unavailable = [], _MAX_BYTES, 0
            truncated = len(paths) > _MAX_FILES
            before = [(p.name, ExistingStateSnapshot._path_token(p)) for p in paths]
            for path in paths[:_MAX_FILES]:
                try:
                    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", path.stem):
                        raise ValueError("Invalid Flow identity")
                    row = {"flowId": path.stem, "available": False}
                    size = path.stat().st_size
                    if size > _MAX_FILE:
                        # One oversized/corrupt definition must not hide later
                        # IDs; no body bytes are read for this placeholder.
                        unavailable += 1
                        rows.append(row)
                        continue
                    if size > remaining:
                        truncated = True
                        unavailable += 1
                        rows.append(row)
                        continue
                    remaining -= size
                    try:
                        flow = self._flow(context[2], path.stem)
                        row.update(available=True, name=_clean(flow["name"]), revision=flow["revision"],
                                   fieldCount=len(flow["fields"]), stepCount=len(flow["steps"]))
                    except (OSError, ValueError, TypeError):
                        unavailable += 1
                    rows.append(row)
                except (OSError, ValueError, TypeError):
                    unavailable += 1
            after_paths = sorted(islice(folder.glob("*.json"), _MAX_FILES + 1))
            if before != [(p.name, ExistingStateSnapshot._path_token(p)) for p in after_paths]:
                raise ManagementError("FLOW_DIRECTORY_CHANGED", 409)
            self._verify(query.team_id, context)
            fingerprint = digest([rows, truncated, unavailable])
            if query.expected_digest is not None and query.expected_digest != fingerprint:
                raise ManagementError("FLOW_DIRECTORY_CHANGED", 409)
            response = FlowListResponse(teamId=query.team_id, flows=[], digest=fingerprint,
                offset=query.offset, limit=0, total=len(rows), nextOffset=None,
                complete=not truncated and not unavailable, truncated=truncated,
                unavailableCount=unavailable).model_dump()
            for row in rows[query.offset:query.offset + query.limit]:
                candidate = {**response, "flows": [*response["flows"], row],
                    "limit": response["limit"] + 1,
                    "nextOffset": query.offset + response["limit"] + 1
                    if query.offset + response["limit"] + 1 < len(rows) else None}
                # Defaults in each closed summary are part of the real wire
                # size; normalize them before accepting a candidate page.
                candidate["flows"] = [FlowSummary.model_validate(item).model_dump() for item in candidate["flows"]]
                if _size(candidate) > _BUDGET:
                    break
                response = candidate
            if query.offset < len(rows) and response["limit"] == 0:
                raise ManagementError("FLOW_NODE_TOO_LARGE", 422)
            return FlowListResponse.model_validate(response).model_dump()
        except ManagementError:
            raise
        except (OSError, ValueError, TypeError):
            raise ManagementError("FLOW_DIRECTORY_UNAVAILABLE", 503) from None

    @staticmethod
    def _operator():
        from core.web.services.team_workflow.research_runtime.operator_authorization import require_server_operator
        try:
            require_server_operator()
        except PermissionError:
            raise ManagementError("OPERATOR_REQUIRED", 403) from None

    def save_flow(self, parameters):
        request = _request(FlowSave, parameters)
        self._operator()
        try:
            context = self._context(request.team_id)
            target = store.path(request.team_id, "flows", request.flow_id)
            expected = context[2] / "flows" / (request.flow_id + ".json")
            nearest = expected.parent
            while not nearest.exists():
                nearest = nearest.parent
            check_path(nearest)
            if target != expected:
                raise ManagementError("TARGET_BINDING_CHANGED", 409)
            with store.locked(target):
                previous = self._flow(context[2], request.flow_id) if target.exists() else None
                store.check_revision(previous or {"revision": 0}, request.expectedRevision)
                requested = request.flow.model_dump()
                if requested.get("failureRecovery") != (previous or {}).get("failureRecovery"):
                    raise ManagementError("FLOW_RECOVERY_AUTHORIZATION_REQUIRED", 403)
                for step in requested["steps"]:
                    if workflows.executable(step):
                        workflows.native.validate_owner(request.team_id, step["owner"])
                from core.web.services.team import team_admission
                with team_admission.workflow_commit_admission(request.team_id):
                    self._verify(request.team_id, context)
                    result = workflows.save_flow(request.team_id, request.flow_id,
                        SaveFlow(flow=request.flow, expectedRevision=request.expectedRevision).model_dump())
                    actual = self._flow(context[2], request.flow_id)
                    if (actual != result or actual["revision"] != request.expectedRevision + 1
                            or {k: v for k, v in actual.items() if k not in {"revision", "updatedAt"}}
                            != {k: v for k, v in requested.items() if k not in {"revision", "updatedAt"}}):
                        raise ManagementError("FLOW_SAVE_UNCONFIRMED", 409)
                    try:
                        self._verify(request.team_id, context)
                    except ManagementError:
                        raise ManagementError("FLOW_SAVE_UNCONFIRMED", 409) from None
            return FlowMutationResponse(action="flow_save", teamId=request.team_id, flowId=request.flow_id,
                revision=actual["revision"], status="saved", verified=True).model_dump()
        except ManagementError:
            raise
        except store.Conflict:
            raise ManagementError("STATE_CONFLICT", 409) from None
        except (OSError, ValueError, TypeError):
            raise ManagementError("FLOW_SAVE_UNCONFIRMED", 409) from None

    def start_flow(self, parameters, *, request_id):
        request = _request(FlowStart, parameters)
        self._operator()
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}", request_id):
            raise ManagementError("INVALID_INPUT", 422)
        try:
            context = self._context(request.team_id)
            flow = self._flow(context[2], request.flow_id)
            key = "ops-flow-" + digest([str(self.native.project_root), "flow_start", request_id])
            payload = StartRun(values=request.values, expectedRevision=request.expectedRevision,
                               idempotencyKey=key).model_dump(exclude_none=True)
            self._verify(request.team_id, context)
            result = workflows.start_run(request.team_id, request.flow_id, payload)
            expected_run = "run-" + workflows.digest([request.flow_id, key])[:40]
            frozen = Flow.model_validate(result.get("flow")).model_dump()
            if (result.get("id") != expected_run or result.get("teamId") != request.team_id
                    or frozen["id"] != request.flow_id or frozen["revision"] != request.expectedRevision
                    or result.get("values") != request.values
                    or flow["revision"] == request.expectedRevision and frozen != flow):
                raise ManagementError("FLOW_START_UNCONFIRMED", 409)
            try:
                self._verify(request.team_id, context)
            except ManagementError:
                raise ManagementError("FLOW_START_UNCONFIRMED", 409) from None
            return FlowMutationResponse(action="flow_start", teamId=request.team_id, flowId=request.flow_id,
                runId=expected_run, revision=result["revision"], status=result["status"], verified=True).model_dump()
        except ManagementError:
            raise
        except store.Conflict:
            raise ManagementError("STATE_CONFLICT", 409) from None
        except (OSError, ValueError, TypeError):
            raise ManagementError("FLOW_START_UNCONFIRMED", 409) from None
