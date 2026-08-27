import { launcherRouteStyles } from "./LauncherRoute.styles";

/**
 * LauncherToolsRoute owns this style module so the tools surface does not
 * import the parent LauncherRoute.styles directly (vuiImportBoundary gate).
 * Keys are composed from the shared Launcher route vocabulary, keeping the
 * rendered classes identical to the previous direct import.
 */
export const launcherToolsRouteStyles = {
  route: launcherRouteStyles.route,
  routeBody: launcherRouteStyles.routeBody,
  workspace: launcherRouteStyles.workspace,
  toolsPageHeader: launcherRouteStyles.toolsPageHeader,
  toolsPageTitle: launcherRouteStyles.toolsPageTitle,
  toolsPageHint: launcherRouteStyles.toolsPageHint,
  toolsWorkspace: launcherRouteStyles.toolsWorkspace,
  notice: launcherRouteStyles.notice,
  panelEyebrow: launcherRouteStyles.panelEyebrow,
} as const;
