function decodeJsonFragment(raw: string): string {
  try {
    return JSON.parse(`"${raw}"`) as string;
  } catch {
    return raw
      .replace(/\\u([0-9a-fA-F]{4})/g, (_, hex: string) => String.fromCharCode(parseInt(hex, 16)))
      .replace(/\\n/g, " ")
      .replace(/\\r/g, " ")
      .replace(/\\t/g, " ")
      .replace(/\\"/g, '"')
      .replace(/\\\\/g, "\\");
  }
}

/**
 * Best-effort conclusion from a structured summary truncated before the JSON
 * closes. Returns the decoded conclusion plus an ellipsis when the string was
 * cut, or "" when the payload has no readable conclusion.
 */
function truncatedConclusion(text: string): string {
  const match = /"conclusion"\s*:\s*"((?:[^"\\]|\\.)*)("?)/.exec(text);
  if (!match) return "";
  const value = decodeJsonFragment(match[1]).trim();
  if (!value) return "";
  return match[2] ? value : `${value}…`;
}

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
    // Backend summaries are length-capped, so structured payloads often arrive
    // truncated and unparsable; fall back to the readable conclusion slice.
    const conclusion = truncatedConclusion(text);
    if (conclusion) return conclusion;
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
