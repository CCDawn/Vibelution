/**
 * Productized presentation for team research workflow API errors.
 * Maps known backend messages to short Chinese-first copy + recommended action.
 */

export type ResearchWorkflowErrorAction =
  | "reset_source_only"
  | "reset_progress_cascade"
  | "wait_for_search"
  | "select_project"
  | "none";

export type ResearchWorkflowErrorPresentation = {
  titleZh: string;
  titleEn: string;
  bodyZh: string;
  bodyEn: string;
  recommendedAction: ResearchWorkflowErrorAction;
  actionLabelZh: string;
  actionLabelEn: string;
};

const DEFAULT_PRESENTATION: ResearchWorkflowErrorPresentation = {
  titleZh: "操作未完成",
  titleEn: "Action could not finish",
  bodyZh: "请根据下方详情调整后重试。",
  bodyEn: "Adjust based on the details below and retry.",
  recommendedAction: "none",
  actionLabelZh: "",
  actionLabelEn: "",
};

export function presentResearchWorkflowError(
  rawMessage: string | null | undefined,
): ResearchWorkflowErrorPresentation {
  const message = String(rawMessage || "").trim();
  if (!message) {
    return DEFAULT_PRESENTATION;
  }
  const lower = message.toLowerCase();

  if (
    lower.includes("source search is still running")
    || message.includes("资料搜索仍在进行")
  ) {
    return {
      titleZh: "资料搜索仍在进行",
      titleEn: "Source search still running",
      bodyZh: "请等待当前批次搜索结束后再清空或重开。",
      bodyEn: "Wait for the active search batch to finish before clearing or restarting.",
      recommendedAction: "wait_for_search",
      actionLabelZh: "稍后再试",
      actionLabelEn: "Try later",
    };
  }

  if (
    lower.includes("downstream experiment")
    || lower.includes("downstream research candidates")
    || message.includes("实验设计或迭代")
    || message.includes("下游科研候选")
    || message.includes("连同实验与迭代")
  ) {
    return {
      titleZh: "仅清资料不可用",
      titleEn: "Source-only reset blocked",
      bodyZh: "本项目已有实验/迭代或下游候选。可改用「连同实验与迭代一起清空」，或保留现状继续推进。",
      bodyEn: "This project already has experiment/iteration or downstream candidates. Use cascade reset, or keep progress.",
      recommendedAction: "reset_progress_cascade",
      actionLabelZh: "连同实验与迭代一起清空",
      actionLabelEn: "Clear sources + experiment/iteration",
    };
  }

  if (
    lower.includes("outside its resettable batches")
    || message.includes("不可重置的资料记录")
  ) {
    return {
      titleZh: "存在不可自动清空的资料",
      titleEn: "Some sources are not auto-resettable",
      bodyZh: "本项目有不在可清空批次内的资料记录，已保留供审计。可尝试级联清空或人工处理异常候选。",
      bodyEn: "Some source records sit outside resettable batches and are kept for audit.",
      recommendedAction: "reset_progress_cascade",
      actionLabelZh: "尝试级联清空",
      actionLabelEn: "Try cascade reset",
    };
  }

  if (
    lower.includes("only be reset for the active")
    || message.includes("只能重置当前激活")
  ) {
    return {
      titleZh: "请先激活目标科研项目",
      titleEn: "Activate the target project first",
      bodyZh: "清空操作只作用于当前激活的科研项目。",
      bodyEn: "Reset only applies to the active research project.",
      recommendedAction: "select_project",
      actionLabelZh: "去切换项目",
      actionLabelEn: "Switch project",
    };
  }

  return {
    ...DEFAULT_PRESENTATION,
    bodyZh: message,
    bodyEn: message,
  };
}

export function researchWorkflowErrorTitle(
  presentation: ResearchWorkflowErrorPresentation,
  lang: "zh" | "en",
): string {
  return lang === "zh" ? presentation.titleZh : presentation.titleEn;
}

export function researchWorkflowErrorBody(
  presentation: ResearchWorkflowErrorPresentation,
  lang: "zh" | "en",
): string {
  return lang === "zh" ? presentation.bodyZh : presentation.bodyEn;
}

export function researchWorkflowErrorActionLabel(
  presentation: ResearchWorkflowErrorPresentation,
  lang: "zh" | "en",
): string {
  return lang === "zh" ? presentation.actionLabelZh : presentation.actionLabelEn;
}
