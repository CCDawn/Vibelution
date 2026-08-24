import { useReactFlow } from "@xyflow/react";
import { Focus, LayoutDashboard, Lock, Maximize2, Minus, MoreHorizontal, Plus, Undo2, Unlock } from "lucide-react";

import { ShadcnDropdownMenu } from "../ShadcnDropdownMenu";
import { resolveWorkflowNodeFocusCenter } from "./workflowSelectionFocus";

export type WorkflowCanvasControlsProps = {
  runtimeCurrentNodeIds?: string[];
  onFitAll?: () => void;
  onFocusCurrent?: () => void;
  manualLayoutPresentation?: "inline" | "menu";
  manualLayout?: {
    canUndo: boolean;
    locked: boolean;
    onAutoArrange: () => void;
    onUndo: () => void;
    onToggleLock: () => void;
  };
};

export function WorkflowCanvasControls({
  runtimeCurrentNodeIds = [],
  onFitAll,
  onFocusCurrent,
  manualLayoutPresentation = "inline",
  manualLayout,
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
    const { x, y } = resolveWorkflowNodeFocusCenter(node, getNode);
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
      {manualLayout && manualLayoutPresentation === "menu" ? (
        <>
          <span className="mx-0.5 my-1 w-px bg-[var(--vui-border-subtle)]" aria-hidden />
          <ShadcnDropdownMenu
            aria-label="布局操作"
            side="top"
            align="start"
            items={[
              { id: "auto-arrange", label: "自动整理", icon: <LayoutDashboard className="h-4 w-4" />, onSelect: manualLayout.onAutoArrange },
              { id: "undo", label: "撤销布局调整", icon: <Undo2 className="h-4 w-4" />, disabled: !manualLayout.canUndo, onSelect: manualLayout.onUndo },
              {
                id: "lock",
                label: manualLayout.locked ? "解锁布局" : "锁定布局",
                icon: manualLayout.locked ? <Lock className="h-4 w-4" /> : <Unlock className="h-4 w-4" />,
                onSelect: manualLayout.onToggleLock,
              },
            ]}
            trigger={(
              <button type="button" className={btn} aria-label="布局操作" title="布局">
                <MoreHorizontal className="h-4 w-4" aria-hidden />
              </button>
            )}
          />
        </>
      ) : manualLayout ? (
        <>
          <span className="mx-0.5 my-1 w-px bg-[var(--vui-border-subtle)]" aria-hidden />
          <button
            type="button"
            className={btn}
            aria-label="自动整理画布"
            title="自动整理"
            onClick={manualLayout.onAutoArrange}
          >
            <LayoutDashboard className="h-4 w-4" aria-hidden />
          </button>
          <button
            type="button"
            className={btn}
            aria-label="撤销布局调整"
            title="撤销布局调整"
            onClick={manualLayout.onUndo}
            disabled={!manualLayout.canUndo}
          >
            <Undo2 className="h-4 w-4" aria-hidden />
          </button>
          <button
            type="button"
            className={btn}
            aria-label={manualLayout.locked ? "解锁布局" : "锁定布局"}
            aria-pressed={manualLayout.locked}
            title={manualLayout.locked ? "解锁布局" : "锁定布局"}
            onClick={manualLayout.onToggleLock}
          >
            {manualLayout.locked ? <Lock className="h-4 w-4" aria-hidden /> : <Unlock className="h-4 w-4" aria-hidden />}
          </button>
        </>
      ) : null}
    </div>
  );
}
