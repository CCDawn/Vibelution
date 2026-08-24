/**
 * Pure model for research board kanban columns (preview-aligned).
 */
import { RESEARCH_STAGE_TERMS } from "./research-workflow/researchTerminology";
import type { ResearchStagePhaseStatus } from "./source-collection/stageProjection";

export type ResearchBoardCard = {
  id: string;
  title: string;
  body: string;
  meta: string[];
  foot: string;
  active?: boolean;
};

export type ResearchBoardColumn = {
  id: "knowledge_collection" | "experiment" | "iteration";
  titleZh: string;
  titleEn: string;
  cards: ResearchBoardCard[];
};

export type ResearchBoardModelInput = {
  lang: "zh" | "en";
  phases: ResearchStagePhaseStatus[];
  sourceRunCount: number;
  sourceCandidateCount: number;
  experimentDesignFrozen?: boolean;
  frozenDesignLabel?: string;
  bestCandidateId?: string;
  latestDiagnostic?: string;
  sourceRunLabel?: string;
  knowledgeStatusLabel?: string;
};

function phaseFor(
  phases: ResearchStagePhaseStatus[],
  stageType: string,
): ResearchStagePhaseStatus | undefined {
  return phases.find((item) => String(item.stageType || "") === stageType);
}

function cardFromPhase(
  phase: ResearchStagePhaseStatus | undefined,
  fallback: ResearchBoardCard,
  lang: "zh" | "en",
): ResearchBoardCard {
  if (!phase) {
    return fallback;
  }
  const round = phase.latestRound;
  const status = String(phase.status || fallback.foot);
  const rawTitle = round
    ? String((round as { topic?: string }).topic || phase.label || fallback.title)
    : (phase.label || fallback.title);
  return {
    id: String(phase.activeRoundId || phase.stageType || fallback.id),
    title: productBoardTitle(rawTitle, fallback.title),
    body: fallback.body,
    meta: [
      phase.roundCount
        ? (lang === "zh" ? `第 ${phase.roundCount} 轮` : `Round ${phase.roundCount}`)
        : "",
      phase.activeRoundId
        ? (lang === "zh" ? "进行中" : "Active")
        : "",
    ].filter(Boolean),
    foot: humanizeBoardStatus(status || fallback.foot, lang),
    active: Boolean(phase.activeRoundId || phase.canContinue),
  };
}

/** Prefer short human titles; keep machine ids out of the primary line. */
function productBoardTitle(raw: string, fallback: string): string {
  const value = String(raw || "").trim();
  if (!value) return fallback;
  // exp-plan-… / dprun-… / uuid-like ids → keep fallback product title
  if (/^(exp-plan|dprun|run|plan)[-_]/i.test(value)) return fallback || value;
  if (/^[0-9a-f]{8,}$/i.test(value)) return fallback || value;
  return value;
}

function humanizeBoardStatus(raw: string, lang: "zh" | "en"): string {
  const value = String(raw || "").trim();
  if (!value) return value;
  const key = value.toLowerCase().replace(/[\s-]+/g, "_");
  const zh: Record<string, string> = {
    active: "进行中",
    planning: "规划中",
    needs_attention: "需关注",
    frozen: "已冻结",
    executable: "可执行",
    not_started: "未开始",
    waiting_upstream: "等待上游",
    needs_review: "待审查",
  };
  const en: Record<string, string> = {
    active: "Active",
    planning: "Planning",
    needs_attention: "Needs attention",
    frozen: "Frozen",
    executable: "Ready",
    not_started: "Not started",
    waiting_upstream: "Waiting",
    needs_review: "Needs review",
  };
  const table = lang === "zh" ? zh : en;
  return table[key] || value;
}


export function buildResearchBoardColumns(input: ResearchBoardModelInput): ResearchBoardColumn[] {
  const knowledge = phaseFor(input.phases, "knowledge_collection");
  const experiment = phaseFor(input.phases, "experiment");
  const iteration = phaseFor(input.phases, "iteration");

  const knowledgeCards: ResearchBoardCard[] = [];
  if (input.sourceRunCount > 0 || input.sourceCandidateCount > 0) {
    knowledgeCards.push({
      id: "kc-progress",
      title: input.lang === "zh" ? "资料批次进度" : "Source batch progress",
      body: input.lang === "zh"
        ? `批次 ${input.sourceRunCount} · 候选 ${input.sourceCandidateCount}${input.knowledgeStatusLabel ? ` · ${input.knowledgeStatusLabel}` : ""}`
        : `Runs ${input.sourceRunCount} · candidates ${input.sourceCandidateCount}${input.knowledgeStatusLabel ? ` · ${input.knowledgeStatusLabel}` : ""}`,
      meta: [
        input.sourceCandidateCount
          ? (input.lang === "zh" ? `候选 ${input.sourceCandidateCount}` : `${input.sourceCandidateCount} candidates`)
          : "",
      ].filter(Boolean),
      foot: humanizeBoardStatus(
        input.knowledgeStatusLabel || (input.lang === "zh" ? "进行中" : "In progress"),
        input.lang,
      ),
      active: true,
    });
  }
  knowledgeCards.push(
    cardFromPhase(knowledge, {
      id: "kc-empty",
      title: input.lang === "zh" ? `开始${RESEARCH_STAGE_TERMS.knowledge_collection.zh}` : "Start knowledge collection",
      body: input.lang === "zh"
        ? "生成搜索计划和团队分工，先把资料搜索跑起来。"
        : "Create the search plan and team assignments.",
      meta: input.lang === "zh" ? ["资料寻找", "提炼", "入库"] : ["find", "extract", "ingest"],
      foot: input.lang === "zh" ? "未开始" : "Not started",
    }, input.lang),
  );

  const experimentCards: ResearchBoardCard[] = [];
  if (input.experimentDesignFrozen || input.frozenDesignLabel) {
    const frozenTitle = productBoardTitle(
      input.frozenDesignLabel || "",
      input.lang === "zh" ? "冻结设计" : "Frozen design",
    );
    experimentCards.push({
      id: "ex-frozen",
      title: frozenTitle,
      body: input.lang === "zh"
        ? "实验设计已冻结；可进入执行迭代或补证据。"
        : "Design is frozen; move to iteration or add evidence.",
      meta: input.lang === "zh" ? ["冻结", "可执行"] : ["frozen", "executable"],
      foot: input.lang === "zh" ? "当前主线" : "Current baseline",
      active: true,
    });
  }
  experimentCards.push(
    cardFromPhase(experiment, {
      id: "ex-empty",
      title: input.lang === "zh" ? "实验设计" : "Experiment design",
      body: input.lang === "zh"
        ? "起草假设、变量与复现合同。"
        : "Draft hypothesis, variables, and reproduction contract.",
      meta: input.lang === "zh" ? ["假设", "变量", "冻结设计"] : ["hypothesis", "vars", "freeze"],
      foot: input.lang === "zh" ? "等待上游" : "Waiting upstream",
    }, input.lang),
  );

  const iterationCards: ResearchBoardCard[] = [];
  if (input.bestCandidateId) {
    iterationCards.push({
      id: "it-best",
      title: productBoardTitle(
        input.bestCandidateId,
        input.lang === "zh" ? "当前最佳候选" : "Best candidate",
      ),
      body: input.lang === "zh"
        ? "当前最佳候选 · 独立门禁，不汇总总分。"
        : "Current best candidate · independent gates, no total score.",
      meta: input.lang === "zh" ? ["最佳", "可比较"] : ["best", "comparable"],
      foot: input.lang === "zh" ? "已晋升/保留" : "Promoted / retained",
      active: !input.latestDiagnostic,
    });
  }
  if (input.latestDiagnostic) {
    iterationCards.push({
      id: "it-diag",
      title: productBoardTitle(
        input.latestDiagnostic,
        input.lang === "zh" ? "最近诊断" : "Latest diagnostic",
      ),
      body: input.lang === "zh"
        ? "最近诊断单独展示，不覆盖主线结果。"
        : "Latest diagnostic is separate from the mainline result.",
      meta: input.lang === "zh" ? ["诊断"] : ["diagnostic"],
      foot: input.lang === "zh" ? "待审查" : "Needs review",
    });
  }
  if (!iterationCards.length) {
    iterationCards.push(
      cardFromPhase(iteration, {
        id: "it-empty",
        title: input.lang === "zh" ? "执行与迭代" : "Execution & iteration",
        body: input.lang === "zh"
          ? "冻结实验设计后进入执行、评估和迭代。"
          : "Run, evaluate, and iterate after the design is frozen.",
        meta: input.lang === "zh" ? ["批次", "评估", "晋升"] : ["runs", "eval", "promote"],
        foot: input.lang === "zh" ? "等待上游" : "Waiting upstream",
      }, input.lang),
    );
  }

  return [
    {
      id: "knowledge_collection",
      titleZh: RESEARCH_STAGE_TERMS.knowledge_collection.zh,
      titleEn: RESEARCH_STAGE_TERMS.knowledge_collection.en,
      cards: knowledgeCards.slice(0, 3),
    },
    {
      id: "experiment",
      titleZh: "实验设计",
      titleEn: "Experiment",
      cards: experimentCards.slice(0, 3),
    },
    {
      id: "iteration",
      titleZh: "执行与迭代",
      titleEn: "Iteration",
      cards: iterationCards.slice(0, 3),
    },
  ];
}
