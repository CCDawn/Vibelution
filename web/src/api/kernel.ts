import { fetchJson } from "./client";
import type { KernelTask, KernelTaskListPayload, KernelTaskTimelinePayload } from "./types";

export const KERNEL_TASKS_ENDPOINT = "/api/kernel/tasks";

export function kernelTaskListUrl(status = "", limit = 80) {
  const params = new URLSearchParams();
  if (status) {
    params.set("status", status);
  }
  params.set("limit", String(limit));
  return `${KERNEL_TASKS_ENDPOINT}?${params.toString()}`;
}

export function listKernelTasks(status = "", limit = 80) {
  return fetchJson<KernelTaskListPayload>(kernelTaskListUrl(status, limit));
}

export function kernelTaskTimelineUrl(taskId: string) {
  return `${KERNEL_TASKS_ENDPOINT}/${encodeURIComponent(taskId)}/timeline`;
}

export function kernelTaskCenterHref(taskId: string) {
  const normalized = String(taskId || "").trim();
  if (!normalized) {
    return "/kernel";
  }
  const params = new URLSearchParams();
  params.set("taskId", normalized);
  return `/kernel?${params.toString()}`;
}

export function selectKernelTaskId(tasks: Array<Pick<KernelTask, "taskId">>, requestedTaskId = "") {
  const normalized = String(requestedTaskId || "").trim();
  if (normalized) {
    return normalized;
  }
  return tasks[0]?.taskId ?? "";
}

export function getKernelTaskTimeline(taskId: string) {
  return fetchJson<KernelTaskTimelinePayload>(kernelTaskTimelineUrl(taskId));
}
