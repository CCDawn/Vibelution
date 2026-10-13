import type { ActiveWorkIndicatorItem } from "../../app/systemStatus";
import type { RuntimeTaskCard } from "../../api/runtimeTasks";

/**
 * Active-work chat entries retain their native /chat destination. Resolve the
 * session from that route so nested child-session tasks can collapse into the
 * existing, richer active-work link without guessing from a run id.
 */
export function activeWorkSessionIdentity(item: ActiveWorkIndicatorItem): string {
  if (item.kind !== "chat" || !item.href) {
    return "";
  }
  try {
    const href = new URL(item.href, "http://vibelution.invalid");
    return href.pathname === "/chat" ? String(href.searchParams.get("session") || "").trim() : "";
  } catch {
    return "";
  }
}

export function deduplicateRuntimeTasksByActiveWork(
  tasks: RuntimeTaskCard[],
  activeWorkItems: ActiveWorkIndicatorItem[],
): RuntimeTaskCard[] {
  const activeSessionIds = new Set(
    activeWorkItems.map(activeWorkSessionIdentity).filter(Boolean),
  );
  if (!activeSessionIds.size) {
    return tasks;
  }
  return tasks.filter((task) => {
    const childSessionId = String(task.childSessionId || "").trim();
    return !childSessionId || !activeSessionIds.has(childSessionId);
  });
}

/** Stop acceptance is intent only; a terminal list bucket is the confirmation. */
export function isRuntimeTaskAwaitingStopConfirmation(
  taskId: string,
  requestedTaskIds: readonly string[],
  terminalTaskIds: ReadonlySet<string>,
): boolean {
  const normalizedTaskId = String(taskId || "").trim();
  return Boolean(
    normalizedTaskId
    && requestedTaskIds.includes(normalizedTaskId)
    && !terminalTaskIds.has(normalizedTaskId),
  );
}
