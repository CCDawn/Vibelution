import type { RuntimeTaskCard } from "../api/runtimeTasks";
import type { ActiveWorkIndicator } from "./systemStatus";

/** Match the same explicit /chat session identity used by the task-panel projection. */
function activeChatSessionIdentity(href: string): string {
  try {
    const route = new URL(href, "http://vibelution.invalid");
    return route.pathname === "/chat" ? String(route.searchParams.get("session") || "").trim() : "";
  } catch {
    return "";
  }
}

/**
 * Count active work plus distinct runtime tasks. A runtime task collapses into
 * active chat work only when both projections carry the same child-session ID.
 */
export function projectTaskCount(active: ActiveWorkIndicator | null | undefined, background: readonly RuntimeTaskCard[]) {
  const sessions = new Set(
    (active?.items ?? [])
      .filter((item) => item.kind === "chat")
      .map((item) => activeChatSessionIdentity(item.href))
      .filter(Boolean),
  );
  const seen = new Set<string>();
  let count = active?.count ?? 0;
  for (const task of background) {
    const taskId = String(task.taskId || "").trim();
    if (taskId && seen.has(taskId)) continue;
    if (taskId) seen.add(taskId);

    const childSessionId = String(task.childSessionId || "").trim();
    if (childSessionId && sessions.has(childSessionId)) continue;
    count += 1;
  }
  return count;
}
