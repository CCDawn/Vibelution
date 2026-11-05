import type { LauncherNotice, LauncherNoticeFeature } from "../../app/LauncherNotifications";

export type LauncherNoticeRead = {
  label: string;
  feature?: LauncherNoticeFeature;
  failed: boolean;
  pending: boolean;
  error?: unknown;
  retry: () => unknown | Promise<unknown>;
};

/** With no successful data, React Query clears isError while a retry is
 * pending. The existing failure timestamp keeps the notice until settlement. */
export function launcherNoticeReadFailed(query: { isError: boolean; isPending: boolean; errorUpdatedAt: number }): boolean {
  return query.isError || query.isPending && query.errorUpdatedAt > 0;
}

function diagnostic(error: unknown): string {
  const message = (error instanceof Error ? error.message : typeof error === "string" ? error : "")
    .replace(/\s+/g, " ").trim();
  const codes = message.match(/\bASSISTANT_[A-Z][A-Z0-9_]*\b/g);
  return (codes ? [...new Set(codes)].join(", ")
    : message.replace(/^Error invoking remote method\s+(?:'[^']+'|"[^"]+"|[\w.:-]+):\s*(?:Error:\s*)?/, ""))
    .slice(0, 500);
}

/** Group affected reads, without claiming that equal transport errors prove a
 * shared root cause. Each retry calls only the existing read owners. */
export function launcherAssistantPageNotices(input: {
  lang: "zh" | "en";
  reads: LauncherNoticeRead[];
  appearance: LauncherNoticeRead[];
  history?: { missing: boolean; failed: boolean; pending?: boolean; retry: () => unknown; refresh: () => unknown };
  deliveryUnreported?: boolean;
}): LauncherNotice[] {
  const zh = input.lang === "zh";
  const notices: LauncherNotice[] = [];
  const failedReads = input.reads.filter(read => read.failed);
  if (failedReads.length) notices.push({
    id: "assistant-reads", kind: "connection", tone: "warning",
    title: zh ? "聊天没能刷新" : "Chat could not refresh",
    description: zh ? "稍后再试一次。" : "Try again in a moment.",
    labels: failedReads.map(read => read.label),
    features: [...new Set(failedReads.flatMap(read => read.feature ? [read.feature] : []))],
    details: failedReads.map(read => `${read.label}: ${diagnostic(read.error) || (zh ? "读取延迟" : "Read delayed")}`).join("\n"),
    actions: [{ id: "refresh", label: zh ? "再试一次" : "Try again",
      pending: failedReads.some(read => read.pending),
      run: () => Promise.allSettled(failedReads.map(read => Promise.resolve().then(() => read.retry()))) }],
  });
  const failedImages = input.appearance.filter(read => read.failed);
  if (failedImages.length) notices.push({
    id: "assistant-appearance", kind: "appearance", tone: "info",
    title: zh ? "外观图片未加载" : "Appearance images did not load",
    description: zh ? "暂时使用默认外观，不影响聊天。" : "Using the default appearance. Chat is unaffected.",
    labels: failedImages.map(read => read.label),
    details: failedImages.map(read => `${read.label}: ${diagnostic(read.error)}`).filter(line => !line.endsWith(": ")).join("\n") || undefined,
    actions: [{ id: "refresh", label: zh ? "重试" : "Retry", pending: failedImages.some(read => read.pending),
      run: () => Promise.all(failedImages.map(read => read.retry())) }],
  });
  if (input.history?.missing || input.history?.failed) {
    const history = input.history;
    notices.push({
      id: "assistant-history", kind: "history", tone: "warning",
      title: zh ? "部分历史附件暂不可用" : "Some historical attachments are unavailable",
      description: history.missing
        ? zh ? "历史图片缺少附件标识，暂时无法查看。" : "A historical image has no attachment ID and cannot be opened."
        : zh ? "历史附件暂未加载，单个文件上限为 8 MiB。" : "Historical attachments did not load; the per-file limit is 8 MiB.",
      actions: [{ id: "refresh", label: zh ? "重试" : "Retry", pending: history.pending, run: () => {
        if (history.failed) history.retry();
        if (history.missing) return history.refresh();
      } }],
    });
  }
  if (input.deliveryUnreported) notices.push({
    id: "assistant-delivery", kind: "delivery", tone: "warning",
    title: zh ? "部分任务结果暂未汇报" : "Some task results have not been reported",
    description: zh ? "可在对话中让助理核对原任务的状态。" : "Ask the assistant in chat to check the original task status.",
  });
  return notices;
}
