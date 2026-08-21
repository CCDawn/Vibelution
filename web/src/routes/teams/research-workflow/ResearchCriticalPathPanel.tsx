import type { WorkflowCanvasProjection } from "../../../api/types/researchWorkflow";
import { VEmptyState, VPanelHeader, VStateSurface, VSurface } from "../../../components/vui";
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
  const header = <VPanelHeader title={isZh ? "当前关键路径" : "Current critical path"} headingLevel={3} />;

  if (props.insights.loading) {
    return (
      <VSurface tone="panel" className={styles.root} data-vui="research-critical-path">
        {header}
        <VStateSurface
          tone="loading"
          title={isZh ? "正在加载关键路径" : "Loading critical path"}
          skeletonLines={2}
        />
      </VSurface>
    );
  }

  if (props.insights.error) {
    return (
      <VSurface tone="panel" className={styles.root} data-vui="research-critical-path" role="alert">
        {header}
        <p>{props.insights.error}</p>
      </VSurface>
    );
  }

  return (
    <VSurface tone="panel" className={styles.root} data-vui="research-critical-path">
      {header}
      {path.length ? (
        <ol className={styles.list}>
          {path.map((item, index) => (
            <li key={item.nodeId} className={styles.item}>
              {index ? <span className={styles.arrow}>→ </span> : null}{item.label}
            </li>
          ))}
        </ol>
      ) : <VEmptyState title={isZh ? "关键路径尚未形成" : "Critical path not formed yet"} />}
    </VSurface>
  );
}
