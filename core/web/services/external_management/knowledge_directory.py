"""Existing-only knowledge metadata for legacy Team and operator owner catalogs.

Transport authorization is separate from native privileged-operator admission.
Metadata JSON physically contains descriptions and ACLs; only bounded public
identity/name/status and native ACL fingerprints are projected. No bodies,
statistics, proposals or owner initialization are accessed.
"""
from __future__ import annotations

from pathlib import Path, PureWindowsPath
from contextlib import ExitStack, contextmanager, nullcontext
from copy import deepcopy
import hashlib
import json
import os
import tomllib

import vibelution_storage as storage
from config import paths as config_paths
from core.web.services.team.kind_helpers import SYSTEM_MANAGED_TEAM_IDS

from core.assistant_runtime.migration_io import check_path, pinned_source_files, read_stable_file, strict_json
from core.infrastructure import developer_sandbox
from core.infrastructure.storage_owner_handoff import pinned_storage_owner_handoff
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
        self._payloads = {}
        self._workspace_token = None
        self.bytes_remaining = 64 * 1024 * 1024
        self.project_root, self.directory = root, directory
        self.lexical_root = workspace
        check_path(workspace)
        self._workspace_root = workspace.resolve()

    def path(self, *parts):
        if any(not isinstance(part, str) or not part or part in {".", ".."} or "/" in part or "\\" in part for part in parts):
            raise ValueError("Invalid authority path")
        return self.lexical_root.joinpath(*parts)

    def read_json(self, path, *, strict=False, max_bytes=_METADATA_LIMIT):
        if path in self._payloads:
            return deepcopy(self._payloads[path])
        snapshot = read_stable_file(path, min(max_bytes, _METADATA_LIMIT, self.bytes_remaining))
        self.bytes_remaining -= len(snapshot.raw)
        self.snapshots.append(snapshot)
        value = strict_json(snapshot.raw)
        if not isinstance(value, dict):
            raise ValueError("Invalid metadata authority")
        self._payloads[path] = value
        return deepcopy(value)


@contextmanager
def _existing_sources(project_root, directory):
    """Pin the native project/config/workspace route without provisioning it."""
    from core.web.services import team_knowledge_service as knowledge, team_service
    root = Path(project_root).resolve()
    def check_binding():
        if (Path(directory.PROJECT_ROOT).resolve() != root or Path(team_service.PROJECT_ROOT).resolve() != root
                or Path(knowledge.PROJECT_ROOT).resolve() != root or knowledge._project_root() != root):
            raise ValueError("Project identity changed")

    check_binding()
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
        _, _, root_info = pins.enter_context(_locked_source(
            Path(root.anchor), root, directory=True, allow_child_replacement=True))
        def physical_id(info):
            index = (info.index_high << 32) | info.index_low
            if not index:
                raise ValueError("Unproven physical directory identity")
            return info.volume, index
        if os.path.lexists(storage.storage_migration_state_path(paths)):
            # A current migration marker always retains native authority,
            # including fail-closed handling of malformed/conflicting markers.
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
            _, _, owner_info = pins.enter_context(_locked_source(
                Path(owner_path.anchor), owner_path, directory=True, allow_child_replacement=True))
            if physical_id(owner_info) != physical_id(root_info):
                raise ValueError("Project storage owner mismatch")
        else:
            # This proof only admits the configured legacy metadata route.
            # It never changes the native resolver or ACL/operator admission.
            paths = pins.enter_context(pinned_storage_owner_handoff(
                Path(project_root), identity_snapshot=identity, config_snapshot=config))
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
        yield sources, knowledge
        with pinned_source_files(sources.snapshots) if sources.snapshots else nullcontext():
            if os.environ.get(config_paths.DATA_HOME_ENV, "") != data_env:
                raise ValueError("Data home changed")
            check_binding()
            check_physical_bindings()


def read_team_knowledge_directory(project_root: Path, directory, team_id: str, *, offset: int = 0, limit: int = 6) -> dict:
    """Read an unprivileged projection; caller must enforce REQUIRED_SCOPES.

    Missing Team/base metadata, malformed ownership, routing drift, link aliases
    or ambiguous IDs fail closed. The list is not an Agent ACL determination.
    """
    from core.web.services import team_knowledge_service as knowledge, team_service
    if type(offset) is not int or not 0 <= offset <= _MAX_BASES or type(limit) is not int or not 1 <= limit <= 6:
        raise ManagementError("INVALID_INPUT", 422)
    try:
        requested = _identity(team_id)
        from core.web.services import team_knowledge_service as knowledge
        if (knowledge._safe_token(requested, default="team", max_length=96) != requested
                or PureWindowsPath(requested).is_reserved()):
            raise ValueError("Unsafe Team identity")
        with _existing_sources(project_root, directory) as (sources, knowledge):
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
            page = projected[offset:offset + limit]
            end = offset + len(page)
            return {"teamId": requested, "knowledgeBases": page, "total": len(projected), "offset": offset,
                    "nextOffset": end if end < len(projected) else None, "untrustedContent": True,
                    "requiredScopes": list(REQUIRED_SCOPES), "coverage": _COVERAGE}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, RecursionError):
        raise ManagementError("KNOWLEDGE_DIRECTORY_UNAVAILABLE", 503) from None


def _catalog_owners(sources, knowledge, kind):
    """Validate the same existing owner registries used by native operator ACLs."""
    plural, key = ("agents", "agentId") if kind == "agent" else ("teams", "teamId")
    payload = sources.read_json(sources.path(plural, plural + ".json"), strict=True)
    rows = payload.get(plural)
    if (not isinstance(rows, list) or len(rows) > _MAX_BASES
            or any(not isinstance(row, dict) for row in rows)):
        raise ValueError("Invalid knowledge owner authority")
    owners, seen = [], set()
    for row in rows:
        owner_id = _identity(row.get(key))
        maximum = 128 if kind == "agent" else 96
        if (knowledge._safe_token(owner_id, default="", max_length=maximum) != owner_id
                or PureWindowsPath(owner_id).is_reserved() or owner_id.casefold() in seen
                or row.get("status") not in {"active", "archived"}
                or any(alias in row and row[alias] != owner_id for alias in ("id", kind + "_id"))):
            raise ValueError("Ambiguous knowledge owner")
        seen.add(owner_id.casefold())
        owners.append((kind, owner_id, row))
    return owners


def _catalog_base_ids(payload, knowledge, kind, owner_id):
    rows = payload.get("knowledgeBases")
    if (type(payload.get("schemaVersion")) is not int or payload["schemaVersion"] != knowledge.SCHEMA_VERSION
            or not isinstance(rows, list) or len(rows) > _MAX_BASES):
        raise ValueError("Invalid knowledge authority")
    seen, result = set(), []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid knowledge row")
        base_id = _identity(row.get("knowledgeBaseId"))
        scoped_id = f"{kind}:{owner_id}:{base_id}"
        if (knowledge._safe_token(base_id, default="", max_length=128) != base_id
                or PureWindowsPath(base_id).is_reserved() or base_id.casefold() in seen
                or row.get("ownerType") != kind or row.get("ownerId") != owner_id
                or row.get("status") not in {"active", "archived"}
                or any(key in row and row[key] != value for key, value in (
                    ("teamId", owner_id if kind == "team" else ""),
                    ("agentId", owner_id if kind == "agent" else ""),
                    ("team_id", owner_id if kind == "team" else ""),
                    ("agent_id", owner_id if kind == "agent" else ""),
                    ("owner_type", kind), ("owner_id", owner_id),
                    ("knowledge_base_id", base_id), ("scopedKnowledgeBaseId", scoped_id)))):
            raise ValueError("Invalid knowledge ownership")
        name = _text(row.get("name"), 64)
        if not name:
            raise ValueError("Invalid knowledge name")
        seen.add(base_id.casefold())
        result.append((row, scoped_id, name))
    return result


class _ScopedOwnerSnapshot:
    """A validated exact-owner view for the native scoped ACL resolver.

    Full registries and every base identity were validated once above. Native
    ACL admission/shape/fingerprint remain authoritative; filtering the two
    already-read arrays avoids re-copying and re-scanning all owners/bases for
    each exact scoped reference. No disk reads or alternate store are added.
    """

    def __init__(self, sources, kind, owner, base):
        self.sources, self.kind, self.owner, self.base = sources, kind, owner, base

    def path(self, *parts):
        return self.sources.path(*parts)

    def read_json(self, path, **_kwargs):
        plural = "agents" if self.kind == "agent" else "teams"
        if path == self.path(plural, plural + ".json"):
            return {plural: [self.owner]}
        owner_id = self.owner["agentId" if self.kind == "agent" else "teamId"]
        if path == self.path(plural, owner_id, "knowledge", "knowledge_bases.json"):
            return {"knowledgeBases": [self.base]}
        raise ValueError("Unexpected native ACL authority")

    def verify_workspace(self):
        self.sources.verify_workspace()


def _existing_library_paths(sources, plural):
    """Bound discovery to existing metadata, including unknown owners; no bodies."""
    parent = sources.path(plural)
    check_path(parent)
    result = set()
    with os.scandir(parent) as entries:
        for index, entry in enumerate(entries):
            if index >= _MAX_BASES:
                raise ValueError("Too many knowledge owners")
            if entry.is_symlink():
                raise ValueError("Linked knowledge owner authority")
            if not entry.is_dir(follow_symlinks=False):
                continue
            owner_path = check_path(Path(entry.path))
            candidate = owner_path / "knowledge" / "knowledge_bases.json"
            try:
                candidate.lstat()
            except FileNotFoundError:
                continue
            check_path(candidate)
            result.add(entry.name)
    return result


def read_knowledge_directory(project_root: Path, directory, *, owner_type: str = "", owner_id: str = "",
        query: str = "", offset: int = 0, limit: int = 6, expected_digest: str = "") -> dict:
    """Discover existing native metadata as the operator, never as an Agent.

    The transport independently enforces knowledge:catalog:read. Native
    privileged-operator admission remains mandatory; catalog visibility never
    grants knowledge-body access, Agent ACL rights, or permission to mutate.
    """
    from pydantic import ValidationError
    from .knowledge_catalog_contracts import KnowledgeCatalogQuery, KnowledgeCatalogResponse, KNOWLEDGE_CATALOG_SCOPES
    from core.web.services import team_knowledge_service as knowledge

    try:
        args = KnowledgeCatalogQuery.model_validate(dict(owner_type=owner_type, owner_id=owner_id, query=query,
            offset=offset, limit=limit, expected_digest=expected_digest))
    except ValidationError:
        raise ManagementError("INVALID_INPUT", 422) from None
    # This checks the server's authenticated operator context. It does not
    # substitute any owner/Agent identity, even for private or system libraries.
    try:
        knowledge._knowledge_acl_operator()
    except knowledge.TeamKnowledgePermissionError:
        raise ManagementError("OPERATOR_CONTROL_REQUIRED", 403) from None
    try:
        with _existing_sources(project_root, directory) as (sources, knowledge):
            rows, issues, unavailable, scans = [], set(), 0, {}
            for kind in ([args.owner_type] if args.owner_type else ["agent", "team"]):
                plural = "agents" if kind == "agent" else "teams"
                try:
                    owners = _catalog_owners(sources, knowledge, kind)
                    if not args.owner_id:
                        scans[plural] = _existing_library_paths(sources, plural)
                        if scans[plural] - {identity for _, identity, _row in owners}:
                            issues.add("unknown_library_owner")
                except (OSError, ValueError, TypeError, KeyError):
                    issues.add("owner_authority_unavailable")
                    unavailable += 1
                    continue
                selected = [(kind, identity, row) for kind, identity, row in owners if not args.owner_id or identity == args.owner_id]
                if args.owner_id and not selected:
                    issues.add("owner_authority_unavailable")
                    unavailable += 1
                for kind, identity, owner_row in selected:
                    try:
                        payload = sources.read_json(sources.path(plural, identity, "knowledge", "knowledge_bases.json"), strict=True)
                        bases = _catalog_base_ids(payload, knowledge, kind, identity)
                        owner_rows = []
                        for base, scoped_id, name in bases:
                            acl = knowledge.read_operator_knowledge_base_acl(scoped_id,
                                existing_snapshot=_ScopedOwnerSnapshot(sources, kind, owner_row, base))
                            owner_rows.append({key: acl[key] for key in (
                                "knowledgeBaseId", "scopedKnowledgeBaseId", "ownerType", "ownerId", "status", "fingerprint")})
                            owner_rows[-1]["name"] = name
                        if len(rows) + len(owner_rows) > _MAX_BASES:
                            raise ValueError("Too many knowledge bases")
                        rows.extend(owner_rows)
                    except (OSError, ValueError, TypeError, KeyError, knowledge.TeamKnowledgeError):
                        issues.add("library_authority_unavailable")
                        unavailable += 1
            for plural, scanned in scans.items():
                if _existing_library_paths(sources, plural) != scanned:
                    raise ValueError("Knowledge owner directory changed")
            # Bind continuations to source bytes as well as sanitized public
            # rows so ACL/owner/name changes cannot cause silent skipped items.
            revision = {"project": str(Path(project_root).resolve()),
                        "sources": sorted((str(item.path.relative_to(sources.lexical_root)), item.sha256)
                                          for item in sources.snapshots),
                        "libraries": {key: sorted(value) for key, value in scans.items()},
                        "filter": [args.owner_type, args.owner_id, args.query],
                        "issues": sorted(issues), "unavailable": unavailable}
            digest = hashlib.sha256(json.dumps(revision, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")).encode("utf-8")).hexdigest()
            if args.expected_digest and args.expected_digest != digest:
                raise ManagementError("STATE_CONFLICT", 409)
            needle = args.query.strip().casefold()
            rows = [row for row in rows if not needle or any(needle in row[key].casefold()
                for key in ("name", "knowledgeBaseId", "scopedKnowledgeBaseId", "ownerId"))]
            rows.sort(key=lambda row: row["scopedKnowledgeBaseId"])
            page = rows[args.offset:args.offset + args.limit]
            initial_end = args.offset + len(page)
            result = KnowledgeCatalogResponse(knowledgeBases=page,
                status=("partial" if rows else "unavailable") if issues else "available",
                total=len(rows), offset=args.offset, nextOffset=initial_end if initial_end < len(rows) else None,
                digest=digest, unavailableOwnerCount=min(unavailable, _MAX_BASES), issues=sorted(issues),
                requiredScopes=list(KNOWLEDGE_CATALOG_SCOPES),
                coverage="Existing native owner/library metadata only. Missing, damaged or unknown-owner authorities are reported; "
                    "total counts only verified matching libraries. Metadata files include ACLs/descriptions but no bodies are opened. "
                    "Catalog visibility grants no Agent permissions or body access.").model_dump()
            # Leave room for Launcher project/source wrappers within the
            # native 3400-character action result budget. Shrink complete rows,
            # never scoped identities, ACL fingerprints, or JSON fragments.
            while True:
                end = args.offset + len(result["knowledgeBases"])
                result["nextOffset"] = end if end < len(rows) else None
                if len(json.dumps(result, ensure_ascii=False)) <= 3000 or len(result["knowledgeBases"]) <= 1:
                    return result
                result["knowledgeBases"].pop()
    except ManagementError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, RecursionError):
        raise ManagementError("KNOWLEDGE_DIRECTORY_UNAVAILABLE", 503) from None
