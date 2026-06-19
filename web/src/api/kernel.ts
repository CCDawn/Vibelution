import { fetchJson } from "./client";
import type { KernelTaskListPayload, KernelTaskTimelinePayload } from "./types";

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

export function getKernelTaskTimeline(taskId: string) {
  return fetchJson<KernelTaskTimelinePayload>(kernelTaskTimelineUrl(taskId));
}
