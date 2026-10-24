export type LauncherCommandResultFacts = {
  completed?: boolean;
  ok?: boolean | null;
  cancelled?: boolean;
  errorType?: string;
  supersededByCommandId?: string;
};

type LauncherCommandResultState = "pending" | "completed" | "failed" | "cancelled" | "superseded" | "unknown";

const SUPERSEDED_ERRORS = new Set([
  "SupersededByOpenWorkbench",
  "SupersededByCloseWorkbench",
  "SupersededByForceCloseWorkbench",
]);

/** Queue completion and operation success are separate facts. */
export function launcherCommandResultPresentation(
  result: LauncherCommandResultFacts | null | undefined,
  lang: "zh" | "en",
): { state: LauncherCommandResultState; tone: "neutral" | "success" | "error"; label: string } {
  let state: LauncherCommandResultState;
  if (result?.completed !== true) {
    state = "pending";
  } else if (typeof result.ok !== "boolean") {
    state = "unknown";
  } else if (result.cancelled === true || result.errorType === "LifecycleCommandCancelled") {
    state = "cancelled";
  } else if (SUPERSEDED_ERRORS.has(result.errorType ?? "") || result.supersededByCommandId?.trim()) {
    state = "superseded";
  } else {
    state = result.ok ? "completed" : "failed";
  }
  const labels: Record<LauncherCommandResultState, [string, string]> = {
    pending: ["处理中", "Pending"],
    completed: ["已完成", "Completed"],
    failed: ["失败", "Failed"],
    cancelled: ["已取消", "Cancelled"],
    superseded: ["已被后续请求替代", "Superseded"],
    unknown: ["结果未知", "Unknown result"],
  };
  return {
    state,
    tone: state === "completed" ? "success" : state === "failed" ? "error" : "neutral",
    label: labels[state][lang === "zh" ? 0 : 1],
  };
}

/** Only command-result events carry the queue's terminal outcome contract. */
export function launcherCommandResultEventPresentation(
  event: LauncherCommandResultFacts & { type: string },
  lang: "zh" | "en",
) {
  return event.type === "command_queue.command_result_written"
    ? launcherCommandResultPresentation(event, lang)
    : null;
}
