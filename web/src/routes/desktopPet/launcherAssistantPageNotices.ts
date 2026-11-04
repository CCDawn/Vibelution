import type { LauncherNotice } from "../../app/LauncherNotifications";

export type LauncherNoticeRead = {
  label: string;
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
  return (error instanceof Error ? error.message : typeof error === "string" ? error : "")
    .replace(/\s+/g, " ").trim().slice(0, 500);
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
    title: zh ? "部分状态未更新" : "Some status is out of date",
    description: zh ? "暂时无法读取最新状态，已保留现有内容。操作是否完成仍需核对。"
      : "The latest status could not be read. Existing content is retained; operation outcomes still need checking.",
    labels: failedReads.map(read => read.label),
    details: failedReads.map(read => `${read.label}: ${diagnostic(read.error) || (zh ? "读取延迟" : "Read delayed")}`).join("\n"),
    actions: [{ id: "refresh", label: zh ? "重新连接" : "Reconnect",
      pending: failedReads.some(read => read.pending),
      run: () => Promise.all(failedReads.map(read => read.retry())) }],
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
