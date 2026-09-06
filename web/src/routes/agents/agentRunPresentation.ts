/** Display projection only; preserve ordinary summaries and unknown payloads. */
export function agentRunSummary(summary: string | undefined): string {
  const text = summary || "";
  if (!text.trimStart().startsWith("{")) return text;
  try {
    const payload = JSON.parse(text);
    // The same display contract used by ChatGroupMessagePresentation.
    if (payload?.schemaVersion === 1 && typeof payload.display?.conclusion === "string") {
      return payload.display.conclusion.trim() || text;
    }
  } catch {
    // A prose/truncated summary is not a structured meeting payload.
  }
  return text;
}

export function agentRunStatusLabel(status: string, lang: "zh" | "en"): string {
  const labels: Record<string, string> = {
    completed: "已完成", succeeded: "已成功", running: "进行中", queued: "排队中",
    failed: "失败", cancelled: "已取消", blocked: "已阻塞", pending: "待处理",
    idle: "空闲", waiting: "等待中", paused: "已暂停", timed_out: "已超时",
  };
  return lang === "zh" ? labels[status] || status : status;
}
