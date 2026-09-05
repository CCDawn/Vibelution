import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import type { WorkflowCanvasProjection } from "../../../api/types/researchWorkflow";
import type { WorkflowEventEnvelope } from "../../../api/types/research-workflow/events";
import { VEmptyState, VErrorSummary, VPanelHeader, VSurface } from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import { buildResearchTimelineGroups } from "./researchWorkflowTimelineModel";
import { ResearchWorkflowInsightsPanel } from "./ResearchWorkflowInsightsPanel";
import { ResearchCriticalPathPanel } from "./ResearchCriticalPathPanel";
import type { ResearchWorkflowInsights } from "./useResearchWorkflowInsights";
import { RUN_TIMELINE_TERM } from "./researchTerminology";
import styles from "./ResearchRunTimeline.styles";

export function ResearchRunTimeline(props: {
  run: WorkflowRunRecord | null;
  projection: WorkflowCanvasProjection | null;
  insights: ResearchWorkflowInsights;
}) {
  const { lang } = useShellI18n();
  const isZh = lang === "zh";
  const groups = buildResearchTimelineGroups(
    (props.run?.events ?? []) as WorkflowEventEnvelope[],
    {
      nodeRuns: props.projection?.run.nodeRuns,
      blockedReason: props.projection?.run.blockedReason ?? props.run?.blockedReason,
    },
  );
  return (
    <div className={styles.root}>
      <ResearchCriticalPathPanel projection={props.projection} insights={props.insights} lang={lang} />
      <ResearchWorkflowInsightsPanel insights={props.insights} lang={lang} />
      <VSurface tone="panel" className={styles.surface}>
        <VPanelHeader title={isZh ? RUN_TIMELINE_TERM.zh : RUN_TIMELINE_TERM.en} headingLevel={3} />
        {groups.length ? (
          <ol className={styles.groups}>
            {groups.map((group) => (
              <li key={group.key}>
                <h4 className={styles.groupTitle}>{group.title}</h4>
                <ul className={styles.items}>
                  {group.items.map((item) => (
                    <li key={item.key} className={styles.item}>
                      {item.details ? <VErrorSummary label={isZh ? "事件详情" : "Event details"} summary={item.label} details={item.details} openLabel={isZh ? "诊断详情" : "Details"} closeLabel={isZh ? "收起详情" : "Hide details"} defaultOpen={false} /> : <span>{item.label}</span>}
                      <time className={styles.status} dateTime={item.occurredAt || undefined}>
                        {item.occurredAt ? new Date(item.occurredAt).toLocaleString(isZh ? "zh-CN" : "en-US", { hour12: false }) : (isZh ? "当前状态快照 · 无事件时间" : "Current snapshot · no event time")}
                      </time>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        ) : (
          <VEmptyState title={isZh ? "暂无运行事件" : "No run events yet"} className={styles.empty} />
        )}
      </VSurface>
    </div>
  );
}
