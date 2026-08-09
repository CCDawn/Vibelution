import type { WorkflowCanvasProjection } from "../../../api/types/researchWorkflow";
import { VEmptyState, VPanelHeader, VSurface } from "../../../components/vui";
import { buildResearchCriticalPath } from "./researchCriticalPathModel";
import type { ResearchWorkflowInsights } from "./useResearchWorkflowInsights";
import styles from "./ResearchCriticalPathPanel.styles";

export function ResearchCriticalPathPanel(props: {
  projection: WorkflowCanvasProjection | null;
  insights: ResearchWorkflowInsights;
}) {
  const path = props.projection
    ? buildResearchCriticalPath(
        props.projection.definition,
        props.insights.handoffs?.handoffs ?? [],
        props.projection.run.runtimeCurrentNodeIds,
      )
    : [];
  return (
    <VSurface tone="panel" className={styles.root} data-vui="research-critical-path">
      <VPanelHeader title="当前关键路径" headingLevel={3} />
      {path.length ? (
        <ol className={styles.list}>
          {path.map((item, index) => (
            <li key={item.nodeId} className={styles.item}>
              {index ? <span className={styles.arrow}>→ </span> : null}{item.label}
            </li>
          ))}
        </ol>
      ) : <VEmptyState title="暂无已确认路径" />}
    </VSurface>
  );
}
