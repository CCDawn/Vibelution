#!/usr/bin/env python3
"""把 model_library 条目里错层的 interaction contract 迁到 canonical 形态。

规则（唯一迁移规则，不加戏）：
    schema v2 条目（llm.providers.<pid>.models.<mid>）的 model_protocol 若存的是
    interaction contract（basic_chat / tool_chat / reasoning_chat / responses_agent）：
    - interaction_contract 已有非空值：保留 interaction_contract，仅清空 model_protocol；
    - interaction_contract 为空/缺失：把该值写入 interaction_contract，并清空 model_protocol。
    其余条目一律不动（不做协议改名、不删字段、不做顺手优化）。

校验基准：core/llm/discovery.llm_model_entry_issues。dry-run 输出迁移计划
（迁移后 errors 必须为 0 才算计划有效）；--apply 按 备份 -> 原子写 -> 写后重载校验
执行，任一步失败回滚到写前字节。

写入语义复用 config 层既有设施：config.operator_config_transaction.replace_toml_scalar
（保格式外科替换）做文本修改，config.public_config._config_edit_lock 做跨进程编辑锁，
原子写沿用 config/llm_schema_upgrader.py 等模块的 mkstemp+fsync+os.replace 模式。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.llm_identity import make_model_ref
from config.llm_security import validate_llm_public_config
from config.operator_config_transaction import (
    _normalized_table_path,
    _table_spans,
    replace_toml_scalar,
)
from config.paths import resolve_config_path
from config.public_config import _config_edit_lock, build_effective_config
from config.toml_writer import format_toml_scalar
from core.llm.discovery import (
    build_llm_profile_from_model_entry,
    doctor_model_library,
    llm_model_entry_issues,
)

INTERACTION_CONTRACT_VALUES = frozenset(
    {"basic_chat", "tool_chat", "reasoning_chat", "responses_agent"}
)


class MigrationError(RuntimeError):
    """迁移计划无效或 apply 失败。"""


# ---------------------------------------------------------------------------
# 基础设施（与 config/llm_schema_upgrader.py 的既有原子写语义一致）
# ---------------------------------------------------------------------------


def _strict_atomic_write(path: Path, payload: bytes) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _parse_public_config(text: str) -> dict[str, Any]:
    parsed = tomllib.loads(text)
    if not isinstance(parsed, dict):
        raise MigrationError("config root must be a table")
    return parsed


def _iter_model_entries(public: dict[str, Any]):
    llm = public.get("llm") if isinstance(public, dict) else None
    if not isinstance(llm, dict):
        return
    providers = llm.get("providers")
    if not isinstance(providers, dict):
        return
    for provider_id, provider in providers.items():
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, dict):
            continue
        for model_key, entry in models.items():
            if isinstance(entry, dict):
                yield str(provider_id), str(model_key), entry


def _entry_table_path(provider_id: str, model_key: str) -> tuple[str, ...]:
    return ("llm", "providers", provider_id, "models", model_key)


# ---------------------------------------------------------------------------
# 文本外科修改
# ---------------------------------------------------------------------------


def _insert_table_key(
    text: str, table_path: tuple[str, ...], key: str, value: Any
) -> str:
    """在既有表头部之后插入 `key = value` 行（键缺失时的兜底路径）。"""

    target = _normalized_table_path(table_path)
    lines = text.splitlines(keepends=True)
    for span in _table_spans(lines):
        if span.path != target:
            continue
        header = lines[span.start]
        newline = "\r\n" if header.endswith("\r\n") else "\n"
        lines.insert(span.start + 1, f"{key} = {format_toml_scalar(value)}{newline}")
        candidate = "".join(lines)
        tomllib.loads(candidate)
        return candidate
    raise MigrationError(f"TOML table not found: {'.'.join(target)}")


def _set_interaction_contract(
    text: str, table_path: tuple[str, ...], value: str
) -> str:
    try:
        return replace_toml_scalar(text, table_path, "interaction_contract", "", value)
    except ValueError:
        return _insert_table_key(text, table_path, "interaction_contract", value)


def _apply_plan_to_text(original_text: str, plan: list[dict[str, Any]]) -> str:
    after_text = original_text
    for item in plan:
        table_path = _entry_table_path(item["providerId"], item["modelKey"])
        for change in item["changes"]:
            field = change["field"]
            if field == "model_protocol":
                after_text = replace_toml_scalar(
                    after_text, table_path, "model_protocol", change["before"], ""
                )
            elif field == "interaction_contract":
                after_text = _set_interaction_contract(after_text, table_path, change["after"])
            else:  # pragma: no cover - 规则封闭，防御未来改动
                raise MigrationError(f"unsupported migration field: {field}")
    return after_text


# ---------------------------------------------------------------------------
# 迁移计划
# ---------------------------------------------------------------------------


def build_plan(public: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """扫描条目，返回 (plan, skipped)。纯内存，不触碰文件。"""

    plan: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for provider_id, model_key, entry in _iter_model_entries(public):
        raw_protocol = str(entry.get("model_protocol") or "").strip()
        normalized = raw_protocol.lower()
        context = {
            "providerId": provider_id,
            "modelKey": model_key,
            "modelRef": make_model_ref(provider_id, model_key),
        }
        if normalized in INTERACTION_CONTRACT_VALUES:
            current_contract = str(entry.get("interaction_contract") or "").strip()
            changes: list[dict[str, Any]] = []
            if not current_contract:
                changes.append(
                    {"field": "interaction_contract", "before": "", "after": normalized}
                )
            changes.append({"field": "model_protocol", "before": raw_protocol, "after": ""})
            plan.append({**context, "changes": changes})
        elif raw_protocol:
            skipped.append(
                {
                    **context,
                    "reason": (
                        f"model_protocol=`{raw_protocol}` 不是 interaction contract；"
                        "协议名保持不动（由协议族表与 Wave1 校验闸把关）"
                    ),
                }
            )
        else:
            skipped.append({**context, "reason": "model_protocol 为空；无需迁移"})
    return plan, skipped


# ---------------------------------------------------------------------------
# issues 校验（与 doctor_model_library 同一套规则）
# ---------------------------------------------------------------------------


def _base_payload(effective: Any) -> dict[str, Any]:
    profile = None
    try:
        profile = effective.llm.get_profile(role="primary")
    except Exception:
        profile = None
    if profile is None:
        profile = next(iter(effective.llm.profiles.values()), None)
    return dict(profile.model_dump()) if profile is not None else {}


def entry_issues(effective: Any, provider_id: str, model_key: str) -> tuple[list[str], list[str]]:
    """单条目 issues；从运行投影（schema v2 -> runtime）取条目与 provider。"""

    model_ref = make_model_ref(provider_id, model_key)
    library = effective.llm.model_library or {}
    entry = library.get(model_ref)
    provider = effective.llm.providers.get(provider_id)
    if not isinstance(entry, dict) or provider is None:
        return [f"model_ref `{model_ref}` 在运行投影中缺失"], []
    profile = build_llm_profile_from_model_entry(
        _base_payload(effective),
        entry,
        profile_id=model_ref,
        provider_id=provider_id,
        model_ref=model_ref,
        model_name=str(entry.get("model") or ""),
    )
    return llm_model_entry_issues(profile, provider, model_entry=entry)


def _doctor_error_findings(effective: Any) -> list[dict[str, Any]]:
    return [finding for finding in doctor_model_library(effective) if finding.get("errors")]


def _finding_key(model_ref: str, error: str) -> tuple[str, str]:
    return (str(model_ref or ""), str(error))


def validate_candidate(
    public: dict[str, Any],
    plan: list[dict[str, Any]],
    baseline_findings: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """候选公开配置的完整校验：canonical -> runtime 投影 -> 条目 issues -> doctor。

    硬闸（任一触发即抛 MigrationError）：
    - 任一迁移条目 llm_model_entry_issues errors 非空；
    - doctor 出现 baseline 之外的新错误（无回归闸；baseline 取不到时退化为全绿闸）。

    迁移范围之外的既有 doctor 错误不阻断迁移，作为 persistentDoctorErrorFindings
    返回给调用方如实上报（迁移规则不越权修它们）。
    """

    validate_llm_public_config(public)
    effective = build_effective_config(copy.deepcopy(public))
    issues: dict[str, dict[str, list[str]]] = {}
    for item in plan:
        errors, warnings = entry_issues(effective, item["providerId"], item["modelKey"])
        if errors:
            raise MigrationError(
                f"迁移后条目 {item['modelRef']} 仍有校验错误: {'; '.join(errors)}"
            )
        issues[item["modelRef"]] = {"errors": errors, "warnings": warnings}
    doctor_errors = _doctor_error_findings(effective)
    baseline_keys: set[tuple[str, str]] = set()
    if baseline_findings is not None:
        for finding in baseline_findings:
            for error in finding.get("errors") or []:
                baseline_keys.add(_finding_key(finding.get("modelRef"), error))
    persistent: list[dict[str, Any]] = []
    for finding in doctor_errors:
        unknown = [
            error
            for error in finding.get("errors") or []
            if _finding_key(finding.get("modelRef"), error) not in baseline_keys
        ]
        if unknown:
            raise MigrationError(
                f"迁移引入新错误 {finding.get('modelRef')}: {'; '.join(unknown)}"
            )
        persistent.append(
            {"modelRef": finding.get("modelRef"), "errors": list(finding.get("errors") or [])}
        )
    return {
        "entryIssues": issues,
        "persistentDoctorErrorFindings": persistent,
    }


# ---------------------------------------------------------------------------
# dry-run / apply
# ---------------------------------------------------------------------------


def _load_state(config_path: Path) -> tuple[bytes, dict[str, Any]]:
    original_bytes = config_path.read_bytes()
    try:
        original_text = original_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MigrationError(f"config is not valid UTF-8: {config_path}") from exc
    return original_bytes, _parse_public_config(original_text)


def _before_snapshot(public: dict[str, Any], plan: list[dict[str, Any]]) -> dict[str, Any]:
    """before 侧快照：迁移条目 issues + doctor 错误基线；取不到时降级为信息性错误。"""

    try:
        effective = build_effective_config(copy.deepcopy(public))
    except Exception as exc:
        return {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
            "entries": {},
            "doctorErrorFindings": [],
        }
    entries: dict[str, dict[str, list[str]]] = {}
    for item in plan:
        errors, warnings = entry_issues(effective, item["providerId"], item["modelKey"])
        entries[item["modelRef"]] = {"errors": errors, "warnings": warnings}
    doctor_error_findings = [
        {"modelRef": finding.get("modelRef"), "errors": list(finding.get("errors") or [])}
        for finding in _doctor_error_findings(effective)
    ]
    return {
        "available": True,
        "error": "",
        "entries": entries,
        "doctorErrorFindings": doctor_error_findings,
    }


def run_dry_run(config_path: Path, *, as_json: bool) -> int:
    original_bytes, public = _load_state(config_path)
    plan, skipped = build_plan(public)
    llm_section = public.get("llm") if isinstance(public.get("llm"), dict) else {}
    schema_version = int(llm_section.get("schema_version") or 0)
    total_entries = sum(1 for _ in _iter_model_entries(public))

    before = _before_snapshot(public, plan)
    baseline = before["doctorErrorFindings"] if before["available"] else None

    validation: dict[str, Any] = {"entryIssues": {}, "persistentDoctorErrorFindings": []}
    if plan:
        candidate_text = _apply_plan_to_text(original_bytes.decode("utf-8"), plan)
        candidate = _parse_public_config(candidate_text)
        validation = validate_candidate(candidate, plan, baseline)

    plan_payload = [
        {
            **item,
            "issuesBefore": before["entries"].get(item["modelRef"]),
            "issuesAfter": validation["entryIssues"].get(item["modelRef"]),
        }
        for item in plan
    ]
    valid = all(
        (item["issuesAfter"] or {}).get("errors") == [] for item in plan_payload
    ) if plan else True

    payload = {
        "mode": "dry-run",
        "configPath": str(config_path),
        "schemaVersion": schema_version,
        "totalEntries": total_entries,
        "planCount": len(plan),
        "skippedCount": len(skipped),
        "plan": plan_payload,
        "skipped": skipped,
        "valid": valid,
        "baselineAvailable": before["available"],
        "persistentDoctorErrorFindings": validation["persistentDoctorErrorFindings"],
        "applied": False,
        "backupPath": None,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human(payload)
    return 0 if valid else 1


def _backup_config(config_path: Path, original_bytes: bytes) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_path = config_path.parent / f"{config_path.name}.bak-{stamp}"
    counter = 1
    while backup_path.exists():
        backup_path = config_path.parent / f"{config_path.name}.bak-{stamp}-{counter}"
        counter += 1
    _strict_atomic_write(backup_path, original_bytes)
    return backup_path


def _post_apply_gate(
    config_path: Path,
    plan: list[dict[str, Any]],
    baseline_findings: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """写后重载校验：重新读盘 -> canonical -> runtime -> 条目 issues -> doctor 无回归。"""

    persisted = _parse_public_config(config_path.read_bytes().decode("utf-8"))
    return validate_candidate(persisted, plan, baseline_findings)


def run_apply(config_path: Path, *, as_json: bool) -> int:
    original_bytes, public = _load_state(config_path)
    plan, skipped = build_plan(public)
    llm_section = public.get("llm") if isinstance(public.get("llm"), dict) else {}
    total_entries = sum(1 for _ in _iter_model_entries(public))

    if not plan:
        before = _before_snapshot(public, plan)
        payload = {
            "mode": "apply",
            "configPath": str(config_path),
            "schemaVersion": int(llm_section.get("schema_version") or 0),
            "totalEntries": total_entries,
            "planCount": 0,
            "skippedCount": len(skipped),
            "plan": [],
            "skipped": skipped,
            "valid": True,
            "baselineAvailable": before["available"],
            "persistentDoctorErrorFindings": before["doctorErrorFindings"],
            "applied": False,
            "noop": True,
            "backupPath": None,
        }
        if as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("没有需要迁移的条目；未改动配置文件。")
            persistent = before["doctorErrorFindings"]
            if persistent:
                print("迁移范围外的既有 doctor 错误（不越权修改，另行治理）:")
                for finding in persistent:
                    print(f"  - {finding.get('modelRef')}: {'; '.join(finding.get('errors') or [])}")
        return 0

    # 写前先在内存里完整验证候选文本（失败即不动文件）；doctor 基线取写前状态。
    before = _before_snapshot(public, plan)
    baseline = before["doctorErrorFindings"] if before["available"] else None
    candidate_text = _apply_plan_to_text(original_bytes.decode("utf-8"), plan)
    candidate = _parse_public_config(candidate_text)
    validate_candidate(candidate, plan, baseline)
    candidate_bytes = candidate_text.encode("utf-8")

    backup_path = _backup_config(config_path, original_bytes)
    try:
        with _config_edit_lock(config_path):
            current_bytes = config_path.read_bytes()
            if current_bytes != original_bytes:
                raise MigrationError(
                    "配置文件在迁移准备阶段被并发修改（stale bytes）；已中止，未写入"
                )
            _strict_atomic_write(config_path, candidate_bytes)
            if config_path.read_bytes() != candidate_bytes:
                raise MigrationError("写后读回不一致（atomic write mismatch）")
            validation = _post_apply_gate(config_path, plan, baseline)
    except Exception as exc:
        # 任一步失败：回滚到写前字节。
        restored = False
        rollback_error = ""
        try:
            _strict_atomic_write(config_path, original_bytes)
            restored = config_path.read_bytes() == original_bytes
        except Exception as rollback_exc:
            rollback_error = f"{type(rollback_exc).__name__}: {rollback_exc}"
        detail = f"{type(exc).__name__}: {exc}"
        if not restored:
            raise MigrationError(
                f"迁移失败且回滚未完成，请用备份手动恢复 {backup_path}; "
                f"原始错误: {detail}; 回滚错误: {rollback_error}"
            ) from exc
        raise MigrationError(
            f"迁移失败，已回滚到写前内容（备份保留在 {backup_path}）。原因: {detail}"
        ) from exc

    payload = {
        "mode": "apply",
        "configPath": str(config_path),
        "schemaVersion": int((public.get("llm") or {}).get("schema_version") or 0),
        "totalEntries": total_entries,
        "planCount": len(plan),
        "skippedCount": len(skipped),
        "plan": [
            {**item, "issuesAfter": validation["entryIssues"].get(item["modelRef"])}
            for item in plan
        ],
        "skipped": skipped,
        "valid": True,
        "baselineAvailable": before["available"],
        "persistentDoctorErrorFindings": validation["persistentDoctorErrorFindings"],
        "applied": True,
        "noop": False,
        "backupPath": str(backup_path),
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"已迁移 {len(plan)} 条条目（备份: {backup_path}），写后校验全绿。")
        persistent = validation["persistentDoctorErrorFindings"]
        if persistent:
            print("迁移范围外的既有 doctor 错误（不越权修改，另行治理）:")
            for finding in persistent:
                print(f"  - {finding.get('modelRef')}: {'; '.join(finding.get('errors') or [])}")
    return 0


def _print_human(payload: dict[str, Any]) -> None:
    print(
        f"配置: {payload['configPath']} (schema v{payload.get('schemaVersion', '?')}, "
        f"{payload['totalEntries']} 条模型条目)"
    )
    plan = payload["plan"]
    print(f"待迁移条目: {len(plan)}；保持不动: {payload['skippedCount']}")
    for item in plan:
        changes = ", ".join(
            f"{change['field']}: `{change['before']}` -> `{change['after']}`"
            for change in item["changes"]
        )
        print(f"  - {item['modelRef']}: {changes}")
        before = item.get("issuesBefore") or {}
        if before.get("errors"):
            print(f"      迁移前错误: {'; '.join(before['errors'])}")
        after = item.get("issuesAfter") or {}
        if after.get("warnings"):
            print(f"      迁移后提醒: {'; '.join(after['warnings'])}")
    if payload["valid"]:
        print("计划校验: 迁移条目 llm_model_entry_issues errors = 0，且 doctor 无新增错误；计划有效。")
    else:
        print("计划校验: 存在迁移后错误，计划无效（详见 --json 输出）。")
    persistent = payload.get("persistentDoctorErrorFindings") or []
    if persistent:
        print("迁移范围外的既有 doctor 错误（不越权修改，另行治理）:")
        for finding in persistent:
            print(f"  - {finding.get('modelRef')}: {'; '.join(finding.get('errors') or [])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--dry-run", action="store_true", help="只输出迁移计划，不写盘（默认行为）"
    )
    target.add_argument("--apply", action="store_true", help="备份后原子写入并做写后校验")
    parser.add_argument("--config", default="", help="config.toml 路径（默认活配置）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args(argv)

    config_path = (
        Path(args.config).expanduser().resolve() if args.config else resolve_config_path()
    )
    if not config_path.is_file():
        print(f"config file not found: {config_path}", file=sys.stderr)
        return 2
    try:
        if args.apply:
            return run_apply(config_path, as_json=args.json)
        return run_dry_run(config_path, as_json=args.json)
    except MigrationError as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
