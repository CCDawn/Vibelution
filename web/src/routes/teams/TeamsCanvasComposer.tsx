/**
 * Organization-canvas primary surface composer — keeps TeamsRoute canvas branch thin.
 * Shell rail stays owned by the route; this owns canvas + inspector layout only.
 */
import type { ReactNode } from "react";
import { AlertTriangle, Eye } from "lucide-react";
import { TeamWorkspaceFrame } from "./TeamWorkspaceFrame";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";

export type TeamsCanvasComposerProps = {
  className?: string;
  layoutId?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  resize: any;
  ariaLabel: string;
  title: string;
  responsiveRailLabel?: string;
  rail: ReactNode;
  teamSwitcher?: ReactNode;
  toolbar: ReactNode;
  canvas: ReactNode;
  /**
   * Optional research strip stacked above the org canvas.
   * Status / next-step now live in the left rail; keep this slot for compatibility.
   */
  researchFlowSlot?: ReactNode;
  inspectorTitle: string;
  inspectorBody: ReactNode;
  researchWorkflowTeamSelected?: boolean;
  researchCanvasReadOnly?: boolean;
  /** Hide right inspector only when the caller explicitly opts out. */
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
  responsiveRailLabel = "Team list",
  rail,
  teamSwitcher,
  toolbar,
  canvas,
  researchFlowSlot = null,
  inspectorTitle,
  inspectorBody,
  researchCanvasReadOnly = false,
  hideInspector = false,
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
    <TeamWorkspaceFrame
      className={className}
      hideHeader
      domainRecipe="teams-organization-workbench"
      layoutId={layoutId}
      resize={resize}
      shellTestId="team-shell-workspace"
      shellMode="canvas"
      ariaLabel={ariaLabel}
      title={title}
      responsive={{
        enabled: true,
        rail: { label: responsiveRailLabel },
        inspector: { label: inspectorTitle },
      }}
      rail={rail}
      railTitle={teamSwitcher}
      railLabel={responsiveRailLabel}
      toolbar={toolbar}
      canvas={canvasBody}
      inspectorTitle={inspectorTitle}
      inspectorActions={!validationValid ? <AlertTriangle size={16} aria-label="画布校验异常" /> : researchCanvasReadOnly ? <Eye size={16} aria-label="只读画布" /> : undefined}
      inspector={hideInspector ? undefined : <div data-vui-region="teams-inspector" data-composer="teams-canvas">{inspectorBody}</div>}
    />
  );
}
