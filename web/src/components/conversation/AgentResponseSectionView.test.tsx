import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentResponseSectionView } from "./AgentResponseSectionView";

describe("AgentResponseSectionView", () => {
  it("renders the response section shell with stable AgentMessage metadata", () => {
    const html = renderToStaticMarkup(
      <AgentResponseSectionView
        answerKey="assistant-1-answer"
        answerContentSectionIds="assistant-1-section-content-0"
        expanded={true}
        label="回答"
        expandedTitle="收起回答"
        collapsedTitle="展开回答"
        showSpinner={true}
        onToggle={() => undefined}
      >
        <p>最终回答内容</p>
      </AgentResponseSectionView>,
    );

    expect(html).toContain('data-conversation-part-key="assistant-1-answer"');
    expect(html).toContain('data-agent-content-section-ids="assistant-1-section-content-0"');
    expect(html).toContain('data-agent-content-channel="answer"');
    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain('title="收起回答"');
    expect(html).toContain("回答");
    expect(html).toContain("最终回答内容");
    expect(html).toContain("responseBody");
    expect(html).toContain("statusSpinner");
  });

  it("omits response body and answer channel metadata when collapsed or section ids are absent", () => {
    const html = renderToStaticMarkup(
      <AgentResponseSectionView
        answerKey="assistant-2-answer"
        answerContentSectionIds=""
        expanded={false}
        label="Response"
        expandedTitle="Hide response"
        collapsedTitle="Show response"
        showSpinner={false}
        onToggle={() => undefined}
      >
        <p>Hidden response body</p>
      </AgentResponseSectionView>,
    );

    expect(html).toContain('data-conversation-part-key="assistant-2-answer"');
    expect(html).not.toContain("data-agent-content-channel");
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('title="Show response"');
    expect(html).not.toContain("Hidden response body");
  });
});
