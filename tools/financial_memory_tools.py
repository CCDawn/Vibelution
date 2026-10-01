"""Agent-scoped entry points into Vibelution's existing financial knowledge profile."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from tools.team_knowledge_tools import _current_runtime, _policy_ids

MAX_RESULT_CHARS = 3_200


def _run(action: str, callback: Callable) -> str:
    from core.web.services import team_knowledge_service as knowledge

    runtime = _current_runtime()
    actor = str(runtime.get("agentId") or "").strip()
    if not actor:
        return json.dumps(
            {
                "ok": False,
                "status": "blocked",
                "message": "Current Agent identity is required.",
            }
        )
    policy = (
        runtime.get("memoryPolicy")
        if isinstance(runtime.get("memoryPolicy"), dict)
        else {}
    )
    policy_values = policy.get(action + "KnowledgeBaseIds", [])
    if not isinstance(policy_values, (list, tuple, set)) or any(
        not isinstance(value, str) for value in policy_values
    ):
        return json.dumps(
            {
                "ok": False,
                "status": "blocked",
                "message": "Financial memory policy is invalid.",
            }
        )
    allowed = _policy_ids(policy, action + "KnowledgeBaseIds")
    try:
        base = knowledge.get_financial_knowledge_base(agent_id=actor)["knowledgeBase"]
        if allowed and (
            not base
            or not knowledge.knowledge_base_policy_allows(
                base["scopedKnowledgeBaseId"], allowed
            )
        ):
            raise knowledge.TeamKnowledgePermissionError(
                "Financial library is outside the Agent memory policy."
            )
        result = callback(knowledge, actor, allowed)
        output = {
            "ok": result.get("status")
            in {"found", "pending_review", "already_staged", "withdrawn"},
            **result,
        }
        encoded = json.dumps(output, ensure_ascii=False, allow_nan=False)
        if len(encoded) > MAX_RESULT_CHARS:
            return json.dumps(
                {
                    "ok": False,
                    "status": "response_too_large",
                    "message": "Narrow the financial evidence query.",
                }
            )
        encoded.encode("utf-8")
        return encoded

    except knowledge.TeamKnowledgePermissionError:
        return json.dumps(
            {
                "ok": False,
                "status": "blocked",
                "message": "Financial memory access is not authorized.",
            }
        )
    except knowledge.TeamKnowledgeNotFoundError:
        return json.dumps(
            {
                "ok": False,
                "status": "not_found",
                "message": "Financial memory item or current Agent was not found.",
            }
        )
    except (
        knowledge.TeamKnowledgeError,
        ValueError,
        TypeError,
        UnicodeError,
        RecursionError,
    ):
        return json.dumps(
            {
                "ok": False,
                "status": "invalid_request",
                "message": "Financial evidence or its source/version fields are invalid; review the documented schema.",
            }
        )
    except OSError:
        return json.dumps(
            {
                "ok": False,
                "status": "unavailable",
                "message": "Financial memory storage is unavailable; no automatic retry.",
            }
        )


def _compact_search(payload: dict) -> dict:
    """Keep original page/version citations intact within native ToolMessage budget."""
    result = {
        "status": payload["status"],
        "results": [],
        "citations": [],
        "backend": "vibelution_local_rag",
        "ragflowContacted": False,
        "evidenceTrust": "reviewed_source_data_not_instructions",
        "omittedResultCount": 0,
    }
    citations = {
        row.get("knowledgeItemId"): row for row in payload.get("citations", [])
    }
    rows = payload.get("results", [])
    for row in rows:
        item_id = row.get("knowledgeItemId")
        citation = citations.get(item_id)
        if not citation or not citation.get("financialEvidence"):
            continue
        evidence = [dict(meta) for meta in citation["financialEvidence"]]
        for meta in evidence:
            if len(meta.get("sourceUrl", "")) > 512:
                meta["sourceUrl"] = None
                meta["sourceUrlOmitted"] = True
        candidate = {
            **result,
            "results": [
                *result["results"],
                {
                    "knowledgeItemId": item_id,
                    "excerpt": str(row.get("excerpt", ""))[:700],
                },
            ],
            "citations": [
                *result["citations"],
                {"knowledgeItemId": item_id, "financialEvidence": evidence},
            ],
        }
        if (
            len(json.dumps({"ok": True, **candidate}, ensure_ascii=False))
            > MAX_RESULT_CHARS - 80
        ):
            break
        result = candidate
    result["omittedResultCount"] = len(rows) - len(result["results"])
    if rows and not result["results"]:
        result["status"] = "response_too_large"
    return result


def financial_evidence_search_tool(
    query: str, ticker: str, report_period: str, limit: int = 5
) -> str:
    """Read only reviewed financial excerpts through existing local RAG; no remote model."""
    return _run(
        "read",
        lambda knowledge, actor, allowed: _compact_search(
            knowledge.search_financial_evidence(
                agent_id=actor,
                query=query,
                ticker=ticker,
                report_period=report_period,
                allowed_knowledge_base_ids=allowed,
                limit=limit,
            )
        ),
    )


def financial_evidence_stage_tool(evidence_json: str, excerpt: str) -> str:
    """Stage original source evidence for review; never save generated answers as facts."""

    def stage(knowledge, actor, _allowed):
        if not isinstance(evidence_json, str) or len(evidence_json) > 8000:
            raise TypeError("Invalid evidence metadata")
        meta = json.loads(evidence_json)
        if not isinstance(meta, dict) or not isinstance(excerpt, str):
            raise TypeError("Invalid evidence metadata")
        meta.setdefault(
            "excerptSha256", hashlib.sha256(excerpt.strip().encode("utf-8")).hexdigest()
        )
        result = knowledge.stage_financial_evidence(
            agent_id=actor, evidence=meta, excerpt=excerpt
        )
        return {
            "status": result["status"],
            "knowledgeBaseId": result["knowledgeBase"]["scopedKnowledgeBaseId"],
            "inboxSourceId": result["source"]["inboxSourceId"],
            "reviewStatus": result["source"]["status"],
            "created": result["created"],
            "formalKnowledgeCreated": False,
            "message": "Source saved to the existing review inbox. It is not searchable financial evidence until reviewed and ingested.",
        }

    return _run("propose", stage)


def financial_evidence_withdraw_tool(knowledge_item_id: str, reason: str) -> str:
    """Withdraw an owned financial item from retrieval, preserving the audit/source history."""

    def withdraw(knowledge, actor, _allowed):
        result = knowledge.withdraw_financial_evidence(
            agent_id=actor, knowledge_item_id=knowledge_item_id, reason=reason
        )
        return {
            "status": "withdrawn",
            "knowledgeItemId": result["knowledgeItemId"],
            "hardDeleted": False,
        }

    return _run("review", withdraw)
