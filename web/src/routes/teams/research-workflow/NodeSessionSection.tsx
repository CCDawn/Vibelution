import type {
  NodeSessionAnchor,
  ResearchWorkflowNodeDetail,
  ScopedSessionAnchor,
} from "../../../api/types/research-workflow/core";
import { VRouteLinkButton } from "../../../components/vui";
import styles from "./NodeSessionSection.styles";

function sessionLink(anchor: Pick<NodeSessionAnchor, "chatDeepLink" | "chatRoute">): string {
  for (const candidate of [anchor.chatDeepLink, anchor.chatRoute]) {
    const link = typeof candidate === "string" ? candidate.trim() : "";
    if (link) return link;
  }
  return "";
}

function childCanOpen(anchor: ScopedSessionAnchor): boolean {
  return Boolean(
    anchor.sessionId
    && sessionLink(anchor)
    && anchor.sessionAnchorDegraded === false,
  );
}

function childActionLabel(status: string | null | undefined): string {
  const normalized = String(status || "").trim().toLowerCase();
  if (["failed", "blocked", "cancelled", "timed_out", "timeout", "expired"].includes(normalized)) {
    return "查看失败上下文";
  }
  return ["succeeded", "completed", "closed"].includes(normalized)
    ? "查看记录"
    : "继续讨论";
}

function ChildSession({ anchor }: { anchor: ScopedSessionAnchor }) {
  const link = sessionLink(anchor);
  const canOpen = childCanOpen(anchor);
  return (
    <article className={styles.child} data-vui="candidate-session">
      <div className={styles.childHeader}>
        <strong className={styles.candidate}>候选 {anchor.candidateId || "—"}</strong>
        <span className={styles.status}>{anchor.status || "—"}</span>
      </div>
      <dl className={styles.details} data-vui="candidate-session-anchor">
        <dt className={styles.label}>状态</dt><dd className={styles.value}>{anchor.status || "—"}</dd>
        <dt className={styles.label}>attempt</dt><dd className={styles.value}>{anchor.sessionAttempt ?? "—"}</dd>
        <dt className={styles.label}>会话</dt><dd className={styles.valueBreak}>{anchor.sessionId || "—"}</dd>
        {anchor.taskId ? <><dt className={styles.label}>任务</dt><dd className={styles.valueBreak}>{anchor.taskId}</dd></> : null}
        <dt className={styles.label}>fragment</dt><dd className={styles.valueBreak}>{anchor.fragmentRef || "未就绪"}</dd>
      </dl>
      {canOpen ? (
        <VRouteLinkButton className={styles.action} to={link} variant="ghost">
          {childActionLabel(anchor.status)}
        </VRouteLinkButton>
      ) : (
        <div className={styles.degraded} role="status">会话链接暂不可用</div>
      )}
    </article>
  );
}

export function NodeSessionSection({ detail }: { detail: ResearchWorkflowNodeDetail }) {
  const childSessions = detail.scopedSessions ?? [];
  const legacyRoot = childSessions.length === 0 ? {
      sessionId: detail.sessionId,
      taskId: detail.taskId,
      turnId: detail.turnId,
      sessionAttempt: detail.sessionAttempt,
      status: detail.status,
      chatDeepLink: detail.chatDeepLink,
      sessionAnchorDegraded: detail.sessionAnchorDegraded,
    } : null;
  const root = detail.rootSession ?? legacyRoot;
  const rootLink = root ? sessionLink(root) : "";
  const canOpen = Boolean(
    root?.sessionId
    && rootLink
    && root.sessionAnchorDegraded === false,
  );
  const failedCandidateIds = childSessions
    .filter((anchor) => String(anchor.status || "").trim().toLowerCase() === "failed")
    .map((anchor) => anchor.candidateId)
    .filter(Boolean);
  return (
    <section data-vui="node-session-section">
      <h4 className={styles.title}>会话</h4>
      {root?.sessionId ? (
        <article className={styles.rootSession} data-vui="node-root-session">
          <h5 className={styles.subtitle}>节点根会话</h5>
          <dl className={styles.details} data-vui="session-anchor">
            <dt className={styles.label}>会话</dt><dd className={styles.valueBreak}>{root.sessionId}</dd>
            <dt className={styles.label}>状态</dt><dd className={styles.value}>{root.status || "—"}</dd>
            {root.taskId ? <><dt className={styles.label}>任务</dt><dd className={styles.valueBreak}>{root.taskId}</dd></> : null}
            {root.turnId ? <><dt className={styles.label}>轮次</dt><dd className={styles.valueBreak}>{root.turnId}</dd></> : null}
            {root.sessionAttempt != null ? <><dt className={styles.label}>attempt</dt><dd className={styles.value}>{root.sessionAttempt}</dd></> : null}
          </dl>
          {canOpen ? (
            <VRouteLinkButton className={styles.action} to={rootLink} variant="ghost">查看节点总览</VRouteLinkButton>
          ) : (
            <div className={styles.degraded} role="status">会话链接暂不可用</div>
          )}
        </article>
      ) : (
        <div className={styles.empty} data-vui="node-root-session-empty">未绑定节点根会话</div>
      )}
      {childSessions.length ? (
        <div className={styles.children} data-vui="candidate-child-sessions">
          <h5 className={styles.subtitle}>候选子会话（Child Sessions）</h5>
          {failedCandidateIds.length ? (
            <p className={styles.retryNote} role="status">
              节点重试仅处理失败候选 {failedCandidateIds.join("、")}，已完成候选不会重跑。
            </p>
          ) : null}
          <div className={styles.childList}>
            {childSessions.map((anchor, index) => (
              <ChildSession key={`${anchor.candidateId || "candidate"}-${anchor.sessionId || index}-${anchor.sessionAttempt ?? 0}`} anchor={anchor} />
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
