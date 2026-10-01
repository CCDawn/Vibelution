import { describe, expect, it } from "vitest";

import routeSource from "./LauncherToolsRoute.tsx?raw";
import { launcherToolsRouteStyles as routeStyles } from "./LauncherToolsRoute.styles";
import developerPanelSource from "./LauncherDeveloperModePanel.tsx?raw";
import developerPanelStyles from "./LauncherDeveloperModePanel.styles";
import maintenancePanelSource from "./LauncherProjectMaintenancePanel.tsx?raw";
import maintenancePanelStyles from "./LauncherProjectMaintenancePanel.styles";

describe("Launcher tools navigation and density", () => {
  it("routes the shell's diagnostics and maintenance views without leaving the tools route", () => {
    expect(routeSource).toContain('searchParams.get("view") === "maintenance" ? "maintenance" : "diagnostics"');
    expect(routeSource).toContain('data-launcher-tools-view="diagnostics"');
    expect(routeSource).toContain('data-launcher-tools-view="maintenance"');
    expect(routeSource).toContain('id: "processes", label: copy.processTab');
    expect(routeSource).toContain('id: "ports", label: copy.portsTab');
    expect(routeSource).toContain('id: "advanced", label: copy.advancedDiagnostics');
    expect(routeSource).toContain('id: "project", label: copy.projectMaintenanceTab');
    expect(routeSource).toContain('id: "sandbox", label: copy.developerSandboxTab');
  });

  it("keeps tab contents mounted while switching so pending work and unsaved port drafts survive", () => {
    expect(routeSource).toContain('hidden={diagnosticsTab !== "processes"}');
    expect(routeSource).toContain('hidden={diagnosticsTab !== "ports"}');
    expect(routeSource).toContain('hidden={diagnosticsTab !== "advanced"}');
    expect(routeSource).toContain('hidden={maintenanceTab !== "project"}');
    expect(routeSource).toContain('hidden={maintenanceTab !== "sandbox"}');
    expect(routeSource).toContain("const maintenanceApplyMutation = useMutation({");
    expect(routeSource).toContain("const cleanupApplyMutation = useMutation({");
  });

  it("accepts a branch instance from the shell and keeps process selection in sync", () => {
    expect(routeSource).toContain('searchParams.get("instance")?.trim() ?? ""');
    expect(routeSource).toContain("setSelectedInstanceId(requestedInstanceId)");
    expect(routeSource).toContain("selectedId={selectedBranchId}");
  });

  it("sizes maintenance summaries to their contents and de-emphasizes preview actions", () => {
    expect(maintenancePanelSource).toContain("expandToContent");
    expect(developerPanelSource).toContain("expandToContent");
    expect(maintenancePanelSource).toContain("copy.maintenanceEmptyItems");
    expect(developerPanelSource).toContain("copy.developerModeNoiseEmpty");
    expect(maintenancePanelStyles.iconButton).not.toContain("accent-primary");
    expect(maintenancePanelStyles.primaryButton).not.toContain("accent-primary");
    expect(maintenancePanelStyles.primaryButton).not.toContain("bg-");
    expect(developerPanelStyles.primaryButton).not.toContain("accent-primary");
    expect(developerPanelStyles.primaryButton).not.toContain("bg-");
    expect(maintenancePanelStyles.developerGrid).toContain("grid-cols-[minmax(0,1fr)]");
    expect(maintenancePanelStyles.segmentedControl).toContain("w-full");
    expect(maintenancePanelStyles.segmentedControl).toContain("!grid-cols-2");
    expect(developerPanelStyles.developerGrid).toContain("max-[860px]");
  });

  it("uses a branch-sized maintenance heading and avoids a false profile when summary data is empty", () => {
    expect(routeSource).toContain("<h1 className={styles.toolsPageTitle}>{routeHeading}</h1>");
    expect(routeSource).not.toContain("className={styles.panelEyebrow}>{copy.eyebrow}");
    expect(routeStyles.toolsPageHeader).toContain("px-7");
    expect(routeStyles.toolsPageHeader).toContain("pt-4");
    expect(routeStyles.toolsPageTitle).toContain("text-xl");
    expect(maintenancePanelSource).not.toContain("Launcher 维护中心");
    expect(maintenancePanelSource).not.toContain("selectedProfile?.label || copy.maintenanceFactoryRuntime");
    expect(maintenancePanelSource).toContain("copy.maintenanceActiveWorkPolicy");
    expect(maintenancePanelSource).toContain('className="w-full min-w-0"');
  });
});
