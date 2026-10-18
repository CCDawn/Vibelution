import { childSessionHref, type RuntimeTaskCard } from "../api/runtimeTasks";
import type { ActiveWorkIndicatorItem, SystemStatusTone } from "./systemStatus";

export type RuntimeTaskMenuItem = Omit<ActiveWorkIndicatorItem, "kind"> & { kind: string };

/** Preserve task identity/status; missing or unfamiliar facts never imply running. */
export function runtimeTaskMenuItem(task: RuntimeTaskCard): RuntimeTaskMenuItem {
  const label = String(task.title || "").trim() || String(task.taskId || "").trim();
  const summary = String(task.summary || "").trim();
  const status = String(task.status || "").trim().toLowerCase() || "unknown";
  let tone: SystemStatusTone = "caution";
  if (["running", "sent"].includes(status)) tone = "running";
  else if (["failed", "error", "incomplete", "timeout", "timed_out"].includes(status)) tone = "failed";
  else if (["idle", "completed", "closed", "stopped", "cancelled", "canceled", "exited"].includes(status)) tone = "idle";
  return {
    kind: task.kind || "unknown",
    label, summary, fullSummary: summary, status,
    runId: String(task.taskId || ""),
    href: task.kind === "child_session" ? childSessionHref(String(task.childSessionId || "")) : "/aux",
    detail: label, tone,
  };
}
