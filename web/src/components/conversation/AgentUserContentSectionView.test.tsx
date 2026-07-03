import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentUserContentSectionView } from "./AgentUserContentSectionView";

describe("AgentUserContentSectionView", () => {
  it("renders the user content shell with stable AgentMessage content metadata", () => {
    const html = renderToStaticMarkup(
      <AgentUserContentSectionView userContentSectionIds="message-1-section-content-0">
        <p>用户输入内容</p>
      </AgentUserContentSectionView>,
    );

    expect(html).toContain("userMessageBody");
    expect(html).toContain('data-agent-content-section-ids="message-1-section-content-0"');
    expect(html).toContain('data-agent-content-channel="user"');
    expect(html).toContain("用户输入内容");
  });

  it("omits the content channel metadata when no section ids are available", () => {
    const html = renderToStaticMarkup(
      <AgentUserContentSectionView userContentSectionIds="">
        <p>legacy user content</p>
      </AgentUserContentSectionView>,
    );

    expect(html).toContain("userMessageBody");
    expect(html).not.toContain("data-agent-content-channel");
    expect(html).toContain("legacy user content");
  });
});
