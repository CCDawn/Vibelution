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
