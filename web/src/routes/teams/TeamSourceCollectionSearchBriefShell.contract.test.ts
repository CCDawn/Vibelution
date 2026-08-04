import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const shellSource = readFileSync(new URL("./TeamSourceCollectionSearchBriefShell.tsx", import.meta.url), "utf8");
const storageSource = readFileSync(new URL("./TeamSourceCollectionStorageActionsInject.tsx", import.meta.url), "utf8");

describe("SC inject shell extraction contract", () => {
  it("TeamsRoute mounts search-brief shell and storage inject helpers", () => {
    expect(routeSource).toContain("TeamSourceCollectionSearchBriefShell");
    expect(routeSource).toContain("TeamSourceCollectionStorageActionsInject");
    expect(routeSource).toContain("function handleSourceCollectionProjectResetSuccess");
    expect(routeSource).toContain("function runSourceCollectionProjectReset");
    // Reset chrome left the route body.
    expect(routeSource).not.toContain("重新开始本项目的资料搜集");
    expect(routeSource).not.toContain("Clear this project's sources and restart");
    expect(routeSource).not.toContain("连同实验与迭代一起清空");
  });

  it("search-brief shell owns reset surface and brief inject", () => {
    expect(shellSource).toContain("重新开始本项目的资料搜集");
    expect(shellSource).toContain("TeamSourceCollectionSearchBriefInject");
    expect(shellSource).toContain("ResearchWorkflowErrorSurface");
    expect(shellSource).toContain("onReset");
  });

  it("storage inject builds detail targets and primary run directory action", () => {
    expect(storageSource).toContain("run_directory");
    expect(storageSource).toContain("candidate_store");
    expect(storageSource).toContain("TeamSourceCollectionStorageActionsPanel");
    expect(storageSource).toContain("sourceCollectionStorageTargetLabel");
  });
});
