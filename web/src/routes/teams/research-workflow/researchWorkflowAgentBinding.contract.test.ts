import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const serviceSource = readFileSync(
  resolve(import.meta.dirname, "../../../../../core/web/services/team_workflow/research_runtime/service.py"),
  "utf8",
);
const bindingsSource = readFileSync(
  resolve(import.meta.dirname, "../../../../../core/research/workflow/bindings.py"),
  "utf8",
);
const workspaceSource = readFileSync(
  resolve(import.meta.dirname, "ResearchProcessWorkspace.tsx"),
  "utf8",
);
const inspectorSource = readFileSync(
  resolve(import.meta.dirname, "ResearchProcessNodeInspector.tsx"),
  "utf8",
);
const inspectorPaneSource = readFileSync(
  resolve(import.meta.dirname, "ResearchProcessInspectorPane.tsx"),
  "utf8",
);
const commandSectionSource = readFileSync(
  resolve(import.meta.dirname, "NodeCommandSection.tsx"),
  "utf8",
);
const renderersSource = readFileSync(
  resolve(import.meta.dirname, "../teamResearchPrimarySurfaceRenderers.tsx"),
  "utf8",
);
const chatAnchorSource = readFileSync(
  resolve(import.meta.dirname, "chatSessionAnchor.ts"),
  "utf8",
);

describe("researchWorkflowAgentBinding.contract", () => {
  it("resolution order is workflow → stage → node → snapshot", () => {
    expect(bindingsSource).toContain("node_override");
    expect(bindingsSource).toContain("stage_override");
    expect(bindingsSource).toContain("workflow_default");
    expect(bindingsSource).toContain("build_run_binding_snapshots");
  });

  it("runtime persists binding snapshots and rebind_node", () => {
    expect(serviceSource).toContain("bindingSnapshots");
    expect(serviceSource).toContain("rebind_node");
    expect(serviceSource).toContain("put_session_binding");
    expect(serviceSource).toContain("sessionAnchorDegraded");
  });

  it("chat deep links require task and turn anchors", () => {
    expect(chatAnchorSource).toContain("focusTask");
    expect(chatAnchorSource).toContain("focusTurn");
    expect(chatAnchorSource).toContain("missing_focus_task");
    expect(chatAnchorSource).toContain("degraded");
  });

  it("workspace agents panel reads effective bindings + run snapshot", () => {
    expect(inspectorPaneSource).toContain("ResearchAgentBindingPanel");
    expect(workspaceSource).toContain("effectiveBindings");
    expect(workspaceSource).toContain("useResearchWorkflowRun");
  });

  it("removes legacy stage writers from the canonical workflow workspace", () => {
    expect(workspaceSource).not.toContain('panel === "experiment"');
    expect(workspaceSource).not.toContain("experimentPanel");
    expect(workspaceSource).not.toContain('panel === "knowledge"');
    expect(workspaceSource).not.toContain("knowledgePanel");
    expect(renderersSource).not.toContain("TeamSourceCollectionSearchBriefPanel");
    expect(renderersSource).not.toContain("experimentPanel=");
  });

  it("node inspector exposes only backend-declared node commands", () => {
    expect(inspectorSource).toContain("detail.commands");
    expect(commandSectionSource).toContain("capabilities");
    expect(inspectorSource).not.toContain("onOpenPanel");
    expect(inspectorSource).not.toContain("drawerPanel");
  });
});
