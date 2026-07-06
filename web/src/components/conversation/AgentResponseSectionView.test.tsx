import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentResponseSectionView } from "./AgentResponseSectionView";
import styles from "./AgentResponseSectionView.styles";

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
    expect(html).toContain('aria-controls="agent-response-assistant-1-answer"');
    expect(html).toContain('aria-label="收起回答"');
    expect(html).toContain('id="agent-response-assistant-1-answer"');
    expect(html).toContain('title="收起回答"');
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain("回答");
    expect(html).toContain("最终回答内容");
    expect(html).toContain("responseBody");
    expect(html).toContain("responseToggleStatus");
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
    expect(html).toContain('aria-controls="agent-response-assistant-2-answer"');
    expect(html).toContain('aria-label="Show response"');
    expect(html).not.toContain('id="agent-response-assistant-2-answer"');
    expect(html).toContain('title="Show response"');
    expect(html).toContain("responseToggleStatus");
    expect(html).not.toContain("statusSpinner");
    expect(html).not.toContain("Hidden response body");
  });

  it("can keep live answer content visible even when the disclosure state is collapsed", () => {
    const html = renderToStaticMarkup(
      <AgentResponseSectionView
        answerKey="assistant-live-answer"
        answerContentSectionIds="assistant-live-section-content-0"
        expanded={false}
        label="回答"
        expandedTitle="收起回答"
        collapsedTitle="展开回答"
        showSpinner={true}
        forceBodyVisible={true}
        onToggle={() => undefined}
      >
        <p>正在实时输出的回答</p>
      </AgentResponseSectionView>,
    );

    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain('aria-label="收起回答"');
    expect(html).toContain('title="收起回答"');
    expect(html).toContain("正在实时输出的回答");
    expect(html).toContain("responseBody");
    expect(html).toContain('id="agent-response-assistant-live-answer"');
    expect(html).toContain("statusSpinner");
  });

  it("keeps the response control styled as a bounded slot button", () => {
    expect(styles.responseToggle).toContain("grid-cols-[auto_minmax(0,auto)_1rem]");
    expect(styles.responseToggle).toContain("max-w-full");
    expect(styles.responseToggle).toContain("overflow-hidden");
    expect(styles.responseToggle).toContain("focus-visible:!ring-2");
    expect(styles.responseToggleStatus).toContain("size-4");
    expect(styles.responseToggleStatus).toContain("place-items-center");
    expect(styles.responseToggle).toContain("[&_[data-slot=vui-button-content]]:contents");
    expect(styles.responseToggle).toContain("[&_[data-slot=vui-button-label]]:contents");
    expect(styles.statusSpinner).toContain("size-3.5");
    expect(styles.responseBody).toContain("[overflow-wrap:anywhere]");
  });
});
