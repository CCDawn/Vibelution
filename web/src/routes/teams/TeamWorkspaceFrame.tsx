import type { ReactNode } from "react";
import { VCanvasWorkbenchPage, VPanel, VPanelHeader, type VCanvasWorkbenchPageProps } from "../../components/vui";
import { vuiRailFillClass } from "../../design/vuiSurfaceRecipes";

import styles from "./TeamWorkspaceFrame.styles";

type TeamWorkspacePanelProps = {
  title: ReactNode;
  label: string;
  children: ReactNode;
  actions?: ReactNode;
  scroll?: boolean;
  region: "navigation" | "content" | "inspector";
};

function TeamWorkspacePanel({ title, label, children, actions, scroll = true, region }: TeamWorkspacePanelProps) {
  const surfaceClassName = region === "content"
    ? styles.contentPanel
    : `${vuiRailFillClass} ${styles.railPanel}`;

  return <VPanel ariaLabel={label} className={`${styles.panel} ${surfaceClassName}`} data-team-panel={region}>
    <VPanelHeader title={title} headingLevel={region === "navigation" ? null : 2} actions={actions}
      data-vui="team-workspace-panel-header"
      className={styles.header} />
    <div data-vui="team-workspace-panel-body" className={`${styles.body} ${scroll ? styles.bodyScroll : styles.bodyFixed}`}>
      {children}
    </div>
  </VPanel>;
}

/** Team-owned composition of the shared canvas recipe; business slots keep their existing owners. */
export type TeamWorkspaceFrameProps = VCanvasWorkbenchPageProps & {
  railTitle?: ReactNode;
  railLabel?: string;
  inspectorTitle?: string;
  inspectorActions?: ReactNode;
  mainScroll?: boolean;
};

export function TeamWorkspaceFrame({ title, toolbar, rail, railTitle, railLabel = "团队导航", canvas,
  inspector, inspectorTitle = "详情", inspectorActions, mainScroll = false, className, workspaceClassName, ...props }: TeamWorkspaceFrameProps) {
  return <VCanvasWorkbenchPage {...props} hideHeader chrome="embedded" title={title}
    className={`${styles.page} ${vuiRailFillClass} ${className ?? ""}`}
    workspaceClassName={`${styles.workspace} ${workspaceClassName ?? ""}`}
    railClassName={styles.barePane} canvasClassName={styles.barePane} inspectorClassName={styles.barePane}
    rail={rail || railTitle ? <TeamWorkspacePanel title={railTitle ?? railLabel} label={railLabel} region="navigation">{rail}</TeamWorkspacePanel> : undefined}
    canvas={<TeamWorkspacePanel title={title} label={typeof title === "string" ? title : "团队内容"} region="content" actions={toolbar} scroll={mainScroll}>{canvas}</TeamWorkspacePanel>}
    inspector={inspector ? <TeamWorkspacePanel title={inspectorTitle} label={inspectorTitle} actions={inspectorActions} region="inspector">{inspector}</TeamWorkspacePanel> : undefined}
  />;
}
