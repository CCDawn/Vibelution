import { launcherRouteStyles } from "./LauncherRoute.styles";

/**
 * LauncherToolsRoute shares the Launcher visual tokens while keeping local
 * layout choices here, so its diagnostics and maintenance views can evolve
 * without changing the main Launcher workbench.
 */
export const launcherToolsRouteStyles = {
  route: launcherRouteStyles.route,
  routeBody: "!flex min-h-0 !flex-col !gap-1.5 !overflow-hidden !p-0",
  workspace: "flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden px-2 pb-2 pt-1",
  toolsPageHeader: "flex min-w-0 shrink-0 items-start gap-3 px-7 pb-3 pt-4 max-[640px]:px-4",
  toolsPageTitle: "m-0 text-xl font-semibold text-vui-fg-primary",
  toolsPageHint: "mb-0 mt-1 text-vui-xs text-vui-fg-secondary",
  toolsWorkspace: "flex min-h-0 min-w-0 flex-1 flex-col gap-1.5 overflow-x-clip overflow-y-auto px-0 pb-2 [scrollbar-gutter:stable]",
  toolsView: "grid min-w-0 gap-1.5",
  toolsTabs: "grid min-w-0 gap-1.5",
  toolsTabList: "w-fit max-w-full",
  toolsTabTrigger: "min-w-0 max-w-full truncate",
  toolsTabPanels: "min-w-0",
  toolsTabPanel: "min-w-0",
  notice: launcherRouteStyles.notice,
  panelEyebrow: launcherRouteStyles.panelEyebrow,
} as const;
