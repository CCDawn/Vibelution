# -*- coding: utf-8 -*-
"""Hypothesis-side knowledge provisioning tool for the Challenge Cup flow.

The experiment planner role uses this tool to serve its own evidence needs
without touching the stage-1 collection machinery directly:

- ``request`` ensures a scoped knowledge-sideflow invocation through the
  workflow CommandService, but never blocks the hypothesis node.
- ``status`` inspects the scoped invocation and child run read-only.
- ``preview`` runs a bounded metadata search whose results are advisory
  context only: they must never be cited as ``allowedEvidenceRefs``.

Every action resolves the server-authoritative scope from the bound research
project task; the caller cannot pick another question's scope.
"""

from __future__ import annotations

import json
import hashlib
import time
from typing import Any

from core.research.workflow.contracts import (
    ActorRef,
    CommandRequest,
    WorkflowCommandKind,
)
from core.chat.chat_task_types import trim_lines


RESEARCH_KNOWLEDGE_REQUEST_TOOL_NAME = "research_knowledge_request_tool"
_ALLOWED_ACTIONS = {"request", "status", "preview"}
_PREVIEW_KINDS = {"paper", "web", "dataset", "github"}
_PREVIEW_METHODS = {
    "paper": "search_papers",
    "web": "search_web",
    "dataset": "search_datasets",
    "github": "search_github",
}
_PLANNER_TASK_KINDS = ("hypothesis_design", "experiment_design", "protocol_design")
_MAX_KEYWORDS = 8
_MAX_KEYWORD_LENGTH = 120
_MAX_PREVIEW_QUERY_LENGTH = 200
_MAX_PREVIEW_LIMIT = 8

_ADVISORY_NOTICE = (
    "Advisory only: request does not block hypothesis design and preview "
    "results are not citable evidence; formal evidence still requires the "
    "knowledge sideflow plus human knowledge-package handoff."
)


class ResearchKnowledgeRequestError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def research_knowledge_request_tool(
    team_id: str = "research-team",
    action: str = "status",
    keywords: str = "",
    preview_query: str = "",
    preview_kind: str = "paper",
    preview_limit: int = 5,
    research_project_id: str = "",
    task_id: str = "",
) -> str:
    """
    【假说侧知识请求】为本题按需触发受控知识搜集、查看搜集状态或做 advisory 检索预览。

    Args:
        team_id: 团队 ID，默认 research-team
        action: request / status / preview
        keywords: action=request 时的检索关键词，逗号或换行分隔（1-8 条）
        preview_query: action=preview 时的检索词
        preview_kind: preview 来源类型：paper / web / dataset / github
        preview_limit: preview 返回条数上限，1-8，默认 5
        research_project_id: 可选，显式绑定科研任务所属项目（默认从当前运行时解析）
        task_id: 可选，显式绑定的科研任务 ID（与 research_project_id 成对提供）

    Returns:
        JSON 字符串：scope、collection 摘要或 advisory 预览结果与边界说明
    """

    normalized_team = str(team_id or "").strip() or "research-team"
    normalized_action = str(action or "").strip().lower()
    try:
        if normalized_action not in _ALLOWED_ACTIONS:
            raise ResearchKnowledgeRequestError(
                f"Unsupported action: {action}", code="unsupported_action"
            )
        scope, envelope = _resolve_bound_scope(
            normalized_team,
            research_project_id=research_project_id,
            task_id=task_id,
        )
        if normalized_action == "request":
            result = _run_request(normalized_team, scope, envelope, keywords=keywords)
        elif normalized_action == "preview":
            result = _run_preview(
                scope,
                query=preview_query,
                kind=preview_kind,
                limit=preview_limit,
            )
        else:
            result = _run_status(normalized_team, scope, envelope)
        _record_event(
            "research_knowledge.request.succeeded",
            outcome="succeeded",
            fields={
                "action": normalized_action,
                "questionId": scope.get("question", ""),
                "mode": scope.get("mode", ""),
            },
        )
        return _json_result(result)
    except ResearchKnowledgeRequestError as exc:
        _record_event(
            "research_knowledge.request.failed",
            level="error",
            outcome="failed",
            fields={"action": normalized_action, "errorType": exc.code},
        )
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": exc.code,
                "message": trim_lines(str(exc), max_lines=3),
            }
        )
    except Exception as exc:  # service failures stay structured for the agent
        _record_event(
            "research_knowledge.request.failed",
            level="error",
            outcome="failed",
            fields={"action": normalized_action, "errorType": type(exc).__name__},
        )
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=3),
            }
        )


# ---------------------------------------------------------------------------
# bound-scope resolution (server-authoritative; caller cannot spoof it)
# ---------------------------------------------------------------------------


def _resolve_bound_scope(
    team_id: str,
    *,
    research_project_id: str,
    task_id: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    from tools.challenge_cup_operations_tools import _project_task_binding

    from core.web.services import team_workflow_orchestration_service as workflow_service

    binding = _project_task_binding(
        workflow_service,
        team_id=team_id,
        research_project_id=research_project_id,
        task_id=task_id,
        allowed_task_kinds=_PLANNER_TASK_KINDS,
        recorded_by_agent="",
        load_context=True,
    )
    if not isinstance(binding, dict):
        raise ResearchKnowledgeRequestError(
            "No bound research project task was found for this runtime; "
            "research_knowledge_request_tool only serves planner tasks.",
            code="no_bound_task",
        )
    task = binding.get("task") if isinstance(binding.get("task"), dict) else binding
    workflow_run_id = str(task.get("workflowRunId") or "").strip()
    if not workflow_run_id:
        raise ResearchKnowledgeRequestError(
            "The bound task does not carry a workflowRunId.", code="task_not_workflow_bound"
        )
    from core.web.services.team_workflow.research_runtime import (
        get_research_workflow_runtime_service,
    )

    run = get_research_workflow_runtime_service().get_run(workflow_run_id)
    run_team = str(run.get("teamId") or "").strip()
    if run_team and run_team != team_id:
        raise ResearchKnowledgeRequestError(
            "The bound workflow run belongs to another team.", code="run_team_mismatch"
        )
    question_id = str(run.get("questionId") or "").strip().upper()
    if not question_id:
        raise ResearchKnowledgeRequestError(
            "The bound workflow run does not carry a questionId.",
            code="run_question_missing",
        )
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain
    from core.web.services.team_workflow import research_scope as scope_service

    seed = hypothesis_first_chain._question_scope_envelope(team_id, question_id)
    envelope = scope_service.resolve_research_scope(
        team_id,
        agent_id=str(seed.get("agentId") or ""),
        scope_seed=seed,
    )
    scope: dict[str, Any] = {
        "questionId": question_id,
        "themeId": str(envelope.get("theme") or ""),
        "campaignId": str(envelope.get("campaign") or ""),
        "workflowRunId": workflow_run_id,
        "mode": str(envelope.get("mode") or ""),
        "scopeHash": str(envelope.get("scopeHash") or ""),
        "runVersion": int(run.get("runVersion") or 1),
    }
    return scope, dict(envelope)


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------


def _split_keywords(raw: str) -> list[str]:
    items: list[str] = []
    for chunk in str(raw or "").replace(";", ",").replace("\n", ",").split(","):
        value = chunk.strip()[:_MAX_KEYWORD_LENGTH]
        if value and value not in items:
            items.append(value)
        if len(items) >= _MAX_KEYWORDS:
            break
    return items


def _command_call(
    team_id: str,
    scope: dict[str, Any],
    *,
    action: str,
    keywords: list[str],
) -> dict[str, Any]:
    from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
        get_command_service,
    )
    command = (
        WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION
        if action == "ensure"
        else WorkflowCommandKind.INSPECT_KNOWLEDGE_COLLECTION
    )
    run_id = str(scope.get("workflowRunId") or "").strip()
    question_id = str(scope.get("questionId") or "").strip().upper()
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "action": action,
                "runId": run_id,
                "questionId": question_id,
                "keywords": keywords,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    payload: dict[str, Any] = {"questionId": question_id}
    if action == "ensure":
        payload["searchEnvelope"] = {
            "keywords": keywords,
            "evidenceTypes": [],
            "timeWindow": {},
        }
    receipt = get_command_service().submit(
        CommandRequest(
            command_id=f"cmd-rkr-{fingerprint[:24]}",
            run_id=run_id,
            team_id=team_id,
            command=command,
            node_id="hypothesis_design" if action == "ensure" else None,
            expected_run_version=int(scope.get("runVersion") or 1),
            idempotency_key=f"research-knowledge-request:{fingerprint}",
            payload=payload,
            requested_by=ActorRef("agent", "research-knowledge-request-tool"),
            requested_at_ms=int(time.time() * 1000),
        )
    )
    result = receipt.result if isinstance(receipt.result, dict) else {}
    return {"commandStatus": str(receipt.status or ""), **dict(result)}


def _run_request(
    team_id: str,
    scope: dict[str, str],
    envelope: dict[str, Any],
    *,
    keywords: str,
) -> dict[str, Any]:
    keyword_list = _split_keywords(keywords)
    if not keyword_list:
        raise ResearchKnowledgeRequestError(
            "action=request requires keywords (comma or newline separated).",
            code="keywords_required",
        )
    ensured = _command_call(team_id, scope, action="ensure", keywords=keyword_list)
    return {
        "ok": True,
        "status": "succeeded",
        "action": "request",
        "scope": scope,
        "keywords": keyword_list,
        "collection": _command_projection(ensured),
        "advisory": {"blocking": False, "notice": _ADVISORY_NOTICE},
    }


def _run_status(
    team_id: str,
    scope: dict[str, str],
    envelope: dict[str, Any],
) -> dict[str, Any]:
    inspected = _command_call(team_id, scope, action="inspect", keywords=[])
    return {
        "ok": True,
        "status": "succeeded",
        "action": "status",
        "scope": scope,
        "collection": _command_projection(inspected),
    }


def _command_projection(result: dict[str, Any]) -> dict[str, Any]:
    """Keep one bounded collection envelope while exposing canonical IDs."""

    return {
        "commandStatus": str(result.get("commandStatus") or ""),
        "invocationId": str(result.get("invocationId") or ""),
        "childRunId": str(result.get("childRunId") or ""),
        "replayed": bool(result.get("replayed")),
        "reused": bool(result.get("reused")),
        "invocationStatus": str(result.get("invocationStatus") or ""),
        "handoffState": str(result.get("handoffState") or ""),
        "invocations": list(result.get("invocations") or []),
        "childRun": result.get("childRun") if isinstance(result.get("childRun"), dict) else None,
        "recoveryActions": list(result.get("recoveryActions") or []),
        "knowledgeSideflowMode": str(result.get("knowledgeSideflowMode") or ""),
    }


def _dev_preview_provider() -> Any:
    from core.research.providers import DeterministicResearchSearchProvider

    return DeterministicResearchSearchProvider()


def _formal_preview_provider() -> Any:
    from core.research.providers import PublicResearchSearchProvider

    return PublicResearchSearchProvider(timeout=15.0, per_kind_limit=4)


def _run_preview(
    scope: dict[str, str],
    *,
    query: str,
    kind: str,
    limit: int,
) -> dict[str, Any]:
    normalized_query = trim_lines(str(query or ""), max_lines=4).strip()[
        :_MAX_PREVIEW_QUERY_LENGTH
    ]
    if not normalized_query:
        raise ResearchKnowledgeRequestError(
            "action=preview requires preview_query.", code="preview_query_required"
        )
    normalized_kind = str(kind or "paper").strip().lower()
    if normalized_kind not in _PREVIEW_KINDS:
        raise ResearchKnowledgeRequestError(
            f"Unsupported preview_kind: {kind}", code="preview_kind_invalid"
        )
    try:
        normalized_limit = max(1, min(_MAX_PREVIEW_LIMIT, int(limit or 5)))
    except (TypeError, ValueError):
        normalized_limit = 5
    mode = str(scope.get("mode") or "").strip().lower()
    if mode == "platform":
        raise ResearchKnowledgeRequestError(
            "Preview search stays closed until the question's research scope is "
            "activated (dev fixture or authorized campaign).",
            code="research_authorization_required",
        )
    provider = _dev_preview_provider() if mode == "dev" else _formal_preview_provider()
    search = getattr(provider, _PREVIEW_METHODS[normalized_kind], None)
    if search is None:
        raise ResearchKnowledgeRequestError(
            f"Preview kind is not searchable: {normalized_kind}",
            code="preview_kind_invalid",
        )
    results = list(search(normalized_query) or [])[:normalized_limit]
    items = [
        {
            "title": trim_lines(str(getattr(item, "title", "") or ""), max_lines=2),
            "url": str(getattr(item, "url", "") or "").strip(),
            "summary": trim_lines(str(getattr(item, "summary", "") or ""), max_lines=4),
        }
        for item in results
    ]
    return {
        "ok": True,
        "status": "succeeded",
        "action": "preview",
        "scope": scope,
        "preview": {
            "query": normalized_query,
            "kind": normalized_kind,
            "provider": str(getattr(provider, "provider_name", "") or ""),
            "advisoryOnly": True,
            "citationPolicy": (
                "Preview results must never be cited as allowedEvidenceRefs; "
                "use request+status and wait for the human-accepted knowledge "
                "package before citing evidence."
            ),
            "items": items,
        },
    }


# ---------------------------------------------------------------------------
# plumbing shared with the other research knowledge tools
# ---------------------------------------------------------------------------


def _record_event(
    event_code: str,
    *,
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        from core.web.services.agent_directory_service import current_agent_runtime
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        runtime = current_agent_runtime()
        runtime = runtime if isinstance(runtime, dict) else {}
        record_runtime_scene_event(
            "research_knowledge",
            "tool",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={
                "agentId": str(runtime.get("agentId") or "").strip(),
                "sessionId": str(runtime.get("sessionId") or "").strip(),
                **dict(fields or {}),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
