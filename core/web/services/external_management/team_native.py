"""Read-only Team materialization proof and the single native template entrypoint."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .native import NativeAgentGateway
from .store import digest


class NativeTeamGateway:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.agents = NativeAgentGateway(self.project_root)

    def _owners(self):
        from core.web.services import (
            chat_room_service,
            session_service,
            team_service,
            team_template_service,
        )

        from .service import ManagementError
        self.agents._owners()
        if any(Path(service.PROJECT_ROOT).resolve() != self.project_root
               for service in (chat_room_service, session_service, team_service, team_template_service)):
            raise ManagementError("TARGET_BINDING_CHANGED", 409)
        return team_template_service, session_service, team_service, chat_room_service

    def recipe_fingerprint(self, template_id):
        templates, sessions, _, _ = self._owners()
        return digest([templates.get_team_template(template_id), sessions.default_session_llm_bindings()])

    def materialize(self, parameters, marker):
        templates, _, _, _ = self._owners()
        templates.instantiate_team_template(parameters["template_id"], name=parameters["name"].strip(),
            team_source=marker["teamSource"], instantiation_marker=marker)

    def owns(self, team_id, marker):
        from core.web.services.team_workflow.generic import store
        self._owners()
        team = store.team(team_id)
        return team.get("teamSource") == marker["teamSource"] and team.get("status") != "archived"

    def recover(self, marker, recipe_fingerprint):
        from core.web.services.agent_config_authority import (
            canonical_agent_config_payload,
        )
        from core.web.services.team import team_store
        from core.web.services.team_workflow import one_shot

        from .service import _subset
        templates, sessions, teams, rooms = self._owners()
        if self.recipe_fingerprint("dev-team") != recipe_fingerprint:
            return None
        template = templates.get_team_template("dev-team")
        # Canonical index read only: CRUD getters can reconcile room/canvas state.
        with teams._TEAM_LOCK:
            matches = [deepcopy(item) for item in team_store._load_index().get("teams", [])
                       if item.get("teamSource") == marker["teamSource"]]
        if len(matches) != 1:
            return None
        team = matches[0]
        if team.get("status") == "archived" or team.get("teamTemplateId") != "dev-team":
            return None
        directory = self.agents._owners()
        with directory._STATE_LOCK:
            rows = directory.load_state().get("agents", [])
            if not isinstance(rows, list) or len(rows) > 100_000:
                return None
            actors = [deepcopy(row) for row in rows if isinstance(row, dict) and row.get("agentId")
                      and _subset(marker, (row.get("metadata") or {}).get("teamTemplateInstantiation"))]
        if len(actors) != len(one_shot._ROLES):
            return None
        # Public Agent views can hide unavailable tool names. Recovery compares
        # the persisted configuration to the compiled snapshot, not that UI view.
        ids = {actor["agentId"] for actor in actors}
        by_role = {(actor.get("metadata") or {}).get("teamTemplateRole"): actor for actor in actors if actor}
        if set(by_role) != {role for role, _, _ in one_shot._ROLES}:
            return None
        if {item.get("agentId") for item in team.get("members", []) if item.get("status") != "archived"} != set(ids):
            return None
        ordered = []
        for role in template["roles"]:
            raw = by_role[role["roleKey"]]
            config = canonical_agent_config_payload(raw)
            actor = {**raw, **config}
            expected = {"roleKey": role["roleKey"], "personaProfile": role["personaProfile"], "taskProfile": role["taskProfile"],
                        "llmBindings": sessions.default_session_llm_bindings(), "toolPolicy": templates._role_tool_policy(role),
                        "permissionPreset": role.get("permissionPreset") or "request_approval"}
            actor_marker = (actor.get("metadata") or {}).get("teamTemplateInstantiation")
            if (actor.get("status") != "active" or not actor.get("directSessionId")
                or actor_marker != {**marker, "roleKey": role["roleKey"]} or not _subset(expected, actor)):
                return None
            compiled = self.agents.compiled(actor["agentId"], actor["directSessionId"])
            # The config snapshot, not registry metadata, proves the admitted permissions/profiles.
            # Native compilation applies delegation restrictions (e.g. hides
            # list_child_sessions_tool when subagents are disabled). Reuse that
            # exact owner function; never accept arbitrary policy subsets.
            effective_config = {**config, "toolPolicy": directory._effective_agent_tool_policy(config["toolPolicy"], config["delegationPolicy"])}
            if not _subset(effective_config, compiled):
                return None
            ordered.append(actor)
        room = [item for item in rooms.read_chat_rooms_snapshot() if item.get("roomId") == team.get("linkedChatRoomId")]
        if len(room) != 1 or not _subset({"mode": template["chatRoom"]["mode"], "purpose": template["chatRoom"]["purpose"],
            # Native canvas save reasserts roster-managed room source="team";
            # the request owner remains canonical Team.teamSource + role markers.
            "config": {"source": "team", "teamId": team["teamId"], "teamTemplateId": "dev-team",
                       **template["chatRoom"].get("config", {})}}, room[0]):
            return None
        canvas = team_store._read_json(team_store._team_canvas_path(team["teamId"]))
        expected_canvas = templates._template_canvas(template, team["teamId"], ordered, team["members"])
        actor_map = {actor["agentId"]: actor for actor in ordered}
        expected_canvas = teams._normalize_canvas(expected_canvas, team, agents_by_id=actor_map, active_agents_by_id=actor_map)
        if not _subset({key: value for key, value in expected_canvas.items() if key != "updatedAt"}, canvas):
            return None
        return {"team": team, "createdAgents": ordered}
