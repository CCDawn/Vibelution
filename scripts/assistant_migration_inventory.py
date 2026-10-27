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
    modes.add_argument("--recovery-inventory", metavar="ASSISTANT_AGENT_ID",
        help="Read-only disposition of old recovery bindings and temporary grants")
    modes.add_argument("--correlate-handoff", metavar="ASSISTANT_AGENT_ID")
    modes.add_argument("--observe-handoff", metavar="ASSISTANT_AGENT_ID",
        help="Provision a receipt-only whitelist using the target profile's existing native SDK")
    parser.add_argument("--target-profile", type=Path)
    parser.add_argument("--target-config", type=Path,
        help="Existing explicit operator config inside the selected activation profile")
    parser.add_argument("--migration-id")
    parser.add_argument("--path-grants", type=Path)
    parser.add_argument("--source-config", type=Path,
        help="Existing source operator config; required for observation and explicit sandbox selection")
    parser.add_argument("--registered-project-id")
    parser.add_argument("--request-id")
    parser.add_argument("--message-id", action="append", default=[])
    args = parser.parse_args()
    activating = args.activate_personal is not None or args.activate_knowledge is not None
    importing = args.history_import is not None or args.source_import is not None or activating
    observing = args.observe_handoff is not None
    if importing and (args.target_profile is None or args.migration_id is None):
        parser.error("Import requires --target-profile and --migration-id together")
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
        paths = resolve_active_project_storage_paths(args.project.resolve())
        kwargs = dict(project_root=paths.project_root, workspace=paths.data / "workspace",
            project_id=paths.project_id, instance_id=paths.instance_id)
        authority_snapshots, authority_verify, runtime_root = (), None, paths.runtime
        if args.source_config is not None:
            kwargs["workspace"], runtime_root, authority_snapshots, authority_verify = _existing_route(paths, args.source_config)
        if activating:
            from scripts.assistant_migration_activate import activate_in_subprocess
            report = activate_in_subprocess(paths=paths, workspace=kwargs["workspace"],
                agent_id=args.activate_personal or args.activate_knowledge, source_config=args.source_config,
                target_profile=args.target_profile, target_config=args.target_config,
                migration_id=args.migration_id, path_grants=args.path_grants,
                authority_snapshots=authority_snapshots, authority_verify=authority_verify,
                category="knowledge" if args.activate_knowledge is not None else "personal")
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
    raise SystemExit(main())
