/** @vitest-environment happy-dom */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it } from "vitest";
import { WorkflowWorkspaceLoading } from "./WorkflowWorkspaceLoading";
import { rememberWorkflowLoadingShape } from "./workflowLoadingShape";
import { createWorkflow } from "./workflowTemplates";
Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 });
afterEach(() => localStorage.clear());

it("reserves actual editor nodes, input controls and shared inspector panes before data arrives", () => {
  const flow = createWorkflow("验收流程", "blank", []);
  flow.fields = [{id:"a",label:"任务说明",kind:"paragraph",required:true,options:[]}, {id:"b",label:"范围",kind:"select",required:false,options:["公开"]}];
  rememberWorkflowLoadingShape("team-a", [flow]);
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(<WorkflowWorkspaceLoading teamId="team-a"/>);
  expect(host.querySelectorAll("[data-team-flow-editor] li > button")).toHaveLength(flow.steps.length);
  expect(host.querySelector("[data-team-workspace-start]")).toBeNull();
  expect(host.querySelector('[data-vui="canvas-workbench-inspector"]')).not.toBeNull();
  expect(host.querySelector("[data-team-inspector-header]")?.className).toContain("h-[52px]");
  expect(host.querySelector('[aria-label="输入2选项"]')).not.toBeNull();
  expect(host.querySelector('[data-team-inspector-footer]')).not.toBeNull();
  expect(host.querySelector("main[inert]")).not.toBeNull();
  expect(host.querySelector('[data-team-flow-editor]')?.getAttribute("aria-hidden")).toBe("true");
  expect(host.querySelector('[data-vui-layout-id="teams"]')).not.toBeNull();
  expect(host.querySelector('[data-team-workspace-toolbar]')?.textContent).not.toContain("已保存");
});

it("does not show another team's cached editor", () => {
  rememberWorkflowLoadingShape("team-a", [createWorkflow("A", "blank", [])]);
  const markup = renderToStaticMarkup(<WorkflowWorkspaceLoading teamId="team-b"/>);
  expect(markup).toContain("data-team-flow-editor");
  expect(markup).not.toContain("A saved");
});

it("reserves an editor frame even with no prior history, then honors confirmed empty", () => {
  let markup = renderToStaticMarkup(<WorkflowWorkspaceLoading teamId="unseen"/>);
  expect(markup).toContain('data-vui="canvas-workbench-inspector"');
  expect(markup).toContain("data-team-flow-editor");
  rememberWorkflowLoadingShape("unseen", []);
  markup = renderToStaticMarkup(<WorkflowWorkspaceLoading teamId="unseen"/>);
  expect(markup).toContain("data-team-workspace-start");
  expect(markup).not.toContain("data-team-flow-editor");
});
