"""Existing Team knowledge-base metadata, without provisioning or Agent ACL claims.

This target-side reader is not wired to any transport. A future caller must
independently authorize both knowledge:catalog:read and teams:directory:read.
The canonical metadata JSON physically includes descriptions and ACLs; it is
decoded as a whole, but only ID/name/status are projected. No knowledge body,
statistics, proposal or Agent-owned knowledge source is opened.
"""
from __future__ import annotations

from pathlib import Path, PureWindowsPath
from contextlib import ExitStack
import os
import tomllib

import vibelution_storage as storage
from config import paths as config_paths
from core.web.services.team.kind_helpers import SYSTEM_MANAGED_TEAM_IDS

from core.assistant_runtime.migration_io import check_path, pinned_source_files, read_stable_file, strict_json
from core.infrastructure import developer_sandbox
from core.web.services.personal_assistant_project.windows_read import _locked_source

from .service import ManagementError
from .state_snapshot import ExistingStateSnapshot
from .workspace_queries import _identity, _teams, _text


_METADATA_LIMIT = 8_000_000
_MAX_BASES = 10_000
REQUIRED_SCOPES = ("knowledge:catalog:read", "teams:directory:read")
_COVERAGE = ("Existing metadata for one validated ordinary active Team only; the metadata JSON contains ACL and descriptions, "
             "which are decoded but never returned or used as Agent authorization. No bodies, statistics or Agent libraries are read.")


class _Sources(ExistingStateSnapshot):
    """Record exact, bounded authority snapshots without resolving away links."""

    def __init__(self, root, directory, workspace):
        self.snapshots = []
        self.project_root, self.directory = root, directory
        self.lexical_root = workspace
        check_path(workspace)
        self._workspace_root = workspace.resolve()

    def path(self, *parts):
        if any(not isinstance(part, str) or not part or part in {".", ".."} or "/" in part or "\\" in part for part in parts):
            raise ValueError("Invalid authority path")
        return self.lexical_root.joinpath(*parts)

    def read_json(self, path, *, strict=False, max_bytes=_METADATA_LIMIT):
        snapshot = read_stable_file(path, min(max_bytes, _METADATA_LIMIT))
        self.snapshots.append(snapshot)
        value = strict_json(snapshot.raw)
        if not isinstance(value, dict):
            raise ValueError("Invalid metadata authority")
        return value


def read_team_knowledge_directory(project_root: Path, directory, team_id: str, *, offset: int = 0, limit: int = 6) -> dict:
    """Read an unprivileged projection; caller must enforce REQUIRED_SCOPES.

    Missing Team/base metadata, malformed ownership, routing drift, link aliases
    or ambiguous IDs fail closed. The list is not an Agent ACL determination.
    """
    from core.web.services import team_knowledge_service as knowledge, team_service
    if type(offset) is not int or not 0 <= offset <= _MAX_BASES or type(limit) is not int or not 1 <= limit <= 6:
        raise ManagementError("INVALID_INPUT", 422)
    try:
        root = Path(project_root).resolve()
        def check_binding():
            if (Path(directory.PROJECT_ROOT).resolve() != root or Path(team_service.PROJECT_ROOT).resolve() != root
                    or Path(knowledge.PROJECT_ROOT).resolve() != root or knowledge._project_root() != root):
                raise ValueError("Project identity changed")

        check_binding()
        requested = _identity(team_id)
        if (knowledge._safe_token(requested, default="team", max_length=96) != requested
                or PureWindowsPath(requested).is_reserved()):
            raise ValueError("Unsafe Team identity")
        # Lock the same bytes used for all routing decisions. Re-reading the
        # config or identity before pinning can otherwise admit an A-B-A race.
        identity = read_stable_file(root / storage.PROJECT_IDENTITY_RELATIVE_PATH, 64 * 1024)
        config = read_stable_file(Path(directory.CONFIG_PATH), 16 * 1024 * 1024)
        with ExitStack() as pins:
            pins.enter_context(pinned_source_files((identity, config)))
            identity_data = strict_json(identity.raw)
            if (not isinstance(identity_data, dict) or type(identity_data.get("schemaVersion")) is not int
                    or identity_data["schemaVersion"] != storage.PROJECT_IDENTITY_SCHEMA_VERSION
                    or not isinstance(identity_data.get("projectId"), str)):
                raise ValueError("Invalid project identity")
            project_id = identity_data["projectId"].strip().lower()
            if not storage._PROJECT_ID_RE.fullmatch(project_id):
                raise ValueError("Invalid project identity")
            config_data = tomllib.loads(config.raw.decode("utf-8"))
            if Path(config_paths.resolve_config_path()).resolve() != Path(directory.CONFIG_PATH).resolve():
                raise ValueError("Config authority mismatch")
            storage_config = config_data.get("storage", {})
            if not isinstance(storage_config, dict):
                raise ValueError("Invalid storage config")
            data_env = os.environ.get(config_paths.DATA_HOME_ENV, "")
            configured_data = storage_config.get("data_home", "")
            if not isinstance(configured_data, str):
                raise ValueError("Invalid data home")
            paths = storage.resolve_project_storage_paths(root)
            if paths.project_id != project_id:
                raise ValueError("Project identity mismatch")
            marker = read_stable_file(storage.storage_migration_state_path(paths), 64 * 1024)
            pins.enter_context(pinned_source_files((marker,)))
            marker_data = strict_json(marker.raw)
            if (not isinstance(marker_data, dict) or type(marker_data.get("schemaVersion")) is not int
                    or marker_data["schemaVersion"] != storage.STORAGE_MIGRATION_SCHEMA_VERSION
                    or marker_data.get("status") != "completed" or marker_data.get("projectId") != project_id
                    or marker_data.get("instanceId") != paths.instance_id):
                raise ValueError("Unproven project storage")
            marker_root = marker_data.get("projectRoot")
            if not isinstance(marker_root, str) or not marker_root:
                raise ValueError("Missing project storage owner")
            owner_path = check_path(Path(marker_root))
            # Pin both directory chains and compare their physical identities.
            # Windows case-sensitive directories can contain distinct paths
            # that differ only by case, so textual case folding is not proof.
            _, _, owner_info = pins.enter_context(_locked_source(
                Path(owner_path.anchor), owner_path, directory=True, allow_child_replacement=True))
            _, _, root_info = pins.enter_context(_locked_source(
                Path(root.anchor), root, directory=True, allow_child_replacement=True))
            def physical_id(info):
                index = (info.index_high << 32) | info.index_low
                if not index:
                    raise ValueError("Unproven physical directory identity")
                return info.volume, index
            if physical_id(owner_info) != physical_id(root_info):
                raise ValueError("Project storage owner mismatch")
            # Match the native resolver's environment-over-config priority;
            # only the already-proven canonical instance data may be read.
            raw_data = data_env.strip() or configured_data.strip()
            if raw_data:
                data_path = Path(os.path.expandvars(raw_data)).expanduser()
                if not data_path.is_absolute():
                    data_path = (Path.cwd() if data_env.strip() else Path(directory.CONFIG_PATH).parent) / data_path
                data_path = Path(os.path.abspath(data_path))
                if os.path.normcase(str(data_path)) != os.path.normcase(str(paths.data)):
                    raise ValueError("Shared storage cannot establish project ownership")
                data_path = check_path(data_path)
                canonical_data = check_path(paths.data)
                _, _, data_info = pins.enter_context(_locked_source(
                    Path(data_path.anchor), data_path, directory=True, allow_child_replacement=True))
                _, _, canonical_info = pins.enter_context(_locked_source(
                    Path(canonical_data.anchor), canonical_data, directory=True, allow_child_replacement=True))
                if physical_id(data_info) != physical_id(canonical_info):
                    raise ValueError("Project data home mismatch")
            # Path equality is also case-insensitive in pathlib on Windows;
            # all service bindings must refer to this same physical directory.
            def check_physical_bindings():
                for bound in (directory.PROJECT_ROOT, team_service.PROJECT_ROOT,
                              knowledge.PROJECT_ROOT, knowledge._project_root()):
                    bound = check_path(Path(bound))
                    _, _, bound_info = pins.enter_context(_locked_source(
                        Path(bound.anchor), bound, directory=True, allow_child_replacement=True))
                    if physical_id(bound_info) != physical_id(root_info):
                        raise ValueError("Project binding mismatch")
            check_physical_bindings()
            if (storage.resolve_active_project_storage_paths(root) != paths
                    or storage.resolve_project_workspace_home(root) != paths.workspace.resolve()
                    or developer_sandbox.formal_workspace_path(root) != paths.workspace.resolve()):
                raise ValueError("Project workspace mismatch")
            launcher = config_data.get("launcher", {})
            if not isinstance(launcher, dict):
                raise ValueError("Invalid launcher config")
            setting = launcher.get("developer_mode", {})
            if not isinstance(setting, dict) or type(setting.get("enabled", False)) is not bool:
                raise ValueError("Invalid sandbox config")
            workspace = paths.workspace
            if setting.get("enabled", False):
                state_path = paths.runtime / "developer-mode" / developer_sandbox.ACTIVE_STATE_NAME
                if developer_sandbox._active_state_path(root) != state_path:
                    raise ValueError("Sandbox route mismatch")
                active = read_stable_file(state_path, 64 * 1024)
                pins.enter_context(pinned_source_files((active,)))
                state = strict_json(active.raw)
                token = state.get("sandboxId") if isinstance(state, dict) else None
                if (not isinstance(state, dict) or type(state.get("schemaVersion")) is not int
                        or state["schemaVersion"] != 1 or not isinstance(token, str) or not token
                        or len(token) > 128 or developer_sandbox._safe_token(token, default="") != token
                        or PureWindowsPath(token).is_reserved()):
                    raise ValueError("Invalid sandbox identity")
                sandbox = paths.runtime / "developer-mode" / developer_sandbox.SANDBOXES_DIR / token
                if developer_sandbox._sandbox_root(root, token) != sandbox:
                    raise ValueError("Sandbox route mismatch")
                workspace = sandbox / "workspace"
            sources = _Sources(root, directory, workspace)
            teams = _teams(sources)
            tokens = set()
            for tid in teams:
                token = knowledge._safe_token(tid, default="team", max_length=96).casefold()
                if token in tokens:
                    raise ValueError("Colliding Team storage identity")
                tokens.add(token)
            if requested.casefold() in {tid.casefold() for tid in SYSTEM_MANAGED_TEAM_IDS}:
                raise ValueError("Protected Team identity")
            team = teams.get(requested)
            if team is None or team["private"] or team["row"]["status"] != "active":
                raise ValueError("Unavailable Team")
            payload = sources.read_json(sources.path("teams", requested, "knowledge", "knowledge_bases.json"), strict=True)
            rows = payload.get("knowledgeBases")
            if (type(payload.get("schemaVersion")) is not int or payload["schemaVersion"] != knowledge.SCHEMA_VERSION
                    or not isinstance(rows, list) or len(rows) > _MAX_BASES):
                raise ValueError("Invalid knowledge authority")
            seen, projected = set(), []
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Invalid knowledge row")
                base_id = _identity(row.get("knowledgeBaseId"))
                if (knowledge._safe_token(base_id, default="", max_length=128) != base_id
                        or PureWindowsPath(base_id).is_reserved() or base_id.casefold() in seen):
                    raise ValueError("Ambiguous knowledge identity")
                seen.add(base_id.casefold())
                if (row.get("ownerType") != "team" or row.get("ownerId") != requested or row.get("teamId") != requested
                        or row.get("agentId", "") != "" or row.get("status") not in {"active", "archived"}
                        or any(key in row and row[key] != value for key, value in
                               (("owner_type", "team"), ("owner_id", requested), ("team_id", requested),
                                ("knowledge_base_id", base_id), ("scopedKnowledgeBaseId", f"team:{requested}:{base_id}")))):
                    raise ValueError("Invalid knowledge ownership")
                name = _text(row.get("name"), 64)
                if not name:
                    raise ValueError("Invalid knowledge name")
                if row["status"] == "active":
                    projected.append({"id": base_id, "name": name, "status": "active"})
            projected.sort(key=lambda row: row["id"])
            with pinned_source_files(sources.snapshots):
                if os.environ.get(config_paths.DATA_HOME_ENV, "") != data_env:
                    raise ValueError("Data home changed")
                check_binding()
                check_physical_bindings()
                page = projected[offset:offset + limit]
                end = offset + len(page)
                return {"teamId": requested, "knowledgeBases": page, "total": len(projected), "offset": offset,
                        "nextOffset": end if end < len(projected) else None, "untrustedContent": True,
                        "requiredScopes": list(REQUIRED_SCOPES), "coverage": _COVERAGE}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, RecursionError):
        raise ManagementError("KNOWLEDGE_DIRECTORY_UNAVAILABLE", 503) from None
