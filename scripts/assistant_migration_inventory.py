#!/usr/bin/env python3
"""Inventory, explicit immutable history import and operator source snapshots.

Import flags write only the explicitly selected target profile. They never
activate old queues/plugins, freeze a source, or retire a platform assistant.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.assistant_runtime.migration_inventory import InventoryError, inventory_sources
from core.assistant_runtime.migration_io import MigrationIOError, read_stable_file, strict_json, verify_snapshot
from vibelution_storage import resolve_active_project_storage_paths


def _existing_route(paths, config_path):
    """Read the selected config/sandbox authority without creating any state."""
    from types import SimpleNamespace
    from config.public_config import read_existing_config_snapshot
    from core.infrastructure import developer_sandbox
    from core.assistant_runtime.migration_io import check_path
    from core.web.services.external_management.state_snapshot import ExistingStateSnapshot
    config = read_stable_file(config_path, 16 * 1024 * 1024)
    public = read_existing_config_snapshot(config.path)
    lexical = developer_sandbox.existing_sandboxed_workspace_path(paths.project_root, public_config=public)
    check_path(lexical)  # Before the native resolver normalizes the path.
    state = ExistingStateSnapshot(paths.project_root, SimpleNamespace(CONFIG_PATH=config.path), pin_workspace=True)
    active = developer_sandbox._active_state_path(paths.project_root)
    snapshots = [config]
    if active.exists() or active.is_symlink():
        snapshots.append(read_stable_file(active, 64 * 1024))
    def verify():
        for snapshot in snapshots:
            verify_snapshot(snapshot)
        state.verify_workspace()
        if not any(snapshot.path == active for snapshot in snapshots) and (active.exists() or active.is_symlink()):
            raise MigrationIOError("source_routing_changed")
        check_path(lexical)
        if lexical.resolve() != state.path():
            raise MigrationIOError("source_routing_changed")
    verify()
    runtime = lexical.parent / ".runtime" if public.get("launcher", {}).get("developer_mode", {}).get("enabled", False) else paths.runtime
    return state.path(), runtime, tuple(snapshots), verify


def _bound_route(paths, config_path, *, formal_home=None):
    """Bind a disabled developer route to source-owned paths and snapshots."""
    from config.paths import resolve_configured_data_home
    from config.public_config import read_existing_config_snapshot
    from core.assistant_runtime.migration_io import check_path
    from core.assistant_runtime.migration_paths import _identity_chain
    config = read_stable_file(config_path, 16 * 1024 * 1024)
    public = read_existing_config_snapshot(config.path)
    launcher = public.get('launcher', {})
    settings = launcher.get('developer_mode', {}) if isinstance(launcher, dict) else None
    if not isinstance(settings, dict) or type(settings.get('enabled', False)) is not bool:
        raise MigrationIOError('source_routing_changed')
    if settings.get('enabled', False):
        raise MigrationIOError('source_developer_mode_unverified')
    configured = resolve_configured_data_home(config_path=config.path) if formal_home is None else None
    formal = ((Path(formal_home) / 'workspace') if formal_home is not None else
              (configured / 'workspace').resolve() if configured is not None else paths.workspace)
    check_path(formal)
    if not formal.is_dir():
        raise MigrationIOError('source_routing_changed')
    workspace = formal.resolve()
    active = paths.runtime / 'developer-mode/active.json'
    active_chain = _identity_chain(active)
    active_snapshot = read_stable_file(active, 64 * 1024) if active.exists() or active.is_symlink() else None
    snapshots = (config, *((active_snapshot,) if active_snapshot is not None else ()))
    def verify():
        for snapshot in snapshots:
            verify_snapshot(snapshot)
        if active_snapshot is None and (active.exists() or active.is_symlink()):
            raise MigrationIOError('source_routing_changed')
        if _identity_chain(active) != active_chain:
            raise MigrationIOError('source_routing_changed')
        check_path(formal)
        if not formal.is_dir() or formal.resolve() != workspace:
            raise MigrationIOError('source_routing_changed')
    verify()
    return workspace, paths.runtime, snapshots, verify


def _initial_offline():
    """Private main-only entry; no path, operation or approval is accepted in argv."""
    import os
    from core.assistant_runtime.migration_io import check_path
    from core.assistant_runtime.initial_migration_binding import (read_initial_intent, source_identity,
        target_identity, authority_identity)
    from scripts.assistant_migration_activate import (initial_binding, storage_authority,
        activate_in_subprocess, prepare_initial_model_config, _assert_source_target_disjoint)
    token = os.environ.pop("VIBELUTION_INITIAL_MIGRATION_TOKEN", "")
    url = os.environ.pop("VIBELUTION_INITIAL_MIGRATION_URL", "")
    operation_id = None
    try:
        match = re.fullmatch(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})", url)
        if match is None:
            raise MigrationIOError("initial_channel_invalid")
        port = int(match.group(1))
        bound = initial_binding(port, token)
        operation_id = bound["operationId"]
        for key in ("projectRoot", "sourceConfig", "targetProfile"):
            path = check_path(Path(bound[key]))
            if path.resolve() != path:
                raise MigrationIOError("initial_channel_binding_invalid")
        target = Path(bound["targetProfile"])
        intent = read_initial_intent(target, operation_id)
        if (intent is None or intent["registeredProjectId"] != bound["registeredProjectId"]
                or intent["revision"] > bound["revision"]):
            raise MigrationIOError("initial_migration_binding_changed")
        if str(os.environ.get("VIBELUTION_DATA_HOME") or "").strip():
            raise MigrationIOError("source_environment_unverified")
        paths, storage, verify_storage = storage_authority(Path(bound["projectRoot"]), Path(bound["sourceConfig"]))
        workspace, _, routing, verify_routing = _bound_route(paths, Path(bound["sourceConfig"]))
        scope = intent["sourceScope"]
        if (scope["projectId"] != paths.project_id or scope["instanceId"] != paths.instance_id):
            raise MigrationIOError("initial_migration_binding_changed")
        _assert_source_target_disjoint(target, (paths.project_root, paths.data, workspace.parent,
                                                 workspace, Path(bound["sourceConfig"])))
        def verify():
            verify_storage()
            verify_routing()
            verify_storage()
        verify()
        registry = read_stable_file(workspace / "agents/agents.json", 16 * 1024 * 1024)
        sd, project_id, workspace_id = source_identity(scope, paths.project_root, workspace)
        td, target_id = target_identity(target, intent["targetAgentId"], intent["targetSessionId"])
        if (sd != intent["sourceIdentityDigest"] or project_id != intent["projectDirectory"]
                or workspace_id != intent["workspaceDirectory"] or authority_identity((*routing, registry, *storage)) != intent["registryDigest"]
                or td != intent["targetIdentityDigest"] or target_id != intent["targetDirectory"]):
            raise MigrationIOError("initial_migration_binding_changed")
        target_config = prepare_initial_model_config(Path(bound["sourceConfig"]), target,
            Path(bound["targetConfig"]), operation_id, intent["registryDigest"])
        verify()
        report = activate_in_subprocess(paths=paths, workspace=workspace, agent_id=scope["agentId"],
            source_config=Path(bound["sourceConfig"]), target_profile=target,
            target_config=target_config, migration_id=operation_id, path_grants=None,
            authority_snapshots=(*storage, *routing), authority_verify=verify, category=intent["category"],
            initial_control={"binding": bound, "port": port, "token": token})
        state = "completed" if report.get("status") == "complete" and not report.get("requiresReconciliation") else "partial"
        print(json.dumps({"schemaVersion": 1, "operationId": operation_id, "state": state, "readyForCutover": False}))
        return 0
    except Exception:
        # The main process must reconcile the original ID after a lost child;
        # never fabricate a new ID or automatically replay it here.
        valid = isinstance(operation_id, str) and re.fullmatch(r"initial-[a-f0-9]{40}", operation_id)
        print(json.dumps({"schemaVersion": 1, "operationId": operation_id if valid else None,
                          "state": "unknown" if valid else "unavailable", "readyForCutover": False}))
        return 1


def _initial_list(arguments):
    """Read only native intent identities; malformed state is never an empty list."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--initial-list", action="store_true", required=True)
    parser.add_argument("--target-profile", type=Path, required=True)
    args = parser.parse_args(arguments)
    try:
        from core.assistant_runtime.initial_migration_binding import list_initial_intents
        from core.assistant_runtime.migration_io import check_path, pinned_mutable_file, pinned_target_directory
        from core.infrastructure.file_lock import locked_sidecar
        from scripts.assistant_migration_activate import _initial_receipts_or_claim
        target = check_path(args.target_profile)
        if target.resolve() != target:
            raise MigrationIOError("initial_target_invalid")
        with pinned_target_directory(target), pinned_mutable_file(target / "host-owner.lock", create=False), \
                locked_sidecar(target / "host-owner", timeout=0):
            rows = list_initial_intents(target)
            output = [{**{key: row[key] for key in ("operationId", "registeredProjectId", "category", "registryDigest")},
                "state": "claimed_unknown" if _initial_receipts_or_claim(target, row["operationId"], row["category"])
                         else "dispatchable"} for row in rows]
        print(json.dumps({"schemaVersion": 1, "intents": output}))
        return 0
    except Exception:
        print(json.dumps({"schemaVersion": 1, "error": "initial_intents_unavailable"}))
        return 1


def _initial_verify(arguments):
    """Read-only business receipt verification after main has drained the Job."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--initial-verify", action="store_true", required=True)
    parser.add_argument("--target-profile", type=Path, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args(arguments)
    valid = re.fullmatch(r"initial-[a-f0-9]{40}", args.operation_id)
    result = {"schemaVersion": 1, "operationId": args.operation_id if valid else None,
              "state": "unknown", "readyForCutover": False}
    try:
        from core.assistant_runtime.migration_io import check_path, pinned_mutable_file, pinned_target_directory
        from core.infrastructure.file_lock import locked_sidecar
        from scripts.assistant_migration_activate import (verify_initial_personal_receipts,
            verify_initial_knowledge_receipts)
        from core.assistant_runtime.initial_migration_binding import read_initial_intent
        target = check_path(args.target_profile)
        if not valid or target.resolve() != target:
            raise MigrationIOError("initial_receipts_unknown")
        with pinned_target_directory(target), pinned_mutable_file(target / "host-owner.lock", create=False), \
                locked_sidecar(target / "host-owner", timeout=0):
            intent = read_initial_intent(target, args.operation_id)
            if intent is None:
                raise MigrationIOError("initial_receipts_unknown")
            if intent["category"] == "personal":
                verify_initial_personal_receipts(target, args.operation_id, allow_partial=args.allow_partial)
            elif intent["category"] == "knowledge":
                verify_initial_knowledge_receipts(target, args.operation_id)
            else:
                raise MigrationIOError("initial_receipts_unknown")
        # A partial receipt proves at least one historical write only. The
        # caller must separately own the drained Job and its partial result.
        result["state"] = "confirmed_partial" if args.allow_partial else "confirmed_completed"
        print(json.dumps(result))
        return 0
    except Exception:
        print(json.dumps(result))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--handoff-preview", metavar="ASSISTANT_AGENT_ID",
        help="Read-only legacy dispatch preview for this explicit PA identity")
    modes.add_argument("--history-preview", metavar="ASSISTANT_AGENT_ID")
    modes.add_argument("--history-import", metavar="ASSISTANT_AGENT_ID")
    modes.add_argument("--source-paths", metavar="ASSISTANT_AGENT_ID")
    modes.add_argument("--source-import", metavar="ASSISTANT_AGENT_ID",
        help="Copy approved data to an immutable archive, never active plugin/queue state")
    modes.add_argument("--activate-personal", metavar="ASSISTANT_AGENT_ID",
        help="Offline import of explicit episodic/affairs snapshots into an isolated native profile")
    modes.add_argument("--activate-knowledge", metavar="ASSISTANT_AGENT_ID",
        help="Offline import of proven private formal knowledge into a native profile")
    modes.add_argument("--prepare-affairs-conflicts", metavar="ASSISTANT_AGENT_ID",
        help="Offline archive a verified source snapshot and preserve ambiguous affairs changes")
    modes.add_argument("--sync-affairs", metavar="ASSISTANT_AGENT_ID",
        help="Offline reconcile non-conflicting changes from a verified affairs snapshot")
    modes.add_argument("--recovery-inventory", metavar="ASSISTANT_AGENT_ID",
        help="Read-only disposition of old recovery bindings and temporary grants")
    modes.add_argument("--correlate-handoff", metavar="ASSISTANT_AGENT_ID")
    modes.add_argument("--observe-handoff", metavar="ASSISTANT_AGENT_ID",
        help="Provision a receipt-only whitelist using the target profile's existing native SDK")
    parser.add_argument("--target-profile", type=Path)
    parser.add_argument("--target-config", type=Path,
        help="Existing explicit operator config inside the selected activation profile")
    parser.add_argument("--migration-id")
    parser.add_argument("--baseline-migration-id", help="Published baseline personal import for affairs conflict preparation")
    parser.add_argument("--path-grants", type=Path)
    parser.add_argument("--source-config", type=Path,
        help="Existing source operator config; required for observation and explicit sandbox selection")
    parser.add_argument("--registered-project-id")
    parser.add_argument("--request-id")
    parser.add_argument("--message-id", action="append", default=[])
    args = parser.parse_args()
    activating = (args.activate_personal is not None or args.activate_knowledge is not None
                  or args.prepare_affairs_conflicts is not None or args.sync_affairs is not None)
    importing = args.history_import is not None or args.source_import is not None or activating
    observing = args.observe_handoff is not None
    if importing and (args.target_profile is None or args.migration_id is None):
        parser.error("Import requires --target-profile and --migration-id together")
    if ((args.prepare_affairs_conflicts is None and args.sync_affairs is None)
            != (args.baseline_migration_id is None)):
        parser.error("--baseline-migration-id is required only with affairs preparation or sync")
    if args.source_import is not None and args.source_config is None:
        parser.error("Source import requires --source-config")
    if activating and (args.target_config is None or args.source_config is None):
        parser.error("Activation requires --source-config and an existing --target-config inside --target-profile")
    if not activating and args.target_config is not None:
        parser.error("Target config requires --activate-personal or --activate-knowledge")
    if not importing and not observing and (args.target_profile is not None or args.migration_id is not None):
        parser.error("Target options require an explicit import mode")
    if observing and (args.target_profile is None or args.migration_id is not None
                      or not args.registered_project_id or not args.request_id or not args.message_id or args.source_config is None):
        parser.error("Observation requires --target-profile, --source-config, --registered-project-id, --request-id and --message-id")
    if not observing and (args.registered_project_id or args.request_id or args.message_id):
        parser.error("Observer options require --observe-handoff")
    if args.path_grants is not None and args.source_paths is None and args.source_import is None and not activating:
        parser.error("Path grants apply only to source-paths/source-import or activation")
    try:
        if activating:
            from core.infrastructure.native_runtime import is_launcher_assistant_process
            if is_launcher_assistant_process():
                raise MigrationIOError("activation_requires_source_process")
        storage_snapshots, verify_storage = (), None
        if activating or args.source_import is not None:
            import os
            if str(os.environ.get('VIBELUTION_DATA_HOME') or '').strip():
                raise MigrationIOError('source_environment_unverified')
            from scripts.assistant_migration_activate import storage_authority
            paths, storage_snapshots, verify_storage = storage_authority(args.project.resolve(), args.source_config)
        else:
            paths = resolve_active_project_storage_paths(args.project.resolve(), config_path=args.source_config)
        kwargs = dict(project_root=paths.project_root, workspace=paths.data / "workspace",
            project_id=paths.project_id, instance_id=paths.instance_id)
        authority_snapshots, authority_verify, runtime_root = (), None, paths.runtime
        if args.source_config is not None:
            route = _bound_route if verify_storage is not None else _existing_route
            kwargs["workspace"], runtime_root, authority_snapshots, authority_verify = route(paths, args.source_config)
        if verify_storage is not None:
            route_verify = authority_verify
            def verify_all():
                verify_storage()
                route_verify()
                verify_storage()
            authority_verify = verify_all
            authority_snapshots = (*storage_snapshots, *authority_snapshots)
        if activating:
            from scripts.assistant_migration_activate import activate_in_subprocess
            report = activate_in_subprocess(paths=paths, workspace=kwargs["workspace"],
                agent_id=args.activate_personal or args.activate_knowledge or args.prepare_affairs_conflicts or args.sync_affairs, source_config=args.source_config,
                target_profile=args.target_profile, target_config=args.target_config,
                migration_id=args.migration_id, path_grants=args.path_grants,
                authority_snapshots=authority_snapshots, authority_verify=authority_verify,
                category=("knowledge" if args.activate_knowledge is not None else "affairs_sync" if args.sync_affairs is not None else
                          "affairs_conflicts" if args.prepare_affairs_conflicts is not None else "personal"),
                baseline_migration_id=args.baseline_migration_id)
        elif observing:
            import anyio
            from core.assistant_runtime.dispatch import DispatchService
            from core.assistant_runtime.migration_history import _canonical_target
            from core.assistant_runtime.migration_io import pinned_target_directory, pinned_mutable_file
            from core.infrastructure.file_lock import cross_process_file_lock
            target = _canonical_target(args.target_profile)
            for root in (paths.project_root, kwargs["workspace"]):
                if target.is_relative_to(root.resolve()) or root.resolve().is_relative_to(target):
                    raise MigrationIOError("history_target_overlaps_source")
            registry = read_stable_file(kwargs["workspace"] / "agents/agents.json", 16 * 1024 * 1024)
            from types import SimpleNamespace
            from core.web.services.external_management.legacy_native import LegacyNativeGateway
            prepared = LegacyNativeGateway(paths.project_root, SimpleNamespace(CONFIG_PATH=args.source_config)).snapshot(
                {"projectId": paths.project_id, "instanceId": paths.instance_id}, args.observe_handoff,
                sorted(set(args.message_id)), registry.sha256)
            async def observe():
                authority_verify()
                prepared.verify()
                verify_snapshot(registry)
                service = DispatchService(target, {args.registered_project_id: paths.project_root})
                return await service._call(args.registered_project_id, lambda client:
                    client.management_legacy_observer_create(request_id=args.request_id,
                        source_agent_id=args.observe_handoff, legacy_message_ids=sorted(set(args.message_id)),
                        expected_registry_sha256=registry.sha256,
                        expected_source_authority=prepared.data["sourceAuthority"]))
            # Use the native profile owner lock. Offline migration must never
            # compete with a resident host writing the same SDK credential state.
            with pinned_target_directory(target), pinned_mutable_file(target / "host-owner.lock"), \
                    cross_process_file_lock(target / "host-owner", timeout=0):
                report = anyio.run(observe)
                prepared.verify()
                authority_verify()
                verify_snapshot(registry)
        elif args.history_preview is not None or args.history_import is not None:
            from core.assistant_runtime.migration_history import discover_history, import_history
            found = discover_history(**kwargs, assistant_agent_id=args.history_preview or args.history_import)
            report = found.report
            if args.history_import is not None:
                report = {**report, "import": import_history(found, args.target_profile, args.migration_id,
                    authority_verify=authority_verify)}
        elif args.source_paths is not None or args.source_import is not None:
            from core.assistant_runtime.migration_inventory import declared_assistant_identities
            from core.assistant_runtime.migration_paths import resolve_source_paths, source_snapshot
            registry = read_stable_file(kwargs["workspace"] / "agents/agents.json", 16 * 1024 * 1024)
            raw = strict_json(registry.raw)
            if not isinstance(raw, dict):
                raise MigrationIOError("invalid_source_registry")
            aid = args.source_paths or args.source_import
            identities = declared_assistant_identities(raw.get("agents"))
            if not any(row["agentId"] == aid for row in identities):
                raise MigrationIOError("assistant_identity_unavailable")
            row = next(row for row in raw["agents"] if row["agentId"] == aid)
            policies = raw.get("memoryPolicies", {})
            if not isinstance(policies, dict):
                raise MigrationIOError("invalid_memory_policy_snapshot")
            grant = read_stable_file(args.path_grants.absolute(), 64 * 1024) if args.path_grants is not None else None
            resolved = resolve_source_paths(**kwargs, agent_row=row,
                memory_policy=policies.get(row.get("memoryPolicyId")),
                grants=strict_json(grant.raw) if grant is not None else None)
            captured = source_snapshot(resolved)
            verify_snapshot(registry)
            if grant is not None:
                verify_snapshot(grant)
            report = captured.report
            if args.source_import is not None:
                from core.assistant_runtime.migration_source_archive import import_source_snapshots
                from core.assistant_runtime.migration_io import pinned_source_files
                with pinned_source_files(storage_snapshots):
                    authority_verify()
                    report = {**report, "import": import_source_snapshots(captured, args.target_profile, args.migration_id,
                        source_roots=(paths.project_root, kwargs["workspace"]),
                        authority_snapshots=authority_snapshots + ((registry, grant) if grant is not None else (registry,)),
                        authority_verify=authority_verify)}
                verify_snapshot(registry)
                if grant is not None:
                    verify_snapshot(grant)
        elif args.recovery_inventory is not None:
            from core.assistant_runtime.migration_inventory import declared_assistant_identities
            from core.assistant_runtime.migration_recovery_bindings import inventory_recovery_bindings, verify_recovery_inventory
            registry = read_stable_file(kwargs["workspace"] / "agents/agents.json", 16 * 1024 * 1024)
            raw = strict_json(registry.raw)
            if not isinstance(raw, dict) or not any(
                    row["agentId"] == args.recovery_inventory for row in declared_assistant_identities(raw.get("agents"))):
                raise MigrationIOError("assistant_identity_unavailable")
            row = next(row for row in raw["agents"] if row.get("agentId") == args.recovery_inventory)
            inventory = inventory_recovery_bindings(workspace=kwargs["workspace"], agent_id=args.recovery_inventory,
                project_id=kwargs["project_id"], instance_id=kwargs["instance_id"],
                agent_row=row, project_root=kwargs["project_root"])
            verify_recovery_inventory(inventory)
            verify_snapshot(registry)
            report = {"stage": "recovery_inventory", **inventory.report}
        elif args.handoff_preview is not None or args.correlate_handoff is not None:
            from core.assistant_runtime.legacy_handoff import preview_legacy_handoff
            report = preview_legacy_handoff(**kwargs, assistant_agent_id=args.handoff_preview or args.correlate_handoff)
            if args.correlate_handoff is not None:
                from core.assistant_runtime.legacy_correlation import correlate_legacy_dispatches
                report = correlate_legacy_dispatches(report, workspace=kwargs["workspace"], runtime_root=runtime_root)
        else:
            report = inventory_sources(**kwargs)
        if authority_verify is not None:
            if activating:
                try:
                    authority_verify()
                except (MigrationIOError, OSError, ValueError):
                    from scripts.assistant_migration_activate import mark_reconciliation
                    mark_reconciliation(report, args.migration_id, "source_authority_changed")
            else:
                authority_verify()
    except MigrationIOError as error:
        failure = {"ok": False, "code": "SOURCE_MIGRATION_UNAVAILABLE", "reason": str(error)}
        if activating and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", args.migration_id):
            failure["migrationId"] = args.migration_id
            if str(error) == "activation_outcome_unknown":
                failure.update(outcomeUnknown=True, requiresReconciliation=True)
        print(json.dumps(failure))
        return 1
    except TimeoutError:
        print(json.dumps({"ok": False, "code": "TARGET_PROFILE_BUSY"}))
        return 1
    except Exception as error:
        from core.assistant_runtime.dispatch import DispatchError
        from core.web.services.external_management.service import ManagementError
        if isinstance(error, (DispatchError, ManagementError)):
            print(json.dumps({"ok": False, "code": error.code}))
            return 1
        if not isinstance(error, (InventoryError, OSError, ValueError)):
            raise
        print(json.dumps({"ok": False, "code": "SOURCE_INVENTORY_UNAVAILABLE"}))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    arguments = sys.argv[1:]
    raise SystemExit(_initial_offline() if arguments == ["--initial-offline"] else
                     _initial_list(arguments) if "--initial-list" in arguments else
                     _initial_verify(arguments) if "--initial-verify" in arguments else main())
