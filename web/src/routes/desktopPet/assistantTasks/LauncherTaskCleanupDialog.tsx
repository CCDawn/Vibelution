import { VButton, VDialog } from "../../../components/vui";
import type { AssistantCleanupDialogState } from "./assistantTaskCleanup";
import styles from "./LauncherAssistantTaskCards.styles";

export function LauncherTaskCleanupDialog({ state, onClose, onConfirm, onRetry, lang }: {
  state: AssistantCleanupDialogState | null; onClose: () => void; onConfirm: () => void; onRetry: () => void; lang: "zh" | "en";
}) {
  if (!state) return null;
  const zh = lang === "zh", pending = state.pending !== null;
  const ready = state.preview?.items.some(item => item.status === "ready") === true;
  const retryable = Boolean(state.error || state.result?.items.some(item => item.status !== "deleted") || state.preview?.items.some(item => item.status === "blocked"));
  const bytes = (value: number) => `${value.toLocaleString(lang === "zh" ? "zh-CN" : "en-GB")} ${zh ? "字节" : "bytes"}`;
  const resourceName = (kind: string) => {
    const names: Record<string, [string, string]> = {
      launcher_task_record: ["助理任务记录", "Assistant task record"], task_record: ["原生任务记录", "Native task record"],
      task_files: ["任务文件", "Task files"], session_files: ["独占会话文件", "Exclusive session files"], workspace: ["任务工作目录", "Task workspace"],
      shared_team_resources: ["共用团队、会话和成果", "Shared team, sessions and results"], shared_runtime_storage: ["共用运行数据", "Shared runtime data"],
      session_guards: ["会话恢复保护记录", "Session recovery guards"], project: ["项目", "Project"], session: ["会话", "Session"],
      request_tombstone: ["防重复执行记录", "Request replay protection"], deduplication_marker: ["防重复执行记录", "Request replay protection"],
      local_branch: ["本地开发分支", "Local development branch"],
    };
    return names[kind]?.[zh ? 0 : 1] || (zh ? "相关资源" : "Related resource");
  };
  const reason = (value: string) => value === "shared_database_and_git_objects" ? zh ? "共享数据库和 Git 对象供其他功能使用。" : "Database and Git objects are shared with other features."
    : value === "native_recovery_and_admission_guards" ? zh ? "保留会话恢复与接收所需的保护记录。" : "Session recovery and admission guards are retained." : value;
  return <VDialog open title={state.result ? zh ? "任务清理结果" : "Task cleanup result" : state.bulk ? zh ? "清理已完成" : "Clean up completed" : zh ? "删除任务" : "Delete task"}
    description={zh ? "永久删除所列任务的可清理记录与文件，无法恢复。共享资源和仍被引用的内容会保留。" : "Permanently delete the listed task records and eligible files. Shared or referenced content is retained."}
    size="md" onOpenChange={open => { if (!open && state.pending !== "execute") onClose(); }} hideClose={state.pending === "execute"}
    footer={<>
      <VButton isDisabled={state.pending === "execute"} onClick={onClose}>{state.result ? zh ? "关闭" : "Close" : zh ? "取消" : "Cancel"}</VButton>
      {retryable ? <VButton onClick={onRetry} isDisabled={pending}>{zh ? "重新预览后重试" : "Preview again to retry"}</VButton> : null}
      {!state.result ? <VButton variant="danger" isDisabled={pending || !ready} isPending={state.pending === "execute"}
        onClick={onConfirm}>{zh ? "永久删除" : "Permanently delete"}</VButton> : null}
    </>}>
    <div className={styles.cleanupBody}>
      {state.bulk ? <p>{zh ? "范围：当前已加载且执行成功结束的任务和团队运行，以及此前已确认删除但清理未完成的记录。执行已结束，不代表业务已验收。" : "Scope: loaded successful task and team endings, plus previously confirmed incomplete cleanup. Business acceptance is still pending."}</p> : null}
      {state.pending === "preview" ? <p role="status">{zh ? "正在读取真实清理范围…" : "Reading the actual cleanup scope…"}</p> : null}
      {state.pending === "execute" ? <p role="status">{zh ? "正在永久删除…" : "Permanently deleting…"}</p> : null}
      {state.error ? <p role="alert">{zh ? "清理未获确认，记录可能仍在。请重新预览后重试。" : "Cleanup was not confirmed. Records may remain; preview again to retry."} {state.error}</p> : null}
      {state.preview ? <>
        <p>{zh ? "预计释放：" : "Estimated release: "}{bytes(state.preview.estimatedBytes)}</p>
        <ul className={styles.cleanupList}>{state.preview.items.map(item => <li key={item.key} className={styles.cleanupItem}>
          <strong>{state.titles[item.key] || item.title || (zh ? "未命名任务" : "Untitled task")}</strong>
          <span>{item.status === "blocked" ? zh ? "暂不能删除" : "Cannot delete" : zh ? "可删除" : "Ready to delete"} · {bytes(item.estimatedBytes)}</span>
          {item.reason ? <p>{reason(item.reason)}</p> : null}
          {item.resources.map((resource, index) => <p key={index}>{resourceName(resource.kind)} · {resource.count} · {bytes(resource.bytes)}</p>)}
          {item.retained.map((resource, index) => <p key={index}>{zh ? "保留" : "Retained"}：{resourceName(resource.kind)} — {reason(resource.reason)}</p>)}
        </li>)}</ul>
      </> : null}
      {state.result ? <>
        <p role="status">{zh ? "实际释放：" : "Actually released: "}{bytes(state.result.releasedBytes)}</p>
        {state.result.items.some(item => item.failures.some(failure => failure.code === "cleanup_batch_unconfirmed"))
          ? <p>{zh ? "字节仅包含已确认的结果；未确认的部分请重新预览核对。" : "Bytes include confirmed results only. Preview unconfirmed items again to check their state."}</p> : null}
        <ul className={styles.cleanupList}>{state.result.items.map(item => <li key={item.key} className={styles.cleanupItem}>
          <strong>{state.titles[item.key] || (zh ? "任务" : "Task")}</strong>
          <span>{item.status === "deleted" ? zh ? "已删除" : "Deleted" : item.status === "partial" ? zh ? "部分删除，可重试" : "Partially deleted; retry available" : zh ? "未删除，可重新预览" : "Not deleted; preview again"} · {bytes(item.releasedBytes)}</span>
          {item.retained.map((resource, index) => <p key={index}>{zh ? "保留" : "Retained"}：{resourceName(resource.kind)} — {reason(resource.reason)}</p>)}
          {item.failures.map((failure, index) => <p role="alert" key={index}>{failure.message} ({failure.code})</p>)}
        </li>)}</ul>
      </> : null}
    </div>
  </VDialog>;
}
