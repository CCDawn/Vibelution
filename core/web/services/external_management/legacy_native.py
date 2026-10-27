"""Target-owned existing-state adapter for whitelisted legacy receipt observation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.assistant_runtime.legacy_correlation import correlate_legacy_dispatches
from core.assistant_runtime.legacy_handoff import ObservationPreview, preview_legacy_observation
from core.assistant_runtime.migration_io import check_path, path_identity, read_stable_file, strict_json, verify_snapshot

from .contracts import LegacyDispatchView
from .service import ManagementError
from .state_snapshot import ExistingStateSnapshot
from .store import digest


@dataclass(frozen=True)
class PreparedObservation:
    data: dict
    verify: Callable[[], None]


class LegacyNativeGateway:
    def __init__(self, project_root, directory, *, runtime_root=None):
        self.project_root, self.directory = Path(project_root), directory
        self.runtime_root = Path(runtime_root) if runtime_root is not None else None

    def _runtime(self, state, workspace):
        """Match the native WorkRun owner without ensuring a runtime or sandbox."""
        if self.runtime_root is not None:
            candidate, kind = self.runtime_root, "explicit"
        else:
            setting = state.config.get("launcher", {}).get("developer_mode", {})
            if not isinstance(setting, dict) or type(setting.get("enabled", False)) is not bool:
                return None, None, "runtime_authority_unproven"
            if setting.get("enabled", False):
                # existing_sandboxed_workspace_path already validates the active
                # sandbox token and its workspace; native WorkRunStore uses
                # that exact sandbox root/.runtime (no seeding is needed).
                from core.infrastructure.developer_sandbox import existing_sandboxed_workspace_path
                lexical_workspace = existing_sandboxed_workspace_path(self.project_root, public_config=state.config)
                try:
                    check_path(lexical_workspace)
                except (OSError, ValueError):
                    return None, None, "runtime_authority_unproven"
                if lexical_workspace.name != "workspace" or lexical_workspace.resolve() != workspace:
                    return None, None, "runtime_authority_unproven"
                candidate, kind = lexical_workspace.parent / ".runtime", "sandbox"
            else:
                from vibelution_storage import resolve_project_runtime_home
                candidate, kind = resolve_project_runtime_home(self.project_root), "formal"
        authority = [kind, str(candidate).casefold()]
        try:
            check_path(candidate)
            if not candidate.is_dir():
                return None, authority, "runtime_root_unavailable"
        except (OSError, ValueError):
            return None, authority, "runtime_root_unavailable"
        return candidate, authority, "runtime_root_not_supplied"

    def snapshot(self, binding, source_agent_id, legacy_message_ids, expected_registry_sha256=None):
        try:
            state = ExistingStateSnapshot(self.project_root, self.directory, pin_workspace=True)
            workspace = state.path()
            check_path(workspace)
            workspace_stamp = path_identity(workspace)
            runtime_root, runtime_authority, runtime_reason = self._runtime(state, workspace)
            source_authority = digest([str(workspace).casefold(), workspace_stamp[0], workspace_stamp[1],
                                       workspace_stamp[4], workspace_stamp[5], runtime_authority])
            registry = read_stable_file(workspace / "agents/agents.json", 16 * 1024 * 1024)
            payload = strict_json(registry.raw)
            agents = payload.get("agents") if isinstance(payload, dict) else None
            if not isinstance(agents, list) or len(agents) > 256:
                raise ValueError("Invalid source authority")
            sources = [row for row in agents if isinstance(row, dict) and row.get("agentId") == source_agent_id]
            if len(sources) != 1:
                raise ManagementError("LEGACY_SOURCE_CHANGED", 409)
            source = sources[0]
            identity = {"agentId": source_agent_id, "sessionId": source.get("directSessionId"),
                        "roleKey": source.get("roleKey"),
                        "profile": (source.get("metadata") or {}).get("personalAssistantProfile")}
            if identity["roleKey"] != "personal_assistant" or identity["profile"] != "personal_assistant_v1":
                raise ManagementError("LEGACY_SOURCE_CHANGED", 409)
            if expected_registry_sha256 is not None and registry.sha256 != expected_registry_sha256:
                raise ManagementError("LEGACY_REGISTRY_CHANGED", 409)
            observation = preview_legacy_observation(project_root=self.project_root, workspace=workspace,
                project_id=binding["projectId"], instance_id=binding["instanceId"], assistant_agent_id=source_agent_id,
                legacy_message_ids=legacy_message_ids)
            preview = observation.report
            if any(issue["code"] == "observation_reference_unavailable" for issue in preview["issues"]):
                raise ManagementError("LEGACY_REFERENCE_UNAVAILABLE", 409)
            if not preview["observationComplete"] or preview["registrySha256"] != registry.sha256:
                raise ManagementError("LEGACY_SOURCE_UNAVAILABLE", 503)
            available = {row["legacyMessageId"]: row for row in preview["dispatches"]}
            if any(ref not in available for ref in legacy_message_ids):
                raise ManagementError("LEGACY_REFERENCE_UNAVAILABLE", 409)
            selected = [available[ref] for ref in legacy_message_ids]
            filtered = ObservationPreview({**preview, "dispatches": selected}, observation.absences)
            correlated = correlate_legacy_dispatches(filtered, workspace=workspace, runtime_root=runtime_root)
            if correlated["issues"] or len(correlated["dispatches"]) != len(selected):
                raise ManagementError("LEGACY_SOURCE_UNAVAILABLE", 503)
            views, bindings = [], []
            for original, row in zip(selected, correlated["dispatches"], strict=True):
                if (row["sourceAgentId"] != source_agent_id or row["sourceSessionId"] != identity["sessionId"]
                        or row["reason"] in {"dispatch_identity_mismatch", "dispatch_source_missing", "dispatch_routing_mismatch",
                                             "receipt_routing_mismatch", "receipt_turn_mismatch", "consumed_identity_mismatch"}):
                    raise ManagementError("LEGACY_SOURCE_CHANGED", 409)
                receipts = original["receipts"]
                view = {key: row[key] for key in ("legacyMessageId", "targetAgentId", "targetSessionId", "businessTaskStatus",
                    "nativeCorrelation", "nativeTurnId", "nativeRunId", "nativeTaskId", "nativeTurnStatus", "reason")}
                view.update(receipts=receipts[-32:], receiptCount=len(receipts), receiptsTruncated=len(receipts) > 32)
                view["nativeRunReason"] = row.get("nativeRunReason", "native_turn_unresolved")
                if view["nativeRunReason"] == "runtime_root_not_supplied":
                    view["nativeRunReason"] = runtime_reason
                views.append(LegacyDispatchView.model_validate(view).model_dump())
                bindings.append({key: row[key] for key in ("legacyMessageId", "targetAgentId", "targetSessionId", "nativeTurnId")})
            # Retain stable bytes only inside the target preparation. Neither the
            # subject proof nor any transport contains source files or paths.
            snapshots = [registry]
            for item in preview["sources"]:
                snapshot = read_stable_file(workspace / "agents" / item["agentId"] / "events/agent_inbox_messages.jsonl", 8 * 1024 * 1024)
                if snapshot.sha256 != item["sha256"]:
                    raise ValueError("Source changed")
                snapshots.append(snapshot)
            for sid in sorted({row["targetSessionId"] for row in views if row["nativeTurnId"] is not None}):
                snapshots.append(read_stable_file(workspace / "sessions" / sid / "turn_journal.jsonl", 8 * 1024 * 1024))
            # Bind the retained Journal bytes to the exact correlation that was
            # projected. A mutation between projection and capture cannot mint
            # an observation proof for stale native identities.
            if correlate_legacy_dispatches(filtered, workspace=workspace, runtime_root=runtime_root) != correlated:
                raise ManagementError("LEGACY_SOURCE_CHANGED", 409)
            def verify():
                try:
                    state.verify_workspace()
                    if path_identity(workspace)[0:2] != workspace_stamp[0:2]:
                        raise ValueError("Workspace identity changed")
                    _current_runtime, authority, _reason = self._runtime(state, workspace)
                    if authority != runtime_authority:
                        raise ValueError("Runtime authority changed")
                    for snapshot in snapshots:
                        verify_snapshot(snapshot)
                    for absent in observation.absences:
                        absent.verify(workspace)
                    state.verify_workspace()
                except (OSError, ValueError, TypeError):
                    raise ManagementError("LEGACY_SOURCE_CHANGED", 409) from None
            verify()
            return PreparedObservation({"sourceIdentity": identity, "sourceAuthority": source_authority, "registrySha256": registry.sha256,
                "dispatchBindings": bindings, "dispatches": views}, verify)
        except ManagementError:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise ManagementError("LEGACY_SOURCE_UNAVAILABLE", 503) from None
