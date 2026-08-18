/**
 * Visual status mapping for workflow nodes/edges (renderer presentation).
 * Graph semantic enrichment lives in product/workflow/workflowCanvasModel.
 */

import type {
  WorkflowEdgePathState,
  WorkflowEdgeSemanticKind,
  WorkflowNodeRunStatus,
} from "../../../product/workflow/workflowCanvasTypes";

export type NodeStatusVisual = {
  status: WorkflowNodeRunStatus;
  statusLabel: string;
  icon: "circle" | "play" | "user" | "check" | "x" | "ban" | "minus" | "alert" | "skip" | "stale";
  toneClass: string;
  borderClass: string;
  ringClass: string;
  textClass: string;
  /** Serpentine card surface tint — keeps the four status buckets legible on white cards. */
  surfaceClass: string;
  /** Serpentine top accent bar, colored by status bucket. */
  accentBarClass: string;
  /** Status badge (icon + label) chip classes. */
  badgeClass: string;
};

const STATUS_LABEL_ZH: Record<WorkflowNodeRunStatus, string> = {
  pending: "待运行",
  ready: "就绪",
  running: "运行中",
  waiting_human: "等待人工",
  succeeded: "已完成",
  failed: "失败",
  blocked: "阻塞",
  skipped: "已跳过",
  stale: "过期",
  cancelled: "已取消",
};

export function nodeStatusLabel(status: WorkflowNodeRunStatus, lang: "zh" | "en" = "zh"): string {
  if (lang === "en") {
    return status.replace(/_/g, " ");
  }
  return STATUS_LABEL_ZH[status] ?? status;
}

/**
 * Visual grammar: four legible buckets aligned with CI/pipeline convention —
 * Done uses the shared `--state-success` token, In Progress uses system blue,
 * attention uses amber, failure uses red, and pending stays the faintest.
 */
export function resolveNodeStatusVisual(status: WorkflowNodeRunStatus): NodeStatusVisual {
  switch (status) {
    case "pending":
      return {
        status,
        statusLabel: STATUS_LABEL_ZH.pending,
        icon: "circle",
        toneClass: "bg-[color-mix(in_srgb,var(--vui-surface-row)_55%,transparent)] text-[var(--fg-tertiary)]",
        borderClass: "border-[var(--vui-border-subtle)]",
        ringClass: "",
        textClass: "text-[var(--fg-tertiary)]",
        surfaceClass: "bg-[color-mix(in_srgb,var(--vui-surface-row)_38%,var(--vui-surface-panel))]",
        accentBarClass: "bg-[var(--vui-border-subtle)]",
        badgeClass:
          "border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-row)_72%,transparent)] text-[var(--fg-tertiary)]",
      };
    case "ready":
      return {
        status,
        statusLabel: STATUS_LABEL_ZH.ready,
        icon: "circle",
        toneClass: "bg-[var(--vui-surface-panel)] text-[var(--fg-secondary)]",
        borderClass: "border-[color-mix(in_srgb,var(--accent-cool)_32%,var(--vui-border-subtle))]",
        ringClass: "",
        textClass: "text-[var(--fg-secondary)]",
        surfaceClass: "bg-[color-mix(in_srgb,var(--accent-cool)_3%,var(--vui-surface-panel))]",
        accentBarClass: "bg-[color-mix(in_srgb,var(--accent-cool)_55%,transparent)]",
        badgeClass:
          "border-[color-mix(in_srgb,var(--accent-cool)_30%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_7%,transparent)] text-[var(--accent-cool)]",
      };
    case "running":
      return {
        status,
        statusLabel: STATUS_LABEL_ZH.running,
        icon: "play",
        toneClass: "bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-panel))] text-[var(--accent-cool)]",
        borderClass: "border-[color-mix(in_srgb,var(--accent-cool)_60%,var(--vui-border-subtle))]",
        ringClass: "ring-2 ring-[color-mix(in_srgb,var(--accent-cool)_35%,transparent)]",
        textClass: "text-[var(--accent-cool)]",
        surfaceClass: "bg-[color-mix(in_srgb,var(--accent-cool)_7%,var(--vui-surface-panel))]",
        accentBarClass: "bg-[var(--accent-cool)]",
        badgeClass:
          "border-[color-mix(in_srgb,var(--accent-cool)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)] text-[var(--accent-cool)]",
      };
    case "waiting_human":
      return {
        status,
        statusLabel: STATUS_LABEL_ZH.waiting_human,
        icon: "user",
        toneClass: "bg-[color-mix(in_srgb,var(--state-warning)_10%,var(--vui-surface-panel))] text-[var(--state-warning)]",
        borderClass: "border-[color-mix(in_srgb,var(--state-warning)_48%,var(--vui-border-subtle))]",
        ringClass: "ring-2 ring-[color-mix(in_srgb,var(--state-warning)_28%,transparent)]",
        textClass: "text-[var(--state-warning)]",
        surfaceClass: "bg-[color-mix(in_srgb,var(--state-warning)_7%,var(--vui-surface-panel))]",
        accentBarClass: "bg-[var(--state-warning)]",
        badgeClass:
          "border-[color-mix(in_srgb,var(--state-warning)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-warning)_12%,transparent)] text-[var(--state-warning)]",
      };
    case "succeeded":
      return {
        status,
        statusLabel: STATUS_LABEL_ZH.succeeded,
        icon: "check",
        toneClass: "bg-[color-mix(in_srgb,var(--state-success)_9%,var(--vui-surface-panel))] text-[var(--state-success)]",
        borderClass: "border-[color-mix(in_srgb,var(--state-success)_48%,var(--vui-border-subtle))]",
        ringClass: "",
        textClass: "text-[var(--state-success)]",
        surfaceClass: "bg-[color-mix(in_srgb,var(--state-success)_6%,var(--vui-surface-panel))]",
        accentBarClass: "bg-[var(--state-success)]",
        badgeClass:
          "border-[color-mix(in_srgb,var(--state-success)_36%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-success)_12%,transparent)] text-[var(--state-success)]",
      };
    case "failed":
      return {
        status,
        statusLabel: STATUS_LABEL_ZH.failed,
        icon: "x",
        toneClass: "bg-[color-mix(in_srgb,var(--state-error)_8%,var(--vui-surface-panel))] text-[var(--state-error)]",
        borderClass: "border-[color-mix(in_srgb,var(--state-error)_48%,var(--vui-border-subtle))]",
        ringClass: "",
        textClass: "text-[var(--state-error)]",
        surfaceClass: "bg-[color-mix(in_srgb,var(--state-error)_6%,var(--vui-surface-panel))]",
        accentBarClass: "bg-[var(--state-error)]",
        badgeClass:
          "border-[color-mix(in_srgb,var(--state-error)_36%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_10%,transparent)] text-[var(--state-error)]",
      };
    case "blocked":
      return {
        status,
        statusLabel: STATUS_LABEL_ZH.blocked,
        icon: "ban",
        toneClass: "bg-[color-mix(in_srgb,var(--state-error)_6%,var(--vui-surface-panel))] text-[var(--state-error)]",
        borderClass: "border-[color-mix(in_srgb,var(--state-warning)_40%,var(--state-error))]",
        ringClass: "ring-1 ring-[color-mix(in_srgb,var(--state-error)_25%,transparent)]",
        textClass: "text-[var(--state-error)]",
        surfaceClass: "bg-[color-mix(in_srgb,var(--state-error)_5%,var(--vui-surface-panel))]",
        accentBarClass: "bg-[var(--state-error)]",
        badgeClass:
          "border-[color-mix(in_srgb,var(--state-error)_36%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_10%,transparent)] text-[var(--state-error)]",
      };
    case "skipped":
      return {
        status,
        statusLabel: STATUS_LABEL_ZH.skipped,
        icon: "skip",
        toneClass: "bg-transparent text-[var(--fg-tertiary)] opacity-75",
        borderClass: "border-dashed border-[var(--vui-border-subtle)]",
        ringClass: "",
        textClass: "text-[var(--fg-tertiary)]",
        surfaceClass: "bg-[color-mix(in_srgb,var(--vui-surface-panel)_70%,transparent)]",
        accentBarClass: "bg-transparent",
        badgeClass:
          "border-dashed border-[var(--vui-border-subtle)] bg-transparent text-[var(--fg-tertiary)]",
      };
    case "stale":
      return {
        status,
        statusLabel: STATUS_LABEL_ZH.stale,
        icon: "stale",
        toneClass: "bg-transparent text-[var(--fg-tertiary)] opacity-70",
        borderClass: "border-dashed border-[var(--vui-border-subtle)]",
        ringClass: "",
        textClass: "text-[var(--fg-tertiary)]",
        surfaceClass: "bg-[color-mix(in_srgb,var(--vui-surface-panel)_70%,transparent)]",
        accentBarClass: "bg-transparent",
        badgeClass:
          "border-dashed border-[var(--vui-border-subtle)] bg-transparent text-[var(--fg-tertiary)]",
      };
    case "cancelled":
      return {
        status,
        statusLabel: STATUS_LABEL_ZH.cancelled,
        icon: "minus",
        toneClass: "bg-transparent text-[var(--fg-tertiary)] opacity-70",
        borderClass: "border-[var(--vui-border-subtle)]",
        ringClass: "",
        textClass: "text-[var(--fg-tertiary)]",
        surfaceClass: "bg-[color-mix(in_srgb,var(--vui-surface-panel)_70%,transparent)]",
        accentBarClass: "bg-transparent",
        badgeClass:
          "border-[var(--vui-border-subtle)] bg-transparent text-[var(--fg-tertiary)]",
      };
    default:
      return resolveNodeStatusVisual("pending");
  }
}

export type EdgeStrokeVisual = {
  stroke: string;
  strokeWidth: number;
  animated: boolean;
  dasharray?: string;
};

export function resolveEdgeStroke(pathState: WorkflowEdgePathState, semanticKind: WorkflowEdgeSemanticKind): EdgeStrokeVisual {
  if (pathState === "danger") {
    return { stroke: "var(--state-error, #dc2626)", strokeWidth: 2, animated: false };
  }
  if (pathState === "attention") {
    return { stroke: "var(--state-warning, #d97706)", strokeWidth: 2, animated: true };
  }
  if (pathState === "active") {
    return { stroke: "var(--accent-cool, #2563eb)", strokeWidth: 2.25, animated: true };
  }
  if (pathState === "traversed") {
    return { stroke: "var(--fg-secondary, #52525b)", strokeWidth: 1.75, animated: false };
  }
  if (semanticKind === "rerun" || semanticKind === "revise" || semanticKind === "rollback") {
    return {
      stroke: "var(--vui-border-strong, #a1a1aa)",
      strokeWidth: 1.5,
      animated: false,
      dasharray: "6 4",
    };
  }
  if (semanticKind === "stop") {
    return { stroke: "var(--fg-tertiary, #71717a)", strokeWidth: 1.5, animated: false, dasharray: "4 4" };
  }
  return { stroke: "var(--vui-border-strong, #a1a1aa)", strokeWidth: 1.5, animated: false };
}
