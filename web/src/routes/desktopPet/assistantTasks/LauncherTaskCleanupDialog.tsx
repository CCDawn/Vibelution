import { VButton, VDialog } from "../../../components/vui";
import type { AssistantCleanupDialogState } from "./assistantTaskCleanup";
import styles from "./LauncherTaskCleanupDialog.styles";

export function LauncherTaskCleanupDialog({ state, onClose, onRetry, lang }: {
  state: AssistantCleanupDialogState | null; onClose: () => void; onRetry: () => void; lang: "zh" | "en";
}) {
  if (!state) return null;
  const zh = lang === "zh", pending = state.pending !== null;
  const retryable = Boolean(state.error || state.result?.items.some(item => item.status !== "deleted"));
  const bytes = (value: number) => `${value.toLocaleString(zh ? "zh-CN" : "en-GB")} ${zh ? "字节" : "bytes"}`;
  const resourceName = (kind: string) => {
    const names: Record<string, [string, string]> = {
      shared_team_resources: ["共用团队、会话和成果", "Shared team, sessions and results"],
      source_resources: ["源任务和文件", "Source task and files"],
      shared_runtime_storage: ["共用运行数据", "Shared runtime data"], session_guards: ["会话恢复保护记录", "Session recovery guards"],
      project: ["项目", "Project"], session: ["会话", "Session"], request_tombstone: ["防重复执行记录", "Request replay protection"],
      deduplication_marker: ["防重复执行记录", "Request replay protection"], local_branch: ["本地开发分支", "Local development branch"],
    };
    return names[kind]?.[zh ? 0 : 1] || (zh ? "相关资源" : "Related resource");
  };
  const reason = (value: string) => value === "shared_database_and_git_objects"
    ? zh ? "共享数据库和 Git 对象供其他功能使用。" : "Database and Git objects are shared with other features."
    : value === "native_recovery_and_admission_guards"
      ? zh ? "保留会话恢复与接收所需的保护记录。" : "Session recovery and admission guards are retained." : value;
  return <VDialog open title={pending ? zh ? "正在清理任务" : "Cleaning up tasks" : zh ? "任务清理结果" : "Task cleanup result"}
    description={state.bulk ? zh ? "核验当前助理全部任务，清理已结束事项的记录与可清理文件。" : "Verify all assistant tasks and clean up records and eligible files for ended tasks."
      : state.scope.targets.length > 0 && state.scope.targets.every(target => target.localOnly === true)
        ? zh ? "核验后仅移除本地记录，保留源任务和文件。" : "After verification, remove only the local record and retain the source task and files."
        : zh ? "核验所选任务后清理，实际处理范围以结果为准。" : "Verify the selected task before cleanup. The result reports what was changed."}
    data-vui="launcher-task-cleanup" size="md" onOpenChange={open => { if (!open && !pending) onClose(); }} hideClose={pending}
    footer={<>
      <VButton isDisabled={pending} onClick={onClose}>{zh ? "关闭" : "Close"}</VButton>
      {retryable ? <VButton onClick={onRetry} isDisabled={pending}>{zh ? "重试清理" : "Retry cleanup"}</VButton> : null}
    </>}>
    <div className={styles.cleanupBody}>
      {state.pending === "loading" ? <p role="status">{zh ? "正在收集任务…" : "Collecting tasks…"}</p> : null}
      {state.pending === "execute" ? <p role="status">{zh ? "正在核验并清理…" : "Verifying and cleaning up…"}</p> : null}
      {state.error ? <p role="alert">{zh ? "清理未完成，可重试。" : "Cleanup is incomplete. Retry is available."} {state.error}</p> : null}
      {state.result ? <>
        <p role="status">{state.result.items.length ? <>{zh ? "实际释放 " : "Released "}{bytes(state.result.releasedBytes)}</>
          : zh ? "当前没有可批量清理的已结束任务。" : "There are no ended tasks available for bulk cleanup."}</p>
        {state.result.items.some(item => item.failures.some(failure => failure.code === "cleanup_batch_unconfirmed"))
          ? <p>{zh ? "已发送的请求尚待核对，重试会重新检查任务状态。" : "Sent requests need verification. Retrying checks task state again."}</p> : null}
        <ul className={styles.cleanupList}>{state.result.items.map(item => <li key={item.key} className={styles.cleanupItem}>
          <strong>{state.titles[item.key] || (zh ? "任务" : "Task")}</strong>
          <span>{item.status === "deleted" ? zh ? "已清理" : "Cleaned up" : item.status === "partial"
            ? zh ? "部分清理，可重试" : "Partially cleaned up; retry available" : zh ? "暂不能清理" : "Cannot clean up yet"} · {bytes(item.releasedBytes)}</span>
          {item.retained.map((resource, index) => <p key={index}>{zh ? "保留 " : "Retained "}{resourceName(resource.kind)} — {reason(resource.reason)}</p>)}
          {item.failures.map((failure, index) => <p role="alert" key={index}>{failure.message} ({failure.code})</p>)}
        </li>)}</ul>
      </> : null}
    </div>
  </VDialog>;
}
