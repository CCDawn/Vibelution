import type { ReactNode } from "react";
import { VCanvasWorkbenchPage, VPanel, VPanelHeader, type VCanvasWorkbenchPageProps } from "../../components/vui";

type TeamWorkspacePanelProps = {
  title: ReactNode;
  label: string;
  children: ReactNode;
  actions?: ReactNode;
  scroll?: boolean;
  region: "navigation" | "content" | "inspector";
};

function TeamWorkspacePanel({ title, label, children, actions, scroll = true, region }: TeamWorkspacePanelProps) {
  return <VPanel ariaLabel={label} className="flex h-full min-h-0 min-w-0 flex-1 flex-col gap-0 overflow-hidden [--shell-surface:var(--vui-surface-chat)] [--vui-surface-panel:var(--vui-surface-chat)] [--vui-surface-workspace:var(--vui-surface-chat)]" data-team-panel={region}>
    <VPanelHeader title={title} headingLevel={region === "navigation" ? null : 2} actions={actions}
      data-vui="team-workspace-panel-header"
      className="h-11 shrink-0 items-center! border-b border-[var(--vui-border-subtle)] px-2 py-0 [&>div:first-child]:shrink-0 [&>div:last-child]:overflow-x-auto [&>div:last-child]:justify-start [&_h2]:whitespace-nowrap [&_h2]:font-medium [&_h2]:leading-6 [&_h2]:[font-size:var(--vui-font-sm)]" />
    <div data-vui="team-workspace-panel-body" className={`flex min-h-0 min-w-0 flex-1 flex-col p-2 ${scroll ? "overflow-auto" : "overflow-hidden"}`}>
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
  const barePane = "!border-0 !rounded-none !bg-transparent !p-0";
  return <VCanvasWorkbenchPage {...props} hideHeader chrome="embedded" title={title}
    className={`!p-3 ${className ?? ""}`}
    workspaceClassName={`[&>[data-vui=split-main]]:mx-2 ${workspaceClassName ?? ""}`}
    railClassName={barePane} canvasClassName={barePane} inspectorClassName={barePane}
    rail={rail || railTitle ? <TeamWorkspacePanel title={railTitle ?? railLabel} label={railLabel} region="navigation">{rail}</TeamWorkspacePanel> : undefined}
    canvas={<TeamWorkspacePanel title={title} label={typeof title === "string" ? title : "团队内容"} region="content" actions={toolbar} scroll={mainScroll}>{canvas}</TeamWorkspacePanel>}
    inspector={inspector ? <TeamWorkspacePanel title={inspectorTitle} label={inspectorTitle} actions={inspectorActions} region="inspector">{inspector}</TeamWorkspacePanel> : undefined}
  />;
}
