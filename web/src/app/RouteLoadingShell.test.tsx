/** @vitest-environment happy-dom */
import React from "react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { teamFlowKeys } from "../api/genericTeamWorkflows";
import { createWorkflow } from "../routes/teams/generic/workflowTemplates";
import { RouteLoadingShell } from "./RouteLoadingShell";
import { WorkflowWorkspaceLoading } from "../routes/teams/generic/WorkflowWorkspaceLoading";
function renderLoading(element: React.ReactNode, flows?: ReturnType<typeof createWorkflow>[]) {
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}});
  if (flows) client.setQueryData(teamFlowKeys.flows("team-5"), {schemaVersion:1,teamId:"team-5",flows});
  const markup = renderToStaticMarkup(<QueryClientProvider client={client}>{element}</QueryClientProvider>);
  client.clear(); return markup;
}
const shellCss = readFileSync(join(import.meta.dirname, "../design/tailwind.css"), "utf8");

Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 });
afterEach(() => { window.history.replaceState(null, "", "/"); localStorage.clear(); });

it("loads the real full-height flow framework before the Teams route chunk", () => {
  window.history.replaceState(null, "", "/teams?team=team-5&teamWorkspace=flows");
  const host = document.createElement("div");
  host.innerHTML = renderLoading(<RouteLoadingShell layout="teams"/>);
  expect(host.querySelector('[data-vui-domain-recipe="generic-team-workspace"]')).not.toBeNull();
  expect(host.querySelector('[data-vui-layout-id="teams"]')).not.toBeNull();
  expect(host.querySelector('[data-team-workspace-toolbar]')).not.toBeNull();
  expect(host.querySelector('[data-vui="canvas-workbench-rail"]')).not.toBeNull();
  expect(host.querySelector('[data-team-flow-editor]')).not.toBeNull();
  expect(host.querySelector('[data-route-loading]')?.classList.contains("h-full")).toBe(true);
  expect(host.querySelector('[data-loading-region="team-canvas"]')).toBeNull();
  expect(host.querySelector('[data-route-loading]')?.textContent).not.toContain("还没有流程");
  expect(host.querySelector("[inert]")).not.toBeNull();
});

it("uses the same framework for the team-data loading phase", () => {
  const markup = renderLoading(<WorkflowWorkspaceLoading teamId="team-5" teams={[{id:"team-5",label:"开发团队"}]}/>, []);
  expect(markup).toContain('data-vui-domain-recipe="generic-team-workspace"');
  expect(markup).toContain("开发团队");
  expect(markup).toContain("正在读取团队工作台");
  expect(markup).toContain('data-team-loading-content="true"');
  expect(markup).not.toContain("place-content-center");
});

it("keeps ordinary team navigation on its existing loading contract", () => {
  window.history.replaceState(null, "", "/teams?team=team-5&teamView=discussion");
  expect(renderLoading(<RouteLoadingShell layout="teams"/>)).toContain('data-loading-region="team-canvas"');
});

it("ships real framework and content utilities before lazy Teams CSS arrives", () => {
  for (const source of ["WorkbenchShell", "WorkflowStart", "FlowEditor"]) {
    expect(shellCss).toContain(`@source "../routes/teams/generic/${source}.tsx"`);
    expect(shellCss).toContain(`@source "../routes/teams/generic/${source}.styles.ts"`);
  }
});

it("keeps the editor footprint in the initial route-chunk loading phase", () => {
  window.history.replaceState(null, "", "/teams?team=team-a&teamWorkspace=flows");
  const markup = renderLoading(<RouteLoadingShell layout="teams"/>);
  expect(markup).toContain("data-team-flow-editor");
  expect(markup).toContain('data-vui="canvas-workbench-inspector"');
  expect(markup).not.toContain("data-team-workspace-start");
});
