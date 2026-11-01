"""Operator asset adapters; native owners retain all writes and policy gates."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from pydantic import ValidationError

from core.web.services.team.team_crud import team_record_fingerprint as _fingerprint

from .asset_contracts import (AssetMutationResponse, KnowledgeACLMutation, KnowledgeACLQuery,
    KnowledgeACLResponse, TeamAssetQuery, TeamAssetResponse, TeamUpdate, ToolPolicyPatch,
    ToolPolicyQuery, ToolPolicyResponse, ToolPolicyUpdate)
from .state_snapshot import ExistingStateSnapshot


def _error(code, status=409):
    from .service import ManagementError
    return ManagementError(code, status)


def _validate(model, value):
    try:
        return model.model_validate(value)
    except ValidationError:
        raise _error("INVALID_INPUT", 422) from None


class AssetControl:
    def __init__(self, native):
        self.native = native

    def _owners(self):
        from core.web.services.team_workflow.research_runtime.operator_authorization import current_server_operator
        from core.web.services.team_workflow.research_runtime.operator_permissions import operator_has_privileged_role
        operator = current_server_operator()
        if operator is None or not operator.operator_id or not operator_has_privileged_role(operator.roles):
            raise _error("OPERATOR_CONTROL_REQUIRED", 403)
        return self.native._owners()

    def _team_owner(self):
        from core.web.services import team_service
        self._owners()
        if Path(team_service.PROJECT_ROOT).resolve() != self.native.project_root:
            raise _error("TARGET_BINDING_CHANGED")
        return team_service

    def _team_snapshot(self, owner, team_id):
        try:
            snapshot = ExistingStateSnapshot(self.native.project_root, self._owners(), pin_workspace=True)
            state = snapshot.read_json(snapshot.path("teams", "teams.json"), strict=True)
            rows = state.get("teams")
            if (not isinstance(rows, list) or len(rows) > 100000 or any(not isinstance(row, dict) for row in rows)
                    or any(not isinstance(row.get("teamId"), str) or not row["teamId"] for row in rows)
                    or len({row["teamId"] for row in rows}) != len(rows)):
                raise ValueError("Invalid existing Team authority")
            row = next((row for row in rows if row["teamId"] == team_id), None)
            snapshot.verify_workspace()
            if row is None:
                raise _error("TEAM_UNAVAILABLE", 404)
            members = row.get("members")
            if (not isinstance(members, list) or len(members) > 120
                    or any(not isinstance(member, dict) or not isinstance(member.get("agentId"), str) for member in members)
                    or len({member["agentId"] for member in members}) != len(members)):
                raise ValueError("Invalid existing Team roster")
            return deepcopy(row)
        except (OSError, ValueError, TypeError):
            raise _error("TEAM_UNAVAILABLE", 503) from None

    def _team_view(self, row):
        member_fields = {"memberId", "agentId", "role", "purpose", "responsibilities"}
        return _validate(TeamAssetResponse, {"teamId": row["teamId"],
            **{key: row.get(key, "") for key in ("name", "description", "purpose", "status", "updatedAt")},
            "members": [{key: value for key, value in member.items() if key in member_fields}
                        for member in row.get("members", [])], "fingerprint": _fingerprint(row)}).model_dump()

    def read_team(self, team_id):
        from .service import ManagementError
        query = _validate(TeamAssetQuery, {"team_id": team_id})
        owner = self._team_owner()
        try:
            with owner._TEAM_LOCK:
                return self._team_view(self._team_snapshot(owner, query.team_id))
        except ManagementError as exc:
            if exc.code == "INVALID_INPUT":
                raise _error("TEAM_UNAVAILABLE", 503) from None
            raise

    def update_team(self, parameters, marker=None):
        from core.web.services.team import team_admission
        from core.web.services.team.team_crud import TeamStateConflictError, _reject_locked_team_update
        args = _validate(TeamUpdate, parameters)
        owner = self._team_owner()
        try:
            with owner._TEAM_LOCK:
                before = self._team_snapshot(owner, args.team_id)
                if _fingerprint(before) != args.expected_team_fingerprint:
                    raise _error("STATE_CONFLICT")
                _reject_locked_team_update(before)
                if args.updates.members is not None:
                    team_admission.assert_roster_mutation_allowed(args.team_id)
                    members = owner._normalize_members(
                        [row.model_dump() for row in args.updates.members], require_active=True)
                    owner._ensure_members_can_join_team(members, owner._load_index(), args.team_id)
        except owner.TeamLockedError:
            raise _error("TEAM_LOCKED") from None
        except owner.TeamServiceError:
            raise _error("INVALID_INPUT", 422) from None
        try:
            # CAS belongs to the native initial metadata commit. Keep its
            # existing lock boundaries during linked Session/canvas follow-up.
            owner.update_team(args.team_id, expected_fingerprint=args.expected_team_fingerprint,
                              **args.updates.model_dump(exclude_unset=True))
            with owner._TEAM_LOCK:
                after = self._team_snapshot(owner, args.team_id)
        except TeamStateConflictError:
            raise _error("STATE_CONFLICT") from None
        except Exception:
            # The roster may already be durable when linked room/session or
            # canvas follow-up fails. Never label that a no-write rejection.
            raise _error("OPERATION_UNCONFIRMED") from None
        return AssetMutationResponse(action="team_update", resourceId=args.team_id,
            fingerprint=_fingerprint(after), verified=True).model_dump()

    def _policy_snapshot(self, directory, agent_id):
        from core.web.services import tool_policy_configuration_service as policies
        from core.web.services.agent_config_authority import canonical_agent_config_payload
        try:
            snapshot = ExistingStateSnapshot(self.native.project_root, directory, pin_workspace=True)
            _state, rows = policies._existing_agents(snapshot)
            current = next((row for row in rows if row["agentId"] == agent_id), None)
            self.native._editable(current)
            detail = policies.get_tool_policy_configuration(agent_id, declared_policy=True, existing_snapshot=snapshot)
            store = self.native._control_store()
            compiled = store.repository.get_current_agent_config(agent_id) if store is not None else None
            compiled_policy = compiled.get("config", {}).get("toolPolicy") if compiled else None
            declared = canonical_agent_config_payload(current)["toolPolicy"]
            matches = isinstance(compiled_policy, dict) and compiled_policy == declared
            snapshot.verify_workspace()
            return current, detail, store, compiled, matches
        except (OSError, ValueError, TypeError):
            raise _error("TOOL_POLICY_UNAVAILABLE", 503) from None

    def _policy_view(self, current, detail, matches):
        policy = {key: deepcopy(value) for key, value in detail["currentPolicy"].items()
                  if key in ToolPolicyPatch.model_fields}
        if "perToolRules" in policy:
            policy["perToolRules"] = {name: {"approval": rule["approval"]}
                for name, rule in policy["perToolRules"].items()
                if isinstance(rule, dict) and "approval" in rule}
        return _validate(ToolPolicyResponse, {"agentId": current["agentId"],
            "configRevision": int(current.get("configRevision") or 0), "agentUpdatedAt": current["updatedAt"],
            "policyFingerprint": detail["policyFingerprint"], "registryVersion": detail["registryVersion"],
            "registryFingerprint": detail["registryFingerprint"],
            "compiledMatches": bool(matches), "policy": policy,
            "visibleTools": detail["preview"]["visibleTools"],
            "executableTools": detail["preview"]["executableTools"]}).model_dump(exclude_none=True)

    def read_tool_policy(self, agent_id):
        from .service import ManagementError
        query = _validate(ToolPolicyQuery, {"agent_id": agent_id})
        directory = self._owners()
        try:
            with directory._STATE_LOCK:
                current, detail, _store, _compiled, matches = self._policy_snapshot(directory, query.agent_id)
                return self._policy_view(current, detail, matches)
        except ManagementError as exc:
            if exc.code == "INVALID_INPUT":
                raise _error("TOOL_POLICY_UNAVAILABLE", 503) from None
            raise
        except (KeyError, ValueError, TypeError):
            raise _error("TOOL_POLICY_UNAVAILABLE", 503) from None

    def update_tool_policy(self, parameters, marker=None):
        from core.web.services import tool_policy_configuration_service as policies
        from core.web.services.agent_config_authority import canonical_agent_config_payload
        args = _validate(ToolPolicyUpdate, parameters)
        directory = self._owners()
        write_started = False
        try:
            with directory.agent_session_lifecycle_transaction(), directory._STATE_LOCK:
                current, detail, store, compiled, matches = self._policy_snapshot(directory, args.agent_id)
                if (int(current.get("configRevision") or 0) != args.expected_config_revision
                        or current.get("updatedAt") != args.expected_agent_updated_at
                        or detail["policyFingerprint"] != args.expected_policy_fingerprint
                        or detail["registryVersion"] != args.expected_registry_version
                        or detail["registryFingerprint"] != args.expected_registry_fingerprint):
                    raise _error("STATE_CONFLICT")
                if not compiled:
                    raise _error("CONFIG_SNAPSHOT_UNAVAILABLE")
                if not matches:
                    raise _error("CONFIG_SNAPSHOT_MISMATCH")
                changes = args.updates.model_dump(exclude_unset=True)
                # Already-approved call grants are not policy inputs. Preserve
                # existing native grants when a per-tool approval is edited.
                if "perToolRules" in changes:
                    existing = deepcopy(detail["currentPolicy"].get("perToolRules") or {})
                    for name, rule in changes["perToolRules"].items():
                        existing[name] = {**existing.get(name, {}), **rule}
                    changes["perToolRules"] = existing
                snapshot = ExistingStateSnapshot(self.native.project_root, directory, pin_workspace=True)
                preview = policies.validate_tool_policy_configuration(args.agent_id, changes, declared_policy=True,
                                                                      existing_snapshot=snapshot)
                if (preview["registryVersion"] != args.expected_registry_version
                        or preview["registryFingerprint"] != args.expected_registry_fingerprint):
                    raise _error("STATE_CONFLICT")
                if not preview["validation"]["valid"]:
                    raise _error("INVALID_INPUT", 422)
                write_started = True
                policies.update_tool_policy_configuration(args.agent_id, policy=changes,
                    expected_agent_updated_at=args.expected_agent_updated_at,
                    expected_policy_fingerprint=args.expected_policy_fingerprint, confirmed=True,
                    expected_registry_version=args.expected_registry_version,
                    expected_registry_fingerprint=args.expected_registry_fingerprint, declared_policy=True,
                    existing_snapshot=snapshot)
                raw = directory._find_agent(directory.load_state(), args.agent_id)
                # Same canonical snapshot CAS as NativeAgentGateway.update;
                # accepted Session revision pins are never touched.
                store.repository.compare_and_swap_agent_config(agent_id=args.agent_id,
                    expected_config_revision_id=compiled["configRevisionId"], display_name=raw["displayName"],
                    kind=raw["kind"], status=raw["status"], config=canonical_agent_config_payload(raw),
                    source="external_operator_management").result(timeout=3)
                current, detail, _store, _compiled, matches = self._policy_snapshot(directory, args.agent_id)
                return AssetMutationResponse(action="agent_tool_policy_update", resourceId=args.agent_id,
                    revision=int(current["configRevision"]), fingerprint=detail["policyFingerprint"],
                    verified=bool(matches and detail["policyFingerprint"] == preview["proposedPolicyFingerprint"])).model_dump()
        except policies.ToolPolicyConfigurationConflictError:
            raise _error("STATE_CONFLICT") from None
        except Exception as exc:
            if write_started:
                # Registry policy can be durable before compiled CAS or its
                # acknowledgement fails. Recovery must retain the same ID.
                raise _error("OPERATION_UNCONFIRMED") from None
            if isinstance(exc, (policies.ToolPolicyConfigurationError, ValueError, TypeError)):
                raise _error("INVALID_INPUT", 422) from None
            raise

    def _knowledge_owner(self):
        from core.web.services import team_knowledge_service as knowledge
        self._owners()
        if Path(knowledge.PROJECT_ROOT).resolve() != self.native.project_root:
            raise _error("TARGET_BINDING_CHANGED")
        return knowledge

    def read_knowledge_acl(self, knowledge_base_id):
        from .service import ManagementError
        query = _validate(KnowledgeACLQuery, {"knowledge_base_id": knowledge_base_id})
        owner = self._knowledge_owner()
        try:
            return _validate(KnowledgeACLResponse, owner.read_operator_knowledge_base_acl(query.knowledge_base_id)).model_dump()
        except ManagementError as exc:
            if exc.code == "INVALID_INPUT":
                raise _error("KNOWLEDGE_BASE_UNAVAILABLE", 503) from None
            raise
        except owner.TeamKnowledgePermissionError:
            raise _error("OPERATOR_CONTROL_REQUIRED", 403) from None
        except owner.TeamKnowledgeNotFoundError:
            raise _error("KNOWLEDGE_BASE_UNAVAILABLE", 404) from None
        except (OSError, ValueError, TypeError):
            raise _error("KNOWLEDGE_BASE_UNAVAILABLE", 503) from None

    def _mutate_acl(self, parameters, *, revoke):
        args = _validate(KnowledgeACLMutation, parameters)
        owner = self._knowledge_owner()
        snapshot = self.read_knowledge_acl(args.knowledge_base_id)
        if args.knowledge_base_id != snapshot["scopedKnowledgeBaseId"]:
            raise _error("INVALID_INPUT", 422)
        try:
            result = owner.mutate_operator_knowledge_base_acl(args.knowledge_base_id, args.target_agent_id,
                permissions=args.permissions, expected_acl_fingerprint=args.expected_acl_fingerprint, revoke=revoke)
        except owner.TeamKnowledgeACLConflictError:
            raise _error("STATE_CONFLICT") from None
        except owner.TeamKnowledgeNotFoundError:
            raise _error("KNOWLEDGE_BASE_UNAVAILABLE", 404) from None
        except owner.TeamKnowledgeError:
            raise _error("INVALID_INPUT", 422) from None
        return AssetMutationResponse(action="knowledge_acl_revoke" if revoke else "knowledge_acl_grant",
            resourceId=result["scopedKnowledgeBaseId"], fingerprint=result["fingerprint"], verified=True).model_dump()

    def grant_knowledge_acl(self, parameters, marker=None):
        return self._mutate_acl(parameters, revoke=False)

    def revoke_knowledge_acl(self, parameters, marker=None):
        return self._mutate_acl(parameters, revoke=True)
