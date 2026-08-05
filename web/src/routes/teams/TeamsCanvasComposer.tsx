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
  inspectorTitle: string;
  inspectorBody: ReactNode;
  researchWorkflowTeamSelected?: boolean;
  researchCanvasReadOnly?: boolean;
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
  inspectorTitle,
  inspectorBody,
  researchWorkflowTeamSelected = false,
  researchCanvasReadOnly = false,
  styles,
  validationValid = true,
}: TeamsCanvasComposerProps) {
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
      canvas={canvas}
      inspector={(
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
      )}
    />
  );
}
