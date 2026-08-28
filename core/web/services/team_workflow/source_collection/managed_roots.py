"""Managed desktop source roots: persistent registry, locators and resolution.

Claim scope:登记桌面受管资料根（ManagedSourceRoot），提供 ``managed://`` locator
构造/反解与 containment 校验。桌面根明确允许位于项目根之外；绝对路径只允许
存在于本模块维护的受控 JSON registry，绝不进入 DataRecord/manifest/日志。

存储模式参照 source_collection_exclusions 的受控 JSON 文件（原子写 + 受控字段）。
本模块不引入任何后台监听；扫描始终由收集运行显式触发（手动刷新语义）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STORE_KIND = "team_workflow_managed_source_roots"
LOCATOR_SCHEME = "managed://"
PARSER_VERSION = "managed-local-parsing/1"

ROOT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")

# 受管根默认放行的类型。zip 是隔离展开入口，OOXML/HTML/PDF/图片按解析链处理。
MANAGED_SOURCE_ROOT_ALLOWED_EXTENSIONS = {
    ".md",
    ".txt",
    ".json",
    ".jsonl",
    ".ndjson",
    ".pdf",
    ".html",
    ".htm",
    ".docx",
    ".pptx",
    ".xlsx",
    ".zip",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".webp",
}

# 方案 §5.2：桌面根目录类别与证据策略。allowedForEvidence=false 的产物只允许
# 作为候选（candidate-only），不允许进入正式证据链；conversation_archive 默认
# 连扫描都关闭。
MANAGED_SOURCE_ROOT_CATEGORIES: dict[str, dict[str, bool]] = {
    "official_requirement": {"allowedForEvidence": True, "enabledByDefault": True},
    "project_material": {"allowedForEvidence": True, "enabledByDefault": True},
    "research_note": {"allowedForEvidence": True, "enabledByDefault": True},
    "engineering_contract": {"allowedForEvidence": False, "enabledByDefault": True},
    "submission_material": {"allowedForEvidence": True, "enabledByDefault": True},
    "generated_delivery": {"allowedForEvidence": False, "enabledByDefault": True},
    "tool_asset": {"allowedForEvidence": False, "enabledByDefault": True},
    "conversation_archive": {"allowedForEvidence": False, "enabledByDefault": False},
}

MANAGED_SOURCE_ROOT_TRUST_CLASSES = {"operator_managed", "external_reviewed"}

# 目录名前缀 → 类别的默认映射（桌面“挑战杯”根的一级子目录约定）。
DEFAULT_CATEGORY_PREFIX_MAP: dict[str, str] = {
    "00": "generated_delivery",
    "01": "project_material",
    "02": "research_note",
    "03": "engineering_contract",
    "04": "official_requirement",
    "05": "conversation_archive",
    "06": "submission_material",
    "07": "tool_asset",
}

# 前缀未命中时按名称关键词兜底（仍然只作用于根内一级子目录）。
DEFAULT_CATEGORY_NAME_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("任务书", "official_requirement"),
    ("官方", "official_requirement"),
    ("合同", "engineering_contract"),
    ("调研", "research_note"),
    ("方案", "research_note"),
    ("交付", "generated_delivery"),
    ("提交", "submission_material"),
    ("聊天", "conversation_archive"),
    ("工具", "tool_asset"),
    ("项目", "project_material"),
)

FALLBACK_CATEGORY = "project_material"

MANAGED_SCAN_BUDGET_DEFAULTS = {
    "maxFiles": 2000,
    "maxTotalBytes": 2 * 1024 * 1024 * 1024,
    "maxFileBytes": 32 * 1024 * 1024,
}
MANAGED_SCAN_BUDGET_LIMITS = {
    "maxFiles": (1, 20000),
    "maxTotalBytes": (1024, 64 * 1024 * 1024 * 1024),
    "maxFileBytes": (1024, 1024 * 1024 * 1024),
}

_MAX_RELATIVE_PATH_LENGTH = 900
_MAX_ZIP_ENTRY_NAME_LENGTH = 400


class ManagedSourceRootError(Exception):
    """Raised when a managed source root registration or resolution fails."""


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    """读取 registry JSON；返回 (payload, failure)。

    failure 为空表示正常（存在且为 dict）；否则取值：
    "missing"（文件不存在）、"not_dict"（存在但顶层非对象）、"parse_failed"。
    """

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}, "missing"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}, "parse_failed"
    if not isinstance(payload, dict):
        return {}, "not_dict"
    return payload, ""


def _quarantine_corrupt_registry(path: Path) -> None:
    """损坏 registry 只隔离不重写：改名保留现场，隔离失败绝不覆盖。"""

    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    quarantine_path = path.parent / f"index.corrupt-{stamp}.json"
    try:
        os.replace(path, quarantine_path)
    except OSError as exc:
        raise ManagedSourceRootError(
            f"Managed source root registry is corrupt and cannot be quarantined: {exc}"
        ) from exc


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=".tmp-msr-", suffix="", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def default_registry_path() -> Path:
    """受控 registry 的默认落点：data_home 下，与排除台账同级别受控。"""

    from config.paths import resolve_data_home

    return resolve_data_home() / "team_workflow" / "managed_source_roots" / "index.json"


def _load_registry(registry_path: Path | None = None) -> dict[str, Any]:
    path = registry_path or default_registry_path()
    store, failure = _read_json(path)
    if failure in {"parse_failed", "not_dict"}:
        # 损坏 registry 先隔离保留现场（jsonl_quarantine 先例），再从空 registry 起步。
        _quarantine_corrupt_registry(path)
        store = {}
    roots = [item for item in list(store.get("roots") or []) if isinstance(item, dict)]
    if not store:
        now = _utc_now_iso()
        store = {
            "schemaVersion": SCHEMA_VERSION,
            "storeKind": STORE_KIND,
            "roots": [],
            "createdAt": now,
            "updatedAt": now,
        }
    store["schemaVersion"] = SCHEMA_VERSION
    store["storeKind"] = STORE_KIND
    store["roots"] = roots
    return store


def _save_registry(store: dict[str, Any], registry_path: Path | None = None) -> None:
    path = registry_path or default_registry_path()
    store["updatedAt"] = _utc_now_iso()
    _write_json(path, store)


def _normalized_roots(store: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in list(store.get("roots") or []) if isinstance(item, dict)]


def _coerce_budget(raw: Any) -> dict[str, int]:
    budget: dict[str, int] = {}
    source = raw if isinstance(raw, dict) else {}
    for key, default in MANAGED_SCAN_BUDGET_DEFAULTS.items():
        minimum, maximum = MANAGED_SCAN_BUDGET_LIMITS[key]
        try:
            value = int(source.get(key) or default)
        except (TypeError, ValueError):
            value = default
        budget[key] = max(minimum, min(maximum, value))
    return budget


def _managed_root_file_budget(entry: dict[str, Any]) -> int:
    """该受管根的单文件预算（zip 条目反解上限），缺省回退默认预算。"""

    budget = entry.get("scanBudget") if isinstance(entry.get("scanBudget"), dict) else {}
    minimum, maximum = MANAGED_SCAN_BUDGET_LIMITS["maxFileBytes"]
    try:
        value = int(budget.get("maxFileBytes"))
    except (TypeError, ValueError):
        return MANAGED_SCAN_BUDGET_DEFAULTS["maxFileBytes"]
    return max(minimum, min(maximum, value))


def _coerce_category_policy(raw: Any) -> dict[str, Any]:
    policy: dict[str, Any] = {}
    source = raw if isinstance(raw, dict) else {}
    enabled_categories = [
        str(item).strip()
        for item in list(source.get("enableCategories") or [])[:32]
        if str(item).strip() in MANAGED_SOURCE_ROOT_CATEGORIES
    ]
    if enabled_categories:
        policy["enableCategories"] = enabled_categories
    for key, value in list(source.items())[:64]:
        if key == "enableCategories":
            continue
        segment = str(key or "").strip().strip("/").lower()
        category = str(value or "").strip()
        if segment and category in MANAGED_SOURCE_ROOT_CATEGORIES:
            policy[segment] = category
    return policy


def _coerce_allowed_types(raw: Any) -> list[str]:
    if raw is None:
        return sorted(MANAGED_SOURCE_ROOT_ALLOWED_EXTENSIONS)
    if not isinstance(raw, list):
        return sorted(MANAGED_SOURCE_ROOT_ALLOWED_EXTENSIONS)
    values: list[str] = []
    for item in raw[:64]:
        suffix = str(item or "").strip().lower()
        if not suffix.startswith("."):
            suffix = f".{suffix}"
        if suffix in MANAGED_SOURCE_ROOT_ALLOWED_EXTENSIONS and suffix not in values:
            values.append(suffix)
    return values or sorted(MANAGED_SOURCE_ROOT_ALLOWED_EXTENSIONS)


def register_managed_source_root(payload: dict[str, Any] | None = None, *, registry_path: Path | None = None) -> dict[str, Any]:
    """登记一个桌面受管资料根；localPath 只落在本 registry。"""

    request = payload if isinstance(payload, dict) else {}
    raw_path = str(request.get("localPath") or request.get("path") or "").strip()
    if not raw_path:
        raise ManagedSourceRootError("Managed source root localPath is required.")
    try:
        root_path = Path(os.path.expandvars(raw_path)).expanduser()
        resolved_root = root_path.resolve()
    except (OSError, ValueError) as exc:
        raise ManagedSourceRootError(f"Managed source root path cannot be resolved: {raw_path}") from exc
    if not resolved_root.exists() or not resolved_root.is_dir():
        raise ManagedSourceRootError(f"Managed source root path must be an existing directory: {raw_path}")

    store = _load_registry(registry_path)
    roots = _normalized_roots(store)
    for existing in roots:
        try:
            existing_resolved = Path(str(existing.get("localPath") or "")).resolve()
        except (OSError, ValueError):
            continue
        if existing_resolved == resolved_root:
            raise ManagedSourceRootError(
                f"Managed source root already registered for this path: {existing.get('rootId', '')}"
            )

    display_name = str(request.get("displayName") or "").strip()[:120] or resolved_root.name
    root_id = str(request.get("rootId") or "").strip().lower()
    if not root_id:
        digest = hashlib.sha256(str(resolved_root).lower().encode("utf-8")).hexdigest()[:10]
        root_id = f"msroot-{digest}"
    if not ROOT_ID_PATTERN.match(root_id):
        raise ManagedSourceRootError(
            "Managed source rootId must match ^[a-z0-9][a-z0-9-]{2,62}$."
        )
    if any(item.get("rootId") == root_id for item in roots):
        raise ManagedSourceRootError(f"Managed source rootId already registered: {root_id}")

    trust_class = str(request.get("trustClass") or "operator_managed").strip()
    if trust_class not in MANAGED_SOURCE_ROOT_TRUST_CLASSES:
        raise ManagedSourceRootError(f"Unsupported managed source root trustClass: {trust_class}")

    now = _utc_now_iso()
    entry = {
        "rootId": root_id,
        "displayName": display_name,
        "localPath": str(resolved_root),
        "categoryPolicy": _coerce_category_policy(request.get("categoryPolicy")),
        "allowedTypes": _coerce_allowed_types(request.get("allowedTypes")),
        "trustClass": trust_class,
        "enabled": bool(request.get("enabled", True)),
        "registeredBy": str(request.get("registeredBy") or "").strip()[:160] or "operator",
        "registeredAt": now,
        "lastScanAt": "",
        "scanBudget": _coerce_budget(request.get("scanBudget")),
    }
    roots.append(entry)
    store["roots"] = roots
    _save_registry(store, registry_path)
    return dict(entry)


def list_managed_source_roots(*, registry_path: Path | None = None) -> dict[str, Any]:
    store = _load_registry(registry_path)
    roots = _normalized_roots(store)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "storeKind": STORE_KIND,
        "roots": roots,
        "updatedAt": str(store.get("updatedAt") or ""),
    }


def get_managed_source_root(root_id: str, *, registry_path: Path | None = None) -> dict[str, Any] | None:
    normalized = str(root_id or "").strip().lower()
    if not normalized:
        return None
    for entry in _normalized_roots(_load_registry(registry_path)):
        if str(entry.get("rootId") or "") == normalized:
            return entry
    return None


def remove_managed_source_root(root_id: str, *, registry_path: Path | None = None) -> dict[str, Any]:
    normalized = str(root_id or "").strip().lower()
    store = _load_registry(registry_path)
    roots = _normalized_roots(store)
    remaining = [item for item in roots if str(item.get("rootId") or "") != normalized]
    if len(remaining) == len(roots):
        raise ManagedSourceRootError(f"Managed source root not found: {normalized}")
    store["roots"] = remaining
    _save_registry(store, registry_path)
    return {"removed": normalized, "remainingCount": len(remaining)}


def mark_managed_root_scanned(root_id: str, *, registry_path: Path | None = None) -> None:
    normalized = str(root_id or "").strip().lower()
    store = _load_registry(registry_path)
    roots = _normalized_roots(store)
    changed = False
    for entry in roots:
        if str(entry.get("rootId") or "") == normalized:
            entry["lastScanAt"] = _utc_now_iso()
            changed = True
    if changed:
        store["roots"] = roots
        _save_registry(store, registry_path)


def category_allows_evidence(category: str) -> bool:
    return bool(MANAGED_SOURCE_ROOT_CATEGORIES.get(category, {}).get("allowedForEvidence", True))


def category_enabled_by_default(category: str) -> bool:
    return bool(MANAGED_SOURCE_ROOT_CATEGORIES.get(category, {}).get("enabledByDefault", True))


def _first_path_segment(relative_path: str) -> str:
    return relative_path.replace("\\", "/").split("/", 1)[0].strip()


def derive_managed_category(relative_path: str, category_policy: dict[str, str] | None = None) -> str:
    """按根内一级子目录名前缀映射类别；categoryPolicy 覆盖默认映射。"""

    segment = _first_path_segment(relative_path).lower()
    if not segment:
        return FALLBACK_CATEGORY
    policy = category_policy if isinstance(category_policy, dict) else {}
    if segment in policy:
        return policy[segment]
    prefix_match = re.match(r"^(\d{1,3})", segment)
    if prefix_match:
        numeric_prefix = prefix_match.group(1)
        if f"{numeric_prefix:0>2}" in policy:
            return policy[f"{numeric_prefix:0>2}"]
        if numeric_prefix in policy:
            return policy[numeric_prefix]
        mapped = DEFAULT_CATEGORY_PREFIX_MAP.get(numeric_prefix.zfill(2))
        if mapped:
            return mapped
    for keyword, category in DEFAULT_CATEGORY_NAME_KEYWORDS:
        if keyword in segment:
            return category
    return FALLBACK_CATEGORY


def validate_relative_path(relative_path: str) -> list[str]:
    """受管根内相对路径校验：拒绝 ``..``、绝对段、盘符、反斜杠与空段。"""

    issues: list[str] = []
    value = str(relative_path or "")
    if not value.strip():
        return ["empty_relative_path"]
    if len(value) > _MAX_RELATIVE_PATH_LENGTH:
        issues.append("relative_path_too_long")
    if "\\" in value:
        issues.append("backslash_in_relative_path")
    if value.startswith(("/", "~")):
        issues.append("absolute_relative_path")
    if re.match(r"^[A-Za-z]:", value):
        issues.append("drive_letter_in_relative_path")
    parts = value.split("/")
    if any(part in {"..", "."} for part in parts):
        issues.append("dot_segment_in_relative_path")
    if any(part == "" for part in parts):
        issues.append("empty_segment_in_relative_path")
    if any("\x00" in part for part in parts):
        issues.append("null_byte_in_relative_path")
    return issues


def build_managed_locator(root_id: str, relative_path: str) -> str:
    return f"{LOCATOR_SCHEME}{str(root_id).strip().lower()}/{str(relative_path).strip('/')}"


def build_zip_entry_locator(root_id: str, zip_relative_path: str, entry_name: str) -> str:
    return f"{build_managed_locator(root_id, zip_relative_path)}!/{str(entry_name).strip('/')}"


def parse_managed_locator(locator: str) -> dict[str, str]:
    """``managed://<rootId>/<relative>[!/<zip-entry>]`` → 结构化字段。"""

    raw = str(locator or "").strip()
    if not raw.startswith(LOCATOR_SCHEME):
        raise ManagedSourceRootError("Locator must use the managed:// scheme.")
    remainder = raw[len(LOCATOR_SCHEME):]
    if "!" in remainder:
        root_and_zip, _, entry = remainder.partition("!")
        entry = entry.lstrip("/")
    else:
        root_and_zip, entry = remainder, ""
    root_id, _, relative = root_and_zip.partition("/")
    root_id = root_id.strip().lower()
    relative = relative.strip("/")
    if not root_id or not relative:
        raise ManagedSourceRootError("managed:// locator requires rootId and relative path.")
    issues = validate_relative_path(relative)
    if issues:
        raise ManagedSourceRootError(f"managed:// locator relative path rejected: {issues[0]}")
    normalized_entry = ""
    if entry:
        entry = entry.replace("\\", "/").lstrip("/")
        if not entry or len(entry) > _MAX_ZIP_ENTRY_NAME_LENGTH:
            raise ManagedSourceRootError("managed:// locator zip entry name rejected.")
        if entry.startswith("/") or re.match(r"^[A-Za-z]:", entry) or ".." in entry.split("/"):
            raise ManagedSourceRootError("managed:// locator zip entry escapes the archive.")
        normalized_entry = entry
    return {
        "rootId": root_id,
        "relativePath": relative,
        "zipEntry": normalized_entry,
    }


def _contained_resolve(root_path: Path, relative_path: str) -> Path:
    issues = validate_relative_path(relative_path)
    if issues:
        raise ManagedSourceRootError(f"Relative path rejected: {issues[0]}")
    candidate = root_path / relative_path
    try:
        resolved = candidate.resolve()
    except (OSError, ValueError) as exc:
        raise ManagedSourceRootError("Relative path cannot be resolved inside the managed root.") from exc
    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise ManagedSourceRootError("Resolved path escapes the managed root (symlink or traversal).") from exc
    return resolved


def resolve_managed_locator(locator: str, *, allow_disabled: bool = False, registry_path: Path | None = None) -> dict[str, Any]:
    """授权边界内反解 managed:// locator 为本地路径。

    zip 条目（``!`` 形式）会展开到一次性临时目录，调用方负责调用 ``cleanup``。
    返回值不含根外绝对路径以外的泄漏面：rootPath 仅授权调用方（导入链/提炼链）
    可见，禁止写入 DataRecord/manifest/日志。
    """

    parsed = parse_managed_locator(locator)
    entry = get_managed_source_root(parsed["rootId"], registry_path=registry_path)
    if entry is None:
        raise ManagedSourceRootError(f"Managed source root is not registered: {parsed['rootId']}")
    if not bool(entry.get("enabled", True)) and not allow_disabled:
        raise ManagedSourceRootError(f"Managed source root is disabled: {parsed['rootId']}")
    try:
        root_path = Path(str(entry.get("localPath") or "")).resolve()
    except (OSError, ValueError) as exc:
        raise ManagedSourceRootError(f"Managed source root path is invalid: {parsed['rootId']}") from exc
    target = _contained_resolve(root_path, parsed["relativePath"])
    cleanup = None
    if parsed["zipEntry"]:
        if not target.exists() or not target.is_file():
            raise ManagedSourceRootError(f"Managed archive is missing: {parsed['relativePath']}")
        max_entry_bytes = _managed_root_file_budget(entry)
        extracted_dir = Path(tempfile.mkdtemp(prefix="msr-zip-")).resolve()
        try:
            with zipfile.ZipFile(target) as archive:
                info = archive.getinfo(parsed["zipEntry"])
                if info.is_dir():
                    raise ManagedSourceRootError("managed:// zip entry is a directory.")
                if info.flag_bits & 0x1:
                    raise ManagedSourceRootError("managed:// zip entry is encrypted; blocked.")
                if info.file_size > max_entry_bytes:
                    raise ManagedSourceRootError(
                        f"zip entry exceeds size budget: {parsed['zipEntry']} "
                        f"declared {info.file_size} > {max_entry_bytes}"
                    )
                dest = _contained_resolve(extracted_dir, "_entry_")
                dest.parent.mkdir(parents=True, exist_ok=True)
                # remaining 递减读取（同 local_parsing._safe_extract_entry）：
                # 声明超限已在上面拦截，这里兜底「声明与实际不符」的读取超限。
                remaining = info.file_size
                written = 0
                with archive.open(info) as source_handle, open(dest, "wb") as target_handle:
                    while chunk := source_handle.read(min(1024 * 1024, remaining or 1024 * 1024)):
                        target_handle.write(chunk)
                        written += len(chunk)
                        remaining -= len(chunk)
                        if written > max_entry_bytes:
                            raise ManagedSourceRootError(
                                f"zip entry exceeds size budget: {parsed['zipEntry']} "
                                f"read {written} > {max_entry_bytes}"
                            )
        except ManagedSourceRootError:
            import shutil

            shutil.rmtree(extracted_dir, ignore_errors=True)
            raise
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            import shutil

            shutil.rmtree(extracted_dir, ignore_errors=True)
            raise ManagedSourceRootError(f"Managed archive entry cannot be extracted: {exc}") from exc
        final_path = dest
        archive_path = target

        def _cleanup() -> None:
            import shutil

            shutil.rmtree(extracted_dir, ignore_errors=True)

        cleanup = _cleanup
    else:
        if not target.exists():
            raise ManagedSourceRootError(f"Managed source file is missing: {parsed['relativePath']}")
        final_path = target
        archive_path = None
    return {
        "rootId": parsed["rootId"],
        "relativePath": parsed["relativePath"],
        "zipEntry": parsed["zipEntry"],
        "rootPath": root_path,
        "path": final_path,
        "archivePath": archive_path,
        "entry": entry,
        "cleanup": cleanup,
    }
