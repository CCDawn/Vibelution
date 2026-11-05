"""Configuration discovery reuses native owners and never expands grants."""
from __future__ import annotations

import json
from copy import deepcopy
from .asset_control import AssetControl, _error
from .asset_contracts import AssetMutationResponse, ToolPolicyPatch
from .configuration_discovery_contracts import (AgentPromptQuery, AgentPromptResponse,
    AgentPromptUpdate, ToolPolicyInspectQuery, ToolPolicyInspectResponse)
from .state_snapshot import ExistingStateSnapshot
from .store import digest


class ConfigurationDiscovery:
    def __init__(self, native):
        self.native = native

    def _agent(self, agent_id):
        from .agent_configuration import AgentConfigurationControl
        # Share the ordinary-Agent visibility and compiled-authority checks.
        view = AgentConfigurationControl(self.native).read_configuration(agent_id)
        if not view["compiledMatches"]:
            raise _error("CONFIG_SNAPSHOT_UNAVAILABLE")
        return view

    def _templates(self, directory, template_id):
        from core.web.services import prompt_template_service as prompts
        snapshot = ExistingStateSnapshot(self.native.project_root, directory, pin_workspace=True)
        _payload, rows = prompts.read_existing_prompt_template_records(
            index_path=snapshot.path("agent_config", "prompt_templates.json"),
            workspace_root=snapshot.path(), project_root=self.native.project_root, resolve_template_id=template_id)
        snapshot.verify_workspace()
        return snapshot, rows

    def read_prompt(self, agent_id):
        AgentPromptQuery(agent_id=agent_id)
        from .agent_configuration import AgentConfigurationControl
        from core.web.services import prompt_template_service as prompts
        try:
            with AgentConfigurationControl(self.native)._locked() as directory:
                with prompts.PROMPT_TEMPLATE_LOCK:
                    agent = self._agent(agent_id)
                    _snapshot, rows = self._templates(directory, agent["promptTemplateId"])
                    template = next((row for row in rows if row["templateId"] == agent["promptTemplateId"]), None)
                    if template is None:
                        raise _error("PROMPT_TEMPLATE_UNAVAILABLE", 503)
                    candidates = [{key: value for key, value in row.items() if key != "content"}
                        for row in rows if row["status"] == "active" and row["category"] in {"general", "chat"}]
                    return AgentPromptResponse(agentId=agent_id, configRevision=agent["configRevision"],
                        template=template, candidates=candidates).model_dump()
        except (OSError, ValueError, prompts.PromptTemplateError):
            raise _error("PROMPT_TEMPLATE_UNAVAILABLE", 503) from None

    def update_prompt(self, parameters, marker=None):
        from core.web.services import prompt_template_service as prompts
        from core.web.services.agent_config_authority import canonical_agent_config_payload
        from core.web.services.agent_operation_service import update_agent_from_catalog_request

        args = AgentPromptUpdate.model_validate(parameters)
        from .agent_configuration import AgentConfigurationControl
        started = False
        try:
            with AgentConfigurationControl(self.native)._locked(write=True) as directory, prompts.PROMPT_TEMPLATE_LOCK:
                current = self._agent(args.agent_id)
                if (current["configRevision"] != args.expected_config_revision
                        or current["promptTemplateId"] != args.expected_template_id):
                    raise _error("STATE_CONFLICT")
                snapshot, rows = self._templates(directory, args.expected_template_id)
                template = next((row for row in rows if row["templateId"] == args.expected_template_id), None)
                if template is None or template["contentHash"] != args.expected_content_hash:
                    raise _error("STATE_CONFLICT")
                store = self.native._control_store()
                compiled = store.repository.get_current_agent_config(args.agent_id)
                if not compiled:
                    raise _error("CONFIG_SNAPSHOT_UNAVAILABLE")
                # A separate inline template is never allowed to inherit a shared sourcePath.
                template_id = "prompt-agent-" + digest([args.agent_id, marker or parameters])[:40]
                snapshot.verify_workspace()
                started = True
                created = prompts.create_agent_prompt_template_checked(template_id=template_id,
                    agent_id=args.agent_id, base_template_id=args.expected_template_id,
                    expected_content_hash=args.expected_content_hash, content=args.content,
                    index_path=snapshot.path("agent_config", "prompt_templates.json"),
                    workspace_root=snapshot.path(), project_root=self.native.project_root)
                update_agent_from_catalog_request(args.agent_id, updates={"promptTemplateId": template_id},
                    expected_config_revision=args.expected_config_revision, source="external_operator_management")
                raw = directory._find_agent(directory.load_state(), args.agent_id)
                store.repository.compare_and_swap_agent_config(agent_id=args.agent_id,
                    expected_config_revision_id=compiled["configRevisionId"], display_name=raw["displayName"],
                    kind=raw["kind"], status=raw["status"], config=canonical_agent_config_payload(raw),
                    source="external_operator_management").result(timeout=3)
                snapshot.verify_workspace()
                result = self.read_prompt(args.agent_id)
                if (result["template"]["templateId"] != template_id
                        or result["template"]["contentHash"] != created["contentHash"]
                        or result["configRevision"] <= args.expected_config_revision):
                    raise ValueError("Prompt mutation not verified")
                response = AssetMutationResponse(action="agent_prompt_update", resourceId=args.agent_id,
                    revision=result["configRevision"], fingerprint=digest([template_id, created["contentHash"]]), verified=True).model_dump()
                return AssetControl(self.native)._acknowledge("agent_prompt_update", parameters, marker, response)
        except Exception as exc:
            if started:
                # Template persistence may precede the Agent CAS. Never replay an unknown request.
                raise _error("OPERATION_UNCONFIRMED", 503) from None
            if isinstance(exc, (ValueError, prompts.PromptTemplateError)):
                raise _error("INVALID_INPUT", 422) from None
            raise

    def inspect_policy(self, agent_id, updates_json="{}"):
        from core.web.services import tool_policy_configuration_service as policies, tool_registry_service as registry
        args = ToolPolicyInspectQuery(agent_id=agent_id, updates_json=updates_json)
        from .agent_configuration import AgentConfigurationControl
        with AgentConfigurationControl(self.native)._locked() as directory:
            self._agent(agent_id)
            control = AssetControl(self.native)
            agent, current, _store, _compiled, matches = control._policy_snapshot(directory, agent_id)
            snapshot = ExistingStateSnapshot(self.native.project_root, directory, pin_workspace=True)
            updates = json.loads(args.updates_json)
            detail = (policies.validate_tool_policy_configuration(agent_id, updates, declared_policy=True,
                existing_snapshot=snapshot) if updates else current)
            tools = registry.get_existing_tool_registry(snapshot)
            policy = {key: deepcopy(value) for key, value in detail["proposedPolicy"].items()
                if key in ToolPolicyPatch.model_fields}
            if "perToolRules" in policy:
                policy["perToolRules"] = {key: {"approval": row["approval"]}
                    for key, row in policy["perToolRules"].items() if "approval" in row}
            response = ToolPolicyInspectResponse(agentId=agent_id,
                current=control._policy_view(agent, current, matches), proposedPolicy=policy,
                proposedPolicyFingerprint=detail["proposedPolicyFingerprint"], validation=detail["validation"],
                preview=detail["preview"], affectedAgentCount=detail["impact"]["affectedAgentCount"],
                confirmationRequired=detail["confirmation"]["required"],
                confirmationReasons=detail["confirmation"]["reasons"],
                candidates=[{"name": row["name"], "description": str(row.get("description") or ""),
                    "available": policies._tool_available(row)} for row in tools["tools"]])
            snapshot.verify_workspace()
            return response.model_dump(exclude_none=True)
