"""Feed current extraction gaps back to the existing finding task."""

from __future__ import annotations

import json
from typing import Any


def source_repair_message(
    *, team_id: str, run_id: str, candidates: list[dict[str, Any]]
) -> str:
    from core.web.services import team_workflow_orchestration_service as s

    tasks = [
        task for task in s._source_collection_stage_session_tasks(team_id, run_id)
        if task.get("stageId") == "extraction"
    ]
    task = s._latest_source_collection_stage_task(tasks)
    if not task:
        return ""
    focus = s._source_collection_stage_evidence_retry_focus(task, candidates)
    gap_ids = set(focus.get("evidenceGapCandidateIds") or [])
    # A failed fetch needs another source even when a metadata/record anchor
    # made the generic extraction ledger ready. Successful fetches do not.
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    latest_fetches = {
        attempt.get("candidateId"): attempt.get("status")
        for attempt in result.get("evidenceFetchAttempts", [])
        if isinstance(attempt, dict) and attempt.get("candidateId")
    }
    gap_ids.update(
        candidate.get("candidateId") for candidate in candidates
        if latest_fetches.get(candidate.get("candidateId")) == "failed"
        and (candidate.get("metadata") or {}).get("contentExtraction", {}).get("taskId") == task.get("taskId")
    )
    if not gap_ids:
        return ""
    gaps = [
        {
            "candidateId": candidate.get("candidateId"),
            "title": str(candidate.get("title") or "")[:300],
            "sourceUrl": str(candidate.get("sourceUrl") or "")[:1000],
            "doi": str(candidate.get("doi") or "")[:200],
        }
        for candidate in candidates if candidate.get("candidateId") in gap_ids
    ]
    return (
        "\n\n## 本轮提炼退回的来源缺口\n"
        "以下来源尚无可引用原文，只是补源线索，不能当作已核实事实。"
        "保留本题和冻结检索范围；优先寻找同一文献的开放版本，或能回答同一证据需求的可访问来源。"
        "用真实搜索回执登记新来源，不要重复提交原有不可访问网址；"
        "用 web_fetch_tool 检查新网址确实有正文或作者摘要，再交给提炼阶段逐字核验。"
        "确认旧定位符不可访问且已有可用替代来源时，将旧定位符写入 invalidSources[]，"
        "填写 reason=unobtainable 和实际失败原因，通过现有排除流程移出，避免下一阶段再次处理。"
        "抓取失败如实记录，不得将搜索摘要冒充原文，不要重做已就绪的证据。\n"
        + json.dumps({"sourceTaskId": task.get("taskId"), "sources": gaps}, ensure_ascii=False)
    )
