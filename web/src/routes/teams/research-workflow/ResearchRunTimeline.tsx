import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import type { WorkflowCanvasProjection } from "../../../api/types/researchWorkflow";
import { VEmptyState, VPanelHeader, VSurface } from "../../../components/vui";
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
  const groups = buildResearchTimelineGroups(props.run?.events);
  return (
    <div className={styles.root}>
      <ResearchCriticalPathPanel projection={props.projection} insights={props.insights} />
      <ResearchWorkflowInsightsPanel insights={props.insights} />
      <VSurface tone="panel" className={styles.surface}>
        <VPanelHeader title="运行时间线" headingLevel={3} />
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
                        {item.status || "完成"}
                      </span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        ) : (
          <VEmptyState title="暂无运行事件" className={styles.empty} />
        )}
      </VSurface>
    </div>
  );
}
