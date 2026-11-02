"""Operator Team lifecycle adapters; native owners retain all side effects."""
from __future__ import annotations

from copy import deepcopy

from core.chat.chat_task_types import trim_lines
from core.web.services.team.kind_helpers import team_is_system_managed
from core.web.services.team.team_crud import TeamStateConflictError, team_record_fingerprint

from .asset_contracts import TeamAssetQuery
from .asset_control import AssetControl, _error, _validate
from .state_snapshot import ExistingStateSnapshot
from .store import digest
from .team_lifecycle_contracts import (TEAM_ARCHIVE_EFFECTS, TeamArchive, TeamArchivePreviewResponse,
    TeamCreate, TeamMemberAdd, TeamMemberRemove)


class TeamLifecycleControl(AssetControl):
    @staticmethod
    def _result(action, row):
        return {"action": action, "resourceId": row["teamId"],
                "fingerprint": team_record_fingerprint(row), "verified": True, "untrustedContent": True}

    @staticmethod
    def _archive_eligible(owner, row):
        # Preview uses the raw native record and pure classification only.
        # get_team() may repair/hydrate both Team and Agent state.
        if (row.get("status", owner.DEFAULT_TEAM_STATUS) != "active" or team_is_system_managed(row)
                or str(row.get("teamKind") or owner._infer_team_kind(row)) not in {"custom", "template_demo", "ephemeral"}):
            raise _error("TEAM_LOCKED")

    def read_archive_preview(self, team_id):
        args = _validate(TeamAssetQuery, {"team_id": team_id})
        owner = self._team_owner()
        with owner._TEAM_LOCK:
            row = self._team_snapshot(owner, args.team_id)
            self._archive_eligible(owner, row)
            return _validate(TeamArchivePreviewResponse, {"teamId": args.team_id,
                "fingerprint": team_record_fingerprint(row),
                "memberAgentIds": [member["agentId"] for member in row["members"]],
                "linkedChatRoomId": row.get("linkedChatRoomId", ""),
                "effects": list(TEAM_ARCHIVE_EFFECTS)}).model_dump()

    @staticmethod
    def _create_source(marker):
        if marker is None:
            # Direct no-marker calls exist only for isolated native adapter tests.
            return "operator_team_test"
        if (not isinstance(marker, dict) or marker.get("subjectType") != "operator"
                or any(not isinstance(marker.get(key), str) or not marker[key]
                       for key in ("subjectId", "requestKey"))):
            raise _error("INVALID_INPUT", 422)
        return "operator_team_" + digest([marker["subjectType"], marker["subjectId"], marker["requestKey"]])

    def create_team(self, parameters, marker=None):
        args = _validate(TeamCreate, parameters)
        owner = self._team_owner()
        source = self._create_source(marker)
        name = trim_lines(args.name, max_lines=1).strip()
        if not name:
            raise _error("INVALID_INPUT", 422)
        try:
            with owner._TEAM_LOCK:
                members = owner._normalize_members([member.model_dump() for member in args.members], require_active=True)
                owner._ensure_members_can_join_team(members, owner._load_index(), "")
        except owner.TeamLockedError:
            raise _error("TEAM_LOCKED") from None
        except owner.TeamServiceError:
            raise _error("INVALID_INPUT", 422) from None
        try:
            created = owner.create_team(name=args.name, description=args.description, purpose=args.purpose,
                members=[member.model_dump() for member in args.members], team_kind="custom", team_source=source)
            team_id = _validate(TeamAssetQuery, {"team_id": created["teamId"]}).team_id
            with owner._TEAM_LOCK:
                after = self._team_snapshot(owner, team_id)
                if (after.get("name") != name or after.get("members") != members
                        or after.get("description") != trim_lines(args.description, max_lines=8).strip()
                        or after.get("purpose") != trim_lines(args.purpose, max_lines=4).strip()
                        or after.get("teamKind") != "custom" or after.get("teamSource") != source
                        or after.get("status") != "active"):
                    raise ValueError("Native Team creation could not be verified")
        except Exception:
            # Native index creation precedes canvas, room and Session follow-up.
            raise _error("OPERATION_UNCONFIRMED", 503) from None
        return self._acknowledge("team_create", parameters, marker, self._result("team_create", after))

    def add_member(self, parameters, marker=None):
        return self._change_member("team_member_add", _validate(TeamMemberAdd, parameters), parameters, marker)

    def remove_member(self, parameters, marker=None):
        return self._change_member("team_member_remove", _validate(TeamMemberRemove, parameters), parameters, marker)

    def _change_member(self, action, args, parameters, marker):
        from core.web.services.team import team_admission
        from core.web.services.team.team_crud import _reject_locked_team_update
        owner = self._team_owner()
        try:
            with owner._TEAM_LOCK:
                before = self._team_snapshot(owner, args.team_id)
                if team_record_fingerprint(before) != args.expected_team_fingerprint:
                    raise _error("STATE_CONFLICT")
                _reject_locked_team_update(before)
                team_admission.assert_roster_mutation_allowed(args.team_id)
                members = deepcopy(before["members"])
                ids = {member["agentId"] for member in members}
                if action == "team_member_add":
                    if args.member.agentId in ids or len(members) >= 120:
                        raise _error("INVALID_INPUT", 422)
                    members.append(args.member.model_dump())
                else:
                    if args.agent_id not in ids:
                        raise _error("INVALID_INPUT", 422)
                    members = [member for member in members if member["agentId"] != args.agent_id]
                normalized = owner._normalize_members(members, require_active=True)
                owner._ensure_members_can_join_team(normalized, owner._load_index(), args.team_id)
        except owner.TeamLockedError:
            raise _error("TEAM_LOCKED") from None
        except owner.TeamServiceError:
            raise _error("INVALID_INPUT", 422) from None
        try:
            # Preserve every untouched raw member row through the native call.
            # Its own CAS and normalizer remain the only roster writer.
            owner.update_team(args.team_id, members=members, expected_fingerprint=args.expected_team_fingerprint)
            with owner._TEAM_LOCK:
                after = self._team_snapshot(owner, args.team_id)
                if after.get("members") != normalized or after.get("status") != "active":
                    raise ValueError("Native Team roster change could not be verified")
        except TeamStateConflictError:
            raise _error("STATE_CONFLICT") from None
        except Exception:
            raise _error("OPERATION_UNCONFIRMED", 503) from None
        return self._acknowledge(action, parameters, marker, self._result(action, after))

    def _verify_archived_members(self, agent_ids):
        if not agent_ids:
            return
        directory = self._owners()
        with directory._STATE_LOCK:
            # Read the original Agent authority once, without directory getters
            # that may hydrate/repair it or native Team reads that retry cascades.
            snapshot = ExistingStateSnapshot(self.native.project_root, directory, pin_workspace=True)
            rows = snapshot.read_json(snapshot.path("agents", "agents.json"), strict=True).get("agents")
            if (not isinstance(rows, list) or len(rows) > 100000 or any(not isinstance(row, dict) for row in rows)
                    or any(not isinstance(row.get("agentId"), str) or not row["agentId"] for row in rows)
                    or len({row["agentId"] for row in rows}) != len(rows)):
                raise ValueError("Native Agent archive authority is unavailable")
            by_id = {row["agentId"]: row for row in rows}
            if any(by_id.get(agent_id, {}).get("status") != "archived" for agent_id in agent_ids):
                raise ValueError("Native Team member archive could not be verified")
            snapshot.verify_workspace()
            self._owners()

    def archive_team(self, parameters, marker=None):
        from core.web.services.team import team_admission
        args = _validate(TeamArchive, parameters)
        owner = self._team_owner()
        try:
            with owner._TEAM_LOCK:
                before = self._team_snapshot(owner, args.team_id)
                if (team_record_fingerprint(before) != args.expected_team_fingerprint
                        or set(member["agentId"] for member in before["members"]) != set(args.expected_member_agent_ids)
                        or before.get("linkedChatRoomId", "") != args.expected_linked_chat_room_id):
                    raise _error("STATE_CONFLICT")
                self._archive_eligible(owner, before)
                team_admission.assert_roster_mutation_allowed(args.team_id)
                team_admission._require_settled_workflows(owner, args.team_id)
                owner._ensure_team_member_agents_can_archive(before, owner._unique_active_member_agent_ids(before))
        except owner.TeamLockedError:
            raise _error("TEAM_LOCKED") from None
        except owner.TeamServiceError:
            raise _error("INVALID_INPUT", 422) from None
        try:
            # Native admission checks this same record under _TEAM_LOCK before
            # reserving the roster or running any Agent/session/room cascade.
            owner.archive_team(args.team_id, expected_fingerprint=args.expected_team_fingerprint)
            with owner._TEAM_LOCK:
                after = self._team_snapshot(owner, args.team_id)
                if after.get("status") != "archived" or after.get("linkedChatRoomId"):
                    raise ValueError("Native Team archive could not be verified")
            # Native bulk archive can classify a late protection change as a
            # skip while finalizing the Team. Every preview-bound member must
            # have reached archived before any causal success acknowledgement.
            self._verify_archived_members(args.expected_member_agent_ids)
        except TeamStateConflictError:
            raise _error("STATE_CONFLICT") from None
        except Exception:
            # The native cascade deliberately preserves earlier successes.
            raise _error("OPERATION_UNCONFIRMED", 503) from None
        return self._acknowledge("team_archive", parameters, marker, self._result("team_archive", after))
