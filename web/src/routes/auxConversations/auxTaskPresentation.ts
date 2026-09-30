import type { VStatusTone } from "../../components/vui";

/**
 * Display projection helpers for the aux conversations center.
 * Pure functions, no React — kept separate so route tests can cover the
 * mapping table without mounting the workbench shell.
 */

export type AuxLang = "zh" | "en";

export const AUX_TASK_KINDS = ["child_session", "cli_agent", "research_task"] as const;

export type AuxTaskKind = (typeof AUX_TASK_KINDS)[number];

const KIND_LABELS_ZH: Record<string, string> = {
  child_session: "子会话",
  cli_agent: "CLI agent",
  research_task: "研究任务",
};

const KIND_LABELS_EN: Record<string, string> = {
  child_session: "Child session",
  cli_agent: "CLI agent",
  research_task: "Research task",
};

export function auxTaskKindLabel(kind: string, lang: AuxLang): string {
  const normalized = String(kind || "").trim();
  if (lang === "zh") {
    return KIND_LABELS_ZH[normalized] || normalized || "-";
  }
  return KIND_LABELS_EN[normalized] || normalized || "-";
}

const STATUS_LABELS_ZH: Record<string, string> = {
  running: "运行中",
  queued: "排队中",
  waiting: "等待中",
  succeeded: "已成功",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  stopped: "已停止",
  stopping: "停止中",
  timed_out: "已超时",
};

export function auxTaskStatusLabel(status: string, lang: AuxLang): string {
  const normalized = String(status || "").trim();
  if (lang === "zh") {
    return STATUS_LABELS_ZH[normalized] || normalized || "-";
  }
  return normalized || "-";
}

export function auxTaskStatusTone(status: string): VStatusTone {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "succeeded" || normalized === "completed") {
    return "success";
  }
  if (normalized === "running" || normalized === "queued" || normalized === "stopping") {
    return "accent";
  }
  if (normalized === "failed" || normalized === "timed_out") {
    return "danger";
  }
  if (normalized === "cancelled" || normalized === "stopped") {
    return "warning";
  }
  return "neutral";
}

/**
 * Terminal-state marker for a single card outside the list buckets: an ended
 * task always carries `endedAt`, live tasks never do. Never derive liveness
 * from the status string — the registry may add new status words.
 */
export function isTerminalRuntimeTask(card: { endedAt?: string | null }): boolean {
  return Boolean(String(card.endedAt || "").trim());
}

const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;

/** Compact relative time: "刚刚" / "N 分钟前" / "N 小时前" / "N 天前", else the date. */
export function formatRelativeTime(value: string, lang: AuxLang, nowMs = Date.now()): string {
  const raw = String(value || "").trim();
  if (!raw) {
    return "-";
  }
  const time = new Date(raw).getTime();
  if (Number.isNaN(time)) {
    return raw;
  }
  const delta = Math.max(0, nowMs - time);
  if (delta < MINUTE_MS) {
    return lang === "zh" ? "刚刚" : "just now";
  }
  if (delta < HOUR_MS) {
    const minutes = Math.floor(delta / MINUTE_MS);
    return lang === "zh" ? `${minutes} 分钟前` : `${minutes}m ago`;
  }
  if (delta < DAY_MS) {
    const hours = Math.floor(delta / HOUR_MS);
    return lang === "zh" ? `${hours} 小时前` : `${hours}h ago`;
  }
  const days = Math.floor(delta / DAY_MS);
  if (days < 14) {
    return lang === "zh" ? `${days} 天前` : `${days}d ago`;
  }
  return new Date(time).toLocaleString(lang === "zh" ? "zh-CN" : "en-US", { hour12: false });
}

/** Absolute start-end range for the detail meta strip. */
export function formatTaskTimeRange(
  startedAt: string,
  endedAt: string | null | undefined,
  lang: AuxLang,
  nowMs = Date.now(),
): string {
  const started = formatRelativeTime(startedAt, lang, nowMs);
  const ended = String(endedAt || "").trim();
  if (!ended) {
    return lang === "zh" ? `${started} 起` : `since ${started}`;
  }
  return `${started} → ${formatRelativeTime(ended, lang, nowMs)}`;
}
