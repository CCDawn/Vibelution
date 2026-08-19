import type { WorkflowCanvasProjection } from "../../../api/types/researchWorkflow";
import { VEmptyState, VPanelHeader, VSurface } from "../../../components/vui";
import { buildResearchCriticalPath } from "./researchCriticalPathModel";
import type { ResearchWorkflowInsights } from "./useResearchWorkflowInsights";
import styles from "./ResearchCriticalPathPanel.styles";

export function ResearchCriticalPathPanel(props: {
  projection: WorkflowCanvasProjection | null;
  insights: ResearchWorkflowInsights;
  lang?: "zh" | "en";
}) {
  const isZh = props.lang !== "en";
  const path = props.projection
    ? buildResearchCriticalPath(
        props.projection.definition,
        props.insights.handoffs?.handoffs ?? [],
        props.projection.run.runtimeCurrentNodeIds,
      )
    : [];
  return (
    <VSurface tone="panel" className={styles.root} data-vui="research-critical-path">
      <VPanelHeader title={isZh ? "当前关键路径" : "Current critical path"} headingLevel={3} />
      {path.length ? (
        <ol className={styles.list}>
          {path.map((item, index) => (
            <li key={item.nodeId} className={styles.item}>
              {index ? <span className={styles.arrow}>→ </span> : null}{item.label}
            </li>
          ))}
        </ol>
      ) : <VEmptyState title={isZh ? "暂无已确认路径" : "No confirmed path yet"} />}
    </VSurface>
  );
}
