"""Internal subprocess boundary for explicit offline personal snapshot activation.

The source-role parent resolves routing. The native-role child consumes only
that frozen authority and rechecks every proof; it must never resolve source
routing through native storage facades. No credentials or source bytes go into
the child environment or the public diagnostic report.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def _capture(project, workspace, scope, grant_path):
    from core.assistant_runtime.migration_inventory import declared_assistant_identities
    from core.assistant_runtime.migration_io import MigrationIOError, read_stable_file, strict_json
    from core.assistant_runtime.migration_paths import resolve_source_paths, source_snapshot
    registry = read_stable_file(workspace / "agents/agents.json", 16 * 1024 * 1024)
    raw = strict_json(registry.raw)
    if not isinstance(raw, dict):
        raise MigrationIOError("invalid_source_registry")
    if not any(row["agentId"] == scope["agentId"] for row in declared_assistant_identities(raw.get("agents"))):
        raise MigrationIOError("assistant_identity_unavailable")
    row = next(row for row in raw["agents"] if row.get("agentId") == scope["agentId"])
    policies = raw.get("memoryPolicies", {})
    if not isinstance(policies, dict):
        raise MigrationIOError("invalid_memory_policy_snapshot")
    grant = read_stable_file(grant_path, 64 * 1024) if grant_path is not None else None
    captured = source_snapshot(resolve_source_paths(project_root=project, workspace=workspace,
        project_id=scope["projectId"], instance_id=scope["instanceId"], agent_row=row,
        memory_policy=policies.get(row.get("memoryPolicyId")),
        grants=strict_json(grant.raw) if grant is not None else None))
    return captured, (registry, grant) if grant is not None else (registry,)


def _snapshot_proof(snapshot):
    return {"path": str(snapshot.path), "sha256": snapshot.sha256, "identity": list(snapshot.identity)}


def _source_proof(captured, authorities):
    def chains(values):
        return {ref: [[str(path), list(identity)] for path, identity in chain] for ref, chain in values.items()}
    return {"report": captured.report, "identities": chains(captured._identities),
        "directories": chains(captured.directoryproofs),
        "files": {ref: [_snapshot_proof(item) for item in snapshots]
                  for ref, snapshots in captured.snapshots.items()},
        "authorities": [_snapshot_proof(item) for item in authorities]}


def _verify_file_proofs(proofs):
    from core.assistant_runtime.migration_io import MigrationIOError, read_stable_file
    for proof in proofs:
        current = read_stable_file(Path(proof["path"]), 16 * 1024 * 1024)
        if _snapshot_proof(current) != proof:
            raise MigrationIOError("source_authority_changed")


def _target(target_profile, target_config):
    from core.assistant_runtime.migration_io import MigrationIOError, check_path, read_stable_file
    target = check_path(target_profile).resolve()
    config = read_stable_file(target_config, 16 * 1024 * 1024)
    if not target.is_dir() or not config.path.resolve().is_relative_to(target):
        raise MigrationIOError("activation_target_config_outside_profile")
    return target, config


def _isolated_environment(target, config):
    # Use a small OS-only allowlist instead of attempting to enumerate every
    # provider credential or inherited Python/runtime override.
    allowed = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "SYSTEMDRIVE",
               "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    private = target / ".offline-activation"
    env.update({"VIBELUTION_PROCESS_ROLE": "launcher_assistant",
        "VIBELUTION_ASSISTANT_NATIVE_ROOT": str(target), "VIBELUTION_DATA_HOME": str(target / "data"),
        "VIBELUTION_CONFIG_PATH": str(config), "VIBELUTION_CONFIG_HOME": str(config.parent),
        "VIBELUTION_PROJECTS_HOME": str(target / "projects"),
        "HOME": str(private / "user"), "USERPROFILE": str(private / "user"),
        "APPDATA": str(private / "user/AppData/Roaming"),
        "LOCALAPPDATA": str(private / "user/AppData/Local"),
        "TEMP": str(private / "tmp"), "TMP": str(private / "tmp"), "TMPDIR": str(private / "tmp"),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
    return env


def activate_in_subprocess(*, paths, workspace, agent_id, source_config, target_profile,
        target_config, migration_id, path_grants, authority_snapshots, authority_verify):
    import re
    import subprocess
    from core.assistant_runtime.migration_active import _selected, _verify_captured
    from core.assistant_runtime import migration_affairs, migration_episodic
    from core.assistant_runtime.migration_io import MigrationIOError, verify_snapshot
    from core.assistant_runtime.migration_paths import _identity_chain
    from core.infrastructure import developer_sandbox
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", migration_id):
        raise MigrationIOError("migration_id_invalid")
    target, config = _target(target_profile, target_config)
    scope = {"projectId": paths.project_id, "instanceId": paths.instance_id, "agentId": agent_id}
    grant_path = path_grants.absolute() if path_grants is not None else None
    captured, selected_authorities = _capture(paths.project_root, workspace, scope, grant_path)
    migration_episodic._parse_rows(_selected(captured, "episodic_memory").raw, agent_id)
    migration_affairs._parse_rows(_selected(captured, "personal_affairs").raw)
    authorities = (*authority_snapshots, *selected_authorities)
    # Refuse overlap before native bootstrap, including external grants and
    # authority files that might otherwise be placed inside the target.
    for root in (paths.project_root, workspace, *captured.paths.values(),
                 *(item.path for item in authorities)):
        resolved = root.resolve()
        if target.is_relative_to(resolved) or resolved.is_relative_to(target):
            raise MigrationIOError("history_source_target_overlap")
    _verify_captured(captured, authorities, authority_verify)
    # Include absence and ancestor identity, so creating/replacing a routing
    # authority cannot hide behind an unchanged selected source directory.
    route_paths = (paths.project_root, workspace, developer_sandbox._active_state_path(paths.project_root))
    route_proof = [[str(path), [[str(node), list(identity)] for node, identity in _identity_chain(path)]]
                   for path in route_paths]
    request = {"schemaVersion": 1, "project": str(paths.project_root), "workspace": str(workspace),
        "scope": scope, "grant": str(grant_path) if grant_path is not None else None,
        "target": str(target), "config": _snapshot_proof(config), "migrationId": migration_id,
        "route": route_proof, "source": _source_proof(captured, authorities)}
    encoded = json.dumps(request, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 8 * 1024 * 1024:
        raise MigrationIOError("activation_proof_too_large")
    verify_snapshot(config)
    try:
        process = subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--offline-child"],
            input=encoded, cwd=ROOT,
            env=_isolated_environment(target, config.path), shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    except (subprocess.TimeoutExpired, OSError):
        # The native import may have committed. Never replay an uncertain
        # outcome; an operator can explicitly reconcile using this migration ID.
        raise MigrationIOError("activation_outcome_unknown") from None
    try:
        from core.assistant_runtime.migration_io import strict_json
        if len(process.stdout) > 64 * 1024:
            raise ValueError("oversized child report")
        result = strict_json(process.stdout)
        if not isinstance(result, dict):
            raise ValueError("invalid child report")
    except ValueError:
        raise MigrationIOError("activation_outcome_unknown") from None
    if process.returncode != 0:
        if result == {"ok": False, "code": "TARGET_PROFILE_BUSY"}:
            raise TimeoutError("profile busy")
        reason = result.get("reason")
        if result.get("code") == "SOURCE_MIGRATION_UNAVAILABLE" and isinstance(reason, str) and re.fullmatch(r"[a-z_]{1,96}", reason):
            raise MigrationIOError(reason)
        raise MigrationIOError("activation_outcome_unknown")
    if (result.get("status") not in {"complete", "partial"} or result.get("readyForCutover") is not False
            or result.get("migrationId") != migration_id or result.get("sourceScope") != scope):
        raise MigrationIOError("activation_outcome_unknown")
    try:
        _verify_captured(captured, authorities, authority_verify)
        verify_snapshot(config)
    except (MigrationIOError, OSError, ValueError):
        # A confirmed child receipt remains useful even when the source moves
        # immediately after a native commit. Keep the per-category evidence.
        mark_reconciliation(result, migration_id, "source_authority_changed")
    return result


def mark_reconciliation(result, migration_id, reason):
    """Preserve committed categories while refusing a complete activation claim."""
    result.update(status="partial", migrationId=migration_id, requiresReconciliation=True,
                  sourceQuiesced=False, readyForCutover=False)
    result.setdefault("reason", reason)
    if reason != "activation_outcome_unknown":
        result["sourceValidation"] = "changed"
    else:
        result["outcomeUnknown"] = True
    return result


def _install_audit(target):
    """Deny network, process escapes and Python writes beyond the target."""
    def audit(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "subprocess.Popen", "os.system",
                     "os.exec", "os.posix_spawn", "os.spawn", "os.startfile"}:
            raise PermissionError("offline_activation_operation_denied")
        if event == "open":
            path, _mode, flags = args
            if isinstance(path, int) or not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                return
            paths = (path,)
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.chown", "os.utime", "os.truncate"}:
            paths = (args[0],)
        elif event in {"os.rename", "os.link", "os.symlink"}:
            paths = args[:2]
        else:
            return
        for path in paths:
            if event == "open" and os.path.normcase(os.fsdecode(path)) == os.path.normcase(os.devnull):
                continue
            if isinstance(path, int) or not Path(os.fsdecode(path)).resolve().is_relative_to(target):
                raise PermissionError("offline_activation_write_denied")
    sys.addaudithook(audit)


def _child():
    # All imports which freeze native identity happen after environment setup
    # and the Python I/O audit hook. The request travels over stdin, not disk.
    target = Path(os.environ["VIBELUTION_ASSISTANT_NATIVE_ROOT"]).resolve()
    _install_audit(target)
    sys.path.insert(0, str(ROOT))
    from core.assistant_runtime.migration_io import MigrationIOError, strict_json
    result, request, activation_started = None, None, False
    try:
        raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise MigrationIOError("activation_proof_too_large")
        request = strict_json(raw)
        if request.get("schemaVersion") != 1 or request["target"] != str(target):
            raise MigrationIOError("activation_request_invalid")
        _target(target, Path(request["config"]["path"]))
        _verify_file_proofs([request["config"]])
        from core.assistant_runtime.migration_paths import _identity_chain
        def verify_route():
            _verify_file_proofs(request["source"]["authorities"])
            for path, chain in request["route"]:
                current = [[str(node), list(identity)] for node, identity in _identity_chain(Path(path))]
                if current != chain:
                    raise MigrationIOError("source_routing_changed")
        verify_route()
        captured, selected = _capture(Path(request["project"]), Path(request["workspace"]),
            request["scope"], Path(request["grant"]) if request["grant"] else None)
        from core.assistant_runtime.migration_io import read_stable_file
        authorities = tuple(read_stable_file(Path(row["path"]), 16 * 1024 * 1024)
                            for row in request["source"]["authorities"])
        if _source_proof(captured, authorities) != request["source"]:
            raise MigrationIOError("source_snapshot_changed")
        from core.assistant_runtime.migration_active import activate_personal_snapshot
        from core.assistant_runtime.migration_profile import offline_migration_profile
        for key in ("HOME", "APPDATA", "LOCALAPPDATA", "TEMP", "VIBELUTION_PROJECTS_HOME"):
            Path(os.environ[key]).mkdir(parents=True, exist_ok=True)
        with offline_migration_profile() as lease:
            activation_started = True
            result = activate_personal_snapshot(lease, captured, migration_id=request["migrationId"],
                source_roots=(Path(request["project"]), Path(request["workspace"])),
                authority_snapshots=authorities, authority_verify=verify_route)
            result["migrationId"] = request["migrationId"]
        verify_route()
        _verify_file_proofs([request["config"]])
    except TimeoutError:
        if result is not None and result.get("status") in {"complete", "partial"}:
            mark_reconciliation(result, request["migrationId"], "activation_outcome_unknown")
        elif activation_started:
            result = {"ok": False, "code": "SOURCE_MIGRATION_UNAVAILABLE", "reason": "activation_outcome_unknown"}
        else:
            result = {"ok": False, "code": "TARGET_PROFILE_BUSY"}
    except MigrationIOError as error:
        if result is not None and result.get("status") in {"complete", "partial"}:
            mark_reconciliation(result, request["migrationId"], str(error))
        else:
            result = {"ok": False, "code": "SOURCE_MIGRATION_UNAVAILABLE", "reason": str(error)}
    except Exception:
        if result is not None and result.get("status") in {"complete", "partial"}:
            mark_reconciliation(result, request["migrationId"], "activation_outcome_unknown")
        else:
            result = {"ok": False, "code": "SOURCE_MIGRATION_UNAVAILABLE", "reason": "activation_outcome_unknown"}
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result.get("ok") is False else 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--offline-child"]:
        raise SystemExit("Use assistant_migration_inventory.py --activate-personal")
    raise SystemExit(_child())
