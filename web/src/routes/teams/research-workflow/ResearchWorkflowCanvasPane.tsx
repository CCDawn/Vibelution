import type { WorkflowLayoutInput } from "../../../components/vui";
import { VStateSurface, VWorkflowCanvas } from "../../../components/vui";
import styles from "./ResearchWorkflowCanvasPane.styles";

export function ResearchWorkflowCanvasPane(props: {
  graph: WorkflowLayoutInput | null;
  selectedNodeId: string | null;
  runtimeCurrentNodeIds: string[];
  error: string | null;
  onSelectNode: (nodeId: string | null) => void;
}) {
  return (
    <div
      className={styles.root}
      data-testid="research-process-canvas-host"
      data-composer="research-process-canvas"
    >
      {props.error ? (
        <div
          className={styles.error}
          role="alert"
        >
          {props.error}
        </div>
      ) : null}
      <div className={styles.stage}>
        {props.graph ? (
          <VWorkflowCanvas
            graph={props.graph}
            selectedNodeId={props.selectedNodeId}
            runtimeCurrentNodeIds={props.runtimeCurrentNodeIds}
            onSelectNode={props.onSelectNode}
            height="100%"
            className={styles.canvas}
          />
        ) : (
          <VStateSurface tone="loading" title="加载流程定义" fill className={styles.loading} />
        )}
      </div>
    </div>
  );
}
