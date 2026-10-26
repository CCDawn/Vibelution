"""Existing archive authorities only; never seed, reconcile or repair a read."""
from __future__ import annotations

import json
from pathlib import Path

from config.public_config import read_existing_config_snapshot
from core.infrastructure.developer_sandbox import existing_sandboxed_workspace_path


class ArchiveState:
    def __init__(self, project_root, directory):
        self.project_root = project_root
        self.directory = directory
        self.config = read_existing_config_snapshot(Path(directory.CONFIG_PATH))

    def path(self, *parts):
        return existing_sandboxed_workspace_path(self.project_root, *parts, public_config=self.config)

    @staticmethod
    def read_json(path):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Ambiguous archive authority")
                result[key] = value
            return result
        before = path.stat()
        with path.open("rb") as stream:
            raw = stream.read(32 * 1024 * 1024 + 1)
        after = path.stat()
        stamp = lambda info: (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if len(raw) > 32 * 1024 * 1024 or stamp(before) != stamp(after):
            raise ValueError("Archive authority unavailable")
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique)
        if not isinstance(payload, dict):
            raise ValueError("Invalid archive authority")
        return payload

    def agent(self, agent_id):
        rows = self.read_json(self.path("agents", "agents.json")).get("agents")
        if not isinstance(rows, list) or len(rows) > 100_000 or any(not isinstance(row, dict) for row in rows):
            raise ValueError("Invalid Agent authority")
        matches = [row for row in rows if row.get("agentId") == agent_id]
        if len(matches) > 1:
            raise ValueError("Ambiguous Agent identity")
        return matches[0] if matches else None

    def team_member_ids(self):
        from core.web.services.team import team_projection, team_store
        service = team_store._service()
        if Path(service.PROJECT_ROOT).resolve() != self.project_root or service._project_root().resolve() != self.project_root:
            raise ValueError("Team authority binding changed")
        with service._TEAM_LOCK:
            teams = self.read_json(self.path("teams", "teams.json")).get("teams")
        if not isinstance(teams, list) or len(teams) > 100_000 or any(not isinstance(team, dict) for team in teams):
            raise ValueError("Invalid Team authority")
        result = set()
        for team in teams:
            members = team.get("members")
            if (not isinstance(members, list) or len(members) > 120
                or any(not isinstance(member, dict) or "agent_id" in member
                    or not isinstance(member.get("agentId"), str) or not member["agentId"].strip() for member in members)):
                raise ValueError("Invalid Team roster")
            projected = team_projection._members_to_api(members)
            if len(projected) != len(members):
                raise ValueError("Invalid Team roster projection")
            result.update(member["agentId"] for member in projected)
        return result

    def binding(self, agent_id):
        from core.agent_plugins.virtual_human_life.storage import VirtualHumanLifeStore
        store = VirtualHumanLifeStore(self.project_root, plugin_root_resolver=lambda owner:
            self.path("agents", owner, "plugins", "virtual-human-life"))
        return store.read_json(agent_id, "binding.json")
