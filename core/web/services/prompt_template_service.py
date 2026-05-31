"""Prompt template index service for AgentInstance configuration."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROMPT_TEMPLATE_INDEX_VERSION = 1
PROMPT_TEMPLATE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,95}$")
PROMPT_TEMPLATE_PATH = PROJECT_ROOT / "workspace" / "agent_config" / "prompt_templates.json"


class PromptTemplateError(ValueError):
    """Raised when a prompt template update is invalid."""


DEFAULT_PROMPT_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "templateId": "prompt-chat-default",
        "name": "Chat default",
        "category": "chat",
        "sourcePath": "workspace/prompts/DYNAMIC.md",
        "metadata": {"builtin": True},
    },
    {
        "templateId": "prompt-research-ceo",
        "name": "Research CEO",
        "category": "research",
        "sourcePath": "workspace/prompts/research/ceo.md",
        "content": (
            "# 科研 CEO agent 默认提示词\n\n"
            "你是 Vibelution 科研组织中的“科研 CEO agent”。你的职责是直接承接用户目标，把开放科研意图转成可执行的组织任务，"
            "并在多个研究 agent 之间维持方向、优先级和风险边界。\n\n"
            "## 工作策略\n"
            "- 先确认用户目标、限制和成功标准，再决定是否需要组织顾问或 specialist agent 介入。\n"
            "- 把模糊目标拆成研究任务、证据任务、审查任务和汇报任务，避免所有 agent 做同一件事。\n"
            "- 对高风险动作保持用户闸门：新增/归档 Agent、扩大权限、写入共享资料或影响项目主线时，先要求确认。\n"
            "- 当确实需要新增岗位时，要求组织顾问或能力管家先用 research_agent_creation_proposal_tool 提交创建提案；提案应用后再配置权限和通信边。\n"
            "- 接收其他 agent 汇报时，优先判断下一步决策，而不是复述材料。\n\n"
            "## 输出要求\n"
            "输出结构化结果：\n"
            "1. Goal Frame：当前用户目标、限制和待确认点。\n"
            "2. Organization Tasking：分配给各 agent 的任务和交付物。\n"
            "3. Decision Notes：已做出的方向判断、暂缓项和原因。\n"
            "4. User Gate：需要用户确认的高风险动作。\n\n"
            "## 禁止\n"
            "- 不要绕过用户确认直接扩大 Agent 权限或组织规模。\n"
            "- 不要把未验证材料当成最终研究结论。\n"
            "- 不要让多个 agent 长期重复同一职责。"
        ),
        "metadata": {"builtin": True, "roleKey": "research_ceo"},
    },
    {
        "templateId": "prompt-research-organization-advisor",
        "name": "Research organization advisor",
        "category": "research",
        "sourcePath": "workspace/prompts/research/organization_advisor.md",
        "content": (
            "# 科研组织顾问 agent 默认提示词\n\n"
            "你是 Vibelution 科研组织中的“组织顾问 agent”。你的职责是根据 CEO 或用户的目标，设计临时研究组织、通信边、权限边界和人员调整方案。\n\n"
            "## 工作策略\n"
            "- 先识别当前组织是否已经能完成任务，再决定是否建议新增、归档或调整 agent。\n"
            "- 每个 agent 必须有清晰职责、可交付物、允许工具和工作区边界。\n"
            "- 对新增 Agent、权限变化、归档、跨 Agent 通信边等动作给出可审查提案，而不是直接执行。\n"
            "- 需要新增 Agent 时，先使用 research_agent_creation_proposal_tool 创建提案；只有提案应用并生成 Agent 后，才能继续配置工具权限和通信边。\n"
            "- 需要变更通信边时，使用 research_communication_edge_proposal_tool 创建提案，不要口头声称已经修改。\n"
            "- 保留前员工与历史职责信息，避免组织记忆断裂。\n\n"
            "## 输出要求\n"
            "输出结构化结果：\n"
            "1. Organization Diagnosis：现有组织是否覆盖目标。\n"
            "2. Proposed Changes：建议新增/调整/归档的 agent、原因和风险。\n"
            "3. Communication Edges：建议允许哪些消息类型、意图和唤醒策略。\n"
            "4. User Approval Items：必须由用户确认后才能应用的动作。\n\n"
            "## 禁止\n"
            "- 不要提出没有职责边界的 Agent。\n"
            "- 不要默认授予写权限、网络权限或高风险工具。\n"
            "- 不要删除历史组织信息；归档优先于不可恢复删除。"
        ),
        "metadata": {"builtin": True, "roleKey": "research_organization_advisor"},
    },
    {
        "templateId": "prompt-research-capability-steward",
        "name": "Research capability steward",
        "category": "research",
        "sourcePath": "workspace/prompts/research/capability_steward.md",
        "content": (
            "# 科研能力管家 agent 默认提示词\n\n"
            "你是 Vibelution 科研组织中的“能力管家 agent”。你的职责是统一管理科研 Agent 的提示词、工具权限和记忆策略，"
            "让组织能随任务动态调整能力，同时避免权限过宽、职责重叠和记忆污染。\n\n"
            "## 工作策略\n"
            "- 先判断任务需要哪些能力，再映射到提示词、工具白名单、记忆读写组和通信边。\n"
            "- 对每个 Agent 维护最小权限：默认只给完成职责必需的工具，不默认开放 shell、文件写入、diff、git 或重启类工具。\n"
            "- 权限扩大、共享记忆写入、提示词重写和人员配置变化必须形成可审查建议，由 CEO 或用户确认后再应用。\n"
            "- 若能力缺口需要新增 Agent，先使用 research_agent_creation_proposal_tool 创建提案；不要对不存在的 Agent 调用权限或通信边工具。\n"
            "- 审查沟通边是否允许正确消息类型和意图，发现缺边、错边或唤醒策略不当时及时上报。\n\n"
            "## 输出要求\n"
            "输出结构化结果：\n"
            "1. Capability Map：当前任务需要的能力、对应 Agent 和缺口。\n"
            "2. Prompt Policy：提示词模板建议、需要修改的边界和风险。\n"
            "3. Tool Policy：允许工具、禁止工具、网络/变更访问和原因。\n"
            "4. Memory Policy：可读/可写记忆组、私有记忆边界和污染风险。\n"
            "5. Approval Items：需要 CEO 或用户确认后才能执行的变更。\n\n"
            "## 禁止\n"
            "- 不要直接授予高风险执行、文件写入、Git、重启或长期自动化权限。\n"
            "- 不要把共享记忆当作所有 Agent 都可写的公共草稿区。\n"
            "- 不要绕过 CEO 或用户确认修改核心 Agent 的职责、权限或提示词。"
        ),
        "metadata": {"builtin": True, "roleKey": "research_capability_steward"},
    },
    {
        "templateId": "prompt-research-broad",
        "name": "Research broad search",
        "category": "research",
        "sourcePath": "workspace/prompts/research/broad.md",
        "content": "# 广撒网探索 agent\n\n用于快速展开研究空间、收集候选线索和发现后续深挖方向。",
        "metadata": {"builtin": True, "roleKey": "research_broad"},
    },
    {
        "templateId": "prompt-research-deep",
        "name": "Research deep search",
        "category": "research",
        "sourcePath": "workspace/prompts/research/deep.md",
        "content": "# 深度研究 agent\n\n用于围绕已选线索做细读、证据归纳和风险核查。",
        "metadata": {"builtin": True, "roleKey": "research_deep"},
    },
    {
        "templateId": "prompt-research-review",
        "name": "Research review",
        "category": "research",
        "sourcePath": "workspace/prompts/research/review.md",
        "content": "# 研究审查 agent\n\n用于复核研究结论、寻找证据缺口和提出反例。",
        "metadata": {"builtin": True, "roleKey": "research_review"},
    },
    {
        "templateId": "prompt-research-themes",
        "name": "Research themes",
        "category": "research",
        "sourcePath": "workspace/prompts/research/themes.md",
        "content": "# 主题生成 agent\n\n用于把候选资料聚类成可执行研究主题。",
        "metadata": {"builtin": True, "roleKey": "research_themes"},
    },
    {
        "templateId": "prompt-research-card",
        "name": "Research card",
        "category": "research",
        "sourcePath": "workspace/prompts/research/card.md",
        "content": "# 主题卡 agent\n\n用于把研究主题整理成结构化卡片。",
        "metadata": {"builtin": True, "roleKey": "research_card"},
    },
    {
        "templateId": "prompt-supervised-baseline",
        "name": "Supervised baseline",
        "category": "supervised_evolution",
        "sourcePath": "",
        "metadata": {"builtin": True, "roleKey": "baseline"},
    },
    {
        "templateId": "prompt-supervised-candidate",
        "name": "Supervised candidate",
        "category": "supervised_evolution",
        "sourcePath": "",
        "metadata": {"builtin": True, "roleKey": "candidate"},
    },
    {
        "templateId": "prompt-supervised-reviewer",
        "name": "Supervised reviewer",
        "category": "supervised_evolution",
        "sourcePath": "",
        "metadata": {"builtin": True, "roleKey": "reviewer"},
    },
    {
        "templateId": "prompt-supervised-auditor",
        "name": "Supervised auditor",
        "category": "supervised_evolution",
        "sourcePath": "",
        "metadata": {"builtin": True, "roleKey": "auditor"},
    },
    {
        "templateId": "prompt-supervised-judge",
        "name": "Supervised judge",
        "category": "supervised_evolution",
        "sourcePath": "",
        "metadata": {"builtin": True, "roleKey": "judge"},
    },
    {
        "templateId": "prompt-self-executor",
        "name": "Self-evolution executor",
        "category": "self_evolution",
        "sourcePath": "",
        "metadata": {"builtin": True, "roleKey": "executor"},
    },
    {
        "templateId": "prompt-self-reviewer",
        "name": "Self-evolution reviewer",
        "category": "self_evolution",
        "sourcePath": "",
        "metadata": {"builtin": True, "roleKey": "reviewer"},
    },
    {
        "templateId": "prompt-self-summarizer",
        "name": "Self-evolution summarizer",
        "category": "self_evolution",
        "sourcePath": "",
        "metadata": {"builtin": True, "roleKey": "summarizer"},
    },
)


def list_prompt_templates(*, include_inactive: bool = False) -> dict[str, Any]:
    """Return the prompt template index with lightweight content metadata."""

    payload = repair_prompt_templates()
    templates = [
        _template_to_api(item, include_content=False)
        for item in payload.get("templates") or []
        if include_inactive or str(item.get("status") or "active").strip() != "inactive"
    ]
    templates.sort(key=lambda item: (str(item.get("category") or ""), str(item.get("templateId") or "")))
    return {
        "schemaVersion": PROMPT_TEMPLATE_INDEX_VERSION,
        "path": str(prompt_template_path()),
        "storagePath": _relative_project_path(prompt_template_path()),
        "templates": templates,
        "repairWarnings": list(payload.get("repairWarnings") or []),
    }


def get_prompt_template(template_id: str) -> dict[str, Any] | None:
    """Return one prompt template with resolved content."""

    normalized = _normalize_template_id(template_id)
    for item in repair_prompt_templates().get("templates") or []:
        if str(item.get("templateId") or "").strip() == normalized:
            return _template_to_api(item, include_content=True)
    return None


def build_agent_prompt_template_context(
    template_id: str,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Build the runtime context block for one Agent prompt template."""

    normalized = str(template_id or "").strip()
    if not normalized:
        return {
            "contextBlock": "",
            "promptTemplateId": "",
            "reason": "missing_template_id",
        }
    template = _get_prompt_template_for_project(normalized, project_root=project_root)
    if not template:
        return {
            "contextBlock": "",
            "promptTemplateId": normalized,
            "reason": "missing_template",
        }
    content = str(template.get("content") or "").strip()
    if not content:
        return {
            "contextBlock": "",
            "promptTemplateId": normalized,
            "sourcePath": str(template.get("sourcePath") or "").strip(),
            "sourceExists": bool(template.get("sourceExists")),
            "reason": "empty_template_content",
        }
    return {
        "contextBlock": "\n".join(
            [
                "## Agent Prompt Template",
                f"PromptTemplateId: {normalized}",
                content,
            ]
        ).strip(),
        "promptTemplateId": normalized,
        "sourcePath": str(template.get("sourcePath") or "").strip(),
        "sourceExists": bool(template.get("sourceExists")),
        "reason": "",
    }


def update_prompt_template(
    template_id: str,
    *,
    name: str | None = None,
    category: str | None = None,
    source_path: str | None = None,
    content: str | None = None,
    metadata: dict[str, Any] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Create or update one prompt template record."""

    normalized = _normalize_template_id(template_id)
    payload = repair_prompt_templates()
    templates = list(payload.get("templates") or [])
    index = next((idx for idx, item in enumerate(templates) if item.get("templateId") == normalized), -1)
    if index < 0:
        templates.append(_normalize_template_record({"templateId": normalized, "name": normalized}))
        index = len(templates) - 1
    record = dict(templates[index])
    if name is not None:
        record["name"] = _trim_text(name, max_chars=120) or normalized
    if category is not None:
        record["category"] = _safe_token(category, fallback="general")
    if source_path is not None:
        record["sourcePath"] = _normalize_source_path(source_path)
    if content is not None:
        record["content"] = _trim_content(content, max_chars=80_000)
        _write_template_source_if_configured(record)
    if metadata is not None:
        record["metadata"] = dict(metadata) if isinstance(metadata, dict) else {}
    if status is not None:
        record["status"] = _normalize_status(status)
    record["updatedAt"] = _now()
    templates[index] = _normalize_template_record(record)
    payload["templates"] = templates
    _save_prompt_templates(payload)
    _record_prompt_template_event("prompt_template.updated", normalized, outcome="updated")
    return _template_to_api(templates[index], include_content=True)


def reset_prompt_template(template_id: str) -> dict[str, Any]:
    """Reset a template to its built-in default record when one exists."""

    normalized = _normalize_template_id(template_id)
    default = _default_template_map().get(normalized)
    if not default:
        raise PromptTemplateError(f"Prompt template has no built-in default: {normalized}")
    payload = repair_prompt_templates()
    templates = [item for item in payload.get("templates") or [] if item.get("templateId") != normalized]
    reset_record = _normalize_template_record(copy.deepcopy(default))
    reset_record["updatedAt"] = _now()
    _write_template_source_if_configured(reset_record)
    templates.append(reset_record)
    payload["templates"] = templates
    _save_prompt_templates(payload)
    _record_prompt_template_event("prompt_template.reset", normalized, outcome="reset")
    return _template_to_api(reset_record, include_content=True)


def repair_prompt_templates() -> dict[str, Any]:
    """Load and repair the prompt template index."""

    payload = _load_prompt_templates()
    templates_by_id = _default_template_map()
    changed = False
    for raw in payload.get("templates") or []:
        if not isinstance(raw, dict):
            changed = True
            continue
        try:
            record = _normalize_template_record(raw)
        except PromptTemplateError:
            changed = True
            continue
        existing = templates_by_id.get(record["templateId"])
        if existing:
            merged = copy.deepcopy(existing)
            merged.update(record)
            merged["metadata"] = {
                **dict(existing.get("metadata") or {}),
                **dict(record.get("metadata") or {}),
            }
            templates_by_id[record["templateId"]] = _normalize_template_record(merged)
        else:
            templates_by_id[record["templateId"]] = record
    next_payload = {
        "schemaVersion": PROMPT_TEMPLATE_INDEX_VERSION,
        "updatedAt": str(payload.get("updatedAt") or _now()),
        "templates": list(templates_by_id.values()),
        "repairWarnings": list(payload.get("repairWarnings") or [])[-50:],
    }
    if payload.get("schemaVersion") != PROMPT_TEMPLATE_INDEX_VERSION:
        changed = True
    if _template_signature(payload.get("templates") or []) != _template_signature(next_payload["templates"]):
        changed = True
    if changed or not prompt_template_path().exists():
        next_payload["updatedAt"] = _now()
        for record in next_payload["templates"]:
            _write_template_source_if_missing(record)
        _save_prompt_templates(next_payload)
        _record_prompt_template_event(
            "prompt_template.repaired",
            "",
            outcome="repaired",
            fields={"templateCount": len(next_payload["templates"])},
        )
    return next_payload


def prompt_template_path() -> Path:
    return PROJECT_ROOT / "workspace" / "agent_config" / "prompt_templates.json"


def _get_prompt_template_for_project(template_id: str, *, project_root: Path | None = None) -> dict[str, Any] | None:
    if project_root is None:
        return get_prompt_template(template_id)
    global PROJECT_ROOT
    previous_root = PROJECT_ROOT
    PROJECT_ROOT = Path(project_root)
    try:
        return get_prompt_template(template_id)
    finally:
        PROJECT_ROOT = previous_root


def _load_prompt_templates() -> dict[str, Any]:
    path = prompt_template_path()
    if not path.exists():
        return {"schemaVersion": PROMPT_TEMPLATE_INDEX_VERSION, "templates": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": PROMPT_TEMPLATE_INDEX_VERSION, "templates": []}
    return payload if isinstance(payload, dict) else {"schemaVersion": PROMPT_TEMPLATE_INDEX_VERSION, "templates": []}


def _save_prompt_templates(payload: dict[str, Any]) -> None:
    data = {
        "schemaVersion": PROMPT_TEMPLATE_INDEX_VERSION,
        "updatedAt": _now(),
        "templates": [_normalize_template_record(item) for item in payload.get("templates") or [] if isinstance(item, dict)],
        "repairWarnings": list(payload.get("repairWarnings") or [])[-50:],
    }
    _atomic_write_json(prompt_template_path(), data)


def _template_to_api(record: dict[str, Any], *, include_content: bool) -> dict[str, Any]:
    content = _resolve_template_content(record)
    source_path = str(record.get("sourcePath") or "").strip()
    source_exists = _source_exists(source_path)
    payload = {
        "templateId": str(record.get("templateId") or "").strip(),
        "promptTemplateId": str(record.get("templateId") or "").strip(),
        "name": str(record.get("name") or "").strip(),
        "category": str(record.get("category") or "general").strip(),
        "sourcePath": source_path,
        "sourceExists": source_exists,
        "status": str(record.get("status") or "active").strip(),
        "metadata": dict(record.get("metadata") or {}),
        "contentLength": len(content),
        "contentHash": _content_hash(content),
        "contentPreview": _trim_text(content.replace("\r\n", "\n"), max_chars=240),
        "content": content if include_content else "",
        "createdAt": str(record.get("createdAt") or "").strip(),
        "updatedAt": str(record.get("updatedAt") or "").strip(),
    }
    return payload


def _resolve_template_content(record: dict[str, Any]) -> str:
    if "content" in record:
        return str(record.get("content") or "")
    source_path = str(record.get("sourcePath") or "").strip()
    if not source_path:
        return ""
    try:
        path = _resolve_project_path(source_path)
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    except Exception:
        _record_prompt_template_event(
            "prompt_template.missing_source",
            str(record.get("templateId") or ""),
            level="warning",
            outcome="missing_source",
            fields={"sourcePath": source_path},
        )
    return ""


def _normalize_template_record(raw: dict[str, Any]) -> dict[str, Any]:
    template_id = _normalize_template_id(raw.get("templateId") or raw.get("id"))
    now = _now()
    record = {
        "templateId": template_id,
        "name": _trim_text(raw.get("name") or template_id, max_chars=120) or template_id,
        "category": _safe_token(raw.get("category") or "general", fallback="general"),
        "sourcePath": _normalize_source_path(raw.get("sourcePath") or ""),
        "status": _normalize_status(raw.get("status") or "active"),
        "metadata": dict(raw.get("metadata") or {}) if isinstance(raw.get("metadata"), dict) else {},
        "createdAt": str(raw.get("createdAt") or now).strip(),
        "updatedAt": str(raw.get("updatedAt") or now).strip(),
    }
    if "content" in raw:
        record["content"] = _trim_content(raw.get("content") or "", max_chars=80_000)
    return record


def _write_template_source_if_configured(record: dict[str, Any]) -> None:
    source_path = str(record.get("sourcePath") or "").strip()
    if not source_path:
        return
    path = _resolve_project_path(source_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(record.get("content") or ""), encoding="utf-8", newline="\n")


def _write_template_source_if_missing(record: dict[str, Any]) -> None:
    source_path = str(record.get("sourcePath") or "").strip()
    if not source_path or "content" not in record:
        return
    path = _resolve_project_path(source_path)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(record.get("content") or ""), encoding="utf-8", newline="\n")


def _source_exists(source_path: str) -> bool:
    if not source_path:
        return False
    try:
        return _resolve_project_path(source_path).is_file()
    except PromptTemplateError:
        return False


def _content_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()


def _normalize_template_id(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized or not PROMPT_TEMPLATE_ID_PATTERN.fullmatch(normalized):
        raise PromptTemplateError("Invalid prompt template id.")
    return normalized


def _normalize_source_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    _resolve_project_path(raw)
    return raw


def _resolve_project_path(value: str) -> Path:
    root = Path(PROJECT_ROOT).resolve()
    candidate = (root / value).resolve()
    if candidate != root and root not in candidate.parents:
        raise PromptTemplateError("Prompt template source path must stay inside the project.")
    return candidate


def _default_template_map() -> dict[str, dict[str, Any]]:
    return {
        str(item["templateId"]): _normalize_template_record(copy.deepcopy(item))
        for item in DEFAULT_PROMPT_TEMPLATES
    }


def _template_signature(templates: list[Any]) -> list[tuple[str, str, str, str]]:
    signature: list[tuple[str, str, str, str]] = []
    for item in templates:
        if isinstance(item, dict):
            signature.append(
                (
                    str(item.get("templateId") or ""),
                    str(item.get("name") or ""),
                    str(item.get("category") or ""),
                    str(item.get("sourcePath") or ""),
                )
            )
    return sorted(signature)


def _safe_token(value: Any, *, fallback: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip().lower()).strip("._-")
    return token or fallback


def _normalize_status(value: Any) -> str:
    normalized = str(value or "active").strip().lower()
    return normalized if normalized in {"active", "inactive"} else "active"


def _trim_text(value: Any, *, max_chars: int) -> str:
    text = str(value or "").strip()
    return text[:max(0, int(max_chars))]


def _trim_content(value: Any, *, max_chars: int) -> str:
    text = str(value or "")
    return text[:max(0, int(max_chars))]


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _relative_project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(PROJECT_ROOT).resolve()).as_posix()
    except ValueError:
        return str(path)


def _record_prompt_template_event(
    event_code: str,
    template_id: str,
    *,
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "agent_configuration",
            "prompt_template",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={"templateId": str(template_id or "").strip(), **dict(fields or {})},
            lifecycle=True,
        )
    except Exception:
        return


def _now() -> str:
    return datetime.now(UTC).isoformat()
