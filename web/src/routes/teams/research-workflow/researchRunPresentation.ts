import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import { getNodeAdapter } from "./nodeAdapterModel";

const RUN_STATUS_LABELS: Record<string, string> = {
  queued: "准备中",
  running: "运行中",
  waiting_human: "等待确认",
  blocked: "等待处理",
  succeeded: "已完成",
  failed: "运行失败",
  cancelled: "已取消",
};

const RUN_STATUS_LABELS_EN: Record<string, string> = {
  queued: "Preparing",
  running: "Running",
  waiting_human: "Waiting for review",
  blocked: "Needs attention",
  succeeded: "Completed",
  failed: "Run failed",
  cancelled: "Cancelled",
};

export type ResearchRunOption = {
  runId: string;
  label: string;
};

export function researchRunStatusLabel(status: string, lang: "zh" | "en" = "zh"): string {
  if (lang === "en") return RUN_STATUS_LABELS_EN[status] ?? "Status unavailable";
  return RUN_STATUS_LABELS[status] ?? "状态待确认";
}

function runTimestamp(run: WorkflowRunRecord): number {
  const parsed = Date.parse(run.createdAt || run.updatedAt || "");
  return Number.isFinite(parsed) ? parsed : 0;
}

function runTimeLabel(run: WorkflowRunRecord): string {
  const timestamp = runTimestamp(run);
  if (!timestamp) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(timestamp);
}

export function buildResearchRunOptions(runs: WorkflowRunRecord[]): ResearchRunOption[] {
  const chronological = runs
    .map((run, sourceIndex) => ({ run, sourceIndex }))
    .sort((left, right) => {
      const byTime = runTimestamp(left.run) - runTimestamp(right.run);
      return byTime || left.sourceIndex - right.sourceIndex;
    });

  return chronological
    .map(({ run }, index) => {
      const time = runTimeLabel(run);
      const nodeLabel = getNodeAdapter(run.runtimeCurrentNodeIds?.[0])?.label ?? "";
      const detail = [time, nodeLabel, researchRunStatusLabel(run.status)].filter(Boolean).join(" · ");
      return {
        runId: run.runId,
        label: `第 ${index + 1} 次运行 · ${detail}`,
      };
    })
    .reverse();
}
