"""Closed assistant workspace actions over native Session/Team/room services.

The public wrapper owns canonical assistant identity and native approval. This
adapter additionally binds its caller to the current runtime, never selects an
operator session, and projects only public metadata from native readbacks.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SessionId(Arguments):
    session_id: str = Field(min_length=1, max_length=160, pattern=r"^\S+$")


class ReasoningUpdate(SessionId):
    reasoning_effort: str = Field(min_length=1, max_length=40, pattern=r"^\S+$")


class ModelParametersUpdate(SessionId):
    expected_agent_id: str = Field(min_length=1, max_length=160, pattern=r"^\S+$")
    expected_model_ref: str = Field(min_length=1, max_length=300, pattern=r"^\S+$")
    expected_config_revision: int = Field(ge=0)
    context_window: int | None = Field(default=None, gt=0)
    reasoning_effort: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def nonempty(self):
        edits = self.model_fields_set & {"context_window", "reasoning_effort"}
        if not edits or any(getattr(self, key) is None for key in edits):
            raise ValueError("A non-null parameter update is required.")
        return self


class BudgetUpdate(SessionId):
    revision: int = Field(ge=0)
    max_calls_per_turn: int | None = Field(ge=0, le=200)


class TeamId(Arguments):
    team_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class TeamUpdate(TeamId):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    purpose: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def nonempty(self):
        edits = self.model_fields_set & {"name", "description", "purpose"}
        if not edits or any(getattr(self, key) is None for key in edits):
            raise ValueError("A non-null metadata update is required.")
        if "name" in edits and not self.name.strip():
            raise ValueError("A name is required.")
        return self


class RoomId(Arguments):
    room_id: str = Field(min_length=1, max_length=160, pattern=r"^\S+$")


class RoomUpdate(RoomId):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    purpose: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def nonempty(self):
        edits = self.model_fields_set & {"title", "purpose"}
        if not edits or any(getattr(self, key) is None or not getattr(self, key).strip() for key in edits):
            raise ValueError("A nonempty metadata update is required.")
        return self


class WorkspaceList(Arguments):
    kind: Literal["sessions", "teams", "rooms"]
    limit: int = Field(default=20, ge=1, le=30)
    cursor: str = Field(default="", max_length=200)
    archived: bool = False


_CONTRACTS = {
    "workspace_list": (WorkspaceList, False, "分页读取会话、团队或房间的公开名称和标识；archived=true 查看会话归档或包含已归档团队。无正文搜索。", [("GET", "/api/sessions"), ("GET", "/api/session-archive"), ("GET", "/api/teams"), ("GET", "/api/chat-rooms")]),
    "session_get": (SessionId, False, "读取会话公开标识、标题、置顶、运行及归档状态，不返回会话正文。", [("GET", "/api/sessions/{session_id}")]),
    "session_parameters_get": (SessionId, False, "读取会话当前模型标识、参数及 revision；更新前先取得原生条件。", [("GET", "/api/sessions/{session_id}/llm-options"), ("GET", "/api/sessions/{session_id}/budget-parameters")]),
    "session_pin": (SessionId, True, "置顶指定的非个人助理会话；不改变操作者当前选择。", [("POST", "/api/sessions/{session_id}/pin")]),
    "session_unpin": (SessionId, True, "取消指定的非个人助理会话置顶。", [("POST", "/api/sessions/{session_id}/unpin")]),
    "session_reasoning_update": (ReasoningUpdate, True, "修改绑定 Agent 后续轮次的推理强度；先读取支持选项和完整模型参数，保留 Agent/modelRef/revision 条件经原生模型参数 CAS 更新，不改变已受理轮次。", [("PATCH", "/api/sessions/{session_id}/model-parameters")]),
    "session_model_parameters_update": (ModelParametersUpdate, True, "修改现有模型的上下文或推理强度；保留 Agent、modelRef、revision 条件。省略字段从完整原生参数读回合并；影响绑定 Agent 的后续轮次。", [("PATCH", "/api/sessions/{session_id}/model-parameters")]),
    "session_budget_update": (BudgetUpdate, True, "按 revision 修改后续轮次工具调用预算；null 清除覆盖，0 表示无限，最多200。影响绑定 Agent。", [("PATCH", "/api/sessions/{session_id}/budget-parameters")]),
    "session_archive": (SessionId, True, "可逆归档空闲会话并清除置顶；不删除正文，不改变操作者当前选择。", [("POST", "/api/sessions/{session_id}/archive")]),
    "session_unarchive": (SessionId, True, "恢复用户手动归档的会话；保留原只读状态，不解除 Agent 归档封存，置顶不恢复。", [("POST", "/api/sessions/{session_id}/unarchive")]),
    "team_get": (TeamId, False, "读取团队名称、状态、目的和成员 Agent 标识，不返回成员内容或路径。", [("GET", "/api/teams/{team_id}")]),
    "team_update": (TeamUpdate, True, "仅修改团队 name、description、purpose；禁止成员、权限、状态和生命周期字段。", [("PATCH", "/api/teams/{team_id}")]),
    "team_archive": (TeamId, True, "归档已收口团队，级联归档成员 Agent 及其会话并删除关联房间。拒绝个人助理成员及未结束、失败或恢复未收口的流程；先停止这些流程。原生 admission 原子保护成员与新流程提交，需要原生审批。", [("DELETE", "/api/teams/{team_id}")]),
    "room_get": (RoomId, False, "只读取房间标识、标题和状态。", [("GET", "/api/chat-rooms/{room_id}")]),
    "room_update": (RoomUpdate, True, "仅修改房间标题或已有 purpose 选项；保留成员、模式、config 和权限，原生服务拒绝忙碌房间。", [("PATCH", "/api/chat-rooms/{room_id}")]),
}


def contracts() -> dict[str, dict[str, Any]]:
    return {name: {"action": name, "description": description, "governed": governed,
                   "parameters": _schema(schema),
                   "apiMethods": [{"method": method, "path": path} for method, path in methods]}
            for name, (schema, governed, description, methods) in _CONTRACTS.items()}


def _schema(model: type[Arguments]) -> dict:
    schema = model.model_json_schema()
    if model in {ModelParametersUpdate, TeamUpdate, RoomUpdate}:
        # Optional patch fields may be omitted, but explicit null is rejected.
        for field in schema["properties"].values():
            choices = field.get("anyOf", [])
            non_null = [choice for choice in choices if choice.get("type") != "null"]
            if choices and len(non_null) == 1:
                field.pop("anyOf")
                field.pop("default", None)
                field.update(non_null[0])
        editable = ({"context_window", "reasoning_effort"} if model is ModelParametersUpdate
                    else {"name", "description", "purpose"} if model is TeamUpdate else {"title", "purpose"})
        schema["anyOf"] = [{"required": [field]} for field in sorted(editable)]
    return schema


def _native():
    from core.web.services import agent_directory_service, chat_room_service, session_archive_service, session_service, team_service
    return agent_directory_service, session_service, session_archive_service, team_service, chat_room_service


def _failure(error: str, *, unknown: bool = False) -> dict:
    return {"ok": False, "status": "unknown" if unknown else "blocked", "error": error,
            "message": "操作未确认；请先读取状态核验，不要自动重复写入。"}


def _text(value: Any, limit: int = 160) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _session_public(row: dict) -> dict:
    archive = row.get("archiveState") or row.get("archive_state") or {}
    return {"id": _text(row.get("id") or row.get("sessionId")), "title": _text(row.get("title")),
            "agentId": _text(row.get("agentId") or row.get("agent_id")),
            "pinned": row.get("pinned") is True or bool(row.get("pinnedAtMs")),
            "status": _text(row.get("phase") or row.get("status"), 32),
            "archived": row.get("archived") is True or (isinstance(archive, dict) and archive.get("status") == "archived")}


def _team_public(row: dict) -> dict:
    return {"id": _text(row.get("teamId")), "name": _text(row.get("name")),
            "status": _text(row.get("status"), 32), "purpose": _text(row.get("purpose"), 1000),
            "members": [_text(member.get("agentId")) for member in row.get("members", []) if isinstance(member, dict) and member.get("agentId")]}


def _room_public(row: dict) -> dict:
    return {"id": _text(row.get("roomId")), "title": _text(row.get("title")), "status": _text(row.get("status"), 32)}


def _read_session(session_id: str, sessions) -> dict:
    # Read directory metadata directly: no transcript hydration or operator
    # selection. The archive authority is the native conversation metadata.
    from core.web.services.session import directory_runtime
    store = directory_runtime.get_open_directory_store()
    if store is None:
        raise LookupError("directory_unavailable")
    row = store.repository.get_session(session_id, include_archived=True)
    if not isinstance(row, dict):
        raise LookupError("not_found")
    with sessions._CHAT_STATE_LOCK:
        conversation = sessions.load_session_chat_state(sessions.PROJECT_ROOT, session_id) or {}
        archive = conversation.get("archive_state") or conversation.get("archiveState") or {}
    runtime_state = store.repository.get_session_runtime_state(session_id) or {}
    live_status = sessions._active_session_work_run_statuses([session_id]).get(session_id)
    return {**row, "id": session_id, "archiveState": archive,
            "phase": live_status or runtime_state.get("last_turn_status") or runtime_state.get("lastTurnStatus") or row.get("status", "")}


def _is_assistant(agent_id: str, directory, runtime: dict) -> bool:
    if agent_id == runtime["agentId"]:
        return True
    agent = directory.get_agent(agent_id, include_archived=True) if agent_id else None
    return bool(agent and (agent.get("roleKey") == "personal_assistant" or
                          (agent.get("metadata") or {}).get("personalAssistantProfile")))


def _llm_public(row: dict) -> dict:
    return {"sessionId": _text(row.get("sessionId")), "agentId": _text(row.get("agentId")),
            "modelRef": _text(row.get("currentModelId"), 300), "configRevision": _integer(row.get("configRevision")),
            "contextWindow": _integer(row.get("contextWindow")), "maxContextWindow": _integer(row.get("maxContextWindow")),
            "reasoningEffort": _text(row.get("currentReasoningEffort"), 40),
            "reasoningEffortValues": _effort_values(row)}


def _effort_values(row: dict) -> list[str]:
    model = row.get("model")
    values = model.get("reasoningEffortValues") if isinstance(model, dict) else None
    if not isinstance(values, (list, tuple)):
        return []
    return list(dict.fromkeys(value for value in values if isinstance(value, str)
                             and 0 < len(value) <= 40 and value.isascii()
                             and all(character.isalnum() or character in "_-" for character in value)))[:20]


def _integer(value: Any) -> int | None:
    return value if type(value) is int else None


def _budget_public(row: dict) -> dict:
    return {key: _integer(row.get(key)) for key in ("revision", "maxCallsPerTurn")}


def _workspace_list(args: WorkspaceList, sessions, archives, teams, rooms) -> dict:
    if args.kind == "sessions":
        page = (archives.list_archived_sessions(limit=args.limit, cursor=args.cursor) if args.archived
                else sessions.query_sessions(limit=args.limit, cursor=args.cursor))
        items = [_session_public(row) for row in page["items"]]
        if args.archived:
            for row in items:
                row["archived"] = True
        return {"ok": True, "items": items, "nextCursor": _text(page.get("nextCursor", ""), 200),
                "totalEstimate": _integer(page.get("totalEstimate")), "kind": args.kind}
    if args.cursor and (not args.cursor.isascii() or not args.cursor.isdigit() or len(args.cursor) > 6):
        return _failure("invalid_cursor")
    offset = int(args.cursor or "0")
    if args.kind == "teams":
        rows = teams.list_teams_compact(include_archived=args.archived)["teams"]
        project = _team_public
    else:
        if args.archived:
            return _failure("unsupported_filter")
        rows = rooms.list_chat_rooms_compact()
        project = _room_public
    end = offset + args.limit
    return {"ok": True, "kind": args.kind, "items": [project(row) for row in rows[offset:end]],
            "nextCursor": str(end) if end < len(rows) else "", "totalEstimate": len(rows)}


def _team_runs(team_id: str) -> list[dict]:
    from core.web.services.team_workflow.generic import store
    # Never mistake a bounded scan for proof that no older active run exists.
    return store.records(team_id, "runs", limit=201)


def _assert_team_archive_safe(team: dict, directory, sessions, runtime: dict) -> None:
    members = set(_team_public(team)["members"])
    if any(_is_assistant(agent_id, directory, runtime) for agent_id in members):
        raise PermissionError("assistant_protected")
    linked = team.get("linkedChatRoom") or {}
    if team.get("status") in {"running", "waiting", "stopping"} or linked.get("status") in {"running", "stopping"}:
        raise PermissionError("team_busy")
    for run in sessions.list_active_session_work_runs(reconcile=False):
        if run.get("agentId") in members or run.get("teamId") == team["teamId"]:
            raise PermissionError("team_busy")
        # Native active-turn snapshots carry sessionId rather than agentId.
        if run.get("sessionId") and _session_public(_read_session(run["sessionId"], sessions))["agentId"] in members:
            raise PermissionError("team_busy")
    runs = _team_runs(team["teamId"])
    if len(runs) >= 201:
        raise PermissionError("team_activity_check_incomplete")
    if any(run.get("status") not in {"completed", "stopped"}
           or (isinstance(run.get("recovery"), dict) and run["recovery"]
               and run["recovery"].get("status") not in {"resolved", "cancelled"}) for run in runs):
        raise PermissionError("team_busy")


def execute(action: str, parameters: dict, runtime: dict, governed: bool = False) -> dict:
    contract = _CONTRACTS.get(action)
    if contract is None:
        return _failure("unknown_action")
    if contract[1] and governed is not True:
        return _failure("native_approval_required")
    write_started = False
    try:
        args = contract[0].model_validate(parameters)
        directory, sessions, archives, teams, rooms = _native()
        current = directory.current_agent_runtime()
        if any(not isinstance(runtime.get(key), str) or not runtime[key].strip() or
               current.get(key) != runtime[key] for key in ("agentId", "sessionId")):
            return _failure("runtime_identity_mismatch")
        if action == "workspace_list":
            return _workspace_list(args, sessions, archives, teams, rooms)
        if action.startswith("session_"):
            before = _read_session(args.session_id, sessions)
            agent_id = _session_public(before)["agentId"]
            if contract[1] and _is_assistant(agent_id, directory, runtime):
                return _failure("assistant_protected")
            if action == "session_get":
                return {"ok": True, "session": _session_public(before)}
            if action == "session_parameters_get":
                llm = _llm_public(sessions.get_session_llm_options(args.session_id))
                budget = sessions.get_session_budget_parameters_view(args.session_id)
                return {"ok": True, "parameters": llm, "budget": _budget_public(budget)}
            if action in {"session_model_parameters_update", "session_reasoning_update"}:
                view = sessions.get_session_llm_options(args.session_id)
                if action == "session_model_parameters_update" and (view.get("agentId"), view.get("currentModelId"), view.get("configRevision")) != (
                    args.expected_agent_id, args.expected_model_ref, args.expected_config_revision):
                    return _failure("state_conflict")
                if view.get("agentId") != agent_id:
                    return _failure("state_conflict")
                expected_model_ref = view["currentModelId"]
                expected_revision = view["configRevision"]
                changes = {"context_window": args.context_window if action == "session_model_parameters_update" and "context_window" in args.model_fields_set else view["contextWindow"],
                           "reasoning_effort": args.reasoning_effort if "reasoning_effort" in args.model_fields_set else view["currentReasoningEffort"]}
                if changes["reasoning_effort"] and changes["reasoning_effort"] not in _effort_values(view):
                    return _failure("invalid_reasoning_effort")
                write_started = True
                sessions.update_session_model_parameters(args.session_id, expected_agent_id=agent_id,
                    expected_model_ref=expected_model_ref, expected_config_revision=expected_revision, **changes)
            elif action == "session_budget_update":
                write_started = True
                sessions.update_session_budget_parameters(args.session_id, expected_revision=args.revision,
                                                          max_calls_per_turn=args.max_calls_per_turn)
                budget = sessions.get_session_budget_parameters_view(args.session_id)
                if budget.get("maxCallsPerTurn") != args.max_calls_per_turn:
                    return _failure("verification_failed", unknown=True)
                return {"ok": True, "status": "applied", "verified": True, "sessionId": args.session_id,
                        "budget": _budget_public(budget)}
            elif action in {"session_pin", "session_unpin"}:
                from core.web.services.session.session_pin_ops import set_chat_session_pinned
                write_started = True
                set_chat_session_pinned(args.session_id, pinned=action == "session_pin")
            elif action in {"session_archive", "session_unarchive"}:
                write_started = True
                (archives.archive_session if action == "session_archive" else archives.unarchive_session)(args.session_id)
            if action in {"session_reasoning_update", "session_model_parameters_update"}:
                observed = _llm_public(sessions.get_session_llm_options(args.session_id))
                expected_values = {"reasoningEffort": changes["reasoning_effort"],
                                   "contextWindow": changes["context_window"], "modelRef": expected_model_ref}
                if observed["agentId"] != agent_id or any(observed[field] != value for field, value in expected_values.items()):
                    return _failure("verification_failed", unknown=True)
                return {"ok": True, "status": "applied", "verified": True, "parameters": observed}
            observed = _session_public(_read_session(args.session_id, sessions))
            field = "pinned" if action in {"session_pin", "session_unpin"} else "archived"
            expected = action in {"session_pin", "session_archive"}
            if observed[field] != expected:
                return _failure("verification_failed", unknown=True)
            return {"ok": True, "status": "applied", "verified": True, "session": observed}
        if action.startswith("team_"):
            before = teams.get_team_light(args.team_id)
            if action == "team_get":
                return {"ok": True, "team": _team_public(before)}
            if action == "team_archive":
                _assert_team_archive_safe(before, directory, sessions, runtime)
                write_started = True
                teams.archive_team(args.team_id, protected_agent_ids=(runtime["agentId"],))
                expected = {"status": "archived"}
            else:
                expected = {key: getattr(args, key).strip() for key in ("name", "description", "purpose") if key in args.model_fields_set}
                if len(expected.get("description", "").splitlines()) > 8 or len(expected.get("purpose", "").splitlines()) > 4 or len(expected.get("name", "").splitlines()) > 1:
                    return _failure("invalid_input")
                from core.chat.chat_task_types import trim_lines
                expected = {key: trim_lines(value, max_lines={"name": 1, "description": 8, "purpose": 4}[key])
                            for key, value in expected.items()}
                write_started = True
                teams.update_team(args.team_id, **expected)
            observed = teams.get_team_light(args.team_id)
            if any(observed.get(key) != value for key, value in expected.items()):
                return _failure("verification_failed", unknown=True)
            return {"ok": True, "status": "applied", "verified": True, "team": _team_public(observed)}
        before = rooms.get_chat_room_compact(args.room_id)
        if not before:
            return _failure("not_found")
        if action == "room_get":
            return {"ok": True, "room": _room_public(before)}
        changes = {key: getattr(args, key).strip() for key in ("title", "purpose") if key in args.model_fields_set}
        if "purpose" in changes and changes["purpose"] not in {option["id"] for option in rooms.list_chat_room_purposes()}:
            return _failure("invalid_purpose")
        if "title" in changes and len(changes["title"].splitlines()) > 1:
            return _failure("invalid_input")
        write_started = True
        rooms.update_chat_room(args.room_id, **changes)
        observed = rooms.get_chat_room_compact(args.room_id)
        if not observed or any(observed.get(key) != value for key, value in changes.items()):
            return _failure("verification_failed", unknown=True)
        return {"ok": True, "status": "applied", "verified": True, "room": _room_public(observed)}
    except ValidationError:
        return _failure("invalid_input")
    except PermissionError as exc:
        return _failure(str(exc) if str(exc) in {"assistant_protected", "team_busy", "team_activity_check_incomplete"} else "operation_blocked")
    except LookupError:
        return _failure("source_unavailable")
    except Exception as exc:
        name = type(exc).__name__
        if "Conflict" in name or "Stale" in name:
            return _failure("state_conflict")
        if "Busy" in name or "Locked" in name:
            return _failure("object_busy")
        if "NotFound" in name:
            return _failure("not_found")
        if isinstance(exc, ValueError):
            return _failure("native_validation_failed", unknown=write_started)
        return _failure("operation_failed", unknown=write_started)
