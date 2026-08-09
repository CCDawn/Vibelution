"""Stage-specific structured writeback contracts for source-collection Agents."""

from __future__ import annotations


def stage_writeback_prompt_lines(stage_id: str) -> list[str]:
    if stage_id == "finding":
        return [
            "- 本任务只负责资料寻找：新资料只写入 `candidateLeads[]`，无效来源只写入 `invalidSources[]`；不要把检索结果写成 `candidateExtractions[]`、`recordExtractions[]` 或 `candidateDecisions[]`。",
            "- 检索计划必须同时覆盖四类视角：`mechanism`（机制/支持）、`independent_baseline`（独立基线或复现）、`limitation_or_null`（限制、失败或零结果）和 `falsification`（反例或可证伪线索）；不得只检索支持当前设想的资料。",
            "- 每条 `candidateLeads[]` 至少包含 `title`、`locator`（可验证 DOI 或 https URL）、`sourceType`、`summary`、本条资料对应的 `query`，以及上述四类之一的 `perspective`；可额外填写 `doi`、`authors`、`year`、`container`、`relevance`。",
            "- `result.searchTrace[]` 必须逐条登记四类视角的实际检索轨迹；每项包含 `perspective`、`query`、`status=found/no_credible_source`、真实 `resultRefs[]`，未找到可信来源时再写 `failureReason`。",
            "- 至少一条候选资料必须属于 `limitation_or_null` 或 `falsification`，并能作为后续反证候选；如果真实检索后仍未找到，保留完整 `searchTrace[]`、写 `status=needs_review`，不得伪造负面资料或把支持性背景冒充反证。",
            "- `locator` 必须是本条资料的 DOI 或 https URL；不要只写自然语言来源名，也不要把搜索结果的概述当作资料定位符。",
            "- 先在同一批 `result.candidateLeads[]` 写入检索到的可用资料，再用 `result.invalidSources[]` 登记明确无效、跑题或不可获取的来源；自然语言总结不能替代这些结构化写回。",
        ]
    if stage_id == "extraction":
        return [
            "- 资料提炼阶段如果 `candidatePage.total=0`，输入就是原始 DataRecord：请用 `recordExtractions[]` 回写，并绑定完整 `recordId`；已有候选后优先用 `candidateExtractions[]` 绑定完整 `candidateId`，可直接在每项里写 `decision=keep/needs_more_info/exclude`。",
            "- 资料提炼阶段不需要额外提交一份 `candidateDecisions[]`；只有专门做资料审查/质检时才单独回写 `candidateDecisions[]`。",
            "- 资料提炼采用宽松保留：只要有可用内容或有价值线索，就写 `decision=keep` 或 `needs_more_info`，并填写 `valueSummary`、`defects`、`followUpSuggestion`；不要因为缺 DOI/缺全文直接丢弃。",
            "- 资料提炼必须区分来源定位与主张级证据：DOI/URL/论文 ID 只能写入 `sourceRefs[]`；它们只能说明资料在哪里，不能单独证明资料支持某个结论。",
            "- `evidenceRefs[]` 只写页码、PDF 页、段落、章节、引文或受控记录锚点；`claims[]` / `keyFindings[]` / `citations[]` 每项必须包含 `sourceRef`，并至少包含 `page/pageRange/citation/evidenceRef` 之一。",
            "- 对摘要或元数据足以支持的范围，可把 `candidates[].evidenceRefs` 中已有的真实锚点原样写入对应 extraction；如果只有 DOI/URL 或摘要定位，保留 `keep/needs_more_info` 决定，但证据状态必须保持 `missing_evidence_anchor`，不得虚构页码、直接引语或全文结论。",
        ]
    if stage_id == "relations":
        return [
            "- 证据关系阶段必须在 `missingLinks[]` 逐条写出证据缺口；每项包含稳定 `id`、`description`、`neededEvidence` 和 `blocksConclusion`。",
            "- 必须显式写 `counterEvidenceRefs[]`：只登记真实限制、反例或否定性证据，每项包含 `evidenceRef`、`claim` 和处置 `disposition`；支持性背景关系不得冒充反证。",
            "- 如果没有真实反证，`counterEvidenceRefs=[]` 并保持 `status=needs_review`；不得为了通过门禁伪造反证引用。",
            "- `candidateRelations[]` 的每条边必须绑定真实 `evidenceRefs[]`，关系图只表达候选事实，不得升级为正式结论。",
        ]
    return []
