/**
 * Canonical user-facing terms for the research workflow surfaces.
 *
 * Split synonyms previously drifted across panels: the toolbar said
 * "资料搜集" while stage summaries said "知识搜集", the canvas node said
 * "假设设计" while every hypothesis-first surface said "假说", and the
 * timeline tab/panel disagreed on "运行记录" vs "运行时间线". Surfaces must
 * consume these constants instead of re-typing the literals; the companion
 * contract test bans the retired synonyms in the owning source files.
 */
export const RESEARCH_STAGE_TERMS = {
  problem_understanding: { zh: "问题理解", en: "Problem understanding" },
  knowledge_collection: { zh: "资料搜集", en: "Knowledge collection" },
  experiment_design: { zh: "实验设计", en: "Experiment design" },
  execution_iteration: { zh: "执行迭代", en: "Execution & iteration" },
} as const;

export type ResearchStageTermId = keyof typeof RESEARCH_STAGE_TERMS;

export const HYPOTHESIS_DESIGN_NODE_TERM = { zh: "假说设计", en: "Hypothesis design" } as const;

export const RUN_TIMELINE_TERM = { zh: "运行时间线", en: "Run timeline" } as const;

export function researchStageTermZh(stageId: string): string {
  const term = RESEARCH_STAGE_TERMS[stageId as ResearchStageTermId];
  return term ? term.zh : "流程阶段";
}

/**
 * Display-layer mapping for workflow definition labels.
 *
 * The server definition labels still carry the legacy "挑战杯" prefix and
 * participate in the definition structureHash, so they cannot be renamed in
 * place. Surfaces that render a definition-derived label must pass it through
 * this mapping so users only ever see the renamed flow. Unknown labels pass
 * through unchanged; no logic may branch on the legacy literals.
 */
const LEGACY_WORKFLOW_LABEL_DISPLAY: Record<string, string> = {
  挑战杯科研流程: "AI科研流程",
  挑战杯第一阶段科研流程: "AI科研第一阶段流程",
  挑战杯知识搜集子流程: "科研知识搜集子流程",
};

export function displayWorkflowLabel(label: string | null | undefined): string {
  const trimmed = String(label ?? "").trim();
  if (!trimmed) return "";
  return LEGACY_WORKFLOW_LABEL_DISPLAY[trimmed] ?? trimmed;
}
