import type { FinancialResearchBatchItemStatus, FinancialResearchBatchStatus, FinancialResearchSchedule } from "../../api/financialJobs";

export const MAX_BATCH_SYMBOLS = 10;
export const ACTIVE_FINANCIAL_BATCH_STATUSES = new Set<FinancialResearchBatchStatus>(["queued", "running", "stop_requested"]);

export function parseFinancialBatchSymbols(value: string): { symbols: string[]; invalid: string[] } {
  const tokens = value.trim().split(/[\s,，;；]+/).filter(Boolean);
  const symbols = new Set<string>(), invalid: string[] = [];
  for (const token of tokens) {
    const normalized = normalizeFinancialBatchSymbol(token);
    if (normalized) symbols.add(normalized); else invalid.push(token);
  }
  return { symbols: [...symbols], invalid };
}

function normalizeFinancialBatchSymbol(value: string): string | null {
  const token = String(value || "").trim();
  const cn = /^(?:(sh|sz|bj))?(\d{6})$/i.exec(token);
  if (cn) {
    const code = cn[2];
    const inferred = /^6/.test(code) ? "sh" : /^[03]/.test(code) ? "sz" : /^[489]/.test(code) ? "bj" : "";
    const explicit = cn[1]?.toLowerCase();
    if (!inferred || (explicit && explicit !== inferred)) return null;
    return `${inferred}${code}`;
  }

  const hk = /^hk(\d{1,5})$/i.exec(token);
  if (hk) return `hk${hk[1].padStart(5, "0")}`;

  const us = /^us([a-z][a-z0-9.-]{0,9})$/i.exec(token);
  if (!us) return null;
  let ticker = us[1].toUpperCase();
  for (const suffix of [".NASDAQ", ".NYSE", ".PNK", ".OQ", ".AM", ".PK", ".N"]) {
    if (ticker.endsWith(suffix)) {
      ticker = ticker.slice(0, -suffix.length);
      break;
    }
  }
  return /^[A-Z][A-Z0-9.-]{0,9}$/.test(ticker) ? `us${ticker}` : null;
}

export function financialBatchStatusLabel(status: FinancialResearchBatchStatus | FinancialResearchBatchItemStatus, zh: boolean): string {
  const labels: Record<FinancialResearchBatchStatus | FinancialResearchBatchItemStatus, readonly [string, string]> = {
    queued: ["排队中", "Queued"], running: ["研究中", "Running"], stop_requested: ["正在停止", "Stopping"],
    completed: ["已完成", "Completed"], partial: ["部分完成", "Partial"], failed: ["失败", "Failed"],
    stopped: ["已停止", "Stopped"], blocked: ["需处理", "Needs attention"], preparing: ["准备中", "Preparing"],
    submitting: ["正在提交", "Submitting"], cancelled: ["已停止", "Stopped"], skipped: ["未启动", "Not started"],
  };
  return labels[status]?.[zh ? 0 : 1] ?? (zh ? "状态待核对" : "Check status");
}

export function financialBatchStatusTone(status: FinancialResearchBatchStatus | FinancialResearchBatchItemStatus): "neutral" | "success" | "warning" {
  return status === "completed" ? "success" : ["partial", "failed", "stopped", "blocked", "cancelled", "skipped"].includes(status) ? "warning" : "neutral";
}

export function financialScheduleLabel(schedule: FinancialResearchSchedule, zh: boolean): string {
  const execution = schedule.execution;
  if (execution.kind === "now") return zh ? "立即研究" : "Immediate";
  if (execution.kind === "once") return zh ? "执行一次" : "Once";
  return `${execution.kind === "weekdays" ? (zh ? "周一至五" : "Mon–Fri") : (zh ? "每天" : "Daily")} ${execution.timeOfDay ?? ""}`.trim();
}

export function financialJobTime(value: string | null, zh: boolean): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat(zh ? "zh-CN" : "en-GB", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

/** Input labels say Beijing time, so parsing must not use the browser's own zone. */
export function beijingScheduledTime(value: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null;
  const iso = `${value}:00+08:00`, date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const [year, month, day, hour, minute] = value.match(/\d+/g)!.map(Number);
  const utc = new Date(Date.UTC(year, month - 1, day, hour, minute));
  if (utc.getUTCFullYear() !== year || utc.getUTCMonth() !== month - 1 || utc.getUTCDate() !== day || hour > 23 || minute > 59) return null;
  return iso;
}
