import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { createResearchWorkflowSurfaceRenderers } from "./teamResearchWorkflowSurfaceRenderers";

describe("organization inspector composition", () => {
  function inspector(researchWorkflowTeamSelected: boolean) {
    return renderToStaticMarkup(createResearchWorkflowSurfaceRenderers({
      lang: "zh",
      selectedTeam: { teamId: "team-a" },
      selectedNodeId: "node-a",
      researchWorkflowTeamSelected,
      researchCanvasReadOnly: true,
      showAiSearchScopePanel: true,
      showWorkflowPanel: false,
      showTeamCommunicationPanel: false,
      renderResearchCanvasReadOnlyPanel: () => <p>节点身份</p>,
      renderTeamNodeBindingPanel: () => <p>成员绑定</p>,
      renderAiSearchSourceScopePanel: () => <p>现有范围</p>,
    }).renderTeamsInspectorSharedPanels());
  }

  it("groups organization members into tabs without changing their existing renderers", () => {
    const html = inspector(false);
    expect(html).toContain("data-team-inspector-tabs");
    expect(html).toContain("节点身份");
    expect(html).toContain("成员绑定");
    expect(html).toContain("现有范围");
    expect(html).toContain('data-team-inspector-section="members"');
    expect(html).not.toContain('data-team-inspector-section="tasks"');
    expect(html).toContain('data-team-inspector-section="records"');
  });

  it("preserves the scientific workflow inspector path", () => {
    const html = inspector(true);
    expect(html).not.toContain("data-team-inspector-tabs");
    expect(html).toContain("节点身份");
    expect(html).toContain("成员绑定");
    expect(html).toContain("现有范围");
  });
});
