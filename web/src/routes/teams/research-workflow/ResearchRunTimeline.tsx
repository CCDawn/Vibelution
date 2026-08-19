import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import type { WorkflowCanvasProjection } from "../../../api/types/researchWorkflow";
import type { WorkflowEventEnvelope } from "../../../api/types/research-workflow/events";
import { VEmptyState, VPanelHeader, VSurface } from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import { buildResearchTimelineGroups } from "./researchWorkflowTimelineModel";
import { ResearchWorkflowInsightsPanel } from "./ResearchWorkflowInsightsPanel";
import { ResearchCriticalPathPanel } from "./ResearchCriticalPathPanel";
import type { ResearchWorkflowInsights } from "./useResearchWorkflowInsights";
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
        <VPanelHeader title={isZh ? "运行时间线" : "Run timeline"} headingLevel={3} />
        {groups.length ? (
          <ol className={styles.groups}>
            {groups.map((group) => (
              <li key={group.key}>
                <h4 className={styles.groupTitle}>{group.title}</h4>
                <ul className={styles.items}>
                  {group.items.map((item) => (
                    <li key={item.key} className={styles.item}>
                      <span>{item.label}</span>
                      <span className={styles.status} title={item.occurredAt || undefined}>
                        {item.status || (isZh ? "完成" : "Done")}
                      </span>
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
