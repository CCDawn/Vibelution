import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentInspectorRailPanel } from "./AgentInspectorRailPanel";

describe("AgentInspectorRailPanel", () => {
  it("does not repeat the inspector title when no distinct subtitle exists", () => {
    const markup = renderToStaticMarkup(
      <AgentInspectorRailPanel
        ariaLabel="Agent 检查器"
        title="Agent"
        emptyTitle="选择一个 Agent"
        brief={null}
        resources={null}
      />,
    );

    expect(markup.match(/>Agent</g)).toHaveLength(1);
    expect(markup).not.toContain("<p");
  });

  it("keeps a meaningful category eyebrow only when a distinct Agent name is present", () => {
    const markup = renderToStaticMarkup(
      <AgentInspectorRailPanel
        ariaLabel="Agent 检查器"
        title="Agent"
        subtitle="研究 Agent"
        emptyTitle="选择一个 Agent"
        brief={null}
        resources={null}
      />,
    );

    expect(markup).toContain(">Agent</p>");
    expect(markup).toContain(">研究 Agent</div>");
  });
});
