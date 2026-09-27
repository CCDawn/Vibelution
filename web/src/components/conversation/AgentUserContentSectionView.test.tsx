import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { dictionaryChat } from "../../i18n/domains/dictionaryChat";
import { AgentUserContentSectionView } from "./AgentUserContentSectionView";
import styles from "./AgentUserContentSectionView.styles";

function renderShell(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

describe("AgentUserContentSectionView", () => {
  it("renders the user content shell with stable AgentMessage content metadata", () => {
    const html = renderShell(
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
    const html = renderShell(
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
    expect(styles.userMessageBody).toContain("max-w-full");
    expect(styles.userMessageBody).toContain("rounded-2xl");
    expect(styles.userMessageBody).toContain("border-0");
    expect(styles.userMessageBody).toContain("bg-[var(--vui-control-muted)]");
    expect(styles.userMessageBody).toContain("px-3");
    expect(styles.userMessageBody).toContain("py-2");
    expect(styles.userMessageBody).toContain("shadow-none");
    expect(styles.userMessageBody).toContain("[&_.markdownBody]:max-w-full");
    expect(styles.userMessageBody).toContain("[&_.markdownBody]:whitespace-normal");
    expect(styles.userMessageBody).toContain("[&_.markdownBody]:break-words");
    expect(styles.userMessageBody).toContain("[&_.markdownBody]:[overflow-wrap:anywhere]");
    expect(styles.userMessageBody).toContain("[&_.inlineLink]:break-words");
    expect(styles.userMessageBody).toContain("[&_.inlineLink]:[overflow-wrap:anywhere]");
  });

  it("clamps collapsed content at the 120px fold with a token-matched bottom fade", () => {
    expect(styles.userMessageBodyClamped).toContain("max-h-[120px]");
    expect(styles.userMessageBodyClamped).toContain("overflow-hidden");
    expect(styles.userMessageBodyClamped).toContain("relative");
    expect(styles.userMessageBodyWrap).toContain("relative");
    expect(styles.userMessageBodyWrap).not.toContain("overflow-hidden");
    expect(styles.userMessageCollapseFade).toContain("bg-gradient-to-t");
    expect(styles.userMessageCollapseFade).toContain("from-[var(--vui-control-muted)]");
    expect(styles.userMessageCollapseFade).toContain("to-transparent");
    expect(styles.userMessageCollapseFade).toContain("pointer-events-none");
  });

  it("hosts the expand toggle on a small ghost text VNativeButton", () => {
    expect(styles.userMessageCollapseToggle).toContain("border-0");
    expect(styles.userMessageCollapseToggle).toContain("bg-transparent");
    expect(styles.userMessageCollapseToggle).toContain("p-0");
    expect(styles.userMessageCollapseToggle).toContain("[font-size:var(--vui-type-caption-size)]");
    expect(styles.userMessageCollapseToggle).toContain("text-[var(--fg-tertiary)]");
  });

  it("keeps the collapse affordance out of static markup until the client measures", () => {
    const html = renderShell(
      <AgentUserContentSectionView>
        <p>short content</p>
      </AgentUserContentSectionView>,
    );

    expect(html).toContain("user-message-measured-content");
    expect(html).not.toContain("user-message-collapse-toggle");
    expect(html).not.toContain("userMessageBodyClamped");
  });

  it("localizes the collapse toggle copy in both dictionaries", () => {
    expect(dictionaryChat.zh.expandUserMessage).toBe("展开");
    expect(dictionaryChat.zh.collapseUserMessage).toBe("收起");
    expect(dictionaryChat.en.expandUserMessage).toBe("Expand");
    expect(dictionaryChat.en.collapseUserMessage).toBe("Collapse");
  });
});
