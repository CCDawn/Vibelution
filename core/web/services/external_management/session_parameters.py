"""Existing-only current Agent settings, never the parameters of an active Turn.

Saved model candidates and current loaded runtime config intentionally remain
separate authorities, matching the native parameter view's source precedence.
"""
from __future__ import annotations

from pathlib import Path

from .service import ManagementError
from .archive_state import ArchiveState
from .state_snapshot import ExistingStateSnapshot


class _ParameterState(ArchiveState):
    """Keep the existing authority owners with strict reads for this GET only."""

    @staticmethod
    def read_json(path, *, strict=False, max_bytes=32 * 1024 * 1024):
        return ExistingStateSnapshot.read_json(path, strict=True, max_bytes=max_bytes)


def _project_parameters(session_id, agent, public_config, runtime_config, catalog):
    """Project frozen sources through the existing native parameter resolvers."""
    from core.llm.agent_runtime import resolve_agent_llm
    from core.llm.reasoning_effort import normalize_reasoning_effort
    from core.orchestration.session_budget_resolve import session_budget_parameters_from_agent
    from core.web.services.agent_model_candidate_service import project_agent_model_candidates
    from core.web.services.session.conversation_index import _conversation_agent_dialogue_context_window_payload

    revision = agent.get("configRevision")
    bindings = agent.get("llmBindings")
    dialogue = bindings.get("dialogue") if isinstance(bindings, dict) else None
    model_ref = dialogue.get("modelId") if isinstance(dialogue, dict) else None
    if (type(revision) is not int or revision < 0 or not isinstance(model_ref, str)
        or not model_ref.strip() or not isinstance(agent.get("metadata", {}), dict)):
        raise ValueError("invalid Agent parameter authority")
    model_ref = model_ref.strip()
    llm = public_config.get("llm")
    if (not isinstance(llm, dict) or llm.get("schema_version") != 2
        or not isinstance(llm.get("providers"), dict) or not llm["providers"]):
        raise ValueError("invalid public configuration authority")
    choices = project_agent_model_candidates(public_config, catalog)
    selected = next((choice for choice in choices if model_ref in (choice.get("modelRef"), choice.get("modelId"))), None)
    if selected is None:
        raise ValueError("bound model is absent from saved candidates")
    supported = list(dict.fromkeys(value for raw in selected["reasoningEffortValues"]
        if (value := normalize_reasoning_effort(raw))))
    # Incomplete runtime configuration is unavailable, rather than a saved
    # metadata fallback presented as an effective setting.
    resolved = resolve_agent_llm(agent, "dialogue", config=runtime_config,
        runtime_profile_id="primary", fallback_to_dialogue=False, catalog_snapshot=catalog)
    resolved_effort = normalize_reasoning_effort(resolved.reasoning_effort_requested)
    current = resolved_effort if resolved_effort in supported else ""
    # This existing owner reads only cfg + the explicit cached Agent. Its
    # library -> provider maximum deliberately excludes catalog fallback and
    # is distinct from a resolved spec already shrunk by Agent overrides.
    context = _conversation_agent_dialogue_context_window_payload(runtime_config,
        {"agentId": agent["agentId"], "_agent": agent})
    budget = session_budget_parameters_from_agent(agent)
    return {"sessionId": session_id, "agentId": agent["agentId"], "configRevision": revision,
        "currentModelId": model_ref, "currentReasoningEffort": current, "reasoningEffortValues": supported,
        "contextWindow": context["limit"], "maxContextWindow": context["maxLimit"],
        "budget": {"revision": revision, "maxCallsPerTurn": budget.maxCallsPerTurn if budget is not None else None}}


def _visibility_source(snapshot, kind, agent_id=None):
    """Read existing authorities; visibility decisions remain in workspace."""
    try:
        if kind == "agents":
            agents = snapshot.read_json(snapshot.path("agents", "agents.json"), strict=True).get("agents")
            if (not isinstance(agents, list) or len(agents) > 100_000
                or any(not isinstance(agent, dict) for agent in agents)):
                raise ValueError("invalid Agent authority")
            return agents
        if kind == "team_member_ids":
            return snapshot.team_member_ids()
        if kind == "binding":
            from core.agent_plugins.virtual_human_life.storage import VirtualHumanLifeStore

            owner = VirtualHumanLifeStore._validated_agent_id(agent_id)
            path = snapshot.path("agents", owner, "plugins", "virtual-human-life", "binding.json")
            try:
                path.stat()
            except FileNotFoundError:
                return None
            return snapshot.read_json(path, strict=True, max_bytes=64 * 1024)
        raise ValueError("unknown visibility source")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
        raise ManagementError("SESSION_PARAMETERS_UNAVAILABLE", 503) from None


def _directory_authority():
    """Freeze the published native store, independently of current Agent routing."""
    from core.web.services.session import directory_runtime

    with directory_runtime._RUNTIME_LOCK:
        store = directory_runtime.get_open_directory_store()
        root = directory_runtime.directory_store_project_root()
        if store is None or root is None:
            raise ManagementError("SESSION_DIRECTORY_UNAVAILABLE", 503)
        database = store.database
        path = Path(database.path)
        if not path.is_absolute():
            raise ValueError("Invalid directory authority")
        return store, (id(store.repository), id(database), str(path),
            Path(root).resolve(), directory_runtime._GENERATION)


def _verify_directory_authority(expected):
    try:
        current = _directory_authority()
    except ManagementError:
        raise ValueError("Directory authority changed") from None
    if current[0] is not expected[0] or current[1] != expected[1]:
        raise ValueError("Directory authority changed")


def read_session_parameters(project_root: Path, directory, session_id: str) -> dict:
    """Read current settings for subsequent accepted Turns without initializing."""
    from config import settings
    from config.model_catalog import read_existing_model_catalog_snapshot
    from config.paths import resolve_model_catalog_state_path
    from .contracts import SessionParametersResponse
    from .workspace import _validated_session_snapshot

    try:
        # This existing reader shares the public snapshot with every path
        # resolution and never ensures a developer sandbox, even when absent.
        config_path = Path(directory.CONFIG_PATH)
        sources = _ParameterState(project_root, directory, pin_workspace=True)
        if Path(directory.CONFIG_PATH) != config_path:
            raise ValueError("configuration authority changed")
        authority = _directory_authority()
        try:
            repository, _row, _runtime, agent, used_store = _validated_session_snapshot(
                project_root, directory, session_id, return_agent=True, _return_store=True,
                _source_reader=lambda kind, agent_id=None: _visibility_source(sources, kind, agent_id))
            if used_store is not authority[0] or repository is not authority[0].repository:
                raise ValueError("Directory authority changed")
            runtime_config = settings.peek_loaded_config_snapshot()
            if runtime_config is None:
                raise ValueError("current runtime config has not loaded")
            catalog, catalog_source = read_existing_model_catalog_snapshot(
                resolve_model_catalog_state_path(config_path), allow_missing=True)
            parameters = _project_parameters(session_id, agent, sources.config, runtime_config, catalog)
            return SessionParametersResponse.model_validate({
                "source": "native-current-agent-runtime-parameters", "untrustedContent": True,
                "catalogState": catalog_source, "parameters": parameters}).model_dump()
        finally:
            # Also check on an ACL rejection: a changed routing generation
            # must not turn mixed-source evidence into any visibility decision.
            sources.verify_workspace()
            _verify_directory_authority(authority)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
        raise ManagementError("SESSION_PARAMETERS_UNAVAILABLE", 503) from None
