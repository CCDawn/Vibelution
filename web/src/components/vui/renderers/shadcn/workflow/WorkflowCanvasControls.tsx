import { useReactFlow } from "@xyflow/react";
import { Focus, Maximize2, Minus, Plus } from "lucide-react";

export type WorkflowCanvasControlsProps = {
  runtimeCurrentNodeIds?: string[];
  onFitAll?: () => void;
  onFocusCurrent?: () => void;
};

export function WorkflowCanvasControls({
  runtimeCurrentNodeIds = [],
  onFitAll,
  onFocusCurrent,
}: WorkflowCanvasControlsProps) {
  const { zoomIn, zoomOut, fitView, setCenter, getNode } = useReactFlow();

  const fitAll = () => {
    if (onFitAll) {
      onFitAll();
      return;
    }
    void fitView({ padding: 0.1, duration: 200 });
  };

  const focusCurrent = () => {
    const id = runtimeCurrentNodeIds[0];
    if (!id) {
      fitAll();
      onFocusCurrent?.();
      return;
    }
    const node = getNode(id);
    if (!node) {
      fitAll();
      return;
    }
    const w = typeof node.width === "number" ? node.width : 240;
    const h = typeof node.height === "number" ? node.height : 88;
    // Account for parent stage offset when parented.
    let x = node.position.x + w / 2;
    let y = node.position.y + h / 2;
    if (node.parentId) {
      const parent = getNode(node.parentId);
      if (parent) {
        x += parent.position.x;
        y += parent.position.y;
      }
    }
    void setCenter(x, y, { zoom: 1.05, duration: 220 });
    onFocusCurrent?.();
  };

  const btn =
    "inline-flex size-9 items-center justify-center rounded-lg border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_94%,transparent)] text-[var(--fg-secondary)] shadow-sm transition hover:-translate-y-px hover:bg-[var(--vui-control-hover-bg)] disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-cool)]";

  return (
    <div
      className="pointer-events-auto absolute bottom-3 left-3 z-10 flex gap-1 rounded-xl border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_84%,transparent)] p-1 shadow-sm backdrop-blur"
      data-vui="workflow-canvas-controls"
    >
      <button type="button" className={btn} aria-label="放大画布" title="放大" onClick={() => void zoomIn({ duration: 120 })}>
        <Plus className="h-4 w-4" aria-hidden />
      </button>
      <button type="button" className={btn} aria-label="缩小画布" title="缩小" onClick={() => void zoomOut({ duration: 120 })}>
        <Minus className="h-4 w-4" aria-hidden />
      </button>
      <button type="button" className={btn} aria-label="适应全部" title="适应全部流程" onClick={fitAll}>
        <Maximize2 className="h-4 w-4" aria-hidden />
      </button>
      <button
        type="button"
        className={btn}
        aria-label="定位当前工作"
        title="定位当前"
        onClick={focusCurrent}
        disabled={runtimeCurrentNodeIds.length === 0}
      >
        <Focus className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}
