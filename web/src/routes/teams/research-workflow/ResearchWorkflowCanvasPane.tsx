import { memo, useState } from "react";

import type { WorkflowLayoutInput } from "../../../components/vui";
import { VButton, VErrorSummary, VStateSurface, VWorkflowCanvas } from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import styles from "./ResearchWorkflowCanvasPane.styles";
import { presentResearchWorkflowError } from "../researchWorkflowErrorModel";

// Memoized: the canvas subtree is expensive (ELK layout + node rendering) and
// must not re-render on unrelated workspace polls; graph identity is already
// stabilized by useMemo in ResearchProcessWorkspace.
export const ResearchWorkflowCanvasPane = memo(function ResearchWorkflowCanvasPane(props: {
  graph: WorkflowLayoutInput | null;
  unavailableMessage?: string;
  selectedNodeId: string | null;
  runtimeCurrentNodeIds: string[];
  /** Hypothesis-first current task, independent from the formal run cursor. */
  currentTaskNodeId?: string | null;
  error: string | null;
  onSelectNode: (nodeId: string | null) => void;
}) {
  const { lang } = useShellI18n();
  const [viewMode, setViewMode] = useState<"stage" | "canvas">("stage");
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
        <VErrorSummary
          className={styles.error}
          label={lang === "zh" ? presentResearchWorkflowError(props.error).titleZh : presentResearchWorkflowError(props.error).titleEn}
          summary={lang === "zh" ? presentResearchWorkflowError(props.error).bodyZh : presentResearchWorkflowError(props.error).bodyEn}
          details={props.error}
          defaultOpen={false}
        />
      ) : null}
      {props.graph ? <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[var(--vui-border-subtle)] p-2" aria-label="画布展示范围">
        <VButton density="compact" variant={viewMode === "stage" ? "primary" : "secondary"} aria-pressed={viewMode === "stage"} onClick={() => setViewMode("stage")}>阶段聚焦</VButton>
        <VButton density="compact" variant={viewMode === "canvas" ? "primary" : "secondary"} aria-pressed={viewMode === "canvas"} onClick={() => setViewMode("canvas")}>全流程</VButton>
        <VButton density="compact" variant="secondary" isDisabled={!props.currentTaskNodeId} onClick={() => { setViewMode("stage"); props.onSelectNode(props.currentTaskNodeId ?? null); }}>定位当前任务</VButton>
      </div> : null}
      <div className={styles.stage}>
        {props.graph ? (
          <VWorkflowCanvas
            graph={props.graph}
            viewMode={viewMode}
            selectedNodeId={props.selectedNodeId}
            runtimeCurrentNodeIds={currentNodeIds}
            onSelectNode={props.onSelectNode}
            height="100%"
            className={styles.canvas}
            layoutMode="serpentine"
            compactControls
            showMiniMap
            showLegend={false}
          />
        ) : (
          <VStateSurface
            tone={props.error ? "error" : "loading"}
            title={props.unavailableMessage ?? (props.error
              ? (lang === "zh" ? "流程定义无法读取" : "Workflow definition unavailable")
              : (lang === "zh" ? "加载流程定义" : "Loading workflow definition"))}
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
