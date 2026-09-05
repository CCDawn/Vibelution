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

  const readinessReasons = [
    ["knowledge_package_not_materialized", "知识包尚未形成，请先完成知识搜集与交接", "The knowledge package is not ready; complete collection and handoff"],
    ["hypothesis_round_unconverged", "假说讨论尚未收敛，请检查本轮有效候选与未解决分歧", "The hypothesis round has not converged; review valid candidates and open disagreements"],
    ["template_baseline_missing", "缺少研究模板基线，请核对题目档案中的基线配置", "The research template baseline is missing; check the question baseline configuration"],
    ["rebind_target_required", "请先选择要重绑的 Agent", "Select the replacement agent first"],
    ["four-perspective canonical search receipts", "资料检索缺少四视角的有效回执或与回执关联的候选，请查看资料寻找的来源记录", "Source search requires valid four-perspective receipts and receipt-bound candidates"],
  ].filter(([code]) => lower.includes(code));
  if (readinessReasons.length) {
    return {
      ...DEFAULT_PRESENTATION,
      titleZh: "前置条件未满足", titleEn: "Prerequisites are not ready",
      bodyZh: readinessReasons.map(([, zh]) => zh).join("；") + "。",
      bodyEn: readinessReasons.map(([, , en]) => en).join("; ") + ".",
    };
  }

  if (lower.includes("workflow_definition_unavailable") || lower.includes("unavailable workflow definition")) {
    return {
      ...DEFAULT_PRESENTATION,
      titleZh: "此运行引用的流程定义不可用", titleEn: "This run's workflow definition is unavailable",
      bodyZh: "当前版本无法读取此运行固定的流程定义。可查看题目档案或全局进度；等待和重复重试不会恢复已移除的定义。",
      bodyEn: "This version cannot read the workflow definition pinned to this run. Question records and global progress remain available; waiting or retrying cannot restore a removed definition.",
    };
  }
  if (lower.includes("dispatch") || lower.includes("thread")) {
    return {
      ...DEFAULT_PRESENTATION,
      titleZh: "任务执行链路未就绪", titleEn: "Task execution is not ready",
      bodyZh: "任务尚未正常启动或执行状态需要核对。请先查看诊断详情，再选择当前任务提供的恢复操作。",
      bodyEn: "The task has not started normally or its execution state needs reconciliation. Review diagnostic details before choosing a recovery action.",
    };
  }

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

/**
 * Compact single-line Chinese text for inline error display at the action
 * site (button row). Known backend failures get the productized title plus
 * guidance; unknown failures show only the generic title (or the caller's
 * context-specific fallback) so raw technical messages stay out of the main
 * flow.
 */
export function researchWorkflowErrorInlineText(
  rawMessage: string | null | undefined,
  fallbackZh?: string,
): string {
  const message = String(rawMessage || "").trim();
  const presentation = presentResearchWorkflowError(message);
  if (!message || presentation.bodyZh === message) {
    return fallbackZh?.trim() || presentation.titleZh;
  }
  return `${presentation.titleZh}。${presentation.bodyZh}`;
}
