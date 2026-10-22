"""Managed write actions delegated to the personal assistant manage tool.

Three closed, high-risk write actions reached only through
``personal_assistant_manage_tool``'s dispatch table (per-call approval):

- ``team_create``: create an empty Team or materialize a Team template.
- ``knowledge_ingest``: direct-ingest one screened owner inbox source as a
  formal knowledge item (staged document content only; the PA never authors
  knowledge content and the human per-call approval is the review gate).
- ``config_update``: a closed operator-config preference whitelist applied
  through the optimistic-hash operator config transaction.

None of these accept arbitrary API paths, TOML text, credential material, or
provider/gateway configuration. Unknown keys fail closed: one invalid entry
rejects the whole request.
"""

from __future__ import annotations

import json
import re
from typing import Any

_MAX_UPDATES = 20
_MAX_TAG_LENGTH = 64

# --- Closed config whitelist -------------------------------------------------
# Only operator preference keys with no secret material. Credentials always go
# through env-var credential_ref values owned by [llm.providers.*]; provider
# tables and [external_agent_gateway] are untouchable by design.

_USER_PROFILE_TEXT_LIMITS: dict[str, int] = {
    "display_name": 120,
    "bio": 2000,
    "avatar_preset": 64,
}
_USER_PROFILE_PREFERENCES_KEY = "preferences"
_UI_LANGUAGE_VALUES = {"zh", "en"}
_UI_INT_RANGES: dict[str, tuple[int, int]] = {
    "max_log_entries": (1, 10000),
    "refresh_rate": (1, 120),
}
_UI_BOOL_KEYS = {"show_ascii_art", "show_welcome"}
_LLM_MODEL_REF_KEY = re.compile(r"^profiles\.([A-Za-z0-9_-]{1,64})\.model_ref$")
_MODEL_REF_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}/[^/\s]{1,120}$")
_BARE_TOML_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_SECTION_HEADER = re.compile(r"^\s*\[(?P<header>[^\]]+)\]\s*$")

_FORBIDDEN_MARKERS = (
    "credential",
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "external_agent_gateway",
    "providers",
)


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _fail(*, error: str, message: str, status: str = "error", **fields: Any) -> str:
    payload: dict[str, Any] = {"ok": False, "status": status, "error": error, "message": message}
    payload.update({key: value for key, value in fields.items() if value not in (None, "")})
    return _json_result(payload)


def _clean_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


# --- team_create -------------------------------------------------------------


def team_create_tool(name: str, description: str = "", templateId: str = "") -> str:
    """Create an empty Team, or materialize a Team template by id.

    With ``templateId`` (e.g. "dev-team") the authoritative template service
    builds the role agents, session, chat room and canvas. Without it the Team
    CRUD empty-team path applies (same-name empty teams are reused). Errors
    from the owning services are returned verbatim for the assistant.
    """

    normalized_name = " ".join(str(name or "").split())
    if not normalized_name or len(normalized_name) > 120:
        return _fail(error="invalid_input", message="团队名称必填，且不超过 120 个字符。")
    normalized_description = _clean_text(description, 600)
    normalized_template_id = str(templateId or "").strip()
    try:
        if normalized_template_id:
            from core.web.services.team_template_service import instantiate_team_template

            result = instantiate_team_template(normalized_template_id, name=normalized_name)
            team = result.get("team") if isinstance(result.get("team"), dict) else {}
            team_id = str(team.get("teamId") or "").strip()
            if not team_id:
                return _fail(error="template_failed", message="模板实例化未返回 Team。")
            return _json_result({
                "ok": True,
                "status": "ok",
                "message": f"已按模板 {normalized_template_id} 创建团队。",
                "teamId": team_id,
                "templateId": normalized_template_id,
            })
        from core.web.services.team import team_crud

        team = team_crud.create_team(
            name=normalized_name,
            description=normalized_description,
            team_source="personal_assistant",
        )
        team_id = str(team.get("teamId") or "").strip()
        if not team_id:
            return _fail(error="team_failed", message="团队创建未返回 teamId。")
        return _json_result({
            "ok": True,
            "status": "ok",
            "message": "团队已创建。",
            "teamId": team_id,
        })
    except ValueError as exc:
        return _fail(error="validation_error", message=str(exc))
    except Exception as exc:
        return _fail(error=exc.__class__.__name__, message=str(exc))


# --- knowledge_ingest --------------------------------------------------------


def knowledge_ingest_tool(
    inboxSourceId: str,
    ownerType: str,
    ownerId: str,
    knowledgeBaseId: str = "",
    title: str = "",
    summary: str = "",
    tags: str = "",
) -> str:
    """Direct-ingest one screened owner inbox source as formal knowledge.

    Thin wrapper over ``knowledge_ingestion_tool``'s inbox mode with
    ``content_mode="source_document"``: the staged document text is ingested
    verbatim; the assistant cannot inject or rewrite knowledge content. The
    human per-call approval is the review gate; review state, permissions and
    duplication are enforced by the knowledge service and its errors are
    returned verbatim.
    """

    normalized_inbox_source_id = str(inboxSourceId or "").strip()
    normalized_owner_type = str(ownerType or "").strip().lower()
    normalized_owner_id = str(ownerId or "").strip()
    if not normalized_inbox_source_id or not normalized_owner_type or not normalized_owner_id:
        return _fail(error="invalid_input", message="inboxSourceId、ownerType 和 ownerId 均为必填。")
    normalized_tags = ",".join(
        item.strip()[:_MAX_TAG_LENGTH]
        for item in str(tags or "").replace("，", ",").split(",")
        if item.strip()
    )
    try:
        from tools.team_knowledge_tools import knowledge_ingestion_tool

        raw = knowledge_ingestion_tool(
            knowledge_base_id=str(knowledgeBaseId or "").strip(),
            source_type="",
            source_ref_json="{}",
            proposal_title=_clean_text(title, 200),
            proposal_summary=_clean_text(summary, 400),
            tags=normalized_tags,
            inbox_source_id=normalized_inbox_source_id,
            owner_type=normalized_owner_type,
            owner_id=normalized_owner_id,
            review_decision="accepted",
            content_mode="source_document",
        )
        result = json.loads(raw)
        if not isinstance(result, dict):
            return _fail(error="invalid_result", message="知识入库服务未返回有效回执。")
        if not result.get("ok"):
            # Service errors pass through verbatim (review state, permissions).
            return raw
        direct = result.get("directIngestion") if isinstance(result.get("directIngestion"), dict) else {}
        item = direct.get("item") if isinstance(direct.get("item"), dict) else {}
        projected: dict[str, Any] = {
            "ok": True,
            "status": str(direct.get("status") or result.get("status") or "ingested"),
            "message": "知识来源已入库。",
            "inboxSourceId": normalized_inbox_source_id,
            "ownerType": normalized_owner_type,
            "ownerId": normalized_owner_id,
        }
        knowledge_base_id = str(result.get("knowledgeBaseId") or knowledgeBaseId or "").strip()
        if knowledge_base_id:
            projected["knowledgeBaseId"] = knowledge_base_id
        knowledge_item_id = str(item.get("knowledgeItemId") or "").strip()
        if knowledge_item_id:
            projected["knowledgeItemId"] = knowledge_item_id
        return _json_result(projected)
    except Exception as exc:
        return _fail(error=exc.__class__.__name__, message=str(exc))


# --- config_update -----------------------------------------------------------


def _reject(sections: list[str]) -> ValueError:
    return ValueError(
        "配置更新包含白名单之外的键，整体拒绝："
        + "；".join(sections[:8])
        + "。仅允许用户偏好、界面语言/开关和默认模型档位切换。"
    )


def _validate_one_update(section: Any, key: Any, value: Any) -> tuple[tuple[str, ...], str, Any]:
    normalized_section = str(section or "").strip()
    normalized_key = str(key or "").strip()
    label = f"{normalized_section}.{normalized_key}"

    def forbidden() -> bool:
        lowered = f"{normalized_section}.{normalized_key}".lower()
        return any(marker in lowered for marker in _FORBIDDEN_MARKERS)

    if forbidden():
        raise _reject([label])
    if normalized_section == "user_profile":
        if normalized_key in _USER_PROFILE_TEXT_LIMITS:
            if not isinstance(value, str):
                raise ValueError(f"{label} 需要字符串值。")
            text = value.strip()
            if not text or len(text) > _USER_PROFILE_TEXT_LIMITS[normalized_key]:
                raise ValueError(f"{label} 需要非空且不超过 {_USER_PROFILE_TEXT_LIMITS[normalized_key]} 字符的字符串。")
            return ("user_profile",), normalized_key, text
        if normalized_key == _USER_PROFILE_PREFERENCES_KEY:
            if not isinstance(value, list) or len(value) > 50:
                raise ValueError(f"{label} 需要不超过 50 条的字符串数组。")
            items: list[str] = []
            for entry in value:
                text = str(entry or "").strip()
                if not text or len(text) > 200:
                    raise ValueError(f"{label} 每条偏好需要 1-200 字符。")
                items.append(text)
            if not items:
                raise ValueError(f"{label} 需要至少一条偏好。")
            return ("user_profile",), normalized_key, items
        raise _reject([label])
    if normalized_section == "ui":
        if normalized_key == "language":
            normalized = str(value or "").strip()
            if normalized not in _UI_LANGUAGE_VALUES:
                raise ValueError(f"{label} 仅支持 {'/'.join(sorted(_UI_LANGUAGE_VALUES))}。")
            return ("ui",), normalized_key, normalized
        if normalized_key in _UI_INT_RANGES:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{label} 需要整数。")
            low, high = _UI_INT_RANGES[normalized_key]
            if not low <= value <= high:
                raise ValueError(f"{label} 需要在 {low}-{high} 之间。")
            return ("ui",), normalized_key, value
        if normalized_key in _UI_BOOL_KEYS:
            if not isinstance(value, bool):
                raise ValueError(f"{label} 需要布尔值。")
            return ("ui",), normalized_key, value
        raise _reject([label])
    if normalized_section == "llm":
        match = _LLM_MODEL_REF_KEY.fullmatch(normalized_key)
        if match:
            profile_id = match.group(1)
            if not isinstance(value, str) or not _MODEL_REF_VALUE.match(value.strip()):
                raise ValueError(f"{label} 需要形如 provider/model 的模型引用。")
            return ("llm", "profiles", profile_id), "model_ref", value.strip()
        raise _reject([label])
    raise _reject([label])


def _validate_updates(updates: Any) -> list[tuple[tuple[str, ...], str, Any]]:
    if not isinstance(updates, list) or not updates:
        raise ValueError("updates 必须是非空数组。")
    if len(updates) > _MAX_UPDATES:
        raise ValueError(f"updates 一次最多 {_MAX_UPDATES} 条。")
    normalized: list[tuple[tuple[str, ...], str, Any]] = []
    offending: list[str] = []
    for item in updates:
        if not isinstance(item, dict) or set(item) != {"section", "key", "value"}:
            raise ValueError("updates 每条必须只包含 section、key、value。")
        try:
            normalized.append(_validate_one_update(item["section"], item["key"], item["value"]))
        except ValueError as exc:
            message = str(exc)
            if message.startswith("配置更新包含白名单之外的键"):
                offending.append(f"{item.get('section')}.{item.get('key')}")
                continue
            raise
    if offending:
        # Fail closed: one unknown or forbidden key rejects the whole request.
        raise _reject(offending)
    return normalized


def _format_value(value: Any) -> str:
    from config.toml_writer import format_toml_scalar

    if isinstance(value, list):
        return "[" + ", ".join(format_toml_scalar(item) for item in value) + "]"
    return format_toml_scalar(value)


def _quote_table_part(part: str) -> str:
    return f'"{part}"' if not _BARE_TOML_KEY.match(part) else part


def _upsert_toml_key(text: str, table_path: tuple[str, ...], key: str, value_text: str) -> str:
    """Insert or replace one scalar key under one exact table header.

    Source-preserving: only the target line moves; comments stay. The caller
    re-parses and hash-validates the result inside the config transaction.
    """

    header = "[" + ".".join(_quote_table_part(part) for part in table_path) + "]"
    assignment = f"{key} = {value_text}\n"
    lines = text.splitlines(keepends=True)
    header_index: int | None = None
    for index, line in enumerate(lines):
        match = _SECTION_HEADER.match(line)
        if match and match.group("header").strip() == header[1:-1]:
            header_index = index
            break
    if header_index is None:
        trimmed = text.rstrip("\n")
        return (trimmed + "\n\n" if trimmed else "") + header + "\n" + assignment
    for index in range(header_index + 1, len(lines)):
        line = lines[index]
        if _SECTION_HEADER.match(line):
            lines.insert(index, assignment)
            return "".join(lines)
        if re.match(rf"^\s*{re.escape(key)}\s*=", line):
            newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            lines[index] = assignment.rstrip("\n") + newline
            return "".join(lines)
    lines.insert(header_index + 1, assignment)
    return "".join(lines)


def _assert_whitelist_targets_exist(normalized: list[tuple[tuple[str, ...], str, Any]]) -> None:
    """Fail fast on unknown llm profile ids or provider prefixes before prepare."""

    llm_updates = [entry for entry in normalized if entry[0][0] == "llm"]
    if not llm_updates:
        return
    import tomllib

    from config.paths import resolve_config_path

    text = resolve_config_path().read_text(encoding="utf-8")
    current = tomllib.loads(text)
    providers = current.get("llm", {}).get("providers", {})
    profiles = current.get("llm", {}).get("profiles", {})
    for table_path, _, value in llm_updates:
        profile_id = table_path[2]
        if profile_id not in profiles:
            raise ValueError(f"未知的模型偏好档位：{profile_id}。")
        provider_id = str(value).split("/", 1)[0]
        if provider_id not in providers:
            raise ValueError(f"模型引用的 Provider 不存在：{provider_id}。")


def config_update_tool(updates: list) -> str:
    """Apply whitelisted operator preference updates via the config transaction.

    Closed whitelist: ``[user_profile]`` display/profile keys, ``[ui]``
    language/limits/switches, and ``[llm]`` default model preference switches
    (``profiles.<id>.model_ref``). Any unknown or forbidden key — including
    provider tables, credential refs, or the external agent gateway — rejects
    the whole request. The optimistic base-hash check inside the transaction
    catches concurrent edits; the assistant re-reads on the next call.
    """

    try:
        normalized = _validate_updates(updates)
    except ValueError as exc:
        return _fail(error="invalid_input", message=str(exc))
    try:
        _assert_whitelist_targets_exist(normalized)
    except ValueError as exc:
        return _fail(error="validation_error", message=str(exc))
    except Exception as exc:
        return _fail(error=exc.__class__.__name__, message=str(exc))

    def _mutate(text: str) -> str:
        for table_path, key, value in normalized:
            text = _upsert_toml_key(text, table_path, key, _format_value(value))
        return text

    try:
        from config.operator_config_transaction import (
            apply_operator_config_transaction,
            prepare_operator_config_transaction,
        )
        from config.paths import resolve_config_path
        from config.public_config import load_public_config, public_config_hash

        config_path = resolve_config_path()
        base_hash = public_config_hash(load_public_config(config_path))
        prepared = prepare_operator_config_transaction(
            operation_kind="pa_config_update",
            expected_base_hash=base_hash,
            mutate_text=_mutate,
            config_path=config_path,
        )
        transaction = apply_operator_config_transaction(prepared)
    except ValueError as exc:
        message = str(exc)
        if "stale config hash" in message or "changed after transaction preparation" in message:
            return _fail(
                error="config_conflict",
                status="blocked",
                message="配置已被其他操作更新，本次未写入；请重试，将自动读取最新配置。",
            )
        return _fail(error="validation_error", message=message)
    except Exception as exc:
        return _fail(error=exc.__class__.__name__, message=str(exc))
    applied = ", ".join(f"{path[0]}.{key}" if len(path) == 1 else f"llm.profiles.{path[2]}.{key}" for path, key, _ in normalized)
    return _json_result({
        "ok": True,
        "status": str(transaction.get("status") or "completed"),
        "message": f"已更新：{applied}。",
    })
