import { EvolutionActiveRun } from "../api/types";

type SummaryLanguage = "zh" | "en";

export type SupervisedRunSummaryLabels = {
  statusLabel: (status: string) => string;
  roleLabel: (role: string | undefined) => string;
};

export type SupervisedRunControlSummary = {
  tone: "running" | "success" | "warning" | "danger" | "idle";
  headline: string;
  reason: string;
  nextAction: string;
  stageLabel: string;
  resultLabel: string;
  decisiveEvent: EvolutionActiveRun["eventTail"][number] | null;
};

const TERMINAL_STATUSES = new Set(["done", "failed", "cancelled"]);

function clean(value: unknown): string {
  return String(value ?? "").trim();
}

function normalized(value: unknown): string {
  return clean(value).toLowerCase();
}

function sentenceFor(lang: SummaryLanguage, zh: string, en: string) {
  return lang === "zh" ? zh : en;
}

function roleResultText(
  event: EvolutionActiveRun["eventTail"][number],
  lang: SummaryLanguage,
  labels: SupervisedRunSummaryLabels,
) {
  const role = labels.roleLabel(event.role);
  const status = labels.statusLabel(event.resultStatus || event.status);
  const reason = clean(event.reason);
  return sentenceFor(
    lang,
    `${role} ${status}${reason ? `：${reason}` : ""}`,
    `${role} ${status}${reason ? `: ${reason}` : ""}`,
  );
}

function findLastEvent(run: EvolutionActiveRun, eventNames: string[]) {
  const names = new Set(eventNames);
  return [...(run.eventTail ?? [])].reverse().find((event) => names.has(normalized(event.event))) ?? null;
}

function findLastRoleFinish(run: EvolutionActiveRun, status?: string) {
  return [...(run.eventTail ?? [])].reverse().find((event) => {
    if (normalized(event.event) !== "role_finish") {
      return false;
    }
    return status ? normalized(event.resultStatus || event.status) === status : true;
  }) ?? null;
}

function countRoleFinishes(run: EvolutionActiveRun, statuses: string[]) {
  const wanted = new Set(statuses.map((item) => item.toLowerCase()));
  return (run.eventTail ?? []).filter((event) => (
    normalized(event.event) === "role_finish" && wanted.has(normalized(event.resultStatus || event.status))
  )).length;
}

function activeStage(run: EvolutionActiveRun, lang: SummaryLanguage, labels: SupervisedRunSummaryLabels) {
  const caseText = run.currentCaseId
    ? sentenceFor(
      lang,
      `第 ${run.currentCaseIndex || "--"}/${run.caseTotal || "--"} 个 case`,
      `Case ${run.currentCaseIndex || "--"}/${run.caseTotal || "--"}`,
    )
    : sentenceFor(lang, "尚未进入 case", "No case started");
  const role = clean(run.currentRole) ? labels.roleLabel(run.currentRole) : labels.statusLabel(run.currentPhase || run.status);
  return `${caseText} · ${role}`;
}

export function buildSupervisedRunControlSummary(
  run: EvolutionActiveRun,
  lang: SummaryLanguage,
  labels: SupervisedRunSummaryLabels,
): SupervisedRunControlSummary {
  const status = normalized(run.status);
  const sessionCancelled = findLastEvent(run, ["session_cancelled", "run_cancelled"]);
  const sessionError = findLastEvent(run, ["session_error", "run_failed"]);
  const sessionFinish = findLastEvent(run, ["session_finish", "run_completed"]);
  const failedRole = findLastRoleFinish(run, "failed");
  const cancelledRole = findLastRoleFinish(run, "cancelled");
  const lastRole = findLastRoleFinish(run);
  const decisiveEvent = sessionError || sessionCancelled || sessionFinish || failedRole || cancelledRole || lastRole;
  const reason = clean(run.reason) || clean(decisiveEvent?.reason) || clean(decisiveEvent?.summary) || clean(run.latestMessage);
  const statusText = labels.statusLabel(run.status);
  const stageLabel = activeStage(run, lang, labels);

  if (status === "cancelled" || sessionCancelled) {
    const parts = [
      failedRole ? roleResultText(failedRole, lang, labels) : "",
      cancelledRole ? roleResultText(cancelledRole, lang, labels) : "",
    ].filter(Boolean);
    const headline = parts.length > 0
      ? sentenceFor(lang, `本轮已取消：${parts.join("；")}。`, `Run cancelled: ${parts.join("; ")}.`)
      : sentenceFor(lang, "本轮监督任务已取消。", "This supervised run was cancelled.");
    return {
      tone: "warning",
      headline,
      reason,
      nextAction: sentenceFor(lang, "确认取消原因后，可以重跑失败项、打开历史记录或清理记录。", "Review the cancellation reason, then rerun failed items, open history, or clear the record."),
      stageLabel,
      resultLabel: statusText,
      decisiveEvent: sessionCancelled || cancelledRole || failedRole,
    };
  }

  if (status === "done" || sessionFinish) {
    const decision = clean(run.decision);
    const failedCaseCount = countRoleFinishes(run, ["failed", "timeout"]);
    if (failedCaseCount > 0) {
      return {
        tone: "warning",
        headline: decision
          ? sentenceFor(
            lang,
            `本轮评测已完成，监督结论为 ${decision}；包含 ${failedCaseCount} 个失败或超时样例。`,
            `Run complete with supervised decision ${decision}; ${failedCaseCount} case role(s) failed or timed out.`,
          )
          : sentenceFor(
            lang,
            `本轮评测已完成；包含 ${failedCaseCount} 个失败或超时样例。`,
            `Run complete; ${failedCaseCount} case role(s) failed or timed out.`,
          ),
        reason,
        nextAction: sentenceFor(
          lang,
          "这不是中断；失败样例已计入本轮结果。查看样例轨迹后，可以重跑失败项或调整评测环境。",
          "This was not interrupted; failed cases are counted in the completed run. Inspect the traces, then rerun failed items or adjust the evaluation environment.",
        ),
        stageLabel,
        resultLabel: statusText,
        decisiveEvent: sessionFinish,
      };
    }
    return {
      tone: "success",
      headline: decision
        ? sentenceFor(lang, `本轮已完成，监督结论为 ${decision}。`, `Run complete with supervised decision ${decision}.`)
        : sentenceFor(lang, "本轮监督任务已完成。", "This supervised run is complete."),
      reason,
      nextAction: sentenceFor(lang, "查看结论详情；如有提案，进入提案库或评审区继续处理。", "Review the decision; if a proposal exists, continue in the library or review workspace."),
      stageLabel,
      resultLabel: statusText,
      decisiveEvent: sessionFinish,
    };
  }

  if (status === "failed" || sessionError || failedRole) {
    const failedText = failedRole ? roleResultText(failedRole, lang, labels) : reason;
    return {
      tone: "danger",
      headline: sentenceFor(lang, `本轮失败：${failedText || "监督任务异常结束"}。`, `Run failed: ${failedText || "the supervised run ended with an error"}.`),
      reason,
      nextAction: sentenceFor(lang, "优先查看失败原因，再重跑失败项；如果是后端连接异常，先恢复服务。", "Inspect the failure reason first, then rerun failed items; if the backend is unreachable, restore the service first."),
      stageLabel,
      resultLabel: statusText,
      decisiveEvent: sessionError || failedRole,
    };
  }

  if (status === "stopping" || run.stopRequested) {
    return {
      tone: "warning",
      headline: sentenceFor(lang, "正在终止监督任务，等待当前安全点收束。", "Stopping the supervised run at the next safe checkpoint."),
      reason: clean(run.latestMessage) || reason,
      nextAction: sentenceFor(lang, "等待终止完成；完成后再决定重跑或清理。", "Wait for the stop to finish, then decide whether to rerun or clear the record."),
      stageLabel,
      resultLabel: statusText,
      decisiveEvent,
    };
  }

  if (status === "paused") {
    return {
      tone: "warning",
      headline: sentenceFor(lang, "监督任务已暂停，等待人工恢复。", "The supervised run is paused and waiting for resume."),
      reason: clean(run.latestMessage) || reason,
      nextAction: sentenceFor(lang, "确认当前 case 状态后恢复，或终止这一轮。", "Check the current case, then resume or terminate this run."),
      stageLabel,
      resultLabel: statusText,
      decisiveEvent,
    };
  }

  if (!TERMINAL_STATUSES.has(status)) {
    const task = clean(run.currentTask) || clean(run.latestMessage);
    return {
      tone: "running",
      headline: sentenceFor(lang, `正在运行：${stageLabel}。`, `Running: ${stageLabel}.`),
      reason: task,
      nextAction: sentenceFor(lang, "继续观察当前 case 输出；必要时可以暂停或终止。", "Watch the current case output; pause or terminate if needed."),
      stageLabel,
      resultLabel: statusText,
      decisiveEvent,
    };
  }

  return {
    tone: "idle",
    headline: clean(run.latestMessage) || sentenceFor(lang, "监督任务状态待确认。", "The supervised run state needs confirmation."),
    reason,
    nextAction: sentenceFor(lang, "查看事件时间线确认最后一次状态变化。", "Check the event timeline for the latest state change."),
    stageLabel,
    resultLabel: statusText,
    decisiveEvent,
  };
}
