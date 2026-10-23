/** @vitest-environment happy-dom */
import React from "react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it } from "vitest";
import { RouteLoadingShell } from "./RouteLoadingShell";
import { WorkflowWorkspaceLoading } from "../routes/teams/generic/WorkflowWorkspaceLoading";
const shellCss = readFileSync(join(import.meta.dirname, "../design/tailwind.css"), "utf8");

afterEach(() => window.history.replaceState(null, "", "/"));

it("loads the real full-height flow framework before the Teams route chunk", () => {
  window.history.replaceState(null, "", "/teams?team=team-5&teamWorkspace=flows");
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(<RouteLoadingShell layout="teams"/>);
  expect(host.querySelector('[data-vui-domain-recipe="generic-team-workspace"]')).not.toBeNull();
  expect(host.querySelector('[data-vui-layout-id="teams"]')).not.toBeNull();
  expect(host.querySelector('[data-team-workspace-toolbar]')).not.toBeNull();
  expect(host.querySelector('[data-vui="canvas-workbench-rail"]')).not.toBeNull();
  expect(host.querySelector('[data-team-workspace-start]')).not.toBeNull();
  expect(host.querySelector('[data-route-loading]')?.classList.contains("h-full")).toBe(true);
  expect(host.querySelector('[data-loading-region="team-canvas"]')).toBeNull();
  expect(host.querySelector('[data-route-loading]')?.textContent).not.toContain("还没有流程");
  expect(host.querySelector("[inert]")).not.toBeNull();
});

it("uses the same framework for the team-data loading phase", () => {
  const markup = renderToStaticMarkup(<WorkflowWorkspaceLoading teamId="team-5" teams={[{id:"team-5",label:"开发团队"}]}/>);
  expect(markup).toContain('data-vui-domain-recipe="generic-team-workspace"');
  expect(markup).toContain("开发团队");
  expect(markup).toContain("正在读取团队工作台");
  expect(markup).toContain('data-team-loading-content="true"');
  expect(markup).not.toContain("place-content-center");
});

it("keeps ordinary team navigation on its existing loading contract", () => {
  window.history.replaceState(null, "", "/teams?team=team-5&teamView=discussion");
  expect(renderToStaticMarkup(<RouteLoadingShell layout="teams"/>)).toContain('data-loading-region="team-canvas"');
});

it("ships real framework and content utilities before lazy Teams CSS arrives", () => {
  for (const source of ["WorkbenchShell", "WorkflowStart", "FlowEditor"]) {
    expect(shellCss).toContain(`@source "../routes/teams/generic/${source}.tsx"`);
    expect(shellCss).toContain(`@source "../routes/teams/generic/${source}.styles.ts"`);
  }
});
