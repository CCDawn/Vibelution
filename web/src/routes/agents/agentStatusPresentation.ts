import type {
  AgentConfigHealthIssue,
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
} from "../../api/types";

export type RuntimeFocusEvidenceReason = "run" | "source_run" | "session" | "fallback" | "missing";

/** Tool governance request status labels (shared; keep panel free of shell-only deps). */
export function governanceStatusLabel(value: string, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  const zh: Record<string, string> = {
    pending_review: "待审批",
    applied: "已应用",
    rejected: "已拒绝",
  };
  const en: Record<string, string> = {
    pending_review: "Pending review",
    applied: "Applied",
    rejected: "Rejected",
  };
  return ((lang === "zh" ? zh : en)[normalized] ?? normalized) || "-";
}

export function issueTone(issues: AgentConfigHealthIssue[]) {
  if (issues.some((item) => item.severity === "blocking")) {
    return "blocking";
  }
  if (issues.some((item) => item.severity === "warning")) {
    return "warning";
  }
  if (issues.length > 0) {
    return "info";
  }
  return "ok";
}

export function issueLabel(issues: AgentConfigHealthIssue[], lang: "zh" | "en") {
  const tone = issueTone(issues);
  if (tone === "blocking") {
    return lang === "zh" ? "阻塞" : "Blocked";
  }
  if (tone === "warning") {
    return lang === "zh" ? "需处理" : "Review";
  }
  if (tone === "info") {
    return lang === "zh" ? "提醒" : "Notice";
  }
  return lang === "zh" ? "正常" : "OK";
}

export function issuePanelLabel(
  issues: AgentConfigHealthIssue[],
  labels: { statusReminders: string; healthIssues: string },
) {
  return issueTone(issues) === "info" ? labels.statusReminders : labels.healthIssues;
}

export function workspaceHealthStatusLabel(status: string, lang: "zh" | "en") {
  const normalized = String(status || "ok").trim().toLowerCase();
  const zh: Record<string, string> = {
    ok: "正常",
    warning: "需处理",
    blocked: "阻塞",
  };
  const en: Record<string, string> = {
    ok: "OK",
    warning: "Needs review",
    blocked: "Blocked",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? status;
}

export function workspaceHealthStatusDescription(status: string, summary: AgentConfigWorkspace["summary"] | undefined, lang: "zh" | "en") {
  const normalized = String(status || "ok").trim().toLowerCase();
  const issueCount = summary?.healthIssueCount ?? 0;
  const blockingCount = summary?.blockingIssueCount ?? 0;
  const warningCount = summary?.warningIssueCount ?? 0;
  if (normalized === "ok" || issueCount === 0) {
    return lang === "zh" ? "当前没有需处理问题。" : "No issues need review.";
  }
  if (lang === "zh") {
    return `共 ${issueCount} 个需处理问题，阻塞 ${blockingCount} 个，警告 ${warningCount} 个。`;
  }
  return `${issueCount} issues need review: ${blockingCount} blocking, ${warningCount} warning.`;
}

export function sortedHealthIssues(issues: AgentConfigHealthIssue[]) {
  const order: Record<string, number> = { blocking: 0, warning: 1, info: 2 };
  return [...issues].sort((left, right) => (order[left.severity] ?? 3) - (order[right.severity] ?? 3));
}

export function issueSummary(issues: AgentConfigHealthIssue[], lang: "zh" | "en") {
  const [first] = sortedHealthIssues(issues);
  if (!first) {
    return lang === "zh" ? "配置完整，可直接引用" : "Ready to use";
  }
  const rest = issues.length > 1 ? (lang === "zh" ? `，另有 ${issues.length - 1} 项` : `, +${issues.length - 1} more`) : "";
  return `${issueDisplayTitle(first, lang)}${rest}`;
}

export function issueDisplayTitle(issue: AgentConfigHealthIssue, lang: "zh" | "en") {
  if (issue.code === "pending_inbox_messages") {
    return lang === "zh" ? "Inbox 有待处理消息" : "Pending inbox messages";
  }
  return issue.title;
}

export function issueNextStep(issues: AgentConfigHealthIssue[], lang: "zh" | "en") {
  const [first] = sortedHealthIssues(issues);
  const tone = issueTone(issues);
  if (tone === "blocking") {
    return lang === "zh" ? "先补齐阻塞项，否则不要加入可调度池。" : "Fix blocking items before routing this Agent.";
  }
  if (tone === "warning") {
    return lang === "zh" ? "建议在配置页处理，避免运行时缺上下文。" : "Review config to avoid missing runtime context.";
  }
  if (tone === "info") {
    if (first?.code === "pending_inbox_messages") {
      return lang === "zh"
        ? "这是 Inbox 待办提醒，不代表配置坏了；进入活动页处理消息即可。"
        : "This is an inbox reminder, not a broken config; handle the messages in Activity.";
    }
    return lang === "zh" ? "这是提醒项，不影响当前配置完整度。" : "This is a reminder and does not affect current config readiness.";
  }
  return lang === "zh" ? "当前没有需要处理的问题或提醒。" : "No issue or reminder needs action.";
}

export function runtimeStatusLabel(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  const state = String(agent?.runtimeStatus?.state || (agent?.status === "archived" ? "archived" : "idle")).trim();
  const zh: Record<string, string> = {
    idle: "空闲",
    running: "运行中",
    failed: "失败",
    blocked: "阻塞",
    stopped: "已停止",
    archived: "已归档",
    unknown: "未知",
  };
  const en: Record<string, string> = {
    idle: "Idle",
    running: "Running",
    failed: "Failed",
    blocked: "Blocked",
    stopped: "Stopped",
    archived: "Archived",
    unknown: "Unknown",
  };
  return (lang === "zh" ? zh : en)[state] ?? agent?.runtimeStatus?.label ?? (state || "-");
}

export function runtimeStatusTone(agent: AgentConfigWorkspaceAgent | null | undefined) {
  const state = String(agent?.runtimeStatus?.state || (agent?.status === "archived" ? "archived" : "idle")).trim();
  return ["idle", "running", "failed", "blocked", "stopped", "archived", "unknown"].includes(state) ? state : "unknown";
}

export function runtimeNextStep(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  const state = runtimeStatusTone(agent);
  if (state === "running") {
    return lang === "zh"
      ? "先打开会话确认实时输出；如果出现卡住，再进入日志证据查看当前 run。"
      : "Open the session first to inspect live output; if it stalls, open log evidence for the current run.";
  }
  if (state === "failed") {
    return lang === "zh"
      ? "优先打开日志证据，定位失败事件和 raw log；再对照下方运行历史。"
      : "Open log evidence first to locate the failed event and raw log, then compare the run history below.";
  }
  if (state === "blocked") {
    return lang === "zh"
      ? "先检查 Inbox 和运行历史，确认是在等输入、等证据，还是需要人工复核。"
      : "Check Inbox and run history first to see whether it is waiting for input, evidence, or review.";
  }
  if (state === "stopped") {
    return lang === "zh"
      ? "查看最近运行记录确认停止原因；需要继续时从关联会话恢复上下文。"
      : "Inspect the latest run record for the stop reason; resume from the linked session when needed.";
  }
  if (state === "archived") {
    return lang === "zh"
      ? "该 Agent 已归档；其绑定会话已封存并从会话栏隐藏，可在本页执行彻底删除。"
      : "This Agent is archived. Its bound sessions are sealed and hidden from chat; permanent cleanup is available on this page.";
  }
  if (state === "unknown") {
    return lang === "zh"
      ? "运行态来源不可用；先刷新配置，再查看日志总入口确认是否缺少 WorkRun 快照。"
      : "Runtime status is unavailable; refresh config, then inspect Logs to confirm whether WorkRun snapshots are missing.";
  }
  return lang === "zh"
    ? "当前没有活跃运行；可查看最近运行历史、Inbox，或打开直连会话分配下一步任务。"
    : "No active run is visible; inspect recent run history, Inbox, or open the direct session for the next task.";
}

export function runtimeEvidenceReasonLabel(reason: RuntimeFocusEvidenceReason, lang: "zh" | "en") {
  const zh: Record<RuntimeFocusEvidenceReason, string> = {
    run: "按 run 命中",
    source_run: "按 source run 命中",
    session: "按 session 命中",
    fallback: "回落证据",
    missing: "暂无证据",
  };
  const en: Record<RuntimeFocusEvidenceReason, string> = {
    run: "Matched by run",
    source_run: "Matched by source run",
    session: "Matched by session",
    fallback: "Fallback evidence",
    missing: "No evidence",
  };
  return (lang === "zh" ? zh : en)[reason];
}

export function modeLabel(mode: string, lang: "zh" | "en") {
  const zh: Record<string, string> = {
    chat: "会话",
    research: "科研",
    supervised_evolution: "监督",
    self_evolution: "自进化",
    general: "通用",
  };
  const en: Record<string, string> = {
    chat: "Chat",
    research: "Research",
    supervised_evolution: "Supervised",
    self_evolution: "Self evolution",
    general: "General",
  };
  return (lang === "zh" ? zh : en)[mode] ?? mode;
}
