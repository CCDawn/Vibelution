"""Declarative role file layer: workspace-level shared role library.

One role = one markdown file (``docs/standards/unified-team-format.md`` §5):

- Registry: ``workspace/agent_config/role_definitions.json`` holding one row
  per role (``roleKey`` / ``sourcePath`` / ``metadata``). The registry holds
  **no role content**: the markdown file is the sole content authority.
- Role file: ``workspace/roles/<roleKey>.md``. A YAML-subset frontmatter
  carries the structured fields (``ROLE_DEFINITION_FIELDS`` plus optional
  ``modelRef`` slot reference); the markdown body carries the persona/task
  narrative for operators and reviewers.

Builtin role files ship with the product under
``core/web/services/team/role_definitions/*.md``. On repair, missing
workspace files are seeded from the builtin content and builtin entries are
overwritten when ``builtinContentVersion`` bumps; user-created entries
(roleKey outside the builtin set) are never touched — the same seeding
semantics as the prompt template registry
(``prompt_template_service.repair_prompt_templates``).

Trust tier: role files are operator-controlled content (the same tier as
prompt-template role prompts). They never enter the knowledge / untrusted
channel, and ``sourcePath`` must resolve to
``workspace/roles/<roleKey>.md`` inside the routed workspace — anything else
is rejected (fail closed, mirroring the prompt-template source-path guard).

No file watcher: the established pattern is load-time repair + explicit
invalidation + metadata versions, and this module follows it. Every load
entry point runs ``team_format.validate_role_definition`` so the unified
format validator has a real production caller; malformed files fail closed
with a locatable error instead of materializing broken roles.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from core.infrastructure.atomic_io import atomic_write_json, atomic_write_text
from core.infrastructure.developer_sandbox import route_workspace_path
from core.infrastructure.file_lock import cross_process_file_lock

from . import team_format

__all__ = [
    "RoleDefinitionError",
    "PROJECT_ROOT",
    "ROLE_DEFINITIONS_PACKAGE_DIR",
    "ROLE_REGISTRY_SCHEMA_VERSION",
    "BUILTIN_ROLE_CONTENT_VERSION",
    "ROLE_KEY_PATTERN",
    "role_registry_path",
    "role_file_path",
    "builtin_role_keys",
    "builtin_role_definition",
    "builtin_role_markdown",
    "repair_role_definitions",
    "list_role_definitions",
    "get_role_definition",
    "load_role_definitions",
    "parse_role_markdown",
]

PROJECT_ROOT = Path(__file__).resolve().parents[4]
ROLE_DEFINITIONS_PACKAGE_DIR = Path(__file__).resolve().parent / "role_definitions"
ROLE_REGISTRY_SCHEMA_VERSION = 1
# Bump when shipped role files change in a way that must overwrite seeded
# workspace copies; user-created roles are never affected by the bump.
BUILTIN_ROLE_CONTENT_VERSION = 1
ROLE_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")

_FRONTMATTER_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_ROLE_TOP_LEVEL_KEYS = frozenset(
    {
        "roleKey",
        "role",
        "purpose",
        "agentName",
        "responsibilities",
        "personaProfile",
        "taskProfile",
        "toolPolicy",
        "modelRef",
    }
)
_TOP_LEVEL_SCALAR_KEYS = ("roleKey", "role", "purpose", "agentName")
_PERSONA_SCALAR_KEYS = ("personality", "communicationStyle", "background", "identityNotes")
_TASK_SCALAR_KEYS = (
    "mission",
    "responsibilities",
    "preferredTasks",
    "avoidTasks",
    "successCriteria",
    "constraints",
    "deliverables",
)
_TOOL_POLICY_LIST_KEYS = ("allowedTools", "preferredTools", "writeScopes")

_REPAIR_LOCK = threading.RLock()


class RoleDefinitionError(ValueError):
    """Raised when a role file / registry entry is missing or malformed."""


# --- paths -----------------------------------------------------------------


def role_registry_path(*, project_root: Path | None = None) -> Path:
    return _workspace_path("agent_config", "role_definitions.json", project_root=project_root)


def role_file_path(role_key: str, *, project_root: Path | None = None) -> Path:
    return _workspace_path("roles", f"{_normalize_role_key(role_key)}.md", project_root=project_root)


def _workspace_path(*parts: str, project_root: Path | None = None) -> Path:
    root = Path(project_root) if project_root is not None else PROJECT_ROOT
    return route_workspace_path(root, "team", *parts, intent="state", seed=True)


def _default_source_path(role_key: str) -> str:
    return f"workspace/roles/{role_key}.md"


def _resolve_role_source_path(source_path: Any, *, project_root: Path | None = None) -> Path | None:
    """Resolve a registry ``sourcePath`` or ``None`` when it is unsafe.

    Only ``workspace/roles/<roleKey>.md`` inside the routed workspace is
    accepted; ``..`` segments, other directories and paths outside the
    workspace are rejected (fail closed).
    """

    raw = str(source_path or "").strip().replace("\\", "/")
    if not raw:
        return None
    parts = PurePosixPath(raw).parts
    if len(parts) != 3 or parts[0] != "workspace" or parts[1] != "roles":
        return None
    filename = parts[2]
    if not filename.endswith(".md") or not ROLE_KEY_PATTERN.fullmatch(filename[: -len(".md")]):
        return None
    try:
        candidate = _workspace_path("roles", filename, project_root=project_root).resolve()
    except Exception:
        return None
    roles_root = _workspace_path("roles", project_root=project_root).resolve()
    if candidate != roles_root and roles_root not in candidate.parents:
        return None
    return candidate


# --- builtin role files (shipped with the product) --------------------------


def builtin_role_keys() -> tuple[str, ...]:
    """Role keys shipped in the product package, sorted for determinism."""

    if not ROLE_DEFINITIONS_PACKAGE_DIR.is_dir():
        return ()
    return tuple(sorted(path.stem for path in ROLE_DEFINITIONS_PACKAGE_DIR.glob("*.md") if path.is_file()))


def builtin_role_markdown(role_key: str) -> str:
    path = ROLE_DEFINITIONS_PACKAGE_DIR / f"{_normalize_role_key(role_key)}.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RoleDefinitionError(f"builtin 角色文件缺失或不可读：{path}") from exc


def builtin_role_definition(role_key: str) -> dict[str, Any]:
    """Parse and validate one shipped role file (no workspace IO)."""

    key = _normalize_role_key(role_key)
    if key not in builtin_role_keys():
        raise RoleDefinitionError(f"未知 builtin 角色：{role_key}")
    return parse_role_markdown(builtin_role_markdown(key), source=f"builtin:role_definitions/{key}.md")


# --- markdown parsing (strict YAML-subset frontmatter) ----------------------


def parse_role_markdown(text: str, *, source: str) -> dict[str, Any]:
    """Parse one role markdown file into a validated role definition.

    Fail closed: malformed frontmatter, unknown fields, wrong value types or
    a ``validate_role_definition`` rejection raise :class:`RoleDefinitionError`
    with the file (``source``) and field path called out.
    """

    mapping = _parse_frontmatter_mapping(_split_frontmatter_lines(text, source=source), source=source)
    return _role_from_mapping(mapping, source=source)


def _split_frontmatter_lines(text: str, *, source: str) -> list[str]:
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise RoleDefinitionError(f"{source}: 角色文件必须以 --- frontmatter 开头。")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index]
    raise RoleDefinitionError(f"{source}: frontmatter 缺少闭合 --- 行。")


def _parse_frontmatter_mapping(lines: list[str], *, source: str) -> dict[str, Any]:
    entries: list[tuple[int, str]] = []
    for offset, raw in enumerate(lines, start=2):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if raw.lstrip(" ").startswith("\t"):
            raise RoleDefinitionError(f"{source}: frontmatter 第 {offset} 行使用 Tab 缩进（只允许空格）。")
        entries.append((indent, stripped))

    root: dict[str, Any] = {}
    pos = 0

    def parse_mapping(indent: int, container: dict[str, Any]) -> None:
        nonlocal pos
        while pos < len(entries):
            entry_indent, text = entries[pos]
            if entry_indent < indent:
                return
            if entry_indent > indent:
                raise RoleDefinitionError(f"{source}: frontmatter 缩进不合法：{text!r}")
            if text.startswith("- "):
                raise RoleDefinitionError(f"{source}: 列表项不能直接出现在映射层：{text!r}")
            key, value = _split_key_value(text, source=source)
            pos += 1
            if value == "":
                if pos < len(entries) and entries[pos][0] > indent:
                    next_indent, next_text = entries[pos]
                    if next_text.startswith("- "):
                        items: list[str] = []
                        container[key] = items
                        parse_list(next_indent, items)
                        continue
                    nested: dict[str, Any] = {}
                    container[key] = nested
                    parse_mapping(next_indent, nested)
                    continue
                container[key] = ""
            else:
                container[key] = _coerce_scalar(value)

    def parse_list(indent: int, container: list[str]) -> None:
        nonlocal pos
        while pos < len(entries):
            entry_indent, text = entries[pos]
            if entry_indent < indent:
                return
            if entry_indent != indent or not text.startswith("- "):
                raise RoleDefinitionError(f"{source}: 列表项缩进或格式不合法：{text!r}")
            container.append(_coerce_scalar(text[2:].strip()))
            pos += 1

    parse_mapping(0, root)
    return root


def _split_key_value(text: str, *, source: str) -> tuple[str, str]:
    key, sep, value = text.partition(":")
    if not sep:
        raise RoleDefinitionError(f"{source}: frontmatter 行缺少冒号：{text!r}")
    normalized_key = key.strip()
    if not _FRONTMATTER_KEY_PATTERN.fullmatch(normalized_key):
        raise RoleDefinitionError(f"{source}: frontmatter 键名不合法：{normalized_key!r}")
    return normalized_key, value.strip()


def _coerce_scalar(value: str) -> Any:
    if value == "[]":
        return []
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _require_str(mapping: dict[str, Any], key: str, *, source: str, where: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RoleDefinitionError(f"{source}: {where} 缺少非空字符串字段 {key}。")
    return value.strip()


def _require_str_list(mapping: dict[str, Any], key: str, *, source: str, where: str) -> list[str]:
    value = mapping.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RoleDefinitionError(f"{source}: {where}.{key} 必须是字符串列表。")
    return [item.strip() for item in value]


def _role_from_mapping(mapping: dict[str, Any], *, source: str) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        raise RoleDefinitionError(f"{source}: frontmatter 必须解析为键值映射。")
    unknown = sorted(set(mapping) - _ROLE_TOP_LEVEL_KEYS)
    if unknown:
        raise RoleDefinitionError(f"{source}: frontmatter 含未登记字段（拒绝静默丢弃）：{unknown}")

    role: dict[str, Any] = {key: _require_str(mapping, key, source=source, where="frontmatter") for key in _TOP_LEVEL_SCALAR_KEYS}
    role["responsibilities"] = _require_str_list(mapping, "responsibilities", source=source, where="frontmatter")

    persona = mapping.get("personaProfile")
    if not isinstance(persona, dict):
        raise RoleDefinitionError(f"{source}: frontmatter 缺少 personaProfile 小节。")
    persona_unknown = sorted(set(persona) - set(team_format.PERSONA_PROFILE_FIELDS))
    if persona_unknown:
        raise RoleDefinitionError(f"{source}: personaProfile 含未登记字段：{persona_unknown}")
    role["personaProfile"] = {
        **{key: _require_str(persona, key, source=source, where="personaProfile") for key in _PERSONA_SCALAR_KEYS},
        "expertise": _require_str_list(persona, "expertise", source=source, where="personaProfile"),
    }

    task = mapping.get("taskProfile")
    if not isinstance(task, dict):
        raise RoleDefinitionError(f"{source}: frontmatter 缺少 taskProfile 小节。")
    task_unknown = sorted(set(task) - set(team_format.TASK_PROFILE_FIELDS))
    if task_unknown:
        raise RoleDefinitionError(f"{source}: taskProfile 含未登记字段：{task_unknown}")
    role["taskProfile"] = {key: _require_str(task, key, source=source, where="taskProfile") for key in _TASK_SCALAR_KEYS}

    policy = mapping.get("toolPolicy")
    if not isinstance(policy, dict):
        raise RoleDefinitionError(f"{source}: frontmatter 缺少 toolPolicy 小节。")
    policy_unknown = sorted(set(policy) - set(team_format.TOOL_POLICY_FIELDS))
    if policy_unknown:
        raise RoleDefinitionError(f"{source}: toolPolicy 含未登记字段：{policy_unknown}")
    role["toolPolicy"] = {key: _require_str_list(policy, key, source=source, where="toolPolicy") for key in _TOOL_POLICY_LIST_KEYS}

    if "modelRef" in mapping:
        role["modelRef"] = _require_str(mapping, "modelRef", source=source, where="frontmatter")

    result = team_format.validate_role_definition(role)
    if not result["valid"]:
        codes = [
            f"{issue.get('code')}({issue.get('path')})"
            for issue in result["issues"]
            if issue.get("severity") == "error"
        ]
        raise RoleDefinitionError(f"{source}: 角色定义未通过统一格式校验：{codes}")
    return role


# --- registry load / repair -------------------------------------------------


def repair_role_definitions(*, project_root: Path | None = None) -> dict[str, Any]:
    """Load the registry, seed/upgrade builtin roles and save when changed.

    Semantics (mirrors the prompt template registry):

    - missing workspace role files are seeded from the shipped builtin content;
    - builtin entries whose stored ``builtinContentVersion`` is older than the
      shipped version have their workspace file overwritten with the builtin
      content and their metadata bumped;
    - user-created entries (roleKey outside the builtin set) and user edits to
      builtin role files survive untouched unless a builtin version bump
      overwrites that builtin file;
    - unsafe ``sourcePath`` values and malformed registry rows are dropped
      with a ``repairWarnings`` entry instead of being materialized.
    """

    root = Path(project_root) if project_root is not None else PROJECT_ROOT
    with _REPAIR_LOCK, cross_process_file_lock(role_registry_path(project_root=root)):
        return _repair_locked(project_root=root)


def _repair_locked(*, project_root: Path | None) -> dict[str, Any]:
    payload = _load_registry_payload(project_root=project_root)
    warnings: list[str] = [str(item) for item in (payload.get("repairWarnings") or [])][-49:]
    stored = _normalize_registry_rows(payload.get("roles"), warnings=warnings, project_root=project_root)
    now = _now()
    changed = payload.get("schemaVersion") != ROLE_REGISTRY_SCHEMA_VERSION

    roles_root = _workspace_path("roles", project_root=project_root)
    roles_root.mkdir(parents=True, exist_ok=True)

    merged: dict[str, dict[str, Any]] = {}
    for role_key in builtin_role_keys():
        builtin_markdown = builtin_role_markdown(role_key)
        entry = stored.get(role_key)
        if entry is None:
            path = _workspace_path("roles", f"{role_key}.md", project_root=project_root)
            if not path.exists():
                _write_role_file(path, builtin_markdown)
            merged[role_key] = _builtin_registry_entry(role_key, now=now)
            changed = True
            continue
        metadata = dict(entry.get("metadata") or {})
        path = _resolve_role_source_path(entry.get("sourcePath"), project_root=project_root)
        if path is None:
            entry = {**entry, "sourcePath": _default_source_path(role_key)}
            path = _resolve_role_source_path(entry["sourcePath"], project_root=project_root)
            warnings.append(f"builtin 角色 {role_key} 的 sourcePath 非法，已重置为 {_default_source_path(role_key)}")
            changed = True
        assert path is not None
        try:
            stored_version = int((metadata.get("builtinContentVersion")) or 0)
        except (TypeError, ValueError):
            stored_version = 0
        if not path.exists() or stored_version < BUILTIN_ROLE_CONTENT_VERSION:
            _write_role_file(path, builtin_markdown)
            metadata["builtinContentVersion"] = BUILTIN_ROLE_CONTENT_VERSION
            metadata["updatedAt"] = now
            entry = {**entry, "metadata": metadata, "updatedAt": now}
            changed = True
        else:
            entry = {**entry, "metadata": metadata}
        merged[role_key] = entry

    for role_key, entry in stored.items():
        if role_key in merged:
            continue
        path = _resolve_role_source_path(entry.get("sourcePath"), project_root=project_root)
        if path is None:
            warnings.append(f"非 builtin 角色 {role_key} 的 sourcePath 非法，已丢弃：{entry.get('sourcePath')}")
            changed = True
            continue
        merged[role_key] = entry

    next_payload = {
        "schemaVersion": ROLE_REGISTRY_SCHEMA_VERSION,
        "updatedAt": str(payload.get("updatedAt") or now),
        "roles": [merged[role_key] for role_key in sorted(merged)],
        "repairWarnings": warnings[-50:],
    }
    registry_path = role_registry_path(project_root=project_root)
    if changed or not registry_path.exists():
        next_payload["updatedAt"] = now
        _save_registry(next_payload, project_root=project_root)
    return next_payload


def _normalize_registry_rows(
    raw_rows: Any,
    *,
    warnings: list[str],
    project_root: Path | None,
) -> dict[str, dict[str, Any]]:
    stored: dict[str, dict[str, Any]] = {}
    if not isinstance(raw_rows, list):
        if raw_rows is not None:
            warnings.append("registry roles 字段不是数组，已按空登记处理")
        return stored
    for raw in raw_rows:
        if not isinstance(raw, dict):
            warnings.append("registry 存在非对象条目，已丢弃")
            continue
        role_key = str(raw.get("roleKey") or "").strip()
        if not ROLE_KEY_PATTERN.fullmatch(role_key):
            warnings.append(f"registry 条目缺少合法 roleKey，已丢弃：{role_key!r}")
            continue
        metadata_raw = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        try:
            builtin_version = int(metadata_raw.get("builtinContentVersion") or 0)
        except (TypeError, ValueError):
            builtin_version = 0
        entry = {
            "roleKey": role_key,
            "sourcePath": str(raw.get("sourcePath") or "").strip() or _default_source_path(role_key),
            "status": "active" if str(raw.get("status") or "active").strip() == "active" else "inactive",
            "metadata": {
                "builtin": bool(metadata_raw.get("builtin")),
                "builtinContentVersion": max(0, builtin_version),
                "updatedAt": str(metadata_raw.get("updatedAt") or "").strip(),
            },
            "createdAt": str(raw.get("createdAt") or "").strip(),
            "updatedAt": str(raw.get("updatedAt") or "").strip(),
        }
        if role_key in stored:
            warnings.append(f"registry 角色 {role_key} 重复登记，保留首条")
            continue
        stored[role_key] = entry
    return stored


def _builtin_registry_entry(role_key: str, *, now: str) -> dict[str, Any]:
    return {
        "roleKey": role_key,
        "sourcePath": _default_source_path(role_key),
        "status": "active",
        "metadata": {
            "builtin": True,
            "builtinContentVersion": BUILTIN_ROLE_CONTENT_VERSION,
            "updatedAt": now,
        },
        "createdAt": now,
        "updatedAt": now,
    }


def _load_registry_payload(*, project_root: Path | None = None) -> dict[str, Any]:
    path = role_registry_path(project_root=project_root)
    empty = {"schemaVersion": ROLE_REGISTRY_SCHEMA_VERSION, "roles": [], "repairWarnings": []}
    if not path.exists():
        return empty
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    return payload if isinstance(payload, dict) else empty


def _save_registry(payload: dict[str, Any], *, project_root: Path | None = None) -> None:
    path = role_registry_path(project_root=project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schemaVersion": ROLE_REGISTRY_SCHEMA_VERSION,
        "updatedAt": _now(),
        "roles": list(payload.get("roles") or []),
        "repairWarnings": list(payload.get("repairWarnings") or [])[-50:],
    }
    atomic_write_json(path, data, ensure_ascii=False, indent=2)


def _write_role_file(path: Path, markdown: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, markdown.replace("\r\n", "\n"))


# --- public read API --------------------------------------------------------


def get_role_definition(role_key: str, *, project_root: Path | None = None) -> dict[str, Any]:
    """Return one validated role definition from the workspace role library.

    Fail closed: unknown role, unsafe sourcePath, missing file or malformed
    content all raise :class:`RoleDefinitionError` with a locatable message.
    """

    key = _normalize_role_key(role_key)
    repair_role_definitions(project_root=project_root)
    entry = _find_registry_entry(key, project_root=project_root)
    if entry is None:
        raise RoleDefinitionError(f"角色未登记：{key}")
    return _read_role_entry(entry, project_root=project_root)


def load_role_definitions(
    role_keys: Any,
    *,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Load several roles in the requested order; any failure aborts the batch.

    This is the fail-closed bulk loader for template materialization: a
    missing or malformed role raises instead of producing a partial team.
    """

    keys = [str(key or "").strip() for key in (role_keys or [])]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise RoleDefinitionError(f"角色键重复：{duplicates}")
    return [get_role_definition(key, project_root=project_root) for key in keys]


def list_role_definitions(*, project_root: Path | None = None) -> dict[str, Any]:
    """List the role library with per-role validity (never raises per role)."""

    payload = repair_role_definitions(project_root=project_root)
    roles: list[dict[str, Any]] = []
    for entry in payload.get("roles") or []:
        metadata = dict(entry.get("metadata") or {}) if isinstance(entry, dict) else {}
        summary: dict[str, Any] = {
            "roleKey": str(entry.get("roleKey") or ""),
            "sourcePath": str(entry.get("sourcePath") or ""),
            "status": str(entry.get("status") or "active"),
            "metadata": metadata,
            "builtin": bool(metadata.get("builtin")),
            "valid": True,
            "issues": [],
            "role": "",
            "purpose": "",
        }
        try:
            role = _read_role_entry(entry, project_root=project_root)
            summary["role"] = str(role.get("role") or "")
            summary["purpose"] = str(role.get("purpose") or "")
        except RoleDefinitionError as exc:
            summary["valid"] = False
            summary["issues"] = [{"severity": "error", "code": "role_file_invalid", "message": str(exc)}]
        roles.append(summary)
    path = role_registry_path(project_root=project_root)
    return {
        "schemaVersion": ROLE_REGISTRY_SCHEMA_VERSION,
        "path": str(path),
        "storagePath": _relative_workspace_path(path, project_root=project_root),
        "roles": roles,
        "builtinRoleKeys": list(builtin_role_keys()),
        "repairWarnings": list(payload.get("repairWarnings") or []),
        "updatedAt": str(payload.get("updatedAt") or ""),
    }


def _find_registry_entry(role_key: str, *, project_root: Path | None = None) -> dict[str, Any] | None:
    payload = _load_registry_payload(project_root=project_root)
    for entry in payload.get("roles") or []:
        if isinstance(entry, dict) and str(entry.get("roleKey") or "").strip() == role_key:
            return entry
    return None


def _read_role_entry(entry: dict[str, Any], *, project_root: Path | None = None) -> dict[str, Any]:
    role_key = str(entry.get("roleKey") or "").strip()
    path = _resolve_role_source_path(entry.get("sourcePath"), project_root=project_root)
    if path is None:
        raise RoleDefinitionError(f"角色 {role_key} 的 sourcePath 非法（只允许 workspace/roles/<roleKey>.md）：{entry.get('sourcePath')}")
    if not path.exists() or not path.is_file():
        raise RoleDefinitionError(f"角色 {role_key} 的文件缺失：{path}")
    try:
        markdown = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RoleDefinitionError(f"角色 {role_key} 的文件不可读：{path}") from exc
    return parse_role_markdown(markdown, source=str(path))


def _normalize_role_key(role_key: Any) -> str:
    key = str(role_key or "").strip()
    if not ROLE_KEY_PATTERN.fullmatch(key):
        raise RoleDefinitionError(f"角色键不合法（需匹配 {ROLE_KEY_PATTERN.pattern}）：{role_key!r}")
    return key


def _relative_workspace_path(path: Path, *, project_root: Path | None = None) -> str:
    root = Path(project_root) if project_root is not None else PROJECT_ROOT
    try:
        return path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
