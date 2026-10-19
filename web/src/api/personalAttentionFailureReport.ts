import { fetchWithControl } from "./client";

/**
 * Fire-and-forget renderer-side report for human-attention notification
 * delivery failures. The notify ledger is at-most-once per id per day, so a
 * rejected IPC call or an `invalid_payload` result means the user may never
 * see the attention row; this helper tells the backend, which files one
 * `delivery_failure` message into the personal-assistant agent inbox.
 *
 * The report itself is best-effort: in-module dedup per id plus a daily cap
 * keep the channel bounded, and any transport failure is swallowed — the
 * emitter path must never block or throw. The 403 control-token self-heal and
 * failure reporting live in `fetchWithControl` (see browserTelemetry.ts for
 * the buffered-delivery sibling pattern).
 */

export type HumanAttentionDeliveryFailureReport = {
  id: string;
  kind: string;
  severity?: string;
  reason: string;
  title?: string;
};

const REPORT_ENDPOINT = "/api/personal-assistant/attention/report-delivery-failure";
const MAX_REPORTS_PER_DAY = 10;
const MAX_ID_LENGTH = 128;
const MAX_KIND_LENGTH = 40;
const MAX_SEVERITY_LENGTH = 16;
const MAX_REASON_LENGTH = 400;
const MAX_TITLE_LENGTH = 160;

let reportedDay = "";
const reportedIds = new Set<string>();
let reportsToday = 0;

function localDayKey(date: Date): string {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function resetHumanAttentionFailureReporterForTests(): void {
  reportedDay = "";
  reportedIds.clear();
  reportsToday = 0;
}

function clip(value: string | undefined, limit: number): string {
  return String(value ?? "").slice(0, limit);
}

export function reportHumanAttentionDeliveryFailure(
  report: HumanAttentionDeliveryFailureReport,
): void {
  try {
    if (!report || typeof report.id !== "string" || !report.id) {
      return;
    }
    const day = localDayKey(new Date());
    if (day !== reportedDay) {
      reportedDay = day;
      reportedIds.clear();
      reportsToday = 0;
    }
    // 进程内防灌水：当日上限 + 同 id 只报一次（账本已 at-most-once，重复
    // 失败只会来自同一条通知的重复轮询）。
    if (reportsToday >= MAX_REPORTS_PER_DAY || reportedIds.has(report.id)) {
      return;
    }
    reportedIds.add(report.id);
    reportsToday += 1;
    const body = JSON.stringify({
      id: clip(report.id, MAX_ID_LENGTH),
      kind: clip(report.kind, MAX_KIND_LENGTH) || "unknown",
      ...(report.severity ? { severity: clip(report.severity, MAX_SEVERITY_LENGTH) } : {}),
      stage: "renderer",
      reason: clip(report.reason, MAX_REASON_LENGTH),
      ...(report.title ? { title: clip(report.title, MAX_TITLE_LENGTH) } : {}),
    });
    void fetchWithControl(REPORT_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    }).then(
      () => undefined,
      () => undefined,
    );
  } catch {
    // Reporting must never affect the notification path.
  }
}
