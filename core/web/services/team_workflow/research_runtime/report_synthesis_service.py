"""Deep-research report synthesis orchestration (LLM prose pass).

Consumes the pure skeleton from ``core.research.report_synthesis``: the
knowledge items are grouped and citation-anchored deterministically, then
one LLM call drafts the report prose under the invariant that every
``[KI-...]`` anchor used in the prose must exist in the skeleton's
citation index. The finished report lands in the team workflow artifact
store (kind ``research_report``) as an immutable, replay-idempotent
record. Human review stays in charge: the artifact is evidence, not an
auto-promoted conclusion.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from core.infrastructure.workspace_manager import get_workspace
from core.llm import LLMInvocationContext, get_llm_client, invoke_llm
from core.llm.agent_runtime import config_for_agent_llm_model
from core.logging import debug as _debug_logger
from core.research.report_synthesis import (
    REPORT_SYNTHESIS_CONTRACT_VERSION,
    build_report_skeleton,
    check_citation_integrity,
    render_skeleton_markdown,
)
from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
    put_workflow_artifact,
)
from config import get_config

REPORT_SYNTHESIS_PROFILE_ID = "team_report_synthesis"
_ANCHOR_PATTERN = re.compile(r"\[KI-[A-Za-z0-9_.:-]+\]")

REPORT_PROSE_SYSTEM_PROMPT = (
    "你是研究综述撰写者。你会得到一份带引用锚点的报告骨架"
    "（markdown 列表，每条含 [KI-xxx] 锚点、标题、摘要与来源标注）。"
    "请撰写一篇结构完整的研究报告正文：直接输出 markdown，"
    "沿用骨架的章节结构，把每条证据融入流畅段落，"
    "并在对应陈述后保留原始 [KI-xxx] 锚点。"
    "不得发明骨架之外的新锚点；无来源标注的条目只能作为待验证观点表述。"
    "总长不超过 3000 字，不要输出骨架原文以外的解释。"
)


class ReportSynthesisError(ValueError):
    def __init__(self, message: str, *, code: str = "synthesis_failed") -> None:
        super().__init__(message)
        self.code = code


def _invoke_report_llm(model_ref: str, skeleton_markdown: str, topic: str) -> str:
    runtime_config = config_for_agent_llm_model(
        get_config(),
        model_id=model_ref,
        runtime_profile_id=REPORT_SYNTHESIS_PROFILE_ID,
        slot="dialogue",
    )
    client = get_llm_client(profile_id=REPORT_SYNTHESIS_PROFILE_ID, config=runtime_config)
    response = invoke_llm(
        client,
        [
            {"role": "system", "content": REPORT_PROSE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"研究主题：{topic}\n\n报告骨架：\n{skeleton_markdown}",
            },
        ],
        context=LLMInvocationContext(
            surface="team_report_synthesis",
            run_kind="tool_assistant_task",
            agent_id="report_synthesis_service",
            llm_slot="summary",
            model_id=model_ref,
            cache_scope="report_synthesis",
            cache_partition=f"report-synthesis-{model_ref}",
            prompt_purpose="team_report_synthesis",
            conversation_bound=False,
        ),
        metadata={"feature": "team_report_synthesis", "skeletonChars": len(skeleton_markdown)},
    )
    return str(getattr(response, "content", "") or "").strip()


def _assert_anchors_resolved(prose_markdown: str, citation_index: Dict[str, Any]) -> None:
    # Prose anchors render as "[KI-x]"; index keys are bare "KI-x".
    used = {match[1:-1] for match in _ANCHOR_PATTERN.findall(prose_markdown)}
    unknown = sorted(anchor for anchor in used if anchor not in citation_index)
    if unknown:
        raise ReportSynthesisError(
            "report prose invented anchors outside the citation index: "
            + ", ".join(f"[{anchor}]" for anchor in unknown[:5]),
            code="anchor_violation",
        )
    if not used:
        raise ReportSynthesisError(
            "report prose kept no citation anchors", code="anchor_violation"
        )


def synthesize_research_report(
    team_id: str,
    *,
    topic: str,
    items: List[Dict[str, Any]],
    model_ref: str,
    workflow_run_id: str,
) -> Dict[str, Any]:
    if not str(team_id or "").strip():
        raise ReportSynthesisError("teamId is required", code="invalid_request")
    run_id = str(workflow_run_id or "").strip()
    if not run_id:
        raise ReportSynthesisError("workflowRunId is required", code="invalid_request")

    skeleton = build_report_skeleton(items, report_id=f"{team_id}:{run_id}", topic=topic)
    if not skeleton["itemCount"]:
        raise ReportSynthesisError("no knowledge items to synthesize", code="empty_items")
    integrity_problems: List[str] = check_citation_integrity(skeleton)

    skeleton_markdown = render_skeleton_markdown(skeleton)
    prose = _invoke_report_llm(model_ref, skeleton_markdown, skeleton["topic"])
    if not prose:
        raise ReportSynthesisError("report LLM returned empty prose", code="empty_prose")
    _assert_anchors_resolved(prose, skeleton["citationIndex"])

    payload = {
        "schemaVersion": REPORT_SYNTHESIS_CONTRACT_VERSION,
        "topic": skeleton["topic"],
        "reportMarkdown": prose,
        "skeleton": skeleton,
        "citationIntegrity": {
            "clean": not integrity_problems,
            "problems": integrity_problems,
        },
        "modelRef": model_ref,
    }
    record = put_workflow_artifact(
        team_id,
        kind="research_report",
        workflow_run_id=run_id,
        payload=payload,
        artifact_identity=f"research-report:{run_id}",
    )
    _debug_logger.info(
        f"[report_synthesis] report {record.get('recordId')} written "
        f"({skeleton['itemCount']} items, {len(integrity_problems)} integrity problems)",
        tag="RESEARCH",
    )
    return {
        "recordId": record.get("recordId"),
        "topic": skeleton["topic"],
        "reportMarkdown": prose,
        "itemCount": skeleton["itemCount"],
        "citationIndex": skeleton["citationIndex"],
        "citationIntegrity": payload["citationIntegrity"],
        "updatedAt": record.get("updatedAt"),
    }
