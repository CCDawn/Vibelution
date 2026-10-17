import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import { fetchPersonalAssistantOverview } from "../../api/personalAssistant";
import { queryKeys } from "../../api/queryKeys";
import { VButton, VIconButton, VRouteLinkButton, VStateSurface } from "../../components/vui";
import { assistantStatusLabel } from "./personalAssistantModel";
import styles from "./PersonalAssistant.styles";

export function PersonalAssistantOverview({ onOpenSession, desktop = false, showTitles = true, headerAction }: {
  onOpenSession: (sessionId: string) => void; desktop?: boolean; showTitles?: boolean;
  headerAction?: ReactNode;
}) {
  const overview = useQuery({ queryKey: queryKeys.personalAssistantOverview(),
    queryFn: ({ signal }) => fetchPersonalAssistantOverview({ signal }), refetchInterval: 5_000,
    refetchIntervalInBackground: false, retry: 1 });
  const data = overview.data;
  return <section className={styles.overview} aria-label="平台概览">
    <div className={styles.sectionHeader}><h2>平台概览</h2><div className={styles.overviewHeaderActions}><VIconButton label="刷新平台概览" icon={<RefreshCw size={14} />}
      isDisabled={overview.isFetching} onClick={() => void overview.refetch()} />{headerAction}</div></div>
    {overview.isError ? <VStateSurface density="compact" tone="error" title="平台状态读取失败">{overview.error.message}</VStateSurface>
      : overview.isPending ? <VStateSurface density="compact" tone="loading" busy skeletonLines title="正在读取平台状态" />
      : data ? <>
        <dl className={styles.metrics}>{([
          ["智能体", data.counts.agents], ["会话", data.counts.sessions], ["运行中", data.counts.running],
          ["待确认", data.counts.waiting], ["异常", data.counts.failed],
        ] as const).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
        <p className={styles.caption}>更新于 {data.generatedAt ? new Date(data.generatedAt).toLocaleTimeString() : "—"}</p>
        <h3 className={styles.sectionTitle}>需要关注</h3>
        {data.attention.length ? <ul className={styles.list}>{data.attention.map((item, index) => <li key={item.id}>
          {item.sessionId ? <VButton variant="ghost" className={styles.rowButton} onClick={() => onOpenSession(item.sessionId!)}>{showTitles ? item.title : `事项 ${index + 1}`}</VButton> : <span>{showTitles ? item.title : `事项 ${index + 1}`}</span>}
        </li>)}</ul> : <p className={styles.caption}>当前没有待处理事项</p>}
        <h3 className={styles.sectionTitle}>会话状态</h3>
        {data.sessions.length ? <ul className={styles.list}>{data.sessions.map((session, index) => <li key={session.id}>
          <VButton variant="ghost" className={styles.rowButton} onClick={() => onOpenSession(session.id)}>
            <span className="min-w-0 truncate">{showTitles ? session.title || "未命名会话" : `会话 ${index + 1}`}</span><span className={styles.caption}>{assistantStatusLabel(session.currentPhase || session.status)}</span>
          </VButton></li>)}</ul> : <p className={styles.caption}>还没有会话</p>}
        <h3 className={styles.sectionTitle}>智能体</h3>
        <ul className={styles.list}>{data.agents.map((agent, index) => <li key={agent.id} className={styles.agentRow}>
          <span className="min-w-0 truncate">{showTitles ? agent.displayName || agent.id : `智能体 ${index + 1}`}</span><span className={styles.caption}>{assistantStatusLabel(agent.status)}</span>
        </li>)}</ul>
      </> : null}
    {!desktop ? <div className={styles.links}>
      <VRouteLinkButton to="/agents" variant="secondary">智能体管理</VRouteLinkButton>
      <VRouteLinkButton to="/aux" variant="secondary">后台任务</VRouteLinkButton>
      <VRouteLinkButton to="/memory" variant="secondary">记忆管理</VRouteLinkButton>
      <VRouteLinkButton to="/agents/tools" variant="secondary">工具管理</VRouteLinkButton>
      <VRouteLinkButton to="/teams" variant="secondary">团队管理</VRouteLinkButton>
      <VRouteLinkButton to="/memory/knowledge" variant="secondary">知识管理</VRouteLinkButton>
      <VRouteLinkButton to="/config" variant="secondary">配置管理</VRouteLinkButton>
      <VRouteLinkButton to="/logs" variant="secondary">运行诊断</VRouteLinkButton>
    </div> : null}
    <p className={styles.caption}>高风险操作会在原生会话中请求你的确认。</p>
  </section>;
}
