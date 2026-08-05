import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeShellSource = readFileSync(new URL("./TeamsRouteWorkbench.tsx", import.meta.url), "utf8");
const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./buildTeamsWorkbenchResearchSurfacesFromBag.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./createTeamsWorkbenchResearchSurfaces.ts", import.meta.url), "utf8");
const scCompositionSource = readFileSync(new URL("./useTeamsScComposition.ts", import.meta.url), "utf8");
const injectRenderersSource = readFileSync(new URL("./teamSourceCollectionInjectRenderers.tsx", import.meta.url), "utf8");
const researchSurfacesSource = readFileSync(new URL("./createTeamsResearchSurfaces.ts", import.meta.url), "utf8");
const routeSource = [routeShellSource, routeModelSource, scCompositionSource, injectRenderersSource, researchSurfacesSource].join("\n");

const injectSource = readFileSync(new URL("./teamSourceCollectionInjectRenderers.tsx", import.meta.url), "utf8");
const shellSource = readFileSync(new URL("./TeamSourceCollectionSearchBriefShell.tsx", import.meta.url), "utf8");
const workspaceSource = readFileSync(new URL("./source-collection/ui/TeamSourceCollectionActiveStageWorkspacePanel.tsx", import.meta.url), "utf8");
const storageSource = readFileSync(new URL("./TeamSourceCollectionStorageActionsInject.tsx", import.meta.url), "utf8");

describe("SC inject shell extraction contract", () => {
  it("inject factory mounts search-brief shell; route keeps no reset chrome", () => {
    expect(injectSource).toContain("TeamSourceCollectionSearchBriefShell");
    expect(injectSource).toContain("TeamSourceCollectionStorageActionsInject");
    expect(injectSource).toContain("function handleSourceCollectionProjectResetSuccess");
    expect(injectSource).toContain("function runSourceCollectionProjectReset");
    expect(routeSource).toContain("useTeamsScComposition");
    // Reset chrome left the route body and left-rail search brief.
    expect(routeSource).not.toContain("重新开始本项目的资料搜集");
    expect(routeSource).not.toContain("Clear this project's sources and restart");
    expect(routeSource).not.toContain("连同实验与迭代一起清空");
    expect(shellSource).not.toContain("重新开始本项目的资料搜集");
    expect(shellSource).not.toContain("连同实验与迭代一起清空");
  });

  it("search-brief shell only hosts brief inject; project reset lives under stage card", () => {
    expect(shellSource).toContain("TeamSourceCollectionSearchBriefInject");
    expect(shellSource).not.toContain("onReset");
    expect(shellSource).not.toContain("VStateSurface");
    expect(shellSource).not.toContain("onStart");
    expect(shellSource).not.toContain("canStart");
    expect(workspaceSource).toContain("projectReset");
    expect(workspaceSource).toContain("清空本项目资料并重新开始");
    expect(workspaceSource).toContain("连同实验与迭代一起清空");
    expect(workspaceSource).toContain("ResearchWorkflowErrorSurface");
    expect(injectSource).toContain("projectReset={{");
  });

  it("storage inject builds detail targets and primary run directory action", () => {
    expect(storageSource).toContain("run_directory");
    expect(storageSource).toContain("candidate_store");
    expect(storageSource).toContain("TeamSourceCollectionStorageActionsPanel");
    expect(storageSource).toContain("sourceCollectionStorageTargetLabel");
  });
});
