"""Active skill contracts for cross-turn skill guidance."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


ACTIVE_SKILL_CONTEXT_HEADER = "## Active Skill Context"
ACTIVE_SKILL_CONTRACT_SCHEMA_VERSION = 1
MAX_ACTIVE_SKILL_RULES = 8
MAX_ACTIVE_SKILL_CONTEXT_CHARS = 4_000


def build_active_skill_contract(
    invocation: Any,
    *,
    activated_at: str = "",
    activated_turn_id: str = "",
    scope: str = "task",
) -> dict[str, Any] | None:
    if not isinstance(invocation, dict):
        return None
    skill = invocation.get("_skill")
    if skill is None:
        return None
    content = str(getattr(skill, "content", "") or "")
    description = str(getattr(skill, "description", "") or invocation.get("description") or "").strip()
    skill_hash = str(getattr(skill, "content_hash", "") or invocation.get("skillHash") or "").strip()
    skill_path = str(getattr(skill, "path", "") or invocation.get("skillPath") or "").strip()
    return normalize_active_skill_contract(
        {
            "schemaVersion": ACTIVE_SKILL_CONTRACT_SCHEMA_VERSION,
            "status": "active",
            "scope": str(scope or "task").strip() or "task",
            "command": str(invocation.get("command") or "").strip(),
            "args": str(invocation.get("args") or "").strip(),
            "skillName": str(getattr(skill, "name", "") or invocation.get("skillName") or "").strip(),
            "skillPath": skill_path,
            "skillHash": skill_hash,
            "skillContentLength": int(getattr(skill, "content_length", 0) or invocation.get("skillContentLength") or 0),
            "description": description,
            "keyRules": _extract_skill_contract_rules(content),
            "activatedAt": str(activated_at or "").strip(),
            "activatedTurnId": str(activated_turn_id or "").strip(),
        }
    )


def normalize_active_skill_contract(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    command = _normalize_alias(value.get("command") or value.get("skillName") or "")
    skill_name = str(value.get("skillName") or value.get("skill_name") or command).strip()
    skill_path = str(value.get("skillPath") or value.get("skill_path") or "").strip()
    skill_hash = str(value.get("skillHash") or value.get("skill_hash") or "").strip()
    if not command or not skill_name:
        return None
    rules = [
        _clean_rule_line(item)
        for item in list(value.get("keyRules") or value.get("key_rules") or [])
        if _clean_rule_line(item)
    ][:MAX_ACTIVE_SKILL_RULES]
    status = str(value.get("status") or "active").strip().lower() or "active"
    if status not in {"active", "stale", "missing"}:
        status = "active"
    return {
        "schemaVersion": ACTIVE_SKILL_CONTRACT_SCHEMA_VERSION,
        "status": status,
        "scope": str(value.get("scope") or "task").strip() or "task",
        "command": command,
        "args": str(value.get("args") or "").strip(),
        "skillName": skill_name,
        "skillPath": skill_path,
        "skillHash": skill_hash,
        "skillContentLength": _coerce_nonnegative_int(value.get("skillContentLength") or value.get("skill_content_length") or 0),
        "description": str(value.get("description") or "").strip(),
        "keyRules": rules,
        "activatedAt": str(value.get("activatedAt") or value.get("activated_at") or "").strip(),
        "activatedTurnId": str(value.get("activatedTurnId") or value.get("activated_turn_id") or "").strip(),
        "staleReason": str(value.get("staleReason") or value.get("stale_reason") or "").strip(),
    }


def refresh_active_skill_contract_status(contract: Any) -> dict[str, Any] | None:
    normalized = normalize_active_skill_contract(contract)
    if normalized is None:
        return None
    skill_path = str(normalized.get("skillPath") or "").strip()
    expected_hash = str(normalized.get("skillHash") or "").strip()
    if not skill_path:
        return normalized
    path = Path(skill_path)
    if not path.is_file():
        return {**normalized, "status": "missing", "staleReason": "skill_file_missing"}
    if expected_hash:
        try:
            current = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return {**normalized, "status": "missing", "staleReason": "skill_file_unreadable"}
        current_hash = hashlib.sha256(current.encode("utf-8", errors="replace")).hexdigest()[:16]
        if current_hash != expected_hash:
            return {**normalized, "status": "stale", "staleReason": "skill_hash_changed"}
    return {**normalized, "status": "active", "staleReason": ""}


def build_active_skill_runtime_context(contract: Any) -> str:
    normalized = refresh_active_skill_contract_status(contract)
    if normalized is None:
        return ""
    lines = [
        ACTIVE_SKILL_CONTEXT_HEADER,
        f"Command: /{normalized['command']}",
        f"Skill: {normalized['skillName']}",
        f"SkillPath: {normalized.get('skillPath') or ''}",
        f"SkillHash: {normalized.get('skillHash') or ''}",
        f"Status: {normalized.get('status') or 'active'}",
        f"Scope: {normalized.get('scope') or 'task'}",
        "",
        "Use this compact skill contract for this chat turn. It is a cross-turn reminder derived from a previous slash skill activation; do not treat it as a user-authored message.",
    ]
    description = str(normalized.get("description") or "").strip()
    if description:
        lines.extend(["", "Description:", description])
    args = str(normalized.get("args") or "").strip()
    if args:
        lines.extend(["", "SlashCommandArgs:", args])
    stale_reason = str(normalized.get("staleReason") or "").strip()
    if stale_reason:
        lines.extend(["", "StaleReason:", stale_reason])
    rules = list(normalized.get("keyRules") or [])
    if rules:
        lines.append("")
        lines.append("KeyRules:")
        lines.extend(f"- {rule}" for rule in rules)
    text = "\n".join(lines).strip()
    if len(text) > MAX_ACTIVE_SKILL_CONTEXT_CHARS:
        text = text[:MAX_ACTIVE_SKILL_CONTEXT_CHARS].rstrip() + "\n\n[Active skill contract truncated.]"
    return text


def _extract_skill_contract_rules(content: str) -> list[str]:
    text = _strip_frontmatter(str(content or ""))
    rules: list[str] = []
    for raw_line in text.splitlines():
        line = _clean_rule_line(raw_line)
        if not line:
            continue
        lowered = line.lower()
        is_candidate = (
            raw_line.lstrip().startswith(("#", "-", "*"))
            or "must" in lowered
            or "不要" in line
            or "必须" in line
            or "should" in lowered
            or "使用" in line
        )
        if not is_candidate:
            continue
        if line not in rules:
            rules.append(line)
        if len(rules) >= MAX_ACTIVE_SKILL_RULES:
            break
    return rules


def _strip_frontmatter(content: str) -> str:
    text = str(content or "")
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end < 0:
        return text
    return text[end + 4 :]


def _clean_rule_line(value: Any) -> str:
    line = str(value or "").strip()
    line = re.sub(r"^#{1,6}\s*", "", line)
    line = re.sub(r"^[-*]\s*", "", line)
    line = re.sub(r"\s+", " ", line).strip()
    return line[:280]


def _normalize_alias(value: Any) -> str:
    alias = str(value or "").strip().lower().removeprefix("/")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", alias):
        return ""
    return alias


def _coerce_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
