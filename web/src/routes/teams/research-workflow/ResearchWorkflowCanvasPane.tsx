import { memo } from "react";

import type { WorkflowLayoutInput } from "../../../components/vui";
import { VStateSurface, VWorkflowCanvas } from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import styles from "./ResearchWorkflowCanvasPane.styles";

// Memoized: the canvas subtree is expensive (ELK layout + node rendering) and
// must not re-render on unrelated workspace polls; graph identity is already
// stabilized by useMemo in ResearchProcessWorkspace.
export const ResearchWorkflowCanvasPane = memo(function ResearchWorkflowCanvasPane(props: {
  graph: WorkflowLayoutInput | null;
  selectedNodeId: string | null;
  runtimeCurrentNodeIds: string[];
  /** Hypothesis-first current task, independent from the formal run cursor. */
  currentTaskNodeId?: string | null;
  error: string | null;
  onSelectNode: (nodeId: string | null) => void;
}) {
  const { lang } = useShellI18n();
  const currentNodeIds = resolveCanvasCurrentNodeIds(
    props.runtimeCurrentNodeIds,
    props.currentTaskNodeId,
  );
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
            runtimeCurrentNodeIds={currentNodeIds}
            onSelectNode={props.onSelectNode}
            height="100%"
            className={styles.canvas}
            layoutMode="serpentine"
            showMiniMap
            showLegend={false}
          />
        ) : (
          <VStateSurface
            tone="loading"
            title={lang === "zh" ? "加载流程定义" : "Loading workflow definition"}
            fill
            className={styles.loading}
          />
        )}
      </div>
    </div>
  );
});

/**
 * Keep the formal runtime cursor and the hypothesis-first task cursor as two
 * inputs while presenting one current marker to the canvas renderer. The
 * hypothesis-first task owns the marker whenever it exists; the formal cursor
 * is only a fallback for a converged workflow. Selection remains a separate
 * prop and is never inferred from this list.
 */
export function resolveCanvasCurrentNodeIds(
  runtimeCurrentNodeIds: readonly string[] | null | undefined,
  currentTaskNodeId?: string | null,
): string[] {
  const taskId = currentTaskNodeId?.trim();
  if (taskId) return [taskId];
  return [...(runtimeCurrentNodeIds ?? [])];
}
