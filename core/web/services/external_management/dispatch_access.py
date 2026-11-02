"""One-Agent operator gateway edits; the native config manifest owns proof."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import re
import tomllib

from config.models import ExternalAgentGatewayConfig
from config.operator_config_transaction import (
    OperatorConfigTransactionError, TransactionParticipant, append_toml_table,
    apply_operator_config_transaction, prepare_operator_config_transaction,
    read_native_config_outcome, remove_toml_table_tree,
)
from config.public_config import public_config_hash

from .asset_contracts import AssetMutationResponse, DispatchAccessQuery, DispatchAccessResponse, DispatchAccessSet
from .state_snapshot import ExistingStateSnapshot
from .store import digest

_ACTION = "agent_dispatch_access_set"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")


def _error(code, status=409):
    from .service import ManagementError
    return ManagementError(code, status)


def _gateway(public):
    raw = public.get("external_agent_gateway", {})
    if not isinstance(raw, dict) or type(raw.get("enabled", False)) is not bool:
        raise ValueError("Invalid gateway authority")
    for key in ("allowed_agent_ids", "denied_agent_ids"):
        values = raw.get(key, [])
        if (not isinstance(values, list) or len(values) > 100000
                or any(not isinstance(item, str) or not _ID.fullmatch(item) for item in values)):
            raise ValueError("Invalid gateway Agent list")
    return ExternalAgentGatewayConfig.model_validate(raw)


def _request(native, parameters, marker):
    from .operation_receipts import _binding
    _binding(native.project_root, _ACTION, parameters, marker)
    return {"projectRoot": str(native.project_root), **marker, "action": _ACTION,
            "agentId": parameters["agent_id"], "enabled": parameters["enabled"]}


class DispatchAccessControl:
    def __init__(self, native):
        self.native = native

    def _owners(self):
        from .asset_control import AssetControl
        control = AssetControl(self.native)
        return control._owners(), control._team_owner()

    @contextmanager
    def _mutation_lock(self, args):
        from core.web.services import session_service as sessions
        from core.web.services.session.admission_lock import session_has_active_work_run
        from core.external_agent.contracts import TASK_TERMINAL_STATUSES
        from .runtime_operations import _external_tasks
        from .archive_state import ArchiveState
        from vibelution_storage import resolve_project_runtime_home
        from core.assistant_runtime.migration_io import check_path
        if args.enabled:
            with self._locked() as directory:
                yield directory
            return
        self._owners()
        if Path(sessions.PROJECT_ROOT).resolve() != self.native.project_root:
            raise _error("TARGET_BINDING_CHANGED")
        try:
            # Native admission handles exclude new Session submits; CHAT ->
            # Life also excludes new Session creation. The external task owner
            # now shares Life before its durable queued admission.
            with sessions.agent_archive_transaction(args.agent_id, timeout=3.0) as admitted:
                with self._locked() as directory:
                    current = ArchiveState(self.native.project_root, directory).agent(args.agent_id)
                    if current is None:
                        raise _error("AGENT_UNAVAILABLE", 404)
                    direct = current.get("directSessionId")
                    if (not isinstance(admitted, set) or not isinstance(direct, str)
                            or not direct or direct not in admitted):
                        raise _error("STATE_UNAVAILABLE", 503)
                    payload = sessions.load_chat_state(sessions.PROJECT_ROOT)
                    rows = payload.get("conversations") if isinstance(payload, dict) else None
                    if (not isinstance(rows, list) or len(rows) > 100000
                            or any(not isinstance(row, dict) for row in rows)):
                        raise _error("STATE_UNAVAILABLE", 503)
                    selected = [row for row in rows if row.get("conversation_id") in admitted]
                    by_id = {row.get("conversation_id"): row for row in selected}
                    if len(by_id) != len(admitted) or len(selected) != len(admitted):
                        raise _error("STATE_UNAVAILABLE", 503)
                    for session_id, row in by_id.items():
                        if (sessions._is_session_busy_for_delete(session_id, row)
                                or session_has_active_work_run(sessions, session_id)):
                            raise _error("AGENT_BUSY")
                    folder = resolve_project_runtime_home(self.native.project_root) / "external_agents" / "tasks"
                    try:
                        folder.lstat()
                    except FileNotFoundError:
                        ancestor = folder.parent
                        while True:
                            try:
                                ancestor.lstat()
                                break
                            except FileNotFoundError:
                                ancestor = ancestor.parent
                        check_path(ancestor)
                        records, complete = [], True
                    else:
                        records, complete = _external_tasks(self.native)
                    if not complete:
                        raise _error("STATE_UNAVAILABLE", 503)
                    for row in records:
                        if not isinstance(row.get("agentId"), str) or not row["agentId"]:
                            raise _error("STATE_UNAVAILABLE", 503)
                        if row["agentId"] == args.agent_id and row.get("status") not in TASK_TERMINAL_STATUSES:
                            raise _error("AGENT_BUSY")
                    yield directory
        except (sessions.SessionBusyError, TimeoutError):
            raise _error("AGENT_BUSY") from None
        except (OSError, ValueError, TypeError, KeyError):
            raise _error("STATE_UNAVAILABLE", 503) from None

    @contextmanager
    def _locked(self):
        directory, teams = self._owners()
        # Team roster edits already resolve Agents while holding TEAM_LOCK.
        # Keep that order; config transaction subsequently enters Fence -> Config.
        with directory.agent_session_lifecycle_transaction(), teams._TEAM_LOCK, directory._STATE_LOCK:
            yield directory

    def _snapshot(self, directory, agent_id):
        from .agent_directory import _rows, _teams
        from core.web.services.external_agent.policy import external_mcp_eligibility
        snapshot = ExistingStateSnapshot(self.native.project_root, directory, pin_workspace=True)
        _payload, agents = _rows(snapshot, snapshot.path("agents", "agents.json"), "agents")
        _payload, teams = _rows(snapshot, snapshot.path("teams", "teams.json"), "teams")
        _team_index, memberships = _teams(teams)
        agent = next((row for row in agents if row.get("agentId") == agent_id), None)
        if agent is None:
            raise _error("AGENT_UNAVAILABLE", 404)
        metadata = agent.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("Invalid Agent metadata")
        classification = directory.agent_conversation_index_classification(agent)
        projected = {**agent, "conversationIndexKind": classification["kind"],
                     "roleKey": directory._normalize_role_key(agent.get("roleKey") or directory._infer_agent_role_key(agent))}
        active = next((team for team in memberships.get(agent_id, []) if team["status"] == "active"), None)
        decision = external_mcp_eligibility(projected, active_team_lookup=lambda _aid: active,
            operator_enabled=lambda _aid: True, operator_explicitly_enabled=lambda _aid: False)
        protected = (projected["roleKey"] == "personal_assistant" or directory._agent_archive_protected(agent)
            or any(metadata.get(key) for key in ("personalAssistantProfile", "virtualHumanCompanion",
                "virtualHumanSelfWake", "lifeStewardForAgentId", "selfWakeForAgentId")))
        reason = ("agent_protected" if protected else decision.reason if decision.reason != "eligible"
                  else "unsupported_agent_class" if classification["kind"] != "personal_agent" else "eligible")
        gateway = _gateway(snapshot.config)
        operator_enabled = (gateway.enabled and agent_id not in gateway.denied_agent_ids
            and (not gateway.allowed_agent_ids or agent_id in gateway.allowed_agent_ids))
        fingerprint = digest([str(self.native.project_root).casefold(), str(Path(directory.CONFIG_PATH).resolve()).casefold(),
            str(snapshot.path()).casefold(), agent, memberships.get(agent_id, []), classification])
        snapshot.verify_workspace()
        view = DispatchAccessResponse(agentId=agent_id, gatewayEnabled=gateway.enabled,
            operatorEnabled=bool(operator_enabled), dispatchable=reason == "eligible" and operator_enabled,
            dispatchReason=reason if reason != "eligible" else "eligible" if operator_enabled else "operator_disabled",
            publicConfigHash=public_config_hash(snapshot.config), eligibilityFingerprint=fingerprint).model_dump()
        return snapshot, gateway, reason, view

    def read(self, agent_id):
        query = DispatchAccessQuery(agent_id=agent_id)
        try:
            with self._locked() as directory:
                return self._snapshot(directory, query.agent_id)[3]
        except (OSError, ValueError, TypeError, KeyError):
            raise _error("DISPATCH_ACCESS_UNAVAILABLE", 503) from None

    def receipt(self, parameters, marker):
        """Historical proof does not depend on current membership/config values."""
        request = _request(self.native, parameters, marker)
        directory, _teams = self._owners()
        config_path = Path(directory.CONFIG_PATH).resolve()
        proof = read_native_config_outcome(config_path, request)
        self._owners()  # Discard any result after native root/owner changes.
        if Path(directory.CONFIG_PATH).resolve() != config_path:
            raise ValueError("Config owner changed")
        if proof is None or proof["status"] != "completed":
            return None
        return AssetMutationResponse(action=_ACTION, resourceId=parameters["agent_id"],
            fingerprint=proof["candidateHash"], verified=True).model_dump(exclude_none=True)

    def set(self, parameters, marker):
        args = DispatchAccessSet.model_validate(parameters)
        request = _request(self.native, parameters, marker)
        try:
            with self._mutation_lock(args) as directory:
                config_path = Path(directory.CONFIG_PATH).resolve()
                try:
                    previous = read_native_config_outcome(config_path, request)
                except Exception:
                    raise _error("OPERATION_UNCONFIRMED", 503) from None
                if previous is not None:
                    if previous["status"] != "completed":
                        raise _error("OPERATION_UNCONFIRMED", 503)
                    return self.receipt(parameters, marker)
                snapshot, gateway, reason, view = self._snapshot(directory, args.agent_id)
                if (view["publicConfigHash"] != args.expected_public_config_hash
                        or view["eligibilityFingerprint"] != args.expected_eligibility_fingerprint):
                    raise _error("STATE_CONFLICT")
                if reason != "eligible":
                    raise _error("AGENT_DISPATCH_ACCESS_DENIED", 403)
                if args.enabled and not gateway.enabled:
                    raise _error("GATEWAY_NOT_READY")
                before = snapshot.config
                candidate = deepcopy(before)
                table = candidate.setdefault("external_agent_gateway", {})
                allowed = list(table.get("allowed_agent_ids", []))
                denied = list(table.get("denied_agent_ids", []))
                if args.enabled:
                    if allowed and args.agent_id not in allowed:
                        allowed.append(args.agent_id)
                    denied = [item for item in denied if item != args.agent_id]
                    # Preserve an absent/empty allowlist: its native semantics
                    # already admit ordinary Agents and must not narrow others.
                    if "allowed_agent_ids" in table or allowed:
                        table["allowed_agent_ids"] = allowed
                elif args.agent_id not in denied:
                    denied.append(args.agent_id)
                if "denied_agent_ids" in table or denied:
                    table["denied_agent_ids"] = denied
                expected_gateway = _gateway(candidate)

                def mutate(text):
                    updated = remove_toml_table_tree(text, ("external_agent_gateway",))
                    updated = append_toml_table(updated, ("external_agent_gateway",), table)
                    if tomllib.loads(updated) != candidate:
                        raise ValueError("Unexpected gateway configuration delta")
                    return updated

                prepared = prepare_operator_config_transaction(operation_kind=_ACTION,
                    expected_base_hash=args.expected_public_config_hash, mutate_text=mutate,
                    config_path=config_path, native_request=request)

                def verify():
                    from config.settings import get_config
                    self._owners()
                    if (Path(directory.CONFIG_PATH).resolve() != config_path
                            or get_config().external_agent_gateway != expected_gateway):
                        raise ValueError("Reloaded gateway authority changed")
                    _snapshot, _gateway_value, eligibility, observed = self._snapshot(directory, args.agent_id)
                    if (eligibility != "eligible" or observed["eligibilityFingerprint"] != args.expected_eligibility_fingerprint
                            or observed["publicConfigHash"] != prepared.candidate_hash
                            or observed["operatorEnabled"] is not args.enabled):
                        raise ValueError("Gateway configuration could not be verified")

                snapshot.verify_workspace()
                try:
                    apply_operator_config_transaction(prepared, participants=[TransactionParticipant(
                        "agent_dispatch_access_reload", lambda: None, verify, lambda: None)])
                    result = self.receipt(parameters, marker)
                    if result is None:
                        raise ValueError("Final native config proof unavailable")
                except Exception:
                    # The config may already have been visible before rollback.
                    # A missing final proof is never a no-write rejection.
                    raise _error("OPERATION_UNCONFIRMED", 503) from None
                return result
        except OperatorConfigTransactionError:
            raise _error("OPERATION_UNCONFIRMED", 503) from None
        except (OSError, ValueError, TypeError, KeyError):
            raise _error("DISPATCH_ACCESS_UNAVAILABLE", 503) from None
