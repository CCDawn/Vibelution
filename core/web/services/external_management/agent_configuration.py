"""Existing-only configuration projection and one native parameter owner per edit."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from pathlib import Path

from pydantic import ValidationError

from .agent_configuration_contracts import (
    AgentConfigurationQuery, AgentConfigurationResponse, AgentParametersUpdate,
    CompressionPolicy, PersonaProfile, TaskProfile,
)
from .state_snapshot import ExistingStateSnapshot


def _error(code, status=409):
    from .service import ManagementError
    return ManagementError(code, status)


def _validate(model, value):
    try:
        return model.model_validate(value)
    except ValidationError:
        raise _error("INVALID_INPUT", 422) from None


def _fields(model, value):
    if not isinstance(value, dict):
        raise ValueError("Invalid configuration block")
    return {key: deepcopy(item) for key, item in value.items() if key in model.model_fields}


def _parameters(agent, sources, directory):
    from config import settings
    from config.model_catalog import read_existing_model_catalog_snapshot
    from config.paths import resolve_model_catalog_state_path
    from core.llm.agent_model_parameters import resolve_agent_model_parameters
    from core.orchestration.session_budget_resolve import session_budget_parameters_from_agent
    from core.orchestration.tool_budget_profiles import DEFAULT_MAX_CALLS_BY_MODEL_FAMILY, normalize_max_calls_by_model_family
    from core.web.services.team.challenge_cup_context_policy import CHALLENGE_CUP_CONTEXT_POLICY_VERSION
    from .session_parameters import _project_parameters

    model_ref = agent["llmBindings"]["dialogue"]["modelId"]
    runtime = settings.peek_loaded_config_snapshot()
    current = None
    context_source = "unavailable"
    if runtime is not None:
        from core.llm.agent_runtime import resolve_agent_llm
        from core.web.services.session.conversation_index import _conversation_agent_dialogue_context_window_payload
        catalog, _catalog_source = read_existing_model_catalog_snapshot(
            resolve_model_catalog_state_path(Path(directory.CONFIG_PATH)), allow_missing=True)
        current = _project_parameters(agent.get("directSessionId", ""), agent, sources.config, runtime, catalog)
        resolved = resolve_agent_llm(agent, "dialogue", config=runtime, runtime_profile_id="primary",
            fallback_to_dialogue=False, catalog_snapshot=catalog)
        # The parameter editor's currentReasoningEffort is the requested
        # control value. Effective means the native adapter's final value.
        current["effectiveReasoningEffort"] = resolved.reasoning_effort_effective
        context = _conversation_agent_dialogue_context_window_payload(runtime, {"_agent": agent, "agentId": agent["agentId"]})
        model_ref, context_source = context["modelRef"], context["source"]
    stored = resolve_agent_model_parameters(agent, model_ref)
    budget = session_budget_parameters_from_agent(agent)
    override = budget.maxCallsPerTurn if budget is not None else None
    policy = directory.normalize_agent_context_compression_policy(agent.get("contextCompressionPolicy"))
    explicit = policy.get("mode") == "custom"
    stored_policy = _fields(CompressionPolicy, policy) if explicit else None
    # The legacy effective resolver calls get_config() inside its budget
    # derivation even with an explicit base_policy. Its versioned branch is
    # pure; do not initialize runtime configuration on behalf of this GET.
    compression_available = bool(current is not None and explicit
        and policy.get("policyVersion", 0) >= CHALLENGE_CUP_CONTEXT_POLICY_VERSION)
    effective = (directory.effective_agent_context_compression_policy(agent, base_policy={},
        context_window_limit=current["contextWindow"]) if compression_available else {})
    tool_policy = agent.get("toolPolicy", {})
    if not isinstance(tool_policy, dict):
        raise ValueError("Invalid declared tool budget")
    family_values = normalize_max_calls_by_model_family(tool_policy.get("maxCallsPerTurnByModelFamily"))
    return {"model": {"modelRef": model_ref,
        "stored": {"contextWindow": stored["context_window"] if stored["has_context_window"] else None,
            "reasoningEffort": stored["reasoning_effort"] if stored["has_reasoning_effort"] else None,
            "legacyReasoningEffort": stored["legacy_reasoning_effort"] or None},
        "effective": {"available": current is not None,
            "contextWindow": current["contextWindow"] if current is not None else None,
            "reasoningEffort": current["effectiveReasoningEffort"] if current is not None else None},
        "origin": {"contextWindow": context_source,
            "reasoningEffort": "native_runtime" if current is not None else "unavailable"},
        "limits": {"maxContextWindow": current["maxContextWindow"] if current is not None else None,
            "reasoningEffortValues": current["reasoningEffortValues"] if current is not None else []}},
        "budget": {"stored": {"maxCallsPerTurn": override},
            "effective": {"available": override is not None, "maxCallsPerTurn": override},
            "origin": "agent_override" if override is not None else "family_or_base_unavailable", "limits": {},
            "declaredPolicy": {"maxCallsPerTurn": tool_policy.get("maxCallsPerTurn"),
                "maxCallsPerTurnByModelFamily": {key: value for key, value in family_values.items()
                    if key in DEFAULT_MAX_CALLS_BY_MODEL_FAMILY}}},
        "compression": {"stored": stored_policy, "origin": "agent" if explicit else "migration_required",
            "effective": {"available": compression_available,
                "source": effective.get("source", "native_runtime_reader_required" if explicit else "migration_required"),
                **{key: effective.get(key) for key in ("effectiveTokenLimit", "compressionTriggerTokenLimit",
                    "postCompressionTargetTokenLimit", "contextWindowLimit")}, "enabled": effective.get("enabled")}}}


class AgentConfigurationControl:
    def __init__(self, native):
        self.native = native

    @contextmanager
    def _locked(self, *, write=False):
        from .asset_control import AssetControl
        control = AssetControl(self.native)
        directory, teams = control._owners(), control._team_owner()
        # Share native lifecycle -> Team -> Agent ordering. GET never enters a
        # lifecycle transaction, whose legacy readers can provision state.
        lifecycle = directory.agent_session_lifecycle_transaction() if write else nullcontext()
        with lifecycle, teams._TEAM_LOCK, directory._STATE_LOCK:
            yield directory

    def _snapshot(self, directory, agent_id):
        from .agent_directory import _ownership, _rows, _teams
        from .session_parameters import _visibility_source
        from core.web.services.external_agent.policy import external_mcp_eligibility
        from core.web.services.agent_config_authority import canonical_agent_config_payload

        sources = ExistingStateSnapshot(self.native.project_root, directory, pin_workspace=True)
        _payload, agents = _rows(sources, sources.path("agents", "agents.json"), "agents")
        ids = [row.get("agentId") for row in agents]
        if any(not isinstance(aid, str) or not aid for aid in ids) or len(set(ids)) != len(ids):
            raise ValueError("Ambiguous Agent authority")
        agent = next((row for row in agents if row["agentId"] == agent_id), None)
        if agent is None or agent.get("status") != "active":
            raise _error("AGENT_UNAVAILABLE", 404)
        metadata = agent.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("Invalid Agent metadata")
        _payload, teams = _rows(sources, sources.path("teams", "teams.json"), "teams")
        team_index, memberships = _teams(teams)
        classification = directory.agent_conversation_index_classification(agent, hidden_team_member_agent_ids=set())
        role = directory._normalize_role_key(agent.get("roleKey") or directory._infer_agent_role_key(agent))
        mode = directory._normalize_primary_mode(agent.get("primaryMode") or directory._infer_agent_primary_mode(agent))
        projected = {**agent, "conversationIndexKind": classification["kind"], "roleKey": role}
        ownership = _ownership(projected, classification["kind"], mode, memberships.get(agent_id, []), team_index, {})
        decision = external_mcp_eligibility(projected, active_team_lookup=lambda _aid:
            next((team for team in memberships.get(agent_id, []) if team["status"] == "active"), None))
        binding = _visibility_source(sources, "binding", agent_id)
        if binding is not None and (not isinstance(binding, dict) or type(binding.get("enabled")) is not bool
                or binding.get("agentId") != agent_id):
            raise ValueError("Invalid Companion binding")
        if (directory._agent_archive_protected(agent) or ownership["kind"] in {"team", "system", "companion"}
                or not decision.eligible or classification["kind"] != "personal_agent" or classification["errors"]
                or binding is not None and binding["enabled"]):
            raise _error("AGENT_PROTECTED", 403)
        if type(agent.get("configRevision")) is not int or agent["configRevision"] < 0:
            raise ValueError("Invalid configuration revision")
        model_ref = agent.get("llmBindings", {}).get("dialogue", {}).get("modelId")
        if not isinstance(model_ref, str) or not model_ref.strip():
            raise ValueError("Missing dialogue binding")
        store = self.native._control_store()
        compiled = store.repository.get_current_agent_config(agent_id) if store is not None else None
        matches = bool(compiled and compiled.get("config") == canonical_agent_config_payload(agent))
        sources.verify_workspace()
        if self.native._control_store() is not store:
            raise ValueError("Compiled authority changed")
        return sources, deepcopy(agent), store, compiled, matches

    def _view(self, directory, snapshot):
        sources, agent, _store, _compiled, matches = snapshot
        metadata = agent.get("metadata", {})
        result = AgentConfigurationResponse.model_validate({"agentId": agent["agentId"],
            "configRevision": agent["configRevision"], "agentUpdatedAt": agent["updatedAt"],
            "compiledMatches": matches, "displayName": agent["displayName"],
            "dialogueModelId": agent["llmBindings"]["dialogue"]["modelId"],
            "promptTemplateId": agent.get("promptTemplateId", ""),
            "personaProfile": _fields(PersonaProfile, metadata.get("personaProfile", {})),
            "taskProfile": _fields(TaskProfile, metadata.get("taskProfile", {})),
            "parameters": _parameters(agent, sources, directory)}).model_dump()
        sources.verify_workspace()
        if self.native._control_store() is not _store:
            raise ValueError("Compiled authority changed")
        return result

    def read_configuration(self, agent_id):
        query = _validate(AgentConfigurationQuery, {"agent_id": agent_id})
        try:
            with self._locked() as directory:
                return self._view(directory, self._snapshot(directory, query.agent_id))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise _error("AGENT_CONFIGURATION_UNAVAILABLE", 503) from None

    def update_parameters(self, parameters, marker=None):
        from .asset_contracts import AssetMutationResponse
        from .operation_receipts import record_success
        from .store import digest
        from core.web.services.agent_config_authority import canonical_agent_config_payload
        from core.llm.agent_model_parameters import validate_agent_model_parameters

        args = _validate(AgentParametersUpdate, parameters)
        write_started = False
        try:
            with self._locked(write=True) as directory:
                before = self._snapshot(directory, args.agent_id)
                sources, agent, store, compiled, matches = before
                if agent["configRevision"] != args.expected_config_revision:
                    raise _error("STATE_CONFLICT")
                if not compiled:
                    raise _error("CONFIG_SNAPSHOT_UNAVAILABLE")
                if not matches:
                    raise _error("CONFIG_SNAPSHOT_MISMATCH")
                block = args.parameters
                if args.kind == "model":
                    view = _parameters(agent, sources, directory)["model"]
                    if block.expected_model_ref != view["modelRef"]:
                        raise _error("STATE_CONFLICT")
                    if not view["effective"]["available"]:
                        raise _error("AGENT_CONFIGURATION_UNAVAILABLE", 503)
                    values = validate_agent_model_parameters(context_window=block.context_window,
                        reasoning_effort=block.reasoning_effort, max_context_window=view["limits"]["maxContextWindow"],
                        supported_reasoning_efforts=view["limits"]["reasoningEffortValues"])
                    owner = lambda: directory.update_agent_model_parameters_if_current(args.agent_id,
                        expected_model_ref=block.expected_model_ref, expected_config_revision=args.expected_config_revision,
                        context_window=block.context_window, reasoning_effort=block.reasoning_effort,
                        supported_reasoning_efforts=view["limits"]["reasoningEffortValues"])
                elif args.kind == "budget":
                    values = {} if block.maxCallsPerTurn is None else {"maxCallsPerTurn": block.maxCallsPerTurn}
                    owner = lambda: directory.update_agent_budget_parameters_if_current(args.agent_id,
                        expected_config_revision=args.expected_config_revision, values=values)
                else:
                    from core.web.services.agent_operation_service import update_agent_from_catalog_request
                    values = directory.normalize_agent_context_compression_policy(block.policy.model_dump(exclude_none=True))
                    owner = lambda: update_agent_from_catalog_request(args.agent_id,
                        updates={"contextCompressionPolicy": values}, expected_config_revision=args.expected_config_revision,
                        source="external_operator_management")
                sources.verify_workspace()
                write_started = True
                try:
                    owner()
                except directory.AgentStateConflictError:
                    write_started = False
                    raise _error("STATE_CONFLICT") from None
                after = self._snapshot(directory, args.agent_id)
                if after[2] is not store:
                    raise _error("OPERATION_UNCONFIRMED", 503)
                raw = after[1]
                # One native block write, then the existing compiled snapshot
                # CAS. A failure after the registry write remains unconfirmed;
                # this adapter does not claim a multi-owner transaction.
                store.repository.compare_and_swap_agent_config(agent_id=args.agent_id,
                    expected_config_revision_id=compiled["configRevisionId"], display_name=raw["displayName"],
                    kind=raw["kind"], status=raw["status"], config=canonical_agent_config_payload(raw),
                    source="external_operator_management").result(timeout=3)
                verified = self._snapshot(directory, args.agent_id)
                if verified[2] is not store:
                    raise _error("OPERATION_UNCONFIRMED", 503)
                raw, matches = verified[1], verified[4]
                metadata = raw.get("metadata", {})
                if args.kind == "model":
                    actual = metadata.get("llmModelParameters", {}).get(block.expected_model_ref, {})
                    applied = all(actual.get(key) == value for key, value in values.items())
                elif args.kind == "budget":
                    actual = metadata.get("sessionBudgetParameters", {})
                    applied = actual == values
                else:
                    actual = raw.get("contextCompressionPolicy")
                    applied = actual == values
                if not matches or not applied:
                    raise _error("OPERATION_UNCONFIRMED", 503)
                result = AssetMutationResponse(action="agent_parameters_update", resourceId=args.agent_id,
                    revision=raw["configRevision"], fingerprint=digest([raw["configRevision"], args.kind, actual]),
                    verified=True).model_dump()
                return record_success(self.native, "agent_parameters_update", parameters, marker, result) if marker is not None else result
        except Exception as exc:
            if write_started:
                raise _error("OPERATION_UNCONFIRMED", 503) from None
            if isinstance(exc, (OSError, ValueError, TypeError, KeyError, AttributeError)):
                raise _error("INVALID_INPUT", 422) from None
            raise
