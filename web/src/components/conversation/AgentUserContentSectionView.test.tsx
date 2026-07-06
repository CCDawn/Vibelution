import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentUserContentSectionView } from "./AgentUserContentSectionView";
import styles from "./AgentUserContentSectionView.styles";

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

  it("keeps user message bubbles readable for long prose and nested markdown links", () => {
    expect(styles.userMessageBody).toContain("whitespace-pre-wrap");
    expect(styles.userMessageBody).toContain("[overflow-wrap:anywhere]");
    expect(styles.userMessageBody).toContain("max-w-[min(100%,68ch)]");
    expect(styles.userMessageBody).toContain("border border-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))]");
    expect(styles.userMessageBody).toContain("bg-[color-mix(in_srgb,var(--accent-cool)_6%,var(--vui-surface-panel))]");
    expect(styles.userMessageBody).toContain("px-2.5");
    expect(styles.userMessageBody).toContain("py-1.5");
    expect(styles.userMessageBody).toContain("shadow-none");
    expect(styles.userMessageBody).toContain("[&_.markdownBody]:max-w-[min(100%,68ch)]");
    expect(styles.userMessageBody).toContain("[&_.markdownBody]:whitespace-normal");
    expect(styles.userMessageBody).toContain("[&_.markdownBody]:break-words");
    expect(styles.userMessageBody).toContain("[&_.markdownBody]:[overflow-wrap:anywhere]");
    expect(styles.userMessageBody).toContain("[&_.inlineLink]:break-words");
    expect(styles.userMessageBody).toContain("[&_.inlineLink]:[overflow-wrap:anywhere]");
  });
});
