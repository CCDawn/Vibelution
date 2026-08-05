/**
 * Organization-canvas primary surface composer — keeps TeamsRoute canvas branch thin.
 * Shell rail stays owned by the route; this owns canvas + inspector layout only.
 */
import type { ReactNode } from "react";
import { AlertTriangle, Eye, Link2 } from "lucide-react";

import { VCanvasWorkbenchPage } from "../../components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";

export type TeamsCanvasComposerProps = {
  className?: string;
  layoutId?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  resize: any;
  ariaLabel: string;
  title: string;
  rail: ReactNode;
  toolbar: ReactNode;
  canvas: ReactNode;
  /**
   * Research end-user strip (stage rail + next-step CTA) stacked above the org canvas.
   * When set, main column is flow + canvas only.
   */
  researchFlowSlot?: ReactNode;
  inspectorTitle: string;
  inspectorBody: ReactNode;
  researchWorkflowTeamSelected?: boolean;
  researchCanvasReadOnly?: boolean;
  /** Hide right inspector for pure flow+canvas end-user density. */
  hideInspector?: boolean;
  styles: Record<string, string>;
  validationValid?: boolean;
};

export function TeamsCanvasComposer({
  className = "",
  layoutId = WORKBENCH_LAYOUT_IDS.teams,
  resize,
  ariaLabel,
  title,
  rail,
  toolbar,
  canvas,
  researchFlowSlot = null,
  inspectorTitle,
  inspectorBody,
  researchWorkflowTeamSelected = false,
  researchCanvasReadOnly = false,
  hideInspector = false,
  styles,
  validationValid = true,
}: TeamsCanvasComposerProps) {
  const canvasBody = researchFlowSlot ? (
    <div
      className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden"
      data-testid="research-canvas-with-flow"
      data-composer="teams-canvas-flow"
    >
      <div className="min-w-0 shrink-0 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-3 py-2.5">
        {researchFlowSlot}
      </div>
      <div className="min-h-0 min-w-0 flex-1 overflow-hidden">{canvas}</div>
    </div>
  ) : (
    canvas
  );

  return (
    <VCanvasWorkbenchPage
      className={className}
      hideHeader
      domainRecipe="teams-organization-workbench"
      layoutId={layoutId}
      resize={resize}
      shellTestId="team-shell-workspace"
      shellMode="canvas"
      ariaLabel={ariaLabel}
      title={title}
      rail={rail}
      toolbar={toolbar}
      canvasClassName="!border-0 !rounded-none"
      inspectorClassName="!border-0 !rounded-none !bg-transparent"
      canvas={canvasBody}
      inspector={
        hideInspector ? undefined : (
          <aside
            className={[
              styles.inspector,
              researchWorkflowTeamSelected ? styles.researchInspector : "",
              "min-h-0 h-full flex-1 !border-0 !rounded-none",
            ].filter(Boolean).join(" ")}
            data-vui-region="teams-inspector"
            data-composer="teams-canvas"
          >
            <div className={styles.inspectorHeader}>
              <strong>{inspectorTitle}</strong>
              {!validationValid
                ? <AlertTriangle size={16} />
                : researchCanvasReadOnly
                  ? <Eye size={16} />
                  : <Link2 size={16} />}
            </div>
            <div className={styles.inspectorBody}>
              {inspectorBody}
            </div>
          </aside>
        )
      }
    />
  );
}
